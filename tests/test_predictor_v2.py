"""Tests for agents.ml.predictor (Sprint 4B replacement)."""
import numpy as np
import pytest

from agents.ml.predictor import StrategyPredictor
from trainer.data_exporter import generate_synthetic_ohlcv


class TestStrategyPredictorV2:
    def test_init_without_model(self) -> None:
        """Should init without crashing even if model doesn't exist."""
        predictor = StrategyPredictor(model_path="/nonexistent/model.joblib")
        assert predictor.is_loaded is False

    def test_predict_strategy_returns_none_without_model(self) -> None:
        predictor = StrategyPredictor(model_path="/nonexistent/model.joblib")
        result = predictor.predict_strategy()
        assert result is None

    def test_predict_signal_quality_without_model(self) -> None:
        predictor = StrategyPredictor(model_path="/nonexistent/model.joblib")
        ohlcv = generate_synthetic_ohlcv(n_candles=50)
        result = predictor.predict_signal_quality(ohlcv, "long", 0.7)
        assert result["should_trade"] is True  # Pass-through when no model
        assert result["ml_score"] == -1.0
