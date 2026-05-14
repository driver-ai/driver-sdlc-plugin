"""Artifact schema validation tests for feature project documents.

Validates that artifacts with YAML frontmatter conform to expected schemas:
required fields, allowed type/status values, and date formats.
Documents without frontmatter are skipped with a warning.
"""

import re
import unittest
import warnings
from pathlib import Path

from conftest import discover_feature_projects, get_md_body, get_md_sections, is_active_feature, parse_frontmatter


def _has_real_frontmatter(path: Path) -> bool:
    """Check if a file starts with YAML frontmatter (--- on first non-blank line)."""
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        return line.strip() == "---"
    return False


def _parse_artifact_frontmatter(path: Path) -> dict:
    """Parse frontmatter only if the file actually starts with --- fences."""
    if not _has_real_frontmatter(path):
        return {}
    return parse_frontmatter(path)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_TYPES = {
    "research", "plan", "task", "implementation_log", "feature_log",
    "decision", "deviation", "learning", "test_plan", "test_result",
    "assessment", "open_question", "dry_run",
}

ALLOWED_STATUSES = {
    "not_started", "in_progress", "complete", "approved", "accepted",
    "pending_review", "resolved", "open", "confirmed", "unverified",
    "invalidated",
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

PLAN_REQUIRED_SECTIONS = {
    "Context",
    "Architecture Fit",
    "Data Structures & Callables",
    "Acceptance Criteria",
    "Test Strategy",
    "Task Breakdown",
}

# ---------------------------------------------------------------------------
# Discover feature projects once at module level
# ---------------------------------------------------------------------------

_FEATURE_PROJECTS = discover_feature_projects()


def _collect_research_docs():
    """Return research docs (research/*.md, NOT 00-overview.md) across all feature projects."""
    docs = []
    for proj in _FEATURE_PROJECTS:
        research_dir = proj / "research"
        if not research_dir.is_dir():
            continue
        for md in research_dir.glob("*.md"):
            if md.name == "00-overview.md":
                continue
            docs.append(md)
    return docs


def _collect_decision_docs():
    """Return decision docs (research/decisions/*.md) across all feature projects."""
    docs = []
    for proj in _FEATURE_PROJECTS:
        decisions_dir = proj / "research" / "decisions"
        if not decisions_dir.is_dir():
            continue
        for md in decisions_dir.glob("*.md"):
            docs.append(md)
    return docs


def _collect_task_docs():
    """Return task docs (plans/*/tasks/*.md) across all feature projects."""
    docs = []
    for proj in _FEATURE_PROJECTS:
        plans_dir = proj / "plans"
        if not plans_dir.is_dir():
            continue
        for tasks_dir in plans_dir.glob("*/tasks"):
            if tasks_dir.is_dir():
                for md in sorted(tasks_dir.glob("[0-9][0-9]-*.md")):
                    docs.append(md)
    return docs


def _collect_all_artifacts():
    """Return all .md artifacts (excluding FEATURE_LOG.md and 00-overview.md) across feature projects."""
    docs = []
    for proj in _FEATURE_PROJECTS:
        for md in proj.rglob("*.md"):
            if md.name in ("FEATURE_LOG.md", "00-overview.md"):
                continue
            docs.append(md)
    return docs


def _strip_quotes(value):
    """Strip surrounding quotes from a frontmatter value string."""
    if isinstance(value, str) and len(value) >= 2:
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            return value[1:-1]
    return value


@unittest.skipIf(not _FEATURE_PROJECTS, "No feature projects found")
class TestArtifactSchemas(unittest.TestCase):
    """Validate artifact frontmatter against expected schemas."""

    def test_research_doc_frontmatter(self):
        """Research docs with frontmatter must have type, status, created, updated."""
        docs = _collect_research_docs()
        self.assertTrue(docs, "No research docs found to test")
        tested = 0
        skipped = 0
        for doc in docs:
            with self.subTest(doc=str(doc)):
                fm = _parse_artifact_frontmatter(doc)
                if not fm:
                    warnings.warn(f"No frontmatter in {doc.name}, skipping")
                    skipped += 1
                    continue
                tested += 1
                required = {"type", "status", "created", "updated"}
                missing = required - set(fm.keys())
                self.assertFalse(missing,
                    f"{doc.name} missing required fields: {missing}")
        if tested == 0:
            warnings.warn("All research docs lacked frontmatter; none validated")

    def test_research_doc_type_value(self):
        """Research docs with frontmatter must have type='research'."""
        docs = _collect_research_docs()
        self.assertTrue(docs, "No research docs found to test")
        tested = 0
        for doc in docs:
            with self.subTest(doc=str(doc)):
                fm = _parse_artifact_frontmatter(doc)
                if not fm:
                    warnings.warn(f"No frontmatter in {doc.name}, skipping")
                    continue
                if "type" not in fm:
                    continue
                tested += 1
                self.assertEqual(fm["type"], "research",
                    f"{doc.name} type must be 'research', got '{fm['type']}'")
        if tested == 0:
            warnings.warn("No research docs with type field found; none validated")

    def test_decision_doc_frontmatter(self):
        """Decision docs with frontmatter must have type, status, created, updated, choice, rationale."""
        docs = _collect_decision_docs()
        self.assertTrue(docs, "No decision docs found to test")
        tested = 0
        skipped = 0
        for doc in docs:
            with self.subTest(doc=str(doc)):
                fm = _parse_artifact_frontmatter(doc)
                if not fm:
                    warnings.warn(f"No frontmatter in {doc.name}, skipping")
                    skipped += 1
                    continue
                tested += 1
                required = {"type", "status", "created", "updated", "choice", "rationale"}
                missing = required - set(fm.keys())
                self.assertFalse(missing,
                    f"{doc.name} missing required fields: {missing}")
        self.assertGreater(tested, 0, "All decision docs lacked frontmatter")

    def test_frontmatter_type_in_allowed_set(self):
        """Any artifact with a 'type' field must use an allowed value."""
        docs = _collect_all_artifacts()
        self.assertTrue(docs, "No artifacts found to test")
        tested = 0
        for doc in docs:
            with self.subTest(doc=str(doc)):
                fm = _parse_artifact_frontmatter(doc)
                if not fm:
                    warnings.warn(f"No frontmatter in {doc.name}, skipping")
                    continue
                if "type" not in fm:
                    continue
                tested += 1
                self.assertIn(fm["type"], ALLOWED_TYPES,
                    f"{doc.name} has invalid type '{fm['type']}'")
        if tested == 0:
            warnings.warn("No artifacts with type field found; none validated")

    def test_frontmatter_status_in_allowed_set(self):
        """Any artifact with a 'status' field must use an allowed value."""
        docs = _collect_all_artifacts()
        self.assertTrue(docs, "No artifacts found to test")
        tested = 0
        for doc in docs:
            with self.subTest(doc=str(doc)):
                fm = _parse_artifact_frontmatter(doc)
                if not fm:
                    warnings.warn(f"No frontmatter in {doc.name}, skipping")
                    continue
                if "status" not in fm:
                    continue
                tested += 1
                self.assertIn(fm["status"], ALLOWED_STATUSES,
                    f"{doc.name} has invalid status '{fm['status']}'")
        if tested == 0:
            warnings.warn("No artifacts with status field found; none validated")

    def test_date_format(self):
        """Any artifact with created/updated fields must match YYYY-MM-DD format."""
        docs = _collect_all_artifacts()
        self.assertTrue(docs, "No artifacts found to test")
        tested = 0
        for doc in docs:
            with self.subTest(doc=str(doc)):
                fm = _parse_artifact_frontmatter(doc)
                if not fm:
                    warnings.warn(f"No frontmatter in {doc.name}, skipping")
                    continue
                for field in ("created", "updated"):
                    if field in fm:
                        tested += 1
                        value = _strip_quotes(fm[field])
                        self.assertTrue(DATE_RE.match(value),
                            f"{doc.name} {field}='{value}' does not match YYYY-MM-DD")
        if tested == 0:
            warnings.warn("No artifacts with date fields found; none validated")

    def test_materialized_at_timestamp_format(self):
        """Any artifact with materialized_at field must match ISO 8601 timestamp format."""
        docs = _collect_all_artifacts()
        self.assertTrue(docs, "No artifacts found to test")
        tested = 0
        for doc in docs:
            with self.subTest(doc=str(doc)):
                fm = _parse_artifact_frontmatter(doc)
                if not fm:
                    continue
                if "materialized_at" not in fm:
                    continue
                tested += 1
                value = _strip_quotes(fm["materialized_at"])
                self.assertTrue(TIMESTAMP_RE.match(value),
                    f"{doc.name} materialized_at='{value}' does not match ISO 8601 timestamp")
        if tested == 0:
            warnings.warn("No artifacts with materialized_at field found; none validated")


# ---------------------------------------------------------------------------
# Structural section validation
# ---------------------------------------------------------------------------

@unittest.skipIf(not _FEATURE_PROJECTS, "No feature projects found")
class TestStructuralSections(unittest.TestCase):
    """Validate that key artifacts contain required H2 sections and content."""

    def test_feature_log_current_state_section(self):
        """FEATURE_LOG.md has a 'Current State' H2 with Phase, Active, Last updated."""
        for project in _FEATURE_PROJECTS:
            with self.subTest(project=project.name):
                fl = project / "FEATURE_LOG.md"
                self.assertTrue(fl.exists(), f"{project.name} missing FEATURE_LOG.md")
                sections = get_md_sections(fl)
                self.assertIn("Current State", sections,
                    f"{project.name} FEATURE_LOG.md missing '## Current State'")
                body = get_md_body(fl)
                # Extract content under ## Current State (up to next ## or end)
                cs_match = re.search(
                    r"## Current State\s*\n(.*?)(?=\n## |\Z)",
                    body, re.DOTALL,
                )
                self.assertIsNotNone(cs_match,
                    f"{project.name} could not extract Current State content")
                cs_text = cs_match.group(1)
                for field in ("**Phase**:", "**Active**:", "**Last updated**:"):
                    self.assertIn(field, cs_text,
                        f"{project.name} FEATURE_LOG.md Current State missing {field}")

    def test_feature_log_table_section(self):
        """FEATURE_LOG.md has a 'Log' H2 with a Date/Event/Artifact table header."""
        for project in _FEATURE_PROJECTS:
            with self.subTest(project=project.name):
                fl = project / "FEATURE_LOG.md"
                self.assertTrue(fl.exists(), f"{project.name} missing FEATURE_LOG.md")
                sections = get_md_sections(fl)
                self.assertIn("Log", sections,
                    f"{project.name} FEATURE_LOG.md missing '## Log'")
                body = get_md_body(fl)
                self.assertRegex(body, r"\|\s*Date\s*\|\s*Event\s*\|\s*Artifact\s*\|",
                    f"{project.name} FEATURE_LOG.md Log section missing table header row")

    def test_research_overview_sections(self):
        """research/00-overview.md has required H2 sections."""
        required = {"Status", "Problem Statement", "Scope", "Codebases"}
        for project in _FEATURE_PROJECTS:
            with self.subTest(project=project.name):
                overview = project / "research" / "00-overview.md"
                if not overview.exists():
                    warnings.warn(f"{project.name} has no research/00-overview.md, skipping")
                    continue
                sections = set(get_md_sections(overview))
                missing = required - sections
                self.assertFalse(missing,
                    f"{project.name} research/00-overview.md missing sections: {missing}")

    def test_task_doc_sections(self):
        """Task docs must have required H2 sections."""
        # NOTE: This test is meaningful only after Plan 01 materializes task docs.
        # Until then, it skips gracefully.
        # Tests and Code Quality Standards are conditional (omitted when no test strategy
        # or standards artifact). Constraints and Context are always present per the
        # task doc template.
        required = {"Codebase", "Goal", "Files", "Constraints", "Context", "Instructions"}
        docs = _collect_task_docs()
        if not docs:
            self.skipTest("No task docs found")
        # Filter to only task docs from active features.
        # Task doc path: features/<name>/plans/<plan>/tasks/<task>.md
        # Feature root is 4 levels up from the task doc.
        docs = [d for d in docs if is_active_feature(d.parent.parent.parent.parent)]
        if not docs:
            self.skipTest("No task docs from active features found")
        for doc in docs:
            with self.subTest(doc=str(doc)):
                sections = set(get_md_sections(doc))
                missing = required - sections
                self.assertFalse(missing,
                    f"{doc.name} missing required sections: {missing}")

    def test_plan_doc_sections(self):
        """Plan docs (01-*.md, 02-*.md, etc.) have required H2 sections."""
        required = PLAN_REQUIRED_SECTIONS.copy()
        tested = 0
        active_projects = [p for p in _FEATURE_PROJECTS if is_active_feature(p)]
        for project in active_projects:
            plans_dir = project / "plans"
            if not plans_dir.is_dir():
                continue
            for plan in sorted(plans_dir.glob("[0-9][0-9]-*.md")):
                if plan.name == "00-overview.md":
                    continue
                with self.subTest(project=project.name, plan=plan.name):
                    tested += 1
                    sections = set(get_md_sections(plan))
                    missing = required - sections
                    self.assertFalse(missing,
                        f"{project.name}/{plan.name} missing sections: {missing}")
        self.assertGreater(tested, 0, "No plan docs found to validate")

    def test_plan_overview_sections(self):
        """plans/00-overview.md has required H2 sections and a Progress table."""
        required = {"Planning Strategy", "Dependency Graph", "Interface Contracts Between Plans", "Feature Dependencies"}
        tested = 0
        active_projects = [p for p in _FEATURE_PROJECTS if is_active_feature(p)]
        for project in active_projects:
            with self.subTest(project=project.name):
                overview = project / "plans" / "00-overview.md"
                if not overview.exists():
                    warnings.warn(f"{project.name} has no plans/00-overview.md, skipping")
                    continue
                tested += 1
                sections = set(get_md_sections(overview))
                missing = required - sections
                self.assertFalse(missing,
                    f"{project.name} plans/00-overview.md missing sections: {missing}")
                # Progress table lives under Status H2 as H3, check for table header
                body = get_md_body(overview)
                self.assertRegex(body, r"\|\s*Plan\s*\|\s*Status\s*\|",
                    f"{project.name} plans/00-overview.md missing Progress table '| Plan | Status |'")
        if tested == 0:
            warnings.warn("No plans/00-overview.md files found; none validated")
