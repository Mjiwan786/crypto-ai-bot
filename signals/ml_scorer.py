"""
ML Signal Scorer -- pre-filter for production engine.

Loads a trained XGBoost model and scores signals before execution.
Feature-flagged: ML_SCORER_ENABLED=false by default.
Graceful fallback: if model file doesn't exist or loading fails,
all signals pass through (no veto).

Sprint 4B -- wired into production_engine.py between confidence gate
and signal publishing.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MLScorerConfig:
    """ML scorer configuration from environment variables."""

    enabled: bool = False
    model_path: str = "models/signal_scorer.joblib"
    min_score: float = 0.60
    shadow_mode: bool = True

    @classmethod
    def from_env(cls) -> "MLScorerConfig":
        return cls(
            enabled=os.getenv("ML_SCORER_ENABLED", "false").lower() == "true",
            model_path=os.getenv("ML_MODEL_PATH", "models/signal_scorer.joblib"),
            min_score=float(os.getenv("ML_MIN_SCORE", "0.60")),
            shadow_mode=os.getenv("ML_SHADOW_MODE", "true").lower() == "true",
        )


class MLScorer:
    """
    ML-based signal quality scorer.

    Loads XGBoostSignalClassifier from .joblib and uses FeatureBuilder
    to compute features from OHLCV data. Returns a probability score
    indicating how likely a trade at this moment would be profitable.

    Thread-safe: model and feature_builder are read-only after init.
    """

    def __init__(self, config: Optional[MLScorerConfig] = None) -> None:
        self.config = config or MLScorerConfig.from_env()
        self._model = None
        self._feature_builder = None
        self._loaded = False
        self._load_error: Optional[str] = None
        self._score_count = 0
        self._veto_count = 0

    def load(self) -> bool:
        """
        Load model from disk. Call once at engine startup.

        Returns True if model loaded successfully.
        On failure, scorer operates in pass-through mode.
        """
        if not self.config.enabled:
            logger.info("ML Scorer disabled (ML_SCORER_ENABLED=false)")
            return False

        model_path = Path(self.config.model_path)
        if not model_path.exists():
            self._load_error = f"Model file not found: {model_path}"
            logger.warning("ML Scorer: %s -- operating in pass-through mode", self._load_error)
            return False

        try:
            from trainer.models.xgboost_signal import XGBoostSignalClassifier
            from trainer.feature_builder import FeatureBuilder

            self._model = XGBoostSignalClassifier.load(str(model_path))
            self._feature_builder = FeatureBuilder()
            self._loaded = True

            # Validate feature names match
            model_features = self._model.feature_names
            builder_features = self._feature_builder.FEATURE_NAMES
            if model_features and builder_features and model_features != builder_features:
                logger.error(
                    "ML Scorer: feature name mismatch! Model=%d, builder=%d. Retraining needed.",
                    len(model_features), len(builder_features),
                )
                self._loaded = False
                self._load_error = "Feature name mismatch"
                return False

            logger.info(
                "ML Scorer loaded: model=%s, features=%d, min_score=%.2f, shadow=%s",
                model_path, len(builder_features), self.config.min_score, self.config.shadow_mode,
            )
            return True

        except Exception as e:
            self._load_error = str(e)
            logger.error("ML Scorer load failed: %s -- operating in pass-through mode", e)
            return False

    def score_signal(
        self,
        ohlcv: np.ndarray,
        direction: str,
        confidence: float,
    ) -> Tuple[bool, float, str]:
        """
        Score a signal candidate.

        Args:
            ohlcv: numpy array shape (N, 5) -- same format as consensus gate input.
            direction: "long" or "short" from consensus gate.
            confidence: consensus gate confidence (0.0-1.0).

        Returns:
            Tuple of (should_pass, ml_score, reason).
        """
        if not self._loaded or not self.config.enabled:
            return (True, -1.0, "ml_scorer_disabled")

        try:
            start = time.monotonic()

            features = self._feature_builder.build_single(ohlcv)
            if features is None:
                return (True, -1.0, "insufficient_data_for_features")

            ml_score = self._model.predict_proba(features.reshape(1, -1))

            elapsed_ms = (time.monotonic() - start) * 1000
            self._score_count += 1

            should_pass = ml_score >= self.config.min_score

            if not should_pass:
                self._veto_count += 1

            reason = (
                f"ml_score={ml_score:.3f} "
                f"{'>' if should_pass else '<'}{self.config.min_score:.2f} "
                f"({elapsed_ms:.1f}ms)"
            )

            # Shadow mode: log but don't actually veto
            if self.config.shadow_mode and not should_pass:
                logger.info(
                    "ML Scorer SHADOW veto: %s (would veto, passing through)", reason,
                )
                return (True, ml_score, f"shadow_veto: {reason}")

            if not should_pass:
                logger.info("ML Scorer VETO: %s", reason)
            else:
                logger.debug("ML Scorer PASS: %s", reason)

            return (should_pass, ml_score, reason)

        except Exception as e:
            logger.warning("ML Scorer error: %s -- passing signal through", e)
            return (True, -1.0, f"scorer_error: {e}")

    @property
    def stats(self) -> dict:
        """Return scorer statistics for metrics/health."""
        return {
            "enabled": self.config.enabled,
            "loaded": self._loaded,
            "shadow_mode": self.config.shadow_mode,
            "model_path": self.config.model_path,
            "min_score": self.config.min_score,
            "total_scored": self._score_count,
            "total_vetoed": self._veto_count,
            "veto_rate": self._veto_count / max(self._score_count, 1),
            "load_error": self._load_error,
        }
