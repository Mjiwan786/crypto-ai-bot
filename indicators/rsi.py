"""AI Predicted Signals — RSI Indicator. Wilder's smoothing RSI."""
import numpy as np


def compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute RSI using Wilder's smoothing.

    Args:
        closes: Array of closing prices.
        period: RSI period (default 14).

    Returns:
        Array of RSI values (same length as input, NaN-padded for first `period` values).
    """
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n < period + 1:
        return rsi

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Initial averages (SMA of first `period` values)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    # First RSI value
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))

    # Wilder's smoothing for remaining values
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return rsi
