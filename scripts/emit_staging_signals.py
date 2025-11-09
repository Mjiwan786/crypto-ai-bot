#!/usr/bin/env python3
"""
Staging Signal Emitter - Test script for A4 soak test

Emits demo signals for all 5 pairs (BTC, ETH, SOL, ADA, AVAX) to staging stream
to verify multi-pair functionality.

USAGE:
    python scripts/emit_staging_signals.py --count 20
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

# Load staging environment
load_dotenv(".env.staging", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Demo price data for all 5 pairs
DEMO_PRICES = {
    "BTC/USD": 50000.0,
    "ETH/USD": 3000.0,
    "SOL/USD": 150.0,
    "ADA/USD": 0.50,
    "AVAX/USD": 35.0,
}

ALL_PAIRS = list(DEMO_PRICES.keys())


def generate_demo_signal(
    pair: str,
    side: Literal["long", "short"] | None = None,
    price: float | None = None,
) -> Signal:
    """Generate a realistic demo signal."""
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

    # Create signal for PAPER mode (will use signals:paper:staging due to PUBLISH_MODE=staging)
    signal = create_signal(
        pair=pair,
        side=side,
        entry=price,
        sl=sl,
        tp=tp,
        strategy="staging_test",
        confidence=confidence,
        mode="paper",  # Paper mode + PUBLISH_MODE=staging -> signals:paper:staging
    )

    return signal


async def emit_signal_to_staging(
    pair: str,
    side: Literal["long", "short"] | None = None,
    price: float | None = None,
) -> Signal:
    """Emit a single demo signal to staging stream."""
    # Create publisher with staging configuration
    publisher = SignalPublisher(
        redis_url=os.getenv("REDIS_URL"),
        redis_cert_path=os.getenv("REDIS_SSL_CA_CERT"),
    )

    try:
        # Connect
        await publisher.connect()

        # Generate signal
        signal = generate_demo_signal(pair, side, price)

        # Publish to staging stream
        entry_id = await publisher.publish(signal)

        print(f"[OK] Published {pair} {side} signal (ID: {signal.id[:8]}...)", flush=True)

        return signal

    finally:
        await publisher.close()


async def emit_multi_pair_test(count_per_pair: int = 4) -> None:
    """
    Emit signals for all 5 pairs to test multi-pair functionality.

    Args:
        count_per_pair: Number of signals to emit per pair
    """
    total = count_per_pair * len(ALL_PAIRS)

    print("=" * 70, flush=True)
    print(f"STAGING MULTI-PAIR SIGNAL TEST", flush=True)
    print("=" * 70, flush=True)
    print(f"Target Stream: signals:paper:staging", flush=True)
    print(f"Pairs: {', '.join(ALL_PAIRS)}", flush=True)
    print(f"Signals per pair: {count_per_pair}", flush=True)
    print(f"Total signals: {total}", flush=True)
    print("=" * 70, flush=True)
    print("", flush=True)

    signal_count = 0

    for round_num in range(count_per_pair):
        print(f"Round {round_num + 1}/{count_per_pair}:", flush=True)

        # Emit one signal for each pair
        for pair in ALL_PAIRS:
            signal_count += 1
            await emit_signal_to_staging(pair)
            await asyncio.sleep(0.2)  # Small delay between signals

        print("", flush=True)
        if round_num < count_per_pair - 1:
            await asyncio.sleep(1)  # Pause between rounds

    print("=" * 70, flush=True)
    print(f"[SUCCESS] Emitted {signal_count} signals to staging stream", flush=True)
    print("=" * 70, flush=True)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Emit demo signals to staging stream for all 5 pairs"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=4,
        help="Number of signals per pair (default: 4)",
    )

    args = parser.parse_args()

    # Verify staging configuration
    publish_mode = os.getenv("PUBLISH_MODE", "")
    if publish_mode != "staging":
        print(f"ERROR: PUBLISH_MODE must be 'staging', got: {publish_mode}", flush=True)
        return

    # Emit multi-pair test signals
    await emit_multi_pair_test(args.count)


if __name__ == "__main__":
    asyncio.run(main())
