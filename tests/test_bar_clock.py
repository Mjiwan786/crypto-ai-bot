"""
Comprehensive unit tests for BarClock scheduler.

Test Coverage:
- Boundary computation (exact 5m alignment)
- Sleep delta calculation
- Clock skew detection (>2s triggers backoff)
- Redis debouncing (no duplicate events)
- Callback invocation
- Time jumps (ensure one event per boundary)
- Restart scenarios (no duplicate after restart)
- Graceful shutdown
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from agents.scheduler.bar_clock import (
    BarClock,
    ClockConfig,
    BarCloseEvent,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def clock_config():
    """Default clock configuration."""
    return ClockConfig(
        timeframe_minutes=5,
        max_clock_skew_seconds=2.0,
        backoff_on_skew_seconds=10.0,
        debounce_ttl_seconds=360,
        jitter_tolerance_ms=100,
    )


@pytest.fixture
def redis_mock():
    """Mock Redis client."""
    mock = AsyncMock()
    mock.exists.return_value = 0
    mock.setex.return_value = True
    return mock


@pytest.fixture
def clock(redis_mock, clock_config):
    """Initialize BarClock with mocks."""
    return BarClock(
        redis_client=redis_mock,
        pairs=["BTC/USD", "ETH/USD"],
        config=clock_config,
    )


# =============================================================================
# TEST: BOUNDARY COMPUTATION
# =============================================================================

def test_compute_next_boundary_exact_boundary(clock):
    """Test boundary computation when exactly at boundary."""
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    next_boundary = clock.compute_next_boundary(now)

    # At 12:00:00 -> next is 12:05:00
    expected = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    assert next_boundary == expected


def test_compute_next_boundary_mid_window(clock):
    """Test boundary computation in middle of window."""
    now = datetime(2025, 1, 1, 12, 3, 45, tzinfo=timezone.utc)
    next_boundary = clock.compute_next_boundary(now)

    # At 12:03:45 -> next is 12:05:00
    expected = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    assert next_boundary == expected


def test_compute_next_boundary_just_after_boundary(clock):
    """Test boundary computation just after boundary."""
    now = datetime(2025, 1, 1, 12, 5, 1, tzinfo=timezone.utc)
    next_boundary = clock.compute_next_boundary(now)

    # At 12:05:01 -> next is 12:10:00
    expected = datetime(2025, 1, 1, 12, 10, 0, tzinfo=timezone.utc)
    assert next_boundary == expected


def test_compute_next_boundary_various_times(clock):
    """Test boundary computation for various times."""
    test_cases = [
        # (now, expected_next_boundary)
        (datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc), datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)),
        (datetime(2025, 1, 1, 12, 2, 30, tzinfo=timezone.utc), datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)),
        (datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc), datetime(2025, 1, 1, 12, 10, 0, tzinfo=timezone.utc)),
        (datetime(2025, 1, 1, 12, 7, 0, tzinfo=timezone.utc), datetime(2025, 1, 1, 12, 10, 0, tzinfo=timezone.utc)),
        (datetime(2025, 1, 1, 12, 10, 0, tzinfo=timezone.utc), datetime(2025, 1, 1, 12, 15, 0, tzinfo=timezone.utc)),
        (datetime(2025, 1, 1, 12, 59, 59, tzinfo=timezone.utc), datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)),
    ]

    for now, expected in test_cases:
        next_boundary = clock.compute_next_boundary(now)
        assert next_boundary == expected, f"Failed for {now}: expected {expected}, got {next_boundary}"


# =============================================================================
# TEST: SLEEP DELTA CALCULATION
# =============================================================================

def test_compute_sleep_delta_mid_window(clock):
    """Test sleep delta computation in middle of window."""
    now = datetime(2025, 1, 1, 12, 3, 45, tzinfo=timezone.utc)
    delta = clock.compute_sleep_delta(now)

    # 12:03:45 -> 12:05:00 = 1 minute 15 seconds = 75 seconds
    assert delta == 75.0


def test_compute_sleep_delta_just_before_boundary(clock):
    """Test sleep delta just before boundary."""
    now = datetime(2025, 1, 1, 12, 4, 59, tzinfo=timezone.utc)
    delta = clock.compute_sleep_delta(now)

    # 12:04:59 -> 12:05:00 = 1 second
    assert delta == 1.0


def test_compute_sleep_delta_at_boundary(clock):
    """Test sleep delta exactly at boundary."""
    now = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    delta = clock.compute_sleep_delta(now)

    # 12:05:00 -> 12:10:00 = 5 minutes = 300 seconds
    assert delta == 300.0


def test_compute_sleep_delta_always_positive(clock):
    """Test sleep delta is always positive."""
    # Test many random times
    for minute in range(0, 60, 1):
        for second in range(0, 60, 15):
            now = datetime(2025, 1, 1, 12, minute, second, tzinfo=timezone.utc)
            delta = clock.compute_sleep_delta(now)
            assert delta >= 0, f"Delta should be positive for {now}, got {delta}"


# =============================================================================
# TEST: CLOCK SKEW DETECTION
# =============================================================================

def test_detect_clock_skew_no_skew(clock):
    """Test no skew when timing is precise."""
    expected = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    actual = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)

    skew = clock.detect_clock_skew(expected, actual)
    assert skew is False


def test_detect_clock_skew_acceptable_drift(clock):
    """Test acceptable drift (<= 2s)."""
    expected = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)

    # 1 second drift (OK)
    actual = datetime(2025, 1, 1, 12, 5, 1, tzinfo=timezone.utc)
    skew = clock.detect_clock_skew(expected, actual)
    assert skew is False

    # 2 second drift (OK, at threshold)
    actual = datetime(2025, 1, 1, 12, 5, 2, tzinfo=timezone.utc)
    skew = clock.detect_clock_skew(expected, actual)
    assert skew is False


def test_detect_clock_skew_excessive_drift(clock):
    """Test excessive drift (> 2s)."""
    expected = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)

    # 3 second drift (BAD)
    actual = datetime(2025, 1, 1, 12, 5, 3, tzinfo=timezone.utc)
    skew = clock.detect_clock_skew(expected, actual)
    assert skew is True

    # 5 second drift (BAD)
    actual = datetime(2025, 1, 1, 12, 5, 5, tzinfo=timezone.utc)
    skew = clock.detect_clock_skew(expected, actual)
    assert skew is True


def test_detect_clock_skew_negative_drift(clock):
    """Test negative drift (early firing)."""
    expected = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)

    # 1 second early (OK)
    actual = datetime(2025, 1, 1, 12, 4, 59, tzinfo=timezone.utc)
    skew = clock.detect_clock_skew(expected, actual)
    assert skew is False

    # 3 seconds early (BAD)
    actual = datetime(2025, 1, 1, 12, 4, 57, tzinfo=timezone.utc)
    skew = clock.detect_clock_skew(expected, actual)
    assert skew is True


# =============================================================================
# TEST: REDIS DEBOUNCING
# =============================================================================

@pytest.mark.asyncio
async def test_is_already_processed_not_processed(clock, redis_mock):
    """Test debouncing when bar not yet processed."""
    redis_mock.exists.return_value = 0

    bar_ts = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    is_processed = await clock.is_already_processed("BTC/USD", bar_ts)

    assert is_processed is False
    redis_mock.exists.assert_called_once()


@pytest.mark.asyncio
async def test_is_already_processed_already_processed(clock, redis_mock):
    """Test debouncing when bar already processed."""
    redis_mock.exists.return_value = 1

    bar_ts = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    is_processed = await clock.is_already_processed("BTC/USD", bar_ts)

    assert is_processed is True


@pytest.mark.asyncio
async def test_mark_processed(clock, redis_mock):
    """Test marking bar as processed."""
    bar_ts = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    await clock.mark_processed("BTC/USD", bar_ts)

    # Check Redis setex called with correct TTL
    redis_mock.setex.assert_called_once()
    args = redis_mock.setex.call_args[0]

    assert "bar_clock:processed:BTC/USD:2025-01-01T12:05:00+00:00" in args[0]
    assert args[1] == 360  # TTL = 6 minutes


@pytest.mark.asyncio
async def test_debouncing_prevents_duplicate_events(clock, redis_mock):
    """Test debouncing prevents duplicate event emission."""
    bar_ts = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)

    # First emission: not processed
    redis_mock.exists.return_value = 0
    call_count = 0

    async def test_callback(event: BarCloseEvent):
        nonlocal call_count
        call_count += 1

    clock.register_callback("BTC/USD", test_callback)

    await clock.emit_bar_close_event("BTC/USD", bar_ts)
    assert call_count == 1, "Should invoke callback once"

    # Second emission: already processed (should skip)
    redis_mock.exists.return_value = 1
    await clock.emit_bar_close_event("BTC/USD", bar_ts)
    assert call_count == 1, "Should not invoke callback for duplicate"


# =============================================================================
# TEST: CALLBACK REGISTRATION
# =============================================================================

def test_register_callback_valid_pair(clock):
    """Test callback registration for valid pair."""
    async def callback(event: BarCloseEvent):
        pass

    clock.register_callback("BTC/USD", callback)

    assert len(clock._callbacks["BTC/USD"]) == 1


def test_register_callback_invalid_pair(clock):
    """Test callback registration fails for invalid pair."""
    async def callback(event: BarCloseEvent):
        pass

    with pytest.raises(ValueError, match="not in configured pairs"):
        clock.register_callback("INVALID/PAIR", callback)


def test_register_multiple_callbacks(clock):
    """Test multiple callbacks can be registered for same pair."""
    async def callback1(event: BarCloseEvent):
        pass

    async def callback2(event: BarCloseEvent):
        pass

    clock.register_callback("BTC/USD", callback1)
    clock.register_callback("BTC/USD", callback2)

    assert len(clock._callbacks["BTC/USD"]) == 2


# =============================================================================
# TEST: EVENT EMISSION
# =============================================================================

@pytest.mark.asyncio
async def test_emit_bar_close_event_invokes_callbacks(clock, redis_mock):
    """Test event emission invokes all registered callbacks."""
    redis_mock.exists.return_value = 0

    call_count = 0
    received_events = []

    async def callback(event: BarCloseEvent):
        nonlocal call_count
        call_count += 1
        received_events.append(event)

    clock.register_callback("BTC/USD", callback)

    bar_ts = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    await clock.emit_bar_close_event("BTC/USD", bar_ts)

    assert call_count == 1
    assert len(received_events) == 1
    assert received_events[0].pair == "BTC/USD"
    assert received_events[0].timestamp == bar_ts
    assert received_events[0].timeframe == "5m"


@pytest.mark.asyncio
async def test_emit_bar_close_event_multiple_callbacks(clock, redis_mock):
    """Test event emission invokes all callbacks."""
    redis_mock.exists.return_value = 0

    call_count1 = 0
    call_count2 = 0

    async def callback1(event: BarCloseEvent):
        nonlocal call_count1
        call_count1 += 1

    async def callback2(event: BarCloseEvent):
        nonlocal call_count2
        call_count2 += 1

    clock.register_callback("BTC/USD", callback1)
    clock.register_callback("BTC/USD", callback2)

    bar_ts = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    await clock.emit_bar_close_event("BTC/USD", bar_ts)

    assert call_count1 == 1
    assert call_count2 == 1


@pytest.mark.asyncio
async def test_emit_bar_close_event_callback_exception_handling(clock, redis_mock):
    """Test event emission continues even if callback fails."""
    redis_mock.exists.return_value = 0

    call_count_good = 0

    async def bad_callback(event: BarCloseEvent):
        raise ValueError("Test error")

    async def good_callback(event: BarCloseEvent):
        nonlocal call_count_good
        call_count_good += 1

    clock.register_callback("BTC/USD", bad_callback)
    clock.register_callback("BTC/USD", good_callback)

    bar_ts = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)

    # Should not raise, should continue to good_callback
    await clock.emit_bar_close_event("BTC/USD", bar_ts)

    assert call_count_good == 1, "Good callback should still be invoked"


# =============================================================================
# TEST: TIME JUMPS (ONE EVENT PER BOUNDARY)
# =============================================================================

@pytest.mark.asyncio
async def test_time_jump_forward_emits_one_event(clock, redis_mock):
    """Test time jump forward emits exactly one event."""
    redis_mock.exists.return_value = 0

    call_count = 0

    async def callback(event: BarCloseEvent):
        nonlocal call_count
        call_count += 1

    clock.register_callback("BTC/USD", callback)

    # Emit for 12:05:00
    bar_ts_1 = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    await clock.emit_bar_close_event("BTC/USD", bar_ts_1)

    # Jump to 12:15:00 (skipped 12:10:00)
    bar_ts_2 = datetime(2025, 1, 1, 12, 15, 0, tzinfo=timezone.utc)
    await clock.emit_bar_close_event("BTC/USD", bar_ts_2)

    # Should have 2 total events (not 3)
    assert call_count == 2


@pytest.mark.asyncio
async def test_restart_no_duplicate(clock, redis_mock):
    """Test restart doesn't emit duplicate for already-processed bar."""
    # First run: emit event
    redis_mock.exists.return_value = 0

    call_count = 0

    async def callback(event: BarCloseEvent):
        nonlocal call_count
        call_count += 1

    clock.register_callback("BTC/USD", callback)

    bar_ts = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    await clock.emit_bar_close_event("BTC/USD", bar_ts)

    assert call_count == 1

    # Simulate restart: same bar, but already processed
    redis_mock.exists.return_value = 1

    await clock.emit_bar_close_event("BTC/USD", bar_ts)

    # Should still be 1 (no duplicate)
    assert call_count == 1


# =============================================================================
# TEST: GRACEFUL SHUTDOWN
# =============================================================================

def test_request_shutdown(clock):
    """Test shutdown request stops clock."""
    assert clock._running is False
    assert clock._shutdown_event.is_set() is False

    clock._running = True
    clock.request_shutdown()

    assert clock._running is False
    assert clock._shutdown_event.is_set() is True


@pytest.mark.asyncio
async def test_cleanup(clock):
    """Test cleanup clears callbacks."""
    async def callback(event: BarCloseEvent):
        pass

    clock.register_callback("BTC/USD", callback)
    assert len(clock._callbacks["BTC/USD"]) == 1

    await clock.cleanup()

    assert len(clock._callbacks["BTC/USD"]) == 0


# =============================================================================
# SUMMARY
# =============================================================================

if __name__ == "__main__":
    """Run tests with pytest."""
    pytest.main([__file__, "-v", "--tb=short"])
