"""Unit tests for the consolidated redaction core (scripts/capture/redact.py).

Redaction is the capture flow's load-bearing security control (DEC-010 one core,
DEC-020 typed tokens). These tests pin the union pattern coverage, whole-value
masking, no-double-count typing, benign-input safety, and idempotency. The core
is pure (values in, values out), so every assertion is on a direct return value —
no mocks, stdlib only.
"""

import sys, unittest
from conftest import PLUGIN_ROOT
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import redact


class TestRedactText(unittest.TestCase):
    def test_redact_text_each_pattern(self):
        # Every union label: a planted synthetic secret masks to its typed token.
        # The value is the input to redact; the assertion is that the typed token
        # for that label appears and the raw secret no longer does.
        cases = [
            # label, input string, raw fragment that must disappear
            ("aws_access_key_id", "key AKIAIOSFODNN7EXAMPLE here", "AKIAIOSFODNN7EXAMPLE"),
            ("anthropic_key", "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123", "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"),
            ("openai_key", "sk-abcdefghijklmnopqrstuvwxyz0123", "sk-abcdefghijklmnopqrstuvwxyz0123"),
            ("slack_token", "xoxb-0123456789-abcdefghij", "xoxb-0123456789-abcdefghij"),
            ("gitlab_token", "glpat-abcdefghijklmnopqrst", "glpat-abcdefghijklmnopqrst"),
            ("huggingface_token", "hf_" + "a" * 34, "hf_" + "a" * 34),
            ("twilio_account_sid", "AC" + "0" * 32, "AC" + "0" * 32),
            ("twilio_api_key", "SK" + "a" * 32, "SK" + "a" * 32),
            ("private_key_block", "-----BEGIN RSA PRIVATE KEY-----", "-----BEGIN RSA PRIVATE KEY-----"),
            ("bearer_token", "Authorization: Bearer abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz"),
        ]
        for label, text, raw in cases:
            with self.subTest(label=label):
                masked, counts = redact.redact_text(text)
                self.assertIn(f"[REDACTED:{label}]", masked,
                              f"{label}: expected typed token in {masked!r}")
                self.assertNotIn(raw, masked,
                                 f"{label}: raw secret leaked in {masked!r}")
                self.assertEqual(counts.get(label), 1)

        # --- Boundary: ghp_ with a 30-char body must be caught at {30,} ---
        ghp30 = "ghp_" + "a" * 30
        masked, counts = redact.redact_text(f"token={ghp30}")
        self.assertIn("[REDACTED:github_token]", masked)
        self.assertNotIn(ghp30, masked)

        # --- Boundary: AIza with a 30-char body must be caught at {30,} ---
        aiza30 = "AIza" + "b" * 30
        masked, counts = redact.redact_text(f"key {aiza30} end")
        self.assertIn("[REDACTED:google_api_key]", masked)
        self.assertNotIn(aiza30, masked)

        # --- M1: sk-ant-... labels anthropic_key, NOT openai_key (anthropic first) ---
        masked, counts = redact.redact_text("sk-ant-api03-zzzzzzzzzzzzzzzzzzzzzzzz")
        self.assertIn("[REDACTED:anthropic_key]", masked)
        self.assertNotIn("[REDACTED:openai_key]", masked)
        self.assertEqual(counts.get("anthropic_key"), 1)
        self.assertIsNone(counts.get("openai_key"))

        # --- Viewer ENV_SECRET parity: mid-line, not ^-anchored ---
        masked, counts = redact.redact_text("prefix text ACCESS_TOKEN=somesecretvalue trailing")
        self.assertIn("ACCESS_TOKEN=[REDACTED:env_secret_assignment]", masked)
        self.assertNotIn("somesecretvalue", masked)

        # --- Viewer ENV_SECRET parity: hyphenated name, case-insensitive ---
        masked, counts = redact.redact_text("x-api-key: somesecretvalue")
        self.assertIn("[REDACTED:env_secret_assignment]", masked)
        self.assertNotIn("somesecretvalue", masked)

    def test_redact_env_full_value(self):
        # H2: the WHOLE value (a quoted span including spaces) is masked, and the
        # name + separator are preserved.
        masked, counts = redact.redact_text('PASSWORD="a b c"')
        self.assertNotIn('"a b c"', masked)
        self.assertNotIn("a b c", masked)
        self.assertIn("[REDACTED:env_secret_assignment]", masked)
        self.assertTrue(
            "PASSWORD=[REDACTED:env_secret_assignment]" in masked
            or "PASSWORD = [REDACTED:env_secret_assignment]" in masked,
            f"name+separator not preserved: {masked!r}",
        )

    def test_redact_no_double_count(self):
        # M12: ANTHROPIC_API_KEY=sk-ant-<20+> yields exactly ONE flag, anthropic_key.
        # The specific pattern types the value first; the env pattern's
        # (?!\[REDACTED:) guard then declines the already-masked value.
        text = "ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
        masked, counts = redact.redact_text(text)
        self.assertEqual(counts.get("anthropic_key"), 1)
        self.assertIsNone(counts.get("env_secret_assignment"))
        self.assertIn("[REDACTED:anthropic_key]", masked)

    def test_redact_benign_untouched(self):
        # M6: the env pattern requires a COMPOUND secret word (API_KEY/_TOKEN/...),
        # so bare API/KEY substrings and ordinary content are not flagged.
        benign = [
            "MONKEY=banana",
            "PUBLIC_API_URL=https://x.com",
            "This is ordinary prose describing the API and a key concept.",
            "def add(a, b):\n    return a + b",
        ]
        for text in benign:
            with self.subTest(text=text):
                masked, counts = redact.redact_text(text)
                self.assertEqual(masked, text, f"benign input altered: {masked!r}")
                self.assertEqual(counts, {}, f"benign input flagged: {counts!r}")

    def test_redact_trajectory_flags_and_idempotent(self):
        # A small dict trajectory with secrets in nested strings, plus an explicit
        # env-assignment line so the idempotency check exercises the
        # (?!\[REDACTED:) guard.
        traj = {
            "steps": [
                {"message": "my key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"},
                {"reasoning": "and another sk-ant-api03-zzzzzzzzzzzzzzzzzzzzzzzz here"},
                {"observation": "config line ACCESS_TOKEN=somesecretvalue exposed"},
                {"tool": {"args": ["AKIAIOSFODNN7EXAMPLE"]}},
            ],
        }
        redacted, flags = redact.redact_trajectory(traj)

        # flags is a list of {type, count}.
        self.assertIsInstance(flags, list)
        for f in flags:
            self.assertEqual(set(f.keys()), {"type", "count"})

        # Sorted by count desc: anthropic_key (2) before the singletons.
        counts_by_type = {f["type"]: f["count"] for f in flags}
        self.assertEqual(counts_by_type.get("anthropic_key"), 2)
        self.assertEqual(counts_by_type.get("aws_access_key_id"), 1)
        self.assertEqual(counts_by_type.get("env_secret_assignment"), 1)
        descending = [f["count"] for f in flags]
        self.assertEqual(descending, sorted(descending, reverse=True))

        # Idempotent: re-running on the redacted output produces no new flags.
        rerun, rerun_flags = redact.redact_trajectory(redacted)
        self.assertEqual(rerun_flags, [])
        self.assertEqual(rerun, redacted)


if __name__ == "__main__":
    unittest.main()
