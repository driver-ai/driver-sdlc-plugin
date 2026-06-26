"""Unit tests for the pure pricing cost table (scripts/capture/pricing.py).

Pins the cost-table contract: substring precedence, step-cost math, and
unpriced-model detection. Pricing is a pure vendored literal table (DEC-021),
so these tests assert directly on return values — no mocks.
"""

import sys, unittest
from conftest import PLUGIN_ROOT
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import pricing


class TestPricing(unittest.TestCase):
    def test_pricing_rates_for_precedence(self):
        # _TABLE must be a list: precedence is order-dependent. A dict refactor
        # would lose the most-specific-first ordering this contract relies on.
        self.assertIsInstance(pricing._TABLE, list)

        # A dated opus-4-8 suffix resolves to the specific opus-4-8 row, NOT the
        # generic opus row — the specific key must be matched first.
        self.assertEqual(
            pricing.rates_for("claude-opus-4-8-20260315"),
            (5.0, 25.0, 6.25, 0.50),
        )
        # A generic opus model (no -4-8) falls through to the opus row.
        self.assertEqual(
            pricing.rates_for("claude-opus-4-20250101"),
            (15.0, 75.0, 18.75, 1.50),
        )
        # An unknown model resolves to the fallback tuple.
        self.assertEqual(
            pricing.rates_for("gpt-5"),
            (3.0, 15.0, 3.75, 0.30),
        )
        self.assertEqual(pricing.rates_for("gpt-5"), pricing._FALLBACK)

    def test_pricing_step_cost_math(self):
        # opus-4-8 rates: (input=5.0, output=25.0, cache_write=6.25, cache_read=0.50).
        # Hand-computed (each rate / 1e6):
        #   input:          1000 * 5.0  / 1e6 = 0.005
        #   cache_creation: 2000 * 6.25 / 1e6 = 0.0125
        #   cache_read:     4000 * 0.50 / 1e6 = 0.002
        #   output:          500 * 25.0 / 1e6 = 0.0125
        #   total                              = 0.032
        cost = pricing.step_cost_usd(
            "claude-opus-4-8-20260315",
            input_tokens=1000,
            cache_creation=2000,
            cache_read=4000,
            output_tokens=500,
        )
        self.assertAlmostEqual(cost, 0.032)

        # Zero tokens → exactly 0.0.
        zero = pricing.step_cost_usd(
            "claude-opus-4-8-20260315",
            input_tokens=0,
            cache_creation=0,
            cache_read=0,
            output_tokens=0,
        )
        self.assertEqual(zero, 0.0)

    def test_pricing_is_priced(self):
        # Known models → True.
        self.assertTrue(pricing.is_priced("claude-opus-4-8-20260315"))
        self.assertTrue(pricing.is_priced("claude-sonnet-4-6"))
        # Unknown / future models → False (M7).
        self.assertFalse(pricing.is_priced("gpt-5"))
        self.assertFalse(pricing.is_priced("some-unknown-model"))


if __name__ == "__main__":
    unittest.main()
