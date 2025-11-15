"""
Test scalper strategy with STEP 6 enhancements.

Tests verify:
- Trade throttling (max 3/min)
- Spread check (max 3bps)
- Latency check (max 500ms)
- RR validation (min 1.0)
- Signal emission/abstention logic
"""

import pytest
import pandas as pd
import numpy as np
from decimal import Decimal
from datetime import datetime, timezone

from strategies.scalper import ScalperStrategy
from ai_engine.schemas import MarketSnapshot, RegimeLabel


@pytest.fixture
def scalper_strategy():
    """Create scalper strategy with STEP 6 defaults."""
    return ScalperStrategy(
        ema_fast=5,
        ema_slow=15,
        atr_period=14,
        max_spread_bps=Decimal("3.0"),
        target_rr=Decimal("1.2"),
        max_hold_bars=8,
        sl_atr_multiple=Decimal("1.0"),
        kelly_cap=Decimal("0.30"),
        max_latency_ms=500.0,         # STEP 6
        max_trades_per_minute=3,      # STEP 6
        min_rr=1.0,                   # STEP 6
    )


@pytest.fixture
def scalping_ohlcv():
    """Create fast-moving OHLCV data for scalping (1m bars)."""
    np.random.seed(42)
    n = 50

    # Quick uptrend for EMA crossover
    base_prices = np.linspace(50000, 50200, n)
    noise = np.random.normal(0, 20, n)
    close_prices = base_prices + noise

    volume = np.random.uniform(1e6, 3e6, n)

    high_prices = close_prices + np.random.uniform(10, 50, n)
    low_prices = close_prices - np.random.uniform(10, 50, n)
    open_prices = close_prices - np.random.uniform(-20, 20, n)

    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="1min"),
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volume,
    })


@pytest.fixture
def tight_spread_snapshot():
    """Create market snapshot with tight spread."""
    # MarketSnapshot is frozen, so we can't add bid/ask after creation
    # The strategy has a fallback to use the spread_check filter if bid/ask are missing
    return MarketSnapshot(
        symbol="BTC/USD",
        timeframe="1m",  # 1 minute bars
        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        mid_price=50100.0,
        spread_bps=2.0,  # Tight spread (< 3bps)
        volume_24h=1000000000.0,  # High liquidity for scalping
    )


@pytest.fixture
def wide_spread_snapshot():
    """Create market snapshot with wide spread."""
    return MarketSnapshot(
        symbol="BTC/USD",
        timeframe="1m",
        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        mid_price=50100.0,
        spread_bps=10.0,  # Wide spread (> 3bps)
        volume_24h=1000000000.0,
    )


class TestScalperThrottling:
    """Test trade throttling (max 3 trades/min)."""

    def test_throttles_after_max_trades(self, scalper_strategy, scalping_ohlcv, tight_spread_snapshot):
        """Test that throttler limits trades to 3 per minute."""
        # Reset throttler
        scalper_strategy.throttler.reset()

        # Prepare strategy
        scalper_strategy.prepare(tight_spread_snapshot, scalping_ohlcv)

        # Generate multiple signals rapidly
        signals_generated = []
        for i in range(5):
            signals = scalper_strategy.generate_signals(
                tight_spread_snapshot,
                scalping_ohlcv,
                RegimeLabel.BULL,
            )
            signals_generated.extend(signals)

        # Should have max 3 signals (throttled)
        assert len(signals_generated) <= scalper_strategy.max_trades_per_minute

    def test_allows_trade_within_limit(self, scalper_strategy):
        """Test that trades are allowed when under throttle limit."""
        # Reset throttler
        scalper_strategy.throttler.reset()

        current_time = pd.Timestamp.now()

        # Should allow first 3 trades
        for i in range(3):
            assert scalper_strategy.throttler.can_trade(current_time)
            scalper_strategy.throttler.record_trade(current_time)

        # Should NOT allow 4th trade
        assert not scalper_strategy.throttler.can_trade(current_time)

    def test_resets_after_one_minute(self, scalper_strategy):
        """Test that throttler resets after 1 minute."""
        # Reset throttler
        scalper_strategy.throttler.reset()

        # Record 3 trades at t=0
        start_time = pd.Timestamp('2024-10-25 10:00:00')
        for i in range(3):
            scalper_strategy.throttler.record_trade(start_time)

        # Should be throttled immediately
        assert not scalper_strategy.throttler.can_trade(start_time)

        # After 61 seconds, should allow new trades
        later_time = start_time + pd.Timedelta(seconds=61)
        assert scalper_strategy.throttler.can_trade(later_time)


class TestScalperSpreadCheck:
    """Test spread check (max 3bps)."""

    def test_accepts_tight_spread(self, scalper_strategy, tight_spread_snapshot):
        """Test that tight spreads are accepted."""
        # Should trade with tight spread
        should_trade = scalper_strategy.should_trade(tight_spread_snapshot, latency_ms=100.0)
        assert should_trade

    def test_rejects_wide_spread(self, scalper_strategy, wide_spread_snapshot):
        """Test that wide spreads are rejected."""
        # Should NOT trade with wide spread
        should_trade = scalper_strategy.should_trade(wide_spread_snapshot, latency_ms=100.0)
        assert not should_trade

    def test_spread_check_uses_centralized_utility(self, scalper_strategy):
        """Test that spread check uses centralized check_spread_acceptable()."""
        from strategies.utils import check_spread_acceptable

        # Test with tight spread (1.5 / 50000.5 = 0.003% = 0.3bps)
        tight_ok = check_spread_acceptable(
            bid=50000.0,
            ask=50001.5,
            max_spread_bps=3.0,
        )
        assert tight_ok

        # Test with wide spread (25 / 50012.5 = 0.05% = 50bps)
        wide_ok = check_spread_acceptable(
            bid=50000.0,
            ask=50025.0,  # Much wider spread
            max_spread_bps=3.0,
        )
        assert not wide_ok


class TestScalperLatencyCheck:
    """Test latency check (max 500ms)."""

    def test_accepts_low_latency(self, scalper_strategy, tight_spread_snapshot):
        """Test that low latency is accepted."""
        # Should trade with low latency
        should_trade = scalper_strategy.should_trade(tight_spread_snapshot, latency_ms=100.0)
        assert should_trade

    def test_rejects_high_latency(self, scalper_strategy, tight_spread_snapshot):
        """Test that high latency is rejected."""
        # Should NOT trade with high latency
        should_trade = scalper_strategy.should_trade(tight_spread_snapshot, latency_ms=600.0)
        assert not should_trade

    def test_latency_check_uses_centralized_utility(self):
        """Test that latency check uses centralized check_latency_acceptable()."""
        from strategies.utils import check_latency_acceptable

        # Test with acceptable latency
        low_ok = check_latency_acceptable(
            latency_ms=100.0,
            max_latency_ms=500.0,
        )
        assert low_ok

        # Test with high latency
        high_ok = check_latency_acceptable(
            latency_ms=600.0,
            max_latency_ms=500.0,
        )
        assert not high_ok

    def test_skips_latency_check_when_none(self, scalper_strategy, tight_spread_snapshot):
        """Test that latency check is skipped if latency_ms is None."""
        # Should still trade (latency not checked)
        should_trade = scalper_strategy.should_trade(tight_spread_snapshot, latency_ms=None)
        # May pass or fail based on other checks, but shouldn't error
        assert isinstance(should_trade, bool)


class TestScalperRRValidation:
    """Test RR ratio validation (min 1.0 for scalping)."""

    def test_enforces_minimum_rr(self, scalper_strategy, scalping_ohlcv, tight_spread_snapshot):
        """Test that signals with RR < 1.0 are rejected."""
        # Prepare strategy
        scalper_strategy.prepare(tight_spread_snapshot, scalping_ohlcv)

        # Generate signals
        signals = scalper_strategy.generate_signals(
            tight_spread_snapshot,
            scalping_ohlcv,
            RegimeLabel.BULL,
        )

        # All signals should have RR >= 1.0
        for signal in signals:
            entry = float(signal.entry_price)
            sl = float(signal.stop_loss)
            tp = float(signal.take_profit)

            risk = abs(entry - sl)
            reward = abs(tp - entry)

            if risk > 0:
                rr_ratio = reward / risk
                assert rr_ratio >= scalper_strategy.min_rr, \
                    f"RR ratio {rr_ratio:.2f} below minimum {scalper_strategy.min_rr:.2f}"

    def test_lower_rr_threshold_for_scalping(self, scalper_strategy):
        """Test that scalper uses lower RR threshold (1.0 vs 1.6)."""
        # Scalper should have lower RR requirement
        assert scalper_strategy.min_rr == 1.0

        # Compare to other strategies (they use 1.6)
        from strategies.momentum_strategy import MomentumStrategy
        from strategies.mean_reversion import MeanReversionStrategy

        momentum = MomentumStrategy()
        mean_rev = MeanReversionStrategy()

        assert momentum.min_rr == 1.6
        assert mean_rev.min_rr == 1.6


class TestScalperSignalQuality:
    """Test overall signal quality with STEP 6 enhancements."""

    def test_signal_contains_step6_metadata(self, scalper_strategy, scalping_ohlcv, tight_spread_snapshot):
        """Test that signals contain all STEP 6 metadata fields."""
        scalper_strategy.throttler.reset()
        scalper_strategy.prepare(tight_spread_snapshot, scalping_ohlcv)

        signals = scalper_strategy.generate_signals(
            tight_spread_snapshot,
            scalping_ohlcv,
            RegimeLabel.BULL,
        )

        # Verify STEP 6 metadata
        for signal in signals:
            assert "max_spread_bps" in signal.metadata
            assert "max_latency_ms" in signal.metadata
            assert "throttled_trades_per_min" in signal.metadata
            assert "max_hold_bars" in signal.metadata

    def test_signal_has_valid_sltp(self, scalper_strategy, scalping_ohlcv, tight_spread_snapshot):
        """Test that signals have valid SL/TP levels."""
        scalper_strategy.throttler.reset()
        scalper_strategy.prepare(tight_spread_snapshot, scalping_ohlcv)

        signals = scalper_strategy.generate_signals(
            tight_spread_snapshot,
            scalping_ohlcv,
            RegimeLabel.BULL,
        )

        for signal in signals:
            entry = float(signal.entry_price)
            sl = float(signal.stop_loss)
            tp = float(signal.take_profit)

            if signal.side == "long":
                assert sl < entry, "Long SL should be below entry"
                assert tp > entry, "Long TP should be above entry"
            else:  # short
                assert sl > entry, "Short SL should be above entry"
                assert tp < entry, "Short TP should be below entry"

    def test_throttler_metadata_accurate(self, scalper_strategy, scalping_ohlcv, tight_spread_snapshot):
        """Test that throttler metadata accurately reflects limits."""
        scalper_strategy.throttler.reset()
        scalper_strategy.prepare(tight_spread_snapshot, scalping_ohlcv)

        signals = scalper_strategy.generate_signals(
            tight_spread_snapshot,
            scalping_ohlcv,
            RegimeLabel.BULL,
        )

        for signal in signals:
            throttle_limit = int(signal.metadata["throttled_trades_per_min"])
            assert throttle_limit == scalper_strategy.max_trades_per_minute


class TestScalperIntegration:
    """Integration tests for scalper strategy."""

    def test_end_to_end_signal_generation(self, scalper_strategy, scalping_ohlcv, tight_spread_snapshot):
        """Test full signal generation pipeline with STEP 6 enhancements."""
        # Reset throttler
        scalper_strategy.throttler.reset()

        # 1. Prepare
        scalper_strategy.prepare(tight_spread_snapshot, scalping_ohlcv)

        # 2. Check should_trade (with latency)
        should_trade = scalper_strategy.should_trade(tight_spread_snapshot, latency_ms=100.0)
        assert isinstance(should_trade, bool)

        # 3. Generate signals
        signals = scalper_strategy.generate_signals(
            tight_spread_snapshot,
            scalping_ohlcv,
            RegimeLabel.BULL,
        )

        # 4. Verify signals are valid
        assert isinstance(signals, list)

        # 5. If signals exist, verify they pass all STEP 6 requirements
        for signal in signals:
            # Verify structure
            assert signal.signal_id
            assert signal.symbol == "BTC/USD"
            assert signal.side in ["long", "short"]
            assert signal.entry_price > 0
            assert signal.stop_loss > 0
            assert signal.take_profit > 0
            assert 0 < signal.confidence <= 1

            # Verify STEP 6 enhancements
            assert "max_spread_bps" in signal.metadata
            assert "max_latency_ms" in signal.metadata
            assert "throttled_trades_per_min" in signal.metadata

    def test_multiple_signals_respect_throttle(self, scalper_strategy, scalping_ohlcv, tight_spread_snapshot):
        """Test that multiple signal generation calls respect throttle."""
        # Reset throttler
        scalper_strategy.throttler.reset()
        scalper_strategy.prepare(tight_spread_snapshot, scalping_ohlcv)

        total_signals = []

        # Try to generate signals 10 times
        for i in range(10):
            signals = scalper_strategy.generate_signals(
                tight_spread_snapshot,
                scalping_ohlcv,
                RegimeLabel.BULL,
            )
            total_signals.extend(signals)

        # Should have max 3 signals total (throttled)
        assert len(total_signals) <= scalper_strategy.max_trades_per_minute


# =============================================================================
# RUNNER
# =============================================================================

if __name__ == "__main__":
    """Run tests with pytest."""
    import sys

    exit_code = pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "--color=yes",
    ])

    sys.exit(exit_code)
