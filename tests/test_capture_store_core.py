"""Unit tests for the rolling-capture store + throttle pure core (capture_store_core).

Pure-core tests: import `capture_store_core` ONLY (its `import cc_to_atif_core`
resolves off the inserted path). No logs2atif, no mocks. Values in, values out —
mtimes and counts are passed as arguments, never read from a clock or disk.
Stdlib `unittest` only.
"""
import os
import sys
import unittest

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import capture_store_core as store   # its `import cc_to_atif_core` resolves off the inserted path


# ---------------------------------------------------------------------------
# store_path_for
# ---------------------------------------------------------------------------

class TestStorePathFor(unittest.TestCase):
    def test_valid_uuid_session_id_full_path(self):
        base = "/var/capture"
        sid = "8f5a3cf6-4988-4beb-a861-3163dfac3371"
        path = store.store_path_for(base, sid)
        expected = os.path.join(base, "sessions", sid, "trajectory.redacted.json")
        self.assertEqual(path, expected)
        # Parent dir is <base>/sessions/<session_id>.
        self.assertEqual(os.path.dirname(path),
                         os.path.join(base, "sessions", sid))

    def test_unsafe_session_id_raises_value_error(self):
        # traversal guard: a transcript-supplied id can never traverse out.
        for sid in ("../etc", "", "."):
            with self.assertRaises(ValueError):
                store.store_path_for("/var/capture", sid)

    def test_non_str_session_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            store.store_path_for("/var/capture", 123)


# ---------------------------------------------------------------------------
# annotations_path_for
# ---------------------------------------------------------------------------

class TestAnnotationsPathFor(unittest.TestCase):
    def test_valid_session_id_full_path(self):
        base = "/var/capture"
        sid = "8f5a3cf6-4988-4beb-a861-3163dfac3371"
        path = store.annotations_path_for(base, sid)
        expected = os.path.join(base, "sessions", sid, "annotations.json")
        self.assertEqual(path, expected)
        # Sidecar lives alongside the trajectory in the same session dir.
        self.assertEqual(os.path.dirname(path),
                         os.path.dirname(store.store_path_for(base, sid)))

    def test_unsafe_session_id_raises_value_error(self):
        # traversal guard mirrors store_path_for: a URL-supplied id can't traverse.
        for sid in ("../etc", "", ".", "a/b", ".hidden"):
            with self.subTest(sid=sid):
                with self.assertRaises(ValueError):
                    store.annotations_path_for("/var/capture", sid)

    def test_non_str_session_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            store.annotations_path_for("/var/capture", 123)


# ---------------------------------------------------------------------------
# should_roll
# ---------------------------------------------------------------------------

class TestShouldRoll(unittest.TestCase):
    def setUp(self):
        self.t = store.RollThreshold()

    def test_first_roll_true_when_at_min_first_count(self):
        # prev_count <= 0 (first roll) and cur_count >= min_first_count → True.
        self.assertTrue(store.should_roll(
            prev_count=0, prev_mtime=0.0,
            cur_count=self.t.min_first_count, cur_mtime=0.0,
            threshold=self.t))

    def test_first_roll_false_when_below_min_first_count(self):
        # Too-thin transcript: cur_count < min_first_count → not converted early.
        self.assertFalse(store.should_roll(
            prev_count=0, prev_mtime=0.0,
            cur_count=self.t.min_first_count - 1, cur_mtime=0.0,
            threshold=self.t))

    def test_true_when_record_delta_crosses_threshold(self):
        # prev_count > 0 and (cur_count - prev_count) >= min_record_delta → True.
        prev = 5
        self.assertTrue(store.should_roll(
            prev_count=prev, prev_mtime=0.0,
            cur_count=prev + self.t.min_record_delta, cur_mtime=0.0,
            threshold=self.t))

    def test_true_when_mtime_delta_crosses_threshold(self):
        # prev_count > 0, line delta below threshold, but elapsed mtime crosses.
        prev = 5
        self.assertTrue(store.should_roll(
            prev_count=prev, prev_mtime=100.0,
            cur_count=prev + 1, cur_mtime=100.0 + self.t.min_seconds,
            threshold=self.t))

    def test_false_when_both_deltas_below_threshold(self):
        prev = 5
        self.assertFalse(store.should_roll(
            prev_count=prev, prev_mtime=100.0,
            cur_count=prev + 1, cur_mtime=100.0 + self.t.min_seconds - 1.0,
            threshold=self.t))


# ---------------------------------------------------------------------------
# is_store_fresh
# ---------------------------------------------------------------------------

class TestIsStoreFresh(unittest.TestCase):
    def setUp(self):
        self.t = store.RollThreshold()

    def test_fresh_when_prev_positive_and_delta_below_threshold(self):
        prev = 10
        self.assertTrue(store.is_store_fresh(
            prev_count=prev, cur_count=prev + self.t.min_record_delta - 1,
            threshold=self.t))

    def test_not_fresh_when_delta_at_or_above_threshold(self):
        prev = 10
        self.assertFalse(store.is_store_fresh(
            prev_count=prev, cur_count=prev + self.t.min_record_delta,
            threshold=self.t))

    def test_not_fresh_when_prev_count_not_positive(self):
        # prev_count <= 0 means nothing was rolled yet → never fresh.
        self.assertFalse(store.is_store_fresh(
            prev_count=0, cur_count=5, threshold=self.t))


# ---------------------------------------------------------------------------
# Tying / multi-session index (group_key_for, is_provisional_group,
# update_index, resolve_lineage, complete_identity)
# ---------------------------------------------------------------------------

class TestGroupKeyFor(unittest.TestCase):
    def test_task_id_takes_precedence(self):
        self.assertEqual(store.group_key_for("T-1", "S-1", "br"), "T-1")

    def test_spec_id_when_no_task(self):
        self.assertEqual(store.group_key_for(None, "S-1", "br"), "S-1")

    def test_branch_fallback_when_no_task_or_spec(self):
        self.assertEqual(store.group_key_for(None, None, "br"), "branch:br")

    def test_ungrouped_when_nothing(self):
        self.assertEqual(store.group_key_for(None, None, None), "ungrouped")

    def test_empty_and_whitespace_count_as_absent(self):
        # empty AND whitespace-only strings fall through to the next level.
        self.assertEqual(store.group_key_for("", "", "br"), "branch:br")
        self.assertEqual(store.group_key_for("  ", None, "br"), "branch:br")

    def test_returned_key_is_stripped(self):
        self.assertEqual(store.group_key_for(" T-1 ", None, None), "T-1")


class TestIsProvisionalGroup(unittest.TestCase):
    def test_branch_and_ungrouped_are_provisional(self):
        self.assertTrue(store.is_provisional_group("branch:x"))
        self.assertTrue(store.is_provisional_group("ungrouped"))

    def test_task_and_spec_keys_are_not_provisional(self):
        self.assertFalse(store.is_provisional_group("T-1"))
        self.assertFalse(store.is_provisional_group("S-1"))

    def test_non_str_argument_is_not_provisional_no_crash(self):
        self.assertFalse(store.is_provisional_group(None))
        self.assertFalse(store.is_provisional_group(123))


class TestUpdateIndex(unittest.TestCase):
    def _entry(self, sid, gk, **kw):
        entry = {
            "session_id": sid,
            "group_key": gk,
            "store_path": f"/s/{sid}",
            "cwd": "/repo",
            "first_seen": "2026-01-01T00:00:00Z",
            "last_seen": "2026-01-01T00:00:00Z",
            "record_count": 10,
            "total_cost_usd": 0.01,
            "prev_session_id": None,
        }
        entry.update(kw)
        return entry

    def test_records_entry_under_group_key(self):
        idx = store.update_index({}, self._entry("A", "branch:x"))
        self.assertIn("branch:x", idx)
        self.assertIn("A", idx["branch:x"])
        self.assertEqual(idx["branch:x"]["A"]["session_id"], "A")

    def test_same_session_same_group_updates_in_place(self):
        idx = store.update_index({}, self._entry("A", "branch:x", last_seen="t1"))
        idx = store.update_index(idx, self._entry("A", "branch:x", last_seen="t2"))
        # one entry, updated in place.
        self.assertEqual(len(idx["branch:x"]), 1)
        self.assertEqual(idx["branch:x"]["A"]["last_seen"], "t2")

    def test_different_session_appends_union(self):
        idx = store.update_index({}, self._entry("A", "branch:x"))
        idx = store.update_index(idx, self._entry("B", "branch:x"))
        self.assertEqual(set(idx["branch:x"].keys()), {"A", "B"})

    def test_returns_new_dict_input_not_mutated(self):
        original = {}
        idx = store.update_index(original, self._entry("A", "branch:x"))
        # input untouched.
        self.assertEqual(original, {})
        self.assertIsNot(idx, original)

    def test_branch_change_migrates_and_prunes_empty_group(self):
        idx = store.update_index(
            {}, self._entry("S", "branch:main", first_seen="orig"))
        idx = store.update_index(
            idx, self._entry("S", "branch:feature", first_seen="later"))
        # S lives under branch:feature only; branch:main pruned.
        self.assertNotIn("branch:main", idx)
        self.assertIn("S", idx["branch:feature"])
        # first_seen preserved from the original appearance.
        self.assertEqual(idx["branch:feature"]["S"]["first_seen"], "orig")

    def test_accumulator_none_keeps_prior(self):
        idx = store.update_index(
            {}, self._entry("A", "branch:x", record_count=40, total_cost_usd=0.12))
        idx = store.update_index(
            idx, self._entry("A", "branch:x", record_count=None, total_cost_usd=None))
        self.assertEqual(idx["branch:x"]["A"]["record_count"], 40)
        self.assertEqual(idx["branch:x"]["A"]["total_cost_usd"], 0.12)

    def test_accumulator_genuine_zero_overwrites(self):
        idx = store.update_index(
            {}, self._entry("A", "branch:x", record_count=40, total_cost_usd=0.12))
        idx = store.update_index(
            idx, self._entry("A", "branch:x", record_count=0, total_cost_usd=0.0))
        # a genuine 0/0.0 (free/cached roll) overwrites a stale prior.
        self.assertEqual(idx["branch:x"]["A"]["record_count"], 0)
        self.assertEqual(idx["branch:x"]["A"]["total_cost_usd"], 0.0)

    def test_accumulator_real_value_overwrites(self):
        idx = store.update_index(
            {}, self._entry("A", "branch:x", record_count=40))
        idx = store.update_index(
            idx, self._entry("A", "branch:x", record_count=80))
        self.assertEqual(idx["branch:x"]["A"]["record_count"], 80)


class TestResolveLineage(unittest.TestCase):
    def _entry(self, sid, gk, cwd, last_seen, prev=None):
        return {
            "session_id": sid,
            "group_key": gk,
            "store_path": f"/s/{sid}",
            "cwd": cwd,
            "first_seen": last_seen,
            "last_seen": last_seen,
            "record_count": 1,
            "total_cost_usd": 0.0,
            "prev_session_id": prev,
        }

    def test_branch_group_links_only_when_cwd_matches(self):
        idx = store.update_index(
            {}, self._entry("A", "branch:x", "/repo", "t1"))
        # matching cwd -> A is the prior for a new session B.
        self.assertEqual(
            store.resolve_lineage(idx, "branch:x", "/repo", "B"), "A")

    def test_branch_group_no_link_across_cwd(self):
        idx = store.update_index(
            {}, self._entry("A", "branch:x", "/repo", "t1"))
        # different cwd -> no cross-repo/worktree link.
        self.assertIsNone(
            store.resolve_lineage(idx, "branch:x", "/other-repo", "B"))

    def test_ungrouped_always_none(self):
        idx = store.update_index(
            {}, self._entry("A", "ungrouped", "/repo", "t1"))
        self.assertIsNone(
            store.resolve_lineage(idx, "ungrouped", "/repo", "B"))

    def test_none_when_no_prior_session(self):
        # first session in the arc -> no prior.
        self.assertIsNone(store.resolve_lineage({}, "branch:x", "/repo", "A"))

    def test_none_when_only_candidate_is_self(self):
        idx = store.update_index(
            {}, self._entry("A", "branch:x", "/repo", "t1"))
        # the only session is the new one itself -> no prior.
        self.assertIsNone(
            store.resolve_lineage(idx, "branch:x", "/repo", "A"))

    def test_tie_break_by_session_id_on_equal_last_seen(self):
        idx = store.update_index(
            {}, self._entry("A", "branch:x", "/repo", "t-equal"))
        idx = store.update_index(
            idx, self._entry("B", "branch:x", "/repo", "t-equal"))
        # equal last_seen -> deterministic max by session_id -> "B".
        self.assertEqual(
            store.resolve_lineage(idx, "branch:x", "/repo", "C"), "B")


class TestReRollLineageStability(unittest.TestCase):
    def _register(self, idx, sid, cwd, last_seen, prev):
        entry = {
            "session_id": sid,
            "group_key": "branch:x",
            "store_path": f"/s/{sid}",
            "cwd": cwd,
            "first_seen": last_seen,
            "last_seen": last_seen,
            "record_count": 1,
            "total_cost_usd": 0.0,
            "prev_session_id": prev,
        }
        return store.update_index(idx, entry)

    def test_in_arc_lineage_is_immutable_on_reroll(self):
        idx = {}
        # A, B, C registered in order under branch:x.
        idx = self._register(idx, "A", "/repo", "t1", None)
        idx = self._register(idx, "B", "/repo", "t2", "A")
        idx = self._register(idx, "C", "/repo", "t3", "B")
        # A re-rolls: same session_id, bumped last_seen, a freshly-computed
        # prev_session_id (would be C for a new session) -> A.prev STAYS None.
        idx = self._register(idx, "A", "/repo", "t4", "C")
        self.assertIsNone(idx["branch:x"]["A"]["prev_session_id"])
        self.assertEqual(idx["branch:x"]["B"]["prev_session_id"], "A")
        self.assertEqual(idx["branch:x"]["C"]["prev_session_id"], "B")

    def test_branch_switch_migrate_recomputes_prev_for_new_arc(self):
        idx = {}
        # A, B live on branch:x; a prior P already sits on branch:y.
        idx = self._register(idx, "P", "/repo", "t0", None)
        idx["branch:y"] = idx.pop("branch:x")
        idx["branch:y"]["P"]["group_key"] = "branch:y"
        idx = self._register(idx, "A", "/repo", "t1", None)
        # A switches to branch:y with a freshly-computed prev for the new arc.
        entry = {
            "session_id": "A",
            "group_key": "branch:y",
            "store_path": "/s/A",
            "cwd": "/repo",
            "first_seen": "t1",
            "last_seen": "t2",
            "record_count": 1,
            "total_cost_usd": 0.0,
            "prev_session_id": "P",
        }
        idx = store.update_index(idx, entry)
        # migrate keeps the freshly-computed prev for the NEW arc.
        self.assertEqual(idx["branch:y"]["A"]["prev_session_id"], "P")
        self.assertNotIn("branch:x", idx)


class TestCompleteIdentity(unittest.TestCase):
    def test_fills_absent_ids_and_nested_branch(self):
        traj = {"extra": {}}
        out = store.complete_identity(traj, "T-1", "S-1", "main")
        self.assertEqual(out["extra"]["sdlc_task_id"], "T-1")
        self.assertEqual(out["extra"]["sdlc_spec_id"], "S-1")
        # branch nests at extra.environment.branch (the REAL serialized location).
        self.assertEqual(out["extra"]["environment"]["branch"], "main")
        self.assertNotIn("environment", out)

    def test_idempotent_present_values_unchanged(self):
        traj = {"extra": {
            "sdlc_task_id": "T-orig",
            "sdlc_spec_id": "S-orig",
            "environment": {"branch": "orig"},
        }}
        # different override args -> still a no-op (present values kept).
        out = store.complete_identity(traj, "T-new", "S-new", "new")
        self.assertEqual(out["extra"]["sdlc_task_id"], "T-orig")
        self.assertEqual(out["extra"]["sdlc_spec_id"], "S-orig")
        self.assertEqual(out["extra"]["environment"]["branch"], "orig")

    def test_whitespace_input_args_treated_as_absent(self):
        traj = {"extra": {}}
        out = store.complete_identity(traj, "  ", "\t", "  ")
        # whitespace-only args are never stored.
        self.assertNotIn("sdlc_task_id", out["extra"])
        self.assertNotIn("sdlc_spec_id", out["extra"])
        self.assertNotIn("environment", out["extra"])

    def test_stored_whitespace_treated_as_absent_and_filled(self):
        traj = {"extra": {
            "sdlc_task_id": "   ",
            "environment": {"branch": "\t"},
        }}
        out = store.complete_identity(traj, "T-1", None, "main")
        # a stored whitespace-only id/branch counts as absent and is filled.
        self.assertEqual(out["extra"]["sdlc_task_id"], "T-1")
        self.assertEqual(out["extra"]["environment"]["branch"], "main")

    def test_non_dict_extra_coerced(self):
        for bad in (None, "junk", ["list"]):
            traj = {"extra": bad}
            out = store.complete_identity(traj, "T-1", None, "main")
            self.assertEqual(out["extra"]["sdlc_task_id"], "T-1")
            self.assertEqual(out["extra"]["environment"]["branch"], "main")

    def test_non_dict_environment_coerced(self):
        traj = {"extra": {"environment": "junk"}}
        out = store.complete_identity(traj, None, None, "main")
        self.assertEqual(out["extra"]["environment"]["branch"], "main")

    def test_content_free_only_ids_and_branch_written(self):
        traj = {"extra": {}}
        out = store.complete_identity(traj, "T-1", "S-1", "main")
        for forbidden in ("message", "reasoning", "observation"):
            self.assertNotIn(forbidden, out["extra"])

    def test_input_not_mutated(self):
        traj = {"extra": {}}
        out = store.complete_identity(traj, "T-1", "S-1", "main")
        # a new dict is returned; the input extra stays empty.
        self.assertEqual(traj["extra"], {})
        self.assertIsNot(out, traj)


if __name__ == "__main__":
    unittest.main()
