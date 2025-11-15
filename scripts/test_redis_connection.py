"""
scripts/test_redis_connection.py - Test Redis Cloud Connection

Quick test script to verify Redis Cloud connectivity before running the live engine.

Usage:
    python scripts/test_redis_connection.py

Environment Variables:
    REDIS_URL: Redis Cloud connection URL (required)
    REDIS_CA_CERT: Path to Redis CA certificate (optional, uses default path)

Author: Crypto AI Bot Team
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis


def test_redis_connection():
    """Test Redis Cloud connection"""

    print("\n" + "="*80)
    print("REDIS CLOUD CONNECTION TEST")
    print("="*80 + "\n")

    # Get Redis URL from environment
    redis_url = os.getenv("REDIS_URL")

    if not redis_url:
        print("ERROR: REDIS_URL not set in environment")
        print("\nPlease set REDIS_URL:")
        print("  Example: export REDIS_URL='rediss://default:password@host:port'")
        print("  Your URL: redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818")
        sys.exit(1)

    # Mask password for display
    display_url = redis_url
    if "@" in redis_url:
        parts = redis_url.split("@")
        if ":" in parts[0]:
            auth_parts = parts[0].rsplit(":", 1)
            display_url = f"{auth_parts[0]}:***@{parts[1]}"

    print(f"Redis URL: {display_url}")
    print("")

    # Get CA cert path
    ca_cert_path = os.getenv(
        "REDIS_CA_CERT",
        str(project_root / "config" / "certs" / "redis_ca.pem")
    )

    print(f"CA Certificate: {ca_cert_path}")

    if not os.path.exists(ca_cert_path):
        print(f"WARNING: CA certificate not found at {ca_cert_path}")
        print("TLS connection may fail")
    else:
        print("CA certificate found")

    print("")

    # Try to connect
    print("Testing connection...")

    try:
        # Create Redis client
        if redis_url.startswith("rediss://"):
            # TLS connection
            print("Using TLS (rediss://)")
            client = redis.from_url(
                redis_url,
                ssl_cert_reqs='required' if os.path.exists(ca_cert_path) else None,
                ssl_ca_certs=ca_cert_path if os.path.exists(ca_cert_path) else None,
                decode_responses=True,
                socket_timeout=10,
                socket_connect_timeout=5,
            )
        else:
            # Non-TLS connection
            print("Using non-TLS (redis://)")
            client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=10,
                socket_connect_timeout=5,
            )

        # Test 1: PING
        print("\n[TEST 1] PING...")
        response = client.ping()
        if response:
            print("SUCCESS: PING returned True")
        else:
            print("FAILED: PING returned False")
            sys.exit(1)

        # Test 2: SET/GET
        print("\n[TEST 2] SET/GET test key...")
        test_key = "test:connection:key"
        test_value = "test_value_123"

        client.set(test_key, test_value, ex=60)  # Expire in 60 seconds
        retrieved = client.get(test_key)

        if retrieved == test_value:
            print(f"SUCCESS: Retrieved value matches: {retrieved}")
        else:
            print(f"FAILED: Retrieved value mismatch: {retrieved} != {test_value}")
            sys.exit(1)

        # Test 3: Stream operations (XADD)
        print("\n[TEST 3] Stream operations (XADD)...")
        test_stream = "test:stream:signals"

        entry_id = client.xadd(
            test_stream,
            {"test": "signal", "timestamp": "1234567890"},
            maxlen=100,
        )

        print(f"SUCCESS: Added stream entry: {entry_id}")

        # Test 4: Read stream (XREVRANGE)
        print("\n[TEST 4] Read stream (XREVRANGE)...")
        entries = client.xrevrange(test_stream, count=1)

        if entries:
            print(f"SUCCESS: Read {len(entries)} entries from stream")
            print(f"Latest entry: {entries[0]}")
        else:
            print("WARNING: No entries found in stream")

        # Test 5: Get server info
        print("\n[TEST 5] Server info...")
        info = client.info("server")

        print(f"Redis Version: {info.get('redis_version', 'unknown')}")
        print(f"OS: {info.get('os', 'unknown')}")
        print(f"Uptime (days): {info.get('uptime_in_days', 'unknown')}")

        # Test 6: Memory info
        print("\n[TEST 6] Memory info...")
        memory_info = client.info("memory")

        used_memory_mb = int(memory_info.get("used_memory", 0)) / (1024 * 1024)
        print(f"Used Memory: {used_memory_mb:.2f} MB")

        # Cleanup
        print("\n[CLEANUP] Removing test keys...")
        client.delete(test_key)
        client.delete(test_stream)
        print("Test keys removed")

        # Close connection
        client.close()

        # Success
        print("\n" + "="*80)
        print("ALL TESTS PASSED")
        print("="*80)
        print("\nRedis Cloud connection is working correctly!")
        print("You can now run: python scripts/run_paper.py")
        print("")

        sys.exit(0)

    except redis.ConnectionError as e:
        print(f"\nCONNECTION ERROR: {e}")
        print("\nPossible causes:")
        print("  1. Incorrect REDIS_URL")
        print("  2. Network connectivity issues")
        print("  3. Redis Cloud instance not running")
        print("  4. Firewall blocking connection")
        sys.exit(1)

    except redis.AuthenticationError as e:
        print(f"\nAUTHENTICATION ERROR: {e}")
        print("\nPossible causes:")
        print("  1. Incorrect password in REDIS_URL")
        print("  2. Redis Cloud user permissions")
        sys.exit(1)

    except Exception as e:
        print(f"\nUNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    test_redis_connection()
