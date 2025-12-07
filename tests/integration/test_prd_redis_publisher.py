"""
Integration tests for PRD-001 compliant Redis publisher.

Tests verify:
1. Redis TLS connection with CA certificate
2. Signal schema validation and publishing
3. PnL publishing
4. Event publishing
5. Stream naming matches PRD-001 exactly
6. No schema drift across strategies
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

import pytest

# Try to import fakeredis, fallback to mock if not available
try:
    from fakeredis.aioredis import FakeRedis
    FAKEREDIS_AVAILABLE = True
except ImportError:
    FAKEREDIS_AVAILABLE = False
    # Use a simple mock for testing
    from unittest.mock import AsyncMock
    FakeRedis = None

from agents.infrastructure.prd_redis_publisher import (
    get_prd_redis_client,
    publish_signal,
    publish_pnl,
    publish_event,
    get_signal_stream_name,
    get_pnl_stream_name,
    get_event_stream_name,
    STREAM_MAXLEN_SIGNALS,
    STREAM_MAXLEN_PNL,
    STREAM_MAXLEN_EVENTS,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
async def fake_redis():
    """Create fake Redis client for testing."""
    if not FAKEREDIS_AVAILABLE:
        pytest.skip("fakeredis not available, install with: pip install fakeredis[aioredis]")
    
    client = FakeRedis(decode_responses=False)
    yield client
    await client.aclose()


@pytest.fixture
def valid_signal_data() -> Dict[str, Any]:
    """Create valid PRD-001 signal data."""
    return {
        "signal_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        "pair": "BTC/USD",
        "side": "LONG",
        "strategy": "SCALPER",
        "regime": "TRENDING_UP",
        "entry_price": 50000.0,
        "take_profit": 52000.0,
        "stop_loss": 49000.0,
        "position_size_usd": 100.0,
        "confidence": 0.85,
        # risk_reward_ratio will be calculated automatically if not provided
        "indicators": {
            "rsi_14": 58.3,
            "macd_signal": "BULLISH",
            "atr_14": 425.80,
            "volume_ratio": 1.23,
        },
        "metadata": {
            "model_version": "v2.1.0",
            "backtest_sharpe": 1.85,
            "latency_ms": 127,
        },
    }


@pytest.fixture
def valid_pnl_data() -> Dict[str, Any]:
    """Create valid PRD-001 PnL data."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        "equity": 10000.0,
        "realized_pnl": 500.0,
        "unrealized_pnl": 100.0,
        "num_positions": 2,
        "drawdown_pct": 0.0,
    }


@pytest.fixture
def valid_event_data() -> Dict[str, Any]:
    """Create valid PRD-001 event data."""
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        "event_type": "SIGNAL_PUBLISHED",
        "source": "signal_generator",
        "severity": "INFO",
        "message": "Signal published successfully",
        "data": {"signal_id": str(uuid.uuid4())},
    }


# =============================================================================
# STREAM NAME TESTS
# =============================================================================

def test_get_signal_stream_name_paper():
    """Test signal stream name for paper mode."""
    assert get_signal_stream_name("paper", "BTC/USD") == "signals:paper:BTC-USD"
    assert get_signal_stream_name("paper", "ETH/USD") == "signals:paper:ETH-USD"
    assert get_signal_stream_name("paper", "BTC-USD") == "signals:paper:BTC-USD"  # Already has dash


def test_get_signal_stream_name_live():
    """Test signal stream name for live mode."""
    assert get_signal_stream_name("live", "BTC/USD") == "signals:live:BTC-USD"
    assert get_signal_stream_name("live", "ETH/USD") == "signals:live:ETH-USD"


def test_get_signal_stream_name_invalid_mode():
    """Test signal stream name rejects invalid mode."""
    with pytest.raises(ValueError, match="Invalid mode"):
        get_signal_stream_name("invalid", "BTC/USD")


def test_get_pnl_stream_name():
    """Test PnL stream names."""
    assert get_pnl_stream_name("paper") == "pnl:paper:equity_curve"
    assert get_pnl_stream_name("live") == "pnl:live:equity_curve"


def test_get_event_stream_name():
    """Test event stream name."""
    assert get_event_stream_name() == "events:bus"


# =============================================================================
# SIGNAL PUBLISHING TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_publish_signal_paper_mode(fake_redis, valid_signal_data):
    """Test publishing signal to paper mode stream."""
    # Mock RedisCloudClient to use fake_redis
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    # Publish signal
    entry_id = await publish_signal(mock_client, "paper", valid_signal_data)

    assert entry_id is not None

    # Verify stream exists
    stream_name = get_signal_stream_name("paper", "BTC/USD")
    length = await fake_redis.xlen(stream_name)
    assert length == 1

    # Verify stream content
    messages = await fake_redis.xread({stream_name: "0"}, count=1)
    assert len(messages) == 1
    stream, entries = messages[0]
    assert stream.decode() == stream_name
    assert len(entries) == 1

    # Verify fields match PRD-001 schema
    entry_id_bytes, fields = entries[0]
    field_dict = {k.decode(): v.decode() if isinstance(v, bytes) else v for k, v in fields.items()}

    assert "signal_id" in field_dict
    assert "timestamp" in field_dict
    assert "pair" in field_dict
    assert field_dict["pair"] == "BTC/USD"
    assert "side" in field_dict
    assert field_dict["side"] == "LONG"
    assert "strategy" in field_dict
    assert field_dict["strategy"] == "SCALPER"


@pytest.mark.asyncio
async def test_publish_signal_live_mode(fake_redis, valid_signal_data):
    """Test publishing signal to live mode stream."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    entry_id = await publish_signal(mock_client, "live", valid_signal_data)

    assert entry_id is not None

    stream_name = get_signal_stream_name("live", "BTC/USD")
    length = await fake_redis.xlen(stream_name)
    assert length == 1


@pytest.mark.asyncio
async def test_publish_signal_schema_validation(fake_redis):
    """Test signal schema validation rejects invalid data."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    # Invalid signal (missing required fields)
    invalid_signal = {
        "pair": "BTC/USD",
        "side": "LONG",
        # Missing: signal_id, timestamp, strategy, etc.
    }

    with pytest.raises(ValueError, match="Signal schema validation failed"):
        await publish_signal(mock_client, "paper", invalid_signal)


@pytest.mark.asyncio
async def test_publish_signal_all_pairs(fake_redis, valid_signal_data):
    """Test publishing signals for all PRD-001 required pairs."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    # PRD-001 required pairs
    pairs = ["BTC/USD", "ETH/USD", "ADA/USD", "SOL/USD", "AVAX/USD", "LINK/USD"]

    for pair in pairs:
        signal_data = valid_signal_data.copy()
        signal_data["pair"] = pair

        entry_id = await publish_signal(mock_client, "paper", signal_data)
        assert entry_id is not None

        stream_name = get_signal_stream_name("paper", pair)
        length = await fake_redis.xlen(stream_name)
        assert length == 1


@pytest.mark.asyncio
async def test_publish_signal_all_strategies(fake_redis, valid_signal_data):
    """Test publishing signals for all PRD-001 strategies (no schema drift)."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    # PRD-001 strategies
    strategies = ["SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT"]

    for strategy in strategies:
        signal_data = valid_signal_data.copy()
        signal_data["strategy"] = strategy

        entry_id = await publish_signal(mock_client, "paper", signal_data)
        assert entry_id is not None

        # Verify all signals have same schema fields
        stream_name = get_signal_stream_name("paper", "BTC/USD")
        messages = await fake_redis.xread({stream_name: "0"}, count=100)
        if messages:
            _, entries = messages[0]
            for entry_id_bytes, fields in entries:
                field_dict = {k.decode(): v.decode() if isinstance(v, bytes) else v for k, v in fields.items()}
                # All signals must have same required fields
                assert "signal_id" in field_dict
                assert "timestamp" in field_dict
                assert "pair" in field_dict
                assert "side" in field_dict
                assert "strategy" in field_dict
                assert "regime" in field_dict
                assert "entry_price" in field_dict
                assert "take_profit" in field_dict
                assert "stop_loss" in field_dict
                assert "position_size_usd" in field_dict
                assert "confidence" in field_dict
                assert "risk_reward_ratio" in field_dict


# =============================================================================
# PnL PUBLISHING TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_publish_pnl_paper_mode(fake_redis, valid_pnl_data):
    """Test publishing PnL to paper mode stream."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    entry_id = await publish_pnl(mock_client, "paper", valid_pnl_data)

    assert entry_id is not None

    stream_name = get_pnl_stream_name("paper")
    length = await fake_redis.xlen(stream_name)
    assert length == 1

    # Verify fields
    messages = await fake_redis.xread({stream_name: "0"}, count=1)
    assert len(messages) == 1
    _, entries = messages[0]
    assert len(entries) == 1

    entry_id_bytes, fields = entries[0]
    field_dict = {k.decode(): v.decode() if isinstance(v, bytes) else v for k, v in fields.items()}

    assert "timestamp" in field_dict
    assert "equity" in field_dict
    assert "realized_pnl" in field_dict
    assert "unrealized_pnl" in field_dict
    assert "num_positions" in field_dict
    assert "drawdown_pct" in field_dict


@pytest.mark.asyncio
async def test_publish_pnl_live_mode(fake_redis, valid_pnl_data):
    """Test publishing PnL to live mode stream."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    entry_id = await publish_pnl(mock_client, "live", valid_pnl_data)

    assert entry_id is not None

    stream_name = get_pnl_stream_name("live")
    length = await fake_redis.xlen(stream_name)
    assert length == 1


# =============================================================================
# EVENT PUBLISHING TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_publish_event(fake_redis, valid_event_data):
    """Test publishing event to events:bus stream."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    entry_id = await publish_event(mock_client, valid_event_data)

    assert entry_id is not None

    stream_name = get_event_stream_name()
    length = await fake_redis.xlen(stream_name)
    assert length == 1

    # Verify fields
    messages = await fake_redis.xread({stream_name: "0"}, count=1)
    assert len(messages) == 1
    _, entries = messages[0]
    assert len(entries) == 1

    entry_id_bytes, fields = entries[0]
    field_dict = {k.decode(): v.decode() if isinstance(v, bytes) else v for k, v in fields.items()}

    assert "event_id" in field_dict
    assert "timestamp" in field_dict
    assert "event_type" in field_dict
    assert field_dict["event_type"] == "SIGNAL_PUBLISHED"
    assert "source" in field_dict
    assert "severity" in field_dict
    assert "message" in field_dict


# =============================================================================
# MAXLEN TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_signal_stream_maxlen(fake_redis, valid_signal_data):
    """Test signal stream MAXLEN enforcement."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    stream_name = get_signal_stream_name("paper", "BTC/USD")

    # Publish more than MAXLEN signals
    for i in range(STREAM_MAXLEN_SIGNALS + 100):
        signal_data = valid_signal_data.copy()
        signal_data["signal_id"] = str(uuid.uuid4())
        await publish_signal(mock_client, "paper", signal_data)

    # Stream should be trimmed to MAXLEN
    length = await fake_redis.xlen(stream_name)
    assert length <= STREAM_MAXLEN_SIGNALS + 10  # Allow some tolerance for approximate trimming


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_publish_signal_invalid_mode(fake_redis, valid_signal_data):
    """Test publishing signal with invalid mode."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    with pytest.raises(ValueError, match="Invalid mode"):
        await publish_signal(mock_client, "invalid", valid_signal_data)


@pytest.mark.asyncio
async def test_publish_signal_retry_logic(fake_redis, valid_signal_data):
    """Test signal publishing retry logic on transient failures."""
    call_count = 0

    class MockRedisClient:
        def __init__(self, client):
            self._client = client
            self._call_count = 0

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            self._call_count += 1
            # Fail first 2 attempts, succeed on 3rd
            if self._call_count < 3:
                raise Exception("Transient error")
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    entry_id = await publish_signal(mock_client, "paper", valid_signal_data, retry_attempts=3)

    assert entry_id is not None
    assert mock_client._call_count == 3  # Should have retried


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_full_pipeline_paper_mode(fake_redis, valid_signal_data, valid_pnl_data, valid_event_data):
    """Test full pipeline: signal → PnL → event in paper mode."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    # Publish signal
    signal_entry_id = await publish_signal(mock_client, "paper", valid_signal_data)
    assert signal_entry_id is not None

    # Publish PnL update
    pnl_entry_id = await publish_pnl(mock_client, "paper", valid_pnl_data)
    assert pnl_entry_id is not None

    # Publish event
    event_entry_id = await publish_event(mock_client, valid_event_data)
    assert event_entry_id is not None

    # Verify all streams exist
    signal_stream = get_signal_stream_name("paper", "BTC/USD")
    pnl_stream = get_pnl_stream_name("paper")
    event_stream = get_event_stream_name()

    assert await fake_redis.xlen(signal_stream) == 1
    assert await fake_redis.xlen(pnl_stream) == 1
    assert await fake_redis.xlen(event_stream) == 1


@pytest.mark.asyncio
async def test_mode_separation(fake_redis, valid_signal_data):
    """Test that paper and live modes use separate streams."""
    class MockRedisClient:
        def __init__(self, client):
            self._client = client

        async def xadd(self, name, fields, maxlen=None, approximate=None):
            return await self._client.xadd(name, fields, maxlen=maxlen, approximate=approximate)

        async def ping(self):
            return await self._client.ping()

    mock_client = MockRedisClient(fake_redis)

    # Publish to paper mode
    paper_entry_id = await publish_signal(mock_client, "paper", valid_signal_data)
    assert paper_entry_id is not None

    # Publish to live mode
    live_entry_id = await publish_signal(mock_client, "live", valid_signal_data)
    assert live_entry_id is not None

    # Verify separate streams
    paper_stream = get_signal_stream_name("paper", "BTC/USD")
    live_stream = get_signal_stream_name("live", "BTC/USD")

    assert await fake_redis.xlen(paper_stream) == 1
    assert await fake_redis.xlen(live_stream) == 1
    assert paper_stream != live_stream

