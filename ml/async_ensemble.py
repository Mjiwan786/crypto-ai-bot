"""
Async Ensemble Predictor Wrapper

This module provides an async wrapper around PRDEnsemblePredictor to enable
non-blocking model inference in the trading bot pipeline.

Usage:
    async_ensemble = AsyncEnsemblePredictor(
        rf_predictor=rf_model,
        lstm_predictor=lstm_model
    )

    result = await async_ensemble.predict(market_context, pair="BTC/USD")

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional

from ml.prd_ensemble_predictor import PRDEnsemblePredictor

logger = logging.getLogger(__name__)


class AsyncEnsemblePredictor:
    """
    Async wrapper for PRDEnsemblePredictor.

    Runs CPU-intensive model inference in a thread pool to avoid
    blocking the asyncio event loop.

    Features:
    - Non-blocking async prediction
    - Thread pool for CPU-intensive operations
    - Same API as PRDEnsemblePredictor but with async/await
    - Proper exception handling and logging

    Example:
        ensemble = AsyncEnsemblePredictor()

        # Non-blocking prediction
        result = await ensemble.predict(market_context)

        # Update feedback
        await ensemble.update_feedback(
            rf_correct=True,
            lstm_correct=False
        )
    """

    def __init__(
        self,
        rf_predictor=None,
        lstm_predictor=None,
        rf_weight: float = 0.6,
        lstm_weight: float = 0.4,
        recent_window: int = 100,
        max_workers: int = 2
    ):
        """
        Initialize async ensemble predictor.

        Args:
            rf_predictor: RandomForest/LightGBM predictor
            lstm_predictor: LSTM predictor
            rf_weight: Initial RF weight (default 0.6 per PRD-001)
            lstm_weight: Initial LSTM weight (default 0.4 per PRD-001)
            recent_window: Recent predictions window (default 100)
            max_workers: Thread pool size (default 2)
        """
        # Create underlying sync predictor
        self.predictor = PRDEnsemblePredictor(
            rf_predictor=rf_predictor,
            lstm_predictor=lstm_predictor,
            rf_weight=rf_weight,
            lstm_weight=lstm_weight,
            recent_window=recent_window
        )

        # Thread pool for CPU-intensive operations
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="model_inference"
        )

        logger.info(
            f"AsyncEnsemblePredictor initialized with {max_workers} workers"
        )

    async def predict(
        self,
        ctx: Dict[str, Any],
        pair: str = "BTC/USD"
    ) -> Dict[str, Any]:
        """
        Make async ensemble prediction.

        Runs model inference in thread pool to avoid blocking
        the asyncio event loop.

        Args:
            ctx: Market context dictionary
            pair: Trading pair (for logging)

        Returns:
            Prediction result dict with:
                - probability: Weighted ensemble probability
                - confidence: Model agreement confidence
                - rf_prob: RF model probability
                - lstm_prob: LSTM model probability
                - weights: Current model weights
                - agree: Whether models agree

        Raises:
            Exception: If prediction fails
        """
        try:
            # Run CPU-intensive prediction in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                self.predictor.predict,
                ctx,
                pair
            )

            return result

        except Exception as e:
            logger.error(f"Async prediction failed for {pair}: {e}")
            raise

    async def update_feedback(
        self,
        rf_correct: bool,
        lstm_correct: bool
    ) -> None:
        """
        Async update of model performance tracking.

        Args:
            rf_correct: Whether RF prediction was correct
            lstm_correct: Whether LSTM prediction was correct
        """
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor,
                self.predictor.update_feedback,
                rf_correct,
                lstm_correct
            )

        except Exception as e:
            logger.error(f"Failed to update feedback: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get predictor statistics.

        Returns:
            Dict with current weights, accuracies, and agreement rate
        """
        agreement_rate = 0.0
        if self.predictor.total_predictions > 0:
            agreement_rate = (
                self.predictor.total_agreements /
                self.predictor.total_predictions
            )

        return {
            "rf_weight": self.predictor.rf_weight,
            "lstm_weight": self.predictor.lstm_weight,
            "total_predictions": self.predictor.total_predictions,
            "agreement_rate": agreement_rate,
            "recent_window": self.predictor.recent_window
        }

    async def close(self) -> None:
        """
        Cleanup resources.

        Shuts down thread pool executor gracefully.
        """
        logger.info("Shutting down AsyncEnsemblePredictor")
        self.executor.shutdown(wait=True)


# Convenience function for creating async ensemble
async def create_ensemble(
    rf_predictor=None,
    lstm_predictor=None,
    **kwargs
) -> AsyncEnsemblePredictor:
    """
    Factory function to create async ensemble predictor.

    Args:
        rf_predictor: RandomForest/LightGBM model
        lstm_predictor: LSTM model
        **kwargs: Additional arguments for AsyncEnsemblePredictor

    Returns:
        Initialized AsyncEnsemblePredictor

    Example:
        ensemble = await create_ensemble(
            rf_predictor=rf_model,
            lstm_predictor=lstm_model,
            rf_weight=0.65,
            lstm_weight=0.35
        )
    """
    return AsyncEnsemblePredictor(
        rf_predictor=rf_predictor,
        lstm_predictor=lstm_predictor,
        **kwargs
    )


if __name__ == "__main__":
    import time

    # Demo async prediction
    async def demo():
        print("=" * 70)
        print("AsyncEnsemblePredictor Demo")
        print("=" * 70)

        # Create ensemble (with None predictors for demo)
        ensemble = AsyncEnsemblePredictor(
            rf_predictor=None,  # Would be real model in production
            lstm_predictor=None
        )

        # Sample market context
        ctx = {
            "rsi": 65.5,
            "macd": 0.02,
            "atr": 425.0,
            "volume_ratio": 1.23
        }

        print("\nMaking async prediction...")
        start = time.time()

        result = await ensemble.predict(ctx, pair="BTC/USD")

        elapsed = (time.time() - start) * 1000

        print(f"\nPrediction completed in {elapsed:.2f}ms")
        print(f"Probability: {result['probability']:.3f}")
        print(f"Confidence: {result['confidence']:.2f}")
        print(f"Models agree: {result['agree']}")
        print(f"Weights: RF={result['weights']['rf']:.2f}, "
              f"LSTM={result['weights']['lstm']:.2f}")

        # Get stats
        stats = ensemble.get_stats()
        print(f"\nStats:")
        print(f"  Total predictions: {stats['total_predictions']}")
        print(f"  Agreement rate: {stats['agreement_rate']:.2%}")

        # Cleanup
        await ensemble.close()
        print("\n✅ Demo completed successfully")

    # Run demo
    asyncio.run(demo())
