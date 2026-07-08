"""Shell tests for scripts/capture/set_rolling_capture.py (the flip command shell).

The shell flips `rolling_capture` in $HOME/.driver/config.json: argv parse, config
read, atomic write, human-readable report, exit codes. Every decision (what the new
config is, whether anything changed) lives in capture_config_core; these tests pin
only the shell's OBSERVABLE contract:

  exit 0 = flipped or already in target state;
  exit 1 = bad argv, unreadable/corrupt/non-dict config (never clobbered), or
           write failure.

All tests drive the REAL script via `subprocess.run([sys.executable, SCRIPT, ...])`
with an isolated tmp HOME -- always OVERRIDDEN, never deleted (`expanduser` falls
back to the pwd database and would read the real home) -- and zero mocks. File
content is asserted via json.load, never string matching; never-clobber cases
assert the file is byte-identical after the run; idempotency asserts st_ino
(os.replace always changes the inode; float mtime is same-second-flaky on coarse
filesystems).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT

SCRIPT = PLUGIN_ROOT / "scripts" / "capture" / "set_rolling_capture.py"


class SetRollingCaptureShellBase(unittest.TestCase):
    """Isolated tmp HOME per test; the script only ever touches $HOME/.driver."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="drvr-flip-home-"))
        self.driver = self.home / ".driver"
        self.config = self.driver / "config.json"

    def tearDown(self):
        # Restore perms first: the write-failure test chmods .driver to 0o555,
        # and rmtree cannot delete the children of a read-only directory.
        if self.driver.exists():
            os.chmod(self.driver, 0o755)
        shutil.rmtree(self.home, ignore_errors=True)

    # -- helpers ---------------------------------------------------------------

    def _write_config(self, obj=None, raw=None):
        self.driver.mkdir(parents=True, exist_ok=True)
        self.config.write_text(raw if raw is not None else json.dumps(obj))

    def _read_config(self):
        with open(self.config) as f:
            return json.load(f)

    def _run(self, flag):
        return subprocess.run(
            [sys.executable, str(SCRIPT), flag],
            env={**os.environ, "HOME": str(self.home)},
            capture_output=True, text=True, timeout=60, cwd=str(PLUGIN_ROOT),
        )

    def _tmp_residue(self):
        if not self.driver.exists():
            return []
        return sorted(p.name for p in self.driver.glob("*.tmp*"))


class TestFlipAndReport(SetRollingCaptureShellBase):
    """Happy paths: flip, create-on-start, no-create-on-stop, preserve, idempotence."""

    def test_off_flips_and_reports(self):
        self._write_config({"rolling_capture": True})
        res = self._run("--off")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("stopped", res.stdout.lower())
        self.assertIs(self._read_config()["rolling_capture"], False)

    def test_on_creates_missing_config(self):
        self.assertFalse(self.driver.exists())
        res = self._run("--on")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertTrue(self.config.exists(),
                        "--on must create ~/.driver/config.json when absent")
        self.assertIs(self._read_config()["rolling_capture"], True)

    def test_off_missing_config_no_create(self):
        self.assertFalse(self.driver.exists())
        res = self._run("--off")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("already stopped", res.stdout.lower())
        self.assertFalse(self.config.exists(),
                         "--off must not invent a config file")
        self.assertFalse(self.driver.exists(),
                         "--off must not create ~/.driver either")

    def test_preserves_unknown_keys(self):
        seeded = {
            "rolling_capture": True,
            "projects_path": "/somewhere/projects",
            "friction_tracking": {"enabled": True},
            "trajectory_capture": False,
        }
        self._write_config(seeded)
        res = self._run("--off")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        after = self._read_config()
        self.assertIs(after["rolling_capture"], False)
        for key in ("projects_path", "friction_tracking", "trajectory_capture"):
            self.assertEqual(after[key], seeded[key],
                             f"unknown key {key!r} must survive the flip verbatim")

    def test_idempotent_no_rewrite(self):
        self._write_config({"rolling_capture": False})
        ino_before = os.stat(self.config).st_ino
        res = self._run("--off")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("already", res.stdout.lower())
        self.assertEqual(os.stat(self.config).st_ino, ino_before,
                         "already-in-target-state must not rewrite the file "
                         "(os.replace always changes the inode)")
        self.assertIs(self._read_config()["rolling_capture"], False)

    def test_no_tmp_residue(self):
        self._write_config({"rolling_capture": True})
        res = self._run("--off")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertEqual(self._tmp_residue(), [],
                         "a successful flip must clean up its tmp file")


class TestNeverClobber(SetRollingCaptureShellBase):
    """Corrupt or valid-JSON-but-non-dict config: exit 1, file byte-identical."""

    def _assert_refused(self, raw, flag):
        self._write_config(raw=raw)
        before = self.config.read_bytes()
        res = self._run(flag)
        self.assertEqual(res.returncode, 1,
                         f"{flag} on {raw!r} must exit 1, got {res.returncode} "
                         f"(stdout={res.stdout!r})")
        self.assertNotEqual(res.stderr.strip(), "",
                            "a refusal must explain itself on stderr")
        self.assertEqual(self.config.read_bytes(), before,
                         f"{flag} on {raw!r} must leave the file byte-identical")

    def test_corrupt_config_refused(self):
        for flag in ("--on", "--off"):
            with self.subTest(flag=flag):
                self._assert_refused("{ this is not valid json ]", flag)

    def test_nondict_config_refused(self):
        # Never-clobber extends past parse errors: valid JSON that is not an
        # object is not ours to rewrite (the core's treat-as-{} is read-only).
        for raw in ("[]", '"x"'):
            for flag in ("--on", "--off"):
                with self.subTest(raw=raw, flag=flag):
                    self._assert_refused(raw, flag)


@unittest.skipUnless(os.geteuid() != 0,
                     "running as root -- directory write permissions are not enforced")
class TestWriteFailure(SetRollingCaptureShellBase):
    """Unwritable ~/.driver: exit 1, clear message, no tmp residue, config intact."""

    def test_write_failure_exit1_no_residue(self):
        self._write_config({"rolling_capture": False})
        before = self.config.read_bytes()
        os.chmod(self.driver, 0o555)  # read/list ok, create/rename refused; tearDown restores
        res = self._run("--on")
        self.assertEqual(res.returncode, 1,
                         f"unwritable config dir must exit 1 (stdout={res.stdout!r})")
        self.assertNotEqual(res.stderr.strip(), "",
                            "a write failure must explain itself on stderr")
        self.assertEqual(self._tmp_residue(), [],
                         "a failed write must leave no *.tmp* residue")
        self.assertEqual(self.config.read_bytes(), before,
                         "a failed write must leave the existing config untouched")


if __name__ == "__main__":
    unittest.main()
