# Observability System Documentation

## Overview

This document describes the observability hooks implemented in `infra/metrics.py` for measuring system performance and tracking resilience patterns.

**Key Components:**
- Timing decorators and context managers
- Metric counters and gauges
- Resilience metrics (retries, throttles, circuit breaker trips)
- Centralized log keys in `agents/core/log_keys.py`
- No-op safe implementations

---

## Features

### 1. Timing Measurements
- Signal analysis duration
- Decision→publish latency
- Gateway roundtrip time
- Any custom operation

### 2. Resilience Metrics
- Retry attempt tracking
- Throttle event recording
- Circuit breaker state changes

### 3. Counter & Gauge Metrics
- Request counters
- Error counters
- Queue depth gauges
- Connection pool gauges

### 4. No-op Safety
- Never breaks business logic
- Graceful degradation if backends unavailable
- All logging wrapped in try-except

---

## Module: `infra.metrics`

### Timing Decorator

#### `@time_operation(operation, *, log_level=INFO, include_result=False, component=None)`

Decorator to measure and log function execution time.

**Parameters:**
- `operation` (str): Operation name (e.g., "signal_analysis", "gateway_roundtrip")
- `log_level` (int): Logging level (default: INFO)
- `include_result` (bool): Include function result in log (default: False)
- `component` (str): Component name for grouping metrics

**Examples:**

```python
from infra.metrics import time_operation

# Simple usage
@time_operation("signal_analysis")
def analyze_signal(data):
    # Analyze market data
    return {"signal": "buy", "confidence": 0.85}

# With component
@time_operation("gateway_roundtrip", component="kraken")
async def fetch_ticker(pair):
    return await kraken_api.get_ticker(pair)

# With result logging
@time_operation("decision_to_publish", include_result=True)
def make_decision(signal):
    return {"publish": True, "reason": "high_confidence"}
```

**Log Output:**

```json
{
  "operation": "signal_analysis",
  "signal_analysis_ms": 45.23,
  "duration_ms": 45.23,
  "start_time": 1697000000123.45,
  "end_time": 1697000000168.68,
  "component": "signal_processor"
}
```

---

### Timing Context Manager

#### `TimeOperation(operation, *, log_level=INFO, component=None, labels=None)`

Context manager to measure code block execution time.

**Parameters:**
- `operation` (str): Operation name
- `log_level` (int): Logging level
- `component` (str): Component name
- `labels` (dict): Additional labels for metrics

**Examples:**

```python
from infra.metrics import TimeOperation

# Simple usage
with TimeOperation("gateway_roundtrip"):
    response = await gateway.fetch_ticker("BTC/USD")

# With component and labels
with TimeOperation("decision_to_publish",
                   component="signal_processor",
                   labels={"pair": "BTC/USD"}):
    decision = make_trading_decision(signal)
    publish_to_redis(decision)
```

---

### Counters

#### `increment_counter(counter_name, *, delta=1, component=None, labels=None)`

Increment a counter metric.

**Parameters:**
- `counter_name` (str): Counter name (e.g., "retries", "requests")
- `delta` (int): Amount to increment (default: 1)
- `component` (str): Component name
- `labels` (dict): Additional labels

**Examples:**

```python
from infra.metrics import increment_counter

# Simple counter
increment_counter("api_requests")

# With component
increment_counter("retries", component="kraken_api")

# With labels
increment_counter("requests",
                 delta=5,
                 component="gateway",
                 labels={"endpoint": "/ticker", "method": "GET"})
```

---

### Gauges

#### `set_gauge(gauge_name, value, *, component=None, labels=None)`

Set a gauge metric value.

**Parameters:**
- `gauge_name` (str): Gauge name (e.g., "queue_depth", "active_connections")
- `value` (float): Gauge value
- `component` (str): Component name
- `labels` (dict): Additional labels

**Examples:**

```python
from infra.metrics import set_gauge

# Queue depth
set_gauge("queue_depth", 42, component="redis")

# Connection pool
set_gauge("active_connections", 10,
         component="postgres",
         labels={"pool": "main"})

# Memory usage
set_gauge("memory_usage_mb", 512.5, component="signal_processor")
```

---

### Resilience Metrics

#### `record_retry(operation, attempt, max_retries, *, backoff_ms=None, component=None, error=None)`

Record a retry attempt.

**Parameters:**
- `operation` (str): Operation being retried
- `attempt` (int): Current attempt number (1-indexed)
- `max_retries` (int): Maximum retry attempts
- `backoff_ms` (float): Backoff duration in milliseconds
- `component` (str): Component name
- `error` (str): Error message

**Examples:**

```python
from infra.metrics import record_retry

# Basic retry
record_retry("fetch_ticker", attempt=1, max_retries=3)

# With backoff and error
record_retry("place_order",
            attempt=2,
            max_retries=5,
            backoff_ms=1000,
            component="kraken",
            error="Rate limited: 429")
```

**Log Output:**

```json
{
  "operation": "fetch_ticker",
  "retry_attempt": 2,
  "max_retries": 5,
  "backoff_ms": 1000,
  "component": "kraken",
  "error": "Rate limited: 429"
}
```

---

#### `record_throttle(operation, *, reason=None, duration_ms=None, component=None)`

Record a throttle event (rate limit, backpressure).

**Parameters:**
- `operation` (str): Operation being throttled
- `reason` (str): Reason (e.g., "rate_limit", "backpressure")
- `duration_ms` (float): Throttle duration
- `component` (str): Component name

**Examples:**

```python
from infra.metrics import record_throttle

# Rate limit throttle
record_throttle("api_call", reason="rate_limit", duration_ms=1000)

# Backpressure throttle
record_throttle("publish", reason="backpressure", component="redis")

# Custom throttle
record_throttle("heavy_computation",
               reason="cpu_limit",
               duration_ms=5000,
               component="signal_processor")
```

---

#### `record_circuit_breaker_trip(circuit_name, state, *, failure_count=None, component=None, error=None)`

Record a circuit breaker state change.

**Parameters:**
- `circuit_name` (str): Circuit breaker name
- `state` (str): Circuit state ("open", "half_open", "closed")
- `failure_count` (int): Number of failures
- `component` (str): Component name
- `error` (str): Error message

**Examples:**

```python
from infra.metrics import record_circuit_breaker_trip

# Circuit opens
record_circuit_breaker_trip("postgres", "open", failure_count=5)

# Circuit goes half-open
record_circuit_breaker_trip("kraken_api", "half_open", component="gateway")

# Circuit closes (recovered)
record_circuit_breaker_trip("redis", "closed", component="cache")
```

---

## Metrics Backend Configuration

### Setting a Backend

```python
from infra.metrics import set_metrics_backend
import redis

# Configure Redis backend
r = redis.Redis(host='localhost', port=6379)
set_metrics_backend(r)

# Now all metrics will be published to Redis
```

### Redis Backend

When a Redis backend is configured, metrics are published to:
- `metrics:timing` - Timing metrics (stream)
- `metrics:counters` - Counter metrics (hash)
- `metrics:gauges` - Gauge metrics (hash)

### StatsD Backend

```python
from infra.metrics import set_metrics_backend
import statsd

# Configure StatsD backend
stats = statsd.StatsClient('localhost', 8125)
set_metrics_backend(stats)
```

### No Backend

If no backend is set, metrics are only logged to console (no-op safe).

---

## Centralized Log Keys

All log keys are defined in `agents/core/log_keys.py` for consistency.

### Timing Keys

```python
from agents.core.log_keys import (
    K_SIGNAL_ANALYSIS_MS,
    K_DECISION_TO_PUBLISH_MS,
    K_GATEWAY_ROUNDTRIP_MS,
    K_DURATION_MS,
    K_START_TIME,
    K_END_TIME,
)
```

### Retry Keys

```python
from agents.core.log_keys import (
    K_RETRY_ATTEMPT,
    K_MAX_RETRIES,
    K_RETRIES_EXHAUSTED,
    K_BACKOFF_MS,
)
```

### Throttle Keys

```python
from agents.core.log_keys import (
    K_THROTTLED,
    K_THROTTLE_REASON,
    K_THROTTLE_DURATION_MS,
    K_RATE_LIMIT_REMAINING,
    K_RATE_LIMIT_RESET,
)
```

### Circuit Breaker Keys

```python
from agents.core.log_keys import (
    K_CIRCUIT_BREAKER,
    K_CIRCUIT_STATE,
    K_CIRCUIT_BREAKER_TRIP,
    K_FAILURE_COUNT,
    K_FAILURE_THRESHOLD,
    K_CIRCUIT_OPEN_UNTIL,
)
```

### Counter & Gauge Keys

```python
from agents.core.log_keys import (
    K_COUNTER_NAME,
    K_COUNTER_VALUE,
    K_COUNTER_DELTA,
    K_GAUGE_NAME,
    K_GAUGE_VALUE,
)
```

---

## Complete Integration Examples

### Example 1: Signal Processing with Timing

```python
from infra.metrics import time_operation, TimeOperation, increment_counter
from agents.core.log_keys import K_COMPONENT, K_PAIR

@time_operation("signal_analysis", component="signal_processor")
async def analyze_market_data(pair: str):
    """Analyze market data and generate trading signal."""
    # Fetch data
    with TimeOperation("data_fetch", component="signal_processor"):
        data = await fetch_market_data(pair)

    # Analyze
    with TimeOperation("analysis", component="signal_processor"):
        signal = perform_technical_analysis(data)

    # Track successful analysis
    increment_counter("signals_generated",
                     component="signal_processor",
                     labels={"pair": pair})

    return signal
```

### Example 2: Retry with Backoff

```python
from infra.metrics import record_retry, record_throttle
import asyncio

async def fetch_with_retry(url, max_retries=3):
    """Fetch URL with exponential backoff."""
    for attempt in range(1, max_retries + 1):
        try:
            return await fetch(url)
        except RateLimitError as e:
            # Record throttle
            record_throttle("api_call",
                          reason="rate_limit",
                          duration_ms=e.retry_after * 1000)

            if attempt < max_retries:
                backoff_ms = (2 ** attempt) * 1000
                record_retry("api_call",
                           attempt=attempt,
                           max_retries=max_retries,
                           backoff_ms=backoff_ms,
                           error=str(e))
                await asyncio.sleep(backoff_ms / 1000)
            else:
                raise
```

### Example 3: Circuit Breaker Pattern

```python
from infra.metrics import record_circuit_breaker_trip, record_throttle
import time

class CircuitBreaker:
    def __init__(self, name, failure_threshold=5, timeout=60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.state = "closed"
        self.open_until = None

    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker."""
        # Check if circuit is open
        if self.state == "open":
            if time.time() < self.open_until:
                record_throttle(func.__name__,
                              reason="circuit_open",
                              component=self.name)
                raise CircuitOpenError("Circuit breaker is open")
            else:
                # Try half-open
                self.state = "half_open"
                record_circuit_breaker_trip(self.name, "half_open")

        try:
            result = await func(*args, **kwargs)

            # Success - reset failure count
            if self.state == "half_open":
                self.state = "closed"
                self.failure_count = 0
                record_circuit_breaker_trip(self.name, "closed")

            return result

        except Exception as e:
            self.failure_count += 1

            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                self.open_until = time.time() + self.timeout
                record_circuit_breaker_trip(self.name,
                                          "open",
                                          failure_count=self.failure_count,
                                          error=str(e))
            raise
```

### Example 4: Complete Signal→Decision→Publish Flow

```python
from infra.metrics import time_operation, TimeOperation, increment_counter
from infra.metrics import record_retry, record_throttle

class SignalProcessor:
    @time_operation("signal_analysis", component="signal_processor")
    async def analyze(self, pair: str):
        """Analyze market and generate signal."""
        with TimeOperation("market_scan", component="signal_processor"):
            data = await self.fetch_market_data(pair)

        with TimeOperation("technical_analysis", component="signal_processor"):
            signal = self.perform_analysis(data)

        increment_counter("signals_generated",
                         component="signal_processor",
                         labels={"pair": pair})

        return signal

    @time_operation("decision_to_publish", component="signal_processor")
    async def decide_and_publish(self, signal):
        """Make decision and publish to Redis."""
        # Decision logic
        with TimeOperation("decision", component="signal_processor"):
            decision = self.make_decision(signal)

        if not decision["publish"]:
            increment_counter("signals_filtered",
                            component="signal_processor")
            return

        # Publish with retry
        for attempt in range(1, 4):
            try:
                with TimeOperation("redis_publish", component="signal_processor"):
                    await self.redis.xadd("signals:paper", signal)

                increment_counter("signals_published",
                                component="signal_processor")
                return

            except redis.ConnectionError as e:
                if attempt < 3:
                    backoff_ms = (2 ** attempt) * 100
                    record_retry("redis_publish",
                               attempt=attempt,
                               max_retries=3,
                               backoff_ms=backoff_ms,
                               error=str(e))
                    await asyncio.sleep(backoff_ms / 1000)
                else:
                    increment_counter("publish_failures",
                                    component="signal_processor")
                    raise
```

---

## Log Output Examples

### Timing Log

```json
{
  "timestamp": "2025-10-11T12:34:56.789Z",
  "level": "INFO",
  "message": "Operation 'signal_analysis' completed in 45.23ms",
  "operation": "signal_analysis",
  "signal_analysis_ms": 45.23,
  "duration_ms": 45.23,
  "start_time": 1697000000123.45,
  "end_time": 1697000000168.68,
  "component": "signal_processor"
}
```

### Retry Log

```json
{
  "timestamp": "2025-10-11T12:34:56.789Z",
  "level": "INFO",
  "message": "Retry attempt 2/3 for 'fetch_ticker'",
  "operation": "fetch_ticker",
  "retry_attempt": 2,
  "max_retries": 3,
  "backoff_ms": 2000,
  "component": "kraken_api",
  "error": "Connection timeout"
}
```

### Throttle Log

```json
{
  "timestamp": "2025-10-11T12:34:56.789Z",
  "level": "WARNING",
  "message": "Operation 'api_call' throttled: rate_limit",
  "operation": "api_call",
  "throttled": true,
  "throttle_reason": "rate_limit",
  "throttle_duration_ms": 1000,
  "component": "kraken_api"
}
```

### Circuit Breaker Log

```json
{
  "timestamp": "2025-10-11T12:34:56.789Z",
  "level": "ERROR",
  "message": "Circuit breaker 'postgres' changed to state: open",
  "circuit_breaker": "postgres",
  "circuit_state": "open",
  "circuit_breaker_trip": true,
  "failure_count": 5,
  "component": "database",
  "error": "Connection timeout"
}
```

---

## Testing

### Running Tests

```bash
# Run all observability tests
pytest infra/tests/test_metrics.py -v

# Run with coverage
pytest infra/tests/test_metrics.py --cov=infra.metrics --cov-report=term-missing

# Run specific test class
pytest infra/tests/test_metrics.py::TestTimeOperationDecorator -v
```

### Test Coverage

- **39 tests** covering:
  - Timing decorators (sync and async)
  - Context managers
  - Counters and gauges
  - Retry/throttle/circuit breaker recording
  - Metrics backend integration
  - No-op safety
  - Complete workflows

---

## Best Practices

### 1. Use Consistent Operation Names

```python
# Good - standardized names
@time_operation("signal_analysis")
@time_operation("decision_to_publish")
@time_operation("gateway_roundtrip")

# Bad - inconsistent names
@time_operation("analyze_stuff")
@time_operation("DoDecision")
@time_operation("call_api")
```

### 2. Include Component Names

```python
# Good - component specified
increment_counter("retries", component="kraken_api")
record_throttle("api_call", component="gateway")

# Bad - no component
increment_counter("retries")  # Which component?
```

### 3. Use Labels for Cardinality

```python
# Good - labels for high-cardinality data
increment_counter("requests",
                 component="api",
                 labels={"endpoint": "/ticker", "pair": "BTC/USD"})

# Bad - high-cardinality in metric name
increment_counter(f"requests_{pair}_{endpoint}")
```

### 4. Record All Retry Attempts

```python
# Good - record every retry
for attempt in range(1, max_retries + 1):
    try:
        return await fetch()
    except Exception as e:
        if attempt < max_retries:
            record_retry("fetch", attempt, max_retries)
        else:
            raise

# Bad - only record failures
try:
    return await fetch()
except Exception:
    record_retry("fetch", 1, 3)  # Missing context
```

### 5. Use Context Managers for Code Blocks

```python
# Good - context manager for blocks
with TimeOperation("complex_operation"):
    step1()
    step2()
    step3()

# Bad - manual timing
start = time.time()
step1()
step2()
step3()
logger.info(f"Took {time.time() - start}s")
```

---

## Summary

### Key Takeaways

✅ **Timing:**
- Use `@time_operation` for functions
- Use `TimeOperation` context manager for code blocks
- Standardized keys: signal_analysis_ms, decision_to_publish_ms, gateway_roundtrip_ms

✅ **Counters:**
- Increment for events (retries, requests, errors)
- Use labels for high-cardinality data
- Always include component name

✅ **Resilience:**
- Record all retries with backoff info
- Record throttle events with reason
- Record circuit breaker state changes

✅ **No-op Safety:**
- All operations are no-op safe
- Never breaks business logic
- Graceful degradation if backends fail

✅ **Structured Logs:**
- Consistent field names via log_keys.py
- All logs include operation and component
- Easy to parse and aggregate

---

## Files

- `infra/metrics.py` - Core metrics module
- `agents/core/log_keys.py` - Centralized log key constants
- `infra/tests/test_metrics.py` - Comprehensive test suite (39 tests)
- `infra/OBSERVABILITY.md` - This documentation

---

## Contact

For questions or issues:
1. Review this documentation
2. Check test files for examples
3. Review source code docstrings
4. Test with fakes/mocks first
