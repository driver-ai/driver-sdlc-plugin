"""Shell integration tests for scripts/capture/capture-statusline.sh (the
statusLine capture badge script).

The badge is config-gated and fail-open: with rolling_capture enabled it
prints exactly "📹 capturing\n"; a disabled/absent flag, a missing, corrupt,
or non-dict config, garbage or absent stdin, and a missing python3 all yield
empty stdout -- always exit 0 (a broken statusline must never break a
session). The badge decision itself lives in the pure core
(capture_config_core.statusline_badge); these tests pin the shell's
observable stdout/exit contract only. The statusline never runs headless, so
the script is driven directly -- it IS the real artifact.

Tests drive the REAL script via `subprocess.run(["sh", script], ...)` with an
isolated tmp HOME (config.json lives under it, never the developer's real
~/.driver) and a synthetic statusLine render payload built from the
documented stdin field set -- no mocks.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT

SCRIPT = PLUGIN_ROOT / "scripts" / "capture" / "capture-statusline.sh"

BADGE_LINE = "📹 capturing\n"


def _python3_available() -> bool:
    return shutil.which("python3") is not None


@unittest.skipUnless(_python3_available(),
                     "python3 is not installed -- skipping statusline badge tests")
class CaptureStatuslineBase(unittest.TestCase):
    """Shared isolated-HOME scaffolding (the badge needs no git repos)."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="drvr-sline-home-"))
        self.work = Path(tempfile.mkdtemp(prefix="drvr-sline-work-"))
        self.driver = self.home / ".driver"
        self.config = self.driver / "config.json"
        self.driver.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    # -- helpers --------------------------------------------------------------

    def _write_config(self, rolling_capture=True, raw=None):
        if raw is not None:
            self.config.write_text(raw)
        else:
            self.config.write_text(json.dumps({"rolling_capture": rolling_capture}))

    def _payload(self):
        """Synthetic statusLine render payload (documented stdin field set)."""
        return {
            "hook_event_name": "Status",
            "session_id": "test-sline-session",
            "transcript_path": str(self.work / "transcript.jsonl"),
            "cwd": str(self.work),
            "model": {"id": "claude-test-1", "display_name": "Claude Test"},
            "workspace": {"current_dir": str(self.work),
                          "project_dir": str(self.work)},
            "version": "2.1.204",
            "output_style": {"name": "default"},
            "cost": {"total_cost_usd": 0.0123, "total_duration_ms": 4500,
                     "total_api_duration_ms": 2100, "total_lines_added": 3,
                     "total_lines_removed": 1},
            "context_window": {"total_input_tokens": 1200,
                               "total_output_tokens": 340,
                               "context_window_size": 200000,
                               "used_percentage": 0.8,
                               "remaining_percentage": 99.2},
            "exceeds_200k_tokens": False,
            "thinking": {"enabled": True},
        }

    def _run(self, stdin_text, *, devnull_stdin=False, path=None):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        if path is not None:
            env["PATH"] = path
        kwargs = dict(capture_output=True, text=True, timeout=60, env=env,
                      cwd=str(self.work))
        if devnull_stdin:
            kwargs["stdin"] = subprocess.DEVNULL
        else:
            kwargs["input"] = stdin_text
        return subprocess.run(["sh", str(SCRIPT)], **kwargs)

    # -- PATH helper (mirrors test_session_start_hook) -------------------------

    def _path_without(self, drop_names):
        bindir = self.work / ("bin-" + "-".join(drop_names))
        bindir.mkdir(parents=True, exist_ok=True)
        for tool in ("bash", "sh", "jq", "python3", "python", "cat", "mkdir",
                     "mv", "rm", "printf", "dirname", "env", "git", "cd"):
            if tool in drop_names:
                continue
            real = shutil.which(tool)
            if real:
                link = bindir / tool
                if not link.exists():
                    try:
                        link.symlink_to(real)
                    except OSError:
                        pass
        return str(bindir)


class TestBadgeOutput(CaptureStatuslineBase):
    """Enabled flag -> exactly the badge line; every closed gate -> empty."""

    def test_badge_when_enabled(self):
        self._write_config(rolling_capture=True)
        res = self._run(json.dumps(self._payload()))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout, BADGE_LINE)

    def test_empty_when_disabled_absent_corrupt(self):
        cases = {
            "flag_false": lambda: self._write_config(rolling_capture=False),
            "flag_absent": lambda: self._write_config(raw=json.dumps({})),
            "config_missing": lambda: (self.config.unlink()
                                       if self.config.exists() else None),
            "config_corrupt": lambda: self._write_config(raw="{ not json ]"),
            "config_nondict": lambda: self._write_config(raw=json.dumps(["x"])),
        }
        for name, arrange in cases.items():
            with self.subTest(case=name):
                arrange()
                res = self._run(json.dumps(self._payload()))
                self.assertEqual(res.returncode, 0, msg=res.stderr)
                self.assertEqual(res.stdout, "",
                                 f"case {name}: expected empty stdout, "
                                 f"got {res.stdout!r}")


class TestAlwaysExitZero(CaptureStatuslineBase):
    """Every stdin shape x config shape exits 0 -- the fail-open contract."""

    def test_always_exit_zero(self):
        stdin_cases = {
            "full_payload": lambda: self._run(json.dumps(self._payload())),
            "garbage_stdin": lambda: self._run("%%% not json at all %%%"),
            "empty_stdin": lambda: self._run(""),
            "no_stdin": lambda: self._run(None, devnull_stdin=True),
        }
        config_cases = {
            "enabled": lambda: self._write_config(rolling_capture=True),
            "config_missing": lambda: (self.config.unlink()
                                       if self.config.exists() else None),
            "config_corrupt": lambda: self._write_config(raw="{ not json ]"),
        }
        for cfg_name, arrange in config_cases.items():
            for stdin_name, run in stdin_cases.items():
                with self.subTest(config=cfg_name, stdin=stdin_name):
                    arrange()
                    res = run()
                    self.assertEqual(res.returncode, 0, msg=res.stderr)


class TestFailOpen(CaptureStatuslineBase):
    """Missing python3 degrades silently -- exit 0, no output."""

    def test_python3_missing_fail_open(self):
        self._write_config(rolling_capture=True)
        path = self._path_without(("python3",))
        res = self._run(json.dumps(self._payload()), path=path)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout, "",
                         f"expected empty stdout, got: {res.stdout!r}")


if __name__ == "__main__":
    unittest.main()
