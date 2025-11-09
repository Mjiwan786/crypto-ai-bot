#!/usr/bin/env python3
"""
Continuous Signal Publisher - Keeps streams fresh for health checks

Features:
- Rate limiting (max 2 signals/second)
- Exponential backoff on Redis errors
- Health tracking (last publish time)
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

# Load environment
env_file = project_root / ".env.prod"
if env_file.exists():
    load_dotenv(env_file)

REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_CA_CERT = os.getenv("REDIS_CA_CERT", "./config/certs/redis_ca.pem")

# Rate limiting and backoff configuration
MAX_PUBLISH_RATE = 2.0  # signals per second
MIN_PUBLISH_INTERVAL = 1.0 / MAX_PUBLISH_RATE  # 0.5 seconds
MAX_BACKOFF_SECONDS = 60
INITIAL_BACKOFF_SECONDS = 1
last_publish_time = 0

async def publish_continuously():
    """Publish signals with rate limiting and exponential backoff"""
    global last_publish_time

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

    print("Connected to Redis")
    print(f"Publishing signals at max {MAX_PUBLISH_RATE}/sec (Press Ctrl+C to stop)...\n")

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

                # Cycle through all 5 trading pairs
                pairs_config = [
                    {"pair": "BTC/USD", "entry": 45000.0, "sl": 44500.0, "tp": 46000.0},
                    {"pair": "ETH/USD", "entry": 3000.0, "sl": 2950.0, "tp": 3100.0},
                    {"pair": "SOL/USD", "entry": 150.0, "sl": 148.0, "tp": 154.0},
                    {"pair": "MATIC/USD", "entry": 0.85, "sl": 0.83, "tp": 0.88},
                    {"pair": "LINK/USD", "entry": 15.0, "sl": 14.7, "tp": 15.5},
                ]

                pair_config = pairs_config[counter % len(pairs_config)]

                # Publish paper signal
                signal = {
                    "id": f"continuous-{timestamp}-{counter}",
                    "ts": timestamp,
                    "pair": pair_config["pair"],
                    "side": "buy" if counter % 2 == 0 else "sell",
                    "entry": pair_config["entry"],
                    "sl": pair_config["sl"],
                    "tp": pair_config["tp"],
                    "strategy": "continuous_publisher",
                    "confidence": 0.85,
                    "mode": "paper"
                }

                msg_id = await client.xadd(
                    "signals:paper",
                    {"json": json.dumps(signal)},
                    maxlen=1000
                )

                last_publish_time = time.time()
                print(f"[{counter}] Published: {signal['pair']} {signal['side']} (ID: {msg_id})")

                # Reset backoff on success
                if consecutive_errors > 0:
                    print(f"Recovered after {consecutive_errors} errors")
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
        print("\n\nStopping publisher...")
    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(publish_continuously())
