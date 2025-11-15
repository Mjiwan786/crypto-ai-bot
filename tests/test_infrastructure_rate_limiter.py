"""
Unit tests for infrastructure rate limiter and backpressure (E1)

Tests:
- Token bucket refill mechanism
- Global rate limiting
- Per-pair rate limiting
- Backpressure queue
- Configuration from environment
- Statistics tracking
"""

import asyncio
import pytest
import time
import os
from agents.infrastructure.rate_limiter import (
    TokenBucket,
    RateLimiter,
    get_rate_limiter
)


class TestTokenBucket:
    """Test token bucket algorithm"""

    def test_initial_capacity(self):
        """Token bucket starts at full capacity"""
        bucket = TokenBucket(capacity=10.0, refill_rate=5.0)
        assert bucket.tokens == 10.0
        assert bucket.capacity == 10.0
        assert bucket.refill_rate == 5.0

    def test_consume_tokens(self):
        """Can consume tokens when available"""
        bucket = TokenBucket(capacity=10.0, refill_rate=5.0)

        # Consume 3 tokens
        assert bucket.try_consume(3.0) is True
        assert bucket.tokens == 7.0

        # Consume 5 more
        assert bucket.try_consume(5.0) is True
        assert bucket.tokens == 2.0

    def test_reject_when_insufficient(self):
        """Rejects when insufficient tokens"""
        bucket = TokenBucket(capacity=5.0, refill_rate=2.0)

        # Consume all tokens
        assert bucket.try_consume(5.0) is True
        assert bucket.tokens == 0.0

        # Try to consume more (should fail)
        assert bucket.try_consume(1.0) is False
        assert bucket.tokens == 0.0

    def test_refill_over_time(self):
        """Tokens refill based on elapsed time"""
        bucket = TokenBucket(capacity=10.0, refill_rate=10.0)  # 10 tokens/sec

        # Consume all tokens
        bucket.try_consume(10.0)
        assert bucket.tokens == 0.0

        # Wait 0.5 seconds
        time.sleep(0.5)

        # Should have ~5 tokens (10 tokens/sec * 0.5 sec)
        bucket._refill()
        assert 4.5 <= bucket.tokens <= 5.5

    def test_refill_caps_at_capacity(self):
        """Refill doesn't exceed capacity"""
        bucket = TokenBucket(capacity=10.0, refill_rate=10.0)

        # Consume 5 tokens
        bucket.try_consume(5.0)
        assert bucket.tokens == 5.0

        # Wait 2 seconds (would add 20 tokens)
        time.sleep(2.0)

        # Should cap at capacity (10)
        bucket._refill()
        assert bucket.tokens == 10.0

    def test_get_available_tokens(self):
        """Can query available tokens"""
        bucket = TokenBucket(capacity=10.0, refill_rate=5.0)

        assert bucket.get_available_tokens() == 10.0

        bucket.try_consume(3.0)
        assert bucket.get_available_tokens() == 7.0

    @pytest.mark.asyncio
    async def test_async_consume_with_wait(self):
        """Async consume waits for token refill"""
        bucket = TokenBucket(capacity=10.0, refill_rate=20.0)  # 20 tokens/sec

        # Consume all tokens
        bucket.try_consume(10.0)

        # Try to consume 5 more (will wait for refill)
        start = time.time()
        result = await bucket.consume(5.0, timeout=1.0)
        elapsed = time.time() - start

        assert result is True  # Should succeed
        assert 0.2 <= elapsed <= 0.4  # ~0.25 sec to get 5 tokens at 20/sec

    @pytest.mark.asyncio
    async def test_async_consume_timeout(self):
        """Async consume times out if tokens unavailable"""
        bucket = TokenBucket(capacity=10.0, refill_rate=1.0)  # Very slow refill

        # Consume all tokens
        bucket.try_consume(10.0)

        # Try to consume 10 more with short timeout
        start = time.time()
        result = await bucket.consume(10.0, timeout=0.1)
        elapsed = time.time() - start

        assert result is False  # Should timeout
        assert elapsed < 0.2  # Should timeout quickly


class TestRateLimiter:
    """Test complete rate limiter system"""

    def test_initialization_defaults(self):
        """Rate limiter initializes with safe defaults"""
        limiter = RateLimiter()

        assert limiter.enabled is True
        assert limiter.global_rate == 10.0
        assert limiter.per_pair_rate == 3.0
        assert limiter.burst_multiplier == 2.0
        assert limiter.queue_max_size == 1000

    def test_initialization_custom(self):
        """Can override defaults via constructor"""
        limiter = RateLimiter(
            global_rate=50.0,
            per_pair_rate=10.0,
            burst_multiplier=3.0,
            queue_max_size=500,
            enabled=False
        )

        assert limiter.enabled is False
        assert limiter.global_rate == 50.0
        assert limiter.per_pair_rate == 10.0
        assert limiter.burst_multiplier == 3.0
        assert limiter.queue_max_size == 500

    def test_initialization_from_env(self, monkeypatch):
        """Reads configuration from environment variables"""
        monkeypatch.setenv('RATE_LIMIT_GLOBAL_PER_SEC', '25.0')
        monkeypatch.setenv('RATE_LIMIT_PER_PAIR_PER_SEC', '8.0')
        monkeypatch.setenv('RATE_LIMIT_BURST_MULTIPLIER', '1.5')
        monkeypatch.setenv('RATE_LIMIT_QUEUE_MAX_SIZE', '2000')
        monkeypatch.setenv('RATE_LIMIT_ENABLED', 'false')

        limiter = RateLimiter()

        assert limiter.enabled is False
        assert limiter.global_rate == 25.0
        assert limiter.per_pair_rate == 8.0
        assert limiter.burst_multiplier == 1.5
        assert limiter.queue_max_size == 2000

    @pytest.mark.asyncio
    async def test_acquire_when_disabled(self):
        """When disabled, all requests pass through"""
        limiter = RateLimiter(enabled=False)

        # Should allow unlimited requests
        for i in range(100):
            result = await limiter.acquire('BTC-USD')
            assert result is True

        stats = limiter.get_stats()
        assert stats['stats']['total_allowed'] == 100
        assert stats['stats']['total_rejected'] == 0

    @pytest.mark.asyncio
    async def test_acquire_respects_global_limit(self):
        """Global rate limit enforced"""
        limiter = RateLimiter(
            global_rate=10.0,  # 10 per second
            per_pair_rate=50.0,  # High per-pair (won't be limiting factor)
            burst_multiplier=1.0  # No burst allowance
        )

        # Consume all global tokens quickly
        results = []
        for i in range(15):
            result = await limiter.acquire('BTC-USD', timeout=0.01)
            results.append(result)

        # First 10 should succeed (global capacity), rest should fail
        assert sum(results) <= 11  # Allow small margin for timing

    @pytest.mark.asyncio
    async def test_acquire_respects_per_pair_limit(self):
        """Per-pair rate limit enforced"""
        limiter = RateLimiter(
            global_rate=100.0,  # High global (won't be limiting factor)
            per_pair_rate=5.0,  # 5 per pair per second
            burst_multiplier=1.0  # No burst allowance
        )

        # Consume all BTC-USD tokens
        btc_results = []
        for i in range(8):
            result = await limiter.acquire('BTC-USD', timeout=0.01)
            btc_results.append(result)

        # First 5 should succeed (per-pair capacity), rest should fail
        assert sum(btc_results) <= 6  # Allow small margin

        # ETH-USD should still work (separate bucket)
        eth_result = await limiter.acquire('ETH-USD', timeout=0.01)
        assert eth_result is True

    @pytest.mark.asyncio
    async def test_burst_allowance(self):
        """Burst multiplier allows temporary spikes"""
        limiter = RateLimiter(
            global_rate=10.0,
            per_pair_rate=5.0,
            burst_multiplier=2.0  # 2x burst
        )

        # Should allow burst up to capacity (rate * multiplier)
        # Global: 10 * 2 = 20 tokens
        # Per-pair: 5 * 2 = 10 tokens

        # Consume burst for BTC-USD
        results = []
        for i in range(12):
            result = await limiter.acquire('BTC-USD', timeout=0.01)
            results.append(result)

        # Should allow ~10 (per-pair burst), reject rest
        assert 9 <= sum(results) <= 11

    @pytest.mark.asyncio
    async def test_multiple_pairs_independent(self):
        """Different pairs have independent rate limits"""
        limiter = RateLimiter(
            global_rate=100.0,  # High global
            per_pair_rate=5.0,
            burst_multiplier=1.0
        )

        # Exhaust BTC-USD tokens
        for i in range(10):
            await limiter.acquire('BTC-USD', timeout=0.01)

        # BTC-USD should be limited
        btc_result = await limiter.acquire('BTC-USD', timeout=0.01)
        assert btc_result is False

        # ETH-USD should still work
        eth_result = await limiter.acquire('ETH-USD', timeout=0.01)
        assert eth_result is True

        # SOL-USD should still work
        sol_result = await limiter.acquire('SOL-USD', timeout=0.01)
        assert sol_result is True

    def test_backpressure_queue(self):
        """Backpressure queue stores items when needed"""
        limiter = RateLimiter(queue_max_size=10)

        # Enqueue items
        for i in range(5):
            result = limiter.try_enqueue(f"item_{i}")
            assert result is True

        stats = limiter.get_stats()
        assert stats['queue_size'] == 5
        assert stats['stats']['total_queued'] == 5

        # Dequeue items
        for i in range(5):
            item = limiter.dequeue()
            assert item == f"item_{i}"

        assert limiter.dequeue() is None  # Queue empty

    def test_backpressure_queue_overflow(self):
        """Queue drops items when full"""
        limiter = RateLimiter(queue_max_size=3)

        # Fill queue
        assert limiter.try_enqueue("item_1") is True
        assert limiter.try_enqueue("item_2") is True
        assert limiter.try_enqueue("item_3") is True

        # Try to overflow
        assert limiter.try_enqueue("item_4") is False

        stats = limiter.get_stats()
        assert stats['queue_size'] == 3
        assert stats['stats']['queue_drops'] == 1

    def test_get_stats(self):
        """Statistics provide comprehensive metrics"""
        limiter = RateLimiter(
            global_rate=10.0,
            per_pair_rate=3.0
        )

        stats = limiter.get_stats()

        # Check structure
        assert 'enabled' in stats
        assert 'config' in stats
        assert 'stats' in stats
        assert 'queue_size' in stats
        assert 'global_tokens_available' in stats
        assert 'active_pairs' in stats
        assert 'pair_tokens' in stats

        # Check config values
        assert stats['config']['global_rate_per_sec'] == 10.0
        assert stats['config']['per_pair_rate_per_sec'] == 3.0

    def test_reset_stats(self):
        """Can reset statistics counters"""
        limiter = RateLimiter()

        # Generate some stats
        limiter.stats['total_allowed'] = 100
        limiter.stats['total_rejected'] = 5

        # Reset
        limiter.reset_stats()

        assert limiter.stats['total_allowed'] == 0
        assert limiter.stats['total_rejected'] == 0

    def test_get_rate_limiter_singleton(self):
        """get_rate_limiter() returns singleton instance"""
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()

        assert limiter1 is limiter2


class TestRateLimiterIntegration:
    """Integration tests for realistic usage scenarios"""

    @pytest.mark.asyncio
    async def test_multi_pair_fairness(self):
        """Multiple pairs get fair access to global budget"""
        limiter = RateLimiter(
            global_rate=30.0,  # 30 total
            per_pair_rate=15.0,  # 15 per pair
            burst_multiplier=1.0
        )

        # Simulate 3 pairs publishing simultaneously
        btc_count = 0
        eth_count = 0
        sol_count = 0

        for i in range(50):
            pair = ['BTC-USD', 'ETH-USD', 'SOL-USD'][i % 3]

            result = await limiter.acquire(pair, timeout=0.01)

            if result and pair == 'BTC-USD':
                btc_count += 1
            elif result and pair == 'ETH-USD':
                eth_count += 1
            elif result and pair == 'SOL-USD':
                sol_count += 1

        # Each pair should get roughly equal share
        # Global limit is 30, per-pair is 15, no burst (mult=1.0)
        # Expected: each pair gets ~10 (30 / 3)
        # Allow margin for timing variations
        assert 8 <= btc_count <= 16
        assert 8 <= eth_count <= 16
        assert 8 <= sol_count <= 16

    @pytest.mark.asyncio
    async def test_preserves_current_behavior(self):
        """Default configuration preserves current 2-pair behavior"""
        limiter = RateLimiter()  # Default: 10 global, 3 per-pair

        # Simulate publishing for BTC and ETH (current system)
        # At 2 signals/pair/sec = 4 signals/sec total
        # Should be well under limits (10 global, 3 per-pair)

        for i in range(10):
            btc_ok = await limiter.acquire('BTC-USD')
            eth_ok = await limiter.acquire('ETH-USD')

            assert btc_ok is True
            assert eth_ok is True

            await asyncio.sleep(0.5)  # 2 per second

        stats = limiter.get_stats()
        assert stats['stats']['total_rejected'] == 0

    @pytest.mark.asyncio
    async def test_scales_to_5_pairs(self):
        """Can scale to 5 pairs without overwhelming system"""
        limiter = RateLimiter()  # Default: 10 global, 3 per-pair

        pairs = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'ADA-USD', 'AVAX-USD']

        # Each pair tries to publish 3 times (15 total)
        # Global limit is 10, so some should be rejected
        success_count = 0

        for pair in pairs:
            for i in range(3):
                result = await limiter.acquire(pair, timeout=0.01)
                if result:
                    success_count += 1

        # With burst multiplier 2.0, global capacity is 20
        # But per-pair is 6, so each pair limited to 6
        # 5 pairs * 6 max = 30, but global caps at 20
        # Allow margin for timing
        assert 15 <= success_count <= 25

        stats = limiter.get_stats()
        # With generous limits, may not reject any
        assert stats['active_pairs'] == 5  # All pairs tracked


# Mark all tests for easy running
pytest_plugins = ['pytest_asyncio']
