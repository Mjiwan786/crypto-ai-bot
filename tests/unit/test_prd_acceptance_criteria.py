"""
Unit tests for PRD-001 Section 6.3 Acceptance Criteria

Tests coverage:
- Sharpe ratio ≥ 1.5 enforcement
- Max drawdown ≤ -15% enforcement
- Win rate ≥ 45% enforcement
- Profit factor ≥ 1.3 enforcement
- Minimum 200 trades enforcement
- Deployment blocking on failure
- Known good/bad backtest results

Author: Crypto AI Bot Team
"""

import pytest
from backtesting.prd_acceptance_criteria import (
    PRDAcceptanceCriteria,
    AcceptanceCriteriaResult,
    AcceptanceCriteriaError,
    get_acceptance_criteria,
    MIN_SHARPE_RATIO,
    MAX_DRAWDOWN_THRESHOLD,
    MIN_WIN_RATE,
    MIN_PROFIT_FACTOR,
    MIN_TRADES
)
from backtesting.prd_metrics_calculator import BacktestMetrics


class TestPRDAcceptanceCriteriaInit:
    """Test PRDAcceptanceCriteria initialization."""

    def test_init_default(self, caplog):
        """Test initialization with default parameters."""
        import logging
        with caplog.at_level(logging.INFO):
            criteria = PRDAcceptanceCriteria()

        assert criteria.min_sharpe_ratio == MIN_SHARPE_RATIO
        assert criteria.max_drawdown_threshold == MAX_DRAWDOWN_THRESHOLD
        assert criteria.min_win_rate == MIN_WIN_RATE
        assert criteria.min_profit_factor == MIN_PROFIT_FACTOR
        assert criteria.min_trades == MIN_TRADES
        assert "PRDAcceptanceCriteria initialized" in caplog.text

    def test_init_custom_thresholds(self):
        """Test initialization with custom thresholds."""
        criteria = PRDAcceptanceCriteria(
            min_sharpe_ratio=2.0,
            max_drawdown_threshold=-10.0,
            min_win_rate=50.0,
            min_profit_factor=1.5,
            min_trades=300
        )

        assert criteria.min_sharpe_ratio == 2.0
        assert criteria.max_drawdown_threshold == -10.0
        assert criteria.min_win_rate == 50.0
        assert criteria.min_profit_factor == 1.5
        assert criteria.min_trades == 300


class TestGoodBacktestResults:
    """
    PRD-001 Section 6.3 Item 7: Test with known good backtest results.

    These tests verify that backtests passing all criteria are accepted.
    """

    def test_good_backtest_passes_all_criteria(self, caplog):
        """Test that good backtest passes all acceptance criteria."""
        import logging
        criteria = PRDAcceptanceCriteria()

        # Good backtest: all criteria exceeded
        metrics = BacktestMetrics(
            total_return_pct=25.0,
            sharpe_ratio=2.5,           # > 1.5 ✓
            max_drawdown_pct=-8.0,       # > -15% ✓
            win_rate=55.0,               # > 45% ✓
            profit_factor=2.0,           # > 1.3 ✓
            avg_trade_duration_hours=4.0,
            total_trades=300,            # > 200 ✓
            winning_trades=165,
            losing_trades=135,
            gross_profit=10000.0,
            gross_loss=5000.0,
            final_equity=12500.0,
            initial_capital=10000.0
        )

        with caplog.at_level(logging.INFO):
            result = criteria.check_acceptance(metrics)

        assert result.passed is True
        assert len(result.failures) == 0
        assert result.metrics["sharpe_ratio"] is True
        assert result.metrics["max_drawdown"] is True
        assert result.metrics["win_rate"] is True
        assert result.metrics["profit_factor"] is True
        assert result.metrics["min_trades"] is True
        assert "[ACCEPTANCE PASSED]" in caplog.text

    def test_good_backtest_exact_thresholds(self):
        """Test backtest at exact threshold values (should pass)."""
        criteria = PRDAcceptanceCriteria()

        # Exactly at thresholds
        metrics = BacktestMetrics(
            total_return_pct=10.0,
            sharpe_ratio=1.5,            # = 1.5 ✓
            max_drawdown_pct=-15.0,      # = -15% ✓
            win_rate=45.0,               # = 45% ✓
            profit_factor=1.3,           # = 1.3 ✓
            avg_trade_duration_hours=3.0,
            total_trades=200,            # = 200 ✓
            winning_trades=90,
            losing_trades=110,
            gross_profit=5000.0,
            gross_loss=3846.0,
            final_equity=11000.0,
            initial_capital=10000.0
        )

        result = criteria.check_acceptance(metrics)

        assert result.passed is True
        assert len(result.failures) == 0


class TestBadBacktestResults:
    """
    PRD-001 Section 6.3 Item 7: Test with known bad backtest results.

    These tests verify that backtests failing criteria are rejected.
    """

    def test_bad_sharpe_ratio_fails(self, caplog):
        """Test that low Sharpe ratio fails acceptance."""
        import logging
        criteria = PRDAcceptanceCriteria()

        # Bad: Sharpe ratio too low
        metrics = BacktestMetrics(
            total_return_pct=5.0,
            sharpe_ratio=1.0,            # < 1.5 ✗
            max_drawdown_pct=-8.0,
            win_rate=55.0,
            profit_factor=2.0,
            avg_trade_duration_hours=4.0,
            total_trades=300,
            winning_trades=165,
            losing_trades=135,
            gross_profit=5000.0,
            gross_loss=2500.0,
            final_equity=10500.0,
            initial_capital=10000.0
        )

        with caplog.at_level(logging.ERROR):
            result = criteria.check_acceptance(metrics)

        assert result.passed is False
        assert len(result.failures) == 1
        assert result.metrics["sharpe_ratio"] is False
        assert "Sharpe ratio" in result.failures[0]
        assert "[ACCEPTANCE FAILED]" in caplog.text

    def test_bad_max_drawdown_fails(self):
        """Test that excessive drawdown fails acceptance."""
        criteria = PRDAcceptanceCriteria()

        # Bad: Max drawdown too large
        metrics = BacktestMetrics(
            total_return_pct=10.0,
            sharpe_ratio=2.0,
            max_drawdown_pct=-20.0,      # < -15% ✗
            win_rate=55.0,
            profit_factor=2.0,
            avg_trade_duration_hours=4.0,
            total_trades=300,
            winning_trades=165,
            losing_trades=135,
            gross_profit=6000.0,
            gross_loss=3000.0,
            final_equity=11000.0,
            initial_capital=10000.0
        )

        result = criteria.check_acceptance(metrics)

        assert result.passed is False
        assert len(result.failures) == 1
        assert result.metrics["max_drawdown"] is False
        assert "Max drawdown" in result.failures[0]

    def test_bad_win_rate_fails(self):
        """Test that low win rate fails acceptance."""
        criteria = PRDAcceptanceCriteria()

        # Bad: Win rate too low
        metrics = BacktestMetrics(
            total_return_pct=8.0,
            sharpe_ratio=2.0,
            max_drawdown_pct=-8.0,
            win_rate=40.0,               # < 45% ✗
            profit_factor=2.0,
            avg_trade_duration_hours=4.0,
            total_trades=300,
            winning_trades=120,
            losing_trades=180,
            gross_profit=8000.0,
            gross_loss=4000.0,
            final_equity=10800.0,
            initial_capital=10000.0
        )

        result = criteria.check_acceptance(metrics)

        assert result.passed is False
        assert len(result.failures) == 1
        assert result.metrics["win_rate"] is False
        assert "Win rate" in result.failures[0]

    def test_bad_profit_factor_fails(self):
        """Test that low profit factor fails acceptance."""
        criteria = PRDAcceptanceCriteria()

        # Bad: Profit factor too low
        metrics = BacktestMetrics(
            total_return_pct=5.0,
            sharpe_ratio=2.0,
            max_drawdown_pct=-8.0,
            win_rate=55.0,
            profit_factor=1.1,           # < 1.3 ✗
            avg_trade_duration_hours=4.0,
            total_trades=300,
            winning_trades=165,
            losing_trades=135,
            gross_profit=5500.0,
            gross_loss=5000.0,
            final_equity=10500.0,
            initial_capital=10000.0
        )

        result = criteria.check_acceptance(metrics)

        assert result.passed is False
        assert len(result.failures) == 1
        assert result.metrics["profit_factor"] is False
        assert "Profit factor" in result.failures[0]

    def test_bad_insufficient_trades_fails(self):
        """Test that insufficient trades fails acceptance."""
        criteria = PRDAcceptanceCriteria()

        # Bad: Too few trades
        metrics = BacktestMetrics(
            total_return_pct=15.0,
            sharpe_ratio=2.5,
            max_drawdown_pct=-8.0,
            win_rate=60.0,
            profit_factor=2.0,
            avg_trade_duration_hours=4.0,
            total_trades=150,            # < 200 ✗
            winning_trades=90,
            losing_trades=60,
            gross_profit=6000.0,
            gross_loss=3000.0,
            final_equity=11500.0,
            initial_capital=10000.0
        )

        result = criteria.check_acceptance(metrics)

        assert result.passed is False
        assert len(result.failures) == 1
        assert result.metrics["min_trades"] is False
        assert "Total trades" in result.failures[0]


class TestMultipleFailures:
    """Test backtests failing multiple criteria."""

    def test_multiple_failures(self):
        """Test backtest failing multiple criteria."""
        criteria = PRDAcceptanceCriteria()

        # Bad: Multiple failures
        metrics = BacktestMetrics(
            total_return_pct=2.0,
            sharpe_ratio=0.8,            # < 1.5 ✗
            max_drawdown_pct=-18.0,      # < -15% ✗
            win_rate=40.0,               # < 45% ✗
            profit_factor=1.0,           # < 1.3 ✗
            avg_trade_duration_hours=4.0,
            total_trades=150,            # < 200 ✗
            winning_trades=60,
            losing_trades=90,
            gross_profit=3000.0,
            gross_loss=3000.0,
            final_equity=10200.0,
            initial_capital=10000.0
        )

        result = criteria.check_acceptance(metrics)

        assert result.passed is False
        assert len(result.failures) == 5  # All 5 criteria failed
        assert result.metrics["sharpe_ratio"] is False
        assert result.metrics["max_drawdown"] is False
        assert result.metrics["win_rate"] is False
        assert result.metrics["profit_factor"] is False
        assert result.metrics["min_trades"] is False


class TestDeploymentBlocking:
    """
    PRD-001 Section 6.3 Item 6: Test deployment blocking.

    Verify that check_and_raise() blocks deployment on failure.
    """

    def test_check_and_raise_passes_good_backtest(self):
        """Test that check_and_raise() doesn't raise on good backtest."""
        criteria = PRDAcceptanceCriteria()

        # Good backtest
        metrics = BacktestMetrics(
            total_return_pct=20.0,
            sharpe_ratio=2.0,
            max_drawdown_pct=-10.0,
            win_rate=50.0,
            profit_factor=1.8,
            avg_trade_duration_hours=4.0,
            total_trades=250,
            winning_trades=125,
            losing_trades=125,
            gross_profit=9000.0,
            gross_loss=5000.0,
            final_equity=12000.0,
            initial_capital=10000.0
        )

        # Should not raise
        criteria.check_and_raise(metrics)

    def test_check_and_raise_blocks_bad_backtest(self):
        """Test that check_and_raise() raises AcceptanceCriteriaError on failure."""
        criteria = PRDAcceptanceCriteria()

        # Bad backtest
        metrics = BacktestMetrics(
            total_return_pct=3.0,
            sharpe_ratio=0.5,            # FAIL
            max_drawdown_pct=-10.0,
            win_rate=50.0,
            profit_factor=1.8,
            avg_trade_duration_hours=4.0,
            total_trades=250,
            winning_trades=125,
            losing_trades=125,
            gross_profit=5150.0,
            gross_loss=2850.0,
            final_equity=10300.0,
            initial_capital=10000.0
        )

        # Should raise AcceptanceCriteriaError
        with pytest.raises(AcceptanceCriteriaError) as exc_info:
            criteria.check_and_raise(metrics)

        assert "deployment BLOCKED" in str(exc_info.value)
        assert "Sharpe ratio" in str(exc_info.value)

    def test_check_and_raise_error_message_details(self):
        """Test that AcceptanceCriteriaError contains detailed failure info."""
        criteria = PRDAcceptanceCriteria()

        # Multiple failures
        metrics = BacktestMetrics(
            total_return_pct=1.0,
            sharpe_ratio=0.5,            # FAIL
            max_drawdown_pct=-20.0,      # FAIL
            win_rate=30.0,               # FAIL
            profit_factor=0.8,           # FAIL
            avg_trade_duration_hours=4.0,
            total_trades=100,            # FAIL
            winning_trades=30,
            losing_trades=70,
            gross_profit=2000.0,
            gross_loss=2500.0,
            final_equity=10100.0,
            initial_capital=10000.0
        )

        with pytest.raises(AcceptanceCriteriaError) as exc_info:
            criteria.check_and_raise(metrics)

        error_msg = str(exc_info.value)
        # Should mention all failures
        assert "Sharpe ratio" in error_msg
        assert "Max drawdown" in error_msg
        assert "Win rate" in error_msg
        assert "Profit factor" in error_msg
        assert "Total trades" in error_msg


class TestAcceptanceCriteriaResult:
    """Test AcceptanceCriteriaResult class."""

    def test_result_repr_passed(self):
        """Test AcceptanceCriteriaResult.__repr__() for passed result."""
        result = AcceptanceCriteriaResult(
            passed=True,
            failures=[],
            metrics={
                "sharpe_ratio": True,
                "max_drawdown": True,
                "win_rate": True,
                "profit_factor": True,
                "min_trades": True
            }
        )

        repr_str = repr(result)

        assert "PASSED" in repr_str
        assert "0 failures" in repr_str

    def test_result_repr_failed(self):
        """Test AcceptanceCriteriaResult.__repr__() for failed result."""
        result = AcceptanceCriteriaResult(
            passed=False,
            failures=["Sharpe ratio 1.0 < 1.5 (FAIL)", "Win rate 40% < 45% (FAIL)"],
            metrics={
                "sharpe_ratio": False,
                "max_drawdown": True,
                "win_rate": False,
                "profit_factor": True,
                "min_trades": True
            }
        )

        repr_str = repr(result)

        assert "FAILED" in repr_str
        assert "2 failures" in repr_str


class TestGetCriteriaSummary:
    """Test get_criteria_summary() method."""

    def test_get_criteria_summary(self):
        """Test that get_criteria_summary() returns all thresholds."""
        criteria = PRDAcceptanceCriteria()

        summary = criteria.get_criteria_summary()

        assert isinstance(summary, dict)
        assert summary["min_sharpe_ratio"] == MIN_SHARPE_RATIO
        assert summary["max_drawdown_threshold"] == MAX_DRAWDOWN_THRESHOLD
        assert summary["min_win_rate"] == MIN_WIN_RATE
        assert summary["min_profit_factor"] == MIN_PROFIT_FACTOR
        assert summary["min_trades"] == MIN_TRADES


class TestSingletonInstance:
    """Test singleton instance."""

    def test_get_acceptance_criteria_singleton(self):
        """Test get_acceptance_criteria() returns singleton."""
        criteria1 = get_acceptance_criteria()
        criteria2 = get_acceptance_criteria()

        assert criteria1 is criteria2


class TestEdgeCases:
    """Test edge cases."""

    def test_profit_factor_infinite_passes(self):
        """Test that infinite profit factor (no losses) passes."""
        criteria = PRDAcceptanceCriteria()

        # Infinite profit factor (no losses)
        metrics = BacktestMetrics(
            total_return_pct=30.0,
            sharpe_ratio=3.0,
            max_drawdown_pct=0.0,
            win_rate=100.0,
            profit_factor=float('inf'),  # No losses
            avg_trade_duration_hours=4.0,
            total_trades=200,
            winning_trades=200,
            losing_trades=0,
            gross_profit=13000.0,
            gross_loss=0.0,
            final_equity=13000.0,
            initial_capital=10000.0
        )

        result = criteria.check_acceptance(metrics)

        assert result.passed is True
        assert result.metrics["profit_factor"] is True

    def test_zero_drawdown_passes(self):
        """Test that zero drawdown (all gains) passes."""
        criteria = PRDAcceptanceCriteria()

        metrics = BacktestMetrics(
            total_return_pct=15.0,
            sharpe_ratio=2.5,
            max_drawdown_pct=0.0,        # No drawdown
            win_rate=60.0,
            profit_factor=2.5,
            avg_trade_duration_hours=4.0,
            total_trades=250,
            winning_trades=150,
            losing_trades=100,
            gross_profit=7500.0,
            gross_loss=3000.0,
            final_equity=11500.0,
            initial_capital=10000.0
        )

        result = criteria.check_acceptance(metrics)

        assert result.passed is True
        assert result.metrics["max_drawdown"] is True
