"""
Indicator Strategy Library - Canonical TradeIntent Producers.

This module provides deterministic, explainable indicator strategies that
produce ONLY canonical TradeIntent objects (from shared_contracts).

Strategies:
- RSI Mean Reversion
- EMA Crossover
- MACD Trend
- Breakout (HH/LL)

Usage:
    from strategies.indicator import evaluate_strategy, get_evaluator
    from shared_contracts import Strategy, StrategyType

    strategy = Strategy(name="RSI", strategy_type=StrategyType.RSI_MEAN_REVERSION)
    intent = evaluate_strategy(strategy, market_snapshot)
"""

from strategies.indicator.base import (
    StrategyEvaluator,
    evaluate_strategy,
)
from strategies.indicator.registry import (
    get_evaluator,
    register_evaluator,
    list_evaluators,
)
from strategies.indicator.rsi import RSIMeanReversionEvaluator
from strategies.indicator.ema import EMACrossoverEvaluator
from strategies.indicator.macd import MACDTrendEvaluator
from strategies.indicator.breakout import BreakoutEvaluator

__all__ = [
    # Base
    "StrategyEvaluator",
    "evaluate_strategy",
    # Registry
    "get_evaluator",
    "register_evaluator",
    "list_evaluators",
    # Evaluators
    "RSIMeanReversionEvaluator",
    "EMACrossoverEvaluator",
    "MACDTrendEvaluator",
    "BreakoutEvaluator",
]
