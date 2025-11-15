#!/usr/bin/env python3
"""
Demo Signal Emitter (scripts/emit_demo_signal.py)

Manual smoke test script to emit demo signals for testing the full pipeline:
    signal → fill simulator → PnL tracker → Redis

USAGE:
    # Emit single signal
    python scripts/emit_demo_signal.py

    # Emit multiple signals
    python scripts/emit_demo_signal.py --count 5

    # Emit signals for specific pair
    python scripts/emit_demo_signal.py --pair ETH/USD

    # Emit signals with custom parameters
    python scripts/emit_demo_signal.py --pair BTC/USD --side long --price 50000

    # Continuous emission (every N seconds)
    python scripts/emit_demo_signal.py --continuous --interval 10
"""

import asyncio
import argparse
import logging
import os
import random
from typing import Literal
from dotenv import load_dotenv

from signals.schema import create_signal, Signal
from signals.publisher import SignalPublisher

load_dotenv(".env.prod")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Demo price data (rough market prices)
DEMO_PRICES = {
    "BTC/USD": 50000.0,
    "ETH/USD": 3000.0,
    "SOL/USD": 150.0,
    "ADA/USD": 0.50,
}


def generate_demo_signal(
    pair: str,
    side: Literal["long", "short"] | None = None,
    price: float | None = None,
) -> Signal:
    """
    Generate a realistic demo signal.

    Args:
        pair: Trading pair
        side: Trade side (random if None)
        price: Entry price (uses demo price if None)

    Returns:
        Signal instance
    """
    # Use demo price if not specified
    if price is None:
        price = DEMO_PRICES.get(pair, 1000.0)

    # Random side if not specified
    if side is None:
        side = random.choice(["long", "short"])

    # Calculate stop loss and take profit
    if side == "long":
        sl = price * 0.98  # 2% stop loss
        tp = price * 1.04  # 4% take profit
    else:
        sl = price * 1.02  # 2% stop loss
        tp = price * 0.96  # 4% take profit

    # Random confidence
    confidence = random.uniform(0.6, 0.9)

    # Create signal
    signal = create_signal(
        pair=pair,
        side=side,
        entry=price,
        sl=sl,
        tp=tp,
        strategy="demo_emitter",
        confidence=confidence,
        mode="paper",
    )

    return signal


async def emit_signal(
    pair: str,
    side: Literal["long", "short"] | None = None,
    price: float | None = None,
) -> Signal:
    """
    Emit a single demo signal to Redis.

    Args:
        pair: Trading pair
        side: Trade side (random if None)
        price: Entry price (uses demo price if None)

    Returns:
        Published signal
    """
    # Create publisher
    publisher = SignalPublisher(
        redis_url=os.getenv("REDIS_URL"),
        redis_cert_path=os.getenv("REDIS_TLS_CERT_PATH"),
    )

    try:
        # Connect
        await publisher.connect()

        # Generate signal
        signal = generate_demo_signal(pair, side, price)

        # Publish
        entry_id = await publisher.publish(signal)

        print(f"\n[OK] Published signal to Redis")
        print(f"  Signal ID: {signal.id}")
        print(f"  Stream: {signal.get_stream_key()}")
        print(f"  Entry ID: {entry_id}")
        print(f"  Pair: {signal.pair}")
        print(f"  Side: {signal.side}")
        print(f"  Entry: ${signal.entry:.2f}")
        print(f"  Stop Loss: ${signal.sl:.2f}")
        print(f"  Take Profit: ${signal.tp:.2f}")
        print(f"  Strategy: {signal.strategy}")
        print(f"  Confidence: {signal.confidence:.2f}")

        return signal

    finally:
        await publisher.close()


async def emit_multiple_signals(count: int, pair: str) -> None:
    """
    Emit multiple demo signals.

    Args:
        count: Number of signals to emit
        pair: Trading pair
    """
    print(f"\n{'=' * 70}")
    print(f"  EMITTING {count} DEMO SIGNALS FOR {pair}")
    print(f"{'=' * 70}")

    for i in range(count):
        print(f"\n[Signal {i + 1}/{count}]")
        await emit_signal(pair)
        if i < count - 1:
            await asyncio.sleep(0.5)  # Small delay between signals

    print(f"\n{'=' * 70}")
    print(f"[OK] Emitted {count} signals successfully")
    print(f"{'=' * 70}")


async def emit_continuous(interval: int, pair: str) -> None:
    """
    Emit signals continuously at fixed interval.

    Args:
        interval: Interval in seconds
        pair: Trading pair
    """
    print(f"\n{'=' * 70}")
    print(f"  CONTINUOUS SIGNAL EMISSION (every {interval}s)")
    print(f"  Press Ctrl+C to stop")
    print(f"{'=' * 70}")

    count = 0
    try:
        while True:
            count += 1
            print(f"\n[Signal #{count}]")
            await emit_signal(pair)
            await asyncio.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\n{'=' * 70}")
        print(f"[OK] Stopped after emitting {count} signals")
        print(f"{'=' * 70}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Emit demo signals for testing signal → PnL pipeline"
    )
    parser.add_argument(
        "--pair",
        type=str,
        default="BTC/USD",
        choices=list(DEMO_PRICES.keys()),
        help="Trading pair (default: BTC/USD)",
    )
    parser.add_argument(
        "--side",
        type=str,
        choices=["long", "short"],
        help="Trade side (default: random)",
    )
    parser.add_argument(
        "--price", type=float, help="Entry price (default: use demo price)"
    )
    parser.add_argument(
        "--count", type=int, default=1, help="Number of signals to emit (default: 1)"
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Emit signals continuously at fixed interval",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Interval in seconds for continuous mode (default: 10)",
    )

    args = parser.parse_args()

    # Emit signals
    if args.continuous:
        await emit_continuous(args.interval, args.pair)
    elif args.count > 1:
        await emit_multiple_signals(args.count, args.pair)
    else:
        await emit_signal(args.pair, args.side, args.price)


if __name__ == "__main__":
    asyncio.run(main())
