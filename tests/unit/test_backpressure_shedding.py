#!/usr/bin/env python3
"""
Unit Tests for Backpressure Shedding Logic
===========================================

Tests:
- Confidence-based signal shedding
- Queue capacity limits
- Shedding algorithm correctness
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock
from signals.scalper_schema import ScalperSignal
from agents.infrastructure.signal_queue import SignalQueue, QueuedSignal


class TestBackpressureShedding:
    """Test backpressure shedding logic"""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client"""
        redis = Mock()
        redis.xadd = AsyncMock()
        return redis

    @pytest.fixture
    def mock_prometheus(self):
        """Create mock Prometheus exporter"""
        prom = Mock()
        prom.record_signal_published = Mock()
        prom.record_backpressure_event = Mock()
        prom.record_signal_dropped = Mock()
        prom.record_heartbeat = Mock()
        return prom

    @pytest.mark.asyncio
    async def test_queue_under_capacity(self, mock_redis, mock_prometheus):
        """Test that signals are enqueued when queue not full"""
        queue = SignalQueue(
            redis_client=mock_redis,
            max_size=10,
            heartbeat_interval_sec=60,
            prometheus_exporter=mock_prometheus,
        )

        # Create test signal
        signal = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.8,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model",
            trace_id="test-001",
        )

        # Enqueue signal
        success = await queue.enqueue(signal)

        assert success is True
        assert queue.signals_enqueued == 1
        assert queue.queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_queue_at_capacity_sheds_lowest_confidence(
        self, mock_redis, mock_prometheus
    ):
        """Test that lowest confidence signal is shed when queue is full"""
        queue = SignalQueue(
            redis_client=mock_redis,
            max_size=5,  # Small capacity for testing
            heartbeat_interval_sec=60,
            prometheus_exporter=mock_prometheus,
        )

        # Fill queue with signals of varying confidence
        confidence_values = [0.60, 0.70, 0.80, 0.85, 0.90]

        for i, conf in enumerate(confidence_values):
            signal = ScalperSignal(
                ts_exchange=int(time.time() * 1000),
                ts_server=int(time.time() * 1000),
                symbol="BTC/USD",
                timeframe="15s",
                side="long",
                confidence=conf,
                entry=45000.0 + i,
                stop=44500.0 + i,
                tp=46000.0 + i,
                model="test_model",
                trace_id=f"test-{i}",
            )
            success = await queue.enqueue(signal)
            assert success is True

        # Queue should be full
        assert queue.queue.qsize() == 5
        assert queue.signals_enqueued == 5

        # Add new signal with medium confidence
        new_signal = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="ETH/USD",
            timeframe="15s",
            side="short",
            confidence=0.75,  # Between 0.70 and 0.80
            entry=3000.0,
            stop=2950.0,
            tp=3100.0,
            model="test_model",
            trace_id="test-new",
        )

        # This should trigger shedding
        success = await queue.enqueue(new_signal)

        # Should return False (backpressure)
        assert success is False

        # Queue should still be at capacity
        assert queue.queue.qsize() == 5

        # Signals shed counter should increment
        assert queue.signals_shed == 1

        # Prometheus backpressure should be recorded
        mock_prometheus.record_backpressure_event.assert_called_once()
        mock_prometheus.record_signal_dropped.assert_called_once_with("backpressure")

    @pytest.mark.asyncio
    async def test_shedding_keeps_highest_confidence(
        self, mock_redis, mock_prometheus
    ):
        """Test that shedding preserves highest confidence signals"""
        queue = SignalQueue(
            redis_client=mock_redis,
            max_size=3,
            heartbeat_interval_sec=60,
            prometheus_exporter=mock_prometheus,
        )

        # Add signals: 0.50, 0.70, 0.90
        signals_data = [
            (0.50, "test-1"),
            (0.70, "test-2"),
            (0.90, "test-3"),
        ]

        for conf, trace_id in signals_data:
            signal = ScalperSignal(
                ts_exchange=int(time.time() * 1000),
                ts_server=int(time.time() * 1000),
                symbol="BTC/USD",
                timeframe="15s",
                side="long",
                confidence=conf,
                entry=45000.0,
                stop=44500.0,
                tp=46000.0,
                model="test_model",
                trace_id=trace_id,
            )
            await queue.enqueue(signal)

        # Add signal with confidence 0.80
        new_signal = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="ETH/USD",
            timeframe="15s",
            side="short",
            confidence=0.80,
            entry=3000.0,
            stop=2950.0,
            tp=3100.0,
            model="test_model",
            trace_id="test-new",
        )

        await queue.enqueue(new_signal)

        # Lowest confidence (0.50) should be shed
        # Remaining: 0.70, 0.80, 0.90
        assert queue.signals_shed == 1

        # Extract signals to verify
        remaining_confidences = []
        while not queue.queue.empty():
            queued = queue.queue.get_nowait()
            remaining_confidences.append(queued.confidence)

        # Should have 3 signals
        assert len(remaining_confidences) == 3

        # Should NOT contain 0.50
        assert 0.50 not in remaining_confidences

        # Should contain 0.70, 0.80, 0.90
        assert 0.70 in remaining_confidences
        assert 0.80 in remaining_confidences
        assert 0.90 in remaining_confidences

    @pytest.mark.asyncio
    async def test_multiple_shedding_events(self, mock_redis, mock_prometheus):
        """Test multiple shedding events in sequence"""
        queue = SignalQueue(
            redis_client=mock_redis,
            max_size=2,  # Very small capacity
            heartbeat_interval_sec=60,
            prometheus_exporter=mock_prometheus,
        )

        # Fill queue with 0.60, 0.70
        for conf in [0.60, 0.70]:
            signal = ScalperSignal(
                ts_exchange=int(time.time() * 1000),
                ts_server=int(time.time() * 1000),
                symbol="BTC/USD",
                timeframe="15s",
                side="long",
                confidence=conf,
                entry=45000.0,
                stop=44500.0,
                tp=46000.0,
                model="test_model",
                trace_id=f"test-{conf}",
            )
            await queue.enqueue(signal)

        assert queue.signals_shed == 0

        # Add signal with 0.80 (should shed 0.60)
        signal_1 = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.80,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model",
            trace_id="test-1",
        )
        await queue.enqueue(signal_1)
        assert queue.signals_shed == 1

        # Add signal with 0.90 (should shed 0.70)
        signal_2 = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.90,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test_model",
            trace_id="test-2",
        )
        await queue.enqueue(signal_2)
        assert queue.signals_shed == 2

        # Remaining should be 0.80, 0.90
        remaining = []
        while not queue.queue.empty():
            queued = queue.queue.get_nowait()
            remaining.append(queued.confidence)

        assert set(remaining) == {0.80, 0.90}

    @pytest.mark.asyncio
    async def test_shedding_with_equal_confidence(
        self, mock_redis, mock_prometheus
    ):
        """Test shedding behavior when all signals have equal confidence"""
        queue = SignalQueue(
            redis_client=mock_redis,
            max_size=3,
            heartbeat_interval_sec=60,
            prometheus_exporter=mock_prometheus,
        )

        # Fill queue with equal confidence signals
        for i in range(3):
            signal = ScalperSignal(
                ts_exchange=int(time.time() * 1000),
                ts_server=int(time.time() * 1000),
                symbol="BTC/USD",
                timeframe="15s",
                side="long",
                confidence=0.75,  # All equal
                entry=45000.0 + i,
                stop=44500.0 + i,
                tp=46000.0 + i,
                model="test_model",
                trace_id=f"test-{i}",
            )
            await queue.enqueue(signal)

        # Add another with same confidence
        new_signal = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="ETH/USD",
            timeframe="15s",
            side="short",
            confidence=0.75,
            entry=3000.0,
            stop=2950.0,
            tp=3100.0,
            model="test_model",
            trace_id="test-new",
        )

        await queue.enqueue(new_signal)

        # One should be shed (first in sorted order)
        assert queue.signals_shed == 1

        # Queue should still have 3 signals
        assert queue.queue.qsize() == 3


class TestQueuedSignalOrdering:
    """Test QueuedSignal ordering for priority queue"""

    def test_queued_signal_ordering_by_confidence(self):
        """Test that QueuedSignal orders by confidence"""
        signal1 = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.60,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test",
            trace_id="test-1",
        )

        signal2 = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.90,
            entry=45000.0,
            stop=44500.0,
            tp=46000.0,
            model="test",
            trace_id="test-2",
        )

        queued1 = QueuedSignal(
            confidence=signal1.confidence,
            signal=signal1,
            enqueue_time_ms=int(time.time() * 1000),
        )

        queued2 = QueuedSignal(
            confidence=signal2.confidence,
            signal=signal2,
            enqueue_time_ms=int(time.time() * 1000),
        )

        # Lower confidence should be "less than" (for shedding)
        assert queued1 < queued2

        # Higher confidence should be "greater than"
        assert queued2 > queued1

    def test_queued_signal_list_sorting(self):
        """Test sorting list of QueuedSignals"""
        signals = []

        for conf in [0.90, 0.50, 0.75, 0.85, 0.60]:
            signal = ScalperSignal(
                ts_exchange=int(time.time() * 1000),
                ts_server=int(time.time() * 1000),
                symbol="BTC/USD",
                timeframe="15s",
                side="long",
                confidence=conf,
                entry=45000.0,
                stop=44500.0,
                tp=46000.0,
                model="test",
                trace_id=f"test-{conf}",
            )

            queued = QueuedSignal(
                confidence=conf,
                signal=signal,
                enqueue_time_ms=int(time.time() * 1000),
            )
            signals.append(queued)

        # Sort (should be ascending by confidence)
        signals.sort()

        confidences = [q.confidence for q in signals]

        # Should be sorted: 0.50, 0.60, 0.75, 0.85, 0.90
        assert confidences == [0.50, 0.60, 0.75, 0.85, 0.90]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
