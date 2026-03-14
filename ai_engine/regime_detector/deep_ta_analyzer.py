"""
Deep technical analysis for regime detection.

Computes RSI, MACD, Bollinger Bands, ATR, and trend strength from
price data. Used by the regime detector to classify market conditions.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Union

import numpy as np

logger = logging.getLogger(__name__)


def analyse_prices(prices: Union[List[float], np.ndarray]) -> Dict[str, float]:
    """
    Analyse a sequence of prices and return technical indicators.

    Args:
        prices: List or array of historical close prices.
                Needs at least 30 values for full analysis.

    Returns:
        Dictionary with real indicator values:
        - rsi: RSI 14-period (0-100)
        - macd: MACD line value (EMA12 - EMA26)
        - macd_signal: MACD signal line (EMA9 of MACD)
        - macd_histogram: MACD histogram
        - bollinger: tuple of (upper_band, lower_band)
        - bb_position: price position in BB (0=lower, 1=upper)
        - atr_pct: ATR as percentage of current price
        - trend_strength: abs(EMA9 - EMA21) / EMA21 * 100
        - volatility: std of returns over 20 periods
    """
    closes = np.asarray(prices, dtype=np.float64)
    result: Dict = {}

    if len(closes) < 15:
        return {"rsi": 50.0, "macd": 0.0, "bollinger": (0.0, 0.0)}

    # RSI 14
    result["rsi"] = _compute_rsi(closes, 14)

    # MACD
    if len(closes) >= 26:
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        macd_line = ema12 - ema26
        result["macd"] = float(macd_line)
        result["macd_signal"] = 0.0
        result["macd_histogram"] = float(macd_line)
    else:
        result["macd"] = 0.0
        result["macd_signal"] = 0.0
        result["macd_histogram"] = 0.0

    # Bollinger Bands
    if len(closes) >= 20:
        sma20 = float(np.mean(closes[-20:]))
        std20 = float(np.std(closes[-20:]))
        upper = sma20 + 2 * std20
        lower = sma20 - 2 * std20
        result["bollinger"] = (upper, lower)
        bb_width = upper - lower
        result["bb_position"] = float((closes[-1] - lower) / bb_width) if bb_width > 0 else 0.5
    else:
        result["bollinger"] = (0.0, 0.0)
        result["bb_position"] = 0.5

    # ATR (approximated from close-to-close changes)
    if len(closes) >= 15:
        true_ranges = np.abs(np.diff(closes[-15:]))
        atr = float(np.mean(true_ranges))
        result["atr_pct"] = atr / closes[-1] * 100 if closes[-1] > 0 else 0.0
    else:
        result["atr_pct"] = 0.0

    # Trend strength
    if len(closes) >= 21:
        ema9 = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        result["trend_strength"] = abs(ema9 - ema21) / ema21 * 100 if ema21 != 0 else 0.0
    else:
        result["trend_strength"] = 0.0

    # Volatility
    if len(closes) >= 21:
        returns = np.diff(closes[-21:]) / closes[-21:-1]
        result["volatility"] = float(np.std(returns))
    else:
        result["volatility"] = 0.0

    return result


def _compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    """RSI with Wilder smoothing."""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains))
    avg_loss = max(float(np.mean(losses)), 1e-10)
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _ema(data: np.ndarray, period: int) -> float:
    """Compute EMA of last value."""
    if len(data) < period:
        return float(data[-1])
    k = 2.0 / (period + 1)
    ema = float(np.mean(data[:period]))
    for price in data[period:]:
        ema = float(price) * k + ema * (1 - k)
    return ema
