"""Integration + egress tests for the capture shells (Plan 02, Task 10).

These drive the three capture shells (render_trace / atif_to_viewer / atif_to_opik)
as REAL subprocesses against REAL I/O -- mirroring the isolated-HOME / tmpdir
pattern from `tests/test_friction.py`. No internal mocks: external/absent
dependencies (opik, node/npm) are handled with `unittest.skipUnless`, never a mock.

The load-bearing test is `test_render_trace_summary_egress`: it plants a unique
sentinel secret in EACH of the four content fields the trajectory carries
(message, reasoning_content, tool_calls[].arguments, observation.results[].content)
and proves the `--summary` block (the in-chat review surface) never echoes any of
them -- the egress non-negotiable.

The stdlib subset (egress, missing-flags, main-writes-html) MUST pass with 0
external deps installed; the viewer test needs node/npm and the opik tests need a
local Opik server, so those three are `skipUnless`-guarded.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = PLUGIN_ROOT / "scripts" / "capture"

# A distinctive sentinel that cannot collide with any metadata/count token the
# egress-safe summary legitimately prints. Planted into every content field.
SENTINEL = "ZZ_EGRESS_SENTINEL_SECRET_8f3a91c7_ZZ"

# Subagent-specific sentinels: one in a subagent step's content, one in the
# free-text subagent_type. The in-chat summary surfaces subagent COUNTS only, so
# neither may ever appear in --summary output.
SUB_STEP_SENTINEL = "ZZ_SUBAGENT_STEP_SENTINEL_5d2e1a9b_ZZ"
SUB_TYPE_SENTINEL = "ZZ_SUBAGENT_TYPE_SENTINEL_7c4f3e0d_ZZ"

# Dependency probes -> skipUnless guards (the ONLY permitted skips here).
_HAS_OPIK = importlib.util.find_spec("opik") is not None
_HAS_NODE = shutil.which("node") is not None and shutil.which("npm") is not None


def _run_capture(script, *args, env=None, timeout=120):
    """Run a capture shell as a subprocess from scripts/capture/ (so bare imports
    like `import redact` resolve) and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, script, *args],
        cwd=str(CAPTURE_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def _planted_trajectory(session_id="egress-test-session", task_id="T10",
                        spec_id="S2", with_subagent=False):
    """A minimal ATIF v1.7 trajectory with SENTINEL planted in all four content
    fields: steps[].message, steps[].reasoning_content,
    steps[].tool_calls[].arguments, steps[].observation.results[].content.

    When with_subagent is True, attach one subagent (Plan-01 flat shape) whose
    steps[0].message AND extra.subagent_type carry their own sentinels, so the
    in-chat summary's metadata-only invariant can be proven non-vacuously."""
    traj = {
        "schema_version": "ATIF-v1.7",
        "session_id": session_id,
        "extra": {"sdlc_task_id": task_id, "sdlc_spec_id": spec_id,
                  "sdlc_intent": "egress integration test"},
        "agent": {"name": "claude-code", "model_name": "claude-opus-4-8"},
        "final_metrics": {"total_steps": 2, "total_completion_tokens": 5,
                          "total_cost_usd": 0.01},
        "steps": [
            {"step_id": 1, "source": "user",
             "message": f"please look at this {SENTINEL}"},
            {"step_id": 2, "source": "agent", "model_name": "claude-opus-4-8",
             "message": "reading the file",
             "reasoning_content": f"the secret is {SENTINEL}",
             "metrics": {"prompt_tokens": 100, "cached_tokens": 10,
                         "completion_tokens": 5, "cost_usd": 0.01},
             "tool_calls": [{"tool_call_id": "c1", "function_name": "read_file",
                             "arguments": {"path": f"/secrets/{SENTINEL}.txt"}}],
             "observation": {"results": [
                 {"source_call_id": "c1", "content": f"file body {SENTINEL}"}]}},
        ],
    }
    if with_subagent:
        traj["subagent_trajectories"] = [{
            "trajectory_id": f"{session_id}/agent-a",
            "extra": {"subagent_type": SUB_TYPE_SENTINEL},
            "steps": [{"step_id": 1, "source": "agent",
                       "model_name": "claude-opus-4-8",
                       "message": f"subagent body {SUB_STEP_SENTINEL}"}],
            "final_metrics": {"total_steps": 1, "total_completion_tokens": 2,
                              "total_cost_usd": 0.005},
        }]
    return traj


class TestRenderTraceSummaryEgress(unittest.TestCase):
    """Load-bearing egress NFR: --summary never echoes trajectory content.

    Stdlib only -- must pass with 0 external deps installed.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="capture-egress-")
        self.traj_path = Path(self.tmp) / "traj.json"
        self.traj = _planted_trajectory()
        self.traj_path.write_text(json.dumps(self.traj))
        # Real redaction flags file (the shape redact.py --flags-out writes).
        self.flags_path = Path(self.tmp) / "flags.json"
        self.flags_path.write_text(json.dumps(
            [{"type": "openai_key", "count": 2}, {"type": "aws_access_key_id", "count": 1}]))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_render_trace_summary_egress(self):
        rc, stdout, stderr = _run_capture(
            "render_trace.py", str(self.traj_path), "--summary",
            "--flags-file", str(self.flags_path), "--no-open")
        self.assertEqual(rc, 0, f"non-zero exit; stderr={stderr}")

        # The summary should carry metadata / counts / flag types only.
        self.assertIn("egress-test-session", stdout, "session id (metadata) expected")
        self.assertIn("Steps:", stdout, "step counts (metadata) expected")
        self.assertIn("openai_key", stdout, "flag type (metadata) expected")
        self.assertIn("Redaction flags:", stdout, "flags line (metadata) expected")

        # Precondition: the sentinel really IS planted in all four content fields
        # of the trajectory we just wrote (so an "absent from stdout" pass means
        # the shell stripped it, not that it was never there).
        s = self.traj["steps"]
        self.assertIn(SENTINEL, s[0]["message"])
        self.assertIn(SENTINEL, s[1]["reasoning_content"])
        self.assertIn(SENTINEL, json.dumps(s[1]["tool_calls"][0]["arguments"]))
        self.assertIn(SENTINEL, s[1]["observation"]["results"][0]["content"])

        # The load-bearing assertion: the planted secret never reaches stdout.
        # Assert per-field so a failure tells you WHICH content field leaked.
        msg = "%s leaked into --summary stdout (egress NFR violated)"
        self.assertNotIn(SENTINEL, stdout, msg % "steps[].message")
        self.assertNotIn(SENTINEL, stdout, msg % "steps[].reasoning_content")
        self.assertNotIn(SENTINEL, stdout, msg % "steps[].tool_calls[].arguments")
        self.assertNotIn(SENTINEL, stdout, msg % "steps[].observation.results[].content")

    def test_render_trace_summary_subagent_egress(self):
        # Same egress NFR, extended to subagents and made non-vacuous: a subagent
        # whose step message AND free-text subagent_type carry sentinels. The
        # in-chat summary must show the metadata-only Subagents line (proving the
        # subagent path executed, not silently skipped) while leaking neither.
        traj = _planted_trajectory(with_subagent=True)
        traj_path = Path(self.tmp) / "traj-sub.json"
        traj_path.write_text(json.dumps(traj))

        rc, stdout, stderr = _run_capture(
            "render_trace.py", str(traj_path), "--summary",
            "--flags-file", str(self.flags_path), "--no-open")
        self.assertEqual(rc, 0, f"non-zero exit; stderr={stderr}")

        # Precondition: the sentinels really ARE in the subagent we wrote, so an
        # "absent from stdout" pass means the shell omitted them by design.
        sub = traj["subagent_trajectories"][0]
        self.assertIn(SUB_STEP_SENTINEL, sub["steps"][0]["message"])
        self.assertIn(SUB_TYPE_SENTINEL, sub["extra"]["subagent_type"])

        # (2) The subagent path executed -> the metadata-only line is present.
        self.assertIn("Subagents:", stdout,
                      "the metadata-only subagent line must appear")

        # (3) Neither subagent content string leaks into the in-chat block.
        self.assertNotIn(SUB_STEP_SENTINEL, stdout,
                         "subagent step message leaked into --summary stdout")
        self.assertNotIn(SUB_TYPE_SENTINEL, stdout,
                         "free-text subagent_type leaked into --summary stdout")


class TestRenderTraceSummaryMissingFlags(unittest.TestCase):
    """--summary with a missing/malformed --flags-file: one-line stderr, the
    summary STILL renders (flags=[] / "no flags"), exit 0, no raw traceback.

    Stdlib only.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="capture-flags-")
        self.traj_path = Path(self.tmp) / "traj.json"
        self.traj_path.write_text(json.dumps(_planted_trajectory()))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _assert_graceful(self, stdout, stderr, rc):
        self.assertEqual(rc, 0, f"expected graceful exit 0; stderr={stderr}")
        # Summary still renders, with no flags.
        self.assertIn("Redaction flags:", stdout)
        self.assertIn("none", stdout.lower())
        self.assertIn("Steps:", stdout)
        # Clear one-line stderr message; no raw Python traceback.
        self.assertTrue(stderr.strip(), "expected a one-line stderr warning")
        self.assertNotIn("Traceback", stderr)

    def test_render_trace_summary_missing_flags(self):
        # Both the missing-file and the malformed-file cases must degrade the
        # same graceful way: one-line stderr, summary still renders, exit 0.
        missing = Path(self.tmp) / "does-not-exist.json"
        rc, stdout, stderr = _run_capture(
            "render_trace.py", str(self.traj_path), "--summary",
            "--flags-file", str(missing), "--no-open")
        self._assert_graceful(stdout, stderr, rc)

        bad = Path(self.tmp) / "bad.json"
        bad.write_text("{ this is not valid json ")
        rc, stdout, stderr = _run_capture(
            "render_trace.py", str(self.traj_path), "--summary",
            "--flags-file", str(bad), "--no-open")
        self._assert_graceful(stdout, stderr, rc)


class TestRenderTraceMainWritesHtml(unittest.TestCase):
    """Default mode (no --summary) with --no-open writes the .review.html and
    prints only the path + counts -- never trajectory content.

    Stdlib only.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="capture-html-")
        self.traj_path = Path(self.tmp) / "traj.json"
        self.traj_path.write_text(json.dumps(_planted_trajectory()))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_render_trace_main_writes_html(self):
        rc, stdout, stderr = _run_capture(
            "render_trace.py", str(self.traj_path), "--no-open")
        self.assertEqual(rc, 0, f"non-zero exit; stderr={stderr}")

        html_path = Path(self.tmp) / "traj.review.html"
        self.assertTrue(html_path.exists(),
                        "default mode should write the .review.html file")
        self.assertIn(str(html_path), stdout, "path should be printed to stdout")
        self.assertIn("steps", stdout, "step counts should be printed to stdout")

        # stdout prints path + counts only -- the planted secret must NOT be
        # echoed to the agent's context. (The secret IS in the HTML file, which
        # the human opens themselves; it must never be in stdout.)
        self.assertNotIn(SENTINEL, stdout,
                         "trajectory content leaked into stdout")
        # The HTML artifact is the human review surface -- it legitimately
        # contains the content, so confirm the round-trip wrote a real file.
        self.assertIn(SENTINEL, html_path.read_text(),
                      "HTML review file should contain the trajectory content")


@unittest.skipUnless(_HAS_NODE, "node/npm absent")
class TestAtifToViewerDataWrite(unittest.TestCase):
    """atif_to_viewer writes public/dataset.json + public/runs/<rid>.json.

    The git-clone / npm path is external (absent in CI), so this is guarded by
    node/npm. To stay hermetic (no network), we point --repo at a tiny LOCAL git
    repo and --pin at its HEAD: this still exercises ensure_viewer's real
    clone+checkout path without reaching the public network.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="capture-viewer-")
        self.traj_path = Path(self.tmp) / "redacted.json"
        # A redacted trajectory (no secrets) -- this is the artifact the command
        # feeds the viewer.
        self.traj_path.write_text(json.dumps(_planted_trajectory(
            session_id="viewer-sess", task_id="T10", spec_id="S2")))
        # Build a local git repo to serve as the (hermetic) viewer source.
        self.src_repo = Path(self.tmp) / "src-repo"
        self.src_repo.mkdir()
        _git = ["git", "-C", str(self.src_repo)]
        subprocess.run(_git + ["init", "-q"], check=True, capture_output=True)
        subprocess.run(_git + ["config", "user.email", "t@t.test"], check=True,
                       capture_output=True)
        subprocess.run(_git + ["config", "user.name", "t"], check=True,
                       capture_output=True)
        (self.src_repo / "placeholder.txt").write_text("{}")
        subprocess.run(_git + ["add", "-A"], check=True, capture_output=True)
        subprocess.run(_git + ["commit", "-qm", "init"], check=True,
                       capture_output=True)
        self.pin = subprocess.run(
            _git + ["rev-parse", "HEAD"], check=True, capture_output=True,
            text=True).stdout.strip()
        self.viewer_dir = Path(self.tmp) / "viewer"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_atif_to_viewer_data_write(self):
        rc, stdout, stderr = _run_capture(
            "atif_to_viewer.py", str(self.traj_path), "--no-serve", "--no-install",
            "--viewer-dir", str(self.viewer_dir),
            "--repo", str(self.src_repo), "--pin", self.pin)
        self.assertEqual(rc, 0, f"non-zero exit; stderr={stderr}")

        public = self.viewer_dir / "public"
        dataset = public / "dataset.json"
        self.assertTrue(dataset.exists(), "public/dataset.json should be written")

        # rid is slug(f"{session_id}-{task_id}") -> "viewer-sess-t10".
        rid = "viewer-sess-t10"
        run_file = public / "runs" / f"{rid}.json"
        self.assertTrue(run_file.exists(),
                        f"public/runs/{rid}.json should be written")

        # Sanity: the run-data is valid JSON with externalized steps.
        run_data = json.loads(run_file.read_text())
        self.assertIn("steps", run_data)
        # The deep link / run id should be surfaced to stdout (path-ish only).
        self.assertIn(rid, stdout)


@unittest.skipUnless(_HAS_OPIK, "opik absent")
class TestAtifToOpikIdempotent(unittest.TestCase):
    """Two main runs with DRVR_LEDGER -> a tmp file in an isolated HOME reuse the
    same trace id (ledger upsert -> 1 trace).

    Requires a reachable local Opik server; skipped when opik is not importable.
    Real opik, no mock.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="capture-opik-idem-")
        self.traj_path = Path(self.tmp) / "redacted.json"
        self.traj_path.write_text(json.dumps(_planted_trajectory(
            session_id="opik-idem-sess", task_id="T10")))
        self.ledger = Path(self.tmp) / "ledger.json"
        self.env = {**os.environ, "HOME": self.tmp,
                    "DRVR_LEDGER": str(self.ledger)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_atif_to_opik_idempotent(self):
        rc1, out1, err1 = _run_capture(
            "atif_to_opik.py", str(self.traj_path), env=self.env)
        self.assertEqual(rc1, 0, f"first run failed; stderr={err1}")
        rc2, out2, err2 = _run_capture(
            "atif_to_opik.py", str(self.traj_path), env=self.env)
        self.assertEqual(rc2, 0, f"second run failed; stderr={err2}")

        # The ledger should hold exactly ONE key -> ONE trace id, reused.
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual(len(ledger), 1, "ledger should record a single trace")
        (entry,) = ledger.values()
        trace_id = entry["trace_id"]
        # Both runs reference the same trace id; the second is an UPSERT (reused).
        self.assertIn(trace_id, out1)
        self.assertIn(trace_id, out2)
        self.assertIn("reused", out2.lower(),
                      "second run should report a reused (upserted) trace id")


@unittest.skipUnless(_HAS_OPIK, "opik absent")
class TestAtifToOpikR9Unreachable(unittest.TestCase):
    """R9: an unreachable --base-url -> non-zero exit, the local redacted artifact
    is STILL on disk, and the message says saved-locally with NO retry-queue claim
    and the 'unreachable' wording specifically (distinct from the generic-error
    path).

    Requires opik importable (so register() runs far enough to hit the network);
    skipped when opik is absent.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="capture-opik-r9-")
        self.traj_path = Path(self.tmp) / "redacted.json"
        self.traj_path.write_text(json.dumps(_planted_trajectory(
            session_id="opik-r9-sess", task_id="T10")))
        self.ledger = Path(self.tmp) / "ledger.json"
        self.env = {**os.environ, "HOME": self.tmp,
                    "DRVR_LEDGER": str(self.ledger)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_atif_to_opik_r9_unreachable(self):
        # An unroutable host:port that no Opik server answers on.
        bad_url = "http://127.0.0.1:1/api"
        rc, stdout, stderr = _run_capture(
            "atif_to_opik.py", str(self.traj_path), "--base-url", bad_url,
            env=self.env, timeout=60)

        self.assertNotEqual(rc, 0, "unreachable upload should exit non-zero")
        # The local redacted artifact is untouched on disk.
        self.assertTrue(self.traj_path.exists(),
                        "local redacted artifact must remain on disk")
        # Saved-locally message, NO retry-queue claim, "unreachable" wording.
        self.assertIn("unreachable", stderr.lower(),
                      "R9 must use the 'unreachable' wording specifically")
        self.assertIn("intact", stderr.lower(),
                      "message should say the local artifact is intact/saved")
        self.assertNotIn("queue", stderr.lower(),
                         "R9 must NOT claim a retry queue")


if __name__ == "__main__":
    unittest.main()
