"""
Unit Tests for AsyncEnsemblePredictor

Tests:
- Async prediction execution
- Thread pool isolation
- Exception handling
- Statistics tracking
- Resource cleanup

Author: Crypto AI Bot Team
Version: 1.0.0
"""

import pytest
import asyncio
import time
from ml.async_ensemble import AsyncEnsemblePredictor, create_ensemble


# Mock predictor for testing
class MockPredictor:
    """Mock model predictor that returns fixed probabilities."""

    def __init__(self, probability: float = 0.7):
        self.probability = probability
        self.call_count = 0

    def predict_proba(self, ctx):
        """Simulate prediction."""
        self.call_count += 1
        time.sleep(0.01)  # Simulate CPU work
        return self.probability


@pytest.fixture
def mock_rf_predictor():
    """Fixture for RF predictor."""
    return MockPredictor(probability=0.75)


@pytest.fixture
def mock_lstm_predictor():
    """Fixture for LSTM predictor."""
    return MockPredictor(probability=0.68)


@pytest.fixture
async def ensemble(mock_rf_predictor, mock_lstm_predictor):
    """Fixture for async ensemble predictor."""
    ensemble = AsyncEnsemblePredictor(
        rf_predictor=mock_rf_predictor,
        lstm_predictor=mock_lstm_predictor,
        rf_weight=0.6,
        lstm_weight=0.4
    )
    yield ensemble
    await ensemble.close()


@pytest.mark.asyncio
async def test_async_prediction_executes(ensemble, mock_rf_predictor, mock_lstm_predictor):
    """Test that async prediction executes successfully."""
    ctx = {
        "rsi": 65.5,
        "macd": 0.02,
        "atr": 425.0,
        "volume_ratio": 1.23
    }

    result = await ensemble.predict(ctx, pair="BTC/USD")

    # Check result structure
    assert "probability" in result
    assert "confidence" in result
    assert "rf_prob" in result
    assert "lstm_prob" in result
    assert "weights" in result
    assert "agree" in result

    # Check values
    assert 0.0 <= result["probability"] <= 1.0
    assert 0.0 <= result["confidence"] <= 1.0

    # Check predictors were called
    assert mock_rf_predictor.call_count == 1
    assert mock_lstm_predictor.call_count == 1


@pytest.mark.asyncio
async def test_weighted_ensemble_calculation(ensemble):
    """Test that ensemble correctly weights predictions."""
    ctx = {"rsi": 50.0}

    result = await ensemble.predict(ctx, pair="BTC/USD")

    # Expected: 0.6 * 0.75 + 0.4 * 0.68 = 0.722
    expected_prob = 0.6 * 0.75 + 0.4 * 0.68
    assert abs(result["probability"] - expected_prob) < 0.01


@pytest.mark.asyncio
async def test_model_agreement_confidence(mock_rf_predictor, mock_lstm_predictor):
    """Test confidence calculation based on model agreement."""
    # Case 1: Models agree (both ~0.7)
    rf_pred = MockPredictor(0.70)
    lstm_pred = MockPredictor(0.72)
    ensemble = AsyncEnsemblePredictor(
        rf_predictor=rf_pred,
        lstm_predictor=lstm_pred
    )

    result = await ensemble.predict({"rsi": 50.0})

    # Should have high confidence (0.9) when models agree
    assert result["confidence"] == 0.9
    assert result["agree"] is True

    await ensemble.close()

    # Case 2: Models disagree (0.3 vs 0.8)
    rf_pred = MockPredictor(0.3)
    lstm_pred = MockPredictor(0.8)
    ensemble = AsyncEnsemblePredictor(
        rf_predictor=rf_pred,
        lstm_predictor=lstm_pred
    )

    result = await ensemble.predict({"rsi": 50.0})

    # Should have low confidence (0.5) when models disagree
    assert result["confidence"] == 0.5
    assert result["agree"] is False

    await ensemble.close()


@pytest.mark.asyncio
async def test_concurrent_predictions(ensemble):
    """Test that ensemble handles concurrent predictions correctly."""
    ctx = {"rsi": 50.0}

    # Run 10 predictions concurrently
    tasks = [
        ensemble.predict(ctx, pair=f"PAIR{i}")
        for i in range(10)
    ]

    results = await asyncio.gather(*tasks)

    # All predictions should complete
    assert len(results) == 10

    # All should have valid structure
    for result in results:
        assert "probability" in result
        assert "confidence" in result


@pytest.mark.asyncio
async def test_exception_handling():
    """Test that exceptions are properly handled."""
    # Predictor that raises exception
    class BrokenPredictor:
        def predict_proba(self, ctx):
            raise ValueError("Prediction failed")

    ensemble = AsyncEnsemblePredictor(
        rf_predictor=BrokenPredictor(),
        lstm_predictor=BrokenPredictor()
    )

    ctx = {"rsi": 50.0}

    # Should raise exception
    with pytest.raises(Exception):
        await ensemble.predict(ctx)

    await ensemble.close()


@pytest.mark.asyncio
async def test_feedback_update(ensemble):
    """Test feedback update mechanism."""
    # Update feedback
    await ensemble.update_feedback(
        rf_correct=True,
        lstm_correct=False
    )

    # Should complete without error
    # (actual weight adjustment tested in sync predictor tests)


@pytest.mark.asyncio
async def test_get_stats(ensemble):
    """Test statistics retrieval."""
    # Make some predictions
    ctx = {"rsi": 50.0}
    await ensemble.predict(ctx)
    await ensemble.predict(ctx)

    stats = ensemble.get_stats()

    # Check stats structure
    assert "rf_weight" in stats
    assert "lstm_weight" in stats
    assert "total_predictions" in stats
    assert "agreement_rate" in stats

    # Check values
    assert stats["total_predictions"] == 2
    assert 0.0 <= stats["agreement_rate"] <= 1.0


@pytest.mark.asyncio
async def test_resource_cleanup(mock_rf_predictor, mock_lstm_predictor):
    """Test that resources are properly cleaned up."""
    ensemble = AsyncEnsemblePredictor(
        rf_predictor=mock_rf_predictor,
        lstm_predictor=mock_lstm_predictor
    )

    # Make a prediction
    ctx = {"rsi": 50.0}
    await ensemble.predict(ctx)

    # Close should complete without hanging
    await asyncio.wait_for(ensemble.close(), timeout=5.0)


@pytest.mark.asyncio
async def test_create_ensemble_factory():
    """Test factory function for creating ensemble."""
    rf_pred = MockPredictor(0.75)
    lstm_pred = MockPredictor(0.68)

    ensemble = await create_ensemble(
        rf_predictor=rf_pred,
        lstm_predictor=lstm_pred,
        rf_weight=0.65,
        lstm_weight=0.35
    )

    # Should create valid ensemble
    assert ensemble is not None

    # Verify weights
    stats = ensemble.get_stats()
    assert abs(stats["rf_weight"] - 0.65) < 0.01
    assert abs(stats["lstm_weight"] - 0.35) < 0.01

    await ensemble.close()


@pytest.mark.asyncio
async def test_latency_is_reasonable(ensemble):
    """Test that async prediction doesn't block event loop."""
    ctx = {"rsi": 50.0}

    start = time.time()

    # Run prediction
    result = await ensemble.predict(ctx)

    elapsed = time.time() - start

    # Should complete in reasonable time (<1s for mock predictors)
    assert elapsed < 1.0

    # Result should be valid
    assert result is not None


@pytest.mark.asyncio
async def test_none_predictors_handle_gracefully():
    """Test that ensemble works with None predictors (returns neutral 0.5)."""
    ensemble = AsyncEnsemblePredictor(
        rf_predictor=None,
        lstm_predictor=None
    )

    ctx = {"rsi": 50.0}
    result = await ensemble.predict(ctx)

    # Should return neutral probability
    assert result["probability"] == 0.5
    assert result["rf_prob"] == 0.5
    assert result["lstm_prob"] == 0.5

    await ensemble.close()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])
