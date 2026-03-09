"""AI Predicted Signals — Trend Following Strategy.

ADX-based trend strength + directional movement for trend confirmation.
"""
from typing import List, Dict, Any
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategyResult


def compute_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute ADX, +DI, -DI.

    Returns:
        (adx, plus_di, minus_di) arrays, NaN-padded.
    """
    n = len(close)
    nan_arr = np.full(n, np.nan)
    if n < period * 2 + 1:
        return nan_arr.copy(), nan_arr.copy(), nan_arr.copy()

    # Directional Movement
    up_move = np.diff(high)
    down_move = -np.diff(low)  # prev_low - low => -(low[1:] - low[:-1])

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # True Range
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
    )

    # Wilder's smoothing
    def wilder_smooth(arr, p):
        out = np.full(len(arr), np.nan)
        out[p - 1] = np.sum(arr[:p])
        for i in range(p, len(arr)):
            out[i] = out[i - 1] - out[i - 1] / p + arr[i]
        return out

    smoothed_tr = wilder_smooth(tr, period)
    smoothed_plus_dm = wilder_smooth(plus_dm, period)
    smoothed_minus_dm = wilder_smooth(minus_dm, period)

    # +DI, -DI
    plus_di_raw = np.where(smoothed_tr > 0, smoothed_plus_dm / smoothed_tr * 100, 0.0)
    minus_di_raw = np.where(smoothed_tr > 0, smoothed_minus_dm / smoothed_tr * 100, 0.0)

    # DX (safe divide to avoid RuntimeWarning)
    di_sum = plus_di_raw + minus_di_raw
    with np.errstate(invalid="ignore", divide="ignore"):
        dx = np.where(di_sum > 0, np.abs(plus_di_raw - minus_di_raw) / di_sum * 100, 0.0)

    # ADX = smoothed DX
    adx_raw = np.full(len(dx), np.nan)
    start = period - 1 + period  # need 2*period-1 valid DX values
    if start < len(dx):
        adx_raw[start] = np.mean(dx[period - 1:start + 1])
        for i in range(start + 1, len(dx)):
            if not np.isnan(adx_raw[i - 1]):
                adx_raw[i] = (adx_raw[i - 1] * (period - 1) + dx[i]) / period

    # Map back to full array (offset by 1 due to diff)
    adx = np.full(n, np.nan)
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    adx[1:] = adx_raw
    plus_di[1:] = plus_di_raw
    minus_di[1:] = minus_di_raw

    return adx, plus_di, minus_di


class TrendFollowingStrategy(BaseStrategy):
    name = "trend_following"

    def __init__(self, adx_threshold: float = 25.0, ema_period: int = 14) -> None:
        self._adx_threshold = adx_threshold
        self._ema_period = ema_period

    def compute_signal(self, ohlcv: np.ndarray, indicators: Dict[str, np.ndarray]) -> StrategyResult:
        if len(ohlcv) < 28:
            return StrategyResult("neutral", 0.0, self.name)

        adx = indicators["adx"]
        plus_di = indicators["plus_di"]
        minus_di = indicators["minus_di"]
        ema_14 = indicators["ema_14"]

        curr_adx = float(adx[-1])
        curr_plus = float(plus_di[-1])
        curr_minus = float(minus_di[-1])
        curr_ema = float(ema_14[-1])
        price = float(ohlcv[-1, 3])

        if any(np.isnan(x) for x in [curr_adx, curr_plus, curr_minus, curr_ema]):
            return StrategyResult("neutral", 0.0, self.name)

        meta = {
            "adx": round(curr_adx, 2),
            "plus_di": round(curr_plus, 2),
            "minus_di": round(curr_minus, 2),
            "ema_14": round(curr_ema, 2),
            "trend_strength": "strong" if curr_adx > 40 else "moderate" if curr_adx > 25 else "weak",
        }

        # ADX < 25 = no trend
        if curr_adx < self._adx_threshold:
            return StrategyResult("neutral", 0.0, self.name, meta)

        # Long: ADX > 25, +DI > -DI, price > EMA
        if curr_plus > curr_minus and price > curr_ema:
            confidence = 55.0 + (curr_adx - 25) * 0.8
            confidence = float(np.clip(confidence, 50.0, 95.0))
            return StrategyResult("long", confidence, self.name, meta)

        # Short: ADX > 25, -DI > +DI, price < EMA
        if curr_minus > curr_plus and price < curr_ema:
            confidence = 55.0 + (curr_adx - 25) * 0.8
            confidence = float(np.clip(confidence, 50.0, 95.0))
            return StrategyResult("short", confidence, self.name, meta)

        return StrategyResult("neutral", 0.0, self.name, meta)

    def get_required_indicators(self) -> List[str]:
        return ["adx", "plus_di", "minus_di", "ema_14"]

    def get_params(self) -> Dict[str, Any]:
        return {"adx_threshold": self._adx_threshold, "ema_period": self._ema_period}
