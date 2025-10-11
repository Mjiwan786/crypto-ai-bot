"""
agents/ml/model_trainer.py

Production-grade, deterministic, time-series-aware training module for crypto-ai-bot.
Implements fast, leak-proof training with purged/embargo cross-validation.

Key Features:
- Purged/embargo K-fold CV to prevent data leakage
- Support for LogReg, XGBoost, LightGBM with class weights
- Probability calibration (Platt/Isotonic)
- Comprehensive metrics (AUC, AP, LogLoss, ECE)
- Deterministic execution with fixed seeds
- Version-controlled artifact output
- No data leakage via proper per-fold scaling (and train-only scaling for final model)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd

# Core ML libraries
import sklearn
from pydantic import BaseModel, Field, field_validator
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score
from sklearn.model_selection import BaseCrossValidator
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_class_weight

# Optional ML libraries with graceful fallback
try:
    import xgboost as xgb

    XGBOOST_AVAILABLE = True
except Exception:
    XGBOOST_AVAILABLE = False

try:
    import lightgbm as lgb

    LIGHTGBM_AVAILABLE = True
except Exception:
    LIGHTGBM_AVAILABLE = False


# ----------------------------- Config & Results ----------------------------- #


class TrainerConfig(BaseModel):
    """Training configuration with validation (pydantic v2)."""

    symbol: str
    timeframe: str = Field(..., pattern=r"^\d+(s|m|h|d)$")
    label_col: str = "y"
    feature_cols: List[str] = Field(..., min_length=1)
    model_type: Literal["logreg", "xgboost", "lightgbm"] = "logreg"
    n_splits: int = Field(default=5, ge=2, le=20)
    embargo_frac: float = Field(default=0.01, ge=0.0, lt=0.2)
    purge_gap: int = Field(default=0, ge=0)
    class_weight: Optional[Union[dict[int, float], str]] = None  # "balanced" or {0: w0, 1: w1}
    calibrator: Literal["none", "platt", "isotonic"] = "platt"
    max_iters: int = Field(default=200, gt=0)
    random_state: int = 17
    test_size_frac: float = Field(default=0.2, gt=0.0, lt=0.5)
    metrics_focus: Literal["auc", "ap", "logloss"] = "auc"
    artifacts_dir: str = "models"
    tag: Optional[str] = None
    strict_checks: bool = True

    @field_validator("feature_cols")
    @classmethod
    def _feature_cols_non_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("feature_cols cannot be empty")
        return v

    @field_validator("embargo_frac")
    @classmethod
    def _embargo_frac_valid(cls, v: float) -> float:
        if not (0 <= v < 0.2):
            raise ValueError("embargo_frac must be in [0, 0.2)")
        return v

    @field_validator("test_size_frac")
    @classmethod
    def _test_size_frac_valid(cls, v: float) -> float:
        if not (0 < v < 0.5):
            raise ValueError("test_size_frac must be in (0, 0.5)")
        return v


class TrainResult(BaseModel):
    """Training result with comprehensive metrics."""

    tag: str
    symbol: str
    timeframe: str
    model_type: str
    n_features: int
    cv_metrics: Dict[str, float]  # summary metrics (means/stds)
    test_metrics: Dict[str, float]  # final OOS metrics
    feature_importance: Optional[Dict[str, float]] = None
    artifact_paths: Dict[str, str]
    warnings: List[str] = Field(default_factory=list)


# ---------------------------- Purged/Embargo KFold ---------------------------- #


class PurgedKFold(BaseCrossValidator):
    """
    Purged K-Fold cross-validator for time series data.

    Implements purging and embargo to prevent data leakage:
    - Purge: remove samples within 'purge_gap' bars around the validation block
    - Embargo: remove an embargo window after the validation block

    Note: Validation blocks are contiguous time segments. Embargo is applied only
    after the validation block for simplicity; this is conservative and avoids
    lookahead.
    """

    def __init__(self, n_splits: int = 5, purge_gap: int = 0, embargo_frac: float = 0.01):
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        self.n_splits = n_splits
        self.purge_gap = max(0, int(purge_gap))
        self.embargo_frac = float(embargo_frac)

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits

    def split(self, X, y=None, groups=None):
        """Generate train/validation splits with purging and embargo."""
        n_samples = len(X)
        fold_size = n_samples // self.n_splits
        if fold_size == 0:
            return
        for fold in range(self.n_splits):
            # contiguous validation window
            val_start = fold * fold_size
            val_end = (fold + 1) * fold_size if fold < self.n_splits - 1 else n_samples

            # train mask
            train_mask = np.ones(n_samples, dtype=bool)

            # remove validation block
            train_mask[val_start:val_end] = False

            # purge around validation boundaries
            purge_start = max(0, val_start - self.purge_gap)
            purge_end = min(n_samples, val_end + self.purge_gap)
            train_mask[purge_start:purge_end] = False

            # embargo sized relative to the validation block
            emb_size = int(self.embargo_frac * (val_end - val_start))
            embargo_end = min(n_samples, val_end + emb_size)
            train_mask[val_end:embargo_end] = False

            train_idx = np.where(train_mask)[0]
            val_idx = np.arange(val_start, val_end)

            # sanity: ensure enough samples
            if len(train_idx) < 10 or len(val_idx) < 5:
                continue

            yield train_idx, val_idx


# --------------------------------- Trainer --------------------------------- #


class ModelTrainer:
    """Production-grade model trainer with time-series awareness and determinism."""

    def __init__(self, cfg: TrainerConfig):
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)

        # Determinism
        np.random.seed(cfg.random_state)
        random.seed(cfg.random_state)
        os.environ["PYTHONHASHSEED"] = str(cfg.random_state)

        # Resolve tag once to ensure consistency
        self.tag = cfg.tag or self.now_tag()

        # CV splitter
        self.cv = PurgedKFold(
            n_splits=cfg.n_splits,
            purge_gap=cfg.purge_gap,
            embargo_frac=cfg.embargo_frac,
        )

        # Artifacts path (sanitize symbol to avoid nested paths like BTC/USD)
        safe_sym = self._safe_symbol(cfg.symbol)
        self.artifacts_path = Path(cfg.artifacts_dir) / safe_sym / self.tag
        self.artifacts_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_symbol(s: str) -> str:
        return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in s)

    @staticmethod
    def now_tag() -> str:
        """Timestamp-based tag (used only for folder naming; does not affect RNG)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")

    @staticmethod
    def time_sort(df: pd.DataFrame) -> pd.DataFrame:
        """Sort DataFrame by time column or index."""
        if "ts" in df.columns:
            return df.sort_values("ts").reset_index(drop=True)
        elif isinstance(df.index, pd.DatetimeIndex):
            return df.sort_index().reset_index(drop=True)
        else:
            return df.sort_index().reset_index(drop=True)

    @staticmethod
    def label_to01(y: np.ndarray) -> np.ndarray:
        """Convert labels to {0, 1} format."""
        y = np.asarray(y)
        uniq = np.unique(y)
        if len(uniq) != 2:
            raise ValueError(f"Expected binary labels, got {len(uniq)} unique values")
        if set(uniq) == {0, 1}:
            return y.astype(int)
        if set(uniq) == {-1, 1}:
            return ((y + 1) // 2).astype(int)
        # map by order
        sorted_vals = sorted(uniq)
        return (y == sorted_vals[1]).astype(int)

    @staticmethod
    def compute_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 15) -> float:
        """Expected Calibration Error with consistent binning."""
        y_prob = np.clip(y_prob, 1e-15, 1 - 1e-15)
        bins = np.linspace(0.0, 1.0, n_bins + 1)
        ece = 0.0
        for i in range(n_bins):
            lo, hi = bins[i], bins[i + 1]
            mask = (
                (y_prob >= lo) & (y_prob < hi)
                if i < n_bins - 1
                else (y_prob >= lo) & (y_prob <= hi)
            )
            if not np.any(mask):
                continue
            acc = y_true[mask].mean()
            conf = y_prob[mask].mean()
            ece += abs(conf - acc) * mask.mean()
        return float(ece)

    def _validate_inputs(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
        """Validate input DataFrame and return warnings."""
        warnings: List[str] = []

        # Required columns
        missing = []
        if self.cfg.label_col not in df.columns:
            missing.append(self.cfg.label_col)
        for col in self.cfg.feature_cols:
            if col not in df.columns:
                missing.append(col)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Data sufficiency
        min_samples = self.cfg.n_splits * 20
        if len(df) < min_samples:
            raise ValueError(f"Insufficient data: {len(df)} samples, need at least {min_samples}")

        # Sort by time
        df_sorted = self.time_sort(df)
        if not df.equals(df_sorted):
            warnings.append("Data was not sorted by time - sorted automatically")
            df = df_sorted

        # Strict checks
        if self.cfg.strict_checks and "ts" in df.columns:
            ts = pd.to_datetime(df["ts"])
            if not ts.is_monotonic_increasing:
                raise ValueError(
                    "strict_checks=True but 'ts' is not strictly increasing after sort."
                )

        return df, warnings

    def _prepare_data(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Extract features and labels; no scaling (to avoid leakage)."""
        X = df[self.cfg.feature_cols].to_numpy()
        y = self.label_to01(df[self.cfg.label_col].to_numpy())

        # Simple median imputation (vectorized)
        if np.any(pd.isna(X)):
            med = np.nanmedian(X, axis=0)
            inds = np.where(np.isnan(X))
            X[inds] = np.take(med, inds[1])
        return X, y

    def _create_model(self) -> Any:
        """Create base model based on configuration."""
        if self.cfg.model_type == "logreg":
            # class_weight can be dict or "balanced" or None
            return LogisticRegression(
                solver="lbfgs",
                max_iter=self.cfg.max_iters,
                random_state=self.cfg.random_state,
                class_weight=self.cfg.class_weight,
            )
        elif self.cfg.model_type == "xgboost":
            if not XGBOOST_AVAILABLE:
                raise ImportError("XGBoost is not installed. Install with: pip install xgboost")
            # scale_pos_weight computed later if "balanced"
            return xgb.XGBClassifier(
                objective="binary:logistic",
                eval_metric="logloss",
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=self.cfg.random_state,
                n_jobs=1,  # determinism
                tree_method="hist",
                verbosity=0,
            )
        elif self.cfg.model_type == "lightgbm":
            if not LIGHTGBM_AVAILABLE:
                raise ImportError("LightGBM is not installed. Install with: pip install lightgbm")
            return lgb.LGBMClassifier(
                objective="binary",
                metric="binary_logloss",
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                class_weight=self.cfg.class_weight,
                random_state=self.cfg.random_state,
                n_jobs=1,  # determinism
                verbose=-1,
                force_row_wise=True,
            )
        else:
            raise ValueError(f"Unsupported model type: {self.cfg.model_type}")

    def _create_calibrator(self):
        """Create probability calibrator."""
        if self.cfg.calibrator == "platt":
            return LogisticRegression(
                solver="lbfgs",
                max_iter=200,
                C=1.0,
                random_state=self.cfg.random_state,
            )
        if self.cfg.calibrator == "isotonic":
            return IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
        return None

    def _compute_metrics(self, y_true: np.ndarray, y_prob: np.ndarray) -> Dict[str, float]:
        """Compute AUC, AP, LogLoss, ECE."""
        y_prob = np.clip(y_prob, 1e-15, 1 - 1e-15)
        return {
            "auc": float(roc_auc_score(y_true, y_prob)),
            "ap": float(average_precision_score(y_true, y_prob)),
            "logloss": float(log_loss(y_true, y_prob)),
            "ece": float(self.compute_ece(y_true, y_prob)),
        }

    def _get_feature_importance(self, model) -> Optional[Dict[str, float]]:
        """Extract and normalize feature importance."""
        if hasattr(model, "coef_"):
            imp = np.abs(model.coef_[0])
        elif hasattr(model, "feature_importances_"):
            imp = model.feature_importances_
        else:
            return None
        s = float(np.sum(imp))
        if s <= 0:
            return None
        imp = imp / s
        return dict(zip(self.cfg.feature_cols, map(float, imp)))

    def _train_one_fold(
        self, X: np.ndarray, y: np.ndarray, train_idx: np.ndarray, val_idx: np.ndarray
    ) -> Tuple[Any, np.ndarray]:
        """Train model on one fold; scale only for logistic regression (no leakage)."""
        X_tr, X_va = X[train_idx], X[val_idx]
        y_tr, _y_va = y[train_idx], y[val_idx]

        # Per-fold scaling only for linear model
        if self.cfg.model_type == "logreg":
            scaler = StandardScaler()
            X_tr = scaler.fit_transform(X_tr)
            X_va = scaler.transform(X_va)

        model = self._create_model()

        # Balanced weights for XGBoost via scale_pos_weight
        if self.cfg.model_type == "xgboost" and self.cfg.class_weight == "balanced":
            cw = compute_class_weight("balanced", classes=np.unique(y_tr), y=y_tr)
            # cw[0] is weight for class 0, cw[1] for class 1; scale_pos_weight = w_neg/w_pos
            spw = float(cw[0] / cw[1])
            model.set_params(scale_pos_weight=spw)

        model.fit(X_tr, y_tr)
        y_val_prob = model.predict_proba(X_va)[:, 1]
        return model, y_val_prob

    def _save_artifacts(
        self,
        model,
        calibrator,
        feature_importance: Optional[Dict[str, float]],
        warnings: List[str],
        scaler: Optional[StandardScaler] = None,
    ) -> Dict[str, str]:
        """Save model artifacts with complete metadata and return paths."""
        artifact_paths: Dict[str, str] = {}

        # model.bin
        model_path = self.artifacts_path / "model.bin"
        joblib.dump(model, model_path)
        artifact_paths["model_bin"] = str(model_path)

        # scaler.pkl (only if provided, e.g., for logistic regression)
        if scaler is not None:
            scaler_path = self.artifacts_path / "scaler.pkl"
            joblib.dump(scaler, scaler_path)
            artifact_paths["scaler_pkl"] = str(scaler_path)

        # feature_list.json
        feature_list_path = self.artifacts_path / "feature_list.json"
        with open(feature_list_path, "w") as f:
            json.dump(self.cfg.feature_cols, f, sort_keys=True)
        artifact_paths["feature_list"] = str(feature_list_path)

        # calibrator.pkl
        if calibrator is not None:
            calibrator_path = self.artifacts_path / "calibrator.pkl"
            joblib.dump(calibrator, calibrator_path)
            artifact_paths["calibrator_pkl"] = str(calibrator_path)

        # feature_importance.json
        if feature_importance:
            fi_path = self.artifacts_path / "feature_importance.json"
            with open(fi_path, "w") as f:
                json.dump(feature_importance, f, sort_keys=True, indent=2)
            artifact_paths["feature_importance"] = str(fi_path)

        # training_cfg.json (with version info & feature list hash)
        training_cfg_path = self.artifacts_path / "training_cfg.json"
        cfg_dict = self.cfg.model_dump()
        cfg_dict["versions"] = {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "sklearn": sklearn.__version__,
            "xgboost": xgb.__version__ if XGBOOST_AVAILABLE else None,
            "lightgbm": lgb.__version__ if LIGHTGBM_AVAILABLE else None,
        }
        cfg_dict["feature_list_sha256"] = hashlib.sha256(
            "||".join(self.cfg.feature_cols).encode()
        ).hexdigest()
        cfg_dict["warnings"] = warnings

        with open(training_cfg_path, "w") as f:
            json.dump(cfg_dict, f, sort_keys=True, indent=2)
        artifact_paths["training_cfg"] = str(training_cfg_path)

        return artifact_paths

    # ------------------------------- Fit Pipeline ------------------------------- #

    def fit(self, df: pd.DataFrame) -> TrainResult:
        """
        Train with time-series safety:
        - Temporal train/test split (tail = OOS)
        - Purged/embargo K-fold on the train portion
        - Per-fold scaling for LogReg only (no leakage)
        - OOF-based calibration where available
        """
        start = time.time()
        self.logger.info("Training start: %s %s", self.cfg.symbol, self.cfg.timeframe)

        # 1) Validate inputs
        df, warnings = self._validate_inputs(df)

        # 2) Prepare arrays (no scaling yet)
        X, y = self._prepare_data(df)
        n = len(X)

        # 3) Temporal train/test split (tail is test)
        test_size = int(self.cfg.test_size_frac * n)
        train_size = n - test_size
        if train_size <= 0 or test_size <= 0:
            raise ValueError("Invalid split sizes; adjust test_size_frac.")

        # Note: for final model we will scale only for logreg
        if self.cfg.model_type == "logreg":
            final_scaler = StandardScaler()
            X_train = final_scaler.fit_transform(X[:train_size])
            X_test = final_scaler.transform(X[train_size:])
        else:
            final_scaler = None
            X_train = X[:train_size]
            X_test = X[train_size:]
        y_train, y_test = y[:train_size], y[train_size:]

        # Class distribution logs
        try:
            train_dist = (np.bincount(y_train) / len(y_train)).tolist()
            test_dist = (np.bincount(y_test) / len(y_test)).tolist()
            self.logger.info("Class distribution train=%s test=%s", train_dist, test_dist)
        except Exception:
            pass

        # 4) Cross-validation on *unscaled* train X for per-fold scaling in _train_one_fold
        cv_metrics = {"fold": [], "auc": [], "ap": [], "logloss": [], "ece": []}
        oof_predictions = np.full(train_size, np.nan, dtype=float)

        for fold, (tr_idx, va_idx) in enumerate(self.cv.split(X[:train_size], y_train)):
            if len(tr_idx) < 10 or len(va_idx) < 5:
                warnings.append(f"Fold {fold} skipped due to insufficient samples")
                continue

            self.logger.info("Fold %d: train=%d val=%d", fold, len(tr_idx), len(va_idx))
            fold_model, val_pred = self._train_one_fold(X[:train_size], y_train, tr_idx, va_idx)
            val_pred = np.clip(val_pred, 1e-15, 1 - 1e-15)
            oof_predictions[va_idx] = val_pred

            m = self._compute_metrics(y_train[va_idx], val_pred)
            cv_metrics["fold"].append(fold)
            for k, v in m.items():
                cv_metrics[k].append(v)

        # CV summaries
        cv_summary: Dict[str, float] = {}
        for k in ["auc", "ap", "logloss", "ece"]:
            vals = cv_metrics[k]
            if vals:
                cv_summary[f"{k}_mean"] = float(np.mean(vals))
                cv_summary[f"{k}_std"] = float(np.std(vals))
            else:
                cv_summary[f"{k}_mean"] = 0.0
                cv_summary[f"{k}_std"] = 0.0

        # 5) Train final model on scaled/ready X_train
        model = self._create_model()

        # Balanced weights for XGBoost in final fit
        if self.cfg.model_type == "xgboost" and self.cfg.class_weight == "balanced":
            cw = compute_class_weight("balanced", classes=np.unique(y_train), y=y_train)
            spw = float(cw[0] / cw[1])
            model.set_params(scale_pos_weight=spw)

        model.fit(X_train, y_train)

        # 6) Calibration (prefer OOF; fallback to in-sample final model preds)
        calibrator = None
        if self.cfg.calibrator != "none":
            use_oof = not np.any(np.isnan(oof_predictions))
            train_scores = (
                oof_predictions
                if use_oof
                else np.clip(model.predict_proba(X_train)[:, 1], 1e-15, 1 - 1e-15)
            )
            cal = self._create_calibrator()
            if self.cfg.calibrator == "platt":
                cal.fit(train_scores.reshape(-1, 1), y_train)
            else:
                cal.fit(train_scores, y_train)
            calibrator = cal
            if not use_oof:
                warnings.append(
                    "OOF predictions incomplete; calibrated using in-sample scores as fallback."
                )

        # 7) Test evaluation
        test_raw = np.clip(model.predict_proba(X_test)[:, 1], 1e-15, 1 - 1e-15)
        if calibrator is not None:
            test_prob = (
                calibrator.predict_proba(test_raw.reshape(-1, 1))[:, 1]
                if self.cfg.calibrator == "platt"
                else calibrator.predict(test_raw)
            )
        else:
            test_prob = test_raw
        test_metrics = self._compute_metrics(y_test, test_prob)

        # Confusion metrics at 0.5
        y_hat = (test_prob >= 0.5).astype(int)
        tp = int(np.sum((y_test == 1) & (y_hat == 1)))
        fp = int(np.sum((y_test == 0) & (y_hat == 1)))
        tn = int(np.sum((y_test == 0) & (y_hat == 0)))
        fn = int(np.sum((y_test == 1) & (y_hat == 0)))
        prec = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        rec = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        test_metrics.update(
            {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": prec, "recall": rec}
        )

        # 8) Feature importance
        feat_imp = self._get_feature_importance(model)

        # 9) Save artifacts (include scaler only if used)
        artifact_paths = self._save_artifacts(
            model=model,
            calibrator=calibrator,
            feature_importance=feat_imp,
            warnings=warnings,
            scaler=final_scaler,
        )

        # Save metrics.json
        metrics = {
            "cv_metrics": cv_summary,
            "cv_per_fold": {
                k: (v if k == "fold" else [float(x) for x in v]) for k, v in cv_metrics.items()
            },
            "test_metrics": {k: float(v) for k, v in test_metrics.items()},
            "training_time_seconds": float(time.time() - start),
            "n_samples": int(n),
            "n_features": int(len(self.cfg.feature_cols)),
            "class_distribution": {
                "train": train_dist if "train_dist" in locals() else None,
                "test": test_dist if "test_dist" in locals() else None,
            },
        }
        metrics_path = self.artifacts_path / "metrics.json"
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, sort_keys=True, indent=2)
        artifact_paths["metrics_json"] = str(metrics_path)

        # 10) Result
        result = TrainResult(
            tag=self.tag,
            symbol=self.cfg.symbol,
            timeframe=self.cfg.timeframe,
            model_type=self.cfg.model_type,
            n_features=len(self.cfg.feature_cols),
            cv_metrics=cv_summary,
            test_metrics=test_metrics,
            feature_importance=feat_imp,
            artifact_paths=artifact_paths,
            warnings=warnings,
        )

        self.logger.info(
            "Training done in %.3fs | Test AUC=%.4f AP=%.4f LogLoss=%.4f ECE=%.4f",
            time.time() - start,
            result.test_metrics.get("auc", 0.0),
            result.test_metrics.get("ap", 0.0),
            result.test_metrics.get("logloss", 0.0),
            result.test_metrics.get("ece", 0.0),
        )
        return result


# ------------------------------ Self-test (optional) ------------------------------ #

if __name__ == "__main__":
    # Minimal smoke test with synthetic data; safe to remove in production.
    logging.basicConfig(level=logging.INFO)

    def generate_test_data(n_samples: int = 2000) -> pd.DataFrame:
        rng = np.random.default_rng(42)
        start_date = datetime.now(timezone.utc) - pd.Timedelta(hours=n_samples)
        ts = pd.date_range(start_date, periods=n_samples, freq="H")
        feats = {}
        for i in range(10):
            series = rng.standard_normal(n_samples)
            for j in range(1, n_samples):
                series[j] += 0.3 * series[j - 1]
            feats[f"feature_{i}"] = series
        logits = (
            0.5 * feats["feature_0"]
            + 0.3 * feats["feature_1"]
            - 0.2 * feats["feature_2"]
            + rng.standard_normal(n_samples) * 0.5
        )
        prob = 1 / (1 + np.exp(-logits))
        y = (rng.random(n_samples) < prob).astype(int)
        df = pd.DataFrame(feats)
        df["ts"] = ts
        df["y"] = y
        return df

    df = generate_test_data(2000)

    cfg = TrainerConfig(
        symbol="BTC/USD",
        timeframe="1h",
        label_col="y",
        feature_cols=[f"feature_{i}" for i in range(10)],
        model_type="logreg",
        n_splits=5,
        embargo_frac=0.02,
        purge_gap=2,
        class_weight="balanced",
        calibrator="platt",
        test_size_frac=0.2,
        artifacts_dir="test_models",
        strict_checks=True,
    )

    trainer = ModelTrainer(cfg)
    res = trainer.fit(df)

    logger = logging.getLogger(__name__)
    logger.info("\n=== Training Results ===")
    logger.info("Tag: %s", res.tag)
    logger.info("Symbol: %s", res.symbol)
    logger.info("Model: %s", res.model_type)
    logger.info("Features: %d", res.n_features)
    logger.info("Test AUC: %.4f", res.test_metrics.get("auc", 0.0))
    logger.info("Test AP: %.4f", res.test_metrics.get("ap", 0.0))
    logger.info("Test LogLoss: %.4f", res.test_metrics.get("logloss", 0.0))
    logger.info("Test ECE: %.4f", res.test_metrics.get("ece", 0.0))
    if res.feature_importance:
        top = sorted(res.feature_importance.items(), key=lambda x: x[1], reverse=True)[:5]
        logger.info("Top features: %s", top)
    logger.info("\nArtifacts:")
    for k, v in res.artifact_paths.items():
        logger.info(" - %s: %s", k, v)
