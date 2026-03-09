"""AI Predicted Signals — MACD Strategy.

MACD crossover with histogram filter for noise reduction.
"""
from typing import List, Dict, Any
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategyResult


class MACDStrategy(BaseStrategy):
    name = "macd"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self._fast = fast
        self._slow = slow
        self._signal = signal

    def compute_signal(self, ohlcv: np.ndarray, indicators: Dict[str, np.ndarray]) -> StrategyResult:
        if len(ohlcv) < 35:
            return StrategyResult("neutral", 0.0, self.name)

        macd_line = indicators["macd_line"]
        signal_line = indicators["macd_signal"]
        histogram = indicators["macd_histogram"]
        atr = indicators.get("atr")

        curr_macd = float(macd_line[-1])
        curr_sig = float(signal_line[-1])
        prev_macd = float(macd_line[-2])
        prev_sig = float(signal_line[-2])
        curr_hist = float(histogram[-1])

        if any(np.isnan(x) for x in [curr_macd, curr_sig, prev_macd, prev_sig, curr_hist]):
            return StrategyResult("neutral", 0.0, self.name)

        price = float(ohlcv[-1, 3])
        meta = {
            "macd_line": round(curr_macd, 6),
            "signal_line": round(curr_sig, 6),
            "histogram": round(curr_hist, 6),
            "crossover_type": "none",
        }

        # Noise filter: histogram must be meaningful relative to price
        if abs(curr_hist) < 0.0001 * price:
            return StrategyResult("neutral", 0.0, self.name, meta)

        # ATR for confidence scaling
        atr_val = float(atr[-1]) if atr is not None and not np.isnan(atr[-1]) else price * 0.01

        # Bullish crossover
        if prev_macd < prev_sig and curr_macd > curr_sig:
            confidence = 55.0 + min(40.0, abs(curr_hist) / atr_val * 100)
            confidence = float(np.clip(confidence, 50.0, 95.0))
            meta["crossover_type"] = "bullish"
            return StrategyResult("long", confidence, self.name, meta)

        # Bearish crossover
        if prev_macd > prev_sig and curr_macd < curr_sig:
            confidence = 55.0 + min(40.0, abs(curr_hist) / atr_val * 100)
            confidence = float(np.clip(confidence, 50.0, 95.0))
            meta["crossover_type"] = "bearish"
            return StrategyResult("short", confidence, self.name, meta)

        return StrategyResult("neutral", 0.0, self.name, meta)

    def get_required_indicators(self) -> List[str]:
        return ["macd_line", "macd_signal", "macd_histogram", "atr"]

    def get_params(self) -> Dict[str, Any]:
        return {"fast": self._fast, "slow": self._slow, "signal": self._signal}
