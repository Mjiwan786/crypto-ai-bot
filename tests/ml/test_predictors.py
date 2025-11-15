"""
Tests for ml/predictors.py

Validates deterministic behavior of ML ensemble confidence gate.
Per Step 7 requirements:
- Deterministic predictions with fixed seed
- BasePredictor interface compliance
- LogitPredictor, TreePredictor, EnsemblePredictor behavior
- Feature computation from OHLCV context
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_ohlcv():
    """Sample OHLCV data for feature extraction"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=100, freq="5min")

    # Generate deterministic price series
    closes = 50000 + np.cumsum(np.random.randn(100) * 100)

    df = pd.DataFrame({
        "timestamp": dates,
        "open": closes + np.random.randn(100) * 50,
        "high": closes + np.abs(np.random.randn(100)) * 100,
        "low": closes - np.abs(np.random.randn(100)) * 100,
        "close": closes,
        "volume": np.abs(np.random.randn(100)) * 100,
    })

    return df


@pytest.fixture
def market_ctx(sample_ohlcv):
    """Market context dict for prediction"""
    return {
        "ohlcv_df": sample_ohlcv,
        "current_price": float(sample_ohlcv["close"].iloc[-1]),
        "timeframe": "5m",
    }


class TestBasePredictor:
    """Test BasePredictor abstract interface"""

    def test_base_predictor_interface_exists(self):
        """BasePredictor should define .fit() and .predict_proba() interface"""
        from ml.predictors import BasePredictor

        assert hasattr(BasePredictor, "fit")
        assert hasattr(BasePredictor, "predict_proba")

    def test_base_predictor_has_seed(self):
        """BasePredictor should accept deterministic seed"""
        from ml.predictors import LogitPredictor

        # Use concrete class to test abstract interface
        predictor = LogitPredictor(seed=42)
        assert predictor.seed == 42


class TestLogitPredictor:
    """Test LogitPredictor (logistic regression on simple features)"""

    def test_logit_predictor_init(self):
        """LogitPredictor should initialize with seed"""
        from ml.predictors import LogitPredictor

        predictor = LogitPredictor(seed=42)
        assert predictor.seed == 42

    def test_logit_predictor_deterministic(self, market_ctx):
        """LogitPredictor should produce deterministic predictions"""
        from ml.predictors import LogitPredictor

        pred1 = LogitPredictor(seed=42)
        pred2 = LogitPredictor(seed=42)

        # Fit with dummy data (no actual training, just initialization)
        pred1.fit(market_ctx)
        pred2.fit(market_ctx)

        # Same seed → same predictions
        prob1 = pred1.predict_proba(market_ctx)
        prob2 = pred2.predict_proba(market_ctx)

        assert abs(prob1 - prob2) < 1e-6, "Same seed should produce identical predictions"

    def test_logit_predictor_returns_probability(self, market_ctx):
        """LogitPredictor should return probability in [0, 1]"""
        from ml.predictors import LogitPredictor

        predictor = LogitPredictor(seed=42)
        predictor.fit(market_ctx)
        prob = predictor.predict_proba(market_ctx)

        assert 0.0 <= prob <= 1.0, f"Probability must be in [0,1], got {prob}"

    def test_logit_predictor_uses_features(self, market_ctx):
        """LogitPredictor should use returns, RSI, ADX, slope features"""
        from ml.predictors import LogitPredictor

        predictor = LogitPredictor(seed=42)

        # Fit should compute features
        predictor.fit(market_ctx)

        # Should have feature names
        assert hasattr(predictor, "feature_names_")
        assert "returns" in predictor.feature_names_
        assert "rsi" in predictor.feature_names_
        assert "adx" in predictor.feature_names_
        assert "slope" in predictor.feature_names_


class TestTreePredictor:
    """Test TreePredictor (decision tree on simple features)"""

    def test_tree_predictor_init(self):
        """TreePredictor should initialize with seed"""
        from ml.predictors import TreePredictor

        predictor = TreePredictor(seed=42)
        assert predictor.seed == 42

    def test_tree_predictor_deterministic(self, market_ctx):
        """TreePredictor should produce deterministic predictions"""
        from ml.predictors import TreePredictor

        pred1 = TreePredictor(seed=42)
        pred2 = TreePredictor(seed=42)

        pred1.fit(market_ctx)
        pred2.fit(market_ctx)

        prob1 = pred1.predict_proba(market_ctx)
        prob2 = pred2.predict_proba(market_ctx)

        assert abs(prob1 - prob2) < 1e-6, "Same seed should produce identical predictions"

    def test_tree_predictor_returns_probability(self, market_ctx):
        """TreePredictor should return probability in [0, 1]"""
        from ml.predictors import TreePredictor

        predictor = TreePredictor(seed=42)
        predictor.fit(market_ctx)
        prob = predictor.predict_proba(market_ctx)

        assert 0.0 <= prob <= 1.0, f"Probability must be in [0,1], got {prob}"


class TestEnsemblePredictor:
    """Test EnsemblePredictor (mean vote of multiple models)"""

    def test_ensemble_predictor_init(self):
        """EnsemblePredictor should accept list of models"""
        from ml.predictors import EnsemblePredictor, LogitPredictor, TreePredictor

        models = [LogitPredictor(seed=42), TreePredictor(seed=42)]
        ensemble = EnsemblePredictor(models=models, seed=42)

        assert len(ensemble.models) == 2

    def test_ensemble_predictor_mean_vote(self, market_ctx):
        """EnsemblePredictor should return mean of model predictions"""
        from ml.predictors import EnsemblePredictor, LogitPredictor, TreePredictor

        logit = LogitPredictor(seed=42)
        tree = TreePredictor(seed=42)
        ensemble = EnsemblePredictor(models=[logit, tree], seed=42)

        # Fit all models
        logit.fit(market_ctx)
        tree.fit(market_ctx)
        ensemble.fit(market_ctx)

        # Get individual predictions
        prob_logit = logit.predict_proba(market_ctx)
        prob_tree = tree.predict_proba(market_ctx)
        prob_ensemble = ensemble.predict_proba(market_ctx)

        # Ensemble should be mean
        expected_mean = (prob_logit + prob_tree) / 2.0
        assert abs(prob_ensemble - expected_mean) < 1e-6

    def test_ensemble_predictor_deterministic(self, market_ctx):
        """EnsemblePredictor should be deterministic with fixed seeds"""
        from ml.predictors import EnsemblePredictor, LogitPredictor, TreePredictor

        ens1 = EnsemblePredictor(
            models=[LogitPredictor(seed=42), TreePredictor(seed=42)],
            seed=42
        )
        ens2 = EnsemblePredictor(
            models=[LogitPredictor(seed=42), TreePredictor(seed=42)],
            seed=42
        )

        ens1.fit(market_ctx)
        ens2.fit(market_ctx)

        prob1 = ens1.predict_proba(market_ctx)
        prob2 = ens2.predict_proba(market_ctx)

        assert abs(prob1 - prob2) < 1e-6

    def test_ensemble_predictor_empty_models(self):
        """EnsemblePredictor should handle empty model list gracefully"""
        from ml.predictors import EnsemblePredictor

        with pytest.raises((ValueError, AssertionError)):
            EnsemblePredictor(models=[], seed=42)
