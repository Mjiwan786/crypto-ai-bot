"""
Unit tests for Resilient Publisher (Redis Publish Reliability)

Tests coverage:
- Successful immediate publish
- Retry on failure with exponential backoff
- Retry queue management
- Dead Letter Queue (DLQ) for permanent failures
- Queue flushing and recovery
- Priority message handling
- Queue size limits and message dropping
- Health status reporting
- Prometheus metrics

Author: Reliability & QA Team
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch, call

from agents.infrastructure.resilient_publisher import (
    ResilientPublisher,
    ResilientPublisherConfig,
    PublishMessage,
)


@pytest.fixture
def mock_redis_client():
    """Mock Redis client"""
    client = AsyncMock()
    client.xadd = AsyncMock()
    return client


@pytest.fixture
def publisher(mock_redis_client):
    """Create resilient publisher with mock client"""
    config = ResilientPublisherConfig(
        max_retries=3,
        base_delay_seconds=0.1,  # Fast for testing
        max_queue_size=10
    )
    return ResilientPublisher(mock_redis_client, config)


class TestResilientPublisherBasics:
    """Test basic publisher functionality"""

    @pytest.mark.asyncio
    async def test_successful_publish(self, publisher, mock_redis_client):
        """Test successful immediate publish"""
        mock_redis_client.xadd.return_value = "1234-0"

        success = await publisher.publish(
            stream_name="test:stream",
            data={"key": "value"},
            maxlen=1000
        )

        assert success is True
        assert publisher.stats["successful_publishes"] == 1
        assert publisher.stats["total_publishes"] == 1
        assert publisher.stats["failed_publishes"] == 0

        # Verify xadd was called correctly
        mock_redis_client.xadd.assert_called_once_with(
            "test:stream",
            {"key": "value"},
            maxlen=1000
        )

    @pytest.mark.asyncio
    async def test_publish_with_message_id(self, publisher, mock_redis_client):
        """Test publish with message ID for tracing"""
        mock_redis_client.xadd.return_value = "1234-0"

        success = await publisher.publish(
            stream_name="test:stream",
            data={"key": "value"},
            message_id="trace-123"
        )

        assert success is True


class TestResilientPublisherRetry:
    """Test retry logic"""

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, publisher, mock_redis_client):
        """Test message is queued for retry on failure"""
        # First attempt fails
        mock_redis_client.xadd.side_effect = Exception("Connection error")

        success = await publisher.publish(
            stream_name="test:stream",
            data={"key": "value"}
        )

        # Should be queued (returns True)
        assert success is True
        assert publisher.stats["total_publishes"] == 1
        assert publisher.stats["successful_publishes"] == 0

        # Check retry queue
        assert "test:stream" in publisher.retry_queues
        assert len(publisher.retry_queues["test:stream"]) == 1

    @pytest.mark.asyncio
    async def test_retry_queue_flush(self, publisher, mock_redis_client):
        """Test retry queue flushes on recovery"""
        # First attempt fails
        mock_redis_client.xadd.side_effect = [
            Exception("Connection error"),  # Initial publish fails
            "1234-0"  # Retry succeeds
        ]

        # Publish (will be queued)
        await publisher.publish(
            stream_name="test:stream",
            data={"key": "value"}
        )

        # Flush queue (simulates background task)
        await publisher._flush_queue("test:stream")

        # Wait for retry delay
        await asyncio.sleep(0.2)

        # Queue should be empty after successful retry
        assert len(publisher.retry_queues.get("test:stream", [])) == 0
        assert publisher.stats["successful_publishes"] == 1
        assert publisher.stats["retries"] == 1

    @pytest.mark.asyncio
    async def test_max_retries_sends_to_dlq(self, publisher, mock_redis_client):
        """Test message sent to DLQ after max retries"""
        # Track call count
        call_count = [0]

        def xadd_side_effect(stream_name, data, **kwargs):
            call_count[0] += 1
            # Regular stream fails 4 times (initial + 3 retries)
            # DLQ stream succeeds
            if stream_name.endswith(":dlq"):
                return "dlq-1234-0"
            raise Exception(f"Connection error {call_count[0]}")

        mock_redis_client.xadd.side_effect = xadd_side_effect

        # Publish (will be queued)
        await publisher.publish(
            stream_name="test:stream",
            data={"key": "value"},
            message_id="msg-123"
        )

        # Flush queue 3 times (trigger max retries)
        for _ in range(3):
            await publisher._flush_queue("test:stream")
            await asyncio.sleep(0.2)  # Wait for backoff

        # Verify DLQ call
        dlq_calls = [
            c for c in mock_redis_client.xadd.call_args_list
            if "test:stream:dlq" in str(c)
        ]

        assert len(dlq_calls) == 1
        assert publisher.stats["dlq_messages"] == 1


class TestResilientPublisherQueueManagement:
    """Test queue management"""

    @pytest.mark.asyncio
    async def test_queue_size_limit(self, publisher, mock_redis_client):
        """Test queue drops messages when full"""
        publisher.config.max_queue_size = 3

        # All publishes fail
        mock_redis_client.xadd.side_effect = Exception("Connection error")

        # Fill queue to limit
        for i in range(3):
            success = await publisher.publish(
                stream_name="test:stream",
                data={"msg": str(i)}
            )
            assert success is True  # Queued

        # Next message should be dropped
        success = await publisher.publish(
            stream_name="test:stream",
            data={"msg": "dropped"}
        )

        assert success is False  # Dropped
        assert publisher.stats["dropped_messages"] == 1
        assert len(publisher.retry_queues["test:stream"]) == 3

    @pytest.mark.asyncio
    async def test_priority_message_ordering(self, publisher, mock_redis_client):
        """Test priority messages are processed first"""
        mock_redis_client.xadd.side_effect = Exception("Connection error")

        # Add messages with different priorities
        await publisher.publish("test:stream", {"msg": "normal1"}, priority=0)
        await publisher.publish("test:stream", {"msg": "high"}, priority=10)
        await publisher.publish("test:stream", {"msg": "normal2"}, priority=0)

        queue = publisher.retry_queues["test:stream"]

        # High priority should be first
        assert queue[0].data["msg"] == "high"
        assert queue[0].priority == 10


class TestResilientPublisherDLQ:
    """Test Dead Letter Queue"""

    @pytest.mark.asyncio
    async def test_dlq_metadata(self, publisher, mock_redis_client):
        """Test DLQ message includes metadata"""
        mock_redis_client.xadd.side_effect = [
            Exception("Error 1"),
            Exception("Error 2"),
            Exception("Error 3"),
            Exception("Error 4"),
            "dlq-1234-0"  # DLQ succeeds
        ]

        # Publish and fail repeatedly
        await publisher.publish(
            stream_name="test:stream",
            data={"original": "data"},
            message_id="trace-123"
        )

        # Flush until DLQ
        for _ in range(3):
            await publisher._flush_queue("test:stream")
            await asyncio.sleep(0.2)

        # Find DLQ call
        dlq_call = None
        for c in mock_redis_client.xadd.call_args_list:
            if len(c.args) > 0 and "dlq" in c.args[0]:
                dlq_call = c
                break

        assert dlq_call is not None

        dlq_stream, dlq_data = dlq_call.args[0], dlq_call.args[1]

        assert dlq_stream == "test:stream:dlq"
        assert "_dlq_reason" in dlq_data
        assert "_dlq_attempts" in dlq_data
        assert "_dlq_message_id" in dlq_data
        assert dlq_data["_dlq_message_id"] == "trace-123"
        assert "original" in dlq_data  # Original data preserved


class TestResilientPublisherHealthStatus:
    """Test health status reporting"""

    @pytest.mark.asyncio
    async def test_health_healthy(self, publisher, mock_redis_client):
        """Test healthy status"""
        mock_redis_client.xadd.return_value = "1234-0"

        # Successful publish
        await publisher.publish("test:stream", {"key": "value"})

        health = publisher.get_health_stats()

        assert health["health"] == "healthy"
        assert health["total_queue_size"] == 0
        assert health["stats"]["successful_publishes"] == 1

    @pytest.mark.asyncio
    async def test_health_degraded_queue_size(self, publisher, mock_redis_client):
        """Test degraded status when queue is growing"""
        publisher.config.degraded_queue_size_threshold = 2

        # Fail publishes to build queue
        mock_redis_client.xadd.side_effect = Exception("Connection error")

        for i in range(3):
            await publisher.publish("test:stream", {"msg": str(i)})

        health = publisher.get_health_stats()

        assert health["health"] == "degraded"
        assert health["total_queue_size"] >= publisher.config.degraded_queue_size_threshold

    @pytest.mark.asyncio
    async def test_health_unhealthy_large_queue(self, publisher, mock_redis_client):
        """Test unhealthy status when queue is very large"""
        publisher.config.unhealthy_queue_size_threshold = 3

        # Fail publishes
        mock_redis_client.xadd.side_effect = Exception("Connection error")

        for i in range(5):
            await publisher.publish("test:stream", {"msg": str(i)})

        health = publisher.get_health_stats()

        assert health["health"] == "unhealthy"
        assert health["total_queue_size"] >= publisher.config.unhealthy_queue_size_threshold


class TestResilientPublisherBackgroundTasks:
    """Test background tasks"""

    @pytest.mark.asyncio
    async def test_start_stop(self, publisher):
        """Test start and stop background tasks"""
        publisher.start()

        assert publisher.flush_task is not None
        assert not publisher.flush_task.done()

        await publisher.stop()

        assert publisher.is_running is False

    @pytest.mark.asyncio
    async def test_periodic_flush(self, publisher, mock_redis_client):
        """Test periodic queue flushing"""
        mock_redis_client.xadd.side_effect = [
            Exception("Connection error"),  # Initial publish fails
            "1234-0"  # Flush retry succeeds
        ]

        # Start background tasks
        publisher.start()

        # Publish (will be queued)
        await publisher.publish("test:stream", {"key": "value"})

        # Wait for periodic flush (5 seconds + backoff)
        await asyncio.sleep(6)

        # Should have been flushed
        assert len(publisher.retry_queues.get("test:stream", [])) == 0

        await publisher.stop()


class TestResilientPublisherEdgeCases:
    """Test edge cases"""

    @pytest.mark.asyncio
    async def test_empty_queue_flush(self, publisher):
        """Test flushing empty queue doesn't error"""
        await publisher._flush_queue("nonexistent:stream")

        # Should not raise

    @pytest.mark.asyncio
    async def test_dlq_disabled(self, publisher, mock_redis_client):
        """Test messages dropped when DLQ disabled"""
        publisher.config.dlq_enabled = False

        mock_redis_client.xadd.side_effect = [
            Exception("Error 1"),
            Exception("Error 2"),
            Exception("Error 3"),
            Exception("Error 4")
        ]

        # Publish and fail repeatedly
        await publisher.publish("test:stream", {"key": "value"})

        # Flush until max retries
        for _ in range(3):
            await publisher._flush_queue("test:stream")
            await asyncio.sleep(0.2)

        # Should be dropped, not sent to DLQ
        assert publisher.stats["dropped_messages"] == 1
        assert publisher.stats["dlq_messages"] == 0

    @pytest.mark.asyncio
    async def test_multiple_streams(self, publisher, mock_redis_client):
        """Test publisher handles multiple streams independently"""
        mock_redis_client.xadd.side_effect = Exception("Connection error")

        # Publish to different streams
        await publisher.publish("stream1", {"msg": "1"})
        await publisher.publish("stream2", {"msg": "2"})
        await publisher.publish("stream1", {"msg": "3"})

        # Check separate queues
        assert len(publisher.retry_queues["stream1"]) == 2
        assert len(publisher.retry_queues["stream2"]) == 1

        # Get queue sizes
        sizes = publisher.get_queue_sizes()
        assert sizes["stream1"] == 2
        assert sizes["stream2"] == 1


@pytest.mark.asyncio
async def test_resilient_publisher_integration():
    """Integration test with real scenario"""
    mock_redis = AsyncMock()

    # Simulate intermittent failures
    mock_redis.xadd.side_effect = [
        Exception("Network error"),  # Fail
        Exception("Still down"),  # Retry 1 fails
        "1234-0",  # Retry 2 succeeds
    ]

    config = ResilientPublisherConfig(
        max_retries=3,
        base_delay_seconds=0.1
    )

    publisher = ResilientPublisher(mock_redis, config)

    # Publish (will be queued)
    success = await publisher.publish(
        stream_name="signals:paper",
        data={"signal": "buy", "symbol": "BTC/USD"},
        message_id="signal-123"
    )

    assert success is True

    # Flush queue (will retry twice before succeeding)
    await publisher._flush_queue("signals:paper")
    await asyncio.sleep(0.2)
    await publisher._flush_queue("signals:paper")
    await asyncio.sleep(0.2)

    # Should eventually succeed
    assert publisher.stats["successful_publishes"] == 1
    assert publisher.stats["retries"] == 1
    assert len(publisher.retry_queues.get("signals:paper", [])) == 0
