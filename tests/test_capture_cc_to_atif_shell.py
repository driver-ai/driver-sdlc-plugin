"""Shell tests for the logs2atif-backed `cc_to_atif.py` wrapper.

The wrapper imports logs2atif lazily inside the convert path, so the CLI's
argparse/env-file validation is dependency-free while every conversion needs
the external logs2atif package. The test split mirrors that boundary:

  * env-file error tests run UNGATED — they exit before any logs2atif import,
    so they must pass on the zero-dep CI path;
  * every conversion test is gated with a named
    `@unittest.skipUnless(_logs2atif_available(), ...)` — an absent external
    dependency means a clean SKIP, never a mock.

All tests drive `cc_to_atif.py` via subprocess against real I/O in tmpdirs,
exactly as the rolling hook and the capture command invoke it. The main
transcript fixture is the real captured session
`tests/fixtures/capture/session_97f81a2c.scrubbed.jsonl`; subagent layouts
(`<project>/<session-id>/subagents/agent-*.jsonl` + `.meta.json` sidecars)
are crafted per-test in tmpdirs. Crafted records carry valid ISO 8601
timestamps — upstream validation silently drops invalid-timestamp records.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT

SCRIPT = PLUGIN_ROOT / "scripts" / "capture" / "cc_to_atif.py"
FIXTURE = PLUGIN_ROOT / "tests" / "fixtures" / "capture" / "session_97f81a2c.scrubbed.jsonl"
FIXTURE_SESSION_ID = "97f81a2c-7771-44df-a4f3-caaebb60cec7"
MARKER = "/drvr:capture-session"


def _logs2atif_available() -> bool:
    try:
        import logs2atif  # noqa: F401
        return True
    except Exception:
        return False


def _run(transcript, *extra_args):
    """Run cc_to_atif.py from the repo root; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(transcript), *extra_args],
        cwd=str(PLUGIN_ROOT), capture_output=True, text=True,
    )


# ---------------------------------------------------------------------------
# Crafted-record helpers (real Claude Code JSONL shapes; valid ISO timestamps).
# ---------------------------------------------------------------------------

def _ts(i):
    return f"2026-06-25T00:00:{i:02d}Z"


def _usage(input_tokens=1000, output_tokens=1000):
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _asst(content, *, msg_id, ts, session_id="sess", sidechain=False,
          model="claude-opus-4-8-20260315", usage=None):
    msg = {"id": msg_id, "model": model, "content": content}
    if usage is not None:
        msg["usage"] = usage
    return {"type": "assistant", "isSidechain": sidechain, "sessionId": session_id,
            "timestamp": ts, "message": msg}


def _user(content, *, ts, session_id="sess", sidechain=False):
    return {"type": "user", "isSidechain": sidechain, "sessionId": session_id,
            "timestamp": ts, "message": {"content": content}}


def _text(s):
    return {"type": "text", "text": s}


def _tool_use(call_id, name="Agent", inp=None):
    return {"type": "tool_use", "id": call_id, "name": name, "input": inp or {}}


def _tool_result(call_id, content):
    return {"type": "tool_result", "tool_use_id": call_id, "content": content}


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _write_session_tree(project_dir, session_id, subagent_files):
    """Materialize <project-dir>/<session-id>/subagents/agent-*.jsonl + sidecars.

    subagent_files: {stem: {"records": [...] | "lines": [...], "meta": {...} | None}}.
    "lines" writes raw text lines verbatim (for corrupt-line cases); a None meta
    writes no sidecar.
    """
    sub_dir = Path(project_dir) / session_id / "subagents"
    sub_dir.mkdir(parents=True, exist_ok=True)
    for stem, spec in subagent_files.items():
        jp = sub_dir / f"{stem}.jsonl"
        if "lines" in spec:
            jp.write_text("\n".join(spec["lines"]) + "\n")
        else:
            _write_jsonl(jp, spec["records"])
        if spec.get("meta") is not None:
            (sub_dir / f"{stem}.meta.json").write_text(json.dumps(spec["meta"]))
    return sub_dir


def _fixture_linked_tool_use_ids(n):
    """First n tool_use ids in the fixture that also have a tool_result.

    Crafted subagent metas must reuse REAL dispatch ids from the parent
    transcript: refs only resolve when the meta's toolUseId matches a
    tool_call_id that carries an observation result in the converted parent.
    """
    records = [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]
    result_ids = set()
    use_ids = []
    for rec in records:
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("id"):
                use_ids.append(block["id"])
            elif block.get("type") == "tool_result" and block.get("tool_use_id"):
                result_ids.add(block["tool_use_id"])
    linked = [u for u in use_ids if u in result_ids]
    assert len(linked) >= n, f"fixture has only {len(linked)} linked tool_use ids"
    return linked[:n]


def _refs_for(steps, source_call_id):
    """subagent_trajectory_ref trajectory_ids on the observation result whose
    source_call_id matches, across the given (serialized) steps."""
    out = []
    for step in steps:
        for result in (step.get("observation") or {}).get("results", []):
            if result.get("source_call_id") != source_call_id:
                continue
            for ref in result.get("subagent_trajectory_ref") or []:
                out.append(ref.get("trajectory_id"))
    return out


def _tree(root: Path) -> set:
    """Every path under root, relative — for asserting nothing stray was written."""
    return {str(p.relative_to(root)) for p in Path(root).rglob("*")}


# ---------------------------------------------------------------------------
# Ungated: --env-file validation errors exit before any logs2atif import.
# ---------------------------------------------------------------------------


class TestEnvFileErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.transcript = self.tmpdir / "session.jsonl"
        _write_jsonl(self.transcript, [
            _asst([_text("hello")], msg_id="m1", ts=_ts(0), usage=_usage()),
        ])
        self.out = self.tmpdir / "trajectory.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_env_file_missing_or_invalid_exits_1(self):
        # (a) Missing --env-file path -> exit 1, clear stderr, no raw traceback.
        # Dep-free: the wrapper validates the env-file before importing
        # logs2atif, so this must pass on the zero-dep path too.
        missing = self.tmpdir / "does-not-exist.json"
        res = _run(self.transcript, "--env-file", str(missing), "--out", str(self.out))
        self.assertEqual(res.returncode, 1)
        self.assertIn("error:", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertNotIn("FileNotFoundError", res.stderr)

        # (b) Malformed JSON --env-file -> exit 1, clear stderr, no raw traceback.
        bad = self.tmpdir / "bad.json"
        bad.write_text("{ this is not valid json ")
        res = _run(self.transcript, "--env-file", str(bad), "--out", str(self.out))
        self.assertEqual(res.returncode, 1)
        self.assertIn("error:", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertNotIn("JSONDecodeError", res.stderr)


# ---------------------------------------------------------------------------
# Gated: conversion through the real logs2atif adapter.
# ---------------------------------------------------------------------------


@unittest.skipUnless(_logs2atif_available(), "logs2atif not installed (external dep)")
class TestWrapperRealFixture(unittest.TestCase):
    """The real captured session converts end-to-end via logs2atif."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.out = self.tmpdir / "trajectory.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_wrapper_converts_real_fixture_and_writes_atif(self):
        env_file = self.tmpdir / "env.json"
        env_file.write_text(json.dumps({
            "branch": "feature-branch",
            "totally_unknown_key": "ignored",
        }))
        res = _run(FIXTURE, "--out", str(self.out),
                   "--env-file", str(env_file), "--task-id", "T-1")
        self.assertEqual(res.returncode, 0, msg=res.stderr)

        d = json.loads(self.out.read_text())
        self.assertEqual(d["schema_version"], "ATIF-v1.7")
        self.assertEqual(d["session_id"], FIXTURE_SESSION_ID)
        self.assertTrue(d.get("trajectory_id"))
        self.assertGreater(len(d["steps"]), 0)
        fm = d["final_metrics"]
        self.assertEqual(fm["total_steps"], len(d["steps"]))
        self.assertGreater(fm["total_prompt_tokens"], 0)
        self.assertGreater(fm["total_completion_tokens"], 0)
        self.assertGreater(fm["total_cost_usd"], 0)  # claude-opus-4-8 is priced
        # Per-step metrics survive serialization.
        self.assertTrue(any(s.get("metrics", {}).get("prompt_tokens")
                            for s in d["steps"]))
        # env facts + SDLC identity land under extra; unknown env keys ignored.
        self.assertEqual(d["extra"]["environment"], {"branch": "feature-branch"})
        self.assertEqual(d["extra"]["sdlc_task_id"], "T-1")

        # OK stdout contract.
        lines = res.stdout.splitlines()
        self.assertEqual(lines[0], f"OK  {self.out}")
        self.assertIn("schema=ATIF-v1.7", res.stdout)
        self.assertIn(f"session={FIXTURE_SESSION_ID}", res.stdout)
        self.assertIn(f"steps={fm['total_steps']}", res.stdout)
        self.assertIn(f"prompt_tok={fm['total_prompt_tokens']}", res.stdout)
        self.assertIn(f"compl_tok={fm['total_completion_tokens']}", res.stdout)
        self.assertIn(f"cost=${fm['total_cost_usd']}", res.stdout)
        self.assertIn("peak_step_context_tokens=", res.stdout)
        self.assertIn("tools_used=", res.stdout)
        self.assertIn("Bash", res.stdout)  # the fixture ran Bash tools

    def test_wrapper_embeds_subagents_from_session_dir_layout(self):
        # Two crafted subagents whose meta toolUseIds are REAL dispatch ids
        # copied from the parent fixture, laid out exactly as the store writes
        # them: <project>/<session-id>/subagents/agent-*.jsonl + .meta.json.
        id_a, id_b = _fixture_linked_tool_use_ids(2)
        project = self.tmpdir / "project"
        project.mkdir()
        sub_recs = lambda text, mid: [  # noqa: E731 - tiny per-test builder
            _asst([_text(text)], msg_id=mid, ts=_ts(1),
                  session_id=FIXTURE_SESSION_ID, sidechain=True, usage=_usage()),
        ]
        _write_session_tree(project, FIXTURE_SESSION_ID, {
            "agent-aaa": {"records": sub_recs("subagent A work", "sa1"),
                          "meta": {"agentType": "explorer", "toolUseId": id_a}},
            "agent-bbb": {"records": sub_recs("subagent B work", "sb1"),
                          "meta": {"agentType": "builder", "toolUseId": id_b}},
        })

        # Baseline run (no --session-dir) pins the parent-only token totals.
        baseline_out = self.tmpdir / "baseline.json"
        res = _run(FIXTURE, "--out", str(baseline_out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        base_fm = json.loads(baseline_out.read_text())["final_metrics"]

        res = _run(FIXTURE, "--session-dir", str(project), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())

        # All subagents embedded, with session-qualified trajectory ids.
        ids = {s["trajectory_id"] for s in d["subagent_trajectories"]}
        self.assertEqual(ids, {f"{FIXTURE_SESSION_ID}/agent-aaa",
                               f"{FIXTURE_SESSION_ID}/agent-bbb"})

        # Refs resolve on the real dispatch ids, on the parent's steps.
        self.assertEqual(_refs_for(d["steps"], id_a),
                         [f"{FIXTURE_SESSION_ID}/agent-aaa"])
        self.assertEqual(_refs_for(d["steps"], id_b),
                         [f"{FIXTURE_SESSION_ID}/agent-bbb"])

        # Parent totals are subagent-INCLUSIVE: each subagent contributes one
        # usage-bearing step (prompt 1000 / completion 1000 / cached 0).
        fm = d["final_metrics"]
        self.assertEqual(fm["total_prompt_tokens"],
                         base_fm["total_prompt_tokens"] + 2000)
        self.assertEqual(fm["total_completion_tokens"],
                         base_fm["total_completion_tokens"] + 2000)
        self.assertEqual(fm.get("total_cached_tokens", 0),
                         base_fm.get("total_cached_tokens", 0))
        self.assertEqual(fm["total_steps"], base_fm["total_steps"])
        # Cost stays upstream's subtree-inclusive figure: baseline plus each
        # subagent step (1000 in @ $5/M + 1000 out @ $25/M = $0.03).
        self.assertAlmostEqual(fm["total_cost_usd"],
                               base_fm["total_cost_usd"] + 0.06, places=6)


@unittest.skipUnless(_logs2atif_available(), "logs2atif not installed (external dep)")
class TestWrapperSubagentLayouts(unittest.TestCase):
    """Crafted session-dir layouts: nesting depth, session scoping, tolerance."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.project = self.tmpdir / "project"
        self.project.mkdir()
        self.out = self.tmpdir / "trajectory.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_parent(self, session_id, spawn_call="spawn-a"):
        """A crafted parent transcript with one subagent dispatch + result."""
        transcript = self.tmpdir / "session.jsonl"
        _write_jsonl(transcript, [
            _asst([_text("dispatching"), _tool_use(spawn_call)], msg_id="m1",
                  ts=_ts(0), session_id=session_id, usage=_usage()),
            _user([_tool_result(spawn_call, "subagent finished")], ts=_ts(3),
                  session_id=session_id),
        ])
        return transcript

    def test_wrapper_depth2_subagent_nested_ref_resolves(self):
        # Parent spawns child; the CHILD spawns a grandchild. Upstream links
        # refs on parent steps only; the wrapper's re-link pass must attach the
        # grandchild's ref inside the child's own steps.
        session_id = "sess-depth2"
        transcript = self._write_parent(session_id, spawn_call="spawn-child")
        child_records = [
            _asst([_text("child working"), _tool_use("spawn-grandchild")],
                  msg_id="cm1", ts=_ts(1), session_id=session_id,
                  sidechain=True, usage=_usage()),
            _user([_tool_result("spawn-grandchild", "grandchild done")],
                  ts=_ts(2), session_id=session_id, sidechain=True),
        ]
        grandchild_records = [
            _asst([_text("grandchild working")], msg_id="gm1", ts=_ts(1),
                  session_id=session_id, sidechain=True, usage=_usage()),
        ]
        _write_session_tree(self.project, session_id, {
            "agent-child": {"records": child_records,
                            "meta": {"agentType": "child", "toolUseId": "spawn-child",
                                     "spawnDepth": 1}},
            "agent-grandchild": {"records": grandchild_records,
                                 "meta": {"agentType": "grandchild",
                                          "toolUseId": "spawn-grandchild",
                                          "spawnDepth": 2}},
        })
        res = _run(transcript, "--session-dir", str(self.project), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())

        ids = {s["trajectory_id"] for s in d["subagent_trajectories"]}
        self.assertEqual(ids, {f"{session_id}/agent-child",
                               f"{session_id}/agent-grandchild"})

        # Parent -> child ref (upstream's own link, not duplicated by re-link).
        self.assertEqual(_refs_for(d["steps"], "spawn-child"),
                         [f"{session_id}/agent-child"])

        # Child -> grandchild ref: attached INSIDE the child's steps.
        child = next(s for s in d["subagent_trajectories"]
                     if s["trajectory_id"] == f"{session_id}/agent-child")
        self.assertEqual(_refs_for(child["steps"], "spawn-grandchild"),
                         [f"{session_id}/agent-grandchild"])

    def test_wrapper_scopes_to_own_session_subagents(self):
        # Two session-uuid dirs under one project dir; capturing A embeds only A's.
        transcript = self._write_parent("sess-A")
        _write_session_tree(self.project, "sess-A", {
            "agent-a": {"records": [
                _asst([_text("A-sub work")], msg_id="sa1", ts=_ts(1),
                      session_id="sess-A", sidechain=True, usage=_usage())],
                "meta": {"agentType": "explorer", "toolUseId": "spawn-a"}},
        })
        _write_session_tree(self.project, "sess-B", {
            "agent-b": {"records": [
                _asst([_text("B-sub work")], msg_id="sb1", ts=_ts(1),
                      session_id="sess-B", sidechain=True, usage=_usage())],
                "meta": {"agentType": "other", "toolUseId": "spawn-b"}},
        })
        res = _run(transcript, "--session-dir", str(self.project), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())
        ids = {s["trajectory_id"] for s in d.get("subagent_trajectories", [])}
        self.assertEqual(ids, {"sess-A/agent-a"})
        self.assertNotIn("B-sub", json.dumps(d))

    def test_wrapper_corrupt_subagent_line_tolerated(self):
        # A subagent file carrying a valid-JSON NON-DICT line (`null`) — which
        # upstream would crash the whole conversion on — plus a garbled text
        # line (tolerated upstream). Line-cleaned staging drops only those
        # lines: parent AND subagent both convert, siblings unaffected.
        transcript = self._write_parent("sess-A")
        good = _asst([_text("survives")], msg_id="sa1", ts=_ts(1),
                     session_id="sess-A", sidechain=True, usage=_usage())
        _write_session_tree(self.project, "sess-A", {
            "agent-a": {"lines": ["null",                    # valid JSON, not a dict
                                  "{ not valid json at all",  # garbled text
                                  json.dumps(good)],
                        "meta": {"agentType": "explorer", "toolUseId": "spawn-a"}},
            "agent-b": {"records": [
                _asst([_text("sibling intact")], msg_id="sb1", ts=_ts(1),
                      session_id="sess-A", sidechain=True, usage=_usage())],
                "meta": {"agentType": "other"}},
        })
        res = _run(transcript, "--session-dir", str(self.project), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())
        self.assertGreater(len(d["steps"]), 0)  # parent converted
        ids = {s["trajectory_id"] for s in d["subagent_trajectories"]}
        self.assertEqual(ids, {"sess-A/agent-a", "sess-A/agent-b"})
        sub_a = next(s for s in d["subagent_trajectories"]
                     if s["trajectory_id"] == "sess-A/agent-a")
        self.assertTrue(any("survives" in str(st.get("message") or "")
                            for st in sub_a["steps"]))


@unittest.skipUnless(_logs2atif_available(), "logs2atif not installed (external dep)")
class TestWrapperRobustness(unittest.TestCase):
    """Unsafe ids, corrupt input, usage-less transcripts, the exit-1 contract."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.transcript = self.tmpdir / "session.jsonl"
        self.out = self.tmpdir / "trajectory.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_wrapper_unsafe_session_id_uses_fallback_stem(self):
        # A traversal-shaped sessionId must never reach a filesystem path: the
        # wrapper converts under the `session` fallback stem and skips subagent
        # discovery. Nothing may be written outside the workspace.
        project = self.tmpdir / "project"
        project.mkdir()
        _write_jsonl(self.transcript, [
            _asst([_text("hello")], msg_id="m1", ts=_ts(0),
                  session_id="../../../etc", usage=_usage()),
            _user("thanks", ts=_ts(1), session_id="../../../etc"),
        ])
        res = _run(self.transcript, "--session-dir", str(project), "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("not a safe path component", res.stderr)
        d = json.loads(self.out.read_text())
        self.assertGreater(len(d["steps"]), 0)
        self.assertNotIn("subagent_trajectories", d)
        # Only our inputs and the artifact exist — no traversal writes, no
        # '../../../etc.jsonl'-derived paths, and the empty project dir intact.
        self.assertEqual(_tree(self.tmpdir),
                         {"session.jsonl", "trajectory.json", "project"})

        # A transcript with no sessionId on ANY record behaves the same:
        # fallback stem, no crash, no None.jsonl anywhere.
        _write_jsonl(self.transcript, [
            {"type": "assistant", "isSidechain": False, "timestamp": _ts(0),
             "message": {"id": "m1", "model": "claude-opus-4-8-20260315",
                         "content": [_text("no session id")],
                         "usage": _usage()}},
        ])
        out2 = self.tmpdir / "trajectory2.json"
        res = _run(self.transcript, "--session-dir", str(project), "--out", str(out2))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("no sessionId", res.stderr)
        d = json.loads(out2.read_text())
        self.assertGreater(len(d["steps"]), 0)
        self.assertEqual(d["session_id"], "session")  # the fallback stem drove it
        self.assertNotIn("subagent_trajectories", d)
        self.assertEqual(_tree(self.tmpdir),
                         {"session.jsonl", "trajectory.json", "trajectory2.json",
                          "project"})

    def test_wrapper_corrupt_main_line_skipped_run_succeeds(self):
        # One garbled line and one valid-JSON-but-not-an-object line cost only
        # themselves; the remaining record still converts.
        good = _asst([_text("survives")], msg_id="m1", ts=_ts(0), usage=_usage())
        self.transcript.write_text("\n".join([
            "{ not valid json at all",
            "[]",
            json.dumps(good),
        ]) + "\n")
        res = _run(self.transcript, "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("skipping corrupt line", res.stderr)
        self.assertIn("skipping non-object line", res.stderr)
        d = json.loads(self.out.read_text())
        self.assertEqual(len(d["steps"]), 1)
        self.assertIn("survives", str(d["steps"][0].get("message")))

    def test_wrapper_usage_less_transcript_ok(self):
        # A user-only transcript has no usage anywhere: no token totals, no
        # cost. The wrapper still exits 0, writes the artifact, and prints the
        # OK summary with absent keys handled (cost=n/a).
        _write_jsonl(self.transcript, [
            _user("first question", ts=_ts(0)),
            _user("second question", ts=_ts(1)),
        ])
        res = _run(self.transcript, "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())
        self.assertEqual(len(d["steps"]), 2)
        self.assertTrue(all(s["source"] == "user" for s in d["steps"]))
        self.assertNotIn("total_cost_usd", d.get("final_metrics") or {})
        self.assertEqual(res.stdout.splitlines()[0], f"OK  {self.out}")
        self.assertIn("cost=n/a", res.stdout)
        self.assertIn("prompt_tok=0", res.stdout)
        self.assertIn("tools_used=(none)", res.stdout)

    def test_wrapper_empty_after_prefilter_exits_1(self):
        # The failure contract the rolling hook's backoff relies on: nothing
        # convertible -> error on stderr + exit 1, no artifact.
        # (a) Marker as the FIRST record: prefilter empties the transcript.
        _write_jsonl(self.transcript, [
            _user(MARKER, ts=_ts(0)),
            _asst([_text("capture cmd turn")], msg_id="m1", ts=_ts(1), usage=_usage()),
        ])
        res = _run(self.transcript, "--exclude-marker", MARKER, "--out", str(self.out))
        self.assertEqual(res.returncode, 1)
        self.assertIn("error:", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertFalse(self.out.exists())

        # (b) An entirely empty transcript file.
        self.transcript.write_text("")
        res = _run(self.transcript, "--out", str(self.out))
        self.assertEqual(res.returncode, 1)
        self.assertIn("error:", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertFalse(self.out.exists())

    def test_wrapper_exclude_marker_end_to_end(self):
        # Everything from the capture command's own turn onward is absent from
        # the emitted ATIF.
        _write_jsonl(self.transcript, [
            _user("real question", ts=_ts(0)),
            _asst([_text("real answer")], msg_id="m1", ts=_ts(1), usage=_usage()),
            _user("<command-name>" + MARKER + " --store", ts=_ts(2)),
            _asst([_text("post-marker capture work")], msg_id="m2", ts=_ts(3),
                  usage=_usage()),
        ])
        res = _run(self.transcript, "--exclude-marker", MARKER, "--out", str(self.out))
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        d = json.loads(self.out.read_text())
        blob = json.dumps(d)
        self.assertIn("real answer", blob)
        self.assertNotIn("post-marker", blob)
        self.assertNotIn(MARKER, blob)


if __name__ == "__main__":
    unittest.main()
