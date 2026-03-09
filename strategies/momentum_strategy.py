"""AI Predicted Signals — Momentum Strategy.

Rate of Change + volume confirmation for momentum entries.
"""
from typing import List, Dict, Any
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategyResult


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def __init__(self, roc_period: int = 10, roc_threshold: float = 0.3, volume_threshold: float = 1.2) -> None:
        self._roc_period = roc_period
        self._roc_threshold = roc_threshold
        self._vol_threshold = volume_threshold

    def compute_signal(self, ohlcv: np.ndarray, indicators: Dict[str, np.ndarray]) -> StrategyResult:
        if len(ohlcv) < 25:
            return StrategyResult("neutral", 0.0, self.name)

        close = ohlcv[:, 3]
        volume = ohlcv[:, 4]

        # ROC
        roc = (close[-1] - close[-1 - self._roc_period]) / close[-1 - self._roc_period] * 100

        # Volume ratio
        avg_vol = np.mean(volume[-21:-1])
        vol_ratio = float(volume[-1] / avg_vol) if avg_vol > 0 else 1.0

        meta = {
            "roc": round(float(roc), 4),
            "volume_ratio": round(vol_ratio, 2),
            "roc_period": self._roc_period,
        }

        # Low volume = ignore
        if vol_ratio < 0.8:
            return StrategyResult("neutral", 0.0, self.name, meta)

        vol_bonus = 1.0 + max(0, vol_ratio - 1.0) * 0.2

        # Long: positive ROC + volume
        if roc > self._roc_threshold and vol_ratio > self._vol_threshold:
            confidence = (55.0 + min(35.0, abs(roc) * 10)) * vol_bonus
            confidence = float(np.clip(confidence, 50.0, 95.0))
            return StrategyResult("long", confidence, self.name, meta)

        # Short: negative ROC + volume
        if roc < -self._roc_threshold and vol_ratio > self._vol_threshold:
            confidence = (55.0 + min(35.0, abs(roc) * 10)) * vol_bonus
            confidence = float(np.clip(confidence, 50.0, 95.0))
            return StrategyResult("short", confidence, self.name, meta)

        return StrategyResult("neutral", 0.0, self.name, meta)

    def get_required_indicators(self) -> List[str]:
        return []  # computes from raw OHLCV

    def get_params(self) -> Dict[str, Any]:
        return {"roc_period": self._roc_period, "roc_threshold": self._roc_threshold, "volume_threshold": self._vol_threshold}
