"""
PRD-001 Compliant Transparent Predictor Wrapper

This module wraps the existing EnhancedPredictorV2 with PRD-001 Section 3.4 compliance:
- Log feature importance for every prediction (top 5 features with weights)
- Store feature importance in metadata.feature_importance field
- Use SHAP values for model explainability
- Publish model predictions to events:bus stream for audit trail
- Log model version in signal metadata.model_version field

Architecture:
- Wraps ml/predictor_v2.py
- Adds feature importance logging, SHAP support, audit trail
- Maintains backward compatibility with existing predictor

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, List
from decimal import Decimal

import numpy as np

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    shap = None

# PRD-001 Section 3.4: Prometheus metrics
try:
    from prometheus_client import Counter
    MODEL_PREDICTIONS_TOTAL = Counter(
        'model_predictions_total',
        'Total model predictions made',
        ['model_version', 'pair']
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    MODEL_PREDICTIONS_TOTAL = None

from ml.predictor_v2 import EnhancedPredictorV2

logger = logging.getLogger(__name__)


class PRDTransparentPredictor:
    """
    PRD-001 Section 3.4 compliant transparent ML predictor.

    Wraps EnhancedPredictorV2 and adds:
    - Feature importance logging (top 5 features)
    - SHAP value calculation for explainability
    - Prediction audit trail publishing to events:bus
    - Model version tracking
    - Metadata population with feature importance

    Usage:
        predictor = PRDTransparentPredictor(
            model_path=Path("models/predictor_v2.1.pkl"),
            redis_client=redis_client,
            model_version="v2.1"
        )

        result = predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )
        # Returns: {
        #   "probability": 0.75,
        #   "feature_importance": {...},
        #   "shap_values": {...} (if available),
        #   "model_version": "v2.1"
        # }
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        redis_client = None,
        model_version: str = "v2.0",
        use_shap: bool = True,
        publish_audit: bool = True,
        top_k_features: int = 5
    ):
        """
        Initialize PRD-compliant transparent predictor.

        Args:
            model_path: Path to saved model (if loading pre-trained)
            redis_client: Redis client for audit trail publishing
            model_version: Model version string (e.g., "v2.1")
            use_shap: Calculate SHAP values if available (may be slow)
            publish_audit: Publish predictions to events:bus stream
            top_k_features: Number of top features to log (default 5)
        """
        self.predictor = EnhancedPredictorV2(model_path=model_path)
        self.redis_client = redis_client
        self.model_version = model_version
        self.use_shap = use_shap and SHAP_AVAILABLE
        self.publish_audit = publish_audit
        self.top_k_features = top_k_features

        # Initialize SHAP explainer if using LightGBM and SHAP is available
        self.shap_explainer = None
        if self.use_shap and self.predictor._fitted and self.predictor.use_lightgbm:
            try:
                self.shap_explainer = shap.TreeExplainer(self.predictor.model)
                logger.info("SHAP explainer initialized for model transparency")
            except Exception as e:
                logger.warning(f"Failed to initialize SHAP explainer: {e}")
                self.shap_explainer = None

        logger.info(
            f"PRDTransparentPredictor initialized: version={model_version}, "
            f"shap_enabled={self.shap_explainer is not None}, "
            f"audit_enabled={publish_audit}"
        )

    def predict_with_transparency(
        self,
        ctx: Dict[str, Any],
        pair: str = "BTC/USD"
    ) -> Dict[str, Any]:
        """
        Make prediction with full transparency and audit trail.

        PRD-001 Section 3.4 compliance:
        1. Calculate prediction probability
        2. Extract feature importance (top K features)
        3. Calculate SHAP values if enabled
        4. Log feature importance at INFO level
        5. Publish prediction to events:bus for audit
        6. Return enriched result with metadata

        Args:
            ctx: Market context dict (see EnhancedPredictorV2._compute_enhanced_features)
            pair: Trading pair (for logging and metrics)

        Returns:
            Dictionary with:
                - probability: Predicted probability [0, 1]
                - feature_importance: Dict of top K features and their importance
                - shap_values: Dict of SHAP values (if enabled)
                - model_version: Model version string
                - features: Computed feature values
                - timestamp: Prediction timestamp
        """
        start_time = time.time()

        # 1. Make prediction
        probability = self.predictor.predict_proba(ctx)

        # 2. Compute features for transparency
        features = self.predictor._compute_enhanced_features(ctx)
        feature_dict = {
            name: float(value)
            for name, value in zip(self.predictor.feature_names_, features)
        }

        # 3. PRD-001 Section 3.4: Extract feature importance (top K features)
        feature_importance = self._get_feature_importance()

        # 4. PRD-001 Section 3.4: Calculate SHAP values if enabled
        shap_values_dict = None
        if self.shap_explainer and self.use_shap:
            shap_values_dict = self._calculate_shap_values(features)

        # Build result
        result = {
            "probability": float(probability),
            "feature_importance": feature_importance,
            "shap_values": shap_values_dict,
            "model_version": self.model_version,
            "features": feature_dict,
            "timestamp": time.time(),
            "pair": pair,
            "latency_ms": (time.time() - start_time) * 1000
        }

        # 5. PRD-001 Section 3.4: Log feature importance at INFO level (top 5)
        self._log_feature_importance(pair, probability, feature_importance)

        # 6. PRD-001 Section 3.4: Publish to events:bus for audit trail
        if self.publish_audit and self.redis_client:
            self._publish_audit_trail(result)

        # 7. PRD-001 Section 3.4: Emit Prometheus counter
        if PROMETHEUS_AVAILABLE and MODEL_PREDICTIONS_TOTAL:
            MODEL_PREDICTIONS_TOTAL.labels(
                model_version=self.model_version,
                pair=pair
            ).inc()

        return result

    def _get_feature_importance(self) -> Dict[str, float]:
        """
        Get feature importance from fitted model.

        For LightGBM: Uses feature_importance(importance_type='gain')
        For sklearn: Uses feature_importances_ attribute

        Returns:
            Dictionary of {feature_name: importance} for top K features
        """
        if not self.predictor._fitted:
            return {}

        try:
            if self.predictor.use_lightgbm:
                # LightGBM feature importance (gain)
                importance_values = self.predictor.model.feature_importance(importance_type='gain')
            else:
                # sklearn RandomForest/GradientBoosting
                importance_values = self.predictor.model.feature_importances_

            # Create dict of all features with importance
            all_importance = {
                name: float(imp)
                for name, imp in zip(self.predictor.feature_names_, importance_values)
            }

            # Sort by importance and take top K
            sorted_features = sorted(
                all_importance.items(),
                key=lambda x: x[1],
                reverse=True
            )[:self.top_k_features]

            return dict(sorted_features)

        except Exception as e:
            logger.warning(f"Failed to get feature importance: {e}")
            return {}

    def _calculate_shap_values(self, features: np.ndarray) -> Optional[Dict[str, float]]:
        """
        Calculate SHAP values for prediction explainability.

        PRD-001 Section 3.4: Use SHAP values for LSTM model explainability
        Note: While the PRD mentions LSTM, SHAP works for LightGBM as well

        Args:
            features: Feature array [20 features]

        Returns:
            Dictionary of {feature_name: shap_value} or None if failed
        """
        if not self.shap_explainer:
            return None

        try:
            # Calculate SHAP values for this prediction
            shap_values = self.shap_explainer.shap_values(features.reshape(1, -1))

            # For binary classification, shap_values might be a list of 2 arrays
            if isinstance(shap_values, list):
                shap_values = shap_values[1]  # Take positive class SHAP values

            # Convert to dict
            shap_dict = {
                name: float(value)
                for name, value in zip(self.predictor.feature_names_, shap_values[0])
            }

            return shap_dict

        except Exception as e:
            logger.warning(f"Failed to calculate SHAP values: {e}")
            return None

    def _log_feature_importance(
        self,
        pair: str,
        probability: float,
        feature_importance: Dict[str, float]
    ) -> None:
        """
        Log feature importance at INFO level.

        PRD-001 Section 3.4: Log feature importance for every prediction (top 5 features)

        Args:
            pair: Trading pair
            probability: Predicted probability
            feature_importance: Top K features with importance weights
        """
        if not feature_importance:
            return

        # Format top features
        top_features_str = ", ".join([
            f"{name}={weight:.4f}"
            for name, weight in feature_importance.items()
        ])

        logger.info(
            f"[MODEL PREDICTION] {pair} | Probability: {probability:.3f} | "
            f"Version: {self.model_version} | "
            f"Top Features: {top_features_str}"
        )

    def _publish_audit_trail(self, result: Dict[str, Any]) -> None:
        """
        Publish prediction to events:bus stream for audit trail.

        PRD-001 Section 3.4: Publish model predictions to events:bus for audit trail

        Args:
            result: Prediction result dict
        """
        if not self.redis_client:
            return

        try:
            # Build audit event
            audit_event = {
                "event_type": "model_prediction",
                "timestamp": result["timestamp"],
                "model_version": result["model_version"],
                "pair": result["pair"],
                "probability": result["probability"],
                "feature_importance": result["feature_importance"],
                "latency_ms": result["latency_ms"],
            }

            # Add SHAP values if available (may be large, so optional)
            if result.get("shap_values"):
                audit_event["shap_values"] = result["shap_values"]

            # Publish to events:bus stream
            # Note: Assuming redis client has xadd method
            self.redis_client.xadd(
                "events:bus",
                audit_event,
                maxlen=10000  # Keep last 10k events
            )

            logger.debug(f"Published prediction audit event for {result['pair']}")

        except Exception as e:
            logger.warning(f"Failed to publish audit trail: {e}")

    def get_feature_documentation(self) -> List[Dict[str, Any]]:
        """
        Get documentation for all features.

        Returns:
            List of feature metadata dicts with:
                - name: Feature name
                - formula: How it's calculated
                - purpose: What it measures
                - expected_range: Typical value range
        """
        # Feature documentation (PRD-001 Section 3.4 requirement)
        return [
            # Base technical features (4)
            {
                "name": "returns",
                "formula": "log(close[t] / close[t-1])",
                "purpose": "Price momentum",
                "expected_range": "[-0.1, 0.1]"
            },
            {
                "name": "rsi",
                "formula": "RSI(14)",
                "purpose": "Overbought/oversold indicator",
                "expected_range": "[0, 100]"
            },
            {
                "name": "adx",
                "formula": "ADX(14)",
                "purpose": "Trend strength",
                "expected_range": "[0, 100]"
            },
            {
                "name": "slope",
                "formula": "Linear regression slope of closes",
                "purpose": "Trend direction",
                "expected_range": "[-1.0, 1.0]"
            },
            # Sentiment features (5)
            {
                "name": "tw_sentiment",
                "formula": "Twitter sentiment score (5-min aggregation)",
                "purpose": "Social media sentiment",
                "expected_range": "[-1.0, 1.0]"
            },
            {
                "name": "rd_sentiment",
                "formula": "Reddit sentiment score (5-min aggregation)",
                "purpose": "Community sentiment",
                "expected_range": "[-1.0, 1.0]"
            },
            {
                "name": "news_sentiment",
                "formula": "News sentiment score (5-min aggregation)",
                "purpose": "Media sentiment",
                "expected_range": "[-1.0, 1.0]"
            },
            {
                "name": "sentiment_delta",
                "formula": "current_sentiment - prev_sentiment (5-min lag)",
                "purpose": "Sentiment momentum",
                "expected_range": "[-1.0, 1.0]"
            },
            {
                "name": "sentiment_confidence",
                "formula": "Sentiment score confidence",
                "purpose": "Sentiment reliability",
                "expected_range": "[0.0, 1.0]"
            },
            # Whale flow features (5)
            {
                "name": "whale_inflow_ratio",
                "formula": "Large buy orders / total volume",
                "purpose": "Institutional buying pressure",
                "expected_range": "[0.0, 1.0]"
            },
            {
                "name": "whale_outflow_ratio",
                "formula": "Large sell orders / total volume",
                "purpose": "Institutional selling pressure",
                "expected_range": "[0.0, 1.0]"
            },
            {
                "name": "whale_net_flow",
                "formula": "inflow_ratio - outflow_ratio",
                "purpose": "Net institutional flow",
                "expected_range": "[-1.0, 1.0]"
            },
            {
                "name": "whale_orderbook_imbalance",
                "formula": "(bid_depth - ask_depth) / (bid_depth + ask_depth)",
                "purpose": "Orderbook skew from large orders",
                "expected_range": "[-1.0, 1.0]"
            },
            {
                "name": "whale_smart_money_divergence",
                "formula": "whale_flow divergence from price action",
                "purpose": "Smart money vs. market divergence",
                "expected_range": "[-1.0, 1.0]"
            },
            # Liquidation features (4)
            {
                "name": "liq_imbalance",
                "formula": "(long_liq - short_liq) / total_liq",
                "purpose": "Liquidation pressure direction",
                "expected_range": "[-1.0, 1.0]"
            },
            {
                "name": "cascade_severity",
                "formula": "Liquidation cascade detection score",
                "purpose": "Risk of liquidation cascade",
                "expected_range": "[0.0, 1.0]"
            },
            {
                "name": "funding_spread",
                "formula": "Perpetual funding rate spread",
                "purpose": "Long/short sentiment in futures",
                "expected_range": "[-0.01, 0.01]"
            },
            {
                "name": "liquidation_pressure",
                "formula": "Total liquidation volume / market volume",
                "purpose": "Overall liquidation stress",
                "expected_range": "[0.0, 1.0]"
            },
            # Market microstructure (2)
            {
                "name": "volume_surge",
                "formula": "current_volume / avg_volume(24h)",
                "purpose": "Volume anomaly detection",
                "expected_range": "[0.0, 10.0]"
            },
            {
                "name": "volatility_regime",
                "formula": "ATR(14) / price (normalized)",
                "purpose": "Current volatility level",
                "expected_range": "[0.0, 1.0]"
            },
        ]

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get predictor metrics.

        Returns:
            Dictionary with metrics
        """
        return {
            "model_version": self.model_version,
            "shap_enabled": self.shap_explainer is not None,
            "audit_enabled": self.publish_audit,
            "top_k_features": self.top_k_features,
            "num_features": len(self.predictor.feature_names_),
            "fitted": self.predictor._fitted,
            "uses_lightgbm": self.predictor.use_lightgbm,
        }


# Export for convenience
__all__ = [
    "PRDTransparentPredictor",
]
