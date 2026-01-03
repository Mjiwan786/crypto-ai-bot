#!/usr/bin/env python3
"""
Shadow Mode Test with Live Kraken Data
=======================================

Connects to live Kraken WebSocket (public endpoint - no API keys needed),
receives real market data, generates test signals, and runs them through
the ExecutionGate in SHADOW mode.

NO REAL ORDERS ARE PLACED - this is for validation only.

Usage:
    python scripts/run_shadow_test.py

    # With custom duration
    python scripts/run_shadow_test.py --duration 60

    # Specific pairs
    python scripts/run_shadow_test.py --pairs BTC/USD,ETH/USD

Output:
    - Live market data from Kraken
    - Shadow orders recorded with full audit trail
    - Summary statistics at end
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import random

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Try to import websockets
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logger.warning("websockets not installed - using simulated data")


async def connect_kraken_ws(pairs: List[str], callback, duration: int):
    """Connect to Kraken public WebSocket and stream ticker data."""

    if not HAS_WEBSOCKETS:
        # Simulate data if websockets not available
        await simulate_market_data(pairs, callback, duration)
        return

    uri = "wss://ws.kraken.com"

    # Convert pairs to Kraken WebSocket format
    # Kraken uses XBT instead of BTC, and pairs need "/" format
    def to_kraken_pair(pair: str) -> str:
        p = pair.upper()
        # Replace BTC with XBT (Kraken's naming convention)
        p = p.replace("BTC", "XBT")
        # Ensure "/" separator exists
        if "/" not in p and len(p) >= 6:
            p = f"{p[:3]}/{p[3:]}"
        return p

    kraken_pairs = [to_kraken_pair(p) for p in pairs]

    subscribe_msg = {
        "event": "subscribe",
        "pair": kraken_pairs,
        "subscription": {"name": "ticker"}
    }

    try:
        async with websockets.connect(uri) as ws:
            logger.info(f"Connected to Kraken WebSocket")

            # Subscribe to ticker
            await ws.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to: {pairs}")

            start_time = time.time()
            msg_count = 0

            while time.time() - start_time < duration:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    data = json.loads(msg)
                    msg_count += 1

                    # Log first few messages for debugging
                    if msg_count <= 3:
                        logger.info(f"WS msg #{msg_count}: {str(data)[:100]}")

                    # Skip system messages (dicts like {"event": "..."})
                    if isinstance(data, dict):
                        if data.get("event") == "subscriptionStatus":
                            logger.info(f"Subscription: {data.get('status')} - {data.get('pair', 'N/A')}")
                        continue

                    # Parse ticker data [channelID, tickerData, channelName, pair]
                    if isinstance(data, list) and len(data) >= 4:
                        ticker = data[1]
                        pair = data[3]

                        if isinstance(ticker, dict) and "c" in ticker:
                            price = float(ticker["c"][0])  # Last trade price
                            await callback(pair, price)

                except asyncio.TimeoutError:
                    # No message in 5s, check if we should continue
                    logger.debug("No message received (5s timeout)")
                    continue
                except Exception as e:
                    logger.warning(f"WebSocket error: {e}")

            logger.info(f"Received {msg_count} WebSocket messages")

    except Exception as e:
        logger.error(f"Failed to connect to Kraken: {e}")
        logger.info("Falling back to simulated data...")
        await simulate_market_data(pairs, callback, duration)


async def simulate_market_data(pairs: List[str], callback, duration: int):
    """Simulate market data for testing without WebSocket."""

    # Base prices
    base_prices = {
        "BTC/USD": 100000.0,
        "ETH/USD": 3500.0,
        "SOL/USD": 200.0,
        "LINK/USD": 25.0,
        "XRP/USD": 2.5,
    }

    # Track current prices for realistic movement
    current_prices = {pair: base_prices.get(pair, 100.0) for pair in pairs}

    start_time = time.time()
    tick_count = 0

    while time.time() - start_time < duration:
        for pair in pairs:
            # More volatile simulation for testing (-1% to +1%)
            change = random.uniform(-0.01, 0.01)
            current_prices[pair] *= (1 + change)
            # Convert to Kraken format for callback (XBT instead of BTC)
            kraken_pair = pair.replace("BTC", "XBT").replace("/", "")
            await callback(kraken_pair, current_prices[pair])
            tick_count += 1

        await asyncio.sleep(0.5)  # Faster ticks for testing

    logger.info(f"Simulated {tick_count} ticks")


class ShadowModeTest:
    """Shadow mode test runner."""

    def __init__(self, pairs: List[str], duration: int):
        self.pairs = pairs
        self.duration = duration
        self.tick_count = 0
        self.signal_count = 0
        self.last_prices: Dict[str, float] = {}
        self.start_time = None

        # Set up shadow mode environment
        os.environ["LIVE_TRADING_ENABLED"] = "true"
        os.environ["SHADOW_EXECUTION"] = "true"
        os.environ["MODE"] = "live"
        os.environ["LIVE_TRADING_CONFIRMATION"] = "I-accept-the-risk"

        # Import after setting env
        from protections.execution_gate import get_execution_gate, reset_execution_gate
        from protections.shadow_recorder import get_shadow_recorder, reset_shadow_recorder

        reset_execution_gate()
        reset_shadow_recorder()

        self.gate = get_execution_gate()
        self.recorder = get_shadow_recorder()

    async def on_tick(self, pair: str, price: float):
        """Process a market tick."""
        self.tick_count += 1

        # Normalize pair format (Kraken uses XBT, convert back to BTC for display)
        if "/" not in pair:
            pair = f"{pair[:3]}/{pair[3:]}" if len(pair) >= 6 else pair
        # Convert XBT back to BTC for display consistency
        pair = pair.replace("XBT", "BTC")

        prev_price = self.last_prices.get(pair, price)
        self.last_prices[pair] = price

        # Calculate price change
        pct_change = (price - prev_price) / prev_price * 100 if prev_price else 0

        # Generate signal on significant price move (>0.1%)
        if abs(pct_change) > 0.1:
            await self.generate_shadow_order(pair, price, pct_change)

        # Log every 10 ticks
        if self.tick_count % 10 == 0:
            elapsed = time.time() - self.start_time
            logger.info(
                f"[{elapsed:.0f}s] Ticks: {self.tick_count} | "
                f"Signals: {self.signal_count} | "
                f"{pair}: ${price:,.2f}"
            )

    async def generate_shadow_order(self, pair: str, price: float, pct_change: float):
        """Generate a shadow order based on price movement."""
        import uuid

        side = "buy" if pct_change < 0 else "sell"  # Buy dips, sell rallies
        # Calculate size to stay under $20 notional (below $25 limit)
        target_notional = 20.0  # USD
        size = target_notional / price if price > 0 else 0.0001
        notional = size * price

        # Check execution gate
        result = self.gate.check(position_size_usd=notional)

        if result.allowed and result.shadow_mode:
            shadow_id = f"SHADOW-{uuid.uuid4().hex[:8].upper()}"

            # Record shadow order with full audit trail
            event = self.recorder.record_shadow_order(
                shadow_order_id=shadow_id,
                symbol=pair,
                side=side,
                size=size,
                price=price,
                order_type="limit",
                reason=f"price_move_{pct_change:+.2f}%",
                risk_check_passed=True,
                risk_check_details={
                    "notional_usd": notional,
                    "pct_change": pct_change,
                },
                gate_allowed=True,
            )

            self.signal_count += 1
            logger.info(f"SHADOW: {side.upper()} {size} {pair} @ ${price:,.2f} -> {shadow_id}")

    async def run(self, force_simulate: bool = False):
        """Run the shadow mode test."""
        self.start_time = time.time()

        mode_label = "SIMULATED" if force_simulate else "LIVE KRAKEN"
        print("\n" + "=" * 70)
        print(f"SHADOW MODE TEST - {mode_label} DATA")
        print("=" * 70)
        print(f"Pairs: {', '.join(self.pairs)}")
        print(f"Duration: {self.duration} seconds")
        print(f"Mode: SHADOW (no real orders)")
        print("=" * 70)

        # Log preflight status
        self.gate.log_preflight_status()

        if force_simulate:
            print("\nRunning with SIMULATED volatile data...")
            await simulate_market_data(self.pairs, self.on_tick, self.duration)
        else:
            print("\nConnecting to Kraken WebSocket...")
            try:
                await connect_kraken_ws(self.pairs, self.on_tick, self.duration)
            except Exception as e:
                logger.error(f"Error during test: {e}")

        # Print summary
        await self.print_summary()

    async def print_summary(self):
        """Print test summary."""
        elapsed = time.time() - self.start_time
        summary = self.recorder.get_summary()

        print("\n" + "=" * 70)
        print("SHADOW MODE TEST COMPLETE")
        print("=" * 70)
        print(f"Duration: {elapsed:.1f} seconds")
        print(f"Ticks processed: {self.tick_count}")
        print(f"Shadow orders: {summary['total_events']}")
        print(f"Would execute: {summary['would_execute_count']}")
        print(f"Blocked: {summary['blocked_count']}")
        print(f"Total notional: ${summary['total_notional_usd']:,.2f}")
        print("=" * 70)

        # Show recent events
        events = self.recorder.get_recent_events(limit=5)
        if events:
            print("\nLast 5 Shadow Orders:")
            print("-" * 70)
            for event in events[-5:]:
                print(f"  {event.timestamp[11:19]} | {event.side.upper():4} {event.size} {event.symbol} @ ${event.price:,.2f}")

        print("\n[OK] Shadow test complete - no real orders were placed")
        print("=" * 70)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Shadow mode test with live data")
    parser.add_argument(
        "--pairs",
        type=str,
        default="BTC/USD,ETH/USD",
        help="Comma-separated trading pairs (default: BTC/USD,ETH/USD)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Test duration in seconds (default: 30)"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Force simulated data (more volatile, for testing audit trail)"
    )
    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_args()
    pairs = [p.strip() for p in args.pairs.split(",")]

    test = ShadowModeTest(pairs=pairs, duration=args.duration)
    await test.run(force_simulate=args.simulate)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
