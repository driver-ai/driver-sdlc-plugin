"""Integration tests for the viewer-backend shell (scripts/capture/capture_viewer_server.py).

These pin the full HTTP contract of the localhost capture viewer: the live
Dataset endpoint (statuses for branch-keyed, ungrouped, and missing-artifact
sessions), the per-run step payload (404/500 discipline), the counts-only scan
endpoint, the gated sync endpoint (the DoD invariant: a refused request
performs ZERO egress calls), the single-flight sync lock (409 on contention,
released on every exit path), the Host-header/DNS-rebind defense, static/SPA
serving with API isolation, and the launch orchestration (localhost-only bind,
identity validation, ensure_built's clone/fetch/install/build decisions).

Fixtures build a REAL tmp capture store (index.json, s3-sync-ledger.json,
sessions/<id>/trajectory.redacted.json) plus a tmp dist/ -- the store helpers
mirror test_capture_atif_to_s3.py's module-private _seed_session/_write_index/
_mk_traj pattern (copied, never cross-imported). Requests are driven over a
real socket with urllib (http.client only where urllib cannot go: a POST with
no Content-Length). Egress seams are stubbed with unittest.mock.patch on the
atif_to_s3 module namespace (atif_to_s3.upload_one / atif_to_s3.preflight_sso)
-- the server calls them as module attributes, so one patch site covers both.

capture_viewer_server is imported INSIDE test methods (via _import_server), and
every symbol is referenced as a module attribute: the module is absent at the
Task-5 red checkpoint and its launch half stays absent through the Task-6
checkpoint -- a top-level from-import would break collection of this file.
"""

import contextlib
import http.client
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the modules
import atif_to_s3
import atif_to_viewer


def _import_server():
    """Import the shell lazily so COLLECTION survives while it is absent (the
    Task-5 red checkpoint): each test fails with a clean ImportError instead of
    taking the whole file down."""
    import capture_viewer_server
    return capture_viewer_server


# Session ids used across fixtures (valid path components -> route-safe).
SID_1 = "11111111-1111-4111-8111-111111111111"
SID_2 = "22222222-2222-4222-8222-222222222222"
SID_UNGROUPED = "33333333-3333-4333-8333-333333333333"
SID_MISSING = "44444444-4444-4444-8444-444444444444"
SID_UNKNOWN = "99999999-9999-4999-8999-999999999999"

BRANCH_KEY = "branch:eric/agent-session-capture"

IDENTITY = {"principal_id": "auth0|user123", "principal_type": "user",
            "org_id": "org_ABC123"}


# -- store fixtures (pattern copied from test_capture_atif_to_s3.py -- its
#    helpers are module-private, so the pattern is duplicated, not imported) --

def _artifact_path(base_dir, sid):
    return os.path.join(base_dir, "sessions", sid, "trajectory.redacted.json")


def _seed_session(base_dir, sid, traj, *, group_key=BRANCH_KEY,
                  cwd="/Users/dev/PycharmProjects/DriverAI/driver-sdlc-plugin",
                  record_count=16, total_cost_usd=0.5):
    """Write a redacted artifact under the base-dir convention and return the
    index entry pointing at it."""
    art = _artifact_path(base_dir, sid)
    os.makedirs(os.path.dirname(art), exist_ok=True)
    with open(art, "w") as fh:
        json.dump(traj, fh)
    return {"session_id": sid, "group_key": group_key, "cwd": cwd,
            "store_path": art, "first_seen": "2026-07-01T00:00:00+00:00",
            "last_seen": "2026-07-01T00:00:00+00:00",
            "record_count": record_count, "total_cost_usd": total_cost_usd,
            "prev_session_id": None}


def _write_index(base_dir, entries):
    index = {}
    for e in entries:
        index.setdefault(e["group_key"], {})[e["session_id"]] = e
    os.makedirs(base_dir, exist_ok=True)
    with open(os.path.join(base_dir, "index.json"), "w") as fh:
        json.dump(index, fh)
    return index


def _mk_traj(sid, *, message="synced.", total_cost_usd=0.5, total_steps=4):
    return {"schema_version": "ATIF-v1.7", "session_id": sid,
            "agent": {"name": "claude-code"},
            "final_metrics": {"total_cost_usd": total_cost_usd,
                              "total_steps": total_steps},
            "steps": [{"step_id": 1, "source": "agent", "message": message}]}


def _sha_of(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


class _ViewerServerBase(unittest.TestCase):
    """Tmp capture store + tmp built dist/ + a live server on an ephemeral port."""

    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="drvr-viewer-server-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.base = os.path.join(self.tmp, "capture")
        os.makedirs(self.base, exist_ok=True)
        self.dist = os.path.join(self.tmp, "dist")
        os.makedirs(self.dist, exist_ok=True)
        with open(os.path.join(self.dist, "index.html"), "w") as fh:
            fh.write("<!doctype html><title>viewer</title>SPA-INDEX-MARKER")

    def _ctx(self, cvs):
        return cvs.ServerContext(
            base_dir=self.base, viewer_dir=os.path.join(self.tmp, "viewer"),
            dist_dir=self.dist, identity=dict(IDENTITY),
            bucket="test-bucket", profile="test-profile")

    def _start(self):
        cvs = _import_server()
        self.srv = cvs.make_server(0, self._ctx(cvs))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)   # LIFO: shutdown before close
        return cvs

    # -- HTTP drivers ---------------------------------------------------------

    def _request(self, path, *, method="GET", data=None, headers=None,
                 host=None, timeout=10):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        if host is not None:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            hdrs = e.headers
            e.close()
            return e.code, hdrs, body

    def _get_json(self, path, **kw):
        status, headers, body = self._request(path, **kw)
        return status, headers, json.loads(body)

    def _post_sync(self, payload, *, ct="application/json", host=None,
                   timeout=10):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        headers = {"Content-Type": ct} if ct is not None else {}
        return self._request("/api/sync", method="POST", data=data,
                             headers=headers, host=host, timeout=timeout)

    def _raw_post(self, headers):
        """POST /api/sync via http.client so headers are EXACTLY as given --
        urllib always adds a Content-Length for a bytes body."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("POST", "/api/sync")
            for k, v in headers.items():
                conn.putheader(k, v)
            conn.endheaders()
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    # -- store fixtures -------------------------------------------------------

    def _seed(self, sid, *, group_key=BRANCH_KEY, message="hello there.", **kw):
        return _seed_session(self.base, sid, _mk_traj(sid, message=message),
                             group_key=group_key, **kw)

    def _write_ledger(self, records):
        with open(os.path.join(self.base, "s3-sync-ledger.json"), "w") as fh:
            json.dump(records, fh)

    def _ledger_on_disk(self):
        with open(os.path.join(self.base, "s3-sync-ledger.json")) as fh:
            return json.load(fh)


class TestDatasetEndpoint(_ViewerServerBase):
    def test_get_dataset_end_to_end(self):
        e_synced = self._seed(SID_1)
        e_pending = self._seed(SID_2)
        e_ungrouped = self._seed(SID_UNGROUPED, group_key="ungrouped")
        e_missing = self._seed(SID_MISSING)
        _write_index(self.base, [e_synced, e_pending, e_ungrouped, e_missing])
        self._write_ledger({SID_1: {
            "s3_key": "trajectories/v1/h/p/cb/br/x/trajectory.redacted.json",
            "etag": "e1", "synced_at": "2026-07-09T00:00:00Z",
            "artifact_sha256": _sha_of(_artifact_path(self.base, SID_1))}})
        os.remove(_artifact_path(self.base, SID_MISSING))
        self._start()

        status, headers, body = self._get_json("/dataset.json")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("Content-Type"), "application/json")
        self.assertIn("generatedAt", body)
        self.assertEqual(body["vendors"], [{"id": "drvr", "name": "drvr sessions"}])

        runs = {r["id"]: r for r in body["runs"]}
        self.assertEqual(set(runs),
                         {SID_1, SID_2, SID_UNGROUPED, SID_MISSING})
        # Ledger sha matches -> synced, not uploadable (capture-viewer DEC-008).
        self.assertEqual(runs[SID_1]["syncStatus"], "synced")
        self.assertFalse(runs[SID_1]["uploadable"])
        # Un-ledgered branch-keyed session with a readable artifact -> pending.
        self.assertEqual(runs[SID_2]["syncStatus"], "pending")
        self.assertTrue(runs[SID_2]["uploadable"])
        self.assertEqual(runs[SID_2]["branch"], "agent-session-capture")
        self.assertEqual(runs[SID_2]["codebase"], "driver-sdlc-plugin")
        # Ungrouped sessions appear but are never uploadable; branch is null.
        self.assertEqual(runs[SID_UNGROUPED]["syncStatus"], "pending")
        self.assertFalse(runs[SID_UNGROUPED]["uploadable"])
        self.assertIsNone(runs[SID_UNGROUPED]["branch"])
        # Missing artifact -> missing, never uploadable.
        self.assertEqual(runs[SID_MISSING]["syncStatus"], "missing")
        self.assertFalse(runs[SID_MISSING]["uploadable"])
        # One task per run; task.id == run.id == session_id.
        self.assertEqual({t["id"] for t in body["tasks"]}, set(runs))


class TestRunPayloadEndpoint(_ViewerServerBase):
    def test_get_run_payload_and_404(self):
        e1 = self._seed(SID_1, message="run payload body.")
        e_missing = self._seed(SID_MISSING)
        e_corrupt = self._seed(SID_2)
        _write_index(self.base, [e1, e_missing, e_corrupt])
        os.remove(_artifact_path(self.base, SID_MISSING))
        with open(_artifact_path(self.base, SID_2), "w") as fh:
            fh.write("{ not valid json ]")
        self._start()

        # Known id: converted via the bridge transform (steps + truncated).
        status, headers, body = self._get_json(f"/runs/{SID_1}.json")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertIs(body["truncated"], False)
        self.assertEqual(len(body["steps"]), 1)
        self.assertEqual(body["steps"][0]["text"], "run payload body.")
        self.assertEqual(body["steps"][0]["role"], "agent")

        # Unknown id -> 404 JSON (with the no-store header on the ERROR too).
        status, headers, body = self._get_json(f"/runs/{SID_UNKNOWN}.json")
        self.assertEqual(status, 404)
        self.assertIn("error", body)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

        # Known id, artifact missing -> 404 with the pinned error body.
        status, headers, body = self._get_json(f"/runs/{SID_MISSING}.json")
        self.assertEqual(status, 404)
        self.assertEqual(body, {"error": "artifact missing"})
        self.assertEqual(headers.get("Cache-Control"), "no-store")

        # Artifact present but corrupt JSON -> 500 {"error": ...}, no crash.
        status, headers, body = self._get_json(f"/runs/{SID_2}.json")
        self.assertEqual(status, 500)
        self.assertIn("error", body)
        self.assertEqual(headers.get("Cache-Control"), "no-store")


class TestScanEndpoint(_ViewerServerBase):
    def test_scan_counts_only(self):
        e1 = self._seed(SID_1, message="contact dev@example.com")
        e_missing = self._seed(SID_MISSING)
        e_corrupt = self._seed(SID_2)
        _write_index(self.base, [e1, e_missing, e_corrupt])
        os.remove(_artifact_path(self.base, SID_MISSING))
        with open(_artifact_path(self.base, SID_2), "w") as fh:
            fh.write("{ not valid json ]")
        self._start()

        status, headers, raw = self._request(f"/api/sessions/{SID_1}/scan")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        body = json.loads(raw)
        self.assertEqual(body["session_id"], SID_1)
        self.assertTrue(body["by_type"])
        self.assertTrue(all(isinstance(v, int) for v in body["by_type"].values()))
        self.assertGreaterEqual(body["by_type"].get("Email address", 0), 1)
        # Counts ONLY: no snippet/where keys -- and no finding text -- anywhere.
        self.assertNotIn(b"snippet", raw)
        self.assertNotIn(b"where", raw)
        self.assertNotIn(b"dev@example.com", raw)

        # Known id, artifact missing -> 404 (never a misleading empty-counts 200).
        status, _headers, body = self._get_json(f"/api/sessions/{SID_MISSING}/scan")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

        # Corrupt-but-hashable artifact must never read as clean -> 500.
        status, _headers, body = self._get_json(f"/api/sessions/{SID_2}/scan")
        self.assertEqual(status, 500)
        self.assertIn("error", body)


class TestSyncGateRefusal(_ViewerServerBase):
    def test_sync_gate_refusal_no_egress(self):
        e1 = self._seed(SID_1)
        _write_index(self.base, [e1])
        self._start()
        valid = {"confirm": True, "session_ids": [SID_1]}

        with mock.patch.object(atif_to_s3, "upload_one") as up, \
             mock.patch.object(atif_to_s3, "preflight_sso") as pre:
            # Missing confirm -> 400 (strict-True is pinned in the core tests).
            status, headers, raw = self._post_sync({"session_ids": [SID_1]})
            self.assertEqual(status, 400)
            self.assertIn("error", json.loads(raw))
            self.assertEqual(headers.get("Cache-Control"), "no-store")

            # Unknown id -> 400.
            status, _h, raw = self._post_sync(
                {"confirm": True, "session_ids": [SID_UNKNOWN]})
            self.assertEqual(status, 400)
            self.assertIn("error", json.loads(raw))

            # Wrong Content-Type -> 400 before the gate runs.
            status, _h, _b = self._post_sync(valid, ct="text/plain")
            self.assertEqual(status, 400)

            # No explicit Content-Type (urllib defaults to a form CT) -> 400.
            status, _h, _b = self._post_sync(valid, ct=None)
            self.assertEqual(status, 400)

            # Media-type compare: a charset parameter is ACCEPTED -- this 400 is
            # the GATE's (confirm missing), proving the CT check passed.
            status, _h, raw = self._post_sync(
                {"session_ids": [SID_1]}, ct="application/json; charset=utf-8")
            self.assertEqual(status, 400)
            self.assertIn("confirm", json.loads(raw)["error"])

            # Invalid JSON body -> 400.
            status, _h, _b = self._post_sync(b"{ not json", ct="application/json")
            self.assertEqual(status, 400)

            # Missing Content-Length (urllib always sends one -> raw http.client).
            status, _body = self._raw_post({"Content-Type": "application/json"})
            self.assertEqual(status, 400)

            # Negative Content-Length -> 400.
            status, _body = self._raw_post({"Content-Type": "application/json",
                                            "Content-Length": "-7"})
            self.assertEqual(status, 400)

            # Non-integer Content-Length -> 400.
            status, _body = self._raw_post({"Content-Type": "application/json",
                                            "Content-Length": "nan"})
            self.assertEqual(status, 400)

            # THE invariant: a refused request performs ZERO egress calls.
            up.assert_not_called()
            pre.assert_not_called()


class TestSyncHappyPath(_ViewerServerBase):
    def test_sync_happy_path(self):
        e1 = self._seed(SID_1)
        e2 = self._seed(SID_2)
        _write_index(self.base, [e1, e2])
        sha1 = _sha_of(_artifact_path(self.base, SID_1))
        sha2 = _sha_of(_artifact_path(self.base, SID_2))
        self._start()

        def fake_upload(key, body_path, metadata, *, bucket, profile):
            return "etag-" + metadata["session-id"]

        with mock.patch.object(atif_to_s3, "upload_one",
                               side_effect=fake_upload) as up, \
             mock.patch.object(atif_to_s3, "preflight_sso") as pre:
            status, headers, raw = self._post_sync(
                {"confirm": True, "session_ids": [SID_1, SID_2]})
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("Cache-Control"), "no-store")
            results = {r["session_id"]: r for r in json.loads(raw)["results"]}
            self.assertEqual(set(results), {SID_1, SID_2})   # every requested id
            for sid in (SID_1, SID_2):
                self.assertTrue(results[sid]["ok"])
                self.assertEqual(results[sid]["etag"], "etag-" + sid)
                self.assertIn("s3_key", results[sid])
            self.assertEqual(up.call_count, 2)
            pre.assert_called_once_with("test-profile")

            # The ledger was updated per session with the artifact shas.
            ledger = self._ledger_on_disk()
            self.assertEqual(set(ledger), {SID_1, SID_2})
            self.assertEqual(ledger[SID_1]["artifact_sha256"], sha1)
            self.assertEqual(ledger[SID_2]["artifact_sha256"], sha2)

            # Second POST of the SAME ids: now synced -> non-uploadable -> 400
            # with zero additional egress (capture-viewer DEC-008).
            status, _h, raw = self._post_sync(
                {"confirm": True, "session_ids": [SID_1, SID_2]})
            self.assertEqual(status, 400)
            self.assertIn("not uploadable", json.loads(raw)["error"])
            self.assertEqual(up.call_count, 2)


class TestSyncConcurrency(_ViewerServerBase):
    def test_sync_concurrent_second_request_409(self):
        e1 = self._seed(SID_1)
        e2 = self._seed(SID_2)
        _write_index(self.base, [e1, e2])
        self._start()
        entered, release = threading.Event(), threading.Event()

        def slow_upload(key, body_path, metadata, *, bucket, profile):
            entered.set()
            if not release.wait(timeout=30):
                raise RuntimeError("test release timed out")
            return "etag-slow"

        holder = {}

        def first_post():
            holder["resp"] = self._post_sync(
                {"confirm": True, "session_ids": [SID_1]}, timeout=60)

        with mock.patch.object(atif_to_s3, "upload_one",
                               side_effect=slow_upload) as up, \
             mock.patch.object(atif_to_s3, "preflight_sso"):
            t = threading.Thread(target=first_post, daemon=True)
            t.start()
            try:
                self.assertTrue(entered.wait(timeout=15),
                                "first sync never reached its upload")
                # The overlapping second sync gets exactly one 409.
                status, _h, raw = self._post_sync(
                    {"confirm": True, "session_ids": [SID_2]})
                self.assertEqual(status, 409)
                self.assertEqual(json.loads(raw),
                                 {"error": "sync already in progress"})
            finally:
                release.set()       # never leave the process-global lock held
                t.join(timeout=30)
            self.assertFalse(t.is_alive())

            status, _h, raw = holder["resp"]
            self.assertEqual(status, 200)
            results = json.loads(raw)["results"]
            self.assertEqual([r["session_id"] for r in results], [SID_1])
            self.assertTrue(results[0]["ok"])
            # At most once per session: the refused batch never egressed.
            self.assertEqual(up.call_count, 1)


class TestSyncToctou(_ViewerServerBase):
    def test_sync_toctou_artifact_vanishes(self):
        e1 = self._seed(SID_1)
        e2 = self._seed(SID_2)
        _write_index(self.base, [e1, e2])
        self._start()

        def upload_and_vanish(key, body_path, metadata, *, bucket, profile):
            if metadata["session-id"] == SID_1:
                # The second session's artifact vanishes mid-batch, AFTER the
                # request validated against it.
                os.remove(_artifact_path(self.base, SID_2))
            return "etag-" + metadata["session-id"]

        with mock.patch.object(atif_to_s3, "upload_one",
                               side_effect=upload_and_vanish), \
             mock.patch.object(atif_to_s3, "preflight_sso"):
            status, _h, raw = self._post_sync(
                {"confirm": True, "session_ids": [SID_1, SID_2]})

        self.assertEqual(status, 200)
        results = {r["session_id"]: r for r in json.loads(raw)["results"]}
        # The vanished id still appears in results -- as a per-session failure.
        self.assertEqual(set(results), {SID_1, SID_2})
        self.assertTrue(results[SID_1]["ok"])
        self.assertFalse(results[SID_2]["ok"])
        self.assertIn("trajectory.redacted.json", results[SID_2]["error"])
        # Only the successful session was ledgered.
        self.assertEqual(set(self._ledger_on_disk()), {SID_1})


class TestSsoPreflightFailure(_ViewerServerBase):
    def test_sso_preflight_failure_503(self):
        e1 = self._seed(SID_1)
        _write_index(self.base, [e1])
        self._start()
        boom = RuntimeError(
            "SSO session expired or invalid — sign in again, then retry")

        with mock.patch.object(atif_to_s3, "preflight_sso",
                               side_effect=boom), \
             mock.patch.object(atif_to_s3, "upload_one") as up:
            status, headers, raw = self._post_sync(
                {"confirm": True, "session_ids": [SID_1]})
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(raw)["error"], str(boom))
            self.assertEqual(headers.get("Cache-Control"), "no-store")
            up.assert_not_called()

            # Lock released in finally: the retry is a fresh 503, NEVER a 409 --
            # retrying after signing in works.
            status, _h, raw = self._post_sync(
                {"confirm": True, "session_ids": [SID_1]})
            self.assertEqual(status, 503)
            self.assertNotEqual(json.loads(raw).get("error"),
                                "sync already in progress")
            up.assert_not_called()


class TestStaticSpa(_ViewerServerBase):
    def test_static_spa_fallback_and_api_isolation(self):
        # A stale build artifact in dist/ must never shadow the live API.
        with open(os.path.join(self.dist, "dataset.json"), "w") as fh:
            fh.write("STALE-STATIC")
        self._start()

        # Extension-less SPA route -> index.html.
        status, headers, body = self._request("/sessions/abc")
        self.assertEqual(status, 200)
        self.assertIn(b"SPA-INDEX-MARKER", body)
        self.assertIn("text/html", headers.get("Content-Type", ""))

        # Unknown /api/ path -> JSON 404, never the SPA fallback.
        status, headers, body = self._get_json("/api/unknown")
        self.assertEqual(status, 404)
        self.assertEqual(headers.get("Content-Type"), "application/json")
        self.assertIn("error", body)

        # HEAD near-miss: API headers (headers-only), never the stale file.
        status, headers, body = self._request("/dataset.json", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "application/json")
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(body, b"")

        # And the GET serves the live dataset, not the stale static file.
        status, _h, body = self._request("/dataset.json")
        self.assertEqual(status, 200)
        self.assertNotIn(b"STALE-STATIC", body)
        self.assertIn("generatedAt", json.loads(body))


class TestHostHeader(_ViewerServerBase):
    def test_host_header_rejected(self):
        e1 = self._seed(SID_1)
        _write_index(self.base, [e1])
        self._start()

        # A rebound DNS name -> 403 on any route (GET and the sync POST).
        status, headers, body = self._get_json("/dataset.json",
                                               host="evil.example")
        self.assertEqual(status, 403)
        self.assertIn("error", body)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

        with mock.patch.object(atif_to_s3, "upload_one") as up, \
             mock.patch.object(atif_to_s3, "preflight_sso") as pre:
            status, _h, _b = self._post_sync(
                {"confirm": True, "session_ids": [SID_1]}, host="evil.example")
            self.assertEqual(status, 403)
            up.assert_not_called()
            pre.assert_not_called()

        # 127.0.0.1:<port> (urllib default) and localhost:<port> accepted.
        status, _h, _b = self._get_json("/dataset.json")
        self.assertEqual(status, 200)
        status, _h, _b = self._get_json("/dataset.json",
                                        host=f"localhost:{self.port}")
        self.assertEqual(status, 200)
        # Hostname-ONLY compare: the vite dev proxy forwards Host:
        # localhost:5173 -- a DIFFERENT port -- and must be accepted.
        status, _h, _b = self._get_json("/dataset.json", host="localhost:5173")
        self.assertEqual(status, 200)


class TestServerBinding(_ViewerServerBase):
    def test_server_binds_localhost_only(self):
        cvs = _import_server()
        srv = cvs.make_server(0, self._ctx(cvs))
        self.addCleanup(srv.server_close)
        self.assertEqual(srv.server_address[0], "127.0.0.1")
        port = srv.server_address[1]

        # A second bind on the same port fails while the first is listening.
        with self.assertRaises(OSError):
            cvs.make_server(port, self._ctx(cvs))

        # main() renders that as the actionable, INTERPOLATED port-in-use
        # message (never a hardcoded default port) and exits 1.
        argv = ["--port", str(port), "--no-build",
                "--base-dir", self.base,
                "--viewer-dir", os.path.join(self.tmp, "viewer"),
                "--principal-id", "auth0|user123", "--principal-type", "user",
                "--org-id", "org_ABC123"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cvs.main(argv)
            except SystemExit as e:
                rc = e.code
        self.assertEqual(rc, 1)
        expected = (f"port {port} in use — viewer already running? "
                    f"http://127.0.0.1:{port}/ (or pass --port)")
        self.assertIn(expected, err.getvalue())


class TestIdentityArgs(unittest.TestCase):
    def _run_main(self, cvs, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cvs.main(argv)
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def test_identity_args_validated(self):
        cvs = _import_server()
        tmp = tempfile.mkdtemp(prefix="drvr-viewer-id-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        def argv(pid="auth0|user123", ptype="user", org="org_ABC123"):
            return ["--principal-id", pid, "--principal-type", ptype,
                    "--org-id", org,
                    "--base-dir", os.path.join(tmp, "capture"),
                    "--viewer-dir", os.path.join(tmp, "viewer")]

        bad = [argv(pid=""), argv(pid="   "), argv(org=""), argv(org=" \t "),
               argv(ptype="robot")]
        with mock.patch.object(cvs, "make_server") as ms, \
             mock.patch("subprocess.run") as sr:
            for a in bad:
                rc, _out, _err = self._run_main(cvs, a)
                self.assertEqual(rc, 2, a)
            # Exit 2 happens BEFORE any server start (and before any build).
            ms.assert_not_called()
            sr.assert_not_called()


class TestEnsureBuilt(unittest.TestCase):
    """ensure_built's decisions with subprocess.run mocked at ONE patch site --
    capture_viewer_server and atif_to_viewer share the module object, so
    ensure_viewer's git calls hit the same fake."""

    PIN = "a" * 40
    REPO = "https://github.com/driver-ai/ATIF-trajectory-viewer"
    UPSTREAM = "https://github.com/Slimshilin/ATIF-trajectory-viewer"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="drvr-viewer-build-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _vd(self, name, *, git=True, node_modules=True, dist=False,
            built_sha=None, lockfile_newer=False):
        vd = os.path.join(self.tmp, name)
        if git:
            os.makedirs(os.path.join(vd, ".git"), exist_ok=True)
        if node_modules:
            os.makedirs(os.path.join(vd, "node_modules"), exist_ok=True)
        if dist:
            os.makedirs(os.path.join(vd, "dist"), exist_ok=True)
            with open(os.path.join(vd, "dist", "index.html"), "w") as fh:
                fh.write("<html>")
            if built_sha is not None:
                with open(os.path.join(vd, "dist", ".built-sha"), "w") as fh:
                    fh.write(built_sha + "\n")
        if lockfile_newer:
            lock = os.path.join(vd, "package-lock.json")
            with open(lock, "w") as fh:
                fh.write("{}")
            nm = os.path.join(vd, "node_modules")
            past = os.path.getmtime(lock) - 60
            os.utime(nm, (past, past))
        return vd

    def _fake_run(self, vd, state):
        """Emulates the git/npm surface (including check=True semantics: rc!=0
        raises CalledProcessError). Records every argv in state["calls"]."""
        def run(argv, **kwargs):
            argv = list(argv)
            state["calls"].append(argv)
            rc, out = 0, ""
            if argv[:2] == ["git", "-C"] and argv[3:] == ["rev-parse", "HEAD"]:
                if state["head"] is None:
                    rc = 128                       # missing dir / not a repo
                else:
                    out = state["head"] + "\n"
            elif (argv[:2] == ["git", "-C"]
                    and argv[3:6] == ["remote", "get-url", "origin"]):
                if state["origin"] is None:
                    rc = 128
                else:
                    out = state["origin"] + "\n"
            elif argv[:2] == ["git", "-C"] and argv[3:5] == ["remote", "set-url"]:
                state["origin"] = argv[-1]
            elif argv[:2] == ["git", "-C"] and argv[3] == "fetch":
                pass
            elif argv[:2] == ["git", "-C"] and argv[3] == "checkout":
                state["head"] = argv[4]
            elif argv[:2] == ["git", "clone"]:
                state["head"] = state.get("clone_head")
            elif argv == ["npm", "install"]:
                pass
            elif argv == ["npm", "run", "build"]:
                rc = state.get("build_rc", 0)
                if rc == 0:
                    # A real build emits index.html AND the fork's sample
                    # public/ data (dataset.json + runs/) into dist.
                    dist = os.path.join(vd, "dist")
                    os.makedirs(os.path.join(dist, "runs"), exist_ok=True)
                    for rel in ("index.html", "dataset.json",
                                os.path.join("runs", "sample.json")):
                        with open(os.path.join(dist, rel), "w") as fh:
                            fh.write("built")
            else:
                raise AssertionError(f"unexpected subprocess argv: {argv}")
            if kwargs.get("check") and rc != 0:
                raise subprocess.CalledProcessError(rc, argv)
            return subprocess.CompletedProcess(argv, rc, stdout=out, stderr="")
        return run

    def _ensure(self, cvs, vd, state, **kwargs):
        kwargs.setdefault("repo", self.REPO)
        kwargs.setdefault("pin", self.PIN)
        kwargs.setdefault("do_install", True)
        kwargs.setdefault("do_build", True)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("subprocess.run", side_effect=self._fake_run(vd, state)), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return cvs.ensure_built(vd, **kwargs)

    def test_ensure_built_decisions(self):
        cvs = _import_server()

        # dist missing -> builds; .built-sha written after the build; the
        # fork's sample public/ data is removed post-build (it would shadow
        # the live near-miss routes otherwise).
        with self.subTest("dist-missing-builds"):
            vd = self._vd("a")
            state = {"head": self.PIN, "origin": self.REPO, "calls": []}
            dist = self._ensure(cvs, vd, state)
            self.assertEqual(dist, os.path.join(vd, "dist"))
            self.assertIn(["npm", "run", "build"], state["calls"])
            # node_modules present + no newer lockfile -> no install.
            self.assertNotIn(["npm", "install"], state["calls"])
            with open(os.path.join(dist, ".built-sha")) as fh:
                self.assertEqual(fh.read().strip(), self.PIN)
            self.assertFalse(os.path.exists(os.path.join(dist, "dataset.json")))
            self.assertFalse(os.path.exists(os.path.join(dist, "runs")))
            self.assertTrue(os.path.exists(os.path.join(dist, "index.html")))
            # Pin already checked out -> no fetch/checkout/clone ran.
            self.assertFalse([c for c in state["calls"]
                              if "fetch" in c or "checkout" in c or "clone" in c])

        # Pin unchanged + dist present + .built-sha matches -> skips entirely:
        # probes only (the offline warm path -- no fetch, no npm).
        with self.subTest("warm-skip"):
            vd = self._vd("b", dist=True, built_sha=self.PIN)
            state = {"head": self.PIN, "origin": self.REPO, "calls": []}
            dist = self._ensure(cvs, vd, state)
            self.assertEqual(dist, os.path.join(vd, "dist"))
            for argv in state["calls"]:
                self.assertEqual(argv[0], "git", argv)
                self.assertTrue("rev-parse" in argv or "get-url" in argv, argv)
            with open(os.path.join(dist, ".built-sha")) as fh:
                self.assertEqual(fh.read().strip(), self.PIN)

        # dist present but .built-sha mismatched -> rebuilds; lockfile newer
        # than node_modules -> npm install first.
        with self.subTest("built-sha-mismatch-rebuilds"):
            vd = self._vd("c", dist=True, built_sha="0" * 40,
                          lockfile_newer=True)
            state = {"head": self.PIN, "origin": self.REPO, "calls": []}
            self._ensure(cvs, vd, state)
            self.assertIn(["npm", "install"], state["calls"])
            self.assertIn(["npm", "run", "build"], state["calls"])
            with open(os.path.join(vd, "dist", ".built-sha")) as fh:
                self.assertEqual(fh.read().strip(), self.PIN)

        # dist present but .built-sha absent -> rebuilds.
        with self.subTest("built-sha-absent-rebuilds"):
            vd = self._vd("c2", dist=True)
            state = {"head": self.PIN, "origin": self.REPO, "calls": []}
            self._ensure(cvs, vd, state)
            self.assertIn(["npm", "run", "build"], state["calls"])

        # Build failure (rc != 0) -> actionable RuntimeError, NO .built-sha.
        with self.subTest("build-failure"):
            vd = self._vd("d")
            state = {"head": self.PIN, "origin": self.REPO, "calls": [],
                     "build_rc": 1}
            with self.assertRaises(RuntimeError):
                self._ensure(cvs, vd, state)
            self.assertFalse(
                os.path.exists(os.path.join(vd, "dist", ".built-sha")))

        # Stale pin + origin != --repo -> git remote set-url BEFORE the fetch;
        # the checkout lands the pin; matching .built-sha skips the rebuild.
        with self.subTest("origin-reconciled-before-fetch"):
            vd = self._vd("e", dist=True, built_sha=self.PIN)
            state = {"head": "0" * 40, "origin": self.UPSTREAM, "calls": []}
            self._ensure(cvs, vd, state)
            set_url = ["git", "-C", vd, "remote", "set-url", "origin", self.REPO]
            self.assertIn(set_url, state["calls"])
            fetch_idx = next(i for i, c in enumerate(state["calls"])
                             if "fetch" in c)
            self.assertLess(state["calls"].index(set_url), fetch_idx)
            self.assertFalse([c for c in state["calls"] if "clone" in c])
            self.assertNotIn(["npm", "run", "build"], state["calls"])

        # viewer_dir absent entirely -> probe failures tolerated (probes never
        # raise); ensure_viewer's clone path invoked with install owned here.
        with self.subTest("cold-start-clone-path"):
            vd = os.path.join(self.tmp, "f")          # nothing exists
            state = {"head": None, "origin": None, "calls": []}
            with mock.patch.object(atif_to_viewer, "ensure_viewer") as ev:
                self._ensure(cvs, vd, state)
            ev.assert_called_once()
            call_values = ev.call_args.args + tuple(ev.call_args.kwargs.values())
            self.assertIn(vd, call_values)
            self.assertIn(self.REPO, call_values)
            self.assertIn(self.PIN, call_values)
            self.assertIn(False, call_values)          # do_install=False
            # A failed probe never triggers the set-url reconciliation.
            self.assertFalse([c for c in state["calls"] if "set-url" in c])
            # node_modules missing -> npm install (owned by ensure_built).
            self.assertIn(["npm", "install"], state["calls"])

        # --no-build -> pure serve mode: ZERO subprocesses, no ensure_viewer.
        with self.subTest("no-build-zero-subprocesses"):
            vd = self._vd("g", git=False, node_modules=False)
            state = {"head": self.PIN, "origin": self.REPO, "calls": []}
            with mock.patch.object(atif_to_viewer, "ensure_viewer") as ev:
                dist = self._ensure(cvs, vd, state, do_build=False)
            self.assertEqual(dist, os.path.join(vd, "dist"))
            self.assertEqual(state["calls"], [])
            ev.assert_not_called()


if __name__ == "__main__":
    unittest.main()
