# Engine Telemetry Keys Reference

**Week 2 Implementation - Quick-Access Telemetry for signals-api**

This document provides complete reference for the lightweight Redis telemetry keys that enable `signals-api` to quickly compute system status without parsing complex stream data.

---

## Overview

The crypto-ai-bot engine maintains two Redis HASH keys that are updated on every signal and PnL publish:

1. **`engine:last_signal_meta`** - Last signal metadata
2. **`engine:last_pnl_meta`** - Last PnL metadata

These keys provide O(1) lookup for status endpoints, reducing stream lag and improving API response times.

---

## 1. `engine:last_signal_meta` (Redis HASH)

**Purpose:** Compact metadata about the most recent signal published.

**Updated:** On every signal publish (atomic HSET operation)

**TTL:** 24 hours (86400 seconds) - auto-cleanup if engine stops

### Field Structure

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `pair` | string | Trading pair | `"BTC/USD"` |
| `side` | string | Signal direction | `"LONG"` or `"SHORT"` |
| `strategy` | string | Strategy name | `"SCALPER"`, `"TREND"`, `"MEAN_REVERSION"`, `"BREAKOUT"` |
| `regime` | string | Market regime | `"TRENDING_UP"`, `"TRENDING_DOWN"`, `"RANGING"`, `"VOLATILE"` |
| `mode` | string | Trading mode | `"paper"` or `"live"` |
| `timestamp` | string | ISO8601 UTC timestamp | `"2025-11-30T13:22:57.983+00:00"` |
| `timestamp_ms` | string | Epoch milliseconds | `"1732971777983"` |
| `confidence` | string | Signal confidence (0.0-1.0) | `"0.75"` |
| `entry_price` | string | Entry price | `"50000.0"` |
| `signal_id` | string | Signal UUID | `"f9a3598a-e367-4bf7-b5d0-1a331ee46ae6"` |
| `timeframe` | string | Signal timeframe (optional) | `"5m"`, `"15s"`, `"1h"` |

### Redis CLI Commands

```bash
# Get all fields (most common)
HGETALL engine:last_signal_meta

# Get specific fields
HGET engine:last_signal_meta pair
HGET engine:last_signal_meta strategy
HGET engine:last_signal_meta timestamp
HGET engine:last_signal_meta confidence

# Check if key exists
EXISTS engine:last_signal_meta

# Check TTL (returns -1 if no TTL, -2 if key doesn't exist)
TTL engine:last_signal_meta

# Get key type (should be "hash")
TYPE engine:last_signal_meta
```

### Example Output

```bash
$ redis-cli -u rediss://default:...@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 --tls --cacert config/certs/redis_ca.pem HGETALL engine:last_signal_meta

1) "pair"
2) "BTC/USD"
3) "side"
4) "LONG"
5) "strategy"
6) "SCALPER"
7) "regime"
8) "TRENDING_UP"
9) "mode"
10) "paper"
11) "timestamp"
12) "2025-11-30T13:22:57.983+00:00"
13) "timestamp_ms"
14) "1732971777983"
15) "confidence"
16) "0.75"
17) "entry_price"
18) "50000.0"
19) "signal_id"
20) "f9a3598a-e367-4bf7-b5d0-1a331ee46ae6"
21) "timeframe"
22) "5m"
```

---

## 2. `engine:last_pnl_meta` (Redis HASH)

**Purpose:** Compact metadata about the most recent PnL update.

**Updated:** On every PnL publish (atomic HSET operation)

**TTL:** 24 hours (86400 seconds) - auto-cleanup if engine stops

### Field Structure

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `equity` | string | Current equity value | `"10500.0"` |
| `realized_pnl` | string | Total realized PnL | `"500.0"` |
| `unrealized_pnl` | string | Total unrealized PnL | `"100.0"` |
| `total_pnl` | string | Total PnL (realized + unrealized) | `"600.0"` |
| `num_positions` | string | Number of open positions | `"2"` |
| `drawdown_pct` | string | Current drawdown percentage | `"-2.5"` |
| `mode` | string | Trading mode | `"paper"` or `"live"` |
| `timestamp` | string | ISO8601 UTC timestamp | `"2025-11-30T13:22:58.097+00:00"` |
| `timestamp_ms` | string | Epoch milliseconds | `"1732971778097"` |

### Redis CLI Commands

```bash
# Get all fields (most common)
HGETALL engine:last_pnl_meta

# Get specific fields
HGET engine:last_pnl_meta equity
HGET engine:last_pnl_meta realized_pnl
HGET engine:last_pnl_meta total_pnl
HGET engine:last_pnl_meta timestamp

# Check if key exists
EXISTS engine:last_pnl_meta

# Check TTL
TTL engine:last_pnl_meta

# Get key type (should be "hash")
TYPE engine:last_pnl_meta
```

### Example Output

```bash
$ redis-cli -u rediss://default:...@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 --tls --cacert config/certs/redis_ca.pem HGETALL engine:last_pnl_meta

1) "equity"
2) "10500.0"
3) "realized_pnl"
4) "500.0"
5) "unrealized_pnl"
6) "100.0"
7) "total_pnl"
8) "600.0"
9) "num_positions"
10) "2"
11) "drawdown_pct"
12) "-2.5"
13) "mode"
14) "paper"
15) "timestamp"
16) "2025-11-30T13:22:58.097+00:00"
17) "timestamp_ms"
18) "1732971778097"
```

---

## Usage in signals-api

### Python (FastAPI) Example

```python
import redis.asyncio as redis
from typing import Optional, Dict

async def get_last_signal_meta(redis_client: redis.Redis) -> Optional[Dict[str, str]]:
    """
    Get last signal metadata with O(1) lookup.
    
    Returns None if key doesn't exist (engine not running or no signals yet).
    """
    data = await redis_client.hgetall("engine:last_signal_meta")
    if not data:
        return None
    
    # Decode bytes to strings (if using decode_responses=False)
    if isinstance(next(iter(data.values())), bytes):
        return {k.decode(): v.decode() for k, v in data.items()}
    return data

async def get_last_pnl_meta(redis_client: redis.Redis) -> Optional[Dict[str, str]]:
    """
    Get last PnL metadata with O(1) lookup.
    
    Returns None if key doesn't exist (engine not running or no PnL updates yet).
    """
    data = await redis_client.hgetall("engine:last_pnl_meta")
    if not data:
        return None
    
    # Decode bytes to strings (if using decode_responses=False)
    if isinstance(next(iter(data.values())), bytes):
        return {k.decode(): v.decode() for k, v in data.items()}
    return data

async def check_engine_alive(redis_client: redis.Redis) -> bool:
    """
    Check if engine is alive by checking if telemetry keys exist and have valid TTL.
    
    Returns True if engine appears to be running, False otherwise.
    """
    ttl = await redis_client.ttl("engine:last_signal_meta")
    # TTL > 0 means key exists and hasn't expired
    # TTL = -1 means key exists but has no expiration (shouldn't happen)
    # TTL = -2 means key doesn't exist
    return ttl > 0 or ttl == -1

# Example usage in FastAPI endpoint
@app.get("/v1/status")
async def get_status(redis: redis.Redis = Depends(get_redis)):
    """Get system status using telemetry keys."""
    last_signal = await get_last_signal_meta(redis)
    last_pnl = await get_last_pnl_meta(redis)
    is_alive = await check_engine_alive(redis)
    
    if not is_alive:
        return {
            "status": "offline",
            "message": "Engine not responding - telemetry keys not found"
        }
    
    return {
        "status": "online",
        "last_signal": last_signal,
        "last_pnl": last_pnl,
        "engine_mode": last_signal.get("mode") if last_signal else "unknown"
    }
```

### Node.js (Express) Example

```javascript
const redis = require('redis');

async function getLastSignalMeta(client) {
    const data = await client.hGetAll('engine:last_signal_meta');
    return Object.keys(data).length > 0 ? data : null;
}

async function getLastPnLMeta(client) {
    const data = await client.hGetAll('engine:last_pnl_meta');
    return Object.keys(data).length > 0 ? data : null;
}

async function checkEngineAlive(client) {
    const ttl = await client.ttl('engine:last_signal_meta');
    return ttl > 0 || ttl === -1;
}

// Express endpoint
app.get('/v1/status', async (req, res) => {
    const lastSignal = await getLastSignalMeta(redisClient);
    const lastPnL = await getLastPnLMeta(redisClient);
    const isAlive = await checkEngineAlive(redisClient);
    
    if (!isAlive) {
        return res.json({
            status: 'offline',
            message: 'Engine not responding'
        });
    }
    
    res.json({
        status: 'online',
        last_signal: lastSignal,
        last_pnl: lastPnL,
        engine_mode: lastSignal?.mode || 'unknown'
    });
});
```

---

## Performance Characteristics

### Lookup Performance

- **Operation:** `HGETALL` - O(N) where N is number of fields (typically 10-12 fields)
- **Latency:** < 1ms for local Redis, < 5ms for Redis Cloud
- **Network:** Single round-trip (no stream scanning required)

### Update Performance

- **Operation:** `HSET` with mapping - O(N) where N is number of fields
- **Latency:** < 1ms (atomic operation)
- **Impact:** Negligible - single HSET per signal/PnL publish

### Comparison to Stream Scanning

**Without Telemetry (Stream Scanning):**
- `XREVRANGE signals:paper:BTC-USD + - COUNT 1` - ~5-10ms
- Requires parsing stream entry
- Multiple round-trips if checking multiple pairs

**With Telemetry:**
- `HGETALL engine:last_signal_meta` - < 1ms
- Single round-trip
- No parsing required

**Performance Improvement:** ~5-10x faster for status checks

---

## TTL Behavior

### Why 24 Hours?

- **Auto-cleanup:** If engine stops, keys expire after 24 hours
- **Stale Detection:** signals-api can detect stale data by checking TTL
- **Memory Efficiency:** Prevents unbounded growth if engine crashes

### TTL Refresh

- TTL is refreshed on every update (signal or PnL publish)
- If engine is running normally, TTL will always be close to 24 hours
- If engine stops, TTL will count down to 0 and key will be deleted

### Checking TTL in signals-api

```python
async def is_engine_stale(redis_client: redis.Redis, max_age_seconds: int = 300) -> bool:
    """
    Check if engine data is stale (no updates in last max_age_seconds).
    
    Returns True if stale, False if fresh.
    """
    ttl = await redis_client.ttl("engine:last_signal_meta")
    
    if ttl == -2:  # Key doesn't exist
        return True
    
    if ttl == -1:  # No TTL (shouldn't happen, but handle gracefully)
        return False
    
    # Calculate age: 24 hours - remaining TTL
    age_seconds = (24 * 3600) - ttl
    return age_seconds > max_age_seconds
```

---

## Error Handling

### Key Doesn't Exist

- **Cause:** Engine not running, or no signals/PnL published yet
- **Handling:** Return `null` or empty dict, indicate "no recent activity"

### Wrong Key Type

- **Cause:** Key was created as wrong type (string instead of hash)
- **Handling:** Delete key and let engine recreate it, or use `DEL engine:last_signal_meta`

### TTL Issues

- **TTL = -1:** Key exists but has no expiration (shouldn't happen, but handle gracefully)
- **TTL = -2:** Key doesn't exist (engine not running)
- **TTL > 0:** Key exists and is fresh

---

## Implementation Details

### Location in Codebase

**File:** `agents/infrastructure/prd_publisher.py`

**Methods:**
- `_update_signal_telemetry()` - Updates `engine:last_signal_meta` after signal publish
- `_update_pnl_telemetry()` - Updates `engine:last_pnl_meta` after PnL publish

### Update Frequency

- **Signal Telemetry:** Updated on every `publish_signal()` call
- **PnL Telemetry:** Updated on every `publish_pnl()` call
- **Atomic:** Single `HSET` operation (no race conditions)

### Failure Handling

- Telemetry updates are **non-blocking**
- If telemetry update fails, signal/PnL publish still succeeds
- Errors are logged but don't affect main publishing flow

---

## Security Considerations

### No Secrets in Telemetry

- Telemetry keys contain **no sensitive data**
- No API keys, passwords, or credentials
- Safe to expose in status endpoints

### Access Control

- Telemetry keys follow same Redis access control as signal streams
- If signals-api can read streams, it can read telemetry keys
- No additional permissions required

---

## Migration Notes

### From Stream Scanning to Telemetry

**Before (Stream Scanning):**
```python
# Slow: requires stream scan
entries = await redis.xrevrange("signals:paper:BTC-USD", "+", "-", count=1)
if entries:
    signal_data = parse_stream_entry(entries[0])
```

**After (Telemetry):**
```python
# Fast: single hash lookup
signal_meta = await redis.hgetall("engine:last_signal_meta")
```

### Backward Compatibility

- Telemetry keys are **additive** - don't break existing stream-based code
- signals-api can use both: telemetry for status, streams for historical data
- Gradual migration recommended

---

## Troubleshooting

### Key Not Updating

1. **Check if PRDPublisher is being used:**
   ```python
   # Verify publisher is PRDPublisher, not old publisher
   from agents.infrastructure.prd_publisher import PRDPublisher
   ```

2. **Check logs for telemetry errors:**
   ```bash
   grep "Failed to update.*telemetry" logs/crypto_ai_bot.log
   ```

3. **Verify Redis connection:**
   ```python
   await redis_client.ping()
   ```

### Wrong Key Type

If key exists as wrong type (string instead of hash):

```bash
# Delete and let engine recreate
DEL engine:last_signal_meta
DEL engine:last_pnl_meta
```

### Stale Data

If TTL shows key is stale:

```python
ttl = await redis_client.ttl("engine:last_signal_meta")
if ttl < 0:
    # Key doesn't exist or has no TTL
    return {"status": "engine_offline"}
```

---

## Summary

✅ **Telemetry keys are implemented and working**

- `engine:last_signal_meta` - Updated on every signal publish
- `engine:last_pnl_meta` - Updated on every PnL publish
- TTL: 24 hours (auto-cleanup if engine stops)
- Performance: O(1) lookup, < 1ms latency
- signals-api reads these keys for fast status checks

**Status (Week 2 Complete):**
1. ✅ Engine writes telemetry keys on every signal/PnL publish
2. ✅ signals-api `/health` endpoint reads telemetry keys
3. ✅ Health response includes `engine_telemetry` field with last signal/PnL metadata
4. ✅ TTL set to 24 hours for auto-cleanup

**Verification:**
```bash
# Check health endpoint includes telemetry
curl https://signals-api-gateway.fly.dev/health | jq '.engine_telemetry'

# Expected response:
{
  "last_signal": {
    "pair": "ETH/USD",
    "strategy": "SCALPER",
    "side": "SHORT",
    "confidence": "0.8",
    "timestamp": "2025-11-30T14:34:45.341+00:00",
    "mode": "paper",
    "age_ms": 35744
  },
  "last_pnl": {
    "equity": "10500.0",
    "total_pnl": "650.0",
    "num_positions": "3",
    "timestamp": "2025-11-30T14:22:55.286+00:00",
    "mode": "paper"
  }
}
```

