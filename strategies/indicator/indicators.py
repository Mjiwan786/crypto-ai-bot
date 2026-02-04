"""
Technical indicator calculations.

Provides indicator calculations with TA-Lib fallback support.
All functions are deterministic and work with lists/arrays of floats.
"""

from typing import Sequence
import logging

logger = logging.getLogger(__name__)

# Try to import TA-Lib
try:
    import talib
    import numpy as np
    HAS_TALIB = True
except ImportError:
    talib = None
    np = None
    HAS_TALIB = False
    logger.info("TA-Lib not available, using fallback implementations")


def calculate_rsi(closes: Sequence[float], period: int = 14) -> float | None:
    """
    Calculate RSI (Relative Strength Index).

    Args:
        closes: Sequence of closing prices (oldest first)
        period: RSI period (default 14)

    Returns:
        RSI value (0-100) or None if insufficient data
    """
    if len(closes) < period + 1:
        return None

    if HAS_TALIB:
        arr = np.array(closes, dtype=np.float64)
        rsi = talib.RSI(arr, timeperiod=period)
        if len(rsi) > 0 and not np.isnan(rsi[-1]):
            return float(rsi[-1])
        return None

    # Fallback: manual RSI calculation
    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    if len(gains) < period:
        return None

    # Use last 'period' values for initial average
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_ema(closes: Sequence[float], period: int) -> float | None:
    """
    Calculate EMA (Exponential Moving Average).

    Args:
        closes: Sequence of closing prices (oldest first)
        period: EMA period

    Returns:
        EMA value or None if insufficient data
    """
    if len(closes) < period:
        return None

    if HAS_TALIB:
        arr = np.array(closes, dtype=np.float64)
        ema = talib.EMA(arr, timeperiod=period)
        if len(ema) > 0 and not np.isnan(ema[-1]):
            return float(ema[-1])
        return None

    # Fallback: manual EMA calculation
    multiplier = 2 / (period + 1)

    # Start with SMA for first value
    ema = sum(closes[:period]) / period

    # Calculate EMA for remaining values
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def calculate_sma(closes: Sequence[float], period: int) -> float | None:
    """
    Calculate SMA (Simple Moving Average).

    Args:
        closes: Sequence of closing prices (oldest first)
        period: SMA period

    Returns:
        SMA value or None if insufficient data
    """
    if len(closes) < period:
        return None

    return sum(closes[-period:]) / period


def calculate_macd(
    closes: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[float | None, float | None, float | None]:
    """
    Calculate MACD (Moving Average Convergence Divergence).

    Args:
        closes: Sequence of closing prices (oldest first)
        fast_period: Fast EMA period (default 12)
        slow_period: Slow EMA period (default 26)
        signal_period: Signal line period (default 9)

    Returns:
        (macd_line, signal_line, histogram) or (None, None, None)
    """
    if len(closes) < slow_period + signal_period:
        return None, None, None

    if HAS_TALIB:
        arr = np.array(closes, dtype=np.float64)
        macd, signal, hist = talib.MACD(
            arr,
            fastperiod=fast_period,
            slowperiod=slow_period,
            signalperiod=signal_period,
        )
        if len(macd) > 0 and not np.isnan(macd[-1]):
            return float(macd[-1]), float(signal[-1]), float(hist[-1])
        return None, None, None

    # Fallback: manual MACD calculation
    fast_ema = calculate_ema(closes, fast_period)
    slow_ema = calculate_ema(closes, slow_period)

    if fast_ema is None or slow_ema is None:
        return None, None, None

    macd_line = fast_ema - slow_ema

    # Need enough data for signal line
    # Build a sequence of MACD values for signal calculation
    macd_values = []
    for i in range(slow_period, len(closes) + 1):
        subset = closes[:i]
        fe = calculate_ema(subset, fast_period)
        se = calculate_ema(subset, slow_period)
        if fe is not None and se is not None:
            macd_values.append(fe - se)

    if len(macd_values) < signal_period:
        return macd_line, None, None

    signal_line = calculate_ema(macd_values, signal_period)
    if signal_line is None:
        return macd_line, None, None

    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    """
    Calculate ATR (Average True Range).

    Args:
        highs: Sequence of high prices
        lows: Sequence of low prices
        closes: Sequence of closing prices
        period: ATR period (default 14)

    Returns:
        ATR value or None if insufficient data
    """
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None

    if HAS_TALIB:
        h = np.array(highs, dtype=np.float64)
        l = np.array(lows, dtype=np.float64)
        c = np.array(closes, dtype=np.float64)
        atr = talib.ATR(h, l, c, timeperiod=period)
        if len(atr) > 0 and not np.isnan(atr[-1]):
            return float(atr[-1])
        return None

    # Fallback: manual ATR calculation
    true_ranges = []

    for i in range(1, len(closes)):
        high_low = highs[i] - lows[i]
        high_close = abs(highs[i] - closes[i - 1])
        low_close = abs(lows[i] - closes[i - 1])
        tr = max(high_low, high_close, low_close)
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    # Simple average for ATR
    return sum(true_ranges[-period:]) / period


def calculate_highest_high(highs: Sequence[float], period: int) -> float | None:
    """
    Calculate highest high over period.

    Args:
        highs: Sequence of high prices
        period: Lookback period

    Returns:
        Highest high value or None if insufficient data
    """
    if len(highs) < period:
        return None
    return max(highs[-period:])


def calculate_lowest_low(lows: Sequence[float], period: int) -> float | None:
    """
    Calculate lowest low over period.

    Args:
        lows: Sequence of low prices
        period: Lookback period

    Returns:
        Lowest low value or None if insufficient data
    """
    if len(lows) < period:
        return None
    return min(lows[-period:])


def detect_crossover(
    fast_values: Sequence[float],
    slow_values: Sequence[float],
) -> str | None:
    """
    Detect crossover between fast and slow lines.

    Args:
        fast_values: Fast line values (at least 2)
        slow_values: Slow line values (at least 2)

    Returns:
        'bullish' if fast crosses above slow,
        'bearish' if fast crosses below slow,
        None if no crossover
    """
    if len(fast_values) < 2 or len(slow_values) < 2:
        return None

    prev_fast = fast_values[-2]
    prev_slow = slow_values[-2]
    curr_fast = fast_values[-1]
    curr_slow = slow_values[-1]

    # Bullish crossover: fast was below, now above
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return "bullish"

    # Bearish crossover: fast was above, now below
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return "bearish"

    return None
