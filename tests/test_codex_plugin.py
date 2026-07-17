"""Structural tests for the Codex plugin compatibility layer."""

import json
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class TestCodexPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest_path = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
        cls.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_manifest_names_and_exposes_components(self):
        self.assertEqual(self.manifest["name"], "drvr")
        self.assertEqual(self.manifest["skills"], "./skills/")
        self.assertIn("driver-mcp", self.manifest["mcpServers"])

    def test_codex_router_references_portable_commands(self):
        router = (PLUGIN_ROOT / "skills" / "drvr" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        portable_commands = {
            "setup",
            "feature",
            "context",
            "orchestrate",
            "dry-run-plan",
            "assess",
            "review",
            "docs-artifacts",
            "open-pr",
            "retro",
        }
        for command in portable_commands:
            with self.subTest(command=command):
                self.assertIn(f"../../commands/{command}.md", router)
                self.assertTrue((PLUGIN_ROOT / "commands" / f"{command}.md").is_file())

    def test_codex_projects_template_exists(self):
        template = PLUGIN_ROOT / "templates" / "AGENTS.md.template"
        self.assertTrue(template.is_file())
        contents = template.read_text(encoding="utf-8")
        self.assertIn("{{TEAM_NAME}}", contents)
        self.assertIn("{{DATE}}", contents)

    def test_legacy_marketplace_has_codex_policy(self):
        marketplace = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], self.manifest["name"])
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
        self.assertTrue(entry["category"])


if __name__ == "__main__":
    unittest.main()
