#!/usr/bin/env python3
"""
Live Kraken Signal Generator - Generates signals from REAL Kraken market data

Features:
- Connects to Kraken WebSocket for real-time price data
- Generates signals based on actual market prices
- Publishes to Redis streams with current prices
- Rate limiting (max 2 signals/second)
- Separate from backtested data
"""
import asyncio
import json
import os
import random
import sys
import time
import websockets
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import redis.asyncio as aioredis

# Load environment
env_file = project_root / ".env.prod"
if env_file.exists():
    load_dotenv(env_file)

REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_CA_CERT = os.getenv("REDIS_CA_CERT", "./config/certs/redis_ca.pem")
MODE = os.getenv("MODE", "paper")

# Kraken WebSocket URL
KRAKEN_WS_URL = "wss://ws.kraken.com"

# Trading pairs with Kraken mapping
PAIRS = {
    "BTC/USD": "XBT/USD",
    "ETH/USD": "ETH/USD",
    "SOL/USD": "SOL/USD",
    "MATIC/USD": "MATIC/USD",
    "LINK/USD": "LINK/USD",
}

# Rate limiting
MAX_PUBLISH_RATE = 2.0  # signals per second
MIN_PUBLISH_INTERVAL = 1.0 / MAX_PUBLISH_RATE

# Market data cache
latest_prices = {}
latest_spreads = {}


async def kraken_ws_listener():
    """Listen to Kraken WebSocket for real-time price data"""
    global latest_prices, latest_spreads

    while True:
        try:
            async with websockets.connect(KRAKEN_WS_URL) as ws:
                # Subscribe to ticker data for all pairs
                kraken_pairs = list(PAIRS.values())
                subscribe_msg = {
                    "event": "subscribe",
                    "pair": kraken_pairs,
                    "subscription": {"name": "ticker"}
                }
                await ws.send(json.dumps(subscribe_msg))
                print(f"📡 Subscribed to Kraken WebSocket for {len(kraken_pairs)} pairs")

                async for message in ws:
                    try:
                        data = json.loads(message)

                        # Skip system messages
                        if isinstance(data, dict):
                            continue

                        # Parse ticker data: [channelID, data, "ticker", "PAIR"]
                        if len(data) >= 4 and data[2] == "ticker":
                            pair_name = data[3]
                            ticker = data[1]

                            # Map Kraken pair back to our format
                            our_pair = None
                            for our_name, kraken_name in PAIRS.items():
                                if kraken_name == pair_name:
                                    our_pair = our_name
                                    break

                            if our_pair:
                                # Extract current price and spread
                                ask = float(ticker.get('a', [0])[0]) if isinstance(ticker.get('a'), list) else float(ticker.get('a', 0))
                                bid = float(ticker.get('b', [0])[0]) if isinstance(ticker.get('b'), list) else float(ticker.get('b', 0))
                                last = float(ticker.get('c', [0])[0]) if isinstance(ticker.get('c'), list) else float(ticker.get('c', 0))

                                latest_prices[our_pair] = last if last > 0 else (ask + bid) / 2
                                latest_spreads[our_pair] = ask - bid

                                # Log price updates occasionally
                                if random.random() < 0.1:  # 10% of updates
                                    print(f"💰 {our_pair}: ${latest_prices[our_pair]:.2f} (spread: ${latest_spreads[our_pair]:.4f})")

                    except Exception as e:
                        print(f"⚠️ Error parsing message: {e}")
                        continue

        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            print("Reconnecting in 5s...")
            await asyncio.sleep(5)


async def generate_live_signals():
    """Generate trading signals based on real Kraken market data"""
    global latest_prices, latest_spreads

    # Resolve CA certificate
    ca_cert_path = Path(REDIS_CA_CERT)
    if not ca_cert_path.is_absolute():
        ca_cert_path = project_root / ca_cert_path

    # Create Redis client
    client = await aioredis.from_url(
        REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        ssl_cert_reqs="required",
        ssl_ca_certs=str(ca_cert_path),
        ssl_check_hostname=True,
        socket_connect_timeout=10,
        socket_timeout=10,
    )

    print(f"✅ Connected to Redis")
    print(f"Publishing signals to signals:{MODE} at max {MAX_PUBLISH_RATE}/sec")
    print("=" * 60)

    counter = 0
    last_publish_time = 0

    while True:
        try:
            # Wait for market data
            if not latest_prices:
                await asyncio.sleep(1)
                continue

            # Rate limiting
            current_time = time.time()
            time_since_last = current_time - last_publish_time
            if time_since_last < MIN_PUBLISH_INTERVAL:
                await asyncio.sleep(MIN_PUBLISH_INTERVAL - time_since_last)

            # Select random pair that has data
            available_pairs = [p for p in PAIRS.keys() if p in latest_prices]
            if not available_pairs:
                await asyncio.sleep(1)
                continue

            pair = random.choice(available_pairs)
            current_price = latest_prices[pair]
            spread = latest_spreads.get(pair, 0)

            # Generate realistic stop loss and take profit based on current price
            # Use a simple strategy: 2% stop loss, 3% take profit
            side = "buy" if counter % 2 == 0 else "sell"

            if side == "buy":
                entry = current_price
                sl = entry * 0.98  # 2% below entry
                tp = entry * 1.03  # 3% above entry
            else:
                entry = current_price
                sl = entry * 1.02  # 2% above entry
                tp = entry * 0.97  # 3% below entry

            # Generate signal with real market data
            timestamp = int(time.time() * 1000)
            signal = {
                "id": f"live-kraken-{timestamp}-{counter}",
                "ts": timestamp,
                "pair": pair,
                "side": side,
                "entry": round(entry, 8),
                "sl": round(sl, 8),
                "tp": round(tp, 8),
                "strategy": "live_kraken_realtime",
                "confidence": round(0.7 + random.random() * 0.25, 2),  # 0.70-0.95
                "mode": MODE,
                "market_data": {
                    "current_price": round(current_price, 8),
                    "spread": round(spread, 8),
                    "source": "kraken_websocket",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat()
                }
            }

            # Publish to Redis
            stream_key = f"signals:{MODE}"
            msg_id = await client.xadd(
                stream_key,
                {"json": json.dumps(signal)},
                maxlen=10000
            )

            last_publish_time = time.time()

            print(f"[{counter}] 📤 {pair} {side.upper()} @ ${entry:.2f} | SL: ${sl:.2f} | TP: ${tp:.2f} | ID: {msg_id}")

            counter += 1

        except Exception as e:
            print(f"❌ Error generating signal: {e}")
            await asyncio.sleep(5)


async def main():
    """Run WebSocket listener and signal generator concurrently"""
    print("=" * 60)
    print("🚀 LIVE KRAKEN SIGNAL GENERATOR")
    print("=" * 60)
    print(f"Mode: {MODE}")
    print(f"Pairs: {', '.join(PAIRS.keys())}")
    print("=" * 60)

    # Run both tasks concurrently
    await asyncio.gather(
        kraken_ws_listener(),
        generate_live_signals()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Stopping live signal generator...")
