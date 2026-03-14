"""
Strategy prediction interface for agents.

Wraps signals.ml_scorer.MLScorer for use by the agent framework.
Does NOT connect to Redis directly -- receives OHLCV data as input.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from signals.ml_scorer import MLScorer, MLScorerConfig

logger = logging.getLogger(__name__)


class StrategyPredictor:
    """Predict signal quality using ML model."""

    def __init__(self, model_path: str = "models/signal_scorer.joblib") -> None:
        config = MLScorerConfig(
            enabled=True,
            model_path=model_path,
            min_score=0.60,
            shadow_mode=False,
        )
        self._scorer = MLScorer(config)
        self._loaded = self._scorer.load()

    @property
    def is_loaded(self) -> bool:
        """Whether the ML model was loaded successfully."""
        return self._loaded

    def predict_signal_quality(
        self,
        ohlcv: np.ndarray,
        direction: str = "long",
        confidence: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Predict whether a signal at this moment would be profitable.

        Returns:
            Dict with 'should_trade', 'ml_score', 'reason'.
        """
        should_pass, ml_score, reason = self._scorer.score_signal(ohlcv, direction, confidence)
        return {
            "should_trade": should_pass,
            "ml_score": ml_score,
            "reason": reason,
        }

    def predict_strategy(self) -> Optional[List[Dict[str, Any]]]:
        """Legacy interface -- returns None if no model loaded."""
        if not self._loaded:
            logger.warning("StrategyPredictor: model not loaded")
            return None
        return []
