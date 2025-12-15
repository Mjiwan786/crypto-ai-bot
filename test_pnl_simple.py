#!/usr/bin/env python3
"""Simple PnL pipeline test."""
import os
import sys

# Set environment variables BEFORE importing
os.environ["REDIS_URL"] = "rediss://default:&lt;REDIS_PASSWORD&gt;**%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0"
os.environ["EMIT_PNL_EVENTS"] = "true"
os.environ["START_EQUITY"] = "10000"

print("=" * 70)
print("PNL COMPONENTS TEST")
print("=" * 70)
print(f"Redis URL: {os.environ['REDIS_URL'][:60]}...")
print("=" * 70 + "\n")

# Test 1: Import publisher
print("Test 1: Importing pnl_publisher...")
try:
    from agents.infrastructure.pnl_publisher import publish_trade_close, publish_equity_point
    print("[OK] pnl_publisher imported successfully\n")
except ImportError as e:
    print(f"[FAIL] Could not import: {e}\n")
    sys.exit(1)

# Test 2: Test publish functions (will fail silently if Redis unavailable)
print("Test 2: Testing publish_trade_close...")
try:
    publish_trade_close({
        "id": "test_001",
        "ts": 1704067200000,
        "pair": "BTC/USD",
        "side": "long",
        "entry": 45000.0,
        "exit": 46000.0,
        "qty": 0.1,
        "pnl": 100.0,
    })
    print("[OK] publish_trade_close executed (check Redis to verify)\n")
except Exception as e:
    print(f"[FAIL] Error: {e}\n")

# Test 3: Check if aggregator can be imported
print("Test 3: Checking aggregator module...")
try:
    import monitoring.pnl_aggregator as agg
    print(f"[OK] Aggregator module loaded")
    print(f"     Redis URL configured: {agg.REDIS_URL[:60]}...")
    print(f"     Start Equity: ${agg.START_EQUITY:,.2f}\n")
except ImportError as e:
    print(f"[FAIL] Could not import aggregator: {e}\n")

# Test 4: Verify Redis connection
print("Test 4: Testing Redis connection...")
try:
    import redis
    client = redis.from_url(
        os.environ["REDIS_URL"],
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    client.ping()
    print("[OK] Redis connection successful\n")

    # Check if trades stream exists
    stream_len = client.xlen("trades:closed")
    print(f"[INFO] trades:closed stream has {stream_len} messages")

    # Check if equity stream exists
    equity_len = client.xlen("pnl:equity")
    print(f"[INFO] pnl:equity stream has {equity_len} messages\n")

except Exception as e:
    print(f"[WARN] Redis connection failed: {e}")
    print("       (This is OK for local testing without Redis)\n")

print("=" * 70)
print("TEST COMPLETE")
print("=" * 70)
print("\nTo run full pipeline:")
print("1. Terminal 1: python -m monitoring.pnl_aggregator")
print("2. Terminal 2: python scripts/seed_closed_trades.py")
print("3. Terminal 3: python scripts/health_check_pnl.py --verbose")
