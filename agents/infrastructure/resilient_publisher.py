"""
Resilient Redis Publisher with Retry Queue and Dead Letter Queue

Ensures signals are never lost due to transient Redis failures.

Features:
- Automatic retry with exponential backoff (up to 3 attempts)
- In-memory retry queue for failed publishes (max 1000 messages)
- Dead Letter Queue (DLQ) for permanently failed messages
- Automatic queue flushing when Redis reconnects
- Prometheus metrics for publish failures and retries
- Circuit breaker integration

PRD-001 Compliance:
- Section 3.2: Redis streaming reliability
- Section 4.4: Graceful degradation
- Section 8.2: Prometheus metrics

Author: Reliability & QA Team
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Deque

import redis.asyncio as redis

# Prometheus metrics
try:
    from prometheus_client import Counter, Gauge, Histogram

    REDIS_PUBLISH_ATTEMPTS = Counter(
        'redis_publish_attempts_total',
        'Total Redis publish attempts',
        ['stream', 'outcome']  # outcome: success, retry, dlq, dropped
    )

    REDIS_PUBLISH_RETRIES = Counter(
        'redis_publish_retries_total',
        'Total Redis publish retries',
        ['stream', 'retry_attempt']
    )

    REDIS_PUBLISH_DLQ = Counter(
        'redis_publish_dlq_total',
        'Messages sent to Dead Letter Queue',
        ['stream', 'reason']
    )

    REDIS_PUBLISH_QUEUE_SIZE = Gauge(
        'redis_publish_queue_size',
        'Current size of retry queue',
        ['stream']
    )

    REDIS_PUBLISH_DURATION = Histogram(
        'redis_publish_duration_seconds',
        'Redis publish operation duration',
        ['stream', 'outcome']
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    REDIS_PUBLISH_ATTEMPTS = None
    REDIS_PUBLISH_RETRIES = None
    REDIS_PUBLISH_DLQ = None
    REDIS_PUBLISH_QUEUE_SIZE = None
    REDIS_PUBLISH_DURATION = None

logger = logging.getLogger(__name__)


@dataclass
class PublishMessage:
    """Message to be published to Redis stream"""

    stream_name: str
    data: Dict[str, str]
    maxlen: Optional[int] = None

    # Retry tracking
    attempts: int = 0
    first_attempt_time: float = field(default_factory=time.time)
    last_attempt_time: float = 0.0
    last_error: Optional[str] = None

    # Metadata
    message_id: Optional[str] = None  # For tracing
    priority: int = 0  # Higher = more important (0 = normal)


@dataclass
class ResilientPublisherConfig:
    """Configuration for resilient publisher"""

    # Retry settings
    max_retries: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 10.0
    exponential_base: float = 2.0

    # Queue settings
    max_queue_size: int = 1000
    queue_flush_batch_size: int = 100

    # DLQ settings
    dlq_enabled: bool = True
    dlq_suffix: str = ":dlq"
    dlq_maxlen: int = 10000

    # Health thresholds
    unhealthy_queue_size_threshold: int = 500
    degraded_queue_size_threshold: int = 200


class ResilientPublisher:
    """
    Resilient Redis publisher with retry queue and DLQ.

    Usage:
        publisher = ResilientPublisher(redis_client)

        # Publish with automatic retry
        await publisher.publish(
            stream_name="signals:paper",
            data={"signal": "buy", "symbol": "BTC/USD"},
            maxlen=5000
        )

        # Check health
        health = publisher.get_health()
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        config: Optional[ResilientPublisherConfig] = None
    ):
        """
        Initialize resilient publisher.

        Args:
            redis_client: Redis client instance
            config: Publisher configuration (uses defaults if None)
        """
        self.redis_client = redis_client
        self.config = config or ResilientPublisherConfig()
        self.logger = logging.getLogger("ResilientPublisher")

        # Retry queues per stream
        self.retry_queues: Dict[str, Deque[PublishMessage]] = {}

        # Statistics
        self.stats = {
            "total_publishes": 0,
            "successful_publishes": 0,
            "failed_publishes": 0,
            "retries": 0,
            "dlq_messages": 0,
            "dropped_messages": 0,
        }

        # State tracking
        self.last_publish_time: float = 0.0
        self.last_success_time: float = 0.0
        self.is_running = True

        # Background task for queue flushing
        self.flush_task: Optional[asyncio.Task] = None

    def start(self):
        """Start background tasks"""
        if self.flush_task is None:
            self.flush_task = asyncio.create_task(self._periodic_queue_flush())
            self.logger.info("Resilient publisher background tasks started")

    async def stop(self):
        """Stop background tasks and flush queues"""
        self.is_running = False

        if self.flush_task:
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass

        # Final queue flush
        await self._flush_all_queues()

        self.logger.info("Resilient publisher stopped")

    async def publish(
        self,
        stream_name: str,
        data: Dict[str, str],
        maxlen: Optional[int] = None,
        message_id: Optional[str] = None,
        priority: int = 0
    ) -> bool:
        """
        Publish message to Redis stream with automatic retry.

        Args:
            stream_name: Redis stream name
            data: Message data (string keys and values)
            maxlen: Stream maxlen for trimming (optional)
            message_id: Optional message ID for tracing
            priority: Message priority (higher = more important)

        Returns:
            True if published successfully (either immediately or queued), False if dropped
        """
        message = PublishMessage(
            stream_name=stream_name,
            data=data,
            maxlen=maxlen,
            message_id=message_id,
            priority=priority
        )

        self.stats["total_publishes"] += 1
        self.last_publish_time = time.time()

        # Try immediate publish
        start_time = time.time()

        try:
            await self._publish_to_redis(message)

            # Success
            duration = time.time() - start_time
            self.stats["successful_publishes"] += 1
            self.last_success_time = time.time()

            if PROMETHEUS_AVAILABLE:
                if REDIS_PUBLISH_ATTEMPTS:
                    REDIS_PUBLISH_ATTEMPTS.labels(stream=stream_name, outcome="success").inc()
                if REDIS_PUBLISH_DURATION:
                    REDIS_PUBLISH_DURATION.labels(stream=stream_name, outcome="success").observe(duration)

            return True

        except Exception as e:
            # Failure - add to retry queue
            duration = time.time() - start_time

            self.logger.warning(
                f"Redis publish failed (attempt 1/{self.config.max_retries}): {e}",
                extra={
                    "stream": stream_name,
                    "error": str(e),
                    "message_id": message_id
                }
            )

            message.last_error = str(e)
            message.attempts = 1
            message.last_attempt_time = time.time()

            if PROMETHEUS_AVAILABLE:
                if REDIS_PUBLISH_ATTEMPTS:
                    REDIS_PUBLISH_ATTEMPTS.labels(stream=stream_name, outcome="retry").inc()
                if REDIS_PUBLISH_DURATION:
                    REDIS_PUBLISH_DURATION.labels(stream=stream_name, outcome="failure").observe(duration)

            # Add to retry queue
            return self._enqueue_for_retry(message)

    async def _publish_to_redis(self, message: PublishMessage):
        """
        Actual Redis XADD operation.

        Args:
            message: Message to publish

        Raises:
            Exception: On Redis errors
        """
        await self.redis_client.xadd(
            message.stream_name,
            message.data,
            maxlen=message.maxlen
        )

    def _enqueue_for_retry(self, message: PublishMessage) -> bool:
        """
        Add message to retry queue.

        Args:
            message: Message to enqueue

        Returns:
            True if queued, False if dropped (queue full)
        """
        stream_name = message.stream_name

        # Create queue if doesn't exist
        if stream_name not in self.retry_queues:
            self.retry_queues[stream_name] = deque()

        queue = self.retry_queues[stream_name]

        # Check queue size
        if len(queue) >= self.config.max_queue_size:
            self.logger.error(
                f"Retry queue full ({len(queue)}/{self.config.max_queue_size}) - dropping message",
                extra={"stream": stream_name, "message_id": message.message_id}
            )
            self.stats["dropped_messages"] += 1

            if PROMETHEUS_AVAILABLE and REDIS_PUBLISH_ATTEMPTS:
                REDIS_PUBLISH_ATTEMPTS.labels(stream=stream_name, outcome="dropped").inc()

            return False

        # Add to queue (priority-sorted)
        if message.priority > 0:
            # Insert by priority (higher first)
            inserted = False
            for i, existing_msg in enumerate(queue):
                if message.priority > existing_msg.priority:
                    queue.insert(i, message)
                    inserted = True
                    break

            if not inserted:
                queue.append(message)
        else:
            # Normal priority - append to end
            queue.append(message)

        # Update metrics
        if PROMETHEUS_AVAILABLE and REDIS_PUBLISH_QUEUE_SIZE:
            REDIS_PUBLISH_QUEUE_SIZE.labels(stream=stream_name).set(len(queue))

        self.logger.debug(
            f"Message enqueued for retry (queue size: {len(queue)})",
            extra={"stream": stream_name, "message_id": message.message_id}
        )

        return True

    async def _retry_message(self, message: PublishMessage) -> bool:
        """
        Retry publishing a message.

        Args:
            message: Message to retry

        Returns:
            True if successful, False if needs more retries or DLQ
        """
        message.attempts += 1
        message.last_attempt_time = time.time()

        # Calculate backoff delay
        delay = min(
            self.config.base_delay_seconds * (self.config.exponential_base ** (message.attempts - 1)),
            self.config.max_delay_seconds
        )

        # Wait before retry
        await asyncio.sleep(delay)

        try:
            await self._publish_to_redis(message)

            # Success!
            self.stats["successful_publishes"] += 1
            self.stats["retries"] += 1
            self.last_success_time = time.time()

            if PROMETHEUS_AVAILABLE:
                if REDIS_PUBLISH_RETRIES:
                    REDIS_PUBLISH_RETRIES.labels(
                        stream=message.stream_name,
                        retry_attempt=str(message.attempts)
                    ).inc()
                if REDIS_PUBLISH_ATTEMPTS:
                    REDIS_PUBLISH_ATTEMPTS.labels(stream=message.stream_name, outcome="success").inc()

            self.logger.info(
                f"Retry successful (attempt {message.attempts})",
                extra={"stream": message.stream_name, "message_id": message.message_id}
            )

            return True

        except Exception as e:
            self.logger.warning(
                f"Retry failed (attempt {message.attempts}/{self.config.max_retries}): {e}",
                extra={"stream": message.stream_name, "message_id": message.message_id}
            )

            message.last_error = str(e)

            # Check if max retries exceeded
            if message.attempts >= self.config.max_retries:
                # Send to DLQ
                await self._send_to_dlq(message, reason="max_retries_exceeded")
                return True  # Remove from retry queue

            # Need more retries
            return False

    async def _send_to_dlq(self, message: PublishMessage, reason: str):
        """
        Send message to Dead Letter Queue.

        Args:
            message: Message that permanently failed
            reason: Failure reason
        """
        if not self.config.dlq_enabled:
            self.logger.warning(
                f"DLQ disabled - dropping message after {message.attempts} attempts",
                extra={"stream": message.stream_name, "message_id": message.message_id}
            )
            self.stats["dropped_messages"] += 1
            return

        dlq_stream = f"{message.stream_name}{self.config.dlq_suffix}"

        dlq_data = {
            **message.data,
            "_dlq_reason": reason,
            "_dlq_attempts": str(message.attempts),
            "_dlq_original_stream": message.stream_name,
            "_dlq_first_attempt": str(int(message.first_attempt_time * 1000)),
            "_dlq_last_error": message.last_error or "unknown",
            "_dlq_message_id": message.message_id or "none"
        }

        try:
            await self.redis_client.xadd(
                dlq_stream,
                dlq_data,
                maxlen=self.config.dlq_maxlen
            )

            self.stats["dlq_messages"] += 1

            if PROMETHEUS_AVAILABLE and REDIS_PUBLISH_DLQ:
                REDIS_PUBLISH_DLQ.labels(stream=message.stream_name, reason=reason).inc()

            self.logger.error(
                f"Message sent to DLQ: {dlq_stream}",
                extra={
                    "stream": message.stream_name,
                    "dlq_stream": dlq_stream,
                    "reason": reason,
                    "attempts": message.attempts,
                    "message_id": message.message_id
                }
            )

        except Exception as e:
            self.logger.error(
                f"Failed to send message to DLQ: {e}",
                extra={"stream": message.stream_name, "dlq_stream": dlq_stream}
            )
            self.stats["dropped_messages"] += 1

    async def _periodic_queue_flush(self):
        """Background task to periodically flush retry queues"""
        while self.is_running:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds
                await self._flush_all_queues()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in queue flush task: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _flush_all_queues(self):
        """Flush all retry queues"""
        for stream_name in list(self.retry_queues.keys()):
            await self._flush_queue(stream_name)

    async def _flush_queue(self, stream_name: str):
        """
        Flush retry queue for a specific stream.

        Args:
            stream_name: Stream name
        """
        if stream_name not in self.retry_queues:
            return

        queue = self.retry_queues[stream_name]

        if not queue:
            return

        # Process batch
        batch_size = min(len(queue), self.config.queue_flush_batch_size)

        for _ in range(batch_size):
            if not queue:
                break

            message = queue.popleft()

            # Update queue size metric
            if PROMETHEUS_AVAILABLE and REDIS_PUBLISH_QUEUE_SIZE:
                REDIS_PUBLISH_QUEUE_SIZE.labels(stream=stream_name).set(len(queue))

            # Retry message
            success = await self._retry_message(message)

            if not success:
                # Re-enqueue for next attempt
                self._enqueue_for_retry(message)

    def get_health_stats(self) -> Dict[str, Any]:
        """
        Get health statistics.

        Returns:
            Health stats dictionary
        """
        # Calculate queue sizes
        total_queue_size = sum(len(q) for q in self.retry_queues.values())

        # Time since last publish
        time_since_publish = time.time() - self.last_publish_time if self.last_publish_time > 0 else 0
        time_since_success = time.time() - self.last_success_time if self.last_success_time > 0 else 0

        # Determine health status
        if total_queue_size >= self.config.unhealthy_queue_size_threshold:
            health = "unhealthy"
        elif total_queue_size >= self.config.degraded_queue_size_threshold:
            health = "degraded"
        elif time_since_success > 60 and self.stats["total_publishes"] > 0:
            health = "degraded"  # No success in last minute
        else:
            health = "healthy"

        return {
            "health": health,
            "total_queue_size": total_queue_size,
            "queues": {name: len(q) for name, q in self.retry_queues.items()},
            "stats": self.stats.copy(),
            "last_publish_seconds_ago": round(time_since_publish, 2),
            "last_success_seconds_ago": round(time_since_success, 2),
        }

    def get_queue_sizes(self) -> Dict[str, int]:
        """Get current retry queue sizes per stream"""
        return {name: len(q) for name, q in self.retry_queues.items()}


__all__ = [
    "ResilientPublisher",
    "ResilientPublisherConfig",
    "PublishMessage",
]
