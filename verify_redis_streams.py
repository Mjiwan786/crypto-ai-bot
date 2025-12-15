#!/usr/bin/env python3
"""
Verify Redis Streams for crypto-ai-bot Production Engine
Checks that all expected streams are being published with valid data
"""
import redis
import ssl
import os
import json
from datetime import datetime
from typing import Dict, List, Any

# Redis Cloud connection details - MUST use environment variables (no hardcoded secrets)
from dotenv import load_dotenv
load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "")
if not REDIS_URL:
    raise ValueError("REDIS_URL environment variable must be set")
REDIS_CA_CERT = os.getenv("REDIS_CA_CERT", os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem"))

# Expected streams
EXPECTED_STREAMS = [
    "kraken:heartbeat",
    "kraken:metrics",
    "kraken:ticker",
    "signals:paper:BTC-USD",
    "signals:paper:ETH-USD",
    "signals:paper:SOL-USD",
    "pnl:summary",
    "pnl:equity_curve",
]

# Also check for OHLCV and trade streams (dynamic based on pairs/timeframes)
PATTERN_STREAMS = [
    "kraken:ohlc:*",
    "kraken:trade:*",
    "kraken:spread:*",
    "signals:paper:*",
]


def connect_redis() -> redis.Redis:
    """Connect to Redis Cloud with TLS"""
    print("[1] Connecting to Redis Cloud...")

    # Create SSL context
    ssl_context = ssl.create_default_context()
    if os.path.exists(REDIS_CA_CERT):
        ssl_context.load_verify_locations(REDIS_CA_CERT)
        print(f"    [OK] Loaded TLS certificate from {REDIS_CA_CERT}")
    else:
        print(f"    [WARNING] TLS certificate not found at {REDIS_CA_CERT}, using system certs")

    # Connect to Redis
    client = redis.from_url(
        REDIS_URL,
        ssl_cert_reqs='required',
        ssl_ca_certs=REDIS_CA_CERT if os.path.exists(REDIS_CA_CERT) else None,
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=5,
    )

    # Test connection
    client.ping()
    print("    [OK] Connected to Redis Cloud successfully!\n")

    return client


def scan_keys_by_pattern(client: redis.Redis, pattern: str) -> List[str]:
    """Scan for keys matching a pattern"""
    keys = []
    cursor = 0
    while True:
        cursor, partial_keys = client.scan(cursor, match=pattern, count=100)
        keys.extend(partial_keys)
        if cursor == 0:
            break
    return sorted(keys)


def get_stream_info(client: redis.Redis, stream_key: str) -> Dict[str, Any]:
    """Get info about a stream"""
    try:
        length = client.xlen(stream_key)

        # Get latest entry
        latest = None
        if length > 0:
            entries = client.xrevrange(stream_key, count=1)
            if entries:
                entry_id, entry_data = entries[0]
                latest = {
                    "id": entry_id,
                    "data": entry_data,
                }

        return {
            "exists": True,
            "length": length,
            "latest": latest,
        }
    except Exception as e:
        return {
            "exists": False,
            "error": str(e),
        }


def verify_streams(client: redis.Redis):
    """Verify all expected streams"""
    print("[2] Verifying Expected Streams")
    print("=" * 80)

    results = {}

    # Check specific expected streams
    for stream_key in EXPECTED_STREAMS:
        info = get_stream_info(client, stream_key)
        results[stream_key] = info

        if info["exists"]:
            print(f"[OK] {stream_key}")
            print(f"     Length: {info['length']} messages")
            if info["latest"]:
                print(f"     Latest: {info['latest']['id']}")
                # Pretty print first few fields
                data = info["latest"]["data"]
                preview = dict(list(data.items())[:3])
                print(f"     Sample: {json.dumps(preview, indent=13)}")
        else:
            print(f"[MISSING] {stream_key}")
            if "error" in info:
                print(f"          Error: {info['error']}")
        print()

    print("\n[3] Scanning for Pattern-based Streams")
    print("=" * 80)

    # Check pattern-based streams
    for pattern in PATTERN_STREAMS:
        print(f"Pattern: {pattern}")
        keys = scan_keys_by_pattern(client, pattern)

        if keys:
            print(f"    Found {len(keys)} streams:")
            for key in keys[:10]:  # Show first 10
                info = get_stream_info(client, key)
                print(f"    [OK] {key} (length: {info.get('length', 0)})")

            if len(keys) > 10:
                print(f"    ... and {len(keys) - 10} more")
        else:
            print(f"    [MISSING] No streams found matching {pattern}")
        print()

    return results


def verify_data_freshness(client: redis.Redis):
    """Check how recent the data is"""
    print("\n[4] Checking Data Freshness")
    print("=" * 80)

    now = datetime.now().timestamp()

    # Check heartbeat (should be very recent)
    heartbeat_info = get_stream_info(client, "kraken:heartbeat")
    if heartbeat_info["exists"] and heartbeat_info["latest"]:
        data = heartbeat_info["latest"]["data"]
        timestamp = float(data.get("timestamp", 0))
        age_seconds = now - timestamp

        print(f"Heartbeat Age: {age_seconds:.1f} seconds")
        if age_seconds < 60:
            print("[OK] Heartbeat is fresh (< 60s)")
        else:
            print(f"[WARNING] Heartbeat is stale ({age_seconds:.1f}s old)")
    else:
        print("[MISSING] No heartbeat found")

    # Check recent signal
    signal_keys = scan_keys_by_pattern(client, "signals:paper:*")
    if signal_keys:
        latest_signal_key = signal_keys[0]
        signal_info = get_stream_info(client, latest_signal_key)
        if signal_info["exists"] and signal_info["latest"]:
            data = signal_info["latest"]["data"]
            timestamp = float(data.get("timestamp", 0))
            age_seconds = now - timestamp

            print(f"\nLatest Signal ({latest_signal_key}) Age: {age_seconds:.1f} seconds")
            if age_seconds < 300:  # 5 minutes
                print("[OK] Signals are fresh (< 5 minutes)")
            else:
                print(f"[WARNING] Signals are stale ({age_seconds:.1f}s old)")
    else:
        print("\n[MISSING] No signals found")

    print()


def main():
    """Main verification function"""
    print("=" * 80)
    print("Redis Streams Verification for crypto-ai-bot")
    print("=" * 80)
    print()

    try:
        # Connect to Redis
        client = connect_redis()

        # Verify streams
        results = verify_streams(client)

        # Check data freshness
        verify_data_freshness(client)

        # Summary
        print("\n[5] Summary")
        print("=" * 80)

        total = len(EXPECTED_STREAMS)
        existing = sum(1 for r in results.values() if r.get("exists"))

        print(f"Expected Streams: {existing}/{total} found")

        if existing == total:
            print("[SUCCESS] All expected streams are present and publishing data!")
        elif existing > 0:
            print("[PARTIAL] Some streams are present, but not all")
        else:
            print("[CRITICAL] No expected streams found!")

        print("\n" + "=" * 80)

    except Exception as e:
        print(f"\n[ERROR] Verification failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
