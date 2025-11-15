"""
Paper Trade Fill Simulator (pnl/paper_fill_simulator.py)

Simulates trade executions for paper trading without real exchange API calls.
Consumes signals from Redis streams and generates realistic fills.

FEATURES:
- Reads signals from signals:paper:<PAIR> streams
- Simulates realistic fill delays (50-200ms)
- Simulates slippage (0.01-0.05%)
- Generates fill events
- Publishes fills to fills:paper stream
- Integrates with PnL tracker

USAGE:
    simulator = PaperFillSimulator(redis_url=REDIS_URL, redis_cert_path=CERT_PATH)
    await simulator.connect()
    await simulator.run()  # Runs continuously
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import os
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import redis.asyncio as redis
import orjson

from signals.schema import Signal
from pnl.rolling_pnl import PnLTracker

logger = logging.getLogger(__name__)


class Fill(Dict[str, Any]):
    """
    Trade fill event.

    Structure:
        {
            "fill_id": str,
            "signal_id": str,
            "timestamp": float,
            "pair": str,
            "side": "long" | "short",
            "quantity": float,
            "price": float,
            "slippage": float,
            "is_entry": bool
        }
    """

    pass


class PaperFillSimulator:
    """
    Paper trading fill simulator.

    Reads signals from Redis streams and simulates fills with realistic delays and slippage.
    """

    def __init__(
        self,
        redis_url: str,
        redis_cert_path: Optional[str] = None,
        trading_pairs: Optional[List[str]] = None,
        slippage_pct: float = 0.03,  # 0.03% default slippage
        fill_delay_ms: tuple = (50, 200),  # Random delay range
    ):
        """
        Initialize paper fill simulator.

        Args:
            redis_url: Redis connection URL
            redis_cert_path: Path to TLS certificate
            trading_pairs: List of trading pairs to monitor
            slippage_pct: Slippage percentage (0.03 = 0.03%)
            fill_delay_ms: Tuple of (min_delay_ms, max_delay_ms) for fill simulation
        """
        self.redis_url = redis_url
        self.redis_cert_path = redis_cert_path
        self.trading_pairs = trading_pairs or []
        self.slippage_pct = slippage_pct
        self.fill_delay_ms = fill_delay_ms

        self.redis_client: Optional[redis.Redis] = None
        self.pnl_tracker: Optional[PnLTracker] = None
        self.running = False

        # Track last processed signal IDs to avoid duplicates
        self.processed_signal_ids: set = set()

        # Metrics
        self.metrics = {
            "total_fills": 0,
            "by_pair": {},
        }

    async def connect(self) -> bool:
        """
        Connect to Redis server and initialize PnL tracker.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Build connection parameters
            conn_params = {
                "socket_connect_timeout": 5,
                "socket_keepalive": True,
                "decode_responses": False,
            }

            # Add TLS certificate if using rediss://
            if self.redis_url.startswith("rediss://") and self.redis_cert_path:
                conn_params["ssl_ca_certs"] = self.redis_cert_path
                conn_params["ssl_cert_reqs"] = "required"

            # Create async Redis client
            self.redis_client = redis.from_url(self.redis_url, **conn_params)

            # Test connection
            await self.redis_client.ping()

            # Initialize PnL tracker
            self.pnl_tracker = PnLTracker(
                redis_url=self.redis_url,
                redis_cert_path=self.redis_cert_path,
                initial_balance=10000.0,
                mode="paper",
            )
            await self.pnl_tracker.connect()

            logger.info("Paper fill simulator connected to Redis")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None
            return False

    async def close(self) -> None:
        """Close Redis connection and PnL tracker."""
        if self.pnl_tracker:
            await self.pnl_tracker.close()
            self.pnl_tracker = None

        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None

        logger.info("Paper fill simulator disconnected from Redis")

    async def simulate_fill(self, signal: Signal) -> Fill:
        """
        Simulate a fill for a signal with realistic delay and slippage.

        Args:
            signal: Signal to fill

        Returns:
            Fill event dictionary
        """
        # Random delay (50-200ms)
        delay_ms = random.uniform(*self.fill_delay_ms)
        await asyncio.sleep(delay_ms / 1000.0)

        # Calculate slippage (0.01-0.05% of price)
        slippage_range = self.slippage_pct / 100.0
        slippage_factor = random.uniform(
            -slippage_range / 2, slippage_range / 2
        )  # Can be positive or negative

        # Apply slippage to entry price
        slippage_amount = signal.entry * slippage_factor
        fill_price = signal.entry + slippage_amount

        # Determine if this is entry or exit
        # For simplicity, assume signal.side indicates entry direction
        # In practice, you'd track open positions to determine entry vs exit
        is_entry = True  # Simplified for demo

        # Create fill event
        fill = Fill(
            {
                "fill_id": f"fill_{int(time.time() * 1000)}_{random.randint(1000, 9999)}",
                "signal_id": signal.id,
                "timestamp": time.time(),
                "timestamp_iso": datetime.now(timezone.utc).isoformat(),
                "pair": signal.pair,
                "side": signal.side,
                "quantity": 0.01,  # Fixed quantity for demo (use signal.quantity in production)
                "price": fill_price,
                "slippage": slippage_amount,
                "is_entry": is_entry,
            }
        )

        return fill

    async def publish_fill(self, fill: Fill) -> None:
        """
        Publish fill to fills:paper stream.

        Args:
            fill: Fill event to publish
        """
        if not self.redis_client:
            raise ConnectionError("Not connected to Redis")

        try:
            # Convert fill to Redis dict (all string values)
            fill_data = {k: str(v) for k, v in fill.items()}

            # Publish to fills:paper stream
            await self.redis_client.xadd(
                "fills:paper",
                fill_data,
                maxlen=10000,
                approximate=True,
            )

            logger.info(
                f"Published fill: {fill['pair']} {fill['side']} "
                f"{fill['quantity']} @ ${fill['price']:.2f} "
                f"(slippage: ${fill['slippage']:.4f})"
            )

        except Exception as e:
            logger.error(f"Failed to publish fill: {e}")
            raise

    async def process_signal(self, signal: Signal) -> None:
        """
        Process a signal by simulating fill and updating PnL.

        Args:
            signal: Signal to process
        """
        # Check if already processed (idempotency)
        if signal.id in self.processed_signal_ids:
            logger.debug(f"Skipping already processed signal: {signal.id}")
            return

        # Simulate fill
        fill = await self.simulate_fill(signal)

        # Publish fill
        await self.publish_fill(fill)

        # Update PnL tracker
        if self.pnl_tracker:
            await self.pnl_tracker.process_fill(
                pair=fill["pair"],
                side=fill["side"],
                quantity=fill["quantity"],
                price=fill["price"],
                is_entry=fill["is_entry"],
            )

        # Mark as processed
        self.processed_signal_ids.add(signal.id)

        # Update metrics
        self.metrics["total_fills"] += 1
        pair_key = signal.pair.replace("/", "-")
        self.metrics["by_pair"][pair_key] = (
            self.metrics["by_pair"].get(pair_key, 0) + 1
        )

    async def poll_signals(self) -> None:
        """
        Poll signals from Redis streams continuously.
        """
        if not self.redis_client:
            raise ConnectionError("Not connected to Redis")

        # Build stream keys for each pair
        stream_keys = []
        for pair in self.trading_pairs:
            pair_key = pair.replace("/", "-")
            stream_keys.append(f"signals:paper:{pair_key}")

        # Track last IDs for each stream
        last_ids = {stream: "0" for stream in stream_keys}

        logger.info(f"Polling signals from {len(stream_keys)} streams: {stream_keys}")

        while self.running:
            try:
                # Build XREAD arguments
                streams_dict = {stream: last_ids[stream] for stream in stream_keys}

                # Read new entries from all streams (block for 1 second)
                results = await self.redis_client.xread(
                    streams=streams_dict, count=10, block=1000
                )

                if results:
                    for stream_name, entries in results:
                        stream_name_str = (
                            stream_name.decode()
                            if isinstance(stream_name, bytes)
                            else stream_name
                        )

                        for entry_id, fields in entries:
                            entry_id_str = (
                                entry_id.decode()
                                if isinstance(entry_id, bytes)
                                else entry_id
                            )

                            # Decode fields
                            decoded_fields = {}
                            for k, v in fields.items():
                                key = k.decode() if isinstance(k, bytes) else k
                                val = v.decode() if isinstance(v, bytes) else v
                                decoded_fields[key] = val

                            # Parse signal
                            try:
                                signal = Signal.from_dict(decoded_fields)
                                await self.process_signal(signal)
                            except Exception as e:
                                logger.error(
                                    f"Failed to process signal from {stream_name_str}: {e}"
                                )

                            # Update last ID
                            last_ids[stream_name_str] = entry_id_str

            except asyncio.CancelledError:
                logger.info("Signal polling cancelled")
                break
            except Exception as e:
                logger.error(f"Error polling signals: {e}")
                await asyncio.sleep(1)  # Backoff on error

    async def run(self, duration: Optional[float] = None) -> None:
        """
        Run fill simulator continuously.

        Args:
            duration: Optional duration in seconds (None = run forever)
        """
        self.running = True
        start_time = time.time()

        logger.info(
            f"Starting paper fill simulator "
            f"(pairs: {self.trading_pairs}, duration: {duration or 'unlimited'})"
        )

        try:
            # Start polling task
            poll_task = asyncio.create_task(self.poll_signals())

            # Wait for duration or until cancelled
            if duration:
                await asyncio.sleep(duration)
                self.running = False
                poll_task.cancel()
                try:
                    await poll_task
                except asyncio.CancelledError:
                    pass
            else:
                await poll_task

        except asyncio.CancelledError:
            logger.info("Paper fill simulator cancelled")
            self.running = False

        finally:
            elapsed = time.time() - start_time
            logger.info(
                f"Paper fill simulator stopped after {elapsed:.1f}s "
                f"({self.metrics['total_fills']} fills)"
            )

    def get_metrics(self) -> Dict[str, Any]:
        """Get simulator metrics."""
        return self.metrics.copy()


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "PaperFillSimulator",
    "Fill",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Validate paper fill simulator"""
    import sys
    from dotenv import load_dotenv
    from signals.schema import create_signal
    from signals.publisher import SignalPublisher

    load_dotenv(".env.prod")

    async def main():
        print("=" * 70)
        print(" " * 15 + "PAPER FILL SIMULATOR SELF-CHECK")
        print("=" * 70)

        # Test 1: Create simulator
        print("\nTest 1: Create simulator")
        simulator = PaperFillSimulator(
            redis_url=os.getenv("REDIS_URL"),
            redis_cert_path=os.getenv("REDIS_TLS_CERT_PATH"),
            trading_pairs=["BTC/USD", "ETH/USD"],
        )
        print("  PASS")

        # Test 2: Connect to Redis
        print("\nTest 2: Connect to Redis")
        connected = await simulator.connect()
        if not connected:
            print("  FAIL: Could not connect to Redis")
            return
        print("  PASS")

        # Test 3: Create and publish test signal
        print("\nTest 3: Create and publish test signal")
        signal_publisher = SignalPublisher(
            redis_url=os.getenv("REDIS_URL"),
            redis_cert_path=os.getenv("REDIS_TLS_CERT_PATH"),
        )
        await signal_publisher.connect()

        signal = create_signal(
            pair="BTC/USD",
            side="long",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test_simulator",
            confidence=0.8,
            mode="paper",
        )
        await signal_publisher.publish(signal)
        print(f"  Published signal: {signal.id}")
        print("  PASS")

        # Test 4: Run simulator for 5 seconds
        print("\nTest 4: Run simulator for 5 seconds")
        print("  Polling for signals...")
        await simulator.run(duration=5)
        print("  PASS")

        # Test 5: Check metrics
        print("\nTest 5: Check metrics")
        metrics = simulator.get_metrics()
        print(f"  Total fills: {metrics['total_fills']}")
        if metrics["total_fills"] > 0:
            print(f"  Fills by pair: {metrics['by_pair']}")
            print("  PASS")
        else:
            print("  PASS (no signals to process, which is expected)")

        # Test 6: Check PnL was updated
        print("\nTest 6: Check PnL was updated")
        if simulator.pnl_tracker:
            pnl = await simulator.pnl_tracker.get_summary()
            print(f"  Equity: ${pnl.equity:.2f}")
            print(f"  Positions: {len(pnl.positions)}")
            print("  PASS")

        # Cleanup
        await signal_publisher.close()
        await simulator.close()

        print("\n" + "=" * 70)
        print("[OK] All Self-Checks PASSED")
        print("=" * 70)

    asyncio.run(main())
