"""Compose-contract tests for scripts/capture/statusline-wrapper-template.sh.

The template ships with a {{ORIGINAL_COMMAND}} placeholder that the install
flow substitutes with the user's existing statusline command. These tests
instantiate the template into a tmp directory laid out like the installed
copy under ~/.claude/drvr/ -- the badge script (capture-statusline.sh) and
the pure core (capture_config_core.py) sit beside the instantiated wrapper --
and drive the wrapper as a real subprocess with a synthetic statusLine render
payload on stdin. No mocks: the fixture "original statusline" is a real
on-disk script.

The compose contract pinned here: every original output line is preserved
verbatim (multiline, ANSI codes, even partial output from a nonzero-exit
original -- never blanked, never clobbered) with the capture badge appended
to the FINAL line only when rolling_capture is on; no trailing space when the
badge is empty, no leading space when the original is silent or missing; the
wrapper always exits 0.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT

TEMPLATE = PLUGIN_ROOT / "scripts" / "capture" / "statusline-wrapper-template.sh"
BADGE_SCRIPT = PLUGIN_ROOT / "scripts" / "capture" / "capture-statusline.sh"
CORE = PLUGIN_ROOT / "scripts" / "capture" / "capture_config_core.py"

BADGE = "📹 capturing"
PLACEHOLDER = "{{ORIGINAL_COMMAND}}"


def _python3_available() -> bool:
    return shutil.which("python3") is not None


@unittest.skipUnless(_python3_available(),
                     "python3 is not installed -- skipping wrapper template tests")
class StatuslineWrapperTemplateBase(unittest.TestCase):
    """Isolated tmp HOME with an installed-copy layout under ~/.claude/drvr/."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="drvr-slwrap-home-"))
        self.work = Path(tempfile.mkdtemp(prefix="drvr-slwrap-work-"))
        self.driver = self.home / ".driver"
        self.config = self.driver / "config.json"
        self.driver.mkdir(parents=True, exist_ok=True)
        # Installed-copy layout: badge script + pure core beside the wrapper,
        # exactly as the install flow lays them out under ~/.claude/drvr/.
        self.install = self.home / ".claude" / "drvr"
        self.install.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BADGE_SCRIPT, self.install / "capture-statusline.sh")
        shutil.copy2(CORE, self.install / "capture_config_core.py")
        self.fixture_script = self.install / "original-statusline.sh"

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    # -- helpers --------------------------------------------------------------

    def _write_config(self, rolling_capture=True, raw=None):
        if raw is not None:
            self.config.write_text(raw)
        else:
            self.config.write_text(json.dumps({"rolling_capture": rolling_capture}))

    def _fixture(self, body):
        """Write a real on-disk fixture statusline script; return the command
        string that runs it (what the install flow would substitute)."""
        self.fixture_script.write_text("#!/bin/sh\n" + body + "\n")
        return f'sh "{self.fixture_script}"'

    def _instantiate(self, command):
        """Replace the placeholder with `command`, write the wrapper beside
        the badge script, return its path."""
        text = TEMPLATE.read_text(encoding="utf-8")
        wrapper = self.install / "statusline-wrapper.sh"
        wrapper.write_text(text.replace(PLACEHOLDER, command))
        return wrapper

    def _payload(self):
        """Synthetic statusLine render payload (documented stdin field set)."""
        return {
            "hook_event_name": "Status",
            "session_id": "test-slwrap-session",
            "transcript_path": str(self.work / "transcript.jsonl"),
            "cwd": str(self.work),
            "model": {"id": "claude-test-1", "display_name": "Claude Test"},
            "workspace": {"current_dir": str(self.work),
                          "project_dir": str(self.work)},
            "version": "2.1.204",
            "output_style": {"name": "default"},
            "exceeds_200k_tokens": False,
        }

    def _run(self, wrapper):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        return subprocess.run(
            ["sh", str(wrapper)],
            input=json.dumps(self._payload()),
            capture_output=True, text=True, timeout=60, env=env,
            cwd=str(self.work),
        )


class TestWrapperCompose(StatuslineWrapperTemplateBase):
    """Original output + badge on the final line, exit 0."""

    def test_compose_single_line(self):
        self._write_config(rolling_capture=True)
        wrapper = self._instantiate(self._fixture("printf '%s' 'my-status'"))
        res = self._run(wrapper)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout, f"my-status {BADGE}\n")

    def test_compose_multiline_badge_on_final_line(self):
        # CC renders every stdout line: all original lines must survive
        # verbatim, with the badge appended to the LAST line only.
        self._write_config(rolling_capture=True)
        wrapper = self._instantiate(
            self._fixture("printf 'line1\\nline2\\nline3\\n'"))
        res = self._run(wrapper)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout, f"line1\nline2\nline3 {BADGE}\n")


class TestWrapperBadgeOff(StatuslineWrapperTemplateBase):
    """Flag off -> the original output passes through exactly."""

    def test_badge_empty_original_unchanged(self):
        self._write_config(rolling_capture=False)
        wrapper = self._instantiate(self._fixture("printf 'my-status\\n'"))
        res = self._run(wrapper)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        # Exactly the original -- in particular, no trailing space.
        self.assertEqual(res.stdout, "my-status\n")


class TestWrapperDegradedOriginal(StatuslineWrapperTemplateBase):
    """A missing or failing original never breaks the statusline."""

    def test_original_missing_badge_only(self):
        self._write_config(rolling_capture=True)
        command = self._fixture("printf 'x\\n'")
        # Simulate a broken install: the user's original command is gone.
        self.fixture_script.unlink()
        wrapper = self._instantiate(command)
        res = self._run(wrapper)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        # Badge alone -- in particular, no leading space.
        self.assertEqual(res.stdout, f"{BADGE}\n")

    def test_original_nonzero_still_composes(self):
        # The original prints partial output, THEN exits 1: the partial
        # output must be preserved in the compose, never blanked.
        self._write_config(rolling_capture=True)
        wrapper = self._instantiate(
            self._fixture("printf '%s' 'partial'\nexit 1"))
        res = self._run(wrapper)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout, f"partial {BADGE}\n")


class TestWrapperAnsi(StatuslineWrapperTemplateBase):
    """ANSI color codes pass through the compose verbatim."""

    def test_ansi_passthrough(self):
        self._write_config(rolling_capture=True)
        wrapper = self._instantiate(
            self._fixture("printf '\\033[31mred\\033[0m'"))
        res = self._run(wrapper)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout, f"\x1b[31mred\x1b[0m {BADGE}\n")


if __name__ == "__main__":
    unittest.main()
