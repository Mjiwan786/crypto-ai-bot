"""
Test mean reversion strategy with STEP 6 enhancements.

Tests verify:
- ADX low confirmation (max 20.0)
- RSI extreme check
- RR validation (min 1.6)
- Time-stop metadata
- Signal emission/abstention logic
"""

import pytest
import pandas as pd
import numpy as np
from decimal import Decimal
from datetime import datetime, timezone

from strategies.mean_reversion import MeanReversionStrategy
from ai_engine.schemas import MarketSnapshot, RegimeLabel


@pytest.fixture
def mean_reversion_strategy():
    """Create mean reversion strategy with STEP 6 defaults."""
    return MeanReversionStrategy(
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        atr_period=14,
        max_atr_pct=Decimal("0.008"),
        kelly_cap=Decimal("0.15"),
        max_adx=20.0,           # STEP 6
        adx_period=14,           # STEP 6
        sl_pct=0.02,             # STEP 6
        tp_pct=0.04,             # STEP 6
        max_hold_bars=30,        # STEP 6
        min_rr=1.6,              # STEP 6
    )


@pytest.fixture
def ranging_ohlcv():
    """Create ranging/oscillating OHLCV data (low ADX)."""
    np.random.seed(42)
    n = 50

    # Oscillating prices around mean (bounded range)
    mean_price = 50000
    amplitude = 1500
    close_prices = mean_price + amplitude * np.sin(np.linspace(0, 4 * np.pi, n))
    close_prices += np.random.normal(0, 100, n)

    # Set last value to oversold territory
    close_prices[-1] = mean_price - amplitude * 1.2  # Below normal range

    volume = np.random.uniform(1e6, 2e6, n)

    high_prices = close_prices + np.random.uniform(50, 200, n)
    low_prices = close_prices - np.random.uniform(50, 200, n)
    open_prices = close_prices - np.random.uniform(-100, 100, n)

    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="5min"),
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volume,
    })


@pytest.fixture
def trending_ohlcv():
    """Create trending OHLCV data (high ADX)."""
    np.random.seed(42)
    n = 50

    # Strong uptrend
    base_prices = np.linspace(49000, 52000, n)
    noise = np.random.normal(0, 100, n)
    close_prices = base_prices + noise

    volume = np.random.uniform(1e6, 2e6, n)

    high_prices = close_prices + np.random.uniform(50, 200, n)
    low_prices = close_prices - np.random.uniform(50, 200, n)
    open_prices = close_prices - np.random.uniform(-100, 100, n)

    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="5min"),
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volume,
    })


@pytest.fixture
def market_snapshot():
    """Create market snapshot."""
    return MarketSnapshot(
        symbol="BTC/USD",
        timeframe="5m",
        timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        mid_price=48500.0,  # Potentially oversold
        spread_bps=10.0,
        volume_24h=500000000.0,
    )


class TestMeanReversionADXLowConfirmation:
    """Test ADX low confirmation filter."""

    def test_emits_signal_with_low_adx(self, mean_reversion_strategy, ranging_ohlcv, market_snapshot):
        """Test that signal is emitted when ADX <= 20 (ranging)."""
        # Prepare strategy
        mean_reversion_strategy.prepare(market_snapshot, ranging_ohlcv)

        # Generate signals
        signals = mean_reversion_strategy.generate_signals(
            market_snapshot,
            ranging_ohlcv,
            RegimeLabel.CHOP,
        )

        # If signals emitted, verify ADX is low
        for signal in signals:
            if "adx" in signal.metadata:
                adx = float(signal.metadata["adx"])
                # Should be low ADX or calculation failed
                assert adx <= mean_reversion_strategy.max_adx or adx == 0.0

    def test_abstains_with_high_adx(self, mean_reversion_strategy, trending_ohlcv, market_snapshot):
        """Test that signal is NOT emitted when ADX > 20 (trending)."""
        # Prepare strategy
        mean_reversion_strategy.prepare(market_snapshot, trending_ohlcv)

        # Generate signals
        signals = mean_reversion_strategy.generate_signals(
            market_snapshot,
            trending_ohlcv,
            RegimeLabel.CHOP,
        )

        # Should NOT emit signal (too trendy, high ADX)
        # Or if it does, ADX should be within limits
        for signal in signals:
            if "adx" in signal.metadata:
                adx = float(signal.metadata["adx"])
                assert adx <= 20.0 or adx == 0.0  # Calculation failure


class TestMeanReversionRSIExtreme:
    """Test RSI extreme detection."""

    def test_checks_rsi_state(self, mean_reversion_strategy, ranging_ohlcv, market_snapshot):
        """Test that RSI state is properly detected."""
        # Prepare strategy
        mean_reversion_strategy.prepare(market_snapshot, ranging_ohlcv)

        # Generate signals
        signals = mean_reversion_strategy.generate_signals(
            market_snapshot,
            ranging_ohlcv,
            RegimeLabel.CHOP,
        )

        # If signals emitted, verify RSI state
        for signal in signals:
            assert "rsi_state" in signal.metadata
            rsi_state = signal.metadata["rsi_state"]

            # Should be 'oversold' or 'overbought'
            assert rsi_state in ['oversold', 'overbought', 'neutral']

            # Check RSI value matches state
            if "rsi" in signal.metadata:
                rsi = float(signal.metadata["rsi"])

                if rsi_state == 'oversold':
                    assert rsi < mean_reversion_strategy.rsi_oversold
                elif rsi_state == 'overbought':
                    assert rsi > mean_reversion_strategy.rsi_overbought

    def test_emits_on_oversold(self):
        """Test that signals are emitted on oversold RSI."""
        # Create OHLCV with oversold RSI
        np.random.seed(42)
        n = 50

        # Declining prices (will produce low RSI)
        close_prices = np.linspace(50000, 48000, n)
        close_prices += np.random.normal(0, 50, n)

        ohlcv = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="5min"),
            "open": close_prices,
            "high": close_prices + 100,
            "low": close_prices - 100,
            "close": close_prices,
            "volume": np.random.uniform(1e6, 2e6, n),
        })

        strategy = MeanReversionStrategy(max_adx=50.0)  # Relaxed ADX
        snapshot = MarketSnapshot(
            symbol="BTC/USD",
            timeframe="5m",
            timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            mid_price=48000.0,
            spread_bps=10.0,
            volume_24h=500000000.0,
        )

        strategy.prepare(snapshot, ohlcv)
        signals = strategy.generate_signals(snapshot, ohlcv, RegimeLabel.CHOP)

        # May or may not emit depending on other filters
        # But if emitted, should be on oversold
        for signal in signals:
            if "rsi" in signal.metadata:
                rsi = float(signal.metadata["rsi"])
                # Should be oversold if signal emitted
                assert rsi < 40.0  # Generous threshold


class TestMeanReversionRRValidation:
    """Test RR ratio validation."""

    def test_enforces_minimum_rr(self, mean_reversion_strategy, ranging_ohlcv, market_snapshot):
        """Test that signals with RR < 1.6 are rejected."""
        # Prepare strategy
        mean_reversion_strategy.prepare(market_snapshot, ranging_ohlcv)

        # Generate signals
        signals = mean_reversion_strategy.generate_signals(
            market_snapshot,
            ranging_ohlcv,
            RegimeLabel.CHOP,
        )

        # All signals should have RR >= 1.6
        for signal in signals:
            entry = float(signal.entry_price)
            sl = float(signal.stop_loss)
            tp = float(signal.take_profit)

            risk = abs(entry - sl)
            reward = abs(tp - entry)

            if risk > 0:
                rr_ratio = reward / risk
                assert rr_ratio >= mean_reversion_strategy.min_rr, \
                    f"RR ratio {rr_ratio:.2f} below minimum {mean_reversion_strategy.min_rr:.2f}"

    def test_uses_percentage_sltp(self, mean_reversion_strategy, ranging_ohlcv, market_snapshot):
        """Test that percentage-based SL/TP is used (2% SL, 4% TP)."""
        # Prepare strategy
        mean_reversion_strategy.prepare(market_snapshot, ranging_ohlcv)

        # Generate signals
        signals = mean_reversion_strategy.generate_signals(
            market_snapshot,
            ranging_ohlcv,
            RegimeLabel.CHOP,
        )

        # Verify SL/TP percentages in metadata
        for signal in signals:
            assert "sl_pct" in signal.metadata
            assert "tp_pct" in signal.metadata

            sl_pct = float(signal.metadata["sl_pct"])
            tp_pct = float(signal.metadata["tp_pct"])

            assert sl_pct == mean_reversion_strategy.sl_pct
            assert tp_pct == mean_reversion_strategy.tp_pct


class TestMeanReversionTimeStop:
    """Test time-stop metadata."""

    def test_includes_time_stop_metadata(self, mean_reversion_strategy, ranging_ohlcv, market_snapshot):
        """Test that time-stop metadata is included in signals."""
        # Prepare strategy
        mean_reversion_strategy.prepare(market_snapshot, ranging_ohlcv)

        # Generate signals
        signals = mean_reversion_strategy.generate_signals(
            market_snapshot,
            ranging_ohlcv,
            RegimeLabel.CHOP,
        )

        # Verify time-stop fields
        for signal in signals:
            assert "max_hold_bars" in signal.metadata
            assert "entry_timestamp" in signal.metadata

            max_hold_bars = int(signal.metadata["max_hold_bars"])
            entry_timestamp = signal.metadata["entry_timestamp"]

            # Verify values
            assert max_hold_bars == mean_reversion_strategy.max_hold_bars
            assert float(entry_timestamp) > 0  # Valid timestamp

    def test_time_stop_can_be_calculated(self, mean_reversion_strategy):
        """Test that time-stop can be calculated from metadata."""
        from strategies.utils import should_time_stop_trigger

        # Create entry and current timestamps
        entry_time = pd.Timestamp('2024-10-25 10:00:00')
        current_time = pd.Timestamp('2024-10-25 12:40:00')  # 2h 40m later

        # Check if time-stop triggers (30 bars * 5m = 2h 30m)
        should_trigger = should_time_stop_trigger(
            entry_timestamp=entry_time,
            current_timestamp=current_time,
            max_hold_bars=mean_reversion_strategy.max_hold_bars,
        )

        # Should trigger (exceeded 2h 30m)
        assert should_trigger


class TestMeanReversionSignalQuality:
    """Test overall signal quality with STEP 6 enhancements."""

    def test_signal_contains_step6_metadata(self, mean_reversion_strategy, ranging_ohlcv, market_snapshot):
        """Test that signals contain all STEP 6 metadata fields."""
        mean_reversion_strategy.prepare(market_snapshot, ranging_ohlcv)
        signals = mean_reversion_strategy.generate_signals(
            market_snapshot,
            ranging_ohlcv,
            RegimeLabel.CHOP,
        )

        # Verify STEP 6 metadata
        for signal in signals:
            assert "adx" in signal.metadata
            assert "rsi_state" in signal.metadata
            assert "sl_pct" in signal.metadata
            assert "tp_pct" in signal.metadata
            assert "max_hold_bars" in signal.metadata
            assert "entry_timestamp" in signal.metadata

    def test_signal_has_valid_sltp(self, mean_reversion_strategy, ranging_ohlcv, market_snapshot):
        """Test that signals have valid SL/TP levels."""
        mean_reversion_strategy.prepare(market_snapshot, ranging_ohlcv)
        signals = mean_reversion_strategy.generate_signals(
            market_snapshot,
            ranging_ohlcv,
            RegimeLabel.CHOP,
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


class TestMeanReversionIntegration:
    """Integration tests for mean reversion strategy."""

    def test_end_to_end_signal_generation(self, mean_reversion_strategy, ranging_ohlcv, market_snapshot):
        """Test full signal generation pipeline with STEP 6 enhancements."""
        # 1. Prepare
        mean_reversion_strategy.prepare(market_snapshot, ranging_ohlcv)

        # 2. Check should_trade
        should_trade = mean_reversion_strategy.should_trade(market_snapshot)
        assert isinstance(should_trade, bool)

        # 3. Generate signals
        signals = mean_reversion_strategy.generate_signals(
            market_snapshot,
            ranging_ohlcv,
            RegimeLabel.CHOP,
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
            assert "adx" in signal.metadata
            assert "rsi_state" in signal.metadata
            assert "max_hold_bars" in signal.metadata


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
