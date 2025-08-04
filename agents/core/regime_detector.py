"""Market regime detector.

This agent analyses market metrics such as moving average spreads,
volatility and volume to determine whether the current regime is bull, bear
or range.  It uses simple heuristic functions `_is_bullish`, `_is_bearing` to
categorise the regime.  The real implementation would compute metrics from
actual price data and volume profiles as described in the moderate risk
strategy blueprint.
"""

from __future__ import annotations

import pandas as pd


class RegimeDetector:
    """Determine the current market regime (bull, bear or range)."""

    def __init__(self) -> None:
        pass

    def _is_bullish(self, data: pd.DataFrame) -> bool:
        # Placeholder: bull if 50 EMA above 200 EMA
        ema50 = data['Close'].ewm(span=50, adjust=False).mean()
        ema200 = data['Close'].ewm(span=200, adjust=False).mean()
        return ema50.iloc[-1] > ema200.iloc[-1]

    def _is_bearing(self, data: pd.DataFrame) -> bool:
        # Placeholder: bear if 50 EMA below 200 EMA
        ema50 = data['Close'].ewm(span=50, adjust=False).mean()
        ema200 = data['Close'].ewm(span=200, adjust=False).mean()
        return ema50.iloc[-1] < ema200.iloc[-1]

    def determine_regime(self, data: pd.DataFrame) -> str:
        """Return 'bull', 'bear' or 'range' based on market metrics."""
        if self._is_bullish(data):
            return "bull"
        if self._is_bearing(data):
            return "bear"
        return "range"