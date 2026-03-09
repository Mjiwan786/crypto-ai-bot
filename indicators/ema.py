"""AI Predicted Signals — EMA Indicator."""
import numpy as np


def compute_ema(close: np.ndarray, period: int) -> np.ndarray:
    """Compute Exponential Moving Average.

    Args:
        close: Array of closing prices.
        period: EMA period.

    Returns:
        Array of EMA values (same length, NaN-padded for first period-1 values).
    """
    n = len(close)
    ema = np.full(n, np.nan)
    if n < period:
        return ema

    # SMA seed
    ema[period - 1] = np.mean(close[:period])
    multiplier = 2.0 / (period + 1)

    for i in range(period, n):
        ema[i] = (close[i] - ema[i - 1]) * multiplier + ema[i - 1]

    return ema
