# Week 2 Task B: Telemetry Quick Reference

**Quick reference for signals-api integration**

---

## Telemetry Keys

### 1. `engine:last_signal_meta` (Redis HASH)

**Purpose:** Last signal metadata for `/status` and UI display

**Fields:**
```
pair          → "BTC/USD" (string)
strategy      → "SCALPER" (string)
mode          → "paper" | "live" (string)
timestamp     → "2025-01-27T12:34:56.789Z" (ISO8601 string)
confidence    → "0.85" (string, 0.0-1.0)
```

**TTL:** 7 days

---

### 2. `engine:last_pnl_meta` (Redis HASH)

**Purpose:** Last PnL metadata for `/metrics/system-health`

**Fields:**
```
realized_pnl  → "2500.0" (string)
timestamp     → "2025-01-27T12:34:56.789Z" (ISO8601 string)
equity        → "12500.0" (string)
num_positions → "2" (string)
mode          → "paper" | "live" (string)
```

**TTL:** 7 days

---

## Redis CLI Commands

### Inspect Last Signal

```bash
# Get all fields
HGETALL engine:last_signal_meta

# Get specific field
HGET engine:last_signal_meta pair
HGET engine:last_signal_meta timestamp
HGET engine:last_signal_meta confidence

# Check existence
EXISTS engine:last_signal_meta
```

### Inspect Last PnL

```bash
# Get all fields
HGETALL engine:last_pnl_meta

# Get specific field
HGET engine:last_pnl_meta equity
HGET engine:last_pnl_meta realized_pnl

# Check existence
EXISTS engine:last_pnl_meta
```

---

## signals-api Usage

### Python Example

```python
import redis.asyncio as redis

# Connect
redis_client = await redis.from_url(REDIS_URL)

# Get last signal (single HGETALL)
last_signal = await redis_client.hgetall("engine:last_signal_meta")
if last_signal:
    decoded = {k.decode(): v.decode() for k, v in last_signal.items()}
    print(f"Last signal: {decoded['pair']} {decoded['strategy']} @ {decoded['timestamp']}")

# Get last PnL (single HGETALL)
last_pnl = await redis_client.hgetall("engine:last_pnl_meta")
if last_pnl:
    decoded = {k.decode(): v.decode() for k, v in last_pnl.items()}
    print(f"Last equity: {decoded['equity']}, PnL: {decoded['realized_pnl']}")
```

---

## Performance

- **Read:** < 5ms (single HGETALL)
- **Write:** < 5ms (single HSET, non-blocking)
- **Storage:** ~200 bytes per key
- **Impact:** Negligible (performed after successful publish)

---

**Full Documentation:** See `docs/WEEK2_TASK_B_TELEMETRY.md`


