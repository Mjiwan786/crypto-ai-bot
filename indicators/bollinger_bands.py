"""AI Predicted Signals — Bollinger Bands Indicator."""
import numpy as np

from indicators.sma import compute_sma


def compute_bollinger_bands(
    close: np.ndarray,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute Bollinger Bands.

    Args:
        close: Array of closing prices.
        period: SMA period (default 20).
        std_dev: Standard deviation multiplier (default 2.0).

    Returns:
        (upper_band, middle_band, lower_band) — all same length, NaN-padded.
    """
    n = len(close)
    nan_arr = np.full(n, np.nan)
    if n < period:
        return nan_arr.copy(), nan_arr.copy(), nan_arr.copy()

    middle = compute_sma(close, period)

    # Rolling standard deviation
    rolling_std = np.full(n, np.nan)
    for i in range(period - 1, n):
        rolling_std[i] = np.std(close[i - period + 1 : i + 1], ddof=0)

    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std

    return upper, middle, lower
