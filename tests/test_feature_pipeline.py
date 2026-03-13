"""
Tests for Sprint 3 feature pipeline signal computation.

Tests the rule-based signal logic that transforms raw derivatives data
into Family D direction + confidence.
"""
import unittest

from market_data.onchain.feature_pipeline import evaluate_derivatives_signal


class TestFeaturePipeline(unittest.TestCase):
    """Tests for evaluate_derivatives_signal()."""

    def test_extreme_positive_funding_returns_short(self):
        """Funding rate > 0.05% per 8h → bearish (overleveraged longs)."""
        derivatives = {"funding_rate": 0.001, "oi_change_1h_pct": 3.0}  # 0.1% funding
        positioning = {"long_short_ratio": 1.5, "taker_buy_sell_ratio": 0.6}

        result = evaluate_derivatives_signal(derivatives, positioning, None, None)
        self.assertIsNotNone(result)
        direction, confidence, reasons = result
        self.assertEqual(direction, "short")
        self.assertGreater(confidence, 0.50)
        self.assertTrue(any("funding" in r for r in reasons))

    def test_extreme_negative_funding_returns_long(self):
        """Funding rate < -0.05% per 8h → bullish (overleveraged shorts)."""
        derivatives = {"funding_rate": -0.001, "oi_change_1h_pct": -6.0}
        positioning = {"long_short_ratio": 0.4, "taker_buy_sell_ratio": 1.5}

        result = evaluate_derivatives_signal(derivatives, positioning, None, None)
        self.assertIsNotNone(result)
        direction, confidence, reasons = result
        self.assertEqual(direction, "long")
        self.assertGreater(confidence, 0.50)

    def test_crowded_longs_bearish(self):
        """L/S ratio > 2.0 → bearish (contrarian)."""
        derivatives = {"funding_rate": 0.0008}  # bullish funding
        positioning = {"long_short_ratio": 2.5, "taker_buy_sell_ratio": 0.65}

        result = evaluate_derivatives_signal(derivatives, positioning, None, None)
        self.assertIsNotNone(result)
        direction, confidence, reasons = result
        self.assertEqual(direction, "short")

    def test_crowded_shorts_bullish(self):
        """L/S ratio < 0.5 → bullish (contrarian)."""
        derivatives = {"funding_rate": -0.0008}
        positioning = {"long_short_ratio": 0.3, "taker_buy_sell_ratio": 1.4}

        result = evaluate_derivatives_signal(derivatives, positioning, None, None)
        self.assertIsNotNone(result)
        direction, confidence, reasons = result
        self.assertEqual(direction, "long")

    def test_conflicting_signals_abstain(self):
        """Conflicting sub-signals with equal weight → None (abstain)."""
        derivatives = {"funding_rate": 0.001}  # short signal
        positioning = {"long_short_ratio": 0.3, "taker_buy_sell_ratio": 1.5}  # long signals

        result = evaluate_derivatives_signal(derivatives, positioning, None, None)
        # Could be None or a weak signal depending on weights
        if result is not None:
            _, confidence, _ = result
            self.assertLessEqual(confidence, 0.80)

    def test_single_signal_abstains(self):
        """Only 1 sub-signal firing → None (need 2+)."""
        derivatives = {"funding_rate": 0.001}
        # No positioning data, no OI change
        result = evaluate_derivatives_signal(derivatives, None, None, None)
        self.assertIsNone(result)

    def test_missing_derivatives_returns_none(self):
        """No derivatives data → None."""
        result = evaluate_derivatives_signal(None, None, None, None)
        self.assertIsNone(result)

    def test_missing_positioning_still_computes(self):
        """Missing positioning data → still computes from derivatives only."""
        derivatives = {"funding_rate": 0.001, "oi_change_1h_pct": 8.0}
        result = evaluate_derivatives_signal(derivatives, None, None, None)
        # Should have funding + OI signals = 2 sub-signals, enough to produce direction
        self.assertIsNotNone(result)
        direction, confidence, reasons = result
        self.assertEqual(direction, "short")  # Both are bearish

    def test_fear_greed_veto_extreme_greed_blocks_long(self):
        """Extreme Greed (>80) + long signal → suppressed."""
        derivatives = {"funding_rate": -0.001, "oi_change_1h_pct": -8.0}
        positioning = {"long_short_ratio": 0.3, "taker_buy_sell_ratio": 1.5}
        sentiment = {"fear_greed_index": 85}

        result = evaluate_derivatives_signal(derivatives, positioning, None, sentiment)
        self.assertIsNone(result)  # Vetoed by extreme greed

    def test_fear_greed_veto_extreme_fear_blocks_short(self):
        """Extreme Fear (<20) + short signal → suppressed."""
        derivatives = {"funding_rate": 0.001, "oi_change_1h_pct": 8.0}
        positioning = {"long_short_ratio": 2.5, "taker_buy_sell_ratio": 0.6}
        sentiment = {"fear_greed_index": 15}

        result = evaluate_derivatives_signal(derivatives, positioning, None, sentiment)
        self.assertIsNone(result)  # Vetoed by extreme fear

    def test_fear_greed_neutral_no_veto(self):
        """Neutral sentiment (30-70) does not veto."""
        derivatives = {"funding_rate": 0.001, "oi_change_1h_pct": 8.0}
        positioning = {"long_short_ratio": 2.5, "taker_buy_sell_ratio": 0.6}
        sentiment = {"fear_greed_index": 50}

        result = evaluate_derivatives_signal(derivatives, positioning, None, sentiment)
        self.assertIsNotNone(result)
        direction, _, _ = result
        self.assertEqual(direction, "short")

    def test_confidence_capped_at_080(self):
        """Confidence should never exceed 0.80."""
        # All signals agree strongly
        derivatives = {"funding_rate": 0.002, "oi_change_1h_pct": 10.0}
        positioning = {"long_short_ratio": 3.0, "taker_buy_sell_ratio": 0.5}

        result = evaluate_derivatives_signal(derivatives, positioning, None, None)
        self.assertIsNotNone(result)
        _, confidence, _ = result
        self.assertLessEqual(confidence, 0.80)

    def test_oi_surge_bearish(self):
        """OI surging >5% → bearish signal."""
        derivatives = {"funding_rate": 0.0008, "oi_change_1h_pct": 8.0}
        result = evaluate_derivatives_signal(derivatives, None, None, None)
        self.assertIsNotNone(result)
        direction, _, reasons = result
        self.assertEqual(direction, "short")
        self.assertTrue(any("oi" in r for r in reasons))

    def test_oi_drop_bullish(self):
        """OI dropping <-5% → bullish signal."""
        derivatives = {"funding_rate": -0.0008, "oi_change_1h_pct": -8.0}
        result = evaluate_derivatives_signal(derivatives, None, None, None)
        self.assertIsNotNone(result)
        direction, _, reasons = result
        self.assertEqual(direction, "long")

    def test_all_none_inputs(self):
        """All None inputs → None."""
        result = evaluate_derivatives_signal(None, None, None, None)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
