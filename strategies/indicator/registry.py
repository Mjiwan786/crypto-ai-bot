"""
Strategy Evaluator Registry.

Maps StrategyType to StrategyEvaluator implementations.
Supports registration of custom evaluators.
"""

from typing import Type
import logging

from shared_contracts import StrategyType

from strategies.indicator.base import StrategyEvaluator
from strategies.indicator.rsi import RSIMeanReversionEvaluator
from strategies.indicator.ema import EMACrossoverEvaluator
from strategies.indicator.macd import MACDTrendEvaluator
from strategies.indicator.breakout import BreakoutEvaluator

logger = logging.getLogger(__name__)

# Global registry of evaluators
_EVALUATOR_REGISTRY: dict[StrategyType, StrategyEvaluator] = {}

# Singleton instances (evaluators are stateless, can be shared)
_RSI_EVALUATOR = RSIMeanReversionEvaluator()
_EMA_EVALUATOR = EMACrossoverEvaluator()
_MACD_EVALUATOR = MACDTrendEvaluator()
_BREAKOUT_EVALUATOR = BreakoutEvaluator()


def _init_registry() -> None:
    """Initialize the default evaluator registry."""
    global _EVALUATOR_REGISTRY

    _EVALUATOR_REGISTRY = {
        StrategyType.RSI_MEAN_REVERSION: _RSI_EVALUATOR,
        StrategyType.EMA_CROSSOVER: _EMA_EVALUATOR,
        StrategyType.MACD_TREND: _MACD_EVALUATOR,
        StrategyType.BREAKOUT_HH_LL: _BREAKOUT_EVALUATOR,
    }

    logger.debug(f"Initialized evaluator registry with {len(_EVALUATOR_REGISTRY)} evaluators")


def get_evaluator(strategy_type: StrategyType | str) -> StrategyEvaluator | None:
    """
    Get the evaluator for a strategy type.

    Args:
        strategy_type: StrategyType enum or string value

    Returns:
        StrategyEvaluator instance or None if not found
    """
    if not _EVALUATOR_REGISTRY:
        _init_registry()

    # Handle string input
    if isinstance(strategy_type, str):
        try:
            strategy_type = StrategyType(strategy_type)
        except ValueError:
            logger.warning(f"Unknown strategy type: {strategy_type}")
            return None

    return _EVALUATOR_REGISTRY.get(strategy_type)


def register_evaluator(
    strategy_type: StrategyType,
    evaluator: StrategyEvaluator,
    overwrite: bool = False,
) -> bool:
    """
    Register a custom evaluator for a strategy type.

    Args:
        strategy_type: Strategy type to register for
        evaluator: Evaluator instance
        overwrite: Whether to overwrite existing registration

    Returns:
        True if registered, False if already exists and overwrite=False
    """
    if not _EVALUATOR_REGISTRY:
        _init_registry()

    if strategy_type in _EVALUATOR_REGISTRY and not overwrite:
        logger.warning(f"Evaluator already registered for {strategy_type}")
        return False

    _EVALUATOR_REGISTRY[strategy_type] = evaluator
    logger.info(f"Registered evaluator for {strategy_type}: {type(evaluator).__name__}")
    return True


def list_evaluators() -> list[str]:
    """
    List all registered strategy types.

    Returns:
        List of strategy type values that have evaluators
    """
    if not _EVALUATOR_REGISTRY:
        _init_registry()

    return [st.value for st in _EVALUATOR_REGISTRY.keys()]


def get_evaluator_class(strategy_type: StrategyType) -> Type[StrategyEvaluator] | None:
    """
    Get the evaluator class for a strategy type.

    Useful for introspection or creating custom instances.

    Args:
        strategy_type: Strategy type

    Returns:
        Evaluator class or None
    """
    evaluator = get_evaluator(strategy_type)
    if evaluator:
        return type(evaluator)
    return None
