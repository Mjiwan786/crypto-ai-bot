"""
MACD Trend Strategy Evaluator.

Generates TradeIntent when MACD line crosses signal line with histogram confirmation.

Default parameters (not curve-fit):
- fast_period: 12 (standard)
- slow_period: 26 (standard)
- signal_period: 9 (standard)
- require_histogram_confirmation: True
"""

from decimal import Decimal
from typing import Any
import logging

from shared_contracts import Strategy, TradeIntent, TradeSide, IntentReason, MarketSnapshot

from strategies.indicator.base import StrategyEvaluator
from strategies.indicator.indicators import calculate_macd

logger = logging.getLogger(__name__)


# Parameter defaults and bounds
DEFAULT_PARAMS = {
    "fast_period": 12,
    "slow_period": 26,
    "signal_period": 9,
    "require_histogram_confirmation": True,
    "histogram_threshold": 0.0,  # Histogram must be > this for confirmation
    "sl_pct": 2.0,
    "tp_pct": 4.0,
    "position_size_usd": 100.0,
}

PARAM_BOUNDS = {
    "fast_period": (5, 20),
    "slow_period": (15, 50),
    "signal_period": (5, 15),
    "histogram_threshold": (0.0, 100.0),
    "sl_pct": (0.5, 10.0),
    "tp_pct": (1.0, 20.0),
    "position_size_usd": (10.0, 10000.0),
}


class MACDTrendEvaluator(StrategyEvaluator):
    """
    MACD Trend Strategy.

    Logic:
    - BUY when MACD line crosses above signal line (+ histogram confirmation)
    - SELL when MACD line crosses below signal line (+ histogram confirmation)

    Histogram confirmation:
    - For LONG: histogram must be positive (and growing)
    - For SHORT: histogram must be negative (and growing in magnitude)

    Confidence is based on:
    - MACD/signal line separation
    - Histogram magnitude
    """

    def validate_params(self, strategy: Strategy) -> tuple[bool, str]:
        """Validate MACD parameters."""
        params = {**DEFAULT_PARAMS, **strategy.parameters}

        for key, (min_val, max_val) in PARAM_BOUNDS.items():
            if key in params:
                val = params[key]
                if not (min_val <= val <= max_val):
                    return False, f"{key}={val} out of bounds [{min_val}, {max_val}]"

        # Validate fast < slow
        if params["fast_period"] >= params["slow_period"]:
            return False, "fast_period must be less than slow_period"

        return True, ""

    def evaluate(
        self,
        strategy: Strategy,
        snapshot: MarketSnapshot,
    ) -> TradeIntent | None:
        """
        Evaluate MACD trend conditions.

        Returns TradeIntent if MACD crossover occurs with confirmation.
        """
        # Get parameters with defaults
        params = {**DEFAULT_PARAMS, **strategy.parameters}
        fast_period = int(params["fast_period"])
        slow_period = int(params["slow_period"])
        signal_period = int(params["signal_period"])
        require_histogram = bool(params["require_histogram_confirmation"])
        histogram_threshold = float(params["histogram_threshold"])
        sl_pct = float(params["sl_pct"])
        tp_pct = float(params["tp_pct"])
        position_size = Decimal(str(params["position_size_usd"]))

        # Extract price data from snapshot
        closes = self._get_closes(snapshot)
        min_required = slow_period + signal_period + 2
        if closes is None or len(closes) < min_required:
            logger.debug(f"Insufficient data for MACD: need {min_required} closes")
            return None

        # Calculate current MACD
        macd, signal, histogram = calculate_macd(closes, fast_period, slow_period, signal_period)
        if macd is None or signal is None:
            logger.debug("MACD calculation returned None")
            return None

        # Calculate previous MACD for crossover detection
        prev_closes = closes[:-1]
        prev_macd, prev_signal, prev_histogram = calculate_macd(
            prev_closes, fast_period, slow_period, signal_period
        )
        if prev_macd is None or prev_signal is None:
            return None

        current_price = float(snapshot.last_price)
        entry_price = snapshot.last_price

        # Detect MACD crossover
        bullish_crossover = prev_macd <= prev_signal and macd > signal
        bearish_crossover = prev_macd >= prev_signal and macd < signal

        if not bullish_crossover and not bearish_crossover:
            return None

        # Determine side
        if bullish_crossover:
            side = TradeSide.LONG

            # Histogram confirmation for longs: histogram should be positive
            if require_histogram and histogram is not None:
                if histogram <= histogram_threshold:
                    logger.debug(f"MACD bullish crossover rejected: histogram {histogram:.4f} <= {histogram_threshold}")
                    return None

            # Calculate confidence based on MACD-signal separation and histogram
            separation = abs(macd - signal)
            confidence = self._calculate_macd_confidence(separation, histogram, current_price)

            reasons = [
                IntentReason(
                    rule="macd_bullish_crossover",
                    description=f"MACD ({macd:.4f}) crossed above signal ({signal:.4f})",
                    inputs={
                        "macd": round(macd, 4),
                        "signal": round(signal, 4),
                        "macd_prev": round(prev_macd, 4),
                        "signal_prev": round(prev_signal, 4),
                    },
                    weight=1.0,
                ),
            ]

            if histogram is not None:
                reasons.append(
                    IntentReason(
                        rule="histogram_confirmation",
                        description=f"Histogram is positive ({histogram:.4f}), confirming bullish momentum",
                        inputs={"histogram": round(histogram, 4)},
                        weight=0.5,
                    )
                )

        else:  # bearish_crossover
            side = TradeSide.SHORT

            # Histogram confirmation for shorts: histogram should be negative
            if require_histogram and histogram is not None:
                if histogram >= -histogram_threshold:
                    logger.debug(f"MACD bearish crossover rejected: histogram {histogram:.4f} >= {-histogram_threshold}")
                    return None

            # Calculate confidence
            separation = abs(macd - signal)
            confidence = self._calculate_macd_confidence(separation, histogram, current_price)

            reasons = [
                IntentReason(
                    rule="macd_bearish_crossover",
                    description=f"MACD ({macd:.4f}) crossed below signal ({signal:.4f})",
                    inputs={
                        "macd": round(macd, 4),
                        "signal": round(signal, 4),
                        "macd_prev": round(prev_macd, 4),
                        "signal_prev": round(prev_signal, 4),
                    },
                    weight=1.0,
                ),
            ]

            if histogram is not None:
                reasons.append(
                    IntentReason(
                        rule="histogram_confirmation",
                        description=f"Histogram is negative ({histogram:.4f}), confirming bearish momentum",
                        inputs={"histogram": round(histogram, 4)},
                        weight=0.5,
                    )
                )

        # Calculate SL/TP
        atr = snapshot.indicators.get("atr_14") if snapshot.indicators else None
        stop_loss, take_profit = self._calculate_sl_tp(entry_price, side.value, atr, sl_pct, tp_pct)

        # Ensure positive values
        if stop_loss <= 0 or take_profit <= 0:
            logger.warning("Invalid SL/TP calculated, skipping signal")
            return None

        # Build indicator inputs for explainability
        indicator_inputs: dict[str, Any] = {
            "fast_period": fast_period,
            "slow_period": slow_period,
            "signal_period": signal_period,
            "macd": round(macd, 4),
            "signal": round(signal, 4),
            "macd_prev": round(prev_macd, 4),
            "signal_prev": round(prev_signal, 4),
            "close": round(current_price, 2),
        }

        if histogram is not None:
            indicator_inputs["histogram"] = round(histogram, 4)
        if prev_histogram is not None:
            indicator_inputs["histogram_prev"] = round(prev_histogram, 4)
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

    def _calculate_macd_confidence(
        self,
        separation: float,
        histogram: float | None,
        price: float,
    ) -> float:
        """
        Calculate confidence based on MACD metrics.

        Factors:
        - MACD/signal separation relative to price
        - Histogram magnitude
        """
        # Normalize separation as percentage of price
        sep_pct = (separation / price) * 100 if price > 0 else 0

        # Base confidence from separation (0-0.5% maps to 0.5-0.75)
        base = 0.5 + min(sep_pct / 0.5, 1.0) * 0.25

        # Add histogram bonus (0.0-0.2)
        if histogram is not None:
            hist_pct = (abs(histogram) / price) * 100 if price > 0 else 0
            hist_bonus = min(hist_pct / 0.3, 1.0) * 0.2
            base += hist_bonus

        return min(base, 0.95)

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
