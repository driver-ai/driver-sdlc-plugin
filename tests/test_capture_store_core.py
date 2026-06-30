"""Unit tests for the rolling-capture store + throttle pure core (capture_store_core).

Pure-core tests: import `capture_store_core` ONLY (its `import cc_to_atif_core`
resolves off the inserted path). No harbor, no mocks. Values in, values out —
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


if __name__ == "__main__":
    unittest.main()
