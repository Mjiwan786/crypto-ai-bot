"""Tests for trainer.models.xgboost_signal.XGBoostSignalClassifier."""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from trainer.models.xgboost_signal import XGBoostSignalClassifier, XGBoostSignalConfig


def _make_synthetic_features(
    n: int = 1000, n_features: int = 30, seed: int = 42
) -> tuple:
    """Create synthetic features with a simple decision boundary."""
    rng = np.random.RandomState(seed)
    names = [f"feature_{i}" for i in range(n_features)]
    X = pd.DataFrame(rng.randn(n, n_features), columns=names)
    y = ((X.iloc[:, 0] + X.iloc[:, 1]) > 0).astype(int).values
    return X, y, names


class TestXGBoostSignalClassifier:
    def test_train_basic(self) -> None:
        X, y, _ = _make_synthetic_features()
        model = XGBoostSignalClassifier()
        metrics = model.train(X, y)
        assert "accuracy" in metrics
        assert "precision" in metrics
        assert "recall" in metrics
        assert "f1" in metrics
        assert "auc" in metrics
        assert 0.0 <= metrics["accuracy"] <= 1.0

    def test_predict_proba_range(self) -> None:
        X, y, _ = _make_synthetic_features()
        model = XGBoostSignalClassifier()
        model.train(X, y)
        p = model.predict_proba(X.iloc[0].values)
        assert isinstance(p, float)
        assert 0.0 <= p <= 1.0

    def test_predict_proba_2d_input(self) -> None:
        X, y, _ = _make_synthetic_features()
        model = XGBoostSignalClassifier()
        model.train(X, y)
        p = model.predict_proba(X.iloc[[0]].values)
        assert 0.0 <= p <= 1.0

    def test_save_load_roundtrip(self) -> None:
        X, y, _ = _make_synthetic_features()
        model = XGBoostSignalClassifier()
        model.train(X, y)
        p_before = model.predict_proba(X.iloc[0].values)

        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as f:
            tmp_path = f.name
        try:
            model.save(tmp_path)
            loaded = XGBoostSignalClassifier.load(tmp_path)
            p_after = loaded.predict_proba(X.iloc[0].values)
            assert abs(p_before - p_after) < 1e-6
        finally:
            os.unlink(tmp_path)

    def test_feature_importance(self) -> None:
        X, y, names = _make_synthetic_features()
        model = XGBoostSignalClassifier()
        model.train(X, y)
        fi = model.feature_importance()
        assert isinstance(fi, pd.DataFrame)
        assert len(fi) == 30
        assert "feature" in fi.columns
        assert "importance" in fi.columns
        # Should not be all zeros
        assert fi["importance"].sum() > 0

    def test_class_imbalance(self) -> None:
        """90/10 class split should auto-adjust scale_pos_weight."""
        rng = np.random.RandomState(42)
        X = pd.DataFrame(rng.randn(1000, 10), columns=[f"f{i}" for i in range(10)])
        y = np.zeros(1000, dtype=int)
        y[:100] = 1  # 10% positive
        model = XGBoostSignalClassifier()
        model.train(X, y)
        assert model.config.scale_pos_weight > 1.0

    def test_training_metadata(self) -> None:
        X, y, _ = _make_synthetic_features()
        model = XGBoostSignalClassifier()
        model.train(X, y)
        meta = model.training_metadata
        assert "training_date" in meta
        assert "feature_names" in meta
        assert "n_train_samples" in meta
        assert "model_version" in meta
        assert meta["n_train_samples"] == 1000

    def test_predict_before_train_raises(self) -> None:
        model = XGBoostSignalClassifier()
        with pytest.raises(RuntimeError, match="not trained"):
            model.predict_proba(np.zeros(30))

    def test_save_before_train_raises(self) -> None:
        model = XGBoostSignalClassifier()
        with pytest.raises(RuntimeError, match="not trained"):
            model.save("/tmp/test.joblib")
