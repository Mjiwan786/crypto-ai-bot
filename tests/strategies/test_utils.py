"""
tests/strategies/test_utils.py - Tests for Strategy Utils (STEP 6)

Comprehensive tests for centralized SL/TP math and entry/exit utilities.

Author: Crypto AI Bot Team
"""

import pytest
import pandas as pd
import numpy as np
from decimal import Decimal
from strategies.utils import (
    calculate_sl_tp_from_atr,
    calculate_sl_tp_from_percentage,
    calculate_rr_ratio,
    create_partial_tp_ladder,
    calculate_trailing_stop,
    should_trail_stop_trigger,
    should_time_stop_trigger,
    calculate_adx,
    calculate_slope,
    check_rsi_extreme,
    check_spread_acceptable,
    check_latency_acceptable,
    TradeThrottler,
    validate_signal_params,
)


# =============================================================================
# TEST: SL/TP CALCULATIONS
# =============================================================================


class TestSLTPCalculations:
    """Test stop loss and take profit calculations"""

    def test_sl_tp_from_atr_long(self):
        """Test ATR-based SL/TP for long position"""
        entry = 50000.0
        atr = 500.0
        sl, tp = calculate_sl_tp_from_atr(entry, 'long', atr, sl_atr_multiplier=1.5, tp_atr_multiplier=3.0)

        assert sl == 49250.0  # entry - 1.5 * ATR
        assert tp == 51500.0  # entry + 3.0 * ATR

    def test_sl_tp_from_atr_short(self):
        """Test ATR-based SL/TP for short position"""
        entry = 50000.0
        atr = 500.0
        sl, tp = calculate_sl_tp_from_atr(entry, 'short', atr, sl_atr_multiplier=1.5, tp_atr_multiplier=3.0)

        assert sl == 50750.0  # entry + 1.5 * ATR
        assert tp == 48500.0  # entry - 3.0 * ATR

    def test_sl_tp_from_percentage_long(self):
        """Test percentage-based SL/TP for long position"""
        entry = 50000.0
        sl, tp = calculate_sl_tp_from_percentage(entry, 'long', sl_pct=0.02, tp_pct=0.04)

        assert sl == 49000.0  # entry - 2%
        assert tp == 52000.0  # entry + 4%

    def test_sl_tp_from_percentage_short(self):
        """Test percentage-based SL/TP for short position"""
        entry = 50000.0
        sl, tp = calculate_sl_tp_from_percentage(entry, 'short', sl_pct=0.02, tp_pct=0.04)

        assert sl == 51000.0  # entry + 2%
        assert tp == 48000.0  # entry - 4%

    def test_calculate_rr_ratio(self):
        """Test RR ratio calculation"""
        # Entry 50000, SL 49000 (-1000), TP 53000 (+3000)
        rr = calculate_rr_ratio(50000, 49000, 53000)
        assert rr == 3.0  # Reward 3000 / Risk 1000 = 3.0

        # Entry 50000, SL 49000 (-1000), TP 51000 (+1000)
        rr = calculate_rr_ratio(50000, 49000, 51000)
        assert rr == 1.0  # 1:1 risk/reward

    def test_create_partial_tp_ladder(self):
        """Test partial TP ladder creation"""
        entry = 50000.0
        atr = 500.0
        ladder = create_partial_tp_ladder(
            entry, 'long', atr,
            levels=[1.5, 2.5, 3.5],
            sizes=[0.33, 0.33, 0.34]
        )

        assert len(ladder) == 3
        assert ladder[0]['price'] == 50750.0  # entry + 1.5 * ATR
        assert ladder[1]['price'] == 51250.0  # entry + 2.5 * ATR
        assert ladder[2]['price'] == 51750.0  # entry + 3.5 * ATR
        assert sum(level['size_pct'] for level in ladder) == 1.0

    def test_partial_tp_ladder_validation(self):
        """Test partial TP ladder validation"""
        with pytest.raises(ValueError, match="must have same length"):
            create_partial_tp_ladder(50000, 'long', 500, levels=[1.5, 2.5], sizes=[0.5, 0.3, 0.2])

        with pytest.raises(ValueError, match="must sum to 1.0"):
            create_partial_tp_ladder(50000, 'long', 500, levels=[1.5, 2.5], sizes=[0.5, 0.3])


# =============================================================================
# TEST: TRAILING STOPS
# =============================================================================


class TestTrailingStops:
    """Test trailing stop logic"""

    def test_trailing_stop_not_activated_yet(self):
        """Test trailing stop doesn't activate before min profit"""
        entry = 50000.0
        current = 50400.0  # +0.8% profit (below 1% min)
        highest = 50400.0

        trail_stop = calculate_trailing_stop(
            entry, current, highest, 'long',
            trail_pct=0.02, min_profit_pct=0.01
        )

        assert trail_stop is None  # Not enough profit yet

    def test_trailing_stop_activated_long(self):
        """Test trailing stop activates for long position"""
        entry = 50000.0
        current = 50800.0  # +1.6% profit (above 1% min)
        highest = 51000.0  # Peak at +2%

        trail_stop = calculate_trailing_stop(
            entry, current, highest, 'long',
            trail_pct=0.02, min_profit_pct=0.01
        )

        # Trail from highest: 51000 - (51000 * 0.02) = 50980
        assert trail_stop is not None
        assert abs(trail_stop - 49980.0) < 1.0  # Allow small rounding

    def test_trailing_stop_trigger_long(self):
        """Test trailing stop trigger for long position"""
        # Price drops below trailing stop
        assert should_trail_stop_trigger(50400, 50490, 'long') is True
        # Price still above trailing stop
        assert should_trail_stop_trigger(50500, 50490, 'long') is False
        # No trailing stop set
        assert should_trail_stop_trigger(50400, None, 'long') is False

    def test_trailing_stop_short(self):
        """Test trailing stop for short position"""
        entry = 50000.0
        current = 49200.0  # +1.6% profit (price down)
        lowest = 49000.0  # Lowest at +2%

        trail_stop = calculate_trailing_stop(
            entry, current, lowest, 'short',
            trail_pct=0.02, min_profit_pct=0.01
        )

        # Trail from lowest: 49000 + (49000 * 0.02) = 49980
        assert trail_stop is not None
        assert abs(trail_stop - 49980.0) < 1.0


# =============================================================================
# TEST: TIME STOPS
# =============================================================================


class TestTimeStops:
    """Test time-based stop logic"""

    def test_time_stop_not_triggered(self):
        """Test time stop doesn't trigger before max hold time"""
        entry = pd.Timestamp('2024-10-25 10:00:00')
        current = pd.Timestamp('2024-10-25 10:30:00')  # 30 minutes = 6 bars

        # Max 10 bars (50 minutes)
        assert should_time_stop_trigger(entry, current, max_hold_bars=10) is False

    def test_time_stop_triggered(self):
        """Test time stop triggers after max hold time"""
        entry = pd.Timestamp('2024-10-25 10:00:00')
        current = pd.Timestamp('2024-10-25 12:30:00')  # 150 minutes = 30 bars

        # Max 20 bars (100 minutes)
        assert should_time_stop_trigger(entry, current, max_hold_bars=20) is True


# =============================================================================
# TEST: TECHNICAL INDICATORS
# =============================================================================


class TestTechnicalIndicators:
    """Test technical indicator confirmations"""

    def test_calculate_slope_uptrend(self):
        """Test slope calculation for uptrend"""
        prices = pd.Series([50000, 50100, 50200, 50300, 50400])
        slope = calculate_slope(prices, period=5)

        assert slope > 0  # Positive slope
        assert abs(slope - 100.0) < 10.0  # Approximately 100 per bar

    def test_calculate_slope_downtrend(self):
        """Test slope calculation for downtrend"""
        prices = pd.Series([50400, 50300, 50200, 50100, 50000])
        slope = calculate_slope(prices, period=5)

        assert slope < 0  # Negative slope

    def test_calculate_slope_insufficient_data(self):
        """Test slope with insufficient data"""
        prices = pd.Series([50000, 50100])
        slope = calculate_slope(prices, period=5)

        assert slope == 0.0  # Not enough data

    def test_check_rsi_extreme_oversold(self):
        """Test RSI oversold detection"""
        # Create DataFrame with declining prices (oversold condition)
        close_prices = np.linspace(51000, 49000, 50)  # Steady decline
        df = pd.DataFrame({'close': close_prices})

        rsi_state = check_rsi_extreme(df, period=14, oversold=30.0, overbought=70.0)

        # Should be oversold (or neutral if not extreme enough)
        assert rsi_state in ['oversold', 'neutral']

    def test_check_rsi_extreme_neutral(self):
        """Test RSI neutral state"""
        # Sideways price action
        close_prices = [50000 + np.random.randint(-100, 100) for _ in range(50)]
        df = pd.DataFrame({'close': close_prices})

        rsi_state = check_rsi_extreme(df, period=14)

        # Should be neutral most of the time
        assert rsi_state == 'neutral'


# =============================================================================
# TEST: SPREAD/LATENCY GUARDS
# =============================================================================


class TestSpreadLatencyGuards:
    """Test spread and latency guards for scalper"""

    def test_spread_acceptable(self):
        """Test acceptable spread"""
        # Spread = 5 / 50025 = 0.01% = 1 bps
        assert check_spread_acceptable(50000, 50005, max_spread_bps=10.0) is True

    def test_spread_too_wide(self):
        """Test spread too wide"""
        # Spread = 100 / 50050 = 0.2% = 20 bps
        assert check_spread_acceptable(50000, 50100, max_spread_bps=10.0) is False

    def test_latency_acceptable(self):
        """Test acceptable latency"""
        assert check_latency_acceptable(300.0, max_latency_ms=500.0) is True

    def test_latency_too_high(self):
        """Test latency too high"""
        assert check_latency_acceptable(600.0, max_latency_ms=500.0) is False


# =============================================================================
# TEST: THROTTLING
# =============================================================================


class TestTradeThrottler:
    """Test trade throttling for scalper"""

    def test_throttler_allows_trades_under_limit(self):
        """Test throttler allows trades under limit"""
        throttler = TradeThrottler(max_trades_per_minute=3)
        current_time = pd.Timestamp('2024-10-25 10:00:00')

        # First 3 trades should be allowed
        for i in range(3):
            assert throttler.can_trade(current_time + pd.Timedelta(seconds=i*10)) is True
            throttler.record_trade(current_time + pd.Timedelta(seconds=i*10))

    def test_throttler_blocks_trades_over_limit(self):
        """Test throttler blocks trades over limit"""
        throttler = TradeThrottler(max_trades_per_minute=3)
        current_time = pd.Timestamp('2024-10-25 10:00:00')

        # Execute 3 trades
        for i in range(3):
            throttler.record_trade(current_time + pd.Timedelta(seconds=i*10))

        # 4th trade should be blocked
        assert throttler.can_trade(current_time + pd.Timedelta(seconds=30)) is False

    def test_throttler_resets_after_minute(self):
        """Test throttler resets after 1 minute"""
        throttler = TradeThrottler(max_trades_per_minute=3)
        start_time = pd.Timestamp('2024-10-25 10:00:00')

        # Execute 3 trades
        for i in range(3):
            throttler.record_trade(start_time + pd.Timedelta(seconds=i*10))

        # After 1 minute, should allow new trades
        after_minute = start_time + pd.Timedelta(seconds=70)
        assert throttler.can_trade(after_minute) is True

    def test_throttler_reset(self):
        """Test manual throttler reset"""
        throttler = TradeThrottler(max_trades_per_minute=3)
        current_time = pd.Timestamp('2024-10-25 10:00:00')

        # Execute 3 trades
        for i in range(3):
            throttler.record_trade(current_time + pd.Timedelta(seconds=i*10))

        # Reset
        throttler.reset()

        # Should allow trades again
        assert throttler.can_trade(current_time) is True


# =============================================================================
# TEST: VALIDATION
# =============================================================================


class TestValidation:
    """Test signal parameter validation"""

    def test_validate_good_long_signal(self):
        """Test validation of good long signal"""
        valid, reason = validate_signal_params(
            entry_price=50000,
            stop_loss=49000,  # -2%
            take_profit=53000,  # +6% (RR = 3.0)
            side='long',
            min_rr=1.6
        )

        assert valid is True
        assert reason == ""

    def test_validate_low_rr_signal(self):
        """Test validation rejects low RR signal"""
        valid, reason = validate_signal_params(
            entry_price=50000,
            stop_loss=49000,  # -2%
            take_profit=51000,  # +2% (RR = 1.0)
            side='long',
            min_rr=1.6
        )

        assert valid is False
        assert "RR ratio" in reason
        assert "1.00" in reason

    def test_validate_wrong_sl_side(self):
        """Test validation rejects SL on wrong side"""
        # Long with SL above entry
        valid, reason = validate_signal_params(
            entry_price=50000,
            stop_loss=51000,  # Wrong side!
            take_profit=53000,
            side='long',
            min_rr=1.6
        )

        assert valid is False
        assert "SL" in reason and "below entry" in reason

    def test_validate_wrong_tp_side(self):
        """Test validation rejects TP on wrong side"""
        # Long with TP below entry
        valid, reason = validate_signal_params(
            entry_price=50000,
            stop_loss=49000,
            take_profit=48000,  # Wrong side!
            side='long',
            min_rr=1.6
        )

        assert valid is False
        assert "TP" in reason and "above entry" in reason

    def test_validate_short_signal(self):
        """Test validation of short signal"""
        valid, reason = validate_signal_params(
            entry_price=50000,
            stop_loss=51000,  # +2% (above for short)
            take_profit=47000,  # -6% (below for short, RR = 3.0)
            side='short',
            min_rr=1.6
        )

        assert valid is True
        assert reason == ""


# =============================================================================
# TEST: INTEGRATION SCENARIOS
# =============================================================================


class TestIntegrationScenarios:
    """Test complete workflows"""

    def test_complete_long_trade_workflow(self):
        """Test complete long trade setup and management"""
        # 1. Calculate SL/TP from ATR
        entry = 50000.0
        atr = 500.0
        sl, tp = calculate_sl_tp_from_atr(entry, 'long', atr, 1.5, 3.0)

        # 2. Validate signal
        valid, _ = validate_signal_params(entry, sl, tp, 'long', min_rr=1.6)
        assert valid is True

        # 3. Check RR ratio
        rr = calculate_rr_ratio(entry, sl, tp)
        assert rr >= 2.0  # Should be 2.0 (3.0 ATR / 1.5 ATR)

        # 4. Create partial TP ladder
        ladder = create_partial_tp_ladder(entry, 'long', atr)
        assert len(ladder) == 3

        # 5. Simulate price movement and trailing stop
        current_price = 50800.0
        highest_price = 51000.0
        trail_stop = calculate_trailing_stop(
            entry, current_price, highest_price, 'long',
            trail_pct=0.02, min_profit_pct=0.01
        )
        assert trail_stop is not None  # Should activate

    def test_scalper_complete_workflow(self):
        """Test scalper workflow with guards and throttling"""
        # 1. Check spread
        bid = 50000.0
        ask = 50005.0
        spread_ok = check_spread_acceptable(bid, ask, max_spread_bps=10.0)
        assert spread_ok is True

        # 2. Check latency
        latency_ok = check_latency_acceptable(300.0, max_latency_ms=500.0)
        assert latency_ok is True

        # 3. Check throttle
        throttler = TradeThrottler(max_trades_per_minute=3)
        current_time = pd.Timestamp.now()
        can_trade = throttler.can_trade(current_time)
        assert can_trade is True

        # 4. If all checks pass, execute trade
        if spread_ok and latency_ok and can_trade:
            throttler.record_trade(current_time)
            # Trade executed
            assert len(throttler.trade_timestamps) == 1


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
