"""AI Predicted Signals — Volume Profile Indicators."""
import numpy as np

from indicators.sma import compute_sma


def compute_volume_sma(volume: np.ndarray, period: int = 20) -> np.ndarray:
    """Compute rolling average volume.

    Args:
        volume: Array of volume values.
        period: Rolling period (default 20).

    Returns:
        Array of volume SMA values (same length, NaN-padded).
    """
    return compute_sma(volume, period)


def compute_volume_ratio(volume: np.ndarray, period: int = 20) -> float:
    """Compute current volume relative to average.

    Args:
        volume: Array of volume values.
        period: Lookback for average (default 20).

    Returns:
        Ratio of current volume to average. Returns 1.0 if insufficient data.
    """
    if len(volume) < period + 1:
        return 1.0
    avg_vol = np.mean(volume[-(period + 1):-1])
    if avg_vol == 0:
        return 1.0
    return float(volume[-1] / avg_vol)
