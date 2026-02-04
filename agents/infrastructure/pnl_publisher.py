#!/usr/bin/env python3
"""
PnL Publisher - Crypto AI Bot

Publishes trade close events and equity snapshots to Redis streams for
downstream consumption by analytics, dashboards, and reporting systems.

Streams:
- "trades:closed" - Individual trade results
- "pnl:equity" - Equity curve snapshots

Usage:
    from agents.infrastructure.pnl_publisher import publish_trade_close, publish_equity_point

    # After closing a position
    publish_trade_close({
        "id": "trade_123",
        "ts": 1704067200000,
        "pair": "BTC/USD",
        "side": "long",
        "entry": 45000.0,
        "exit": 46000.0,
        "qty": 0.1,
        "pnl": 100.0
    })

    # Periodically
    publish_equity_point(
        ts_ms=1704067200000,
        equity=10500.0,
        daily_pnl=150.0
    )
"""

import os
from typing import Any, Dict, Optional

try:
    import orjson
except ImportError:
    import json as orjson  # Fallback to stdlib json

try:
    import redis
except ImportError:
    redis = None  # type: ignore


# Redis client singleton
_redis_client: Optional[Any] = None


def _get_redis_client():
    """Get or create Redis client singleton."""
    global _redis_client

    if _redis_client is None:
        if redis is None:
            return None

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        try:
            _redis_client = redis.from_url(
                redis_url,
                decode_responses=False,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            # Test connection
            _redis_client.ping()
        except Exception:
            # Silently fail - don't spam logs
            _redis_client = None

    return _redis_client


def publish_trade_close(event: dict) -> None:
    """
    Publish a trade close event to Redis stream "trades:closed".

    Args:
        event: Trade close event with required keys:
            - id (str): Unique trade identifier
            - ts (int): Timestamp in milliseconds
            - pair (str): Trading pair (e.g., "BTC/USD")
            - side (str): "long" or "short"
            - entry (float): Entry price
            - exit (float): Exit price
            - qty (float): Quantity traded
            - pnl (float): Realized profit/loss

    Returns:
        None (silent failure if Redis unavailable)
    """
    # Validate event is a dict
    if not isinstance(event, dict):
        return  # Silent validation failure

    # Validate required keys
    required_keys = ["id", "ts", "pair", "side", "entry", "exit", "qty", "pnl"]
    missing_keys = [k for k in required_keys if k not in event]
    if missing_keys:
        return  # Silent validation failure

    # Validate types
    try:
        assert isinstance(event["id"], str), "id must be str"
        assert isinstance(event["ts"], int), "ts must be int"
        assert isinstance(event["pair"], str), "pair must be str"
        assert event["side"] in ("long", "short"), "side must be 'long' or 'short'"
        assert isinstance(event["entry"], (int, float)), "entry must be numeric"
        assert isinstance(event["exit"], (int, float)), "exit must be numeric"
        assert isinstance(event["qty"], (int, float)), "qty must be numeric"
        assert isinstance(event["pnl"], (int, float)), "pnl must be numeric"
    except (AssertionError, KeyError, TypeError):
        return  # Silent validation failure

    # Serialize event
    try:
        if hasattr(orjson, 'dumps'):
            json_bytes = orjson.dumps(event)
        else:
            json_bytes = orjson.dumps(event).encode('utf-8')
    except Exception:
        return  # Silent serialization failure

    # Publish to Redis
    client = _get_redis_client()
    if client is None:
        return  # Redis unavailable

    try:
        client.xadd("trades:closed", {"json": json_bytes})
    except Exception:
        # Redis error - fail silently
        pass


def publish_equity_point(ts_ms: int, equity: float, daily_pnl: float) -> None:
    """
    Publish an equity snapshot to Redis stream "pnl:equity" and update latest value.

    Args:
        ts_ms: Timestamp in milliseconds
        equity: Current account equity
        daily_pnl: Daily profit/loss

    Returns:
        None (silent failure if Redis unavailable)
    """
    # Validate types
    try:
        assert isinstance(ts_ms, int), "ts_ms must be int"
        assert isinstance(equity, (int, float)), "equity must be numeric"
        assert isinstance(daily_pnl, (int, float)), "daily_pnl must be numeric"
    except AssertionError:
        return  # Silent validation failure

    # Create snapshot
    snapshot = {
        "ts": ts_ms,
        "equity": float(equity),
        "daily_pnl": float(daily_pnl),
    }

    # Serialize snapshot
    try:
        if hasattr(orjson, 'dumps'):
            json_bytes = orjson.dumps(snapshot)
        else:
            json_bytes = orjson.dumps(snapshot).encode('utf-8')
    except Exception:
        return  # Silent serialization failure

    # Publish to Redis
    client = _get_redis_client()
    if client is None:
        return  # Redis unavailable

    try:
        # Add to stream
        client.xadd("pnl:equity", {"json": json_bytes})

        # Update latest value
        client.set("pnl:equity:latest", json_bytes)
    except Exception:
        # Redis error - fail silently
        pass


if __name__ == "__main__":
    """Self-test block - sends dummy events to verify functionality."""
    print("PnL Publisher Self-Test")
    print("=" * 50)

    # Test 1: Trade close event
    print("\n1. Testing publish_trade_close...")
    dummy_trade = {
        "id": "test_trade_001",
        "ts": 1704067200000,
        "pair": "BTC/USD",
        "side": "long",
        "entry": 45000.0,
        "exit": 46000.0,
        "qty": 0.1,
        "pnl": 100.0,
    }
    publish_trade_close(dummy_trade)
    print(f"   Published: {dummy_trade}")

    # Test 2: Equity point
    print("\n2. Testing publish_equity_point...")
    publish_equity_point(
        ts_ms=1704067200000,
        equity=10500.0,
        daily_pnl=150.0,
    )
    print(f"   Published: ts=1704067200000, equity=10500.0, daily_pnl=150.0")

    # Test 3: Invalid event (should fail silently)
    print("\n3. Testing invalid event (should fail silently)...")
    invalid_trade = {"id": "incomplete"}  # Missing required keys
    publish_trade_close(invalid_trade)
    print("   Invalid event rejected (no error raised)")

    # Check Redis connection
    print("\n4. Checking Redis connection...")
    client = _get_redis_client()
    if client:
        print(f"   ✅ Connected to Redis")
        try:
            # Read back latest equity point
            latest = client.get("pnl:equity:latest")
            if latest:
                if hasattr(orjson, 'loads'):
                    data = orjson.loads(latest)
                else:
                    data = orjson.loads(latest.decode('utf-8'))
                print(f"   Latest equity point: {data}")
            else:
                print("   No equity data found (stream may be empty)")
        except Exception as e:
            print(f"   Could not read latest equity: {e}")
    else:
        print("   ⚠️  Redis not available (events will fail silently)")

    print("\n" + "=" * 50)
    print("Self-test complete!")
    print("\nNote: Events are published to streams only if Redis is reachable.")
    print("Use redis-cli to verify:")
    print("  XREAD COUNT 10 STREAMS trades:closed pnl:equity 0 0")
    print("  GET pnl:equity:latest")
