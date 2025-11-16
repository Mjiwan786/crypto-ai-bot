"""
backtests - Deterministic Backtesting Harness

Production-grade backtesting system with:
- Historical OHLCV replay
- Same strategies/risk code as live
- Comprehensive metrics (ROI, PF, Sharpe, DD)
- Deterministic execution with fixed seed
- Monthly aggregation and reporting
- Per-pair JSON export for TradingView-style UI

Exports:
- BacktestRunner: Main backtesting engine
- BacktestConfig: Configuration
- BacktestResult: Result with metrics and equity curve
- BacktestMetrics: Metrics calculations
- MetricsCalculator: Metrics computation
- Trade: Trade record
- EquityPoint: Equity curve point
- BacktestFile: Per-pair export schema (for UI)
- export_backtest_to_json: Export backtest to JSON file
- run_and_export_backtest: Run backtest and export in one step

Example (basic backtest):
    >>> from backtests import BacktestRunner, BacktestConfig
    >>> config = BacktestConfig(initial_capital=Decimal("10000"))
    >>> runner = BacktestRunner(config)
    >>> result = runner.run(ohlcv_data, pairs=["BTC/USD"], lookback_days=720)
    >>> result.save_report("out/report.json")
    >>> result.save_equity_curve("out/equity.csv")

Example (export for UI):
    >>> from backtests.exporter import run_and_export_backtest
    >>> run_and_export_backtest(
    ...     symbol="BTC/USD",
    ...     timeframe="1h",
    ...     lookback_days=90,
    ...     output_dir="data/backtests"
    ... )

CLI Usage:
    # Export backtest for BTC/USD
    python -m backtests.exporter --symbol BTC/USD --timeframe 1h

    # Export multiple pairs
    python -m backtests.exporter --symbol BTC/USD,ETH/USD,SOL/USD --timeframe 1h

Author: Crypto AI Bot Team
"""

from backtests.runner import BacktestConfig, BacktestResult, BacktestRunner
from backtests.metrics import (
    BacktestMetrics,
    EquityPoint,
    MetricsCalculator,
    Trade,
)
from backtests.schema import (
    BacktestFile,
    normalize_symbol,
    get_backtest_file_path,
)
from backtests.exporter import (
    export_backtest_to_json,
    run_and_export_backtest,
    convert_backtest_result,
)

__all__ = [
    # Core backtesting
    "BacktestRunner",
    "BacktestConfig",
    "BacktestResult",
    "BacktestMetrics",
    "MetricsCalculator",
    "Trade",
    "EquityPoint",
    # Export schema and functions
    "BacktestFile",
    "normalize_symbol",
    "get_backtest_file_path",
    "export_backtest_to_json",
    "run_and_export_backtest",
    "convert_backtest_result",
]
