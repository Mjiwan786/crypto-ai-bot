"""
Synthetic Bar Generator - Consumes trades and generates OHLCV bars

This process:
1. Consumes from kraken:trade:* streams (raw trade ticks)
2. Aggregates into time buckets using SyntheticBarBuilder
3. Publishes to kraken:ohlc:<timeframe>:<symbol> streams

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import asyncio
import os
import sys
from decimal import Decimal
from typing import Dict

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

import redis.asyncio as redis

from utils.synthetic_bars import Trade, create_bar_builder


async def consume_trades_and_generate_bars():
    """Main bar generator loop."""

    print("=" * 70)
    print("SYNTHETIC BAR GENERATOR")
    print("=" * 70)
    print()

    # Configuration
    redis_url = os.getenv("REDIS_URL")
    redis_ca_cert = os.getenv("REDIS_SSL_CA_CERT", "config/certs/redis_ca.pem")
    trading_pairs = os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD,SOL/USD,ADA/USD").split(",")
    timeframes = os.getenv("TIMEFRAMES", "15s,1m,5m").split(",")
    enable_5s = os.getenv("ENABLE_5S_BARS", "false").lower() == "true"

    if enable_5s and "5s" not in timeframes:
        timeframes.insert(0, "5s")

    print(f"Configuration:")
    print(f"  Redis URL: {redis_url[:30]}...")
    print(f"  Trading pairs: {', '.join(trading_pairs)}")
    print(f"  Timeframes: {', '.join(timeframes)}")
    print(f"  Enable 5s bars: {enable_5s}")
    print()

    # Create Redis client
    redis_client = await redis.from_url(
        redis_url,
        ssl_cert_reqs="required",
        ssl_ca_certs=redis_ca_cert,
        decode_responses=False,  # Keep as bytes for stream processing
    )

    # Symbol mapping (Kraken uses XBT for BTC)
    symbol_map = {
        "BTC/USD": "XBT-USD",
        "ETH/USD": "ETH-USD",
        "SOL/USD": "SOL-USD",
        "ADA/USD": "ADA-USD",
    }

    # Create bar builders for each pair/timeframe combination
    builders: Dict[str, Dict[str, any]] = {}

    for pair in trading_pairs:
        kraken_symbol = symbol_map.get(pair, pair.replace("/", "-"))
        builders[pair] = {}

        for tf in timeframes:
            # Only process second-based timeframes for now
            if not tf.endswith("s"):
                print(f"[SKIP] Timeframe {tf} not supported (seconds only)")
                continue

            builder = create_bar_builder(
                timeframe=tf,
                symbol=pair,
                redis_client=redis_client,
            )
            builders[pair][tf] = builder
            print(f"[OK] Created {tf} bar builder for {pair}")

    print()
    print(f"Starting bar generation...")
    print(f"Consuming from: kraken:trade:* streams")
    print(f"Publishing to: kraken:ohlc:<tf>:<symbol> streams")
    print()

    # Track last processed ID for each stream
    last_ids = {}
    for pair in trading_pairs:
        kraken_symbol = symbol_map.get(pair, pair.replace("/", "-"))
        stream_key = f"kraken:trade:{kraken_symbol}"
        last_ids[stream_key] = "0-0"  # Start from beginning

    # Main processing loop
    bars_generated = 0
    trades_processed = 0

    while True:
        try:
            # Read from all trade streams
            streams = {k: v for k, v in last_ids.items()}

            entries = await redis_client.xread(
                streams,
                count=100,
                block=1000,  # Block for 1 second
            )

            if entries:
                for stream_bytes, messages in entries:
                    stream = stream_bytes.decode() if isinstance(stream_bytes, bytes) else stream_bytes

                    # Extract symbol from stream key
                    kraken_symbol = stream.split(":")[-1]

                    # Map back to our format
                    pair = None
                    for p, ks in symbol_map.items():
                        if ks == kraken_symbol:
                            pair = p
                            break

                    if not pair:
                        continue

                    for message_id_bytes, data in messages:
                        message_id = message_id_bytes.decode() if isinstance(message_id_bytes, bytes) else message_id_bytes

                        # Decode data
                        decoded_data = {}
                        for k, v in data.items():
                            key = k.decode() if isinstance(k, bytes) else k
                            value = v.decode() if isinstance(v, bytes) else v
                            decoded_data[key] = value

                        # Create Trade object
                        try:
                            trade = Trade(
                                timestamp=float(decoded_data.get("timestamp", 0)),
                                price=Decimal(str(decoded_data.get("price", 0))),
                                volume=Decimal(str(decoded_data.get("volume", 0))),
                                side=decoded_data.get("side", "unknown"),
                            )

                            # Add to all builders for this pair
                            for tf, builder in builders.get(pair, {}).items():
                                bar = await builder.add_trade(trade)
                                if bar:
                                    bars_generated += 1
                                    print(
                                        f"[{tf}] {pair}: Bar generated "
                                        f"O={bar.open} H={bar.high} L={bar.low} C={bar.close} "
                                        f"V={bar.volume:.2f} trades={bar.trade_count}"
                                    )

                            trades_processed += 1

                        except Exception as e:
                            print(f"[ERROR] Processing trade: {e}")
                            continue

                        # Update last ID
                        last_ids[stream] = message_id

            # Print stats every 100 trades
            if trades_processed > 0 and trades_processed % 100 == 0:
                print(f"\n[STATS] Processed {trades_processed} trades, generated {bars_generated} bars\n")

        except KeyboardInterrupt:
            print("\n[!] Shutting down...")
            break
        except Exception as e:
            print(f"[ERROR] Main loop: {e}")
            await asyncio.sleep(1)

    # Cleanup
    await redis_client.close()
    print(f"\n[DONE] Final stats: {trades_processed} trades processed, {bars_generated} bars generated")


if __name__ == "__main__":
    asyncio.run(consume_trades_and_generate_bars())
