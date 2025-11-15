"""
ml - Lightweight ML Ensemble for Confidence Filtering

Lightweight ensemble predictor that produces confidence ∈ [0,1] for trade filtering.

Per PRD §7:
- Ensemble predictors (direction classifier, move magnitude regressor)
- Produce confidence ∈ [0,1]
- Filter: suppress trades under MIN_ALIGNMENT_CONFIDENCE
- Optional majority vote gating

Exports:
- EnsemblePredictor: Main ensemble class
- MLConfig: Configuration
- predict_confidence: Convenience function

Example:
    >>> from ml import EnsemblePredictor, MLConfig
    >>> config = MLConfig(min_alignment_confidence=0.55)
    >>> predictor = EnsemblePredictor(config=config)
    >>> confidence = predictor.predict(snapshot, ohlcv_df)
    >>> if confidence >= config.min_alignment_confidence:
    ...     # Execute trade
    ...     pass

Author: Crypto AI Bot Team
"""

from ml.ensemble import EnsemblePredictor, MLConfig, predict_confidence

__all__ = [
    "EnsemblePredictor",
    "MLConfig",
    "predict_confidence",
]
