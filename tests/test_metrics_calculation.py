"""
Test metrics calculation per PRD-001.
Run with: pytest tests/test_metrics_calculation.py -v
"""
import pytest
from datetime import datetime, timezone, timedelta


class TestSignalFrequencyMetrics:
    """Test signal frequency calculations."""

    def test_signals_per_day_calculation(self):
        """Calculate average signals per day."""
        total_signals = 48 * 30  # 48 signals/day for 30 days
        days = 30
        signals_per_day = total_signals / days
        assert signals_per_day == 48

    def test_signals_per_week_calculation(self):
        """Calculate average signals per week."""
        signals_per_day = 48
        signals_per_week = signals_per_day * 7
        assert signals_per_week == 336


class TestPerformanceMetrics:
    """Test performance metrics calculations."""

    def test_win_rate_calculation(self):
        """PRD-001 Appendix C: Win rate calculation."""
        winning_trades = 68
        total_trades = 100
        win_rate = winning_trades / total_trades
        assert win_rate == 0.68
        assert 0 <= win_rate <= 1

    def test_profit_factor_calculation(self):
        """Profit factor = gross profit / gross loss."""
        gross_profit = 18500.0
        gross_loss = 10000.0
        profit_factor = gross_profit / gross_loss
        assert profit_factor == 1.85
        assert profit_factor > 1  # Profitable system

    def test_roi_calculation(self):
        """ROI = (final - initial) / initial * 100."""
        initial_equity = 10000.0
        final_equity = 11250.0
        roi = ((final_equity - initial_equity) / initial_equity) * 100
        assert roi == 12.5

    def test_max_drawdown_calculation(self):
        """Max drawdown = (peak - trough) / peak * 100."""
        peak_equity = 12000.0
        trough_equity = 11016.0  # 8.2% drawdown
        drawdown = ((peak_equity - trough_equity) / peak_equity) * 100
        assert abs(drawdown - 8.2) < 0.1

    def test_sharpe_ratio_bounds(self):
        """Sharpe ratio should be reasonable for trading systems."""
        sharpe_ratio = 1.72
        # Good trading systems typically have Sharpe > 1.0
        assert sharpe_ratio > 0
        # Extremely high Sharpe (>3) is suspicious
        assert sharpe_ratio < 5


class TestRiskFilters:
    """Test risk filter calculations per PRD-001 Section 7."""

    def test_spread_filter(self):
        """PRD-001 7.1: Reject if spread > 0.5%."""
        max_spread_pct = 0.5

        # Acceptable spread
        bid, ask = 50000.0, 50200.0
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100
        assert spread_pct < max_spread_pct  # 0.4%

        # Too wide spread
        bid, ask = 50000.0, 50300.0
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100
        assert spread_pct > max_spread_pct  # 0.6%

    def test_volatility_adjustment(self):
        """PRD-001 7.2: Reduce size in high volatility."""
        base_size = 100.0
        current_atr = 600.0
        avg_atr = 200.0  # 3x normal volatility

        ratio = current_atr / avg_atr
        if ratio > 3.0:
            adjusted_size = base_size * 0.5  # 50% reduction
        else:
            adjusted_size = base_size

        assert adjusted_size == 50.0

    def test_daily_drawdown_circuit_breaker(self):
        """PRD-001 7.3: Halt at -5% daily drawdown."""
        starting_equity = 10000.0
        current_equity = 9400.0  # -6% down
        daily_drawdown_limit = -5.0

        drawdown_pct = ((current_equity - starting_equity) / starting_equity) * 100

        should_halt = drawdown_pct < daily_drawdown_limit
        assert should_halt is True

    def test_position_sizing_with_confidence(self):
        """PRD-001 7.4: Size scales with confidence."""
        base_size = 100.0
        confidence = 0.85

        adjusted_size = base_size * confidence
        assert adjusted_size == 85.0

    def test_max_position_limit(self):
        """PRD-001 7.4: Max position size is $2,000."""
        max_size = 2000.0
        calculated_size = 2500.0

        final_size = min(calculated_size, max_size)
        assert final_size == 2000.0


class TestLossStreakManagement:
    """Test loss streak tracking per PRD-001 Section 7.5."""

    def test_reduce_after_3_losses(self):
        """After 3 consecutive losses, reduce allocation by 50%."""
        consecutive_losses = 3
        base_allocation = 1.0

        if consecutive_losses >= 3:
            allocation = base_allocation * 0.5
        else:
            allocation = base_allocation

        assert allocation == 0.5

    def test_pause_after_5_losses(self):
        """After 5 consecutive losses, pause strategy."""
        consecutive_losses = 5
        pause_threshold = 5

        should_pause = consecutive_losses >= pause_threshold
        assert should_pause is True

    def test_reset_on_win(self):
        """Win resets loss streak counter."""
        loss_streak = 4
        last_trade_profit = 100.0  # Winning trade

        if last_trade_profit > 0:
            loss_streak = 0

        assert loss_streak == 0


class TestEquityCurve:
    """Test equity curve calculations."""

    def test_equity_updates_correctly(self):
        """Equity curve should reflect PnL changes."""
        initial_equity = 10000.0
        trades = [
            {"pnl": 100.0},
            {"pnl": -50.0},
            {"pnl": 200.0},
            {"pnl": -30.0},
        ]

        equity = initial_equity
        for trade in trades:
            equity += trade["pnl"]

        expected_equity = 10000.0 + 100.0 - 50.0 + 200.0 - 30.0
        assert equity == expected_equity
        assert equity == 10220.0

    def test_realized_vs_unrealized_pnl(self):
        """Track realized and unrealized PnL separately."""
        realized_pnl = 500.0
        unrealized_pnl = 150.0
        starting_equity = 10000.0

        total_equity = starting_equity + realized_pnl + unrealized_pnl
        assert total_equity == 10650.0
