"""Tests for ai_engine.regime_detector.macro_analyzer (Sprint 4B replacement)."""
import pytest

from ai_engine.regime_detector.macro_analyzer import MacroAnalyzer, analyse_macro


class TestMacroAnalyzer:
    def test_default_regime(self) -> None:
        analyzer = MacroAnalyzer()
        result = analyzer.compute_market_regime()
        assert result["btc_dominance"] == 0.5
        assert result["macro_regime"] == "neutral"

    def test_classify_risk_on(self) -> None:
        result = MacroAnalyzer._classify_regime({
            "exchange_netflow_zscore": -2.0,
            "fear_greed_normalized": 0.8,
        })
        assert result == "risk_on"

    def test_classify_risk_off(self) -> None:
        result = MacroAnalyzer._classify_regime({
            "exchange_netflow_zscore": 2.0,
            "fear_greed_normalized": 0.2,
        })
        assert result == "risk_off"

    def test_classify_neutral(self) -> None:
        result = MacroAnalyzer._classify_regime({
            "exchange_netflow_zscore": 0.0,
            "fear_greed_normalized": 0.5,
        })
        assert result == "neutral"

    def test_legacy_analyse_macro(self) -> None:
        """Legacy function interface should still work."""
        result = analyse_macro({})
        assert "growth" in result
        assert "inflation" in result
