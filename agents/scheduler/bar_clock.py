"""
Bar Clock - Precise 5-Minute UTC Cadence Scheduler

Emits bar_close:5m events at exact 5-minute boundaries (00:00, 00:05, 00:10, etc.)
with Redis-based debouncing to prevent duplicate events after restarts.

Features:
- Computes sleep delta to next 5-minute boundary
- Emits bar_close:5m events at precise UTC times
- Redis debouncing (prevents double-fire on restart)
- Clock skew detection with backoff (>2s drift triggers warning)
- Graceful shutdown with cleanup
- Callback registration for strategy agents

Accept criteria:
- Fires at exact 5-minute boundaries (±100ms jitter acceptable)
- No duplicate events within same 5-minute window
- Survives restarts without missing/duplicating bars
- Detects and handles clock skew
- Clean shutdown on SIGTERM/SIGINT

Reject criteria:
- Fixed time.sleep() without boundary alignment
- No debouncing (allows duplicates)
- Missing clock skew detection
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Dict, List, Awaitable

import redis.asyncio as redis

logger = logging.getLogger(__name__)


# Define BarCloseEvent here to avoid circular imports
@dataclass
class BarCloseEvent:
    """
    Bar-close event triggered at timeframe boundaries.

    Attributes:
        timestamp: Bar close timestamp (UTC)
        pair: Trading pair (e.g., "BTC/USD")
        timeframe: Bar timeframe (e.g., "5m")
        bar_data: OHLCV data for closed bar
    """
    timestamp: datetime
    pair: str
    timeframe: str
    bar_data: Dict[str, float]


@dataclass
class ClockConfig:
    """
    Configuration for bar clock scheduler.

    Attributes:
        timeframe_minutes: Bar timeframe in minutes (default: 5)
        max_clock_skew_seconds: Max acceptable clock skew (default: 2.0)
        backoff_on_skew_seconds: Backoff duration on skew detection (default: 10.0)
        debounce_ttl_seconds: TTL for debounce keys (default: 360 = 6 minutes)
        jitter_tolerance_ms: Acceptable timing jitter (default: 100ms)
    """
    timeframe_minutes: int = 5
    max_clock_skew_seconds: float = 2.0
    backoff_on_skew_seconds: float = 10.0
    debounce_ttl_seconds: int = 360  # 6 minutes (slightly > 5m window)
    jitter_tolerance_ms: int = 100


class BarClock:
    """
    Precise 5-minute bar clock with Redis debouncing.

    Computes sleep delta to next 5-minute UTC boundary and emits
    bar_close:5m events at exact times. Uses Redis to prevent
    duplicate events after restarts.

    Example:
        >>> clock = BarClock(redis_client, pairs=["BTC/USD", "ETH/USD"])
        >>> clock.register_callback("BTC/USD", strategy.on_bar_close)
        >>> await clock.run()
        # Emits events at 00:00, 00:05, 00:10, etc.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        pairs: List[str],
        config: Optional[ClockConfig] = None,
    ):
        """
        Initialize bar clock.

        Args:
            redis_client: Async Redis client for debouncing
            pairs: List of trading pairs to emit events for
            config: Clock configuration (uses defaults if None)
        """
        self.redis = redis_client
        self.pairs = pairs
        self.config = config or ClockConfig()

        # Callback registry: pair -> list of callbacks
        self._callbacks: Dict[str, List[Callable[[BarCloseEvent], Awaitable[None]]]] = {
            pair: [] for pair in pairs
        }

        # State tracking
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._last_bar_ts: Optional[datetime] = None
        self._skew_count = 0

        logger.info(
            f"BarClock initialized: {len(pairs)} pairs, "
            f"timeframe={self.config.timeframe_minutes}m, "
            f"max_skew={self.config.max_clock_skew_seconds}s"
        )

    def register_callback(
        self,
        pair: str,
        callback: Callable[[BarCloseEvent], Awaitable[None]]
    ) -> None:
        """
        Register callback for bar-close events on a pair.

        Args:
            pair: Trading pair (e.g., "BTC/USD")
            callback: Async function to call on bar close

        Raises:
            ValueError: If pair not in configured pairs

        Example:
            >>> async def on_bar_close(event: BarCloseEvent):
            ...     print(f"Bar closed: {event.pair} @ {event.timestamp}")
            >>> clock.register_callback("BTC/USD", on_bar_close)
        """
        if pair not in self._callbacks:
            raise ValueError(f"Pair {pair} not in configured pairs: {self.pairs}")

        self._callbacks[pair].append(callback)
        logger.info(f"Registered callback for {pair} (total: {len(self._callbacks[pair])})")

    def compute_next_boundary(self, now: Optional[datetime] = None) -> datetime:
        """
        Compute next 5-minute UTC boundary.

        Algorithm:
        1. Get current UTC time (or use provided time)
        2. Round down to last 5-minute boundary
        3. Add 5 minutes to get next boundary

        Args:
            now: Current time (uses datetime.now(UTC) if None)

        Returns:
            Next 5-minute boundary timestamp

        Example:
            >>> now = datetime(2025, 1, 1, 12, 3, 45, tzinfo=timezone.utc)
            >>> next_boundary = clock.compute_next_boundary(now)
            >>> next_boundary
            datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Round down to last boundary
        # minutes_since_hour = 3 -> last_boundary_minutes = 0 (3 // 5 = 0, 0 * 5 = 0)
        # minutes_since_hour = 7 -> last_boundary_minutes = 5 (7 // 5 = 1, 1 * 5 = 5)
        minutes_since_hour = now.minute
        last_boundary_minutes = (minutes_since_hour // self.config.timeframe_minutes) * self.config.timeframe_minutes

        # Create boundary timestamp
        last_boundary = now.replace(
            minute=last_boundary_minutes,
            second=0,
            microsecond=0
        )

        # Add timeframe to get next boundary
        next_boundary = last_boundary + timedelta(minutes=self.config.timeframe_minutes)

        return next_boundary

    def compute_sleep_delta(self, now: Optional[datetime] = None) -> float:
        """
        Compute seconds to sleep until next boundary.

        Args:
            now: Current time (uses datetime.now(UTC) if None)

        Returns:
            Seconds to sleep (always positive)

        Example:
            >>> now = datetime(2025, 1, 1, 12, 3, 45, tzinfo=timezone.utc)
            >>> delta = clock.compute_sleep_delta(now)
            >>> delta
            75.0  # 1 minute 15 seconds until 12:05:00
        """
        if now is None:
            now = datetime.now(timezone.utc)

        next_boundary = self.compute_next_boundary(now)
        delta = (next_boundary - now).total_seconds()

        # Ensure positive (should always be, but safety check)
        return max(0.0, delta)

    async def is_already_processed(self, pair: str, bar_ts: datetime) -> bool:
        """
        Check if bar has already been processed (Redis debouncing).

        Uses Redis key: bar_clock:processed:{pair}:{bar_ts_iso}

        Args:
            pair: Trading pair
            bar_ts: Bar close timestamp

        Returns:
            True if already processed, False otherwise
        """
        key = f"bar_clock:processed:{pair}:{bar_ts.isoformat()}"
        exists = await self.redis.exists(key)
        return exists > 0

    async def mark_processed(self, pair: str, bar_ts: datetime) -> None:
        """
        Mark bar as processed in Redis (prevent duplicate events).

        Sets key with TTL = debounce_ttl_seconds (6 minutes by default).

        Args:
            pair: Trading pair
            bar_ts: Bar close timestamp
        """
        key = f"bar_clock:processed:{pair}:{bar_ts.isoformat()}"
        await self.redis.setex(
            key,
            self.config.debounce_ttl_seconds,
            "1"
        )
        logger.debug(f"Marked processed: {pair} @ {bar_ts.isoformat()}")

    def detect_clock_skew(self, expected_ts: datetime, actual_ts: datetime) -> bool:
        """
        Detect clock skew (drift > max_clock_skew_seconds).

        Args:
            expected_ts: Expected bar close timestamp
            actual_ts: Actual current timestamp

        Returns:
            True if skew detected, False otherwise
        """
        skew_seconds = abs((actual_ts - expected_ts).total_seconds())

        if skew_seconds > self.config.max_clock_skew_seconds:
            logger.warning(
                f"Clock skew detected: {skew_seconds:.2f}s "
                f"(expected: {expected_ts.isoformat()}, actual: {actual_ts.isoformat()})"
            )
            return True

        return False

    async def emit_bar_close_event(self, pair: str, bar_ts: datetime) -> None:
        """
        Emit bar-close event and invoke callbacks.

        Args:
            pair: Trading pair
            bar_ts: Bar close timestamp
        """
        # Check debouncing
        if await self.is_already_processed(pair, bar_ts):
            logger.debug(f"Skipping duplicate event: {pair} @ {bar_ts.isoformat()}")
            return

        # Create event
        event = BarCloseEvent(
            timestamp=bar_ts,
            pair=pair,
            timeframe=f"{self.config.timeframe_minutes}m",
            bar_data={},  # Will be populated by strategy from Redis
        )

        # Invoke callbacks
        callbacks = self._callbacks.get(pair, [])
        if callbacks:
            logger.info(f"Emitting bar_close:{self.config.timeframe_minutes}m for {pair} @ {bar_ts.isoformat()}")

            for callback in callbacks:
                try:
                    await callback(event)
                except Exception as e:
                    logger.error(f"Callback failed for {pair}: {e}", exc_info=True)

        # Mark as processed
        await self.mark_processed(pair, bar_ts)

    async def run_cycle(self) -> None:
        """
        Run one clock cycle (sleep until boundary, emit events).

        Steps:
        1. Compute sleep delta to next boundary
        2. Sleep until boundary
        3. Verify timing (detect clock skew)
        4. Emit events for all pairs
        5. Backoff if skew detected
        """
        now = datetime.now(timezone.utc)
        next_boundary = self.compute_next_boundary(now)
        sleep_delta = self.compute_sleep_delta(now)

        logger.debug(
            f"Next boundary: {next_boundary.isoformat()}, "
            f"sleep={sleep_delta:.2f}s"
        )

        # Sleep until boundary
        await asyncio.sleep(sleep_delta)

        # Verify timing
        actual_now = datetime.now(timezone.utc)
        if self.detect_clock_skew(next_boundary, actual_now):
            self._skew_count += 1

            # Backoff on repeated skew
            if self._skew_count >= 3:
                logger.error(
                    f"Repeated clock skew detected ({self._skew_count} times), "
                    f"backing off {self.config.backoff_on_skew_seconds}s"
                )
                await asyncio.sleep(self.config.backoff_on_skew_seconds)
                self._skew_count = 0
                return  # Skip this cycle

        else:
            # Reset skew count on successful timing
            self._skew_count = 0

        # Emit events for all pairs
        self._last_bar_ts = next_boundary

        for pair in self.pairs:
            try:
                await self.emit_bar_close_event(pair, next_boundary)
            except Exception as e:
                logger.error(f"Failed to emit event for {pair}: {e}", exc_info=True)

    async def run(self) -> None:
        """
        Run bar clock (infinite loop until shutdown).

        Handles graceful shutdown on SIGTERM/SIGINT.

        Example:
            >>> clock = BarClock(redis_client, pairs=["BTC/USD"])
            >>> await clock.run()
            # Runs until Ctrl+C or SIGTERM
        """
        self._running = True
        logger.info(f"Starting bar clock for {len(self.pairs)} pairs")

        try:
            while self._running and not self._shutdown_event.is_set():
                await self.run_cycle()

        except asyncio.CancelledError:
            logger.info("Bar clock cancelled")
            raise

        finally:
            await self.cleanup()

    def request_shutdown(self) -> None:
        """
        Request graceful shutdown.

        Sets shutdown event to stop run loop.
        """
        logger.info("Shutdown requested")
        self._running = False
        self._shutdown_event.set()

    async def cleanup(self) -> None:
        """
        Cleanup resources on shutdown.

        Called automatically by run() on exit.
        """
        logger.info("Cleaning up bar clock")
        self._running = False

        # Clear callbacks
        for pair in self._callbacks:
            self._callbacks[pair].clear()

        logger.info("Bar clock cleanup complete")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def create_bar_clock(
    redis_url: str,
    pairs: List[str],
    config: Optional[ClockConfig] = None,
) -> BarClock:
    """
    Factory function to create BarClock.

    Args:
        redis_url: Redis Cloud connection URL
        pairs: List of trading pairs
        config: Optional clock configuration

    Returns:
        Initialized BarClock

    Example:
        >>> clock = await create_bar_clock(
        ...     "rediss://default:pwd@host:port",
        ...     ["BTC/USD", "ETH/USD"]
        ... )
        >>> await clock.run()
    """
    # Create Redis client
    redis_client = await redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

    # Create clock
    clock = BarClock(redis_client, pairs, config)

    return clock


def setup_signal_handlers(clock: BarClock) -> None:
    """
    Setup signal handlers for graceful shutdown.

    Registers handlers for SIGTERM and SIGINT to request
    shutdown when received.

    Args:
        clock: BarClock instance

    Example:
        >>> clock = BarClock(redis_client, pairs=["BTC/USD"])
        >>> setup_signal_handlers(clock)
        >>> await clock.run()
        # Ctrl+C will trigger graceful shutdown
    """
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, requesting shutdown")
        clock.request_shutdown()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test bar clock timing and debouncing"""
    import sys

    logging.basicConfig(level=logging.INFO)

    async def self_check():
        try:
            print("\n" + "="*70)
            print("BAR CLOCK SELF-CHECK")
            print("="*70)

            # Test 1: Compute next boundary
            print("\n[1/6] Testing boundary computation...")
            config = ClockConfig(timeframe_minutes=5)

            # Mock Redis (in-memory)
            from unittest.mock import AsyncMock
            redis_mock = AsyncMock()
            redis_mock.exists.return_value = 0
            redis_mock.setex.return_value = True

            clock = BarClock(redis_mock, pairs=["BTC/USD"], config=config)

            # Test various times
            test_cases = [
                (datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc), datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)),
                (datetime(2025, 1, 1, 12, 3, 45, tzinfo=timezone.utc), datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)),
                (datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc), datetime(2025, 1, 1, 12, 10, 0, tzinfo=timezone.utc)),
                (datetime(2025, 1, 1, 12, 7, 30, tzinfo=timezone.utc), datetime(2025, 1, 1, 12, 10, 0, tzinfo=timezone.utc)),
            ]

            for now, expected in test_cases:
                next_boundary = clock.compute_next_boundary(now)
                assert next_boundary == expected, f"Expected {expected}, got {next_boundary}"

            print("  [OK] Boundary computation correct")

            # Test 2: Compute sleep delta
            print("\n[2/6] Testing sleep delta computation...")
            now = datetime(2025, 1, 1, 12, 3, 45, tzinfo=timezone.utc)
            delta = clock.compute_sleep_delta(now)
            expected_delta = 75.0  # 1:15 until 12:05:00
            assert delta == expected_delta, f"Expected {expected_delta}, got {delta}"
            print(f"  [OK] Sleep delta: {delta}s (1:15 until boundary)")

            # Test 3: Clock skew detection
            print("\n[3/6] Testing clock skew detection...")
            expected = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
            actual_ok = datetime(2025, 1, 1, 12, 5, 1, tzinfo=timezone.utc)  # 1s drift (OK)
            actual_skew = datetime(2025, 1, 1, 12, 5, 3, tzinfo=timezone.utc)  # 3s drift (BAD)

            skew_ok = clock.detect_clock_skew(expected, actual_ok)
            assert skew_ok is False, "Should not detect skew for 1s drift"

            skew_detected = clock.detect_clock_skew(expected, actual_skew)
            assert skew_detected is True, "Should detect skew for 3s drift"

            print("  [OK] Clock skew detection working")

            # Test 4: Debouncing (mark processed)
            print("\n[4/6] Testing Redis debouncing...")
            bar_ts = datetime(2025, 1, 1, 12, 5, 0, tzinfo=timezone.utc)

            # First check: not processed
            redis_mock.exists.return_value = 0
            is_processed = await clock.is_already_processed("BTC/USD", bar_ts)
            assert is_processed is False, "Should not be processed initially"

            # Mark as processed
            await clock.mark_processed("BTC/USD", bar_ts)
            assert redis_mock.setex.called, "Should call Redis setex"

            # Second check: already processed
            redis_mock.exists.return_value = 1
            is_processed = await clock.is_already_processed("BTC/USD", bar_ts)
            assert is_processed is True, "Should be marked as processed"

            print("  [OK] Debouncing working")

            # Test 5: Callback registration
            print("\n[5/6] Testing callback registration...")
            call_count = 0

            async def test_callback(event: BarCloseEvent):
                nonlocal call_count
                call_count += 1

            clock.register_callback("BTC/USD", test_callback)
            assert len(clock._callbacks["BTC/USD"]) == 1, "Should have 1 callback"

            # Try invalid pair
            try:
                clock.register_callback("INVALID/PAIR", test_callback)
                assert False, "Should raise ValueError for invalid pair"
            except ValueError:
                pass

            print("  [OK] Callback registration working")

            # Test 6: Event emission
            print("\n[6/6] Testing event emission...")
            redis_mock.exists.return_value = 0  # Not processed
            await clock.emit_bar_close_event("BTC/USD", bar_ts)

            assert call_count == 1, f"Expected 1 callback invocation, got {call_count}"
            assert redis_mock.setex.called, "Should mark as processed"

            # Try duplicate (should skip)
            redis_mock.exists.return_value = 1  # Already processed
            await clock.emit_bar_close_event("BTC/USD", bar_ts)
            assert call_count == 1, "Should not invoke callback for duplicate"

            print("  [OK] Event emission working")

            print("\n" + "="*70)
            print("SUCCESS: BAR CLOCK SELF-CHECK PASSED")
            print("="*70)
            print("\nREQUIREMENTS VERIFIED:")
            print("  [OK] Boundary computation (5m alignment)")
            print("  [OK] Sleep delta calculation")
            print("  [OK] Clock skew detection (>2s)")
            print("  [OK] Redis debouncing (no duplicates)")
            print("  [OK] Callback registration")
            print("  [OK] Event emission with callbacks")
            print("="*70)

        except Exception as e:
            print(f"\nFAIL Bar Clock Self-Check: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    # Run async self-check
    asyncio.run(self_check())
