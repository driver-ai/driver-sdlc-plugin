"""Unit tests for the capture control + indicator pure core (capture_config_core).

Pure-core tests: values in, values out — no I/O, no mocks, no subprocesses.
Config dicts are passed as arguments, never read from disk. Stdlib
`unittest` only.
"""
import json
import sys
import unittest

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import capture_config_core as core


ENABLED = {"rolling_capture": True}
ENABLED_STRING = {"rolling_capture": "true"}


# ---------------------------------------------------------------------------
# is_rolling_capture_enabled
# ---------------------------------------------------------------------------

class TestIsRollingCaptureEnabled(unittest.TestCase):
    def test_enabled_true(self):
        self.assertTrue(core.is_rolling_capture_enabled({"rolling_capture": True}))

    def test_enabled_string_true(self):
        # Parity with the shipped jq gates: `.rolling_capture // false`
        # string-compared to "true" treats the string "true" as enabled too.
        # All four decision points (two hook gates, banner, badge) must agree.
        self.assertTrue(core.is_rolling_capture_enabled({"rolling_capture": "true"}))

    def test_enabled_false_absent_nondict(self):
        # Non-dict configs are never enabled.
        for config in (None, [], "x"):
            with self.subTest(config=config):
                self.assertFalse(core.is_rolling_capture_enabled(config))
        # Dict configs: only True / "true" enable — everything else is
        # disabled, including truthy-but-not-enabled values (the gates'
        # string-compare-to-"true" semantics).
        for value in (False, 1, "TRUE", "yes"):
            with self.subTest(value=value):
                self.assertFalse(
                    core.is_rolling_capture_enabled({"rolling_capture": value}))
        # Absent key.
        self.assertFalse(core.is_rolling_capture_enabled({}))


# ---------------------------------------------------------------------------
# set_rolling_capture
# ---------------------------------------------------------------------------

class TestSetRollingCapture(unittest.TestCase):
    def test_set_on_from_absent(self):
        new, changed = core.set_rolling_capture({}, True)
        self.assertEqual(new, {"rolling_capture": True})
        self.assertTrue(changed)

    def test_set_off_from_absent(self):
        # "Already stopped" on a machine that never enabled capture:
        # no key invented.
        new, changed = core.set_rolling_capture({}, False)
        self.assertEqual(new, {})
        self.assertFalse(changed)

    def test_set_normalizes_nonbool(self):
        # A stored non-bool value is normalized to the exact boolean, and
        # counts as a change even when it already reads as enabled.
        for stored in ("true", 1):
            with self.subTest(stored=stored):
                new, changed = core.set_rolling_capture(
                    {"rolling_capture": stored}, True)
                self.assertTrue(changed)
                self.assertIs(new["rolling_capture"], True)
        # changed is False ONLY when the stored value is already the exact
        # boolean (1 == True in Python — an isinstance check is required).
        new, changed = core.set_rolling_capture({"rolling_capture": True}, True)
        self.assertFalse(changed)
        self.assertIs(new["rolling_capture"], True)

    def test_set_off_preserves_keys(self):
        original = {
            "rolling_capture": True,
            "projects_path": "/somewhere/projects",
            "friction_tracking": True,
            "trajectory_capture": {"mode": "opt-in"},
        }
        snapshot = {
            "rolling_capture": True,
            "projects_path": "/somewhere/projects",
            "friction_tracking": True,
            "trajectory_capture": {"mode": "opt-in"},
        }
        new, changed = core.set_rolling_capture(original, False)
        self.assertTrue(changed)
        self.assertIs(new["rolling_capture"], False)
        # Unknown keys survive verbatim.
        self.assertEqual(new["projects_path"], "/somewhere/projects")
        self.assertEqual(new["friction_tracking"], True)
        self.assertEqual(new["trajectory_capture"], {"mode": "opt-in"})
        # Input never mutated.
        self.assertEqual(original, snapshot)

    def test_set_idempotent(self):
        for config, enabled in (({"rolling_capture": True}, True),
                                ({"rolling_capture": False}, False)):
            with self.subTest(config=config, enabled=enabled):
                new, changed = core.set_rolling_capture(config, enabled)
                self.assertFalse(changed)
                self.assertEqual(new, config)

    def test_set_nondict_treated_as_empty(self):
        # Read tolerance only — the shell refuses non-dict files on disk
        # before calling.
        new, changed = core.set_rolling_capture(None, True)
        self.assertEqual(new, {"rolling_capture": True})
        self.assertTrue(changed)


# ---------------------------------------------------------------------------
# banner_message
# ---------------------------------------------------------------------------

class TestBannerMessage(unittest.TestCase):
    def test_banner_on_startup_resume_clear(self):
        for source in ("startup", "resume", "clear"):
            for config in (ENABLED, ENABLED_STRING):
                with self.subTest(source=source, config=config):
                    msg = core.banner_message(config, source)
                    self.assertIsInstance(msg, str)
                    self.assertIn("🔴 Capture ON", msg)
                    self.assertIn("/drvr:capture-stop", msg)

    def test_banner_none_on_compact_disabled_unknown_source(self):
        # compact never banners, even when enabled.
        self.assertIsNone(core.banner_message(ENABLED, "compact"))
        # Disabled config never banners, even on a banner source.
        self.assertIsNone(core.banner_message({"rolling_capture": False}, "startup"))
        self.assertIsNone(core.banner_message({}, "startup"))
        self.assertIsNone(core.banner_message(None, "startup"))
        # Unknown / missing source never banners.
        self.assertIsNone(core.banner_message(ENABLED, None))
        self.assertIsNone(core.banner_message(ENABLED, "unknown"))


# ---------------------------------------------------------------------------
# banner_hook_json
# ---------------------------------------------------------------------------

class TestBannerHookJson(unittest.TestCase):
    def test_banner_hook_json_envelope(self):
        out = core.banner_hook_json(ENABLED, "startup")
        self.assertIsInstance(out, str)
        # Parse-then-compare: the raw serialized output is ensure_ascii-escaped
        # (the emoji appears as \uXXXX escapes), so never assert the raw emoji
        # on the serialized string.
        parsed = json.loads(out)
        self.assertEqual(parsed, {
            "continue": True,
            "systemMessage": core.banner_message(ENABLED, "startup"),
        })
        # Escaping is safe for quotes/emoji: the round-tripped message still
        # carries the emoji and command reference.
        self.assertIn("🔴 Capture ON", parsed["systemMessage"])
        self.assertIn("/drvr:capture-stop", parsed["systemMessage"])
        # None whenever banner_message is None.
        self.assertIsNone(core.banner_hook_json(ENABLED, "compact"))
        self.assertIsNone(core.banner_hook_json({}, "startup"))
        self.assertIsNone(core.banner_hook_json(None, None))


# ---------------------------------------------------------------------------
# statusline_badge
# ---------------------------------------------------------------------------

class TestStatuslineBadge(unittest.TestCase):
    def test_statusline_badge(self):
        self.assertEqual(core.statusline_badge(ENABLED), "📹 capturing")
        self.assertEqual(core.statusline_badge(ENABLED_STRING), "📹 capturing")
        # Disabled / absent / non-dict → empty string.
        for config in ({"rolling_capture": False}, {}, None, [], "x"):
            with self.subTest(config=config):
                self.assertEqual(core.statusline_badge(config), "")


if __name__ == "__main__":
    unittest.main()
