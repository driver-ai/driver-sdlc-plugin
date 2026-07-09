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
        "docs-artifacts", "open-pr", "orchestrate", "retro", "setup",
        "driverize", "un-driverize", "review", "capture-session",
        "capture-sync",
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
        re.compile(r'[Bb]ackward\s+compat'),
        re.compile(r'/drvr:'),
        re.compile(r'<!--\s*/'),
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


class TestCaptureSessionGovernance(unittest.TestCase):
    """Registration + egress-control governance for /drvr:capture-session.

    These tests pin the command's registration (plugin.json + COMMANDS scanner +
    frontmatter convention) and the load-bearing gate-before-egress ordering of
    the command body, so an MD regression that moves the approval gate after an
    upload step — or drops the reject cleanup — fails the suite.
    """

    @classmethod
    def setUpClass(cls):
        plugin_json_path = PLUGIN_CONFIG_DIR / "plugin.json"
        with open(plugin_json_path, encoding="utf-8") as f:
            cls.plugin_data = json.load(f)
        cls.command_path = PLUGIN_ROOT / "commands" / "capture-session.md"

    def test_capture_session_registered(self):
        """capture-session must be registered in plugin.json + COMMANDS, have valid
        frontmatter (allowed-tools a comma-separated string with >=2 tools), and
        reference itself fully-qualified as /drvr:capture-session in its body."""
        # Registered in plugin.json commands array
        self.assertIn(
            "./commands/capture-session.md",
            self.plugin_data.get("commands", []),
            "capture-session not registered in plugin.json commands array",
        )
        # Registered in the qualified-name scanner's COMMANDS list
        self.assertIn(
            "capture-session",
            TestCommandQualification.COMMANDS,
            "capture-session not added to COMMANDS list",
        )
        # Command file exists
        self.assertTrue(
            self.command_path.is_file(),
            f"command file does not exist: {self.command_path}",
        )

        fm = parse_frontmatter(self.command_path)
        # Three required frontmatter fields
        for field in ("description", "argument-hint", "allowed-tools"):
            self.assertIn(field, fm, f"capture-session missing frontmatter '{field}'")

        # allowed-tools must be a comma-separated STRING (not a YAML list)
        self.assertEqual(
            fm.get("allowed-tools-format"), "string",
            "capture-session allowed-tools must be a comma-separated string, not a YAML list",
        )
        tools = fm.get("allowed-tools", [])
        self.assertGreaterEqual(
            len(tools), 2,
            f"capture-session allowed-tools must list >=2 tools, got {tools}",
        )

        # Body references the command fully-qualified
        body = get_md_body(self.command_path)
        self.assertIn(
            "/drvr:capture-session", body,
            "capture-session body must reference the command fully-qualified as /drvr:capture-session",
        )

    def test_command_governance_structure(self):
        """The AskUserQuestion gate must appear BEFORE any routing/upload step, and the
        reject branch must contain a guarded rm -rf of the well-known capture dir."""
        self.assertTrue(
            self.command_path.is_file(),
            f"command file does not exist: {self.command_path}",
        )
        body = get_md_body(self.command_path)

        # Gate-before-egress: AskUserQuestion must precede the first Opik-upload reference.
        gate_idx = body.find("AskUserQuestion")
        self.assertNotEqual(gate_idx, -1, "capture-session body has no AskUserQuestion gate")

        upload_idx = body.find("atif_to_opik")
        self.assertNotEqual(
            upload_idx, -1,
            "capture-session body has no atif_to_opik upload step to order against",
        )
        self.assertLess(
            gate_idx, upload_idx,
            "AskUserQuestion gate must appear BEFORE the first atif_to_opik / upload step "
            "(no network egress before the approval gate)",
        )

        # Reject branch must guard-and-clean the well-known per-run dir.
        self.assertRegex(
            body,
            r'\[\s*-d\s+"\$HOME/\.driver/capture/current"\s*\]\s*&&\s*rm\s+-rf\s+"\$HOME/\.driver/capture/current"',
            "reject branch must contain a guarded rm -rf \"$HOME/.driver/capture/current\"",
        )


class TestCaptureSyncGovernance(unittest.TestCase):
    """Registration + egress-control governance for /drvr:capture-sync.

    Mirrors TestCaptureSessionGovernance: pins the command's registration
    (plugin.json + COMMANDS scanner + comma-separated-string frontmatter) and the
    load-bearing gate-before-egress ordering of the command body.

    The wrinkle capture-sync adds: its body references ``atif_to_s3.py`` THREE
    times — ``--dry-run`` (key preview), ``--scan`` (PII counts), and the real
    upload — with the AskUserQuestion gate sitting BETWEEN the previews and the
    upload. A naive ``body.find("atif_to_s3.py")`` would land on the pre-gate
    ``--dry-run`` reference and wrongly conclude 'egress before gate'. The real
    upload therefore carries a unique ``REAL UPLOAD (egress)`` marker, and this
    test anchors the egress point on that marker so the earlier preview references
    cannot defeat the ordering assertion.
    """

    UPLOAD_MARKER = "REAL UPLOAD (egress)"

    @classmethod
    def setUpClass(cls):
        plugin_json_path = PLUGIN_CONFIG_DIR / "plugin.json"
        with open(plugin_json_path, encoding="utf-8") as f:
            cls.plugin_data = json.load(f)
        cls.command_path = PLUGIN_ROOT / "commands" / "capture-sync.md"

    def test_capture_sync_registered(self):
        """capture-sync must be registered in plugin.json + COMMANDS, have valid
        frontmatter (allowed-tools a comma-separated string with >=2 tools,
        including the get_caller_identity MCP tool), and reference itself
        fully-qualified as /drvr:capture-sync in its body."""
        # Registered in plugin.json commands array
        self.assertIn(
            "./commands/capture-sync.md",
            self.plugin_data.get("commands", []),
            "capture-sync not registered in plugin.json commands array",
        )
        # Registered in the qualified-name scanner's COMMANDS list
        self.assertIn(
            "capture-sync",
            TestCommandQualification.COMMANDS,
            "capture-sync not added to COMMANDS list",
        )
        # Command file exists
        self.assertTrue(
            self.command_path.is_file(),
            f"command file does not exist: {self.command_path}",
        )

        fm = parse_frontmatter(self.command_path)
        # Three required frontmatter fields
        for field in ("description", "argument-hint", "allowed-tools"):
            self.assertIn(field, fm, f"capture-sync missing frontmatter '{field}'")

        # allowed-tools must be a comma-separated STRING (not a YAML list)
        self.assertEqual(
            fm.get("allowed-tools-format"), "string",
            "capture-sync allowed-tools must be a comma-separated string, not a YAML list",
        )
        tools = fm.get("allowed-tools", [])
        self.assertGreaterEqual(
            len(tools), 2,
            f"capture-sync allowed-tools must list >=2 tools, got {tools}",
        )
        # The identity lookup drives the whole command — its MCP tool must be allowed.
        self.assertIn(
            "mcp__driver-mcp__get_caller_identity", tools,
            "capture-sync must allow mcp__driver-mcp__get_caller_identity for identity resolution",
        )

        # Body references the command fully-qualified
        body = get_md_body(self.command_path)
        self.assertIn(
            "/drvr:capture-sync", body,
            "capture-sync body must reference the command fully-qualified as /drvr:capture-sync",
        )

    def test_command_governance_structure(self):
        """The AskUserQuestion gate must appear BEFORE the real-upload egress step,
        and the assertion must NOT be fooled by the earlier --dry-run/--scan
        references to the same script."""
        self.assertTrue(
            self.command_path.is_file(),
            f"command file does not exist: {self.command_path}",
        )
        body = get_md_body(self.command_path)

        # The approval gate.
        gate_idx = body.find("AskUserQuestion")
        self.assertNotEqual(gate_idx, -1, "capture-sync body has no AskUserQuestion gate")

        # The real upload is uniquely marked so it is distinguishable from the
        # --dry-run / --scan previews that reference the same script.
        marker_idx = body.find(self.UPLOAD_MARKER)
        self.assertNotEqual(
            marker_idx, -1,
            f"capture-sync body is missing the {self.UPLOAD_MARKER!r} marker on the real-upload step",
        )
        # The marked step must actually invoke the upload script.
        upload_idx = body.find("atif_to_s3.py", marker_idx)
        self.assertNotEqual(
            upload_idx, -1,
            "no atif_to_s3.py invocation found at/after the REAL UPLOAD marker",
        )

        # Guard against a naive matcher: the FIRST atif_to_s3.py reference is a
        # --dry-run/--scan preview that legitimately precedes the gate. Anchoring
        # the egress point on the bare script name would wrongly place it before
        # the gate — which is exactly why we anchor on the REAL UPLOAD marker.
        first_ref = body.find("atif_to_s3.py")
        self.assertNotEqual(first_ref, -1, "capture-sync body never references atif_to_s3.py")
        self.assertLess(
            first_ref, gate_idx,
            "expected a --dry-run/--scan preview reference to atif_to_s3.py BEFORE the gate "
            "(this is why the egress point is anchored on the REAL UPLOAD marker, "
            "not the bare script name)",
        )

        # Load-bearing ordering: nothing egresses before approval.
        self.assertLess(
            gate_idx, marker_idx,
            "AskUserQuestion gate must appear BEFORE the real-upload egress step "
            "(no trajectory bytes leave the machine before the approval gate)",
        )
        self.assertLess(
            gate_idx, upload_idx,
            "AskUserQuestion gate must appear BEFORE the real-upload atif_to_s3.py invocation",
        )


class TestRollCaptureHookRegistration(unittest.TestCase):
    """Registration of the rolling-capture Stop / SessionEnd hooks and the
    SessionStart lineage hook in hooks.json.

    Pins the nested data["hooks"][<event>] shape so a regression that drops or
    moves the Stop roll hook — the SessionEnd finalize appended after
    commit-artifacts.sh — or the SessionStart lineage hook fails the suite. Asserts
    against the nested data["hooks"][<event>] path, NOT a top-level data[<event>]
    key, so the test cannot pass vacuously.
    """

    @classmethod
    def setUpClass(cls):
        cls.hooks_path = PLUGIN_ROOT / "hooks" / "hooks.json"
        with open(cls.hooks_path, encoding="utf-8") as f:
            cls.hooks_data = json.load(f)

    def _entries(self, event):
        """Flatten every hook entry registered for an event, read from the nested
        data["hooks"][event][*]["hooks"][*] path."""
        entries = []
        for matcher_block in self.hooks_data["hooks"].get(event, []):
            entries.extend(matcher_block.get("hooks", []))
        return entries

    def test_hooks_json_parses(self):
        """hooks.json must be valid JSON with a top-level 'hooks' object."""
        self.assertIsInstance(self.hooks_data, dict)
        self.assertIn("hooks", self.hooks_data)
        self.assertIsInstance(self.hooks_data["hooks"], dict)

    def test_stop_invokes_roll_capture_with_timeout(self):
        """data["hooks"]["Stop"] must invoke roll-capture.sh via ${CLAUDE_PLUGIN_ROOT}
        and declare a timeout."""
        roll_entries = [
            e for e in self._entries("Stop")
            if "roll-capture.sh" in e.get("command", "")
        ]
        self.assertTrue(
            roll_entries,
            'data["hooks"]["Stop"] does not invoke roll-capture.sh',
        )
        for entry in roll_entries:
            self.assertIn(
                "${CLAUDE_PLUGIN_ROOT}", entry["command"],
                "Stop roll-capture command must reference ${CLAUDE_PLUGIN_ROOT}",
            )
            self.assertIn(
                "timeout", entry,
                "Stop roll-capture entry must declare a timeout",
            )

    def test_session_end_has_commit_and_roll(self):
        """data["hooks"]["SessionEnd"] must contain BOTH commit-artifacts.sh and
        roll-capture.sh (the synchronous finalize, appended after the artifact commit)."""
        commands = [e.get("command", "") for e in self._entries("SessionEnd")]
        self.assertTrue(
            any("commit-artifacts.sh" in c for c in commands),
            "SessionEnd must still invoke commit-artifacts.sh",
        )
        self.assertTrue(
            any("roll-capture.sh" in c for c in commands),
            "SessionEnd must invoke roll-capture.sh (finalize)",
        )

    def test_session_start_invokes_capture_with_timeout(self):
        """data["hooks"]["SessionStart"] must invoke session-start-capture.sh via
        ${CLAUDE_PLUGIN_ROOT} and declare a timeout (read the nested
        data["hooks"]["SessionStart"] path, not a top-level key)."""
        start_entries = [
            e for e in self._entries("SessionStart")
            if "session-start-capture.sh" in e.get("command", "")
        ]
        self.assertTrue(
            start_entries,
            'data["hooks"]["SessionStart"] does not invoke session-start-capture.sh',
        )
        for entry in start_entries:
            self.assertIn(
                "${CLAUDE_PLUGIN_ROOT}", entry["command"],
                "SessionStart capture command must reference ${CLAUDE_PLUGIN_ROOT}",
            )
            self.assertIn(
                "timeout", entry,
                "SessionStart capture entry must declare a timeout",
            )


if __name__ == "__main__":
    unittest.main()
