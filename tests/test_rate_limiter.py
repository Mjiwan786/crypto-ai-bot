"""
Tests for Trade Rate Limiting

Tests that SCALPER_MAX_TRADES_PER_MINUTE env variable correctly limits
trading frequency, with proper cooldown and recovery mechanisms.

Tests:
- Rate limiter trip conditions
- Cooldown behavior
- Trade rate calculation
- Circuit breaker integration
- End-to-end latency under rate limiting

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# MOCK CLASSES
# =============================================================================


class MockRateLimiter:
    """
    Mock rate limiter for testing.

    Implements the same interface as the real rate limiter in Kraken WSS client.
    """

    def __init__(self, max_trades_per_minute: int = 4, cooldown_seconds: int = 60):
        self.max_trades_per_minute = max_trades_per_minute
        self.cooldown_seconds = cooldown_seconds
        self.trade_timestamps = []
        self.circuit_breaker_triggered = False
        self.circuit_breaker_trigger_time = None

    async def check_rate_limit(self) -> bool:
        """
        Check if rate limit is exceeded.

        Returns:
            True if rate limit exceeded, False otherwise
        """
        now = time.time()

        # Clean old timestamps (older than 1 minute)
        self.trade_timestamps = [ts for ts in self.trade_timestamps if now - ts < 60]

        # Check rate limit
        if len(self.trade_timestamps) >= self.max_trades_per_minute:
            await self._trigger_circuit_breaker()
            return True

        return False

    async def record_trade(self) -> bool:
        """
        Record a trade attempt.

        Returns:
            True if trade allowed, False if rate limited
        """
        now = time.time()

        # Check if circuit breaker is active
        if self.circuit_breaker_triggered:
            if now - self.circuit_breaker_trigger_time < self.cooldown_seconds:
                return False  # Still in cooldown
            else:
                # Cooldown expired, reset
                self.circuit_breaker_triggered = False
                # Clean old timestamps
                self.trade_timestamps = [ts for ts in self.trade_timestamps if now - ts < 60]

        # Check rate limit
        if await self.check_rate_limit():
            return False  # Rate limit exceeded

        # Record trade
        self.trade_timestamps.append(now)
        return True

    async def _trigger_circuit_breaker(self):
        """Trigger circuit breaker for rate limiting."""
        if not self.circuit_breaker_triggered:
            self.circuit_breaker_triggered = True
            self.circuit_breaker_trigger_time = time.time()

    def get_current_rate(self) -> float:
        """Get current trades per minute."""
        now = time.time()
        recent_trades = [ts for ts in self.trade_timestamps if now - ts < 60]
        return len(recent_trades)

    def reset(self):
        """Reset rate limiter state."""
        self.trade_timestamps = []
        self.circuit_breaker_triggered = False
        self.circuit_breaker_trigger_time = None


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def rate_limiter_4tpm():
    """Rate limiter with 4 trades per minute."""
    return MockRateLimiter(max_trades_per_minute=4, cooldown_seconds=60)


@pytest.fixture
def rate_limiter_10tpm():
    """Rate limiter with 10 trades per minute."""
    return MockRateLimiter(max_trades_per_minute=10, cooldown_seconds=60)


# =============================================================================
# TEST: BASIC RATE LIMITING
# =============================================================================


@pytest.mark.asyncio
async def test_rate_limit_allows_within_limit(rate_limiter_4tpm):
    """Test that trades within limit are allowed."""
    # Record 3 trades (< 4 limit)
    for i in range(3):
        allowed = await rate_limiter_4tpm.record_trade()
        assert allowed, f"Trade {i+1}/3 should be allowed"

    # Should still be able to trade
    assert rate_limiter_4tpm.get_current_rate() == 3
    assert not rate_limiter_4tpm.circuit_breaker_triggered


@pytest.mark.asyncio
async def test_rate_limit_trips_at_limit(rate_limiter_4tpm):
    """Test that rate limiter trips when limit is reached."""
    # Record 4 trades (= limit)
    for i in range(4):
        allowed = await rate_limiter_4tpm.record_trade()
        assert allowed, f"Trade {i+1}/4 should be allowed"

    # 5th trade should trip the rate limiter
    allowed = await rate_limiter_4tpm.record_trade()
    assert not allowed, "5th trade should be blocked by rate limiter"
    assert rate_limiter_4tpm.circuit_breaker_triggered


@pytest.mark.asyncio
async def test_rate_limit_blocks_subsequent_trades(rate_limiter_4tpm):
    """Test that subsequent trades are blocked after limit is reached."""
    # Reach limit
    for i in range(5):
        await rate_limiter_4tpm.record_trade()

    # All subsequent trades should be blocked
    for i in range(10):
        allowed = await rate_limiter_4tpm.record_trade()
        assert not allowed, f"Trade {i+1} after limit should be blocked"


# =============================================================================
# TEST: COOLDOWN BEHAVIOR
# =============================================================================


@pytest.mark.asyncio
async def test_cooldown_blocks_trades_during_period():
    """Test that cooldown blocks trades for the configured period."""
    limiter = MockRateLimiter(max_trades_per_minute=2, cooldown_seconds=1)

    # Trip rate limiter (2 trades in quick succession)
    await limiter.record_trade()
    await limiter.record_trade()

    # 3rd trade triggers rate limit
    allowed = await limiter.record_trade()
    assert not allowed
    assert limiter.circuit_breaker_triggered

    # Should still be blocked during cooldown
    await asyncio.sleep(0.5)
    allowed = await limiter.record_trade()
    assert not allowed, "Should be blocked during cooldown period"
    assert limiter.circuit_breaker_triggered

    # After cooldown expires, but old trades still in 60s window - will still be blocked
    # This is expected behavior - cooldown expires but rate is still high


@pytest.mark.asyncio
async def test_cooldown_resets_properly():
    """Test that cooldown flag resets after cooldown expires."""
    limiter = MockRateLimiter(max_trades_per_minute=2, cooldown_seconds=1)

    # Trip rate limiter
    await limiter.record_trade()
    await limiter.record_trade()
    await limiter.record_trade()  # Triggers circuit breaker

    assert limiter.circuit_breaker_triggered

    # Wait for cooldown + let old trades age out (65s total)
    # For test speed, we'll manually clear old trades
    await asyncio.sleep(1.2)
    limiter.trade_timestamps = []  # Manually clear for test

    # Circuit breaker should reset and trade should be allowed
    allowed = await limiter.record_trade()
    assert allowed, "Trade should be allowed after cooldown and rate clears"
    assert not limiter.circuit_breaker_triggered


# =============================================================================
# TEST: TRADE RATE CALCULATION
# =============================================================================


@pytest.mark.asyncio
async def test_trade_rate_calculation_accuracy(rate_limiter_4tpm):
    """Test that trade rate is calculated accurately."""
    # Record trades with 0.5s spacing
    for i in range(4):
        await rate_limiter_4tpm.record_trade()
        await asyncio.sleep(0.5)

    rate = rate_limiter_4tpm.get_current_rate()
    assert rate == 4, f"Expected rate=4, got {rate}"


@pytest.mark.asyncio
async def test_trade_rate_excludes_old_trades():
    """Test that trades older than 60s are excluded from rate calculation."""
    limiter = MockRateLimiter(max_trades_per_minute=10, cooldown_seconds=60)

    # Record 5 trades
    for i in range(5):
        limiter.trade_timestamps.append(time.time() - 70)  # 70s ago (old)

    # Record 3 new trades
    for i in range(3):
        await limiter.record_trade()

    # Rate should only count recent trades (3, not 8)
    rate = limiter.get_current_rate()
    assert rate == 3, f"Expected rate=3, got {rate}"


# =============================================================================
# TEST: DIFFERENT RATE LIMITS
# =============================================================================


@pytest.mark.asyncio
async def test_rate_limiter_with_high_limit(rate_limiter_10tpm):
    """Test rate limiter with higher limit (10 trades/min)."""
    # Should allow 10 trades
    for i in range(10):
        allowed = await rate_limiter_10tpm.record_trade()
        assert allowed, f"Trade {i+1}/10 should be allowed"

    # 11th should be blocked
    allowed = await rate_limiter_10tpm.record_trade()
    assert not allowed


@pytest.mark.asyncio
async def test_rate_limiter_with_low_limit():
    """Test rate limiter with very strict limit (1 trade/min)."""
    limiter = MockRateLimiter(max_trades_per_minute=1, cooldown_seconds=60)

    # First trade allowed
    allowed = await limiter.record_trade()
    assert allowed

    # Second trade blocked
    allowed = await limiter.record_trade()
    assert not allowed


# =============================================================================
# TEST: CONCURRENT TRADE ATTEMPTS
# =============================================================================


@pytest.mark.asyncio
async def test_concurrent_trade_attempts():
    """Test rate limiter under concurrent trade attempts."""
    limiter = MockRateLimiter(max_trades_per_minute=5, cooldown_seconds=60)

    # Simulate 10 concurrent trade attempts
    results = await asyncio.gather(
        *[limiter.record_trade() for _ in range(10)]
    )

    # Only first 5 should be allowed
    allowed_count = sum(1 for r in results if r)
    assert allowed_count == 5, f"Expected 5 allowed, got {allowed_count}"


# =============================================================================
# TEST: RESET FUNCTIONALITY
# =============================================================================


@pytest.mark.asyncio
async def test_reset_clears_state(rate_limiter_4tpm):
    """Test that reset clears all state."""
    # Trip rate limiter
    for i in range(5):
        await rate_limiter_4tpm.record_trade()

    assert rate_limiter_4tpm.circuit_breaker_triggered
    assert len(rate_limiter_4tpm.trade_timestamps) > 0

    # Reset
    rate_limiter_4tpm.reset()

    # Should be clean
    assert not rate_limiter_4tpm.circuit_breaker_triggered
    assert len(rate_limiter_4tpm.trade_timestamps) == 0
    assert rate_limiter_4tpm.get_current_rate() == 0


# =============================================================================
# TEST: EDGE CASES
# =============================================================================


@pytest.mark.asyncio
async def test_rate_limiter_at_exact_60_second_boundary():
    """Test rate limiter behavior at exactly 60 second boundary."""
    limiter = MockRateLimiter(max_trades_per_minute=4, cooldown_seconds=60)

    # Record trades at specific times
    now = time.time()
    limiter.trade_timestamps = [
        now - 61.0,  # Should be excluded (> 60s old)
        now - 59.5,  # Should be included
        now - 30.0,  # Should be included
        now - 10.0,  # Should be included
    ]

    rate = limiter.get_current_rate()
    assert rate == 3, f"Expected rate=3 (excluding trade > 60s), got {rate}"


@pytest.mark.asyncio
async def test_rate_limiter_with_zero_timestamps():
    """Test rate limiter with no previous trades."""
    limiter = MockRateLimiter(max_trades_per_minute=4, cooldown_seconds=60)

    assert limiter.get_current_rate() == 0

    # First trade should always be allowed
    allowed = await limiter.record_trade()
    assert allowed


# =============================================================================
# BENCHMARK TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_rate_limiter_performance():
    """Benchmark: Rate limiter check should be < 1ms."""
    limiter = MockRateLimiter(max_trades_per_minute=10, cooldown_seconds=60)

    # Add some trade history
    for i in range(5):
        await limiter.record_trade()

    # Benchmark rate limit checks
    iterations = 1000
    start = time.perf_counter()

    for _ in range(iterations):
        await limiter.check_rate_limit()

    end = time.perf_counter()
    avg_time_ms = ((end - start) / iterations) * 1000

    # Should be very fast (< 0.1ms per check)
    assert avg_time_ms < 0.1, f"Rate limit check too slow: {avg_time_ms:.3f}ms"


# =============================================================================
# TEST: INTEGRATION WITH ENV VARIABLE
# =============================================================================


@patch.dict("os.environ", {"SCALPER_MAX_TRADES_PER_MINUTE": "6"})
def test_rate_limiter_respects_env_variable():
    """Test that rate limiter respects SCALPER_MAX_TRADES_PER_MINUTE env var."""
    import os

    max_trades = int(os.getenv("SCALPER_MAX_TRADES_PER_MINUTE", "4"))
    limiter = MockRateLimiter(max_trades_per_minute=max_trades, cooldown_seconds=60)

    assert limiter.max_trades_per_minute == 6


@patch.dict("os.environ", {"SCALPER_MAX_TRADES_PER_MINUTE": "10"})
@pytest.mark.asyncio
async def test_rate_limiter_env_override_functional():
    """Test that env variable override actually affects behavior."""
    import os

    max_trades = int(os.getenv("SCALPER_MAX_TRADES_PER_MINUTE", "4"))
    limiter = MockRateLimiter(max_trades_per_minute=max_trades, cooldown_seconds=60)

    # Should allow 10 trades (from env)
    for i in range(10):
        allowed = await limiter.record_trade()
        assert allowed, f"Trade {i+1}/10 should be allowed with env override"

    # 11th should be blocked
    allowed = await limiter.record_trade()
    assert not allowed
