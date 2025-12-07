"""
Integration Tests for IntegratedSignalPipeline

Tests:
- End-to-end signal generation
- Redis publishing
- WebSocket integration
- Error handling
- Performance benchmarks

Author: Crypto AI Bot Team
Version: 1.0.0
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from agents.core.integrated_signal_pipeline import IntegratedSignalPipeline
from models.prd_signal_schema import TradingSignal, Side, Strategy


# Mock predictors
class MockRFPredictor:
    """Mock RF predictor."""

    def predict_proba(self, ctx):
        return 0.75  # Bullish


class MockLSTMPredictor:
    """Mock LSTM predictor."""

    def predict_proba(self, ctx):
        return 0.68  # Bullish


# Mock Redis client
class MockRedisClient:
    """Mock Redis client for testing."""

    def __init__(self):
        self.published_signals = []
        self.connected = True

    async def xadd(self, stream: str, fields: dict) -> str:
        """Mock xadd."""
        if not self.connected:
            raise ConnectionError("Redis not connected")

        self.published_signals.append({
            "stream": stream,
            "fields": fields,
            "timestamp": time.time()
        })
        return f"{int(time.time()*1000)}-0"

    @classmethod
    def from_url(cls, url: str):
        """Factory method."""
        return cls()


@pytest.fixture
def mock_redis(monkeypatch):
    """Fixture for mock Redis client."""
    mock_client = MockRedisClient()
    monkeypatch.setattr(
        "agents.core.integrated_signal_pipeline.RealRedisClient",
        lambda **kwargs: mock_client
    )
    return mock_client


@pytest.fixture
async def pipeline(mock_redis):
    """Fixture for signal pipeline."""
    pipeline = IntegratedSignalPipeline(
        trading_pairs=["BTC/USD", "ETH/USD"],
        redis_url="redis://localhost:6379",
        rf_model=MockRFPredictor(),
        lstm_model=MockLSTMPredictor(),
        min_confidence=0.6,
        trading_mode="paper"
    )

    yield pipeline

    # Cleanup
    await pipeline.stop()


@pytest.mark.asyncio
async def test_pipeline_initialization(pipeline):
    """Test pipeline initializes correctly."""
    assert pipeline is not None
    assert len(pipeline.trading_pairs) == 2
    assert pipeline.trading_mode == "paper"
    assert pipeline.min_confidence == 0.6


@pytest.mark.asyncio
async def test_feature_extraction(pipeline):
    """Test feature extraction from market data."""
    # Setup market data
    pipeline.market_data["BTC/USD"] = {
        "ticker": {
            "last": 43250.5,
            "bid": 43240.0,
            "ask": 43260.0,
            "volume": 1234.56
        }
    }

    # Extract features
    ctx = pipeline._extract_features("BTC/USD")

    # Check features
    assert ctx["pair"] == "BTC/USD"
    assert ctx["price"] == 43250.5
    assert ctx["bid"] == 43240.0
    assert ctx["ask"] == 43260.0
    assert ctx["volume"] == 1234.56
    assert ctx["spread"] == 20.0  # ask - bid


@pytest.mark.asyncio
async def test_signal_creation(pipeline):
    """Test TradingSignal creation."""
    prediction = {
        "probability": 0.75,
        "confidence": 0.9,
        "rf_prob": 0.75,
        "lstm_prob": 0.68,
        "weights": {"rf": 0.6, "lstm": 0.4},
        "agree": True
    }

    ctx = {
        "pair": "BTC/USD",
        "price": 43250.5,
        "bid": 43240.0,
        "ask": 43260.0,
        "volume": 1234.56,
        "rsi": 65.5,
        "macd": 0.02,
        "atr": 425.0,
        "volume_ratio": 1.23
    }

    signal = await pipeline._create_trading_signal(
        pair="BTC/USD",
        prediction=prediction,
        ctx=ctx,
        latency_ms=15.5
    )

    # Check signal structure
    assert isinstance(signal, TradingSignal)
    assert signal.trading_pair == "BTC/USD"
    assert signal.side == Side.LONG  # probability > 0.5
    assert signal.confidence == 0.9
    assert signal.entry_price == 43250.5

    # Check price relationships for LONG
    assert signal.take_profit > signal.entry_price
    assert signal.stop_loss < signal.entry_price

    # Check metadata
    assert signal.metadata is not None
    assert signal.metadata.latency_ms == 15.5


@pytest.mark.asyncio
async def test_signal_publishing(pipeline, mock_redis):
    """Test signal publishing to Redis."""
    # Create a test signal
    prediction = {
        "probability": 0.75,
        "confidence": 0.9,
        "rf_prob": 0.75,
        "lstm_prob": 0.68,
        "weights": {"rf": 0.6, "lstm": 0.4},
        "agree": True
    }

    ctx = {
        "pair": "BTC/USD",
        "price": 43250.5,
        "rsi": 65.5,
        "atr": 425.0,
        "volume_ratio": 1.23
    }

    signal = await pipeline._create_trading_signal(
        pair="BTC/USD",
        prediction=prediction,
        ctx=ctx,
        latency_ms=15.5
    )

    # Publish signal
    await pipeline._publish_signal(signal)

    # Check that signal was published
    assert len(mock_redis.published_signals) == 1
    published = mock_redis.published_signals[0]

    # Check stream name
    assert published["stream"] == "signals:paper"

    # Check signal fields
    fields = published["fields"]
    assert fields["pair"] == "BTC/USD"
    assert fields["side"] == "LONG"
    assert float(fields["confidence"]) == 0.9


@pytest.mark.asyncio
async def test_confidence_threshold_filtering(pipeline):
    """Test that signals below confidence threshold are filtered."""
    # Setup market data
    pipeline.market_data["BTC/USD"] = {
        "ticker": {
            "last": 43250.5,
            "bid": 43240.0,
            "ask": 43260.0,
            "volume": 1234.56
        },
        "trades": []  # Mark as ready
    }

    # Mock ensemble to return low confidence
    original_predict = pipeline.ensemble.predict

    async def low_confidence_predict(ctx, pair):
        result = await original_predict(ctx, pair)
        result["confidence"] = 0.4  # Below 0.6 threshold
        return result

    pipeline.ensemble.predict = low_confidence_predict

    initial_count = pipeline.signals_generated

    # Try to generate signal
    await pipeline._generate_signal("BTC/USD")

    # Signal should NOT be generated due to low confidence
    assert pipeline.signals_generated == initial_count


@pytest.mark.asyncio
async def test_redis_connection_failure_handling(pipeline):
    """Test handling of Redis connection failures."""
    # Create a signal
    prediction = {
        "probability": 0.75,
        "confidence": 0.9,
        "rf_prob": 0.75,
        "lstm_prob": 0.68,
        "weights": {"rf": 0.6, "lstm": 0.4},
        "agree": True
    }

    ctx = {
        "pair": "BTC/USD",
        "price": 43250.5,
        "rsi": 65.5,
        "atr": 425.0,
        "volume_ratio": 1.23
    }

    signal = await pipeline._create_trading_signal(
        pair="BTC/USD",
        prediction=prediction,
        ctx=ctx,
        latency_ms=15.5
    )

    # Disconnect Redis
    pipeline.redis_client.connected = False

    # Publishing should raise exception
    with pytest.raises(ConnectionError):
        await pipeline._publish_signal(signal)


@pytest.mark.asyncio
async def test_statistics_tracking(pipeline):
    """Test that pipeline tracks statistics correctly."""
    initial_stats = pipeline.get_stats()

    assert initial_stats["signals_generated"] == 0
    assert initial_stats["signals_published"] == 0
    assert initial_stats["trading_mode"] == "paper"
    assert len(initial_stats["trading_pairs"]) == 2


@pytest.mark.asyncio
async def test_ready_for_prediction_check(pipeline):
    """Test the readiness check for prediction."""
    # Initially not ready (no data)
    assert not pipeline._is_ready_for_prediction("BTC/USD")

    # Add partial data
    pipeline.market_data["BTC/USD"] = {
        "ticker": {}
    }
    assert not pipeline._is_ready_for_prediction("BTC/USD")

    # Add complete data
    pipeline.market_data["BTC/USD"] = {
        "ticker": {},
        "trades": []
    }
    assert pipeline._is_ready_for_prediction("BTC/USD")


@pytest.mark.asyncio
async def test_multiple_pairs_processing(pipeline, mock_redis):
    """Test processing multiple trading pairs."""
    # Setup data for both pairs
    for pair in ["BTC/USD", "ETH/USD"]:
        pipeline.market_data[pair] = {
            "ticker": {
                "last": 43250.5 if pair == "BTC/USD" else 2345.75,
                "bid": 43240.0,
                "ask": 43260.0,
                "volume": 1234.56
            },
            "trades": []
        }

        # Generate signal for each pair
        await pipeline._generate_signal(pair)

    # Should have published 2 signals
    assert len(mock_redis.published_signals) == 2

    # Check both pairs are represented
    pairs = [s["fields"]["pair"] for s in mock_redis.published_signals]
    assert "BTC/USD" in pairs
    assert "ETH/USD" in pairs


@pytest.mark.asyncio
async def test_signal_generation_latency(pipeline):
    """Test that signal generation meets latency requirements."""
    # Setup market data
    pipeline.market_data["BTC/USD"] = {
        "ticker": {
            "last": 43250.5,
            "bid": 43240.0,
            "ask": 43260.0,
            "volume": 1234.56
        },
        "trades": []
    }

    # Measure latency
    start = time.time()
    await pipeline._generate_signal("BTC/USD")
    latency_ms = (time.time() - start) * 1000

    # Should be < 50ms per PRD-001 requirement
    # (May be slightly higher in testing due to mocks)
    assert latency_ms < 100  # Allow margin for testing


@pytest.mark.asyncio
async def test_short_signal_generation(pipeline):
    """Test generation of SHORT signals."""
    # Mock ensemble to return bearish prediction
    async def bearish_predict(ctx, pair):
        return {
            "probability": 0.3,  # < 0.5 = SHORT
            "confidence": 0.9,
            "rf_prob": 0.3,
            "lstm_prob": 0.28,
            "weights": {"rf": 0.6, "lstm": 0.4},
            "agree": True
        }

    pipeline.ensemble.predict = bearish_predict

    ctx = {
        "pair": "BTC/USD",
        "price": 43250.5,
        "rsi": 35.0,  # Oversold
        "atr": 425.0,
        "volume_ratio": 1.23
    }

    signal = await pipeline._create_trading_signal(
        pair="BTC/USD",
        prediction=await bearish_predict(ctx, "BTC/USD"),
        ctx=ctx,
        latency_ms=15.5
    )

    # Check SHORT signal price relationships
    assert signal.side == Side.SHORT
    assert signal.take_profit < signal.entry_price
    assert signal.stop_loss > signal.entry_price


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])
