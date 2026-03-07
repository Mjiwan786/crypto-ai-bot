"""
Volume confirmation for signal scoring.

Volume is the most reliable confirmation of price moves.
A breakout on 3x average volume is real.
A breakout on 0.5x average volume is noise.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def compute_volume_ratio(
    volume_series: np.ndarray,
    lookback: int = 20,
) -> float:
    """
    Current candle volume / average of previous `lookback` candles.

    Returns 1.0 if insufficient data.
    """
    if len(volume_series) < lookback + 1:
        return 1.0
    avg_volume = np.mean(volume_series[-(lookback + 1):-1])
    if avg_volume <= 0:
        return 1.0
    return float(volume_series[-1] / avg_volume)


def apply_volume_multiplier(
    confidence: float,
    volume_ratio: float,
) -> float:
    """
    Adjust confidence score based on volume confirmation.

    - volume >= 2.0x avg: +20% confidence (strong confirmation)
    - volume >= 1.5x avg: +10% confidence (above average)
    - volume < 0.7x avg:  -30% confidence (weak / likely noise)
    """
    if volume_ratio >= 2.0:
        confidence *= 1.20
    elif volume_ratio >= 1.5:
        confidence *= 1.10
    elif volume_ratio < 0.7:
        confidence *= 0.70

    return min(confidence, 0.95)


def should_suppress_for_volume(
    volume_ratio: float,
    min_volume_ratio: float = 0.5,
) -> bool:
    """
    Returns True if volume is too low to trust any signal.
    """
    if volume_ratio < min_volume_ratio:
        logger.info(
            "Signal suppressed: volume too low (%.2fx avg, min=%.2fx)",
            volume_ratio, min_volume_ratio,
        )
        return True
    return False
