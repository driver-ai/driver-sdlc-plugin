"""Shell integration tests for hooks/roll-capture.sh (the Stop / SessionEnd roll).

The hook is fail-open: config-gated, throttled, degrades when its tools are
absent, never blocks the turn, and always exits 0. These tests drive the REAL
hook via `subprocess.run(["bash", hook], input=<json>, ...)` and assert exit code
plus on-disk side effects -- no mocks. The pure throttle (`should_roll`) is NOT
re-implemented or mocked here: the hook invokes it via python3, and we assert the
observable roll/no-roll outcome on disk.

Every test uses an isolated tmp HOME (so config.json + the capture store live
under it, never the developer's real ~/.driver) and a unique per-test session id.
PATH is stripped to simulate a missing `uv` / `python3` for the degrade cases.

The two cases that need a real conversion (a token actually redacted into the
store; the SessionEnd synchronous finalize) require harbor, an external dependency
absent from the zero-dep CI path. They are gated with
`@unittest.skipUnless(_harbor_available(), "harbor not installed")` -- a named
justification for skipping, NOT a mock of harbor. When harbor is absent they SKIP
cleanly; that is expected.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT

HOOK = PLUGIN_ROOT / "hooks" / "roll-capture.sh"


def _harbor_available() -> bool:
    try:
        import harbor  # noqa: F401
        return True
    except Exception:
        return False


def _jq_available() -> bool:
    return shutil.which("jq") is not None


def _wait_for(path: Path, seconds: float, interval: float = 0.2) -> bool:
    """Bounded poll: True as soon as `path` exists, else False after `seconds`."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(interval)
    return path.exists()


def _assert_absent_for(test, path: Path, seconds: float, interval: float = 0.2):
    """Poll up to `seconds` asserting `path` never appears (no background roll)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        test.assertFalse(path.exists(), f"{path} should not exist (no roll expected)")
        time.sleep(interval)


# A tiny valid Claude Code JSONL transcript: one assistant turn so the converter
# yields at least one step (avoids an empty-trajectory error confounding the run).
# A planted Anthropic token lives in the assistant text so the harbor-positive
# case can prove the store holds only the REDACTED artifact.
PLANTED_TOKEN = "sk-ant-" + "A" * 40


def _transcript_lines(session_id: str, *, with_token: bool = False, n_turns: int = 1):
    lines = []
    for i in range(n_turns):
        text = "hello world step %d" % i
        if with_token and i == 0:
            text = f"the api key is {PLANTED_TOKEN}"
        lines.append(json.dumps({
            "type": "assistant", "isSidechain": False, "sessionId": session_id,
            "timestamp": "2026-06-25T00:00:00Z",
            "message": {
                "id": f"m{i}", "model": "claude-opus-4-8-20260315",
                "content": [{"type": "text", "text": text}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        }))
    return lines


@unittest.skipUnless(_jq_available(), "jq is not installed -- skipping roll-capture tests")
class RollCaptureHookBase(unittest.TestCase):
    """Shared isolated-HOME + transcript scaffolding for the roll-capture tests."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="drvr-roll-home-"))
        self.work = Path(tempfile.mkdtemp(prefix="drvr-roll-work-"))
        self.driver = self.home / ".driver"
        self.config = self.driver / "config.json"
        self.driver.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    # -- helpers --------------------------------------------------------------

    def _sid(self, label="s"):
        return f"test-{label}-{os.getpid()}-{int(time.time()*1000) % 1000000}"

    def _write_config(self, rolling_capture=True, raw=None):
        if raw is not None:
            self.config.write_text(raw)
        else:
            self.config.write_text(json.dumps({"rolling_capture": rolling_capture}))

    def _write_transcript(self, session_id, *, with_token=False, n_turns=1):
        """Write the transcript under <work>/<session-id>/session.jsonl so that
        --session-dir "$(dirname TRANSCRIPT)" == <work>/<session-id> still reaches
        <session-dir>/<session-id>/subagents (none here -> empty subagents)."""
        sess_dir = self.work / session_id
        sess_dir.mkdir(parents=True, exist_ok=True)
        tpath = sess_dir / "session.jsonl"
        tpath.write_text(
            "\n".join(_transcript_lines(session_id, with_token=with_token,
                                        n_turns=n_turns)) + "\n")
        return tpath

    def _store_dir(self, session_id):
        return self.driver / "capture" / "sessions" / session_id

    def _run(self, payload, *, path=None, env_overrides=None):
        """Run the hook with `payload` as JSON stdin under the isolated HOME."""
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        if path is not None:
            env["PATH"] = path
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(payload) if not isinstance(payload, str) else payload,
            capture_output=True, text=True, timeout=120, env=env, cwd=str(self.work),
        )

    def _payload(self, session_id, transcript, event="Stop"):
        return {
            "session_id": session_id,
            "transcript_path": str(transcript),
            "hook_event_name": event,
            "cwd": str(self.work),
        }


class TestRollCaptureGatesAndFailOpen(RollCaptureHookBase):
    """Config gate, fail-open, and graceful degrade -- all stdlib-only (no harbor)."""

    def test_disabled_when_rolling_capture_unset(self):
        # No rolling_capture key -> gate closed -> exit 0, nothing written.
        self._write_config(raw=json.dumps({}))
        sid = self._sid("unset")
        t = self._write_transcript(sid, n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists(),
                         "store must not be written when gate is closed")

    def test_disabled_when_rolling_capture_false(self):
        self._write_config(rolling_capture=False)
        sid = self._sid("false")
        t = self._write_transcript(sid, n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_no_config_file(self):
        # No config.json at all -> gate closed -> exit 0, no store.
        if self.config.exists():
            self.config.unlink()
        sid = self._sid("noconfig")
        t = self._write_transcript(sid, n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_malformed_stdin(self):
        # Not JSON at all -> exit 0, no crash, no store.
        self._write_config(rolling_capture=True)
        res = self._run("this is not json at all")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse((self.driver / "capture").exists())

    def test_malformed_config_json(self):
        # Config is unreadable JSON -> jq yields nothing -> gate closed -> exit 0.
        self._write_config(raw="{ this is not valid json ]")
        sid = self._sid("badcfg")
        t = self._write_transcript(sid, n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_uv_unavailable_on_path(self):
        # A PATH with jq + python3 but NO uv -> degrade -> exit 0, no store.
        self._write_config(rolling_capture=True)
        sid = self._sid("nouv")
        t = self._write_transcript(sid, n_turns=5)
        path = self._path_without(("uv",))
        res = self._run(self._payload(sid, t), path=path)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_python3_unavailable_on_path(self):
        # python3 backs the pure throttle; without it the hook degrades -> exit 0.
        self._write_config(rolling_capture=True)
        sid = self._sid("nopy")
        t = self._write_transcript(sid, n_turns=5)
        path = self._path_without(("python3", "python"))
        res = self._run(self._payload(sid, t), path=path)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_unsafe_session_id_traversal(self):
        # A '../escape' session id must never write outside the per-session dir.
        self._write_config(rolling_capture=True)
        sid = "../escape"
        t = self._write_transcript("safe-holder", n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        # Nothing leaked above the sessions dir into .driver/capture.
        escaped = self.driver / "capture" / "escape"
        self.assertFalse(escaped.exists())
        self.assertFalse((self.driver / "escape").exists())

    def test_unsafe_session_id_leading_dot(self):
        # A leading-dot session id ('.hidden') is rejected by the write guard.
        self._write_config(rolling_capture=True)
        sid = ".hidden"
        t = self._write_transcript("safe-holder2", n_turns=5)
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse((self.driver / "capture" / "sessions" / ".hidden").exists())

    def test_transcript_missing_file_no_crash(self):
        # transcript_path points at a nonexistent file -> the -f check fails ->
        # exit 0, no convert, no store (empty-metric / missing-file guard).
        self._write_config(rolling_capture=True)
        sid = self._sid("notranscript")
        missing = self.work / "does-not-exist.jsonl"
        res = self._run(self._payload(sid, missing))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self._store_dir(sid).exists())

    def test_below_threshold_no_background_roll(self):
        # A roll-state recording a recent roll at a record_count close to the
        # transcript's current line count -> the pure throttle short-circuits
        # BEFORE any background convert. Assert the store's redacted artifact
        # stays absent across a bounded poll (no background job launched).
        self._write_config(rolling_capture=True)
        sid = self._sid("belowthresh")
        t = self._write_transcript(sid, n_turns=5)  # 5 lines
        store = self._store_dir(sid)
        store.mkdir(parents=True, exist_ok=True)
        cur_mtime = os.stat(t).st_mtime
        # prev_count == 4 (one below the 5-line transcript): delta=1 < 20, and the
        # mtime delta is ~0 < 30 -> should_roll() is False.
        (store / "roll-state.json").write_text(
            json.dumps({"record_count": 4, "mtime": cur_mtime}))
        res = self._run(self._payload(sid, t))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        # No background convert -> the redacted artifact never appears.
        _assert_absent_for(self, store / "trajectory.redacted.json", 2.5)

    # -- PATH helper ----------------------------------------------------------

    def _path_without(self, drop_names):
        """Build a temp bin dir symlinking every needed tool EXCEPT drop_names,
        then return a PATH containing only it. Guarantees the dropped tool is
        absent regardless of where it really lives."""
        bindir = self.work / ("bin-" + "-".join(drop_names))
        bindir.mkdir(parents=True, exist_ok=True)
        for tool in ("bash", "sh", "jq", "python3", "python", "cat", "mkdir",
                     "mktemp", "mv", "rm", "wc", "stat", "tr", "printf", "uv",
                     "dirname", "env", "uname", "sleep"):
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


@unittest.skipUnless(_harbor_available(), "harbor not installed")
class TestRollCaptureHarborPositive(RollCaptureHookBase):
    """Above-threshold + enabled against a REAL fixture transcript: the backgrounded
    Stop roll publishes a redacted-only store atomically."""

    def test_above_threshold_publishes_redacted_only_store(self):
        if shutil.which("uv") is None:
            self.skipTest("uv not installed -- roll path needs uv")
        self._write_config(rolling_capture=True)
        sid = self._sid("above")
        # No prior roll-state -> first roll fires once the transcript clears the
        # min_first_count floor; several turns keep it comfortably above threshold.
        t = self._write_transcript(sid, with_token=True, n_turns=4)
        store = self._store_dir(sid)
        res = self._run(self._payload(sid, t))  # Stop -> backgrounded roll
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        redacted = store / "trajectory.redacted.json"
        # Backgrounded: poll up to ~60s for the atomic publish.
        self.assertTrue(_wait_for(redacted, 60),
                        f"redacted store did not appear: stderr={res.stderr}")
        # Atomic: the published file is always complete, valid JSON (never torn).
        data = json.loads(redacted.read_text())
        self.assertIsInstance(data, dict)
        # The store holds ONLY redacted content: the planted token is masked.
        blob = redacted.read_text()
        self.assertNotIn(PLANTED_TOKEN, blob)
        self.assertIn("[REDACTED:", blob)
        # No unredacted intermediate lingers in the store dir.
        leftovers = [p.name for p in store.iterdir()
                     if p.name.startswith(".redacted.") or p.name.startswith(".flags.")
                     or p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [], f"unredacted/temp intermediates remain: {leftovers}")


@unittest.skipUnless(_harbor_available(), "harbor not installed")
class TestRollCaptureSessionEndFinalize(RollCaptureHookBase):
    """A SessionEnd event forces a roll even below threshold and writes the store
    SYNCHRONOUSLY (foreground) -- the store exists the instant subprocess.run returns."""

    def test_session_end_forces_synchronous_roll(self):
        if shutil.which("uv") is None:
            self.skipTest("uv not installed -- roll path needs uv")
        self._write_config(rolling_capture=True)
        sid = self._sid("sessionend")
        t = self._write_transcript(sid, with_token=True, n_turns=1)
        store = self._store_dir(sid)
        # Plant a roll-state that would make the throttle say "no roll" for a Stop:
        # record_count equal to the current line count, fresh mtime. SessionEnd
        # must override this and roll anyway.
        store.mkdir(parents=True, exist_ok=True)
        cur_mtime = os.stat(t).st_mtime
        (store / "roll-state.json").write_text(
            json.dumps({"record_count": 1, "mtime": cur_mtime}))
        res = self._run(self._payload(sid, t, event="SessionEnd"))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        redacted = store / "trajectory.redacted.json"
        # Foreground finalize: the store exists the instant the call returns -- NO poll.
        self.assertTrue(redacted.exists(),
                        f"SessionEnd roll must finalize synchronously; stderr={res.stderr}")
        data = json.loads(redacted.read_text())
        self.assertIsInstance(data, dict)
        self.assertNotIn(PLANTED_TOKEN, redacted.read_text())


class TestRollCaptureNetworkFree(RollCaptureHookBase):
    """The roll path is network-free by construction: it never imports the uploader.

    Mirrors the atif_to_opik boundary proof -- importing the modules the roll path
    invokes must not pull `opik` (the network egress module) into the process.
    Pure-import assertion; no socket, no mock."""

    def test_roll_path_modules_do_not_import_opik(self):
        cap = str(PLUGIN_ROOT / "scripts" / "capture")
        code = (
            "import sys\n"
            f"sys.path.insert(0, {cap!r})\n"
            "import capture_store_core\n"
            "import redact\n"
            "assert 'opik' not in sys.modules, 'roll path pulled in opik (network egress)'\n"
            "print('OK')\n"
        )
        res = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("OK", res.stdout)


if __name__ == "__main__":
    unittest.main()
