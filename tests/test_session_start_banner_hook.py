"""Shell integration tests for hooks/session-start-banner.sh (the SessionStart
capture-awareness banner hook).

The banner is fail-open and config-gated: with rolling_capture enabled it
prints exactly one JSON line `{"continue": true, "systemMessage": ...}` on
sources startup/resume/clear, and prints nothing on compact, when the flag is
false/absent, when the config is missing, on malformed stdin, or when python3
is unavailable -- always exiting 0. The banner decision itself lives in the
pure core (capture_config_core.banner_hook_json); these tests pin the shell's
observable behavior only.

Tests drive the REAL hook via `subprocess.run(["sh", hook], input=<json>, ...)`
with an isolated tmp HOME (config.json lives under it, never the developer's
real ~/.driver) -- no mocks. Assertions on the banner content are made AFTER
json.loads: the raw stdout is ensure_ascii-escaped by design (locale-proof),
so the raw emoji never appears on the raw stream.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT

HOOK = PLUGIN_ROOT / "hooks" / "session-start-banner.sh"


def _python3_available() -> bool:
    return shutil.which("python3") is not None


@unittest.skipUnless(_python3_available(),
                     "python3 is not installed -- skipping banner hook tests")
class SessionStartBannerHookBase(unittest.TestCase):
    """Shared isolated-HOME scaffolding (the banner needs no git repos)."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="drvr-banner-home-"))
        self.work = Path(tempfile.mkdtemp(prefix="drvr-banner-work-"))
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

    def _payload(self, source="startup"):
        return {"session_id": "test-banner-session", "cwd": str(self.work),
                "hook_event_name": "SessionStart", "source": source}

    def _run(self, payload, *, path=None):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        if path is not None:
            env["PATH"] = path
        return subprocess.run(
            ["sh", str(HOOK)],
            input=json.dumps(payload) if not isinstance(payload, str) else payload,
            capture_output=True, text=True, timeout=60, env=env, cwd=str(self.work),
        )

    def _assert_banner_emitted(self, res):
        """Exit 0, stdout is exactly one JSON line whose parsed systemMessage is
        the banner (parse-then-compare: raw stdout is ensure_ascii-escaped)."""
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        lines = res.stdout.splitlines()
        self.assertEqual(len(lines), 1,
                         f"expected exactly one JSON line, got: {res.stdout!r}")
        parsed = json.loads(lines[0])
        self.assertIs(parsed.get("continue"), True)
        self.assertIn("systemMessage", parsed)
        message = parsed["systemMessage"]
        self.assertIn("Capture ON", message)
        self.assertIn("/drvr:capture-stop", message)

    def _assert_silent(self, res):
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(res.stdout, "",
                         f"expected empty stdout, got: {res.stdout!r}")

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


class TestBannerEmitted(SessionStartBannerHookBase):
    """Enabled flag + banner sources -> one JSON systemMessage line, exit 0."""

    def test_banner_on_startup(self):
        self._write_config(rolling_capture=True)
        res = self._run(self._payload(source="startup"))
        self._assert_banner_emitted(res)

    def test_banner_on_resume(self):
        self._write_config(rolling_capture=True)
        res = self._run(self._payload(source="resume"))
        self._assert_banner_emitted(res)

    def test_banner_on_clear(self):
        self._write_config(rolling_capture=True)
        res = self._run(self._payload(source="clear"))
        self._assert_banner_emitted(res)


class TestBannerSilent(SessionStartBannerHookBase):
    """Non-banner sources and closed gates -> empty stdout, exit 0."""

    def test_silent_on_compact(self):
        self._write_config(rolling_capture=True)
        res = self._run(self._payload(source="compact"))
        self._assert_silent(res)

    def test_silent_when_disabled_or_missing_config(self):
        cases = {
            "flag_false": lambda: self._write_config(rolling_capture=False),
            "flag_absent": lambda: self._write_config(raw=json.dumps({})),
            "config_missing": lambda: (self.config.unlink()
                                       if self.config.exists() else None),
        }
        for name, arrange in cases.items():
            with self.subTest(case=name):
                arrange()
                res = self._run(self._payload(source="startup"))
                self._assert_silent(res)


class TestBannerFailOpen(SessionStartBannerHookBase):
    """Malformed inputs and missing tools degrade silently -- exit 0, no output."""

    def test_malformed_stdin_fail_open(self):
        self._write_config(rolling_capture=True)
        res = self._run("this is not json at all")
        self._assert_silent(res)

    def test_python3_missing_fail_open(self):
        self._write_config(rolling_capture=True)
        path = self._path_without(("python3",))
        res = self._run(self._payload(source="startup"), path=path)
        self._assert_silent(res)


if __name__ == "__main__":
    unittest.main()
