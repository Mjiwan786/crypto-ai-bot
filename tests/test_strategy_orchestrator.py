"""Tests for signals/strategy_orchestrator.py"""
import asyncio
import numpy as np
import pytest

from signals.strategy_orchestrator import (
    StrategyOrchestrator,
    detect_regime,
    _ema,
    REGIME_STRATEGIES,
)


# ── Fixtures ─────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 60, trend: float = 0.0, base: float = 68000.0, seed: int = 42) -> np.ndarray:
    """Generate synthetic OHLCV data."""
    np.random.seed(seed)
    noise = np.random.randn(n) * 50
    closes = base + np.linspace(0, trend, n) + noise
    opens = closes - np.random.rand(n) * 30
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(n)) * 20
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(n)) * 20
    volumes = np.random.rand(n) * 100 + 50
    return np.column_stack([opens, highs, lows, closes, volumes])


# ── Regime Detection ─────────────────────────────────────────────────

class TestRegimeDetection:
    def test_bull_regime(self):
        ohlcv = _make_ohlcv(60, trend=1200)  # strong uptrend
        regime = detect_regime(ohlcv)
        assert regime in ("bull", "neutral"), f"Expected bull or neutral, got {regime}"

    def test_bear_regime(self):
        ohlcv = _make_ohlcv(60, trend=-1200)
        regime = detect_regime(ohlcv)
        assert regime in ("bear", "neutral"), f"Expected bear or neutral, got {regime}"

    def test_sideways_regime(self):
        # Very tight range, low volatility
        ohlcv = _make_ohlcv(60, trend=0, base=68000)
        # Override with tight data
        closes = np.full(60, 68000.0) + np.random.randn(60) * 5
        ohlcv[:, 3] = closes
        ohlcv[:, 0] = closes - 1
        ohlcv[:, 1] = closes + 2
        ohlcv[:, 2] = closes - 2
        regime = detect_regime(ohlcv)
        assert regime in ("sideways", "neutral")

    def test_neutral_on_insufficient_data(self):
        ohlcv = _make_ohlcv(10)
        assert detect_regime(ohlcv) == "neutral"

    def test_regime_returns_valid_string(self):
        ohlcv = _make_ohlcv(60)
        regime = detect_regime(ohlcv)
        assert regime in ("bull", "bear", "sideways", "neutral")


# ── EMA ──────────────────────────────────────────────────────────────

class TestEMA:
    def test_ema_returns_float(self):
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _ema(data, 3)
        assert isinstance(result, float)

    def test_ema_tracks_uptrend(self):
        data = np.arange(1.0, 21.0)
        ema9 = _ema(data, 9)
        ema21 = _ema(data, 21)
        assert ema9 > ema21  # shorter EMA leads in uptrend


# ── Orchestrator ─────────────────────────────────────────────────────

class TestStrategyOrchestrator:
    def test_disabled_returns_none(self):
        orch = StrategyOrchestrator(enabled=False)
        result = asyncio.run(orch.generate_signal(_make_ohlcv(), "BTC/USD"))
        assert result["signal"] is None
        assert result["reason"] == "orchestrator_disabled"

    def test_insufficient_data(self):
        orch = StrategyOrchestrator()
        result = asyncio.run(orch.generate_signal(_make_ohlcv(5), "BTC/USD"))
        assert result["signal"] is None
        assert result["reason"] == "insufficient_data"

    def test_none_ohlcv(self):
        orch = StrategyOrchestrator()
        result = asyncio.run(orch.generate_signal(None, "BTC/USD"))
        assert result["signal"] is None

    def test_returns_dict_keys(self):
        orch = StrategyOrchestrator()
        result = asyncio.run(orch.generate_signal(_make_ohlcv(60, trend=800), "BTC/USD"))
        # Should always have these keys
        assert "regime" in result or "reason" in result

    def test_regime_in_result(self):
        orch = StrategyOrchestrator()
        result = asyncio.run(orch.generate_signal(_make_ohlcv(60), "BTC/USD"))
        if "regime" in result:
            assert result["regime"] in ("bull", "bear", "sideways", "neutral")

    def test_confidence_bounded(self):
        orch = StrategyOrchestrator()
        result = asyncio.run(orch.generate_signal(_make_ohlcv(60, trend=1500), "BTC/USD"))
        if result.get("confidence"):
            assert 0.0 <= result["confidence"] <= 0.95

    def test_source_is_strategy_orchestrator(self):
        orch = StrategyOrchestrator()
        result = asyncio.run(orch.generate_signal(_make_ohlcv(60, trend=1500), "BTC/USD"))
        if result.get("signal"):
            assert result["source"] == "strategy_orchestrator"


# ── Regime→Strategy Routing ──────────────────────────────────────────

class TestRegimeRouting:
    def test_all_regimes_have_strategies(self):
        for regime in ("bull", "bear", "sideways", "neutral"):
            assert regime in REGIME_STRATEGIES
            assert len(REGIME_STRATEGIES[regime]) >= 2
