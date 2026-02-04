"""
RSI Mean Reversion Strategy Evaluator.

Generates TradeIntent when RSI indicates oversold/overbought conditions
with optional trend filter confirmation.

Default parameters (not curve-fit):
- rsi_period: 14 (standard)
- oversold_threshold: 30 (standard)
- overbought_threshold: 70 (standard)
- use_trend_filter: True (requires price above/below EMA)
- trend_ema_period: 50 (medium-term trend)
"""

from decimal import Decimal
from typing import Any
import logging

from shared_contracts import Strategy, TradeIntent, TradeSide, IntentReason, MarketSnapshot

from strategies.indicator.base import StrategyEvaluator
from strategies.indicator.indicators import calculate_rsi, calculate_ema

logger = logging.getLogger(__name__)


# Parameter defaults and bounds
DEFAULT_PARAMS = {
    "rsi_period": 14,
    "oversold_threshold": 30,
    "overbought_threshold": 70,
    "use_trend_filter": True,
    "trend_ema_period": 50,
    "sl_pct": 2.0,
    "tp_pct": 4.0,
    "position_size_usd": 100.0,
}

PARAM_BOUNDS = {
    "rsi_period": (5, 50),
    "oversold_threshold": (10, 40),
    "overbought_threshold": (60, 90),
    "trend_ema_period": (10, 200),
    "sl_pct": (0.5, 10.0),
    "tp_pct": (1.0, 20.0),
    "position_size_usd": (10.0, 10000.0),
}


class RSIMeanReversionEvaluator(StrategyEvaluator):
    """
    RSI Mean Reversion Strategy.

    Logic:
    - BUY when RSI crosses up through oversold threshold (+ optional trend filter)
    - SELL when RSI crosses down through overbought threshold (+ optional trend filter)

    The trend filter requires:
    - For LONG: price must be above EMA (trading with trend on pullback)
    - For SHORT: price must be below EMA (trading with trend on rally)
    """

    def validate_params(self, strategy: Strategy) -> tuple[bool, str]:
        """Validate RSI strategy parameters."""
        params = {**DEFAULT_PARAMS, **strategy.parameters}

        for key, (min_val, max_val) in PARAM_BOUNDS.items():
            if key in params:
                val = params[key]
                if not (min_val <= val <= max_val):
                    return False, f"{key}={val} out of bounds [{min_val}, {max_val}]"

        # Validate oversold < overbought
        if params["oversold_threshold"] >= params["overbought_threshold"]:
            return False, "oversold_threshold must be less than overbought_threshold"

        return True, ""

    def evaluate(
        self,
        strategy: Strategy,
        snapshot: MarketSnapshot,
    ) -> TradeIntent | None:
        """
        Evaluate RSI mean reversion conditions.

        Returns TradeIntent if RSI indicates reversal opportunity.
        """
        # Get parameters with defaults
        params = {**DEFAULT_PARAMS, **strategy.parameters}
        rsi_period = int(params["rsi_period"])
        oversold = float(params["oversold_threshold"])
        overbought = float(params["overbought_threshold"])
        use_trend_filter = bool(params["use_trend_filter"])
        trend_ema_period = int(params["trend_ema_period"])
        sl_pct = float(params["sl_pct"])
        tp_pct = float(params["tp_pct"])
        position_size = Decimal(str(params["position_size_usd"]))

        # Extract price data from snapshot
        closes = self._get_closes(snapshot)
        if closes is None or len(closes) < rsi_period + 1:
            logger.debug(f"Insufficient data for RSI: need {rsi_period + 1} closes")
            return None

        # Calculate RSI
        rsi = calculate_rsi(closes, rsi_period)
        if rsi is None:
            logger.debug("RSI calculation returned None")
            return None

        # Get current and previous RSI for crossover detection
        prev_closes = closes[:-1]
        prev_rsi = calculate_rsi(prev_closes, rsi_period)
        if prev_rsi is None:
            return None

        # Calculate trend filter if enabled
        ema = None
        trend_aligned = True
        if use_trend_filter:
            ema = calculate_ema(closes, trend_ema_period)
            if ema is None:
                logger.debug("EMA calculation returned None, skipping trend filter")
                use_trend_filter = False

        current_price = float(snapshot.last_price)
        entry_price = snapshot.last_price

        # Check for oversold crossover (potential LONG)
        if prev_rsi <= oversold and rsi > oversold:
            side = TradeSide.LONG

            # Trend filter: price should be above EMA for bullish bias
            if use_trend_filter and ema is not None:
                trend_aligned = current_price > ema

            if not trend_aligned:
                logger.debug(f"RSI oversold crossover rejected: price below EMA trend filter")
                return None

            # Calculate confidence based on how oversold it was
            confidence = self._calculate_confidence(prev_rsi, oversold, max_deviation=20.0)

            # Build reasons
            reasons = [
                IntentReason(
                    rule="rsi_oversold_crossover",
                    description=f"RSI crossed up through {oversold} (was {prev_rsi:.1f}, now {rsi:.1f})",
                    inputs={"rsi_prev": round(prev_rsi, 2), "rsi_current": round(rsi, 2), "threshold": oversold},
                    weight=1.0,
                ),
            ]

            if use_trend_filter and ema:
                reasons.append(
                    IntentReason(
                        rule="trend_filter_passed",
                        description=f"Price ({current_price:.2f}) above EMA{trend_ema_period} ({ema:.2f})",
                        inputs={"price": round(current_price, 2), "ema": round(ema, 2), "ema_period": trend_ema_period},
                        weight=0.3,
                    )
                )

        # Check for overbought crossover (potential SHORT)
        elif prev_rsi >= overbought and rsi < overbought:
            side = TradeSide.SHORT

            # Trend filter: price should be below EMA for bearish bias
            if use_trend_filter and ema is not None:
                trend_aligned = current_price < ema

            if not trend_aligned:
                logger.debug(f"RSI overbought crossover rejected: price above EMA trend filter")
                return None

            # Calculate confidence based on how overbought it was
            confidence = self._calculate_confidence(prev_rsi, overbought, max_deviation=20.0)

            # Build reasons
            reasons = [
                IntentReason(
                    rule="rsi_overbought_crossover",
                    description=f"RSI crossed down through {overbought} (was {prev_rsi:.1f}, now {rsi:.1f})",
                    inputs={"rsi_prev": round(prev_rsi, 2), "rsi_current": round(rsi, 2), "threshold": overbought},
                    weight=1.0,
                ),
            ]

            if use_trend_filter and ema:
                reasons.append(
                    IntentReason(
                        rule="trend_filter_passed",
                        description=f"Price ({current_price:.2f}) below EMA{trend_ema_period} ({ema:.2f})",
                        inputs={"price": round(current_price, 2), "ema": round(ema, 2), "ema_period": trend_ema_period},
                        weight=0.3,
                    )
                )
        else:
            # No signal condition met
            return None

        # Calculate SL/TP
        atr = snapshot.indicators.get("atr_14") if snapshot.indicators else None
        stop_loss, take_profit = self._calculate_sl_tp(entry_price, side.value, atr, sl_pct, tp_pct)

        # Ensure positive values
        if stop_loss <= 0 or take_profit <= 0:
            logger.warning("Invalid SL/TP calculated, skipping signal")
            return None

        # Build indicator inputs for explainability
        indicator_inputs: dict[str, Any] = {
            "rsi_period": rsi_period,
            "rsi_current": round(rsi, 2),
            "rsi_previous": round(prev_rsi, 2),
            "oversold_threshold": oversold,
            "overbought_threshold": overbought,
            "close": round(current_price, 2),
        }

        if use_trend_filter and ema:
            indicator_inputs["ema_period"] = trend_ema_period
            indicator_inputs["ema_value"] = round(ema, 2)
            indicator_inputs["trend_filter_passed"] = trend_aligned

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

    def _get_closes(self, snapshot: MarketSnapshot) -> list[float] | None:
        """
        Extract closing prices from snapshot.

        Looks for 'closes' in indicators, falls back to constructing from OHLC.
        """
        if snapshot.indicators:
            closes = snapshot.indicators.get("closes")
            if closes and isinstance(closes, (list, tuple)):
                return list(closes)

            # Try to get from OHLCV data
            ohlcv = snapshot.indicators.get("ohlcv")
            if ohlcv and isinstance(ohlcv, list):
                return [candle.get("close", candle.get("c")) for candle in ohlcv if candle]

        # Fallback: use last_price as single data point (not useful for RSI)
        return None
