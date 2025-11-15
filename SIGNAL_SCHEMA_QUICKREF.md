# Signal Schema - Quick Reference

**Version:** 2.0 | **Status:** Production Ready

---

## Stream Keys

### Signal Streams
```
signals:<SYMBOL>:<TIMEFRAME>

Examples:
  signals:BTC-USD:15s
  signals:ETH-USD:15s
  signals:BTC-USD:1m
```

### Metrics Stream
```
metrics:scalper
```

---

## Schema Fields

| Field | Type | Example | Constraints |
|-------|------|---------|-------------|
| `ts_exchange` | int | 1762861839000 | Milliseconds |
| `ts_server` | int | 1762861839000 | >= ts_exchange |
| `symbol` | str | "BTC/USD" | 3-20 chars |
| `timeframe` | str | "15s" | Valid TF |
| `side` | str | "long" | "long" \| "short" |
| `confidence` | float | 0.85 | [0.0, 1.0] |
| `entry` | float | 45000.0 | > 0 |
| `stop` | float | 44500.0 | > 0, logic check |
| `tp` | float | 46000.0 | > 0, logic check |
| `model` | str | "scalper_v1" | 1-50 chars |
| `trace_id` | str | "abc-123" | 8-64 chars |

---

## Quick Start

### 1. Create Signal
```python
from signals.scalper_schema import ScalperSignal
import time

signal = ScalperSignal(
    ts_exchange=int(time.time() * 1000),
    ts_server=int(time.time() * 1000),
    symbol="BTC/USD",
    timeframe="15s",
    side="long",
    confidence=0.85,
    entry=45000.0,
    stop=44500.0,
    tp=46000.0,
    model="test",
    trace_id="test-123",
)
```

### 2. Validate (Safe)
```python
from signals.scalper_schema import validate_signal_safe

signal, error = validate_signal_safe(signal_data)

if signal is None:
    print(f"Invalid: {error}")
```

### 3. Publish to Redis
```python
stream_key = signal.get_stream_key()
signal_json = signal.to_json_str()

await redis_client.xadd(
    stream_key,
    {"signal": signal_json},
    maxlen=1000,
)
```

---

## Validation Rules

### Long Signals
- `stop < entry` (stop below entry)
- `tp > entry` (take profit above entry)

### Short Signals
- `stop > entry` (stop above entry)
- `tp < entry` (take profit below entry)

---

## Testing

### Schema Tests
```bash
python signals/scalper_schema.py
```

### End-to-End Test
```bash
python scripts/test_signal_flow.py
```

### View Signals in Redis
```bash
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE signals:BTC-USD:15s + - COUNT 10
```

---

## Common Issues

| Issue | Solution |
|-------|----------|
| Stop on wrong side | Check side: long→stop<entry, short→stop>entry |
| Invalid timeframe | Use: 5s, 10s, 15s, 30s, 1m, 2m, 5m, etc. |
| Confidence out of range | Must be [0.0, 1.0] |
| Stream not found | Check symbol normalization: BTC/USD → BTC-USD |

---

## Files

| File | Purpose |
|------|---------|
| `signals/scalper_schema.py` | Schema definition |
| `agents/scalper/signal_publisher.py` | Publisher integration |
| `scripts/run_live_scalper.py` | Live scalper |
| `scripts/test_signal_flow.py` | End-to-end test |

---

## Documentation

- **Complete Guide**: `SIGNAL_SCHEMA_GUIDE.md`
- **Live Scalper**: `LIVE_SCALPER_GUIDE.md`
- **Quick Ref**: This file

---

**Status**: Production Ready
