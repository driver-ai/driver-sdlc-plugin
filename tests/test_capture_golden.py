"""Golden-fixture regression for the convert/redact spine (Plan 01, Task 10).

Two regression surfaces, both asserted against committed fixtures:

  * Conversion golden -- `session_97f81a2c.scrubbed.jsonl`, a content-scrubbed
    REAL Claude Code session (DEC-025). Pins the normalize kernel's step count
    and total cost so a refactor that drifts the walk/pricing math fails loudly.
  * Redaction golden -- `redaction_crafted.json`, a tiny crafted ATIF-shaped
    trajectory with exactly one SYNTHETIC secret per union label. Pins the flag
    output against `redaction_crafted_expected_flags.json` and asserts every
    planted value is masked.

Functional-core / imperative-shell: the pure goldens assert directly on
`core.normalize` and `redact.redact_trajectory` return values -- no mocks. The
two harbor-dependent tests (`to_trajectory`, the CLI subprocess) are guarded by
`@unittest.skipUnless(_harbor_available(), ...)` because harbor is an external
dependency absent from the zero-dep CI path -- a named justification for not
running them, NOT a mock. When harbor is absent they SKIP cleanly. Stdlib
`unittest` only.
"""
import sys, unittest, json
from pathlib import Path
from conftest import PLUGIN_ROOT
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))
import cc_to_atif_core as core
import redact

FIX = PLUGIN_ROOT / "tests" / "fixtures" / "capture"


def _harbor_available():
    try:
        import harbor  # noqa: F401
        return True
    except Exception:
        return False


# The 13 union labels redact.PATTERNS covers (DEC-010 one core).
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


def _load_jsonl(path: Path) -> list[dict]:
    """Read a JSONL transcript exactly as the shell does (one json per line)."""
    records = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


class TestConversionGolden(unittest.TestCase):
    def test_normalize_golden_steps_and_cost(self):
        """Pure: the scrubbed real session normalizes to a pinned step count and
        total cost. No mocks -- a direct call into the kernel."""
        records = _load_jsonl(FIX / "session_97f81a2c.scrubbed.jsonl")
        session_id = next((r.get("sessionId") for r in records if r.get("sessionId")), None)
        n = core.normalize(
            records, session_id=session_id, task_id=None, spec_id=None,
            intent=None, exclude_session_id=None,
        )
        self.assertEqual(n.final_metrics["total_steps"], 45)
        self.assertLess(abs(n.final_metrics["total_cost_usd"] - 22.968098), 0.01)


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


@unittest.skipUnless(_harbor_available(), "harbor not installed (external dep)")
class TestToTrajectoryRoundtrip(unittest.TestCase):
    def test_to_trajectory_roundtrip(self):
        """skipUnless harbor (M11 + L5): crafted records with a DUPLICATE
        source_call_id (two tool_results for one tool_use_id) and a step with a
        None timestamp normalize, then map to a valid harbor Trajectory whose
        to_json_dict() satisfies Contract A (ATIF-v1.7, sequential step_id from
        1, within-step source_call_id)."""
        import cc_to_atif as adapter

        records = [
            {   # assistant turn with one tool_use (M11: one tool_use_id)
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
            {   # DUPLICATE tool_result for tu1 (M11: both must fold in)
                "type": "user", "isSidechain": False, "sessionId": "sess",
                "timestamp": "2026-06-25T00:00:02Z",
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "tu1", "content": "second"},
                ]},
            },
            {   # human turn with a None timestamp (L5: odd/None timestamp)
                "type": "user", "isSidechain": False, "sessionId": "sess",
                "timestamp": None,
                "message": {"content": [{"type": "text", "text": "thanks"}]},
            },
        ]
        n = core.normalize(
            records, session_id="sess", task_id=None, spec_id=None,
            intent=None, exclude_session_id=None,
        )
        # M11: both duplicate tool_results folded into the agent step.
        agent_step = n.steps[0]
        self.assertEqual(len(agent_step.observation_results), 2)
        for res in agent_step.observation_results:
            self.assertEqual(res["source_call_id"], "tu1")
        # L5: the human step carries a None timestamp through normalization.
        self.assertIsNone(n.steps[-1].timestamp)

        traj = adapter.to_trajectory(n)
        d = traj.to_json_dict()

        # Contract A.
        self.assertEqual(d["schema_version"], "ATIF-v1.7")
        step_ids = [s["step_id"] for s in d["steps"]]
        self.assertEqual(step_ids, list(range(1, len(step_ids) + 1)))
        # within-step source_call_id: the duplicate results reference tu1, which
        # is a tool_call in the SAME step. harbor accepted them (no exception).
        scids = {r["source_call_id"]
                 for s in d["steps"] if s.get("observation")
                 for r in s["observation"]["results"]}
        self.assertEqual(scids, {"tu1"})


@unittest.skipUnless(_harbor_available(), "harbor not installed (external dep)")
class TestCcToAtifMainWritesFile(unittest.TestCase):
    def test_cc_to_atif_main_writes_file(self):
        """skipUnless harbor: the CLI shell, driven via subprocess, writes a
        trajectory.json (exit 0) and populates extra.environment when an
        env-file with facts is passed; an empty transcript exits non-zero with
        clear stderr (no SystemExit/traceback dump)."""
        import subprocess, tempfile

        script = PLUGIN_ROOT / "scripts" / "capture" / "cc_to_atif.py"
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

            res = subprocess.run(
                [sys.executable, str(script), str(transcript),
                 "--out", str(out), "--env-file", str(env_file)],
                cwd=str(PLUGIN_ROOT), capture_output=True, text=True,
            )
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
            res2 = subprocess.run(
                [sys.executable, str(script), str(empty), "--out", str(out)],
                cwd=str(PLUGIN_ROOT), capture_output=True, text=True,
            )
            self.assertNotEqual(res2.returncode, 0)
            self.assertIn("error:", res2.stderr)
            self.assertNotIn("Traceback", res2.stderr)
            self.assertNotIn("SystemExit", res2.stderr)


if __name__ == "__main__":
    unittest.main()
