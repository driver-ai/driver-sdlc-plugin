"""Shell tests for cc_to_atif `main()` --env-file handling (M5).

The shell imports harbor (`cc_to_atif` -> `from harbor.models.trajectories ...`),
which is an external dependency absent from the zero-dep CI path. So this whole
module is guarded by `@unittest.skipUnless(_harbor_available(), ...)` -- a named
justification for not running it, NOT a mock of harbor. When harbor is absent the
test SKIPS cleanly; that is expected.

It drives `cc_to_atif.py` via subprocess so the bare `import cc_to_atif_core` /
`import environment` / `import pricing` resolve via `sys.path[0]` (the script's own
directory), exactly as they do in real use.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT

SCRIPT = PLUGIN_ROOT / "scripts" / "capture" / "cc_to_atif.py"


def _harbor_available() -> bool:
    try:
        import harbor  # noqa: F401
        return True
    except Exception:
        return False


def _run(transcript, *extra_args):
    """Run cc_to_atif.py from the repo root; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(transcript), *extra_args],
        cwd=str(PLUGIN_ROOT), capture_output=True, text=True,
    )


# A tiny valid Claude Code JSONL transcript: one assistant turn so normalize()
# yields at least one step (avoids EmptyTranscriptError confounding the result).
TRANSCRIPT_LINES = [
    json.dumps({
        "type": "assistant", "isSidechain": False, "sessionId": "sess",
        "timestamp": "2026-06-25T00:00:00Z",
        "message": {
            "id": "m1", "model": "claude-opus-4-8-20260315",
            "content": [{"type": "text", "text": "hello"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    }),
]


@unittest.skipUnless(_harbor_available(), "harbor not installed")
class TestCcToAtifMainEnvFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.transcript = self.tmpdir / "session.jsonl"
        self.transcript.write_text("\n".join(TRANSCRIPT_LINES) + "\n")
        self.out = self.tmpdir / "trajectory.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_cc_to_atif_main_env_file_errors(self):
        # (a) Missing --env-file path -> non-zero exit, clear stderr, no raw traceback.
        missing = self.tmpdir / "does-not-exist.json"
        res = _run(self.transcript, "--env-file", str(missing), "--out", str(self.out))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("error:", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertNotIn("FileNotFoundError", res.stderr)

        # (b) Malformed JSON --env-file -> non-zero exit, clear stderr, no raw traceback.
        bad = self.tmpdir / "bad.json"
        bad.write_text("{ this is not valid json ")
        res = _run(self.transcript, "--env-file", str(bad), "--out", str(self.out))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("error:", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertNotIn("JSONDecodeError", res.stderr)

        # (c) Unknown keys in an otherwise-valid env-file are ignored -> exit 0.
        good = self.tmpdir / "good.json"
        good.write_text(json.dumps({
            "branch": "eric/agent-session-capture",
            "totally_unknown_key": "ignored",
            "another_bogus": 123,
        }))
        res = _run(self.transcript, "--env-file", str(good), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)


if __name__ == "__main__":
    unittest.main()
