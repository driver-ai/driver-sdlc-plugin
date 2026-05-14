"""
Tests for plugin hooks.

- TestLazinessDetector: laziness-detector.py PreToolUse hook
- TestTrackSkillLoad: track-skill-load.sh PreToolUse hook
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def run_laziness_detector(tool_name, file_path, content_key, content_value):
    """Run laziness-detector.py with crafted JSON stdin.

    content_key is "content" for Write, "new_string" for Edit.
    Returns (returncode, stdout_text, parsed_json_or_none).
    """
    input_data = json.dumps({
        "tool_name": tool_name,
        "tool_input": {
            "file_path": file_path,
            content_key: content_value
        }
    })
    result = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "hooks" / "laziness-detector.py")],
        input=input_data, capture_output=True, text=True, timeout=10
    )
    parsed = None
    if result.stdout.strip():
        parsed = json.loads(result.stdout)
    return result.returncode, result.stdout, parsed


class TestLazinessDetector(unittest.TestCase):
    """Tests for hooks/laziness-detector.py."""

    # =========================================================================
    # Task 1: Block patterns
    # =========================================================================

    def test_blocks_todo_comment(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/app.py", "content", "# TODO: implement\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_blocks_fixme_comment(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/app.py", "content", "# FIXME\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_blocks_not_implemented_error(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/app.py", "content",
            "def foo():\n    raise NotImplementedError\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_blocks_empty_pass(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/app.py", "content",
            "def foo():\n    pass\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_blocks_ellipsis(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/app.py", "content",
            "def foo():\n    ...\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_blocks_implement_later(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/app.py", "content",
            "# implement this later\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_blocks_empty_arrow_function(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/app.ts", "content",
            "const f = () => {}\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_blocks_empty_function_body_js(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/app.js", "content",
            "function foo() {}\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_blocks_fatal_error_swift(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/App.swift", "content",
            'fatalError("not implemented")\n'
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_blocks_panic_go(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/main.go", "content",
            'panic("not implemented")\n'
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_blocks_unsupported_op_java(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/App.java", "content",
            "throw new UnsupportedOperationException()\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_edit_tool_checks_new_string(self):
        rc, stdout, parsed = run_laziness_detector(
            "Edit", "src/app.py", "new_string", "# TODO\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_deny_output_structure(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/app.py", "content", "# TODO: implement\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(parsed)
        self.assertIn("hookSpecificOutput", parsed)
        output = parsed["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertIn("permissionDecisionReason", output)

    # =========================================================================
    # Task 2: Allow / skip patterns
    # =========================================================================

    def test_allows_clean_code(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/app.py", "content",
            "def add(a, b):\n    return a + b\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNone(parsed)
        self.assertEqual(stdout.strip(), "")

    def test_skips_markdown_files(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "docs/notes.md", "content", "# TODO\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNone(parsed)
        self.assertEqual(stdout.strip(), "")

    def test_skips_json_files(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "config.json", "content", '{"key": "TODO"}\n'
        )
        self.assertEqual(rc, 0)
        self.assertIsNone(parsed)
        self.assertEqual(stdout.strip(), "")

    def test_skips_test_files(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "tests/test_foo.py", "content", "# TODO\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNone(parsed)
        self.assertEqual(stdout.strip(), "")

    def test_skips_spec_files(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write", "src/foo.spec.ts", "content", "// TODO\n"
        )
        self.assertEqual(rc, 0)
        self.assertIsNone(parsed)
        self.assertEqual(stdout.strip(), "")

    def test_failopen_invalid_json(self):
        result = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "hooks" / "laziness-detector.py")],
            input="this is not json at all",
            capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_failopen_missing_tool_input(self):
        input_data = json.dumps({"tool_name": "Write"})
        result = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "hooks" / "laziness-detector.py")],
            input=input_data, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


def run_track_skill_load(skill_name=None, session_id=None, raw_input=None):
    """Run track-skill-load.sh with crafted JSON stdin.
    If raw_input is provided, use it directly (for invalid JSON test).
    Returns (returncode, temp_file_path).
    """
    if raw_input is not None:
        input_data = raw_input
    else:
        data = {}
        if skill_name is not None:
            data["tool_input"] = {"skill": skill_name}
        if session_id is not None:
            data["session_id"] = session_id
        input_data = json.dumps(data)

    result = subprocess.run(
        ["bash", str(PLUGIN_ROOT / "hooks" / "track-skill-load.sh")],
        input=input_data, capture_output=True, text=True, timeout=10,
    )
    temp_file = Path(f"/tmp/driver-skills-{session_id}.txt") if session_id else None
    return result.returncode, temp_file


class TestTrackSkillLoad(unittest.TestCase):
    """Tests for hooks/track-skill-load.sh."""

    _session_ids: list  # collected for tearDown cleanup

    @classmethod
    def setUpClass(cls):
        if shutil.which("jq") is None:
            raise unittest.SkipTest("jq is not installed -- skipping track-skill-load tests")

    def setUp(self):
        self._session_ids = []

    def tearDown(self):
        for sid in self._session_ids:
            p = Path(f"/tmp/driver-skills-{sid}.txt")
            if p.exists():
                p.unlink()

    def _sid(self, label):
        """Generate a unique, test-scoped session ID and register it for cleanup."""
        sid = f"test-{label}-{os.getpid()}"
        self._session_ids.append(sid)
        return sid

    # ------------------------------------------------------------------

    def test_tracks_skill_name(self):
        """Valid input -- skill name appears in the temp file."""
        sid = self._sid("tracks_skill_name")
        rc, tmp = run_track_skill_load(skill_name="commit", session_id=sid)
        self.assertEqual(rc, 0)
        self.assertIsNotNone(tmp)
        self.assertTrue(tmp.exists(), f"Expected {tmp} to be created")
        self.assertIn("commit", tmp.read_text())

    def test_appends_multiple_skills(self):
        """Two invocations -- two lines in the temp file."""
        sid = self._sid("appends_multiple_skills")
        run_track_skill_load(skill_name="commit", session_id=sid)
        run_track_skill_load(skill_name="review-pr", session_id=sid)
        _, tmp = run_track_skill_load(skill_name="commit", session_id=sid)
        lines = tmp.read_text().strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "commit")
        self.assertEqual(lines[1], "review-pr")
        self.assertEqual(lines[2], "commit")

    def test_session_isolation(self):
        """Different session_ids -- different temp files."""
        sid_a = self._sid("session_isolation_a")
        sid_b = self._sid("session_isolation_b")
        run_track_skill_load(skill_name="alpha", session_id=sid_a)
        run_track_skill_load(skill_name="beta", session_id=sid_b)
        file_a = Path(f"/tmp/driver-skills-{sid_a}.txt")
        file_b = Path(f"/tmp/driver-skills-{sid_b}.txt")
        self.assertIn("alpha", file_a.read_text())
        self.assertNotIn("beta", file_a.read_text())
        self.assertIn("beta", file_b.read_text())
        self.assertNotIn("alpha", file_b.read_text())

    def test_missing_skill_name(self):
        """No skill in input -- exit 0, no file created."""
        sid = self._sid("missing_skill_name")
        rc, tmp = run_track_skill_load(skill_name=None, session_id=sid)
        self.assertEqual(rc, 0)
        self.assertFalse(tmp.exists(), "File should not be created when skill name is missing")

    def test_missing_session_id(self):
        """No session_id -- exit 0, no file created."""
        rc, tmp = run_track_skill_load(skill_name="commit", session_id=None)
        self.assertEqual(rc, 0)
        self.assertIsNone(tmp, "No temp file path expected when session_id is None")

    def test_invalid_json(self):
        """Bad JSON -- exit 0, no crash."""
        sid = self._sid("invalid_json")
        rc, _ = run_track_skill_load(raw_input="NOT VALID JSON {{{", session_id=None)
        self.assertEqual(rc, 0)
        self.assertFalse(Path(f"/tmp/driver-skills-{sid}.txt").exists())

    def test_always_exits_zero(self):
        """All scenarios exit 0."""
        sid = self._sid("always_exits_zero")
        scenarios = [
            dict(skill_name="x", session_id=sid),
            dict(skill_name=None, session_id=sid),
            dict(skill_name="x", session_id=None),
            dict(raw_input="broken json"),
            dict(raw_input=""),
        ]
        for kwargs in scenarios:
            rc, _ = run_track_skill_load(**kwargs)
            self.assertEqual(rc, 0, f"Expected exit 0 for kwargs={kwargs}")


class TestCommitArtifactsHook(unittest.TestCase):
    """Verify commit-artifacts.sh SessionEnd hook behavior."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.hook_path = str(PLUGIN_ROOT / "hooks" / "commit-artifacts.sh")

    def test_commit_artifacts_hook_exits_zero(self) -> None:
        """commit-artifacts.sh must exit 0 with empty stdin."""
        result = subprocess.run(
            ["sh", self.hook_path],
            input="{}",
            capture_output=True,
            text=True,
            cwd="/tmp",
        )
        self.assertEqual(result.returncode, 0)

    def test_commit_artifacts_hook_no_crash_on_missing_feature(self) -> None:
        """commit-artifacts.sh must handle missing FEATURE_LOG.md gracefully."""
        result = subprocess.run(
            ["sh", self.hook_path],
            input="{}",
            capture_output=True,
            text=True,
            cwd="/tmp",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
