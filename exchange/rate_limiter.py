"""
Per-Exchange Token Bucket Rate Limiter
=======================================

Prevents REST API rate limit exhaustion by tracking a per-exchange
token budget. Each exchange gets an independent bucket with configurable
capacity and refill rate.

Usage:
    limiter = ExchangeRateLimiter(capacity=10, refill_per_second=1.0)
    if await limiter.acquire("kraken"):
        await place_order(...)
    else:
        logger.warning("Rate limit budget exhausted for kraken")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ExchangeRateLimiter:
    """Token bucket rate limiter per exchange."""

    def __init__(
        self,
        capacity: int = 0,
        refill_per_second: float = 0.0,
        enabled: bool = True,
    ) -> None:
        self._capacity = capacity if capacity > 0 else int(
            os.getenv("RATE_LIMIT_TOKENS_PER_EXCHANGE", "10")
        )
        self._refill_per_second = refill_per_second if refill_per_second > 0 else float(
            os.getenv("RATE_LIMIT_REFILL_PER_SECOND", "1.0")
        )
        self._enabled = enabled

        # Per-exchange bucket state
        self._tokens: Dict[str, float] = {}
        self._last_refill: Dict[str, float] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_lock(self, exchange_id: str) -> asyncio.Lock:
        """Get or create per-exchange lock."""
        if exchange_id not in self._locks:
            self._locks[exchange_id] = asyncio.Lock()
        return self._locks[exchange_id]

    def _refill(self, exchange_id: str) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        last = self._last_refill.get(exchange_id, now)
        elapsed = now - last

        if elapsed > 0:
            current = self._tokens.get(exchange_id, float(self._capacity))
            refilled = current + elapsed * self._refill_per_second
            self._tokens[exchange_id] = min(refilled, float(self._capacity))
            self._last_refill[exchange_id] = now

    async def acquire(self, exchange_id: str) -> bool:
        """
        Attempt to acquire a rate limit token for an exchange.

        Args:
            exchange_id: Exchange identifier (e.g. "kraken")

        Returns:
            True if token acquired, False if budget exhausted.
        """
        if not self._enabled:
            return True

        lock = self._get_lock(exchange_id)
        async with lock:
            # Initialize bucket on first use
            if exchange_id not in self._tokens:
                self._tokens[exchange_id] = float(self._capacity)
                self._last_refill[exchange_id] = time.time()

            self._refill(exchange_id)

            if self._tokens[exchange_id] >= 1.0:
                self._tokens[exchange_id] -= 1.0
                return True

            logger.warning(
                "Rate limit budget exhausted for %s, skipping order — will retry next tick",
                exchange_id,
            )
            return False

    def get_headroom(self, exchange_id: str) -> float:
        """Get remaining token headroom as fraction (0.0-1.0)."""
        self._refill(exchange_id)
        current = self._tokens.get(exchange_id, float(self._capacity))
        return current / self._capacity if self._capacity > 0 else 1.0

    def get_all_headroom(self) -> Dict[str, float]:
        """Get headroom for all tracked exchanges."""
        result: Dict[str, float] = {}
        for exchange_id in self._tokens:
            result[exchange_id] = self.get_headroom(exchange_id)
        return result

    def get_metrics(self) -> Dict[str, Any]:
        """Get rate limiter metrics for ops endpoints."""
        return {
            "enabled": self._enabled,
            "capacity": self._capacity,
            "refill_per_second": self._refill_per_second,
            "headroom": self.get_all_headroom(),
        }
