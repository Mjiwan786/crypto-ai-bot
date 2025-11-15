"""
backtests - Deterministic Backtesting Harness

Production-grade backtesting system with:
- Historical OHLCV replay
- Same strategies/risk code as live
- Comprehensive metrics (ROI, PF, Sharpe, DD)
- Deterministic execution with fixed seed
- Monthly aggregation and reporting

Exports:
- BacktestRunner: Main backtesting engine
- BacktestConfig: Configuration
- BacktestResult: Result with metrics and equity curve
- BacktestMetrics: Metrics calculations
- MetricsCalculator: Metrics computation
- Trade: Trade record
- EquityPoint: Equity curve point

Example:
    >>> from backtests import BacktestRunner, BacktestConfig
    >>> config = BacktestConfig(initial_capital=Decimal("10000"))
    >>> runner = BacktestRunner(config)
    >>> result = runner.run(ohlcv_data, pairs=["BTC/USD"], lookback_days=720)
    >>> result.save_report("out/report.json")
    >>> result.save_equity_curve("out/equity.csv")

Author: Crypto AI Bot Team
"""

from backtests.runner import BacktestConfig, BacktestResult, BacktestRunner
from backtests.metrics import (
    BacktestMetrics,
    EquityPoint,
    MetricsCalculator,
    Trade,
)

__all__ = [
    "BacktestRunner",
    "BacktestConfig",
    "BacktestResult",
    "BacktestMetrics",
    "MetricsCalculator",
    "Trade",
    "EquityPoint",
]
