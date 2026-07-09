"""Unit tests for atif_to_viewer's pure cores (scripts/capture/atif_to_viewer.py).

These pin: mutation detection, step mapping (masking routed through the SHARED
redaction core — Contract B — at both scrub sites, with non-str passthrough), and
a deterministic dataset build (time injected, no datetime.now()). Pure functions,
so assertions are on direct return values — no mocks, stdlib only.

The masking-via-Contract-B and time-injected-build_dataset tests are red until
Task 5 consolidates redaction onto redact.redact_text and purifies build_dataset;
detect_mutation / _cap robustness hold in both states.
"""

import copy
import json
import sys
import unittest

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import atif_to_viewer

# A typed token from the shared core looks like "[REDACTED:openai_key]" (colon +
# lowercase label). The retired local scrubber emitted "[REDACTED_API_KEY]" /
# "[REDACTED]" (underscore / bare) — so asserting on "[REDACTED:" proves the
# masking goes through Contract B, not a reintroduced local scrubber.
TYPED = "[REDACTED:"
SECRET_A = "sk-abcdefghijklmnopqrstuvwxyz0123"   # openai-shaped (>=20 body)
SECRET_B = "sk-ZYXWVUTSRQPONMLKJIHGFEDCBA9876"   # openai-shaped, distinct


class TestDetectMutation(unittest.TestCase):
    def test_file_edit_and_arg_key_variants(self):
        for key in ("path", "file_path", "filepath"):
            with self.subTest(key=key):
                m = atif_to_viewer.detect_mutation(
                    "write_file", json.dumps({key: "/a/b.py", "content": "x = 1"}))
                self.assertIsNotNone(m)
                self.assertEqual(m["kind"], "file")
                self.assertEqual(m["target"], "/a/b.py")

    def test_git_commit(self):
        m = atif_to_viewer.detect_mutation(
            "git_commit", json.dumps({"repo_path": "/r", "message": "fix the bug"}))
        self.assertEqual(m["kind"], "git")
        self.assertIn("fix the bug", m["summary"])

    def test_write_command(self):
        m = atif_to_viewer.detect_mutation(
            "bash", json.dumps({"command": "rm -rf /tmp/x"}))
        self.assertEqual(m["kind"], "command")
        self.assertIn("rm -rf", m["summary"])

    def test_non_mutating(self):
        self.assertIsNone(atif_to_viewer.detect_mutation(
            "read_file", json.dumps({"path": "/a"})))
        self.assertIsNone(atif_to_viewer.detect_mutation(
            "bash", json.dumps({"command": "ls -la"})))


class TestStepFromAtif(unittest.TestCase):
    def test_role_mapping_producible_sources(self):
        # Only agent/user are produced by cc_to_atif; pin those.
        self.assertEqual(atif_to_viewer.step_from_atif({"source": "agent"}, 0)["role"], "agent")
        self.assertEqual(atif_to_viewer.step_from_atif({"source": "user"}, 1)["role"], "user")

    def test_masks_via_contract_b_at_both_sites(self):
        step = {
            "step_id": 1, "source": "agent",
            "message": f"plain field {SECRET_A}",
            "tool_calls": [{"function_name": "write_file",
                            "arguments": json.dumps({"path": "/a/b.py",
                                                     "content": f"mutation field {SECRET_B}"})}],
        }
        out = atif_to_viewer.step_from_atif(step, 0)
        # Site 1: plain field (_cap) masked via the typed shared core.
        self.assertIn(TYPED, out["text"])
        self.assertNotIn(SECRET_A, out["text"])
        # Site 2: mutation detail field masked via the typed shared core.
        mut = out["mutations"][0]
        self.assertIn(TYPED, mut["detail"])
        self.assertNotIn(SECRET_B, mut["detail"])

    def test_field_cap_40kb(self):
        # Spaced text (short alnum runs) so this exercises the cap, not the shared
        # core's pure-alnum-run backtracking (a Plan-01 perf characteristic — see
        # the implementation log's follow-up note).
        big = "word " * 12_000          # 60 KB, > STEP_FIELD_CAP
        out = atif_to_viewer.step_from_atif({"step_id": 1, "source": "agent", "message": big}, 0)
        self.assertLess(len(out["text"]), 60_000)
        self.assertIn("truncated", out["text"])

    def test_non_str_passthrough(self):
        # A non-str value passes through unchanged (no TypeError) — mirrors the old
        # scrubber's non-str guard.
        self.assertEqual(atif_to_viewer._cap(12345), 12345)
        self.assertIsNone(atif_to_viewer._cap(None))

    def test_step_from_atif_stamps_hierarchy(self):
        # depth/parentIndex/trajId/spanKind are read from the private stamping keys
        # that flatten bakes in; an explicit _spanKind wins over the role rule; the
        # private keys are consumed and NOT re-emitted into the final step dict.
        stamped = {"step_id": 7, "source": "agent", "message": "child",
                   "_depth": 2, "_parentIndex": 3, "_trajId": "sess/agent-a",
                   "_spanKind": "system"}
        out = atif_to_viewer.step_from_atif(stamped, 5)
        self.assertEqual(out["stepId"], 7)
        self.assertEqual(out["depth"], 2)
        self.assertEqual(out["parentIndex"], 3)
        self.assertEqual(out["trajId"], "sess/agent-a")
        self.assertEqual(out["spanKind"], "system")     # explicit _spanKind wins
        for k in ("_depth", "_parentIndex", "_trajId", "_spanKind"):
            self.assertNotIn(k, out)                      # private keys never leak
        # A root step (session_id as trajId, depth 0, no parent) derives spanKind.
        root = {"step_id": 1, "source": "agent", "message": "root",
                "_depth": 0, "_parentIndex": None, "_trajId": "sess-1"}
        rout = atif_to_viewer.step_from_atif(root, 0)
        self.assertEqual(rout["depth"], 0)
        self.assertIsNone(rout["parentIndex"])
        self.assertEqual(rout["trajId"], "sess-1")
        self.assertEqual(rout["spanKind"], "llm")        # agent role -> llm

    def test_step_from_atif_model_and_cached(self):
        step = {"step_id": 1, "source": "agent", "message": "hi",
                "model_name": f"model {SECRET_A}",
                "metrics": {"prompt_tokens": 100, "completion_tokens": 10,
                            "cached_tokens": 42}}
        out = atif_to_viewer.step_from_atif(step, 0)
        # model surfaced and scrubbed via the shared redaction core.
        self.assertIn(TYPED, out["model"])
        self.assertNotIn(SECRET_A, out["model"])
        # tokens.cached surfaced from metrics.cached_tokens.
        self.assertEqual(out["tokens"]["cached"], 42)
        self.assertEqual(out["tokens"]["prompt"], 100)
        # No metrics -> tokens None, model None; None-safe, no crash.
        bare = atif_to_viewer.step_from_atif({"step_id": 2, "source": "user"}, 1)
        self.assertIsNone(bare["tokens"])
        self.assertIsNone(bare["model"])


class TestCurateMetadata(unittest.TestCase):
    def test_curate_metadata_allowlist(self):
        step = {
            "llm_call_count": 3,                          # step-top-level
            "metrics": {
                "cached_tokens": 500,
                "extra": {
                    "service_tier": f"standard {SECRET_A}",
                    "cache_creation_input_tokens": 128,
                    "cache_read_input_tokens": 500,
                    "api_key": SECRET_B,                  # planted secret, NOT allow-listed
                },
            },
        }
        md = atif_to_viewer.curate_metadata(step)
        self.assertEqual(md["llm_call_count"], 3)
        # service_tier read from metrics.extra and scrubbed.
        self.assertIn(TYPED, md["service_tier"])
        self.assertNotIn(SECRET_A, md["service_tier"])
        # cache summary carries only cache_creation_input_tokens (no read-cache dup).
        self.assertEqual(md["cache"], {"cache_creation_input_tokens": 128})
        self.assertNotIn("cache_read_input_tokens", md["cache"])
        # planted secret excluded; cached_tokens NOT duplicated into metadata.
        self.assertNotIn("api_key", md)
        self.assertNotIn(SECRET_B, json.dumps(md))
        self.assertNotIn("cached_tokens", md)
        # None when nothing allow-listed is present.
        self.assertIsNone(atif_to_viewer.curate_metadata({}))
        self.assertIsNone(atif_to_viewer.curate_metadata({"metrics": {"extra": {}}}))


class TestSpanKind(unittest.TestCase):
    def test_span_kind_for(self):
        cases = {"agent": "llm", "tool": "tool", "system": "system",
                 "user": "general", "assistant": "general", "whatever": "general"}
        for role, expected in cases.items():
            with self.subTest(role=role):
                self.assertEqual(atif_to_viewer._span_kind_for(role), expected)


def _step(step_id, *, source="agent", message="", tool_calls=None, results=None):
    """Build a serialized-trajectory step dict (the ATIF JSON shape the viewer
    consumes): tool_calls carry tool_call_id/function_name/arguments; observation
    results carry source_call_id/content and an optional subagent_trajectory_ref."""
    step = {"step_id": step_id, "source": source, "message": message}
    if tool_calls is not None:
        step["tool_calls"] = tool_calls
    if results is not None:
        step["observation"] = {"results": results}
    return step


def _agent_call(call_id):
    return {"tool_call_id": call_id, "function_name": "Agent", "arguments": "{}"}


def _spawn_result(call_id, child_trajectory_id, content="subagent finished"):
    """An observation result whose source_call_id matches the spawning Agent call,
    carrying the ref to the spawned subagent's trajectory_id."""
    return {"source_call_id": call_id, "content": content,
            "subagent_trajectory_ref": [{"trajectory_id": child_trajectory_id}]}


def _subagent(trajectory_id, steps, *, subagent_type="explorer"):
    """A flat subagent entry: trajectory_id + steps + extra.subagent_type (the key
    mirrors normalize_session's extra mapping; absent when subagent_type is None)."""
    sub = {"trajectory_id": trajectory_id, "steps": steps}
    if subagent_type is not None:
        sub["extra"] = {"subagent_type": subagent_type}
    return sub


def _traj_main_spawns_a(session_id="sess-1"):
    """Nested (depth-2) fixture: main step 1 spawns subagent A (two steps); a
    trailing root step follows. Pre-cap flat order (rebuilt flatten):
        0 main one | 1 markerA | 2 A step one | 3 A step two | 4 main two."""
    return {
        "session_id": session_id,
        "steps": [
            _step(1, message="main one", tool_calls=[_agent_call("spawn-a")],
                  results=[_spawn_result("spawn-a", "sess/agent-a")]),
            _step(2, source="user", message="main two"),
        ],
        "subagent_trajectories": [
            _subagent("sess/agent-a", [
                _step(1, message="A step one"),
                _step(2, message="A step two"),
            ], subagent_type="code-reviewer"),
        ],
    }


def _traj_two_subagents(session_id="sess-1"):
    """Two subagents so the cap boundary can land on a marker. Pre-cap flat order:
        0 main one | 1 markerA | 2 A one | 3 A two |
        4 main two | 5 markerB | 6 B one | 7 B two."""
    return {
        "session_id": session_id,
        "steps": [
            _step(1, message="main one", tool_calls=[_agent_call("spawn-a")],
                  results=[_spawn_result("spawn-a", "sess/agent-a")]),
            _step(2, message="main two", tool_calls=[_agent_call("spawn-b")],
                  results=[_spawn_result("spawn-b", "sess/agent-b")]),
        ],
        "subagent_trajectories": [
            _subagent("sess/agent-a", [
                _step(1, message="A one"), _step(2, message="A two")]),
            _subagent("sess/agent-b", [
                _step(1, message="B one"), _step(2, message="B two")]),
        ],
    }


class TestFlattenWithSubagents(unittest.TestCase):
    def test_depth2_splices_subagent_steps_after_spawning_step(self):
        # main step spawns subagent A; A's two steps splice in right after the
        # spawning step, preceded by a single source:"system" boundary marker.
        traj = {
            "steps": [
                _step(1, message="main turn", tool_calls=[_agent_call("spawn-a")],
                      results=[_spawn_result("spawn-a", "sess/agent-a")]),
                _step(2, source="user", message="after"),
            ],
            "subagent_trajectories": [
                _subagent("sess/agent-a", [
                    _step(1, message="A step one"),
                    _step(2, message="A step two"),
                ], subagent_type="code-reviewer"),
            ],
        }
        out = atif_to_viewer.flatten_with_subagents(traj)
        # length == parent steps + all subagent steps + one marker.
        self.assertEqual(len(out), 2 + 2 + 1)
        # Splice lands right after the spawning step (index 0): marker, then A's steps.
        self.assertEqual(out[0]["message"], "main turn")
        self.assertTrue(out[1].get("_boundary"))
        self.assertEqual(out[1]["source"], "system")
        self.assertIn("code-reviewer", out[1]["message"])
        self.assertIn("depth 1", out[1]["message"])
        self.assertEqual(out[2]["message"], "A step one")
        self.assertEqual(out[3]["message"], "A step two")
        # The non-spawning parent step trails the spliced subtree.
        self.assertEqual(out[4]["message"], "after")
        # Exactly one boundary marker for one subagent.
        self.assertEqual(sum(1 for s in out if s.get("_boundary")), 1)

    def test_no_subagents_returns_parent_steps_unchanged(self):
        steps = [_step(1, message="only"), _step(2, source="user", message="reply")]
        traj = {"session_id": "sess-1", "steps": steps}
        out = atif_to_viewer.flatten_with_subagents(traj)
        # flatten now returns stamped SHALLOW COPIES (capture-viewer DEC-016), so
        # the old `out == steps` identity no longer holds — compare on the original
        # keys (subset) and pin the root stamping instead.
        self.assertEqual(len(out), len(steps))
        for orig, got in zip(steps, out):
            for k, v in orig.items():
                self.assertEqual(got[k], v)
            self.assertEqual(got["_depth"], 0)          # root steps
            self.assertIsNone(got["_parentIndex"])
            self.assertEqual(got["_trajId"], "sess-1")  # root joins the graph root node
        self.assertFalse(any(s.get("_boundary") for s in out))
        # Input list objects are untouched (stamping landed on copies, not input).
        for s in steps:
            for k in ("_depth", "_parentIndex", "_trajId", "_spanKind"):
                self.assertNotIn(k, s)

    def test_depth3_grandchild_splices_under_its_parent_in_tool_calls_order(self):
        # main -> A -> B. A spawns B from within A's step; B's step must splice
        # under A (depth 2), after A's spawning step, in tool_calls order.
        traj = {
            "steps": [
                _step(1, message="main", tool_calls=[_agent_call("spawn-a")],
                      results=[_spawn_result("spawn-a", "sess/agent-a")]),
            ],
            "subagent_trajectories": [
                _subagent("sess/agent-a", [
                    _step(1, message="A turn", tool_calls=[_agent_call("spawn-b")],
                          results=[_spawn_result("spawn-b", "sess/agent-b")]),
                ]),
                _subagent("sess/agent-b", [
                    _step(1, message="B turn"),
                ]),
            ],
        }
        out = atif_to_viewer.flatten_with_subagents(traj)
        msgs = [s["message"] for s in out]
        # Order: main, marker(A depth1), A turn, marker(B depth2), B turn.
        self.assertEqual(msgs[0], "main")
        self.assertTrue(out[1].get("_boundary"))
        self.assertIn("depth 1", out[1]["message"])
        self.assertEqual(msgs[2], "A turn")
        self.assertTrue(out[3].get("_boundary"))
        self.assertIn("depth 2", out[3]["message"])
        self.assertEqual(msgs[4], "B turn")
        self.assertEqual(len(out), 2 + 1 + 1 + 1)  # main+A+B steps + 2 markers

    def test_duplicate_spawning_result_splices_subtree_exactly_once(self):
        # The converter keeps duplicate spawning tool_results and links the ref onto
        # both; the subagent subtree must still appear exactly once.
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
        out = atif_to_viewer.flatten_with_subagents(traj)
        self.assertEqual(sum(1 for s in out if s.get("message") == "A only"), 1)
        self.assertEqual(sum(1 for s in out if s.get("_boundary")), 1)

    def test_unlinked_subagent_surfaced_under_root_with_unlinked_marker(self):
        # An embedded subagent with no incoming ref, plus a dangling ref to a
        # nonexistent trajectory_id. The unlinked subagent is appended under the
        # root at depth 1 with an "(unlinked)" note; the dangling ref splices nothing.
        traj = {
            "steps": [
                _step(1, message="main", tool_calls=[_agent_call("spawn-x")],
                      results=[_spawn_result("spawn-x", "sess/missing")]),
            ],
            "subagent_trajectories": [
                _subagent("sess/agent-orphan", [_step(1, message="orphan step")]),
            ],
        }
        out = atif_to_viewer.flatten_with_subagents(traj)
        msgs = [s["message"] for s in out]
        self.assertIn("orphan step", msgs)
        # The orphan is surfaced via an unlinked marker at depth 1.
        markers = [s for s in out if s.get("_boundary")]
        self.assertEqual(len(markers), 1)
        self.assertIn("unlinked", markers[0]["message"])
        self.assertIn("depth 1", markers[0]["message"])
        # The dangling ref ("sess/missing") spliced nothing extra.
        self.assertEqual(len(out), 1 + 1 + 1)  # main + marker + orphan step

    def test_sparse_subagent_no_keyerror_marker_defaults_to_agent(self):
        # A subagent carrying only trajectory_id + one minimal step (no observation,
        # metrics, or extra) flattens without error; the marker type defaults to "agent".
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
        out = atif_to_viewer.flatten_with_subagents(traj)
        markers = [s for s in out if s.get("_boundary")]
        self.assertEqual(len(markers), 1)
        self.assertIn("agent", markers[0]["message"])
        self.assertEqual(out[-1]["message"], "sparse")

    def test_flatten_global_parent_index(self):
        # The Driver-flagged trap: parentIndex must be the parent's GLOBAL index in
        # the flat list and point at the SEMANTIC parent (identity, not merely
        # in-range) — marker.parent == spawning step; subagent step.parent == its
        # marker; child.depth == parent.depth + 1 throughout. capture-viewer DEC-016.
        out = atif_to_viewer.flatten_with_subagents(_traj_main_spawns_a())
        idx = {s.get("message"): i for i, s in enumerate(out) if not s.get("_boundary")}
        marker_i = next(i for i, s in enumerate(out) if s.get("_boundary"))
        # marker.parent == the spawning root step (global index identity).
        self.assertEqual(out[marker_i]["_parentIndex"], idx["main one"])
        # each subagent step.parent == its marker.
        self.assertEqual(out[idx["A step one"]]["_parentIndex"], marker_i)
        self.assertEqual(out[idx["A step two"]]["_parentIndex"], marker_i)
        # root steps have no parent and depth 0.
        for msg in ("main one", "main two"):
            self.assertIsNone(out[idx[msg]]["_parentIndex"])
            self.assertEqual(out[idx[msg]]["_depth"], 0)
        # child.depth == parent.depth + 1 for every non-root step (semantic chain).
        for i, s in enumerate(out):
            p = s.get("_parentIndex")
            if p is not None:
                self.assertEqual(s["_depth"], out[p]["_depth"] + 1)

    def test_flatten_parent_index_valid_after_cap(self):
        # Apply the cap the way the callers do — slice + pop trailing markers INLINE
        # — NOT by monkeypatching atif_to_viewer.MAX_STEPS (flatten never reads it,
        # and capture_viewer_core binds MAX_STEPS by value at import, so the patch is
        # inert). The two-subagent fixture puts marker B at index 5; capping at 6
        # forces a trailing-marker pop. capture-viewer DEC-016.
        flat = atif_to_viewer.flatten_with_subagents(_traj_two_subagents())
        n = 6
        self.assertTrue(flat[n - 1].get("_boundary"))     # premise: cap lands on a marker
        capped = flat[:n]
        while capped and capped[-1].get("_boundary"):     # caller's trailing-marker pop
            capped.pop()
        self.assertFalse(capped[-1].get("_boundary"))     # the trailing marker was popped
        # Every kept step's parentIndex points inside the capped+popped list; no ref
        # lands on the popped trailing marker.
        for s in capped:
            self.assertIn("_parentIndex", s)
            p = s["_parentIndex"]
            if p is not None:
                self.assertTrue(0 <= p < len(capped))
                self.assertEqual(s["_depth"], capped[p]["_depth"] + 1)

    def test_flatten_does_not_mutate_input(self):
        # flatten stamps onto SHALLOW COPIES — the input trajectory is immutable
        # (dry-run #9 / capture-viewer DEC-016).
        traj = _traj_two_subagents()
        snapshot = copy.deepcopy(traj)
        out = atif_to_viewer.flatten_with_subagents(traj)
        # The OUTPUT is stamped (proves flatten did the enrichment work)...
        self.assertTrue(all("_parentIndex" in s for s in out))
        # ...while the INPUT trajectory is byte-for-byte unchanged.
        self.assertEqual(traj, snapshot)
        for s in traj["steps"]:
            for k in ("_depth", "_parentIndex", "_trajId", "_spanKind"):
                self.assertNotIn(k, s)
        for sub in traj["subagent_trajectories"]:
            for s in sub["steps"]:
                for k in ("_depth", "_parentIndex", "_trajId", "_spanKind"):
                    self.assertNotIn(k, s)

    def test_flatten_boundary_marker_spankind_system(self):
        # Synthetic boundary markers are stamped _spanKind="system" and keep the
        # parent chain intact (marker.parent == spawning step).
        out = atif_to_viewer.flatten_with_subagents(_traj_main_spawns_a())
        marker = next(s for s in out if s.get("_boundary"))
        self.assertEqual(marker["_spanKind"], "system")
        self.assertEqual(atif_to_viewer.step_from_atif(marker, 1)["spanKind"], "system")
        self.assertEqual(marker["_parentIndex"], 0)       # spawning root step index
        # Non-marker steps carry no _spanKind (derived from role in step_from_atif).
        self.assertNotIn("_spanKind", out[0])


class TestSubagentMarkerLabel(unittest.TestCase):
    """Boundary-marker labels read the converter-filled agent.name first, falling
    back to extra.subagent_type so pre-swap artifacts keep rendering."""

    def test_marker_reads_agent_name_with_extra_fallback(self):
        traj = {
            "steps": [],
            "subagent_trajectories": [
                {"trajectory_id": "s/a", "agent": {"name": "code-reviewer"},
                 "steps": [_step(1, message="a")]},
                {"trajectory_id": "s/b", "agent": {"name": "from-agent"},
                 "extra": {"subagent_type": "from-extra"},
                 "steps": [_step(1, message="b")]},
                {"trajectory_id": "s/c", "extra": {"subagent_type": "explorer"},
                 "steps": [_step(1, message="c")]},
            ],
        }
        out = atif_to_viewer.flatten_with_subagents(traj)
        markers = [s["message"] for s in out if s.get("_boundary")]
        self.assertEqual(len(markers), 3)
        # agent.name is the label.
        self.assertIn("subagent code-reviewer", markers[0])
        # agent.name wins when both are present.
        self.assertIn("subagent from-agent", markers[1])
        self.assertNotIn("from-extra", markers[1])
        # Pre-swap artifact (extra.subagent_type only) keeps its label.
        self.assertIn("subagent explorer", markers[2])


class TestBuildAgentGraph(unittest.TestCase):
    """The pure, deterministic subagent-spawn DAG synthesized from the traj
    (capture-viewer DEC-023): root node id == session_id (so a root step's trajId
    joins it), one node per subagent by trajectory_id, one edge per spawn in
    tool_calls order, unlinked subagents parented under root."""

    def test_build_agent_graph_from_refs(self):
        # Root node: id == session_id, kind "root", label from agent.name or "main".
        g = atif_to_viewer.build_agent_graph(_traj_main_spawns_a(session_id="sess-1"))
        self.assertEqual(g["nodes"][0], {"id": "sess-1", "label": "main", "kind": "root"})
        self.assertEqual(g["nodes"][0]["id"], "sess-1")        # root id == session_id
        # One subagent node keyed by trajectory_id + a single spawn edge root -> A.
        self.assertEqual(g["nodes"][1],
                         {"id": "sess/agent-a", "trajId": "sess/agent-a",
                          "kind": "subagent", "label": "code-reviewer"})
        self.assertEqual(g["edges"], [{"from": "sess-1", "to": "sess/agent-a"}])

        # Linked subagents: edges are spawn links IN TOOL_CALLS ORDER (A before B).
        g2 = atif_to_viewer.build_agent_graph(_traj_two_subagents(session_id="sess-1"))
        self.assertEqual([n["id"] for n in g2["nodes"]],
                         ["sess-1", "sess/agent-a", "sess/agent-b"])
        self.assertEqual(g2["nodes"][0]["kind"], "root")
        self.assertEqual(g2["edges"],
                         [{"from": "sess-1", "to": "sess/agent-a"},
                          {"from": "sess-1", "to": "sess/agent-b"}])

        # Grandchild spawn (main -> A, A -> B) yields edge A -> B, not root -> B.
        nested = {
            "session_id": "sess-1",
            "steps": [_step(1, message="main", tool_calls=[_agent_call("spawn-a")],
                            results=[_spawn_result("spawn-a", "sess/agent-a")])],
            "subagent_trajectories": [
                _subagent("sess/agent-a", [
                    _step(1, message="A", tool_calls=[_agent_call("spawn-b")],
                          results=[_spawn_result("spawn-b", "sess/agent-b")])]),
                _subagent("sess/agent-b", [_step(1, message="B")]),
            ],
        }
        g3 = atif_to_viewer.build_agent_graph(nested)
        self.assertEqual(g3["edges"],
                         [{"from": "sess-1", "to": "sess/agent-a"},
                          {"from": "sess/agent-a", "to": "sess/agent-b"}])

        # Unlinked subagent (dangling ref to a nonexistent id) hangs off root.
        unlinked = {
            "session_id": "sess-1",
            "steps": [_step(1, message="main", tool_calls=[_agent_call("spawn-x")],
                            results=[_spawn_result("spawn-x", "sess/missing")])],
            "subagent_trajectories": [_subagent("sess/agent-orphan", [_step(1)])],
        }
        g4 = atif_to_viewer.build_agent_graph(unlinked)
        self.assertEqual(g4["edges"], [{"from": "sess-1", "to": "sess/agent-orphan"}])

        # No subagents -> empty graph (both a real traj and an empty dict).
        self.assertEqual(
            atif_to_viewer.build_agent_graph({"session_id": "s", "steps": [_step(1)]}),
            {"nodes": [], "edges": []})
        self.assertEqual(atif_to_viewer.build_agent_graph({}), {"nodes": [], "edges": []})

        # session_id fallback: root id is "root" when session_id is absent (the same
        # `session_id or "root"` fallback flatten uses -- capture-viewer DEC-022).
        g5 = atif_to_viewer.build_agent_graph(
            {"steps": [], "subagent_trajectories": [_subagent("s/a", [_step(1)])]})
        self.assertEqual(g5["nodes"][0]["id"], "root")
        self.assertEqual(g5["edges"], [{"from": "root", "to": "s/a"}])

        # Deterministic: same input -> byte-equal graph across runs (no clock/random).
        self.assertEqual(
            atif_to_viewer.build_agent_graph(_traj_two_subagents()),
            atif_to_viewer.build_agent_graph(_traj_two_subagents()))


class TestListContentFlatten(unittest.TestCase):
    """list[ContentPart] messages/observations flatten to display text via the
    shared flatten_content — and the flatten runs BEFORE _cap/_scrub, so the
    defense-in-depth re-scrub always sees a string."""

    def test_step_from_atif_flattens_list_message_before_scrub(self):
        step = {
            "step_id": 1, "source": "agent",
            "message": [
                {"type": "text", "text": f"pasted {SECRET_A}"},
                {"type": "image",
                 "source": {"media_type": "image/png", "path": "/tmp/shot.png"}},
            ],
        }
        out = atif_to_viewer.step_from_atif(step, 0)
        self.assertIsInstance(out["text"], str)
        self.assertIn("[image: image/png /tmp/shot.png]", out["text"])
        # Flatten-before-scrub: a secret inside a text part is still masked. If
        # the scrub ran first it would pass the list through untouched and the
        # raw secret would survive the flatten.
        self.assertIn(TYPED, out["text"])
        self.assertNotIn(SECRET_A, out["text"])
        # No Python list-repr of ContentPart dicts.
        self.assertNotIn("{'type'", out["text"])

    def test_observation_list_content_flattened(self):
        step = {
            "step_id": 1, "source": "agent", "message": "did a thing",
            "observation": {"results": [
                {"source_call_id": "c1",
                 "content": [
                     {"type": "text", "text": "tool said hi"},
                     {"type": "image",
                      "source": {"media_type": "image/jpeg", "path": "/tmp/o.jpg"}},
                 ]},
                {"source_call_id": "c2", "content": "plain str result"},
            ]},
        }
        out = atif_to_viewer.step_from_atif(step, 0)
        self.assertIn("tool said hi", out["observation"])
        self.assertIn("[image: image/jpeg /tmp/o.jpg]", out["observation"])
        self.assertIn("plain str result", out["observation"])  # str content joined as today
        self.assertNotIn("{'type'", out["observation"])

    def test_str_message_and_observation_render_as_today(self):
        # Backward compat: a pre-swap artifact (plain str content) is untouched.
        step = {
            "step_id": 1, "source": "agent", "message": "plain message",
            "observation": {"results": [
                {"source_call_id": "c1", "content": "plain result"}]},
        }
        out = atif_to_viewer.step_from_atif(step, 0)
        self.assertEqual(out["text"], "plain message")
        self.assertEqual(out["observation"], "plain result")


class TestBuildDataset(unittest.TestCase):
    def _traj(self):
        return {
            "session_id": "sess-1",
            "agent": {"model_name": "claude"},
            "extra": {"sdlc_task_id": "T1", "sdlc_spec_id": "S1", "sdlc_intent": "do it"},
            "final_metrics": {"total_prompt_tokens": 300, "total_completion_tokens": 40,
                              "total_cached_tokens": 75, "total_cost_usd": 1.23},
            "steps": [
                {"step_id": 1, "source": "agent", "message": "hi",
                 "metrics": {"prompt_tokens": 100, "completion_tokens": 10}},
                {"step_id": 2, "source": "user", "message": "yo"},
            ],
        }

    def test_build_dataset_injected_time(self):
        gen = "2020-01-01T00:00:00Z"
        dataset, rid, tid, steps = atif_to_viewer.build_dataset(
            self._traj(), task_id="T1", spec_id="S1", intent="do it", generated_at=gen)
        # Time is injected, not wall-clock.
        self.assertEqual(dataset["generatedAt"], gen)
        # Deterministic ids/slugs and token rollup given the same inputs.
        dataset2, rid2, tid2, _ = atif_to_viewer.build_dataset(
            self._traj(), task_id="T1", spec_id="S1", intent="do it", generated_at=gen)
        self.assertEqual((rid, tid), (rid2, tid2))
        self.assertEqual(dataset["runs"][0]["tokens"]["completion"], 40)
        self.assertEqual(dataset["runs"][0]["tokens"]["prompt"], 300)
        self.assertEqual(len(steps), 2)

    def test_build_dataset_run_carries_agent_graph(self):
        # The CLI run carries agentGraph (parity with the /runs payload); a
        # subagent-free traj gets the empty graph.
        dataset, *_ = atif_to_viewer.build_dataset(
            self._traj(), task_id="T1", spec_id="S1", intent="",
            generated_at="2020-01-01T00:00:00Z")
        self.assertEqual(dataset["runs"][0]["agentGraph"], {"nodes": [], "edges": []})

        # A subagent traj -> populated graph (root node id == session_id, one spawn edge).
        dataset2, *_ = atif_to_viewer.build_dataset(
            _traj_main_spawns_a(session_id="sess-1"), task_id="T", spec_id="S",
            intent="", generated_at="2020-01-01T00:00:00Z")
        graph = dataset2["runs"][0]["agentGraph"]
        self.assertEqual(graph["nodes"][0]["id"], "sess-1")
        self.assertEqual(graph["nodes"][0]["kind"], "root")
        self.assertEqual(graph["edges"], [{"from": "sess-1", "to": "sess/agent-a"}])
        # Parity: the run's graph equals the pure builder's output for the same traj.
        self.assertEqual(graph, atif_to_viewer.build_agent_graph(
            _traj_main_spawns_a(session_id="sess-1")))


class TestViewerDefaults(unittest.TestCase):
    """The launch defaults are the plugin's viewer provenance: the driver-ai
    fork, pinned to an immutable merged SHA (capture-viewer DEC-010)."""

    def test_default_repo_is_the_driver_ai_fork(self):
        self.assertEqual(atif_to_viewer.DEFAULT_REPO,
                         "https://github.com/driver-ai/ATIF-trajectory-viewer")

    def test_default_pin_is_a_full_sha(self):
        # A 40-char hex SHA is immutable; a branch name or short ref is not.
        self.assertRegex(atif_to_viewer.DEFAULT_PIN, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
