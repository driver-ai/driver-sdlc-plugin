"""Shell integration tests for hooks/session-start-capture.sh (the SessionStart
lineage hook).

The hook is fail-open: config-gated, startup-only, degrades when its tools are
absent, never crashes, and always exits 0. On a genuinely NEW session
(source=startup) it records a branch-arc index entry with lineage to the most
recent prior session of that branch+cwd; the roll path later enriches the same
entry with counts/cost.

These tests drive the REAL hook via `subprocess.run(["bash", hook], input=<json>,
...)` and assert exit code plus on-disk index side effects -- no mocks. The pure
grouping/lineage/merge helpers in capture_store_core are NOT re-implemented or
mocked here: the hook invokes them via python3, and we assert the observable
index contents on disk.

Every test uses an isolated tmp HOME (so config.json + the capture index live
under it, never the developer's real ~/.driver), a real seeded index.json, real
stdin JSON, and -- for the branch cases -- a real on-disk git repo created under
the test's tmp dir. A unique per-test session id keeps runs independent.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT

HOOK = PLUGIN_ROOT / "hooks" / "session-start-capture.sh"


def _jq_available() -> bool:
    return shutil.which("jq") is not None


def _git_available() -> bool:
    return shutil.which("git") is not None


@unittest.skipUnless(_jq_available(), "jq is not installed -- skipping session-start tests")
class SessionStartHookBase(unittest.TestCase):
    """Shared isolated-HOME + git-repo + index scaffolding for the tests."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="drvr-sstart-home-"))
        self.work = Path(tempfile.mkdtemp(prefix="drvr-sstart-work-"))
        self.driver = self.home / ".driver"
        self.config = self.driver / "config.json"
        self.capture = self.driver / "capture"
        self.index = self.capture / "index.json"
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

    def _write_index(self, obj):
        """Seed a real on-disk index.json (raw string or dict)."""
        self.capture.mkdir(parents=True, exist_ok=True)
        if isinstance(obj, str):
            self.index.write_text(obj)
        else:
            self.index.write_text(json.dumps(obj, indent=2))

    def _read_index(self):
        return json.loads(self.index.read_text())

    def _git_repo(self, branch):
        """Create a real git repo under work/ on `branch`, return its realpath.

        realpath-normalized so it matches the hook's os.path.realpath(cwd).
        """
        repo = self.work / f"repo-{branch}-{os.getpid()}-{int(time.time()*1000)%1000000}"
        repo.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update({
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        })
        subprocess.run(["git", "init", "-q"], cwd=str(repo), env=env, check=True,
                       capture_output=True)
        subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=str(repo),
                       env=env, check=True, capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), env=env, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo),
                       env=env, check=True, capture_output=True)
        return os.path.realpath(str(repo))

    def _run(self, payload, *, path=None):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        if path is not None:
            env["PATH"] = path
        return subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(payload) if not isinstance(payload, str) else payload,
            capture_output=True, text=True, timeout=60, env=env, cwd=str(self.work),
        )

    def _payload(self, session_id, cwd, source="startup"):
        return {"session_id": session_id, "source": source, "cwd": str(cwd),
                "hook_event_name": "SessionStart"}


class TestSessionStartGate(SessionStartHookBase):
    """rolling_capture gate + source gate + fail-open, all stdlib (no logs2atif)."""

    def test_disabled_when_rolling_capture_unset(self):
        # No rolling_capture key -> gate closed -> exit 0, index untouched.
        self._write_config(raw=json.dumps({}))
        sid = self._sid("unset")
        cwd = self._git_repo("main") if _git_available() else self.work
        res = self._run(self._payload(sid, cwd))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self.index.exists(),
                         "index must not be written when gate is closed")

    def test_disabled_when_rolling_capture_false(self):
        self._write_config(rolling_capture=False)
        sid = self._sid("false")
        cwd = self._git_repo("main") if _git_available() else self.work
        res = self._run(self._payload(sid, cwd))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self.index.exists())

    def test_no_config_file(self):
        if self.config.exists():
            self.config.unlink()
        sid = self._sid("noconfig")
        res = self._run(self._payload(sid, self.work))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self.index.exists())


@unittest.skipUnless(_git_available(), "git is not installed -- skipping startup lineage tests")
class TestSessionStartStartup(SessionStartHookBase):
    """source=startup writes a branch:<branch> entry and links lineage."""

    def test_startup_writes_branch_entry_with_null_counts(self):
        # A brand-new startup on a real git repo writes a branch:<branch> entry
        # with record_count/total_cost_usd == null (seeded None so the first roll
        # overwrites them) and prev_session_id linked from a seeded prior session.
        self._write_config(rolling_capture=True)
        repo = self._git_repo("feature")
        prior_sid = self._sid("prior")
        new_sid = self._sid("new")
        # Seed a same-branch+cwd prior session so lineage resolves to it.
        self._write_index({
            "branch:feature": {
                prior_sid: {
                    "group_key": "branch:feature", "session_id": prior_sid,
                    "cwd": repo, "first_seen": "2026-06-01T00:00:00+00:00",
                    "last_seen": "2026-06-01T00:00:00+00:00",
                    "record_count": 12, "total_cost_usd": 0.5,
                    "prev_session_id": None,
                }
            }
        })
        res = self._run(self._payload(new_sid, repo))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        idx = self._read_index()
        self.assertIn("branch:feature", idx)
        entry = idx["branch:feature"][new_sid]
        self.assertEqual(entry["group_key"], "branch:feature")
        self.assertEqual(entry["cwd"], repo)
        self.assertIsNone(entry["record_count"])
        self.assertIsNone(entry["total_cost_usd"])
        self.assertEqual(entry["prev_session_id"], prior_sid)

    def test_second_startup_same_branch_links_to_first(self):
        # Two startups on the same branch+cwd: the second links to the first.
        self._write_config(rolling_capture=True)
        repo = self._git_repo("feature")
        sid_a = self._sid("a")
        sid_b = self._sid("b")
        res_a = self._run(self._payload(sid_a, repo))
        self.assertEqual(res_a.returncode, 0, msg=res_a.stderr)
        res_b = self._run(self._payload(sid_b, repo))
        self.assertEqual(res_b.returncode, 0, msg=res_b.stderr)
        idx = self._read_index()
        group = idx["branch:feature"]
        self.assertIn(sid_a, group)
        self.assertIn(sid_b, group)
        self.assertIsNone(group[sid_a]["prev_session_id"])   # first has no parent
        self.assertEqual(group[sid_b]["prev_session_id"], sid_a)

    def test_index_contains_only_metadata_keys(self):
        # Egress-by-construction: the written entry carries only metadata keys,
        # never message/reasoning/observation content.
        self._write_config(rolling_capture=True)
        repo = self._git_repo("feature")
        sid = self._sid("meta")
        res = self._run(self._payload(sid, repo))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        blob = self.index.read_text()
        for banned in ("message", "reasoning", "observation"):
            self.assertNotIn(banned, blob,
                             f"index leaked content key {banned!r}: {blob}")
        entry = self._read_index()["branch:feature"][sid]
        allowed = {"group_key", "session_id", "cwd", "first_seen", "last_seen",
                   "record_count", "total_cost_usd", "prev_session_id", "store_path"}
        self.assertTrue(set(entry.keys()) <= allowed,
                        f"unexpected keys in entry: {set(entry.keys()) - allowed}")


@unittest.skipUnless(_git_available(), "git is not installed -- skipping non-startup tests")
class TestSessionStartNonStartupSources(SessionStartHookBase):
    """resume/clear/compact must NOT rewrite or re-link the index."""

    def _assert_unchanged_for_source(self, source):
        self._write_config(rolling_capture=True)
        repo = self._git_repo("feature")
        existing_sid = self._sid("existing")
        seed = {
            "branch:feature": {
                existing_sid: {
                    "group_key": "branch:feature", "session_id": existing_sid,
                    "cwd": repo, "first_seen": "2026-06-01T00:00:00+00:00",
                    "last_seen": "2026-06-01T00:00:00+00:00",
                    "record_count": 7, "total_cost_usd": 0.1,
                    "prev_session_id": None,
                }
            }
        }
        self._write_index(seed)
        before = self.index.read_text()
        new_sid = self._sid("resumed")
        res = self._run(self._payload(new_sid, repo, source=source))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        # Index UNCHANGED: no rewrite, no new entry, no re-link.
        self.assertEqual(self.index.read_text(), before,
                         f"source={source} must leave the index byte-for-byte unchanged")
        idx = self._read_index()
        self.assertNotIn(new_sid, idx["branch:feature"])

    def test_source_resume_leaves_index_unchanged(self):
        self._assert_unchanged_for_source("resume")

    def test_source_clear_leaves_index_unchanged(self):
        self._assert_unchanged_for_source("clear")

    def test_source_compact_leaves_index_unchanged(self):
        self._assert_unchanged_for_source("compact")


class TestSessionStartCwdAndFailOpen(SessionStartHookBase):
    """cwd-absent, malformed inputs, corrupt index, missing jq -- all fail-open."""

    def test_cwd_absent_no_index_write(self):
        # No cwd on the payload -> the hook must NOT guess $(pwd); no index write.
        self._write_config(rolling_capture=True)
        sid = self._sid("nocwd")
        payload = {"session_id": sid, "source": "startup",
                   "hook_event_name": "SessionStart"}
        res = self._run(payload)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self.index.exists(),
                         "no cwd -> must not write (no pwd guess)")

    def test_malformed_stdin_no_crash(self):
        self._write_config(rolling_capture=True)
        res = self._run("this is not json at all")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self.index.exists())

    def test_missing_jq_degrades(self):
        # A PATH without jq -> degrade -> exit 0, no index.
        self._write_config(rolling_capture=True)
        sid = self._sid("nojq")
        path = self._path_without(("jq",))
        res = self._run(self._payload(sid, self.work), path=path)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self.index.exists())

    @unittest.skipUnless(_git_available(), "git required to reach the index write")
    def test_corrupt_index_warns_and_treated_as_empty(self):
        # A corrupt index.json must NOT crash the hook: it is treated as empty
        # (the new entry is written fresh) AND a stderr warning is emitted --
        # never silently dropped.
        self._write_config(rolling_capture=True)
        repo = self._git_repo("feature")
        sid = self._sid("corrupt")
        self._write_index("{ this is not valid json ]")
        res = self._run(self._payload(sid, repo))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("Warning", res.stderr,
                      f"corrupt index must warn to stderr, got: {res.stderr!r}")
        # Treated as empty: the write still succeeds with the new entry present.
        idx = self._read_index()
        self.assertIn("branch:feature", idx)
        self.assertIn(sid, idx["branch:feature"])

    @unittest.skipUnless(_git_available(), "git required for the off-git contrast")
    def test_off_git_cwd_no_index_write(self):
        # A non-git cwd -> branch resolves empty -> group_key 'ungrouped' ->
        # the hook skips the write (no ungrouped bloat); rc 0.
        self._write_config(rolling_capture=True)
        sid = self._sid("offgit")
        nongit = self.work / "plain"
        nongit.mkdir(parents=True, exist_ok=True)
        res = self._run(self._payload(sid, nongit))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertFalse(self.index.exists(),
                         "off-git (ungrouped) must not write an index entry")

    # -- PATH helper (mirrors test_roll_capture_hook) -------------------------

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


if __name__ == "__main__":
    unittest.main()
