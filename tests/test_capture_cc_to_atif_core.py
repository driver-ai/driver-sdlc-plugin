"""Unit tests for the harbor-free `normalize` kernel (cc_to_atif_core).

Pure-core tests: import `cc_to_atif_core` ONLY (its `import pricing` resolves off
the inserted path). No harbor, no mocks. Stdlib `unittest` only.
"""
import sys
import unittest

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import cc_to_atif_core as core   # its `import pricing` resolves off the inserted path


# ---------------------------------------------------------------------------
# Tiny record-fixture builders (inline JSONL-record dicts)
# ---------------------------------------------------------------------------

USAGE = {
    "input_tokens": 100,
    "cache_creation_input_tokens": 10,
    "cache_read_input_tokens": 20,
    "output_tokens": 50,
}


def asst(content, *, msg_id=None, model="claude-opus-4-8-20260315", usage=None,
         session_id="sess", ts="2026-06-25T00:00:00Z", sidechain=False):
    msg = {"content": content}
    if msg_id is not None:
        msg["id"] = msg_id
    if model is not None:
        msg["model"] = model
    if usage is not None:
        msg["usage"] = usage
    return {"type": "assistant", "isSidechain": sidechain, "sessionId": session_id,
            "timestamp": ts, "message": msg}


def user(content, *, session_id="sess", ts="2026-06-25T00:00:00Z", sidechain=False):
    return {"type": "user", "isSidechain": sidechain, "sessionId": session_id,
            "timestamp": ts, "message": {"content": content}}


def text_block(s):
    return {"type": "text", "text": s}


def tool_use_block(call_id, name="Bash", inp=None):
    return {"type": "tool_use", "id": call_id, "name": name, "input": inp or {}}


def tool_result_block(call_id, content, is_error=False):
    b = {"type": "tool_result", "tool_use_id": call_id, "content": content}
    if is_error:
        b["is_error"] = True
    return b


def normalize(records, **kw):
    kw.setdefault("session_id", "sess")
    kw.setdefault("task_id", None)
    kw.setdefault("spec_id", None)
    kw.setdefault("intent", None)
    kw.setdefault("exclude_session_id", None)
    return core.normalize(records, **kw)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMessageIdGrouping(unittest.TestCase):
    def test_normalize_message_id_grouping(self):
        # Several assistant records sharing one message.id, REPEATING usage.
        recs = [
            asst([text_block("first block")], msg_id="m1", usage=USAGE),
            asst([{"type": "thinking", "thinking": "reasoning"}], msg_id="m1", usage=USAGE),
            asst([tool_use_block("c1")], msg_id="m1", usage=USAGE),
        ]
        n = normalize(recs)
        # ONE step.
        self.assertEqual(len(n.steps), 1)
        step = n.steps[0]
        self.assertEqual(step.source, "agent")
        self.assertIn("first block", step.message)
        self.assertEqual(step.reasoning_content, "reasoning")
        self.assertEqual(len(step.tool_calls), 1)
        # Usage counted ONCE — not 3x.
        self.assertEqual(step.metrics["prompt_tokens"], 100 + 10 + 20)
        self.assertEqual(step.metrics["completion_tokens"], 50)
        self.assertEqual(n.final_metrics["total_prompt_tokens"], 130)
        self.assertEqual(n.final_metrics["total_completion_tokens"], 50)


class TestUsageOnLaterRecord(unittest.TestCase):
    def test_normalize_usage_on_later_record_of_group(self):
        # First record of the same-id group lacks usage; a LATER one carries it (H6).
        recs = [
            asst([text_block("a")], msg_id="m1", usage=None),
            asst([tool_use_block("c1")], msg_id="m1", usage=USAGE),
        ]
        n = normalize(recs)
        self.assertEqual(len(n.steps), 1)
        step = n.steps[0]
        self.assertIsNotNone(step.metrics)
        self.assertEqual(step.metrics["prompt_tokens"], 130)
        self.assertEqual(step.metrics["completion_tokens"], 50)
        # Counted once.
        self.assertEqual(n.final_metrics["total_prompt_tokens"], 130)


class TestNoMessageId(unittest.TestCase):
    def test_normalize_no_message_id(self):
        # Two consecutive assistant records, BOTH lacking message.id → NOT merged (L3).
        recs = [
            asst([text_block("a")], msg_id=None, usage=USAGE),
            asst([text_block("b")], msg_id=None, usage=USAGE),
        ]
        n = normalize(recs)
        self.assertEqual(len(n.steps), 2)
        # Each counted.
        self.assertEqual(n.final_metrics["total_prompt_tokens"], 260)
        self.assertEqual(n.final_metrics["total_completion_tokens"], 100)


class TestToolResultFolding(unittest.TestCase):
    def test_normalize_tool_result_folding(self):
        recs = [
            asst([tool_use_block("c1")], msg_id="m1", usage=USAGE),
            user([tool_result_block("c1", "result text")]),
            # Orphan result: no matching tool_use → dropped.
            user([tool_result_block("c-orphan", "orphan text")]),
        ]
        n = normalize(recs)
        # Folded result does NOT create a new step.
        self.assertEqual(len(n.steps), 1)
        step = n.steps[0]
        self.assertEqual(len(step.observation_results), 1)
        obs = step.observation_results[0]
        self.assertEqual(obs["source_call_id"], "c1")
        self.assertEqual(obs["content"], "result text")


class TestDuplicateToolResult(unittest.TestCase):
    def test_normalize_duplicate_tool_result(self):
        # Two results with the SAME tool_use_id both fold in (M11 — keep both).
        recs = [
            asst([tool_use_block("c1")], msg_id="m1", usage=USAGE),
            user([tool_result_block("c1", "first")]),
            user([tool_result_block("c1", "second")]),
        ]
        n = normalize(recs)
        self.assertEqual(len(n.steps), 1)
        step = n.steps[0]
        self.assertEqual(len(step.observation_results), 2)
        self.assertEqual({o["source_call_id"] for o in step.observation_results}, {"c1"})
        self.assertEqual({o["content"] for o in step.observation_results}, {"first", "second"})


class TestUnansweredToolCall(unittest.TestCase):
    def test_normalize_unanswered_tool_call(self):
        # tool_use with no matching result (L4): keep the tool_call, observation empty.
        recs = [asst([tool_use_block("c1")], msg_id="m1", usage=USAGE)]
        n = normalize(recs)
        self.assertEqual(len(n.steps), 1)
        step = n.steps[0]
        self.assertEqual(len(step.tool_calls), 1)
        self.assertEqual(step.observation_results, [])


class TestToolResultImageContent(unittest.TestCase):
    def test_normalize_tool_result_image_content(self):
        # tool_result content is an image/array block → [image] placeholder (M8).
        img = [{"type": "image", "source": {"data": "..."}}]
        recs = [
            asst([tool_use_block("c1")], msg_id="m1", usage=USAGE),
            user([tool_result_block("c1", img)]),
        ]
        n = normalize(recs)
        step = n.steps[0]
        self.assertEqual(len(step.observation_results), 1)
        self.assertEqual(step.observation_results[0]["content"], "[image]")


class TestHumanTurn(unittest.TestCase):
    def test_normalize_human_turn(self):
        recs = [user([text_block("hello there")])]
        n = normalize(recs)
        self.assertEqual(len(n.steps), 1)
        step = n.steps[0]
        self.assertEqual(step.source, "user")
        self.assertEqual(step.message, "hello there")


class TestSkipsNewerRecordTypes(unittest.TestCase):
    def test_normalize_skips_newer_record_types(self):
        newer_types = ["mode", "last-prompt", "ai-title", "attachment",
                       "file-history-snapshot", "queue-operation"]
        # Interleave a newer-type record between a tool_use and its tool_result (M13).
        recs = [asst([tool_use_block("c1")], msg_id="m1", usage=USAGE)]
        for t in newer_types:
            recs.append({"type": t, "isSidechain": False, "sessionId": "sess",
                         "timestamp": "2026-06-25T00:00:00Z", "message": {}})
        recs.append(user([tool_result_block("c1", "still folds")]))
        n = normalize(recs)
        # Only the agent step survives; the fold still lands.
        self.assertEqual(len(n.steps), 1)
        step = n.steps[0]
        self.assertEqual(len(step.observation_results), 1)
        self.assertEqual(step.observation_results[0]["content"], "still folds")


class TestUnpricedModel(unittest.TestCase):
    def test_normalize_unpriced_model(self):
        # Model absent from the pricing table → extra["unpriced_models"] has its name.
        recs = [asst([text_block("hi")], msg_id="m1",
                     model="some-future-model-9000", usage=USAGE)]
        n = normalize(recs)
        self.assertIn("unpriced_models", n.extra)
        self.assertIn("some-future-model-9000", n.extra["unpriced_models"])

    def test_normalize_priced_session_omits_key(self):
        recs = [asst([text_block("hi")], msg_id="m1",
                     model="claude-opus-4-8-20260315", usage=USAGE)]
        n = normalize(recs)
        self.assertNotIn("unpriced_models", n.extra)


class TestExcludeMarker(unittest.TestCase):
    MARKER = "/drvr:capture-session"

    def test_truncates_at_last_matching_command_turn(self):
        recs = [
            user([text_block("real human turn one")]),
            asst([text_block("agent reply")], msg_id="m1", usage=USAGE),
            user([text_block(self.MARKER + " arg")]),  # the capture invocation
            asst([text_block("should be dropped")], msg_id="m2", usage=USAGE),
        ]
        n = normalize(recs, exclude_marker=self.MARKER)
        # Cut at the marker turn → only the first two steps survive.
        self.assertEqual(len(n.steps), 2)
        self.assertEqual(n.steps[0].source, "user")
        self.assertEqual(n.steps[0].message, "real human turn one")
        self.assertEqual(n.steps[1].source, "agent")

    def test_last_matching_turn_when_multiple(self):
        recs = [
            user([text_block(self.MARKER)]),                # earlier invocation
            asst([text_block("mid")], msg_id="m1", usage=USAGE),
            user([text_block(self.MARKER)]),                # LAST invocation = cut point
            asst([text_block("dropped")], msg_id="m2", usage=USAGE),
        ]
        n = normalize(recs, exclude_marker=self.MARKER)
        # Cut at the LAST marker turn → records[0:2] remain → one user + one agent.
        self.assertEqual(len(n.steps), 2)
        self.assertEqual(n.steps[0].source, "user")
        self.assertEqual(n.steps[1].source, "agent")

    def test_prose_mention_does_not_truncate(self):
        recs = [
            user([text_block("I want to run " + self.MARKER + " later")]),
            asst([text_block("ok")], msg_id="m1", usage=USAGE),
        ]
        n = normalize(recs, exclude_marker=self.MARKER)
        # Prose mention (not the first command token) does NOT cut.
        self.assertEqual(len(n.steps), 2)

    def test_marker_inside_assistant_or_tool_result_does_not_truncate(self):
        recs = [
            user([text_block("human turn")]),
            asst([text_block("here is the " + self.MARKER + " command")],
                 msg_id="m1", usage=USAGE),
            asst([tool_use_block("c1")], msg_id="m2", usage=USAGE),
            user([tool_result_block("c1", self.MARKER + " inside a result")]),
        ]
        n = normalize(recs, exclude_marker=self.MARKER)
        # Marker only inside assistant/tool_result → no truncation; both agent steps stay.
        self.assertEqual(len(n.steps), 3)
        sources = [s.source for s in n.steps]
        self.assertEqual(sources, ["user", "agent", "agent"])

    def test_longer_command_does_not_truncate(self):
        # A LONGER command token must NOT match (whole-token equality, not startswith).
        recs = [
            user([text_block(self.MARKER + "-foo bar")]),
            asst([text_block("kept")], msg_id="m1", usage=USAGE),
        ]
        n = normalize(recs, exclude_marker=self.MARKER)
        self.assertEqual(len(n.steps), 2)
        self.assertEqual(n.steps[0].message, self.MARKER + "-foo bar")

    def test_marker_at_record_zero_raises(self):
        recs = [
            user([text_block(self.MARKER)]),
            asst([text_block("after")], msg_id="m1", usage=USAGE),
        ]
        with self.assertRaises(core.EmptyTranscriptError):
            normalize(recs, exclude_marker=self.MARKER)


class TestExcludeSessionEmpties(unittest.TestCase):
    def test_normalize_exclude_session_empties(self):
        # Every record carries the excluded sessionId → all skipped (M10).
        recs = [
            asst([text_block("a")], msg_id="m1", usage=USAGE, session_id="capsess"),
            user([text_block("b")], session_id="capsess"),
        ]
        with self.assertRaises(core.EmptyTranscriptError):
            normalize(recs, exclude_session_id="capsess")


class TestEmptyRaisesDomainError(unittest.TestCase):
    def test_no_records(self):
        with self.assertRaises(core.EmptyTranscriptError):
            normalize([])

    def test_sidechain_only(self):
        recs = [
            asst([text_block("sub")], msg_id="m1", usage=USAGE, sidechain=True),
            user([text_block("sub user")], sidechain=True),
        ]
        with self.assertRaises(core.EmptyTranscriptError):
            normalize(recs)

    def test_is_value_error_not_systemexit(self):
        # Domain error subclasses ValueError, NOT SystemExit.
        self.assertTrue(issubclass(core.EmptyTranscriptError, ValueError))
        with self.assertRaises(ValueError):
            normalize([])


class TestFinalMetricsTotals(unittest.TestCase):
    def test_normalize_final_metrics_totals(self):
        recs = [
            asst([text_block("a")], msg_id="m1", usage=USAGE),
            user([text_block("human")]),
            asst([text_block("b")], msg_id="m2", usage=USAGE),
        ]
        n = normalize(recs)
        # final_metrics totals == sum of per-step metrics.
        exp_prompt = sum((s.metrics or {}).get("prompt_tokens", 0) for s in n.steps)
        exp_compl = sum((s.metrics or {}).get("completion_tokens", 0) for s in n.steps)
        exp_cached = sum((s.metrics or {}).get("cached_tokens", 0) for s in n.steps)
        exp_cost = round(sum((s.metrics or {}).get("cost_usd", 0.0) for s in n.steps), 6)
        self.assertEqual(n.final_metrics["total_prompt_tokens"], exp_prompt)
        self.assertEqual(n.final_metrics["total_completion_tokens"], exp_compl)
        self.assertEqual(n.final_metrics["total_cached_tokens"], exp_cached)
        self.assertEqual(n.final_metrics["total_cost_usd"], exp_cost)
        self.assertEqual(n.final_metrics["total_steps"], len(n.steps))


# ---------------------------------------------------------------------------
# Subagent representation: skip_sidechain gate + normalize_session + linker + rollup
# ---------------------------------------------------------------------------
#
# Subagent records on disk are all isSidechain:true and carry their own sessionId.
# Spawning calls in the parent (or another subagent) are tool_use blocks named
# "Agent". Meta sidecars come in three shapes, all exercised below:
#   {agentType, description, toolUseId}              (current real shape)
#   {agentType, description, spawnDepth, toolUseId}  (current real shape)
#   {agentType, spawnDepth}                          (forward-compat, no toolUseId)
# Kernel tests set meta["trajectory_id"] inline (the shell sets it in production).


def sub_meta(*, trajectory_id, agent_type="explorer", description="explore the code",
             tool_use_id=None, spawn_depth=None, include_description=True):
    """Build a subagent meta sidecar dict.

    Defaults mirror the {agentType, description, toolUseId} real shape. Pass
    spawn_depth to add the spawnDepth field; pass include_description=False and
    tool_use_id=None for the forward-compat {agentType, spawnDepth} shape.
    """
    meta = {"agentType": agent_type, "trajectory_id": trajectory_id}
    if include_description:
        meta["description"] = description
    if tool_use_id is not None:
        meta["toolUseId"] = tool_use_id
    if spawn_depth is not None:
        meta["spawnDepth"] = spawn_depth
    return meta


def sub_records(*, call_id=None, content="sub step text", spawn=None):
    """Build a minimal isSidechain:true subagent transcript (one agent step).

    Pass call_id to give the step a tool_use it can be addressed by; pass
    spawn=(child_call_id) to add a spawning Agent tool_use (so this subagent can
    itself parent another).
    """
    blocks = [text_block(content)]
    if call_id is not None:
        blocks.append(tool_use_block(call_id, name="Bash"))
    if spawn is not None:
        blocks.append(tool_use_block(spawn, name="Agent"))
    recs = [asst(blocks, msg_id="sm1", usage=USAGE, sidechain=True)]
    if call_id is not None:
        recs.append(user([tool_result_block(call_id, "sub result")], sidechain=True))
    return recs


class TestSkipSidechainGate(unittest.TestCase):
    def test_skip_sidechain_false_keeps_sidechain_records(self):
        # skip_sidechain=False normalizes isSidechain:true records into steps.
        recs = [
            asst([text_block("sub")], msg_id="m1", usage=USAGE, sidechain=True),
            user([text_block("sub user")], sidechain=True),
        ]
        n = normalize(recs, skip_sidechain=False)
        self.assertEqual(len(n.steps), 2)
        self.assertEqual(n.steps[0].source, "agent")
        self.assertEqual(n.steps[1].source, "user")

    def test_skip_sidechain_true_is_default_and_skips(self):
        # Default (skip_sidechain=True) drops sidechain records → empty transcript.
        recs = [
            asst([text_block("sub")], msg_id="m1", usage=USAGE, sidechain=True),
            user([text_block("sub user")], sidechain=True),
        ]
        with self.assertRaises(core.EmptyTranscriptError):
            normalize(recs)  # default skip_sidechain=True

    def test_skip_sidechain_false_keeps_main_records_too(self):
        # Non-sidechain records still normalize when skip_sidechain=False.
        recs = [asst([text_block("main")], msg_id="m1", usage=USAGE)]
        n = normalize(recs, skip_sidechain=False)
        self.assertEqual(len(n.steps), 1)


def normalize_session(main_records, subagents, **kw):
    kw.setdefault("session_id", "sess")
    kw.setdefault("task_id", None)
    kw.setdefault("spec_id", None)
    kw.setdefault("intent", None)
    kw.setdefault("exclude_session_id", None)
    return core.normalize_session(main_records, subagents, **kw)


class TestNormalizeSessionSingleSubagent(unittest.TestCase):
    def test_single_subagent_embedded_and_linked(self):
        # Parent spawns one subagent via an Agent call "spawn-a"; meta carries
        # toolUseId == "spawn-a" so the ref links to the subagent.
        main = [
            asst([text_block("main turn"), tool_use_block("spawn-a", name="Agent")],
                 msg_id="m1", usage=USAGE),
            user([tool_result_block("spawn-a", "subagent finished")]),
        ]
        meta = sub_meta(trajectory_id="sess/agent-a", tool_use_id="spawn-a")
        n = normalize_session(main, [(meta, sub_records(call_id="sc1"))])
        # Exactly one embedded subagent.
        self.assertEqual(len(n.subagent_trajectories), 1)
        self.assertEqual(n.subagent_trajectories[0].trajectory_id, "sess/agent-a")
        # The ref is on the ObservationResult whose source_call_id == the Agent call.
        spawn_step = next(s for s in n.steps if any(
            tc["tool_call_id"] == "spawn-a" for tc in s.tool_calls))
        linked = [r for r in spawn_step.observation_results
                  if r.get("source_call_id") == "spawn-a"]
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0]["subagent_trajectory_ref"],
                         [{"trajectory_id": "sess/agent-a"}])


class TestNormalizeSessionDepth2(unittest.TestCase):
    def test_depth2_linked_on_subagent_A_not_parent(self):
        # main -> A -> B. A's isSidechain steps contain the Agent call "spawn-b";
        # B's meta.toolUseId == "spawn-b". B must be flat in subagent_trajectories
        # AND its ref must land on A's ObservationResult, never the parent's.
        main = [
            asst([text_block("main"), tool_use_block("spawn-a", name="Agent")],
                 msg_id="m1", usage=USAGE),
            user([tool_result_block("spawn-a", "A done")]),
        ]
        # A spawns B: A's step has the Agent call "spawn-b" and folds its result.
        a_records = [
            asst([text_block("A turn"), tool_use_block("spawn-b", name="Agent")],
                 msg_id="am1", usage=USAGE, sidechain=True),
            user([tool_result_block("spawn-b", "B done")], sidechain=True),
        ]
        b_records = sub_records(call_id="bc1", content="B turn")
        meta_a = sub_meta(trajectory_id="sess/agent-a", tool_use_id="spawn-a")
        meta_b = sub_meta(trajectory_id="sess/agent-b", tool_use_id="spawn-b")
        n = normalize_session(main, [(meta_a, a_records), (meta_b, b_records)])
        # Both subagents are flat (depth-agnostic — no nesting).
        ids = {s.trajectory_id for s in n.subagent_trajectories}
        self.assertEqual(ids, {"sess/agent-a", "sess/agent-b"})
        sub_a = next(s for s in n.subagent_trajectories
                     if s.trajectory_id == "sess/agent-a")
        # B's ref is on A's step, not the parent's.
        a_linked = [r for st in sub_a.steps for r in st.observation_results
                    if r.get("subagent_trajectory_ref")]
        self.assertEqual(len(a_linked), 1)
        self.assertEqual(a_linked[0]["subagent_trajectory_ref"],
                         [{"trajectory_id": "sess/agent-b"}])
        # The parent only links A, not B (guards the parent-only dangling bug).
        parent_refs = [r["subagent_trajectory_ref"] for st in n.steps
                       for r in st.observation_results
                       if r.get("subagent_trajectory_ref")]
        self.assertEqual(parent_refs, [[{"trajectory_id": "sess/agent-a"}]])


class TestNormalizeSessionDepth3(unittest.TestCase):
    def test_depth3_synthetic_linked_on_subagent_B(self):
        # Synthetic main -> A -> B -> C. C's ref must land on B's step. One flat
        # toolUseId map handles all depths (no per-depth code path).
        main = [
            asst([text_block("main"), tool_use_block("spawn-a", name="Agent")],
                 msg_id="m1", usage=USAGE),
            user([tool_result_block("spawn-a", "A done")]),
        ]
        a_records = [
            asst([text_block("A"), tool_use_block("spawn-b", name="Agent")],
                 msg_id="am1", usage=USAGE, sidechain=True),
            user([tool_result_block("spawn-b", "B done")], sidechain=True),
        ]
        b_records = [
            asst([text_block("B"), tool_use_block("spawn-c", name="Agent")],
                 msg_id="bm1", usage=USAGE, sidechain=True),
            user([tool_result_block("spawn-c", "C done")], sidechain=True),
        ]
        c_records = sub_records(call_id="cc1", content="C turn")
        meta_a = sub_meta(trajectory_id="sess/agent-a", tool_use_id="spawn-a")
        meta_b = sub_meta(trajectory_id="sess/agent-b", tool_use_id="spawn-b")
        meta_c = sub_meta(trajectory_id="sess/agent-c", tool_use_id="spawn-c")
        n = normalize_session(main, [(meta_a, a_records),
                                     (meta_b, b_records),
                                     (meta_c, c_records)])
        sub_b = next(s for s in n.subagent_trajectories
                     if s.trajectory_id == "sess/agent-b")
        b_linked = [r for st in sub_b.steps for r in st.observation_results
                    if r.get("subagent_trajectory_ref")]
        self.assertEqual(len(b_linked), 1)
        self.assertEqual(b_linked[0]["subagent_trajectory_ref"],
                         [{"trajectory_id": "sess/agent-c"}])


class TestRollupSubagentMetrics(unittest.TestCase):
    def test_rollup_sums_tokens_and_cost_no_double_count(self):
        # Parent + 2 subs, each one agent step with the same known USAGE.
        main = [asst([text_block("main")], msg_id="m1", usage=USAGE)]
        meta1 = sub_meta(trajectory_id="sess/agent-1", tool_use_id="t1")
        meta2 = sub_meta(trajectory_id="sess/agent-2", tool_use_id="t2")
        subs = [(meta1, sub_records(content="s1")), (meta2, sub_records(content="s2"))]
        n = normalize_session(main, subs)

        per_prompt = USAGE["input_tokens"] + USAGE["cache_creation_input_tokens"] + \
            USAGE["cache_read_input_tokens"]
        per_compl = USAGE["output_tokens"]
        per_cached = USAGE["cache_read_input_tokens"]
        # Parent totals = parent step + both subagent steps (flat union).
        self.assertEqual(n.final_metrics["total_prompt_tokens"], per_prompt * 3)
        self.assertEqual(n.final_metrics["total_completion_tokens"], per_compl * 3)
        self.assertEqual(n.final_metrics["total_cached_tokens"], per_cached * 3)
        # total_steps stays parent-only.
        self.assertEqual(n.final_metrics["total_steps"], 1)
        # Cost is the rounded sum of parent + both subs; no double-count.
        sub1, sub2 = n.subagent_trajectories
        expected_cost = round(
            normalize([asst([text_block("main")], msg_id="m1", usage=USAGE)]
                      ).final_metrics["total_cost_usd"]
            + sub1.final_metrics["total_cost_usd"]
            + sub2.final_metrics["total_cost_usd"], 6)
        self.assertEqual(n.final_metrics["total_cost_usd"], expected_cost)
        # Each subagent keeps its own final_metrics (its own single step).
        self.assertEqual(sub1.final_metrics["total_prompt_tokens"], per_prompt)
        self.assertEqual(sub1.final_metrics["total_steps"], 1)
        self.assertEqual(sub2.final_metrics["total_prompt_tokens"], per_prompt)
        self.assertEqual(sub2.final_metrics["total_steps"], 1)


class TestNormalizeSessionNoSubagents(unittest.TestCase):
    def test_no_subagents_reduces_to_normalize(self):
        main = [
            asst([text_block("a")], msg_id="m1", usage=USAGE),
            user([text_block("human")]),
            asst([text_block("b")], msg_id="m2", usage=USAGE),
        ]
        n = normalize_session(main, [])
        self.assertEqual(n.subagent_trajectories, [])
        # Behaves exactly like normalize on the main transcript.
        base = normalize([
            asst([text_block("a")], msg_id="m1", usage=USAGE),
            user([text_block("human")]),
            asst([text_block("b")], msg_id="m2", usage=USAGE),
        ])
        self.assertEqual(len(n.steps), len(base.steps))
        self.assertEqual([s.source for s in n.steps], [s.source for s in base.steps])
        self.assertEqual([s.message for s in n.steps], [s.message for s in base.steps])
        self.assertEqual(n.final_metrics, base.final_metrics)


class TestNormalizeSessionUnlinkedSubagent(unittest.TestCase):
    def test_meta_without_tool_use_id_is_embedded_unlinked(self):
        # Forward-compat shape {agentType, spawnDepth} (no toolUseId, no description).
        main = [
            asst([text_block("main"), tool_use_block("spawn-a", name="Agent")],
                 msg_id="m1", usage=USAGE),
            user([tool_result_block("spawn-a", "done")]),
        ]
        meta = sub_meta(trajectory_id="sess/agent-x", agent_type="mystery",
                        include_description=False, spawn_depth=1)  # no toolUseId
        n = normalize_session(main, [(meta, sub_records())])
        # Embedded.
        self.assertEqual(len(n.subagent_trajectories), 1)
        sub = n.subagent_trajectories[0]
        # subagent_type present, subagent_description absent.
        self.assertEqual(sub.extra["subagent_type"], "mystery")
        self.assertNotIn("subagent_description", sub.extra)
        # No ref attached anywhere (unlinked).
        all_refs = [r for tr in [n, *n.subagent_trajectories]
                    for st in tr.steps for r in st.observation_results
                    if r.get("subagent_trajectory_ref")]
        self.assertEqual(all_refs, [])


class TestEmbeddedTrajectoryIdNonNull(unittest.TestCase):
    def test_every_embedded_subagent_has_non_null_trajectory_id(self):
        main = [asst([text_block("main")], msg_id="m1", usage=USAGE)]
        subs = [
            (sub_meta(trajectory_id="sess/agent-1", tool_use_id="t1"),
             sub_records(content="s1")),
            (sub_meta(trajectory_id="sess/agent-2", tool_use_id="t2"),
             sub_records(content="s2")),
        ]
        n = normalize_session(main, subs)
        for sub in n.subagent_trajectories:
            self.assertIsNotNone(sub.trajectory_id)
            self.assertTrue(sub.trajectory_id)


class TestNormalizeSessionExcludeSessionNotAppliedToSubagents(unittest.TestCase):
    def test_exclude_session_id_does_not_drop_subagents(self):
        # Subagent records carry the captured session's own sessionId. Passing
        # that same id as exclude_session_id must NOT drop the subagent — the
        # exclusion is a parent-transcript concern only.
        main = [
            asst([text_block("main"), tool_use_block("spawn-a", name="Agent")],
                 msg_id="m1", usage=USAGE, session_id="keepsess"),
            user([tool_result_block("spawn-a", "done")], session_id="keepsess"),
        ]
        # Subagent records use a DIFFERENT id ("capsess") which we also exclude;
        # if exclusion were applied to subagents, the subagent would vanish.
        sub_recs = [
            asst([text_block("sub")], msg_id="sm1", usage=USAGE,
                 sidechain=True, session_id="capsess"),
        ]
        meta = sub_meta(trajectory_id="capsess/agent-a", tool_use_id="spawn-a")
        n = normalize_session(main, [(meta, sub_recs)],
                              exclude_session_id="capsess")
        # Parent intact, subagent survived despite the exclusion.
        self.assertTrue(len(n.steps) >= 1)
        self.assertEqual(len(n.subagent_trajectories), 1)
        self.assertEqual(n.subagent_trajectories[0].trajectory_id, "capsess/agent-a")


class TestNormalizeSessionDuplicateToolResultRef(unittest.TestCase):
    def test_ref_attached_to_both_duplicate_results(self):
        # One spawning Agent call with TWO tool_results (same source_call_id).
        # The ref must attach to both.
        main = [
            asst([text_block("main"), tool_use_block("spawn-a", name="Agent")],
                 msg_id="m1", usage=USAGE),
            user([tool_result_block("spawn-a", "first")]),
            user([tool_result_block("spawn-a", "second")]),
        ]
        meta = sub_meta(trajectory_id="sess/agent-a", tool_use_id="spawn-a")
        n = normalize_session(main, [(meta, sub_records())])
        spawn_step = next(s for s in n.steps if any(
            tc["tool_call_id"] == "spawn-a" for tc in s.tool_calls))
        linked = [r for r in spawn_step.observation_results
                  if r.get("source_call_id") == "spawn-a"]
        self.assertEqual(len(linked), 2)
        for r in linked:
            self.assertEqual(r["subagent_trajectory_ref"],
                             [{"trajectory_id": "sess/agent-a"}])


class TestNormalizeSessionEmbedUnlinkedOnTruncation(unittest.TestCase):
    MARKER = "/drvr:capture-session"

    def test_truncated_spawn_call_yields_embedded_but_unlinked(self):
        # The spawning Agent call lives AFTER the capture-invocation turn, so the
        # exclude_marker truncation cuts it away. The subagent is still present on
        # disk → embedded, but with NO ref anywhere (the spawning call is gone).
        main = [
            user([text_block("real human turn")]),
            asst([text_block("agent reply")], msg_id="m1", usage=USAGE),
            user([text_block(self.MARKER)]),                 # capture invocation = cut
            asst([text_block("dropped"), tool_use_block("spawn-a", name="Agent")],
                 msg_id="m2", usage=USAGE),
            user([tool_result_block("spawn-a", "dropped result")]),
        ]
        meta = sub_meta(trajectory_id="sess/agent-a", tool_use_id="spawn-a")
        n = normalize_session(main, [(meta, sub_records())],
                              exclude_marker=self.MARKER)
        # Parent intact (only the pre-marker steps).
        self.assertEqual(len(n.steps), 2)
        # Subagent still embedded.
        self.assertEqual(len(n.subagent_trajectories), 1)
        # ZERO refs anywhere (the spawning call was truncated away).
        all_refs = [r for tr in [n, *n.subagent_trajectories]
                    for st in tr.steps for r in st.observation_results
                    if r.get("subagent_trajectory_ref")]
        self.assertEqual(all_refs, [])


class TestRefResolvabilityInvariant(unittest.TestCase):
    def test_every_ref_resolves_to_an_embedded_subagent(self):
        # Depth-2 fixture: gather every emitted ref across parent + subs and assert
        # each trajectory_id resolves to an embedded subagent's trajectory_id.
        main = [
            asst([text_block("main"), tool_use_block("spawn-a", name="Agent")],
                 msg_id="m1", usage=USAGE),
            user([tool_result_block("spawn-a", "A done")]),
        ]
        a_records = [
            asst([text_block("A"), tool_use_block("spawn-b", name="Agent")],
                 msg_id="am1", usage=USAGE, sidechain=True),
            user([tool_result_block("spawn-b", "B done")], sidechain=True),
        ]
        b_records = sub_records(content="B")
        meta_a = sub_meta(trajectory_id="sess/agent-a", tool_use_id="spawn-a")
        meta_b = sub_meta(trajectory_id="sess/agent-b", tool_use_id="spawn-b")
        n = normalize_session(main, [(meta_a, a_records), (meta_b, b_records)])
        embedded_ids = {s.trajectory_id for s in n.subagent_trajectories}
        emitted = [ref["trajectory_id"]
                   for tr in [n, *n.subagent_trajectories]
                   for st in tr.steps
                   for r in st.observation_results
                   for ref in r.get("subagent_trajectory_ref", [])]
        self.assertTrue(emitted)  # there ARE refs to check
        for tid in emitted:
            self.assertIn(tid, embedded_ids)


class TestIsSafePathComponent(unittest.TestCase):
    """Pure predicate guarding the subagent-dir glob against a transcript-supplied
    session_id (PATH-001): a malicious sessionId like '../../../etc' would otherwise
    join into a path that resolves outside the capture dir. Real Claude Code session
    ids are opaque UUIDs, so the guard never trips on legitimate data.
    """

    def test_real_session_ids_are_safe(self):
        for sid in ("8f5a3cf6-4988-4beb-a861-3163dfac3371", "agent-a",
                    "sess", "sess-A", "abc123"):
            self.assertTrue(core.is_safe_path_component(sid), sid)

    def test_traversal_and_separators_rejected(self):
        for sid in ("..", "../../../etc", "a/b", "a\\b", "/abs",
                    ".hidden", ".", "", "a\x00b"):
            self.assertFalse(core.is_safe_path_component(sid), sid)

    def test_non_str_rejected(self):
        for sid in (None, 123, ["x"]):
            self.assertFalse(core.is_safe_path_component(sid), sid)


class TestNormalizeSessionEmptySubagentOmitted(unittest.TestCase):
    def test_zero_step_subagent_omitted_parent_intact(self):
        # A subagent whose records yield no steps is dropped via EmptyTranscriptError
        # caught inside normalize_session; the parent is unaffected.
        main = [
            asst([text_block("main"), tool_use_block("spawn-a", name="Agent")],
                 msg_id="m1", usage=USAGE),
            user([tool_result_block("spawn-a", "done")]),
        ]
        good_meta = sub_meta(trajectory_id="sess/agent-good", tool_use_id="spawn-a")
        empty_meta = sub_meta(trajectory_id="sess/agent-empty", tool_use_id="t-empty")
        # The empty subagent has only newer-type records → zero steps.
        empty_records = [{"type": "mode", "isSidechain": True, "sessionId": "sess",
                          "timestamp": "2026-06-25T00:00:00Z", "message": {}}]
        n = normalize_session(
            main,
            [(good_meta, sub_records()), (empty_meta, empty_records)])
        # Only the non-empty subagent survives.
        ids = {s.trajectory_id for s in n.subagent_trajectories}
        self.assertEqual(ids, {"sess/agent-good"})
        # Parent intact.
        self.assertTrue(len(n.steps) >= 1)


if __name__ == "__main__":
    unittest.main()
