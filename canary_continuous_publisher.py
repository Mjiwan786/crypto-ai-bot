#!/usr/bin/env python3
"""
Canary Continuous Publisher - Adds SOL/USD and ADA/USD to signals:paper
Runs LOCALLY alongside Fly.io publisher (which publishes BTC/ETH)

Features:
- Publishes ONLY SOL-USD and ADA-USD (not BTC/ETH to avoid duplicates)
- Rate limiting (max 2 signals/second)
- Exponential backoff on Redis errors
- Loads from .env.paper.local
- Instant rollback via Ctrl+C
"""
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path
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

# Load canary environment
env_file = project_root / ".env.paper.local"
if not env_file.exists():
    print(f"ERROR: {env_file} not found!")
    sys.exit(1)

load_dotenv(env_file, override=True)

REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_CA_CERT = os.getenv("REDIS_SSL_CA_CERT", "./config/certs/redis_ca.pem")
EXTRA_PAIRS = os.getenv("EXTRA_PAIRS", "SOL/USD,ADA/USD")

# Parse pairs (convert to hyphen format)
CANARY_PAIRS = [p.strip().replace("/", "-") for p in EXTRA_PAIRS.split(",") if p.strip()]

# Rate limiting and backoff configuration
MAX_PUBLISH_RATE = 2.0  # signals per second
MIN_PUBLISH_INTERVAL = 1.0 / MAX_PUBLISH_RATE  # 0.5 seconds
MAX_BACKOFF_SECONDS = 60
INITIAL_BACKOFF_SECONDS = 1
last_publish_time = 0

# Sample prices for canary pairs
PAIR_PRICES = {
    "SOL-USD": {"entry": 100.0, "sl": 98.0, "tp": 104.0},
    "ADA-USD": {"entry": 0.50, "sl": 0.49, "tp": 0.52},
}

async def publish_continuously():
    """Publish SOL/ADA signals with rate limiting and exponential backoff"""
    global last_publish_time

    print("=" * 70)
    print("CANARY CONTINUOUS PUBLISHER")
    print("=" * 70)
    print(f"Target Stream: signals:paper (PRODUCTION)")
    print(f"Canary Pairs: {', '.join(CANARY_PAIRS)}")
    print(f"Rate Limit: {MAX_PUBLISH_RATE} signals/sec")
    print("=" * 70)
    print()

    # Resolve CA certificate
    ca_cert_path = Path(REDIS_CA_CERT)
    if not ca_cert_path.is_absolute():
        ca_cert_path = project_root / ca_cert_path

    if not ca_cert_path.exists():
        print(f"ERROR: CA cert not found: {ca_cert_path}")
        sys.exit(1)

    # Create Redis client
    print("Connecting to Redis Cloud...")
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

    print("[OK] Connected to Redis")
    print(f"[OK] Publishing canary signals at max {MAX_PUBLISH_RATE}/sec")
    print()
    print("Press Ctrl+C to stop and rollback to BTC/ETH only")
    print("=" * 70)
    print()

    counter = 0
    backoff_seconds = INITIAL_BACKOFF_SECONDS
    consecutive_errors = 0

    try:
        while True:
            try:
                # Rate limiting: enforce minimum interval between publishes
                current_time = time.time()
                time_since_last = current_time - last_publish_time
                if time_since_last < MIN_PUBLISH_INTERVAL:
                    await asyncio.sleep(MIN_PUBLISH_INTERVAL - time_since_last)

                timestamp = int(time.time() * 1000)

                # Rotate through canary pairs only (SOL, ADA)
                pair = CANARY_PAIRS[counter % len(CANARY_PAIRS)]
                prices = PAIR_PRICES.get(pair, {"entry": 1.0, "sl": 0.95, "tp": 1.05})

                # Publish canary signal
                signal = {
                    "id": f"canary-{timestamp}-{counter}",
                    "ts": timestamp,
                    "pair": pair,
                    "side": "buy" if counter % 2 == 0 else "sell",
                    "entry": prices["entry"],
                    "sl": prices["sl"],
                    "tp": prices["tp"],
                    "strategy": "canary_publisher",
                    "confidence": 0.85,
                    "mode": "paper"
                }

                msg_id = await client.xadd(
                    "signals:paper",
                    {"json": json.dumps(signal)},
                    maxlen=10000  # Match production maxlen
                )

                last_publish_time = time.time()
                print(f"[{counter}] Published: {signal['pair']} {signal['side']} (ID: {msg_id})")

                # Reset backoff on success
                if consecutive_errors > 0:
                    print(f"✓ Recovered after {consecutive_errors} errors")
                backoff_seconds = INITIAL_BACKOFF_SECONDS
                consecutive_errors = 0

                counter += 1

            except Exception as e:
                consecutive_errors += 1
                # Exponential backoff with jitter
                jitter = random.uniform(0, backoff_seconds * 0.3)
                sleep_time = min(backoff_seconds + jitter, MAX_BACKOFF_SECONDS)

                print(f"ERROR [{consecutive_errors}]: {e}")
                print(f"Backing off for {sleep_time:.2f}s...")

                await asyncio.sleep(sleep_time)

                # Exponential increase
                backoff_seconds = min(backoff_seconds * 2, MAX_BACKOFF_SECONDS)

                # Try to reconnect
                try:
                    await client.ping()
                    print("Redis connection OK")
                except:
                    print("Reconnecting to Redis...")
                    await client.aclose()
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

    except KeyboardInterrupt:
        print()
        print("=" * 70)
        print("CANARY PUBLISHER STOPPED")
        print("=" * 70)
        print("SOL-USD and ADA-USD signals stopped")
        print("BTC-USD and ETH-USD continue from Fly.io")
        print("Rollback complete")
        print("=" * 70)
    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(publish_continuously())
