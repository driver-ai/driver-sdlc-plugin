"""
Tests for friction capture system (Plan 03).

- TestPhaseTracking: phase file written on skill load
- TestPhaseMapping: all skills map to correct phases
- TestFrictionLog: JSONL friction log written when enabled
- TestFrictionDisabled: no friction log when disabled
- TestWrongPathDetection: wrong_path friction event on Edit to non-existent file
- TestLazinessAsFriction: laziness block also logs friction event
- TestBackwardCompatibility: driver-skills-*.txt still works
- TestHooksExitZero: error paths still exit 0
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = PLUGIN_ROOT / "hooks"


def _unique_sid(label):
    """Generate a unique session ID for a test."""
    return f"friction-{label}-{os.getpid()}"


def _write_config(friction_tracking: bool) -> Path:
    """Write a config.local.json in the plugin root. Returns path."""
    config_path = PLUGIN_ROOT / "config.local.json"
    config_path.write_text(json.dumps({"friction_tracking": friction_tracking}))
    return config_path


def _cleanup_config():
    """Remove config.local.json if it exists."""
    config_path = PLUGIN_ROOT / "config.local.json"
    if config_path.exists():
        config_path.unlink()


def _cleanup_tmp(session_id):
    """Remove all temp files for a session ID."""
    for pattern in ("driver-skills-", "driver-phase-", "driver-friction-"):
        p = Path(f"/tmp/{pattern}{session_id}.txt") if "friction" not in pattern else Path(f"/tmp/{pattern}{session_id}.log")
        if pattern == "driver-friction-":
            p = Path(f"/tmp/{pattern}{session_id}.log")
        else:
            p = Path(f"/tmp/{pattern}{session_id}.txt")
        if p.exists():
            p.unlink()


def run_track_skill_load(skill_name, session_id):
    """Run track-skill-load.sh with crafted Skill tool JSON."""
    input_data = json.dumps({
        "tool_name": "Skill",
        "tool_input": {"skill": skill_name},
        "session_id": session_id,
    })
    result = subprocess.run(
        ["bash", str(HOOKS_DIR / "track-skill-load.sh")],
        input=input_data, capture_output=True, text=True, timeout=10,
    )
    return result.returncode, result.stdout, result.stderr


def run_laziness_detector(tool_name, tool_input, session_id=None):
    """Run laziness-detector.py with crafted JSON stdin."""
    input_data = {
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    if session_id:
        input_data["session_id"] = session_id
    result = subprocess.run(
        [sys.executable, str(HOOKS_DIR / "laziness-detector.py")],
        input=json.dumps(input_data), capture_output=True, text=True, timeout=10,
    )
    parsed = None
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return result.returncode, result.stdout, parsed


class TestPhaseTracking(unittest.TestCase):
    """Pipe Skill tool JSON to track-skill-load.sh, verify phase file."""

    def setUp(self):
        self.sid = _unique_sid("phase-tracking")
        _cleanup_tmp(self.sid)

    def tearDown(self):
        _cleanup_tmp(self.sid)
        _cleanup_config()

    @unittest.skipIf(shutil.which("jq") is None, "jq not installed")
    def test_research_guidance_sets_research_phase(self):
        rc, _, _ = run_track_skill_load("research-guidance", self.sid)
        self.assertEqual(rc, 0)
        phase_file = Path(f"/tmp/driver-phase-{self.sid}.txt")
        self.assertTrue(phase_file.exists(), "Phase file should be created")
        self.assertEqual(phase_file.read_text().strip(), "Research")


class TestPhaseMapping(unittest.TestCase):
    """Verify all skills map to correct phases."""

    EXPECTED = {
        "research-guidance": "Research",
        "planning-guidance": "Planning",
        "implementation-guidance": "Implementation",
        "sdlc-orchestration": "Orchestration",
    }

    def setUp(self):
        self._sids = []

    def tearDown(self):
        for sid in self._sids:
            _cleanup_tmp(sid)
        _cleanup_config()

    def _sid(self, label):
        sid = _unique_sid(f"phase-map-{label}")
        self._sids.append(sid)
        return sid

    @unittest.skipIf(shutil.which("jq") is None, "jq not installed")
    def test_all_skill_phase_mappings(self):
        for skill, expected_phase in self.EXPECTED.items():
            sid = self._sid(skill)
            rc, _, _ = run_track_skill_load(skill, sid)
            self.assertEqual(rc, 0)
            phase_file = Path(f"/tmp/driver-phase-{sid}.txt")
            self.assertTrue(phase_file.exists(), f"Phase file missing for {skill}")
            self.assertEqual(phase_file.read_text().strip(), expected_phase,
                             f"Wrong phase for {skill}")

    @unittest.skipIf(shutil.which("jq") is None, "jq not installed")
    def test_unknown_skill_no_phase_file(self):
        sid = self._sid("unknown")
        rc, _, _ = run_track_skill_load("some-random-skill", sid)
        self.assertEqual(rc, 0)
        phase_file = Path(f"/tmp/driver-phase-{sid}.txt")
        self.assertFalse(phase_file.exists(),
                         "Phase file should NOT be created for unknown skill")


class TestFrictionLog(unittest.TestCase):
    """With friction_tracking: true, verify JSONL friction log."""

    def setUp(self):
        self.sid = _unique_sid("friction-log")
        _cleanup_tmp(self.sid)
        _write_config(True)

    def tearDown(self):
        _cleanup_tmp(self.sid)
        _cleanup_config()

    @unittest.skipIf(shutil.which("jq") is None, "jq not installed")
    def test_skill_load_creates_friction_event(self):
        rc, _, _ = run_track_skill_load("research-guidance", self.sid)
        self.assertEqual(rc, 0)
        log_file = Path(f"/tmp/driver-friction-{self.sid}.log")
        self.assertTrue(log_file.exists(), "Friction log should be created")
        lines = log_file.read_text().strip().splitlines()
        self.assertGreaterEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertIn("ts", event)
        self.assertEqual(event["type"], "skill_invoked")
        self.assertEqual(event["cost"], 0)
        self.assertIn("research-guidance", event["detail"])


class TestFrictionDisabled(unittest.TestCase):
    """With friction_tracking: false, verify no friction log created."""

    def setUp(self):
        self.sid = _unique_sid("friction-disabled")
        _cleanup_tmp(self.sid)
        _write_config(False)

    def tearDown(self):
        _cleanup_tmp(self.sid)
        _cleanup_config()

    @unittest.skipIf(shutil.which("jq") is None, "jq not installed")
    def test_no_friction_log_when_disabled(self):
        rc, _, _ = run_track_skill_load("research-guidance", self.sid)
        self.assertEqual(rc, 0)
        log_file = Path(f"/tmp/driver-friction-{self.sid}.log")
        self.assertFalse(log_file.exists(),
                         "Friction log should NOT be created when disabled")


class TestWrongPathDetection(unittest.TestCase):
    """Edit on non-existent file logs wrong_path friction event."""

    def setUp(self):
        self.sid = _unique_sid("wrong-path")
        _cleanup_tmp(self.sid)
        _write_config(True)

    def tearDown(self):
        _cleanup_tmp(self.sid)
        _cleanup_config()

    def test_edit_nonexistent_file_logs_wrong_path(self):
        rc, _, _ = run_laziness_detector(
            "Edit",
            {"file_path": "/tmp/does-not-exist-ever-12345.py",
             "new_string": "def real_code():\n    return 42\n"},
            session_id=self.sid,
        )
        self.assertEqual(rc, 0)
        log_file = Path(f"/tmp/driver-friction-{self.sid}.log")
        self.assertTrue(log_file.exists(), "Friction log should contain wrong_path event")
        lines = log_file.read_text().strip().splitlines()
        found = any(json.loads(line)["type"] == "wrong_path" for line in lines)
        self.assertTrue(found, "Expected a wrong_path friction event")


class TestLazinessAsFriction(unittest.TestCase):
    """Laziness block also logs friction event when enabled."""

    def setUp(self):
        self.sid = _unique_sid("laziness-friction")
        _cleanup_tmp(self.sid)
        _write_config(True)

    def tearDown(self):
        _cleanup_tmp(self.sid)
        _cleanup_config()

    def test_laziness_block_logs_friction(self):
        rc, stdout, parsed = run_laziness_detector(
            "Write",
            {"file_path": "src/app.py", "content": "# TODO: implement\n"},
            session_id=self.sid,
        )
        self.assertEqual(rc, 0)
        # Should still block
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["hookSpecificOutput"]["permissionDecision"], "deny")
        # Should also log friction
        log_file = Path(f"/tmp/driver-friction-{self.sid}.log")
        self.assertTrue(log_file.exists(), "Friction log should be written on laziness block")
        lines = log_file.read_text().strip().splitlines()
        found = any(json.loads(line)["type"] == "silent_failure" for line in lines)
        self.assertTrue(found, "Expected a silent_failure friction event for laziness block")


class TestBackwardCompatibility(unittest.TestCase):
    """driver-skills-*.txt still written with one-skill-per-line format."""

    def setUp(self):
        self.sid = _unique_sid("backward-compat")
        _cleanup_tmp(self.sid)

    def tearDown(self):
        _cleanup_tmp(self.sid)
        _cleanup_config()

    @unittest.skipIf(shutil.which("jq") is None, "jq not installed")
    def test_skills_file_still_written(self):
        run_track_skill_load("research-guidance", self.sid)
        run_track_skill_load("planning-guidance", self.sid)
        skills_file = Path(f"/tmp/driver-skills-{self.sid}.txt")
        self.assertTrue(skills_file.exists(), "Skills file should still be created")
        lines = skills_file.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "research-guidance")
        self.assertEqual(lines[1], "planning-guidance")


class TestHooksExitZero(unittest.TestCase):
    """Error paths (missing jq, bad JSON, missing config) still exit 0."""

    def test_track_skill_load_bad_json(self):
        result = subprocess.run(
            ["bash", str(HOOKS_DIR / "track-skill-load.sh")],
            input="NOT VALID JSON", capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

    def test_track_skill_load_empty_input(self):
        result = subprocess.run(
            ["bash", str(HOOKS_DIR / "track-skill-load.sh")],
            input="", capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

    def test_laziness_detector_bad_json(self):
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "laziness-detector.py")],
            input="NOT VALID JSON", capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

    def test_laziness_detector_missing_tool_input(self):
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "laziness-detector.py")],
            input=json.dumps({"tool_name": "Write"}),
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

    def test_laziness_detector_empty_input(self):
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "laziness-detector.py")],
            input="", capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
