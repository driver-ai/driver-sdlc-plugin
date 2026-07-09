"""Localhost HTTP shell for the capture viewer -- serve, browse, gated sync.

`/drvr:capture-viewer` launches this server to present the capture store
(`~/.driver/capture`) to the local trajectory-viewer UI: the live session
Dataset (`GET /dataset.json`), per-session step payloads
(`GET /runs/<id>.json`), counts-only PII-scan summaries
(`GET /api/sessions/<id>/scan`), and the gated multi-session upload
(`POST /api/sync`), plus static serving of the built viewer from `dist/` with
an SPA fallback. This module is the IMPERATIVE SHELL of the functional-core /
imperative-shell split: sockets, files, and the clock live here, while ALL
routing, path normalization, dataset/payload shaping, and the sync gate are
decided by the pure planners in `capture_viewer_core` -- the handler passes
the raw method/path straight to `capture_viewer_core.route` and never decodes
or re-implements a decision.

Security posture: the server binds 127.0.0.1 ONLY, holds no long-lived
credentials (identity args are injected at launch; the sync profile's
credentials stay in the SSO cache), and rejects any request whose Host header
hostname is not 127.0.0.1/localhost (DNS-rebind defense; hostname-only compare
so the vite dev proxy's forwarded Host with a different port is accepted).
Egress happens ONLY through `atif_to_s3`'s upload machinery behind
`capture_viewer_core.validate_sync_request` -- a refused request performs zero
egress calls, and this module itself shells out to nothing but `git`/`npm`.

Sync is single-flight: a module-level lock is acquired non-blocking (a
concurrent second sync gets 409 instead of a double upload / clobbered ledger
records) and RELEASED in try/finally on every exit path -- 503/500 included --
so a failed sync never wedges later ones. Reads stay lock-free: the ledger
write is atomic, so readers see old-or-new, never torn. Index/ledger/hashes
are recomputed fresh per request -- deliberate freshness (~60 ms measured on a
real store); do not add a cache.

Launch (`main`) brings the viewer checkout to a servable state via
`ensure_built`: `atif_to_viewer.ensure_viewer` owns clone/pin (skipped on the
offline warm path, when HEAD already equals the pin), `npm install` runs when
node_modules is missing or the lockfile is newer, and `npm run build` runs
only when needed. The `.built-sha` convention decides "needed":
`dist/.built-sha` records the checkout SHA the current `dist/` was built from,
written only AFTER a successful build -- a missing/mismatched value forces a
rebuild, a matching one skips it entirely.
"""
from __future__ import annotations

import argparse
import dataclasses
import errno
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from functools import partial

import atif_to_s3
import atif_to_viewer
import capture_store_core
import capture_viewer_core

# The only bind host, ever. Never 0.0.0.0 -- the store is personal data.
_BIND_HOST = "127.0.0.1"
_ALLOWED_HOSTNAMES = {"127.0.0.1", "localhost"}

# Sync request bodies are tiny ({confirm, session_ids}); anything above this
# is not a viewer request.
_MAX_BODY_BYTES = 1 << 20

# Single-flight sync (process-global): non-blocking acquire -> 409 on
# contention; released in try/finally on EVERY exit path (a leaked lock would
# 409 every later sync).
_SYNC_LOCK = threading.Lock()

# Single-flight annotation write (process-global): a DEDICATED lock, NEVER
# _SYNC_LOCK -- a slow in-flight S3 sync must not 409 a fast local annotation
# save (capture-viewer DEC-017). Non-blocking acquire -> 409 on contention;
# released in try/finally on every exit path.
_ANNOTATIONS_LOCK = threading.Lock()


@dataclasses.dataclass(frozen=True)
class ServerContext:
    """Frozen launch config threaded to handlers: base_dir, viewer_dir,
    dist_dir, identity {principal_id, principal_type, org_id}, bucket,
    profile, author (the DEFAULT annotation author -- used only when a posted
    label omits its own author; capture-viewer DEC-018)."""
    base_dir: str
    viewer_dir: str
    dist_dir: str
    identity: dict
    bucket: str
    profile: str
    author: str


def _utc_now_iso() -> str:
    """Shell: current UTC timestamp for generatedAt (the clock stays out of
    the pure core)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_annotations(path: str, session_id: str) -> dict:
    """Shell: sidecar text -> a doc via the pure parser. A MISSING file ->
    default doc; a present-but-corrupt file -> default (tolerant --
    capture-viewer DEC-019). An OSError on a PRESENT file is NOT swallowed: it
    propagates to the handler's blanket 500 (a readable path that suddenly fails
    to read is a real fault, never empty annotations)."""
    if not os.path.exists(path):
        return capture_viewer_core.parse_annotations(None, session_id=session_id)
    with open(path) as fh:                     # OSError on a present file -> 500
        text = fh.read()
    return capture_viewer_core.parse_annotations(text, session_id=session_id)


def write_annotations(path: str, doc: dict) -> None:
    """Shell: atomic sidecar write -- temp file in the same dir + os.replace, so
    a reader sees old-or-new but never a torn doc. Creates the session dir if
    absent (a session with a pruned trajectory may have no dir yet --
    capture-viewer DEC-024)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, path)


class ViewerRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Routes via capture_viewer_core.route(self.command, self.path):
    dataset -> 200 build_sessions_dataset(...);  run -> 200 build_run_payload(...)
    | 404;  scan -> 200 {"session_id", "by_type"} | 404;  sync -> do_POST;
    static -> SimpleHTTPRequestHandler (directory=dist) with index.html SPA
    fallback for extension-less non-/api/ paths."""

    def __init__(self, *args, ctx: ServerContext, **kwargs):
        self.ctx = ctx
        super().__init__(*args, directory=ctx.dist_dir, **kwargs)

    # -- plumbing -------------------------------------------------------------

    def log_message(self, fmt, *args):
        """Request-log-quiet by design (the launching command reads this
        process's output); errors surface via JSON responses instead."""

    def _send_json(self, status: int, payload: dict) -> None:
        """Every JSON response -- errors included -- carries Cache-Control:
        no-store so sync chips flip without a hard reload. HEAD replies
        headers-only."""
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _host_allowed(self) -> bool:
        """Hostname-ONLY compare (any port accepted): DNS rebinding is defeated
        by the hostname alone, and the vite dev proxy forwards its own port."""
        hostname = (self.headers.get("Host") or "").split(":", 1)[0]
        return hostname.strip().casefold() in _ALLOWED_HOSTNAMES

    def _fail_safe(self, exc: Exception) -> None:
        # A bad artifact or request must never kill the server thread.
        try:
            self._send_json(500, {"error": str(exc)})
        except Exception:
            pass                                   # client already gone

    # -- dispatch (route logic lives in the pure core) ------------------------

    def do_GET(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        # HEAD routes API paths exactly like GET and replies headers-only, so
        # a HEAD near-miss can never serve a stale static file.
        self._dispatch()

    def _dispatch(self) -> None:
        try:
            if not self._host_allowed():
                self._send_json(403, {"error": "forbidden Host header"})
                return
            kind, params = capture_viewer_core.route(self.command, self.path)
            if kind == "dataset":
                self._handle_dataset()
            elif kind == "run":
                self._handle_run(params["session_id"])
            elif kind == "scan":
                self._handle_scan(params["session_id"])
            elif kind == "annotations_get":
                self._handle_annotations_get(params["session_id"])
            elif kind == "api_404":
                self._send_json(404, {"error": "not found"})
            else:
                self._handle_static()
        except Exception as e:
            self._fail_safe(e)

    def do_POST(self) -> None:
        try:
            if not self._host_allowed():
                self._send_json(403, {"error": "forbidden Host header"})
                return
            kind, params = capture_viewer_core.route(self.command, self.path)
            if kind == "sync":
                self._handle_sync()
            elif kind == "annotations_post":
                self._handle_annotations_post(params["session_id"])
            else:
                self._send_json(404, {"error": "not found"})
        except Exception as e:
            self._fail_safe(e)

    # -- store access (fresh per request -- deliberate, see module docstring) --

    def _store(self):
        base = self.ctx.base_dir
        index = atif_to_s3.load_index(os.path.join(base, "index.json"))
        ledger = atif_to_s3.load_ledger(
            os.path.join(base, atif_to_s3.LEDGER_NAME))
        # all_groups=True: EVERY session appears in shas with sha-or-None --
        # the full map the dataset (and the 404 gates) need.
        shas, paths = atif_to_s3.hash_candidates(index, base, all_groups=True)
        return index, ledger, shas, paths

    def _send_artifact_404(self, sid: str, shas: dict) -> None:
        self._send_json(404, {"error": "artifact missing" if sid in shas
                              else "unknown session id"})

    # -- GET handlers ----------------------------------------------------------

    def _handle_dataset(self) -> None:
        index, ledger, shas, _paths = self._store()
        dataset = capture_viewer_core.build_sessions_dataset(
            index, ledger, shas, generated_at=_utc_now_iso())
        self._send_json(200, dataset)

    def _handle_run(self, sid: str) -> None:
        _index, _ledger, shas, paths = self._store()
        if shas.get(sid) is None:      # unknown id OR unreadable/absent artifact
            self._send_artifact_404(sid, shas)
            return
        try:
            with open(paths[sid]) as fh:   # only trajectory.redacted.json, ever
                traj = json.load(fh)
        except OSError:
            self._send_json(404, {"error": "artifact missing"})
            return
        # A ValueError (corrupt JSON) propagates to the blanket 500 -- a
        # corrupt artifact must never render as an empty run.
        self._send_json(200, capture_viewer_core.build_run_payload(traj))

    def _handle_scan(self, sid: str) -> None:
        _index, _ledger, shas, paths = self._store()
        if shas.get(sid) is None:          # same gate as /runs/
            self._send_artifact_404(sid, shas)
            return
        # Probe the artifact HERE rather than relying on scan_sessions'
        # error-swallowing (unreadable -> []): a corrupt-but-hashable artifact
        # must never 200 with empty counts. OSError -> 404; corrupt JSON ->
        # ValueError -> the blanket 500.
        try:
            with open(paths[sid]) as fh:
                json.load(fh)
        except OSError:
            self._send_json(404, {"error": "artifact missing"})
            return
        findings = atif_to_s3.scan_sessions(
            [{"session_id": sid, "store_path": paths[sid]}])
        agg = atif_to_s3.aggregate_scan(findings)
        # Counts only -- snippets/locations never leave the machine-local
        # report path (capture-s3-sync DEC-071 lineage).
        self._send_json(200, {"session_id": sid, "by_type": agg["by_type"]})

    # -- static / SPA ----------------------------------------------------------

    def _handle_static(self) -> None:
        # The base class gets the RAW path: its translate_path owns unquote +
        # dot-dot dropping, so pre-decoding here would double-decode. Only the
        # query/fragment are split off for the extension probe.
        plain = self.path.split("#", 1)[0].split("?", 1)[0]
        if "." not in plain.rsplit("/", 1)[-1]:
            # Extension-less -> the SPA's index.html (route() already
            # guarantees /api/ paths never reach the static branch). This also
            # covers "/" and directories, so listings are never served.
            self.path = "/index.html"
        if self.command == "HEAD":
            super().do_HEAD()
        else:
            super().do_GET()

    # -- POST /api/sync --------------------------------------------------------

    def _read_json_body(self):
        """(body, error): Content-Type media-type + Content-Length checks, then
        the JSON parse. Any error string means 400 -- BEFORE the gate/validator
        runs. Shared by POST /api/sync and the annotations POST."""
        ctype = (self.headers.get("Content-Type") or "")
        if ctype.split(";", 1)[0].strip().casefold() != "application/json":
            return None, "Content-Type must be application/json"
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            return None, "Content-Length required"
        try:
            length = int(raw_len)
        except ValueError:
            return None, "invalid Content-Length"
        if length < 0:
            return None, "invalid Content-Length"
        if length > _MAX_BODY_BYTES:
            return None, "request body too large"
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            return None, "request body must be valid JSON"
        return body, None

    def _handle_sync(self) -> None:
        body, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return

        # Hash ONCE, reuse everywhere (gate, selection, upload -- no re-hash).
        index, ledger, shas, paths = self._store()
        runs_by_id = {r["id"]: r for r in capture_viewer_core.build_sessions_dataset(
            index, ledger, shas, generated_at=_utc_now_iso())["runs"]}
        # THE gate -- one owner for the uploadable predicate (capture-viewer
        # DEC-008: synced/ungrouped/unreadable ids are refused). NOTHING runs
        # on error.
        ids, gate_err = capture_viewer_core.validate_sync_request(body, runs_by_id)
        if gate_err is not None:
            self._send_json(400, {"error": gate_err})
            return

        if not _SYNC_LOCK.acquire(blocking=False):
            self._send_json(409, {"error": "sync already in progress"})
            return
        try:
            try:
                atif_to_s3.preflight_sso(self.ctx.profile)
            except RuntimeError as e:
                self._send_json(503, {"error": str(e)})
                return
            selected = atif_to_s3.select_sessions(index, ledger, shas,
                                                  session_ids=set(ids))
            # Belt-and-braces membership filter: deliberately INERT under
            # all_groups hashing (every id is a shas key with sha-or-None), so
            # every requested id stays in the results.
            selected = [e for e in selected if e.get("session_id") in shas]
            _final_ledger, results = atif_to_s3.sync_sessions(
                selected, paths=paths, shas=shas, identity=self.ctx.identity,
                bucket=self.ctx.bucket, profile=self.ctx.profile,
                ledger=ledger,
                ledger_path=os.path.join(self.ctx.base_dir,
                                         atif_to_s3.LEDGER_NAME))
            self._send_json(200, {"results": results})
        finally:
            _SYNC_LOCK.release()   # every exit path: 503/500/200 alike

    # -- annotations (GET/POST /api/sessions/<id>/annotations) ----------------
    # The existence gate is `sid not in shas` (UNKNOWN session -> 404), NOT the
    # `shas.get(sid) is None` artifact-readability check used by /runs and /scan:
    # annotations are a sidecar INDEPENDENT of the trajectory, so a known session
    # whose trajectory is missing/pruned (syncStatus:"missing") stays annotatable
    # -- annotations never 404 on a missing artifact, only on an unknown id
    # (capture-viewer DEC-024).

    def _handle_annotations_get(self, sid: str) -> None:
        _index, _ledger, shas, _paths = self._store()
        if sid not in shas:                          # UNKNOWN session only
            self._send_json(404, {"error": "unknown session"})
            return
        path = capture_store_core.annotations_path_for(self.ctx.base_dir, sid)
        # A corrupt/missing sidecar degrades to a default doc; an OSError on a
        # PRESENT file propagates to the blanket 500 (capture-viewer DEC-019).
        self._send_json(200, read_annotations(path, sid))

    def _handle_annotations_post(self, sid: str) -> None:
        # Order: body -> shape (incl. anchor {trajId, stepId} + required
        # decision) -> existence gate -> lock -> atomic write (capture-viewer
        # DEC-024/DEC-025/DEC-026). Everything up to the lock is a pure decision;
        # nothing is written on any 400/404.
        body, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return
        ok, verr = capture_viewer_core.validate_annotations(body)
        if not ok:
            self._send_json(400, {"error": verr})
            return
        _index, _ledger, shas, _paths = self._store()
        if sid not in shas:                          # UNKNOWN session only
            self._send_json(404, {"error": "unknown session"})
            return
        # Dedicated single-flight lock -- acquired OUTSIDE the try, released in
        # finally on every exit path (capture-viewer DEC-017).
        if not _ANNOTATIONS_LOCK.acquire(blocking=False):
            self._send_json(409,
                            {"error": "annotation write already in progress"})
            return
        try:
            doc = capture_viewer_core.build_annotations_doc(
                body, session_id=sid, author=self.ctx.author,
                now=_utc_now_iso())
            write_annotations(
                capture_store_core.annotations_path_for(self.ctx.base_dir, sid),
                doc)
            self._send_json(200, doc)
        finally:
            _ANNOTATIONS_LOCK.release()


def make_server(port: int, ctx: ServerContext) -> http.server.ThreadingHTTPServer:
    """Binds ('127.0.0.1', port) ONLY -- never 0.0.0.0. port=0 -> ephemeral
    (tests)."""
    server = http.server.ThreadingHTTPServer(
        (_BIND_HOST, port), partial(ViewerRequestHandler, ctx=ctx))
    server.daemon_threads = True
    return server


# ---------------------------------------------------------------------------
# Launch orchestration -- the only subprocess surface in this module, and it
# shells out to nothing but git/npm.
# ---------------------------------------------------------------------------

_BUILT_SHA_NAME = ".built-sha"


def _probe(argv: list) -> str | None:
    """Shell: run a read-only git probe with check=False; stripped stdout on
    success, None on ANY failure. A probe's own failure (missing dir, not a
    repo, git absent) is a COLD-START signal, never an error."""
    try:
        proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def _resolve_author(explicit: str | None) -> str:
    """Shell: the DEFAULT annotation author, resolved once at launch --
    --author override, else `git config user.name`, else $USER, else 'you'
    (capture-viewer DEC-018). Used only when a posted label omits its own author;
    the per-label client author is always preserved (capture-viewer DEC-026)."""
    if explicit and explicit.strip():
        return explicit.strip()
    return (_probe(["git", "config", "user.name"])
            or os.environ.get("USER") or "you")


def _run_step(argv: list, *, cwd: str | None, what: str, hint: str) -> None:
    """Shell: run one REAL work step (set-url/install/build); map failures to
    actionable RuntimeErrors -- no tracebacks for a missing tool or a failed
    build."""
    try:
        subprocess.run(argv, check=True, cwd=cwd)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"{argv[0]} not found on PATH — install it, then rerun") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"{what} failed (exit {e.returncode}) — {hint}") from e


def ensure_built(viewer_dir: str, *, repo: str, pin: str, do_install: bool,
                 do_build: bool) -> str:
    """Shell: bring <viewer_dir>/dist to a servable state; returns the dist path.

    do_build=False is pure serve mode: ZERO subprocesses, the caller serves
    whatever dist/ holds. Otherwise: warm/origin probes run check=False -- ANY
    probe failure (no dir, not a repo) means cold start, straight to
    `ensure_viewer`'s clone path (called with do_install=False; install is
    owned here by the lockfile rule). Warm (HEAD == pin) skips the fetch
    entirely -- the offline warm path. A stale checkout first reconciles
    origin to `repo` (git remote set-url) when they differ, so a pin bump onto
    a new fork fetches from the right place. npm install runs when
    node_modules is missing or package-lock.json is newer than it. npm run
    build runs only when dist/ is missing or dist/.built-sha is absent or
    differs from the checkout SHA; `.built-sha` is written only AFTER a
    successful build, and the build's sample public/ data (dist/dataset.json,
    dist/runs/) is removed so it can never shadow the live routes.
    """
    dist = os.path.join(viewer_dir, "dist")
    if not do_build:
        return dist

    head = _probe(["git", "-C", viewer_dir, "rev-parse", "HEAD"])
    if head != pin:                    # cold start (head None) or stale pin
        origin = _probe(["git", "-C", viewer_dir, "remote", "get-url", "origin"])
        if origin is not None and origin != repo:
            _run_step(["git", "-C", viewer_dir, "remote", "set-url", "origin",
                       repo],
                      cwd=None, what="git remote set-url",
                      hint=f"check that {viewer_dir} is a usable checkout")
        try:
            atif_to_viewer.ensure_viewer(viewer_dir, repo, pin,
                                         do_install=False)
        except FileNotFoundError as e:
            raise RuntimeError(
                "git not found on PATH — install it, then rerun") from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"viewer checkout failed (exit {e.returncode}) — if "
                f"{viewer_dir} has local changes, stash or remove the "
                f"checkout and rerun") from e
        head = _probe(["git", "-C", viewer_dir, "rev-parse", "HEAD"])

    if do_install:
        node_modules = os.path.join(viewer_dir, "node_modules")
        lockfile = os.path.join(viewer_dir, "package-lock.json")
        need_install = not os.path.isdir(node_modules)
        if not need_install and os.path.exists(lockfile):
            # A pin bump can bring new deps: a lockfile newer than
            # node_modules means the install is stale.
            need_install = (os.path.getmtime(lockfile)
                            > os.path.getmtime(node_modules))
        if need_install:
            _run_step(["npm", "install"], cwd=viewer_dir, what="npm install",
                      hint="check the npm output above, then rerun")

    built = None
    if os.path.isdir(dist):
        try:
            with open(os.path.join(dist, _BUILT_SHA_NAME)) as fh:
                built = fh.read().strip()
        except OSError:
            built = None
    if built is None or head is None or built != head:
        _run_step(["npm", "run", "build"], cwd=viewer_dir,
                  what="npm run build",
                  hint="check the build output above, then rerun")
        if head:
            with open(os.path.join(dist, _BUILT_SHA_NAME), "w") as fh:
                fh.write(head + "\n")
        # The build copies the fork's sample public/ data into dist -- remove
        # it so a near-miss route can never serve stale sample data.
        stale_dataset = os.path.join(dist, "dataset.json")
        if os.path.exists(stale_dataset):
            os.remove(stale_dataset)
        shutil.rmtree(os.path.join(dist, "runs"), ignore_errors=True)
    return dist


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="capture_viewer_server.py",
        description="Serve the capture store to the local trajectory viewer "
                    "(localhost only).")
    ap.add_argument("--port", type=int, default=atif_to_viewer.DEFAULT_PORT)
    ap.add_argument("--base-dir", default="~/.driver/capture",
                    help="capture base dir (index.json, sync ledger, sessions/)")
    ap.add_argument("--viewer-dir", default="~/.driver/viewer",
                    help="viewer checkout dir (cloned on demand)")
    # Single edit site for a pin bump: the defaults are IMPORTED, never copied.
    ap.add_argument("--repo", default=atif_to_viewer.DEFAULT_REPO)
    ap.add_argument("--pin", default=atif_to_viewer.DEFAULT_PIN)
    ap.add_argument("--bucket", default=atif_to_s3.DEFAULT_BUCKET)
    ap.add_argument("--profile", default=atif_to_s3.DEFAULT_PROFILE,
                    help="SSO profile the sync endpoint preflights and uploads with")
    # Identity is injected by the launching command -- never discovered here.
    ap.add_argument("--principal-id", required=True)
    ap.add_argument("--principal-type", required=True,
                    choices=["user", "machine"])
    ap.add_argument("--org-id", required=True)
    # Optional default annotation author -- else git config user.name / $USER /
    # "you" (capture-viewer DEC-018); per-label client author is preserved.
    ap.add_argument("--author",
                    help="default annotation author (falls back to git config "
                         "user.name, then $USER, then 'you')")
    ap.add_argument("--no-build", dest="build", action="store_false",
                    default=True,
                    help="pure serve mode: skip checkout/install/build entirely")
    ap.add_argument("--no-install", dest="install", action="store_false",
                    default=True, help="never run npm install")
    return ap


def main(argv=None) -> int:
    """Exit codes: 0 clean shutdown, 1 port-in-use / launch RuntimeError,
    2 identity validation (argparse uses 2 for its own errors too)."""
    args = _build_parser().parse_args(argv)

    if not args.principal_id.strip() or not args.org_id.strip():
        print("error: --principal-id and --org-id must be non-empty "
              "(identity is injected by the launching command)",
              file=sys.stderr)
        return 2

    base_dir = os.path.expanduser(args.base_dir)
    viewer_dir = os.path.expanduser(args.viewer_dir)
    try:
        dist_dir = ensure_built(viewer_dir, repo=args.repo, pin=args.pin,
                                do_install=args.install, do_build=args.build)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not args.build and not os.path.isdir(dist_dir):
        print("API up; UI not built — rerun without --no-build",
              file=sys.stderr)

    ctx = ServerContext(base_dir=base_dir, viewer_dir=viewer_dir,
                        dist_dir=dist_dir,
                        identity={"principal_id": args.principal_id,
                                  "principal_type": args.principal_type,
                                  "org_id": args.org_id},
                        bucket=args.bucket, profile=args.profile,
                        author=_resolve_author(args.author))
    try:
        server = make_server(args.port, ctx)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print(f"error: port {args.port} in use — viewer already running? "
                  f"http://127.0.0.1:{args.port}/ (or pass --port)",
                  file=sys.stderr)
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1

    port = server.server_address[1]
    try:
        # The printed URL is the readiness signal (request logs stay quiet).
        print(f"http://127.0.0.1:{port}/", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        print("viewer stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
