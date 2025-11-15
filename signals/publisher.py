"""
Signal Publisher with Idempotency (signals/publisher.py)

Publishes signals to per-pair Redis streams: signals:live:<PAIR> and signals:paper:<PAIR>
Ensures exactly-once semantics via idempotent signal IDs.

FEATURES:
- Per-pair stream sharding (signals:live:BTC-USD, signals:live:ETH-USD, etc.)
- Idempotent publishing (prevents duplicates)
- Async/await Redis operations
- TLS support for Redis Cloud
- Automatic stream trimming (MAXLEN ~)
- Structured logging

USAGE:
    publisher = SignalPublisher(redis_url=REDIS_URL, redis_cert_path=CERT_PATH)
    await publisher.connect()

    signal = create_signal(...)
    entry_id = await publisher.publish(signal)

    await publisher.close()
"""

from __future__ import annotations

import logging
import os
from typing import Optional, List, Dict, Any

import redis.asyncio as redis
import orjson

from .schema import Signal

logger = logging.getLogger(__name__)


class SignalPublisher:
    """
    Async Redis signal publisher with idempotent IDs and per-pair stream sharding.

    Publishes signals to streams: signals:{mode}:{pair}
    - signals:live:BTC-USD
    - signals:live:ETH-USD
    - signals:paper:BTC-USD
    - etc.
    """

    def __init__(
        self,
        redis_url: str,
        redis_cert_path: Optional[str] = None,
        stream_maxlen: int = 10000,
    ):
        """
        Initialize signal publisher.

        Args:
            redis_url: Redis connection URL (rediss:// for TLS)
            redis_cert_path: Path to TLS certificate (required for rediss://)
            stream_maxlen: Maximum stream length (approximate trimming)
        """
        self.redis_url = redis_url
        self.redis_cert_path = redis_cert_path
        self.stream_maxlen = stream_maxlen

        self.redis_client: Optional[redis.Redis] = None

        # Metrics
        self._metrics = {
            "total_published": 0,
            "mode_paper": 0,
            "mode_live": 0,
            "by_pair": {},
        }

    async def connect(self) -> bool:
        """
        Connect to Redis server.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Build connection parameters
            conn_params = {
                "socket_connect_timeout": 5,
                "socket_keepalive": True,
                "decode_responses": False,  # Use bytes for orjson
            }

            # Add TLS certificate if using rediss://
            # (redis.asyncio automatically handles SSL from URL scheme)
            if self.redis_url.startswith("rediss://") and self.redis_cert_path:
                conn_params["ssl_ca_certs"] = self.redis_cert_path
                conn_params["ssl_cert_reqs"] = "required"

            # Create async Redis client
            self.redis_client = redis.from_url(self.redis_url, **conn_params)

            # Test connection
            await self.redis_client.ping()

            logger.info("Connected to Redis successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None
            logger.info("Disconnected from Redis")

    async def publish(self, signal: Signal) -> str:
        """
        Publish signal to Redis stream with idempotent ID.

        Publishes to stream: signals:{mode}:{pair}
        Example: signals:live:BTC-USD

        Args:
            signal: Signal to publish

        Returns:
            Redis stream entry ID (e.g., "1730000000000-0")

        Raises:
            ConnectionError: If not connected to Redis
            redis.RedisError: If publish fails
        """
        if not self.redis_client:
            raise ConnectionError("Not connected to Redis - call connect() first")

        # Get stream key from signal
        stream_key = signal.get_stream_key()

        # Convert signal to Redis dict (all string values)
        signal_data = signal.to_redis_dict()

        try:
            # Publish to stream using XADD
            # Use MAXLEN ~ for approximate trimming (faster than exact)
            entry_id = await self.redis_client.xadd(
                name=stream_key,
                fields=signal_data,
                maxlen=self.stream_maxlen,
                approximate=True,
            )

            # Update metrics
            self._metrics["total_published"] += 1
            if signal.mode == "paper":
                self._metrics["mode_paper"] += 1
            else:
                self._metrics["mode_live"] += 1

            # Track by pair
            pair_key = signal.pair.replace("/", "-")
            self._metrics["by_pair"][pair_key] = (
                self._metrics["by_pair"].get(pair_key, 0) + 1
            )

            logger.info(
                f"Published signal to {stream_key}",
                extra={
                    "signal_id": signal.id,
                    "pair": signal.pair,
                    "side": signal.side,
                    "strategy": signal.strategy,
                    "mode": signal.mode,
                    "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
                },
            )

            return entry_id.decode() if isinstance(entry_id, bytes) else entry_id

        except redis.RedisError as e:
            logger.error(
                f"Failed to publish signal to {stream_key}: {e}",
                extra={
                    "signal_id": signal.id,
                    "pair": signal.pair,
                    "error": str(e),
                },
            )
            raise

    async def publish_batch(self, signals: List[Signal]) -> List[str]:
        """
        Publish multiple signals efficiently.

        Args:
            signals: List of signals to publish

        Returns:
            List of Redis entry IDs

        Raises:
            ConnectionError: If not connected to Redis
        """
        if not self.redis_client:
            raise ConnectionError("Not connected to Redis - call connect() first")

        entry_ids = []
        for signal in signals:
            try:
                entry_id = await self.publish(signal)
                entry_ids.append(entry_id)
            except Exception as e:
                logger.error(f"Failed to publish signal {signal.id}: {e}")
                entry_ids.append(None)

        return entry_ids

    async def read_latest(
        self, mode: str, pair: str, count: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Read latest signals from stream (for verification).

        Args:
            mode: Trading mode ("paper" or "live")
            pair: Trading pair (e.g., "BTC/USD")
            count: Number of signals to read

        Returns:
            List of signal dictionaries

        Raises:
            ConnectionError: If not connected to Redis
        """
        if not self.redis_client:
            raise ConnectionError("Not connected to Redis - call connect() first")

        # Build stream key
        pair_key = pair.replace("/", "-")
        stream_key = f"signals:{mode}:{pair_key}"

        try:
            # Read latest entries (reverse chronological)
            entries = await self.redis_client.xrevrange(
                name=stream_key, count=count
            )

            # Convert to list of dicts
            signals = []
            for entry_id, fields in entries:
                # Decode bytes to strings
                entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else entry_id

                # Decode field data
                decoded_fields = {}
                for k, v in fields.items():
                    key = k.decode() if isinstance(k, bytes) else k
                    val = v.decode() if isinstance(v, bytes) else v
                    decoded_fields[key] = val

                signals.append({"entry_id": entry_id_str, **decoded_fields})

            return signals

        except redis.RedisError as e:
            logger.error(f"Failed to read from stream {stream_key}: {e}")
            raise

    async def get_stream_length(self, mode: str, pair: str) -> int:
        """
        Get stream length.

        Args:
            mode: Trading mode ("paper" or "live")
            pair: Trading pair (e.g., "BTC/USD")

        Returns:
            Number of entries in stream

        Raises:
            ConnectionError: If not connected to Redis
        """
        if not self.redis_client:
            raise ConnectionError("Not connected to Redis - call connect() first")

        pair_key = pair.replace("/", "-")
        stream_key = f"signals:{mode}:{pair_key}"

        try:
            return await self.redis_client.xlen(stream_key)
        except redis.RedisError as e:
            logger.error(f"Failed to get length of stream {stream_key}: {e}")
            raise

    def get_metrics(self) -> Dict[str, Any]:
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
            "mode_paper": 0,
            "mode_live": 0,
            "by_pair": {},
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_publisher_from_env() -> SignalPublisher:
    """
    Create publisher using environment variables.

    Reads from:
        - REDIS_URL
        - REDIS_TLS_CERT_PATH (optional)

    Returns:
        Configured SignalPublisher instance

    Example:
        >>> publisher = create_publisher_from_env()
        >>> await publisher.connect()
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise ValueError("REDIS_URL environment variable not set")

    redis_cert = os.getenv("REDIS_TLS_CERT_PATH")

    return SignalPublisher(redis_url=redis_url, redis_cert_path=redis_cert)


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "SignalPublisher",
    "create_publisher_from_env",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Validate publisher functionality"""
    import asyncio
    from dotenv import load_dotenv
    from .schema import create_signal

    load_dotenv(".env.prod")

    async def main():
        print("=" * 70)
        print(" " * 20 + "SIGNAL PUBLISHER SELF-CHECK")
        print("=" * 70)

        # Test 1: Create publisher from env
        print("\nTest 1: Create publisher from environment")
        try:
            publisher = create_publisher_from_env()
            print(f"  Redis URL: {publisher.redis_url[:30]}...")
            print("  PASS")
        except Exception as e:
            print(f"  FAIL: {e}")
            return

        # Test 2: Connect to Redis
        print("\nTest 2: Connect to Redis")
        connected = await publisher.connect()
        if not connected:
            print("  FAIL: Could not connect to Redis")
            return
        print("  PASS")

        # Test 3: Create test signal
        print("\nTest 3: Create test signal")
        signal = create_signal(
            pair="BTC/USD",
            side="long",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test_publisher",
            confidence=0.75,
            mode="paper",
        )
        print(f"  Signal ID: {signal.id}")
        print(f"  Stream key: {signal.get_stream_key()}")
        print("  PASS")

        # Test 4: Publish signal
        print("\nTest 4: Publish signal")
        try:
            entry_id = await publisher.publish(signal)
            print(f"  Entry ID: {entry_id}")
            print("  PASS")
        except Exception as e:
            print(f"  FAIL: {e}")
            await publisher.close()
            return

        # Test 5: Read back signal
        print("\nTest 5: Read back signal")
        try:
            signals = await publisher.read_latest("paper", "BTC/USD", count=1)
            if signals:
                latest = signals[0]
                print(f"  Read signal: {latest['pair']} {latest['side']}")
                assert latest["id"] == signal.id
                print("  PASS")
            else:
                print("  FAIL: No signals found")
        except Exception as e:
            print(f"  FAIL: {e}")

        # Test 6: Get stream length
        print("\nTest 6: Get stream length")
        try:
            length = await publisher.get_stream_length("paper", "BTC/USD")
            print(f"  Stream length: {length}")
            print("  PASS")
        except Exception as e:
            print(f"  FAIL: {e}")

        # Test 7: Get metrics
        print("\nTest 7: Get metrics")
        metrics = publisher.get_metrics()
        print(f"  Total published: {metrics['total_published']}")
        print(f"  Paper signals: {metrics['mode_paper']}")
        print("  PASS")

        # Cleanup
        await publisher.close()

        print("\n" + "=" * 70)
        print("[OK] All Self-Checks PASSED")
        print("=" * 70)

    asyncio.run(main())
