#!/usr/bin/env python3
"""
Spread Stream Publisher - Wires SpreadCalculator to Live Orderbook

Subscribes to Kraken orderbook streams, calculates bid-ask spreads,
and publishes to Redis for consumption by execution agents.

Features:
- Real-time spread calculation from orderbook top-of-book
- Redis stream publishing with spread_bps metric
- Circuit breaker for wide spreads
- Latency tracking for monitoring
- Compatible with crypto-bot conda environment

Usage:
    from agents.infrastructure.spread_stream_publisher import SpreadStreamPublisher

    # Create publisher
    publisher = SpreadStreamPublisher(redis_client)

    # Wire to orderbook callback
    kraken_client.register_callback("book", publisher.on_orderbook_update)

    # Start streaming
    await kraken_client.start()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from utils.spread_calculator import SpreadCalculator, SpreadData

logger = logging.getLogger(__name__)


@dataclass
class SpreadStreamConfig:
    """Configuration for spread stream publisher"""

    # Spread thresholds
    max_spread_bps: float = 20.0  # Circuit breaker threshold
    alert_spread_bps: float = 15.0  # Warning threshold

    # Performance
    max_latency_ms: float = 50.0  # Max calculation latency
    batch_size: int = 1  # Publish every N updates (1 = real-time)

    # Monitoring
    log_interval_s: int = 60  # Log stats every N seconds
    enable_circuit_breaker: bool = True


class SpreadStreamPublisher:
    """
    Publishes real-time spread data from orderbook to Redis streams.

    Integrates SpreadCalculator with Kraken WebSocket orderbook feed.
    """

    def __init__(
        self,
        redis_client=None,
        config: Optional[SpreadStreamConfig] = None,
    ):
        """
        Initialize spread stream publisher.

        Args:
            redis_client: Redis client for stream publishing
            config: Publisher configuration
        """
        self.config = config or SpreadStreamConfig()
        self.spread_calculator = SpreadCalculator(redis_client=redis_client)

        # Statistics
        self.stats = {
            "updates_received": 0,
            "spreads_published": 0,
            "wide_spread_alerts": 0,
            "circuit_breaker_trips": 0,
            "last_spread_bps": 0.0,
            "avg_latency_ms": 0.0,
            "last_log_time": time.time(),
        }

        # Circuit breaker state
        self.circuit_breaker_active = False
        self.circuit_breaker_count = 0
        self.circuit_breaker_threshold = 3  # Trip after N consecutive wide spreads

        logger.info(
            f"SpreadStreamPublisher initialized: "
            f"max_spread={self.config.max_spread_bps} bps, "
            f"circuit_breaker={'enabled' if self.config.enable_circuit_breaker else 'disabled'}"
        )

    async def on_orderbook_update(self, pair: str, book_data: dict) -> None:
        """
        Callback for orderbook updates from Kraken WebSocket.

        Args:
            pair: Trading pair (e.g., "BTC/USD")
            book_data: Orderbook data with bids/asks
        """
        start_time = time.time()
        self.stats["updates_received"] += 1

        try:
            # Extract top-of-book bid/ask
            bids = book_data.get("bids", [])
            asks = book_data.get("asks", [])

            if not bids or not asks:
                logger.debug(f"Empty orderbook for {pair}, skipping spread calculation")
                return

            # Get best bid/ask
            best_bid = float(bids[0][0])  # [price, volume, timestamp]
            best_ask = float(asks[0][0])

            # Calculate and publish spread
            spread_data = self.spread_calculator.publish_spread(
                symbol=pair,
                bid=best_bid,
                ask=best_ask,
                timestamp_ms=int(book_data.get("received_at", time.time()) * 1000),
            )

            if spread_data:
                self.stats["spreads_published"] += 1
                self.stats["last_spread_bps"] = spread_data.spread_bps

                # Update latency stats
                latency_ms = (time.time() - start_time) * 1000
                self.stats["avg_latency_ms"] = (
                    0.9 * self.stats["avg_latency_ms"] + 0.1 * latency_ms
                )

                # Check spread thresholds
                await self._check_spread_thresholds(pair, spread_data)

                # Check latency
                if latency_ms > self.config.max_latency_ms:
                    logger.warning(
                        f"Slow spread calculation: {latency_ms:.2f}ms > "
                        f"{self.config.max_latency_ms:.2f}ms for {pair}"
                    )

            # Periodic stats logging
            await self._log_stats_if_needed()

        except Exception as e:
            logger.error(f"Error processing orderbook update for {pair}: {e}")

    async def _check_spread_thresholds(self, pair: str, spread_data: SpreadData) -> None:
        """
        Check if spread exceeds thresholds and trigger alerts/circuit breakers.

        Args:
            pair: Trading pair
            spread_data: Calculated spread data
        """
        spread_bps = spread_data.spread_bps

        # Alert threshold
        if spread_bps > self.config.alert_spread_bps:
            self.stats["wide_spread_alerts"] += 1
            logger.warning(
                f"Wide spread alert: {pair} spread={spread_bps:.2f} bps "
                f"(alert threshold={self.config.alert_spread_bps} bps)"
            )

        # Circuit breaker threshold
        if self.config.enable_circuit_breaker and spread_bps > self.config.max_spread_bps:
            self.circuit_breaker_count += 1

            if self.circuit_breaker_count >= self.circuit_breaker_threshold:
                if not self.circuit_breaker_active:
                    self.circuit_breaker_active = True
                    self.stats["circuit_breaker_trips"] += 1
                    logger.error(
                        f"CIRCUIT BREAKER TRIPPED: {pair} spread={spread_bps:.2f} bps > "
                        f"{self.config.max_spread_bps} bps "
                        f"({self.circuit_breaker_count} consecutive violations)"
                    )

                    # Notify downstream systems (execution agents should pause)
                    await self._notify_circuit_breaker(pair, spread_bps)
        else:
            # Reset circuit breaker if spread returns to normal
            if self.circuit_breaker_active:
                logger.info(
                    f"Circuit breaker reset: {pair} spread={spread_bps:.2f} bps "
                    f"returned to normal"
                )
            self.circuit_breaker_count = 0
            self.circuit_breaker_active = False

    async def _notify_circuit_breaker(self, pair: str, spread_bps: float) -> None:
        """
        Notify downstream systems of circuit breaker trip.

        Args:
            pair: Trading pair
            spread_bps: Spread in basis points
        """
        # Publish circuit breaker event to Redis
        if self.spread_calculator.redis_client:
            try:
                stream_key = f"kraken:circuit_breaker:{pair.replace('/', '-')}"
                payload = {
                    "event": "spread_circuit_breaker",
                    "pair": pair,
                    "spread_bps": f"{spread_bps:.2f}",
                    "threshold_bps": str(self.config.max_spread_bps),
                    "timestamp": str(int(time.time() * 1000)),
                    "action": "pause_trading",
                }

                await self.spread_calculator.redis_client.xadd(
                    stream_key, payload, maxlen=1000
                )
                logger.info(f"Published circuit breaker event to {stream_key}")

            except Exception as e:
                logger.error(f"Failed to publish circuit breaker event: {e}")

    async def _log_stats_if_needed(self) -> None:
        """Log statistics periodically"""
        current_time = time.time()
        time_since_log = current_time - self.stats["last_log_time"]

        if time_since_log >= self.config.log_interval_s:
            logger.info(
                f"Spread stream stats: "
                f"updates={self.stats['updates_received']}, "
                f"published={self.stats['spreads_published']}, "
                f"last_spread={self.stats['last_spread_bps']:.2f} bps, "
                f"avg_latency={self.stats['avg_latency_ms']:.2f}ms, "
                f"wide_spread_alerts={self.stats['wide_spread_alerts']}, "
                f"circuit_breaker_trips={self.stats['circuit_breaker_trips']}"
            )
            self.stats["last_log_time"] = current_time

    def get_stats(self) -> dict:
        """
        Get publisher statistics.

        Returns:
            Dict with statistics
        """
        return {
            **self.stats,
            "circuit_breaker_active": self.circuit_breaker_active,
            "circuit_breaker_count": self.circuit_breaker_count,
        }

    def reset_circuit_breaker(self) -> None:
        """Manually reset circuit breaker (use with caution)"""
        logger.warning("Manually resetting circuit breaker")
        self.circuit_breaker_active = False
        self.circuit_breaker_count = 0


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test spread stream publisher"""
    import sys

    logging.basicConfig(level=logging.INFO)

    try:
        # Test without Redis
        publisher = SpreadStreamPublisher()

        # Simulate orderbook update
        mock_book_data = {
            "pair": "BTC/USD",
            "bids": [[50000.0, 1.5, 1234567890.0]],
            "asks": [[50010.0, 2.0, 1234567890.0]],
            "received_at": time.time(),
        }

        # Process update
        asyncio.run(publisher.on_orderbook_update("BTC/USD", mock_book_data))

        # Check stats
        stats = publisher.get_stats()
        assert stats["updates_received"] == 1
        # Note: SpreadCalculator still processes without Redis, just doesn't publish
        assert stats["last_spread_bps"] > 0, "Should calculate spread"

        print("\nPASS Spread Stream Publisher Self-Check:")
        print(f"  - Updates received: {stats['updates_received']}")
        print(f"  - Spreads published: {stats['spreads_published']}")
        print(f"  - Last spread: {stats['last_spread_bps']:.2f} bps")
        print(f"  - Avg latency: {stats['avg_latency_ms']:.2f}ms")
        print(f"  - Circuit breaker active: {stats['circuit_breaker_active']}")

        # Test circuit breaker
        wide_spread_book = {
            "pair": "BTC/USD",
            "bids": [[50000.0, 1.5, 1234567890.0]],
            "asks": [[50150.0, 2.0, 1234567890.0]],  # 30 bps spread
            "received_at": time.time(),
        }

        # Trigger circuit breaker (3 consecutive wide spreads)
        for _ in range(3):
            asyncio.run(publisher.on_orderbook_update("BTC/USD", wide_spread_book))

        stats = publisher.get_stats()
        assert stats["circuit_breaker_active"], "Circuit breaker should be active"
        print(f"  - Circuit breaker test: PASSED (tripped after 3 wide spreads)")

        print("\nAll spread stream publisher tests passed!")

    except Exception as e:
        print(f"\nFAIL Spread Stream Publisher Self-Check: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
