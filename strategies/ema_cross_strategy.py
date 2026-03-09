"""AI Predicted Signals — EMA Cross Strategy.

Fast/slow EMA crossover with price position confirmation.
"""
from typing import List, Dict, Any
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategyResult


class EMACrossStrategy(BaseStrategy):
    name = "ema_cross"

    def __init__(self, fast_period: int = 9, slow_period: int = 21) -> None:
        self._fast = fast_period
        self._slow = slow_period

    def compute_signal(self, ohlcv: np.ndarray, indicators: Dict[str, np.ndarray]) -> StrategyResult:
        if len(ohlcv) < 25:
            return StrategyResult("neutral", 0.0, self.name)

        ema_fast = indicators["ema_fast"]
        ema_slow = indicators["ema_slow"]
        atr = indicators.get("atr")

        curr_fast = float(ema_fast[-1])
        curr_slow = float(ema_slow[-1])
        prev_fast = float(ema_fast[-2])
        prev_slow = float(ema_slow[-2])

        if any(np.isnan(x) for x in [curr_fast, curr_slow, prev_fast, prev_slow]):
            return StrategyResult("neutral", 0.0, self.name)

        price = float(ohlcv[-1, 3])
        atr_val = float(atr[-1]) if atr is not None and not np.isnan(atr[-1]) else price * 0.01
        spread_bps = (curr_fast - curr_slow) / curr_slow * 10000

        meta = {
            "ema_fast": round(curr_fast, 2),
            "ema_slow": round(curr_slow, 2),
            "spread_bps": round(spread_bps, 1),
            "price_position": "above" if price > max(curr_fast, curr_slow) else "below" if price < min(curr_fast, curr_slow) else "between",
        }

        # Bullish crossover + price above both EMAs
        if prev_fast < prev_slow and curr_fast > curr_slow and price > curr_fast:
            confidence = 60.0 + (curr_fast - curr_slow) / atr_val * 10
            confidence = float(np.clip(confidence, 50.0, 90.0))
            return StrategyResult("long", confidence, self.name, meta)

        # Bearish crossover + price below both EMAs
        if prev_fast > prev_slow and curr_fast < curr_slow and price < curr_fast:
            confidence = 60.0 + (curr_slow - curr_fast) / atr_val * 10
            confidence = float(np.clip(confidence, 50.0, 90.0))
            return StrategyResult("short", confidence, self.name, meta)

        return StrategyResult("neutral", 0.0, self.name, meta)

    def get_required_indicators(self) -> List[str]:
        return ["ema_fast", "ema_slow", "atr"]

    def get_params(self) -> Dict[str, Any]:
        return {"fast_period": self._fast, "slow_period": self._slow}
