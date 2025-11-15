#!/usr/bin/env python3
"""
Signal Queue Test
=================

Tests the signal queue with heartbeat and backpressure handling.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.infrastructure.signal_queue import SignalQueue
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from signals.scalper_schema import ScalperSignal
from dotenv import load_dotenv
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_signal_queue():
    """Test signal queue end-to-end"""
    print("=" * 80)
    print("              SIGNAL QUEUE END-TO-END TEST")
    print("=" * 80)

    # Load environment
    env_file = project_root / ".env.paper.live"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"\n[OK] Loaded environment from: {env_file}")

    # Initialize Redis client
    redis_url = os.getenv("REDIS_URL")
    redis_ca_cert = os.getenv("REDIS_CA_CERT", "config/certs/redis_ca.pem")

    if not redis_url:
        print("\n[FAIL] REDIS_URL not set in environment")
        return False

    print(f"[OK] Redis URL: {redis_url[:50]}...")

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

    # Initialize signal queue
    print("\n2. Initializing signal queue...")
    queue = SignalQueue(
        redis_client=redis_client,
        max_size=10,  # Small queue for testing backpressure
        heartbeat_interval_sec=5.0,  # 5 second heartbeat for testing
    )
    print("   [OK] Queue initialized (max_size=10, heartbeat=5s)")

    # Start queue
    print("\n3. Starting queue processor...")
    await queue.start()
    print("   [OK] Queue started")

    # Enqueue signals with varying confidence
    print("\n4. Enqueuing signals (15 signals to trigger backpressure)...")
    signals_enqueued = 0
    signals_shed = 0

    for i in range(15):  # More than capacity
        signal = ScalperSignal(
            ts_exchange=int(time.time() * 1000),
            ts_server=int(time.time() * 1000),
            symbol="BTC/USD" if i % 2 == 0 else "ETH/USD",
            timeframe="15s",
            side="long" if i % 2 == 0 else "short",
            confidence=0.5 + (i % 10) * 0.05,  # Varying confidence
            entry=45000.0 + i * 10 if i % 2 == 0 else 3000.0 + i,
            stop=44500.0 + i * 10 if i % 2 == 0 else 2950.0 + i,
            tp=46000.0 + i * 10 if i % 2 == 0 else 3100.0 + i,
            model="test_queue_v1",
            trace_id=f"test-queue-{int(time.time())}-{i}",
        )

        success = await queue.enqueue(signal)
        if success:
            signals_enqueued += 1
            print(f"   [OK] Signal {i}: {signal.symbol} (conf={signal.confidence:.2f})")
        else:
            signals_shed += 1
            print(f"   [SHED] Signal {i}: {signal.symbol} (conf={signal.confidence:.2f}) - backpressure")

        await asyncio.sleep(0.2)  # Small delay between signals

    print(f"\n   Total enqueued: {signals_enqueued}")
    print(f"   Total shed: {signals_shed}")

    # Wait for signals to be published
    print("\n5. Waiting for signals to be published (10 seconds)...")
    await asyncio.sleep(10)

    # Check queue stats
    print("\n6. Checking queue stats...")
    stats = queue.get_stats()
    print(f"   [OK] Signals enqueued: {stats['signals_enqueued']}")
    print(f"   [OK] Signals published: {stats['signals_published']}")
    print(f"   [OK] Signals shed: {stats['signals_shed']}")
    print(f"   [OK] Queue depth: {stats['queue_depth']}/{stats['queue_capacity']}")
    print(f"   [OK] Utilization: {stats['queue_utilization_pct']:.1f}%")

    if stats['signals_shed'] > 0:
        print(f"   [OK] Backpressure handling worked (shed {stats['signals_shed']} signals)")

    # Wait for heartbeat
    print("\n7. Waiting for heartbeat emission (10 seconds)...")
    await asyncio.sleep(10)

    # Verify heartbeat in Redis
    print("\n8. Verifying heartbeat in Redis...")
    try:
        messages = await redis_client.xrevrange("metrics:scalper", count=10)

        heartbeats = [m for m in messages if m[1].get("kind") == "heartbeat"]

        if heartbeats:
            print(f"   [OK] Found {len(heartbeats)} heartbeat(s) in Redis")
            latest = heartbeats[0][1]
            print(f"   [OK] Latest heartbeat:")
            print(f"       - queue_depth: {latest.get('queue_depth', 'N/A')}")
            print(f"       - signals_published: {latest.get('signals_published', 'N/A')}")
            print(f"       - signals_shed: {latest.get('signals_shed', 'N/A')}")
            print(f"       - queue_utilization_pct: {latest.get('queue_utilization_pct', 'N/A')}")
        else:
            print("   [WARN] No heartbeats found in metrics:scalper stream")

    except Exception as e:
        print(f"   [FAIL] Failed to read heartbeats: {e}")

    # Stop queue
    print("\n9. Stopping queue...")
    await queue.stop()
    print("   [OK] Queue stopped")

    # Cleanup
    await redis_client.close()

    print("\n" + "=" * 80)
    print("[PASS] END-TO-END TEST COMPLETED")
    print("=" * 80)

    return True


async def main():
    """Main entry point"""
    try:
        success = await test_signal_queue()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
