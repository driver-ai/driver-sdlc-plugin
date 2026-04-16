"""
Structural tests for validation boundary hardening.

Verifies:
- Pre-flight check 2.5 (Codebase table consistency) exists in implementation-guidance SKILL.md
- Blocking check count updated to 9
- Pre-flight report format includes check 2.5
- Implementation-guidance Step 5.3 has upstream commit verification before cascade-check spawn
- sdlc-orchestration has upstream commit verification before cascade-check spawn
- cascade-check.md documents the design boundary (caller verifies commits)
"""

import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


class TestValidationBoundaryHardening(unittest.TestCase):
    """Structural tests for validation boundary hardening changes."""

    impl_guidance: str
    sdlc_orch: str
    cascade_check: str

    @classmethod
    def setUpClass(cls):
        cls.impl_guidance = (
            PLUGIN_ROOT / "skills" / "implementation-guidance" / "SKILL.md"
        ).read_text()
        cls.sdlc_orch = (
            PLUGIN_ROOT / "skills" / "sdlc-orchestration" / "SKILL.md"
        ).read_text()
        cls.cascade_check = (
            PLUGIN_ROOT / "agents" / "cascade-check.md"
        ).read_text()

    # --- Pre-flight check 2.5 ---

    def test_preflight_check_25_exists(self):
        """Check 2.5 Codebase table consistency exists in Phase 2 section."""
        lines = self.impl_guidance.splitlines()
        phase2_start = None
        phase3_start = None
        for i, line in enumerate(lines):
            if line.startswith("#### Phase 2"):
                phase2_start = i
            elif line.startswith("#### Phase 3") and phase2_start is not None:
                phase3_start = i
                break
        self.assertIsNotNone(phase2_start, "Phase 2 header not found")
        self.assertIsNotNone(phase3_start, "Phase 3 header not found after Phase 2")
        phase2_section = "\n".join(lines[phase2_start:phase3_start])
        self.assertIn(
            "**2.5 Codebase table consistency**",
            phase2_section,
            "Check 2.5 not found in Phase 2 section",
        )

    def test_preflight_blocking_count_updated(self):
        """Check summary lists 9 blocking checks including 2.5."""
        match = re.search(r"Blocking checks.*\(9 total\)", self.impl_guidance)
        self.assertIsNotNone(
            match, "Blocking checks line with (9 total) not found"
        )
        blocking_line = match.group(0)
        self.assertIn("2.5", blocking_line, "2.5 not in blocking checks list")

    def test_preflight_report_format_includes_25(self):
        """Pre-flight report format table includes a row for Codebase table check."""
        lines = self.impl_guidance.splitlines()
        report_section = False
        found = False
        for line in lines:
            if "Pre-Flight Report Format" in line:
                report_section = True
            if report_section and "|" in line and "Codebase table" in line:
                found = True
                break
        self.assertTrue(found, "Codebase table row not found in report format table")

    # --- Upstream commit verification in implementation-guidance ---

    def test_impl_guidance_upstream_commit_verification(self):
        """Step 5.3 has commit verification BEFORE cascade-check spawn."""
        lines = self.impl_guidance.splitlines()
        section_start = None
        section_end = None
        for i, line in enumerate(lines):
            if line.startswith("#### 5.3"):
                section_start = i
            elif section_start is not None and line.startswith("#### 5."):
                section_end = i
                break
        if section_end is None:
            section_end = len(lines)
        self.assertIsNotNone(section_start, "Section 5.3 not found")
        section_lines = lines[section_start:section_end]

        verify_idx = None
        spawn_idx = None
        for i, line in enumerate(section_lines):
            if re.search(r"verify upstream commits", line, re.IGNORECASE) and verify_idx is None:
                verify_idx = i
            if "Spawn the [cascade-check]" in line and spawn_idx is None:
                spawn_idx = i

        self.assertIsNotNone(verify_idx, "Upstream commit verification text not found in 5.3")
        self.assertIsNotNone(spawn_idx, "Cascade-check spawn text not found in 5.3")
        self.assertLess(
            verify_idx,
            spawn_idx,
            "Commit verification must appear BEFORE cascade-check spawn",
        )

    # --- Upstream commit verification in sdlc-orchestration ---

    def test_sdlc_orch_upstream_commit_verification(self):
        """sdlc-orchestration has commit verification BEFORE cascade-check spawn."""
        lines = self.sdlc_orch.splitlines()

        verify_idx = None
        spawn_idx = None
        for i, line in enumerate(lines):
            if (
                re.search(r"upstream plan commits", line, re.IGNORECASE)
                or "git rev-parse" in line
            ) and verify_idx is None:
                verify_idx = i
            if "Spawn" in line and "cascade-check" in line and spawn_idx is None:
                spawn_idx = i

        self.assertIsNotNone(
            verify_idx,
            "Upstream commit verification not found in sdlc-orchestration",
        )
        self.assertIsNotNone(
            spawn_idx,
            "Cascade-check spawn not found in sdlc-orchestration",
        )
        self.assertLess(
            verify_idx,
            spawn_idx,
            "Commit verification must appear BEFORE cascade-check spawn",
        )

    # --- Design boundary note in cascade-check ---

    def test_cascade_check_design_boundary_note(self):
        """cascade-check.md documents that upstream commit verification is caller's responsibility."""
        self.assertTrue(
            "verified by the caller" in self.cascade_check
            or "does not verify git history" in self.cascade_check,
            "Design boundary note not found in cascade-check.md",
        )


if __name__ == "__main__":
    unittest.main()
