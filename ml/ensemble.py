"""
ml/ensemble.py - Lightweight Ensemble Predictor

Lightweight ensemble predictor for trade confidence filtering.
Combines multiple simple models (logistic, tree) to produce confidence ∈ [0,1].

Per PRD §7:
- Direction classifier (prob up/down)
- Move magnitude regressor
- Confidence aggregation
- MIN_ALIGNMENT_CONFIDENCE filter

Models:
1. Logistic Regression: Returns + RSI + ADX features
2. Decision Tree: Engineered features (momentum, volatility, regime)
3. Simple Momentum: Price momentum + volume
4. Volatility Filter: Penalizes high volatility

Ensemble: Weighted average of model confidences

Features:
- Lightweight (no external model files required)
- Fast inference (< 5ms)
- Deterministic with fixed seed
- Graceful degradation (returns 0.5 if error)
- No training required (uses simple heuristics)

Author: Crypto AI Bot Team
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from ai_engine.schemas import MarketSnapshot

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

class MLConfig(BaseModel):
    """
    ML confidence filter configuration.

    Attributes:
        enabled: Whether ML filtering is enabled
        min_alignment_confidence: Minimum confidence to execute trade [0, 1]
        logistic_weight: Weight for logistic model
        tree_weight: Weight for tree model
        momentum_weight: Weight for momentum model
        volatility_weight: Weight for volatility filter
        lookback_periods: Periods for feature calculation
        rsi_period: RSI calculation period
        adx_period: ADX calculation period
        vol_period: Volatility calculation period
    """
    enabled: bool = Field(default=True, description="Enable ML filtering")
    min_alignment_confidence: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold"
    )

    # Model weights (must sum to 1.0)
    logistic_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    tree_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    momentum_weight: float = Field(default=0.30, ge=0.0, le=1.0)
    volatility_weight: float = Field(default=0.20, ge=0.0, le=1.0)

    # Feature parameters
    lookback_periods: int = Field(default=20, ge=5, le=100)
    rsi_period: int = Field(default=14, ge=5, le=50)
    adx_period: int = Field(default=14, ge=5, le=50)
    vol_period: int = Field(default=20, ge=5, le=100)


# =============================================================================
# PREDICTION RESULT
# =============================================================================

@dataclass
class PredictionResult:
    """
    Ensemble prediction result.

    Attributes:
        confidence: Overall confidence [0, 1]
        prob_up: Probability of upward move [0, 1]
        prob_down: Probability of downward move [0, 1]
        components: Individual model confidences
        features: Computed features (for debugging)
    """
    confidence: float
    prob_up: float
    prob_down: float
    components: dict[str, float]
    features: dict[str, float]


# =============================================================================
# ENSEMBLE PREDICTOR
# =============================================================================

class EnsemblePredictor:
    """
    Lightweight ensemble predictor for trade confidence.

    Combines multiple simple models to produce overall confidence.
    Fast, deterministic, no external dependencies.
    """

    def __init__(self, config: Optional[MLConfig] = None):
        """
        Initialize ensemble predictor.

        Args:
            config: ML configuration (uses defaults if None)
        """
        self.config = config or MLConfig()
        self._call_count = 0
        self._filter_count = 0

        # Validate weights sum to ~1.0
        total_weight = (
            self.config.logistic_weight +
            self.config.tree_weight +
            self.config.momentum_weight +
            self.config.volatility_weight
        )

        if abs(total_weight - 1.0) > 0.01:
            logger.warning(f"Model weights sum to {total_weight:.3f}, not 1.0. Normalizing.")
            norm = total_weight
            self.config.logistic_weight /= norm
            self.config.tree_weight /= norm
            self.config.momentum_weight /= norm
            self.config.volatility_weight /= norm

        logger.info(f"EnsemblePredictor initialized: min_confidence={self.config.min_alignment_confidence:.2f}")

    def predict(
        self,
        snapshot: MarketSnapshot,
        ohlcv_df: pd.DataFrame,
        side: str = "long",
    ) -> PredictionResult:
        """
        Predict confidence for trade.

        Args:
            snapshot: Current market snapshot
            ohlcv_df: Historical OHLCV data
            side: Trade direction ("long" or "short")

        Returns:
            PredictionResult with confidence and components
        """
        self._call_count += 1

        try:
            # Compute features
            features = self._compute_features(ohlcv_df)

            # Run individual models
            logistic_conf = self._logistic_model(features, side)
            tree_conf = self._tree_model(features, side)
            momentum_conf = self._momentum_model(features, side)
            volatility_conf = self._volatility_filter(features)

            # Weighted ensemble
            confidence = (
                self.config.logistic_weight * logistic_conf +
                self.config.tree_weight * tree_conf +
                self.config.momentum_weight * momentum_conf +
                self.config.volatility_weight * volatility_conf
            )

            # Clip to [0, 1]
            confidence = max(0.0, min(1.0, confidence))

            # Prob up/down based on side
            if side == "long":
                prob_up = confidence
                prob_down = 1.0 - confidence
            else:
                prob_up = 1.0 - confidence
                prob_down = confidence

            # Components for debugging
            components = {
                "logistic": logistic_conf,
                "tree": tree_conf,
                "momentum": momentum_conf,
                "volatility": volatility_conf,
            }

            result = PredictionResult(
                confidence=confidence,
                prob_up=prob_up,
                prob_down=prob_down,
                components=components,
                features=features,
            )

            # Track filtering
            if confidence < self.config.min_alignment_confidence:
                self._filter_count += 1

            logger.debug(
                f"Prediction: confidence={confidence:.3f}, side={side}, "
                f"components={components}"
            )

            return result

        except Exception as e:
            logger.error(f"Prediction error: {e}", exc_info=True)
            # Graceful degradation: return neutral confidence
            return PredictionResult(
                confidence=0.5,
                prob_up=0.5,
                prob_down=0.5,
                components={},
                features={},
            )

    def should_trade(self, result: PredictionResult) -> bool:
        """
        Check if confidence meets threshold.

        Args:
            result: Prediction result

        Returns:
            True if confidence >= min_alignment_confidence
        """
        return result.confidence >= self.config.min_alignment_confidence

    # -------------------------------------------------------------------------
    # FEATURE COMPUTATION
    # -------------------------------------------------------------------------

    def _compute_features(self, ohlcv_df: pd.DataFrame) -> dict[str, float]:
        """
        Compute features from OHLCV data.

        Args:
            ohlcv_df: Historical OHLCV DataFrame

        Returns:
            Dict of features
        """
        if len(ohlcv_df) < self.config.lookback_periods:
            # Not enough data, return neutral features
            return {
                "returns_1": 0.0,
                "returns_5": 0.0,
                "returns_10": 0.0,
                "rsi": 50.0,
                "adx": 0.0,
                "volatility": 0.0,
                "volume_ratio": 1.0,
                "momentum_score": 0.0,
            }

        # Extract arrays
        close = ohlcv_df["close"].values
        high = ohlcv_df["high"].values
        low = ohlcv_df["low"].values
        volume = ohlcv_df["volume"].values

        # Returns
        returns_1 = (close[-1] - close[-2]) / close[-2] if len(close) > 1 else 0.0
        returns_5 = (close[-1] - close[-6]) / close[-6] if len(close) > 5 else 0.0
        returns_10 = (close[-1] - close[-11]) / close[-11] if len(close) > 10 else 0.0

        # RSI
        rsi = self._calculate_rsi(close, self.config.rsi_period)

        # ADX
        adx = self._calculate_adx(high, low, close, self.config.adx_period)

        # Volatility (realized)
        returns = np.diff(close) / close[:-1]
        volatility = np.std(returns[-self.config.vol_period:]) if len(returns) >= self.config.vol_period else 0.0

        # Volume ratio (current vs average)
        avg_volume = np.mean(volume[-20:]) if len(volume) >= 20 else volume[-1]
        volume_ratio = volume[-1] / avg_volume if avg_volume > 0 else 1.0

        # Momentum score (simple)
        momentum_score = returns_1 * 0.5 + returns_5 * 0.3 + returns_10 * 0.2

        return {
            "returns_1": float(returns_1),
            "returns_5": float(returns_5),
            "returns_10": float(returns_10),
            "rsi": float(rsi),
            "adx": float(adx),
            "volatility": float(volatility),
            "volume_ratio": float(volume_ratio),
            "momentum_score": float(momentum_score),
        }

    def _calculate_rsi(self, close: np.ndarray, period: int) -> float:
        """Calculate RSI"""
        if len(close) < period + 1:
            return 50.0

        delta = np.diff(close)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)

        avg_gain = np.mean(gain[-period:])
        avg_loss = np.mean(loss[-period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return float(rsi)

    def _calculate_adx(
        self,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        period: int,
    ) -> float:
        """Calculate ADX (simplified)"""
        if len(close) < period + 1:
            return 0.0

        # True Range
        tr1 = high - low
        tr2 = np.abs(high - np.roll(close, 1))
        tr3 = np.abs(low - np.roll(close, 1))
        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        tr[0] = high[0] - low[0]

        # ATR
        atr = np.mean(tr[-period:])

        # Simplified ADX approximation
        adx = (atr / np.mean(close[-period:])) * 100 if np.mean(close[-period:]) > 0 else 0.0

        return float(np.clip(adx, 0, 100))

    # -------------------------------------------------------------------------
    # MODELS
    # -------------------------------------------------------------------------

    def _logistic_model(self, features: dict[str, float], side: str) -> float:
        """
        Logistic model based on returns, RSI, ADX.

        Simple heuristic model:
        - Positive returns → higher confidence
        - RSI in favorable range → higher confidence
        - High ADX (trending) → higher confidence
        """
        # Base confidence from returns
        returns = features["returns_1"] + features["returns_5"]

        if side == "long":
            # Long: want positive returns, RSI not overbought
            ret_score = 1.0 / (1.0 + np.exp(-returns * 20))  # Sigmoid
            rsi_score = 1.0 - abs(features["rsi"] - 50) / 50.0  # Closer to 50 = better
            if features["rsi"] > 70:
                rsi_score *= 0.5  # Penalize overbought
        else:
            # Short: want negative returns, RSI not oversold
            ret_score = 1.0 / (1.0 + np.exp(returns * 20))  # Inverted sigmoid
            rsi_score = 1.0 - abs(features["rsi"] - 50) / 50.0
            if features["rsi"] < 30:
                rsi_score *= 0.5  # Penalize oversold

        # ADX score (higher = more trending = better)
        adx_score = min(features["adx"] / 50.0, 1.0)

        # Weighted combination
        confidence = ret_score * 0.5 + rsi_score * 0.3 + adx_score * 0.2

        return max(0.0, min(1.0, confidence))

    def _tree_model(self, features: dict[str, float], side: str) -> float:
        """
        Decision tree model based on engineered features.

        Simple rule-based model:
        - Check momentum score
        - Check volatility regime
        - Check volume confirmation
        """
        momentum = features["momentum_score"]
        volatility = features["volatility"]
        volume_ratio = features["volume_ratio"]

        if side == "long":
            # Long rules
            if momentum > 0.01 and volume_ratio > 1.2 and volatility < 0.03:
                confidence = 0.8
            elif momentum > 0.005 and volume_ratio > 1.0:
                confidence = 0.6
            elif momentum > 0:
                confidence = 0.55
            else:
                confidence = 0.4
        else:
            # Short rules
            if momentum < -0.01 and volume_ratio > 1.2 and volatility < 0.03:
                confidence = 0.8
            elif momentum < -0.005 and volume_ratio > 1.0:
                confidence = 0.6
            elif momentum < 0:
                confidence = 0.55
            else:
                confidence = 0.4

        return confidence

    def _momentum_model(self, features: dict[str, float], side: str) -> float:
        """
        Momentum model based on price and volume momentum.

        Simple momentum confirmation:
        - Price momentum aligned with side
        - Volume confirming move
        """
        momentum = features["momentum_score"]
        volume_ratio = features["volume_ratio"]

        if side == "long":
            momentum_conf = 1.0 / (1.0 + np.exp(-momentum * 50))
        else:
            momentum_conf = 1.0 / (1.0 + np.exp(momentum * 50))

        # Volume confirmation boost
        volume_boost = min((volume_ratio - 1.0) * 0.2, 0.2) if volume_ratio > 1.0 else 0.0

        confidence = momentum_conf + volume_boost

        return max(0.0, min(1.0, confidence))

    def _volatility_filter(self, features: dict[str, float]) -> float:
        """
        Volatility filter model.

        Penalizes high volatility (more uncertain).
        Returns confidence based on volatility regime.
        """
        volatility = features["volatility"]

        # Low volatility = high confidence
        # High volatility = low confidence
        if volatility < 0.01:
            confidence = 0.9
        elif volatility < 0.02:
            confidence = 0.7
        elif volatility < 0.03:
            confidence = 0.5
        else:
            confidence = 0.3

        return confidence

    # -------------------------------------------------------------------------
    # METRICS
    # -------------------------------------------------------------------------

    def get_metrics(self) -> dict[str, int]:
        """Get predictor metrics"""
        return {
            "total_predictions": self._call_count,
            "filtered_trades": self._filter_count,
            "filter_rate": self._filter_count / self._call_count if self._call_count > 0 else 0.0,
        }


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def predict_confidence(
    snapshot: MarketSnapshot,
    ohlcv_df: pd.DataFrame,
    side: str = "long",
    config: Optional[MLConfig] = None,
) -> float:
    """
    Convenience function to predict confidence.

    Args:
        snapshot: Market snapshot
        ohlcv_df: Historical OHLCV data
        side: Trade direction
        config: ML configuration

    Returns:
        Confidence value [0, 1]

    Example:
        >>> confidence = predict_confidence(snapshot, ohlcv_df, side="long")
        >>> if confidence >= 0.55:
        ...     # Execute trade
        ...     pass
    """
    predictor = EnsemblePredictor(config=config)
    result = predictor.predict(snapshot, ohlcv_df, side)
    return result.confidence


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "MLConfig",
    "PredictionResult",
    "EnsemblePredictor",
    "predict_confidence",
]
