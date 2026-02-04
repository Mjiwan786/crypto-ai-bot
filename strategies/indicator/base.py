"""
Base interface for indicator strategy evaluators.

All evaluators implement the same interface:
    evaluate(strategy, snapshot) -> TradeIntent | None

This ensures:
- Determinism: same inputs -> same outputs
- Explainability: every TradeIntent has reasons[] and indicator_inputs
- No side effects: no orders, no execution, no exchange calls
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any
import logging

from shared_contracts import Strategy, TradeIntent, MarketSnapshot

logger = logging.getLogger(__name__)


class StrategyEvaluator(ABC):
    """
    Abstract base class for indicator strategy evaluators.

    Each evaluator:
    - Takes a Strategy config and MarketSnapshot
    - Returns TradeIntent if conditions are met, None otherwise
    - Must be deterministic (same inputs -> same outputs)
    - Must provide full explainability (reasons, indicator_inputs)
    """

    @abstractmethod
    def evaluate(
        self,
        strategy: Strategy,
        snapshot: MarketSnapshot,
    ) -> TradeIntent | None:
        """
        Evaluate the strategy against current market conditions.

        Args:
            strategy: Strategy configuration with parameters
            snapshot: Current market state with indicators

        Returns:
            TradeIntent if signal conditions are met, None otherwise

        Note:
            - Must be deterministic
            - Must populate reasons[] and indicator_inputs
            - Must NOT make any external calls or side effects
        """
        ...

    def validate_params(self, strategy: Strategy) -> tuple[bool, str]:
        """
        Validate strategy parameters are within safe bounds.

        Args:
            strategy: Strategy to validate

        Returns:
            (is_valid, error_message) tuple
        """
        return True, ""

    def _calculate_confidence(
        self,
        primary_value: float,
        threshold: float,
        max_deviation: float = 20.0,
    ) -> float:
        """
        Calculate deterministic confidence based on distance from threshold.

        Confidence increases as value moves further from threshold,
        capped at max_deviation distance.

        Args:
            primary_value: The indicator value (e.g., RSI)
            threshold: The trigger threshold (e.g., 30 for oversold)
            max_deviation: Maximum meaningful deviation from threshold

        Returns:
            Confidence value between 0.5 and 0.95
        """
        distance = abs(primary_value - threshold)
        normalized = min(distance / max_deviation, 1.0)
        # Map to 0.5 - 0.95 range (minimum 0.5 for triggered signals)
        return 0.5 + (normalized * 0.45)

    def _calculate_sl_tp(
        self,
        entry: Decimal,
        side: str,
        atr: float | None,
        sl_pct: float,
        tp_pct: float,
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate stop-loss and take-profit prices.

        Uses ATR if available, otherwise falls back to percentage.

        Args:
            entry: Entry price
            side: 'long' or 'short'
            atr: Average True Range (optional)
            sl_pct: Stop-loss percentage (fallback)
            tp_pct: Take-profit percentage (fallback)

        Returns:
            (stop_loss, take_profit) tuple
        """
        entry_float = float(entry)

        if atr and atr > 0:
            # ATR-based: SL = 1.5 ATR, TP = 3.0 ATR
            sl_distance = atr * 1.5
            tp_distance = atr * 3.0
        else:
            # Percentage-based
            sl_distance = entry_float * (sl_pct / 100)
            tp_distance = entry_float * (tp_pct / 100)

        if side == "long":
            stop_loss = Decimal(str(entry_float - sl_distance))
            take_profit = Decimal(str(entry_float + tp_distance))
        else:
            stop_loss = Decimal(str(entry_float + sl_distance))
            take_profit = Decimal(str(entry_float - tp_distance))

        return stop_loss, take_profit


def evaluate_strategy(
    strategy: Strategy,
    snapshot: MarketSnapshot,
) -> TradeIntent | None:
    """
    Convenience function to evaluate any strategy.

    Looks up the appropriate evaluator from the registry and runs it.

    Args:
        strategy: Strategy configuration
        snapshot: Current market state

    Returns:
        TradeIntent if signal generated, None otherwise
    """
    from strategies.indicator.registry import get_evaluator

    evaluator = get_evaluator(strategy.strategy_type)
    if evaluator is None:
        logger.warning(f"No evaluator registered for {strategy.strategy_type}")
        return None

    # Validate parameters
    is_valid, error = evaluator.validate_params(strategy)
    if not is_valid:
        logger.warning(f"Invalid params for {strategy.name}: {error}")
        return None

    return evaluator.evaluate(strategy, snapshot)
