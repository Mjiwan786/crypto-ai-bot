"""AI Predicted Signals — Mean Reversion Strategy.

Bollinger Band touch + RSI confirmation.
"""
from typing import List, Dict, Any
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategyResult


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"

    def __init__(self, bb_period: int = 20, bb_std: float = 2.0) -> None:
        self._bb_period = bb_period
        self._bb_std = bb_std

    def compute_signal(self, ohlcv: np.ndarray, indicators: Dict[str, np.ndarray]) -> StrategyResult:
        if len(ohlcv) < 22:
            return StrategyResult("neutral", 0.0, self.name)

        close = ohlcv[:, 3]
        rsi = indicators["rsi"]
        bb_upper = indicators["bb_upper"]
        bb_middle = indicators["bb_middle"]
        bb_lower = indicators["bb_lower"]
        atr = indicators.get("atr")

        curr_close = float(close[-1])
        curr_rsi = float(rsi[-1])
        curr_upper = float(bb_upper[-1])
        curr_middle = float(bb_middle[-1])
        curr_lower = float(bb_lower[-1])

        if any(np.isnan(x) for x in [curr_rsi, curr_upper, curr_middle, curr_lower]):
            return StrategyResult("neutral", 0.0, self.name)

        atr_val = float(atr[-1]) if atr is not None and not np.isnan(atr[-1]) else curr_close * 0.01
        bb_width = (curr_upper - curr_lower) / curr_middle * 10000 if curr_middle > 0 else 0

        meta = {
            "bb_upper": round(curr_upper, 2),
            "bb_middle": round(curr_middle, 2),
            "bb_lower": round(curr_lower, 2),
            "bb_width": round(bb_width, 1),
            "rsi": round(curr_rsi, 2),
            "band_touch": "none",
        }

        # Long: close at/below lower BB + RSI < 40
        if curr_close <= curr_lower and curr_rsi < 40:
            confidence = 65.0 + (curr_lower - curr_close) / atr_val * 5
            confidence = float(np.clip(confidence, 55.0, 90.0))
            meta["band_touch"] = "lower"
            return StrategyResult("long", confidence, self.name, meta)

        # Short: close at/above upper BB + RSI > 60
        if curr_close >= curr_upper and curr_rsi > 60:
            confidence = 65.0 + (curr_close - curr_upper) / atr_val * 5
            confidence = float(np.clip(confidence, 55.0, 90.0))
            meta["band_touch"] = "upper"
            return StrategyResult("short", confidence, self.name, meta)

        return StrategyResult("neutral", 0.0, self.name, meta)

    def get_required_indicators(self) -> List[str]:
        return ["rsi", "bb_upper", "bb_middle", "bb_lower", "atr"]

    def get_params(self) -> Dict[str, Any]:
        return {"bb_period": self._bb_period, "bb_std": self._bb_std}
