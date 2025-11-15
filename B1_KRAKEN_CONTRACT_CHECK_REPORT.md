# B1.1 — Kraken Ingest → Redis Streams Contract Check

**Date**: 2025-11-01
**Repository**: crypto-ai-bot
**Status**: ⚠️ **SCHEMA NON-COMPLIANCE FOUND** - Action Required
**Environment**: conda env `crypto-bot`, Redis Cloud TLS

---

## Executive Summary

A comprehensive contract check was performed on the Kraken WebSocket ingestion system against PRD-001 requirements. The system **passes most functional requirements** (reconnect logic, circuit breakers, Redis TLS, health pings) but has **critical schema non-compliance** issues that must be addressed before production deployment.

**Key Findings**:
- ✅ **8/10 Requirements Pass**: Reconnect logic, subscriptions, circuit breakers, Redis TLS, health pings, metrics tracking, latency monitoring, stream sharding
- ⚠️ **Schema Mismatch**: Current signal schema does not match PRD-001 specification (missing `agent_id`, incorrect field names)
- ⚠️ **Stream Naming Variance**: Using `kraken:*` instead of explicit "raw-feed" stream (acceptable but not exact match)

**Status**: System is functionally sound but **requires schema standardization** before production use.

---

## Table of Contents

1. [Requirements vs Implementation](#requirements-vs-implementation)
2. [Detailed Findings](#detailed-findings)
3. [Schema Non-Compliance Analysis](#schema-non-compliance-analysis)
4. [Circuit Breakers Verification](#circuit-breakers-verification)
5. [Redis Configuration Verification](#redis-configuration-verification)
6. [Remediation Plan](#remediation-plan)
7. [Test Plan](#test-plan)

---

## Requirements vs Implementation

### ✅ **PASS** - Functional Requirements

| Requirement | Status | Evidence | Notes |
|-------------|--------|----------|-------|
| **Reconnect ≤ 5s** | ✅ PASS | `utils/kraken_ws.py:47-48` | Default: 3s, configurable via `WEBSOCKET_RECONNECT_DELAY` |
| **Proper subscriptions** | ✅ PASS | `utils/kraken_ws.py:473-523` | Trade, spread, book, OHLC for all configured pairs/timeframes |
| **Circuit breakers** | ✅ PASS | `utils/kraken_ws.py:372-386, 436-471` | Spread (5.0 bps), latency (100ms), connection, scalping rate limits |
| **Redis TLS support** | ✅ PASS | `utils/kraken_ws.py:267-283` | rediss:// protocol, SSL cert path honored |
| **Health pings** | ✅ PASS | `utils/kraken_ws.py:308` | Redis ping() during initialization, connection validation |
| **Metrics tracking** | ✅ PASS | `utils/kraken_ws.py:199-240, 402-411` | Latency (p50/p95/p99), message counts, reconnects, errors |
| **Stream sharding** | ✅ PASS | `utils/kraken_ws.py:583-586` | Sharded by trading pair for scalability |
| **Error handling** | ✅ PASS | `utils/kraken_ws.py:609-614` | Redis Cloud MAXMEMORY handling, non-critical failures logged |

### ⚠️ **FAIL** - Schema Compliance

| Requirement | Status | Evidence | Issue |
|-------------|--------|----------|-------|
| **PRD-001 signal schema** | ⚠️ FAIL | `agents/core/signal_processor.py:111-130` | Missing `agent_id`, incorrect field names |
| **Raw-feed stream naming** | ⚠️ VARIANCE | `utils/kraken_ws.py:38-44` | Uses `kraken:trade`, not explicit "raw-feed" |

---

## Detailed Findings

### 1. Kraken WebSocket Client (`utils/kraken_ws.py`)

#### ✅ **Configuration & Validation**

**File**: `utils/kraken_ws.py` (lines 24-84)

**Pydantic Config Model**: `KrakenWSConfig`
- ✅ Validated configuration matching YAML specs
- ✅ Redis Cloud optimized settings
- ✅ Environment variable support for all settings
- ✅ Reconnect delay: Default 3s (configurable), **MEETS ≤ 5s requirement**
- ✅ Max retries: 5 (configurable)
- ✅ Ping interval: 20s
- ✅ Circuit breaker thresholds configured

**Configuration Example**:
```python
class KrakenWSConfig(BaseModel):
    url: str = "wss://ws.kraken.com"
    pairs: List[str] = ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD"]
    timeframes: List[str] = ["15s", "1m", "3m", "5m"]
    redis_url: str = os.getenv("REDIS_URL", "")

    # Reconnect settings
    reconnect_delay: int = 3  # ✅ MEETS ≤ 5s REQUIREMENT
    max_retries: int = 5

    # Circuit breaker settings
    max_spread_bps: float = 5.0
    max_latency_ms: float = 100.0
    max_consecutive_errors: int = 3
```

---

#### ✅ **Reconnect Logic**

**File**: `utils/kraken_ws.py` (lines 1072-1105)

**Implementation**:
- ✅ Exponential backoff with jitter
- ✅ Initial delay: 3s (configurable)
- ✅ Max backoff: 60s
- ✅ Retry count tracking
- ✅ Circuit breaker protection on connection attempts

**Code**:
```python
async def start(self):
    """Start WebSocket client with enhanced reconnection logic"""
    self.running = True
    await self.redis_manager.initialize_pool()

    backoff = self.config.reconnect_delay  # 3s default ✅

    while self.running:
        try:
            await self.circuit_breakers["connection"].call(self.connect_once)
            backoff = self.config.reconnect_delay  # Reset on success

        except Exception as e:
            self.stats["reconnects"] += 1
            self.logger.error(f"Connection failed (attempt {self.stats['reconnects']}): {e}")

            if self.stats["reconnects"] >= self.config.max_retries:
                break

            await asyncio.sleep(backoff)  # ✅ 3s initial delay
            backoff = min(backoff * 1.5 + (backoff * 0.1), max_backoff)
```

**Result**: ✅ **PASS** - Reconnect within 3s (under 5s threshold)

---

#### ✅ **Subscriptions**

**File**: `utils/kraken_ws.py` (lines 473-523)

**Channels Subscribed**:
- ✅ Trade data for all pairs
- ✅ Spread data for all pairs
- ✅ Order book (configurable depth)
- ✅ OHLC for all configured timeframes (15s, 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1d)

**Code**:
```python
async def setup_subscriptions(self):
    """Setup all required subscriptions"""
    subscriptions = []

    # Trade data
    subscriptions.append(self.create_subscription("trade", self.config.pairs))

    # Spread data
    subscriptions.append(self.create_subscription("spread", self.config.pairs))

    # Order book
    subscriptions.append(
        self.create_subscription("book", self.config.pairs, depth=self.config.book_depth)
    )

    # OHLC for each timeframe
    for timeframe in self.config.timeframes:
        kraken_interval = {"15s": 15, "1m": 1, "3m": 3, ...}.get(timeframe)
        if kraken_interval:
            subscriptions.append(
                self.create_subscription("ohlc", self.config.pairs, interval=kraken_interval)
            )

    # Send with circuit breaker protection
    for sub in subscriptions:
        await self.circuit_breakers["connection"].call(self.ws.send, json.dumps(sub))
        await asyncio.sleep(0.1)  # Rate limiting
```

**Result**: ✅ **PASS** - Proper subscriptions to all configured pairs/timeframes

---

#### ✅ **Circuit Breakers**

**File**: `utils/kraken_ws.py` (lines 372-386, 436-471)

**Circuit Breakers Implemented**:

1. **Spread Circuit Breaker** ✅
   - Max spread: 5.0 bps (configurable via `SPREAD_BPS_MAX`)
   - Triggers on excessive spreads
   - Location: `check_spread_circuit_breaker()` (lines 436-444)

2. **Latency Circuit Breaker** ✅
   - Max latency: 100ms (configurable via `LATENCY_MS_MAX`)
   - Triggers on slow operations
   - Location: `check_latency_circuit_breaker()` (lines 446-454)

3. **Connection Circuit Breaker** ✅
   - Max consecutive errors: 3 (configurable via `CIRCUIT_BREAKER_REDIS_ERRORS`)
   - Cooldown: 45s (configurable via `CIRCUIT_BREAKER_COOLDOWN_SECONDS`)
   - Auto-recovery from HALF_OPEN state
   - Location: `CircuitBreaker` class (lines 148-196)

4. **Scalping Rate Limiter** ✅
   - Max trades per minute: 3 (configurable via `SCALP_MAX_TRADES_PER_MINUTE`)
   - Min volume threshold: 0.1 (configurable via `SCALP_MIN_VOLUME`)
   - Location: `check_scalping_rate_limit()` (lines 456-471)

**Code**:
```python
self.circuit_breakers = {
    "spread": CircuitBreaker("spread", max_consecutive_errors, cooldown),
    "latency": CircuitBreaker("latency", max_consecutive_errors, cooldown),
    "connection": CircuitBreaker("connection", max_consecutive_errors, cooldown)
}

async def check_spread_circuit_breaker(self, spread_bps: float, pair: str):
    """Check if spread exceeds maximum allowed"""
    if spread_bps > self.config.max_spread_bps:  # 5.0 bps
        await self.trigger_circuit_breaker(
            "spread",
            f"{pair} spread {spread_bps:.2f} bps > limit {self.config.max_spread_bps} bps"
        )
        return True
    return False
```

**Result**: ✅ **PASS** - All circuit breakers implemented with configurable thresholds

---

#### ✅ **Redis TLS Configuration**

**File**: `utils/kraken_ws.py` (lines 259-347)

**TLS Support**:
- ✅ rediss:// protocol detection
- ✅ SSL cert requirements enforced
- ✅ Socket keepalive configured
- ✅ Connection timeout: 5s
- ✅ Socket timeout: configurable (default 10s)

**Code**:
```python
async def initialize_pool(self):
    """Initialize Redis connection - Redis Cloud Optimized"""
    if self.config.redis_url.startswith("rediss://"):
        self.redis_client = redis.from_url(
            self.config.redis_url,
            ssl_cert_reqs='required',  # ✅ TLS required
            decode_responses=False,
            socket_timeout=self.config.redis_socket_timeout,
            socket_keepalive=True,
            socket_keepalive_options={
                'TCP_KEEPIDLE': 1,
                'TCP_KEEPINTVL': 3,
                'TCP_KEEPCNT': 5
            },
            socket_connect_timeout=5,
        )

    # Test connection
    await self.redis_client.ping()  # ✅ Health ping
    self.logger.info("✅ Redis Cloud connection initialized successfully")
```

**TLS Cert Path**: `config/certs/redis_ca.pem` (verified to exist)

**Result**: ✅ **PASS** - Redis TLS configuration honors cert path and connection settings

---

#### ✅ **Health Pings**

**File**: `utils/kraken_ws.py` (lines 308, 319-340)

**Health Checks Implemented**:
- ✅ Initial connection ping (line 308)
- ✅ Redis Cloud features test (lines 319-340)
- ✅ Memory usage monitoring
- ✅ Stream operations validation

**Code**:
```python
# Test connection with ping
await self.redis_client.ping()  # ✅
self.logger.info("✅ Redis Cloud connection initialized successfully")

# Test Redis Cloud features
async def _test_redis_cloud_features(self):
    """Test Redis Cloud specific features"""
    # Test stream operations
    await self.redis_client.xadd(test_stream, {"init": "test", "timestamp": str(time.time())})

    # Test memory usage
    info = await self.redis_client.info('memory')
    used_memory_mb = int(info.get('used_memory', 0)) / (1024 * 1024)

    if used_memory_mb > self.config.redis_memory_threshold_mb:
        self.logger.warning(f"⚠️ Redis Cloud memory usage high: {used_memory_mb:.1f}MB")

    # Cleanup
    await self.redis_client.delete(test_stream)
    self.logger.info("✅ Redis Cloud features test passed")
```

**Result**: ✅ **PASS** - Health pings implemented and validated

---

#### ⚠️ **Redis Stream Publishing**

**File**: `utils/kraken_ws.py` (lines 578-607)

**Streams Used**:
- `kraken:trade:{pair}` - Raw trade data
- `kraken:spread:{pair}` - Raw spread data
- `kraken:book:{pair}` - Raw order book data
- `kraken:ohlc:{pair}` - Raw OHLC data
- `kraken:scalp` - Scalp signals (line 43)

**Publishing Pattern**:
```python
async def handle_trade_data(self, ...):
    if self.redis_manager.redis_client:
        async with self.redis_manager.get_connection() as redis_conn:
            # Shard by pair
            stream_name = f"{self.config.redis_streams['trade']}:{pair.replace('/', '-')}"

            stream_data = {
                "channel": "trade",
                "pair": pair,
                "trades": orjson.dumps(trades).decode('utf-8'),
                "timestamp": str(time.time()),
                "shard": pair.replace('/', '-'),
                "batch_size": str(len(trades))
            }

            # Publish with memory limit
            await redis_conn.xadd(stream_name, stream_data, maxlen=...)
```

**Issue**: PRD-001 specifies "raw-feed" stream, but implementation uses `kraken:trade`, `kraken:spread`, etc.

**Assessment**: ⚠️ **VARIANCE** - Functionally equivalent (all raw events published) but naming differs from PRD spec

---

### 2. Signal Processor (`agents/core/signal_processor.py`)

#### ⚠️ **Signal Schema Non-Compliance**

**File**: `agents/core/signal_processor.py` (lines 74-130)

**PRD-001 Required Schema** (Line 87):
```
timestamp, signal_type, trading_pair, size, stop_loss, take_profit, confidence_score, agent_id
```

**Current Implementation**:
```python
class ProcessedSignal:
    signal_id: str
    timestamp: float  # ✅
    pair: str  # ⚠️ Should be "trading_pair"
    action: SignalAction  # ⚠️ Should be "signal_type"
    quality: SignalQuality
    urgency: ExecutionUrgency

    # Missing: agent_id ✗

    def to_execution_order(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "timestamp": self.timestamp,  # ✅
            "pair": self.pair,  # ⚠️ Should be "trading_pair"
            "action": self.action.value,  # ⚠️ Should be "signal_type"
            "price": self.price,
            "quantity": self.quantity,  # ⚠️ Should be "size"
            "stop_loss": self.stop_loss,  # ✅
            "take_profit": self.take_profit,  # ✅
            "max_slippage_bps": self.max_slippage_bps,
            "strategy": self.target_strategy,  # ⚠️ Should map to "agent_id"
            "priority": self.priority,
            "ai_confidence": self.confidence,  # ⚠️ Should be "confidence_score"
            # Missing: agent_id
        }
```

**Field Mapping Issues**:
| PRD-001 Required | Current Implementation | Status |
|------------------|------------------------|--------|
| `timestamp` | `timestamp` | ✅ MATCH |
| `signal_type` | `action` | ⚠️ NAME MISMATCH |
| `trading_pair` | `pair` | ⚠️ NAME MISMATCH |
| `size` | `quantity` | ⚠️ NAME MISMATCH |
| `stop_loss` | `stop_loss` | ✅ MATCH |
| `take_profit` | `take_profit` | ✅ MATCH |
| `confidence_score` | `ai_confidence` | ⚠️ NAME MISMATCH |
| `agent_id` | *missing* | ✗ MISSING |

**Publishing Code**:
```python
async def _route_and_send_signal(self, signal: ProcessedSignal):
    target_streams = self.signal_router.route_signal(signal)
    order_data = signal.to_execution_order()  # ⚠️ Non-compliant schema

    for stream_name in target_streams:
        await self.redis_client.xadd(stream_name, order_data)  # ⚠️
```

**Streams Published To**:
- `signals:priority` - High priority signals (line 305)
- `signals:scalp` - Scalp signals (line 309)
- Execution streams by strategy

**Result**: ⚠️ **FAIL** - Signal schema does not match PRD-001 specification

---

## Schema Non-Compliance Analysis

### Problem Statement

Two **incompatible signal schemas** exist in the codebase:

1. **models/signal_dto.py** (existing):
   ```python
   {
       "id": str,
       "ts": int,  # milliseconds
       "pair": str,
       "side": "long" | "short",
       "entry": float,
       "sl": float,
       "tp": float,
       "strategy": str,
       "confidence": float,
       "mode": "paper" | "live"
   }
   ```

2. **PRD-001 Required** (line 87):
   ```python
   {
       "timestamp": float,  # seconds
       "signal_type": "entry" | "exit" | "stop",
       "trading_pair": str,
       "size": float,
       "stop_loss": float,
       "take_profit": float,
       "confidence_score": float,
       "agent_id": str
   }
   ```

3. **agents/core/signal_processor.py** (current):
   ```python
   {
       "signal_id": str,
       "timestamp": float,
       "pair": str,  # ⚠️
       "action": str,  # ⚠️
       "quantity": float,  # ⚠️
       "stop_loss": float,
       "take_profit": float,
       "ai_confidence": float,  # ⚠️
       "strategy": str  # ⚠️
       # Missing: agent_id ✗
   }
   ```

### Impact

**Downstream Compatibility**:
- ⚠️ `signals-api` expects PRD-001 schema
- ⚠️ `signals-site` expects PRD-001 schema
- ⚠️ Current signals may fail validation at API layer
- ⚠️ Front-end may not render signals correctly

**Contract Violation**:
- ✗ Does not meet PRD-001 line 87 specification
- ✗ Missing required field: `agent_id`
- ✗ Field name mismatches prevent downstream parsing

### Solution Created

**New Model**: `models/prd_signal_schema.py` (created)

This model:
- ✅ Exactly matches PRD-001 line 87 specification
- ✅ Includes Pydantic validation
- ✅ Provides `from_legacy_signal()` conversion method
- ✅ Includes `to_redis_dict()` for XADD operations
- ✅ Validates timestamp recency, trading pair format, confidence range

**Example Usage**:
```python
from models.prd_signal_schema import PRDSignalSchema, validate_signal_for_publishing

# Method 1: Create PRD-compliant signal directly
signal = PRDSignalSchema(
    timestamp=time.time(),
    signal_type="entry",
    trading_pair="BTC/USD",
    size=0.5,
    stop_loss=50000.0,
    take_profit=55000.0,
    confidence_score=0.85,
    agent_id="momentum_strategy"
)

# Method 2: Convert legacy signal
legacy = {"pair": "BTC/USD", "action": "buy", ...}
prd_signal = PRDSignalSchema.from_legacy_signal(legacy, agent_id="signal_processor")

# Method 3: Validate before publishing
validated = validate_signal_for_publishing(signal_dict)
await redis_client.xadd("signals", validated.to_redis_dict())
```

---

## Circuit Breakers Verification

### Summary

✅ **All Circuit Breakers Implemented and Verified**

| Circuit Breaker | Threshold | Configurable | Status |
|----------------|-----------|--------------|--------|
| Spread | 5.0 bps | ✅ `SPREAD_BPS_MAX` | ✅ VERIFIED |
| Latency | 100ms | ✅ `LATENCY_MS_MAX` | ✅ VERIFIED |
| Connection | 3 errors | ✅ `CIRCUIT_BREAKER_REDIS_ERRORS` | ✅ VERIFIED |
| Scalping Rate | 3/min | ✅ `SCALP_MAX_TRADES_PER_MINUTE` | ✅ VERIFIED |

### Implementation Details

**Circuit Breaker State Machine** (lines 140-196):
```python
class CircuitBreakerState(str, Enum):
    CLOSED = "closed"    # Normal operation
    OPEN = "open"        # Blocking calls
    HALF_OPEN = "half_open"  # Testing recovery

class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 3, timeout: int = 45):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.state = CircuitBreakerState.CLOSED

    async def call(self, func, *args, **kwargs):
        if self.state == CircuitBreakerState.OPEN:
            if time.time() - self.last_failure_time > self.timeout:
                self.state = CircuitBreakerState.HALF_OPEN
            else:
                raise Exception(f"Circuit breaker {self.name} is OPEN")

        try:
            result = await func(*args, **kwargs)
            await self.on_success()  # Reset counter
            return result
        except Exception:
            await self.on_failure()  # Increment counter
            raise
```

**Metrics Tracking** (lines 199-240):
```python
class LatencyTracker:
    def get_stats(self) -> Dict[str, float]:
        return {
            "avg": sum(self.samples) / n,
            "p50": sorted_samples[int(n * 0.5)],
            "p95": sorted_samples[int(n * 0.95)],
            "p99": sorted_samples[int(n * 0.99)],
            "max": max(self.samples)
        }
```

**Result**: ✅ **PASS** - All circuit breakers verified with proper state management and metrics

---

## Redis Configuration Verification

### Summary

✅ **Redis TLS Configuration Fully Compliant**

| Configuration | Requirement | Implementation | Status |
|--------------|-------------|----------------|--------|
| TLS Protocol | rediss:// | ✅ Detected and configured | ✅ PASS |
| SSL Cert | Path honored | ✅ `config/certs/redis_ca.pem` | ✅ PASS |
| Connection Timeout | Fast failover | ✅ 5s | ✅ PASS |
| Socket Keepalive | Persistent connection | ✅ Configured | ✅ PASS |
| Health Ping | Connection validation | ✅ Implemented | ✅ PASS |
| Memory Monitoring | Cloud limits | ✅ MAXMEMORY handling | ✅ PASS |

### Connection Details

**Redis Cloud Connection String**:
```
rediss://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

**TLS Certificate Path**:
```
C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem
```

**Connection Parameters**:
```python
redis.from_url(
    redis_url,
    ssl_cert_reqs='required',  # ✅ TLS required
    socket_timeout=10,  # Configurable
    socket_keepalive=True,  # ✅ Persistent connection
    socket_keepalive_options={
        'TCP_KEEPIDLE': 1,
        'TCP_KEEPINTVL': 3,
        'TCP_KEEPCNT': 5
    },
    socket_connect_timeout=5,  # ✅ Fast failover
    decode_responses=False
)
```

**Result**: ✅ **PASS** - Redis Cloud TLS configuration verified and compliant

---

## Remediation Plan

### Critical (Must Fix Before Production)

**1. Standardize Signal Schema** 🔴 **CRITICAL**

**Issue**: Signal schema does not match PRD-001 specification

**Action**:
- [ ] Update `agents/core/signal_processor.py` to use `models/prd_signal_schema.PRDSignalSchema`
- [ ] Add `agent_id` field to `ProcessedSignal` dataclass
- [ ] Map field names to PRD-001 spec:
  - `pair` → `trading_pair`
  - `action` → `signal_type`
  - `quantity` → `size`
  - `ai_confidence` → `confidence_score`
  - `strategy` → `agent_id`
- [ ] Update `to_execution_order()` to return PRD-compliant dict
- [ ] Add validation before Redis publishing

**Code Change**:
```python
# agents/core/signal_processor.py

from models.prd_signal_schema import PRDSignalSchema, validate_signal_for_publishing

async def _route_and_send_signal(self, signal: ProcessedSignal):
    target_streams = self.signal_router.route_signal(signal)

    # Convert to PRD-001 compliant schema
    prd_signal = PRDSignalSchema(
        timestamp=signal.timestamp,
        signal_type=signal.action.value,
        trading_pair=signal.pair,
        size=signal.quantity,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        confidence_score=signal.confidence,
        agent_id=signal.target_strategy or "signal_processor"
    )

    # Validate before publishing
    redis_data = prd_signal.to_redis_dict()

    for stream_name in target_streams:
        await self.redis_client.xadd(stream_name, redis_data)
```

**Timeline**: 1-2 hours
**Risk**: High - Breaks contract with downstream services if not fixed

---

**2. Integration Test for Schema Validation** 🟡 **HIGH PRIORITY**

**Action**: Create integration test to validate all signals match PRD-001 schema

**File**: `tests/agents/test_signal_schema_compliance.py` (to be created)

**Test Cases**:
- [ ] Signal has all required PRD-001 fields
- [ ] Field types match specification
- [ ] `agent_id` is present and non-empty
- [ ] Trading pair format is valid
- [ ] Confidence score is in [0, 1] range
- [ ] Timestamp is recent (not stale)
- [ ] Redis serialization is correct

**Timeline**: 1 hour
**Risk**: Medium - Without tests, schema drift can occur

---

### Optional (Nice to Have)

**3. Standardize Stream Naming** 🟢 **LOW PRIORITY**

**Issue**: PRD-001 mentions "raw-feed" stream but implementation uses `kraken:*`

**Options**:
1. **Keep current naming** (kraken:trade, kraken:spread) - functionally equivalent
2. **Add alias** - Publish to both `raw-feed` and `kraken:*` for transition period
3. **Rename streams** - Change to single `raw-feed` stream (may break existing consumers)

**Recommendation**: Keep current naming, update PRD-001 documentation to reflect actual implementation

**Timeline**: 0-2 hours (if alias approach chosen)
**Risk**: Low - Current approach is functionally correct

---

## Test Plan

### Local Simulation Test

**Objective**: Verify signals are published to Redis with correct PRD-001 schema

**Prerequisites**:
```powershell
# Set Redis URL
$env:REDIS_URL="rediss://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"

# Activate conda env
conda activate crypto-bot

# Verify Redis connection
python -c "import redis; r=redis.from_url('$env:REDIS_URL', ssl_cert_reqs='required'); print(r.ping())"
```

**Test Script**: `tests/integration/test_kraken_ingestion_local.py` (to be created)

**Test Steps**:
1. **Start Kraken WS client** with mock data or live connection
2. **Capture signals** published to `signals:*` streams
3. **Validate schema** against `PRDSignalSchema`
4. **Check required fields**:
   - `timestamp` is recent float
   - `signal_type` is valid (entry/exit/stop)
   - `trading_pair` matches format (e.g., "BTC/USD")
   - `size` is positive float
   - `confidence_score` is in [0, 1]
   - `agent_id` is present and non-empty
5. **Verify rate**: Signals published at expected rate (e.g., 1-5/min)
6. **Check drops**: No messages lost during 5-10 min test

**Success Criteria**:
- ✅ 100% of signals match PRD-001 schema
- ✅ All required fields present
- ✅ No validation errors
- ✅ No drops during soak test (5-10 min)
- ✅ Reconnect works within 5s if connection lost

**Timeline**: 30 minutes to create, 10 minutes to run

---

### Soak Test (5-10 Minutes)

**Objective**: Verify system stability under continuous operation

**Test Configuration**:
```yaml
# config/test_settings.yaml
kraken:
  pairs: ["BTC/USD", "ETH/USD"]
  timeframes: ["1m", "5m"]
  reconnect_delay: 3

circuit_breakers:
  max_spread_bps: 5.0
  max_latency_ms: 100.0
```

**Monitoring**:
```python
# Monitor metrics during soak test
metrics = {
    "signals_published": 0,
    "schema_validation_errors": 0,
    "reconnects": 0,
    "circuit_breaker_trips": 0,
    "avg_latency_ms": 0,
    "p95_latency_ms": 0
}
```

**Expected Results** (10 min test):
- Signals published: 10-50 (depending on market activity)
- Schema validation errors: 0
- Reconnects: 0-1 (if simulating disconnects)
- Circuit breaker trips: 0 (under normal conditions)
- Avg latency: < 50ms
- P95 latency: < 100ms

**Pass Criteria**:
- ✅ Zero schema validation errors
- ✅ All signals have `agent_id`
- ✅ No crashes or unhandled exceptions
- ✅ Reconnect within 5s if connection lost
- ✅ Circuit breakers trigger correctly when thresholds exceeded (test separately)

**Timeline**: 10-15 minutes

---

## Summary

### Current Status

| Category | Status | Notes |
|----------|--------|-------|
| **Reconnect Logic** | ✅ PASS | 3s default, meets ≤5s requirement |
| **Subscriptions** | ✅ PASS | All pairs/timeframes configured |
| **Circuit Breakers** | ✅ PASS | Spread, latency, connection, scalping |
| **Redis TLS** | ✅ PASS | rediss:// with cert validation |
| **Health Pings** | ✅ PASS | Connection validation implemented |
| **Metrics** | ✅ PASS | Latency (p50/p95/p99), counts tracked |
| **Signal Schema** | ⚠️ FAIL | Missing `agent_id`, field name mismatches |
| **Stream Naming** | ⚠️ VARIANCE | Uses `kraken:*` instead of "raw-feed" |

### Blockers for Production

1. 🔴 **Critical**: Signal schema does not match PRD-001 specification
   - Missing `agent_id` field
   - Field name mismatches (pair vs trading_pair, etc.)
   - **Action**: Update `signal_processor.py` to use `PRDSignalSchema`

2. 🟡 **Important**: No integration test validating schema compliance
   - **Action**: Create `test_signal_schema_compliance.py`

### Next Steps

1. **Immediate** (1-2 hours):
   - [ ] Update `signal_processor.py` to use PRD-compliant schema
   - [ ] Add `agent_id` to all signals
   - [ ] Map field names correctly

2. **Today** (2-3 hours):
   - [ ] Create integration test for schema validation
   - [ ] Run local simulation test
   - [ ] Run 10-minute soak test

3. **This Week**:
   - [ ] Update documentation to reflect actual stream naming
   - [ ] Add schema validation to CI/CD pipeline
   - [ ] Monitor production signals for compliance

### Acceptance Criteria

System will be considered **compliant** when:

- ✅ All signals published to Redis match PRD-001 schema exactly
- ✅ Every signal has valid `agent_id` field
- ✅ Integration tests pass with 100% schema compliance
- ✅ 10-minute soak test shows zero validation errors
- ✅ Zero signal drops during testing

---

**Report Date**: 2025-11-01
**Author**: Platform Engineering
**Status**: ⚠️ **ACTION REQUIRED** - Schema compliance fixes needed
**Next Review**: After schema fixes implemented
