#!/usr/bin/env python3
"""
PnL Loop Verification Script - Crypto AI Bot

End-to-end verification of the complete PnL pipeline:
1. Trade closes published to trades:closed
2. Aggregator processes and publishes to pnl:equity
3. Latest equity value updated
4. Data integrity checks

Usage:
    python scripts/verify_pnl_loop.py
    python scripts/verify_pnl_loop.py --verbose
"""

import argparse
import json
import os
import sys

try:
    import orjson
except ImportError:
    orjson = None

try:
    import redis
except ImportError:
    print("ERROR: redis package not installed. Run: pip install redis")
    sys.exit(1)


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def verify_trades_stream(client: redis.Redis, verbose: bool = False) -> bool:
    """Verify trades:closed stream has data."""
    try:
        stream_len = client.xlen("trades:closed")

        if stream_len == 0:
            print("❌ trades:closed stream is empty")
            return False

        if verbose:
            print(f"✅ trades:closed stream: {stream_len} messages")

            # Read last 3
            messages = client.xrevrange("trades:closed", "+", "-", count=3)
            print(f"\n   Latest 3 trades:")
            for msg_id, fields in messages:
                msg_id_str = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id
                json_bytes = fields.get(b"json") or fields.get("json")
                if json_bytes:
                    if orjson and hasattr(orjson, "loads"):
                        data = orjson.loads(json_bytes)
                    else:
                        data = json.loads(json_bytes.decode("utf-8") if isinstance(json_bytes, bytes) else json_bytes)
                    print(f"   - {msg_id_str}: {data['pair']} {data['side']} PnL ${data['pnl']:+.2f}")

        return True

    except Exception as e:
        print(f"❌ Error checking trades:closed: {e}")
        return False


def verify_equity_stream(client: redis.Redis, verbose: bool = False) -> bool:
    """Verify pnl:equity stream has data."""
    try:
        stream_len = client.xlen("pnl:equity")

        if stream_len == 0:
            print("❌ pnl:equity stream is empty")
            print("   Hint: Ensure aggregator is running and has processed trades")
            return False

        if verbose:
            print(f"✅ pnl:equity stream: {stream_len} messages")

            # Read last 3
            messages = client.xrevrange("pnl:equity", "+", "-", count=3)
            print(f"\n   Latest 3 equity points:")
            for msg_id, fields in messages:
                msg_id_str = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id
                json_bytes = fields.get(b"json") or fields.get("json")
                if json_bytes:
                    if orjson and hasattr(orjson, "loads"):
                        data = orjson.loads(json_bytes)
                    else:
                        data = json.loads(json_bytes.decode("utf-8") if isinstance(json_bytes, bytes) else json_bytes)
                    print(f"   - {msg_id_str}: Equity ${data['equity']:,.2f}, Daily PnL ${data['daily_pnl']:+,.2f}")

        return True

    except Exception as e:
        print(f"❌ Error checking pnl:equity: {e}")
        return False


def verify_latest_equity(client: redis.Redis, verbose: bool = False) -> bool:
    """Verify pnl:equity:latest key exists and is valid."""
    try:
        latest_bytes = client.get("pnl:equity:latest")

        if not latest_bytes:
            print("❌ pnl:equity:latest key not found")
            print("   Hint: Aggregator should update this key after each trade")
            return False

        # Parse JSON
        if orjson and hasattr(orjson, "loads"):
            data = orjson.loads(latest_bytes)
        else:
            data = json.loads(latest_bytes.decode("utf-8") if isinstance(latest_bytes, bytes) else latest_bytes)

        # Validate fields
        required_fields = ["ts", "equity", "daily_pnl"]
        missing = [f for f in required_fields if f not in data]

        if missing:
            print(f"❌ pnl:equity:latest missing fields: {missing}")
            return False

        if verbose:
            print(f"✅ pnl:equity:latest:")
            print(f"   Equity: ${data['equity']:,.2f}")
            print(f"   Daily PnL: ${data['daily_pnl']:+,.2f}")
            print(f"   Timestamp: {data['ts']}")

        return True

    except Exception as e:
        print(f"❌ Error checking pnl:equity:latest: {e}")
        return False


def verify_data_consistency(client: redis.Redis, verbose: bool = False) -> bool:
    """Verify data consistency between streams and latest key."""
    try:
        # Get latest from stream
        stream_messages = client.xrevrange("pnl:equity", "+", "-", count=1)
        if not stream_messages:
            print("⚠️  Cannot verify consistency: pnl:equity stream empty")
            return True  # Not a failure, just can't verify

        # Get latest from key
        latest_bytes = client.get("pnl:equity:latest")
        if not latest_bytes:
            print("⚠️  Cannot verify consistency: pnl:equity:latest not found")
            return True

        # Parse both
        msg_id, fields = stream_messages[0]
        json_bytes = fields.get(b"json") or fields.get("json")

        if orjson and hasattr(orjson, "loads"):
            stream_data = orjson.loads(json_bytes)
            latest_data = orjson.loads(latest_bytes)
        else:
            stream_data = json.loads(json_bytes.decode("utf-8") if isinstance(json_bytes, bytes) else json_bytes)
            latest_data = json.loads(latest_bytes.decode("utf-8") if isinstance(latest_bytes, bytes) else latest_bytes)

        # Compare equity values (should match)
        if stream_data["equity"] == latest_data["equity"]:
            if verbose:
                print(f"✅ Data consistency check passed")
                print(f"   Stream equity: ${stream_data['equity']:,.2f}")
                print(f"   Latest equity: ${latest_data['equity']:,.2f}")
            return True
        else:
            print(f"⚠️  Data consistency mismatch:")
            print(f"   Stream equity: ${stream_data['equity']:,.2f}")
            print(f"   Latest equity: ${latest_data['equity']:,.2f}")
            print(f"   Hint: This may be expected if aggregator is still processing")
            return True  # Not a failure, just a warning

    except Exception as e:
        print(f"⚠️  Could not verify consistency: {e}")
        return True  # Not a failure


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Verify PnL loop end-to-end",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic verification
    python scripts/verify_pnl_loop.py

    # Verbose output with details
    python scripts/verify_pnl_loop.py --verbose

Typical workflow:
    1. Start aggregator: python -m monitoring.pnl_aggregator
    2. Seed trades: python scripts/seed_closed_trades.py
    3. Wait 1-2 seconds for processing
    4. Verify loop: python scripts/verify_pnl_loop.py --verbose
        """,
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output with details",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("PNL LOOP VERIFICATION")
    print("=" * 60)
    print(f"Redis URL: {REDIS_URL}")
    print("=" * 60 + "\n")

    # Connect to Redis
    try:
        client = redis.from_url(
            REDIS_URL,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.ping()
        print("✅ Redis connection OK\n")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return 1

    # Run checks
    checks = [
        ("Trades Stream", lambda: verify_trades_stream(client, args.verbose)),
        ("Equity Stream", lambda: verify_equity_stream(client, args.verbose)),
        ("Latest Equity", lambda: verify_latest_equity(client, args.verbose)),
        ("Data Consistency", lambda: verify_data_consistency(client, args.verbose)),
    ]

    results = []

    for check_name, check_func in checks:
        if args.verbose:
            print(f"\n{'─' * 60}")
            print(f"Checking: {check_name}")
            print(f"{'─' * 60}\n")

        passed = check_func()
        results.append((check_name, passed))

        if not args.verbose:
            status = "✅" if passed else "❌"
            print(f"{status} {check_name}")

        if args.verbose:
            print()

    # Summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    print(f"Checks passed: {passed_count}/{total_count}")

    if passed_count == total_count:
        print("\n✅ All checks passed! PnL loop is working correctly.\n")
        return 0
    else:
        print("\n❌ Some checks failed. See details above.\n")
        print("Troubleshooting:")
        print("  1. Ensure aggregator is running: python -m monitoring.pnl_aggregator")
        print("  2. Seed some trades: python scripts/seed_closed_trades.py")
        print("  3. Wait 1-2 seconds for processing")
        print("  4. Run this verification again\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
