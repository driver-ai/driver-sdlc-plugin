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

    def test_sdlc_orch_materialization_task_docs_check(self):
        """sdlc-orchestration Materialization→Implementation has task-doc gate with BLOCK."""
        lines = self.sdlc_orch.splitlines()
        section_start = None
        section_end = None
        for i, line in enumerate(lines):
            if "Materialization" in line and "Implementation" in line and line.startswith("###"):
                section_start = i
            elif section_start is not None and line.startswith("### ") and i > section_start:
                section_end = i
                break
        self.assertIsNotNone(section_start, "Materialization → Implementation section header not found")
        if section_end is None:
            section_end = len(lines)
        section = "\n".join(lines[section_start:section_end])
        self.assertIn("task doc", section.lower(), "Task doc check not found in Materialization→Implementation")
        self.assertIn("BLOCK", section, "BLOCK severity not found in Materialization→Implementation task doc check")

    def test_sdlc_orch_validation_dryrun_verdict_check(self):
        """sdlc-orchestration Validation→Materialization has dry-run verdict check with WARN."""
        lines = self.sdlc_orch.splitlines()
        section_start = None
        section_end = None
        for i, line in enumerate(lines):
            if "Validation" in line and "Materialization" in line and line.startswith("###"):
                section_start = i
            elif section_start is not None and line.startswith("### ") and i > section_start:
                section_end = i
                break
        self.assertIsNotNone(section_start, "Validation → Materialization section header not found")
        if section_end is None:
            section_end = len(lines)
        section = "\n".join(lines[section_start:section_end])
        self.assertTrue(
            "dry-run verdict" in section.lower() or "dry-run" in section.lower(),
            "Dry-run verdict check not found in Validation→Materialization",
        )
        self.assertIn("WARN", section, "WARN severity not found in Validation→Materialization dry-run check")

    # --- C4: /drvr:docs-artifacts assessment prerequisite ---

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
        """Planning-guidance Step 7 contains the approval flow."""
        self.assertIn("## Step 7: Approve", self.planning_guidance)

    def test_materialize_tasks_dryrun_severity_check(self):
        """materialize-tasks blocks materialization on HIGH/MEDIUM unfixed gaps."""
        materialize_tasks = (
            PLUGIN_ROOT / "skills" / "materialize-tasks" / "SKILL.md"
        ).read_text()
        self.assertRegex(
            materialize_tasks,
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


class TestPlanConcretenessStructural(unittest.TestCase):
    """Structural tests for Plan 01: Data Structures & Callables concreteness rule."""

    dry_run_plan: str
    planning_guidance: str
    impl_guidance: str
    artifact_schemas: str
    readme: str

    @classmethod
    def setUpClass(cls):
        cls.dry_run_plan = (PLUGIN_ROOT / "commands" / "dry-run-plan.md").read_text()
        cls.planning_guidance = (PLUGIN_ROOT / "skills" / "planning-guidance" / "SKILL.md").read_text()
        cls.impl_guidance = (PLUGIN_ROOT / "skills" / "implementation-guidance" / "SKILL.md").read_text()
        cls.artifact_schemas = (PLUGIN_ROOT / "tests" / "test_artifact_schemas.py").read_text()
        cls.readme = (PLUGIN_ROOT / "README.md").read_text()

    def _step3_slice(self) -> str:
        match = re.search(r"### Step 3.*?(?=\n### Step 4|\Z)", self.dry_run_plan, re.DOTALL)
        self.assertIsNotNone(match, "Step 3 section not found in dry-run-plan.md")
        return match.group(0)

    def _gap_types_slice(self) -> str:
        match = re.search(r"## Gap Types to Watch For.*?(?=\n## |\Z)", self.dry_run_plan, re.DOTALL)
        self.assertIsNotNone(match, "Gap Types section not found in dry-run-plan.md")
        return match.group(0)

    def _step6_slice(self) -> str:
        match = re.search(r"## Step 6:.*?(?=\n## Step 7|\Z)", self.planning_guidance, re.DOTALL)
        self.assertIsNotNone(match, "Step 6 section not found in planning-guidance SKILL.md")
        return match.group(0)

    def test_dry_run_has_concreteness_check(self):
        self.assertRegex(
            self._step3_slice(),
            r"13\.\s+\*\*Concreteness\*\*:",
            "dry-run-plan.md Step 3 missing check #13 Concreteness",
        )

    def test_dry_run_has_concreteness_gap_types(self):
        gap_types = self._gap_types_slice()
        for row in [
            "Missing concreteness rollup",
            "Rollup/snippet mismatch",
            "Signature drift on modification",
            "Collision on addition",
        ]:
            with self.subTest(row=row):
                # Match a table-shaped row: | **Label** | cell | cell | — without
                # relying on ^/$ line anchors (assertRegex uses re.search without
                # re.MULTILINE; [^\n]* keeps each row within one line).
                pattern = rf"\|\s*\*\*{re.escape(row)}\*\*\s*\|[^\n]*\|[^\n]*\|"
                self.assertRegex(gap_types, pattern,
                    f"Gap Types table missing table-shaped row for: {row}")

    def test_dry_run_gap_type_severities(self):
        gap_types = self._gap_types_slice()
        exact_expectations = {
            "Rollup/snippet mismatch": "MEDIUM",
            "Signature drift on modification": "HIGH",
            "Collision on addition": "HIGH",
        }
        for label, sev in exact_expectations.items():
            with self.subTest(label=label):
                pattern = rf"\*\*{re.escape(label)}\*\*\s*\|[^|]+\|\s*{re.escape(sev)}\s*\|"
                self.assertRegex(gap_types, pattern,
                    f"Row '{label}' missing expected severity '{sev}'")
        with self.subTest(label="Missing concreteness rollup"):
            row_match = re.search(
                r"\*\*Missing concreteness rollup\*\*\s*\|[^|]+\|\s*([^|]+)\|",
                gap_types,
            )
            self.assertIsNotNone(row_match, "Missing concreteness rollup row not found")
            sev_cell = row_match.group(1)
            self.assertIn("HIGH", sev_cell)
            self.assertIn("MEDIUM", sev_cell)
            self.assertIn("predate", sev_cell.lower())

    def test_dry_run_concreteness_migration_language(self):
        # Check #13's migration clause: plans predating the concreteness rule should
        # downgrade from HIGH to MEDIUM. Test the CONCEPT (tokens co-occur inside
        # Step 3, where check #13 lives), not the exact prose — lets us reword the
        # clause without breaking the test, while still catching intent loss.
        step3 = self._step3_slice()
        self.assertIn("MEDIUM", step3)
        self.assertIn("predate", step3)

    def test_planning_template_has_data_structures_section(self):
        self.assertIn("## Data Structures & Callables", self.planning_guidance)
        for sub in ("### Added", "### Modified", "### Removed"):
            with self.subTest(sub=sub):
                self.assertIn(sub, self.planning_guidance)

    def test_planning_template_has_inline_snippet_example(self):
        self.assertRegex(
            self.planning_guidance,
            r"####\s+Snippet:",
            "planning-guidance task template missing #### Snippet: example",
        )

    def test_planning_section_positioned_after_architecture_fit(self):
        template_match = re.search(
            r"````markdown\n# Plan:.*?````", self.planning_guidance, re.DOTALL
        )
        self.assertIsNotNone(template_match, "Plan document template block not found")
        template = template_match.group(0)
        arch_idx = template.find("## Architecture Fit")
        ds_idx = template.find("## Data Structures & Callables")
        ac_idx = template.find("## Acceptance Criteria")
        self.assertGreater(arch_idx, 0)
        self.assertGreater(ds_idx, arch_idx)
        self.assertGreater(ac_idx, ds_idx)

    def test_planning_self_review_checks_rollup_snippets(self):
        step6 = self._step6_slice()
        self.assertIn("### Data Structures & Callables Self-Review", step6)
        for token in ("rollup", "inline snippet", "signature drift"):
            with self.subTest(token=token):
                self.assertIn(token, step6.lower())

    def test_impl_guidance_preflight_checks_inline_snippets(self):
        match = re.search(
            r"4\.5 Interface verification.*?(?=\n####\s+Phase\s+5\b|\n---|\Z)",
            self.impl_guidance,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Phase 4.5 section not found")
        self.assertIn("inline snippet", match.group(0).lower())

    def test_plan_doc_sections_has_new_required(self):
        import sys, importlib
        sys.path.insert(0, str(PLUGIN_ROOT / "tests"))
        try:
            mod = importlib.import_module("test_artifact_schemas")
            for section in ("Architecture Fit", "Data Structures & Callables"):
                with self.subTest(section=section):
                    self.assertIn(section, mod.PLAN_REQUIRED_SECTIONS)
        finally:
            sys.path.pop(0)

    def test_readme_planning_mentions_data_structures(self):
        match = re.search(r"\|\s*\*\*Planning\*\*\s*\|[^|]+\|", self.readme)
        self.assertIsNotNone(match, "Planning row not found in README Phase Descriptions table")
        self.assertIn("Data Structures & Callables", match.group(0),
            "README Planning row does not mention Data Structures & Callables")


class TestImplementationEnvironmentStructural(unittest.TestCase):
    """Structural tests for Plan 02: Implementation Environment + materialize-tasks hydration."""

    planning_guidance: str
    materialize_tasks: str
    impl_guidance: str
    sdlc_orch: str
    artifact_schemas: str
    readme: str

    @classmethod
    def setUpClass(cls):
        cls.planning_guidance = (PLUGIN_ROOT / "skills" / "planning-guidance" / "SKILL.md").read_text()
        cls.materialize_tasks = (PLUGIN_ROOT / "skills" / "materialize-tasks" / "SKILL.md").read_text()
        cls.impl_guidance = (PLUGIN_ROOT / "skills" / "implementation-guidance" / "SKILL.md").read_text()
        cls.sdlc_orch = (PLUGIN_ROOT / "skills" / "sdlc-orchestration" / "SKILL.md").read_text()
        cls.artifact_schemas = (PLUGIN_ROOT / "tests" / "test_artifact_schemas.py").read_text()
        cls.readme = (PLUGIN_ROOT / "README.md").read_text()

    def _step5_slice(self) -> str:
        match = re.search(r"## Step 5:.*?(?=\n## Step 6|\Z)", self.planning_guidance, re.DOTALL)
        self.assertIsNotNone(match, "Step 5 section not found in planning-guidance")
        return match.group(0)

    def _overview_template_slice(self) -> str:
        match = re.search(
            r"### Multi-Plan Overview.*?```(?:markdown)?\n(.*?)\n```",
            self.planning_guidance,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Multi-Plan Overview template block not found")
        return match.group(1)

    def _resume_step4_slice(self) -> str:
        match = re.search(
            r"4\.\s+\*\*Report current state:\*\*.*?(?=\n---|\n## |\n### |\Z)",
            self.sdlc_orch,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Session Resumption Step 4 region not found")
        return match.group(0)

    def _materialize_step2_slice(self) -> str:
        match = re.search(
            r"## Step 2: Resolve Codebase Target.*?(?=\n## Step 3|\Z)",
            self.materialize_tasks,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Materialize-tasks Step 2 section not found")
        return match.group(0)

    def _materialize_template_slice(self) -> str:
        match = re.search(
            r"Task document template:.*?```markdown\n(.*?)\n```",
            self.materialize_tasks,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Materialize-tasks Task document template block not found")
        return match.group(1)

    def test_planning_overview_has_implementation_environment(self):
        tmpl = self._overview_template_slice()
        self.assertIn("## Implementation Environment", tmpl)
        self.assertIn("| Codebase | Local Path | Base Branch | Feature Branch | Test Command |", tmpl)

    def test_planning_overview_section_position(self):
        tmpl = self._overview_template_slice()
        status_idx = tmpl.find("## Status")
        env_idx = tmpl.find("## Implementation Environment")
        strat_idx = tmpl.find("## Planning Strategy")
        self.assertGreaterEqual(status_idx, 0, "## Status not in overview template")
        self.assertGreater(env_idx, status_idx, "Implementation Environment must follow Status")
        self.assertGreater(strat_idx, env_idx, "Planning Strategy must follow Implementation Environment")

    def test_planning_has_ie_guidance(self):
        step5 = self._step5_slice()
        self.assertIn("Implementation Environment", step5)
        self.assertRegex(step5, r"[Cc]onfirm",
            "Step 5 should mention confirming IE with the user")

    def test_materialize_tasks_step2_reads_ie_first(self):
        step2 = self._materialize_step2_slice()
        ie_idx = step2.find("Implementation Environment")
        codebases_idx = step2.find("`## Codebases`")
        self.assertGreater(ie_idx, 0, "Step 2 must reference Implementation Environment")
        self.assertGreater(codebases_idx, ie_idx,
            "Step 2 must reference Implementation Environment BEFORE Codebases")
        self.assertRegex(step2, r"fall\s*back|fallback",
            "Step 2 must document the fallback to research Codebases")

    def test_materialize_tasks_template_has_enriched_codebase(self):
        tmpl = self._materialize_template_slice()
        self.assertIn("**Base Branch**:", tmpl)
        self.assertIn("**Feature Branch**:", tmpl)

    def test_materialize_tasks_template_has_test_command(self):
        tmpl = self._materialize_template_slice()
        self.assertIn("## Test Command", tmpl)

    def test_impl_guidance_preflight_test_command_priority(self):
        match = re.search(
            r"4\.3 Test baseline.*?(?=\n####\s+Phase\s+5\b|\n---|\Z)",
            self.impl_guidance,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Phase 4.3 section not found")
        section = match.group(0)
        test_cmd_idx = section.find("task doc `## Test Command`")
        env_idx = section.find("Implementation Environment")
        constraints_idx = section.find("task doc constraints")
        self.assertGreater(test_cmd_idx, 0,
            "Phase 4.3 chain must start with task doc Test Command")
        self.assertGreater(env_idx, test_cmd_idx,
            "Implementation Environment must follow task doc Test Command")
        self.assertGreater(constraints_idx, env_idx,
            "task doc constraints must follow Implementation Environment")

    def test_sdlc_orchestration_resume_uses_env(self):
        step4_block = self._resume_step4_slice()
        for token in ("Codebase:", "Test command:", "Implementation Environment"):
            with self.subTest(token=token):
                self.assertIn(token, step4_block,
                    f"Session Resumption Step 4 missing: {token}")

    def test_plan_overview_sections_has_new_required(self):
        match = re.search(
            r"def test_plan_overview_sections.*?required\s*=\s*\{([^}]+)\}",
            self.artifact_schemas,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "test_plan_overview_sections required set not found")
        self.assertRegex(match.group(1), r'["\']Implementation Environment["\']')

    def test_readme_planning_mentions_implementation_environment(self):
        match = re.search(r"\|\s*\*\*Planning\*\*\s*\|[^|]+\|", self.readme)
        self.assertIsNotNone(match, "Planning row not found in README")
        self.assertIn("Implementation Environment", match.group(0))


if __name__ == "__main__":
    unittest.main()
