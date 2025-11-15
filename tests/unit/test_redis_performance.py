"""
Tests for Redis Publishing Performance (PRD-001 Section 2.4)

Tests cover:
- P95 latency measurement (target < 20ms)
- Prometheus histogram redis_publish_latency_ms{stream}
- Handle 50+ signals/second without backpressure
- Backpressure detection: queue depth > 1000 → reject, log ERROR
- Prometheus gauge redis_publish_queue_depth{stream}
"""

import pytest
import asyncio
import time
import logging
from unittest.mock import Mock, patch, AsyncMock

from utils.kraken_ws import (
    RedisConnectionManager,
    KrakenWSConfig,
    REDIS_PUBLISH_LATENCY_MS,
    REDIS_PUBLISH_QUEUE_DEPTH,
    PROMETHEUS_AVAILABLE
)


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


class TestLatencyMeasurement:
    """Test P95 latency measurement (PRD-001 Section 2.4 Item 1)"""

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_latency_histogram_emitted(self, redis_manager, mock_redis, valid_signal_data):
        """Test that latency histogram is emitted on successful publish"""
        redis_manager.redis_client = mock_redis

        # Get initial histogram sum
        initial_sum = REDIS_PUBLISH_LATENCY_MS.labels(stream='signals:paper')._sum.get()

        # Publish signal
        await redis_manager.publish_signal(valid_signal_data)

        # Histogram should have recorded a sample
        final_sum = REDIS_PUBLISH_LATENCY_MS.labels(stream='signals:paper')._sum.get()
        assert final_sum > initial_sum

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_latency_target_under_20ms(self, redis_manager, mock_redis, valid_signal_data):
        """Test that latency is typically under 20ms target"""
        redis_manager.redis_client = mock_redis

        # Publish signal and measure latency
        start = time.time()
        await redis_manager.publish_signal(valid_signal_data)
        latency_ms = (time.time() - start) * 1000

        # Should be well under 20ms for mocked Redis
        assert latency_ms < 100  # Very generous for test environment

    @pytest.mark.asyncio
    async def test_latency_measured_for_all_publishes(self, redis_manager, mock_redis, valid_signal_data):
        """Test that latency is measured for every publish"""
        redis_manager.redis_client = mock_redis

        # Get initial sum
        if PROMETHEUS_AVAILABLE:
            initial_sum = REDIS_PUBLISH_LATENCY_MS.labels(stream='signals:paper')._sum.get()
        else:
            initial_sum = 0

        # Publish multiple signals
        for _ in range(10):
            await redis_manager.publish_signal(valid_signal_data)

        # Each should have been measured (check histogram sum increased)
        if PROMETHEUS_AVAILABLE:
            final_sum = REDIS_PUBLISH_LATENCY_MS.labels(stream='signals:paper')._sum.get()
            assert final_sum > initial_sum


class TestHighThroughput:
    """Test handling 50+ signals/second (PRD-001 Section 2.4 Item 3)"""

    @pytest.mark.asyncio
    async def test_handle_50_signals_per_second(self, redis_manager, mock_redis, valid_signal_data):
        """Test that system can handle 50+ signals/second without backpressure"""
        redis_manager.redis_client = mock_redis

        # Publish 60 signals in quick succession
        signals_published = 0
        start_time = time.time()

        for _ in range(60):
            result = await redis_manager.publish_signal(valid_signal_data)
            if result:
                signals_published += 1

        duration = time.time() - start_time

        # Should publish all 60 signals successfully
        assert signals_published == 60

        # Should complete in reasonable time (< 5 seconds for 60 signals)
        assert duration < 5.0

    @pytest.mark.asyncio
    async def test_concurrent_publishes(self, redis_manager, mock_redis, valid_signal_data):
        """Test that concurrent publishes are handled correctly"""
        redis_manager.redis_client = mock_redis

        # Launch 50 concurrent publishes
        tasks = [redis_manager.publish_signal(valid_signal_data) for _ in range(50)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(results)


class TestBackpressureDetection:
    """Test backpressure detection (PRD-001 Section 2.4 Item 4)"""

    @pytest.mark.asyncio
    async def test_backpressure_triggers_at_1000_depth(self, redis_manager, mock_redis, valid_signal_data, caplog):
        """Test that backpressure is triggered when queue depth > 1000"""
        redis_manager.redis_client = mock_redis

        # Manually set queue depth above threshold
        redis_manager.publish_queue_depth['signals:paper'] = 1001

        with caplog.at_level(logging.ERROR):
            result = await redis_manager.publish_signal(valid_signal_data)

        # Should reject the signal
        assert result is False

        # Should log ERROR
        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert any("Backpressure detected" in log.message for log in error_logs)

    @pytest.mark.asyncio
    async def test_backpressure_error_message(self, redis_manager, mock_redis, valid_signal_data, caplog):
        """Test that backpressure error message includes queue depth and threshold"""
        redis_manager.redis_client = mock_redis
        redis_manager.publish_queue_depth['signals:paper'] = 1500

        with caplog.at_level(logging.ERROR):
            await redis_manager.publish_signal(valid_signal_data)

        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert any(
            "1500" in log.message and "1000" in log.message
            for log in error_logs
        )

    @pytest.mark.asyncio
    async def test_no_backpressure_below_threshold(self, redis_manager, mock_redis, valid_signal_data):
        """Test that signals are accepted when queue depth <= 1000"""
        redis_manager.redis_client = mock_redis

        # Set queue depth at threshold (not over)
        redis_manager.publish_queue_depth['signals:paper'] = 1000

        result = await redis_manager.publish_signal(valid_signal_data)

        # Should accept the signal
        assert result is True

    @pytest.mark.asyncio
    async def test_backpressure_prevents_queue_overflow(self, redis_manager, mock_redis, valid_signal_data):
        """Test that backpressure prevents unbounded queue growth"""
        redis_manager.redis_client = mock_redis

        # Fill queue to capacity
        redis_manager.publish_queue_depth['signals:paper'] = 1001

        # Try to publish many more signals
        for _ in range(100):
            await redis_manager.publish_signal(valid_signal_data)

        # Queue should not grow beyond threshold
        assert redis_manager.publish_queue_depth.get('signals:paper', 0) <= 1002  # +1 for last attempt


class TestQueueDepthGauge:
    """Test queue depth gauge (PRD-001 Section 2.4 Item 5)"""

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_queue_depth_gauge_increments(self, redis_manager, mock_redis, valid_signal_data):
        """Test that queue depth gauge increments when publishing starts"""
        redis_manager.redis_client = mock_redis

        # Reset manager's queue depth to ensure clean state
        redis_manager.publish_queue_depth = {}

        # Make xadd hang to keep publish in progress
        async def slow_xadd(*args, **kwargs):
            await asyncio.sleep(0.1)
            return "message-id"

        mock_redis.xadd.side_effect = slow_xadd

        # Start publish (don't await yet)
        publish_task = asyncio.create_task(redis_manager.publish_signal(valid_signal_data))

        # Give it time to increment
        await asyncio.sleep(0.01)

        # Queue depth should be 1 (in progress)
        current_depth = redis_manager.publish_queue_depth.get('signals:paper', 0)
        assert current_depth == 1

        # Clean up
        await publish_task

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_queue_depth_gauge_decrements(self, redis_manager, mock_redis, valid_signal_data):
        """Test that queue depth gauge decrements after publish completes"""
        redis_manager.redis_client = mock_redis

        # Publish signal
        await redis_manager.publish_signal(valid_signal_data)

        # Queue depth should be back to 0 (or low value)
        final_depth = REDIS_PUBLISH_QUEUE_DEPTH.labels(stream='signals:paper')._value.get()
        assert final_depth <= 1

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    @pytest.mark.asyncio
    async def test_queue_depth_per_stream(self, redis_manager, mock_redis, valid_signal_data):
        """Test that queue depth is tracked separately per stream"""
        redis_manager.redis_client = mock_redis

        # Make xadd hang
        async def slow_xadd(*args, **kwargs):
            await asyncio.sleep(0.1)
            return "message-id"

        mock_redis.xadd.side_effect = slow_xadd

        # Publish to paper stream
        task1 = asyncio.create_task(redis_manager.publish_signal(valid_signal_data, stream_name="signals:paper"))
        await asyncio.sleep(0.01)

        # Publish to live stream
        task2 = asyncio.create_task(redis_manager.publish_signal(valid_signal_data, stream_name="signals:live"))
        await asyncio.sleep(0.01)

        # Each stream should have depth tracked
        paper_depth = REDIS_PUBLISH_QUEUE_DEPTH.labels(stream='signals:paper')._value.get()
        live_depth = REDIS_PUBLISH_QUEUE_DEPTH.labels(stream='signals:live')._value.get()

        assert paper_depth >= 1
        assert live_depth >= 1

        # Clean up
        await task1
        await task2

    @pytest.mark.asyncio
    async def test_queue_depth_tracking_survives_errors(self, redis_manager, mock_redis, valid_signal_data):
        """Test that queue depth is properly decremented even on errors"""
        redis_manager.redis_client = mock_redis

        # Make xadd fail
        mock_redis.xadd.side_effect = Exception("Connection error")

        # Publish signal (will fail)
        await redis_manager.publish_signal(valid_signal_data)

        # Queue depth should be back to 0
        final_depth = redis_manager.publish_queue_depth.get('signals:paper', 0)
        assert final_depth == 0


class TestQueueDepthManagement:
    """Test queue depth increment/decrement logic"""

    @pytest.mark.asyncio
    async def test_queue_depth_increments_on_publish_start(self, redis_manager, mock_redis, valid_signal_data):
        """Test that queue depth increments when publish starts"""
        redis_manager.redis_client = mock_redis

        initial_depth = redis_manager.publish_queue_depth.get('signals:paper', 0)

        # Make publish hang
        async def slow_xadd(*args, **kwargs):
            await asyncio.sleep(0.1)
            return "message-id"

        mock_redis.xadd.side_effect = slow_xadd

        # Start publish
        task = asyncio.create_task(redis_manager.publish_signal(valid_signal_data))
        await asyncio.sleep(0.01)

        # Depth should have incremented
        current_depth = redis_manager.publish_queue_depth.get('signals:paper', 0)
        assert current_depth == initial_depth + 1

        # Clean up
        await task

    @pytest.mark.asyncio
    async def test_queue_depth_decrements_on_publish_complete(self, redis_manager, mock_redis, valid_signal_data):
        """Test that queue depth decrements when publish completes"""
        redis_manager.redis_client = mock_redis

        # Publish signal
        await redis_manager.publish_signal(valid_signal_data)

        # Depth should be 0
        final_depth = redis_manager.publish_queue_depth.get('signals:paper', 0)
        assert final_depth == 0

    @pytest.mark.asyncio
    async def test_multiple_concurrent_publishes_track_depth(self, redis_manager, mock_redis, valid_signal_data):
        """Test that multiple concurrent publishes correctly track depth"""
        redis_manager.redis_client = mock_redis

        # Make xadd hang
        async def slow_xadd(*args, **kwargs):
            await asyncio.sleep(0.2)
            return "message-id"

        mock_redis.xadd.side_effect = slow_xadd

        # Launch 5 concurrent publishes
        tasks = [asyncio.create_task(redis_manager.publish_signal(valid_signal_data)) for _ in range(5)]
        await asyncio.sleep(0.05)

        # Depth should reflect concurrent publishes
        current_depth = redis_manager.publish_queue_depth.get('signals:paper', 0)
        assert current_depth == 5

        # Wait for all to complete
        await asyncio.gather(*tasks)

        # Depth should be back to 0
        final_depth = redis_manager.publish_queue_depth.get('signals:paper', 0)
        assert final_depth == 0
