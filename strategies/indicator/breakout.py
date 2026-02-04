"""
Breakout (HH/LL) Strategy Evaluator.

Generates TradeIntent when price breaks above N-bar high or below N-bar low.

Default parameters (not curve-fit):
- lookback_period: 20 (standard channel)
- breakout_buffer_pct: 0.1 (require price to exceed level by this %)
- volume_confirmation: False (require above-average volume)
"""

from decimal import Decimal
from typing import Any
import logging

from shared_contracts import Strategy, TradeIntent, TradeSide, IntentReason, MarketSnapshot

from strategies.indicator.base import StrategyEvaluator
from strategies.indicator.indicators import calculate_highest_high, calculate_lowest_low

logger = logging.getLogger(__name__)


# Parameter defaults and bounds
DEFAULT_PARAMS = {
    "lookback_period": 20,
    "breakout_buffer_pct": 0.1,  # Price must exceed level by 0.1%
    "volume_confirmation": False,
    "volume_multiplier": 1.5,  # Volume must be 1.5x average
    "sl_pct": 2.0,
    "tp_pct": 4.0,
    "position_size_usd": 100.0,
}

PARAM_BOUNDS = {
    "lookback_period": (5, 100),
    "breakout_buffer_pct": (0.0, 2.0),
    "volume_multiplier": (1.0, 5.0),
    "sl_pct": (0.5, 10.0),
    "tp_pct": (1.0, 20.0),
    "position_size_usd": (10.0, 10000.0),
}


class BreakoutEvaluator(StrategyEvaluator):
    """
    Breakout (HH/LL) Strategy.

    Logic:
    - BUY when price breaks above N-bar highest high (with buffer)
    - SELL when price breaks below N-bar lowest low (with buffer)

    Optional volume confirmation:
    - For breakout: volume must be above average (multiplier)

    Confidence is based on:
    - Breakout magnitude (how far past the level)
    - Volume strength (if enabled)
    """

    def validate_params(self, strategy: Strategy) -> tuple[bool, str]:
        """Validate breakout parameters."""
        params = {**DEFAULT_PARAMS, **strategy.parameters}

        for key, (min_val, max_val) in PARAM_BOUNDS.items():
            if key in params:
                val = params[key]
                if not (min_val <= val <= max_val):
                    return False, f"{key}={val} out of bounds [{min_val}, {max_val}]"

        return True, ""

    def evaluate(
        self,
        strategy: Strategy,
        snapshot: MarketSnapshot,
    ) -> TradeIntent | None:
        """
        Evaluate breakout conditions.

        Returns TradeIntent if price breaks significant level.
        """
        # Get parameters with defaults
        params = {**DEFAULT_PARAMS, **strategy.parameters}
        lookback = int(params["lookback_period"])
        buffer_pct = float(params["breakout_buffer_pct"])
        volume_confirmation = bool(params["volume_confirmation"])
        volume_multiplier = float(params["volume_multiplier"])
        sl_pct = float(params["sl_pct"])
        tp_pct = float(params["tp_pct"])
        position_size = Decimal(str(params["position_size_usd"]))

        # Extract price data from snapshot
        highs, lows, closes, volumes = self._get_ohlcv(snapshot)

        min_required = lookback + 1
        if closes is None or len(closes) < min_required:
            logger.debug(f"Insufficient data for Breakout: need {min_required} bars")
            return None

        if highs is None or lows is None or len(highs) < min_required or len(lows) < min_required:
            logger.debug("Missing high/low data for Breakout")
            return None

        # Calculate levels from PRIOR bars (exclude current bar)
        prior_highs = highs[-(lookback + 1):-1]
        prior_lows = lows[-(lookback + 1):-1]

        highest_high = calculate_highest_high(prior_highs, lookback)
        lowest_low = calculate_lowest_low(prior_lows, lookback)

        if highest_high is None or lowest_low is None:
            logger.debug("Could not calculate HH/LL levels")
            return None

        current_price = float(snapshot.last_price)
        current_high = highs[-1]
        current_low = lows[-1]
        entry_price = snapshot.last_price

        # Calculate breakout thresholds with buffer
        bullish_threshold = highest_high * (1 + buffer_pct / 100)
        bearish_threshold = lowest_low * (1 - buffer_pct / 100)

        # Check for bullish breakout (current high exceeds threshold)
        bullish_breakout = current_high > bullish_threshold
        bearish_breakout = current_low < bearish_threshold

        if not bullish_breakout and not bearish_breakout:
            return None

        # Volume confirmation if enabled
        avg_volume = None
        current_volume = None
        volume_confirmed = True

        if volume_confirmation and volumes is not None and len(volumes) >= lookback:
            avg_volume = sum(volumes[-lookback:]) / lookback
            current_volume = volumes[-1]

            if avg_volume > 0:
                volume_confirmed = current_volume >= avg_volume * volume_multiplier

                if not volume_confirmed:
                    logger.debug(
                        f"Breakout rejected: volume {current_volume:.2f} < "
                        f"{volume_multiplier}x avg ({avg_volume * volume_multiplier:.2f})"
                    )
                    return None

        # Determine side and build reasons
        if bullish_breakout:
            side = TradeSide.LONG

            # Calculate breakout magnitude
            breakout_pct = ((current_high - highest_high) / highest_high) * 100

            # Confidence based on breakout magnitude
            confidence = self._calculate_breakout_confidence(breakout_pct, current_volume, avg_volume)

            reasons = [
                IntentReason(
                    rule="bullish_breakout",
                    description=f"Price ({current_high:.2f}) broke above {lookback}-bar high ({highest_high:.2f})",
                    inputs={
                        "current_high": round(current_high, 2),
                        "highest_high": round(highest_high, 2),
                        "lookback_period": lookback,
                        "breakout_pct": round(breakout_pct, 3),
                    },
                    weight=1.0,
                ),
            ]

            if volume_confirmation and volume_confirmed and avg_volume:
                volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
                reasons.append(
                    IntentReason(
                        rule="volume_confirmation",
                        description=f"Volume ({current_volume:.0f}) is {volume_ratio:.1f}x average",
                        inputs={
                            "current_volume": round(current_volume, 0),
                            "avg_volume": round(avg_volume, 0),
                            "volume_ratio": round(volume_ratio, 2),
                        },
                        weight=0.4,
                    )
                )

        else:  # bearish_breakout
            side = TradeSide.SHORT

            # Calculate breakout magnitude
            breakout_pct = ((lowest_low - current_low) / lowest_low) * 100

            # Confidence based on breakout magnitude
            confidence = self._calculate_breakout_confidence(breakout_pct, current_volume, avg_volume)

            reasons = [
                IntentReason(
                    rule="bearish_breakout",
                    description=f"Price ({current_low:.2f}) broke below {lookback}-bar low ({lowest_low:.2f})",
                    inputs={
                        "current_low": round(current_low, 2),
                        "lowest_low": round(lowest_low, 2),
                        "lookback_period": lookback,
                        "breakout_pct": round(breakout_pct, 3),
                    },
                    weight=1.0,
                ),
            ]

            if volume_confirmation and volume_confirmed and avg_volume:
                volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
                reasons.append(
                    IntentReason(
                        rule="volume_confirmation",
                        description=f"Volume ({current_volume:.0f}) is {volume_ratio:.1f}x average",
                        inputs={
                            "current_volume": round(current_volume, 0),
                            "avg_volume": round(avg_volume, 0),
                            "volume_ratio": round(volume_ratio, 2),
                        },
                        weight=0.4,
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
            "lookback_period": lookback,
            "highest_high": round(highest_high, 2),
            "lowest_low": round(lowest_low, 2),
            "current_high": round(current_high, 2),
            "current_low": round(current_low, 2),
            "close": round(current_price, 2),
            "breakout_buffer_pct": buffer_pct,
        }

        if volume_confirmation:
            indicator_inputs["volume_confirmation"] = volume_confirmed
            if current_volume is not None:
                indicator_inputs["current_volume"] = round(current_volume, 0)
            if avg_volume is not None:
                indicator_inputs["avg_volume"] = round(avg_volume, 0)

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

    def _calculate_breakout_confidence(
        self,
        breakout_pct: float,
        volume: float | None,
        avg_volume: float | None,
    ) -> float:
        """
        Calculate confidence based on breakout metrics.

        Factors:
        - Breakout magnitude (how far past the level)
        - Volume strength (if available)
        """
        # Base confidence from breakout magnitude (0-2% maps to 0.5-0.8)
        base = 0.5 + min(abs(breakout_pct) / 2.0, 1.0) * 0.3

        # Volume bonus (0.0-0.15)
        if volume is not None and avg_volume is not None and avg_volume > 0:
            volume_ratio = volume / avg_volume
            if volume_ratio > 1.0:
                vol_bonus = min((volume_ratio - 1.0) / 2.0, 1.0) * 0.15
                base += vol_bonus

        return min(base, 0.95)

    def _get_ohlcv(
        self,
        snapshot: MarketSnapshot,
    ) -> tuple[list[float] | None, list[float] | None, list[float] | None, list[float] | None]:
        """
        Extract OHLCV data from snapshot.

        Returns (highs, lows, closes, volumes) or (None, None, None, None).
        """
        if not snapshot.indicators:
            return None, None, None, None

        # Try structured OHLCV
        ohlcv = snapshot.indicators.get("ohlcv")
        if ohlcv and isinstance(ohlcv, list):
            highs = [c.get("high", c.get("h")) for c in ohlcv if c]
            lows = [c.get("low", c.get("l")) for c in ohlcv if c]
            closes = [c.get("close", c.get("c")) for c in ohlcv if c]
            volumes = [c.get("volume", c.get("v", 0)) for c in ohlcv if c]

            if all(highs) and all(lows) and all(closes):
                return highs, lows, closes, volumes if any(volumes) else None

        # Try separate arrays
        highs = snapshot.indicators.get("highs")
        lows = snapshot.indicators.get("lows")
        closes = snapshot.indicators.get("closes")
        volumes = snapshot.indicators.get("volumes")

        if highs and lows and closes:
            return list(highs), list(lows), list(closes), list(volumes) if volumes else None

        return None, None, None, None
