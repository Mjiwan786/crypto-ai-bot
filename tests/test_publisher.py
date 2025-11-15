"""
Comprehensive tests for io/publisher.py

Tests cover:
- Signal publishing to Redis streams
- Idempotent ID generation and deduplication
- Retry logic with exponential backoff
- Stream reading and verification
- Metrics tracking
- Context manager usage
- Error handling

Uses fakeredis for hermetic testing (no external Redis required).
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import fakeredis
import redis

from models.signal_dto import SignalDTO, create_signal_dto, generate_signal_id
from streams.publisher import (
    PublisherConfig,
    SignalPublisher,
    create_publisher,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def fake_redis_server():
    """Create fake Redis server for testing"""
    return fakeredis.FakeServer()


@pytest.fixture
def fake_redis_client(fake_redis_server):
    """Create fake Redis client"""
    return fakeredis.FakeStrictRedis(server=fake_redis_server, decode_responses=True)


@pytest.fixture
def publisher_config():
    """Default publisher configuration"""
    return PublisherConfig(
        redis_url="redis://localhost:6379",
        max_retries=3,
        base_delay_ms=100,
        max_delay_ms=5000,
    )


@pytest.fixture
def publisher(publisher_config, fake_redis_client):
    """Publisher instance with fake Redis"""
    pub = SignalPublisher(config=publisher_config)
    pub._client = fake_redis_client  # Inject fake client
    return pub


@pytest.fixture
def sample_signal():
    """Sample signal for testing"""
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return create_signal_dto(
        ts_ms=ts_ms,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="momentum_v1",
        confidence=0.75,
        mode="paper",
    )


# =============================================================================
# SIGNAL DTO TESTS
# =============================================================================


def test_signal_dto_creation():
    """Test SignalDTO creation with validation"""
    signal = create_signal_dto(
        ts_ms=1730000000000,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="paper",
    )

    assert signal.pair == "BTC-USD"
    assert signal.side == "long"
    assert signal.entry == 50000.0
    assert signal.mode == "paper"


def test_signal_id_generation():
    """Test idempotent signal ID generation"""
    ts = 1730000000000
    pair = "BTC-USD"
    strategy = "test"

    id1 = generate_signal_id(ts, pair, strategy)
    id2 = generate_signal_id(ts, pair, strategy)

    assert id1 == id2  # Deterministic
    assert len(id1) == 32  # 32-char hex


def test_signal_id_uniqueness():
    """Test signal IDs are unique for different inputs"""
    ts = 1730000000000

    id_btc = generate_signal_id(ts, "BTC-USD", "test")
    id_eth = generate_signal_id(ts, "ETH-USD", "test")
    id_diff_ts = generate_signal_id(ts + 1, "BTC-USD", "test")
    id_diff_strategy = generate_signal_id(ts, "BTC-USD", "other")

    assert id_btc != id_eth
    assert id_btc != id_diff_ts
    assert id_btc != id_diff_strategy


def test_signal_json_serialization():
    """Test JSON serialization is deterministic"""
    signal = create_signal_dto(
        ts_ms=1730000000000,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="paper",
    )

    json1 = signal.to_json()
    json2 = signal.to_json()

    assert json1 == json2  # Deterministic
    assert "BTC-USD" in json1


def test_signal_json_round_trip():
    """Test JSON serialization and deserialization"""
    signal = create_signal_dto(
        ts_ms=1730000000000,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="paper",
    )

    json_str = signal.to_json()
    signal_restored = SignalDTO.from_json(json_str)

    assert signal_restored.id == signal.id
    assert signal_restored.pair == signal.pair
    assert signal_restored.entry == signal.entry


def test_signal_validation_invalid_side():
    """Test validation rejects invalid side"""
    with pytest.raises(Exception):  # Pydantic ValidationError
        SignalDTO(
            id="test",
            ts=1730000000000,
            pair="BTC-USD",
            side="invalid",  # Invalid
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test",
            confidence=0.75,
            mode="paper",
        )


def test_signal_validation_invalid_confidence():
    """Test validation rejects invalid confidence"""
    with pytest.raises(Exception):
        create_signal_dto(
            ts_ms=1730000000000,
            pair="BTC-USD",
            side="long",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test",
            confidence=1.5,  # > 1.0
            mode="paper",
        )


# =============================================================================
# PUBLISHER CONFIG TESTS
# =============================================================================


def test_publisher_config_creation():
    """Test publisher config creation"""
    config = PublisherConfig(
        redis_url="redis://localhost:6379",
        max_retries=5,
        base_delay_ms=200,
    )

    assert config.redis_url == "redis://localhost:6379"
    assert config.max_retries == 5
    assert config.base_delay_ms == 200


# =============================================================================
# PUBLISHER TESTS
# =============================================================================


def test_publisher_publish_basic(publisher, sample_signal):
    """Test basic signal publishing"""
    entry_id = publisher.publish(sample_signal)

    assert entry_id is not None
    assert isinstance(entry_id, str)


def test_publisher_publish_creates_stream(publisher, sample_signal):
    """Test publish creates stream with correct key"""
    publisher.publish(sample_signal)

    # Check stream exists
    stream_key = f"signals:{sample_signal.mode}"
    stream_len = publisher._client.xlen(stream_key)

    assert stream_len == 1


def test_publisher_publish_paper_mode(publisher):
    """Test publishing to paper mode stream"""
    signal = create_signal_dto(
        ts_ms=1730000000000,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="paper",
    )

    publisher.publish(signal)

    # Verify in paper stream
    paper_len = publisher._client.xlen("signals:paper")
    live_len = publisher._client.xlen("signals:live")

    assert paper_len == 1
    assert live_len == 0


def test_publisher_publish_live_mode(publisher):
    """Test publishing to live mode stream"""
    signal = create_signal_dto(
        ts_ms=1730000000000,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="live",
    )

    publisher.publish(signal)

    # Verify in live stream
    paper_len = publisher._client.xlen("signals:paper")
    live_len = publisher._client.xlen("signals:live")

    assert paper_len == 0
    assert live_len == 1


def test_publisher_read_stream(publisher, sample_signal):
    """Test reading signals from stream"""
    publisher.publish(sample_signal)

    signals = publisher.read_stream("paper", count=10)

    assert len(signals) == 1
    assert signals[0]["pair"] == "BTC-USD"
    assert signals[0]["side"] == "long"


def test_publisher_read_stream_multiple(publisher):
    """Test reading multiple signals"""
    # Publish 3 signals
    for i in range(3):
        signal = create_signal_dto(
            ts_ms=1730000000000 + i,
            pair=f"SYM{i}-USD",
            side="long",
            entry=1000.0 + i,
            sl=990.0,
            tp=1020.0,
            strategy="test",
            confidence=0.75,
            mode="paper",
        )
        publisher.publish(signal)

    signals = publisher.read_stream("paper", count=10)

    assert len(signals) == 3


def test_publisher_get_stream_length(publisher, sample_signal):
    """Test getting stream length"""
    publisher.publish(sample_signal)

    length = publisher.get_stream_length("paper")

    assert length == 1


def test_publisher_idempotency(publisher):
    """Test idempotent signal publishing"""
    # Create two signals with same timestamp/pair/strategy
    ts = 1730000000000
    signal1 = create_signal_dto(
        ts_ms=ts,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="paper",
    )

    signal2 = create_signal_dto(
        ts_ms=ts,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="paper",
    )

    # Both should have same ID
    assert signal1.id == signal2.id

    # Publishing both adds both entries (Redis doesn't dedupe by default)
    # But downstream consumers can dedupe by signal.id
    publisher.publish(signal1)
    publisher.publish(signal2)

    signals = publisher.read_stream("paper", count=10)
    assert len(signals) == 2  # Both published
    assert signals[0]["id"] == signals[1]["id"]  # Same ID (idempotent)


def test_publisher_metrics(publisher, sample_signal):
    """Test metrics tracking"""
    publisher.publish(sample_signal)

    metrics = publisher.get_metrics()

    assert metrics["total_published"] == 1
    assert metrics["mode_paper"] == 1
    assert metrics["mode_live"] == 0


def test_publisher_metrics_multiple_modes(publisher):
    """Test metrics track both modes"""
    # Publish paper signal
    paper_signal = create_signal_dto(
        ts_ms=1730000000000,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="paper",
    )
    publisher.publish(paper_signal)

    # Publish live signal
    live_signal = create_signal_dto(
        ts_ms=1730000000001,
        pair="ETH-USD",
        side="short",
        entry=3000.0,
        sl=3100.0,
        tp=2900.0,
        strategy="test",
        confidence=0.80,
        mode="live",
    )
    publisher.publish(live_signal)

    metrics = publisher.get_metrics()

    assert metrics["total_published"] == 2
    assert metrics["mode_paper"] == 1
    assert metrics["mode_live"] == 1


def test_publisher_reset_metrics(publisher, sample_signal):
    """Test metrics reset"""
    publisher.publish(sample_signal)

    metrics_before = publisher.get_metrics()
    assert metrics_before["total_published"] == 1

    publisher.reset_metrics()

    metrics_after = publisher.get_metrics()
    assert metrics_after["total_published"] == 0


def test_publisher_not_connected():
    """Test error when not connected"""
    config = PublisherConfig(redis_url="redis://localhost:6379")
    publisher = SignalPublisher(config=config)

    signal = create_signal_dto(
        ts_ms=1730000000000,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="paper",
    )

    with pytest.raises(ConnectionError, match="Not connected to Redis"):
        publisher.publish(signal)


def test_publisher_backoff_calculation(publisher):
    """Test exponential backoff calculation"""
    # Attempt 0: 100ms
    delay0 = publisher._calculate_backoff(0)
    assert 75 <= delay0 <= 125  # 100 ± 25% jitter

    # Attempt 1: 200ms
    delay1 = publisher._calculate_backoff(1)
    assert 150 <= delay1 <= 250  # 200 ± 25% jitter

    # Attempt 2: 400ms
    delay2 = publisher._calculate_backoff(2)
    assert 300 <= delay2 <= 500  # 400 ± 25% jitter


def test_publisher_backoff_max_cap(publisher):
    """Test backoff is capped at max delay"""
    # Very high attempt should cap at max_delay_ms (5000)
    delay = publisher._calculate_backoff(100)
    assert delay <= 5000 * 1.25  # Max + jitter


def test_publisher_retry_on_failure(publisher_config):
    """Test retry logic on failure"""
    publisher = SignalPublisher(config=publisher_config)

    # Create mock client that fails twice then succeeds
    mock_client = Mock()
    mock_client.xadd.side_effect = [
        redis.RedisError("Connection lost"),
        redis.RedisError("Still down"),
        "1730000000000-0",  # Success on 3rd try
    ]
    publisher._client = mock_client

    signal = create_signal_dto(
        ts_ms=1730000000000,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="paper",
    )

    # Should succeed after retries
    entry_id = publisher.publish(signal)

    assert entry_id == "1730000000000-0"
    assert mock_client.xadd.call_count == 3


def test_publisher_retry_exhausted(publisher_config):
    """Test failure after all retries exhausted"""
    publisher = SignalPublisher(config=publisher_config)

    # Create mock client that always fails
    mock_client = Mock()
    mock_client.xadd.side_effect = redis.RedisError("Always fails")
    publisher._client = mock_client

    signal = create_signal_dto(
        ts_ms=1730000000000,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.75,
        mode="paper",
    )

    # Should raise after max retries
    with pytest.raises(redis.RedisError):
        publisher.publish(signal)

    # Should have tried 4 times (1 + 3 retries)
    assert mock_client.xadd.call_count == 4


def test_publisher_context_manager(fake_redis_client):
    """Test context manager usage"""
    config = PublisherConfig(redis_url="redis://localhost:6379")

    # Mock connect/disconnect
    with patch.object(SignalPublisher, "connect") as mock_connect:
        with patch.object(SignalPublisher, "disconnect") as mock_disconnect:
            with SignalPublisher(config=config) as publisher:
                # Inject fake client
                publisher._client = fake_redis_client

                signal = create_signal_dto(
                    ts_ms=1730000000000,
                    pair="BTC-USD",
                    side="long",
                    entry=50000.0,
                    sl=49000.0,
                    tp=52000.0,
                    strategy="test",
                    confidence=0.75,
                    mode="paper",
                )
                publisher.publish(signal)

            mock_connect.assert_called_once()
            mock_disconnect.assert_called_once()


def test_create_publisher_convenience():
    """Test convenience function"""
    publisher = create_publisher(
        redis_url="redis://localhost:6379",
        max_retries=5,
    )

    assert isinstance(publisher, SignalPublisher)
    assert publisher.config.redis_url == "redis://localhost:6379"
    assert publisher.config.max_retries == 5


# =============================================================================
# INTEGRATION TEST
# =============================================================================


def test_full_publish_read_workflow(publisher):
    """Test complete publish and read workflow"""
    # Create and publish signal
    signal = create_signal_dto(
        ts_ms=1730000000000,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="momentum_v1",
        confidence=0.75,
        mode="paper",
    )

    entry_id = publisher.publish(signal)

    # Read back
    signals = publisher.read_stream("paper", count=1)

    assert len(signals) == 1
    read_signal = signals[0]

    # Verify all fields
    assert read_signal["id"] == signal.id
    assert int(read_signal["ts"]) == signal.ts
    assert read_signal["pair"] == signal.pair
    assert read_signal["side"] == signal.side
    assert float(read_signal["entry"]) == signal.entry
    assert float(read_signal["sl"]) == signal.sl
    assert float(read_signal["tp"]) == signal.tp
    assert read_signal["strategy"] == signal.strategy
    assert float(read_signal["confidence"]) == signal.confidence
    assert read_signal["mode"] == signal.mode


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
