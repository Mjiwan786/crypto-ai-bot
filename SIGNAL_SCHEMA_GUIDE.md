# Signal Schema & Stream Keys - Complete Guide

**Version:** 2.0
**Status:** Production Ready
**Date:** 2025-11-11

---

## Executive Summary

This guide documents the **new Pydantic v2 signal schema** and **stream key structure** for the crypto-ai-bot scalper system. Signals are validated before publishing to Redis Cloud streams with symbol-specific keys.

### Key Features

- **Pydantic v2 schema** with strict validation
- **Symbol-specific stream keys**: `signals:<SYMBOL>:<TIMEFRAME>`
- **Metrics stream**: `metrics:scalper`
- **Stable JSON ordering** with orjson
- **Fail-safe validation** with alerting on invalid signals
- **End-to-end tested** with Redis Cloud

---

## Stream Key Structure

### Signal Streams

**Format**: `signals:<SYMBOL>:<TIMEFRAME>`

**Examples**:
- `signals:BTC-USD:15s` - BTC/USD signals on 15-second timeframe
- `signals:ETH-USD:15s` - ETH/USD signals on 15-second timeframe
- `signals:BTC-USD:1m` - BTC/USD signals on 1-minute timeframe

**Symbol Normalization**:
- `/` is replaced with `-` for Redis compatibility
- Symbols are uppercased: `btc/usd` → `BTC-USD`

**Timeframe Validation**:
- Supported timeframes: `5s`, `10s`, `15s`, `30s`, `1m`, `2m`, `5m`, `10m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d`, `1w`
- Invalid timeframes are rejected

### Metrics Stream

**Format**: `metrics:scalper`

Contains publisher metrics:
- Signals published count
- Signals rejected count
- Daily PnL percentage
- Portfolio heat percentage
- Mode (live/paper)

---

## Signal Schema (Pydantic v2)

### Schema Definition

```python
class ScalperSignal(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    ts_exchange: int      # Exchange timestamp in milliseconds
    ts_server: int        # Server timestamp in milliseconds
    symbol: str           # Trading pair (e.g., "BTC/USD")
    timeframe: str        # Timeframe (e.g., "15s", "1m")
    side: Literal["long", "short"]
    confidence: float     # Signal confidence [0.0, 1.0]
    entry: float          # Entry price (must be > 0)
    stop: float           # Stop loss price (must be > 0)
    tp: float             # Take profit price (must be > 0)
    model: str            # Model identifier
    trace_id: str         # Unique trace ID for debugging
```

### Field Validation

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `ts_exchange` | int | >= 0, reasonable timestamp | Exchange timestamp (ms) |
| `ts_server` | int | >= ts_exchange, reasonable | Server timestamp (ms) |
| `symbol` | str | 3-20 chars, uppercase | Trading pair |
| `timeframe` | str | Valid TF from whitelist | Timeframe |
| `side` | str | "long" or "short" | Trade direction |
| `confidence` | float | [0.0, 1.0] | Signal confidence |
| `entry` | float | > 0 | Entry price |
| `stop` | float | > 0, logic validated | Stop loss price |
| `tp` | float | > 0, logic validated | Take profit price |
| `model` | str | 1-50 chars | Model name |
| `trace_id` | str | 8-64 chars | Unique ID |

### Logic Validation

**Long Signals**:
- Stop loss must be **below** entry: `stop < entry`
- Take profit must be **above** entry: `tp > entry`

**Short Signals**:
- Stop loss must be **above** entry: `stop > entry`
- Take profit must be **below** entry: `tp < entry`

**Timestamp Validation**:
- Server timestamp must be >= exchange timestamp
- Both timestamps must be within reasonable bounds (not ancient or far future)

---

## Signal Publishing Flow

### 1. Generate Signal

```python
signal_data = {
    "ts_exchange": int(time.time() * 1000),
    "ts_server": int(time.time() * 1000),
    "symbol": "BTC/USD",
    "timeframe": "15s",
    "side": "long",
    "confidence": 0.85,
    "entry": 45000.0,
    "stop": 44500.0,
    "tp": 46000.0,
    "model": "enhanced_scalper_v1",
    "trace_id": generate_trace_id(),
}
```

### 2. Validate Signal

```python
from signals.scalper_schema import validate_signal_safe

signal, error = validate_signal_safe(signal_data)

if signal is None:
    # Invalid signal - log and alert
    logger.error(f"[REJECTED] Signal validation failed: {error}")
    return
```

### 3. Publish to Redis

```python
stream_key = signal.get_stream_key()  # e.g., "signals:BTC-USD:15s"
signal_json = signal.to_json_str()    # Stable JSON with sorted keys

await redis_client.xadd(
    stream_key,
    {"signal": signal_json},
    maxlen=1000,  # Keep last 1000 signals
)

logger.info(f"[PUBLISHED] {signal.symbol} {signal.side} @ {signal.entry}")
```

---

## Usage Examples

### Example 1: Basic Signal Validation

```python
from signals.scalper_schema import ScalperSignal
import time

# Create signal
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
    model="test_model",
    trace_id="test-123",
)

# Get stream key
stream_key = signal.get_stream_key()
# Output: "signals:BTC-USD:15s"

# Get JSON
json_str = signal.to_json_str()
# Output: {"confidence":0.85,"entry":45000.0,...}
```

### Example 2: Safe Validation (Recommended)

```python
from signals.scalper_schema import validate_signal_safe

signal_data = {
    "ts_exchange": int(time.time() * 1000),
    "ts_server": int(time.time() * 1000),
    "symbol": "ETH/USD",
    "timeframe": "1m",
    "side": "short",
    "confidence": 0.75,
    "entry": 3000.0,
    "stop": 3050.0,  # Above entry for short
    "tp": 2950.0,    # Below entry for short
    "model": "scalper_v1",
    "trace_id": "abc-123",
}

signal, error = validate_signal_safe(signal_data)

if signal:
    print(f"Valid signal: {signal.trace_id}")
else:
    print(f"Invalid signal: {error}")
```

### Example 3: Publishing with Publisher Integration

```python
from agents.scalper.signal_publisher import SignalPublisher
from agents.infrastructure.redis_client import RedisCloudClient

# Initialize
redis_client = RedisCloudClient(config)
publisher = SignalPublisher(
    redis_client=redis_client,
    timeframe="15s",
    model_name="enhanced_scalper_v1",
)

# Publish signal (from EnhancedScalperAgent)
success = await publisher.publish_signal(
    enhanced_signal=scalper_signal,
    ts_exchange=exchange_timestamp,
    ts_server=server_timestamp,
)

if success:
    print("Signal published successfully")
```

---

## Integration with Live Scalper

The live scalper (`scripts/run_live_scalper.py`) automatically:

1. **Loads configuration** from `config/live_scalper_config.yaml`
2. **Initializes Redis client** with TLS
3. **Generates signals** for each trading pair
4. **Validates signals** using `validate_signal_safe()`
5. **Publishes to Redis** with proper stream keys
6. **Publishes metrics** every 10 iterations
7. **Handles errors** gracefully with logging

### Running the Live Scalper

```bash
# Paper trading mode (safe)
conda activate crypto-bot
python scripts/run_live_scalper.py

# View signals in Redis
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE signals:BTC-USD:15s + - COUNT 10
```

---

## Testing

### Run Schema Self-Tests

```bash
python signals/scalper_schema.py
```

**Tests**:
1. Create valid long signal
2. Invalid long signal (stop above entry) - should reject
3. Symbol normalization
4. Invalid timeframe - should reject
5. Safe validation with valid data
6. Invalid confidence (>1.0) - should reject
7. Stream key generation
8. JSON ordering stability

### Run End-to-End Test

```bash
python scripts/test_signal_flow.py
```

**Tests**:
1. Redis connection
2. Signal validation (BTC/USD, ETH/USD)
3. Signal publishing (3 iterations × 2 pairs)
4. Metrics publishing
5. Signal verification in Redis

**Expected Output**:
```
[PASS] END-TO-END TEST COMPLETED
       Signals published: 6
```

---

## File Manifest

| File | Purpose | Status |
|------|---------|--------|
| `signals/scalper_schema.py` | Pydantic v2 schema with validation | Tested |
| `agents/scalper/signal_publisher.py` | Publisher integration module | Created |
| `scripts/run_live_scalper.py` | Live scalper entrypoint | Updated |
| `scripts/test_signal_flow.py` | End-to-end test | Tested |
| `SIGNAL_SCHEMA_GUIDE.md` | This document | Complete |

---

## Error Handling

### Invalid Signals

When a signal fails validation:

1. **Alert logged** at CRITICAL level
2. **Signal dropped** (not published)
3. **Error details** logged with signal data
4. **Metrics updated** (signals_rejected counter)

Example log:
```
[ALERT] INVALID SIGNAL DROPPED
   Error: Long stop must be below entry: stop=45500.0, entry=45000.0
   Data: {'symbol': 'BTC/USD', 'side': 'long', ...}
```

### Redis Connection Failures

- **Automatic retry** with exponential backoff
- **Connection status** logged
- **Preflight checks** ensure Redis TLS is working before starting

---

## Configuration

### Environment Variables

```bash
REDIS_URL=rediss://user:pass@host:port    # Redis Cloud with TLS
REDIS_CA_CERT=config/certs/redis_ca.pem   # TLS certificate
```

### YAML Configuration

```yaml
redis:
  url: "${REDIS_URL}"
  ca_cert_path: "${REDIS_CA_CERT}"

  streams:
    signals_live: "signals:live:{pair}"    # Legacy (deprecated)
    metrics: "metrics:scalper"

trading:
  pairs:
    - BTC/USD
    - ETH/USD
    - SOL/USD
    - MATIC/USD
    - LINK/USD

  timeframes:
    primary: 15s
    secondary: 1m
```

---

## Best Practices

### 1. Always Validate Before Publishing

```python
# GOOD
signal, error = validate_signal_safe(signal_data)
if signal:
    await publish_to_redis(signal)
else:
    logger.error(f"Validation failed: {error}")

# BAD - Never skip validation
await publish_to_redis(signal_data)  # Might publish invalid signal
```

### 2. Use Safe Validation Wrapper

```python
# GOOD - Catches exceptions
signal, error = validate_signal_safe(signal_data)

# BAD - Might raise exception
signal = ScalperSignal(**signal_data)  # Can crash if invalid
```

### 3. Include Trace IDs

```python
# GOOD - Unique trace ID for debugging
trace_id = f"{int(time.time())}-{uuid.uuid4().hex[:12]}"

# BAD - Hard to trace signal through system
trace_id = "signal-1"
```

### 4. Monitor Rejection Rate

```python
# Alert if rejection rate is high
if signals_rejected / signals_generated > 0.1:
    logger.warning(f"High rejection rate: {rejection_rate:.1%}")
```

---

## Troubleshooting

### Signal Not Appearing in Redis

**Check**:
1. Validation passed: `signal, error = validate_signal_safe(...)`
2. Stream key correct: `signal.get_stream_key()`
3. Redis connected: `await redis_client.connect()`
4. TLS certificate valid: `config/certs/redis_ca.pem`

### Validation Failures

**Common issues**:
- Stop loss on wrong side of entry (long: stop > entry, short: stop < entry)
- Invalid timeframe (not in whitelist)
- Confidence out of range (< 0 or > 1)
- Invalid timestamp (ancient or far future)

### Stream Key Not Found

**Check**:
- Symbol normalization: `BTC/USD` → `BTC-USD`
- Timeframe lowercase: `15S` → `15s`
- Stream exists in Redis: `XINFO STREAM signals:BTC-USD:15s`

---

## Migration from Old Schema

### Old Format (Legacy)

```python
# Old stream keys
"signals:paper:BTC-USD"
"signals:live:BTC-USD"

# Old schema (no validation)
signal = {
    "symbol": "BTC/USD",
    "side": "long",
    "entry": 45000.0,
    # ... no validation
}
```

### New Format (Current)

```python
# New stream keys (symbol + timeframe)
"signals:BTC-USD:15s"
"signals:BTC-USD:1m"

# New schema (Pydantic v2 validated)
signal = ScalperSignal(
    ts_exchange=...,
    ts_server=...,
    symbol="BTC/USD",
    timeframe="15s",
    # ... all fields validated
)
```

---

## Appendix

### Supported Timeframes

| Timeframe | Description | Use Case |
|-----------|-------------|----------|
| `5s` | 5 seconds | Ultra high-frequency |
| `10s` | 10 seconds | High-frequency |
| `15s` | 15 seconds | **Default** primary timeframe |
| `30s` | 30 seconds | Medium-frequency |
| `1m` | 1 minute | **Default** secondary timeframe |
| `2m` | 2 minutes | Low-frequency |
| `5m` | 5 minutes | Swing trading |
| `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d`, `1w` | Higher timeframes | Trend analysis |

### Stream Key Generation Functions

```python
from signals.scalper_schema import (
    get_signal_stream_key,
    get_metrics_stream_key,
    get_all_signal_stream_keys,
)

# Single stream key
key = get_signal_stream_key("BTC/USD", "15s")
# Output: "signals:BTC-USD:15s"

# Metrics stream
metrics_key = get_metrics_stream_key()
# Output: "metrics:scalper"

# All stream keys for pairs and timeframes
keys = get_all_signal_stream_keys(
    symbols=["BTC/USD", "ETH/USD"],
    timeframes=["15s", "1m"]
)
# Output: [
#   "signals:BTC-USD:15s",
#   "signals:BTC-USD:1m",
#   "signals:ETH-USD:15s",
#   "signals:ETH-USD:1m",
# ]
```

---

## Summary

- **Schema**: Pydantic v2 with strict validation
- **Stream keys**: `signals:<SYMBOL>:<TF>` and `metrics:scalper`
- **Validation**: Fail-safe with error alerting
- **JSON**: Stable ordering with orjson
- **Testing**: Complete end-to-end tests passing
- **Status**: Production ready

**Next Steps**:
1. Run paper trading for 7+ days
2. Monitor validation rejection rate
3. Verify signals in signals-api
4. Go live after validation

---

**Document Version**: 2.0
**Last Updated**: 2025-11-11
**Author**: Senior Quant/Python Engineer
**Status**: Production Ready
