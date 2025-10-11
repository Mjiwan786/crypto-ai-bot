# ML Model Artifacts - Documentation

## Overview

This directory contains versioned ML model artifacts for crypto trading predictions. All models are trained with deterministic, reproducible pipelines and include comprehensive metadata for traceability.

## Directory Structure

```
models/
├── README.md                    # This file
├── {SYMBOL}/                    # Per-symbol models (e.g., BTC_USD, ETH_USD)
│   ├── CURRENT.txt              # Points to current production model version
│   └── {TIMESTAMP}/             # Versioned model artifacts
│       ├── model.bin            # Serialized model (joblib)
│       ├── feature_list.json    # Ordered list of required features
│       ├── scaler.pkl           # Feature scaler (optional)
│       ├── calibrator.pkl       # Probability calibrator (optional)
│       ├── training_cfg.json    # Training configuration + versions
│       ├── metrics.json         # Training & validation metrics
│       ├── feature_importance.json  # Feature importance scores
│       └── manifest.json        # Content hashes + metadata
```

## Artifact Layout

### Required Files

#### 1. `model.bin`
Serialized ML model (joblib format).

**Supported Models:**
- `sklearn.linear_model.LogisticRegression`
- `sklearn.ensemble.RandomForestClassifier`
- `xgboost.XGBClassifier`
- `lightgbm.LGBMClassifier`
- `catboost.CatBoostClassifier` (via calibration wrapper)

**Requirements:**
- Must support `predict_proba()` with 2-class output
- Must have consistent feature count with `feature_list.json`

#### 2. `feature_list.json`
Ordered list of feature names required for predictions.

**Format:**
```json
[
  "ret_1",
  "ret_2",
  "rsi_14",
  "adx_14",
  "atr_14",
  "vol_realized_60",
  ...
]
```

**Rules:**
- Features must appear in exact order used during training
- Feature names must match those from `feature_engineer.py`
- Missing features in prediction input default to 0.0 (with warning)

### Optional Files

#### 3. `scaler.pkl` (optional)
Feature scaler for normalization.

**When Used:**
- Required for LogisticRegression models
- Optional for tree-based models (XGBoost, LightGBM)

**Format:**
- `sklearn.preprocessing.StandardScaler` (most common)
- `sklearn.preprocessing.MinMaxScaler`
- `sklearn.preprocessing.RobustScaler`

#### 4. `calibrator.pkl` (optional)
Probability calibrator for improved confidence estimates.

**Calibration Methods:**
- **Platt Scaling** (`LogisticRegression`): Fits sigmoid to raw probabilities
- **Isotonic Regression** (`IsotonicRegression`): Non-parametric monotonic mapping

**When Used:**
- Recommended for all production models
- Required for high-stakes decisions where confidence matters
- Trained on out-of-fold predictions to avoid overfitting

#### 5. `training_cfg.json`
Training configuration and environment metadata.

**Contents:**
```json
{
  "symbol": "BTC/USD",
  "timeframe": "1h",
  "label_col": "y",
  "feature_cols": ["ret_1", "rsi_14", ...],
  "model_type": "logreg",
  "n_splits": 5,
  "embargo_frac": 0.02,
  "purge_gap": 2,
  "class_weight": "balanced",
  "calibrator": "platt",
  "calibration_input": "proba",
  "random_state": 17,
  "feature_list_sha256": "abc123...",
  "versions": {
    "python": "3.11.0",
    "numpy": "1.26.0",
    "pandas": "2.1.0",
    "sklearn": "1.3.0",
    "xgboost": "2.0.0",
    "lightgbm": "4.0.0"
  },
  "warnings": []
}
```

#### 6. `metrics.json`
Training and validation metrics.

**Contents:**
```json
{
  "cv_metrics": {
    "auc_mean": 0.7523,
    "auc_std": 0.0234,
    "ap_mean": 0.6841,
    "logloss_mean": 0.5432,
    "ece_mean": 0.0345
  },
  "test_metrics": {
    "auc": 0.7612,
    "ap": 0.6934,
    "logloss": 0.5301,
    "ece": 0.0312,
    "precision": 0.6523,
    "recall": 0.7123,
    "tp": 142,
    "fp": 76,
    "tn": 198,
    "fn": 84
  },
  "training_time_seconds": 12.456,
  "n_samples": 2000,
  "n_features": 25,
  "class_distribution": {
    "train": [0.48, 0.52],
    "test": [0.47, 0.53]
  }
}
```

**Metrics Explained:**
- **AUC** (Area Under ROC Curve): Model's ability to rank predictions
- **AP** (Average Precision): Precision-recall curve summary
- **LogLoss** (Log Loss): Probabilistic prediction quality
- **ECE** (Expected Calibration Error): Calibration quality (lower is better)
- **Precision/Recall**: Classification metrics at 0.5 threshold

#### 7. `feature_importance.json` (optional)
Normalized feature importance scores.

**Format:**
```json
{
  "ret_1": 0.1523,
  "rsi_14": 0.1234,
  "adx_14": 0.0987,
  "atr_14": 0.0876,
  ...
}
```

**Extraction Methods:**
- **Linear Models**: Absolute coefficient values
- **Tree Models**: Gini importance or gain
- Normalized to sum to 1.0

#### 8. `manifest.json` (optional but recommended)
Content hashes and metadata for artifact integrity.

**Format:**
```json
{
  "model_bin_sha256": "abc123...",
  "feature_list_json_sha256": "def456...",
  "scaler_pkl_sha256": "ghi789...",
  "calibrator_pkl_sha256": "jkl012...",
  "trainer_version": "v2.1.0",
  "feature_schema_version": "v1.0.0",
  "git_commit": "a1b2c3d4",
  "created_at": "2025-01-15T10:30:00Z",
  "approved_by": "model-ops-team"
}
```

**Uses:**
- Verify artifact integrity on load
- Detect tampering or corruption
- Track model provenance

## Model Versioning

### Version Format: `YYYY-MM-DD_HHMMSS`

**Example:** `2025-01-15_103045`

**Properties:**
- **Lexicographically sortable**: Newest models sort last
- **Timestamp-based**: Reflects training time (UTC)
- **Deterministic**: Same config + data → same model (given fixed seed)

### Content Hashing

Models are identified by content hash (config + data):

```python
config_hash = sha256(json.dumps(config, sort_keys=True))
data_hash = sha256(X.tobytes() + y.tobytes())
model_hash = sha256(f"{config_hash}_{data_hash}")[:16]
```

**Properties:**
- **Deterministic**: Same inputs → same hash
- **Collision-resistant**: SHA256 provides strong uniqueness
- **Compact**: 16-char hex string for readability

### CURRENT.txt

Points to the active production model version:

```
2025-01-15_103045
```

**Usage:**
```python
from agents.ml.predictor import Predictor

# Load current production model
predictor = Predictor(symbol="BTC_USD")  # Reads CURRENT.txt

# Load specific version
predictor = Predictor(symbol="BTC_USD", tag="2025-01-15_103045")
```

## Training Pipeline

### 1. Feature Engineering (`feature_engineer.py`)

**Key Features:**
- Deterministic with fixed seeds
- Left-aligned (no lookahead)
- Explicit dtypes (no implicit conversions)
- No inplace operations

**Example:**
```python
from agents.ml.feature_engineer import FeatureEngineer, FeatureEngineerConfig

config = FeatureEngineerConfig(
    symbol="BTC/USD",
    timeframe="15m",
    rsi_window=14,
    adx_window=14,
    seed=17
)

engineer = FeatureEngineer(config)
features = engineer.compute(ohlcv_df)  # Pure function, deterministic
```

### 2. Model Training (`model_trainer.py`)

**Key Features:**
- Time-series aware (purged/embargo CV)
- Class-balanced weighting
- Probability calibration
- Comprehensive metrics

**Example:**
```python
from agents.ml.model_trainer import ModelTrainer, TrainerConfig

config = TrainerConfig(
    symbol="BTC/USD",
    timeframe="1h",
    label_col="y",
    feature_cols=feature_list,
    model_type="logreg",
    n_splits=5,
    embargo_frac=0.02,
    calibrator="platt",
    random_state=17
)

trainer = ModelTrainer(config)
result = trainer.fit(features_df)

# Artifacts saved to: models/BTC_USD/{timestamp}/
print(f"Model saved: {result.artifact_paths['model_bin']}")
print(f"Test AUC: {result.test_metrics['auc']:.4f}")
```

### 3. Prediction (`predictor.py`)

**Key Features:**
- Sub-10ms latency SLO
- Thread-safe loading
- Calibrated probabilities
- Confidence scores

**Example:**
```python
from agents.ml.predictor import Predictor

predictor = Predictor(
    symbol="BTC_USD",
    strict_mode="hard",  # Strict validation
    warmup_enabled=True,
    latency_budget_ms=10.0
)

# Single prediction
features = {"ret_1": 0.01, "rsi_14": 65.3, ...}
result = predictor.predict_one(features)

print(f"Score: {result['score']:.4f}")  # Calibrated probability
print(f"Confidence: {result['confidence']:.4f}")
print(f"Latency: {result['latency_ms']:.2f}ms")
```

## Deployment Checklist

### Pre-Deployment

- [ ] Train model with production config
- [ ] Verify CV AUC > 0.65 (or domain-specific threshold)
- [ ] Verify test ECE < 0.05 (well-calibrated)
- [ ] Check feature importance (no single feature dominance)
- [ ] Review warnings in `training_cfg.json`
- [ ] Generate `manifest.json` with content hashes
- [ ] Test predictions with sample data

### Deployment

- [ ] Copy artifacts to production directory
- [ ] Update `CURRENT.txt` to new version
- [ ] Verify hash integrity with `manifest.json`
- [ ] Run smoke test with `test_ml_smoke.py`
- [ ] Monitor prediction latency (<10ms p99)
- [ ] Monitor prediction distribution (no drift)

### Post-Deployment

- [ ] Log prediction metrics (latency, throughput)
- [ ] Monitor model performance (AUC, ECE)
- [ ] Set up alerts for prediction failures
- [ ] Schedule periodic retraining (weekly/monthly)

## Troubleshooting

### Model Won't Load

**Error:** `ArtifactMissing: Model file not found`

**Solution:**
1. Check `models/{SYMBOL}/` directory exists
2. Verify `CURRENT.txt` points to valid timestamp
3. Ensure `model.bin` and `feature_list.json` exist

### Feature Mismatch

**Error:** `SchemaMismatch: Missing required features`

**Solution:**
1. Check feature_list.json matches training
2. Ensure feature engineering uses same config
3. Use `strict_mode="coerce"` to fill missing features with 0.0

### Slow Predictions

**Warning:** `Latency budget exceeded: 15.3ms > 10.0ms`

**Solution:**
1. Check model complexity (tree depth, n_estimators)
2. Reduce feature count if possible
3. Use lighter model type (LogReg vs XGBoost)
4. Disable warmup if not needed

### Hash Mismatch

**Error:** `HashMismatch: expected abc123, got def456`

**Solution:**
1. Regenerate manifest.json
2. Check for file corruption
3. Verify no manual edits to artifacts

## Best Practices

### 1. Deterministic Training

```python
# Always set random_state
config = TrainerConfig(
    random_state=17,  # Fixed seed
    strict_checks=True
)

# Features must be deterministic
engineer = FeatureEngineer(FeatureEngineerConfig(seed=17))
```

### 2. Time-Series Safety

```python
# Use purged/embargo CV
config = TrainerConfig(
    n_splits=5,
    embargo_frac=0.02,  # 2% embargo after validation
    purge_gap=2,  # Purge 2 bars around validation
)
```

### 3. Calibration

```python
# Always calibrate for production
config = TrainerConfig(
    calibrator="platt",  # or "isotonic"
    calibration_input="proba"
)
```

### 4. Monitoring

```python
# Log predictions for monitoring
result = predictor.predict_one(features)
logger.info("Prediction", extra={
    "symbol": "BTC_USD",
    "score": result["score"],
    "latency_ms": result["latency_ms"],
    "model_version": result["model_version"]
})
```

## Environment Setup

### Conda Environment

```bash
# Activate crypto-bot environment
conda activate crypto-bot

# Required packages
pip install scikit-learn>=1.3.0
pip install xgboost>=2.0.0
pip install lightgbm>=4.0.0
pip install pandas>=2.1.0
pip install numpy>=1.26.0
pip install joblib>=1.3.0
```

### Redis Connection (Optional)

For distributed model serving:

```bash
redis-cli -u redis://default:inwjuBWkh4rAtGnbQkLBuPkHXSmfokn8@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls
```

## References

- Feature Engineering: `agents/ml/feature_engineer.py`
- Model Training: `agents/ml/model_trainer.py`
- Prediction: `agents/ml/predictor.py`
- Smoke Test: `tests/test_ml_smoke.py`
