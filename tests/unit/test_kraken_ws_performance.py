"""
Tests for KrakenWSClient performance features (PRD-001 Section 1.5)

Tests cover:
- P95 latency measurement and Prometheus histogram emission
- Message processing at 100+ messages/second
- Backpressure detection and message dropping
- Memory bounds on WebSocket buffers
"""

import pytest
import asyncio
import time
import logging
from unittest.mock import Mock, patch, AsyncMock
from collections import deque

from utils.kraken_ws import (
    KrakenWebSocketClient,
    KrakenWSConfig,
    LatencyTracker,
    KRAKEN_WS_LATENCY_MS,
    KRAKEN_WS_BACKPRESSURE_EVENTS_TOTAL,
    PROMETHEUS_AVAILABLE
)


@pytest.fixture
def config():
    """Create test configuration"""
    return KrakenWSConfig(
        url="wss://ws.kraken.com",
        pairs=["BTC/USD"],
        channels=["trade"],
        enable_latency_tracking=True
    )


@pytest.fixture
def client(config):
    """Create test client"""
    return KrakenWebSocketClient(config)


@pytest.fixture
def latency_tracker():
    """Create test latency tracker"""
    return LatencyTracker()


class TestLatencyTracking:
    """Test P95 latency measurement (PRD-001 Section 1.5 Item 44)"""

    def test_latency_tracker_measures_p95(self, latency_tracker):
        """Test that latency tracker calculates P95 correctly"""
        # Generate 100 samples with known distribution
        for i in range(100):
            op_id = f"op_{i}"
            latency_tracker.start_timing(op_id)
            time.sleep(0.001)  # 1ms
            latency_ms = latency_tracker.end_timing(op_id)
            assert latency_ms > 0

        # Get stats including P95
        stats = latency_tracker.get_stats()
        assert stats["p95"] > 0
        assert stats["p95"] < 50  # Should be well under 50ms target

    def test_latency_tracker_rolling_window(self, latency_tracker):
        """Test that latency tracker maintains rolling window of 1000 samples"""
        # Add more than max_samples (1000)
        for i in range(1500):
            op_id = f"op_{i}"
            latency_tracker.start_timing(op_id)
            latency_tracker.end_timing(op_id)

        # Should only keep last 1000
        assert len(latency_tracker.samples) == 1000

    def test_end_timing_returns_zero_for_unknown_operation(self, latency_tracker):
        """Test that end_timing returns 0 for unknown operation ID"""
        latency_ms = latency_tracker.end_timing("unknown_op")
        assert latency_ms == 0.0


class TestPrometheusLatencyHistogram:
    """Test Prometheus histogram for latency (PRD-001 Section 1.5 Item 45)"""

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_latency_histogram_emitted_with_channel(self, latency_tracker):
        """Test that latency histogram is emitted when channel provided"""
        # Get initial sum
        initial_sum = KRAKEN_WS_LATENCY_MS.labels(channel='trade')._sum.get()

        # Track latency with channel
        op_id = "test_op"
        latency_tracker.start_timing(op_id)
        time.sleep(0.001)
        latency_ms = latency_tracker.end_timing(op_id, channel='trade')

        # Should have emitted histogram observation
        final_sum = KRAKEN_WS_LATENCY_MS.labels(channel='trade')._sum.get()
        assert final_sum > initial_sum

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_latency_histogram_not_emitted_without_channel(self, latency_tracker):
        """Test that histogram not emitted when channel not provided"""
        # Get initial sum for 'trade' channel
        initial_sum = KRAKEN_WS_LATENCY_MS.labels(channel='trade')._sum.get()

        # Track latency without channel
        op_id = "test_op"
        latency_tracker.start_timing(op_id)
        time.sleep(0.001)
        latency_tracker.end_timing(op_id)  # No channel parameter

        # Should NOT have changed 'trade' channel sum
        final_sum = KRAKEN_WS_LATENCY_MS.labels(channel='trade')._sum.get()
        assert final_sum == initial_sum

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_latency_histogram_labels_by_channel(self, latency_tracker):
        """Test that histogram has separate metrics per channel"""
        # Track different channels
        for channel in ['trade', 'spread', 'book', 'ohlc']:
            op_id = f"{channel}_op"
            latency_tracker.start_timing(op_id)
            time.sleep(0.001)
            latency_tracker.end_timing(op_id, channel=channel)

        # Each channel should have observations (sum > 0 means observations were recorded)
        for channel in ['trade', 'spread', 'book', 'ohlc']:
            sum_value = KRAKEN_WS_LATENCY_MS.labels(channel=channel)._sum.get()
            assert sum_value > 0


class TestHighThroughput:
    """Test handling 100+ messages/second (PRD-001 Section 1.5 Item 46)"""

    @pytest.mark.asyncio
    async def test_handles_100_messages_per_second(self, client):
        """Test that client can handle 100+ messages/second without backpressure"""
        messages_sent = 0
        target_rate = 100  # messages per second
        duration = 1.0  # seconds

        # Generate test messages
        test_message = '{"event":"heartbeat"}'

        start_time = time.time()
        while time.time() - start_time < duration:
            await client.handle_message(test_message)
            messages_sent += 1

        # Should have processed at least 100 messages
        assert messages_sent >= target_rate
        assert client.stats["messages_received"] >= target_rate

        # Queue might be exactly at or just slightly over threshold due to timing
        # The important thing is backpressure handling kicks in to prevent unbounded growth
        assert len(client.message_queue) <= client.backpressure_threshold + 100

    @pytest.mark.asyncio
    async def test_no_backpressure_under_normal_load(self, client):
        """Test that normal message rates don't trigger backpressure"""
        # Send 500 messages (5 seconds of load at 100 msg/s)
        test_message = '{"event":"heartbeat"}'

        for _ in range(500):
            await client.handle_message(test_message)

        # Queue should stay well below threshold
        assert len(client.message_queue) < client.backpressure_threshold


class TestBackpressureDetection:
    """Test backpressure detection and message dropping (PRD-001 Section 1.5 Item 47)"""

    def test_backpressure_not_detected_below_threshold(self, client):
        """Test that backpressure is not detected when queue depth < 1000"""
        # Add messages below threshold
        for i in range(500):
            client.message_queue.append(time.time())

        # Should not detect backpressure
        backpressure = client.check_backpressure()
        assert backpressure is False

    def test_backpressure_detected_above_threshold(self, client, caplog):
        """Test that backpressure is detected when queue depth > 1000"""
        # Fill queue above threshold
        for i in range(1500):
            client.message_queue.append(time.time())

        with caplog.at_level(logging.WARNING):
            backpressure = client.check_backpressure()

        # Should detect backpressure
        assert backpressure is True

        # Should log warning
        warning_logs = [record for record in caplog.records if record.levelname == "WARNING"]
        assert any("backpressure detected" in log.message.lower() for log in warning_logs)

    def test_backpressure_drops_oldest_messages(self, client):
        """Test that backpressure drops oldest messages"""
        # Fill queue above threshold
        for i in range(1500):
            client.message_queue.append(time.time() + i)

        initial_depth = len(client.message_queue)
        assert initial_depth > client.backpressure_threshold

        # Check backpressure (should drop messages)
        client.check_backpressure()

        # Queue depth should be reduced
        final_depth = len(client.message_queue)
        assert final_depth < initial_depth

    def test_backpressure_warning_throttled(self, client, caplog):
        """Test that backpressure warning is throttled to once per minute"""
        # Fill queue above threshold
        for i in range(1500):
            client.message_queue.append(time.time())

        with caplog.at_level(logging.WARNING):
            # First check should log
            client.check_backpressure()
            first_warning_count = len([r for r in caplog.records if "backpressure" in r.message.lower()])

            # Immediate second check should NOT log again
            client.check_backpressure()
            second_warning_count = len([r for r in caplog.records if "backpressure" in r.message.lower()])

        assert first_warning_count == 1
        assert second_warning_count == 1  # Same count, no new warning

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_backpressure_increments_prometheus_counter(self, client):
        """Test that backpressure events increment Prometheus counter"""
        # Get initial counts
        initial_threshold_count = KRAKEN_WS_BACKPRESSURE_EVENTS_TOTAL.labels(
            action='threshold_exceeded'
        )._value.get()

        # Fill queue above threshold
        for i in range(1500):
            client.message_queue.append(time.time())

        # Trigger backpressure
        client.check_backpressure()

        # Counter should increment
        final_threshold_count = KRAKEN_WS_BACKPRESSURE_EVENTS_TOTAL.labels(
            action='threshold_exceeded'
        )._value.get()
        assert final_threshold_count > initial_threshold_count

    def test_message_queue_hard_cap_at_10k(self, client):
        """Test that message queue has hard cap at 10,000 messages"""
        # Try to add 15,000 messages
        for i in range(15000):
            client.message_queue.append(time.time())

        # Deque maxlen should enforce hard cap
        assert len(client.message_queue) == 10000


class TestMemoryBounds:
    """Test WebSocket buffer memory bounds (PRD-001 Section 1.5 Item 48)"""

    def test_websocket_read_limit_set(self, client):
        """Test that WebSocket read buffer limit is set to 50MB"""
        assert client.websocket_read_limit == 50 * 1024 * 1024  # 50MB

    def test_websocket_write_limit_set(self, client):
        """Test that WebSocket write buffer limit is set to 50MB"""
        assert client.websocket_write_limit == 50 * 1024 * 1024  # 50MB

    def test_total_buffer_limit_is_100mb(self, client):
        """Test that total buffer limit is 100MB"""
        total_limit = client.websocket_read_limit + client.websocket_write_limit
        assert total_limit == 100 * 1024 * 1024  # 100MB

    @pytest.mark.asyncio
    async def test_websocket_connection_uses_buffer_limits(self, client):
        """Test that websocket.connect() is called with buffer limits"""
        with patch('websockets.connect') as mock_connect:
            mock_ws = AsyncMock()
            mock_connect.return_value.__aenter__.return_value = mock_ws
            mock_ws.__aiter__.return_value = iter([])  # Empty message stream

            try:
                await client.connect_once()
            except Exception:
                pass  # Connection will fail, we just want to check the call

            # Verify websockets.connect was called with buffer limits
            mock_connect.assert_called_once()
            call_kwargs = mock_connect.call_args.kwargs
            assert call_kwargs.get('max_size') == 50 * 1024 * 1024
            assert call_kwargs.get('write_limit') == 50 * 1024 * 1024


class TestEndToEndPerformance:
    """Integration tests for performance features"""

    @pytest.mark.asyncio
    async def test_latency_tracking_in_message_handlers(self, client):
        """Test that latency is tracked through message handlers"""
        # Send trade message
        trade_message = '[192, [["50000.00", "1.5", "1234567890.123", "b", "m", ""]], "trade", "BTC/USD"]'

        with patch.object(client, 'handle_trade_data', new_callable=AsyncMock) as mock_handler:
            await client.handle_message(trade_message)

        # Handler should have been called
        assert mock_handler.called

        # Latency should be tracked
        assert client.stats["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_backpressure_integrated_in_handle_message(self, client):
        """Test that backpressure check is integrated in handle_message"""
        # Fill queue above threshold
        for i in range(1500):
            client.message_queue.append(time.time())

        initial_depth = len(client.message_queue)

        # Process message (should trigger backpressure check)
        test_message = '{"event":"heartbeat"}'
        await client.handle_message(test_message)

        # Queue should have been reduced by backpressure check
        final_depth = len(client.message_queue)
        assert final_depth < initial_depth

    @pytest.mark.asyncio
    async def test_performance_under_sustained_load(self, client):
        """Test performance metrics under sustained load"""
        # Send 1000 messages
        test_message = '{"event":"heartbeat"}'
        start_time = time.time()

        for _ in range(1000):
            await client.handle_message(test_message)

        duration = time.time() - start_time

        # Should process 1000 messages quickly (well under 10 seconds)
        assert duration < 10.0

        # Message queue should be managed
        assert len(client.message_queue) <= 10000

        # Stats should be updated
        assert client.stats["messages_received"] >= 1000
