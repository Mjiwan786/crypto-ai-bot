# Serialization & Contracts Documentation

## Overview

This document describes the cross-cutting serialization utilities and Redis stream contracts used throughout the trading system.

**Key Components:**
- `agents/core/serialization.py` - JSON serialization with Decimal and datetime support
- `agents/core/contracts.py` - Redis stream message contracts with Pydantic v2 validators

---

## Serialization Utilities

### Purpose

Provides consistent JSON serialization across the codebase with support for:
- High-performance serialization with orjson (optional)
- Decimal to string conversion without trailing zeros
- Datetime to ISO 8601 conversion
- Single point to switch JSON backends

### Module: `agents.core.serialization`

#### `json_dumps(obj, *, indent=None, ensure_ascii=False) -> str`

Serialize object to JSON string using orjson if available, fallback to json.

**Features:**
- Uses orjson for performance when available
- Automatic fallback to standard json library
- Handles Decimal and datetime objects
- Compact output by default

**Examples:**

```python
from agents.core.serialization import json_dumps
from decimal import Decimal
from datetime import datetime, timezone

# Simple serialization
data = {"symbol": "BTC/USD", "price": 50000}
json_str = json_dumps(data)
# Output: '{"symbol":"BTC/USD","price":50000}'

# With Decimal
data = {"price": Decimal("50000.00")}
json_str = json_dumps(data)
# Output: '{"price":"50000"}'

# With datetime
data = {"timestamp": datetime(2025, 10, 11, 12, 0, 0, tzinfo=timezone.utc)}
json_str = json_dumps(data)
# Output: '{"timestamp":"2025-10-11T12:00:00+00:00"}'

# Indented output
json_str = json_dumps(data, indent=2)
# Output (pretty-printed):
# {
#   "timestamp": "2025-10-11T12:00:00+00:00"
# }
```

---

#### `decimal_to_str(x: Decimal) -> str` / `to_decimal_str(x: Decimal) -> str`

Convert Decimal to string, removing trailing zeros and unnecessary decimal point.

**Features:**
- Removes trailing zeros
- Handles scientific notation
- Consistent string representation

**Examples:**

```python
from agents.core.serialization import decimal_to_str, to_decimal_str
from decimal import Decimal

# Remove trailing zeros
decimal_to_str(Decimal("123.45000"))  # "123.45"
decimal_to_str(Decimal("100.00"))     # "100"
decimal_to_str(Decimal("0.00100"))    # "0.001"

# Alias (same function)
to_decimal_str(Decimal("123.45"))     # "123.45"
```

---

#### `ts_to_iso(dt: datetime) -> str`

Convert datetime to ISO 8601 string with UTC timezone.

**Features:**
- Always returns UTC timezone format
- Treats naive datetime as UTC
- Converts non-UTC timezones to UTC

**Examples:**

```python
from agents.core.serialization import ts_to_iso
from datetime import datetime, timezone

# UTC datetime
dt = datetime(2025, 10, 11, 12, 30, 45, tzinfo=timezone.utc)
ts_to_iso(dt)  # "2025-10-11T12:30:45+00:00"

# Naive datetime (treated as UTC)
dt = datetime(2025, 10, 11, 12, 30, 45)
ts_to_iso(dt)  # "2025-10-11T12:30:45+00:00"
```

---

#### `serialize_for_redis(obj: Any) -> str`

Convenience function for Redis serialization with Decimal/datetime support.

**Features:**
- Handles Decimal and datetime recursively
- Compact JSON output
- Ready for Redis storage

**Examples:**

```python
from agents.core.serialization import serialize_for_redis
from decimal import Decimal
from datetime import datetime, timezone

data = {
    "symbol": "BTC/USD",
    "price": Decimal("50000.00"),
    "timestamp": datetime(2025, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
}

json_str = serialize_for_redis(data)
# Output: '{"symbol":"BTC/USD","price":"50000","timestamp":"2025-10-11T12:00:00+00:00"}'
```

---

## Redis Stream Contracts

### Purpose

Defines canonical message schemas for Redis streams with Pydantic v2 validators to ensure:
- Type safety and consistency
- Clear error messages for invalid payloads
- Automatic type coercion where safe
- Documentation for each field

### Module: `agents.core.contracts`

---

### Contract 1: SignalPayload

**Redis Streams:** `signals:paper`, `signals:live`

**Purpose:** Trading signals with entry/exit parameters and metadata.

**Schema:**

```python
{
    "id": str,           # Unique signal identifier (non-empty)
    "ts": float,         # Unix timestamp (positive)
    "pair": str,         # Trading pair (BASE/QUOTE format, e.g., "BTC/USD")
    "side": str,         # "buy" or "sell" (lowercase)
    "entry": float,      # Entry price (positive)
    "sl": float,         # Stop loss price (positive)
    "tp": float,         # Take profit price (positive)
    "strategy": str,     # Strategy name (non-empty)
    "confidence": float  # Confidence score (0.0 to 1.0)
}
```

**Validation Rules:**

1. **Price Relationships for Buy Signals:**
   - SL must be below entry
   - TP must be above entry

2. **Price Relationships for Sell Signals:**
   - SL must be above entry
   - TP must be below entry

3. **Trading Pair:**
   - Automatically converted to uppercase
   - Must have "/" separator
   - Format: "BASE/QUOTE"

**Examples:**

```python
from agents.core.contracts import SignalPayload, validate_signal_payload

# Valid buy signal
signal = SignalPayload(
    id="sig_001",
    ts=1234567890.123,
    pair="BTC/USD",
    side="buy",
    entry=50000.0,
    sl=49000.0,  # Below entry
    tp=52000.0,  # Above entry
    strategy="momentum",
    confidence=0.85
)

# Convert to dict for Redis
payload = signal.model_dump()

# Validate from dict (e.g., from Redis)
data = {
    "id": "sig_002",
    "ts": 1234567890.0,
    "pair": "ETH/USDT",
    "side": "sell",
    "entry": 1800.0,
    "sl": 1850.0,  # Above entry
    "tp": 1750.0,  # Below entry
    "strategy": "mean_reversion",
    "confidence": 0.75
}
signal = validate_signal_payload(data)

# Lowercase pair is converted to uppercase
signal = SignalPayload(
    id="sig_003",
    ts=1234567890.0,
    pair="btc/usd",  # Lowercase
    side="buy",
    entry=50000.0,
    sl=49000.0,
    tp=52000.0,
    strategy="test",
    confidence=0.8
)
assert signal.pair == "BTC/USD"  # Converted to uppercase
```

**Error Examples:**

```python
from pydantic import ValidationError

# Invalid: SL above entry for buy signal
try:
    signal = SignalPayload(
        id="sig_001",
        ts=1234567890.0,
        pair="BTC/USD",
        side="buy",
        entry=50000.0,
        sl=51000.0,  # Invalid: above entry
        tp=52000.0,
        strategy="test",
        confidence=0.8
    )
except ValueError as e:
    print(e)  # "Buy signal: stop loss (51000.0) must be below entry (50000.0)"

# Invalid: confidence out of range
try:
    signal = SignalPayload(
        id="sig_001",
        ts=1234567890.0,
        pair="BTC/USD",
        side="buy",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=1.5  # Invalid: > 1.0
    )
except ValidationError as e:
    print(e)  # ValidationError with clear message
```

---

### Contract 2: MetricsLatencyPayload

**Redis Stream:** `metrics:latency`

**Purpose:** Latency metrics for system components.

**Schema:**

```python
{
    "component": str,  # Component name (non-empty)
    "p50": float,      # 50th percentile latency in ms (>= 0)
    "p95": float,      # 95th percentile latency in ms (>= p50)
    "window_s": int    # Time window in seconds (> 0)
}
```

**Validation Rules:**

1. p95 must be >= p50
2. All latency values must be non-negative
3. window_s must be positive

**Examples:**

```python
from agents.core.contracts import MetricsLatencyPayload, validate_metrics_latency_payload

# Valid metrics
metrics = MetricsLatencyPayload(
    component="kraken_api",
    p50=45.2,
    p95=128.7,
    window_s=60
)

# Convert to dict
payload = metrics.model_dump()

# Validate from dict
data = {
    "component": "redis",
    "p50": 2.5,
    "p95": 5.0,
    "window_s": 60
}
metrics = validate_metrics_latency_payload(data)

# p50 can equal p95
metrics = MetricsLatencyPayload(
    component="local_cache",
    p50=1.0,
    p95=1.0,
    window_s=60
)
```

**Error Examples:**

```python
from pydantic import ValidationError

# Invalid: p95 < p50
try:
    metrics = MetricsLatencyPayload(
        component="test",
        p50=100.0,
        p95=50.0,  # Invalid: less than p50
        window_s=60
    )
except ValueError as e:
    print(e)  # "p95 (50.0ms) must be >= p50 (100.0ms)"

# Invalid: negative latency
try:
    metrics = MetricsLatencyPayload(
        component="test",
        p50=-10.0,  # Invalid: negative
        p95=128.7,
        window_s=60
    )
except ValidationError as e:
    print(e)  # ValidationError with clear message
```

---

### Contract 3: HealthStatusPayload

**Redis Stream:** `status:health`

**Purpose:** Overall system health with individual component checks.

**Schema:**

```python
{
    "ok": bool,                      # Overall health status
    "checks": Dict[str, bool]        # Component name -> status mapping
}
```

**Validation Rules:**

1. checks dictionary cannot be empty
2. All component names must be non-empty strings
3. All status values must be booleans
4. If ok=True but some checks failed, a warning is logged

**Examples:**

```python
from agents.core.contracts import HealthStatusPayload, validate_health_status_payload

# Valid healthy status
health = HealthStatusPayload(
    ok=True,
    checks={
        "redis": True,
        "kraken": True,
        "postgres": True
    }
)

# Unhealthy status (kraken failed)
health = HealthStatusPayload(
    ok=False,
    checks={
        "redis": True,
        "kraken": False,  # Failed
        "postgres": True
    }
)

# Convert to dict
payload = health.model_dump()

# Validate from dict
data = {
    "ok": True,
    "checks": {
        "redis": True,
        "kraken_api": True,
        "signal_processor": True
    }
}
health = validate_health_status_payload(data)
```

**Error Examples:**

```python
from pydantic import ValidationError

# Invalid: empty checks
try:
    health = HealthStatusPayload(
        ok=True,
        checks={}  # Invalid: empty
    )
except ValidationError as e:
    print(e)  # ValidationError about empty checks

# Invalid: non-boolean value
try:
    health = HealthStatusPayload(
        ok=True,
        checks={
            "redis": True,
            "kraken": "healthy"  # Invalid: not a boolean
        }
    )
except ValidationError as e:
    print(e)  # ValidationError with clear message
```

---

## Publishing to Redis Streams

### Signal Publishing

**Paper Trading:**

```python
from agents.core.contracts import SignalPayload
from agents.core.serialization import serialize_for_redis
import redis

# Create signal
signal = SignalPayload(
    id="momentum_20251011_123045",
    ts=1697000000.123,
    pair="BTC/USD",
    side="buy",
    entry=50000.0,
    sl=49000.0,
    tp=52000.0,
    strategy="momentum",
    confidence=0.85
)

# Serialize
payload_dict = signal.model_dump()
payload_json = serialize_for_redis(payload_dict)

# Publish to Redis stream
r = redis.Redis()
r.xadd("signals:paper", {"payload": payload_json})
```

**Live Trading:**

```python
# Same as paper trading, but use "signals:live" stream
r.xadd("signals:live", {"payload": payload_json})
```

---

### Metrics Publishing

```python
from agents.core.contracts import MetricsLatencyPayload
from agents.core.serialization import serialize_for_redis

# Create metrics
metrics = MetricsLatencyPayload(
    component="kraken_api",
    p50=45.2,
    p95=128.7,
    window_s=60
)

# Serialize
payload_dict = metrics.model_dump()
payload_json = serialize_for_redis(payload_dict)

# Publish to Redis stream
r.xadd("metrics:latency", {"payload": payload_json})
```

---

### Health Status Publishing

```python
from agents.core.contracts import HealthStatusPayload
from agents.core.serialization import serialize_for_redis

# Create health status
health = HealthStatusPayload(
    ok=True,
    checks={
        "redis": True,
        "kraken": True,
        "postgres": True
    }
)

# Serialize
payload_dict = health.model_dump()
payload_json = serialize_for_redis(payload_dict)

# Publish to Redis stream
r.xadd("status:health", {"payload": payload_json})
```

---

## Consuming from Redis Streams

### Signal Consumption

```python
from agents.core.contracts import validate_signal_payload
import redis
import json

# Read from stream
r = redis.Redis()
messages = r.xread({"signals:paper": "0-0"}, count=10)

for stream_name, stream_messages in messages:
    for message_id, fields in stream_messages:
        # Parse payload
        payload_json = fields[b"payload"].decode("utf-8")
        payload_dict = json.loads(payload_json)

        try:
            # Validate with contract
            signal = validate_signal_payload(payload_dict)

            # Process signal
            print(f"Signal: {signal.pair} {signal.side} @ {signal.entry}")

        except Exception as e:
            print(f"Invalid payload: {e}")
```

---

## Testing

### Running Tests

```bash
# Test serialization utilities
pytest agents/core/tests/test_serialization.py -v

# Test contract validation
pytest agents/core/tests/test_contracts.py -v

# Run all tests
pytest agents/core/tests/ -v

# With coverage
pytest agents/core/tests/ --cov=agents.core --cov-report=term-missing
```

### Test Coverage

**Serialization Tests (34 tests):**
- json_dumps with orjson and json fallback
- Decimal conversion with trailing zeros
- Datetime to ISO 8601 conversion
- serialize_for_redis with nested structures
- Edge cases (None, boolean, unicode, large numbers)

**Contract Tests (41 tests):**
- SignalPayload validation (buy/sell signals)
- MetricsLatencyPayload validation
- HealthStatusPayload validation
- Error handling with clear messages
- Integration tests with Redis-like data

---

## Error Handling

### Validation Errors

All validation errors use Pydantic's ValidationError with clear, descriptive messages:

```python
from pydantic import ValidationError
from agents.core.contracts import SignalPayload

try:
    signal = SignalPayload(
        id="",  # Invalid: empty
        ts=1234567890.0,
        pair="BTC/USD",
        side="buy",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="test",
        confidence=0.8
    )
except ValidationError as e:
    print(e)
    # ValidationError: 1 validation error for SignalPayload
    # id
    #   String should have at least 1 character [type=string_too_short, ...]
```

### Best Practices

1. **Always validate payloads before publishing:**
   ```python
   # Create and validate
   signal = SignalPayload(**data)

   # Then publish
   r.xadd("signals:paper", {"payload": serialize_for_redis(signal.model_dump())})
   ```

2. **Handle validation errors gracefully:**
   ```python
   try:
       signal = validate_signal_payload(data)
   except ValidationError as e:
       logger.error(f"Invalid signal payload: {e}")
       # Don't publish invalid data
       return
   ```

3. **Use helper functions for validation:**
   ```python
   from agents.core.contracts import (
       validate_signal_payload,
       validate_metrics_latency_payload,
       validate_health_status_payload
   )

   # Cleaner code
   signal = validate_signal_payload(data)
   ```

---

## Summary

### Key Takeaways

✅ **Serialization:**
- Use `json_dumps()` for all JSON serialization
- Use `to_decimal_str()` for Decimal conversion
- Use `ts_to_iso()` for datetime conversion
- Use `serialize_for_redis()` for Redis payloads

✅ **Contracts:**
- Use Pydantic models for all Redis stream payloads
- Validate before publishing with `validate_*_payload()` helpers
- Handle ValidationError with clear error messages
- All contracts are documented with examples

✅ **Testing:**
- 75 total tests (34 serialization + 41 contracts)
- All tests use fakes/mocks only
- No network calls or external dependencies
- Fast execution (<1s total)

✅ **Redis Streams:**
- `signals:paper` and `signals:live` - SignalPayload
- `metrics:latency` - MetricsLatencyPayload
- `status:health` - HealthStatusPayload

---

## Files

- `agents/core/serialization.py` - Serialization utilities
- `agents/core/contracts.py` - Redis stream contracts
- `agents/core/tests/test_serialization.py` - Serialization tests (34 tests)
- `agents/core/tests/test_contracts.py` - Contract validation tests (41 tests)
- `agents/core/SERIALIZATION_AND_CONTRACTS.md` - This documentation

---

## Contact

For questions or issues:
1. Review this documentation
2. Check test files for examples
3. Run tests to verify behavior
4. Check docstrings in source code
