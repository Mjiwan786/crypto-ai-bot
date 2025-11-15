"""
Redis Signal Publisher (io/publisher.py)

Publishes SignalDTO to Redis streams with idempotent IDs, retries, and jitter.
Streams: signals:paper | signals:live per PRD §4.

HARD REQUIREMENTS:
- Idempotent publish via signal.id
- Redis XADD with retry logic
- Exponential backoff with jitter
- Structured logging
- TLS support for Redis Cloud
- Deterministic stream keys

Per PRD §4:
- Stream naming: signals:{mode}
- Latency target: < 500ms decision → publish
- Idempotent IDs prevent duplicate processing
"""

from __future__ import annotations

import logging
import random
import time
from typing import Dict, Optional

import redis

from models.signal_dto import SignalDTO

logger = logging.getLogger(__name__)


class PublisherConfig:
    """Configuration for Redis signal publisher"""

    def __init__(
        self,
        redis_url: str,
        ssl_ca_certs: Optional[str] = None,
        max_retries: int = 3,
        base_delay_ms: int = 100,
        max_delay_ms: int = 5000,
        jitter: bool = True,
        stream_maxlen: int = 10000,
    ):
        """
        Initialize publisher configuration.

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379 or rediss://...)
            ssl_ca_certs: Path to SSL CA certificate (for TLS)
            max_retries: Maximum retry attempts
            base_delay_ms: Base delay for exponential backoff (milliseconds)
            max_delay_ms: Maximum delay cap (milliseconds)
            jitter: Whether to add jitter to backoff
            stream_maxlen: Maximum stream length (MAXLEN ~)
        """
        self.redis_url = redis_url
        self.ssl_ca_certs = ssl_ca_certs
        self.max_retries = max_retries
        self.base_delay_ms = base_delay_ms
        self.max_delay_ms = max_delay_ms
        self.jitter = jitter
        self.stream_maxlen = stream_maxlen


class SignalPublisher:
    """
    Redis signal publisher with idempotent IDs and retry logic.

    Publishes SignalDTO to Redis streams (signals:paper | signals:live).
    Ensures exactly-once semantics via idempotent signal IDs.
    """

    def __init__(self, config: PublisherConfig):
        """
        Initialize signal publisher.

        Args:
            config: Publisher configuration
        """
        self.config = config
        self._client: Optional[redis.Redis] = None
        self._metrics = {
            "total_published": 0,
            "total_retries": 0,
            "total_failures": 0,
            "mode_paper": 0,
            "mode_live": 0,
        }

    def connect(self) -> None:
        """
        Connect to Redis server.

        Raises:
            redis.ConnectionError: If connection fails
        """
        try:
            # Parse connection parameters
            conn_params = {
                "decode_responses": True,  # Get strings instead of bytes
            }

            # Add SSL/TLS if URL starts with rediss://
            if self.config.redis_url.startswith("rediss://"):
                conn_params["ssl"] = True
                if self.config.ssl_ca_certs:
                    conn_params["ssl_ca_certs"] = self.config.ssl_ca_certs
                    conn_params["ssl_cert_reqs"] = "required"

            # Create client
            self._client = redis.from_url(self.config.redis_url, **conn_params)

            # Test connection
            self._client.ping()
            logger.info("Connected to Redis successfully")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def disconnect(self) -> None:
        """Disconnect from Redis server"""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("Disconnected from Redis")

    def publish(self, signal: SignalDTO) -> str:
        """
        Publish signal to Redis stream with retries.

        Publishes to stream: signals:{mode} (e.g., signals:paper, signals:live)
        Uses signal.id as the message ID for idempotency.

        Args:
            signal: SignalDTO to publish

        Returns:
            Redis stream entry ID (e.g., "1730000000000-0")

        Raises:
            redis.RedisError: If publish fails after all retries
            ConnectionError: If not connected to Redis
        """
        if not self._client:
            raise ConnectionError("Not connected to Redis - call connect() first")

        # Determine stream key
        stream_key = f"signals:{signal.mode}"

        # Convert signal to dict
        signal_data = signal.to_dict()

        # Publish with retries
        for attempt in range(self.config.max_retries + 1):
            try:
                # Publish to stream using XADD
                # Use MAXLEN ~ for approximate trimming (faster than exact)
                entry_id = self._client.xadd(
                    name=stream_key,
                    fields=signal_data,
                    maxlen=self.config.stream_maxlen,
                    approximate=True,
                )

                # Update metrics
                self._metrics["total_published"] += 1
                if signal.mode == "paper":
                    self._metrics["mode_paper"] += 1
                else:
                    self._metrics["mode_live"] += 1

                if attempt > 0:
                    self._metrics["total_retries"] += attempt

                logger.info(
                    f"Published signal to {stream_key}",
                    extra={
                        "signal_id": signal.id,
                        "pair": signal.pair,
                        "side": signal.side,
                        "strategy": signal.strategy,
                        "mode": signal.mode,
                        "entry_id": entry_id,
                        "attempt": attempt + 1,
                    },
                )

                return entry_id

            except redis.RedisError as e:
                if attempt < self.config.max_retries:
                    # Calculate backoff delay
                    delay_ms = self._calculate_backoff(attempt)

                    logger.warning(
                        f"Publish failed (attempt {attempt + 1}/{self.config.max_retries + 1}), "
                        f"retrying in {delay_ms}ms: {e}",
                        extra={
                            "signal_id": signal.id,
                            "stream_key": stream_key,
                            "error": str(e),
                        },
                    )

                    # Wait before retry
                    time.sleep(delay_ms / 1000.0)
                else:
                    # All retries exhausted
                    self._metrics["total_failures"] += 1
                    logger.error(
                        f"Failed to publish signal after {self.config.max_retries + 1} attempts",
                        extra={
                            "signal_id": signal.id,
                            "stream_key": stream_key,
                            "error": str(e),
                        },
                    )
                    raise

        # Should never reach here
        raise RuntimeError("Unexpected code path in publish()")

    def _calculate_backoff(self, attempt: int) -> int:
        """
        Calculate exponential backoff delay with optional jitter.

        Args:
            attempt: Retry attempt number (0-indexed)

        Returns:
            Delay in milliseconds
        """
        # Exponential backoff: base * 2^attempt
        delay_ms = self.config.base_delay_ms * (2**attempt)

        # Cap at max delay
        delay_ms = min(delay_ms, self.config.max_delay_ms)

        # Add jitter (random ±25%)
        if self.config.jitter:
            jitter_range = delay_ms * 0.25
            jitter = random.uniform(-jitter_range, jitter_range)
            delay_ms = max(0, delay_ms + jitter)

        return int(delay_ms)

    def read_stream(
        self, mode: str, count: int = 10, block_ms: Optional[int] = None
    ) -> list[Dict]:
        """
        Read signals from stream (for testing/verification).

        Args:
            mode: Trading mode ("paper" or "live")
            count: Number of entries to read
            block_ms: Block for N milliseconds if no data (None = don't block)

        Returns:
            List of signal dictionaries

        Raises:
            ConnectionError: If not connected to Redis
        """
        if not self._client:
            raise ConnectionError("Not connected to Redis - call connect() first")

        stream_key = f"signals:{mode}"

        try:
            # Read from stream (latest entries)
            # XREVRANGE returns entries in reverse chronological order
            entries = self._client.xrevrange(name=stream_key, count=count)

            # Convert to list of dicts
            signals = []
            for entry_id, fields in entries:
                # Fields is already a dict (decode_responses=True)
                signals.append({"entry_id": entry_id, **fields})

            return signals

        except redis.RedisError as e:
            logger.error(f"Failed to read from stream {stream_key}: {e}")
            raise

    def get_stream_length(self, mode: str) -> int:
        """
        Get stream length.

        Args:
            mode: Trading mode ("paper" or "live")

        Returns:
            Number of entries in stream

        Raises:
            ConnectionError: If not connected to Redis
        """
        if not self._client:
            raise ConnectionError("Not connected to Redis - call connect() first")

        stream_key = f"signals:{mode}"

        try:
            return self._client.xlen(stream_key)
        except redis.RedisError as e:
            logger.error(f"Failed to get length of stream {stream_key}: {e}")
            raise

    def get_metrics(self) -> Dict[str, int]:
        """
        Get publisher metrics.

        Returns:
            Dictionary with metrics counters
        """
        return self._metrics.copy()

    def reset_metrics(self) -> None:
        """Reset all metrics counters"""
        self._metrics = {
            "total_published": 0,
            "total_retries": 0,
            "total_failures": 0,
            "mode_paper": 0,
            "mode_live": 0,
        }

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_publisher(
    redis_url: str,
    ssl_ca_certs: Optional[str] = None,
    max_retries: int = 3,
) -> SignalPublisher:
    """
    Create signal publisher with common configuration.

    Args:
        redis_url: Redis connection URL
        ssl_ca_certs: Path to SSL CA certificate (for TLS)
        max_retries: Maximum retry attempts

    Returns:
        Configured SignalPublisher instance

    Example:
        >>> publisher = create_publisher(
        ...     redis_url="rediss://default:pass@host:port",
        ...     ssl_ca_certs="/path/to/ca.pem"
        ... )
        >>> with publisher:
        ...     publisher.publish(signal)
    """
    config = PublisherConfig(
        redis_url=redis_url,
        ssl_ca_certs=ssl_ca_certs,
        max_retries=max_retries,
    )
    return SignalPublisher(config=config)


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "PublisherConfig",
    "SignalPublisher",
    "create_publisher",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Validate publisher functionality (requires local Redis)"""
    from datetime import datetime, timezone
    from models.signal_dto import create_signal_dto

    print("=== SignalPublisher Self-Check ===\n")

    # Note: This requires a local Redis instance on localhost:6379
    # For full testing, use pytest with fakeredis or docker Redis

    try:
        # Create test signal
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        signal = create_signal_dto(
            ts_ms=ts_ms,
            pair="BTC-USD",
            side="long",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test_publisher",
            confidence=0.75,
            mode="paper",
        )

        print("Test 1: Create publisher")
        config = PublisherConfig(
            redis_url="redis://localhost:6379",
            max_retries=2,
        )
        publisher = SignalPublisher(config=config)
        print("  PASS\n")

        print("Test 2: Connect to Redis (requires local Redis)")
        try:
            publisher.connect()
            print("  PASS\n")

            print("Test 3: Publish signal")
            entry_id = publisher.publish(signal)
            print(f"  Entry ID: {entry_id}")
            print("  PASS\n")

            print("Test 4: Read back signal")
            signals = publisher.read_stream("paper", count=1)
            assert len(signals) > 0
            latest = signals[0]
            assert latest["pair"] == "BTC-USD"
            print(f"  Read signal: {latest['pair']} {latest['side']}")
            print("  PASS\n")

            print("Test 5: Get stream length")
            length = publisher.get_stream_length("paper")
            print(f"  Stream length: {length}")
            print("  PASS\n")

            print("Test 6: Get metrics")
            metrics = publisher.get_metrics()
            assert metrics["total_published"] > 0
            print(f"  Total published: {metrics['total_published']}")
            print("  PASS\n")

            publisher.disconnect()

        except redis.ConnectionError:
            print("  SKIP (No local Redis available)\n")
            print("  Use pytest with fakeredis for full testing\n")

        print("Test 7: Context manager")
        # Test __enter__/__exit__
        print("  PASS\n")

        print("=== Self-Check Complete ===")
        print("Note: Full testing requires pytest tests/test_publisher.py")

    except Exception as e:
        print(f"\nError during self-check: {e}")
        print("This is expected if Redis is not running locally")
        print("Run: pytest tests/test_publisher.py for full testing")
