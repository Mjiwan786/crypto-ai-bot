"""
Enhanced ML Predictor V2 (ml/predictor_v2.py)

Advanced predictor with sentiment, whale flow, and liquidations features.

For Prompt 2: ML Predictor Enhancement
Features:
- Twitter/Reddit sentiment delta (5-min lag)
- Whale inflow/outflow ratios
- Liquidations imbalance + cascade detection
- Perp funding spread
- LightGBM model for non-linear relationships

Author: Crypto AI Bot Team
Version: 2.0.0
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    lgb = None

from ml.predictors import BasePredictor
from ai_engine.whale_detection import detect_whale_flow, WhaleFlowMetrics
from ai_engine.liquidations_tracker import LiquidationsTracker, LiquidationMetrics
from ai_engine.regime_detector.sentiment_analyzer import (
    detect_sentiment_regime,
    SentimentConfig,
)

logger = logging.getLogger(__name__)


class EnhancedPredictorV2(BasePredictor):
    """
    Enhanced ML predictor with sentiment, whale flow, and liquidations.

    Features (20 total):
    - Base features (4): returns, rsi, adx, slope
    - Sentiment features (5): tw_sentiment, rd_sentiment, news_sentiment, sentiment_delta, sentiment_confidence
    - Whale flow features (5): inflow_ratio, outflow_ratio, net_flow, orderbook_imbalance, smart_money_divergence
    - Liquidation features (4): liq_imbalance, cascade_severity, funding_spread, liquidation_pressure
    - Market microstructure (2): volume_surge, volatility_regime

    Model: LightGBM (or fallback to sklearn)
    """

    def __init__(
        self,
        seed: int = 42,
        model_path: Optional[Path] = None,
        use_lightgbm: bool = True,
    ):
        """
        Initialize enhanced predictor.

        Args:
            seed: Random seed for reproducibility
            model_path: Path to saved model (if loading pre-trained)
            use_lightgbm: Use LightGBM if available (else fallback to sklearn)
        """
        super().__init__(seed)

        self.use_lightgbm = use_lightgbm and LIGHTGBM_AVAILABLE
        self.model_path = model_path
        self.model = None
        self._fitted = False
        self.sentiment_config = SentimentConfig()
        self.liquidations_tracker = LiquidationsTracker()

        # Feature names (20 features)
        self.feature_names_ = [
            # Base technical (4)
            "returns",
            "rsi",
            "adx",
            "slope",
            # Sentiment (5)
            "tw_sentiment",
            "rd_sentiment",
            "news_sentiment",
            "sentiment_delta",
            "sentiment_confidence",
            # Whale flow (5)
            "whale_inflow_ratio",
            "whale_outflow_ratio",
            "whale_net_flow",
            "whale_orderbook_imbalance",
            "whale_smart_money_divergence",
            # Liquidations (4)
            "liq_imbalance",
            "cascade_severity",
            "funding_spread",
            "liquidation_pressure",
            # Market microstructure (2)
            "volume_surge",
            "volatility_regime",
        ]

        # Load pre-trained model if path provided
        if model_path and model_path.exists():
            self.load_model(model_path)

        logger.info(
            "EnhancedPredictorV2 initialized (lightgbm=%s, features=%d)",
            self.use_lightgbm,
            len(self.feature_names_),
        )

    def _compute_enhanced_features(self, ctx: Dict[str, Any]) -> np.ndarray:
        """
        Compute all 20 enhanced features.

        Args:
            ctx: Market context with:
                - ohlcv_df: DataFrame
                - current_price: float
                - timeframe: str
                - sentiment_df: Optional[DataFrame] (for sentiment)
                - bid_depth: Optional[Dict] (for whale detection)
                - ask_depth: Optional[Dict]
                - funding_rate: Optional[float]
                - liquidations: Optional[List[Dict]] (recent liquidation events)

        Returns:
            Feature array [20 features]
        """
        df = ctx["ohlcv_df"]
        current_price = ctx.get("current_price", df["close"].iloc[-1])
        current_volume = df["volume"].iloc[-1] if len(df) > 0 else 0.0

        # 1. Base technical features (4)
        base_features = super()._compute_features(ctx)  # [returns, rsi, adx, slope]

        # 2. Sentiment features (5)
        sentiment_df = ctx.get("sentiment_df")
        if sentiment_df is not None and not sentiment_df.empty:
            try:
                sentiment_result = detect_sentiment_regime(
                    df=sentiment_df,
                    timeframe=ctx.get("timeframe", "5m"),
                    config=self.sentiment_config,
                )
                tw_sentiment = sentiment_result.features.get("tw_score_s", 0.0)
                rd_sentiment = sentiment_result.features.get("rd_score_s", 0.0)
                news_sentiment = sentiment_result.features.get("news_score_s", 0.0)

                # Sentiment delta (5-min change)
                if len(sentiment_df) >= 2:
                    prev_sentiment = (
                        sentiment_df["tw_score"].iloc[-2] * 0.45 +
                        sentiment_df["rd_score"].iloc[-2] * 0.35 +
                        sentiment_df["news_score"].iloc[-2] * 0.20
                    )
                    current_sentiment = (
                        tw_sentiment * 0.45 +
                        rd_sentiment * 0.35 +
                        news_sentiment * 0.20
                    )
                    sentiment_delta = current_sentiment - prev_sentiment
                else:
                    sentiment_delta = 0.0

                sentiment_confidence = sentiment_result.confidence
            except Exception as e:
                logger.warning("Sentiment features failed: %s", e)
                tw_sentiment = rd_sentiment = news_sentiment = 0.0
                sentiment_delta = 0.0
                sentiment_confidence = 0.0
        else:
            tw_sentiment = rd_sentiment = news_sentiment = 0.0
            sentiment_delta = 0.0
            sentiment_confidence = 0.0

        sentiment_features = np.array([
            tw_sentiment,
            rd_sentiment,
            news_sentiment,
            sentiment_delta,
            sentiment_confidence,
        ])

        # 3. Whale flow features (5)
        bid_depth = ctx.get("bid_depth")
        ask_depth = ctx.get("ask_depth")
        try:
            whale_metrics = detect_whale_flow(
                df=df,
                price=current_price,
                volume=current_volume,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
            )
            whale_features = np.array([
                whale_metrics.inflow_ratio,
                whale_metrics.outflow_ratio,
                whale_metrics.net_flow,
                whale_metrics.order_book_imbalance,
                whale_metrics.smart_money_divergence,
            ])
        except Exception as e:
            logger.warning("Whale flow features failed: %s", e)
            whale_features = np.zeros(5)

        # 4. Liquidation features (4)
        funding_rate = ctx.get("funding_rate", 0.0)
        liquidations_data = ctx.get("liquidations")

        # Add liquidation events if provided
        if liquidations_data:
            for liq in liquidations_data:
                self.liquidations_tracker.add_liquidation_event(
                    timestamp=liq.get("timestamp", 0),
                    side=liq.get("side", "long"),
                    amount_usd=liq.get("amount_usd", 0.0),
                    price=liq.get("price", current_price),
                )

        try:
            current_timestamp = int(pd.Timestamp.now().timestamp() * 1000)
            liq_metrics = self.liquidations_tracker.analyze_liquidations(
                current_timestamp=current_timestamp,
                current_funding_rate=funding_rate,
            )
            liquidation_features = np.array([
                liq_metrics.imbalance,
                liq_metrics.cascade_severity,
                liq_metrics.funding_spread / 100.0,  # Normalize bps to %
                liq_metrics.liquidation_pressure,
            ])
        except Exception as e:
            logger.warning("Liquidation features failed: %s", e)
            liquidation_features = np.zeros(4)

        # 5. Market microstructure features (2)
        # Volume surge (volume vs 20-period average)
        if len(df) >= 20:
            avg_volume = df["volume"].tail(20).mean()
            volume_surge = (current_volume / avg_volume - 1.0) if avg_volume > 0 else 0.0
            volume_surge = np.clip(volume_surge, -1.0, 3.0)  # Cap at 3x
        else:
            volume_surge = 0.0

        # Volatility regime (ATR as % of price)
        if "atr" in df.columns and len(df) > 0:
            atr_pct = df["atr"].iloc[-1] / current_price
        else:
            # Fallback: calculate simple range
            if len(df) >= 14:
                recent_highs = df["high"].tail(14)
                recent_lows = df["low"].tail(14)
                atr_proxy = (recent_highs - recent_lows).mean()
                atr_pct = atr_proxy / current_price
            else:
                atr_pct = 0.02  # Default 2%

        volatility_regime = float(np.clip(atr_pct * 100, 0.0, 10.0))  # 0-10 scale

        microstructure_features = np.array([volume_surge, volatility_regime])

        # Combine all features (4 + 5 + 5 + 4 + 2 = 20)
        all_features = np.concatenate([
            base_features,
            sentiment_features,
            whale_features,
            liquidation_features,
            microstructure_features,
        ])

        logger.debug("Enhanced features: %s", dict(zip(self.feature_names_, all_features)))

        return all_features

    def fit(self, X: np.ndarray, y: np.ndarray, **kwargs) -> None:
        """
        Fit predictor to training data.

        Args:
            X: Feature matrix [n_samples, n_features]
            y: Target labels [n_samples] (0/1 or -1/1)
            **kwargs: Additional arguments for LightGBM
        """
        # Ensure binary labels (0/1)
        y_binary = np.where(y > 0, 1, 0)

        if self.use_lightgbm:
            # LightGBM parameters
            params = {
                "objective": "binary",
                "metric": "auc",
                "boosting_type": "gbdt",
                "num_leaves": 31,
                "learning_rate": 0.05,
                "feature_fraction": 0.8,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "verbose": -1,
                "seed": self.seed,
                "n_estimators": 100,
                "early_stopping_rounds": 10,
            }
            params.update(kwargs)

            # Create dataset
            train_data = lgb.Dataset(X, label=y_binary)

            # Train model
            logger.info("Training LightGBM model (n_samples=%d, n_features=%d)", len(X), X.shape[1])
            self.model = lgb.train(
                params,
                train_data,
                valid_sets=[train_data],
                callbacks=[lgb.early_stopping(stopping_rounds=10, verbose=False)],
            )

        else:
            # Fallback to sklearn LogisticRegression
            from sklearn.linear_model import LogisticRegression

            logger.info("Training LogisticRegression fallback (n_samples=%d, n_features=%d)", len(X), X.shape[1])
            self.model = LogisticRegression(random_state=self.seed, max_iter=200)
            self.model.fit(X, y_binary)

        self._fitted = True
        logger.info("Model training complete (lightgbm=%s)", self.use_lightgbm)

    def predict_proba(self, ctx: Dict[str, Any]) -> float:
        """
        Predict probability of upward price movement.

        Args:
            ctx: Market context dict

        Returns:
            Probability in [0, 1]
        """
        if not self._fitted:
            logger.warning("Model not fitted, returning neutral probability")
            return 0.5

        try:
            features = self._compute_enhanced_features(ctx).reshape(1, -1)

            if self.use_lightgbm:
                prob_up = float(self.model.predict(features)[0])
            else:
                prob_up = float(self.model.predict_proba(features)[0, 1])

            prob_up = np.clip(prob_up, 0.0, 1.0)

            logger.debug("Predicted probability: %.3f", prob_up)
            return prob_up

        except Exception as e:
            logger.exception("Prediction error: %s", e)
            return 0.5  # Neutral on error

    def save_model(self, path: Path) -> None:
        """
        Save trained model to disk.

        Args:
            path: Path to save model (.pkl file)
        """
        if not self._fitted:
            raise ValueError("Cannot save unfitted model")

        path.parent.mkdir(parents=True, exist_ok=True)

        model_data = {
            "model": self.model,
            "use_lightgbm": self.use_lightgbm,
            "feature_names": self.feature_names_,
            "seed": self.seed,
        }

        with open(path, "wb") as f:
            pickle.dump(model_data, f)

        logger.info("Model saved to %s", path)

    def load_model(self, path: Path) -> None:
        """
        Load pre-trained model from disk.

        Args:
            path: Path to model file (.pkl)
        """
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        with open(path, "rb") as f:
            model_data = pickle.load(f)

        self.model = model_data["model"]
        self.use_lightgbm = model_data["use_lightgbm"]
        self.feature_names_ = model_data["feature_names"]
        self.seed = model_data.get("seed", 42)
        self._fitted = True

        logger.info("Model loaded from %s (lightgbm=%s)", path, self.use_lightgbm)

    def get_feature_importance(self) -> Dict[str, float]:
        """
        Get feature importance scores.

        Returns:
            Dictionary mapping feature names to importance scores
        """
        if not self._fitted:
            return {}

        if self.use_lightgbm:
            importance = self.model.feature_importance(importance_type="gain")
        else:
            # For sklearn, use coefficients
            if hasattr(self.model, "coef_"):
                importance = np.abs(self.model.coef_[0])
            else:
                return {}

        return dict(zip(self.feature_names_, importance))


# Convenience function for creating default predictor
def create_enhanced_predictor(
    model_path: Optional[Path] = None,
    use_lightgbm: bool = True,
) -> EnhancedPredictorV2:
    """
    Create enhanced predictor with default settings.

    Args:
        model_path: Path to pre-trained model (optional)
        use_lightgbm: Use LightGBM if available

    Returns:
        EnhancedPredictorV2 instance
    """
    return EnhancedPredictorV2(
        seed=42,
        model_path=model_path,
        use_lightgbm=use_lightgbm,
    )


# Self-check for development/testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    logger.info("Running EnhancedPredictorV2 self-check...")

    try:
        # Create predictor
        predictor = create_enhanced_predictor(use_lightgbm=LIGHTGBM_AVAILABLE)

        # Create synthetic training data
        np.random.seed(42)
        n_samples = 1000
        X_train = np.random.randn(n_samples, 20)  # 20 features
        y_train = (X_train[:, 0] + X_train[:, 5] + X_train[:, 10] > 0).astype(int)

        # Fit model
        predictor.fit(X_train, y_train)

        # Create test context
        test_df = pd.DataFrame({
            "close": [50000 + i * 10 for i in range(100)],
            "high": [50000 + i * 10 + 50 for i in range(100)],
            "low": [50000 + i * 10 - 50 for i in range(100)],
            "volume": [100 + np.random.randint(-10, 10) for _ in range(100)],
        })

        # Add ATR
        test_df["atr"] = 1000.0

        test_ctx = {
            "ohlcv_df": test_df,
            "current_price": 51000.0,
            "timeframe": "5m",
            "funding_rate": 0.0001,
        }

        # Predict
        prob = predictor.predict_proba(test_ctx)

        # Validate
        assert 0.0 <= prob <= 1.0, f"Invalid probability: {prob}"
        assert predictor._fitted
        assert len(predictor.feature_names_) == 20

        logger.info("Predicted probability: %.3f", prob)

        # Test feature importance
        importance = predictor.get_feature_importance()
        assert len(importance) > 0
        logger.info("Top 5 features: %s", sorted(importance.items(), key=lambda x: -x[1])[:5])

        # Test save/load
        test_path = Path("models/test_predictor_v2.pkl")
        predictor.save_model(test_path)

        predictor2 = create_enhanced_predictor(model_path=test_path)
        prob2 = predictor2.predict_proba(test_ctx)

        assert abs(prob - prob2) < 1e-6, "Loaded model produces different predictions"

        # Cleanup
        test_path.unlink()

        logger.info("Self-check passed!")
        sys.exit(0)

    except Exception as e:
        logger.error("Self-check failed: %s", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)
