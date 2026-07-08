"""Unit tests for the slim pure capture core (cc_to_atif_core).

The record walk (grouping, tool_result folding, usage/cost math, subagent
embedding) is the upstream logs2atif converter's contract, exercised by the
gated wrapper tests at our boundary. This module tests the pure helpers we keep
around that converter: the pre-filter (marker truncation / exclusions / user
content flatten), the shared content flattener, the serialized-dict enrichment
passes (token rollup, nested ref re-link, extra injection), the subagent
staging line cleaner, and the path-segment guard.

Pure-core tests: import `cc_to_atif_core` ONLY. No external deps, no mocks.
Stdlib `unittest` only. Crafted records carry valid ISO 8601 timestamps so the
fixtures stay portable to the gated wrapper suites (upstream drops
invalid-timestamp records silently).
"""
import json
import os
import sys
import unittest

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import cc_to_atif_core as core


# ---------------------------------------------------------------------------
# Tiny record-fixture builders (inline JSONL-record dicts)
# ---------------------------------------------------------------------------


def asst(content, *, msg_id=None, model="claude-opus-4-8-20260315",
         session_id="sess", ts="2026-06-25T00:00:00Z", sidechain=False):
    msg = {"content": content}
    if msg_id is not None:
        msg["id"] = msg_id
    if model is not None:
        msg["model"] = model
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


# ---------------------------------------------------------------------------
# prefilter_records: marker truncation (whole-command-token match)
# ---------------------------------------------------------------------------


class TestPrefilterMarkerTruncation(unittest.TestCase):
    MARKER = "/drvr:capture-session"

    def test_prefilter_truncates_at_last_marker_token(self):
        recs = [
            user("real human turn one"),
            asst([text_block("agent reply")], msg_id="m1"),
            user(self.MARKER + " arg"),                 # the capture invocation
            asst([text_block("should be dropped")], msg_id="m2"),
        ]
        out = core.prefilter_records(recs, exclude_marker=self.MARKER)
        # Cut at the marker turn: only the records before it survive.
        self.assertEqual(out, recs[:2])

    def test_prefilter_last_matching_turn_when_multiple(self):
        recs = [
            user(self.MARKER),                          # earlier invocation
            asst([text_block("mid")], msg_id="m1"),
            user(self.MARKER),                          # LAST invocation = cut point
            asst([text_block("dropped")], msg_id="m2"),
        ]
        out = core.prefilter_records(recs, exclude_marker=self.MARKER)
        # Cut at the LAST marker turn -> records[0:2] remain.
        self.assertEqual(out, recs[:2])

    def test_prefilter_prose_mention_does_not_truncate(self):
        recs = [
            user("I want to run " + self.MARKER + " later"),
            asst([text_block("ok")], msg_id="m1"),
        ]
        out = core.prefilter_records(recs, exclude_marker=self.MARKER)
        # Prose mention (not the first command token) does NOT cut.
        self.assertEqual(out, recs)

    def test_prefilter_longer_command_does_not_truncate(self):
        # A LONGER command token must NOT match (whole-token equality).
        recs = [
            user(self.MARKER + "-foo bar"),
            asst([text_block("kept")], msg_id="m1"),
        ]
        out = core.prefilter_records(recs, exclude_marker=self.MARKER)
        self.assertEqual(out, recs)

    def test_prefilter_marker_inside_assistant_or_tool_result_does_not_truncate(self):
        recs = [
            user("human turn"),
            asst([text_block("here is the " + self.MARKER + " command")],
                 msg_id="m1"),
            asst([tool_use_block("c1")], msg_id="m2"),
            user([tool_result_block("c1", self.MARKER + " inside a result")]),
        ]
        out = core.prefilter_records(recs, exclude_marker=self.MARKER)
        # Marker only inside assistant/tool_result content -> no truncation.
        self.assertEqual(out, recs)

    def test_prefilter_marker_at_record_zero_empties(self):
        # Marker as the very first record: everything is cut. The shell maps an
        # empty filtered list to exit 1 (hook backoff contract).
        recs = [
            user(self.MARKER),
            asst([text_block("after")], msg_id="m1"),
        ]
        out = core.prefilter_records(recs, exclude_marker=self.MARKER)
        self.assertEqual(out, [])

    def test_prefilter_marker_ignores_sidechain_user_records(self):
        # A sidechain user record carrying the marker is never a cut point (and
        # is itself dropped by the sidechain guard).
        recs = [
            user("real turn"),
            asst([text_block("reply")], msg_id="m1"),
            user(self.MARKER, sidechain=True),
            asst([text_block("kept")], msg_id="m2"),
        ]
        out = core.prefilter_records(recs, exclude_marker=self.MARKER)
        self.assertEqual(out, [recs[0], recs[1], recs[3]])

    def test_prefilter_marker_unwraps_command_name_tag(self):
        # A literal <command-name> tag prefixing the command is unwrapped
        # before the whole-token match, so the tagged invocation still cuts.
        recs = [
            user("real turn"),
            asst([text_block("reply")], msg_id="m1"),
            user("<command-name>" + self.MARKER + " arg"),
            asst([text_block("dropped")], msg_id="m2"),
        ]
        out = core.prefilter_records(recs, exclude_marker=self.MARKER)
        self.assertEqual(out, recs[:2])

        # Known pre-existing limit, carried over: the unwrap does not fire on
        # the modern <command-message>-first record shape (the first token is
        # the <command-message> tag), so only bare-typed commands truncate.
        modern = ("<command-message>capture-session is running</command-message>\n"
                  "<command-name>" + self.MARKER + "</command-name>")
        recs2 = [
            user("real turn"),
            asst([text_block("reply")], msg_id="m1"),
            user(modern),
            asst([text_block("kept")], msg_id="m2"),
        ]
        out2 = core.prefilter_records(recs2, exclude_marker=self.MARKER)
        self.assertEqual(out2, recs2)


# ---------------------------------------------------------------------------
# prefilter_records: session-id / sidechain exclusions + identity
# ---------------------------------------------------------------------------


class TestPrefilterExclusions(unittest.TestCase):
    def test_prefilter_drops_exclude_session_id_records(self):
        recs = [
            asst([text_block("cap a")], msg_id="m1", session_id="capsess"),
            user("cap b", session_id="capsess"),
            asst([text_block("keep")], msg_id="m2", session_id="sess"),
        ]
        out = core.prefilter_records(recs, exclude_session_id="capsess")
        self.assertEqual(out, [recs[2]])

    def test_prefilter_drops_inline_sidechain_records(self):
        # isSidechain:true records never survive, even with no exclusion args:
        # subagent work reaches the trajectory only via the subagent files, so
        # an inline copy can never double-count (structural guard).
        recs = [
            asst([text_block("sub")], msg_id="m1", sidechain=True),
            user("sub user", sidechain=True),
            user("main user"),
        ]
        out = core.prefilter_records(recs)
        self.assertEqual(out, [recs[2]])

    def test_prefilter_keeps_order_and_unmatched_records(self):
        # No marker/exclusions -> identity: same records, same order, same
        # objects (nothing rewritten). Non-user/assistant record types pass
        # through too (upstream owns skipping them).
        recs = [
            user("one"),
            asst([text_block("two")], msg_id="m1"),
            {"type": "file-history-snapshot", "isSidechain": False,
             "sessionId": "sess", "timestamp": "2026-06-25T00:00:00Z",
             "message": {}},
            user("three"),
        ]
        out = core.prefilter_records(recs)
        self.assertEqual(out, recs)
        for got, orig in zip(out, recs):
            self.assertIs(got, orig)


# ---------------------------------------------------------------------------
# prefilter_records: list-form user content flatten
# ---------------------------------------------------------------------------


class TestPrefilterFlattensListUserContent(unittest.TestCase):
    def test_prefilter_flattens_list_user_content(self):
        # Text parts joined with newlines; the pasted-screenshot image block
        # becomes an [image] placeholder -- its base64 payload never survives.
        b64 = "iVBORw0KGgoAAAANSUhEUg" + "A" * 64
        recs = [user([
            text_block("look at this"),
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            text_block("what do you think?"),
        ])]
        out = core.prefilter_records(recs)
        content = out[0]["message"]["content"]
        self.assertEqual(content, "look at this\n[image]\nwhat do you think?")
        self.assertNotIn(b64, json.dumps(out))
        # Pure: the input record was not mutated.
        self.assertIsInstance(recs[0]["message"]["content"], list)

    def test_prefilter_tool_result_lists_and_non_user_records_untouched(self):
        recs = [
            asst([tool_use_block("c1"), text_block("assistant list stays")],
                 msg_id="m1"),
            user([tool_result_block("c1", "result text")]),
        ]
        out = core.prefilter_records(recs)
        # A tool_result-bearing user list must NOT be flattened to a string --
        # flattening it would corrupt the logs2atif conversion. The list stays a
        # list carrying the tool_result block.
        user_content = out[1]["message"]["content"]
        self.assertIsInstance(user_content, list)
        self.assertEqual(user_content, [tool_result_block("c1", "result text")])
        # Non-user (assistant) records pass through the flatten untouched.
        self.assertEqual(out[0]["message"]["content"],
                         [tool_use_block("c1"), text_block("assistant list stays")])


# ---------------------------------------------------------------------------
# flatten_content: shared message/observation content -> display text
# ---------------------------------------------------------------------------


class TestFlattenContent(unittest.TestCase):
    def test_flatten_content_str_passthrough(self):
        self.assertEqual(core.flatten_content("plain text"), "plain text")

    def test_flatten_content_joins_text_parts(self):
        parts = [{"type": "text", "text": "first"},
                 {"type": "text", "text": "second"}]
        self.assertEqual(core.flatten_content(parts), "first\nsecond")

    def test_flatten_content_renders_image_placeholder(self):
        # Image fields are read from the NESTED source block (the real ATIF
        # ContentPart shape), not from the part itself.
        parts = [{"type": "text", "text": "see:"},
                 {"type": "image",
                  "source": {"media_type": "image/png", "path": "images/img_001.png"}}]
        self.assertEqual(core.flatten_content(parts),
                         "see:\n[image: image/png images/img_001.png]")

    def test_flatten_content_non_dict_and_unknown_parts(self):
        parts = [{"type": "document"}, 42, "raw"]
        self.assertEqual(core.flatten_content(parts), "[document]\n42\nraw")

    def test_flatten_content_none_empty(self):
        self.assertEqual(core.flatten_content(None), "")
        self.assertEqual(core.flatten_content([]), "")


# ---------------------------------------------------------------------------
# rollup_subagent_tokens: subagent-inclusive parent token totals
# ---------------------------------------------------------------------------


class TestRollupSubagentTokens(unittest.TestCase):
    def _traj(self):
        # Mirrors the REAL upstream serialized shape: subagent final_metrics is
        # cost-only (token totals are dropped by exclude_none); tokens live in
        # each subagent step's per-step metrics.
        return {
            "schema_version": "ATIF-v1.7",
            "session_id": "sess",
            "final_metrics": {
                "total_prompt_tokens": 1000, "total_completion_tokens": 200,
                "total_cached_tokens": 300, "total_cost_usd": 1.25,
                "total_steps": 4,
            },
            "subagent_trajectories": [
                {
                    "trajectory_id": "sess/agent-a",
                    "final_metrics": {"total_cost_usd": 0.40},
                    "steps": [
                        {"step_id": 1, "source": "agent", "message": "s1",
                         "metrics": {"prompt_tokens": 10, "completion_tokens": 5,
                                     "cached_tokens": 2, "cost_usd": 0.40}},
                        {"step_id": 2, "source": "user", "message": "s2"},
                    ],
                },
                {
                    "trajectory_id": "sess/agent-b",
                    "final_metrics": {"total_cost_usd": 0.10},
                    "steps": [
                        {"step_id": 1, "source": "agent", "message": "s3",
                         "metrics": {"prompt_tokens": 7, "completion_tokens": 3}},
                    ],
                },
            ],
        }

    def test_rollup_sums_subagent_step_metrics_into_parent(self):
        traj = self._traj()
        out = core.rollup_subagent_tokens(traj)
        self.assertIs(out, traj)   # in place, returned for chaining
        fm = traj["final_metrics"]
        # Token totals are subagent-inclusive (absent step metrics/keys count 0).
        self.assertEqual(fm["total_prompt_tokens"], 1000 + 10 + 7)
        self.assertEqual(fm["total_completion_tokens"], 200 + 5 + 3)
        self.assertEqual(fm["total_cached_tokens"], 300 + 2)
        # Cost (already subtree-inclusive upstream) and step count untouched.
        self.assertEqual(fm["total_cost_usd"], 1.25)
        self.assertEqual(fm["total_steps"], 4)
        # Subagent final_metrics stay cost-only (never rewritten).
        for sub in traj["subagent_trajectories"]:
            self.assertEqual(set(sub["final_metrics"]), {"total_cost_usd"})

    def test_rollup_creates_absent_parent_totals(self):
        traj = self._traj()
        traj["final_metrics"] = {"total_cost_usd": 0.90}   # unpriced-token parent
        core.rollup_subagent_tokens(traj)
        fm = traj["final_metrics"]
        self.assertEqual(fm["total_prompt_tokens"], 17)
        self.assertEqual(fm["total_completion_tokens"], 8)
        self.assertEqual(fm["total_cached_tokens"], 2)
        self.assertEqual(fm["total_cost_usd"], 0.90)
        self.assertNotIn("total_steps", fm)

        no_fm = self._traj()
        del no_fm["final_metrics"]
        core.rollup_subagent_tokens(no_fm)
        self.assertEqual(no_fm["final_metrics"]["total_prompt_tokens"], 17)
        self.assertNotIn("total_cost_usd", no_fm["final_metrics"])

    def test_rollup_no_subagents_identity(self):
        traj = {"session_id": "sess",
                "final_metrics": {"total_prompt_tokens": 5, "total_steps": 1}}
        before = json.dumps(traj, sort_keys=True)
        out = core.rollup_subagent_tokens(traj)
        self.assertIs(out, traj)
        self.assertEqual(json.dumps(traj, sort_keys=True), before)


# ---------------------------------------------------------------------------
# link_nested_subagent_refs: depth-agnostic ref re-link on the serialized dict
# ---------------------------------------------------------------------------


class TestLinkNestedSubagentRefs(unittest.TestCase):
    def _traj(self):
        # Serialized shape: results nest under step["observation"]["results"].
        # Upstream links the parent's ref only; the grandchild (spawned by the
        # child) is embedded but unreferenced.
        child = {
            "trajectory_id": "sess/agent-a",
            "agent": {"name": "explorer",
                      "extra": {"toolUseId": "spawn-a", "spawnDepth": 1}},
            "steps": [
                {"step_id": 1, "source": "agent", "message": "A",
                 "tool_calls": [{"tool_call_id": "spawn-b",
                                 "function_name": "Agent", "arguments": {}}],
                 "observation": {"results": [
                     {"source_call_id": "spawn-b", "content": "B done"}]}},
                # Same source_call_id in a DIFFERENT step (no tool_call here):
                # the within-step rule must leave it unlinked.
                {"step_id": 2, "source": "agent", "message": "stray",
                 "observation": {"results": [
                     {"source_call_id": "spawn-b", "content": "stray copy"}]}},
            ],
        }
        grandchild = {
            "trajectory_id": "sess/agent-b",
            "agent": {"name": "worker",
                      "extra": {"toolUseId": "spawn-b", "spawnDepth": 2}},
            "steps": [{"step_id": 1, "source": "agent", "message": "B"}],
        }
        return {
            "session_id": "sess",
            "steps": [
                {"step_id": 1, "source": "agent", "message": "main",
                 "tool_calls": [{"tool_call_id": "spawn-a",
                                 "function_name": "Agent", "arguments": {}}],
                 "observation": {"results": [
                     {"source_call_id": "spawn-a", "content": "A done",
                      "subagent_trajectory_ref": [
                          {"trajectory_id": "sess/agent-a"}]}]}},
            ],
            "subagent_trajectories": [child, grandchild],
        }

    def test_link_nested_subagent_refs_depth2(self):
        traj = self._traj()
        out = core.link_nested_subagent_refs(traj)
        self.assertIs(out, traj)   # in place, returned for chaining
        child, grandchild = traj["subagent_trajectories"]
        # The grandchild's ref is attached under the CHILD step's results entry
        # with the matching source_call_id (the within-step rule).
        linked = child["steps"][0]["observation"]["results"][0]
        self.assertEqual(linked["subagent_trajectory_ref"],
                         [{"trajectory_id": "sess/agent-b"}])
        # The stray same-id result in a step WITHOUT the tool_call stays bare.
        stray = child["steps"][1]["observation"]["results"][0]
        self.assertNotIn("subagent_trajectory_ref", stray)
        # The parent's upstream-attached ref is not duplicated.
        parent_result = traj["steps"][0]["observation"]["results"][0]
        self.assertEqual(parent_result["subagent_trajectory_ref"],
                         [{"trajectory_id": "sess/agent-a"}])
        # The grandchild itself gains nothing (no spawning calls inside it).
        self.assertNotIn("observation", grandchild["steps"][0])

    def test_link_is_idempotent(self):
        traj = core.link_nested_subagent_refs(self._traj())
        once = json.dumps(traj, sort_keys=True)
        core.link_nested_subagent_refs(traj)
        self.assertEqual(json.dumps(traj, sort_keys=True), once)

    def test_link_unmatched_ids_no_op(self):
        traj = {
            "session_id": "sess",
            "steps": [
                {"step_id": 1, "source": "agent", "message": "main",
                 "tool_calls": [{"tool_call_id": "no-such",
                                 "function_name": "Agent", "arguments": {}}],
                 "observation": {"results": [
                     {"source_call_id": "no-such", "content": "done"}]}},
            ],
            "subagent_trajectories": [
                {"trajectory_id": "sess/agent-x",
                 "agent": {"name": "worker", "extra": {"toolUseId": "other-id"}},
                 "steps": [{"step_id": 1, "source": "agent", "message": "x"}]},
            ],
        }
        before = json.dumps(traj, sort_keys=True)
        core.link_nested_subagent_refs(traj)
        self.assertEqual(json.dumps(traj, sort_keys=True), before)


# ---------------------------------------------------------------------------
# sanitize_jsonl_lines: staging tolerance for subagent files
# ---------------------------------------------------------------------------


class TestSanitizeJsonlLines(unittest.TestCase):
    def test_sanitize_jsonl_lines(self):
        # Upstream tolerates unparseable lines but crashes the whole conversion
        # on valid-JSON non-dict lines -- both kinds must be dropped here, and
        # kept dict lines must survive byte-identical (odd spacing included).
        dict_line = '{"type": "assistant",  "sessionId": "sess"}'
        lines = [dict_line, "null", '"str"', "[1]", "{not json", "",
                 '{"a": 1}']
        self.assertEqual(core.sanitize_jsonl_lines(lines),
                         [dict_line, '{"a": 1}'])
        self.assertEqual(core.sanitize_jsonl_lines([]), [])


# ---------------------------------------------------------------------------
# inject_capture_extra: environment / SDLC identity on the serialized artifact
# ---------------------------------------------------------------------------


class TestInjectCaptureExtra(unittest.TestCase):
    def test_inject_capture_extra_sets_env_and_sdlc_keys_absent_when_none(self):
        traj = {"session_id": "sess", "extra": {"agent_ids": ["a1"]}}
        out = core.inject_capture_extra(
            traj, environment={"branch": "b", "cwd": "/w"},
            task_id="T1", spec_id=None, intent=None)
        self.assertIs(out, traj)   # in place, returned for chaining
        extra = traj["extra"]
        self.assertEqual(extra["environment"], {"branch": "b", "cwd": "/w"})
        self.assertEqual(extra["sdlc_task_id"], "T1")
        # Absent facts stay absent -- never null.
        self.assertNotIn("sdlc_spec_id", extra)
        self.assertNotIn("sdlc_intent", extra)
        # Upstream extra keys preserved.
        self.assertEqual(extra["agent_ids"], ["a1"])

    def test_inject_truthy_gating_and_extra_creation(self):
        # Falsy values ("" / {}) are not injected; `extra` is created when the
        # upstream trajectory has none and something is set.
        traj = {"session_id": "sess"}
        core.inject_capture_extra(traj, environment={}, task_id="",
                                  spec_id="S1", intent=None)
        self.assertEqual(traj["extra"], {"sdlc_spec_id": "S1"})
        # Nothing truthy -> trajectory unchanged (no empty extra invented).
        traj2 = {"session_id": "sess"}
        core.inject_capture_extra(traj2, environment=None, task_id=None,
                                  spec_id=None, intent=None)
        self.assertNotIn("extra", traj2)


# ---------------------------------------------------------------------------
# is_safe_path_component: path-segment guard (ported unchanged)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Command-bash wiring tests: the identity-completion block (after Step 4) and the
# Step 9 arc summary. These extract the REAL fenced bash blocks from
# commands/capture-session.md and run them as subprocesses against real artifacts /
# a seeded real index -- no module mocks. The fill/arc semantics live in the pure
# capture_store_core helpers (unit-tested in tests/test_capture_store_core.py); these
# prove the thin wiring loads/dumps and resolves the key via git as the writers do.
# ---------------------------------------------------------------------------

import json as _json
import re as _re
import subprocess as _subprocess
import tempfile as _tempfile
from pathlib import Path as _Path

_COMMAND_MD = PLUGIN_ROOT / "commands" / "capture-session.md"


def _extract_bash_block(anchor: str) -> str:
    """Return the single fenced ```bash block from the command markdown that
    contains `anchor`. Fails loudly if zero or more than one block matches, so a
    markdown edit that removes/duplicates the block is caught here (not silently
    skipped)."""
    text = _COMMAND_MD.read_text(encoding="utf-8")
    blocks = _re.findall(r"```bash\n(.*?)```", text, flags=_re.DOTALL)
    matching = [b for b in blocks if anchor in b]
    if len(matching) != 1:
        raise AssertionError(
            f"expected exactly one ```bash block containing {anchor!r}, "
            f"found {len(matching)}")
    return matching[0]


def _run_bash(block: str, *, cwd, env):
    """Run an extracted command-bash block under bash from `cwd` with `env`."""
    return _subprocess.run(
        ["bash", "-c", block], cwd=str(cwd), env=env,
        capture_output=True, text=True)


def _init_git_repo(path: _Path, branch: str) -> None:
    """Init a real git repo at `path` with a single commit on `branch` (so
    `git branch --show-current` yields that branch — matching how the index writers
    resolve the key)."""
    g = ["git", "-C", str(path)]
    _subprocess.run(g + ["init", "-q", "-b", branch], check=True, capture_output=True)
    _subprocess.run(g + ["config", "user.email", "t@t.test"], check=True, capture_output=True)
    _subprocess.run(g + ["config", "user.name", "t"], check=True, capture_output=True)
    (path / "f.txt").write_text("x")
    _subprocess.run(g + ["add", "-A"], check=True, capture_output=True)
    _subprocess.run(g + ["commit", "-qm", "init"], check=True, capture_output=True)


class TestFlushIdentityCompletionWiring(unittest.TestCase):
    """The identity-completion block (after Step 4) fills an absent grouping identity
    on the ALREADY-redacted artifact via the pure complete_identity helper — thin
    wiring only. Real artifact on disk, real git branch, no mocks."""

    IDENTITY_ANCHOR = "the pure complete_identity helper (unit-tested)"

    def setUp(self):
        self.tmp = _tempfile.TemporaryDirectory()
        self.root = _Path(self.tmp.name)
        self.cur = self.root / "cur"
        self.cur.mkdir()
        self.block = _extract_bash_block(self.IDENTITY_ANCHOR)

    def tearDown(self):
        self.tmp.cleanup()

    def _env(self, *, task, spec):
        return {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
                "CUR": str(self.cur), "TASK": task, "SPEC": spec}

    def _write_artifact(self, traj):
        (self.cur / "trajectory.redacted.json").write_text(_json.dumps(traj))

    def _read_artifact(self):
        return _json.loads((self.cur / "trajectory.redacted.json").read_text())

    def test_store_fresh_artifact_gets_task_and_branch(self):
        # A store-fresh artifact lacking sdlc_task_id / environment.branch: after the
        # block runs it carries the command's $TASK and the git branch, so the arc
        # keys by task/branch instead of 'ungrouped'.
        repo = self.root / "repo"
        repo.mkdir()
        _init_git_repo(repo, "eric/rolling-capture")
        self._write_artifact({"schema_version": "ATIF-v1.7", "session_id": "s1",
                              "extra": {}, "steps": []})
        res = _run_bash(self.block, cwd=repo, env=self._env(task="T6", spec="S2"))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        out = self._read_artifact()
        self.assertEqual(out["extra"]["sdlc_task_id"], "T6")
        self.assertEqual(out["extra"]["sdlc_spec_id"], "S2")
        self.assertEqual(out["extra"]["environment"]["branch"], "eric/rolling-capture")
        # Content-free: ONLY ids/branch were added; no step content invented.
        self.assertEqual(out["steps"], [])
        # The resolved group key is now task-keyed (not ungrouped).
        from capture_store_core import group_key_for
        self.assertEqual(
            group_key_for(out["extra"].get("sdlc_task_id"),
                          out["extra"].get("sdlc_spec_id"),
                          out["extra"]["environment"].get("branch")), "T6")

    def test_re_derive_artifact_is_unchanged_idempotent(self):
        # An artifact that ALREADY carries the identity (the re-derive arm): the block
        # is a no-op — nothing is overwritten.
        repo = self.root / "repo"
        repo.mkdir()
        _init_git_repo(repo, "some/other-branch")
        before = {"schema_version": "ATIF-v1.7", "session_id": "s1",
                  "extra": {"sdlc_task_id": "ORIG-T", "sdlc_spec_id": "ORIG-S",
                            "environment": {"branch": "orig/branch"}}, "steps": []}
        self._write_artifact(before)
        res = _run_bash(self.block, cwd=repo, env=self._env(task="T6", spec="S2"))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        out = self._read_artifact()
        self.assertEqual(out["extra"]["sdlc_task_id"], "ORIG-T")
        self.assertEqual(out["extra"]["sdlc_spec_id"], "ORIG-S")
        self.assertEqual(out["extra"]["environment"]["branch"], "orig/branch")

    def test_off_git_no_task_leaves_artifact_identity_free(self):
        # OFF-GIT (cwd not a repo) with no task/spec: git yields no branch and the
        # empty ids are absent, so the artifact stays identity-free and the key stays
        # 'ungrouped' (accepted; no real arc). Only ids/branch could ever be written.
        nogit = self.root / "nogit"
        nogit.mkdir()
        self._write_artifact({"schema_version": "ATIF-v1.7", "session_id": "s1",
                              "extra": {}, "steps": []})
        res = _run_bash(self.block, cwd=nogit, env=self._env(task="", spec=""))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        out = self._read_artifact()
        self.assertNotIn("sdlc_task_id", out["extra"])
        self.assertNotIn("sdlc_spec_id", out["extra"])
        self.assertNotIn("environment", out["extra"])
        from capture_store_core import group_key_for
        self.assertEqual(
            group_key_for(out["extra"].get("sdlc_task_id"),
                          out["extra"].get("sdlc_spec_id"), None), "ungrouped")


class TestStep9ArcSummaryWiring(unittest.TestCase):
    """Step 9 prints the content-free arc summary from a seeded REAL index, resolving
    the branch key the same way the writers do (via git). No mocks."""

    ARC_ANCHOR = "Step 9 (after the gate/save/upload)"

    def setUp(self):
        self.tmp = _tempfile.TemporaryDirectory()
        self.root = _Path(self.tmp.name)
        self.home = self.root / "home"
        (self.home / ".driver" / "capture").mkdir(parents=True)
        self.index_path = self.home / ".driver" / "capture" / "index.json"
        self.block = _extract_bash_block(self.ARC_ANCHOR)

    def tearDown(self):
        self.tmp.cleanup()

    def _env(self):
        return {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
                "HOME": str(self.home)}

    def _write_index(self, index):
        self.index_path.write_text(_json.dumps(index))

    def test_seeded_branch_index_prints_arc(self):
        # A branch:x index with two sessions -> "arc branch:x: 2 session(s), <Σsteps>
        # steps, $<Σcost>", read by the SAME branch:x the writers key with.
        repo = self.root / "repo"
        repo.mkdir()
        _init_git_repo(repo, "x")
        self._write_index({"branch:x": {
            "s1": {"session_id": "s1", "record_count": 3, "total_cost_usd": 0.10},
            "s2": {"session_id": "s2", "record_count": 5, "total_cost_usd": 0.25},
        }})
        res = _run_bash(self.block, cwd=repo, env=self._env())
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout.strip(),
                         "arc branch:x: 2 session(s), 8 steps, $0.3500")

    def test_ungrouped_off_git_prints_nothing(self):
        # OFF-GIT: no branch -> group_key_for -> 'ungrouped' -> no arc printed, no crash.
        nogit = self.root / "nogit"
        nogit.mkdir()
        self._write_index({"branch:x": {
            "s1": {"session_id": "s1", "record_count": 3, "total_cost_usd": 0.10}}})
        res = _run_bash(self.block, cwd=nogit, env=self._env())
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout.strip(), "")

    def test_empty_index_prints_nothing(self):
        # An empty index (no matching group) -> nothing printed, no crash.
        repo = self.root / "repo"
        repo.mkdir()
        _init_git_repo(repo, "x")
        self._write_index({})
        res = _run_bash(self.block, cwd=repo, env=self._env())
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout.strip(), "")

    def test_missing_index_prints_nothing(self):
        # No index file at all -> the block fails open (|| true), prints nothing.
        repo = self.root / "repo"
        repo.mkdir()
        _init_git_repo(repo, "x")
        # (index.json intentionally not written)
        res = _run_bash(self.block, cwd=repo, env=self._env())
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
