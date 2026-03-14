"""Tests for ai_engine.regime_detector.deep_ta_analyzer (Sprint 4B replacement)."""
import numpy as np
import pytest

from ai_engine.regime_detector.deep_ta_analyzer import analyse_prices


class TestDeepTAAnalyzer:
    def test_rsi_bounded(self) -> None:
        prices = list(100 + np.cumsum(np.random.randn(50) * 0.5))
        result = analyse_prices(prices)
        assert 0 <= result["rsi"] <= 100

    def test_macd_computed(self) -> None:
        prices = list(100 + np.cumsum(np.random.randn(50) * 0.5))
        result = analyse_prices(prices)
        assert "macd" in result
        assert isinstance(result["macd"], float)

    def test_bollinger_bands(self) -> None:
        prices = list(100 + np.cumsum(np.random.randn(50) * 0.5))
        result = analyse_prices(prices)
        assert "bollinger" in result
        upper, lower = result["bollinger"]
        assert upper >= lower

    def test_insufficient_data(self) -> None:
        """With < 15 prices, should return defaults."""
        result = analyse_prices([100.0, 101.0, 99.0])
        assert result["rsi"] == 50.0

    def test_full_analysis(self) -> None:
        prices = list(100 + np.arange(50) * 0.3)  # uptrend
        result = analyse_prices(prices)
        assert "rsi" in result
        assert "macd" in result
        assert "bollinger" in result
        assert "bb_position" in result
        assert "atr_pct" in result
        assert "trend_strength" in result
        assert "volatility" in result
        # Uptrend should have RSI > 50
        assert result["rsi"] > 50

    def test_numpy_input(self) -> None:
        """Should accept numpy arrays."""
        prices = np.array([100.0 + i * 0.1 for i in range(30)])
        result = analyse_prices(prices)
        assert "rsi" in result
