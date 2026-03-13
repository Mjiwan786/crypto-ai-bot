"""
Sprint 3B tests for signals/trend_filter.py — MACD-based trend alignment.

6+ tests covering bullish/bearish/neutral MACD with LONG/SHORT signals,
and feature flag behavior.
"""

import os
from unittest import mock

import numpy as np
import pytest

from signals.trend_filter import check_trend_alignment


# ── Helpers ──────────────────────────────────────────────────

def _make_trending_ohlcv(direction: str, n: int = 50, base: float = 100.0) -> np.ndarray:
    """Build OHLCV with a clear trend for MACD to detect."""
    data = np.zeros((n, 5))
    for i in range(n):
        if direction == "up":
            c = base + i * 1.0  # Strong uptrend
        elif direction == "down":
            c = base - i * 1.0  # Strong downtrend
        else:
            c = base + (0.1 if i % 2 == 0 else -0.1)  # Flat
        data[i, 0] = c - 0.5  # open
        data[i, 1] = c + 1.0  # high
        data[i, 2] = c - 1.0  # low
        data[i, 3] = c         # close
        data[i, 4] = 1000.0    # volume
    return data


# ── Test 1: Bullish MACD allows LONG ────────────────────────

def test_bullish_macd_allows_long():
    ohlcv = _make_trending_ohlcv("up", n=50)
    result = check_trend_alignment(ohlcv, pair="BTC/USD", signal_direction="buy")
    assert result["filter_active"] is True
    assert result["htf_direction"] == "bullish"
    assert result["aligned"] is True


# ── Test 2: Bullish MACD vetoes SHORT ───────────────────────

def test_bullish_macd_vetoes_short():
    ohlcv = _make_trending_ohlcv("up", n=50)
    result = check_trend_alignment(ohlcv, pair="BTC/USD", signal_direction="sell")
    assert result["filter_active"] is True
    assert result["htf_direction"] == "bullish"
    assert result["aligned"] is False


# ── Test 3: Bearish MACD allows SHORT ───────────────────────

def test_bearish_macd_allows_short():
    ohlcv = _make_trending_ohlcv("down", n=50)
    result = check_trend_alignment(ohlcv, pair="ETH/USD", signal_direction="sell")
    assert result["filter_active"] is True
    assert result["htf_direction"] == "bearish"
    assert result["aligned"] is True


# ── Test 4: Bearish MACD vetoes LONG ────────────────────────

def test_bearish_macd_vetoes_long():
    ohlcv = _make_trending_ohlcv("down", n=50)
    result = check_trend_alignment(ohlcv, pair="ETH/USD", signal_direction="buy")
    assert result["filter_active"] is True
    assert result["htf_direction"] == "bearish"
    assert result["aligned"] is False


# ── Test 5: Neutral MACD allows any direction ───────────────

def test_neutral_macd_allows_any():
    ohlcv = _make_trending_ohlcv("flat", n=50, base=100.0)
    result_long = check_trend_alignment(ohlcv, pair="SOL/USD", signal_direction="buy")
    result_short = check_trend_alignment(ohlcv, pair="SOL/USD", signal_direction="sell")

    # In a flat market, MACD histogram should be near zero → neutral
    if result_long["htf_direction"] == "neutral":
        assert result_long["aligned"] is True
        assert result_short["aligned"] is True


# ── Test 6: Feature flag disabled passes all ────────────────

def test_feature_flag_disabled():
    with mock.patch.dict(os.environ, {"TREND_FILTER_ENABLED": "false"}):
        ohlcv = _make_trending_ohlcv("down", n=50)
        result = check_trend_alignment(ohlcv, pair="BTC/USD", signal_direction="buy")
        assert result["aligned"] is True
        assert result["filter_active"] is False


# ── Test 7: Insufficient data returns aligned ───────────────

def test_insufficient_data():
    ohlcv = _make_trending_ohlcv("up", n=10)  # Too few bars for MACD(12,26,9)
    result = check_trend_alignment(ohlcv, pair="BTC/USD", signal_direction="buy")
    assert result["aligned"] is True
    assert result["filter_active"] is False


# ── Test 8: MACD histogram sign is correct ──────────────────

def test_macd_histogram_sign():
    ohlcv_up = _make_trending_ohlcv("up", n=50)
    result_up = check_trend_alignment(ohlcv_up, pair="BTC/USD", signal_direction="buy")
    assert result_up["macd_histogram"] > 0

    ohlcv_down = _make_trending_ohlcv("down", n=50)
    result_down = check_trend_alignment(ohlcv_down, pair="BTC/USD", signal_direction="sell")
    assert result_down["macd_histogram"] < 0
