"""AI Predicted Signals — Breakout Strategy.

Price breakout above resistance / below support with volume confirmation.
"""
from typing import List, Dict, Any
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategyResult


class BreakoutStrategy(BaseStrategy):
    name = "breakout"

    def __init__(self, lookback: int = 20, volume_threshold: float = 1.5) -> None:
        self._lookback = lookback
        self._vol_threshold = volume_threshold

    def compute_signal(self, ohlcv: np.ndarray, indicators: Dict[str, np.ndarray]) -> StrategyResult:
        if len(ohlcv) < 22:
            return StrategyResult("neutral", 0.0, self.name)

        high = ohlcv[:, 1]
        low = ohlcv[:, 2]
        close = ohlcv[:, 3]
        volume = ohlcv[:, 4]
        atr = indicators.get("atr")

        curr_close = float(close[-1])

        # Support/resistance from lookback (excluding current candle)
        resistance = float(np.max(high[-self._lookback - 1:-1]))
        support = float(np.min(low[-self._lookback - 1:-1]))

        # ATR for buffer
        atr_val = float(atr[-1]) if atr is not None and not np.isnan(atr[-1]) else curr_close * 0.01
        buffer = atr_val * 0.1

        # Volume ratio
        avg_vol = np.mean(volume[-self._lookback - 1:-1])
        vol_ratio = float(volume[-1] / avg_vol) if avg_vol > 0 else 1.0

        breakout_dist = 0.0
        meta = {
            "resistance": round(resistance, 2),
            "support": round(support, 2),
            "atr": round(atr_val, 4),
            "volume_ratio": round(vol_ratio, 2),
            "breakout_distance_bps": 0.0,
        }

        # Breakout above resistance
        if curr_close > resistance + buffer and vol_ratio > self._vol_threshold:
            breakout_dist = (curr_close - resistance) / resistance * 10000
            confidence = 65.0 + min(30.0, (curr_close - resistance) / atr_val * 20)
            confidence = float(np.clip(confidence, 55.0, 95.0))
            meta["breakout_distance_bps"] = round(breakout_dist, 1)
            return StrategyResult("long", confidence, self.name, meta)

        # Breakdown below support
        if curr_close < support - buffer and vol_ratio > self._vol_threshold:
            breakout_dist = (support - curr_close) / support * 10000
            confidence = 65.0 + min(30.0, (support - curr_close) / atr_val * 20)
            confidence = float(np.clip(confidence, 55.0, 95.0))
            meta["breakout_distance_bps"] = round(breakout_dist, 1)
            return StrategyResult("short", confidence, self.name, meta)

        return StrategyResult("neutral", 0.0, self.name, meta)

    def get_required_indicators(self) -> List[str]:
        return ["atr"]

    def get_params(self) -> Dict[str, Any]:
        return {"lookback": self._lookback, "volume_threshold": self._vol_threshold}
