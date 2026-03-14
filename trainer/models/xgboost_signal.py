"""
XGBoost binary classifier for signal quality prediction.

Predicts whether a trade entered at a given candle would be profitable,
accounting for the 52 bps round-trip fee floor. Wraps StandardScaler +
XGBClassifier with auto class-imbalance handling, early stopping, and
metadata embedded in the .joblib artifact for Sprint 4B validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class XGBoostSignalConfig:
    """Training hyperparameters."""

    n_estimators: int = 200
    max_depth: int = 5
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    min_child_weight: int = 3
    reg_alpha: float = 0.1
    reg_lambda: float = 1.0
    scale_pos_weight: float = 1.0  # Auto-calculated from class imbalance
    random_state: int = 42
    early_stopping_rounds: int = 20


class XGBoostSignalClassifier:
    """XGBoost binary classifier for signal quality prediction."""

    def __init__(self, config: Optional[XGBoostSignalConfig] = None) -> None:
        self.config = config or XGBoostSignalConfig()
        self.scaler: Optional[StandardScaler] = None
        self.classifier: Optional[xgb.XGBClassifier] = None
        self.feature_names: Optional[List[str]] = None
        self.training_metadata: Dict[str, Any] = {}

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: np.ndarray,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[np.ndarray] = None,
    ) -> Dict[str, float]:
        """
        Train the classifier.

        Auto-calculates scale_pos_weight from class imbalance.
        Uses early stopping if validation set provided.

        Returns:
            Dict with training metrics: accuracy, precision, recall, f1, auc.
        """
        self.feature_names = list(X_train.columns)

        n_neg = int(np.sum(y_train == 0))
        n_pos = int(np.sum(y_train == 1))
        if n_pos > 0:
            self.config.scale_pos_weight = n_neg / n_pos

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X_train)

        self.classifier = xgb.XGBClassifier(
            n_estimators=self.config.n_estimators,
            max_depth=self.config.max_depth,
            learning_rate=self.config.learning_rate,
            subsample=self.config.subsample,
            colsample_bytree=self.config.colsample_bytree,
            min_child_weight=self.config.min_child_weight,
            reg_alpha=self.config.reg_alpha,
            reg_lambda=self.config.reg_lambda,
            scale_pos_weight=self.config.scale_pos_weight,
            random_state=self.config.random_state,
            eval_metric="logloss",
        )

        fit_kwargs: Dict[str, Any] = {"verbose": False}
        if X_val is not None and y_val is not None:
            X_val_scaled = self.scaler.transform(X_val)
            fit_kwargs["eval_set"] = [(X_val_scaled, y_val)]
            self.classifier.set_params(
                early_stopping_rounds=self.config.early_stopping_rounds
            )

        self.classifier.fit(X_scaled, y_train, **fit_kwargs)

        # Compute training metrics
        y_pred = self.classifier.predict(X_scaled)
        y_proba = self.classifier.predict_proba(X_scaled)[:, 1]

        metrics = {
            "accuracy": float(accuracy_score(y_train, y_pred)),
            "precision": float(precision_score(y_train, y_pred, zero_division=0)),
            "recall": float(recall_score(y_train, y_pred, zero_division=0)),
            "f1": float(f1_score(y_train, y_pred, zero_division=0)),
            "auc": float(roc_auc_score(y_train, y_proba))
            if len(np.unique(y_train)) > 1
            else 0.0,
        }

        self.training_metadata = {
            "training_date": datetime.now(timezone.utc).isoformat(),
            "feature_names": self.feature_names,
            "n_train_samples": len(y_train),
            "class_balance": {"positive": n_pos, "negative": n_neg},
            "scale_pos_weight": float(self.config.scale_pos_weight),
            "metrics": metrics,
            "model_version": "v4.0.0-sprint4a",
        }

        logger.info("Model trained: %s", metrics)
        return metrics

    def predict_proba(self, X: np.ndarray) -> float:
        """
        Predict probability of profitable trade.

        Args:
            X: Feature vector shape (1, 30) or (30,).

        Returns:
            Probability in [0.0, 1.0].
        """
        if self.classifier is None or self.scaler is None:
            raise RuntimeError("Model not trained. Call train() first.")
        if X.ndim == 1:
            X = X.reshape(1, -1)
        X_scaled = self.scaler.transform(X)
        proba = self.classifier.predict_proba(X_scaled)[:, 1]
        return float(proba[0])

    def save(self, path: str = "models/signal_scorer.joblib") -> str:
        """Save trained model + metadata to .joblib."""
        if self.classifier is None or self.scaler is None:
            raise RuntimeError("Model not trained. Call train() first.")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "scaler": self.scaler,
            "classifier": self.classifier,
            "feature_names": self.feature_names,
            "training_metadata": self.training_metadata,
        }
        joblib.dump(artifact, path)
        logger.info("Model saved to %s", path)
        return path

    @classmethod
    def load(cls, path: str = "models/signal_scorer.joblib") -> "XGBoostSignalClassifier":
        """Load trained model from .joblib."""
        artifact = joblib.load(path)
        instance = cls()
        instance.scaler = artifact["scaler"]
        instance.classifier = artifact["classifier"]
        instance.feature_names = artifact["feature_names"]
        instance.training_metadata = artifact["training_metadata"]
        logger.info("Model loaded from %s", path)
        return instance

    def feature_importance(self) -> pd.DataFrame:
        """Return feature importance ranking (gain-based)."""
        if self.classifier is None:
            raise RuntimeError("Model not trained.")
        importances = self.classifier.feature_importances_
        return (
            pd.DataFrame({"feature": self.feature_names, "importance": importances})
            .sort_values("importance", ascending=False)
            .reset_index(drop=True)
        )
