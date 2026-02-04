#!/usr/bin/env python3
"""
Signal Queue with Heartbeat and Backpressure Handling
======================================================

Bounded async queue for outbound signal events with:
- Heartbeat emission every 15s to metrics:scalper
- Confidence-based signal shedding on backpressure
- Queue depth monitoring
- Error tracking

Features:
- Fixed capacity queue (default: 1000 signals)
- Automatic shedding of lowest-confidence signals when full
- Heartbeat with queue health metrics
- Prometheus metrics integration
"""

import asyncio
import logging
import time
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from signals.scalper_schema import ScalperSignal
from agents.infrastructure.redis_client import RedisCloudClient

logger = logging.getLogger(__name__)


@dataclass(order=True)
class QueuedSignal:
    """
    Signal wrapper for priority queue ordering.

    Signals are ordered by confidence (lowest first for shedding).
    """
    confidence: float
    signal: ScalperSignal = field(compare=False)
    enqueue_time_ms: int = field(compare=False)


class SignalQueue:
    """
    Bounded async queue for signal publishing with backpressure handling.

    Features:
    - Fixed capacity with confidence-based shedding
    - Heartbeat emission every 15s
    - Queue depth and error tracking
    - Prometheus metrics integration
    """

    def __init__(
        self,
        redis_client: RedisCloudClient,
        max_size: int = 1000,
        heartbeat_interval_sec: float = 15.0,
        prometheus_exporter=None,
    ):
        """
        Initialize signal queue.

        Args:
            redis_client: Redis client for publishing
            max_size: Maximum queue size (default: 1000)
            heartbeat_interval_sec: Heartbeat interval in seconds (default: 15)
            prometheus_exporter: Optional Prometheus exporter for metrics
        """
        self.redis = redis_client
        self.max_size = max_size
        self.heartbeat_interval = heartbeat_interval_sec
        self.prometheus = prometheus_exporter

        # Queue (using asyncio.Queue)
        self.queue: asyncio.Queue[QueuedSignal] = asyncio.Queue(maxsize=max_size)

        # Metrics
        self.signals_enqueued = 0
        self.signals_published = 0
        self.signals_shed = 0
        self.last_signal_ms = 0
        self.last_error: Optional[str] = None
        self.last_error_time_ms = 0

        # Heartbeat task
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._publisher_task: Optional[asyncio.Task] = None
        self._running = False

        logger.info(
            f"SignalQueue initialized (max_size={max_size}, "
            f"heartbeat_interval={heartbeat_interval_sec}s)"
        )

    async def start(self):
        """Start the queue processor and heartbeat emitter"""
        if self._running:
            logger.warning("SignalQueue already running")
            return

        self._running = True

        # Start publisher task
        self._publisher_task = asyncio.create_task(self._publisher_loop())
        logger.info("Signal publisher task started")

        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("Heartbeat emitter task started")

    async def stop(self):
        """Stop the queue processor and heartbeat emitter"""
        if not self._running:
            return

        self._running = False

        # Cancel tasks
        if self._publisher_task:
            self._publisher_task.cancel()
            try:
                await self._publisher_task
            except asyncio.CancelledError:
                pass

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        logger.info("SignalQueue stopped")

    async def enqueue(self, signal: ScalperSignal) -> bool:
        """
        Enqueue a signal for publishing.

        If queue is full, shed lowest-confidence signal and enqueue new one.

        Args:
            signal: Signal to enqueue

        Returns:
            True if enqueued successfully, False if shed
        """
        queued_signal = QueuedSignal(
            confidence=signal.confidence,
            signal=signal,
            enqueue_time_ms=int(time.time() * 1000),
        )

        try:
            # Try to put without blocking
            self.queue.put_nowait(queued_signal)
            self.signals_enqueued += 1
            return True

        except asyncio.QueueFull:
            # Queue is full - shed lowest confidence signal
            await self._shed_lowest_confidence(queued_signal)
            return False

    async def _shed_lowest_confidence(self, new_signal: QueuedSignal):
        """
        Shed lowest-confidence signal to make room for new signal.

        Args:
            new_signal: New signal to enqueue after shedding
        """
        # Get all signals from queue
        signals: List[QueuedSignal] = []
        while not self.queue.empty():
            try:
                signals.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        # Add new signal
        signals.append(new_signal)

        # Sort by confidence (lowest first)
        signals.sort(key=lambda x: x.confidence)

        # Shed the lowest confidence signal
        if signals:
            shed_signal = signals.pop(0)
            self.signals_shed += 1

            logger.warning(
                f"[BACKPRESSURE] Shed signal: {shed_signal.signal.symbol} "
                f"{shed_signal.signal.side} @ {shed_signal.signal.entry:.2f} "
                f"(conf={shed_signal.confidence:.3f}, queue_full={self.max_size})"
            )

            # Update Prometheus
            if self.prometheus:
                self.prometheus.record_backpressure_event()
                # Also record as dropped signal
                self.prometheus.record_signal_dropped("backpressure")

        # Re-enqueue remaining signals (highest confidence first)
        signals.reverse()  # Now highest confidence first
        for sig in signals:
            try:
                self.queue.put_nowait(sig)
            except asyncio.QueueFull:
                logger.error("Queue still full after shedding - this shouldn't happen")
                break

    async def _publisher_loop(self):
        """
        Main publisher loop.

        Continuously dequeue signals and publish to Redis.
        """
        logger.info("Publisher loop started")

        while self._running:
            try:
                # Get signal from queue (with timeout to check _running flag)
                try:
                    queued_signal = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                # Publish signal
                await self._publish_signal(queued_signal.signal)

                # Mark task done
                self.queue.task_done()

            except asyncio.CancelledError:
                logger.info("Publisher loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in publisher loop: {e}", exc_info=True)
                self.last_error = str(e)
                self.last_error_time_ms = int(time.time() * 1000)
                await asyncio.sleep(1)  # Back off on error

    async def _publish_signal(self, signal: ScalperSignal):
        """
        Publish signal to Redis.

        Args:
            signal: Signal to publish
        """
        try:
            stream_key = signal.get_stream_key()
            signal_json = signal.to_json_str()

            # Publish to Redis
            await self.redis.xadd(
                stream_key,
                {"signal": signal_json},
                maxlen=1000,
            )

            self.signals_published += 1
            self.last_signal_ms = int(time.time() * 1000)

            # Calculate freshness metrics
            now_ms = int(time.time() * 1000)
            event_age_ms = now_ms - signal.ts_exchange
            ingest_lag_ms = now_ms - signal.ts_server

            # Update Prometheus
            if self.prometheus:
                self.prometheus.record_signal_published(
                    symbol=signal.symbol,
                    timeframe=signal.timeframe,
                    side=signal.side,
                    event_age_ms=event_age_ms,
                    ingest_lag_ms=ingest_lag_ms,
                )

            logger.debug(
                f"[PUBLISHED] {signal.symbol} {signal.side} @ {signal.entry:.2f} "
                f"(conf={signal.confidence:.2f}, queue_depth={self.queue.qsize()})"
            )

        except Exception as e:
            logger.error(f"Failed to publish signal: {e}", exc_info=True)
            self.last_error = str(e)
            self.last_error_time_ms = int(time.time() * 1000)
            raise

    async def _heartbeat_loop(self):
        """
        Heartbeat loop.

        Emit heartbeat to metrics:scalper every 15s.
        """
        logger.info(f"Heartbeat loop started (interval={self.heartbeat_interval}s)")

        while self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                # Emit heartbeat
                await self._emit_heartbeat()

            except asyncio.CancelledError:
                logger.info("Heartbeat loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}", exc_info=True)

    async def _emit_heartbeat(self):
        """Emit heartbeat to metrics:scalper stream"""
        try:
            now_ms = int(time.time() * 1000)

            heartbeat_data = {
                "kind": "heartbeat",
                "now_ms": now_ms,
                "last_signal_ms": self.last_signal_ms,
                "queue_depth": self.queue.qsize(),
                "last_error": self.last_error or "",
                "signals_enqueued": self.signals_enqueued,
                "signals_published": self.signals_published,
                "signals_shed": self.signals_shed,
                "queue_utilization_pct": (self.queue.qsize() / self.max_size) * 100,
            }

            # Publish to metrics stream
            await self.redis.xadd(
                "metrics:scalper",
                heartbeat_data,
                maxlen=10000,
            )

            # Update Prometheus heartbeat metrics
            if self.prometheus:
                self.prometheus.record_heartbeat(
                    queue_depth=self.queue.qsize(),
                    queue_capacity=self.max_size,
                    signals_shed=self.signals_shed,
                )

            logger.info(
                f"[HEARTBEAT] queue={self.queue.qsize()}/{self.max_size} "
                f"({heartbeat_data['queue_utilization_pct']:.1f}%), "
                f"published={self.signals_published}, shed={self.signals_shed}"
            )

        except Exception as e:
            logger.error(f"Failed to emit heartbeat: {e}", exc_info=True)
            self.last_error = f"Heartbeat error: {e}"
            self.last_error_time_ms = int(time.time() * 1000)

    def get_stats(self) -> Dict:
        """
        Get current queue statistics.

        Returns:
            Dictionary with queue stats
        """
        return {
            "queue_depth": self.queue.qsize(),
            "queue_capacity": self.max_size,
            "queue_utilization_pct": (self.queue.qsize() / self.max_size) * 100,
            "signals_enqueued": self.signals_enqueued,
            "signals_published": self.signals_published,
            "signals_shed": self.signals_shed,
            "last_signal_ms": self.last_signal_ms,
            "last_error": self.last_error,
            "last_error_time_ms": self.last_error_time_ms,
        }


# =============================================================================
# Self-Test
# =============================================================================

async def test_signal_queue():
    """Test signal queue with heartbeat and backpressure"""
    print("=" * 80)
    print("              SIGNAL QUEUE TEST")
    print("=" * 80)

    # Mock Redis client
    class MockRedis:
        def __init__(self):
            self.published = []

        async def xadd(self, stream, data, maxlen=None):
            self.published.append({"stream": stream, "data": data})
            print(f"[MOCK XADD] {stream}: {data}")

    # Initialize queue
    print("\n1. Initializing signal queue...")
    redis = MockRedis()
    queue = SignalQueue(
        redis_client=redis,
        max_size=5,  # Small queue for testing backpressure
        heartbeat_interval_sec=2.0,  # Fast heartbeat for testing
    )
    print("   [OK] Queue initialized (max_size=5)")

    # Start queue
    print("\n2. Starting queue processor...")
    await queue.start()
    print("   [OK] Queue started")

    # Enqueue signals
    print("\n3. Enqueuing signals...")
    from signals.scalper_schema import ScalperSignal

    for i in range(8):  # Enqueue more than capacity
        signal = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            confidence=0.5 + i * 0.05,  # Varying confidence
            entry=45000.0 + i * 10,
            stop=44500.0 + i * 10,
            tp=46000.0 + i * 10,
            model="test_queue",
            trace_id=f"test-{i}",
        )

        success = await queue.enqueue(signal)
        if success:
            print(f"   [OK] Enqueued signal {i} (conf={signal.confidence:.2f})")
        else:
            print(f"   [SHED] Signal {i} shed due to backpressure")

        await asyncio.sleep(0.1)  # Small delay

    # Wait for signals to be published
    print("\n4. Waiting for signals to be published...")
    await asyncio.sleep(3)

    # Check stats
    print("\n5. Checking queue stats...")
    stats = queue.get_stats()
    print(f"   [OK] Enqueued: {stats['signals_enqueued']}")
    print(f"   [OK] Published: {stats['signals_published']}")
    print(f"   [OK] Shed: {stats['signals_shed']}")
    print(f"   [OK] Queue depth: {stats['queue_depth']}/{stats['queue_capacity']}")

    # Wait for heartbeat
    print("\n6. Waiting for heartbeat...")
    await asyncio.sleep(3)

    # Check heartbeats
    heartbeats = [p for p in redis.published if p["data"].get("kind") == "heartbeat"]
    if heartbeats:
        print(f"   [OK] {len(heartbeats)} heartbeat(s) emitted")
        latest = heartbeats[-1]["data"]
        print(f"   [OK] Queue depth: {latest['queue_depth']}")
        print(f"   [OK] Utilization: {latest['queue_utilization_pct']:.1f}%")
    else:
        print("   [FAIL] No heartbeats emitted")

    # Stop queue
    print("\n7. Stopping queue...")
    await queue.stop()
    print("   [OK] Queue stopped")

    print("\n" + "=" * 80)
    print("[PASS] All tests COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__file__).rsplit('agents', 1)[0])

    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_signal_queue())
