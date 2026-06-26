"""Unit tests for atif_to_opik's pure cores + ledger recovery (scripts/capture/atif_to_opik.py).

These pin: UUIDv7 minting (valid + deterministic), span id stability, ISO dt
parsing, the idempotency key (trace_key), and corrupt-ledger recovery. The pure
helpers are driven directly — no mocks (mocking pure logic is a boundary failure).
The ledger-recovery test uses a REAL corrupt tmp file via the DRVR_LEDGER env
override inside an isolated tmp HOME (real I/O at the shell edge), so it exercises
trace_id_for's read path without invoking register (no opik needed).

The module MUST import without `opik` installed — that proves the lazy import
(Task 7) lands; until then a top-level `import opik` makes these red.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import atif_to_opik


class TestMintUuid7(unittest.TestCase):
    def test_mint_uuid7_valid_and_deterministic(self):
        ms = 1_700_000_000_000
        u = atif_to_opik._mint_uuid7("session::task", ms)
        hexs = u.replace("-", "")
        # Canonical 8-4-4-4-12 shape.
        self.assertEqual(len(hexs), 32)
        # Version nibble is 7 (13th hex digit, byte 6 high nibble).
        self.assertEqual(hexs[12], "7")
        # RFC4122 variant: high bits of the clock-seq byte (byte 8) are 10.
        variant_byte = int(hexs[16:18], 16)
        self.assertEqual(variant_byte >> 6, 0b10)
        # Embedded 48-bit ms matches the input ms.
        self.assertEqual(int(hexs[:12], 16), ms)
        # Deterministic: same (key, ms) -> same uuid.
        self.assertEqual(u, atif_to_opik._mint_uuid7("session::task", ms))
        # Different key -> different uuid (same ms).
        self.assertNotEqual(u, atif_to_opik._mint_uuid7("session::other", ms))


class TestSpanIdAndDt(unittest.TestCase):
    def test_span_id_and_dt(self):
        trace_id = atif_to_opik._mint_uuid7("session::task", 1_700_000_000_000)
        a = atif_to_opik._span_id(trace_id, "step1")
        # Deterministic: same (trace_id, suffix) -> same span id.
        self.assertEqual(a, atif_to_opik._span_id(trace_id, "step1"))
        # Different suffix -> different span id.
        self.assertNotEqual(a, atif_to_opik._span_id(trace_id, "step2"))
        # Reuses the trace's embedded ms (first 48 bits stay identical).
        self.assertEqual(a.replace("-", "")[:12], trace_id.replace("-", "")[:12])

        # _dt parses an ISO string to a non-str (datetime) value.
        parsed = atif_to_opik._dt("2020-01-01T00:00:00Z")
        self.assertIsNotNone(parsed)
        self.assertNotIsInstance(parsed, str)
        # None / unparseable -> None (and never a str).
        self.assertIsNone(atif_to_opik._dt(None))
        self.assertIsNone(atif_to_opik._dt("not-a-timestamp"))


class TestTraceKey(unittest.TestCase):
    def test_trace_key(self):
        self.assertEqual(atif_to_opik.trace_key("sid", "task"), "sid::task")
        # None inputs fall back to sentinels.
        self.assertEqual(atif_to_opik.trace_key(None, None), "unknown-session::no-task")
        self.assertEqual(atif_to_opik.trace_key(None, "task"), "unknown-session::task")
        self.assertEqual(atif_to_opik.trace_key("sid", None), "sid::no-task")
        # Stable / deterministic.
        self.assertEqual(atif_to_opik.trace_key("sid", "task"),
                         atif_to_opik.trace_key("sid", "task"))


class TestLedgerCorruptRecovers(unittest.TestCase):
    """A corrupt ledger.json is treated as empty (fresh mint + stderr warning),
    NOT a crash. Real corrupt tmp file via DRVR_LEDGER inside an isolated HOME —
    exercises trace_id_for's read path without register (so no opik needed)."""

    def setUp(self):
        self.test_home = tempfile.mkdtemp(prefix="drvr-opik-test-")
        self.ledger = os.path.join(self.test_home, ".driver", "capture", "ledger.json")
        os.makedirs(os.path.dirname(self.ledger), exist_ok=True)
        # Write a corrupt (non-JSON) ledger.
        with open(self.ledger, "w") as f:
            f.write("{ this is not valid json ]")
        self._orig_ledger = atif_to_opik.LEDGER
        self._orig_env = {k: os.environ.get(k) for k in ("HOME", "DRVR_LEDGER")}
        os.environ["HOME"] = self.test_home
        os.environ["DRVR_LEDGER"] = self.ledger
        # The module read LEDGER at import time; point it at the corrupt tmp file.
        atif_to_opik.LEDGER = self.ledger

    def tearDown(self):
        atif_to_opik.LEDGER = self._orig_ledger
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.test_home, ignore_errors=True)

    def test_ledger_corrupt_recovers(self):
        # Should NOT raise — corrupt ledger treated as empty, fresh id minted.
        trace_id, reused = atif_to_opik.trace_id_for(
            atif_to_opik.trace_key("sid", "task"))
        self.assertFalse(reused)
        # A valid UUIDv7-shaped id was minted.
        hexs = trace_id.replace("-", "")
        self.assertEqual(len(hexs), 32)
        self.assertEqual(hexs[12], "7")
        # Ledger was rewritten as valid JSON containing the new key.
        with open(self.ledger) as f:
            ledger = json.load(f)
        self.assertEqual(ledger["sid::task"]["trace_id"], trace_id)


if __name__ == "__main__":
    unittest.main()
