"""AI Predicted Signals — Strategy Library.

All 8 trading strategies for consensus-gate evaluation.
Existing legacy strategy files (breakout.py, momentum.py, etc.) are preserved
for backward compatibility with test_all_strategies.py and regime_based_router.py.
"""
from strategies.base_strategy import BaseStrategy, StrategyResult
from strategies.rsi_strategy import RSIStrategy, AdaptiveRSIStrategy
from strategies.macd_strategy import MACDStrategy
from strategies.ema_cross_strategy import EMACrossStrategy
from strategies.mean_reversion_strategy import MeanReversionStrategy
from strategies.trend_following_strategy import TrendFollowingStrategy, compute_adx
from strategies.momentum_strategy import MomentumStrategy
from strategies.breakout_strategy import BreakoutStrategy

ALL_STRATEGIES = [
    RSIStrategy(),
    MACDStrategy(),
    EMACrossStrategy(),
    MeanReversionStrategy(),
    TrendFollowingStrategy(),
    MomentumStrategy(),
    BreakoutStrategy(),
    AdaptiveRSIStrategy(),
]

FAMILY_MAP = {
    "rsi": "momentum",
    "macd": "momentum",
    "momentum": "momentum",
    "ema_cross": "trend",
    "trend_following": "trend",
    "mean_reversion": "structure",
    "breakout": "structure",
    "rsi_divergence": "momentum",
}

__all__ = [
    "BaseStrategy",
    "StrategyResult",
    "RSIStrategy",
    "AdaptiveRSIStrategy",
    "MACDStrategy",
    "EMACrossStrategy",
    "MeanReversionStrategy",
    "TrendFollowingStrategy",
    "MomentumStrategy",
    "BreakoutStrategy",
    "ALL_STRATEGIES",
    "FAMILY_MAP",
    "compute_adx",
]
