"""Shell integration tests for hooks/roll-capture.sh (the Stop / SessionEnd roll).

The hook is fail-open: config-gated, throttled, degrades when its tools are
absent, never blocks the turn, and always exits 0. These tests drive the REAL
hook via `subprocess.run(["bash", hook], input=<json>, ...)` and assert exit code
plus on-disk side effects -- no mocks. The pure throttle (`should_roll`) is NOT
re-implemented or mocked here: the hook invokes it via python3, and we assert the
observable roll/no-roll outcome on disk.

Every test uses an isolated tmp HOME (so config.json + the capture store live
under it, never the developer's real ~/.driver) and a unique per-test session id.
PATH is stripped to simulate a missing `uv` / `python3` for the degrade cases.

The cases that need a real conversion (a token actually redacted into the store;
the SessionEnd synchronous finalize; the real-roll index enrich) require
logs2atif -- an external dependency absent from the zero-dep CI path, pinned to
a git+ssh ref. They are gated with
`@unittest.skipUnless(_logs2atif_available(), ...)` plus a per-test
pin-resolvability probe (`_hook_pin_resolvable`) -- named justifications for
skipping, NOT mocks of logs2atif. When logs2atif is absent or the hook's git+ssh
pin cannot resolve from this environment, they SKIP cleanly; that is expected.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from functools import lru_cache
from pathlib import Path

from conftest import PLUGIN_ROOT

HOOK = PLUGIN_ROOT / "hooks" / "roll-capture.sh"

_HOOK_PIN_SKIP_REASON = ("logs2atif git+ssh pin not resolvable from this "
                         "environment (needs GitHub ssh auth or a warm uv cache)")


def _logs2atif_available() -> bool:
    try:
        import logs2atif  # noqa: F401
        return True
    except Exception:
        return False


def _jq_available() -> bool:
    return shutil.which("jq") is not None


@lru_cache(maxsize=None)
def _hook_dep_pin() -> str:
    """The exact dependency string the hook hands to `uv run --with`, parsed from
    the hook source so the resolvability probe always exercises the real pin."""
    m = re.search(r"uv run --with '([^']+)'", HOOK.read_text())
    return m.group(1) if m else ""


@lru_cache(maxsize=None)
def _real_uv_cache_dir() -> str:
    """The uv cache dir under the REAL home (asked of uv once). The isolated
    test HOME would otherwise point uv at an empty cache, forcing every hook run
    through a cold git+ssh resolve. "" when uv is absent or unaskable."""
    uv = shutil.which("uv")
    if uv is None:
        return ""
    try:
        res = subprocess.run([uv, "cache", "dir"], capture_output=True,
                             text=True, timeout=30)
    except Exception:
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


@lru_cache(maxsize=None)
def _hook_pin_resolvable() -> bool:
    """Probe (once per test run) whether the hook's inner
    `uv run --with '<git+ssh pin>'` can resolve from this environment.

    logs2atif is pinned to a git+ssh ref, so resolution needs GitHub ssh auth or
    an already-warm uv cache; the e2e tests that run the real hook SKIP with a
    named reason when neither is available (external dependency absent -- never
    mocked). A successful probe also warms the uv cache under the real HOME's
    ssh setup, which the isolated-HOME hook runs then reuse via UV_CACHE_DIR.
    BatchMode/ConnectTimeout keep an authless or offline probe from hanging."""
    pin = _hook_dep_pin()
    uv = shutil.which("uv")
    if not pin or uv is None:
        return False
    env = dict(os.environ)
    env.setdefault("GIT_SSH_COMMAND",
                   "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes "
                   "-o ConnectTimeout=10")
    try:
        res = subprocess.run(
            [uv, "run", "--with", pin, "python", "-c", "import logs2atif"],
            capture_output=True, text=True, timeout=240, env=env,
            cwd=tempfile.gettempdir())  # neutral cwd: no project to sync
    except Exception:
        return False
    return res.returncode == 0


def _wait_for(path: Path, seconds: float, interval: float = 0.2) -> bool:
    """Bounded poll: True as soon as `path` exists, else False after `seconds`."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(interval)
    return path.exists()


def _assert_absent_for(test, path: Path, seconds: float, interval: float = 0.2):
    """Poll up to `seconds` asserting `path` never appears (no background roll)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        test.assertFalse(path.exists(), f"{path} should not exist (no roll expected)")
        time.sleep(interval)


# A tiny valid Claude Code JSONL transcript: one assistant turn so the converter
# yields at least one step (avoids an empty-trajectory error confounding the run).
# A planted Anthropic token lives in the assistant text so the logs2atif-positive
# case can prove the store holds only the REDACTED artifact.
PLANTED_TOKEN = "sk-ant-" + "A" * 40


def _transcript_lines(session_id: str, *, with_token: bool = False, n_turns: int = 1):
    lines = []
    for i in range(n_turns):
        text = "hello world step %d" % i
        if with_token and i == 0:
            text = f"the api key is {PLANTED_TOKEN}"
        lines.append(json.dumps({
            "type": "assistant", "isSidechain": False, "sessionId": session_id,
            "timestamp": "2026-06-25T00:00:00Z",
            "message": {
                "id": f"m{i}", "model": "claude-opus-4-8-20260315",
                "content": [{"type": "text", "text": text}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        }))
    return lines


@unittest.skipUnless(_jq_available(), "jq is not installed -- skipping roll-capture tests")
class RollCaptureHookBase(unittest.TestCase):
    """Shared isolated-HOME + transcript scaffolding for the roll-capture tests."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="drvr-roll-home-"))
        self.work = Path(tempfile.mkdtemp(prefix="drvr-roll-work-"))
        self.driver = self.home / ".driver"
        self.config = self.driver / "config.json"
        self.driver.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    # -- helpers --------------------------------------------------------------

    def _sid(self, label="s"):
        return f"test-{label}-{os.getpid()}-{int(time.time()*1000) % 1000000}"

    def _write_config(self, rolling_capture=True, raw=None):
        if raw is not None:
            self.config.write_text(raw)
        else:
            self.config.write_text(json.dumps({"rolling_capture": rolling_capture}))

    def _write_transcript(self, session_id, *, with_token=False, n_turns=1):
        """Write the transcript under <work>/<session-id>/session.jsonl so that
        --session-dir "$(dirname TRANSCRIPT)" == <work>/<session-id> still reaches
        <session-dir>/<session-id>/subagents (none here -> empty subagents)."""
        sess_dir = self.work / session_id
        sess_dir.mkdir(parents=True, exist_ok=True)
        tpath = sess_dir / "session.jsonl"
        tpath.write_text(
            "\n".join(_transcript_lines(session_id, with_token=with_token,
                                        n_turns=n_turns)) + "\n")
        return tpath

    def _store_dir(self, session_id):
        return self.driver / "capture" / "sessions" / session_id

    def _run(self, payload, *, path=None, env_overrides=None):
        """Run the hook with `payload` as JSON stdin under the isolated HOME.

        The isolated HOME hides the real uv cache and ~/.ssh, both of which the
        hook's inner `uv run --with '<git+ssh logs2atif pin>'` needs to resolve:
        point uv back at the real cache (UV_CACHE_DIR) and auto-accept unknown
        host keys (the fake HOME has no known_hosts). Whether auth/cache
        actually suffice is probed by _hook_pin_resolvable; unresolvable
        environments skip the real-roll e2e tests by name."""
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        if "UV_CACHE_DIR" not in env and _real_uv_cache_dir():
            env["UV_CACHE_DIR"] = _real_uv_cache_dir()
        env.setdefault("GIT_SSH_COMMAND", "ssh -o StrictHostKeyChecking=accept-new")
        if path is not None:
            env["PATH"] = path
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(payload) if not isinstance(payload, str) else payload,
            capture_output=True, text=True, timeout=120, env=env, cwd=str(self.work),
        )

    def _payload(self, session_id, transcript, event="Stop"):
        return {
            "session_id": session_id,
            "transcript_path": str(transcript),
            "hook_event_name": event,
            "cwd": str(self.work),
        }


class TestRollCaptureGatesAndFailOpen(RollCaptureHookBase):
    """Config gate, fail-open, and graceful degrade -- all stdlib-only (no logs2atif)."""

    def test_disabled_when_rolling_capture_unset(self):
        # No rolling_capture key -> gate closed -> exit 0, nothing written.
        self._write_config(raw=json.dumps({}))
        sid = self._sid("unset")
        t = self._write_transcript(sid, n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists(),
                         "store must not be written when gate is closed")

    def test_disabled_when_rolling_capture_false(self):
        self._write_config(rolling_capture=False)
        sid = self._sid("false")
        t = self._write_transcript(sid, n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_no_config_file(self):
        # No config.json at all -> gate closed -> exit 0, no store.
        if self.config.exists():
            self.config.unlink()
        sid = self._sid("noconfig")
        t = self._write_transcript(sid, n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_malformed_stdin(self):
        # Not JSON at all -> exit 0, no crash, no store.
        self._write_config(rolling_capture=True)
        res = self._run("this is not json at all")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse((self.driver / "capture").exists())

    def test_malformed_config_json(self):
        # Config is unreadable JSON -> jq yields nothing -> gate closed -> exit 0.
        self._write_config(raw="{ this is not valid json ]")
        sid = self._sid("badcfg")
        t = self._write_transcript(sid, n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_uv_unavailable_on_path(self):
        # A PATH with jq + python3 but NO uv -> degrade -> exit 0, no store.
        self._write_config(rolling_capture=True)
        sid = self._sid("nouv")
        t = self._write_transcript(sid, n_turns=5)
        path = self._path_without(("uv",))
        res = self._run(self._payload(sid, t), path=path)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_python3_unavailable_on_path(self):
        # python3 backs the pure throttle; without it the hook degrades -> exit 0.
        self._write_config(rolling_capture=True)
        sid = self._sid("nopy")
        t = self._write_transcript(sid, n_turns=5)
        path = self._path_without(("python3", "python"))
        res = self._run(self._payload(sid, t), path=path)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_unsafe_session_id_traversal(self):
        # A '../escape' session id must never write outside the per-session dir.
        self._write_config(rolling_capture=True)
        sid = "../escape"
        t = self._write_transcript("safe-holder", n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        # Nothing leaked above the sessions dir into .driver/capture.
        escaped = self.driver / "capture" / "escape"
        self.assertFalse(escaped.exists())
        self.assertFalse((self.driver / "escape").exists())

    def test_unsafe_session_id_leading_dot(self):
        # A leading-dot session id ('.hidden') is rejected by the write guard.
        self._write_config(rolling_capture=True)
        sid = ".hidden"
        t = self._write_transcript("safe-holder2", n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse((self.driver / "capture" / "sessions" / ".hidden").exists())

    def test_transcript_missing_file_no_crash(self):
        # transcript_path points at a nonexistent file -> the -f check fails ->
        # exit 0, no convert, no store (empty-metric / missing-file guard).
        self._write_config(rolling_capture=True)
        sid = self._sid("notranscript")
        missing = self.work / "does-not-exist.jsonl"
        res = self._run(self._payload(sid, missing))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_below_threshold_no_background_roll(self):
        # A roll-state recording a recent roll at a record_count close to the
        # transcript's current line count -> the pure throttle short-circuits
        # BEFORE any background convert. Assert the store's redacted artifact
        # stays absent across a bounded poll (no background job launched).
        self._write_config(rolling_capture=True)
        sid = self._sid("belowthresh")
        t = self._write_transcript(sid, n_turns=5)  # 5 lines
        store = self._store_dir(sid)
        store.mkdir(parents=True, exist_ok=True)
        cur_mtime = os.stat(t).st_mtime
        # prev_count == 4 (one below the 5-line transcript): delta=1 < 20, and the
        # mtime delta is ~0 < 30 -> should_roll() is False.
        (store / "roll-state.json").write_text(
            json.dumps({"record_count": 4, "mtime": cur_mtime}))
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        # No background convert -> the redacted artifact never appears.
        _assert_absent_for(self, store / "trajectory.redacted.json", 2.5)

    # -- PATH helper ----------------------------------------------------------

    def _path_without(self, drop_names):
        """Build a temp bin dir symlinking every needed tool EXCEPT drop_names,
        then return a PATH containing only it. Guarantees the dropped tool is
        absent regardless of where it really lives."""
        bindir = self.work / ("bin-" + "-".join(drop_names))
        bindir.mkdir(parents=True, exist_ok=True)
        for tool in ("bash", "sh", "jq", "python3", "python", "cat", "mkdir",
                     "mktemp", "mv", "rm", "wc", "stat", "tr", "printf", "uv",
                     "dirname", "env", "uname", "sleep"):
            if tool in drop_names:
                continue
            real = shutil.which(tool)
            if real:
                link = bindir / tool
                if not link.exists():
                    try:
                        link.symlink_to(real)
                    except OSError:
                        pass
        return str(bindir)


@unittest.skipUnless(_logs2atif_available(), "logs2atif not installed (external dep)")
class TestRollCaptureLogs2atifPositive(RollCaptureHookBase):
    """Above-threshold + enabled against a REAL fixture transcript: the backgrounded
    Stop roll publishes a redacted-only store atomically."""

    def test_above_threshold_publishes_redacted_only_store(self):
        if shutil.which("uv") is None:
            self.skipTest("uv not installed -- roll path needs uv")
        if not _hook_pin_resolvable():
            self.skipTest(_HOOK_PIN_SKIP_REASON)
        self._write_config(rolling_capture=True)
        sid = self._sid("above")
        # No prior roll-state -> first roll fires once the transcript clears the
        # min_first_count floor; several turns keep it comfortably above threshold.
        t = self._write_transcript(sid, with_token=True, n_turns=4)
        store = self._store_dir(sid)
        res = self._run(self._payload(sid, t))  # Stop -> backgrounded roll
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        redacted = store / "trajectory.redacted.json"
        # Backgrounded: poll up to ~60s for the atomic publish.
        self.assertTrue(_wait_for(redacted, 60),
                        f"redacted store did not appear: stderr={res.stderr}")
        # Atomic: the published file is always complete, valid JSON (never torn).
        data = json.loads(redacted.read_text())
        self.assertIsInstance(data, dict)
        # The store holds ONLY redacted content: the planted token is masked.
        blob = redacted.read_text()
        self.assertNotIn(PLANTED_TOKEN, blob)
        self.assertIn("[REDACTED:", blob)
        # No unredacted intermediate lingers in the store dir.
        leftovers = [p.name for p in store.iterdir()
                     if p.name.startswith(".redacted.") or p.name.startswith(".flags.")
                     or p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [], f"unredacted/temp intermediates remain: {leftovers}")


@unittest.skipUnless(_logs2atif_available(), "logs2atif not installed (external dep)")
class TestRollCaptureSessionEndFinalize(RollCaptureHookBase):
    """A SessionEnd event forces a roll even below threshold and writes the store
    SYNCHRONOUSLY (foreground) -- the store exists the instant subprocess.run returns."""

    def test_session_end_forces_synchronous_roll(self):
        if shutil.which("uv") is None:
            self.skipTest("uv not installed -- roll path needs uv")
        if not _hook_pin_resolvable():
            self.skipTest(_HOOK_PIN_SKIP_REASON)
        self._write_config(rolling_capture=True)
        sid = self._sid("sessionend")
        t = self._write_transcript(sid, with_token=True, n_turns=1)
        store = self._store_dir(sid)
        # Plant a roll-state that would make the throttle say "no roll" for a Stop:
        # record_count equal to the current line count, fresh mtime. SessionEnd
        # must override this and roll anyway.
        store.mkdir(parents=True, exist_ok=True)
        cur_mtime = os.stat(t).st_mtime
        (store / "roll-state.json").write_text(
            json.dumps({"record_count": 1, "mtime": cur_mtime}))
        res = self._run(self._payload(sid, t, event="SessionEnd"))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        redacted = store / "trajectory.redacted.json"
        # Foreground finalize: the store exists the instant the call returns -- NO poll.
        self.assertTrue(redacted.exists(),
                        f"SessionEnd roll must finalize synchronously; stderr={res.stderr}")
        data = json.loads(redacted.read_text())
        self.assertIsInstance(data, dict)
        self.assertNotIn(PLANTED_TOKEN, redacted.read_text())


class TestRollCaptureNetworkFree(RollCaptureHookBase):
    """The roll path is network-free by construction: it never imports the uploader.

    Mirrors the atif_to_opik boundary proof -- importing the modules the roll path
    invokes must not pull `opik` (the network egress module) into the process.
    Pure-import assertion; no socket, no mock."""

    def test_roll_path_modules_do_not_import_opik(self):
        cap = str(PLUGIN_ROOT / "scripts" / "capture")
        code = (
            "import sys\n"
            f"sys.path.insert(0, {cap!r})\n"
            "import capture_store_core\n"
            "import redact\n"
            "assert 'opik' not in sys.modules, 'roll path pulled in opik (network egress)'\n"
            "print('OK')\n"
        )
        res = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("OK", res.stdout)


# ---------------------------------------------------------------------------
# Per-roll branch-keyed enrich (update_index_from_store): the authoritative
# index writer that runs after do_roll. These drive the REAL hook against a
# pre-seeded redacted-store fixture so ONLY the enrich tail is exercised (the
# logs2atif convert is made a no-op by a stub `uv` on PATH that exits nonzero,
# leaving the pre-seeded store intact) -- no module mocks, real index.json,
# real git repos for the branch derivation.
# ---------------------------------------------------------------------------


def _git_available() -> bool:
    return shutil.which("git") is not None


@unittest.skipUnless(_jq_available(), "jq is not installed -- skipping enrich tests")
@unittest.skipUnless(_git_available(), "git is not installed -- skipping enrich tests")
class RollCaptureEnrichBase(RollCaptureHookBase):
    """Scaffolding to exercise update_index_from_store against a store fixture.

    A stub `uv` (a real on-disk script that exits 1) keeps `command -v uv`
    satisfied while forcing do_roll's logs2atif convert to fail -- so a pre-seeded
    redacted store survives and the enrich tail reads it. This simulates an
    environment condition (convert unavailable) with a real executable, not a
    mock of any internal module.
    """

    @property
    def index(self):
        return self.driver / "capture" / "index.json"

    def _write_index(self, obj):
        cap = self.driver / "capture"
        cap.mkdir(parents=True, exist_ok=True)
        if isinstance(obj, str):
            self.index.write_text(obj)
        else:
            self.index.write_text(json.dumps(obj, indent=2))

    def _read_index(self):
        return json.loads(self.index.read_text())

    def _seed_store(self, session_id, *, total_steps=None, total_cost_usd=None,
                    extra_final=None):
        """Write a real redacted-store fixture with a content-free final_metrics.

        The fixture carries a `content` field OUTSIDE final_metrics to prove the
        enrich reads ONLY final_metrics (counts/cost) into the index.
        """
        store = self._store_dir(session_id)
        store.mkdir(parents=True, exist_ok=True)
        fm = {}
        if total_steps is not None:
            fm["total_steps"] = total_steps
        if total_cost_usd is not None:
            fm["total_cost_usd"] = total_cost_usd
        if extra_final:
            fm.update(extra_final)
        traj = {"final_metrics": fm,
                "records": [{"message": "secret reasoning content"}]}
        (store / "trajectory.redacted.json").write_text(json.dumps(traj))
        return store / "trajectory.redacted.json"

    def _stub_uv_path(self):
        """A PATH whose `uv` is a stub that exits 1 (convert no-op), every other
        tool the hook needs symlinked from the real environment."""
        bindir = self.work / "bin-stub-uv"
        bindir.mkdir(parents=True, exist_ok=True)
        for tool in ("bash", "sh", "jq", "python3", "python", "cat", "mkdir",
                     "mktemp", "mv", "rm", "wc", "stat", "tr", "printf",
                     "dirname", "env", "uname", "sleep", "git"):
            real = shutil.which(tool)
            if real:
                link = bindir / tool
                if not link.exists():
                    try:
                        link.symlink_to(real)
                    except OSError:
                        pass
        stub = bindir / "uv"
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(0o755)
        return str(bindir)

    def _git_repo(self, branch):
        repo = self.work / f"repo-{branch}-{os.getpid()}-{int(time.time()*1000)%1000000}"
        repo.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update({
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        })
        subprocess.run(["git", "init", "-q"], cwd=str(repo), env=env, check=True,
                       capture_output=True)
        subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=str(repo),
                       env=env, check=True, capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), env=env, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo),
                       env=env, check=True, capture_output=True)
        return os.path.realpath(str(repo))

    def _run_enrich(self, session_id, transcript, repo, *, event="SessionEnd",
                    payload_cwd=True):
        """Drive the hook so the enrich tail runs synchronously (SessionEnd) with a
        stub uv that no-ops the convert. `repo` is the cwd used for branch
        derivation; when payload_cwd is False the .cwd is omitted from stdin so
        the backward-scan transcript fallback is exercised."""
        payload = {"session_id": session_id, "transcript_path": str(transcript),
                   "hook_event_name": event}
        if payload_cwd:
            payload["cwd"] = str(repo)
        return self._run(payload, path=self._stub_uv_path())


class TestRollCaptureEnrichInPlace(RollCaptureEnrichBase):
    def test_enrich_seeds_real_counts_in_place(self):
        # A branch:x entry for S with null counts, enriched by a roll whose store
        # carries final_metrics -> S stays under branch:x (no new group) with real
        # record_count/total_cost_usd/store_path; the index write is atomic (no
        # temp left behind).
        self._write_config(rolling_capture=True)
        repo = self._git_repo("x")
        sid = self._sid("enrich")
        t = self._write_transcript(sid, n_turns=5)
        self._write_index({
            "branch:x": {
                sid: {"group_key": "branch:x", "session_id": sid, "cwd": repo,
                      "first_seen": "2026-06-01T00:00:00+00:00",
                      "last_seen": "2026-06-01T00:00:00+00:00",
                      "record_count": None, "total_cost_usd": None,
                      "prev_session_id": None}
            }
        })
        store = self._seed_store(sid, total_steps=42, total_cost_usd=1.25)
        res = self._run_enrich(sid, t, repo)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        idx = self._read_index()
        self.assertEqual(list(idx.keys()), ["branch:x"], "no new group created")
        entry = idx["branch:x"][sid]
        self.assertEqual(entry["record_count"], 42)
        self.assertEqual(entry["total_cost_usd"], 1.25)
        self.assertEqual(entry["store_path"], str(store))
        # Atomic write: no .tmp intermediate left in the capture dir.
        leftovers = [p.name for p in (self.driver / "capture").iterdir()
                     if ".tmp." in p.name]
        self.assertEqual(leftovers, [], f"index temp left behind: {leftovers}")

    def test_enrich_reads_only_final_metrics_no_content(self):
        # Egress-by-construction: the store carries content outside final_metrics;
        # the index entry must hold only metadata (no message/reasoning content).
        self._write_config(rolling_capture=True)
        repo = self._git_repo("x")
        sid = self._sid("nocontent")
        t = self._write_transcript(sid, n_turns=5)
        self._write_index({"branch:x": {sid: {
            "group_key": "branch:x", "session_id": sid, "cwd": repo,
            "first_seen": "2026-06-01T00:00:00+00:00",
            "last_seen": "2026-06-01T00:00:00+00:00",
            "record_count": None, "total_cost_usd": None, "prev_session_id": None}}})
        self._seed_store(sid, total_steps=3, total_cost_usd=0.0)
        res = self._run_enrich(sid, t, repo)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        blob = self.index.read_text()
        for banned in ("secret reasoning content", "reasoning", "observation"):
            self.assertNotIn(banned, blob, f"index leaked content: {banned!r}")
        # A genuine 0.0 cost (free/cached roll) is a real value and is stored.
        self.assertEqual(self._read_index()["branch:x"][sid]["total_cost_usd"], 0.0)


class TestRollCaptureEnrichBranchMigrate(RollCaptureEnrichBase):
    def test_branch_change_migrates_entry(self):
        # A branch:main entry for S, then a roll whose cwd is on branch `feature`
        # -> S migrates to branch:feature only; branch:main is pruned; first_seen
        # preserved.
        self._write_config(rolling_capture=True)
        repo = self._git_repo("feature")
        sid = self._sid("migrate")
        t = self._write_transcript(sid, n_turns=5)
        first_seen = "2026-06-01T00:00:00+00:00"
        self._write_index({"branch:main": {sid: {
            "group_key": "branch:main", "session_id": sid, "cwd": repo,
            "first_seen": first_seen, "last_seen": first_seen,
            "record_count": 9, "total_cost_usd": 0.3, "prev_session_id": None}}})
        self._seed_store(sid, total_steps=15, total_cost_usd=0.7)
        res = self._run_enrich(sid, t, repo)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        idx = self._read_index()
        self.assertNotIn("branch:main", idx, "old branch group must be pruned")
        self.assertIn("branch:feature", idx)
        entry = idx["branch:feature"][sid]
        self.assertEqual(entry["first_seen"], first_seen, "first_seen preserved")
        self.assertEqual(entry["record_count"], 15)
        self.assertEqual(entry["total_cost_usd"], 0.7)


class TestRollCaptureEnrichCwdFallback(RollCaptureEnrichBase):
    def _write_transcript_ending_cwdless(self, session_id, repo):
        """A transcript whose LAST record has NO .cwd (a trailing mode record) while
        an EARLIER record DOES -> the backward-scan must recover the earlier cwd.
        Ends cwd-less so a `tail -n 1` fallback would fail (non-vacuous guard)."""
        sess_dir = self.work / session_id
        sess_dir.mkdir(parents=True, exist_ok=True)
        tpath = sess_dir / "session.jsonl"
        lines = []
        # earlier records carry .cwd
        for i in range(3):
            lines.append(json.dumps({
                "type": "assistant", "sessionId": session_id, "cwd": repo,
                "timestamp": "2026-06-25T00:00:00Z",
                "message": {"id": f"m{i}", "model": "claude-opus-4-8-20260315",
                            "content": [{"type": "text", "text": "hi"}],
                            "usage": {"input_tokens": 1, "output_tokens": 1}}}))
        # trailing record with NO .cwd (mode / file-history-snapshot style)
        lines.append(json.dumps({"type": "mode", "mode": "default",
                                 "timestamp": "2026-06-25T00:00:01Z"}))
        tpath.write_text("\n".join(lines) + "\n")
        return tpath

    def test_backward_scan_recovers_cwd_from_earlier_record(self):
        # No .cwd on the payload; transcript ends in a cwd-less record. The tail
        # backward-scans PAST that record to the earlier cwd, derives the branch,
        # and enriches. (A tail -n 1 fallback would find no cwd and fail this.)
        self._write_config(rolling_capture=True)
        repo = self._git_repo("scan")
        sid = self._sid("bscan")
        t = self._write_transcript_ending_cwdless(sid, repo)
        self._write_index({"branch:scan": {sid: {
            "group_key": "branch:scan", "session_id": sid, "cwd": repo,
            "first_seen": "2026-06-01T00:00:00+00:00",
            "last_seen": "2026-06-01T00:00:00+00:00",
            "record_count": None, "total_cost_usd": None, "prev_session_id": None}}})
        self._seed_store(sid, total_steps=8, total_cost_usd=0.2)
        res = self._run_enrich(sid, t, repo, payload_cwd=False)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        idx = self._read_index()
        self.assertIn("branch:scan", idx)
        self.assertEqual(idx["branch:scan"][sid]["record_count"], 8)
        self.assertEqual(idx["branch:scan"][sid]["total_cost_usd"], 0.2)

    def test_no_resolvable_cwd_no_index_write(self):
        # No .cwd on the payload AND no transcript record has a cwd -> the tail
        # returns 0 with no crash and no index write.
        self._write_config(rolling_capture=True)
        sid = self._sid("nocwd")
        sess_dir = self.work / sid
        sess_dir.mkdir(parents=True, exist_ok=True)
        tpath = sess_dir / "session.jsonl"
        # transcript with content but NO record carrying a .cwd
        lines = [json.dumps({"type": "mode", "mode": "default"}),
                 json.dumps({"type": "last-prompt", "text": "hi"})]
        tpath.write_text("\n".join(lines) + "\n")
        self._seed_store(sid, total_steps=5, total_cost_usd=0.1)
        res = self._run_enrich(sid, tpath, self.work, payload_cwd=False)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self.index.exists(),
                         "no resolvable cwd -> no index write")


class TestRollCaptureEnrichOffGit(RollCaptureEnrichBase):
    def test_off_git_cwd_skips_index_write(self):
        # A roll whose cwd is a non-git dir -> branch empty -> group_key
        # 'ungrouped' -> the enrich tail skips the write (no ungrouped bloat); rc 0.
        self._write_config(rolling_capture=True)
        sid = self._sid("offgit")
        t = self._write_transcript(sid, n_turns=5)
        nongit = self.work / "plain"
        nongit.mkdir(parents=True, exist_ok=True)
        self._seed_store(sid, total_steps=5, total_cost_usd=0.1)
        res = self._run_enrich(sid, t, nongit)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self.index.exists(),
                         "off-git (ungrouped) roll must not write an index entry")


@unittest.skipUnless(_logs2atif_available(), "logs2atif not installed (external dep)")
@unittest.skipUnless(_git_available(), "git not installed")
class TestRollCaptureEnrichLogs2atifReal(RollCaptureEnrichBase):
    """A REAL roll (logs2atif convert + redact) enriches a seeded branch:x entry
    with real counts/cost derived from the converted store's final_metrics."""

    def test_real_roll_enriches_branch_entry(self):
        if shutil.which("uv") is None:
            self.skipTest("uv not installed -- roll path needs uv")
        if not _hook_pin_resolvable():
            self.skipTest(_HOOK_PIN_SKIP_REASON)
        self._write_config(rolling_capture=True)
        repo = self._git_repo("x")
        sid = self._sid("realenrich")
        # transcript lives under the git repo so the roll's cwd derivation works
        sess_dir = Path(repo) / sid
        sess_dir.mkdir(parents=True, exist_ok=True)
        tpath = sess_dir / "session.jsonl"
        tpath.write_text(
            "\n".join(_transcript_lines(sid, n_turns=4)) + "\n")
        self._write_index({"branch:x": {sid: {
            "group_key": "branch:x", "session_id": sid, "cwd": repo,
            "first_seen": "2026-06-01T00:00:00+00:00",
            "last_seen": "2026-06-01T00:00:00+00:00",
            "record_count": None, "total_cost_usd": None, "prev_session_id": None}}})
        payload = {"session_id": sid, "transcript_path": str(tpath),
                   "hook_event_name": "SessionEnd", "cwd": repo}
        res = self._run(payload)  # real uv/logs2atif, foreground SessionEnd finalize
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        redacted = self._store_dir(sid) / "trajectory.redacted.json"
        self.assertTrue(redacted.exists(),
                        f"real roll must publish the store; stderr={res.stderr}")
        idx = self._read_index()
        self.assertIn("branch:x", idx)
        entry = idx["branch:x"][sid]
        self.assertIsNotNone(entry["record_count"],
                             "real roll must enrich record_count from final_metrics")
        self.assertIsNotNone(entry["total_cost_usd"])


if __name__ == "__main__":
    unittest.main()
