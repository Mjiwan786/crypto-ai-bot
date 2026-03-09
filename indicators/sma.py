"""AI Predicted Signals — SMA Indicator."""
import numpy as np


def compute_sma(close: np.ndarray, period: int) -> np.ndarray:
    """Compute Simple Moving Average.

    Args:
        close: Array of closing prices.
        period: SMA period.

    Returns:
        Array of SMA values (same length, NaN-padded for first period-1 values).
    """
    n = len(close)
    sma = np.full(n, np.nan)
    if n < period:
        return sma

    # Cumulative sum trick for O(n) rolling mean
    cumsum = np.cumsum(close)
    sma[period - 1:] = (cumsum[period - 1:] - np.concatenate(([0], cumsum[:-period]))) / period

    return sma
