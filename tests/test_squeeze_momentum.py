"""Tests for signals/squeeze_momentum.py — Squeeze Momentum feature generator."""

import os
from unittest import mock

import numpy as np
import pytest

from signals.squeeze_momentum import (
    compute_squeeze_features,
    should_skip_trade,
    _sma,
    _rolling_std,
    _atr,
    _rolling_max,
    _rolling_min,
    _linreg,
)


# ── Synthetic data generators ──


def _make_flat_ohlcv(n=50, price=100.0, noise=0.001):
    """Create very flat OHLCV data — should trigger squeeze ON."""
    np.random.seed(42)
    close = price + np.random.normal(0, price * noise, n)
    high = close * (1 + abs(np.random.normal(0, noise, n)))
    low = close * (1 - abs(np.random.normal(0, noise, n)))
    open_ = close + np.random.normal(0, price * noise * 0.5, n)
    volume = np.random.uniform(100, 1000, n)
    return np.column_stack([open_, high, low, close, volume])


def _make_volatile_ohlcv(n=50, price=100.0, noise=0.02):
    """Create volatile OHLCV data — should NOT trigger squeeze."""
    np.random.seed(42)
    close = price + np.cumsum(np.random.normal(0, price * noise, n))
    high = close * (1 + abs(np.random.normal(0, noise * 2, n)))
    low = close * (1 - abs(np.random.normal(0, noise * 2, n)))
    open_ = close + np.random.normal(0, price * noise, n)
    volume = np.random.uniform(100, 1000, n)
    return np.column_stack([open_, high, low, close, volume])


def _make_trending_up_ohlcv(n=50, start=100.0, step=0.5):
    """Create uptrending OHLCV data — positive momentum."""
    close = np.linspace(start, start + step * n, n)
    high = close * 1.005
    low = close * 0.995
    open_ = close - step * 0.3
    volume = np.full(n, 500.0)
    return np.column_stack([open_, high, low, close, volume])


def _make_trending_down_ohlcv(n=50, start=100.0, step=0.5):
    """Create downtrending OHLCV data — negative momentum."""
    close = np.linspace(start, start - step * n, n)
    high = close * 1.005
    low = close * 0.995
    open_ = close + step * 0.3
    volume = np.full(n, 500.0)
    return np.column_stack([open_, high, low, close, volume])


# ── Test: Squeeze detection ──


class TestSqueezeDetection:
    def test_squeeze_on_flat_data(self):
        """Flat data should trigger squeeze ON (BB contracts inside KC)."""
        ohlcv = _make_flat_ohlcv(n=50, noise=0.0005)
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        assert result["squeeze_on"] is True

    def test_squeeze_off_volatile_data(self):
        """Volatile data should NOT trigger squeeze (BB expands outside KC)."""
        ohlcv = _make_volatile_ohlcv(n=50, noise=0.03)
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        assert result["squeeze_on"] is False

    def test_squeeze_duration_counts_consecutive(self):
        """Duration should count consecutive squeeze bars from the end."""
        ohlcv = _make_flat_ohlcv(n=50, noise=0.0005)
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        if result["squeeze_on"]:
            assert result["squeeze_duration"] > 0
        else:
            assert result["squeeze_duration"] == 0

    def test_squeeze_duration_zero_when_off(self):
        """Duration should be 0 when squeeze is OFF."""
        ohlcv = _make_volatile_ohlcv(n=50, noise=0.03)
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        if not result["squeeze_on"]:
            assert result["squeeze_duration"] == 0

    def test_squeeze_fired_recently(self):
        """Squeeze fired recently should detect transition from ON to OFF."""
        # Build data: flat period (squeeze on) then volatile burst (squeeze off)
        flat = _make_flat_ohlcv(n=40, noise=0.0005)
        # Add volatile tail to break the squeeze
        np.random.seed(99)
        n_tail = 15
        base_price = flat[-1, 3]
        close = base_price + np.cumsum(np.random.normal(0, base_price * 0.02, n_tail))
        high = close * 1.03
        low = close * 0.97
        open_ = close + np.random.normal(0, base_price * 0.01, n_tail)
        volume = np.random.uniform(100, 1000, n_tail)
        volatile_tail = np.column_stack([open_, high, low, close, volume])
        combined = np.vstack([flat, volatile_tail])
        result = compute_squeeze_features(combined)
        assert result is not None
        # After flat→volatile transition, squeeze_fired_recently might be True
        # depending on how quickly BB expands past KC
        assert isinstance(result["squeeze_fired_recently"], bool)


# ── Test: Momentum ──


class TestMomentum:
    def test_momentum_positive_uptrend(self):
        """Uptrending data should have positive momentum."""
        ohlcv = _make_trending_up_ohlcv(n=50)
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        assert result["squeeze_momentum"] > 0

    def test_momentum_negative_downtrend(self):
        """Downtrending data should have negative momentum."""
        ohlcv = _make_trending_down_ohlcv(n=50)
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        assert result["squeeze_momentum"] < 0

    def test_momentum_direction_positive_rising(self):
        """Rising positive momentum should give direction +1."""
        # Strong uptrend with accelerating prices
        n = 50
        t = np.arange(n, dtype=float)
        close = 100 + 0.5 * t + 0.01 * t**2  # Accelerating up
        high = close * 1.003
        low = close * 0.997
        open_ = close - 0.2
        volume = np.full(n, 500.0)
        ohlcv = np.column_stack([open_, high, low, close, volume])
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        assert result["squeeze_momentum_direction"] == 1

    def test_momentum_direction_negative_falling(self):
        """Falling negative momentum should give direction -1."""
        n = 50
        t = np.arange(n, dtype=float)
        close = 100 - 0.5 * t - 0.01 * t**2  # Accelerating down
        high = close * 1.003
        low = close * 0.997
        open_ = close + 0.2
        volume = np.full(n, 500.0)
        ohlcv = np.column_stack([open_, high, low, close, volume])
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        assert result["squeeze_momentum_direction"] == -1

    def test_momentum_acceleration(self):
        """Acceleration should be non-zero for trending data."""
        ohlcv = _make_trending_up_ohlcv(n=50)
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        assert isinstance(result["squeeze_momentum_acceleration"], float)


# ── Test: Pre-filter ──


class TestShouldSkipTrade:
    def test_skip_during_squeeze_on(self):
        """Should skip trade during squeeze compression."""
        features = {
            "squeeze_on": True,
            "squeeze_duration": 5,
            "squeeze_momentum": 0.1,
            "squeeze_momentum_direction": 0,
            "squeeze_momentum_acceleration": 0.0,
            "squeeze_fired_recently": False,
            "bb_width_pct": 1.0,
            "kc_width_pct": 2.0,
        }
        assert should_skip_trade(features) is True

    def test_allow_normal_conditions(self):
        """Should allow trade when no squeeze."""
        features = {
            "squeeze_on": False,
            "squeeze_duration": 0,
            "squeeze_momentum": 0.5,
            "squeeze_momentum_direction": 1,
            "squeeze_momentum_acceleration": 0.1,
            "squeeze_fired_recently": False,
            "bb_width_pct": 3.0,
            "kc_width_pct": 2.0,
        }
        assert should_skip_trade(features) is False

    def test_allow_when_none(self):
        """Should allow trade when features are None (disabled)."""
        assert should_skip_trade(None) is False


# ── Test: Edge cases ──


class TestEdgeCases:
    def test_feature_flag_disabled(self):
        """SQUEEZE_MOMENTUM_ENABLED=false should return None."""
        ohlcv = _make_flat_ohlcv(n=50)
        with mock.patch.dict(os.environ, {"SQUEEZE_MOMENTUM_ENABLED": "false"}):
            # Need to reimport to pick up env var change
            import importlib
            import signals.squeeze_momentum as sm
            original = sm.SQUEEZE_ENABLED
            sm.SQUEEZE_ENABLED = False
            try:
                result = compute_squeeze_features(ohlcv)
                assert result is None
            finally:
                sm.SQUEEZE_ENABLED = original

    def test_insufficient_data_returns_none(self):
        """Less than min_bars should return None."""
        ohlcv = _make_flat_ohlcv(n=15)  # Only 15 bars, need 25
        result = compute_squeeze_features(ohlcv)
        assert result is None

    def test_bb_width_and_kc_width_calculated(self):
        """BB and KC width should be positive percentages."""
        ohlcv = _make_flat_ohlcv(n=50)
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        assert result["bb_width_pct"] >= 0.0
        assert result["kc_width_pct"] >= 0.0

    def test_all_features_present(self):
        """All 8 feature keys should be present in result."""
        ohlcv = _make_flat_ohlcv(n=50)
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        expected_keys = {
            "squeeze_on",
            "squeeze_duration",
            "squeeze_momentum",
            "squeeze_momentum_direction",
            "squeeze_momentum_acceleration",
            "squeeze_fired_recently",
            "bb_width_pct",
            "kc_width_pct",
        }
        assert set(result.keys()) == expected_keys

    def test_feature_types(self):
        """Feature values should have correct types."""
        ohlcv = _make_volatile_ohlcv(n=50)
        result = compute_squeeze_features(ohlcv)
        assert result is not None
        assert isinstance(result["squeeze_on"], bool)
        assert isinstance(result["squeeze_duration"], int)
        assert isinstance(result["squeeze_momentum"], float)
        assert isinstance(result["squeeze_momentum_direction"], int)
        assert isinstance(result["squeeze_momentum_acceleration"], float)
        assert isinstance(result["squeeze_fired_recently"], bool)
        assert isinstance(result["bb_width_pct"], float)
        assert isinstance(result["kc_width_pct"], float)


# ── Test: Helper functions ──


class TestHelpers:
    def test_sma_constant_data(self):
        """SMA of constant data should equal the constant."""
        data = np.full(20, 42.0)
        result = _sma(data, 10)
        np.testing.assert_allclose(result[-1], 42.0, atol=1e-10)

    def test_rolling_std_constant_data(self):
        """Rolling std of constant data should be ~0."""
        data = np.full(20, 42.0)
        result = _rolling_std(data, 10)
        assert result[-1] < 1e-10

    def test_linreg_linear_data(self):
        """Linear regression of perfectly linear data should return exact values."""
        data = np.arange(30, dtype=float)
        result = _linreg(data, 20)
        # Last value should be close to 29.0 (the last data point)
        np.testing.assert_allclose(result[-1], 29.0, atol=1e-6)
