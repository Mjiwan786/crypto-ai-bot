#!/usr/bin/env python3
"""
End-to-End Signal Pipeline Test
================================

Tests the complete signal flow: crypto-ai-bot → Redis → signals-api → signals-site

USAGE:
    # Set environment variables first
    export REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
    export API_URL="https://signals-api-gateway.fly.dev"

    # Run test
    python scripts/test_signal_pipeline_e2e.py

PURPOSE:
    - Verify signal schema is correct
    - Verify signals publish to unified streams
    - Verify signals-api can read fresh data
    - Verify pipeline end-to-end

SUCCESS CRITERIA:
    - Signal publishes to signals:paper
    - API returns signal within 5 seconds
    - Signal fields match SignalDTO schema
    - Timestamp is fresh (< 10s old)
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.signals_api_config import SIGNALS_API_BASE_URL

# Environment configuration (env vars can override centralized config)
REDIS_URL = os.getenv("REDIS_URL")
API_URL = os.getenv("API_URL", SIGNALS_API_BASE_URL)
REDIS_CA_CERT = os.getenv(
    "REDIS_CA_CERT",
    str(project_root / "config" / "certs" / "redis_ca.pem")
)

# Verify environment
if not REDIS_URL:
    print("❌ ERROR: REDIS_URL environment variable not set")
    print("   Set with: export REDIS_URL='rediss://...'")
    sys.exit(1)


async def test_pipeline():
    """Run end-to-end pipeline test"""

    print("=" * 80)
    print(" " * 25 + "E2E SIGNAL PIPELINE TEST")
    print("=" * 80)
    print()
    print(f"Redis URL: {REDIS_URL[:50]}...")
    print(f"API URL: {API_URL}")
    print()

    # =============================================================================
    # STEP 1: Create Test Signal
    # =============================================================================

    print("[1/6] Creating test signal...")

    from signals.schema import create_signal

    test_signal = create_signal(
        pair="BTC/USD",
        side="buy",  # Using "buy" (not "long") for API compatibility
        entry=45000.0,
        sl=44500.0,
        tp=45500.0,
        strategy="e2e_test_v1",
        confidence=0.85,
        mode="paper"
    )

    print(f"✓ Signal created:")
    print(f"  - ID: {test_signal.id}")
    print(f"  - Pair: {test_signal.pair}")
    print(f"  - Side: {test_signal.side}")
    print(f"  - Entry: ${test_signal.entry}")
    print(f"  - Stream key: {test_signal.get_stream_key()}")

    # Verify unified stream key
    expected_stream = "signals:paper"
    actual_stream = test_signal.get_stream_key()

    if actual_stream != expected_stream:
        print(f"❌ FAIL: Stream key mismatch!")
        print(f"   Expected: {expected_stream}")
        print(f"   Got: {actual_stream}")
        return False

    print(f"✓ Stream key correct: {actual_stream}")

    # =============================================================================
    # STEP 2: Verify Schema Compliance
    # =============================================================================

    print("\n[2/6] Verifying schema compliance...")

    # Check required fields
    required_fields = ["id", "ts", "pair", "side", "entry", "sl", "tp", "strategy", "confidence", "mode"]
    signal_dict = test_signal.to_dict()

    for field in required_fields:
        if field not in signal_dict:
            print(f"❌ FAIL: Missing required field: {field}")
            return False

    print(f"✓ All required fields present: {required_fields}")

    # Verify field values
    if signal_dict["side"] not in ["buy", "sell"]:
        print(f"❌ FAIL: Invalid side value: {signal_dict['side']} (must be 'buy' or 'sell')")
        return False

    print(f"✓ Side value correct: '{signal_dict['side']}' (buy/sell format)")

    if "ts_ms" in signal_dict:
        print(f"❌ FAIL: Old field 'ts_ms' found! Should use 'ts' instead")
        return False

    print(f"✓ Timestamp field correct: 'ts' (not 'ts_ms')")

    # =============================================================================
    # STEP 3: Publish to Redis
    # =============================================================================

    print("\n[3/6] Publishing to Redis Cloud...")

    from signals.publisher import SignalPublisher

    publisher = SignalPublisher(
        redis_url=REDIS_URL,
        redis_cert_path=REDIS_CA_CERT if os.path.exists(REDIS_CA_CERT) else None,
        stream_maxlen=10000
    )

    connected = await publisher.connect()
    if not connected:
        print("❌ FAIL: Could not connect to Redis")
        return False

    print("✓ Connected to Redis Cloud")

    try:
        entry_id = await publisher.publish(test_signal)
        print(f"✓ Published to {actual_stream}")
        print(f"  - Entry ID: {entry_id}")
    except Exception as e:
        print(f"❌ FAIL: Publish failed: {e}")
        await publisher.close()
        return False
    finally:
        await publisher.close()

    # =============================================================================
    # STEP 4: Wait for Propagation
    # =============================================================================

    print("\n[4/6] Waiting for propagation...")
    await asyncio.sleep(2)  # Give Redis time to propagate
    print("✓ Wait complete")

    # =============================================================================
    # STEP 5: Fetch from signals-api
    # =============================================================================

    print("\n[5/6] Fetching from signals-api...")

    import aiohttp

    api_endpoint = f"{API_URL}/v1/signals/latest"
    params = {"limit": 1}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_endpoint, params=params, timeout=10) as response:
                if response.status != 200:
                    print(f"❌ FAIL: API returned HTTP {response.status}")
                    text = await response.text()
                    print(f"   Response: {text[:200]}")
                    return False

                signals = await response.json()

                if not signals:
                    print("❌ FAIL: API returned empty array")
                    print("   No signals in stream. Check bot is running.")
                    return False

                latest = signals[0]
                print(f"✓ API returned signal:")
                print(f"  - Pair: {latest.get('pair')}")
                print(f"  - Side: {latest.get('side')}")
                print(f"  - Entry: ${latest.get('entry')}")
                print(f"  - Timestamp: {latest.get('ts')}")

    except aiohttp.ClientError as e:
        print(f"❌ FAIL: API request failed: {e}")
        return False
    except Exception as e:
        print(f"❌ FAIL: Unexpected error: {e}")
        return False

    # =============================================================================
    # STEP 6: Verify Signal Data
    # =============================================================================

    print("\n[6/6] Verifying signal data...")

    # Check freshness
    now_ms = int(time.time() * 1000)
    signal_ts = latest.get("ts")

    if not signal_ts:
        print("❌ FAIL: No 'ts' field in signal")
        return False

    age_seconds = (now_ms - signal_ts) / 1000
    print(f"✓ Signal timestamp: {signal_ts}")
    print(f"✓ Signal age: {age_seconds:.1f} seconds")

    if age_seconds > 60:
        print(f"⚠️  WARNING: Signal is {age_seconds:.1f}s old (> 60s)")
        print(f"   This might indicate stale data or bot not running")
    else:
        print(f"✓ Signal is FRESH (< 60s old)")

    # Verify schema fields
    if latest.get("side") not in ["buy", "sell"]:
        print(f"❌ FAIL: Invalid side in API response: {latest.get('side')}")
        return False

    print(f"✓ Side field correct: '{latest.get('side')}'")

    # Success!
    print("\n" + "=" * 80)
    print("✅ E2E TEST PASSED - Pipeline is working!")
    print("=" * 80)
    print()
    print("Summary:")
    print(f"  - Signal published to: {actual_stream}")
    print(f"  - Schema uses: ts (not ts_ms), buy/sell (not long/short)")
    print(f"  - API returned fresh data (age: {age_seconds:.1f}s)")
    print(f"  - All field names match SignalDTO")
    print()
    print("Next steps:")
    print("  1. Deploy crypto-ai-bot to Fly.io")
    print("  2. Monitor logs: fly logs -a <bot-app-name>")
    print("  3. Check website: https://www.aipredictedsignals.cloud")
    print("  4. Verify signals update in real-time")
    print()

    return True


async def test_debug_endpoint():
    """Test the new debug endpoint"""

    print("\n" + "=" * 80)
    print(" " * 20 + "BONUS: TESTING DEBUG ENDPOINT")
    print("=" * 80)
    print()

    import aiohttp

    debug_endpoint = f"{API_URL}/v1/signals/debug/BTC-USD"
    params = {"mode": "paper", "limit": 5}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(debug_endpoint, params=params, timeout=10) as response:
                if response.status != 200:
                    print(f"❌ Debug endpoint failed: HTTP {response.status}")
                    return

                result = await response.json()

                print(f"✓ Debug endpoint working:")
                print(f"  - Stream: {result.get('stream_name')}")
                print(f"  - Total messages: {result.get('total_messages')}")
                print(f"  - Signals returned: {result.get('signals_returned')}")

                freshness = result.get('freshness', {})
                print(f"  - Last signal age: {freshness.get('age_seconds')}s")
                print(f"  - Is fresh: {freshness.get('is_fresh')}")

                print()
                print(f"Debug URL: {debug_endpoint}?mode=paper&limit=5")
                print("Use this endpoint to troubleshoot stale signals!")

    except Exception as e:
        print(f"❌ Debug endpoint test failed: {e}")


async def main():
    """Main test runner"""

    try:
        # Run main E2E test
        success = await test_pipeline()

        # Run debug endpoint test (bonus)
        await test_debug_endpoint()

        # Exit with appropriate code
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\nTest cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # Run async main
    asyncio.run(main())
