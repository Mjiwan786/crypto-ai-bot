"""AI Predicted Signals — RSI Strategy + RSI Divergence.

RSI crossover: long when RSI crosses above 30, short when crosses below 70.
RSI divergence: bullish when price makes lower lows but RSI makes higher lows.
"""
from typing import List, Dict, Any
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategyResult


class RSIStrategy(BaseStrategy):
    name = "rsi"

    def __init__(self, period: int = 14, overbought: float = 70.0, oversold: float = 30.0) -> None:
        self._period = period
        self._overbought = overbought
        self._oversold = oversold

    def compute_signal(self, ohlcv: np.ndarray, indicators: Dict[str, np.ndarray]) -> StrategyResult:
        if len(ohlcv) < 20:
            return StrategyResult("neutral", 0.0, self.name)

        rsi = indicators["rsi"]
        current_rsi = float(rsi[-1])
        prev_rsi = float(rsi[-2])

        if np.isnan(current_rsi) or np.isnan(prev_rsi):
            return StrategyResult("neutral", 0.0, self.name)

        meta = {"rsi_current": round(current_rsi, 2), "rsi_previous": round(prev_rsi, 2), "rsi_period": self._period}

        # RSI crosses above oversold (30) — bullish
        if prev_rsi < self._oversold and current_rsi > self._oversold:
            confidence = 60.0 + (self._oversold + 5 - current_rsi) * 0.5
            confidence = float(np.clip(confidence, 50.0, 90.0))
            return StrategyResult("long", confidence, self.name, meta)

        # RSI crosses below overbought (70) — bearish
        if prev_rsi > self._overbought and current_rsi < self._overbought:
            confidence = 60.0 + (current_rsi - (self._overbought - 5)) * 0.5
            confidence = float(np.clip(confidence, 50.0, 90.0))
            return StrategyResult("short", confidence, self.name, meta)

        return StrategyResult("neutral", 0.0, self.name, meta)

    def get_required_indicators(self) -> List[str]:
        return ["rsi"]

    def get_params(self) -> Dict[str, Any]:
        return {"period": self._period, "overbought": self._overbought, "oversold": self._oversold}


class AdaptiveRSIStrategy(BaseStrategy):
    """RSI divergence detection for higher-quality entries."""
    name = "rsi_divergence"

    def __init__(self, period: int = 14, lookback: int = 5) -> None:
        self._period = period
        self._lookback = lookback

    def compute_signal(self, ohlcv: np.ndarray, indicators: Dict[str, np.ndarray]) -> StrategyResult:
        if len(ohlcv) < 30:
            return StrategyResult("neutral", 0.0, self.name)

        rsi = indicators["rsi"]
        low = ohlcv[:, 2]
        high = ohlcv[:, 1]
        lb = self._lookback

        current_rsi = float(rsi[-1])
        prev_rsi = float(rsi[-1 - lb])
        if np.isnan(current_rsi) or np.isnan(prev_rsi):
            return StrategyResult("neutral", 0.0, self.name)

        meta = {
            "rsi_current": round(current_rsi, 2),
            "rsi_lookback": round(prev_rsi, 2),
            "divergence_type": "none",
        }

        # Bullish divergence: price lower low + RSI higher low
        if low[-1] < low[-1 - lb] and current_rsi > prev_rsi:
            price_swing = float((low[-1 - lb] - low[-1]) / low[-1 - lb] * 100)
            rsi_swing = current_rsi - prev_rsi
            meta.update({"divergence_type": "bullish", "price_swing": round(price_swing, 3), "rsi_swing": round(rsi_swing, 2)})
            return StrategyResult("long", 70.0, self.name, meta)

        # Bearish divergence: price higher high + RSI lower high
        if high[-1] > high[-1 - lb] and current_rsi < prev_rsi:
            price_swing = float((high[-1] - high[-1 - lb]) / high[-1 - lb] * 100)
            rsi_swing = prev_rsi - current_rsi
            meta.update({"divergence_type": "bearish", "price_swing": round(price_swing, 3), "rsi_swing": round(rsi_swing, 2)})
            return StrategyResult("short", 70.0, self.name, meta)

        return StrategyResult("neutral", 0.0, self.name, meta)

    def get_required_indicators(self) -> List[str]:
        return ["rsi"]

    def get_params(self) -> Dict[str, Any]:
        return {"period": self._period, "lookback": self._lookback}
