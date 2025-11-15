#!/usr/bin/env python3
"""
Complete PnL Pipeline Verification Script
Tests all components and shows current status.
"""
import os
import sys
import json

# Configure environment
os.environ["REDIS_URL"] = "rediss://default:Salam78614**%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0"
os.environ["EMIT_PNL_EVENTS"] = "true"
os.environ["START_EQUITY"] = "10000"

print("=" * 80)
print("PNL PIPELINE VERIFICATION")
print("=" * 80)
print(f"Redis URL: {os.environ['REDIS_URL'][:70]}...")
print("=" * 80 + "\n")

# Track results
results = []

def test(name, func):
    """Run a test and track result."""
    print(f"\n{'-' * 80}")
    print(f"TEST: {name}")
    print('-' * 80)
    try:
        func()
        print(f"[PASS] {name}")
        results.append((name, "PASS"))
        return True
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        results.append((name, "FAIL", str(e)))
        return False

# ============================================================================
# Test 1: Module Imports
# ============================================================================
def test_imports():
    """Verify all modules can be imported."""
    print("Checking imports...")

    # Publisher
    from agents.infrastructure.pnl_publisher import publish_trade_close, publish_equity_point
    print("  [OK] pnl_publisher")

    # Aggregator
    import monitoring.pnl_aggregator
    print("  [OK] monitoring.pnl_aggregator")

    # Redis
    import redis
    print("  [OK] redis")

    # Optional: orjson
    try:
        import orjson
        print("  [OK] orjson (performance)")
    except ImportError:
        print("  [WARN] orjson not available (using stdlib json)")

test("Module Imports", test_imports)

# ============================================================================
# Test 2: Redis Connection
# ============================================================================
def test_redis_connection():
    """Test Redis Cloud connection."""
    import redis

    print(f"Connecting to Redis Cloud...")
    client = redis.from_url(
        os.environ["REDIS_URL"],
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )

    # Ping
    result = client.ping()
    print(f"  [OK] PING response: {result}")

    # Check streams
    trades_len = client.xlen("trades:closed")
    equity_len = client.xlen("pnl:equity")

    print(f"  [INFO] trades:closed: {trades_len} messages")
    print(f"  [INFO] pnl:equity: {equity_len} messages")

    # Check latest equity
    latest_bytes = client.get("pnl:equity:latest")
    if latest_bytes:
        try:
            import orjson
            latest = orjson.loads(latest_bytes)
        except:
            latest = json.loads(latest_bytes.decode('utf-8'))

        print(f"  [INFO] Latest equity: ${latest['equity']:,.2f}")
        print(f"  [INFO] Daily PnL: ${latest['daily_pnl']:+,.2f}")

test("Redis Connection", test_redis_connection)

# ============================================================================
# Test 3: Publisher Functions
# ============================================================================
def test_publisher():
    """Test publisher functions."""
    from agents.infrastructure.pnl_publisher import publish_trade_close, publish_equity_point
    import time

    print("Testing publish_trade_close...")

    # Publish test trade
    test_trade = {
        "id": f"verify_test_{int(time.time())}",
        "ts": int(time.time() * 1000),
        "pair": "BTC/USD",
        "side": "long",
        "entry": 45000.0,
        "exit": 46000.0,
        "qty": 0.1,
        "pnl": 100.0,
    }

    publish_trade_close(test_trade)
    print(f"  [OK] Published trade: {test_trade['id']}")

    # Verify it's in Redis
    import redis
    client = redis.from_url(os.environ["REDIS_URL"], decode_responses=False)
    messages = client.xrevrange("trades:closed", "+", "-", count=1)

    if messages:
        msg_id, fields = messages[0]
        print(f"  [OK] Verified in Redis stream: {msg_id.decode('utf-8')}")

    # Test equity point
    print("\nTesting publish_equity_point...")
    publish_equity_point(
        ts_ms=int(time.time() * 1000),
        equity=10100.0,
        daily_pnl=100.0
    )
    print("  [OK] Published equity point")

test("Publisher Functions", test_publisher)

# ============================================================================
# Test 4: Aggregator Configuration
# ============================================================================
def test_aggregator_config():
    """Verify aggregator configuration."""
    import monitoring.pnl_aggregator as agg

    print("Checking aggregator configuration...")
    print(f"  Redis URL: {agg.REDIS_URL[:60]}...")
    print(f"  Start Equity: ${agg.START_EQUITY:,.2f}")
    print(f"  Poll Interval: {agg.POLL_MS}ms")
    print(f"  State Key: {agg.STATE_KEY}")
    print(f"  Pandas Enabled: {agg.USE_PANDAS and agg.PANDAS_ENABLED}")

    # Check if aggregator has processed anything
    import redis
    client = redis.from_url(os.environ["REDIS_URL"], decode_responses=False)

    last_id = client.get(agg.STATE_KEY)
    if last_id:
        print(f"  [INFO] Last processed ID: {last_id.decode('utf-8')}")
    else:
        print("  [INFO] No processing history (fresh state)")

test("Aggregator Configuration", test_aggregator_config)

# ============================================================================
# Test 5: PnL Hooks in Position Manager
# ============================================================================
def test_position_manager_hooks():
    """Verify PnL emission hooks are present."""
    print("Checking position_manager.py hooks...")

    with open("agents/scalper/execution/position_manager.py", "r") as f:
        content = f.read()

    # Check for key components
    checks = [
        ("import os", "Environment variable support"),
        ("publish_trade_close", "Publisher import"),
        ("EMIT_PNL_EVENTS", "Feature flag"),
        ("_PNL_EMIT_ENABLED", "Flag variable"),
        ("if _PNL_EMIT_ENABLED", "Conditional emission"),
    ]

    for check_str, description in checks:
        if check_str in content:
            print(f"  [OK] Found: {description}")
        else:
            raise Exception(f"Missing: {description}")

    print(f"  [OK] All hooks present in position_manager.py")

test("Position Manager Hooks", test_position_manager_hooks)

# ============================================================================
# Test 6: Backtest Adapter Hooks
# ============================================================================
def test_backtest_hooks():
    """Verify backtest adapter has PnL hooks."""
    print("Checking backtest_adapter.py hooks...")

    with open("strategies/backtest_adapter.py", "r") as f:
        content = f.read()

    checks = [
        ("publish_trade_close", "Publisher import"),
        ("EMIT_PNL_EVENTS", "Feature flag"),
        ("emit_pnl_events", "Emission toggle"),
        ("_emit_trade_close_event", "Emission method"),
        ("_track_position_entry", "Position tracking"),
    ]

    for check_str, description in checks:
        if check_str in content:
            print(f"  [OK] Found: {description}")
        else:
            raise Exception(f"Missing: {description}")

    print(f"  [OK] All hooks present in backtest_adapter.py")

test("Backtest Adapter Hooks", test_backtest_hooks)

# ============================================================================
# Test 7: File Structure
# ============================================================================
def test_file_structure():
    """Verify all required files exist."""
    import os.path

    files = [
        ("agents/infrastructure/pnl_publisher.py", "Publisher"),
        ("monitoring/pnl_aggregator.py", "Aggregator"),
        ("scripts/seed_closed_trades.py", "Trade seeder"),
        ("scripts/backfill_pnl_from_fills.py", "Backfill script"),
        ("scripts/health_check_pnl.py", "Health check"),
        ("scripts/verify_pnl_loop.py", "Loop verification"),
        ("docs/PNL_PIPELINE.md", "Pipeline docs"),
        ("docs/PNL_VERIFICATION.md", "Verification docs"),
        ("docs/PNL_BACKFILL.md", "Backfill docs"),
    ]

    print("Checking file structure...")
    for filepath, description in files:
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            print(f"  [OK] {description:20s} ({size:,} bytes) - {filepath}")
        else:
            raise Exception(f"Missing file: {filepath}")

test("File Structure", test_file_structure)

# ============================================================================
# Test 8: Stream Data Integrity
# ============================================================================
def test_stream_integrity():
    """Verify stream data is well-formed."""
    import redis

    print("Checking stream data integrity...")
    client = redis.from_url(os.environ["REDIS_URL"], decode_responses=False)

    # Check trades:closed
    trades = client.xrevrange("trades:closed", "+", "-", count=3)
    if trades:
        print(f"  [INFO] Found {len(trades)} recent trade(s)")
        for msg_id, fields in trades[:1]:  # Check first one
            json_bytes = fields.get(b"json") or fields.get("json")
            if json_bytes:
                try:
                    import orjson
                    data = orjson.loads(json_bytes)
                except:
                    data = json.loads(json_bytes.decode('utf-8'))

                # Verify required fields
                required = ["id", "ts", "pair", "side", "entry", "exit", "qty", "pnl"]
                for field in required:
                    if field not in data:
                        raise Exception(f"Missing field '{field}' in trade")

                print(f"  [OK] Trade data valid: {data['pair']} {data['side']} PnL=${data['pnl']:+.2f}")

    # Check pnl:equity
    equity = client.xrevrange("pnl:equity", "+", "-", count=3)
    if equity:
        print(f"  [INFO] Found {len(equity)} equity point(s)")
        for msg_id, fields in equity[:1]:
            json_bytes = fields.get(b"json") or fields.get("json")
            if json_bytes:
                try:
                    import orjson
                    data = orjson.loads(json_bytes)
                except:
                    data = json.loads(json_bytes.decode('utf-8'))

                # Verify required fields
                required = ["ts", "equity", "daily_pnl"]
                for field in required:
                    if field not in data:
                        raise Exception(f"Missing field '{field}' in equity")

                print(f"  [OK] Equity data valid: ${data['equity']:,.2f} (daily: ${data['daily_pnl']:+.2f})")

test("Stream Data Integrity", test_stream_integrity)

# ============================================================================
# Summary
# ============================================================================
print("\n" + "=" * 80)
print("VERIFICATION SUMMARY")
print("=" * 80)

passed = sum(1 for r in results if r[1] == "PASS")
failed = sum(1 for r in results if r[1] == "FAIL")
total = len(results)

for result in results:
    name = result[0]
    status = result[1]
    symbol = "[PASS]" if status == "PASS" else "[FAIL]"
    print(f"{symbol} {name}")

print("\n" + "=" * 80)
print(f"Results: {passed}/{total} tests passed")

if failed > 0:
    print(f"\n[WARN] {failed} test(s) failed - see details above")
    sys.exit(1)
else:
    print("\n[SUCCESS] All components verified successfully!")
    print("\nYou can now run the full pipeline:")
    print("  1. Terminal 1: python -m monitoring.pnl_aggregator")
    print("  2. Terminal 2: python scripts/seed_closed_trades.py --count 20")
    print("  3. Terminal 3: python scripts/health_check_pnl.py --verbose")
    sys.exit(0)
