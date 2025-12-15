# Engine Telemetry for signals-api/frontend

**Week 2 Task B Implementation**

## Overview

This document describes the lightweight Redis telemetry keys that `signals-api` and `signals-site` can use for quick status checks without scanning streams.

## Telemetry Keys

### 1. `engine:last_signal_meta` (Hash)

Contains metadata about the last published signal.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `pair` | string | Trading pair (e.g., "BTC/USD") |
| `side` | string | Signal direction ("LONG" or "SHORT") |
| `strategy` | string | Strategy name (e.g., "SCALPER") |
| `confidence` | string | Confidence score (0.0-1.0) |
| `entry_price` | string | Entry price |
| `mode` | string | Trading mode ("paper" or "live") |
| `timeframe` | string | Signal timeframe (e.g., "5m") |
| `signal_id` | string | Signal UUID |
| `timestamp` | string | ISO8601 timestamp |
| `timestamp_ms` | string | Epoch milliseconds |

**TTL:** 300 seconds (auto-expires if engine stops)

**Redis CLI:**
```bash
HGETALL engine:last_signal_meta
TTL engine:last_signal_meta
```

---

### 2. `engine:last_pnl_meta` (Hash)

Contains metadata about the last PnL update.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `equity` | string | Current equity value |
| `realized_pnl` | string | Realized PnL |
| `unrealized_pnl` | string | Unrealized PnL |
| `total_pnl` | string | Total PnL (realized + unrealized) |
| `num_positions` | string | Number of open positions |
| `drawdown_pct` | string | Current drawdown % |
| `mode` | string | Trading mode ("paper" or "live") |
| `win_rate` | string | Win rate (0.0-1.0) |
| `total_trades` | string | Total number of trades |
| `timestamp` | string | ISO8601 timestamp |
| `timestamp_ms` | string | Epoch milliseconds |

**TTL:** 300 seconds

**Redis CLI:**
```bash
HGETALL engine:last_pnl_meta
TTL engine:last_pnl_meta
```

---

### 3. `engine:status` (Hash)

Contains engine operational status.

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Engine status ("running", "starting", "stopping", "error") |
| `mode` | string | Trading mode ("paper" or "live") |
| `last_heartbeat` | string | ISO8601 timestamp of last heartbeat |
| `last_heartbeat_ms` | string | Epoch milliseconds |
| `uptime_seconds` | string | Engine uptime in seconds |
| `version` | string | Engine version |
| `active_pairs` | string | Comma-separated list of active pairs |

**TTL:** 300 seconds (key expires if engine dies = dead engine detection)

**Redis CLI:**
```bash
HGETALL engine:status
TTL engine:status
```

---

## Usage in signals-api

### Python (FastAPI)

```python
from redis.asyncio import Redis

async def get_last_signal_info(redis: Redis) -> dict:
    """Get last signal metadata with O(1) lookup."""
    data = await redis.hgetall("engine:last_signal_meta")
    if not data:
        return {"status": "no_recent_signal"}

    # Decode bytes to strings
    return {k.decode(): v.decode() for k, v in data.items()}

async def get_engine_health(redis: Redis) -> dict:
    """Check engine health via telemetry."""
    status = await redis.hgetall("engine:status")

    if not status:
        return {"status": "offline", "message": "Engine not responding"}

    # Check if heartbeat is recent
    ttl = await redis.ttl("engine:status")

    return {
        "status": "online" if ttl > 0 else "stale",
        "mode": status.get(b"mode", b"unknown").decode(),
        "last_heartbeat": status.get(b"last_heartbeat", b"").decode(),
        "uptime_seconds": int(status.get(b"uptime_seconds", b"0").decode()),
    }
```

### For `/status` endpoint

```python
@app.get("/v1/status")
async def get_status(redis: Redis = Depends(get_redis)):
    """Public-facing status page."""
    engine = await redis.hgetall("engine:status")
    last_signal = await redis.hgetall("engine:last_signal_meta")

    if engine:
        engine_status = "operational"
        mode = engine.get(b"mode", b"paper").decode()
    else:
        engine_status = "offline"
        mode = "unknown"

    return {
        "system": "Crypto AI Bot",
        "status": engine_status,
        "mode": mode,
        "last_signal": {
            "pair": last_signal.get(b"pair", b"N/A").decode(),
            "timestamp": last_signal.get(b"timestamp", b"N/A").decode(),
        } if last_signal else None,
    }
```

### For "Last Signal Generated at..." UI display

```python
async def get_last_signal_display(redis: Redis) -> str:
    """Get human-readable last signal info for UI."""
    data = await redis.hgetall("engine:last_signal_meta")

    if not data:
        return "No recent signals"

    pair = data.get(b"pair", b"").decode()
    side = data.get(b"side", b"").decode()
    timestamp = data.get(b"timestamp", b"").decode()

    return f"Last signal: {side} {pair} at {timestamp}"
```

---

## Performance Benefits

| Operation | Old Way (Stream Scan) | New Way (Hash Lookup) |
|-----------|----------------------|----------------------|
| Get last signal info | O(n) XREVRANGE | O(1) HGETALL |
| Check engine alive | O(n) Stream scan | O(1) EXISTS/TTL |
| Get PnL summary | O(n) XREVRANGE | O(1) HGETALL |

---

## Integration with crypto-ai-bot

Add telemetry updates where signals and PnL are published:

```python
from monitoring.telemetry import get_telemetry

# Initialize once at startup
telemetry = get_telemetry(redis_client)

# On each signal publish
telemetry.update_last_signal(
    pair="BTC/USD",
    side="LONG",
    strategy="SCALPER",
    confidence=0.87,
    entry_price=90850.0,
    mode="paper",
)

# On each PnL update
telemetry.update_last_pnl(
    equity=10500.0,
    realized_pnl=500.0,
    mode="paper",
)

# Periodically (e.g., every heartbeat)
telemetry.update_engine_status(
    status="running",
    mode="paper",
    version="1.0.0",
    pairs=["BTC/USD", "ETH/USD", "SOL/USD"],
)
```

---

## Files

| File | Description |
|------|-------------|
| `monitoring/telemetry.py` | Telemetry implementation |
| `tests/unit/test_telemetry.py` | Unit tests (11 tests) |
| `docs/TELEMETRY_USAGE.md` | This documentation |

---

## Redis CLI Quick Reference

```bash
# Check last signal
HGETALL engine:last_signal_meta

# Check last PnL
HGETALL engine:last_pnl_meta

# Check engine status
HGETALL engine:status

# Check if engine is alive (TTL > 0 = alive)
TTL engine:status

# Get specific field
HGET engine:last_signal_meta pair
HGET engine:status status
```
