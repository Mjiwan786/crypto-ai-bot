"""AI Predicted Signals — MACD Indicator."""
import numpy as np

from indicators.ema import compute_ema


def compute_macd(
    close: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute MACD line, signal line, and histogram.

    Args:
        close: Array of closing prices.
        fast: Fast EMA period (default 12).
        slow: Slow EMA period (default 26).
        signal: Signal line EMA period (default 9).

    Returns:
        (macd_line, signal_line, histogram) — all same length as input, NaN-padded.
    """
    n = len(close)
    nan_arr = np.full(n, np.nan)
    if n < slow + signal:
        return nan_arr.copy(), nan_arr.copy(), nan_arr.copy()

    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)

    macd_line = ema_fast - ema_slow

    # Signal line: EMA of the MACD line (only where MACD is valid)
    signal_line = np.full(n, np.nan)
    # MACD is valid from index slow-1 onwards
    macd_start = slow - 1
    macd_valid = macd_line[macd_start:]

    if len(macd_valid) >= signal:
        sig_ema = compute_ema(macd_valid, signal)
        signal_line[macd_start:] = sig_ema

    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram
