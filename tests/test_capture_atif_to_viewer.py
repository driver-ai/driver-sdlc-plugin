"""Unit tests for atif_to_viewer's pure cores (scripts/capture/atif_to_viewer.py).

These pin: mutation detection, step mapping (masking routed through the SHARED
redaction core — Contract B — at both scrub sites, with non-str passthrough), and
a deterministic dataset build (time injected, no datetime.now()). Pure functions,
so assertions are on direct return values — no mocks, stdlib only.

The masking-via-Contract-B and time-injected-build_dataset tests are red until
Task 5 consolidates redaction onto redact.redact_text and purifies build_dataset;
detect_mutation / _cap robustness hold in both states.
"""

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


def _step(step_id, *, source="agent", message="", tool_calls=None, results=None):
    """Build a serialized-trajectory step dict (the harbor JSON shape the viewer
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
        traj = {"steps": steps}
        out = atif_to_viewer.flatten_with_subagents(traj)
        self.assertEqual(out, steps)
        self.assertFalse(any(s.get("_boundary") for s in out))

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


if __name__ == "__main__":
    unittest.main()
