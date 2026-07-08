"""Golden-fixture regression for the convert/redact spine.

Two regression surfaces, both asserted against committed fixtures:

  * Conversion golden -- `session_97f81a2c.scrubbed.jsonl`, a content-scrubbed
    REAL Claude Code session. Pins the wrapper's emitted artifact invariants
    (step count, source breakdown, token totals, cost, tool set) so a drift in
    the logs2atif pin or the wrapper's enrichment fails loudly.
  * Redaction golden -- `redaction_crafted.json`, a tiny crafted ATIF-shaped
    trajectory with exactly one SYNTHETIC secret per union label. Pins the flag
    output against `redaction_crafted_expected_flags.json` and asserts every
    planted value is masked.

Pure redaction goldens assert directly on `redact.redact_trajectory` /
`redact.redact_text` return values -- no mocks. Conversion goldens drive
`cc_to_atif.py` via subprocess, exactly as the rolling hook and the capture
command invoke it; they are gated with a named
`@unittest.skipUnless(_logs2atif_available(), ...)` because logs2atif is an
external dependency absent from the zero-dep CI path -- a named justification
for not running them, NOT a mock. When logs2atif is absent they SKIP cleanly.
Stdlib `unittest` only.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))
import redact

FIX = PLUGIN_ROOT / "tests" / "fixtures" / "capture"
SCRIPT = PLUGIN_ROOT / "scripts" / "capture" / "cc_to_atif.py"
FIXTURE = FIX / "session_97f81a2c.scrubbed.jsonl"
FIXTURE_SESSION_ID = "97f81a2c-7771-44df-a4f3-caaebb60cec7"


def _logs2atif_available() -> bool:
    try:
        import logs2atif  # noqa: F401
        return True
    except Exception:
        return False


def _run(transcript, *extra_args):
    """Run cc_to_atif.py from the repo root; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(transcript), *extra_args],
        cwd=str(PLUGIN_ROOT), capture_output=True, text=True,
    )


# The 13 union labels redact.PATTERNS covers (one shared core).
UNION_LABELS = {
    "aws_access_key_id", "anthropic_key", "openai_key", "github_token",
    "slack_token", "google_api_key", "gitlab_token", "huggingface_token",
    "twilio_account_sid", "twilio_api_key", "private_key_block",
    "bearer_token", "env_secret_assignment",
}

# Every SYNTHETIC secret planted in redaction_crafted.json. None is a real
# credential. The redacted output must contain none of these raw fragments.
PLANTED_SECRETS = [
    "AKIAAAAAAAAAAAAAAAAA",                          # aws_access_key_id
    "AIzaSyA1234567890abcdefghijklmnopqr",           # google_api_key
    "sk-ant-abcdefghijklmnopqrstuvwxy",              # anthropic_key
    "sk-abcdefghijklmnopqrstuvwxy",                  # openai_key
    "ghp_abcdefghijklmnopqrstuvwxyz0123",            # github_token
    "xoxb-1234567890-abcdefghij",                    # slack_token
    "glpat-abcdefghijklmnopqrstuv",                  # gitlab_token
    "hf_abcdefghijklmnopqrstuvwxyz0123",             # huggingface_token
    "AC0123456789abcdef0123456789abcdef",            # twilio_account_sid
    "SK0123456789abcdef0123456789abcdef",            # twilio_api_key
    "-----BEGIN RSA PRIVATE KEY-----",               # private_key_block
    "Bearer abcdefghijklmnopqrstuvwxyz0",            # bearer_token
    "supersecretvalue123",                           # env_secret_assignment value
]


@unittest.skipUnless(_logs2atif_available(), "logs2atif not installed (external dep)")
class TestConversionGolden(unittest.TestCase):
    def test_conversion_golden(self):
        """skipUnless logs2atif: the scrubbed real session converts through the
        wrapper to a pinned artifact shape.

        Every pinned value below was regenerated from a real wrapper run on
        this fixture at the pinned logs2atif commit (3364a76) and copied from
        that run's artifact -- not hand-computed, and not carried over from the
        previous bespoke converter (which emitted 45 steps for this fixture;
        logs2atif orders steps by timestamp and emits 46, with identical token
        totals).
        """
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "trajectory.json"
            res = _run(FIXTURE, "--out", str(out))
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            d = json.loads(out.read_text())

        self.assertEqual(d["schema_version"], "ATIF-v1.7")
        self.assertEqual(d["session_id"], FIXTURE_SESSION_ID)

        # Step count and source breakdown.
        steps = d["steps"]
        self.assertEqual(len(steps), 46)
        by_source = {}
        for s in steps:
            by_source[s["source"]] = by_source.get(s["source"], 0) + 1
        self.assertEqual(by_source, {"user": 10, "agent": 36})

        # Token totals and cost.
        fm = d["final_metrics"]
        self.assertEqual(fm["total_steps"], 46)
        self.assertEqual(fm["total_prompt_tokens"], 22324133)
        self.assertEqual(fm["total_completion_tokens"], 72609)
        self.assertEqual(fm["total_cached_tokens"], 20393039)
        self.assertGreater(fm["total_cost_usd"], 0)
        self.assertLess(abs(fm["total_cost_usd"] - 22.968097), 0.01)

        # Tool set.
        tools = {tc["function_name"] for s in steps
                 for tc in s.get("tool_calls") or []}
        self.assertEqual(tools, {"AskUserQuestion", "Bash", "Edit", "Read",
                                 "Skill", "Write"})


class TestRedactionGolden(unittest.TestCase):
    def test_redact_golden_stable(self):
        """Pure: the crafted trajectory's flags equal the committed expected
        flags; every planted synthetic secret is masked; all 13 union labels
        appear. No mocks."""
        traj = json.loads((FIX / "redaction_crafted.json").read_text())
        expected = json.loads((FIX / "redaction_crafted_expected_flags.json").read_text())

        redacted, flags = redact.redact_trajectory(traj)

        # Flags are byte-for-byte the committed golden (order included).
        self.assertEqual(flags, expected)

        # All 13 union labels present, each count >= 1.
        labels = {f["type"] for f in flags}
        self.assertEqual(labels, UNION_LABELS)
        for f in flags:
            self.assertGreaterEqual(f["count"], 1, f"{f['type']} count < 1")

        # No raw planted secret survives anywhere in the redacted output.
        blob = json.dumps(redacted)
        for secret in PLANTED_SECRETS:
            self.assertNotIn(secret, blob, f"raw secret leaked: {secret!r}")

    def test_redact_large_string_smoke(self):
        """Pure (L6): a multi-hundred-KB string with one embedded secret redacts
        promptly (no catastrophic backtracking) and masks the embedded secret."""
        import time
        secret = "ghp_" + "a" * 36   # github_token, well over {30,}
        big = ("benign filler line that is perfectly safe.\n" * 7000) + secret + "\ntail"
        self.assertGreater(len(big), 300_000)

        start = time.monotonic()
        masked, counts = redact.redact_text(big)
        elapsed = time.monotonic() - start

        self.assertNotIn(secret, masked, "embedded secret leaked from large string")
        self.assertIn("[REDACTED:github_token]", masked)
        self.assertEqual(counts.get("github_token"), 1)
        # Linear-time scan should be near-instant; a generous ceiling catches
        # pathological backtracking without flaking on slow CI.
        self.assertLess(elapsed, 5.0, f"redact_text took {elapsed:.2f}s on ~300KB")


@unittest.skipUnless(_logs2atif_available(), "logs2atif not installed (external dep)")
class TestToTrajectoryRoundtrip(unittest.TestCase):
    def test_wrapper_roundtrip_artifact_structure(self):
        """skipUnless logs2atif: crafted records with a DUPLICATE
        source_call_id (two tool_results for one tool_use_id) round-trip
        through the wrapper to an artifact satisfying Contract A (ATIF-v1.7,
        sequential step_id from 1, within-step source_call_id).

        The duplicate-result expectation was regenerated from a real wrapper
        run at the pinned logs2atif commit (3364a76): upstream folds the FIRST
        tool_result for a tool_use_id into the calling step and drops later
        duplicates (the previous bespoke converter kept both) -- the run
        succeeds either way, which is the contract the capture spine needs.
        """
        records = [
            {   # assistant turn with one tool_use
                "type": "assistant", "isSidechain": False, "sessionId": "sess",
                "timestamp": "2026-06-25T00:00:00Z",
                "message": {
                    "id": "m1", "model": "claude-opus-4-8-20260315",
                    "content": [
                        {"type": "text", "text": "calling a tool"},
                        {"type": "tool_use", "id": "tu1", "name": "read_file",
                         "input": {"path": "x"}},
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            },
            {   # FIRST tool_result for tu1
                "type": "user", "isSidechain": False, "sessionId": "sess",
                "timestamp": "2026-06-25T00:00:01Z",
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "tu1", "content": "first"},
                ]},
            },
            {   # DUPLICATE tool_result for tu1 (dropped upstream)
                "type": "user", "isSidechain": False, "sessionId": "sess",
                "timestamp": "2026-06-25T00:00:02Z",
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "tu1", "content": "second"},
                ]},
            },
            {   # trailing human turn
                "type": "user", "isSidechain": False, "sessionId": "sess",
                "timestamp": "2026-06-25T00:00:03Z",
                "message": {"content": [{"type": "text", "text": "thanks"}]},
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            transcript = tmp / "session.jsonl"
            transcript.write_text("\n".join(json.dumps(r) for r in records) + "\n")
            out = tmp / "trajectory.json"
            res = _run(transcript, "--out", str(out))
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            d = json.loads(out.read_text())

        # Contract A.
        self.assertEqual(d["schema_version"], "ATIF-v1.7")
        step_ids = [s["step_id"] for s in d["steps"]]
        self.assertEqual(step_ids, list(range(1, len(step_ids) + 1)))

        # The tool call and its folded result live in the SAME step; every
        # observation result's source_call_id references tu1 within that step.
        agent_step = next(s for s in d["steps"] if s.get("tool_calls"))
        self.assertEqual([tc["tool_call_id"] for tc in agent_step["tool_calls"]],
                         ["tu1"])
        results = agent_step["observation"]["results"]
        self.assertEqual([r["source_call_id"] for r in results], ["tu1"])
        self.assertEqual([r["content"] for r in results], ["first"])

        # The trailing human turn survives as the final user step.
        self.assertEqual(d["steps"][-1]["source"], "user")
        self.assertEqual(d["steps"][-1]["message"], "thanks")


@unittest.skipUnless(_logs2atif_available(), "logs2atif not installed (external dep)")
class TestCcToAtifMainWritesFile(unittest.TestCase):
    def test_cc_to_atif_main_writes_file(self):
        """skipUnless logs2atif: the CLI shell, driven via subprocess, writes a
        trajectory.json (exit 0) and populates extra.environment when an
        env-file with facts is passed; an empty transcript exits non-zero with
        clear stderr (no SystemExit/traceback dump)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            transcript = tmp / "session.jsonl"
            transcript.write_text(json.dumps({
                "type": "assistant", "isSidechain": False, "sessionId": "sess",
                "timestamp": "2026-06-25T00:00:00Z",
                "message": {
                    "id": "m1", "model": "claude-opus-4-8-20260315",
                    "content": [{"type": "text", "text": "hello"}],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            }) + "\n")
            env_file = tmp / "env.json"
            env_file.write_text(json.dumps({
                "branch": "eric/agent-session-capture",
                "cwd": "/work/repo",
            }))
            out = tmp / "trajectory.json"

            res = _run(transcript, "--out", str(out), "--env-file", str(env_file))
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            self.assertTrue(out.exists(), "trajectory.json not written")
            written = json.loads(out.read_text())
            self.assertIn("extra", written)
            self.assertIn("environment", written["extra"])
            self.assertEqual(written["extra"]["environment"]["branch"],
                             "eric/agent-session-capture")
            self.assertEqual(written["extra"]["environment"]["cwd"], "/work/repo")

            # Empty transcript -> non-zero exit, clear stderr, no traceback dump.
            empty = tmp / "empty.jsonl"
            empty.write_text("")
            res2 = _run(empty, "--out", str(out))
            self.assertNotEqual(res2.returncode, 0)
            self.assertIn("error:", res2.stderr)
            self.assertNotIn("Traceback", res2.stderr)
            self.assertNotIn("SystemExit", res2.stderr)


if __name__ == "__main__":
    unittest.main()
