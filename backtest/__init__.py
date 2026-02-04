"""
Canonical Backtest Module - Pipeline-based backtesting.

This module provides a backtest runner that uses the same pipeline as paper/live:
    Strategy → TradeIntent → ExecutionDecision → Trade

All components use canonical contracts from shared_contracts.

Usage:
    from backtest import BacktestRunner, BacktestConfig, BacktestResult

    config = BacktestConfig(
        strategy=my_strategy,
        pair="BTC/USD",
        starting_equity=10000.0,
    )
    result = BacktestRunner(config).run(ohlcv_data)
"""

from backtest.models import (
    BacktestConfig,
    BacktestResult,
    BacktestSummary,
    BacktestAssumptions,
    EquityPoint,
)
from backtest.runner import BacktestRunner
from backtest.simulator import ExecutionSimulator
from backtest.risk_evaluator import RiskEvaluator, RiskLimits

__all__ = [
    # Config & Results
    "BacktestConfig",
    "BacktestResult",
    "BacktestSummary",
    "BacktestAssumptions",
    "EquityPoint",
    # Runner
    "BacktestRunner",
    # Components
    "ExecutionSimulator",
    "RiskEvaluator",
    "RiskLimits",
]
