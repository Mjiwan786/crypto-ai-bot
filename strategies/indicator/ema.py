"""
EMA Crossover Strategy Evaluator.

Generates TradeIntent when fast EMA crosses slow EMA.

Default parameters (not curve-fit):
- fast_ema_period: 12 (short-term)
- slow_ema_period: 26 (medium-term)
- confirmation_bars: 1 (require N bars of crossover confirmation)
"""

from decimal import Decimal
from typing import Any
import logging

from shared_contracts import Strategy, TradeIntent, TradeSide, IntentReason, MarketSnapshot

from strategies.indicator.base import StrategyEvaluator
from strategies.indicator.indicators import calculate_ema, detect_crossover

logger = logging.getLogger(__name__)


# Parameter defaults and bounds
DEFAULT_PARAMS = {
    "fast_ema_period": 12,
    "slow_ema_period": 26,
    "confirmation_bars": 1,
    "sl_pct": 2.0,
    "tp_pct": 4.0,
    "position_size_usd": 100.0,
}

PARAM_BOUNDS = {
    "fast_ema_period": (3, 50),
    "slow_ema_period": (10, 200),
    "confirmation_bars": (0, 5),
    "sl_pct": (0.5, 10.0),
    "tp_pct": (1.0, 20.0),
    "position_size_usd": (10.0, 10000.0),
}


class EMACrossoverEvaluator(StrategyEvaluator):
    """
    EMA Crossover Strategy.

    Logic:
    - BUY when fast EMA crosses above slow EMA
    - SELL when fast EMA crosses below slow EMA

    Confidence is based on:
    - Crossover strength (distance between EMAs after cross)
    - Trend alignment (EMAs sloping in signal direction)
    """

    def validate_params(self, strategy: Strategy) -> tuple[bool, str]:
        """Validate EMA crossover parameters."""
        params = {**DEFAULT_PARAMS, **strategy.parameters}

        for key, (min_val, max_val) in PARAM_BOUNDS.items():
            if key in params:
                val = params[key]
                if not (min_val <= val <= max_val):
                    return False, f"{key}={val} out of bounds [{min_val}, {max_val}]"

        # Validate fast < slow
        if params["fast_ema_period"] >= params["slow_ema_period"]:
            return False, "fast_ema_period must be less than slow_ema_period"

        return True, ""

    def evaluate(
        self,
        strategy: Strategy,
        snapshot: MarketSnapshot,
    ) -> TradeIntent | None:
        """
        Evaluate EMA crossover conditions.

        Returns TradeIntent if EMA crossover occurs.
        """
        # Get parameters with defaults
        params = {**DEFAULT_PARAMS, **strategy.parameters}
        fast_period = int(params["fast_ema_period"])
        slow_period = int(params["slow_ema_period"])
        confirmation_bars = int(params["confirmation_bars"])
        sl_pct = float(params["sl_pct"])
        tp_pct = float(params["tp_pct"])
        position_size = Decimal(str(params["position_size_usd"]))

        # Extract price data from snapshot
        closes = self._get_closes(snapshot)
        min_required = slow_period + confirmation_bars + 2
        if closes is None or len(closes) < min_required:
            logger.debug(f"Insufficient data for EMA: need {min_required} closes")
            return None

        # Calculate EMAs for current and previous bars
        fast_ema_values = []
        slow_ema_values = []

        # Need at least 2 points to detect crossover
        for i in range(len(closes) - confirmation_bars - 1, len(closes) + 1):
            subset = closes[:i]
            if len(subset) < slow_period:
                continue

            fast = calculate_ema(subset, fast_period)
            slow = calculate_ema(subset, slow_period)

            if fast is not None and slow is not None:
                fast_ema_values.append(fast)
                slow_ema_values.append(slow)

        if len(fast_ema_values) < 2 or len(slow_ema_values) < 2:
            logger.debug("Insufficient EMA values for crossover detection")
            return None

        # Detect crossover
        crossover = detect_crossover(fast_ema_values, slow_ema_values)
        if crossover is None:
            return None

        current_price = float(snapshot.last_price)
        entry_price = snapshot.last_price
        fast_ema = fast_ema_values[-1]
        slow_ema = slow_ema_values[-1]
        prev_fast = fast_ema_values[-2]
        prev_slow = slow_ema_values[-2]

        # Determine side and build reasons
        if crossover == "bullish":
            side = TradeSide.LONG

            # Calculate crossover strength (distance between EMAs as % of price)
            ema_spread = fast_ema - slow_ema
            spread_pct = (ema_spread / slow_ema) * 100

            # Confidence based on crossover strength
            confidence = self._calculate_crossover_confidence(spread_pct)

            reasons = [
                IntentReason(
                    rule="ema_bullish_crossover",
                    description=f"EMA{fast_period} ({fast_ema:.2f}) crossed above EMA{slow_period} ({slow_ema:.2f})",
                    inputs={
                        "fast_ema": round(fast_ema, 2),
                        "slow_ema": round(slow_ema, 2),
                        "fast_ema_prev": round(prev_fast, 2),
                        "slow_ema_prev": round(prev_slow, 2),
                    },
                    weight=1.0,
                ),
                IntentReason(
                    rule="crossover_strength",
                    description=f"EMA spread is {spread_pct:.3f}% after crossover",
                    inputs={"spread_pct": round(spread_pct, 4)},
                    weight=0.5,
                ),
            ]

        else:  # bearish
            side = TradeSide.SHORT

            # Calculate crossover strength
            ema_spread = slow_ema - fast_ema
            spread_pct = (ema_spread / slow_ema) * 100

            # Confidence based on crossover strength
            confidence = self._calculate_crossover_confidence(spread_pct)

            reasons = [
                IntentReason(
                    rule="ema_bearish_crossover",
                    description=f"EMA{fast_period} ({fast_ema:.2f}) crossed below EMA{slow_period} ({slow_ema:.2f})",
                    inputs={
                        "fast_ema": round(fast_ema, 2),
                        "slow_ema": round(slow_ema, 2),
                        "fast_ema_prev": round(prev_fast, 2),
                        "slow_ema_prev": round(prev_slow, 2),
                    },
                    weight=1.0,
                ),
                IntentReason(
                    rule="crossover_strength",
                    description=f"EMA spread is {spread_pct:.3f}% after crossover",
                    inputs={"spread_pct": round(spread_pct, 4)},
                    weight=0.5,
                ),
            ]

        # Calculate SL/TP
        atr = snapshot.indicators.get("atr_14") if snapshot.indicators else None
        stop_loss, take_profit = self._calculate_sl_tp(entry_price, side.value, atr, sl_pct, tp_pct)

        # Ensure positive values
        if stop_loss <= 0 or take_profit <= 0:
            logger.warning("Invalid SL/TP calculated, skipping signal")
            return None

        # Build indicator inputs for explainability
        indicator_inputs: dict[str, Any] = {
            "fast_ema_period": fast_period,
            "slow_ema_period": slow_period,
            "fast_ema": round(fast_ema, 2),
            "slow_ema": round(slow_ema, 2),
            "fast_ema_prev": round(prev_fast, 2),
            "slow_ema_prev": round(prev_slow, 2),
            "crossover_type": crossover,
            "close": round(current_price, 2),
        }

        if atr:
            indicator_inputs["atr_14"] = round(atr, 4)

        # Create TradeIntent
        return TradeIntent(
            strategy_id=strategy.strategy_id,
            pair=snapshot.pair,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_usd=position_size,
            confidence=confidence,
            reasons=reasons,
            indicator_inputs=indicator_inputs,
            market_context={
                "regime": snapshot.regime,
                "volatility": snapshot.volatility,
                "spread_bps": snapshot.spread_bps,
            },
            timeframe=strategy.timeframes[0] if strategy.timeframes else "5m",
            mode="paper",
        )

    def _calculate_crossover_confidence(self, spread_pct: float) -> float:
        """
        Calculate confidence based on EMA spread percentage.

        Stronger crossovers (larger spread) get higher confidence.
        """
        # Map spread from 0-1% to confidence 0.5-0.95
        normalized = min(abs(spread_pct) / 1.0, 1.0)
        return 0.5 + (normalized * 0.45)

    def _get_closes(self, snapshot: MarketSnapshot) -> list[float] | None:
        """Extract closing prices from snapshot."""
        if snapshot.indicators:
            closes = snapshot.indicators.get("closes")
            if closes and isinstance(closes, (list, tuple)):
                return list(closes)

            ohlcv = snapshot.indicators.get("ohlcv")
            if ohlcv and isinstance(ohlcv, list):
                return [candle.get("close", candle.get("c")) for candle in ohlcv if candle]

        return None
