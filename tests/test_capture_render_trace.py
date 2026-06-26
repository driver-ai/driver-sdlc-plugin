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


if __name__ == "__main__":
    unittest.main()
