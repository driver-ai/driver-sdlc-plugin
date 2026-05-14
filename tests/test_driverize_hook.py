"""
Tests for the driverize enforcement hooks.

- TestDriverFirstHook: driver-first.sh PreToolUse hook — conditional unlock behavior
- TestDriverizeTemplates: structural validation of settings, shadow agents, and version
- TestInjectDriverPolicy: inject-driver-policy.sh SessionStart hook — event-type awareness
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DRIVERIZE_MD = PLUGIN_ROOT / "commands" / "driverize.md"


def extract_template(section_prefix, fence_type="bash"):
    """Extract a fenced code block from driverize.md after a section header.

    Finds the line starting with section_prefix (e.g., '### 3.1:'),
    then extracts content between the next ```<fence_type> and ``` markers.
    """
    content = DRIVERIZE_MD.read_text()
    lines = content.splitlines()
    in_section = False
    in_fence = False
    fence_lines = []
    for line in lines:
        if line.startswith(section_prefix):
            in_section = True
            continue
        if in_section and not in_fence:
            if line.strip() == f"```{fence_type}":
                in_fence = True
                continue
        if in_fence:
            if line.strip() == "```":
                break
            fence_lines.append(line)
    return "\n".join(fence_lines) + "\n" if fence_lines else ""


def run_driver_first_hook(tool_name, tool_input=None, session_id="test-default",
                          flag_file_exists=False, token="test_token",
                          flag_content=None, unavailable=False):
    """Run driver-first.sh with crafted JSON stdin.

    Extracts the template from driverize.md, substitutes the verification token,
    writes to a temp file, and executes via subprocess.
    """
    script = extract_template("### 3.1:")
    script = script.replace("__DRIVER_VERIFY_TOKEN__", token)

    stdin_data = {
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input if tool_input is not None else {},
    }

    flag_file = Path(f"/tmp/driver-context-loaded-{session_id}")
    unavail_file = Path(f"/tmp/driver-unavailable-{session_id}")

    if flag_content is not None:
        flag_file.write_text(flag_content)
    elif flag_file_exists:
        flag_file.write_text(token)
    else:
        flag_file.unlink(missing_ok=True)

    if unavailable:
        unavail_file.touch()
    else:
        unavail_file.unlink(missing_ok=True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(script)
        tmp_path = f.name

    try:
        os.chmod(tmp_path, 0o755)
        result = subprocess.run(
            ["bash", tmp_path],
            input=json.dumps(stdin_data),
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        os.unlink(tmp_path)


def run_inject_driver_policy(session_id, event_type="startup", cwd=None):
    """Run inject-driver-policy.sh with crafted JSON stdin."""
    script = extract_template("### 3.2:")

    stdin_data = {
        "session_id": session_id,
        "type": event_type,
        "cwd": cwd or "/tmp",
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(script)
        tmp_path = f.name

    try:
        os.chmod(tmp_path, 0o755)
        result = subprocess.run(
            ["bash", tmp_path],
            input=json.dumps(stdin_data),
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        os.unlink(tmp_path)


class TestDriverFirstHook(unittest.TestCase):
    """Tests for the driver-first.sh PreToolUse hook — conditional unlock behavior."""

    _session_ids: list

    @classmethod
    def setUpClass(cls):
        if shutil.which("jq") is None:
            raise unittest.SkipTest("jq is not installed")

    def setUp(self):
        self._session_ids = []

    def tearDown(self):
        for sid in self._session_ids:
            Path(f"/tmp/driver-context-loaded-{sid}").unlink(missing_ok=True)
            Path(f"/tmp/driver-unavailable-{sid}").unlink(missing_ok=True)

    def _sid(self, label):
        sid = f"test-{label}-{os.getpid()}"
        self._session_ids.append(sid)
        return sid

    # --- Grep ---

    def test_grep_blocked_before_context(self):
        sid = self._sid("grep_blocked")
        rc, _, stderr = run_driver_first_hook("Grep", session_id=sid)
        self.assertEqual(rc, 2)
        self.assertIn("Driver", stderr)

    def test_grep_allowed_after_context(self):
        sid = self._sid("grep_allowed")
        rc, _, _ = run_driver_first_hook("Grep", session_id=sid, flag_file_exists=True)
        self.assertEqual(rc, 0)

    # --- Glob ---

    def test_glob_blocked_before_context(self):
        sid = self._sid("glob_blocked")
        rc, _, _ = run_driver_first_hook("Glob", session_id=sid)
        self.assertEqual(rc, 2)

    def test_glob_allowed_after_context(self):
        sid = self._sid("glob_allowed")
        rc, _, _ = run_driver_first_hook("Glob", session_id=sid, flag_file_exists=True)
        self.assertEqual(rc, 0)

    # --- Bash grep ---

    def test_bash_grep_blocked_before_context(self):
        sid = self._sid("bash_grep_blocked")
        rc, _, _ = run_driver_first_hook(
            "Bash", tool_input={"command": "grep -r pattern src/"},
            session_id=sid,
        )
        self.assertEqual(rc, 2)

    def test_bash_grep_allowed_after_context(self):
        sid = self._sid("bash_grep_allowed")
        rc, _, _ = run_driver_first_hook(
            "Bash", tool_input={"command": "grep -r pattern src/"},
            session_id=sid, flag_file_exists=True,
        )
        self.assertEqual(rc, 0)

    # --- Bash find ---

    def test_bash_find_blocked_before_context(self):
        sid = self._sid("bash_find_blocked")
        rc, _, _ = run_driver_first_hook(
            "Bash", tool_input={"command": "find . -name '*.py'"},
            session_id=sid,
        )
        self.assertEqual(rc, 2)

    def test_bash_find_allowed_after_context(self):
        sid = self._sid("bash_find_allowed")
        rc, _, _ = run_driver_first_hook(
            "Bash", tool_input={"command": "find . -name '*.py'"},
            session_id=sid, flag_file_exists=True,
        )
        self.assertEqual(rc, 0)

    # --- Agent Explore ---

    def test_agent_explore_blocked_before_context(self):
        sid = self._sid("agent_explore_blocked")
        rc, _, _ = run_driver_first_hook(
            "Agent", tool_input={"subagent_type": "Explore"},
            session_id=sid,
        )
        self.assertEqual(rc, 2)

    def test_agent_explore_allowed_after_context(self):
        sid = self._sid("agent_explore_allowed")
        rc, _, _ = run_driver_first_hook(
            "Agent", tool_input={"subagent_type": "Explore"},
            session_id=sid, flag_file_exists=True,
        )
        self.assertEqual(rc, 0)

    # --- Agent Plan ---

    def test_agent_plan_blocked_before_context(self):
        sid = self._sid("agent_plan_blocked")
        rc, _, _ = run_driver_first_hook(
            "Agent", tool_input={"subagent_type": "Plan"},
            session_id=sid,
        )
        self.assertEqual(rc, 2)

    def test_agent_plan_allowed_after_context(self):
        sid = self._sid("agent_plan_allowed")
        rc, _, _ = run_driver_first_hook(
            "Agent", tool_input={"subagent_type": "Plan"},
            session_id=sid, flag_file_exists=True,
        )
        self.assertEqual(rc, 0)

    # --- Agent general-purpose ---

    def test_agent_general_purpose_blocked_before_context(self):
        sid = self._sid("agent_gp_blocked")
        rc, _, _ = run_driver_first_hook(
            "Agent", tool_input={"subagent_type": "general-purpose"},
            session_id=sid,
        )
        self.assertEqual(rc, 2)

    def test_agent_general_purpose_allowed_after_context(self):
        sid = self._sid("agent_gp_allowed")
        rc, _, _ = run_driver_first_hook(
            "Agent", tool_input={"subagent_type": "general-purpose"},
            session_id=sid, flag_file_exists=True,
        )
        self.assertEqual(rc, 0)

    # --- Agent null subagent_type ---

    def test_agent_null_blocked_before_context(self):
        sid = self._sid("agent_null_blocked")
        rc, _, _ = run_driver_first_hook(
            "Agent", tool_input={"subagent_type": None},
            session_id=sid,
        )
        self.assertEqual(rc, 2)

    def test_agent_null_allowed_after_context(self):
        sid = self._sid("agent_null_allowed")
        rc, _, _ = run_driver_first_hook(
            "Agent", tool_input={"subagent_type": None},
            session_id=sid, flag_file_exists=True,
        )
        self.assertEqual(rc, 0)

    # --- MCP tools setting flag ---

    def test_mcp_gather_task_context_sets_flag(self):
        sid = self._sid("mcp_gather")
        flag_file = Path(f"/tmp/driver-context-loaded-{sid}")
        rc, _, _ = run_driver_first_hook(
            "mcp__driver-mcp__gather_task_context", session_id=sid,
        )
        self.assertEqual(rc, 0)
        self.assertTrue(flag_file.exists())
        self.assertEqual(flag_file.read_text().strip(), "test_token")

    def test_mcp_get_file_documentation_sets_flag(self):
        sid = self._sid("mcp_file_doc")
        flag_file = Path(f"/tmp/driver-context-loaded-{sid}")
        rc, _, _ = run_driver_first_hook(
            "mcp__driver-mcp__get_file_documentation", session_id=sid,
        )
        self.assertEqual(rc, 0)
        self.assertTrue(flag_file.exists())

    def test_mcp_get_source_file_sets_flag(self):
        sid = self._sid("mcp_source_file")
        flag_file = Path(f"/tmp/driver-context-loaded-{sid}")
        rc, _, _ = run_driver_first_hook(
            "mcp__driver-mcp__get_source_file", session_id=sid,
        )
        self.assertEqual(rc, 0)
        self.assertTrue(flag_file.exists())

    def test_mcp_get_codebase_names_does_not_set_flag(self):
        sid = self._sid("mcp_codebase_names")
        flag_file = Path(f"/tmp/driver-context-loaded-{sid}")
        rc, _, _ = run_driver_first_hook(
            "mcp__driver-mcp__get_codebase_names", session_id=sid,
        )
        self.assertEqual(rc, 0)
        self.assertFalse(flag_file.exists())

    # --- Read always allowed ---

    def test_read_always_allowed(self):
        sid = self._sid("read_allowed")
        rc, _, _ = run_driver_first_hook("Read", session_id=sid)
        self.assertEqual(rc, 0)

    # --- Unavailable fallback ---

    def test_driver_unavailable_allows_all(self):
        sid = self._sid("unavailable")
        for tool in ["Grep", "Glob", "Agent"]:
            tool_input = {"subagent_type": "Explore"} if tool == "Agent" else None
            rc, _, _ = run_driver_first_hook(
                tool, tool_input=tool_input, session_id=sid, unavailable=True,
            )
            self.assertEqual(rc, 0, f"{tool} should be allowed when Driver unavailable")

    # --- Invalid token ---

    def test_invalid_token_blocks(self):
        sid = self._sid("invalid_token")
        rc, _, _ = run_driver_first_hook(
            "Grep", session_id=sid, flag_content="wrong_token",
        )
        self.assertEqual(rc, 2)


class TestDriverizeTemplates(unittest.TestCase):
    """Structural validation tests for settings, shadow agents, and version."""

    def test_settings_template_deny_only_anti_tampering(self):
        """Deny array should contain only anti-tampering entries with corrected paths."""
        settings_json = extract_template("### 3.8:", fence_type="json")
        settings = json.loads(settings_json)
        deny = settings["permissions"]["deny"]
        expected = [
            "Bash(touch /tmp/driver-*)",
            "Bash(rm /tmp/driver-*)",
            "Bash(echo * > /tmp/driver-*)",
            "Bash(printf * > /tmp/driver-*)",
            "Bash(tee /tmp/driver-*)",
            "Bash(cp * /tmp/driver-*)",
        ]
        self.assertEqual(deny, expected)

    def test_settings_deny_matches_flag_path(self):
        """Deny patterns must use the same path prefix as the hook's flag files."""
        hook_script = extract_template("### 3.1:")
        settings_json = extract_template("### 3.8:", fence_type="json")
        settings = json.loads(settings_json)
        deny = settings["permissions"]["deny"]
        self.assertIn("driver-context-loaded", hook_script)
        self.assertIn("driver-unavailable", hook_script)
        for entry in deny:
            self.assertIn(
                "/tmp/driver-", entry,
                f"Deny rule '{entry}' should use hyphen path pattern /tmp/driver-*",
            )
            self.assertNotIn(
                "/tmp/driver:", entry,
                f"Deny rule '{entry}' should NOT use colon path pattern /tmp/driver:*",
            )

    def test_shadow_agents_have_grep_glob(self):
        """Shadow agent templates should include Grep and Glob in their tools lists."""
        for section in ["### 3.4:", "### 3.5:", "### 3.6:"]:
            template = extract_template(section, fence_type="markdown")
            tools_match = re.search(r"^tools:\s*(.+)$", template, re.MULTILINE)
            self.assertIsNotNone(tools_match, f"No tools: line found in {section}")
            tools_line = tools_match.group(1)
            self.assertIn("Grep", tools_line, f"Grep missing from {section}")
            self.assertIn("Glob", tools_line, f"Glob missing from {section}")

    def test_version_is_1_1(self):
        """DRIVERIZE_VERSION should be '1.1'."""
        content = DRIVERIZE_MD.read_text()
        match = re.search(r'DRIVERIZE_VERSION:\s*"([^"]+)"', content)
        self.assertIsNotNone(match, "DRIVERIZE_VERSION not found")
        self.assertEqual(match.group(1), "1.1")


class TestInjectDriverPolicy(unittest.TestCase):
    """Tests for inject-driver-policy.sh — event-type awareness."""

    _session_ids: list
    _mcp_dir: str

    @classmethod
    def setUpClass(cls):
        if shutil.which("jq") is None:
            raise unittest.SkipTest("jq is not installed")
        cls._mcp_dir = tempfile.mkdtemp()
        mcp_json = {"mcpServers": {"driver-mcp": {"command": "echo"}}}
        Path(cls._mcp_dir, ".mcp.json").write_text(json.dumps(mcp_json))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._mcp_dir, ignore_errors=True)

    def setUp(self):
        self._session_ids = []

    def tearDown(self):
        for sid in self._session_ids:
            Path(f"/tmp/driver-context-loaded-{sid}").unlink(missing_ok=True)
            Path(f"/tmp/driver-unavailable-{sid}").unlink(missing_ok=True)

    def _sid(self, label):
        sid = f"test-{label}-{os.getpid()}"
        self._session_ids.append(sid)
        return sid

    def _setup_flag(self, sid, token="test_token"):
        Path(f"/tmp/driver-context-loaded-{sid}").write_text(token)

    def test_compaction_preserves_flag(self):
        sid = self._sid("compact")
        self._setup_flag(sid)
        run_inject_driver_policy(sid, event_type="compact", cwd=self._mcp_dir)
        self.assertTrue(
            Path(f"/tmp/driver-context-loaded-{sid}").exists(),
            "Flag file should be preserved on compaction",
        )

    def test_startup_clears_flag(self):
        sid = self._sid("startup")
        self._setup_flag(sid)
        run_inject_driver_policy(sid, event_type="startup", cwd=self._mcp_dir)
        self.assertFalse(
            Path(f"/tmp/driver-context-loaded-{sid}").exists(),
            "Flag file should be cleared on startup",
        )

    def test_clear_clears_flag(self):
        sid = self._sid("clear")
        self._setup_flag(sid)
        run_inject_driver_policy(sid, event_type="clear", cwd=self._mcp_dir)
        self.assertFalse(
            Path(f"/tmp/driver-context-loaded-{sid}").exists(),
            "Flag file should be cleared on /clear",
        )

    def test_resume_preserves_flag(self):
        sid = self._sid("resume")
        self._setup_flag(sid)
        run_inject_driver_policy(sid, event_type="resume", cwd=self._mcp_dir)
        self.assertTrue(
            Path(f"/tmp/driver-context-loaded-{sid}").exists(),
            "Flag file should be preserved on resume",
        )


if __name__ == "__main__":
    unittest.main()
