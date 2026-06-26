"""Unit tests for atif_to_viewer's pure cores (scripts/capture/atif_to_viewer.py).

These pin: mutation detection, step mapping (masking routed through the SHARED
redaction core — Contract B — at both scrub sites, with non-str passthrough), and
a deterministic dataset build (time injected, no datetime.now()). Pure functions,
so assertions are on direct return values — no mocks, stdlib only.

The masking-via-Contract-B and time-injected-build_dataset tests are red until
Task 5 consolidates redaction onto redact.redact_text and purifies build_dataset;
detect_mutation / _cap robustness hold in both states.
"""

import json
import sys
import unittest

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import atif_to_viewer

# A typed token from the shared core looks like "[REDACTED:openai_key]" (colon +
# lowercase label). The retired local scrubber emitted "[REDACTED_API_KEY]" /
# "[REDACTED]" (underscore / bare) — so asserting on "[REDACTED:" proves the
# masking goes through Contract B, not a reintroduced local scrubber.
TYPED = "[REDACTED:"
SECRET_A = "sk-abcdefghijklmnopqrstuvwxyz0123"   # openai-shaped (>=20 body)
SECRET_B = "sk-ZYXWVUTSRQPONMLKJIHGFEDCBA9876"   # openai-shaped, distinct


class TestDetectMutation(unittest.TestCase):
    def test_file_edit_and_arg_key_variants(self):
        for key in ("path", "file_path", "filepath"):
            with self.subTest(key=key):
                m = atif_to_viewer.detect_mutation(
                    "write_file", json.dumps({key: "/a/b.py", "content": "x = 1"}))
                self.assertIsNotNone(m)
                self.assertEqual(m["kind"], "file")
                self.assertEqual(m["target"], "/a/b.py")

    def test_git_commit(self):
        m = atif_to_viewer.detect_mutation(
            "git_commit", json.dumps({"repo_path": "/r", "message": "fix the bug"}))
        self.assertEqual(m["kind"], "git")
        self.assertIn("fix the bug", m["summary"])

    def test_write_command(self):
        m = atif_to_viewer.detect_mutation(
            "bash", json.dumps({"command": "rm -rf /tmp/x"}))
        self.assertEqual(m["kind"], "command")
        self.assertIn("rm -rf", m["summary"])

    def test_non_mutating(self):
        self.assertIsNone(atif_to_viewer.detect_mutation(
            "read_file", json.dumps({"path": "/a"})))
        self.assertIsNone(atif_to_viewer.detect_mutation(
            "bash", json.dumps({"command": "ls -la"})))


class TestStepFromAtif(unittest.TestCase):
    def test_role_mapping_producible_sources(self):
        # Only agent/user are produced by cc_to_atif; pin those.
        self.assertEqual(atif_to_viewer.step_from_atif({"source": "agent"}, 0)["role"], "agent")
        self.assertEqual(atif_to_viewer.step_from_atif({"source": "user"}, 1)["role"], "user")

    def test_masks_via_contract_b_at_both_sites(self):
        step = {
            "step_id": 1, "source": "agent",
            "message": f"plain field {SECRET_A}",
            "tool_calls": [{"function_name": "write_file",
                            "arguments": json.dumps({"path": "/a/b.py",
                                                     "content": f"mutation field {SECRET_B}"})}],
        }
        out = atif_to_viewer.step_from_atif(step, 0)
        # Site 1: plain field (_cap) masked via the typed shared core.
        self.assertIn(TYPED, out["text"])
        self.assertNotIn(SECRET_A, out["text"])
        # Site 2: mutation detail field masked via the typed shared core.
        mut = out["mutations"][0]
        self.assertIn(TYPED, mut["detail"])
        self.assertNotIn(SECRET_B, mut["detail"])

    def test_field_cap_40kb(self):
        # Spaced text (short alnum runs) so this exercises the cap, not the shared
        # core's pure-alnum-run backtracking (a Plan-01 perf characteristic — see
        # the implementation log's follow-up note).
        big = "word " * 12_000          # 60 KB, > STEP_FIELD_CAP
        out = atif_to_viewer.step_from_atif({"step_id": 1, "source": "agent", "message": big}, 0)
        self.assertLess(len(out["text"]), 60_000)
        self.assertIn("truncated", out["text"])

    def test_non_str_passthrough(self):
        # A non-str value passes through unchanged (no TypeError) — mirrors the old
        # scrubber's non-str guard.
        self.assertEqual(atif_to_viewer._cap(12345), 12345)
        self.assertIsNone(atif_to_viewer._cap(None))


class TestBuildDataset(unittest.TestCase):
    def _traj(self):
        return {
            "session_id": "sess-1",
            "agent": {"model_name": "claude"},
            "extra": {"sdlc_task_id": "T1", "sdlc_spec_id": "S1", "sdlc_intent": "do it"},
            "final_metrics": {"total_prompt_tokens": 300, "total_completion_tokens": 40,
                              "total_cached_tokens": 75, "total_cost_usd": 1.23},
            "steps": [
                {"step_id": 1, "source": "agent", "message": "hi",
                 "metrics": {"prompt_tokens": 100, "completion_tokens": 10}},
                {"step_id": 2, "source": "user", "message": "yo"},
            ],
        }

    def test_build_dataset_injected_time(self):
        gen = "2020-01-01T00:00:00Z"
        dataset, rid, tid, steps = atif_to_viewer.build_dataset(
            self._traj(), task_id="T1", spec_id="S1", intent="do it", generated_at=gen)
        # Time is injected, not wall-clock.
        self.assertEqual(dataset["generatedAt"], gen)
        # Deterministic ids/slugs and token rollup given the same inputs.
        dataset2, rid2, tid2, _ = atif_to_viewer.build_dataset(
            self._traj(), task_id="T1", spec_id="S1", intent="do it", generated_at=gen)
        self.assertEqual((rid, tid), (rid2, tid2))
        self.assertEqual(dataset["runs"][0]["tokens"]["completion"], 40)
        self.assertEqual(dataset["runs"][0]["tokens"]["prompt"], 300)
        self.assertEqual(len(steps), 2)


if __name__ == "__main__":
    unittest.main()
