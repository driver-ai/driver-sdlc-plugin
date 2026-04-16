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
    docs_artifacts: str

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
        cls.docs_artifacts = (
            PLUGIN_ROOT / "commands" / "docs-artifacts.md"
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
        match = re.search(r".*Blocking checks.*\(9 total\).*", self.impl_guidance)
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

    # --- C3: sdlc-orchestration Validation→Implementation checks ---

    def test_sdlc_orch_validation_task_docs_check(self):
        """sdlc-orchestration Validation→Implementation has task-docs check with BLOCK."""
        lines = self.sdlc_orch.splitlines()
        section_start = None
        section_end = None
        for i, line in enumerate(lines):
            if "Validation" in line and "Implementation" in line and line.startswith("###"):
                section_start = i
            elif section_start is not None and line.startswith("### ") and i > section_start:
                section_end = i
                break
        self.assertIsNotNone(section_start, "Validation → Implementation section header not found")
        if section_end is None:
            section_end = len(lines)
        section = "\n".join(lines[section_start:section_end])
        self.assertIn("task docs", section.lower(), "Task docs check not found in Validation→Implementation")
        self.assertIn("BLOCK", section, "BLOCK severity not found in Validation→Implementation task docs check")

    def test_sdlc_orch_validation_dryrun_verdict_check(self):
        """sdlc-orchestration Validation→Implementation has dry-run verdict check with WARN."""
        lines = self.sdlc_orch.splitlines()
        section_start = None
        section_end = None
        for i, line in enumerate(lines):
            if "Validation" in line and "Implementation" in line and line.startswith("###"):
                section_start = i
            elif section_start is not None and line.startswith("### ") and i > section_start:
                section_end = i
                break
        self.assertIsNotNone(section_start, "Validation → Implementation section header not found")
        if section_end is None:
            section_end = len(lines)
        section = "\n".join(lines[section_start:section_end])
        self.assertTrue(
            "dry-run verdict" in section.lower() or "dry-run" in section.lower(),
            "Dry-run verdict check not found in Validation→Implementation",
        )
        self.assertIn("WARN", section, "WARN severity not found in Validation→Implementation dry-run check")

    # --- C4: /docs-artifacts assessment prerequisite ---

    def test_docs_artifacts_assessment_prerequisite(self):
        """docs-artifacts.md Step 2 contains assessment check referencing test-curation."""
        lines = self.docs_artifacts.splitlines()
        step2_start = None
        step3_start = None
        for i, line in enumerate(lines):
            if "Step 2" in line and line.startswith("###"):
                step2_start = i
            elif step2_start is not None and line.startswith("### ") and i > step2_start:
                step3_start = i
                break
        self.assertIsNotNone(step2_start, "Step 2 header not found in docs-artifacts")
        if step3_start is None:
            step3_start = len(lines)
        section = "\n".join(lines[step2_start:step3_start])
        self.assertIn("assessment", section.lower(), "Assessment check not found in Step 2")
        self.assertIn("test-curation", section, "test-curation reference not found in Step 2")


class TestBilateralMaterializationGate(unittest.TestCase):
    """Structural tests for Plan 01: bilateral materialization gate (C1+C2)."""

    planning_guidance: str
    impl_guidance: str
    claude_md: str
    gate_doctrine: str

    @classmethod
    def setUpClass(cls):
        cls.planning_guidance = (
            PLUGIN_ROOT / "skills" / "planning-guidance" / "SKILL.md"
        ).read_text()
        cls.impl_guidance = (
            PLUGIN_ROOT / "skills" / "implementation-guidance" / "SKILL.md"
        ).read_text()
        cls.claude_md = (PLUGIN_ROOT / "CLAUDE.md").read_text()
        doctrine_path = PLUGIN_ROOT / "docs" / "gate-doctrine.md"
        cls.gate_doctrine = doctrine_path.read_text() if doctrine_path.exists() else ""

    # --- C1: Planning-side approval gate ---

    def test_planning_approval_gate_exists(self):
        """Planning-guidance SKILL.md contains a ### 8.0 heading (approval gate sub-step)."""
        self.assertIn("### 8.0", self.planning_guidance)

    def test_planning_dryrun_severity_check(self):
        """Planning-guidance blocks materialization on HIGH/MEDIUM unfixed gaps."""
        self.assertRegex(
            self.planning_guidance,
            re.compile(r"(HIGH|MEDIUM).*unfixed.*BLOCK|BLOCK.*(HIGH|MEDIUM).*unfixed", re.IGNORECASE),
        )

    def test_planning_approval_writes_frontmatter(self):
        """Planning-guidance mentions writing approved_at and approved_by to plan frontmatter."""
        self.assertIn("approved_at", self.planning_guidance)
        self.assertIn("approved_by", self.planning_guidance)

    # --- C2: Implementation-side fallback removal ---

    def test_impl_no_plan_extraction_fallback(self):
        """Implementation-guidance does NOT contain plan-extraction fallback text."""
        self.assertNotIn("plan-extraction mode", self.impl_guidance)
        self.assertNotIn("Fall back to plan-extraction", self.impl_guidance)

    def test_impl_no_fallback_language(self):
        """Implementation-guidance Step 1 section does not contain 'fallback'."""
        lines = self.impl_guidance.splitlines()
        step1_start = None
        step2_start = None
        for i, line in enumerate(lines):
            if line.startswith("### Step 1"):
                step1_start = i
            elif line.startswith("### Step 2") and step1_start is not None:
                step2_start = i
                break
        self.assertIsNotNone(step1_start, "Step 1 header not found")
        self.assertIsNotNone(step2_start, "Step 2 header not found")
        step1_section = "\n".join(lines[step1_start:step2_start])
        self.assertNotIn("fallback", step1_section.lower())

    def test_impl_block_no_task_docs(self):
        """Step 1 point 3 contains BLOCK for missing task docs (scoped to point 3)."""
        lines = self.impl_guidance.splitlines()
        step1_start = None
        step2_start = None
        for i, line in enumerate(lines):
            if line.startswith("### Step 1"):
                step1_start = i
            elif line.startswith("### Step 2") and step1_start is not None:
                step2_start = i
                break
        self.assertIsNotNone(step1_start)
        self.assertIsNotNone(step2_start)
        step1_section = "\n".join(lines[step1_start:step2_start])
        point3_match = re.search(
            r"3\.\s+\*\*.*?\*\*.*?(?=\n\s*\d+\.\s+\*\*|\n###|\Z)",
            step1_section,
            re.DOTALL,
        )
        self.assertIsNotNone(point3_match, "Point 3 not found in Step 1")
        point3_text = point3_match.group(0)
        self.assertIn("BLOCK", point3_text)

    def test_impl_plan_approval_check(self):
        """Implementation-guidance contains 'Verify plan approval' bold heading."""
        self.assertIn("**Verify plan approval**", self.impl_guidance)

    # --- CLAUDE.md and doctrine ---

    def test_claude_md_plan_approved_fields(self):
        """CLAUDE.md type-specific fields table includes approved_at and approved_by for plan type."""
        self.assertIn("approved_at", self.claude_md)
        self.assertIn("approved_by", self.claude_md)

    def test_gate_doctrine_exists(self):
        """docs/gate-doctrine.md exists with required content."""
        self.assertTrue(
            len(self.gate_doctrine) > 0,
            "gate-doctrine.md does not exist or is empty",
        )
        self.assertIn("Process Invariant", self.gate_doctrine)
        self.assertIn("User Decision", self.gate_doctrine)
        self.assertIn("Pattern A", self.gate_doctrine)
        self.assertIn("Pattern B", self.gate_doctrine)
        self.assertIn("Pattern C", self.gate_doctrine)
        self.assertIn("No silent fallbacks", self.gate_doctrine)


if __name__ == "__main__":
    unittest.main()
