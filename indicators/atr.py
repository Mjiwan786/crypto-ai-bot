"""AI Predicted Signals — ATR Indicator."""
import numpy as np


def compute_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Compute Average True Range using Wilder's smoothing.

    Args:
        high: Array of high prices.
        low: Array of low prices.
        close: Array of closing prices.
        period: ATR period (default 14).

    Returns:
        Array of ATR values (same length, NaN-padded).
    """
    n = len(close)
    atr = np.full(n, np.nan)
    if n < period + 1:
        return atr

    # True Range
    high_low = high[1:] - low[1:]
    high_prev_close = np.abs(high[1:] - close[:-1])
    low_prev_close = np.abs(low[1:] - close[:-1])
    tr = np.maximum(high_low, np.maximum(high_prev_close, low_prev_close))

    # First ATR = SMA of first `period` TRs
    atr[period] = np.mean(tr[:period])

    # Wilder's smoothing
    for i in range(period, len(tr)):
        atr[i + 1] = (atr[i] * (period - 1) + tr[i]) / period

    return atr
