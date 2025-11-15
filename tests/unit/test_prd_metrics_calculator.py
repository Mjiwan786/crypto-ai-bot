"""
Unit tests for PRD-001 Section 6.2 Backtest Metrics Calculator

Tests coverage:
- Total return % calculation
- Sharpe ratio calculation: (mean_return - risk_free_rate) / std_deviation
- Max drawdown calculation: max peak-to-trough decline
- Win rate calculation: winning_trades / total_trades
- Profit factor calculation: gross_profit / gross_loss
- Average trade duration calculation
- Total trades counting
- Metrics saving to JSON (out/backtests/{strategy}_{date}.json)

Author: Crypto AI Bot Team
"""

import pytest
import json
from pathlib import Path
from datetime import datetime
from backtesting.prd_metrics_calculator import (
    PRDMetricsCalculator,
    BacktestMetrics,
    get_metrics_calculator,
    RISK_FREE_RATE_ANNUAL
)


class TestPRDMetricsCalculatorInit:
    """Test PRDMetricsCalculator initialization."""

    def test_init_default(self, caplog):
        """Test initialization with default parameters."""
        import logging
        with caplog.at_level(logging.INFO):
            calculator = PRDMetricsCalculator()

        assert calculator.risk_free_rate == RISK_FREE_RATE_ANNUAL
        assert "PRDMetricsCalculator initialized" in caplog.text

    def test_init_custom_risk_free_rate(self):
        """Test initialization with custom risk-free rate."""
        calculator = PRDMetricsCalculator(risk_free_rate=0.03)
        assert calculator.risk_free_rate == 0.03


class TestTotalReturnCalculation:
    """Test total return % calculation."""

    def test_total_return_positive(self):
        """Test total return calculation with profit."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 100, "duration_hours": 1},
            {"pnl": 200, "duration_hours": 2}
        ]
        equity_curve = [10000, 10100, 10300]  # +3% total
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert abs(metrics.total_return_pct - 3.0) < 0.01
        assert metrics.final_equity == 10300
        assert metrics.initial_capital == 10000

    def test_total_return_negative(self):
        """Test total return calculation with loss."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": -100, "duration_hours": 1},
            {"pnl": -50, "duration_hours": 2}
        ]
        equity_curve = [10000, 9900, 9850]  # -1.5% total
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert abs(metrics.total_return_pct - (-1.5)) < 0.01

    def test_total_return_zero(self):
        """Test total return calculation with no change."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 100, "duration_hours": 1},
            {"pnl": -100, "duration_hours": 2}
        ]
        equity_curve = [10000, 10100, 10000]  # 0% total
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert abs(metrics.total_return_pct) < 0.01


class TestSharpeRatioCalculation:
    """Test Sharpe ratio calculation."""

    def test_sharpe_ratio_positive_returns(self):
        """Test Sharpe ratio with positive returns."""
        calculator = PRDMetricsCalculator()

        # Consistent positive returns
        trades = [{"pnl": 100, "duration_hours": 1} for _ in range(10)]
        equity_curve = [10000 + (i * 100) for i in range(11)]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        # Should have positive Sharpe ratio
        assert metrics.sharpe_ratio > 0

    def test_sharpe_ratio_volatile_returns(self):
        """Test Sharpe ratio with volatile returns."""
        calculator = PRDMetricsCalculator()

        # Volatile returns (up/down pattern)
        trades = []
        equity_curve = [10000]
        for i in range(10):
            pnl = 500 if i % 2 == 0 else -300
            trades.append({"pnl": pnl, "duration_hours": 1})
            equity_curve.append(equity_curve[-1] + pnl)

        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        # Volatile returns should lower Sharpe ratio
        assert isinstance(metrics.sharpe_ratio, float)

    def test_sharpe_ratio_no_variance(self):
        """Test Sharpe ratio with no variance (edge case)."""
        calculator = PRDMetricsCalculator()

        # All same returns
        trades = [{"pnl": 0, "duration_hours": 1}]
        equity_curve = [10000, 10000]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        # No variance should result in 0 Sharpe
        assert metrics.sharpe_ratio == 0.0


class TestMaxDrawdownCalculation:
    """Test max drawdown calculation."""

    def test_max_drawdown_with_decline(self):
        """Test max drawdown with actual decline."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 1000, "duration_hours": 1},
            {"pnl": -2000, "duration_hours": 2},
            {"pnl": 500, "duration_hours": 1}
        ]
        # Peak at 11000, trough at 9000 = -18.18% drawdown
        equity_curve = [10000, 11000, 9000, 9500]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        # Max drawdown should be negative
        assert metrics.max_drawdown_pct < 0
        assert abs(metrics.max_drawdown_pct - (-18.18)) < 0.1

    def test_max_drawdown_no_decline(self):
        """Test max drawdown with no decline (only gains)."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 100, "duration_hours": 1},
            {"pnl": 200, "duration_hours": 2}
        ]
        equity_curve = [10000, 10100, 10300]  # No drawdown
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        # Max drawdown should be 0 (or very close)
        assert abs(metrics.max_drawdown_pct) < 0.01

    def test_max_drawdown_full_loss(self):
        """Test max drawdown with significant loss."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": -5000, "duration_hours": 1}
        ]
        equity_curve = [10000, 5000]  # -50% drawdown
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert abs(metrics.max_drawdown_pct - (-50.0)) < 0.1


class TestWinRateCalculation:
    """Test win rate calculation."""

    def test_win_rate_all_winners(self):
        """Test win rate with all winning trades."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 100, "duration_hours": 1},
            {"pnl": 200, "duration_hours": 2},
            {"pnl": 50, "duration_hours": 1}
        ]
        equity_curve = [10000, 10100, 10300, 10350]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert metrics.win_rate == 100.0
        assert metrics.winning_trades == 3
        assert metrics.losing_trades == 0

    def test_win_rate_all_losers(self):
        """Test win rate with all losing trades."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": -100, "duration_hours": 1},
            {"pnl": -200, "duration_hours": 2}
        ]
        equity_curve = [10000, 9900, 9700]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert metrics.win_rate == 0.0
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 2

    def test_win_rate_mixed(self):
        """Test win rate with mixed results."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 100, "duration_hours": 1},  # Win
            {"pnl": -50, "duration_hours": 2},  # Loss
            {"pnl": 200, "duration_hours": 1},  # Win
            {"pnl": -30, "duration_hours": 1}   # Loss
        ]
        equity_curve = [10000, 10100, 10050, 10250, 10220]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert metrics.win_rate == 50.0  # 2 wins out of 4 trades
        assert metrics.winning_trades == 2
        assert metrics.losing_trades == 2


class TestProfitFactorCalculation:
    """Test profit factor calculation."""

    def test_profit_factor_positive(self):
        """Test profit factor with wins and losses."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 300, "duration_hours": 1},  # Gross profit: 300
            {"pnl": 200, "duration_hours": 2},  # Gross profit: 200
            {"pnl": -100, "duration_hours": 1}  # Gross loss: 100
        ]
        # Profit factor = 500 / 100 = 5.0
        equity_curve = [10000, 10300, 10500, 10400]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert abs(metrics.profit_factor - 5.0) < 0.01
        assert metrics.gross_profit == 500
        assert metrics.gross_loss == 100

    def test_profit_factor_no_losses(self):
        """Test profit factor with no losses (infinite)."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 100, "duration_hours": 1},
            {"pnl": 200, "duration_hours": 2}
        ]
        equity_curve = [10000, 10100, 10300]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        # Profit factor should be infinite
        assert metrics.profit_factor == float('inf')
        assert metrics.gross_profit == 300
        assert metrics.gross_loss == 0

    def test_profit_factor_breakeven(self):
        """Test profit factor at breakeven."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 100, "duration_hours": 1},
            {"pnl": -100, "duration_hours": 2}
        ]
        equity_curve = [10000, 10100, 10000]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert abs(metrics.profit_factor - 1.0) < 0.01


class TestAverageTradeDurationCalculation:
    """Test average trade duration calculation."""

    def test_avg_trade_duration(self):
        """Test average trade duration calculation."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 100, "duration_hours": 2},
            {"pnl": 200, "duration_hours": 4},
            {"pnl": 50, "duration_hours": 3}
        ]
        # Average: (2 + 4 + 3) / 3 = 3.0 hours
        equity_curve = [10000, 10100, 10300, 10350]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert abs(metrics.avg_trade_duration_hours - 3.0) < 0.01

    def test_avg_trade_duration_missing(self):
        """Test average trade duration when some trades missing duration."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 100, "duration_hours": 2},
            {"pnl": 200},  # Missing duration
            {"pnl": 50, "duration_hours": 4}
        ]
        equity_curve = [10000, 10100, 10300, 10350]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        # Should average only trades with duration: (2 + 4) / 2 = 3.0
        assert abs(metrics.avg_trade_duration_hours - 3.0) < 0.01


class TestTotalTradesCount:
    """Test total trades counting."""

    def test_total_trades_count(self):
        """Test total trades counting."""
        calculator = PRDMetricsCalculator()

        trades = [
            {"pnl": 100, "duration_hours": 1},
            {"pnl": 200, "duration_hours": 2},
            {"pnl": -50, "duration_hours": 1},
            {"pnl": 150, "duration_hours": 3}
        ]
        equity_curve = [10000, 10100, 10300, 10250, 10400]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert metrics.total_trades == 4

    def test_total_trades_zero(self):
        """Test total trades with no trades."""
        calculator = PRDMetricsCalculator()

        trades = []
        equity_curve = [10000]
        initial_capital = 10000

        metrics = calculator.calculate_metrics(trades, equity_curve, initial_capital)

        assert metrics.total_trades == 0
        assert metrics.total_return_pct == 0.0
        assert metrics.win_rate == 0.0


class TestSaveMetrics:
    """Test metrics saving to JSON."""

    def test_save_metrics_creates_file(self, tmp_path):
        """Test that save_metrics creates JSON file."""
        calculator = PRDMetricsCalculator()

        # Create sample metrics
        metrics = BacktestMetrics(
            total_return_pct=10.5,
            sharpe_ratio=2.3,
            max_drawdown_pct=-8.2,
            win_rate=55.0,
            profit_factor=1.8,
            avg_trade_duration_hours=4.5,
            total_trades=100,
            winning_trades=55,
            losing_trades=45,
            gross_profit=5000.0,
            gross_loss=2500.0,
            final_equity=11050.0,
            initial_capital=10000.0
        )

        # Save to tmp directory
        filepath = calculator.save_metrics(
            metrics=metrics,
            strategy="test_strategy",
            output_dir=tmp_path
        )

        # Verify file exists
        assert filepath.exists()
        assert filepath.suffix == ".json"
        assert "test_strategy" in filepath.name

    def test_save_metrics_correct_content(self, tmp_path):
        """Test that saved metrics have correct content."""
        calculator = PRDMetricsCalculator()

        metrics = BacktestMetrics(
            total_return_pct=10.5,
            sharpe_ratio=2.3,
            max_drawdown_pct=-8.2,
            win_rate=55.0,
            profit_factor=1.8,
            avg_trade_duration_hours=4.5,
            total_trades=100,
            winning_trades=55,
            losing_trades=45,
            gross_profit=5000.0,
            gross_loss=2500.0,
            final_equity=11050.0,
            initial_capital=10000.0
        )

        filepath = calculator.save_metrics(metrics, "scalper", tmp_path)

        # Load and verify content
        with open(filepath, 'r') as f:
            data = json.load(f)

        assert data["strategy"] == "scalper"
        assert "timestamp" in data
        assert "metrics" in data

        metrics_data = data["metrics"]
        assert metrics_data["total_return_pct"] == 10.5
        assert metrics_data["sharpe_ratio"] == 2.3
        assert metrics_data["max_drawdown_pct"] == -8.2
        assert metrics_data["win_rate"] == 55.0
        assert metrics_data["profit_factor"] == 1.8
        assert metrics_data["total_trades"] == 100

    def test_save_metrics_filename_format(self, tmp_path):
        """Test that filename follows PRD format: {strategy}_{date}.json"""
        calculator = PRDMetricsCalculator()

        metrics = BacktestMetrics(
            total_return_pct=5.0,
            sharpe_ratio=1.5,
            max_drawdown_pct=-5.0,
            win_rate=50.0,
            profit_factor=1.3,
            avg_trade_duration_hours=3.0,
            total_trades=50,
            winning_trades=25,
            losing_trades=25,
            gross_profit=1000.0,
            gross_loss=750.0,
            final_equity=10500.0,
            initial_capital=10000.0
        )

        filepath = calculator.save_metrics(metrics, "momentum", tmp_path)

        # Verify filename format
        assert filepath.name.startswith("momentum_")
        assert filepath.name.endswith(".json")


class TestLoadMetrics:
    """Test metrics loading from JSON."""

    def test_load_metrics(self, tmp_path):
        """Test loading metrics from JSON file."""
        calculator = PRDMetricsCalculator()

        # Create and save metrics
        metrics = BacktestMetrics(
            total_return_pct=12.5,
            sharpe_ratio=2.1,
            max_drawdown_pct=-10.0,
            win_rate=60.0,
            profit_factor=2.0,
            avg_trade_duration_hours=5.0,
            total_trades=80,
            winning_trades=48,
            losing_trades=32,
            gross_profit=6000.0,
            gross_loss=3000.0,
            final_equity=11250.0,
            initial_capital=10000.0
        )

        filepath = calculator.save_metrics(metrics, "breakout", tmp_path)

        # Load metrics
        loaded_data = calculator.load_metrics(filepath)

        assert loaded_data["strategy"] == "breakout"
        assert loaded_data["metrics"]["total_return_pct"] == 12.5
        assert loaded_data["metrics"]["sharpe_ratio"] == 2.1


class TestBacktestMetricsClass:
    """Test BacktestMetrics class."""

    def test_to_dict(self):
        """Test BacktestMetrics.to_dict() method."""
        metrics = BacktestMetrics(
            total_return_pct=15.5,
            sharpe_ratio=2.5,
            max_drawdown_pct=-12.0,
            win_rate=58.0,
            profit_factor=1.9,
            avg_trade_duration_hours=6.5,
            total_trades=120,
            winning_trades=70,
            losing_trades=50,
            gross_profit=7000.0,
            gross_loss=3500.0,
            final_equity=11550.0,
            initial_capital=10000.0
        )

        data = metrics.to_dict()

        assert isinstance(data, dict)
        assert data["total_return_pct"] == 15.5
        assert data["sharpe_ratio"] == 2.5
        assert data["total_trades"] == 120

    def test_repr(self):
        """Test BacktestMetrics.__repr__() method."""
        metrics = BacktestMetrics(
            total_return_pct=10.0,
            sharpe_ratio=2.0,
            max_drawdown_pct=-8.0,
            win_rate=55.0,
            profit_factor=1.8,
            avg_trade_duration_hours=4.0,
            total_trades=100,
            winning_trades=55,
            losing_trades=45,
            gross_profit=5000.0,
            gross_loss=2500.0,
            final_equity=11000.0,
            initial_capital=10000.0
        )

        repr_str = repr(metrics)

        assert "BacktestMetrics" in repr_str
        assert "return=10.00%" in repr_str
        assert "sharpe=2.00" in repr_str
        assert "trades=100" in repr_str


class TestSingletonInstance:
    """Test singleton instance."""

    def test_get_metrics_calculator_singleton(self):
        """Test get_metrics_calculator() returns singleton."""
        calculator1 = get_metrics_calculator()
        calculator2 = get_metrics_calculator()

        assert calculator1 is calculator2
