"""
Rate Limiter & Backpressure Module - E1

Provides throughput controls to prevent flooding Redis or API consumers
when adding new trading pairs to the system.

Features:
- Token bucket algorithm for smooth rate limiting
- Per-pair rate controls (prevents single pair from dominating)
- Global throughput limits (overall system protection)
- Backpressure queue with maximum size
- Configurable via environment variables
- Safe defaults that preserve current behavior
"""

import asyncio
import time
import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """
    Token bucket rate limiter implementation.

    Allows bursts up to bucket capacity while maintaining
    average rate over time.
    """
    capacity: float  # Max tokens (allows small bursts)
    refill_rate: float  # Tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self):
        self.tokens = self.capacity
        self.last_refill = time.time()

    def _refill(self):
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill

        # Add tokens based on elapsed time
        self.tokens = min(
            self.capacity,
            self.tokens + (elapsed * self.refill_rate)
        )
        self.last_refill = now

    def try_consume(self, tokens: float = 1.0) -> bool:
        """
        Try to consume tokens. Returns True if successful.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were available and consumed, False otherwise
        """
        self._refill()

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    async def consume(self, tokens: float = 1.0, timeout: Optional[float] = None) -> bool:
        """
        Consume tokens, waiting if necessary.

        Args:
            tokens: Number of tokens to consume
            timeout: Maximum time to wait (seconds), None = wait forever

        Returns:
            True if successful, False if timeout
        """
        start_time = time.time()

        while True:
            if self.try_consume(tokens):
                return True

            # Check timeout
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    return False

            # Sleep briefly before retry
            await asyncio.sleep(0.01)  # 10ms check interval

    def get_available_tokens(self) -> float:
        """Get current token count"""
        self._refill()
        return self.tokens


class RateLimiter:
    """
    Multi-level rate limiter with backpressure.

    Provides:
    - Global rate limiting (overall throughput)
    - Per-pair rate limiting (prevent single pair dominance)
    - Backpressure queue (prevents unbounded memory growth)

    Environment Variables:
    - RATE_LIMIT_GLOBAL_PER_SEC: Global tokens/sec (default: 10.0)
    - RATE_LIMIT_PER_PAIR_PER_SEC: Per-pair tokens/sec (default: 3.0)
    - RATE_LIMIT_BURST_MULTIPLIER: Burst capacity multiplier (default: 2.0)
    - RATE_LIMIT_QUEUE_MAX_SIZE: Max queued items (default: 1000)
    - RATE_LIMIT_ENABLED: Enable/disable rate limiting (default: true)
    """

    def __init__(
        self,
        global_rate: Optional[float] = None,
        per_pair_rate: Optional[float] = None,
        burst_multiplier: Optional[float] = None,
        queue_max_size: Optional[int] = None,
        enabled: Optional[bool] = None
    ):
        """
        Initialize rate limiter with configurable limits.

        Args:
            global_rate: Global tokens/sec (overrides env)
            per_pair_rate: Per-pair tokens/sec (overrides env)
            burst_multiplier: Burst capacity = rate * multiplier
            queue_max_size: Maximum queued items
            enabled: Enable/disable rate limiting
        """
        # Load configuration from environment with safe defaults
        self.enabled = enabled if enabled is not None else \
            os.getenv('RATE_LIMIT_ENABLED', 'true').lower() != 'false'

        self.global_rate = global_rate if global_rate is not None else \
            float(os.getenv('RATE_LIMIT_GLOBAL_PER_SEC', '10.0'))

        self.per_pair_rate = per_pair_rate if per_pair_rate is not None else \
            float(os.getenv('RATE_LIMIT_PER_PAIR_PER_SEC', '3.0'))

        self.burst_multiplier = burst_multiplier if burst_multiplier is not None else \
            float(os.getenv('RATE_LIMIT_BURST_MULTIPLIER', '2.0'))

        self.queue_max_size = queue_max_size if queue_max_size is not None else \
            int(os.getenv('RATE_LIMIT_QUEUE_MAX_SIZE', '1000'))

        # Initialize token buckets
        self.global_bucket = TokenBucket(
            capacity=self.global_rate * self.burst_multiplier,
            refill_rate=self.global_rate
        )

        # Per-pair buckets (created on demand)
        self.pair_buckets: Dict[str, TokenBucket] = {}

        # Backpressure queue
        self.queue: deque = deque(maxlen=self.queue_max_size)

        # Statistics
        self.stats = {
            'total_allowed': 0,
            'total_rejected': 0,
            'total_queued': 0,
            'queue_drops': 0
        }

        logger.info(
            f"RateLimiter initialized: enabled={self.enabled}, "
            f"global={self.global_rate}/s, per_pair={self.per_pair_rate}/s, "
            f"burst={self.burst_multiplier}x, queue_max={self.queue_max_size}"
        )

    def _get_pair_bucket(self, pair: str) -> TokenBucket:
        """Get or create token bucket for specific pair"""
        if pair not in self.pair_buckets:
            self.pair_buckets[pair] = TokenBucket(
                capacity=self.per_pair_rate * self.burst_multiplier,
                refill_rate=self.per_pair_rate
            )
        return self.pair_buckets[pair]

    async def acquire(
        self,
        pair: str,
        tokens: float = 1.0,
        timeout: Optional[float] = None
    ) -> bool:
        """
        Acquire rate limit permission for publishing.

        Args:
            pair: Trading pair (e.g., 'BTC-USD')
            tokens: Number of tokens to consume (default: 1.0)
            timeout: Maximum wait time (seconds), None = wait forever

        Returns:
            True if permission granted, False if rejected/timeout
        """
        # If disabled, always allow
        if not self.enabled:
            self.stats['total_allowed'] += 1
            return True

        # Try to acquire from both global and per-pair buckets
        pair_bucket = self._get_pair_bucket(pair)

        # Try immediate acquisition (no waiting)
        if self.global_bucket.try_consume(tokens) and pair_bucket.try_consume(tokens):
            self.stats['total_allowed'] += 1
            return True

        # If immediate acquisition failed, try with waiting
        global_ok = await self.global_bucket.consume(tokens, timeout=timeout)
        if not global_ok:
            self.stats['total_rejected'] += 1
            logger.warning(f"Global rate limit timeout for {pair}")
            return False

        pair_ok = await pair_bucket.consume(tokens, timeout=timeout)
        if not pair_ok:
            self.stats['total_rejected'] += 1
            logger.warning(f"Per-pair rate limit timeout for {pair}")
            return False

        self.stats['total_allowed'] += 1
        return True

    def try_enqueue(self, item: Any) -> bool:
        """
        Try to add item to backpressure queue.

        Args:
            item: Item to queue

        Returns:
            True if enqueued, False if queue full (item dropped)
        """
        if len(self.queue) >= self.queue_max_size:
            self.stats['queue_drops'] += 1
            logger.warning(f"Backpressure queue full, dropping item")
            return False

        self.queue.append(item)
        self.stats['total_queued'] += 1
        return True

    def dequeue(self) -> Optional[Any]:
        """
        Remove and return item from queue.

        Returns:
            Queued item or None if empty
        """
        try:
            return self.queue.popleft()
        except IndexError:
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics"""
        return {
            'enabled': self.enabled,
            'config': {
                'global_rate_per_sec': self.global_rate,
                'per_pair_rate_per_sec': self.per_pair_rate,
                'burst_multiplier': self.burst_multiplier,
                'queue_max_size': self.queue_max_size
            },
            'stats': self.stats.copy(),
            'queue_size': len(self.queue),
            'global_tokens_available': self.global_bucket.get_available_tokens(),
            'active_pairs': len(self.pair_buckets),
            'pair_tokens': {
                pair: bucket.get_available_tokens()
                for pair, bucket in self.pair_buckets.items()
            }
        }

    def reset_stats(self):
        """Reset statistics counters"""
        self.stats = {
            'total_allowed': 0,
            'total_rejected': 0,
            'total_queued': 0,
            'queue_drops': 0
        }


# Singleton instance for convenience
_default_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create default rate limiter instance"""
    global _default_rate_limiter

    if _default_rate_limiter is None:
        _default_rate_limiter = RateLimiter()

    return _default_rate_limiter
