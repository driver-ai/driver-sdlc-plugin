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


if __name__ == "__main__":
    unittest.main()
