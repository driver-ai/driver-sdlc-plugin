"""Unit tests for render_trace's pure cores (scripts/capture/render_trace.py).

render_trace is the review surface: a heuristic FLAGGING scan (broader than the
masking core — flags for human eyes, never masks), a pure HTML builder, and the
egress-safe in-chat summary. These are pure functions (values in, values out), so
every assertion is on a direct return value — no mocks, stdlib only.

`scan` / `_entropy` / `_benign_blob` / `render` exist in the spike; `_build_meta`
and `format_inline_summary` land in Task 3 (so those two tests are red until then).
"""

import sys
import unittest

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import render_trace


def _step(step_id, source, **kw):
    s = {"step_id": step_id, "source": source}
    s.update(kw)
    return s


class TestScan(unittest.TestCase):
    """The heuristic flagging scan over a trajectory's reviewable strings."""

    def test_scan_detects_each_type(self):
        # One step whose message carries a sample of every SCAN label, each on its
        # own line so the patterns don't cross-match.
        msg = "\n".join([
            "aws AKIAIOSFODNN7EXAMPLE",
            "anthropic sk-ant-0123456789abcdefghij",
            "github ghp_0123456789abcdefABCD0123",
            "slack xoxb-12345678abcd",
            "google AIzaSyA1234567890abcdefghijk",
            "-----BEGIN RSA PRIVATE KEY-----",
            "auth Bearer abcdef0123456789ABCDEF",
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fw",
            "email alice@example.com",
            "ip 10.0.0.42",
            "DATABASE_PASSWORD=hunter2supersecret",
        ])
        traj = {"steps": [_step(1, "agent", message=msg)]}
        findings = render_trace.scan(traj)
        types = {f["type"] for f in findings}
        expected = {
            "AWS access key id", "OpenAI/Anthropic key", "GitHub token",
            "Slack token", "Google API key", "Private key block",
            "Bearer token", "JWT", "Email address", "IPv4 address",
            "Secret-ish assignment",
        }
        self.assertTrue(expected.issubset(types),
                        f"missing labels: {expected - types}")

    def test_scan_dedups_identical(self):
        # Same value at the same location collapses to a single finding.
        traj = {"steps": [_step(1, "agent",
                                message="AKIAIOSFODNN7EXAMPLE and again AKIAIOSFODNN7EXAMPLE")]}
        findings = render_trace.scan(traj)
        aws = [f for f in findings if f["type"] == "AWS access key id"]
        self.assertEqual(len(aws), 1)

    def test_scan_ranks_hard_secrets_first(self):
        # A hard secret (rank 0) must sort ahead of an email (rank 2).
        traj = {"steps": [_step(1, "agent",
                                message="contact alice@example.com key AKIAIOSFODNN7EXAMPLE")]}
        findings = render_trace.scan(traj)
        order = [f["type"] for f in findings]
        self.assertIn("AWS access key id", order)
        self.assertIn("Email address", order)
        self.assertLess(order.index("AWS access key id"), order.index("Email address"))

    def test_scan_entropy_and_benign(self):
        # _entropy: empty / single-char -> 0; a 25-distinct-char token -> high.
        self.assertEqual(render_trace._entropy(""), 0.0)
        self.assertEqual(render_trace._entropy("aaaaaaaa"), 0.0)
        high_token = "Xq7Bv9Zk2Lm4Np6Rs8Tw0Yc3J"  # 26 distinct chars
        self.assertGreaterEqual(render_trace._entropy(high_token), 4.0)

        # _benign_blob: git SHAs, sha256, hex32, UUID, all-digits -> True.
        self.assertTrue(render_trace._benign_blob("a1b2c3d"))                 # 7-hex
        self.assertTrue(render_trace._benign_blob("0" * 40))                  # git SHA
        self.assertTrue(render_trace._benign_blob("0" * 64))                  # sha256
        self.assertTrue(render_trace._benign_blob("0" * 32))                  # hex32
        self.assertTrue(render_trace._benign_blob("12345678-1234-1234-1234-123456789abc"))
        self.assertTrue(render_trace._benign_blob("1234567890"))             # all digits
        self.assertFalse(render_trace._benign_blob(high_token))

        # Through scan: a benign 40-hex blob yields NO high-entropy finding;
        # a genuine high-entropy token does.
        benign = {"steps": [_step(1, "agent", message="sha " + "a" * 40)]}
        self.assertFalse(any(f["type"] == "High-entropy string"
                             for f in render_trace.scan(benign)))
        spicy = {"steps": [_step(1, "agent", message="tok " + high_token)]}
        self.assertTrue(any(f["type"] == "High-entropy string"
                            for f in render_trace.scan(spicy)))


class TestRender(unittest.TestCase):
    """The pure HTML builder."""

    def _traj(self):
        return {
            "schema_version": "ATIF-v1.7",
            "session_id": "sess-1",
            "agent": {"name": "claude-code"},
            "extra": {"sdlc_task_id": "T1", "sdlc_spec_id": "S1", "sdlc_intent": "do it"},
            "final_metrics": {"total_steps": 2, "total_completion_tokens": 40,
                              "total_cost_usd": 1.23},
            "steps": [
                _step(1, "agent", message="hello world",
                      metrics={"prompt_tokens": 100, "completion_tokens": 10, "cost_usd": 0.5}),
                _step(2, "user", message="a question"),
            ],
        }

    def test_render_is_pure_html(self):
        traj = self._traj()
        findings = [{"type": "Email address", "where": "step 1 message",
                     "snippet": "x 〈a@b.co〉 y"}]
        out = render_trace.render(traj, findings)
        self.assertIsInstance(out, str)
        self.assertIn("<!doctype html", out)
        # Flag block present with the finding type + count.
        self.assertIn("Email address", out)
        self.assertIn("potential sensitive item", out)
        # Step rows present (message text rendered, both step sources).
        self.assertIn("hello world", out)
        self.assertIn("a question", out)
        # Deterministic: same inputs -> identical output (no time/random/I/O).
        self.assertEqual(out, render_trace.render(self._traj(), list(findings)))

    def test_render_no_findings_block(self):
        out = render_trace.render(self._traj(), [])
        self.assertIn("no obvious sensitive content", out)


class TestBuildMeta(unittest.TestCase):
    """`_build_meta` (Task 3): pure Contract-A -> summary-meta mapping."""

    def test_build_meta_mapping(self):
        traj = {
            "session_id": "sess-1",
            "steps": [
                _step(1, "agent",
                      tool_calls=[{"function_name": "Bash"}, {"function_name": "Read"}],
                      metrics={"prompt_tokens": 100, "cached_tokens": 20, "completion_tokens": 10}),
                _step(2, "user",
                      metrics={"prompt_tokens": 50, "cached_tokens": 5, "completion_tokens": 0}),
                _step(3, "agent",
                      tool_calls=[{"function_name": "Bash"}],
                      metrics={"prompt_tokens": 200, "cached_tokens": 50, "completion_tokens": 30}),
            ],
            "final_metrics": {"total_steps": 3, "total_completion_tokens": 40,
                              "total_cost_usd": 1.23},
            "extra": {"sdlc_task_id": "T1", "sdlc_spec_id": "S1", "sdlc_intent": "do the thing"},
        }
        meta = render_trace._build_meta(traj)
        self.assertEqual(meta["task_id"], "T1")
        self.assertEqual(meta["spec_id"], "S1")
        self.assertEqual(meta["intent"], "do the thing")
        self.assertEqual(meta["session_id"], "sess-1")
        self.assertEqual(meta["steps"], 3)
        self.assertEqual(meta["agent_steps"], 2)
        self.assertEqual(meta["user_steps"], 1)
        self.assertEqual(meta["tools"], ["Bash", "Read"])  # sorted, unique, names only
        self.assertEqual(meta["completion_tokens"], 40)
        self.assertEqual(meta["peak_context"], 250)        # max(120, 55, 250)
        self.assertEqual(meta["cost_usd"], 1.23)

    def test_build_meta_zero_steps(self):
        meta = render_trace._build_meta({})
        self.assertEqual(meta["steps"], 0)
        self.assertEqual(meta["agent_steps"], 0)
        self.assertEqual(meta["user_steps"], 0)
        self.assertEqual(meta["tools"], [])
        self.assertEqual(meta["peak_context"], 0)
        self.assertEqual(meta["completion_tokens"], 0)
        self.assertEqual(meta["cost_usd"], 0.0)


class TestFormatInlineSummary(unittest.TestCase):
    """`format_inline_summary` (Task 3): egress-safe in-chat block.

    Consumes ONLY metadata + flag counts — never step content — so the summary
    cannot leak trajectory text into the conversation. (The four-content-field
    egress proof against the real --summary subprocess is in test_capture_integration.)
    """

    def _meta(self):
        return {
            "task_id": "T1", "spec_id": "S1", "intent": "do the thing",
            "session_id": "sess-1", "steps": 3, "agent_steps": 2, "user_steps": 1,
            "tools": ["Bash", "Read"], "completion_tokens": 40,
            "peak_context": 250, "cost_usd": 1.23,
        }

    def test_format_inline_summary_is_metadata_only(self):
        flags = [{"type": "openai_key", "count": 2}, {"type": "email", "count": 1}]
        out = render_trace.format_inline_summary(self._meta(), flags)
        self.assertIsInstance(out, str)
        for token in ("T1", "S1", "3", "40", "1.23", "250", "Bash", "Read"):
            self.assertIn(token, out, f"summary missing {token!r}")
        # Flag type + count surfaced.
        self.assertIn("openai_key", out)
        self.assertIn("2", out)
        # Deterministic.
        self.assertEqual(out, render_trace.format_inline_summary(self._meta(), list(flags)))

    def test_format_inline_summary_no_flags_zero_metrics(self):
        meta = {
            "task_id": None, "spec_id": None, "intent": None, "session_id": None,
            "steps": 0, "agent_steps": 0, "user_steps": 0, "tools": [],
            "completion_tokens": 0, "peak_context": 0, "cost_usd": 0.0,
        }
        out = render_trace.format_inline_summary(meta, [])
        self.assertIsInstance(out, str)
        self.assertIn("0", out)             # "0 steps" renders, no crash
        self.assertIn("no flags", out.lower())


def _subagent(trajectory_id, *, subagent_type=None, steps=None, total_cost_usd=0.0):
    """A serialized subagent trajectory in the Plan-01 emitted shape: a flat entry
    under the parent's `subagent_trajectories` with its own `trajectory_id`, `steps`,
    `final_metrics`, and an optional `extra.subagent_type` (key absent when None)."""
    sub = {
        "trajectory_id": trajectory_id,
        "steps": steps or [],
        "final_metrics": {"total_steps": len(steps or []),
                          "total_cost_usd": total_cost_usd},
    }
    if subagent_type is not None:
        sub["extra"] = {"subagent_type": subagent_type}
    return sub


class TestBuildMetaSubagents(unittest.TestCase):
    """`_build_meta` surfaces metadata-only subagent counts (no step content)."""

    def test_subagent_counts_match_fixture(self):
        traj = {
            "session_id": "sess-1",
            "steps": [_step(1, "agent", message="parent work")],
            "final_metrics": {"total_steps": 1, "total_completion_tokens": 5,
                              "total_cost_usd": 1.0},
            "subagent_trajectories": [
                _subagent("sess-1/agent-a", subagent_type="explorer",
                          steps=[_step(1, "agent", message="a1"),
                                 _step(2, "agent", message="a2")],
                          total_cost_usd=0.25),
                _subagent("sess-1/agent-b", subagent_type="reviewer",
                          steps=[_step(1, "agent", message="b1")],
                          total_cost_usd=0.125),
            ],
        }
        meta = render_trace._build_meta(traj)
        self.assertEqual(meta["subagents"], 2)
        self.assertEqual(meta["subagent_steps"], 3)         # 2 + 1
        self.assertEqual(meta["subagent_cost_usd"], 0.375)  # 0.25 + 0.125

    def test_zero_subagents(self):
        traj = {
            "session_id": "sess-1",
            "steps": [_step(1, "agent", message="solo")],
            "final_metrics": {"total_steps": 1, "total_completion_tokens": 0,
                              "total_cost_usd": 0.0},
        }
        meta = render_trace._build_meta(traj)
        self.assertEqual(meta["subagents"], 0)
        self.assertEqual(meta["subagent_steps"], 0)
        self.assertEqual(meta["subagent_cost_usd"], 0.0)


class TestFormatInlineSummarySubagents(unittest.TestCase):
    """The in-chat subagent line is metadata/counts-only.

    The egress sentinel here is NON-VACUOUS: subagent step content and the
    free-text subagent_type are planted via `_build_meta`'s input, the
    `Subagents:` metadata line is asserted PRESENT (so the subagent path
    actually executed), and the planted strings are asserted absent.
    """

    def _meta(self, subagents=2, subagent_steps=3, subagent_cost_usd=0.375):
        return {
            "task_id": "T1", "spec_id": "S1", "intent": "do the thing",
            "session_id": "sess-1", "steps": 3, "agent_steps": 2, "user_steps": 1,
            "tools": ["Bash", "Read"], "completion_tokens": 40,
            "peak_context": 250, "cost_usd": 1.23,
            "subagents": subagents, "subagent_steps": subagent_steps,
            "subagent_cost_usd": subagent_cost_usd,
        }

    def test_subagent_line_present_when_nonzero(self):
        out = render_trace.format_inline_summary(self._meta(), [])
        self.assertIn("Subagents:", out)
        self.assertIn("2", out)      # subagent count
        self.assertIn("3", out)      # subagent steps
        self.assertIn("0.375", out)  # subagent cost

    def test_subagent_line_absent_when_zero(self):
        out = render_trace.format_inline_summary(
            self._meta(subagents=0, subagent_steps=0, subagent_cost_usd=0.0), [])
        self.assertNotIn("Subagents:", out)
        # The metadata-only invariant is unchanged: the rest of the block renders.
        self.assertIn("Steps:", out)
        self.assertIn("Redaction flags:", out)

    def test_subagent_line_omitted_when_key_absent(self):
        # A meta with no subagent keys at all (zero-subagent _build_meta) must not
        # crash and must not print a Subagents line.
        meta = {
            "task_id": "T1", "spec_id": "S1", "intent": "x", "session_id": "s",
            "steps": 1, "agent_steps": 1, "user_steps": 0, "tools": [],
            "completion_tokens": 0, "peak_context": 0, "cost_usd": 0.0,
        }
        out = render_trace.format_inline_summary(meta, [])
        self.assertNotIn("Subagents:", out)

    def test_subagent_egress_sentinel_non_vacuous(self):
        # Plant sentinels in a subagent step message AND extra.subagent_type, then
        # run _build_meta -> format_inline_summary end to end. The Subagents line
        # must appear (proves the subagent path ran), and neither sentinel may leak.
        step_sentinel = "ZZ_SUBAGENT_STEP_SENTINEL_a1b2c3_ZZ"
        type_sentinel = "ZZ_SUBAGENT_TYPE_SENTINEL_d4e5f6_ZZ"
        traj = {
            "session_id": "sess-1",
            "steps": [_step(1, "agent", message="parent")],
            "final_metrics": {"total_steps": 1, "total_completion_tokens": 0,
                              "total_cost_usd": 0.0},
            "subagent_trajectories": [
                _subagent("sess-1/agent-a", subagent_type=type_sentinel,
                          steps=[_step(1, "agent", message=step_sentinel)],
                          total_cost_usd=0.5),
            ],
        }
        meta = render_trace._build_meta(traj)
        out = render_trace.format_inline_summary(meta, [])
        # (2) the subagent path executed -> the metadata line is present.
        self.assertIn("Subagents:", out)
        self.assertIn("1", out)     # one subagent, one step
        # (3) neither planted content string leaks into the in-chat block.
        self.assertNotIn(step_sentinel, out,
                         "subagent step message leaked into the summary")
        self.assertNotIn(type_sentinel, out,
                         "free-text subagent_type leaked into the summary")


class TestScanSubagents(unittest.TestCase):
    """`scan` walks the parent AND every subagent, with the owning trajectory_id
    in the dedup key so same-numbered (step 1) parent/subagent secrets stay
    distinct findings."""

    def test_same_secret_parent_and_subagent_yields_two_findings(self):
        secret = "AKIAIOSFODNN7EXAMPLE"
        traj = {
            "steps": [_step(1, "agent", message=f"parent {secret}")],
            "subagent_trajectories": [
                _subagent("sess/agent-a", subagent_type="explorer",
                          steps=[_step(1, "agent", message=f"subagent {secret}")]),
            ],
        }
        findings = render_trace.scan(traj)
        aws = [f for f in findings if f["type"] == "AWS access key id"]
        self.assertEqual(len(aws), 2,
                         "identical secret in parent step 1 and subagent step 1 "
                         "must report as two findings")

    def test_subagent_only_secret_is_reported(self):
        secret = "AKIAIOSFODNN7EXAMPLE"
        traj = {
            "steps": [_step(1, "agent", message="nothing sensitive here")],
            "subagent_trajectories": [
                _subagent("sess/agent-a", subagent_type="reviewer",
                          steps=[_step(1, "agent", message=f"hidden {secret}")]),
            ],
        }
        findings = render_trace.scan(traj)
        aws = [f for f in findings if f["type"] == "AWS access key id"]
        self.assertEqual(len(aws), 1)


class TestListContentMessages(unittest.TestCase):
    """render_trace is the human review surface: list[ContentPart] messages must
    be scannable (a secret inside a text part is a finding) and displayed
    (flattened via the shared flatten_content), never invisible."""

    def test_scan_sees_secrets_inside_list_message(self):
        secret = "AKIAIOSFODNN7EXAMPLE"
        traj = {"steps": [_step(1, "agent", message=[
            {"type": "text", "text": f"leaked {secret}"},
            {"type": "image",
             "source": {"media_type": "image/png", "path": "/tmp/shot.png"}},
        ])]}
        findings = render_trace.scan(traj)
        aws = [f for f in findings if f["type"] == "AWS access key id"]
        self.assertEqual(len(aws), 1,
                         "a secret inside a list-form message must be scannable")

    def test_render_displays_list_message_flattened(self):
        traj = {
            "session_id": "sess-1",
            "steps": [_step(1, "agent", message=[
                {"type": "text", "text": "hello from a list part"},
                {"type": "image",
                 "source": {"media_type": "image/png", "path": "/tmp/shot.png"}},
            ])],
        }
        out = render_trace.render(traj, [])
        self.assertIn("hello from a list part", out)
        self.assertIn("[image: image/png /tmp/shot.png]", out)
        # No (HTML-escaped) Python list-repr of ContentPart dicts.
        self.assertNotIn("&#x27;type&#x27;", out)

    def test_str_message_scans_and_renders_as_today(self):
        # Backward compat: a pre-swap artifact (plain str message) is untouched.
        secret = "AKIAIOSFODNN7EXAMPLE"
        traj = {"session_id": "sess-1",
                "steps": [_step(1, "agent", message=f"plain {secret}")]}
        findings = render_trace.scan(traj)
        aws = [f for f in findings if f["type"] == "AWS access key id"]
        self.assertEqual(len(aws), 1)
        self.assertIn("plain", render_trace.render(traj, findings))


class TestSubagentLabel(unittest.TestCase):
    """Subagent labels read the converter-filled agent.name first, falling back
    to extra.subagent_type so pre-swap artifacts keep rendering."""

    def test_subagent_label_reads_agent_name_with_fallback(self):
        traj = {
            "steps": [],
            "subagent_trajectories": [
                {"trajectory_id": "s/a", "agent": {"name": "code-reviewer"},
                 "steps": [_step(1, "agent", message="a")]},
                {"trajectory_id": "s/b", "agent": {"name": "from-agent"},
                 "extra": {"subagent_type": "from-extra"},
                 "steps": [_step(1, "agent", message="b")]},
                {"trajectory_id": "s/c", "extra": {"subagent_type": "explorer"},
                 "steps": [_step(1, "agent", message="c")]},
            ],
        }
        # The label surfaces in the public HTML step headers (render()).
        html = render_trace.render(traj, [])
        # agent.name is the label.
        self.assertIn("subagent code-reviewer", html)
        # agent.name wins when both are present -- the extra value is not used.
        self.assertIn("subagent from-agent", html)
        self.assertNotIn("subagent from-extra", html)
        # Pre-swap artifact (extra.subagent_type only) keeps its label.
        self.assertIn("subagent explorer", html)


if __name__ == "__main__":
    unittest.main()
