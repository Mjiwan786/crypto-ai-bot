"""
Sprint 3B: MACD-based trend alignment filter.

Checks whether a signal direction aligns with the higher-timeframe trend
using MACD(12, 26, 9) computed on available OHLCV closes.

LONG signals only allowed when MACD histogram >= 0.
SHORT signals only allowed when MACD histogram <= 0.
Neutral (abs(histogram) < threshold) allows any direction.
"""

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)


def _ema(data: np.ndarray, period: int) -> np.ndarray:
    """Compute EMA over a 1-D array."""
    alpha = 2.0 / (period + 1)
    out = np.empty_like(data)
    out[0] = data[0]
    for i in range(1, len(data)):
        out[i] = alpha * data[i] + (1.0 - alpha) * out[i - 1]
    return out


def check_trend_alignment(
    ohlcv_short: np.ndarray,
    pair: str,
    signal_direction: str,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    neutral_threshold: float = None,
) -> dict:
    """
    Check if signal direction aligns with the higher-timeframe trend.

    Args:
        ohlcv_short: shape (N, 5) — 1-min or 5-min candles
        pair: trading pair (for logging)
        signal_direction: "buy" or "sell"
        macd_fast: fast EMA period (default 12)
        macd_slow: slow EMA period (default 26)
        macd_signal: signal EMA period (default 9)
        neutral_threshold: abs(histogram) below this = neutral (allows any)

    Returns:
        {
            "aligned": bool,
            "htf_direction": str,  # "bullish", "bearish", "neutral"
            "macd_histogram": float,
            "filter_active": bool,
        }
    """
    enabled = os.getenv("TREND_FILTER_ENABLED", "true").lower() == "true"
    if not enabled:
        return {
            "aligned": True,
            "htf_direction": "disabled",
            "macd_histogram": 0.0,
            "filter_active": False,
        }

    if ohlcv_short is None or len(ohlcv_short) < macd_slow + macd_signal:
        return {
            "aligned": True,
            "htf_direction": "insufficient_data",
            "macd_histogram": 0.0,
            "filter_active": False,
        }

    closes = ohlcv_short[:, 3].astype(float)

    # Compute MACD
    ema_fast = _ema(closes, macd_fast)
    ema_slow = _ema(closes, macd_slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, macd_signal)
    histogram = macd_line - signal_line

    current_hist = float(histogram[-1])

    # Neutral threshold: default to 0.05% of price (configurable via env var)
    if neutral_threshold is None:
        neutral_pct = float(os.getenv("TREND_FILTER_NEUTRAL_PCT", "0.0005"))
        neutral_threshold = closes[-1] * neutral_pct

    # Classify higher-timeframe direction
    if abs(current_hist) < neutral_threshold:
        htf_direction = "neutral"
    elif current_hist > 0:
        htf_direction = "bullish"
    else:
        htf_direction = "bearish"

    # Check alignment
    if htf_direction == "neutral":
        aligned = True
    elif signal_direction == "buy" and htf_direction == "bullish":
        aligned = True
    elif signal_direction == "sell" and htf_direction == "bearish":
        aligned = True
    else:
        aligned = False
        logger.info(
            "[TREND_FILTER] %s: vetoed %s signal (HTF=%s, MACD_hist=%.6g)",
            pair, signal_direction, htf_direction, current_hist,
        )

    return {
        "aligned": aligned,
        "htf_direction": htf_direction,
        "macd_histogram": current_hist,
        "filter_active": True,
    }
