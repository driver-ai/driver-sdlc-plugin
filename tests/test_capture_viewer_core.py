"""Unit tests for the viewer-backend pure core (scripts/capture/capture_viewer_core.py).

These pin: sync-status classification (synced/pending/missing), the index-entry ->
viewer Run mapping (core fields the viewer dereferences without guards, plus the
extension fields), the whole-index Dataset build (every group covered, exact
vendor/agent singletons, deterministic last_seen-desc ordering, non-dict
groups/entries skipped), the per-run step payload (identical to
atif_to_viewer.build_dataset's transform), the sync gate (strict `confirm: true`),
and request routing/path normalization (query/fragment strip, single %-decode,
traversal-bearing ids rejected). Pure functions, so assertions are on direct
return values -- plain dicts, no I/O, no mocks, stdlib only.
"""

import sys
import unittest

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import atif_to_viewer
import capture_viewer_core


BRANCH_KEY = "branch:eric/capture-viewer"


def _entry(sid, *, group_key=BRANCH_KEY, cwd="/Users/dev/driver-sdlc-plugin",
           first_seen="2026-07-09T10:00:00Z", last_seen="2026-07-09T11:00:00Z",
           record_count=5, total_cost_usd=1.25, prev_session_id=None):
    """An index entry in the real rolling-index shape (plain dict, no I/O)."""
    return {
        "session_id": sid,
        "store_path": f"/home/dev/.driver/capture/sessions/{sid}/trajectory.redacted.json",
        "cwd": cwd,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "record_count": record_count,
        "total_cost_usd": total_cost_usd,
        "prev_session_id": prev_session_id,
        "group_key": group_key,
    }


def _ledger_record(sha):
    """A sync-ledger record in the real shape."""
    return {
        "s3_key": "trajectories/v1/orghash/auth0|sub/proj/main/sid/trajectory.redacted.json",
        "etag": "d41d8cd98f00b204e9800998ecf8427e",
        "synced_at": "2026-07-09T10:30:00Z",
        "artifact_sha256": sha,
    }


class TestSyncStatus(unittest.TestCase):
    def test_sync_status_synced_pending_missing(self):
        ledger = {"sid-a": _ledger_record("sha-1")}
        # Constants are the wire strings the viewer switches on.
        self.assertEqual(capture_viewer_core.SYNCED, "synced")
        self.assertEqual(capture_viewer_core.PENDING, "pending")
        self.assertEqual(capture_viewer_core.MISSING, "missing")
        # Ledger sha matches the current artifact sha -> synced.
        self.assertEqual(
            capture_viewer_core.sync_status(ledger, "sid-a", "sha-1"), "synced")
        # Sha mismatch (re-rolled capture) -> pending again.
        self.assertEqual(
            capture_viewer_core.sync_status(ledger, "sid-a", "sha-2"), "pending")
        # Absent from the ledger -> pending.
        self.assertEqual(
            capture_viewer_core.sync_status(ledger, "sid-b", "sha-1"), "pending")
        # Unreadable/missing artifact (sha None) -> missing, even when a ledger
        # record exists.
        self.assertEqual(
            capture_viewer_core.sync_status(ledger, "sid-a", None), "missing")
        self.assertEqual(
            capture_viewer_core.sync_status({}, "sid-x", None), "missing")


class TestSessionRun(unittest.TestCase):
    def test_session_run_extension_fields(self):
        entry = _entry("sid-a", group_key="branch:eric/agent-session-capture",
                       cwd="/Users/dev/proj", record_count=7, total_cost_usd=2.5,
                       first_seen="2026-07-09T10:00:00Z",
                       last_seen="2026-07-09T10:01:30Z")
        run = capture_viewer_core.session_run(entry, status="pending", uploadable=True)

        # Identity: id == sessionId == taskId == session_id.
        self.assertEqual(run["id"], "sid-a")
        self.assertEqual(run["sessionId"], "sid-a")
        self.assertEqual(run["taskId"], "sid-a")
        # Core-field literals the viewer dereferences without guards.
        self.assertEqual(run["format"], "atif")
        self.assertEqual(run["status"], "completed")
        self.assertIs(run["passed"], False)
        self.assertIsNone(run["reward"])
        self.assertEqual(run["steps"], [])
        self.assertIs(run["multiUser"], True)
        self.assertEqual(run["agentId"], "claude-code")
        self.assertEqual(run["vendorId"], "drvr")
        # Counts approximate from the index record_count.
        self.assertEqual(run["stepCount"], 7)
        self.assertEqual(run["turns"], 7)
        # durationSec from first/last_seen (90s here).
        self.assertEqual(run["durationSec"], 90)
        # Extension fields per the overview contract.
        self.assertEqual(run["syncStatus"], "pending")
        self.assertIs(run["uploadable"], True)
        self.assertEqual(run["branch"], "agent-session-capture")  # owner-stripped
        self.assertEqual(run["codebase"], "proj")                 # basename(cwd)
        self.assertEqual(run["firstSeen"], "2026-07-09T10:00:00Z")
        self.assertEqual(run["lastSeen"], "2026-07-09T10:01:30Z")
        # costUsd threaded at BOTH sites: top-level and tokens.costUsd.
        self.assertEqual(run["costUsd"], 2.5)
        self.assertEqual(run["tokens"], {"costUsd": 2.5})

        # record_count None (the real store has one today) and 0 both -> 1, so the
        # viewer's lazy runs/ fetch (keyed off stepCount > 0) still triggers.
        for count in (None, 0):
            with self.subTest(record_count=count):
                r = capture_viewer_core.session_run(
                    _entry("sid-n", record_count=count),
                    status="pending", uploadable=True)
                self.assertEqual(r["stepCount"], 1)
                self.assertEqual(r["turns"], 1)

        # Ungrouped session: branch is null.
        r = capture_viewer_core.session_run(
            _entry("sid-u", group_key="ungrouped"), status="pending", uploadable=False)
        self.assertIsNone(r["branch"])
        # Missing timestamps -> durationSec null (never a raise).
        r = capture_viewer_core.session_run(
            _entry("sid-t", first_seen=None), status="pending", uploadable=False)
        self.assertIsNone(r["durationSec"])

        # The uploadable predicate (branch-keyed AND readable AND NOT synced) is
        # owned by build_sessions_dataset; pin it through the runs it emits.
        index = {
            BRANCH_KEY: {
                "sid-pending": _entry("sid-pending"),
                "sid-synced": _entry("sid-synced"),
                "sid-gone": _entry("sid-gone"),
            },
            "ungrouped": {"sid-u": _entry("sid-u", group_key="ungrouped")},
        }
        ledger = {"sid-synced": _ledger_record("sha-s")}
        shas = {"sid-pending": "sha-p", "sid-synced": "sha-s",
                "sid-gone": None, "sid-u": "sha-u"}
        dataset = capture_viewer_core.build_sessions_dataset(
            index, ledger, shas, generated_at="2026-07-09T12:00:00Z")
        by_id = {r["id"]: r for r in dataset["runs"]}
        self.assertIs(by_id["sid-pending"]["uploadable"], True)
        self.assertIs(by_id["sid-synced"]["uploadable"], False)   # synced
        self.assertIs(by_id["sid-gone"]["uploadable"], False)     # unreadable
        self.assertIs(by_id["sid-u"]["uploadable"], False)        # ungrouped


class TestBuildSessionsDataset(unittest.TestCase):
    def test_build_sessions_dataset_covers_all_groups(self):
        index = {
            BRANCH_KEY: {
                "sid-new": _entry("sid-new", cwd="/Users/dev/proj",
                                  last_seen="2026-07-09T12:00:00Z"),
                "sid-synced": _entry("sid-synced", cwd="/Users/dev/proj",
                                     last_seen="2026-07-09T11:00:00Z"),
            },
            "ungrouped": {
                # No last_seen: must sort LAST (via `or ""`), never TypeError.
                "sid-un": _entry("sid-un", group_key="ungrouped", last_seen=None),
            },
            "task:whatever": "not-a-dict-group",       # non-dict group skipped
            "branch:eric/other": {
                "sid-bad": ["not", "a", "dict"],        # non-dict entry skipped
                "sid-nocwd": _entry("sid-nocwd", group_key="branch:eric/other",
                                    cwd=None, last_seen="2026-07-09T10:00:00Z"),
            },
        }
        ledger = {"sid-synced": _ledger_record("sha-synced")}
        shas = {"sid-new": "sha-new", "sid-synced": "sha-synced",
                "sid-un": "sha-un", "sid-nocwd": "sha-nocwd"}
        gen = "2026-07-09T12:34:56Z"
        dataset = capture_viewer_core.build_sessions_dataset(
            index, ledger, shas, generated_at=gen)

        # generated_at is injected, not wall-clock.
        self.assertEqual(dataset["generatedAt"], gen)
        # EXACT vendor/agent singleton dicts per the contract.
        self.assertEqual(dataset["vendors"],
                         [{"id": "drvr", "name": "drvr sessions"}])
        self.assertEqual(dataset["agents"],
                         [{"id": "claude-code", "harness": "Claude Code",
                           "model": None, "family": "Anthropic", "vendorId": "drvr"}])

        # One task + one run per session, EVERY group covered (branch-keyed AND
        # ungrouped); non-dict group and non-dict entry skipped.
        run_ids = [r["id"] for r in dataset["runs"]]
        self.assertEqual(sorted(run_ids),
                         ["sid-new", "sid-nocwd", "sid-synced", "sid-un"])
        self.assertNotIn("sid-bad", run_ids)
        self.assertEqual(len(dataset["tasks"]), 4)
        # Runs sorted by last_seen desc; the None last_seen sorts last.
        self.assertEqual(run_ids, ["sid-new", "sid-synced", "sid-nocwd", "sid-un"])
        # task.id == run.id == session_id, pairwise in the same order.
        self.assertEqual([t["id"] for t in dataset["tasks"]], run_ids)

        tasks_by_id = {t["id"]: t for t in dataset["tasks"]}
        runs_by_id = {r["id"]: r for r in dataset["runs"]}
        # Task title <codebase>@<branch>; full task shape pinned (files: []
        # REQUIRED — TaskDetail crashes without it).
        self.assertEqual(tasks_by_id["sid-new"], {
            "id": "sid-new",
            "vendorId": "drvr",
            "title": "proj@capture-viewer",
            "source": "atif",
            "category": "drvr",
            "difficulty": "n/a",
            "instruction": "",
            "files": [],
            "metadata": {"spec_id": "drvr", "task_id": "proj@capture-viewer",
                         "session_id": "sid-new"},
        })
        # Fallback to session_id when branch is None (ungrouped) …
        self.assertEqual(tasks_by_id["sid-un"]["title"], "sid-un")
        # … and when codebase is empty/None (no cwd) even on a branch group.
        self.assertEqual(tasks_by_id["sid-nocwd"]["title"], "sid-nocwd")
        for task in dataset["tasks"]:
            self.assertEqual(task["files"], [])

        # Full viewer-required Run relations/aggregates present on every run.
        for run in dataset["runs"]:
            self.assertEqual(run["taskId"], run["id"])
            self.assertEqual(run["agentId"], "claude-code")
            self.assertEqual(run["vendorId"], "drvr")
            self.assertIn("turns", run)
            self.assertIn("durationSec", run)
        self.assertEqual(runs_by_id["sid-new"]["durationSec"], 7200)

        # Statuses: ledger match -> synced; readable un-synced -> pending.
        self.assertEqual(runs_by_id["sid-synced"]["syncStatus"], "synced")
        self.assertEqual(runs_by_id["sid-new"]["syncStatus"], "pending")
        self.assertEqual(runs_by_id["sid-un"]["syncStatus"], "pending")
        # uploadable = branch-keyed AND readable AND NOT synced.
        self.assertIs(runs_by_id["sid-new"]["uploadable"], True)
        self.assertIs(runs_by_id["sid-synced"]["uploadable"], False)
        self.assertIs(runs_by_id["sid-un"]["uploadable"], False)

        # Deterministic: same inputs -> same dataset (no clock, no randomness).
        again = capture_viewer_core.build_sessions_dataset(
            index, ledger, shas, generated_at=gen)
        self.assertEqual(dataset, again)

    def test_build_sessions_dataset_empty_index(self):
        # Fresh machine: {} index must still be a valid Dataset shape.
        dataset = capture_viewer_core.build_sessions_dataset(
            {}, {}, {}, generated_at="2026-07-09T00:00:00Z")
        self.assertEqual(dataset["generatedAt"], "2026-07-09T00:00:00Z")
        self.assertEqual(dataset["vendors"],
                         [{"id": "drvr", "name": "drvr sessions"}])
        self.assertEqual(dataset["agents"],
                         [{"id": "claude-code", "harness": "Claude Code",
                           "model": None, "family": "Anthropic", "vendorId": "drvr"}])
        self.assertEqual(dataset["tasks"], [])
        self.assertEqual(dataset["runs"], [])


def _traj_step(step_id, *, source="agent", message="", tool_calls=None, results=None):
    """A serialized ATIF step (the shape atif_to_viewer consumes)."""
    step = {"step_id": step_id, "source": source, "message": message}
    if tool_calls is not None:
        step["tool_calls"] = tool_calls
    if results is not None:
        step["observation"] = {"results": results}
    return step


def _traj_with_subagent():
    """A small ATIF traj whose subagent must splice into the flattened steps."""
    return {
        "session_id": "sess-1",
        "agent": {"model_name": "claude"},
        "final_metrics": {"total_prompt_tokens": 300, "total_completion_tokens": 40,
                          "total_cost_usd": 1.23},
        "steps": [
            _traj_step(1, message="main turn",
                       tool_calls=[{"tool_call_id": "spawn-a",
                                    "function_name": "Agent", "arguments": "{}"}],
                       results=[{"source_call_id": "spawn-a",
                                 "content": "subagent finished",
                                 "subagent_trajectory_ref": [
                                     {"trajectory_id": "sess/agent-a"}]}]),
            _traj_step(2, source="user", message="after"),
        ],
        "subagent_trajectories": [
            {"trajectory_id": "sess/agent-a",
             "extra": {"subagent_type": "explorer"},
             "steps": [_traj_step(1, message="A step one")]},
        ],
    }


class TestBuildRunPayload(unittest.TestCase):
    def test_build_run_payload_matches_bridge_transform(self):
        # Same steps as atif_to_viewer.build_dataset for the same traj: subagent
        # splice + cap + step mapping are one transform, not a re-implementation.
        traj = _traj_with_subagent()
        payload = capture_viewer_core.build_run_payload(traj)
        _, _, _, bridge_steps = atif_to_viewer.build_dataset(
            traj, task_id="t", spec_id="s", intent="",
            generated_at="2020-01-01T00:00:00Z")
        self.assertEqual(payload["steps"], bridge_steps)
        self.assertIs(payload["truncated"], False)
        # The splice actually happened (parent + marker + subagent + trailing user).
        self.assertEqual(len(payload["steps"]), 4)

        # Trailing-boundary pop parity: a flatten that ends on a dangling subagent
        # marker (empty unlinked subagent) drops it, exactly like build_dataset.
        dangling = {
            "session_id": "sess-2",
            "steps": [_traj_step(1, message="only")],
            "subagent_trajectories": [{"trajectory_id": "sess/empty", "steps": []}],
        }
        payload = capture_viewer_core.build_run_payload(dangling)
        _, _, _, bridge_steps = atif_to_viewer.build_dataset(
            dangling, task_id="t", spec_id="s", intent="",
            generated_at="2020-01-01T00:00:00Z")
        self.assertEqual(payload["steps"], bridge_steps)
        self.assertIs(payload["truncated"], False)
        self.assertEqual(len(payload["steps"]), 1)

        # Over the MAX_STEPS cap: steps trimmed AND truncated flips true (the UI
        # must not present a capped transcript as complete).
        cap = atif_to_viewer.MAX_STEPS
        big = {"session_id": "sess-big",
               "steps": [_traj_step(i, message=f"s{i}") for i in range(cap + 5)]}
        payload = capture_viewer_core.build_run_payload(big)
        self.assertIs(payload["truncated"], True)
        self.assertEqual(len(payload["steps"]), cap)


class TestValidateSyncRequest(unittest.TestCase):
    RUNS_BY_ID = {
        "sid-up": {"id": "sid-up", "uploadable": True},
        "sid-up2": {"id": "sid-up2", "uploadable": True},
        "sid-synced": {"id": "sid-synced", "uploadable": False},   # already synced
        "sid-un": {"id": "sid-un", "uploadable": False},           # ungrouped
        "sid-gone": {"id": "sid-gone", "uploadable": False},       # unreadable
    }

    def _assert_rejected(self, body, label):
        ids, err = capture_viewer_core.validate_sync_request(body, self.RUNS_BY_ID)
        self.assertEqual(ids, [], msg=label)
        self.assertIsInstance(err, str, msg=label)
        self.assertTrue(err, msg=label)

    def test_validate_sync_request_gate(self):
        # Malformed body: not a JSON object.
        for body in (None, [], "confirm", 42):
            with self.subTest(body=body):
                self._assert_rejected(body, "non-dict body")
        # Missing / false confirm.
        self._assert_rejected({"session_ids": ["sid-up"]}, "missing confirm")
        self._assert_rejected({"session_ids": ["sid-up"], "confirm": False},
                              "confirm false")
        # Strict boolean True — the load-bearing gate detail: truthy look-alikes
        # ("true", 1) must NOT open the gate.
        for confirm in ("true", 1, "yes", [True]):
            with self.subTest(confirm=confirm):
                self._assert_rejected(
                    {"session_ids": ["sid-up"], "confirm": confirm},
                    "truthy-but-not-True confirm")
        # session_ids must be a non-empty list of strings.
        self._assert_rejected({"confirm": True}, "missing session_ids")
        self._assert_rejected({"confirm": True, "session_ids": []}, "empty ids")
        for ids in ("abc", {"a": 1}, ["sid-up", 5], [None], 7):
            with self.subTest(session_ids=ids):
                self._assert_rejected({"confirm": True, "session_ids": ids},
                                      "non-list-of-strings session_ids")
        # Unknown id.
        self._assert_rejected({"confirm": True, "session_ids": ["sid-nope"]},
                              "unknown id")
        # Non-uploadable ids: ungrouped, unreadable, or already synced — and a
        # single bad id poisons the whole batch (nothing egresses).
        for sid in ("sid-synced", "sid-un", "sid-gone"):
            with self.subTest(sid=sid):
                self._assert_rejected({"confirm": True, "session_ids": [sid]},
                                      "non-uploadable id")
        self._assert_rejected(
            {"confirm": True, "session_ids": ["sid-up", "sid-synced"]},
            "mixed batch with one non-uploadable id")
        # Happy path: ids echoed, no error.
        ids, err = capture_viewer_core.validate_sync_request(
            {"confirm": True, "session_ids": ["sid-up", "sid-up2"]},
            self.RUNS_BY_ID)
        self.assertIsNone(err)
        self.assertEqual(ids, ["sid-up", "sid-up2"])


class TestRoute(unittest.TestCase):
    def test_route_dispatch(self):
        route = capture_viewer_core.route

        # normalize_path pinned directly: query/fragment stripped, %-decoded
        # exactly ONCE, duplicate slashes collapsed.
        norm = capture_viewer_core.normalize_path
        self.assertEqual(norm("/dataset.json?x=1"), "/dataset.json")
        self.assertEqual(norm("/a#frag"), "/a")
        self.assertEqual(norm("/a?x=1#frag"), "/a")
        self.assertEqual(norm("/a%40b"), "/a@b")
        self.assertEqual(norm("/a%2540b"), "/a%40b")   # %2540 -> %40, NEVER @
        self.assertEqual(norm("//a///b"), "/a/b")
        self.assertEqual(norm("/a%2F%2Fb"), "/a/b")    # collapse runs post-decode
        # Query strip happens on the RAW path; a decoded '?' is path data.
        self.assertEqual(norm("/a%3Fb"), "/a?b")

        # API routes.
        self.assertEqual(route("GET", "/dataset.json"), ("dataset", {}))
        self.assertEqual(route("GET", "/runs/abc-123.json"),
                         ("run", {"session_id": "abc-123"}))
        self.assertEqual(route("GET", "/api/sessions/abc-123/scan"),
                         ("scan", {"session_id": "abc-123"}))
        self.assertEqual(route("POST", "/api/sync"), ("sync", {}))
        # route normalizes the RAW request path internally.
        self.assertEqual(route("GET", "/dataset.json?x=1"), ("dataset", {}))
        self.assertEqual(route("GET", "//dataset.json"), ("dataset", {}))

        # /api/ is never static-fallbacked; unknown API paths are api_404.
        self.assertEqual(route("GET", "/api/nope")[0], "api_404")
        # POST to anything but /api/sync -> api_404 (even non-/api/ paths).
        for path in ("/dataset.json", "/runs/abc.json", "/", "/index.html"):
            with self.subTest(post_path=path):
                self.assertEqual(route("POST", path)[0], "api_404")
        # HEAD routes like GET: /api/sync is POST-only, so HEAD gets api_404 …
        self.assertEqual(route("HEAD", "/api/sync")[0], "api_404")
        self.assertEqual(route("GET", "/api/sync")[0], "api_404")
        # … and a HEAD of a real API route matches that route (headers-only reply
        # is the shell's job).
        self.assertEqual(route("HEAD", "/dataset.json"), ("dataset", {}))
        # Trailing slash is not the sync endpoint.
        self.assertEqual(route("POST", "/api/sync/")[0], "api_404")

        # Everything else on GET is static (SPA fallback is the shell's job).
        for path in ("/", "/index.html", "/assets/app.js", "/sessions/abc"):
            with self.subTest(get_path=path):
                self.assertEqual(route("GET", path), ("static", {}))

        # Traversal-bearing ids (raw and %-encoded post-decode) degrade to
        # api_404 — a URL-supplied id can never traverse.
        for path in ("/runs/../secrets.json",
                     "/runs/..%2F..%2Fsecrets.json",
                     "/runs/%2e%2e%2fsecrets.json",
                     "/runs/.hidden.json",
                     "/runs/.json",
                     "/api/sessions/../x/scan",
                     "/api/sessions/..%2Fx/scan",
                     "/api/sessions//scan"):
            with self.subTest(path=path):
                self.assertEqual(route("GET", path)[0], "api_404")


if __name__ == "__main__":
    unittest.main()
