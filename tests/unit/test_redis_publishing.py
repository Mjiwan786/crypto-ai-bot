"""
Tests for Redis Signal Publishing (PRD-001 Section 2.3)

Tests cover:
- UUID v4 message ID generation for idempotency
- Pydantic validation before publish
- JSON serialization with UTF-8 encoding
- Atomic XADD with all signal fields
- Duplicate ID rejection handling
- Retry logic with exponential backoff (100ms, 200ms, 400ms)
- Error logging at ERROR level with signal_id
- Prometheus counters: redis_publish_errors_total, signal_schema_errors_total, signal_duplicates_rejected_total
- 5s publish timeout
- Failed publish queue (max 1000)
"""

import pytest
import asyncio
import time
import json
import uuid
import logging
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pydantic import ValidationError

from utils.kraken_ws import (
    RedisConnectionManager,
    KrakenWSConfig,
    REDIS_PUBLISH_ERRORS_TOTAL,
    SIGNAL_SCHEMA_ERRORS_TOTAL,
    SIGNAL_DUPLICATES_REJECTED_TOTAL,
    PROMETHEUS_AVAILABLE,
    PRD_SCHEMA_AVAILABLE
)
from redis import exceptions as redis_exceptions


@pytest.fixture
def config():
    """Create test configuration"""
    return KrakenWSConfig(
        redis_url="rediss://test:password@redis.example.com:6380",
        trading_mode="paper"
    )


@pytest.fixture
def redis_manager(config):
    """Create test Redis manager"""
    return RedisConnectionManager(config)


@pytest.fixture
def mock_redis():
    """Create mock Redis connection"""
    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock()
    return redis_mock


@pytest.fixture
def valid_signal_data():
    """Create valid signal data for testing"""
    return {
        "timestamp": time.time(),
        "signal_type": "entry",
        "trading_pair": "BTC/USD",
        "size": 0.01,
        "stop_loss": 45000.0,
        "take_profit": 55000.0,
        "confidence_score": 0.85,
        "agent_id": "test_agent"
    }


class TestUUIDGeneration:
    """Test UUID v4 generation for idempotency (PRD-001 Section 2.3 Item 1)"""

    @pytest.mark.asyncio
    async def test_signal_id_is_uuid_v4(self, redis_manager, mock_redis, valid_signal_data):
        """Test that signal_id is generated as UUID v4"""
        redis_manager.redis_client = mock_redis

        await redis_manager.publish_signal(valid_signal_data)

        # Extract signal_id from the xadd call
        call_args = mock_redis.xadd.call_args
        signal_id = call_args[1]['id']

        # Verify it's a valid UUID v4
        try:
            parsed_uuid = uuid.UUID(signal_id, version=4)
            assert str(parsed_uuid) == signal_id
            assert parsed_uuid.version == 4
        except ValueError:
            pytest.fail(f"signal_id {signal_id} is not a valid UUID v4")

    @pytest.mark.asyncio
    async def test_signal_id_included_in_data(self, redis_manager, mock_redis, valid_signal_data):
        """Test that signal_id is included in signal data"""
        redis_manager.redis_client = mock_redis

        await redis_manager.publish_signal(valid_signal_data)

        # Extract data from xadd call
        call_args = mock_redis.xadd.call_args
        data_json = call_args[0][1]['data']
        data = json.loads(data_json)

        assert 'signal_id' in data
        # Verify it's a valid UUID
        uuid.UUID(data['signal_id'])


class TestPydanticValidation:
    """Test Pydantic validation before publish (PRD-001 Section 2.3 Item 2)"""

    @pytest.mark.skipif(not PRD_SCHEMA_AVAILABLE, reason="PRD schema not available")
    @pytest.mark.asyncio
    async def test_valid_signal_passes_validation(self, redis_manager, mock_redis, valid_signal_data):
        """Test that valid signals pass Pydantic validation"""
        redis_manager.redis_client = mock_redis

        result = await redis_manager.publish_signal(valid_signal_data)

        assert result is True
        mock_redis.xadd.assert_called_once()

    @pytest.mark.skipif(not PRD_SCHEMA_AVAILABLE, reason="PRD schema not available")
    @pytest.mark.asyncio
    async def test_invalid_signal_fails_validation(self, redis_manager, mock_redis):
        """Test that invalid signals fail Pydantic validation"""
        redis_manager.redis_client = mock_redis

        # Missing required field
        invalid_signal = {
            "timestamp": time.time(),
            "signal_type": "entry",
            # Missing trading_pair
            "size": 0.01,
            "confidence_score": 0.85,
            "agent_id": "test_agent"
        }

        result = await redis_manager.publish_signal(invalid_signal)

        assert result is False
        mock_redis.xadd.assert_not_called()

    @pytest.mark.skipif(not PRD_SCHEMA_AVAILABLE or not PROMETHEUS_AVAILABLE,
                        reason="PRD schema or Prometheus not available")
    @pytest.mark.asyncio
    async def test_validation_error_emits_metric(self, redis_manager, mock_redis):
        """Test that validation errors emit Prometheus counter"""
        redis_manager.redis_client = mock_redis

        # Get initial count
        initial_count = SIGNAL_SCHEMA_ERRORS_TOTAL.labels(reason='missing')._value.get()

        # Invalid signal
        invalid_signal = {
            "timestamp": time.time(),
            "signal_type": "entry"
            # Missing required fields
        }

        await redis_manager.publish_signal(invalid_signal)

        # Counter should increment
        final_count = SIGNAL_SCHEMA_ERRORS_TOTAL.labels(reason='missing')._value.get()
        assert final_count > initial_count


class TestJSONSerialization:
    """Test JSON serialization with UTF-8 (PRD-001 Section 2.3 Item 3)"""

    @pytest.mark.asyncio
    async def test_signal_serialized_to_json(self, redis_manager, mock_redis, valid_signal_data):
        """Test that signal is serialized to JSON"""
        redis_manager.redis_client = mock_redis

        await redis_manager.publish_signal(valid_signal_data)

        # Extract serialized data
        call_args = mock_redis.xadd.call_args
        data_json = call_args[0][1]['data']

        # Verify it's valid JSON
        parsed_data = json.loads(data_json)
        assert isinstance(parsed_data, dict)

    @pytest.mark.asyncio
    async def test_serialization_uses_utf8(self, redis_manager, mock_redis, valid_signal_data):
        """Test that serialization uses UTF-8 encoding"""
        redis_manager.redis_client = mock_redis

        # Add unicode characters to test UTF-8
        valid_signal_data['agent_id'] = "test_agent_™"

        await redis_manager.publish_signal(valid_signal_data)

        call_args = mock_redis.xadd.call_args
        data_json = call_args[0][1]['data']

        # Should be valid UTF-8
        assert isinstance(data_json, str)
        parsed_data = json.loads(data_json)
        assert parsed_data['agent_id'] == "test_agent_™"


class TestAtomicPublish:
    """Test atomic XADD with all fields (PRD-001 Section 2.3 Item 4)"""

    @pytest.mark.asyncio
    async def test_xadd_called_with_correct_stream(self, redis_manager, mock_redis, valid_signal_data):
        """Test that XADD is called with correct stream name"""
        redis_manager.redis_client = mock_redis

        await redis_manager.publish_signal(valid_signal_data)

        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "signals:paper"  # trading_mode=paper

    @pytest.mark.asyncio
    async def test_xadd_called_with_maxlen(self, redis_manager, mock_redis, valid_signal_data):
        """Test that XADD includes MAXLEN for stream trimming"""
        redis_manager.redis_client = mock_redis

        await redis_manager.publish_signal(valid_signal_data)

        call_args = mock_redis.xadd.call_args
        assert call_args[1]['maxlen'] == 10000
        assert call_args[1]['approximate'] is True

    @pytest.mark.asyncio
    async def test_xadd_uses_signal_id_as_message_id(self, redis_manager, mock_redis, valid_signal_data):
        """Test that signal_id is used as Redis message ID"""
        redis_manager.redis_client = mock_redis

        await redis_manager.publish_signal(valid_signal_data)

        call_args = mock_redis.xadd.call_args
        message_id = call_args[1]['id']

        # Should be a UUID
        uuid.UUID(message_id)


class TestDuplicateRejection:
    """Test duplicate ID rejection handling (PRD-001 Section 2.3 Item 5)"""

    @pytest.mark.asyncio
    async def test_duplicate_id_logged_at_debug(self, redis_manager, mock_redis, valid_signal_data, caplog):
        """Test that duplicate IDs are logged at DEBUG level"""
        redis_manager.redis_client = mock_redis

        # Simulate duplicate ID error
        mock_redis.xadd.side_effect = redis_exceptions.ResponseError("ERR The ID specified is equal or smaller")

        with caplog.at_level(logging.DEBUG):
            result = await redis_manager.publish_signal(valid_signal_data)

        assert result is False
        debug_logs = [r for r in caplog.records if r.levelname == "DEBUG"]
        assert any("Duplicate signal_id rejected" in log.message for log in debug_logs)

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_duplicate_id_emits_metric(self, redis_manager, mock_redis, valid_signal_data):
        """Test that duplicate IDs emit Prometheus counter"""
        redis_manager.redis_client = mock_redis

        # Get initial count
        initial_count = SIGNAL_DUPLICATES_REJECTED_TOTAL.labels(stream='signals:paper')._value.get()

        # Simulate duplicate ID error
        mock_redis.xadd.side_effect = redis_exceptions.ResponseError("ERR The ID specified is equal or smaller")

        await redis_manager.publish_signal(valid_signal_data)

        # Counter should increment
        final_count = SIGNAL_DUPLICATES_REJECTED_TOTAL.labels(stream='signals:paper')._value.get()
        assert final_count > initial_count


class TestRetryLogic:
    """Test retry logic with exponential backoff (PRD-001 Section 2.3 Item 6)"""

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self, redis_manager, mock_redis, valid_signal_data):
        """Test that publish retries on transient errors"""
        redis_manager.redis_client = mock_redis

        # Fail twice, succeed on third attempt
        mock_redis.xadd.side_effect = [
            Exception("Connection error"),
            Exception("Connection error"),
            AsyncMock()
        ]

        result = await redis_manager.publish_signal(valid_signal_data)

        assert result is True
        assert mock_redis.xadd.call_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self, redis_manager, mock_redis, valid_signal_data):
        """Test exponential backoff delays (100ms, 200ms, 400ms)"""
        redis_manager.redis_client = mock_redis

        # Track timing of retries
        call_times = []

        async def track_time(*args, **kwargs):
            call_times.append(time.time())
            raise Exception("Connection error")

        mock_redis.xadd.side_effect = track_time

        start_time = time.time()
        await redis_manager.publish_signal(valid_signal_data)

        # Should have 3 attempts
        assert len(call_times) == 3

        # Check delays (allowing 50ms tolerance)
        if len(call_times) >= 2:
            delay1 = call_times[1] - call_times[0]
            assert 0.05 <= delay1 <= 0.15  # ~100ms

        if len(call_times) >= 3:
            delay2 = call_times[2] - call_times[1]
            assert 0.15 <= delay2 <= 0.25  # ~200ms

    @pytest.mark.asyncio
    async def test_max_three_retries(self, redis_manager, mock_redis, valid_signal_data):
        """Test that max 3 retry attempts are made"""
        redis_manager.redis_client = mock_redis

        # Always fail
        mock_redis.xadd.side_effect = Exception("Connection error")

        result = await redis_manager.publish_signal(valid_signal_data)

        assert result is False
        assert mock_redis.xadd.call_count == 3  # Exactly 3 attempts


class TestErrorLogging:
    """Test error logging (PRD-001 Section 2.3 Item 7)"""

    @pytest.mark.asyncio
    async def test_publish_failure_logged_at_error(self, redis_manager, mock_redis, valid_signal_data, caplog):
        """Test that publish failures are logged at ERROR level"""
        redis_manager.redis_client = mock_redis
        mock_redis.xadd.side_effect = Exception("Connection error")

        with caplog.at_level(logging.ERROR):
            await redis_manager.publish_signal(valid_signal_data)

        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_logs) > 0
        # Check for either "Failed to publish" or "Unexpected error"
        assert any("publish" in log.message.lower() or "error" in log.message.lower() for log in error_logs)

    @pytest.mark.asyncio
    async def test_error_log_includes_signal_id(self, redis_manager, mock_redis, valid_signal_data, caplog):
        """Test that error logs include signal_id"""
        redis_manager.redis_client = mock_redis
        mock_redis.xadd.side_effect = Exception("Connection error")

        with caplog.at_level(logging.ERROR):
            await redis_manager.publish_signal(valid_signal_data)

        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert any("signal_id=" in log.message for log in error_logs)


class TestPrometheusCounters:
    """Test Prometheus counter emission (PRD-001 Section 2.3 Item 8-10)"""

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_redis_error_emits_metric(self, redis_manager, mock_redis, valid_signal_data):
        """Test that Redis errors emit redis_publish_errors_total counter"""
        redis_manager.redis_client = mock_redis

        # Get initial count (generic exceptions get 'unknown' error_type)
        initial_count = REDIS_PUBLISH_ERRORS_TOTAL.labels(
            stream='signals:paper',
            error_type='unknown'
        )._value.get()

        # Simulate generic error
        mock_redis.xadd.side_effect = Exception("Connection error")

        await redis_manager.publish_signal(valid_signal_data)

        # Counter should increment
        final_count = REDIS_PUBLISH_ERRORS_TOTAL.labels(
            stream='signals:paper',
            error_type='unknown'
        )._value.get()
        assert final_count > initial_count


class TestPublishTimeout:
    """Test publish timeout (PRD-001 Section 2.3 Item 11)"""

    @pytest.mark.asyncio
    async def test_publish_timeout_default_5s(self, redis_manager, mock_redis, valid_signal_data, caplog):
        """Test that publish has 5s timeout by default"""
        redis_manager.redis_client = mock_redis

        # Simulate slow operation
        async def slow_xadd(*args, **kwargs):
            await asyncio.sleep(10)  # Longer than timeout

        mock_redis.xadd.side_effect = slow_xadd

        with caplog.at_level(logging.ERROR):
            result = await redis_manager.publish_signal(valid_signal_data)

        assert result is False
        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert any("timeout" in log.message.lower() for log in error_logs)

    @pytest.mark.asyncio
    async def test_custom_timeout(self, redis_manager, mock_redis, valid_signal_data):
        """Test that custom timeout can be specified"""
        redis_manager.redis_client = mock_redis

        # Simulate slow operation
        async def slow_xadd(*args, **kwargs):
            await asyncio.sleep(0.5)

        mock_redis.xadd.side_effect = slow_xadd

        # Use very short timeout
        result = await redis_manager.publish_signal(valid_signal_data, timeout=0.1)

        assert result is False


class TestFailedPublishQueue:
    """Test failed publish queue (PRD-001 Section 2.3 Item 12)"""

    @pytest.mark.asyncio
    async def test_failed_publish_added_to_queue(self, redis_manager, mock_redis, valid_signal_data):
        """Test that failed publishes are added to queue"""
        redis_manager.redis_client = mock_redis
        mock_redis.xadd.side_effect = Exception("Connection error")

        initial_queue_size = len(redis_manager.failed_publishes)

        await redis_manager.publish_signal(valid_signal_data)

        final_queue_size = len(redis_manager.failed_publishes)
        assert final_queue_size > initial_queue_size

    @pytest.mark.asyncio
    async def test_queue_max_1000(self, redis_manager, mock_redis, valid_signal_data):
        """Test that queue has max 1000 items"""
        redis_manager.redis_client = mock_redis
        mock_redis.xadd.side_effect = Exception("Connection error")

        # Try to add 1500 failed publishes
        for _ in range(1500):
            await redis_manager.publish_signal(valid_signal_data)

        # Queue should cap at 1000
        assert len(redis_manager.failed_publishes) == 1000

    @pytest.mark.asyncio
    async def test_queue_stores_signal_data_and_stream(self, redis_manager, mock_redis, valid_signal_data):
        """Test that queue stores both signal data and stream name"""
        redis_manager.redis_client = mock_redis
        mock_redis.xadd.side_effect = Exception("Connection error")

        await redis_manager.publish_signal(valid_signal_data, stream_name="signals:live")

        # Should have one failed publish
        assert len(redis_manager.failed_publishes) > 0

        # Check stored data
        stored_data, stored_stream = redis_manager.failed_publishes[-1]
        assert stored_data == valid_signal_data
        assert stored_stream == "signals:live"


class TestPublishWithNoRedis:
    """Test publish behavior when Redis is not connected"""

    @pytest.mark.asyncio
    async def test_publish_fails_gracefully_without_redis(self, redis_manager, valid_signal_data, caplog):
        """Test that publish fails gracefully when Redis not connected"""
        # Redis client is None
        assert redis_manager.redis_client is None

        with caplog.at_level(logging.ERROR):
            result = await redis_manager.publish_signal(valid_signal_data)

        assert result is False
        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert any("Cannot publish signal" in log.message for log in error_logs)

    @pytest.mark.asyncio
    async def test_queues_publish_when_redis_unavailable(self, redis_manager, valid_signal_data):
        """Test that publish is queued when Redis unavailable"""
        initial_queue_size = len(redis_manager.failed_publishes)

        await redis_manager.publish_signal(valid_signal_data)

        final_queue_size = len(redis_manager.failed_publishes)
        assert final_queue_size > initial_queue_size
