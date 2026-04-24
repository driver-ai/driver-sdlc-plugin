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
    """Structural tests for Plan 02: Implementation Environment concept across skills."""

    planning_guidance: str
    materialize_tasks: str
    impl_guidance: str
    sdlc_orch: str
    readme: str

    @classmethod
    def setUpClass(cls):
        cls.planning_guidance = (PLUGIN_ROOT / "skills" / "planning-guidance" / "SKILL.md").read_text()
        cls.materialize_tasks = (PLUGIN_ROOT / "skills" / "materialize-tasks" / "SKILL.md").read_text()
        cls.impl_guidance = (PLUGIN_ROOT / "skills" / "implementation-guidance" / "SKILL.md").read_text()
        cls.sdlc_orch = (PLUGIN_ROOT / "skills" / "sdlc-orchestration" / "SKILL.md").read_text()
        cls.readme = (PLUGIN_ROOT / "README.md").read_text()

    def test_planning_overview_has_implementation_environment(self):
        match = re.search(
            r"### Multi-Plan Overview.*?```(?:markdown)?\n(.*?)\n```",
            self.planning_guidance, re.DOTALL,
        )
        self.assertIsNotNone(match, "Multi-Plan Overview template block not found")
        self.assertIn("## Implementation Environment", match.group(1))

    def test_planning_has_ie_guidance(self):
        step5 = re.search(r"## Step 5:.*?(?=\n## Step 6|\Z)", self.planning_guidance, re.DOTALL)
        self.assertIsNotNone(step5)
        self.assertIn("Implementation Environment", step5.group(0))

    def test_materialize_tasks_reads_ie(self):
        step2 = re.search(r"## Step 2:.*?(?=\n## Step 3|\Z)", self.materialize_tasks, re.DOTALL)
        self.assertIsNotNone(step2)
        self.assertIn("Implementation Environment", step2.group(0))

    def test_materialize_tasks_template_has_environment_info(self):
        match = re.search(r"Task document template:.*?```markdown\n(.*?)\n```",
            self.materialize_tasks, re.DOTALL)
        self.assertIsNotNone(match)
        tmpl = match.group(1)
        self.assertIn("## Codebase", tmpl)
        self.assertIn("Implementation Environment", tmpl)

    def test_impl_guidance_uses_ie_for_test_discovery(self):
        self.assertIn("Implementation Environment", self.impl_guidance)
        match = re.search(r"4\.3 Test baseline.*", self.impl_guidance)
        self.assertIsNotNone(match)
        self.assertIn("Implementation Environment", match.group(0))

    def test_sdlc_orchestration_resume_uses_env(self):
        match = re.search(
            r"4\.\s+\*\*Report current state:\*\*.*?(?=\n---|\n## |\n### |\Z)",
            self.sdlc_orch, re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertIn("Codebase:", match.group(0))
        self.assertIn("Test command:", match.group(0))

    def test_readme_planning_mentions_implementation_environment(self):
        match = re.search(r"\|\s*\*\*Planning\*\*\s*\|[^|]+\|", self.readme)
        self.assertIsNotNone(match, "Planning row not found in README")
        self.assertIn("Implementation Environment", match.group(0))


class TestIntentPhaseStructural(unittest.TestCase):
    """Structural tests for Plan 03: Intent as first-class SDLC phase."""

    plugin_json: dict
    claude_md: str
    template_md: str
    hook_sh: str
    sdlc_orch: str
    intent_skill: str
    feature_cmd: str
    research_guidance: str
    artifact_schemas: str

    @classmethod
    def setUpClass(cls):
        import json
        cls.plugin_json = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text()
        )
        cls.claude_md = (PLUGIN_ROOT / "CLAUDE.md").read_text()
        cls.template_md = (PLUGIN_ROOT / "templates" / "CLAUDE.md.template").read_text()
        cls.hook_sh = (PLUGIN_ROOT / "hooks" / "track-skill-load.sh").read_text()
        cls.sdlc_orch = (PLUGIN_ROOT / "skills" / "sdlc-orchestration" / "SKILL.md").read_text()
        intent_path = PLUGIN_ROOT / "skills" / "intent-guidance" / "SKILL.md"
        cls.intent_skill = intent_path.read_text() if intent_path.is_file() else ""
        cls.feature_cmd = (PLUGIN_ROOT / "commands" / "feature.md").read_text()
        cls.research_guidance = (PLUGIN_ROOT / "skills" / "research-guidance" / "SKILL.md").read_text()
        cls.artifact_schemas = (PLUGIN_ROOT / "tests" / "test_artifact_schemas.py").read_text()

    def _intent_research_slice(self) -> str:
        match = re.search(r"### Intent → Research.*?(?=\n### |\Z)", self.sdlc_orch, re.DOTALL)
        self.assertIsNotNone(match, "Intent → Research transition boundary not found")
        return match.group(0)

    def _feature_cmd_overview_template_slice(self) -> str:
        match = re.search(
            r"### Step 5:.*?# <Project Name>.*?(?=\n### Step |\Z)",
            self.feature_cmd,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "feature.md Step 5 research/00-overview.md template not found")
        return match.group(0)

    def test_intent_skill_registered(self):
        self.assertIn("./skills/intent-guidance", self.plugin_json.get("skills", []))

    def test_intent_skill_exists_and_valid(self):
        path = PLUGIN_ROOT / "skills" / "intent-guidance" / "SKILL.md"
        self.assertTrue(path.is_file(), f"{path} does not exist")
        self.assertIn("name: intent-guidance", self.intent_skill)

    def test_intent_phase_in_claude_md(self):
        self.assertIn("| Intent |", self.claude_md)
        self.assertIn("intent-guidance", self.claude_md)

    def test_intent_phase_in_template(self):
        self.assertIn("| Intent |", self.template_md)
        self.assertIn("intent-guidance", self.template_md)

    def test_intent_lifecycle_diagram(self):
        self.assertIn("Intent --> Research", self.claude_md)
        self.assertIn("Intent --> Research", self.template_md)

    def test_hook_tracks_intent_phase(self):
        self.assertRegex(self.hook_sh, r'intent-guidance\)\s*PHASE="Intent"')

    def test_sdlc_orch_has_intent_transition(self):
        self.assertIn("### Intent → Research", self.sdlc_orch)
        self.assertIn("### Scaffold → Intent", self.sdlc_orch)

    def test_sdlc_orch_intent_gate_blocks_without_artifact(self):
        section = self._intent_research_slice()
        for phrase in ("BLOCK", "research/00-intent.md", "skip intent", "Activate `intent-guidance`"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section,
                    f"Intent → Research section missing required phrase: {phrase}")

    def test_sdlc_orch_loop_has_research_to_intent(self):
        self.assertRegex(self.sdlc_orch, r"\|\s*Research\s*→\s*Intent\s*\|")

    def test_sdlc_orch_feature_log_events_has_intent(self):
        self.assertRegex(self.sdlc_orch, r"\|\s*`intent-guidance`\s*\|[^|]*Intent")

    def test_sdlc_orch_resumption_detects_intent(self):
        resume_match = re.search(
            r"## Session Resumption.*?(?=\n## |\Z)",
            self.sdlc_orch,
            re.DOTALL,
        )
        self.assertIsNotNone(resume_match)
        self.assertIn("research/00-intent.md", resume_match.group(0),
            "Session Resumption should reference research/00-intent.md detection")

    def test_feature_cmd_scaffolds_intent(self):
        self.assertIn("research/00-intent.md", self.feature_cmd)
        self.assertRegex(self.feature_cmd, r"\*\*Phase\*\*:\s*Intent")
        self.assertIn("Intent started", self.feature_cmd,
            "feature.md FEATURE_LOG template should include 'Intent started' initial log row")

    def test_feature_cmd_scaffold_no_setup_questions(self):
        template_slice = self._feature_cmd_overview_template_slice()
        self.assertNotIn("## Setup Questions", template_slice,
            "feature.md research/00-overview.md scaffold template should not include ## Setup Questions anymore")

    def test_feature_cmd_has_brief_flag(self):
        self.assertIn("--brief", self.feature_cmd)
        self.assertIn("brief", self.feature_cmd.lower())

    def test_research_overview_sections_sans_setup_questions(self):
        match = re.search(
            r"def test_research_overview_sections.*?required\s*=\s*\{([^}]+)\}",
            self.artifact_schemas,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        required_text = match.group(1)
        self.assertNotRegex(required_text, r'["\']Setup Questions["\']',
            "test_research_overview_sections required set should no longer contain Setup Questions")
        for section in ("Status", "Problem Statement", "Scope", "Codebases"):
            with self.subTest(section=section):
                self.assertRegex(required_text, rf'["\']{re.escape(section)}["\']',
                    f"required set missing: {section}")


if __name__ == "__main__":
    unittest.main()
