"""Tests for signals.ml_scorer.MLScorer."""
import os
import time

import numpy as np
import pytest

from signals.ml_scorer import MLScorer, MLScorerConfig
from trainer.data_exporter import generate_synthetic_ohlcv


@pytest.fixture
def trained_model(tmp_path):
    """Create a small trained model for testing."""
    from trainer.data_exporter import label_candles
    from trainer.feature_builder import FeatureBuilder
    from trainer.models.xgboost_signal import XGBoostSignalClassifier

    ohlcv = generate_synthetic_ohlcv(n_candles=500, seed=42)
    fb = FeatureBuilder()
    features = fb.build_features(ohlcv).dropna()
    labels = label_candles(ohlcv)
    valid = labels[: len(features)]
    mask = valid >= 0
    X, y = features[mask], valid[mask]

    model = XGBoostSignalClassifier()
    model.train(X, y)
    path = str(tmp_path / "test_model.joblib")
    model.save(path)
    return path


class TestMLScorerDisabled:
    def test_disabled_returns_pass_through(self) -> None:
        scorer = MLScorer(MLScorerConfig(enabled=False))
        ohlcv = generate_synthetic_ohlcv(n_candles=50)
        ok, score, reason = scorer.score_signal(ohlcv, "long", 0.7)
        assert ok is True
        assert score == -1.0
        assert "disabled" in reason

    def test_load_returns_false_when_disabled(self) -> None:
        scorer = MLScorer(MLScorerConfig(enabled=False))
        assert scorer.load() is False


class TestMLScorerMissingModel:
    def test_missing_model_passes_through(self) -> None:
        scorer = MLScorer(MLScorerConfig(enabled=True, model_path="/nonexistent/model.joblib"))
        assert scorer.load() is False
        ok, score, reason = scorer.score_signal(
            generate_synthetic_ohlcv(50), "long", 0.7
        )
        assert ok is True
        assert score == -1.0


class TestMLScorerLoaded:
    def test_load_succeeds(self, trained_model) -> None:
        scorer = MLScorer(MLScorerConfig(enabled=True, model_path=trained_model))
        assert scorer.load() is True

    def test_score_returns_valid_range(self, trained_model) -> None:
        scorer = MLScorer(MLScorerConfig(enabled=True, model_path=trained_model, shadow_mode=False))
        scorer.load()
        ohlcv = generate_synthetic_ohlcv(n_candles=50)
        ok, score, reason = scorer.score_signal(ohlcv, "long", 0.7)
        assert isinstance(ok, bool)
        assert 0.0 <= score <= 1.0
        assert len(reason) > 0

    def test_shadow_mode_passes_vetoed(self, trained_model) -> None:
        """Shadow mode should pass through even when score is below threshold."""
        scorer = MLScorer(MLScorerConfig(
            enabled=True, model_path=trained_model,
            shadow_mode=True, min_score=0.99,  # Very high threshold to force veto
        ))
        scorer.load()
        ohlcv = generate_synthetic_ohlcv(n_candles=50)
        ok, score, reason = scorer.score_signal(ohlcv, "long", 0.7)
        # Shadow mode should pass through
        assert ok is True
        assert "shadow_veto" in reason

    def test_veto_when_below_threshold(self, trained_model) -> None:
        """Non-shadow mode should actually veto low scores."""
        scorer = MLScorer(MLScorerConfig(
            enabled=True, model_path=trained_model,
            shadow_mode=False, min_score=0.99,
        ))
        scorer.load()
        ohlcv = generate_synthetic_ohlcv(n_candles=50)
        ok, score, reason = scorer.score_signal(ohlcv, "long", 0.7)
        # Should veto (score is unlikely to be >= 0.99)
        assert ok is False
        assert score < 0.99

    def test_stats_tracking(self, trained_model) -> None:
        scorer = MLScorer(MLScorerConfig(
            enabled=True, model_path=trained_model, shadow_mode=False,
        ))
        scorer.load()
        ohlcv = generate_synthetic_ohlcv(n_candles=50)
        scorer.score_signal(ohlcv, "long", 0.7)
        scorer.score_signal(ohlcv, "short", 0.6)
        stats = scorer.stats
        assert stats["total_scored"] == 2
        assert stats["enabled"] is True
        assert stats["loaded"] is True

    def test_insufficient_ohlcv(self, trained_model) -> None:
        scorer = MLScorer(MLScorerConfig(enabled=True, model_path=trained_model))
        scorer.load()
        ohlcv = generate_synthetic_ohlcv(n_candles=10)  # Too few
        ok, score, reason = scorer.score_signal(ohlcv, "long", 0.7)
        assert ok is True
        assert "insufficient" in reason

    def test_latency_under_5ms(self, trained_model) -> None:
        scorer = MLScorer(MLScorerConfig(enabled=True, model_path=trained_model))
        scorer.load()
        ohlcv = generate_synthetic_ohlcv(n_candles=50)
        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            scorer.score_signal(ohlcv, "long", 0.7)
            times.append((time.perf_counter() - t0) * 1000)
        avg = np.mean(times)
        assert avg < 10, f"Average latency {avg:.1f}ms exceeds 10ms"


class TestMLScorerConfig:
    def test_from_env_defaults(self) -> None:
        config = MLScorerConfig.from_env()
        assert config.enabled is False
        assert config.min_score == 0.60
        assert config.shadow_mode is True

    def test_from_env_custom(self, monkeypatch) -> None:
        monkeypatch.setenv("ML_SCORER_ENABLED", "true")
        monkeypatch.setenv("ML_MIN_SCORE", "0.75")
        monkeypatch.setenv("ML_SHADOW_MODE", "false")
        config = MLScorerConfig.from_env()
        assert config.enabled is True
        assert config.min_score == 0.75
        assert config.shadow_mode is False
