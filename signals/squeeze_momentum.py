"""
Squeeze Momentum Indicator — volatility regime detector and ML feature generator.

Based on John Carter's TTM Squeeze (LazyBear's TradingView implementation).
Detects Bollinger Band contraction inside Keltner Channels.

NOT a consensus voter — generates features for XGBoost ML scorer.

Features produced:
  1. squeeze_on (bool): True when BB inside KC (compression)
  2. squeeze_duration (int): Bars since squeeze started (0 if not in squeeze)
  3. squeeze_momentum (float): Linear regression momentum value
  4. squeeze_momentum_direction (int): +1 rising, -1 falling, 0 flat
  5. squeeze_momentum_acceleration (float): Rate of change of momentum
  6. squeeze_fired_recently (bool): Squeeze ended in last 3 bars
  7. bb_width_pct (float): BB width as % of price
  8. kc_width_pct (float): KC width as % of price

Published crypto backtests with 0.03% commission:
  ETH/USD 4H: +185% return, profit factor 1.70, 36% win rate
  XRP/USD 4H: +371% return, profit factor 1.78, 34% win rate
"""

import logging
import os
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Feature flag
SQUEEZE_ENABLED = os.getenv("SQUEEZE_MOMENTUM_ENABLED", "true").lower() == "true"

# Bollinger Bands params
BB_LENGTH = int(os.getenv("SQUEEZE_BB_LENGTH", "20"))
BB_MULT = float(os.getenv("SQUEEZE_BB_MULT", "2.0"))

# Keltner Channel params
KC_LENGTH = int(os.getenv("SQUEEZE_KC_LENGTH", "20"))
KC_MULT = float(os.getenv("SQUEEZE_KC_MULT", "1.5"))

# Momentum params (linear regression length)
MOM_LENGTH = int(os.getenv("SQUEEZE_MOM_LENGTH", "20"))


def compute_squeeze_features(
    ohlcv: np.ndarray,
    bb_length: int = None,
    bb_mult: float = None,
    kc_length: int = None,
    kc_mult: float = None,
    mom_length: int = None,
) -> Optional[Dict]:
    """
    Compute Squeeze Momentum features from OHLCV data.

    Args:
        ohlcv: numpy array shape (N, 5) — [open, high, low, close, volume]

    Returns:
        Dict with features, or None if insufficient data:
        {
            "squeeze_on": bool,
            "squeeze_duration": int,
            "squeeze_momentum": float,
            "squeeze_momentum_direction": int,  # +1, -1, or 0
            "squeeze_momentum_acceleration": float,
            "squeeze_fired_recently": bool,
            "bb_width_pct": float,
            "kc_width_pct": float,
        }
    """
    if not SQUEEZE_ENABLED:
        return None

    bb_length = bb_length or BB_LENGTH
    bb_mult = bb_mult or BB_MULT
    kc_length = kc_length or KC_LENGTH
    kc_mult = kc_mult or KC_MULT
    mom_length = mom_length or MOM_LENGTH

    min_bars = max(bb_length, kc_length, mom_length) + 5
    if ohlcv is None or len(ohlcv) < min_bars:
        return None

    close = ohlcv[:, 3]
    high = ohlcv[:, 1]
    low = ohlcv[:, 2]

    # ── Bollinger Bands ──
    bb_basis = _sma(close, bb_length)
    bb_std = _rolling_std(close, bb_length)
    upper_bb = bb_basis + bb_mult * bb_std
    lower_bb = bb_basis - bb_mult * bb_std

    # ── Keltner Channels ──
    kc_basis = _sma(close, kc_length)
    atr = _atr(high, low, close, kc_length)
    upper_kc = kc_basis + kc_mult * atr
    lower_kc = kc_basis - kc_mult * atr

    # ── Squeeze Detection ──
    # Squeeze ON when BB is inside KC
    squeeze_on_arr = (lower_bb > lower_kc) & (upper_bb < upper_kc)

    current_squeeze = bool(squeeze_on_arr[-1])

    # Squeeze duration: count consecutive True from the end
    squeeze_duration = 0
    if current_squeeze:
        for i in range(len(squeeze_on_arr) - 1, -1, -1):
            if squeeze_on_arr[i]:
                squeeze_duration += 1
            else:
                break

    # Squeeze fired recently (was on, now off — within last 3 bars)
    squeeze_fired = False
    if not current_squeeze and len(squeeze_on_arr) >= 4:
        squeeze_fired = any(squeeze_on_arr[-4:-1])  # Was on in last 3 bars before current

    # ── Momentum (Linear Regression) ──
    # Momentum = linreg(close - avg(highest_high, lowest_low), length)
    highest = _rolling_max(high, mom_length)
    lowest = _rolling_min(low, mom_length)
    midpoint = (highest + lowest) / 2.0

    # Value to regress: close - midpoint of (range_midpoint + sma) / 2
    val = close - (midpoint + bb_basis) / 2.0

    # Linear regression value at current bar
    momentum = _linreg(val, mom_length)
    current_mom = momentum[-1] if len(momentum) > 0 else 0.0
    prev_mom = momentum[-2] if len(momentum) > 1 else 0.0

    # Direction: +1 if momentum > 0 and rising, -1 if < 0 and falling
    if current_mom > 0 and current_mom > prev_mom:
        mom_direction = 1   # Strong bullish (lime)
    elif current_mom > 0 and current_mom <= prev_mom:
        mom_direction = 0   # Fading bullish (dark green) — treat as neutral
    elif current_mom < 0 and current_mom < prev_mom:
        mom_direction = -1  # Strong bearish (red)
    else:
        mom_direction = 0   # Fading bearish (maroon) — treat as neutral

    # Acceleration: rate of change of momentum
    mom_acceleration = current_mom - prev_mom

    # Volatility metrics
    bb_width = (upper_bb[-1] - lower_bb[-1]) / close[-1] * 100 if close[-1] > 0 else 0.0
    kc_width = (upper_kc[-1] - lower_kc[-1]) / close[-1] * 100 if close[-1] > 0 else 0.0

    result = {
        "squeeze_on": current_squeeze,
        "squeeze_duration": squeeze_duration,
        "squeeze_momentum": float(current_mom),
        "squeeze_momentum_direction": mom_direction,
        "squeeze_momentum_acceleration": float(mom_acceleration),
        "squeeze_fired_recently": squeeze_fired,
        "bb_width_pct": float(bb_width),
        "kc_width_pct": float(kc_width),
    }

    if current_squeeze:
        logger.debug(
            "[SQUEEZE] ON (duration=%d bars, momentum=%.4f, direction=%d)",
            squeeze_duration, current_mom, mom_direction,
        )
    elif squeeze_fired:
        logger.info(
            "[SQUEEZE] FIRED (momentum=%.4f, direction=%s)",
            current_mom, "bullish" if mom_direction > 0 else "bearish" if mom_direction < 0 else "neutral",
        )

    return result


def should_skip_trade(squeeze_features: Optional[Dict]) -> bool:
    """
    Pre-filter: should this trade be skipped based on squeeze state?

    Skip when:
    - Squeeze is ON (compression — direction unknown, wait for breakout)

    Allow when:
    - No squeeze (normal trading)
    - Squeeze just fired with clear momentum direction
    - Features are None (disabled)
    """
    if squeeze_features is None:
        return False  # Feature disabled, don't filter

    if squeeze_features["squeeze_on"]:
        return True  # In compression — don't trade

    return False


# ── Helper Functions (pure numpy, no talib dependency) ──


def _sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average."""
    kernel = np.ones(period) / period
    # Pad to maintain array length
    padded = np.concatenate([np.full(period - 1, data[0]), data])
    return np.convolve(padded, kernel, mode="valid")


def _rolling_std(data: np.ndarray, period: int) -> np.ndarray:
    """Rolling standard deviation."""
    result = np.zeros(len(data))
    for i in range(period - 1, len(data)):
        result[i] = np.std(data[i - period + 1 : i + 1], ddof=0)
    # Fill initial values
    result[: period - 1] = result[period - 1]
    return result


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Average True Range."""
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )
    tr = np.concatenate([[high[0] - low[0]], tr])

    # EMA of TR
    result = np.zeros(len(tr))
    result[0] = tr[0]
    alpha = 2.0 / (period + 1)
    for i in range(1, len(tr)):
        result[i] = alpha * tr[i] + (1 - alpha) * result[i - 1]
    return result


def _rolling_max(data: np.ndarray, period: int) -> np.ndarray:
    """Rolling maximum."""
    result = np.zeros(len(data))
    for i in range(len(data)):
        start = max(0, i - period + 1)
        result[i] = np.max(data[start : i + 1])
    return result


def _rolling_min(data: np.ndarray, period: int) -> np.ndarray:
    """Rolling minimum."""
    result = np.zeros(len(data))
    for i in range(len(data)):
        start = max(0, i - period + 1)
        result[i] = np.min(data[start : i + 1])
    return result


def _linreg(data: np.ndarray, period: int) -> np.ndarray:
    """Linear regression value at each point (endpoint of regression line)."""
    result = np.zeros(len(data))
    for i in range(period - 1, len(data)):
        y = data[i - period + 1 : i + 1]
        x = np.arange(period)
        # Linear regression: y = mx + b, return endpoint value
        coeffs = np.polyfit(x, y, 1)
        result[i] = coeffs[0] * (period - 1) + coeffs[1]
    # Fill initial values
    result[: period - 1] = result[period - 1]
    return result
