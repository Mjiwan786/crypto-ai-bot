"""
Tests for per-exchange token bucket rate limiter.
"""

import asyncio
import time

import pytest

from exchange.rate_limiter import ExchangeRateLimiter


@pytest.fixture
def limiter() -> ExchangeRateLimiter:
    return ExchangeRateLimiter(capacity=3, refill_per_second=1.0, enabled=True)


class TestExchangeRateLimiter:
    """Test token bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_acquire_within_capacity(self, limiter: ExchangeRateLimiter) -> None:
        """acquire() returns True for first N=capacity calls."""
        assert await limiter.acquire("kraken") is True
        assert await limiter.acquire("kraken") is True
        assert await limiter.acquire("kraken") is True

    @pytest.mark.asyncio
    async def test_acquire_exhausted(self, limiter: ExchangeRateLimiter) -> None:
        """acquire() returns False on N+1 call."""
        for _ in range(3):
            await limiter.acquire("kraken")
        assert await limiter.acquire("kraken") is False

    @pytest.mark.asyncio
    async def test_refill_after_wait(self) -> None:
        """After 1s simulated wait, bucket has refilled by refill_rate."""
        limiter = ExchangeRateLimiter(capacity=2, refill_per_second=10.0, enabled=True)
        # Exhaust bucket
        await limiter.acquire("kraken")
        await limiter.acquire("kraken")
        assert await limiter.acquire("kraken") is False

        # Wait 0.15s — should refill ~1.5 tokens at 10/s
        await asyncio.sleep(0.15)
        assert await limiter.acquire("kraken") is True

    @pytest.mark.asyncio
    async def test_separate_buckets_per_exchange(self, limiter: ExchangeRateLimiter) -> None:
        """Each exchange has independent budget."""
        for _ in range(3):
            await limiter.acquire("kraken")
        assert await limiter.acquire("kraken") is False
        # Binance should still have full budget
        assert await limiter.acquire("binance") is True

    @pytest.mark.asyncio
    async def test_disabled_always_allows(self) -> None:
        """When disabled, acquire always returns True."""
        limiter = ExchangeRateLimiter(capacity=1, refill_per_second=0.0, enabled=False)
        for _ in range(100):
            assert await limiter.acquire("kraken") is True

    def test_get_headroom(self, limiter: ExchangeRateLimiter) -> None:
        """Headroom reports fraction of capacity remaining."""
        headroom = limiter.get_headroom("kraken")
        assert headroom == 1.0  # full bucket

    def test_get_all_headroom_empty(self, limiter: ExchangeRateLimiter) -> None:
        """get_all_headroom returns empty dict when no exchanges tracked."""
        assert limiter.get_all_headroom() == {}

    @pytest.mark.asyncio
    async def test_get_all_headroom_after_use(self, limiter: ExchangeRateLimiter) -> None:
        await limiter.acquire("kraken")
        headroom = limiter.get_all_headroom()
        assert "kraken" in headroom
        assert 0.0 < headroom["kraken"] < 1.0

    def test_get_metrics(self, limiter: ExchangeRateLimiter) -> None:
        metrics = limiter.get_metrics()
        assert metrics["enabled"] is True
        assert metrics["capacity"] == 3
        assert metrics["refill_per_second"] == 1.0
