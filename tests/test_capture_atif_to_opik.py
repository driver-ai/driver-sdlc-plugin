"""Unit tests for atif_to_opik's pure cores + ledger recovery (scripts/capture/atif_to_opik.py).

These pin: UUIDv7 minting (valid + deterministic), span id stability, ISO dt
parsing, the idempotency key (trace_key), and corrupt-ledger recovery. The pure
helpers are driven directly — no mocks (mocking pure logic is a boundary failure).
The ledger-recovery test uses a REAL corrupt tmp file via the DRVR_LEDGER env
override inside an isolated tmp HOME (real I/O at the shell edge), so it exercises
trace_id_for's read path without invoking register (no opik needed).

The module MUST import without `opik` installed — that proves the lazy import
(Task 7) lands; until then a top-level `import opik` makes these red.
"""

import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import atif_to_opik


# ---------------------------------------------------------------------------
# Gating for the one live integration test (real local Opik, no mock).
#
# The pure tests above need neither opik nor a server. The single integration
# test below talks to a REAL local Opik (mocking it would defeat the point: it
# validates the span API live). Its skipUnless predicate is True only when BOTH
# (a) opik is importable AND (b) the local Opik server actually answers on the
# host:port from OPIK_URL_OVERRIDE -- probed by a real socket connect, so a DOWN
# server SKIPS rather than erroring. atif_to_opik sets OPIK_URL_OVERRIDE to the
# local default (http://localhost:5173/api; port 5173 is Opik, 5273 the viewer)
# at import, so it is always populated here.
# ---------------------------------------------------------------------------

_HAS_OPIK = importlib.util.find_spec("opik") is not None


def _opik_server_reachable() -> bool:
    """True only when a TCP connection to the OPIK_URL_OVERRIDE host:port succeeds.
    Parses host/port from the resolved env URL; a refused/timed-out connect (server
    down) returns False so the gated test SKIPS instead of erroring."""
    url = os.environ.get("OPIK_URL_OVERRIDE")
    if not url:
        return False
    parts = urlsplit(url if "://" in url else f"//{url}")
    host = parts.hostname
    if not host:
        return False
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


_OPIK_REACHABLE = _HAS_OPIK and _opik_server_reachable()


class TestMintUuid7(unittest.TestCase):
    def test_mint_uuid7_valid_and_deterministic(self):
        ms = 1_700_000_000_000
        u = atif_to_opik._mint_uuid7("session::task", ms)
        hexs = u.replace("-", "")
        # Canonical 8-4-4-4-12 shape.
        self.assertEqual(len(hexs), 32)
        # Version nibble is 7 (13th hex digit, byte 6 high nibble).
        self.assertEqual(hexs[12], "7")
        # RFC4122 variant: high bits of the clock-seq byte (byte 8) are 10.
        variant_byte = int(hexs[16:18], 16)
        self.assertEqual(variant_byte >> 6, 0b10)
        # Embedded 48-bit ms matches the input ms.
        self.assertEqual(int(hexs[:12], 16), ms)
        # Deterministic: same (key, ms) -> same uuid.
        self.assertEqual(u, atif_to_opik._mint_uuid7("session::task", ms))
        # Different key -> different uuid (same ms).
        self.assertNotEqual(u, atif_to_opik._mint_uuid7("session::other", ms))


class TestSpanIdAndDt(unittest.TestCase):
    def test_span_id_and_dt(self):
        trace_id = atif_to_opik._mint_uuid7("session::task", 1_700_000_000_000)
        a = atif_to_opik._span_id(trace_id, "step1")
        # Deterministic: same (trace_id, suffix) -> same span id.
        self.assertEqual(a, atif_to_opik._span_id(trace_id, "step1"))
        # Different suffix -> different span id.
        self.assertNotEqual(a, atif_to_opik._span_id(trace_id, "step2"))
        # Reuses the trace's embedded ms (first 48 bits stay identical).
        self.assertEqual(a.replace("-", "")[:12], trace_id.replace("-", "")[:12])

        # _dt parses an ISO string to a non-str (datetime) value.
        parsed = atif_to_opik._dt("2020-01-01T00:00:00Z")
        self.assertIsNotNone(parsed)
        self.assertNotIsInstance(parsed, str)
        # None / unparseable -> None (and never a str).
        self.assertIsNone(atif_to_opik._dt(None))
        self.assertIsNone(atif_to_opik._dt("not-a-timestamp"))


class TestTraceKey(unittest.TestCase):
    def test_trace_key(self):
        self.assertEqual(atif_to_opik.trace_key("sid", "task"), "sid::task")
        # None inputs fall back to sentinels.
        self.assertEqual(atif_to_opik.trace_key(None, None), "unknown-session::no-task")
        self.assertEqual(atif_to_opik.trace_key(None, "task"), "unknown-session::task")
        self.assertEqual(atif_to_opik.trace_key("sid", None), "sid::no-task")
        # Stable / deterministic.
        self.assertEqual(atif_to_opik.trace_key("sid", "task"),
                         atif_to_opik.trace_key("sid", "task"))


# ---------------------------------------------------------------------------
# Fixture builders for the pure span planner — the serialized-trajectory JSON
# shape the planner consumes (mirrors the converter output): tool_calls carry
# tool_call_id/function_name/arguments; observation results carry
# source_call_id/content and an optional subagent_trajectory_ref; subagents are
# flat under subagent_trajectories with a trajectory_id + extra.subagent_type.
# ---------------------------------------------------------------------------


def _step(step_id, *, source="agent", message="", tool_calls=None, results=None,
          metrics=None, model_name=None, reasoning_content=None, timestamp=None):
    step = {"step_id": step_id, "source": source, "message": message}
    if tool_calls is not None:
        step["tool_calls"] = tool_calls
    if results is not None:
        step["observation"] = {"results": results}
    if metrics is not None:
        step["metrics"] = metrics
    if model_name is not None:
        step["model_name"] = model_name
    if reasoning_content is not None:
        step["reasoning_content"] = reasoning_content
    if timestamp is not None:
        step["timestamp"] = timestamp
    return step


def _agent_call(call_id):
    return {"tool_call_id": call_id, "function_name": "Agent", "arguments": "{}"}


def _spawn_result(call_id, child_trajectory_id, content="subagent finished"):
    return {"source_call_id": call_id, "content": content,
            "subagent_trajectory_ref": [{"trajectory_id": child_trajectory_id}]}


def _subagent(trajectory_id, steps, *, subagent_type="explorer"):
    sub = {"trajectory_id": trajectory_id, "steps": steps}
    if subagent_type is not None:
        sub["extra"] = {"subagent_type": subagent_type}
    return sub


def _trace_id():
    return atif_to_opik._mint_uuid7("session::task", 1_700_000_000_000)


class TestPlanSpans(unittest.TestCase):
    def test_depth2_hierarchy_unique_deterministic_ids_and_usage(self):
        # main step spawns subagent A from an Agent tool_call; A's steps become
        # spans parented under the spawning tool span.
        trace_id = _trace_id()
        traj = {
            "steps": [
                _step(1, message="main turn",
                      tool_calls=[_agent_call("spawn-a")],
                      results=[_spawn_result("spawn-a", "sess/agent-a")],
                      metrics={"prompt_tokens": 100, "completion_tokens": 10,
                               "cost_usd": 0.5}),
            ],
            "subagent_trajectories": [
                _subagent("sess/agent-a", [
                    _step(1, message="A step one",
                          metrics={"prompt_tokens": 5, "completion_tokens": 2}),
                ], subagent_type="code-reviewer"),
            ],
        }
        spans = atif_to_opik.plan_spans(traj, trace_id)
        by_id = {s["id"]: s for s in spans}

        # Three spans: top-level step, its tool span, the subagent step span.
        self.assertEqual(len(spans), 3)
        # All span ids unique.
        self.assertEqual(len({s["id"] for s in spans}), 3)

        # Top-level step span: parent_span_id OMITTED entirely.
        top_step = spans[0]
        self.assertNotIn("parent_span_id", top_step)
        self.assertEqual(top_step["name"], "step 1 (agent)")
        self.assertEqual(top_step["type"], "llm")

        # Top-level suffixes are byte-identical to the Cycle One register() suffixes.
        self.assertEqual(top_step["id"], atif_to_opik._span_id(trace_id, "step1"))
        tool_span = spans[1]
        self.assertEqual(tool_span["id"],
                         atif_to_opik._span_id(trace_id, "step1:tool:spawn-a"))
        # Tool span is a child of the step span.
        self.assertEqual(tool_span["parent_span_id"], top_step["id"])
        self.assertEqual(tool_span["type"], "tool")

        # Subagent step span: child of the spawning tool span; suffix qualified by
        # the subagent trajectory_id so it never collides with a top-level suffix.
        sub_step = spans[2]
        self.assertEqual(sub_step["parent_span_id"], tool_span["id"])
        self.assertEqual(sub_step["id"],
                         atif_to_opik._span_id(trace_id, "sess/agent-a:step1"))
        self.assertNotEqual(sub_step["id"], top_step["id"])

        # Per-subagent usage is present (built from its own step metrics).
        self.assertIsNotNone(sub_step["usage"])
        self.assertEqual(sub_step["usage"]["total_tokens"], 7)

        # Deterministic: a second call yields byte-identical ids in the same order.
        again = atif_to_opik.plan_spans(traj, trace_id)
        self.assertEqual([s["id"] for s in spans], [s["id"] for s in again])
        # Identical span planning across the two calls.
        self.assertEqual(by_id.keys(), {s["id"] for s in again})

    def test_no_opik_import_reachable_in_pure_path(self):
        # Boundary proof: exercising the pure planner must NOT pull opik into the
        # process. opik is not installed on the stdlib test path, so a top-level
        # `import opik` in the module would already have failed the import above;
        # this locks it in as an explicit assertion.
        trace_id = _trace_id()
        atif_to_opik.plan_spans({"steps": [_step(1, message="x")]}, trace_id)
        self.assertNotIn("opik", sys.modules)
        self.assertFalse(atif_to_opik.is_local_opik("http://example.com:9000"))
        self.assertNotIn("opik", sys.modules)

    def test_two_subagents_same_step_ids_distinct_trajectories_no_collision(self):
        # Two subagents, each with a per-trajectory step_id of 1; the trajectory_id
        # prefix disambiguates so the two subagent step spans never collide.
        trace_id = _trace_id()
        traj = {
            "steps": [
                _step(1, message="main",
                      tool_calls=[_agent_call("spawn-a"), _agent_call("spawn-b")],
                      results=[_spawn_result("spawn-a", "sess/agent-a"),
                               _spawn_result("spawn-b", "sess/agent-b")]),
            ],
            "subagent_trajectories": [
                _subagent("sess/agent-a", [_step(1, message="A one")]),
                _subagent("sess/agent-b", [_step(1, message="B one")]),
            ],
        }
        spans = atif_to_opik.plan_spans(traj, trace_id)
        ids = [s["id"] for s in spans]
        # All span ids unique despite the colliding per-trajectory step_ids.
        self.assertEqual(len(ids), len(set(ids)))
        a_id = atif_to_opik._span_id(trace_id, "sess/agent-a:step1")
        b_id = atif_to_opik._span_id(trace_id, "sess/agent-b:step1")
        self.assertIn(a_id, ids)
        self.assertIn(b_id, ids)
        self.assertNotEqual(a_id, b_id)

    def test_duplicate_spawning_result_emits_subtree_exactly_once(self):
        # The converter keeps duplicate spawning tool_results and links the ref onto
        # both; the subagent subtree must still be emitted exactly once.
        trace_id = _trace_id()
        traj = {
            "steps": [
                _step(1, message="main", tool_calls=[_agent_call("spawn-a")],
                      results=[
                          _spawn_result("spawn-a", "sess/agent-a", content="first"),
                          _spawn_result("spawn-a", "sess/agent-a", content="second"),
                      ]),
            ],
            "subagent_trajectories": [
                _subagent("sess/agent-a", [_step(1, message="A only")]),
            ],
        }
        spans = atif_to_opik.plan_spans(traj, trace_id)
        sub_id = atif_to_opik._span_id(trace_id, "sess/agent-a:step1")
        self.assertEqual(sum(1 for s in spans if s["id"] == sub_id), 1)
        # main step + its tool span + exactly one subagent step span.
        self.assertEqual(len(spans), 3)

    def test_unlinked_and_dangling_subagent_surfaced_under_root(self):
        # An embedded subagent reached by no ref, plus a dangling ref to a
        # nonexistent trajectory_id. The unlinked subagent is surfaced under the
        # trace root (parent_span_id omitted on its top step); the dangling ref
        # plans nothing extra.
        trace_id = _trace_id()
        traj = {
            "steps": [
                _step(1, message="main", tool_calls=[_agent_call("spawn-x")],
                      results=[_spawn_result("spawn-x", "sess/missing")]),
            ],
            "subagent_trajectories": [
                _subagent("sess/agent-orphan", [_step(1, message="orphan step")]),
            ],
        }
        spans = atif_to_opik.plan_spans(traj, trace_id)
        orphan_id = atif_to_opik._span_id(trace_id, "sess/agent-orphan:step1")
        orphan = next(s for s in spans if s["id"] == orphan_id)
        # Surfaced under the trace root: no parent span.
        self.assertNotIn("parent_span_id", orphan)
        self.assertEqual(orphan["name"], "step 1 (agent)")
        # The dangling ref ("sess/missing") planned no extra span.
        # spans: main step, its tool span, the appended orphan step.
        self.assertEqual(len(spans), 3)

    def test_sparse_subagent_no_keyerror(self):
        # A subagent carrying only trajectory_id + one minimal step (no observation,
        # metrics, model, or extra) is planned without error; usage is None (no metrics).
        trace_id = _trace_id()
        traj = {
            "steps": [
                _step(1, message="main", tool_calls=[_agent_call("spawn-s")],
                      results=[_spawn_result("spawn-s", "sess/agent-sparse")]),
            ],
            "subagent_trajectories": [
                {"trajectory_id": "sess/agent-sparse",
                 "steps": [{"step_id": 1, "source": "agent", "message": "sparse"}]},
            ],
        }
        spans = atif_to_opik.plan_spans(traj, trace_id)
        sparse_id = atif_to_opik._span_id(trace_id, "sess/agent-sparse:step1")
        sparse = next(s for s in spans if s["id"] == sparse_id)
        self.assertIsNone(sparse["usage"])
        self.assertEqual(sparse["name"], "step 1 (agent)")

    def test_null_trajectory_id_subagent_surfaced_not_skipped(self):
        # Defensive symmetry: a subagent with a null trajectory_id is surfaced
        # (not skipped); its lone "None:" span prefix does not collide.
        trace_id = _trace_id()
        traj = {
            "steps": [_step(1, message="main")],
            "subagent_trajectories": [
                {"trajectory_id": None,
                 "steps": [{"step_id": 1, "source": "agent", "message": "nullsub"}]},
            ],
        }
        spans = atif_to_opik.plan_spans(traj, trace_id)
        ids = [s["id"] for s in spans]
        self.assertEqual(len(ids), len(set(ids)))
        null_id = atif_to_opik._span_id(trace_id, "None:step1")
        self.assertIn(null_id, ids)
        null_span = next(s for s in spans if s["id"] == null_id)
        # Surfaced under the trace root (never reached via a ref).
        self.assertNotIn("parent_span_id", null_span)
        self.assertEqual(null_span["name"], "step 1 (agent)")


class TestIsLocalOpik(unittest.TestCase):
    def test_local_hosts_classify_true(self):
        for url in ("localhost", "127.0.0.1", "::1", None, "localhost:5173",
                    "LOCALHOST", "http://[::1]:5173",
                    "http://localhost:5173/api", "http://127.0.0.1:5173"):
            self.assertTrue(atif_to_opik.is_local_opik(url), url)

    def test_remote_and_malformed_classify_false_fail_safe(self):
        # A remote host, plus malformed/unparseable inputs that must fail SAFE
        # (empty/unparseable host -> non-local -> warn), never silently trusted.
        for url in ("http://example.com:9000/api", "remote.host:5173",
                    "http://", "://garbage", "example.com"):
            self.assertFalse(atif_to_opik.is_local_opik(url), url)


class TestOpikHostPort(unittest.TestCase):
    def test_parses_host_and_explicit_port(self):
        self.assertEqual(atif_to_opik._opik_host_port("http://localhost:5173/api"),
                         ("localhost", 5173))
        self.assertEqual(atif_to_opik._opik_host_port("http://127.0.0.1:1/api"),
                         ("127.0.0.1", 1))

    def test_defaults_port_by_scheme(self):
        self.assertEqual(atif_to_opik._opik_host_port("https://opik.example.com/api"),
                         ("opik.example.com", 443))
        self.assertEqual(atif_to_opik._opik_host_port("http://opik.example.com/api"),
                         ("opik.example.com", 80))

    def test_schemeless_host_port(self):
        self.assertEqual(atif_to_opik._opik_host_port("localhost:5173"),
                         ("localhost", 5173))

    def test_unparseable_returns_none(self):
        for url in (None, "", "http://"):
            self.assertIsNone(atif_to_opik._opik_host_port(url), url)


class TestLedgerCorruptRecovers(unittest.TestCase):
    """A corrupt ledger.json is treated as empty (fresh mint + stderr warning),
    NOT a crash. Real corrupt tmp file via DRVR_LEDGER inside an isolated HOME —
    exercises trace_id_for's read path without register (so no opik needed)."""

    def setUp(self):
        self.test_home = tempfile.mkdtemp(prefix="drvr-opik-test-")
        self.ledger = os.path.join(self.test_home, ".driver", "capture", "ledger.json")
        os.makedirs(os.path.dirname(self.ledger), exist_ok=True)
        # Write a corrupt (non-JSON) ledger.
        with open(self.ledger, "w") as f:
            f.write("{ this is not valid json ]")
        self._orig_ledger = atif_to_opik.LEDGER
        self._orig_env = {k: os.environ.get(k) for k in ("HOME", "DRVR_LEDGER")}
        os.environ["HOME"] = self.test_home
        os.environ["DRVR_LEDGER"] = self.ledger
        # The module read LEDGER at import time; point it at the corrupt tmp file.
        atif_to_opik.LEDGER = self.ledger

    def tearDown(self):
        atif_to_opik.LEDGER = self._orig_ledger
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.test_home, ignore_errors=True)

    def test_ledger_corrupt_recovers(self):
        # Should NOT raise — corrupt ledger treated as empty, fresh id minted.
        trace_id, reused = atif_to_opik.trace_id_for(
            atif_to_opik.trace_key("sid", "task"))
        self.assertFalse(reused)
        # A valid UUIDv7-shaped id was minted.
        hexs = trace_id.replace("-", "")
        self.assertEqual(len(hexs), 32)
        self.assertEqual(hexs[12], "7")
        # Ledger was rewritten as valid JSON containing the new key.
        with open(self.ledger) as f:
            ledger = json.load(f)
        self.assertEqual(ledger["sid::task"]["trace_id"], trace_id)


@unittest.skipUnless(
    _OPIK_REACHABLE,
    "opik absent or local Opik server unreachable on OPIK_URL_OVERRIDE")
class TestRegisterAgainstLocalOpik(unittest.TestCase):
    """register() drives the pure plan_spans into a REAL local Opik (no mock).

    Asserts a trace plus step / tool / SUBAGENT spans land, then re-runs register()
    and asserts the deterministic span ids make re-capture an UPSERT (span count
    does not grow). Also exercises the single-complete-message span API on the
    bumped pin: register() calls client.span(**kw) with start_time+end_time
    together (not trace.span() + span.end()).

    Idempotency rides on the ledger, so an isolated HOME + DRVR_LEDGER keep this
    run from minting an id that collides with a developer's real ledger. The trace
    id is the ledger value, so verification queries by it directly.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="capture-opik-register-")
        self.project = "drvr-capture-register-itest"
        self.ledger = os.path.join(self.tmp, "ledger.json")
        self._orig_ledger = atif_to_opik.LEDGER
        self._orig_env = {k: os.environ.get(k) for k in ("HOME", "DRVR_LEDGER")}
        os.environ["HOME"] = self.tmp
        os.environ["DRVR_LEDGER"] = self.ledger
        atif_to_opik.LEDGER = self.ledger

    def tearDown(self):
        atif_to_opik.LEDGER = self._orig_ledger
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _trajectory_with_subagent(self):
        # A realistic trajectory whose main turn spawns a subagent via an Agent
        # tool_call; the spawning observation result carries the
        # subagent_trajectory_ref linking to the flat subagent_trajectories entry
        # (the Plan-01 emitted shape).
        return {
            "schema_version": "ATIF-v1.7",
            "session_id": "opik-register-itest-session",
            "extra": {"sdlc_task_id": "register-itest",
                      "sdlc_spec_id": "S2",
                      "sdlc_intent": "register against a real local Opik"},
            "agent": {"name": "claude-code", "model_name": "claude-opus-4-8"},
            "final_metrics": {"total_steps": 2, "total_completion_tokens": 12,
                              "total_cost_usd": 0.51},
            "steps": [
                _step(1, source="user", message="please review the diff",
                      timestamp="2026-06-29T00:00:00Z"),
                _step(2, source="agent", message="delegating to a reviewer",
                      model_name="claude-opus-4-8",
                      timestamp="2026-06-29T00:00:01Z",
                      tool_calls=[_agent_call("spawn-rev")],
                      results=[_spawn_result("spawn-rev",
                                             "opik-register-itest-session/agent-rev")],
                      metrics={"prompt_tokens": 200, "completion_tokens": 10,
                               "cost_usd": 0.5}),
            ],
            "subagent_trajectories": [
                _subagent("opik-register-itest-session/agent-rev", [
                    _step(1, source="agent", message="reviewed; no issues",
                          model_name="claude-opus-4-8",
                          timestamp="2026-06-29T00:00:02Z",
                          metrics={"prompt_tokens": 40, "completion_tokens": 2,
                                   "cost_usd": 0.01}),
                ], subagent_type="code-reviewer"),
            ],
        }

    def test_register_creates_trace_and_subagent_spans_then_upserts(self):
        import opik

        traj = self._trajectory_with_subagent()
        trace_id, reused = atif_to_opik.register(traj, project=self.project)
        # First capture of this key: a freshly minted (not reused) trace id.
        self.assertFalse(reused, "first register() should mint a new trace id")

        # The pure planner decides exactly which spans exist; the live run must
        # land all of them. plan_spans gives: main step + its tool span + the
        # subagent step span = 3.
        planned = atif_to_opik.plan_spans(traj, trace_id)
        self.assertEqual(len(planned), 3)
        planned_ids = {s["id"] for s in planned}
        subagent_step_id = atif_to_opik._span_id(
            trace_id, "opik-register-itest-session/agent-rev:step1")
        tool_span_id = atif_to_opik._span_id(trace_id, "step2:tool:spawn-rev")
        self.assertIn(subagent_step_id, planned_ids)

        client = opik.Opik(project_name=self.project)

        # The trace exists (single-complete-message create landed name/metadata).
        trace = client.get_trace_content(trace_id)
        self.assertEqual(trace.id, trace_id)

        # Wait for all planned spans to be ingested (eventual consistency), then
        # verify the hierarchy by id.
        spans = client.search_spans(project_name=self.project, trace_id=trace_id,
                                    wait_for_at_least=len(planned))
        got_ids = {s.id for s in spans}
        for sid in planned_ids:
            self.assertIn(sid, got_ids,
                          f"planned span {sid} missing from the live trace")

        by_id = {s.id: s for s in spans}
        # The tool span parents the subagent step span: the subagent is a real
        # nested child, not a sibling.
        self.assertEqual(by_id[subagent_step_id].parent_span_id, tool_span_id,
                         "subagent step span should be a child of the spawning tool span")
        # The single-complete-message create landed name + cost on the subagent span
        # (the racing trace.span()+span.end() pattern would null these out).
        self.assertEqual(by_id[subagent_step_id].name, "step 1 (agent)")
        self.assertIsNotNone(by_id[subagent_step_id].total_estimated_cost)

        baseline = len(got_ids)

        # Re-run: deterministic ids -> UPSERT, not duplication.
        trace_id2, reused2 = atif_to_opik.register(traj, project=self.project)
        self.assertEqual(trace_id2, trace_id, "re-run must reuse the same trace id")
        self.assertTrue(reused2, "second register() should report a reused trace id")

        spans2 = client.search_spans(project_name=self.project, trace_id=trace_id,
                                     wait_for_at_least=len(planned))
        got_ids2 = {s.id for s in spans2}
        self.assertEqual(got_ids2, planned_ids,
                         "re-capture introduced extra spans (ids not deterministic)")
        self.assertEqual(len(got_ids2), baseline,
                         "re-capture duplicated spans instead of upserting")


if __name__ == "__main__":
    unittest.main()
