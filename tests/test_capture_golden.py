"""Golden-fixture regression for the redaction spine.

Redaction golden -- `redaction_crafted.json`, a tiny crafted ATIF-shaped
trajectory with exactly one SYNTHETIC secret per union label. Pins the flag
output against `redaction_crafted_expected_flags.json` and asserts every
planted value is masked.

Pure goldens assert directly on `redact.redact_trajectory` /
`redact.redact_text` return values -- no mocks. Stdlib `unittest` only.
"""
import sys, unittest, json
from conftest import PLUGIN_ROOT
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))
import redact

FIX = PLUGIN_ROOT / "tests" / "fixtures" / "capture"


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


if __name__ == "__main__":
    unittest.main()
