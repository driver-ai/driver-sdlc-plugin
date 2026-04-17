"""Structural tests for plugin.json and path resolution.

Validates that plugin.json is well-formed, contains the required fields,
uses valid semver versioning, and that all declared skill / agent / command
paths resolve to real files on disk.
"""

import json
import re
import unittest
from pathlib import Path

# Import shared helpers
from conftest import PLUGIN_ROOT, PLUGIN_CONFIG_DIR, parse_frontmatter, get_md_body


class TestPluginJson(unittest.TestCase):
    """Tests for .claude-plugin/plugin.json validity."""

    @classmethod
    def setUpClass(cls):
        plugin_json_path = PLUGIN_CONFIG_DIR / "plugin.json"
        cls.plugin_json_path = plugin_json_path
        with open(plugin_json_path, encoding="utf-8") as f:
            cls.plugin_data = json.load(f)

    def test_plugin_json_valid(self):
        """plugin.json must be valid JSON and parse without errors."""
        # If setUpClass succeeded, the JSON is valid.  Re-read to be explicit.
        with open(self.plugin_json_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_plugin_json_required_fields(self):
        """plugin.json must contain name, version, description, skills, agents, commands."""
        required = {"name", "version", "description", "skills", "agents", "commands"}
        missing = required - set(self.plugin_data.keys())
        self.assertFalse(missing, f"Missing required fields: {missing}")

    def test_plugin_json_version_semver(self):
        """version field must be valid semver (MAJOR.MINOR.PATCH)."""
        version = self.plugin_data.get("version", "")
        semver_re = re.compile(
            r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
            r"(-([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$"
        )
        self.assertRegex(version, semver_re, f"Version '{version}' is not valid semver")

    def test_skill_paths_resolve(self):
        """Every skill path in plugin.json must resolve to a directory containing SKILL.md."""
        for skill_path in self.plugin_data.get("skills", []):
            resolved = (PLUGIN_ROOT / skill_path).resolve()
            self.assertTrue(resolved.is_dir(), f"Skill directory does not exist: {resolved}")
            skill_md = resolved / "SKILL.md"
            self.assertTrue(skill_md.is_file(), f"SKILL.md missing in: {resolved}")

    def test_agent_paths_resolve(self):
        """Every agent path in plugin.json must resolve to an existing file."""
        for agent_path in self.plugin_data.get("agents", []):
            resolved = (PLUGIN_ROOT / agent_path).resolve()
            self.assertTrue(resolved.is_file(), f"Agent file does not exist: {resolved}")

    def test_command_paths_resolve(self):
        """Every command path in plugin.json must resolve to an existing file."""
        for cmd_path in self.plugin_data.get("commands", []):
            resolved = (PLUGIN_ROOT / cmd_path).resolve()
            self.assertTrue(resolved.is_file(), f"Command file does not exist: {resolved}")

    def test_marketplace_name_matches(self):
        """marketplace.json plugin name must match plugin.json name."""
        marketplace_path = PLUGIN_CONFIG_DIR / "marketplace.json"
        self.assertTrue(marketplace_path.is_file(), "marketplace.json not found")
        with open(marketplace_path, encoding="utf-8") as f:
            marketplace_data = json.load(f)
        # Top-level name
        self.assertEqual(
            marketplace_data.get("name"),
            self.plugin_data.get("name"),
            "marketplace.json top-level name does not match plugin.json name",
        )
        # First plugin entry name
        plugins = marketplace_data.get("plugins", [])
        self.assertTrue(len(plugins) > 0, "marketplace.json has no plugins entries")
        self.assertEqual(
            plugins[0].get("name"),
            self.plugin_data.get("name"),
            "marketplace.json plugins[0].name does not match plugin.json name",
        )


class TestFrontmatterSchemas(unittest.TestCase):
    """Tests for frontmatter validation across skills, agents, and commands."""

    @classmethod
    def setUpClass(cls):
        plugin_json_path = PLUGIN_CONFIG_DIR / "plugin.json"
        with open(plugin_json_path, encoding="utf-8") as f:
            cls.plugin_data = json.load(f)

        # Resolve skill SKILL.md paths
        cls.skill_paths = [
            (PLUGIN_ROOT / sp).resolve() / "SKILL.md"
            for sp in cls.plugin_data["skills"]
        ]
        # Resolve agent .md paths
        cls.agent_paths = [
            (PLUGIN_ROOT / ap).resolve()
            for ap in cls.plugin_data["agents"]
        ]
        # Resolve command .md paths
        cls.command_paths = [
            (PLUGIN_ROOT / cp).resolve()
            for cp in cls.plugin_data["commands"]
        ]

    # --- Skill tests ---

    def test_skill_frontmatter_has_description(self):
        """Every skill SKILL.md must have a 'description' in its frontmatter."""
        for path in self.skill_paths:
            with self.subTest(name=path.parent.name):
                fm = parse_frontmatter(path)
                self.assertIn("description", fm, f"{path.parent.name}: missing 'description'")
                self.assertTrue(fm["description"].strip(), f"{path.parent.name}: empty 'description'")

    # --- Agent tests ---

    def test_agent_frontmatter_required_fields(self):
        """Every agent must have name, description, model, allowed-tools."""
        required = {"name", "description", "model", "allowed-tools"}
        for path in self.agent_paths:
            with self.subTest(name=path.stem):
                fm = parse_frontmatter(path)
                missing = required - set(fm.keys())
                self.assertFalse(missing, f"{path.stem}: missing fields {missing}")

    def test_agent_name_matches_filename(self):
        """Agent 'name' field must equal the filename without .md extension."""
        for path in self.agent_paths:
            with self.subTest(name=path.stem):
                fm = parse_frontmatter(path)
                self.assertEqual(
                    fm.get("name"), path.stem,
                    f"name '{fm.get('name')}' != filename '{path.stem}'",
                )

    def test_agent_model_valid(self):
        """Agent model must be one of opus, sonnet, haiku."""
        valid_models = {"opus", "sonnet", "haiku"}
        for path in self.agent_paths:
            with self.subTest(name=path.stem):
                fm = parse_frontmatter(path)
                self.assertIn(
                    fm.get("model"), valid_models,
                    f"{path.stem}: model '{fm.get('model')}' not in {valid_models}",
                )

    def test_agent_allowed_tools_is_list(self):
        """Agent allowed-tools must use YAML list format."""
        for path in self.agent_paths:
            with self.subTest(name=path.stem):
                fm = parse_frontmatter(path)
                self.assertEqual(
                    fm.get("allowed-tools-format"), "list",
                    f"{path.stem}: expected allowed-tools-format 'list'",
                )

    # --- Command tests ---

    def test_command_frontmatter_required_fields(self):
        """Every command must have description, argument-hint, allowed-tools."""
        required = {"description", "argument-hint", "allowed-tools"}
        for path in self.command_paths:
            with self.subTest(name=path.stem):
                fm = parse_frontmatter(path)
                missing = required - set(fm.keys())
                self.assertFalse(missing, f"{path.stem}: missing fields {missing}")

    def test_command_allowed_tools_is_string(self):
        """Command allowed-tools must use comma-separated string format."""
        for path in self.command_paths:
            with self.subTest(name=path.stem):
                fm = parse_frontmatter(path)
                self.assertEqual(
                    fm.get("allowed-tools-format"), "string",
                    f"{path.stem}: expected allowed-tools-format 'string'",
                )


class TestCrossReferences(unittest.TestCase):
    """Tests for MCP prefixes, trigger phrase consistency, and body non-emptiness."""

    @classmethod
    def setUpClass(cls):
        plugin_json_path = PLUGIN_CONFIG_DIR / "plugin.json"
        with open(plugin_json_path, encoding="utf-8") as f:
            cls.plugin_data = json.load(f)

        # Resolve skill SKILL.md paths
        cls.skill_paths = [
            (PLUGIN_ROOT / sp).resolve() / "SKILL.md"
            for sp in cls.plugin_data["skills"]
        ]
        # Resolve agent .md paths
        cls.agent_paths = [
            (PLUGIN_ROOT / ap).resolve()
            for ap in cls.plugin_data["agents"]
        ]
        # Resolve command .md paths
        cls.command_paths = [
            (PLUGIN_ROOT / cp).resolve()
            for cp in cls.plugin_data["commands"]
        ]

    def test_mcp_tool_prefix(self):
        """Any tool name containing 'mcp' must start with 'mcp__driver-mcp__'."""
        all_components = (
            [("agent", p) for p in self.agent_paths]
            + [("command", p) for p in self.command_paths]
        )
        for kind, path in all_components:
            with self.subTest(kind=kind, name=path.stem):
                fm = parse_frontmatter(path)
                tools = fm.get("allowed-tools", [])
                if isinstance(tools, str):
                    tools = [t.strip() for t in tools.split(",")]
                for tool in tools:
                    if "mcp" in tool.lower():
                        self.assertTrue(
                            tool.startswith("mcp__driver-mcp__"),
                            f"{path.stem}: MCP tool '{tool}' must start with 'mcp__driver-mcp__'",
                        )

    def test_skill_trigger_phrases_in_description(self):
        """Skills with 'Trigger phrases:' must have valid quoted phrases (excluding negative examples)."""
        for path in self.skill_paths:
            with self.subTest(name=path.parent.name):
                fm = parse_frontmatter(path)
                desc = fm.get("description", "")
                if "Trigger phrases:" not in desc:
                    continue

                # Extract the substring from "Trigger phrases:" to the next
                # "Do NOT" line or end of description.
                tp_start = desc.index("Trigger phrases:")
                tp_text = desc[tp_start:]

                # Cut off at "Do NOT" boundary if present
                do_not_match = re.search(r"Do NOT", tp_text[len("Trigger phrases:"):])
                if do_not_match:
                    tp_text = tp_text[: len("Trigger phrases:") + do_not_match.start()]

                # Extract all quoted strings from the trigger-phrase region
                phrases = re.findall(r'"([^"]+)"', tp_text)

                self.assertTrue(
                    len(phrases) > 0,
                    f"{path.parent.name}: 'Trigger phrases:' found but no quoted phrases extracted",
                )
                for phrase in phrases:
                    self.assertTrue(
                        phrase.strip(),
                        f"{path.parent.name}: empty trigger phrase found",
                    )

    def test_component_body_nonempty(self):
        """All skills, agents, and commands must have non-empty markdown body after frontmatter."""
        all_components = (
            [("skill", p) for p in self.skill_paths]
            + [("agent", p) for p in self.agent_paths]
            + [("command", p) for p in self.command_paths]
        )
        for kind, path in all_components:
            label = path.parent.name if kind == "skill" else path.stem
            with self.subTest(kind=kind, name=label):
                body = get_md_body(path)
                self.assertTrue(
                    body.strip(),
                    f"{label}: markdown body after frontmatter is empty",
                )


class TestCommandQualification(unittest.TestCase):
    """Tests that all command references use fully qualified drvr:* names."""

    COMMANDS = [
        "feature", "assess", "context", "dry-run-plan",
        "docs-artifacts", "orchestrate", "retro", "setup",
    ]

    SCAN_DIRS = ["commands", "skills", "agents", "docs", "hooks", "templates"]
    SCAN_ROOT_FILES = ["CLAUDE.md", "README.md"]

    FALSE_POSITIVE_PATTERNS = [
        re.compile(r'commands/'),
        re.compile(r'features/'),
        re.compile(r'assessment/'),
        re.compile(r'FEATURE_LOG'),
        re.compile(r'feature_log'),
        re.compile(r'\btype:\s'),
        re.compile(r'branch\s*[:=]'),
    ]

    @classmethod
    def setUpClass(cls):
        cls.md_files = []
        for dir_name in cls.SCAN_DIRS:
            dir_path = PLUGIN_ROOT / dir_name
            if dir_path.is_dir():
                cls.md_files.extend(dir_path.rglob("*.md"))
        for fname in cls.SCAN_ROOT_FILES:
            fpath = PLUGIN_ROOT / fname
            if fpath.is_file():
                cls.md_files.append(fpath)

    def test_no_bare_command_references(self):
        """All command references must use fully qualified drvr:* names."""
        violations = []

        for md_file in self.md_files:
            content = md_file.read_text(encoding="utf-8")
            lines = content.splitlines()

            for line_num, line in enumerate(lines, 1):
                if any(p.search(line) for p in self.FALSE_POSITIVE_PATTERNS):
                    continue

                for cmd in self.COMMANDS:
                    pattern = re.compile(
                        rf'(?<![:\w./])'
                        rf'/{re.escape(cmd)}'
                        rf'(?=[\s`\])<>,:;"\'|]|$)'
                    )
                    for match in pattern.finditer(line):
                        rel_path = md_file.relative_to(PLUGIN_ROOT)
                        violations.append(
                            f"  {rel_path}:{line_num}: /{cmd} -> {line.strip()[:80]}"
                        )

        if violations:
            self.fail(
                f"Found {len(violations)} bare command reference(s):\n"
                + "\n".join(violations)
            )


if __name__ == "__main__":
    unittest.main()
