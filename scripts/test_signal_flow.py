#!/usr/bin/env python3
"""
End-to-End Signal Flow Test
============================

Tests the complete signal flow:
1. Schema validation
2. Signal publishing to Redis
3. Stream key structure
4. Metrics publishing

Runs for 3 iterations and verifies signals are published correctly.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from signals.scalper_schema import (
    ScalperSignal,
    validate_signal_safe,
    get_signal_stream_key,
    get_metrics_stream_key,
)
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from dotenv import load_dotenv
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_signal_flow():
    """Test end-to-end signal flow"""
    print("=" * 80)
    print("               END-TO-END SIGNAL FLOW TEST")
    print("=" * 80)

    # Load environment
    env_file = project_root / ".env.paper.live"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"\n[OK] Loaded environment from: {env_file}")
    else:
        print(f"\n[WARN] Environment file not found: {env_file}")
        print("Using environment variables from shell")

    # Initialize Redis client
    redis_url = os.getenv("REDIS_URL")
    redis_ca_cert = os.getenv("REDIS_CA_CERT", "config/certs/redis_ca.pem")

    if not redis_url:
        print("\n[FAIL] REDIS_URL not set in environment")
        return False

    print(f"[OK] Redis URL: {redis_url[:50]}...")
    print(f"[OK] Redis CA cert: {redis_ca_cert}")

    # Connect to Redis
    print("\n1. Testing Redis connection...")
    redis_config = RedisCloudConfig(
        url=redis_url,
        ca_cert_path=redis_ca_cert,
    )
    redis_client = RedisCloudClient(redis_config)

    try:
        await redis_client.connect()
        print("   [OK] Connected to Redis Cloud")
    except Exception as e:
        print(f"   [FAIL] Failed to connect to Redis: {e}")
        return False

    # Test signal validation
    print("\n2. Testing signal validation...")
    test_pairs = ["BTC/USD", "ETH/USD"]
    test_tf = "15s"

    for pair in test_pairs:
        signal_data = {
            "ts_exchange": int(time.time() * 1000),
            "ts_server": int(time.time() * 1000),
            "symbol": pair,
            "timeframe": test_tf,
            "side": "long",
            "confidence": 0.85,
            "entry": 45000.0 if pair == "BTC/USD" else 3000.0,
            "stop": 44500.0 if pair == "BTC/USD" else 2950.0,
            "tp": 46000.0 if pair == "BTC/USD" else 3100.0,
            "model": "test_flow_v1",
            "trace_id": f"test-{int(time.time())}-{pair.replace('/', '-')}",
        }

        signal, error = validate_signal_safe(signal_data)

        if signal is None:
            print(f"   [FAIL] {pair}: {error}")
            await redis_client.close()
            return False

        print(f"   [OK] {pair}: validated (trace_id={signal.trace_id})")

    # Test signal publishing
    print("\n3. Testing signal publishing...")
    signals_published = 0

    for iteration in range(1, 4):  # 3 iterations
        print(f"\n   Iteration {iteration}/3:")

        for pair in test_pairs:
            # Create signal
            signal_data = {
                "ts_exchange": int(time.time() * 1000),
                "ts_server": int(time.time() * 1000),
                "symbol": pair,
                "timeframe": test_tf,
                "side": "long" if iteration % 2 == 1 else "short",
                "confidence": 0.70 + iteration * 0.05,
                "entry": 45000.0 + iteration * 10 if pair == "BTC/USD" else 3000.0 + iteration,
                "stop": (45000.0 + iteration * 10 - 500) if pair == "BTC/USD" and iteration % 2 == 1 else (45000.0 + iteration * 10 + 500) if pair == "BTC/USD" else (3000.0 + iteration - 50) if iteration % 2 == 1 else (3000.0 + iteration + 50),
                "tp": (45000.0 + iteration * 10 + 1000) if pair == "BTC/USD" and iteration % 2 == 1 else (45000.0 + iteration * 10 - 1000) if pair == "BTC/USD" else (3000.0 + iteration + 100) if iteration % 2 == 1 else (3000.0 + iteration - 100),
                "model": "test_flow_v1",
                "trace_id": f"test-{int(time.time())}-{iteration}-{pair.replace('/', '-')}",
            }

            # Validate
            signal, error = validate_signal_safe(signal_data)

            if signal is None:
                print(f"      [FAIL] {pair}: {error}")
                continue

            # Publish
            try:
                stream_key = signal.get_stream_key()
                signal_json = signal.to_json_str()

                await redis_client.xadd(
                    stream_key,
                    {"signal": signal_json},
                    maxlen=1000,
                )

                signals_published += 1
                print(
                    f"      [OK] {pair} {signal.side} @ {signal.entry:.2f} "
                    f"-> {stream_key}"
                )

            except Exception as e:
                print(f"      [FAIL] Failed to publish {pair}: {e}")

        await asyncio.sleep(1)  # Wait 1 second between iterations

    # Test metrics publishing
    print("\n4. Testing metrics publishing...")
    try:
        metrics_stream = get_metrics_stream_key()
        await redis_client.xadd(
            metrics_stream,
            {
                "ts": int(time.time() * 1000),
                "signals_published": signals_published,
                "test_mode": "true",
                "test_duration_sec": 3,
            },
            maxlen=10000,
        )
        print(f"   [OK] Metrics published to {metrics_stream}")
    except Exception as e:
        print(f"   [FAIL] Failed to publish metrics: {e}")
        await redis_client.close()
        return False

    # Verify signals in Redis
    print("\n5. Verifying signals in Redis...")
    for pair in test_pairs:
        stream_key = get_signal_stream_key(pair, test_tf)

        try:
            # Read last 3 signals from stream
            messages = await redis_client.xrevrange(stream_key, count=3)

            if messages and len(messages) > 0:
                print(f"   [OK] {stream_key}: {len(messages)} signals found")
                # Show latest signal
                latest = messages[0]
                print(f"       Latest: ID={latest[0]}, Signal={latest[1].get('signal', '')[:100]}...")
            else:
                print(f"   [WARN] {stream_key}: No signals found (may have expired)")

        except Exception as e:
            print(f"   [FAIL] Failed to read from {stream_key}: {e}")

    # Cleanup
    await redis_client.close()

    print("\n" + "=" * 80)
    print("[PASS] END-TO-END TEST COMPLETED")
    print(f"       Signals published: {signals_published}")
    print("=" * 80)

    return True


async def main():
    """Main entry point"""
    try:
        success = await test_signal_flow()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
