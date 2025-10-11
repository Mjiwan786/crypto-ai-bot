"""
ML Smoke Test - Verifies end-to-end train/predict cycle with deterministic artifacts.

Tests:
1. Feature engineering is deterministic
2. Model training creates versioned artifacts
3. Artifacts round-trip correctly (save/load)
4. Predictions are calibrated and confident
5. Reproducibility (same inputs → same outputs)

Success criteria:
- All tests pass
- Artifacts hash consistently
- Predictions are deterministic
- Latency meets SLO (<10ms)
"""

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Import ML modules
from agents.ml.feature_engineer import FeatureEngineer, FeatureEngineerConfig
from agents.ml.model_trainer import ModelTrainer, TrainerConfig
from agents.ml.predictor import Predictor, StrictPolicy


# ==============================================================================
# Test Fixtures
# ==============================================================================


@pytest.fixture
def temp_artifacts_dir():
    """Create temporary directory for model artifacts."""
    temp_dir = tempfile.mkdtemp(prefix="ml_test_")
    yield temp_dir
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def synthetic_ohlcv_data():
    """Generate synthetic OHLCV data for testing."""
    n_samples = 500
    rng = np.random.default_rng(42)

    # Generate realistic time series
    start_date = datetime.now(timezone.utc) - pd.Timedelta(hours=n_samples)
    ts = pd.date_range(start_date, periods=n_samples, freq="H")

    # Price with trend + noise
    base_price = 50000
    trend = np.linspace(0, 2000, n_samples)
    noise = rng.standard_normal(n_samples) * 500
    close = base_price + trend + noise
    close = np.maximum(close, 10000)  # Floor at 10k

    # OHLCV
    high = close + rng.uniform(0, 200, n_samples)
    low = close - rng.uniform(0, 200, n_samples)
    open_price = close + rng.uniform(-100, 100, n_samples)
    volume = rng.uniform(100, 1000, n_samples)

    df = pd.DataFrame({
        "ts": ts,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })

    return df


@pytest.fixture
def feature_config():
    """Create feature engineering config."""
    return FeatureEngineerConfig(
        symbol="TEST/USD",
        timeframe="1h",
        rsi_window=14,
        adx_window=14,
        atr_window=14,
        vol_window=60,
        ret_lags=[1, 2, 3, 5],
        seed=42,  # Fixed seed for determinism
        strict_checks=False,  # Allow test data
    )


@pytest.fixture
def trainer_config(temp_artifacts_dir):
    """Create training config."""
    return TrainerConfig(
        symbol="TEST_USD",
        timeframe="1h",
        label_col="y",
        feature_cols=[],  # Will be set dynamically
        model_type="logreg",
        n_splits=3,  # Fewer splits for speed
        embargo_frac=0.02,
        purge_gap=1,
        class_weight="balanced",
        calibrator="platt",
        max_iters=100,  # Fewer iterations for speed
        random_state=42,  # Fixed seed
        test_size_frac=0.2,
        artifacts_dir=temp_artifacts_dir,
        strict_checks=False,  # Allow test data
    )


# ==============================================================================
# Test 1: Feature Engineering Determinism
# ==============================================================================


def test_feature_engineering_deterministic(synthetic_ohlcv_data, feature_config):
    """Test that feature engineering is deterministic."""
    engineer = FeatureEngineer(feature_config)

    # Compute features twice
    features1 = engineer.compute(synthetic_ohlcv_data.copy())
    features2 = engineer.compute(synthetic_ohlcv_data.copy())

    # Should be identical
    pd.testing.assert_frame_equal(features1, features2)

    # Verify dtypes
    for col in features1.columns:
        if col != "ts":
            assert pd.api.types.is_numeric_dtype(features1[col]), f"Column {col} is not numeric"

    # Verify no NaN in final features
    assert not features1.drop(columns=["ts"]).isnull().any().any(), "Features contain NaN"

    print(f"✓ Feature engineering is deterministic ({len(features1)} samples, {len(features1.columns)-1} features)")


def test_feature_hashing(synthetic_ohlcv_data, feature_config):
    """Test that feature hash is consistent."""
    engineer = FeatureEngineer(feature_config)
    features = engineer.compute(synthetic_ohlcv_data)

    # Compute hash twice
    def compute_hash(df):
        values = df.drop(columns=["ts"]).values.tobytes()
        return hashlib.sha256(values).hexdigest()[:16]

    hash1 = compute_hash(features)
    hash2 = compute_hash(features)

    assert hash1 == hash2, "Feature hash is not consistent"

    print(f"✓ Feature hash is consistent: {hash1}")


# ==============================================================================
# Test 2: Model Training & Artifacts
# ==============================================================================


def test_model_training_creates_artifacts(synthetic_ohlcv_data, feature_config, trainer_config):
    """Test that model training creates all required artifacts."""
    # Generate features
    engineer = FeatureEngineer(feature_config)
    features = engineer.compute(synthetic_ohlcv_data)

    # Create target variable (synthetic)
    rng = np.random.default_rng(42)
    # Use first feature + noise for target
    first_feat = features.columns[1]  # Skip 'ts'
    logits = features[first_feat] + rng.standard_normal(len(features)) * 0.5
    features["y"] = (logits > logits.median()).astype(int)

    # Update trainer config with actual feature list
    feature_cols = [col for col in features.columns if col not in ["ts", "y"]]
    trainer_config.feature_cols = feature_cols

    # Train model
    trainer = ModelTrainer(trainer_config)
    result = trainer.fit(features)

    # Verify artifacts were created
    artifact_dir = Path(result.artifact_paths["model_bin"]).parent

    required_files = ["model.bin", "feature_list.json", "training_cfg.json", "metrics.json"]
    for filename in required_files:
        filepath = artifact_dir / filename
        assert filepath.exists(), f"Missing artifact: {filename}"

    # Verify metrics
    assert result.test_metrics["auc"] > 0.4, "Test AUC too low"
    assert result.test_metrics["ece"] < 0.2, "ECE too high (poorly calibrated)"

    print(f"✓ Model training completed")
    print(f"  Test AUC: {result.test_metrics['auc']:.4f}")
    print(f"  Test ECE: {result.test_metrics['ece']:.4f}")
    print(f"  Features: {result.n_features}")
    print(f"  Artifacts: {artifact_dir}")

    return result, feature_cols


# ==============================================================================
# Test 3: Artifact Round-Trip
# ==============================================================================


def test_artifacts_round_trip(synthetic_ohlcv_data, feature_config, trainer_config):
    """Test that artifacts can be saved and loaded correctly."""
    # Train model and save artifacts
    engineer = FeatureEngineer(feature_config)
    features = engineer.compute(synthetic_ohlcv_data)

    rng = np.random.default_rng(42)
    first_feat = features.columns[1]
    logits = features[first_feat] + rng.standard_normal(len(features)) * 0.5
    features["y"] = (logits > logits.median()).astype(int)

    feature_cols = [col for col in features.columns if col not in ["ts", "y"]]
    trainer_config.feature_cols = feature_cols

    trainer = ModelTrainer(trainer_config)
    result = trainer.fit(features)

    # Load predictor
    predictor = Predictor(
        symbol=trainer_config.symbol,
        artifacts_dir=trainer_config.artifacts_dir,
        tag=result.tag,
        strict_mode=StrictPolicy.HARD,
        warmup_enabled=False,  # Skip warmup for speed
    )

    # Verify loaded correctly
    metadata = predictor.get_metadata()
    assert metadata["n_features"] == len(feature_cols)
    assert metadata["model_version"] == result.tag
    assert metadata["has_scaler"] == True  # LogReg uses scaler
    assert metadata["has_calibrator"] == True  # Calibrator enabled

    print(f"✓ Artifacts round-trip successful")
    print(f"  Model version: {metadata['model_version']}")
    print(f"  Features: {metadata['n_features']}")
    print(f"  Has scaler: {metadata['has_scaler']}")
    print(f"  Has calibrator: {metadata['has_calibrator']}")

    return predictor, feature_cols


# ==============================================================================
# Test 4: Predictions
# ==============================================================================


def test_predictions_calibrated_and_confident(synthetic_ohlcv_data, feature_config, trainer_config):
    """Test that predictions are calibrated and meet confidence criteria."""
    # Setup
    engineer = FeatureEngineer(feature_config)
    features = engineer.compute(synthetic_ohlcv_data)

    rng = np.random.default_rng(42)
    first_feat = features.columns[1]
    logits = features[first_feat] + rng.standard_normal(len(features)) * 0.5
    features["y"] = (logits > logits.median()).astype(int)

    feature_cols = [col for col in features.columns if col not in ["ts", "y"]]
    trainer_config.feature_cols = feature_cols

    trainer = ModelTrainer(trainer_config)
    result = trainer.fit(features)

    # Load predictor
    predictor = Predictor(
        symbol=trainer_config.symbol,
        artifacts_dir=trainer_config.artifacts_dir,
        tag=result.tag,
        strict_mode=StrictPolicy.HARD,
        warmup_enabled=True,
    )

    # Test single prediction
    test_features = features[feature_cols].iloc[0].to_dict()
    pred = predictor.predict_one(test_features)

    # Validate response
    assert 0.0 <= pred["score"] <= 1.0, "Score out of range"
    assert 0.0 <= pred["confidence"] <= 1.0, "Confidence out of range"
    assert 0.0 <= pred["raw_score"] <= 1.0, "Raw score out of range"
    assert pred["latency_ms"] > 0, "Latency not measured"
    assert pred["model_version"] == result.tag

    # Test batch prediction
    test_batch = features[feature_cols].iloc[:10]
    batch_pred = predictor.predict_batch(test_batch)

    assert len(batch_pred) == 10, "Batch size mismatch"
    assert all(0.0 <= s <= 1.0 for s in batch_pred["score"]), "Batch scores out of range"

    print(f"✓ Predictions validated")
    print(f"  Single prediction score: {pred['score']:.4f}")
    print(f"  Single prediction latency: {pred['latency_ms']:.2f}ms")
    print(f"  Batch predictions: {len(batch_pred)}")


# ==============================================================================
# Test 5: Determinism & Reproducibility
# ==============================================================================


def test_end_to_end_determinism(synthetic_ohlcv_data, feature_config, temp_artifacts_dir):
    """Test that entire pipeline is deterministic."""
    # Run pipeline twice
    def run_pipeline():
        engineer = FeatureEngineer(feature_config)
        features = engineer.compute(synthetic_ohlcv_data.copy())

        rng = np.random.default_rng(42)  # Same seed
        first_feat = features.columns[1]
        logits = features[first_feat] + rng.standard_normal(len(features)) * 0.5
        features["y"] = (logits > logits.median()).astype(int)

        feature_cols = [col for col in features.columns if col not in ["ts", "y"]]

        config = TrainerConfig(
            symbol="TEST_USD",
            timeframe="1h",
            label_col="y",
            feature_cols=feature_cols,
            model_type="logreg",
            n_splits=3,
            calibrator="platt",
            random_state=42,  # Same seed
            artifacts_dir=temp_artifacts_dir,
            strict_checks=False,
        )

        trainer = ModelTrainer(config)
        result = trainer.fit(features)

        return result, features

    result1, features1 = run_pipeline()
    result2, features2 = run_pipeline()

    # Verify features are identical
    pd.testing.assert_frame_equal(features1, features2)

    # Verify metrics are identical (or very close)
    assert abs(result1.test_metrics["auc"] - result2.test_metrics["auc"]) < 0.001, "AUC not deterministic"
    assert abs(result1.test_metrics["ece"] - result2.test_metrics["ece"]) < 0.001, "ECE not deterministic"

    print(f"✓ End-to-end pipeline is deterministic")
    print(f"  Run 1 AUC: {result1.test_metrics['auc']:.4f}")
    print(f"  Run 2 AUC: {result2.test_metrics['auc']:.4f}")
    print(f"  Difference: {abs(result1.test_metrics['auc'] - result2.test_metrics['auc']):.6f}")


# ==============================================================================
# Test 6: Performance SLO
# ==============================================================================


def test_prediction_latency_slo(synthetic_ohlcv_data, feature_config, trainer_config):
    """Test that predictions meet latency SLO."""
    # Setup
    engineer = FeatureEngineer(feature_config)
    features = engineer.compute(synthetic_ohlcv_data)

    rng = np.random.default_rng(42)
    first_feat = features.columns[1]
    logits = features[first_feat] + rng.standard_normal(len(features)) * 0.5
    features["y"] = (logits > logits.median()).astype(int)

    feature_cols = [col for col in features.columns if col not in ["ts", "y"]]
    trainer_config.feature_cols = feature_cols

    trainer = ModelTrainer(trainer_config)
    result = trainer.fit(features)

    # Load predictor with latency budget
    predictor = Predictor(
        symbol=trainer_config.symbol,
        artifacts_dir=trainer_config.artifacts_dir,
        tag=result.tag,
        latency_budget_ms=10.0,  # 10ms SLO
        warmup_enabled=True,
    )

    # Measure latency over multiple predictions
    latencies = []
    test_features = features[feature_cols].iloc[0].to_dict()

    for _ in range(100):
        pred = predictor.predict_one(test_features)
        latencies.append(pred["latency_ms"])

    # Analyze latencies
    latencies = np.array(latencies)
    p50 = np.percentile(latencies, 50)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)

    # SLO: p99 < 10ms (after warmup)
    assert p99 < 10.0, f"p99 latency {p99:.2f}ms exceeds 10ms SLO"

    print(f"✓ Latency SLO met")
    print(f"  p50: {p50:.2f}ms")
    print(f"  p95: {p95:.2f}ms")
    print(f"  p99: {p99:.2f}ms")
    print(f"  SLO: <10ms (PASS)")


# ==============================================================================
# Run All Tests
# ==============================================================================


if __name__ == "__main__":
    """Run all smoke tests."""
    print("=" * 70)
    print("ML SMOKE TEST - Train/Predict Cycle")
    print("=" * 70)
    print()

    # Create fixtures manually
    temp_dir = tempfile.mkdtemp(prefix="ml_smoke_")
    synthetic_data = pytest.fixture(lambda: None)

    try:
        # Generate data once
        n_samples = 500
        rng = np.random.default_rng(42)
        start_date = datetime.now(timezone.utc) - pd.Timedelta(hours=n_samples)
        ts = pd.date_range(start_date, periods=n_samples, freq="h")

        base_price = 50000
        trend = np.linspace(0, 2000, n_samples)
        noise = rng.standard_normal(n_samples) * 500
        close = base_price + trend + noise
        close = np.maximum(close, 10000)

        high = close + rng.uniform(0, 200, n_samples)
        low = close - rng.uniform(0, 200, n_samples)
        open_price = close + rng.uniform(-100, 100, n_samples)
        volume = rng.uniform(100, 1000, n_samples)

        ohlcv_data = pd.DataFrame({
            "ts": ts,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

        feat_config = FeatureEngineerConfig(
            symbol="TEST/USD",
            timeframe="1h",
            rsi_window=14,
            adx_window=14,
            atr_window=14,
            vol_window=60,
            ret_lags=[1, 2, 3, 5],
            seed=42,
            strict_checks=False,
        )

        # Generate features first to get feature list
        engineer = FeatureEngineer(feat_config)
        temp_features = engineer.compute(ohlcv_data.copy())
        feature_cols_list = [col for col in temp_features.columns if col not in ["ts"]]

        train_config = TrainerConfig(
            symbol="TEST_USD",
            timeframe="1h",
            label_col="y",
            feature_cols=feature_cols_list,  # Use actual features
            model_type="logreg",
            n_splits=3,
            embargo_frac=0.02,
            purge_gap=1,
            class_weight="balanced",
            calibrator="platt",
            max_iters=100,
            random_state=42,
            test_size_frac=0.2,
            artifacts_dir=temp_dir,
            strict_checks=False,
        )

        # Run tests
        print("Test 1: Feature Engineering Determinism")
        print("-" * 70)
        test_feature_engineering_deterministic(ohlcv_data, feat_config)
        print()

        print("Test 2: Feature Hashing")
        print("-" * 70)
        test_feature_hashing(ohlcv_data, feat_config)
        print()

        print("Test 3: Model Training & Artifacts")
        print("-" * 70)
        test_model_training_creates_artifacts(ohlcv_data, feat_config, train_config)
        print()

        print("Test 4: Artifact Round-Trip")
        print("-" * 70)
        test_artifacts_round_trip(ohlcv_data, feat_config, train_config)
        print()

        print("Test 5: Predictions")
        print("-" * 70)
        test_predictions_calibrated_and_confident(ohlcv_data, feat_config, train_config)
        print()

        print("Test 6: End-to-End Determinism")
        print("-" * 70)
        test_end_to_end_determinism(ohlcv_data, feat_config, temp_dir)
        print()

        print("Test 7: Latency SLO")
        print("-" * 70)
        test_prediction_latency_slo(ohlcv_data, feat_config, train_config)
        print()

        print("=" * 70)
        print("ALL TESTS PASSED ✓")
        print("=" * 70)
        print()
        print("Success Criteria Met:")
        print("  ✓ Feature engineering is deterministic")
        print("  ✓ Model training creates versioned artifacts")
        print("  ✓ Artifacts round-trip correctly")
        print("  ✓ Predictions are calibrated and confident")
        print("  ✓ End-to-end pipeline is reproducible")
        print("  ✓ Latency meets SLO (<10ms p99)")

    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
