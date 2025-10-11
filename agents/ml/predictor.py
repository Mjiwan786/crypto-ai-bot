"""
Production-ready ML predictor module for crypto-ai-bot.

Loads trained model artifacts and provides real-time predictions with sub-10ms latency
for high-frequency crypto trading operations.

Key guarantees:
- Deterministic predictions with reproducible results (thread caps, fixed pipelines)
- Thread-safe model loading and stats accounting
- Comprehensive input validation and robust error handling
- Security hardening (path constraints, module allowlist, manifest hashing)
- Contracts for calibration input ("proba" | "logit") and feature schema
- Positive-class index correctness (no silent label inversions)
- Structured logging + pluggable metrics hooks
- Support for sklearn, XGBoost, LightGBM, CatBoost models
- Optional scaling and calibration with manifest validation
- Production-grade error handling and performance monitoring
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

# ------------------------
# Determinism: cap threads
# ------------------------
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

logger = logging.getLogger(__name__)

# ------------------------
# Security constraints
# ------------------------
_SYMBOL_RE = re.compile(r"^[A-Z0-9:_-]{2,40}$", re.ASCII)
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$", re.ASCII)

ALLOWED_MODEL_MODULES = {
    "sklearn.",
    "xgboost.",
    "lightgbm.",
    "catboost.",
}


# ------------------------
# Errors
# ------------------------
class PredictorError(Exception):
    code: str

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class ArtifactMissing(PredictorError):
    def __init__(self, message: str):
        super().__init__(message, "ARTIFACT_MISSING")


class HashMismatch(PredictorError):
    def __init__(self, message: str):
        super().__init__(message, "HASH_MISMATCH")


class SchemaMismatch(PredictorError):
    def __init__(self, message: str):
        super().__init__(message, "SCHEMA_MISMATCH")


class PredictFailed(PredictorError):
    def __init__(self, message: str):
        super().__init__(message, "PREDICT_FAILED")


# ------------------------
# Metrics (pluggable)
# ------------------------
class Metrics:
    """No-op metrics adapter. Replace with Prometheus or StatsD in prod."""

    def observe_latency(
        self, symbol: str, version: str, latency_ms: float, batch: bool = False
    ) -> None:
        pass

    def inc_error(self, symbol: str, version: str, reason: str) -> None:
        pass

    def inc_count(self, symbol: str, version: str, n: int = 1) -> None:
        pass


# ------------------------
# Strict policy
# ------------------------
class StrictPolicy(str, Enum):
    HARD = "hard"  # raise on missing/extra/NaN
    WARN = "warn"  # log warning, coerce to 0.0
    COERCE = "coerce"  # silently coerce to 0.0


# ------------------------
# Pydantic Schemas
# ------------------------
class PredictorConfig(BaseModel):
    symbol: str = Field(..., description="Trading symbol (e.g., BTC_USD)")
    artifacts_dir: str = Field(default="models", description="Directory containing model artifacts")
    tag: Optional[str] = Field(default=None, description="Specific model version tag")
    # Backward-compat: 'strict' boolean maps to strict_mode (default HARD if True else WARN)
    strict: Optional[bool] = Field(default=None, description="Deprecated; use strict_mode")
    strict_mode: StrictPolicy = Field(default=StrictPolicy.HARD, description="Validation policy")
    warmup_enabled: bool = Field(default=True, description="Enable warmup prediction")
    latency_budget_ms: float = Field(default=10.0, ge=0, description="Per-sample latency SLO")
    manifest_required: bool = Field(
        default=False, description="Fail if manifest.json missing or invalid"
    )

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        if not _SYMBOL_RE.fullmatch(v):
            raise ValueError(f"Invalid symbol format: {v}")
        return v.replace("/", "_")

    @model_validator(mode="after")
    def map_strict_bool(self) -> "PredictorConfig":
        if self.strict is not None:
            self.strict_mode = StrictPolicy.HARD if self.strict else StrictPolicy.WARN
        return self


class PredictOneRequest(BaseModel):
    features: Dict[str, float] = Field(..., description="Feature values")

    @field_validator("features")
    @classmethod
    def validate_features(cls, v: Dict[str, float]) -> Dict[str, float]:
        if not v:
            raise ValueError("Features cannot be empty")
        for k, val in v.items():
            if not isinstance(val, (int, float)):
                raise ValueError(f"Feature {k} must be numeric, got {type(val)}")
        return v


class PredictOneResponse(BaseModel):
    score: float = Field(
        ..., ge=0.0, le=1.0, description="Calibrated probability of positive class"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence score")
    raw_score: float = Field(..., ge=0.0, le=1.0, description="Pre-calibration predict_proba")
    model_version: str = Field(..., description="Model version tag")
    n_features: int = Field(..., ge=1, description="Number of features used")
    latency_ms: float = Field(..., ge=0.0, description="Prediction latency in milliseconds")


# ------------------------
# Artifact state
# ------------------------
@dataclass
class ArtifactBundle:
    model: Any
    scaler: Optional[Any]
    calibrator: Optional[Any]
    feature_list: List[str]
    feature_index_map: Dict[str, int]
    metadata: Dict[str, Any]
    metrics: Dict[str, Any]
    model_version: str
    pos_class_idx: int
    manifest: Optional[Dict[str, Any]]


# ------------------------
# Predictor
# ------------------------
class Predictor:
    """
    Production ML predictor with sub-10ms latency SLO.

    Thread-safe, deterministic predictions with comprehensive validation.
    Supports sklearn, XGBoost, LightGBM, CatBoost with optional scaling and calibration.
    """

    def __init__(
        self,
        symbol: str,
        artifacts_dir: str = "models",
        tag: Optional[str] = None,
        strict: Optional[bool] = None,
        strict_mode: StrictPolicy = StrictPolicy.HARD,
        warmup_enabled: bool = True,
        metrics: Optional[Metrics] = None,
        latency_budget_ms: float = 10.0,
        manifest_required: bool = False,
    ) -> None:
        self.config = PredictorConfig(
            symbol=symbol,
            artifacts_dir=artifacts_dir,
            tag=tag,
            strict=strict,
            strict_mode=strict_mode,
            warmup_enabled=warmup_enabled,
            latency_budget_ms=latency_budget_ms,
            manifest_required=manifest_required,
        )

        # Observability
        self._metrics = metrics or Metrics()

        # Thread safety
        self._load_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._artifacts: Optional[ArtifactBundle] = None

        # Perf stats
        self._prediction_count = 0
        self._total_latency_ms = 0.0

        # Path security
        self._validate_paths()

        # Load artifacts and warm up
        self._load_artifacts()
        if self.config.warmup_enabled:
            self._warmup()

    # -------------- Security / Paths --------------
    def _validate_paths(self) -> None:
        base_path = Path(self.config.artifacts_dir).resolve()
        if not base_path.exists():
            raise ArtifactMissing(f"Base artifacts directory not found: {base_path}")

        symbol_path = (base_path / self.config.symbol).resolve()
        try:
            symbol_path.relative_to(base_path)
        except ValueError:
            raise ValueError(f"Symbol path escapes base directory: {symbol_path}")

    # -------------- Hashing / Manifest --------------
    @staticmethod
    def _compute_file_hash(path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def _validate_manifest(self, artifacts_path: Path) -> Optional[Dict[str, Any]]:
        manifest_path = artifacts_path / "manifest.json"
        if not manifest_path.exists():
            if self.config.manifest_required:
                raise ArtifactMissing(f"manifest.json required but missing at {manifest_path}")
            logger.warning("No manifest found at %s", manifest_path)
            return None

        try:
            manifest = self._load_json(manifest_path)

            def chk(name: str, key: str) -> None:
                p = artifacts_path / name
                if p.exists() and key in manifest:
                    actual = self._compute_file_hash(p)
                    if actual != manifest[key]:
                        raise HashMismatch(
                            f"Hash mismatch for {name}: expected {manifest[key]}, got {actual}"
                        )

            chk("model.bin", "model_bin_sha256")
            chk("feature_list.json", "feature_list_json_sha256")
            # optional
            chk("scaler.pkl", "scaler_pkl_sha256")
            chk("calibrator.pkl", "calibrator_pkl_sha256")
            logger.info("Manifest validation passed for %s", artifacts_path)
            return manifest
        except Exception as e:
            if isinstance(e, HashMismatch):
                raise
            if self.config.manifest_required:
                raise ArtifactMissing(f"manifest.json invalid: {e}")
            logger.warning("Manifest validation failed: %s", e)
            return None

    # -------------- Tag resolution --------------
    def _resolve_tag(self) -> str:
        if self.config.tag:
            return self.config.tag

        env_tag = os.getenv("PREDICTOR_MODEL_TAG")
        if env_tag:
            return env_tag

        symbol_dir = Path(self.config.artifacts_dir) / self.config.symbol
        if not symbol_dir.exists():
            raise ArtifactMissing(f"No model directory found for symbol {self.config.symbol}")

        current_file = symbol_dir / "CURRENT.txt"
        if current_file.exists():
            try:
                tag = current_file.read_text().strip()
                if tag and _TIMESTAMP_RE.fullmatch(tag):
                    return tag
            except Exception as e:
                logger.warning("Failed to read CURRENT.txt: %s", e)

        dirs = [d for d in symbol_dir.iterdir() if d.is_dir() and _TIMESTAMP_RE.fullmatch(d.name)]
        if not dirs:
            raise ArtifactMissing(f"No valid model versions found for symbol {self.config.symbol}")
        return sorted(dirs, key=lambda p: p.name)[-1].name

    # -------------- Safe loads --------------
    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            raise ArtifactMissing(f"Failed to load JSON from {path}: {e}")

    @staticmethod
    def _module_allowed(obj: Any) -> bool:
        mod = type(obj).__module__
        return any(mod.startswith(pfx) for pfx in ALLOWED_MODEL_MODULES)

    def _safe_joblib_load(self, path: Path) -> Any:
        try:
            obj = joblib.load(path)
            if not self._module_allowed(obj):
                raise TypeError(f"Disallowed object module: {type(obj).__module__}")
            return obj
        except Exception as e:
            if isinstance(e, TypeError):
                raise
            raise ArtifactMissing(f"Failed to load joblib artifact from {path}: {e}")

    # -------------- Model validation --------------
    @staticmethod
    def _derive_pos_index(model: Any) -> int:
        if hasattr(model, "classes_"):
            classes = list(model.classes_)
            target = 1 if 1 in classes else max(classes)
            return classes.index(target)
        return -1  # last column

    @staticmethod
    def _has_expected_features(model: Any, n_features: int) -> Optional[bool]:
        if hasattr(model, "n_features_in_"):
            return model.n_features_in_ == n_features
        return None

    @staticmethod
    def _validate_model_proba_shape(model: Any, n_features: int) -> None:
        if not hasattr(model, "predict_proba"):
            raise TypeError(f"Model {type(model)} does not support predict_proba")
        dummy_X = np.zeros((1, n_features), dtype=np.float64)
        out = model.predict_proba(dummy_X)
        if out.ndim != 2 or out.shape[1] < 2:
            raise SchemaMismatch("Model must output 2-class probabilities")

    # -------------- Artifact loading --------------
    def _load_artifacts(self) -> None:
        with self._load_lock:
            if self._artifacts is not None:
                return

            base = Path(self.config.artifacts_dir).resolve()
            tag = self._resolve_tag()
            path = (base / self.config.symbol / tag).resolve()
            try:
                path.relative_to(base)
            except ValueError:
                raise ValueError(f"Artifacts path escapes base directory: {path}")
            if not path.exists():
                raise ArtifactMissing(f"Artifacts directory not found: {path}")

            manifest = self._validate_manifest(path)

            model_path = path / "model.bin"
            feat_path = path / "feature_list.json"
            if not model_path.exists():
                raise ArtifactMissing(f"Model file not found: {model_path}")
            if not feat_path.exists():
                raise ArtifactMissing(f"Feature list not found: {feat_path}")

            feature_list = self._load_json(feat_path)
            if not isinstance(feature_list, list) or not feature_list:
                raise SchemaMismatch("feature_list.json must contain a non-empty list")
            n_features = len(feature_list)
            fmap = {name: i for i, name in enumerate(feature_list)}

            model = self._safe_joblib_load(model_path)
            self._validate_model_proba_shape(model, n_features)
            pos_idx = self._derive_pos_index(model)

            expected = self._has_expected_features(model, n_features)
            if expected is False:
                raise SchemaMismatch(
                    f"Feature count mismatch: model expects "
                    f"{getattr(model, 'n_features_in_', 'unknown')}, got {n_features}"
                )

            scaler = None
            sp = path / "scaler.pkl"
            if sp.exists():
                scaler = self._safe_joblib_load(sp)
                logger.info("Loaded scaler: %s", type(scaler).__name__)

            calibrator = None
            cp = path / "calibrator.pkl"
            if cp.exists():
                calibrator = self._safe_joblib_load(cp)
                logger.info("Loaded calibrator: %s", type(calibrator).__name__)

            metadata: Dict[str, Any] = {}
            mcfg = path / "training_cfg.json"
            if mcfg.exists():
                metadata = self._load_json(mcfg)

            train_metrics: Dict[str, Any] = {}
            metp = path / "metrics.json"
            if metp.exists():
                train_metrics = self._load_json(metp)

            self._artifacts = ArtifactBundle(
                model=model,
                scaler=scaler,
                calibrator=calibrator,
                feature_list=feature_list,
                feature_index_map=fmap,
                metadata=metadata,
                metrics=train_metrics,
                model_version=tag,
                pos_class_idx=pos_idx,
                manifest=manifest,
            )

            logger.info(
                "Model artifacts loaded",
                extra=dict(
                    event="model_loaded",
                    symbol=self.config.symbol,
                    model_version=tag,
                    n_features=n_features,
                    model_type=type(model).__name__,
                    has_scaler=scaler is not None,
                    has_calibrator=calibrator is not None,
                    has_manifest=manifest is not None,
                ),
            )

    # -------------- Warmup --------------
    def _warmup(self) -> None:
        try:
            # Use full feature list with zeros to pass all transforms
            dummy = {name: 0.0 for name in self._artifacts.feature_list}
            self.predict_one(dummy, safe=True)
            logger.info("Model warmup completed")
        except Exception as e:
            logger.warning("Model warmup failed (non-critical): %s", e)

    # -------------- Feature preparation --------------
    def _coerce_or_raise(self, msg: str) -> None:
        if self.config.strict_mode == StrictPolicy.HARD:
            raise PredictFailed(msg)
        elif self.config.strict_mode == StrictPolicy.WARN:
            logger.warning(msg)

    def _prepare_X_one(self, features: Union[Dict[str, float], pd.Series]) -> np.ndarray:
        if isinstance(features, pd.Series):
            features = features.to_dict()

        n = len(self._artifacts.feature_list)
        X = np.zeros((1, n), dtype=np.float64)

        provided = set(features.keys())
        required = set(self._artifacts.feature_list)

        # Unknowns
        extra = provided - required
        if extra:
            self._coerce_or_raise(f"Unknown features: {sorted(extra)}")

        # Missing
        missing = required - provided
        if missing:
            self._coerce_or_raise(f"Missing required features: {sorted(missing)}")

        # Map known features
        for name, value in features.items():
            if name in self._artifacts.feature_index_map:
                idx = self._artifacts.feature_index_map[name]
                if pd.isna(value):
                    self._coerce_or_raise(f"NaN value for feature '{name}'")
                    value = 0.0
                X[0, idx] = float(value)

        if self._artifacts.scaler is not None:
            X = self._artifacts.scaler.transform(X)
        return X

    def _prepare_X_batch(self, features: Union[pd.DataFrame, List[Dict[str, float]]]) -> np.ndarray:
        if isinstance(features, list):
            if not features:
                raise PredictFailed("Empty feature list")
            features = pd.DataFrame(features)
        if features.empty:
            raise PredictFailed("Empty DataFrame")

        n_samples = len(features)
        n = len(self._artifacts.feature_list)
        X = np.zeros((n_samples, n), dtype=np.float64)

        required = set(self._artifacts.feature_list)
        present = set(features.columns)

        extra = present - required
        if extra:
            self._coerce_or_raise(f"Unknown columns: {sorted(extra)}")

        missing = required - present
        if missing:
            self._coerce_or_raise(f"Missing required columns: {sorted(missing)}")

        for i, fname in enumerate(self._artifacts.feature_list):
            if fname in features.columns:
                col = features[fname].values
                if np.isnan(col).any():
                    self._coerce_or_raise(f"NaN values in feature '{fname}'")
                    col = np.nan_to_num(col, nan=0.0)
                X[:, i] = col
            # else remain zeros (coerce)

        if self._artifacts.scaler is not None:
            X = self._artifacts.scaler.transform(X)
        return X

    # -------------- Core prediction --------------
    def _predict_proba(self, X: np.ndarray) -> np.ndarray:
        proba = self._artifacts.model.predict_proba(X)
        return proba[:, self._artifacts.pos_class_idx]

    def _calibrate(self, prob: np.ndarray) -> np.ndarray:
        if self._artifacts.calibrator is not None:
            cal_in = self._artifacts.metadata.get("calibration_input", "proba")
            x = prob
            if cal_in == "logit":
                x = np.log(prob / (1.0 - prob + 1e-15))
            x2d = x.reshape(-1, 1)
            out = self._artifacts.calibrator.predict_proba(x2d)
            return out[:, 1] if out.ndim == 2 and out.shape[1] > 1 else out.ravel()
        return prob

    @staticmethod
    def _finalize_prob(p: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        p = np.asarray(p, dtype=np.float64)
        if not np.isfinite(p).all():
            raise PredictFailed("Non-finite probability encountered")
        return np.clip(p, 0.0, 1.0)

    # -------------- Public API --------------
    def predict_one(self, features: Union[Dict[str, float], pd.Series]) -> Dict[str, Any]:
        start = time.perf_counter()
        try:
            if isinstance(features, dict):
                req = PredictOneRequest(features=features)
                features = req.features

            X = self._prepare_X_one(features)
            raw = float(self._predict_proba(X)[0])
            cal = float(self._calibrate(np.array([raw]))[0])
            score = float(self._finalize_prob(cal))

            lat_ms = (time.perf_counter() - start) * 1000.0

            # latency watchdog
            if self.config.latency_budget_ms > 0 and lat_ms > self.config.latency_budget_ms:
                logger.warning(
                    "Latency budget exceeded",
                    extra=dict(
                        event="predict_slow",
                        symbol=self.config.symbol,
                        model_version=self._artifacts.model_version,
                        latency_ms=lat_ms,
                        budget_ms=self.config.latency_budget_ms,
                    ),
                )

            with self._stats_lock:
                self._prediction_count += 1
                self._total_latency_ms += lat_ms

            self._metrics.observe_latency(
                self.config.symbol, self._artifacts.model_version, lat_ms, batch=False
            )
            self._metrics.inc_count(self.config.symbol, self._artifacts.model_version, 1)

            result = dict(
                score=score,
                confidence=score,  # placeholder: can be replaced with calibrated uncertainty
                raw_score=float(raw),
                model_version=self._artifacts.model_version,
                n_features=len(self._artifacts.feature_list),
                latency_ms=round(lat_ms, 3),
            )

            logger.debug(
                "Prediction completed",
                extra=dict(
                    event="predict",
                    symbol=self.config.symbol,
                    model_version=self._artifacts.model_version,
                    latency_ms=lat_ms,
                    n_features=len(self._artifacts.feature_list),
                    strict_mode=self.config.strict_mode.value,
                ),
            )

            # Contract validation
            _ = PredictOneResponse(**result)
            return result

        except Exception as e:
            reason = type(e).__name__
            self._metrics.inc_error(
                self.config.symbol,
                self._artifacts.model_version if self._artifacts else "unknown",
                reason,
            )
            logger.error(
                "Prediction failed",
                extra=dict(
                    event="predict_error",
                    symbol=self.config.symbol,
                    error=str(e),
                    error_type=reason,
                ),
            )
            if isinstance(e, PredictorError):
                raise
            raise PredictFailed(f"Prediction failed: {e}")

    def predict_batch(self, features: Union[pd.DataFrame, List[Dict[str, float]]]) -> pd.DataFrame:
        start = time.perf_counter()
        try:
            X = self._prepare_X_batch(features)
            n = X.shape[0]
            raw = self._predict_proba(X)
            cal = self._calibrate(raw)
            scores = self._finalize_prob(cal)

            lat_ms = (time.perf_counter() - start) * 1000.0
            avg_ms = lat_ms / max(n, 1)

            with self._stats_lock:
                self._prediction_count += n
                self._total_latency_ms += lat_ms

            self._metrics.observe_latency(
                self.config.symbol, self._artifacts.model_version, avg_ms, batch=True
            )
            self._metrics.inc_count(self.config.symbol, self._artifacts.model_version, n)

            df = pd.DataFrame(
                {
                    "score": scores.astype(np.float64),
                    "confidence": scores.astype(np.float64),
                    "raw_score": raw.astype(np.float64),
                    "model_version": [self._artifacts.model_version] * n,
                }
            )
            if isinstance(features, pd.DataFrame):
                df.index = features.index

            logger.debug(
                "Batch prediction completed",
                extra=dict(
                    event="predict_batch",
                    symbol=self.config.symbol,
                    model_version=self._artifacts.model_version,
                    n_samples=n,
                    total_latency_ms=lat_ms,
                    avg_latency_ms=avg_ms,
                ),
            )
            return df

        except Exception as e:
            reason = type(e).__name__
            self._metrics.inc_error(
                self.config.symbol,
                self._artifacts.model_version if self._artifacts else "unknown",
                reason,
            )
            logger.error(
                "Batch prediction failed",
                extra=dict(
                    event="predict_batch_error",
                    symbol=self.config.symbol,
                    error=str(e),
                    error_type=reason,
                ),
            )
            if isinstance(e, PredictorError):
                raise
            raise PredictFailed(f"Batch prediction failed: {e}")

    # -------------- Metadata --------------
    def get_metadata(self) -> Dict[str, Any]:
        if self._artifacts is None:
            raise RuntimeError("Model not loaded")

        with self._stats_lock:
            count = self._prediction_count
            tot_ms = self._total_latency_ms
        avg_ms = tot_ms / count if count > 0 else 0.0

        metrics_summary: Dict[str, Any] = {}
        if self._artifacts.metrics:
            for k in ["accuracy", "precision", "recall", "f1", "auc", "cv_score"]:
                if k in self._artifacts.metrics:
                    metrics_summary[k] = self._artifacts.metrics[k]

        manifest_info = {}
        if self._artifacts.manifest:
            mf = self._artifacts.manifest
            manifest_info = {
                "trainer_version": mf.get("trainer_version"),
                "feature_schema_version": mf.get("feature_schema_version"),
                "git_commit": mf.get("git_commit"),
                "created_at": mf.get("created_at"),
                "approved_by": mf.get("approved_by"),
            }

        return {
            "symbol": self.config.symbol,
            "model_version": self._artifacts.model_version,
            "feature_list": list(self._artifacts.feature_list),
            "n_features": len(self._artifacts.feature_list),
            "model_type": type(self._artifacts.model).__name__,
            "model_module": type(self._artifacts.model).__module__,
            "pos_class_idx": self._artifacts.pos_class_idx,
            "has_scaler": self._artifacts.scaler is not None,
            "has_calibrator": self._artifacts.calibrator is not None,
            "has_manifest": self._artifacts.manifest is not None,
            "calibration_input": self._artifacts.metadata.get("calibration_input", "proba"),
            "artifacts_path": str(
                Path(self.config.artifacts_dir) / self.config.symbol / self._artifacts.model_version
            ),
            "metrics_summary": metrics_summary,
            "manifest_info": manifest_info,
            "performance_stats": {
                "prediction_count": count,
                "total_latency_ms": round(tot_ms, 3),
                "avg_latency_ms": round(avg_ms, 3),
            },
            "config": self.config.model_dump(),
        }


# ------------------------
# Demo utilities (optional)
# ------------------------
def _create_demo_data(feature_list: List[str], n_samples: int = 5) -> pd.DataFrame:
    rng = np.random.RandomState(42)
    data: Dict[str, np.ndarray] = {}
    for f in feature_list:
        fl = f.lower()
        if "price" in fl:
            data[f] = rng.uniform(40000, 50000, n_samples)
        elif "volume" in fl:
            data[f] = rng.uniform(0.1, 10.0, n_samples)
        elif "ratio" in fl or "pct" in fl:
            data[f] = rng.uniform(-0.05, 0.05, n_samples)
        else:
            data[f] = rng.uniform(-1, 1, n_samples)
    return pd.DataFrame(data)


def _compute_file_hash(path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def _create_simple_test_artifacts(symbol: str, artifacts_dir: str = "models") -> str:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.preprocessing import StandardScaler

    ts = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    sym_dir = Path(artifacts_dir) / symbol
    tag_dir = sym_dir / ts
    tag_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.RandomState(42)
    n_samples, n_features = 1000, 10
    X = rng.randn(n_samples, n_features)
    y = (X[:, 0] + X[:, 1] + rng.randn(n_samples) * 0.1 > 0).astype(int)

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    model = LogisticRegression(random_state=42, solver="liblinear")
    model.fit(Xs, y)

    calibrator = CalibratedClassifierCV(model, method="isotonic", cv=3)
    calibrator.fit(Xs, y)

    feature_list = [f"feature_{i}" for i in range(n_features)]

    joblib.dump(model, tag_dir / "model.bin")
    joblib.dump(scaler, tag_dir / "scaler.pkl")
    joblib.dump(calibrator, tag_dir / "calibrator.pkl")
    (tag_dir / "feature_list.json").write_text(json.dumps(feature_list))

    y_pred = model.predict(Xs)
    y_proba = model.predict_proba(Xs)[:, 1]
    metrics = {
        "accuracy": float(accuracy_score(y, y_pred)),
        "precision": float(precision_score(y, y_pred)),
        "recall": float(recall_score(y, y_pred)),
        "f1": float(f1_score(y, y_pred)),
        "auc": float(roc_auc_score(y, y_proba)),
    }
    (tag_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    training_cfg = {
        "trainer_version": "test-suite",
        "feature_schema_version": "v1.0.0",
        "calibration_input": "proba",
        "model_params": model.get_params(),
        "n_samples": n_samples,
        "n_features": n_features,
    }
    (tag_dir / "training_cfg.json").write_text(json.dumps(training_cfg, indent=2))

    manifest = {
        "model_bin_sha256": _compute_file_hash(tag_dir / "model.bin"),
        "feature_list_json_sha256": _compute_file_hash(tag_dir / "feature_list.json"),
        "scaler_pkl_sha256": _compute_file_hash(tag_dir / "scaler.pkl"),
        "calibrator_pkl_sha256": _compute_file_hash(tag_dir / "calibrator.pkl"),
        "trainer_version": "test-suite-v1.0.0",
        "feature_schema_version": "v1.0.0",
        "git_commit": "test-commit-123",
        "created_at": datetime.datetime.now(timezone.utc).isoformat(),
        "approved_by": "test-system",
    }
    (tag_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (sym_dir / "CURRENT.txt").write_text(ts)
    return ts


# ------------------------
# Self-test / demo
# ------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    test_symbol = "BTC_USD"
    models_dir = "models"
    sym_dir = Path(models_dir) / test_symbol

    if not sym_dir.exists() or not any(sym_dir.iterdir()):
        logger.info("No artifacts found for %s. Creating test artifacts…", test_symbol)
        try:
            stamp = _create_simple_test_artifacts(test_symbol, models_dir)
            logger.info("Created test artifacts with timestamp: %s", stamp)
        except Exception as e:
            logger.error("Failed to create test artifacts: %s", e)
            sys.exit(1)

    try:
        logger.info("Testing ML Predictor for %s", test_symbol)
        logger.info("=" * 60)
        t0 = time.time()
        predictor = Predictor(
            symbol=test_symbol,
            artifacts_dir=models_dir,
            strict_mode=StrictPolicy.HARD,
            warmup_enabled=True,
            latency_budget_ms=10.0,
            manifest_required=False,
        )
        logger.info("Predictor initialized successfully.")

        # Test prediction
        logger.info("Testing prediction...")
        test_features = {f"feature_{i}": 0.5 for i in range(10)}
        result = predictor.predict_one(test_features)
        logger.info(
            "Prediction successful: score=%.4f, latency=%.2fms",
            result["score"],
            result["latency_ms"],
        )

        # Show metadata
        logger.info("Model metadata:")
        metadata = predictor.get_metadata()
        logger.info("  Symbol: %s", metadata["symbol"])
        logger.info("  Model version: %s", metadata["model_version"])
        logger.info("  Model type: %s", metadata["model_type"])
        logger.info("  Features: %d", metadata["n_features"])
        logger.info("  Has scaler: %s", metadata["has_scaler"])
        logger.info("  Has calibrator: %s", metadata["has_calibrator"])

        logger.info("ML Predictor test completed successfully!")
        sys.exit(0)

    except Exception as e:
        logger.error("Error testing Predictor: %s", e)
        sys.exit(1)
