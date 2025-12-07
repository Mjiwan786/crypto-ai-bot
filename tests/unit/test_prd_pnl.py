"""
Unit tests for PRD-001 PnL Attribution and Performance Metrics

Tests:
1. PRDTradeRecord creation and validation
2. Trade record factory function
3. PerformanceAggregator calculations
4. Sharpe/Sortino ratio computation
5. Per-strategy attribution
6. Redis serialization

Run: pytest tests/unit/test_prd_pnl.py -v
"""

import math
from datetime import datetime, timezone, timedelta
from typing import List

import pytest

from agents.infrastructure.prd_pnl import (
    PRDTradeRecord,
    PRDPerformanceMetrics,
    PerformanceAggregator,
    PRDPnLPublisher,
    TradeOutcome,
    ExitReason,
    create_trade_record,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_long_win():
    """Sample winning LONG trade."""
    return create_trade_record(
        signal_id="signal-long-win",
        pair="BTC/USD",
        side="LONG",
        strategy="SCALPER",
        entry_price=50000.0,
        exit_price=50500.0,
        position_size_usd=1000.0,
        quantity=0.02,
        timestamp_open=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        exit_reason=ExitReason.TAKE_PROFIT,
    )


@pytest.fixture
def sample_long_loss():
    """Sample losing LONG trade."""
    return create_trade_record(
        signal_id="signal-long-loss",
        pair="ETH/USD",
        side="LONG",
        strategy="TREND",
        entry_price=3000.0,
        exit_price=2900.0,
        position_size_usd=600.0,
        quantity=0.2,
        timestamp_open=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
        exit_reason=ExitReason.STOP_LOSS,
        fees_usd=0.60,
    )


@pytest.fixture
def sample_short_win():
    """Sample winning SHORT trade."""
    return create_trade_record(
        signal_id="signal-short-win",
        pair="SOL/USD",
        side="SHORT",
        strategy="MEAN_REVERSION",
        entry_price=100.0,
        exit_price=95.0,
        position_size_usd=500.0,
        quantity=5.0,
        timestamp_open=(datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(),
        exit_reason=ExitReason.TAKE_PROFIT,
    )


@pytest.fixture
def aggregator():
    """Fresh performance aggregator."""
    return PerformanceAggregator(initial_equity=10000.0, mode="paper")


def generate_trades(
    count: int,
    win_ratio: float = 0.6,
    avg_win: float = 50.0,
    avg_loss: float = 30.0,
) -> List[PRDTradeRecord]:
    """Generate a list of trades with specified win ratio."""
    trades = []
    wins = int(count * win_ratio)
    losses = count - wins

    for i in range(wins):
        trades.append(create_trade_record(
            signal_id=f"win-{i}",
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER" if i % 2 == 0 else "TREND",
            entry_price=50000.0,
            exit_price=50000.0 + (avg_win / 0.02),  # Calculate price for target PnL
            position_size_usd=1000.0,
            quantity=0.02,
            timestamp_open=(datetime.now(timezone.utc) - timedelta(hours=i)).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        ))

    for i in range(losses):
        trades.append(create_trade_record(
            signal_id=f"loss-{i}",
            pair="ETH/USD",
            side="LONG",
            strategy="SCALPER" if i % 2 == 0 else "TREND",
            entry_price=3000.0,
            exit_price=3000.0 - (avg_loss / 0.2),  # Calculate price for target loss
            position_size_usd=600.0,
            quantity=0.2,
            timestamp_open=(datetime.now(timezone.utc) - timedelta(hours=wins + i)).isoformat(),
            exit_reason=ExitReason.STOP_LOSS,
        ))

    return trades


# =============================================================================
# PRDTradeRecord TESTS
# =============================================================================

class TestPRDTradeRecord:
    """Test PRDTradeRecord model."""

    def test_create_long_winning_trade(self, sample_long_win):
        """Test creating a winning LONG trade."""
        assert sample_long_win.outcome == TradeOutcome.WIN
        assert sample_long_win.side == "LONG"
        assert sample_long_win.pair == "BTC/USD"
        # 0.02 BTC * ($50500 - $50000) = $10 gross PnL
        assert sample_long_win.gross_pnl == pytest.approx(10.0, abs=0.01)
        assert sample_long_win.realized_pnl > 0

    def test_create_long_losing_trade(self, sample_long_loss):
        """Test creating a losing LONG trade with fees."""
        assert sample_long_loss.outcome == TradeOutcome.LOSS
        # 0.2 ETH * ($2900 - $3000) = -$20 gross PnL
        assert sample_long_loss.gross_pnl == pytest.approx(-20.0, abs=0.01)
        # -$20 - $0.60 fees = -$20.60 realized
        assert sample_long_loss.realized_pnl == pytest.approx(-20.60, abs=0.01)

    def test_create_short_winning_trade(self, sample_short_win):
        """Test creating a winning SHORT trade."""
        assert sample_short_win.outcome == TradeOutcome.WIN
        assert sample_short_win.side == "SHORT"
        # SHORT profit: (entry - exit) * qty = ($100 - $95) * 5 = $25
        assert sample_short_win.gross_pnl == pytest.approx(25.0, abs=0.01)

    def test_trade_id_is_uuid(self, sample_long_win):
        """Test trade_id is valid UUID format."""
        assert len(sample_long_win.trade_id) == 36  # UUID format
        assert sample_long_win.trade_id.count("-") == 4

    def test_pnl_pct_calculation(self, sample_long_win):
        """Test PnL percentage calculation."""
        # $10 PnL on $1000 position = 1%
        assert sample_long_win.pnl_pct == pytest.approx(1.0, abs=0.1)

    def test_pair_normalization(self):
        """Test pair is normalized to forward slash."""
        trade = create_trade_record(
            signal_id="test",
            pair="BTC-USD",  # Dash format
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            exit_price=50100.0,
            position_size_usd=100.0,
            quantity=0.002,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        )
        assert trade.pair == "BTC/USD"  # Normalized

    def test_to_redis_dict_all_strings(self, sample_long_win):
        """Test Redis dict has all string values."""
        redis_dict = sample_long_win.to_redis_dict()
        for key, value in redis_dict.items():
            assert isinstance(value, str), f"Key {key} has non-string value: {type(value)}"

    def test_to_redis_dict_required_fields(self, sample_long_win):
        """Test Redis dict contains required fields."""
        redis_dict = sample_long_win.to_redis_dict()
        required_fields = [
            "trade_id", "signal_id", "pair", "side", "strategy",
            "entry_price", "exit_price", "realized_pnl", "outcome"
        ]
        for field in required_fields:
            assert field in redis_dict, f"Missing required field: {field}"

    def test_breakeven_trade(self):
        """Test trade classified as breakeven."""
        trade = create_trade_record(
            signal_id="breakeven",
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            exit_price=50000.0,  # No price change
            position_size_usd=1000.0,
            quantity=0.02,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TIME_STOP,
        )
        assert trade.outcome == TradeOutcome.BREAKEVEN

    def test_slippage_reduces_pnl(self):
        """Test slippage is deducted from PnL."""
        trade = create_trade_record(
            signal_id="slippage-test",
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            exit_price=50500.0,
            position_size_usd=1000.0,
            quantity=0.02,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
            slippage_pct=0.1,  # 0.1% slippage = $1 on $1000
        )
        # Gross PnL = $10, slippage = $1, realized = $9
        assert trade.gross_pnl == pytest.approx(10.0, abs=0.01)
        assert trade.realized_pnl == pytest.approx(9.0, abs=0.01)

    def test_hold_duration_calculated(self, sample_long_win):
        """Test hold duration is calculated correctly."""
        assert sample_long_win.hold_duration_sec >= 0
        # Trade opened 5 minutes ago
        assert sample_long_win.hold_duration_sec >= 290  # Allow some tolerance

    def test_all_exit_reasons(self):
        """Test all exit reasons are valid."""
        for reason in ExitReason:
            trade = create_trade_record(
                signal_id=f"exit-{reason.value}",
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                exit_price=50100.0,
                position_size_usd=100.0,
                quantity=0.002,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=reason,
            )
            assert trade.exit_reason == reason


# =============================================================================
# PerformanceAggregator TESTS
# =============================================================================

class TestPerformanceAggregator:
    """Test PerformanceAggregator calculations."""

    def test_initial_state(self, aggregator):
        """Test aggregator initial state."""
        assert aggregator.initial_equity == 10000.0
        assert aggregator.current_equity == 10000.0
        assert aggregator.total_trades == 0
        assert aggregator.winning_trades == 0
        assert aggregator.losing_trades == 0

    def test_add_single_winning_trade(self, aggregator, sample_long_win):
        """Test adding a winning trade."""
        aggregator.add_trade(sample_long_win)

        assert aggregator.total_trades == 1
        assert aggregator.winning_trades == 1
        assert aggregator.losing_trades == 0
        assert aggregator.current_equity > 10000.0

    def test_add_single_losing_trade(self, aggregator, sample_long_loss):
        """Test adding a losing trade."""
        aggregator.add_trade(sample_long_loss)

        assert aggregator.total_trades == 1
        assert aggregator.winning_trades == 0
        assert aggregator.losing_trades == 1
        assert aggregator.current_equity < 10000.0

    def test_win_rate_calculation(self, aggregator):
        """Test win rate is calculated correctly."""
        trades = generate_trades(count=10, win_ratio=0.6)  # 60% win rate
        for t in trades:
            aggregator.add_trade(t)

        metrics = aggregator.get_metrics()
        assert metrics.win_rate_pct == pytest.approx(60.0, abs=5.0)

    def test_profit_factor_calculation(self, aggregator):
        """Test profit factor calculation."""
        # Add 3 wins of $50 each = $150 gross profit
        for i in range(3):
            aggregator.add_trade(create_trade_record(
                signal_id=f"pf-win-{i}",
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                exit_price=52500.0,  # $2500 * 0.02 = $50
                position_size_usd=1000.0,
                quantity=0.02,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT,
            ))

        # Add 2 losses of $30 each = $60 gross loss
        for i in range(2):
            aggregator.add_trade(create_trade_record(
                signal_id=f"pf-loss-{i}",
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                exit_price=48500.0,  # -$1500 * 0.02 = -$30
                position_size_usd=1000.0,
                quantity=0.02,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.STOP_LOSS,
            ))

        metrics = aggregator.get_metrics()
        # PF = 150 / 60 = 2.5
        assert metrics.profit_factor == pytest.approx(2.5, abs=0.2)

    def test_max_drawdown_tracking(self, aggregator):
        """Test max drawdown is tracked correctly."""
        # Add a winning trade (equity goes up)
        aggregator.add_trade(create_trade_record(
            signal_id="dd-win",
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            exit_price=55000.0,  # $100 profit
            position_size_usd=1000.0,
            quantity=0.02,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        ))
        peak = aggregator.current_equity  # Should be 10100

        # Add losing trades (drawdown)
        for i in range(3):
            aggregator.add_trade(create_trade_record(
                signal_id=f"dd-loss-{i}",
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                exit_price=48500.0,  # -$30 each
                position_size_usd=1000.0,
                quantity=0.02,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.STOP_LOSS,
            ))

        metrics = aggregator.get_metrics()
        # Drawdown from peak ~10100 to ~10010 (100 - 3*30 = 10) = ~0.9%
        assert metrics.max_drawdown_pct > 0
        assert metrics.max_drawdown_usd > 0

    def test_per_strategy_attribution(self, aggregator):
        """Test per-strategy performance tracking."""
        # Add SCALPER trades
        for i in range(3):
            aggregator.add_trade(create_trade_record(
                signal_id=f"scalper-{i}",
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                exit_price=50500.0,
                position_size_usd=500.0,
                quantity=0.01,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT,
            ))

        # Add TREND trades
        for i in range(2):
            aggregator.add_trade(create_trade_record(
                signal_id=f"trend-{i}",
                pair="ETH/USD",
                side="LONG",
                strategy="TREND",
                entry_price=3000.0,
                exit_price=2900.0,  # Loss
                position_size_usd=300.0,
                quantity=0.1,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.STOP_LOSS,
            ))

        metrics = aggregator.get_metrics()

        assert "SCALPER" in metrics.strategy_performance
        assert "TREND" in metrics.strategy_performance

        scalper_stats = metrics.strategy_performance["SCALPER"]
        assert scalper_stats["trades"] == 3
        assert scalper_stats["wins"] == 3
        assert scalper_stats["pnl"] > 0

        trend_stats = metrics.strategy_performance["TREND"]
        assert trend_stats["trades"] == 2
        assert trend_stats["losses"] == 2
        assert trend_stats["pnl"] < 0

    def test_roi_calculation(self, aggregator):
        """Test total ROI calculation."""
        # Add trades totaling $500 profit
        for i in range(10):
            aggregator.add_trade(create_trade_record(
                signal_id=f"roi-{i}",
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                exit_price=52500.0,  # $50 each
                position_size_usd=1000.0,
                quantity=0.02,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT,
            ))

        metrics = aggregator.get_metrics()
        # $500 profit on $10000 = 5% ROI
        assert metrics.total_roi_pct == pytest.approx(5.0, abs=0.5)
        assert metrics.total_pnl == pytest.approx(500.0, abs=5.0)

    def test_average_win_loss(self, aggregator):
        """Test average win/loss calculation."""
        # Add wins and losses
        trades = generate_trades(count=10, win_ratio=0.6, avg_win=50.0, avg_loss=30.0)
        for t in trades:
            aggregator.add_trade(t)

        metrics = aggregator.get_metrics()
        assert metrics.avg_win_usd > 0
        assert metrics.avg_loss_usd > 0

    def test_largest_win_loss(self, aggregator):
        """Test largest win/loss tracking."""
        # Add a big win
        aggregator.add_trade(create_trade_record(
            signal_id="big-win",
            pair="BTC/USD",
            side="LONG",
            strategy="TREND",
            entry_price=50000.0,
            exit_price=55000.0,  # $100 win
            position_size_usd=1000.0,
            quantity=0.02,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        ))

        # Add a big loss
        aggregator.add_trade(create_trade_record(
            signal_id="big-loss",
            pair="BTC/USD",
            side="LONG",
            strategy="TREND",
            entry_price=50000.0,
            exit_price=46000.0,  # $80 loss
            position_size_usd=1000.0,
            quantity=0.02,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.STOP_LOSS,
        ))

        metrics = aggregator.get_metrics()
        assert metrics.largest_win_usd == pytest.approx(100.0, abs=5.0)
        assert metrics.largest_loss_usd == pytest.approx(80.0, abs=5.0)

    def test_reset_clears_state(self, aggregator, sample_long_win):
        """Test reset clears all state."""
        aggregator.add_trade(sample_long_win)
        aggregator.reset()

        assert aggregator.total_trades == 0
        assert aggregator.winning_trades == 0
        assert aggregator.current_equity == 10000.0

    def test_reset_with_new_initial_equity(self, aggregator, sample_long_win):
        """Test reset with new initial equity."""
        aggregator.add_trade(sample_long_win)
        aggregator.reset(initial_equity=20000.0)

        assert aggregator.initial_equity == 20000.0
        assert aggregator.current_equity == 20000.0


# =============================================================================
# Sharpe/Sortino TESTS
# =============================================================================

class TestRiskMetrics:
    """Test Sharpe and Sortino ratio calculations."""

    def test_sharpe_with_insufficient_data(self, aggregator):
        """Test Sharpe returns 0 with insufficient data."""
        metrics = aggregator.get_metrics()
        assert metrics.sharpe_ratio == 0.0

    def test_sharpe_with_consistent_returns(self):
        """Test Sharpe calculation with consistent positive returns."""
        agg = PerformanceAggregator(initial_equity=10000.0)

        # Simulate daily returns by directly adding to daily_returns
        for _ in range(30):
            agg.daily_returns.append(0.002)  # 0.2% daily return

        sharpe = agg._calculate_sharpe()
        # With 0.2% consistent daily return and low volatility, Sharpe should be high
        assert sharpe > 0

    def test_sharpe_with_volatile_returns(self):
        """Test Sharpe calculation with volatile returns."""
        agg = PerformanceAggregator(initial_equity=10000.0)

        # Simulate volatile returns
        import random
        random.seed(42)
        for _ in range(30):
            agg.daily_returns.append(random.uniform(-0.05, 0.05))

        sharpe = agg._calculate_sharpe()
        # Volatile returns should have lower Sharpe
        assert isinstance(sharpe, float)

    def test_sortino_with_no_negative_returns(self):
        """Test Sortino returns None with no negative returns."""
        agg = PerformanceAggregator(initial_equity=10000.0)

        for _ in range(10):
            agg.daily_returns.append(0.01)  # All positive

        sortino = agg._calculate_sortino()
        assert sortino is None

    def test_sortino_with_mixed_returns(self):
        """Test Sortino calculation with mixed returns."""
        agg = PerformanceAggregator(initial_equity=10000.0)

        # Mixed returns with some negative
        for i in range(20):
            if i % 3 == 0:
                agg.daily_returns.append(-0.01)
            else:
                agg.daily_returns.append(0.015)

        sortino = agg._calculate_sortino()
        assert sortino is not None
        assert isinstance(sortino, float)


# =============================================================================
# PRDPerformanceMetrics TESTS
# =============================================================================

class TestPRDPerformanceMetrics:
    """Test PRDPerformanceMetrics model."""

    def test_metrics_to_redis_dict(self, aggregator, sample_long_win):
        """Test metrics can be converted to Redis dict."""
        aggregator.add_trade(sample_long_win)
        metrics = aggregator.get_metrics()

        redis_dict = metrics.to_redis_dict()
        assert all(isinstance(v, str) for v in redis_dict.values())

    def test_metrics_contains_required_fields(self, aggregator, sample_long_win):
        """Test metrics contains all PRD-required fields."""
        aggregator.add_trade(sample_long_win)
        metrics = aggregator.get_metrics()

        required_fields = [
            "total_roi_pct", "win_rate_pct", "profit_factor",
            "max_drawdown_pct", "sharpe_ratio", "strategy_performance"
        ]

        data = metrics.model_dump()
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    def test_metrics_timestamp_is_iso8601(self, aggregator):
        """Test timestamp is ISO8601 format."""
        metrics = aggregator.get_metrics()

        # Should parse without error
        dt = datetime.fromisoformat(metrics.timestamp.replace('Z', '+00:00'))
        assert dt is not None


# =============================================================================
# PRDPnLPublisher TESTS
# =============================================================================

class TestPRDPnLPublisher:
    """Test PRDPnLPublisher configuration."""

    def test_publisher_initialization(self):
        """Test publisher initializes with defaults."""
        publisher = PRDPnLPublisher()

        assert publisher.mode == "paper"
        assert publisher._connected is False
        assert publisher._publish_count == 0

    def test_publisher_mode_override(self):
        """Test publisher mode can be overridden."""
        publisher = PRDPnLPublisher(mode="live")
        assert publisher.mode == "live"


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_position_size(self):
        """Test handling of edge case with minimal position."""
        trade = create_trade_record(
            signal_id="tiny",
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            exit_price=50100.0,
            position_size_usd=1.0,  # Minimum
            quantity=0.00002,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        )
        assert trade.pnl_pct > 0

    def test_very_large_pnl(self):
        """Test handling of large PnL values."""
        trade = create_trade_record(
            signal_id="whale",
            pair="BTC/USD",
            side="LONG",
            strategy="BREAKOUT",
            entry_price=50000.0,
            exit_price=100000.0,  # 2x
            position_size_usd=100000.0,
            quantity=2.0,
            timestamp_open=datetime.now(timezone.utc).isoformat(),
            exit_reason=ExitReason.TAKE_PROFIT,
        )
        assert trade.gross_pnl == pytest.approx(100000.0, abs=1.0)

    def test_all_strategies_tracked(self, aggregator):
        """Test all 4 strategies are tracked separately."""
        strategies = ["SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT"]

        for strategy in strategies:
            aggregator.add_trade(create_trade_record(
                signal_id=f"strat-{strategy}",
                pair="BTC/USD",
                side="LONG",
                strategy=strategy,
                entry_price=50000.0,
                exit_price=50100.0,
                position_size_usd=100.0,
                quantity=0.002,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT,
            ))

        metrics = aggregator.get_metrics()
        for strategy in strategies:
            assert strategy in metrics.strategy_performance

    def test_no_division_by_zero_profit_factor(self, aggregator):
        """Test profit factor with no losses doesn't cause division by zero."""
        # Only winning trades
        for i in range(5):
            aggregator.add_trade(create_trade_record(
                signal_id=f"all-wins-{i}",
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                exit_price=50100.0,
                position_size_usd=100.0,
                quantity=0.002,
                timestamp_open=datetime.now(timezone.utc).isoformat(),
                exit_reason=ExitReason.TAKE_PROFIT,
            ))

        metrics = aggregator.get_metrics()
        # Should be capped at 999.99
        assert metrics.profit_factor == 999.99

    def test_empty_aggregator_metrics(self, aggregator):
        """Test metrics with no trades."""
        metrics = aggregator.get_metrics()

        assert metrics.total_trades == 0
        assert metrics.win_rate_pct == 0.0
        assert metrics.profit_factor == 0.0
        assert metrics.total_roi_pct == 0.0


# =============================================================================
# SELF-CHECK: Run all tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
