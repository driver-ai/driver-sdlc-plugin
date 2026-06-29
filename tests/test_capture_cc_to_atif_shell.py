"""Shell tests for cc_to_atif `main()` --env-file handling (M5).

The shell imports harbor (`cc_to_atif` -> `from harbor.models.trajectories ...`),
which is an external dependency absent from the zero-dep CI path. So this whole
module is guarded by `@unittest.skipUnless(_harbor_available(), ...)` -- a named
justification for not running it, NOT a mock of harbor. When harbor is absent the
test SKIPS cleanly; that is expected.

It drives `cc_to_atif.py` via subprocess so the bare `import cc_to_atif_core` /
`import environment` / `import pricing` resolve via `sys.path[0]` (the script's own
directory), exactly as they do in real use.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT

SCRIPT = PLUGIN_ROOT / "scripts" / "capture" / "cc_to_atif.py"


def _harbor_available() -> bool:
    try:
        import harbor  # noqa: F401
        return True
    except Exception:
        return False


def _run(transcript, *extra_args):
    """Run cc_to_atif.py from the repo root; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(transcript), *extra_args],
        cwd=str(PLUGIN_ROOT), capture_output=True, text=True,
    )


# A tiny valid Claude Code JSONL transcript: one assistant turn so normalize()
# yields at least one step (avoids EmptyTranscriptError confounding the result).
TRANSCRIPT_LINES = [
    json.dumps({
        "type": "assistant", "isSidechain": False, "sessionId": "sess",
        "timestamp": "2026-06-25T00:00:00Z",
        "message": {
            "id": "m1", "model": "claude-opus-4-8-20260315",
            "content": [{"type": "text", "text": "hello"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    }),
]


@unittest.skipUnless(_harbor_available(), "harbor not installed")
class TestCcToAtifMainEnvFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.transcript = self.tmpdir / "session.jsonl"
        self.transcript.write_text("\n".join(TRANSCRIPT_LINES) + "\n")
        self.out = self.tmpdir / "trajectory.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_cc_to_atif_main_env_file_errors(self):
        # (a) Missing --env-file path -> non-zero exit, clear stderr, no raw traceback.
        missing = self.tmpdir / "does-not-exist.json"
        res = _run(self.transcript, "--env-file", str(missing), "--out", str(self.out))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("error:", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertNotIn("FileNotFoundError", res.stderr)

        # (b) Malformed JSON --env-file -> non-zero exit, clear stderr, no raw traceback.
        bad = self.tmpdir / "bad.json"
        bad.write_text("{ this is not valid json ")
        res = _run(self.transcript, "--env-file", str(bad), "--out", str(self.out))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("error:", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertNotIn("JSONDecodeError", res.stderr)

        # (c) Unknown keys in an otherwise-valid env-file are ignored -> exit 0.
        good = self.tmpdir / "good.json"
        good.write_text(json.dumps({
            "branch": "eric/agent-session-capture",
            "totally_unknown_key": "ignored",
            "another_bogus": 123,
        }))
        res = _run(self.transcript, "--env-file", str(good), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)


# ---------------------------------------------------------------------------
# Recursive subagent mapping + session-scoped discovery + robustness.
#
# These exercise the harbor adapter directly: in-process for to_trajectory /
# redaction (build the NormalizedTrajectory via the kernel, map it onto real
# harbor models, then inspect / redact the result) and via subprocess for the
# --session-dir discovery path (build a small on-disk session tree, run the
# script, read the emitted trajectory.json).
#
# Real subagents on disk live at
#   <project-dir>/<session-id>/subagents/agent-<id>.jsonl  (+ .meta.json sidecar)
# and every subagent record is isSidechain:true; spawning calls in the parent are
# tool_use blocks named "Agent". Fixtures mirror that exactly.
# ---------------------------------------------------------------------------

def _capture_modules():
    """Import the capture modules in-process for the harbor-adapter tests.

    Mirrors tests/test_capture_cc_to_atif_core.py: insert the capture script dir
    onto sys.path so `cc_to_atif`'s sibling imports (`cc_to_atif_core`, `pricing`,
    `environment`) resolve, then import the adapter, kernel, and redactor. Only
    called inside the skipUnless-gated class, so harbor is present.
    """
    cap = str(PLUGIN_ROOT / "scripts" / "capture")
    if cap not in sys.path:
        sys.path.insert(0, cap)
    import cc_to_atif
    import cc_to_atif_core as core
    import redact
    return cc_to_atif, core, redact


def _usage(input_tokens=100, output_tokens=50):
    return {"input_tokens": input_tokens, "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 20, "output_tokens": output_tokens}


def _asst(blocks, *, msg_id, sidechain=False, session_id="sess",
          model="claude-opus-4-8-20260315", usage=None):
    msg = {"id": msg_id, "model": model, "content": blocks}
    if usage is not None:
        msg["usage"] = usage
    return {"type": "assistant", "isSidechain": sidechain, "sessionId": session_id,
            "timestamp": "2026-06-25T00:00:00Z", "message": msg}


def _user(blocks, *, sidechain=False, session_id="sess"):
    return {"type": "user", "isSidechain": sidechain, "sessionId": session_id,
            "timestamp": "2026-06-25T00:00:00Z", "message": {"content": blocks}}


def _text(s):
    return {"type": "text", "text": s}


def _tool_use(call_id, name="Bash", inp=None):
    return {"type": "tool_use", "id": call_id, "name": name, "input": inp or {}}


def _tool_result(call_id, content):
    return {"type": "tool_result", "tool_use_id": call_id, "content": content}


def _write_session_tree(project_dir, session_id, subagent_files):
    """Materialize <project-dir>/<session-id>/subagents/agent-*.jsonl + sidecars.

    subagent_files: {stem: {"records": [...], "meta": {...} | None}}. A None meta
    writes no sidecar (the missing-sidecar case).
    """
    sub_dir = Path(project_dir) / session_id / "subagents"
    sub_dir.mkdir(parents=True, exist_ok=True)
    for stem, spec in subagent_files.items():
        jp = sub_dir / f"{stem}.jsonl"
        jp.write_text("\n".join(json.dumps(r) for r in spec["records"]) + "\n")
        if spec.get("meta") is not None:
            (sub_dir / f"{stem}.meta.json").write_text(json.dumps(spec["meta"]))
    return sub_dir


@unittest.skipUnless(_harbor_available(), "harbor not installed")
class TestToTrajectoryRecursive(unittest.TestCase):
    """In-process: NormalizedTrajectory -> harbor Trajectory recursive mapping."""

    def _two_deep_normalized(self):
        cc_to_atif, core, redact = _capture_modules()
        main = [
            _asst([_text("parent"), _tool_use("spawn-a", name="Agent")],
                  msg_id="m1", usage=_usage()),
            _user([_tool_result("spawn-a", "A finished")]),
        ]
        sub_records = [
            _asst([_text("subagent work"), _tool_use("sc1", name="Bash")],
                  msg_id="sm1", sidechain=True, usage=_usage()),
            _user([_tool_result("sc1", "tool output")], sidechain=True),
        ]
        meta = {"agentType": "explorer", "description": "explore",
                "toolUseId": "spawn-a", "trajectory_id": "sess/agent-a"}
        return core.normalize_session(
            main, [(meta, sub_records)], session_id="sess", task_id=None,
            spec_id=None, intent=None, exclude_session_id=None)

    def test_two_deep_trajectory_validates_and_embeds_subagent(self):
        cc_to_atif, core, redact = _capture_modules()
        n = self._two_deep_normalized()
        traj = cc_to_atif.to_trajectory(n)
        d = traj.to_json_dict()
        # The harbor Trajectory constructed without raising == validators passed.
        self.assertIn("subagent_trajectories", d)
        self.assertEqual(len(d["subagent_trajectories"]), 1)
        self.assertEqual(d["subagent_trajectories"][0]["trajectory_id"], "sess/agent-a")
        # The subagent_trajectory_ref lands on the observation whose source_call_id
        # is the spawning Agent call.
        refs = [r for s in d["steps"] for r in (s.get("observation") or {}).get("results", [])
                if r.get("subagent_trajectory_ref")]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["source_call_id"], "spawn-a")
        self.assertEqual(
            [x["trajectory_id"] for x in refs[0]["subagent_trajectory_ref"]],
            ["sess/agent-a"])

    def test_no_subagents_omits_key(self):
        # [] -> None coercion: a trajectory with no subagents emits no
        # subagent_trajectories key at all.
        cc_to_atif, core, redact = _capture_modules()
        main = [_asst([_text("solo")], msg_id="m1", usage=_usage())]
        n = core.normalize_session(
            main, [], session_id="sess", task_id=None, spec_id=None,
            intent=None, exclude_session_id=None)
        d = cc_to_atif.to_trajectory(n).to_json_dict()
        self.assertNotIn("subagent_trajectories", d)


@unittest.skipUnless(_harbor_available(), "harbor not installed")
class TestSubagentRedaction(unittest.TestCase):
    """In-process: a secret inside a subagent step (incl. depth-2) is masked +
    counted after redact_trajectory over the real harbor model dict."""

    def test_secret_in_depth2_subagent_is_masked_and_counted(self):
        cc_to_atif, core, redact = _capture_modules()
        secret = "sk-ant-" + "A" * 40
        main = [
            _asst([_text("parent"), _tool_use("spawn-a", name="Agent")],
                  msg_id="m1", usage=_usage()),
            _user([_tool_result("spawn-a", "A done")]),
        ]
        # A (depth-1) spawns B (depth-2); B's step carries the secret.
        a_records = [
            _asst([_text("A turn"), _tool_use("spawn-b", name="Agent")],
                  msg_id="am1", sidechain=True, usage=_usage()),
            _user([_tool_result("spawn-b", "B done")], sidechain=True),
        ]
        b_records = [
            _asst([_text(f"the key is {secret}")], msg_id="bm1",
                  sidechain=True, usage=_usage()),
        ]
        meta_a = {"agentType": "a", "toolUseId": "spawn-a",
                  "trajectory_id": "sess/agent-a"}
        meta_b = {"agentType": "b", "toolUseId": "spawn-b",
                  "trajectory_id": "sess/agent-b"}
        n = core.normalize_session(
            main, [(meta_a, a_records), (meta_b, b_records)], session_id="sess",
            task_id=None, spec_id=None, intent=None, exclude_session_id=None)
        d = cc_to_atif.to_trajectory(n).to_json_dict()
        redacted, flags = redact.redact_trajectory(d)
        blob = json.dumps(redacted)
        self.assertNotIn(secret, blob)
        self.assertIn("[REDACTED:", blob)
        total = sum(f["count"] for f in flags)
        self.assertGreaterEqual(total, 1)


@unittest.skipUnless(_harbor_available(), "harbor not installed")
class TestSessionDirDiscovery(unittest.TestCase):
    """Subprocess: --session-dir globs the captured session's subagents."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.project = self.tmpdir / "project"
        self.project.mkdir()
        self.out = self.tmpdir / "trajectory.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_transcript(self, session_id, *, spawn_call="spawn-a"):
        """A main transcript carrying sessionId and a spawning Agent call."""
        lines = [
            _asst([_text("parent"), _tool_use(spawn_call, name="Agent")],
                  msg_id="m1", session_id=session_id, usage=_usage()),
            _user([_tool_result(spawn_call, "subagent finished")],
                  session_id=session_id),
        ]
        tpath = self.tmpdir / "session.jsonl"
        tpath.write_text("\n".join(json.dumps(r) for r in lines) + "\n")
        return tpath

    def _sub_records(self, *, content="sub work", call_id="sc1"):
        return [
            _asst([_text(content), _tool_use(call_id, name="Bash")],
                  msg_id="sm1", sidechain=True, usage=_usage()),
            _user([_tool_result(call_id, "tool output")], sidechain=True),
        ]

    def test_session_dir_embeds_subagents_and_rolls_up(self):
        session_id = "sess-A"
        transcript = self._write_transcript(session_id)
        _write_session_tree(self.project, session_id, {
            "agent-a": {"records": self._sub_records(),
                        "meta": {"agentType": "explorer", "description": "explore",
                                 "toolUseId": "spawn-a"}},
        })
        res = _run(transcript, "--session-dir", str(self.project), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())
        self.assertIn("subagent_trajectories", d)
        self.assertEqual(len(d["subagent_trajectories"]), 1)
        self.assertEqual(d["subagent_trajectories"][0]["trajectory_id"],
                         f"{session_id}/agent-a")
        # The subagent's prompt tokens rolled into the parent total (flat union):
        # parent step + subagent step both carry usage, so the total exceeds a
        # single step's prompt tokens.
        single = _usage()["input_tokens"] + _usage()["cache_creation_input_tokens"] \
            + _usage()["cache_read_input_tokens"]
        self.assertGreater(d["final_metrics"]["total_prompt_tokens"], single)

    def test_session_scope_excludes_sibling_session_subagents(self):
        # Two session-uuid dirs under one project dir; capturing A embeds only A's.
        transcript = self._write_transcript("sess-A")
        _write_session_tree(self.project, "sess-A", {
            "agent-a": {"records": self._sub_records(content="A-sub"),
                        "meta": {"agentType": "explorer", "toolUseId": "spawn-a"}},
        })
        _write_session_tree(self.project, "sess-B", {
            "agent-b": {"records": self._sub_records(content="B-sub", call_id="bc1"),
                        "meta": {"agentType": "other", "toolUseId": "spawn-b"}},
        })
        res = _run(transcript, "--session-dir", str(self.project), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())
        ids = {s["trajectory_id"] for s in d.get("subagent_trajectories", [])}
        self.assertEqual(ids, {"sess-A/agent-a"})
        self.assertNotIn("B-sub", json.dumps(d))

    def test_trajectory_id_uniqueness_within_capture(self):
        # Two subagent files -> distinct session-qualified ids; harbor's
        # validate_embedded_subagent_trajectory_ids passes (run exits 0, output loads).
        session_id = "sess-A"
        transcript = self._write_transcript(session_id)
        _write_session_tree(self.project, session_id, {
            "agent-1": {"records": self._sub_records(content="one"),
                        "meta": {"agentType": "explorer", "toolUseId": "spawn-a"}},
            "agent-2": {"records": self._sub_records(content="two", call_id="sc2"),
                        "meta": {"agentType": "explorer"}},  # unlinked second
        })
        res = _run(transcript, "--session-dir", str(self.project), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())
        ids = [s["trajectory_id"] for s in d["subagent_trajectories"]]
        self.assertEqual(sorted(ids), [f"{session_id}/agent-1", f"{session_id}/agent-2"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i for i in ids))  # all non-null/non-empty

    def test_missing_sidecar_embeds_unlinked(self):
        # A subagent jsonl with no .meta.json -> embedded with only trajectory_id,
        # no subagent_type, no ref, no crash.
        session_id = "sess-A"
        transcript = self._write_transcript(session_id)
        _write_session_tree(self.project, session_id, {
            "agent-a": {"records": self._sub_records(), "meta": None},
        })
        res = _run(transcript, "--session-dir", str(self.project), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())
        self.assertEqual(len(d["subagent_trajectories"]), 1)
        sub = d["subagent_trajectories"][0]
        self.assertEqual(sub["trajectory_id"], f"{session_id}/agent-a")
        self.assertNotIn("subagent_type", (sub.get("extra") or {}))
        # No ref anywhere (no meta -> no toolUseId -> unlinked).
        refs = [r for s in d["steps"] for r in (s.get("observation") or {}).get("results", [])
                if r.get("subagent_trajectory_ref")]
        self.assertEqual(refs, [])

    def test_corrupt_jsonl_line_is_skipped_run_succeeds(self):
        # A subagent file with one malformed line AND one valid-JSON-but-not-an-object
        # line (a bare array). Both are skipped; the valid steps are still captured;
        # parent + other subagents intact.
        session_id = "sess-A"
        transcript = self._write_transcript(session_id)
        sub_dir = Path(self.project) / session_id / "subagents"
        sub_dir.mkdir(parents=True, exist_ok=True)
        good = _asst([_text("survives")], msg_id="sm1", sidechain=True, usage=_usage())
        lines = [
            "{ not valid json at all",     # malformed
            "[]",                          # valid JSON, not an object
            json.dumps(good),              # a real record
        ]
        (sub_dir / "agent-a.jsonl").write_text("\n".join(lines) + "\n")
        (sub_dir / "agent-a.meta.json").write_text(json.dumps(
            {"agentType": "explorer", "toolUseId": "spawn-a"}))
        # A second, clean subagent to confirm siblings are unaffected.
        _write_session_tree(self.project, session_id, {
            "agent-b": {"records": self._sub_records(content="sibling", call_id="bc1"),
                        "meta": {"agentType": "other"}},
        })
        res = _run(transcript, "--session-dir", str(self.project), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())
        ids = {s["trajectory_id"] for s in d["subagent_trajectories"]}
        self.assertEqual(ids, {f"{session_id}/agent-a", f"{session_id}/agent-b"})
        # agent-a kept its one good step despite the two bad lines.
        sub_a = next(s for s in d["subagent_trajectories"]
                     if s["trajectory_id"] == f"{session_id}/agent-a")
        self.assertTrue(any("survives" in (st.get("message") or "")
                            for st in sub_a["steps"]))


if __name__ == "__main__":
    unittest.main()
