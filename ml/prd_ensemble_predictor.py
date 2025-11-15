"""
PRD-001 Compliant Ensemble Predictor

This module implements PRD-001 Section 3.6 ensemble prediction with:
- Weighted ensemble: RF (60%) + LSTM (40%)
- Dynamic weight adjustment based on recent accuracy (last 100 predictions)
- Confidence calculation from model agreement (both agree → 0.9, disagree → 0.5)
- DEBUG level logging for ensemble predictions
- Performance tracking and metrics

Architecture:
- Combines RandomForest (or LightGBM) with LSTM predictions
- Tracks recent predictions for adaptive weight adjustment
- Calculates confidence based on model consensus

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Dict, Any, Tuple, Optional, List
from decimal import Decimal

import numpy as np

logger = logging.getLogger(__name__)


class PRDEnsemblePredictor:
    """
    PRD-001 Section 3.6 compliant ensemble predictor.

    Combines multiple models with:
    - Weighted voting (RF/LightGBM 60%, LSTM 40% default)
    - Adaptive weight adjustment based on recent accuracy
    - Confidence scoring from model agreement
    - DEBUG level logging

    Usage:
        ensemble = PRDEnsemblePredictor(
            rf_predictor=rf_model,
            lstm_predictor=lstm_model,
            rf_weight=0.6,
            lstm_weight=0.4
        )

        result = ensemble.predict(market_context)
        # Returns: {
        #   "probability": 0.72,
        #   "confidence": 0.9,  # High if models agree
        #   "rf_prob": 0.75,
        #   "lstm_prob": 0.68,
        #   "weights": {"rf": 0.6, "lstm": 0.4}
        # }
    """

    def __init__(
        self,
        rf_predictor = None,
        lstm_predictor = None,
        rf_weight: float = 0.6,
        lstm_weight: float = 0.4,
        recent_window: int = 100,
        min_weight: float = 0.3,
        max_weight: float = 0.7,
        agreement_threshold: float = 0.1
    ):
        """
        Initialize PRD-compliant ensemble predictor.

        Args:
            rf_predictor: RandomForest/LightGBM predictor
            lstm_predictor: LSTM predictor
            rf_weight: Initial weight for RF predictions (default 0.6 per PRD)
            lstm_weight: Initial weight for LSTM predictions (default 0.4 per PRD)
            recent_window: Number of recent predictions to track (default 100 per PRD)
            min_weight: Minimum allowed weight for any model (default 0.3)
            max_weight: Maximum allowed weight for any model (default 0.7)
            agreement_threshold: Threshold for considering models agree (default 0.1)
        """
        self.rf_predictor = rf_predictor
        self.lstm_predictor = lstm_predictor

        # PRD-001 Section 3.6: Initial weights (RF 60%, LSTM 40%)
        self.rf_weight = rf_weight
        self.lstm_weight = lstm_weight

        # Constraints for weight adjustment
        self.min_weight = min_weight
        self.max_weight = max_weight

        # PRD-001 Section 3.6: Track last 100 predictions for weight adjustment
        self.recent_window = recent_window
        self.rf_recent_correct = deque(maxlen=recent_window)
        self.lstm_recent_correct = deque(maxlen=recent_window)

        # Agreement threshold for confidence calculation
        self.agreement_threshold = agreement_threshold

        # Statistics
        self.total_predictions = 0
        self.total_agreements = 0

        logger.info(
            f"PRDEnsemblePredictor initialized: "
            f"rf_weight={rf_weight:.2f}, lstm_weight={lstm_weight:.2f}, "
            f"recent_window={recent_window}"
        )

    def predict(
        self,
        ctx: Dict[str, Any],
        pair: str = "BTC/USD"
    ) -> Dict[str, Any]:
        """
        Make ensemble prediction with confidence scoring.

        PRD-001 Section 3.6:
        1. Get predictions from both models
        2. Calculate weighted ensemble probability
        3. Calculate confidence from model agreement
        4. Log at DEBUG level
        5. Return result with metadata

        Args:
            ctx: Market context dict
            pair: Trading pair (for logging)

        Returns:
            Dictionary with:
                - probability: Weighted ensemble probability
                - confidence: Confidence score based on agreement
                - rf_prob: RF model probability
                - lstm_prob: LSTM model probability
                - weights: Current model weights
                - agree: Boolean indicating if models agree
        """
        # 1. Get individual model predictions
        rf_prob = self._get_rf_prediction(ctx)
        lstm_prob = self._get_lstm_prediction(ctx)

        # 2. PRD-001 Section 3.6: Calculate weighted ensemble
        ensemble_prob = (self.rf_weight * rf_prob) + (self.lstm_weight * lstm_prob)

        # 3. PRD-001 Section 3.6: Calculate confidence from model agreement
        confidence, agree = self._calculate_confidence(rf_prob, lstm_prob)

        # Build result
        result = {
            "probability": float(ensemble_prob),
            "confidence": float(confidence),
            "rf_prob": float(rf_prob),
            "lstm_prob": float(lstm_prob),
            "weights": {
                "rf": float(self.rf_weight),
                "lstm": float(self.lstm_weight)
            },
            "agree": agree,
            "pair": pair
        }

        # 4. PRD-001 Section 3.6: Log at DEBUG level
        self._log_prediction(result)

        # Update statistics
        self.total_predictions += 1
        if agree:
            self.total_agreements += 1

        return result

    def _get_rf_prediction(self, ctx: Dict[str, Any]) -> float:
        """
        Get prediction from RandomForest/LightGBM model.

        Args:
            ctx: Market context

        Returns:
            Probability [0, 1]
        """
        if self.rf_predictor is None:
            logger.warning("RF predictor not available, returning neutral 0.5")
            return 0.5

        try:
            prob = self.rf_predictor.predict_proba(ctx)
            return float(np.clip(prob, 0.0, 1.0))
        except Exception as e:
            logger.error(f"RF prediction failed: {e}")
            return 0.5

    def _get_lstm_prediction(self, ctx: Dict[str, Any]) -> float:
        """
        Get prediction from LSTM model.

        Args:
            ctx: Market context

        Returns:
            Probability [0, 1]
        """
        if self.lstm_predictor is None:
            logger.warning("LSTM predictor not available, returning neutral 0.5")
            return 0.5

        try:
            prob = self.lstm_predictor.predict_proba(ctx)
            return float(np.clip(prob, 0.0, 1.0))
        except Exception as e:
            logger.error(f"LSTM prediction failed: {e}")
            return 0.5

    def _calculate_confidence(
        self,
        rf_prob: float,
        lstm_prob: float
    ) -> Tuple[float, bool]:
        """
        PRD-001 Section 3.6: Calculate confidence from model agreement.

        Logic:
        - Both models agree (prob difference < threshold) → confidence = 0.9
        - Models disagree → confidence = 0.5

        Args:
            rf_prob: RF probability
            lstm_prob: LSTM probability

        Returns:
            (confidence, agree) tuple
        """
        # Check agreement
        prob_diff = abs(rf_prob - lstm_prob)
        agree = prob_diff < self.agreement_threshold

        if agree:
            # PRD-001 Section 3.6: Both agree → 0.9 confidence
            confidence = 0.9
        else:
            # PRD-001 Section 3.6: Disagree → 0.5 confidence
            confidence = 0.5

        return confidence, agree

    def _log_prediction(self, result: Dict[str, Any]):
        """
        PRD-001 Section 3.6: Log ensemble prediction at DEBUG level.

        Args:
            result: Prediction result dict
        """
        logger.debug(
            f"[ENSEMBLE] {result['pair']} | "
            f"Probability: {result['probability']:.3f} | "
            f"Confidence: {result['confidence']:.2f} | "
            f"RF: {result['rf_prob']:.3f} (w={result['weights']['rf']:.2f}) | "
            f"LSTM: {result['lstm_prob']:.3f} (w={result['weights']['lstm']:.2f}) | "
            f"Agree: {result['agree']}"
        )

    def update_feedback(
        self,
        rf_correct: bool,
        lstm_correct: bool
    ):
        """
        PRD-001 Section 3.6: Update model performance tracking.

        Track which models were correct for last 100 predictions
        and adjust weights based on recent accuracy.

        Args:
            rf_correct: Whether RF prediction was correct
            lstm_correct: Whether LSTM prediction was correct
        """
        # Add to recent history
        self.rf_recent_correct.append(rf_correct)
        self.lstm_recent_correct.append(lstm_correct)

        # Adjust weights if we have enough history
        if len(self.rf_recent_correct) >= 10:  # Min 10 samples
            self._adjust_weights()

    def _adjust_weights(self):
        """
        PRD-001 Section 3.6: Adjust weights based on recent accuracy (last 100 predictions).

        Logic:
        - Calculate recent accuracy for each model
        - Adjust weights proportionally to accuracy
        - Ensure weights sum to 1.0
        - Respect min/max weight constraints
        """
        # Calculate recent accuracies
        rf_accuracy = sum(self.rf_recent_correct) / len(self.rf_recent_correct)
        lstm_accuracy = sum(self.lstm_recent_correct) / len(self.lstm_recent_correct)

        total_accuracy = rf_accuracy + lstm_accuracy

        if total_accuracy > 0:
            # Proportional weighting based on accuracy
            new_rf_weight = rf_accuracy / total_accuracy
            new_lstm_weight = lstm_accuracy / total_accuracy

            # Apply constraints
            new_rf_weight = np.clip(new_rf_weight, self.min_weight, self.max_weight)
            new_lstm_weight = np.clip(new_lstm_weight, self.min_weight, self.max_weight)

            # Normalize to sum to 1.0
            weight_sum = new_rf_weight + new_lstm_weight
            new_rf_weight /= weight_sum
            new_lstm_weight /= weight_sum

            # Update weights
            old_rf_weight = self.rf_weight
            old_lstm_weight = self.lstm_weight

            self.rf_weight = new_rf_weight
            self.lstm_weight = new_lstm_weight

            logger.info(
                f"Weights adjusted based on recent accuracy: "
                f"RF: {old_rf_weight:.3f}→{new_rf_weight:.3f} (acc={rf_accuracy:.3f}), "
                f"LSTM: {old_lstm_weight:.3f}→{new_lstm_weight:.3f} (acc={lstm_accuracy:.3f})"
            )

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get ensemble predictor metrics.

        Returns:
            Dictionary with metrics
        """
        agreement_rate = (
            self.total_agreements / self.total_predictions
            if self.total_predictions > 0
            else 0.0
        )

        rf_recent_accuracy = (
            sum(self.rf_recent_correct) / len(self.rf_recent_correct)
            if len(self.rf_recent_correct) > 0
            else 0.0
        )

        lstm_recent_accuracy = (
            sum(self.lstm_recent_correct) / len(self.lstm_recent_correct)
            if len(self.lstm_recent_correct) > 0
            else 0.0
        )

        return {
            "total_predictions": self.total_predictions,
            "total_agreements": self.total_agreements,
            "agreement_rate": agreement_rate,
            "current_weights": {
                "rf": self.rf_weight,
                "lstm": self.lstm_weight
            },
            "recent_accuracy": {
                "rf": rf_recent_accuracy,
                "lstm": lstm_recent_accuracy,
                "samples": len(self.rf_recent_correct)
            }
        }

    def reset_weights(self, rf_weight: float = 0.6, lstm_weight: float = 0.4):
        """
        Reset weights to defaults.

        Args:
            rf_weight: RF weight (default 0.6)
            lstm_weight: LSTM weight (default 0.4)
        """
        self.rf_weight = rf_weight
        self.lstm_weight = lstm_weight

        logger.info(f"Weights reset to RF={rf_weight:.2f}, LSTM={lstm_weight:.2f}")


# Export for convenience
__all__ = [
    "PRDEnsemblePredictor",
]
