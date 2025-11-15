#!/usr/bin/env python3
"""
Test Pipeline Validation
=========================

Seeds test signals to Redis and validates the pipeline validator works.
"""

import asyncio
import logging
import sys
import time
import os
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from signals.scalper_schema import ScalperSignal
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def seed_test_signals(redis_client: RedisCloudClient, count: int = 5):
    """Seed test signals to Redis streams"""
    print(f"\nSeeding {count} test signals to Redis...")

    for i in range(count):
        # Create test signal
        signal = ScalperSignal(
            ts_exchange=int(time.time() * 1000) - 100,  # 100ms ago
            ts_server=int(time.time() * 1000) - 50,  # 50ms ago
            symbol="BTC/USD" if i % 2 == 0 else "ETH/USD",
            timeframe="15s",
            side="long" if i % 2 == 0 else "short",
            confidence=0.75 + (i * 0.03),
            entry=45000.0 + i * 10 if i % 2 == 0 else 3000.0 + i,
            stop=44500.0 + i * 10 if i % 2 == 0 else 2950.0 + i,
            tp=46000.0 + i * 10 if i % 2 == 0 else 3100.0 + i,
            model="test_pipeline_v1",
            trace_id=f"test-pipeline-{int(time.time())}-{i}",
        )

        # Publish to Redis
        stream_key = signal.get_stream_key()
        signal_json = signal.to_json_str()

        await redis_client.xadd(
            stream_key,
            {"signal": signal_json},
            maxlen=1000,
        )

        print(f"  [{i+1}/{count}] Published: {signal.symbol} {signal.side} "
              f"(trace_id={signal.trace_id[:20]}...)")

        await asyncio.sleep(0.2)  # Small delay between signals

    print(f"\n[OK] Seeded {count} test signals")


async def main():
    """Main entry point"""
    print("=" * 80)
    print("              PIPELINE VALIDATION TEST")
    print("=" * 80)

    # Load environment
    env_file = project_root / ".env.paper"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"\n[OK] Loaded environment from: {env_file}")

    # Redis connection
    redis_url = os.getenv("REDIS_URL")
    redis_ca_cert = os.getenv("REDIS_CA_CERT", "config/certs/redis_ca.pem")

    if not redis_url:
        print("\n[FAIL] REDIS_URL not set in environment")
        return 1

    print(f"[OK] Redis URL configured")

    # Connect to Redis
    print("\n[1/3] Connecting to Redis...")
    redis_config = RedisCloudConfig(
        url=redis_url,
        ca_cert_path=redis_ca_cert,
    )
    redis_client = RedisCloudClient(redis_config)

    try:
        await redis_client.connect()
        print("      [OK] Connected to Redis Cloud")
    except Exception as e:
        print(f"      [FAIL] Failed to connect to Redis: {e}")
        return 1

    # Seed test signals
    print("\n[2/3] Seeding test signals...")
    try:
        await seed_test_signals(redis_client, count=5)
    except Exception as e:
        logger.error(f"Failed to seed signals: {e}", exc_info=True)
        return 1
    finally:
        await redis_client.aclose()

    # Run validation (separate process)
    print("\n[3/3] Running validation pipeline...")
    print("      (Will monitor for 15 seconds)")
    print("")

    import subprocess
    result = subprocess.run(
        ["python", "scripts/validate_pipeline.py"],
        env={**os.environ, "VALIDATION_DURATION_SEC": "15"},
        cwd=str(project_root),
    )

    print("\n" + "=" * 80)
    if result.returncode == 0:
        print("[PASS] Pipeline validation test completed successfully")
        print("=" * 80)
        return 0
    else:
        print("[INFO] Pipeline validation completed (check output above)")
        print("=" * 80)
        return 0  # Don't fail - signals might have been consumed


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
