# Agents Architecture Overview

**Quick Reference: Understand the entire system dataflow in 2 minutes**

## 🎯 System at a Glance

This is a multi-agent crypto trading system that ingests market data, generates trading signals, applies risk management, and executes orders — all orchestrated through Redis streams with Redis Cloud (TLS).

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CRYPTO AI BOT DATAFLOW                        │
└──────────────────────────────────────────────────────────────────────┘

  Market Data           Infrastructure         Core Agents            Risk System
┌─────────────┐       ┌─────────────────┐   ┌──────────────┐     ┌──────────────┐
│             │       │                 │   │              │     │              │
│  Kraken WS  │──────▶│  Data Pipeline  │──▶│   Strategy   │────▶│ Risk Router  │
│             │       │                 │   │   Scanner    │     │              │
│ • Trades    │       │ Redis Streams:  │   │              │     │ • Compliance │
│ • Book      │       │ md:trades       │   │ Generates    │     │ • Drawdown   │
│ • Spreads   │       │ md:book         │   │ Signals      │     │ • Balancer   │
│ • Candles   │       │ md:spread       │   │              │     │              │
│             │       │ md:candles      │   └──────────────┘     └──────────────┘
└─────────────┘       └─────────────────┘           │                    │
                              │                     │                    │
                              │                     ▼                    ▼
                              │            ┌──────────────┐     ┌──────────────┐
                              │            │              │     │              │
                              │            │   signals:   │────▶│   orders:    │
                              │            │   generated  │     │   intents    │
                              │            │              │     │              │
                              │            └──────────────┘     └──────────────┘
                              │                                        │
                              │                                        │
                              ▼                                        ▼
                      ┌─────────────────┐                  ┌──────────────────┐
                      │                 │                  │                  │
                      │  events:bus     │◀─────────────────│  Execution Agent │
                      │                 │                  │                  │
                      │ • Errors        │                  │ • Order Submit   │
                      │ • Health        │                  │ • Fill Tracking  │
                      │ • Alerts        │                  │ • Reconciliation │
                      │                 │                  │                  │
                      └─────────────────┘                  └──────────────────┘
```

---

## 📂 Module Breakdown

### 1. **Infrastructure Layer** (`agents/infrastructure/`)

**Purpose**: Ingests raw market data from Kraken WebSocket and publishes to Redis streams.

**Key Components**:
- `data_pipeline.py` - WebSocket → Redis stream adapter with batching
- `redis_client.py` - Production Redis client with retry/backoff
- `redis_health.py` - Connection health monitoring

**Output Streams**:
- `md:trades:{symbol}` - Individual trades
- `md:spread:{symbol}` - Bid/ask spreads
- `md:book:{symbol}` - Order book snapshots
- `md:candles:{symbol}:{tf}` - OHLCV candles per timeframe

---

### 2. **Core Layer** (`agents/core/`)

**Purpose**: Strategy execution and signal generation.

**Key Components**:
- `market_scanner.py` - Reads market data streams and runs strategies
- `signal_analyst.py` - Multi-strategy signal aggregation
- `signal_processor.py` - Deduplication and signal routing
- `execution_agent.py` - Submits orders to exchange and tracks fills

**Output Streams**:
- `signals:generated` - Trading signals after strategy analysis
- `signals:paper:{pair}` - Paper trading signals (test mode)

---

### 3. **Risk Layer** (`agents/risk/`)

**Purpose**: Gate-keeping system that validates signals against risk constraints.

**Key Components**:
- `risk_router.py` - **Main orchestrator** (Compliance → Drawdown → Balancer)
- `compliance_checker.py` - Validates against regulatory/policy rules
- `drawdown_protector.py` - Monitors daily/position drawdowns
- `portfolio_balancer.py` - Position sizing and allocation limits

**Flow**: `Signal → Compliance → Drawdown → Balancer → OrderIntent`

**Output**: `OrderIntent` (if approved) or denial with reasons

---

### 4. **Scalper Module** (`agents/scalper/`)

**Purpose**: High-frequency scalping agent with sub-second execution.

**Key Components**:
- `kraken_scalper_agent.py` - Main scalping agent
- `analysis/liquidity.py` - Spread and depth analysis
- `analysis/order_flow.py` - Book imbalance detection
- `execution/position_manager.py` - Active position tracking
- `infra/redis_bus.py` - **Production Redis message bus** (Streams + Pub/Sub + RPC)

**Output Streams**:
- Uses `RedisBus` with custom stream names per scalping strategy

---

## 🔄 Data Flow Sequence

### Happy Path: Market Data → Signal → Order

```
1. Kraken WS: Trade {BTC/USD, price=50000, size=0.5}
   │
   ▼
2. DataPipeline: Normalizes → xadd("md:trades:BTC-USD", {...})
   │
   ▼
3. MarketScanner: xreadgroup("md:trades:BTC-USD") → runs strategies
   │
   ▼
4. Strategy: Detects signal → creates Signal{BTC/USD, side=BUY, confidence=0.85}
   │
   ▼
5. RiskRouter.assess(signal, price_usd=50000):
   ├── ComplianceChecker: ✓ allowed (not sanctioned symbol)
   ├── DrawdownProtector: ✓ allowed (no halt, size_multiplier=1.0)
   └── PortfolioBalancer: ✓ allowed (notional=$1000, leverage=1.0)
   │
   ▼
6. RiskRouter: Returns OrderIntent{BTC/USD, side=BUY, size_quote_usd=1000}
   │
   ▼
7. ExecutionAgent: Submits order to Kraken → tracks fill
   │
   ▼
8. EventBus: Publishes "order.filled" → xadd("events:bus", {type: "execution", ...})
```

---

## 📡 Redis Streams Reference

### **Redis Cloud Connection**
- **Environment**: `REDIS_URL=rediss://username:password@host:port/db`
- **TLS**: Required (Redis Cloud uses `rediss://` protocol)
- **Conda Env**: `crypto-bot` (Python 3.10.18)

### Stream 1: `md:trades:{symbol}`

**Purpose**: Real-time trade feed per symbol (e.g., `md:trades:BTC-USD`)

**Example Payload**:
```json
{
  "symbol": "BTC/USD",
  "price": "50123.45",
  "size": "0.125",
  "side": "buy",
  "trade_id": "1234567890",
  "exchange_ts": "1704067200.123",
  "received_ts": "1704067200.145"
}
```

**Consumer Groups**: `md:trades_group`, `scalper_trades_group`

---

### Stream 2: `md:spread:{symbol}`

**Purpose**: Bid/ask spread snapshots per symbol

**Example Payload**:
```json
{
  "symbol": "BTC/USD",
  "bid": "50120.00",
  "ask": "50125.00",
  "spread_bps": "1.0",
  "timestamp": "1704067200.456"
}
```

**Consumer Groups**: `md:spread_group`

---

### Stream 3: `md:book:{symbol}`

**Purpose**: Order book snapshots (top 10 levels)

**Example Payload**:
```json
{
  "symbol": "BTC/USD",
  "bids": [
    ["50120.00", "1.25"],
    ["50119.00", "2.50"]
  ],
  "asks": [
    ["50125.00", "0.75"],
    ["50126.00", "1.00"]
  ],
  "timestamp": "1704067200.789",
  "checksum": "abc123"
}
```

**Consumer Groups**: `md:book_group`, `scalper_book_group`

---

### Stream 4: `md:candles:{symbol}:{tf}`

**Purpose**: OHLCV candles per symbol and timeframe (e.g., `md:candles:BTC-USD:1m`)

**Example Payload**:
```json
{
  "symbol": "BTC/USD",
  "timeframe": "1m",
  "open": "50100.00",
  "high": "50150.00",
  "low": "50090.00",
  "close": "50125.00",
  "volume": "12.5",
  "trades_count": 45,
  "start_ts": "1704067200.000",
  "received_ts": "1704067260.123"
}
```

**Consumer Groups**: `md:candles_group`

---

### Stream 5: `signals:generated`

**Purpose**: Trading signals from strategies (production mode)

**Schema**: `Signal` from `mcp/schemas.py`

**Example Payload**:
```json
{
  "schema_version": "1.0",
  "type": "signal",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "exchange": "kraken",
  "source": "mcp",
  "strategy": "scalp",
  "symbol": "BTC/USD",
  "timeframe": "15s",
  "side": "buy",
  "confidence": 0.85,
  "features": {
    "volume_ratio": 1.2,
    "book_imbalance": 0.7,
    "spread_bps": 2.5
  },
  "risk": {
    "sl_bps": 5,
    "tp_bps": [10, 15],
    "ttl_s": 120
  },
  "notes": "Strong book imbalance signal",
  "timestamp": 1704067200.456
}
```

**Consumer Groups**: `risk_router_group`, `signal_processor_group`

---

### Stream 6: `signals:paper:{pair}`

**Purpose**: Paper trading signals (test mode without real execution)

**Example**: `signals:paper:BTC-USD`

**Payload**: Same as `signals:generated` but isolated for testing

---

### Stream 7: `orders:intents`

**Purpose**: Risk-approved order intents ready for execution

**Schema**: `OrderIntent` from `mcp/schemas.py`

**Example Payload**:
```json
{
  "schema_version": "1.0",
  "type": "order.intent",
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "exchange": "kraken",
  "symbol": "BTC/USD",
  "side": "buy",
  "order_type": "limit",
  "price": 50000.00,
  "size_quote_usd": 1000.00,
  "reduce_only": false,
  "post_only": true,
  "tif": "GTC",
  "metadata": {
    "strategy": "scalp",
    "signal_id": "550e8400-e29b-41d4-a716-446655440000",
    "confidence": 0.85,
    "source": "risk_router",
    "leverage": 1.0
  },
  "timestamp": 1704067200.789
}
```

**Consumer Groups**: `execution_agent_group`

---

### Stream 8: `events:bus`

**Purpose**: System-wide events (errors, health checks, alerts)

**Example Payload** (Error Event):
```json
{
  "type": "error",
  "severity": "warning",
  "component": "data_pipeline",
  "message": "WebSocket reconnecting after timeout",
  "details": {
    "symbol": "BTC/USD",
    "error_code": "WS_TIMEOUT",
    "retry_count": 2
  },
  "timestamp": 1704067200.999
}
```

**Example Payload** (Health Check):
```json
{
  "type": "health",
  "component": "risk_router",
  "status": "healthy",
  "metrics": {
    "signals_processed": 1234,
    "signals_approved": 890,
    "signals_denied": 344,
    "avg_latency_ms": 12.5
  },
  "timestamp": 1704067200.111
}
```

**Consumer Groups**: `monitoring_group`, `alerting_group`

---

## 🚦 Risk Router Decision Flow

The `RiskRouter` is the **critical gate** between signals and execution. It enforces strict precedence:

```
Signal Input
    │
    ├──> [1] Compliance Check
    │    ├─✗─> DENY: compliance-reject
    │    └─✓─> Continue
    │
    ├──> [2] Drawdown Check
    │    ├─✗─> DENY: drawdown-halt
    │    ├─⚠─> SOFT: drawdown-reduce-only (flag set)
    │    └─✓─> Continue (with size_multiplier: 0.0-1.0)
    │
    ├──> [3] Balancer Check
    │    ├─✗─> DENY: over-cap-gross / over-cap-net / over-budget-strategy
    │    │         spread-too-wide / depth-too-thin / size-too-small
    │    └─✓─> Continue (with final notional, leverage)
    │
    └──> [4] Build OrderIntent
         └─✓─> OUTPUT: OrderIntent with all risk constraints applied
```

**Canonical Deny Reasons** (ordered):
1. `compliance-reject`
2. `drawdown-halt`
3. `drawdown-reduce-only` (soft stop, reduces position size)
4. `over-cap-gross` / `over-cap-net` / `over-cap-symbol`
5. `over-budget-strategy`
6. `spread-too-wide`
7. `depth-too-thin`
8. `size-too-small`
9. `missing-price` / `malformed-symbol` / `malformed-signal`

---

## 🔌 Scalper Redis Bus

The `agents/scalper/infra/redis_bus.py` module provides a **production-grade message bus** with:

### Features
- **Streams**: Consumer groups with pending message handling
- **Pub/Sub**: Fan-out broadcasting
- **RPC**: Request/response pattern with timeout
- **TLS**: Redis Cloud support with certifi CA certs
- **Compression**: Optional gzip+base64 for large payloads
- **Backpressure**: Stream trimming (MAXLEN ~10k)
- **Idempotency**: Message deduplication via correlation_id

### Message Envelope

All messages use a standardized envelope from `redis_bus.Message`:

```python
{
  "id": "uuid",                    # Unique message ID
  "type": "market_data|signal|order|execution|risk|health|control|metrics",
  "source": "agent_id",            # Producer identity
  "destination": "target_agent",   # Optional routing
  "timestamp": 1704067200.123,     # UTC epoch
  "correlation_id": "trace_id",    # For request tracing
  "reply_to": "channel",           # For RPC replies
  "expiry": 1704067500.0,          # Optional TTL
  "data": { ... },                 # Actual payload
  "metadata": { ... }              # Optional routing metadata
}
```

### Delivery Modes
1. **STREAM**: Persistent, ordered, consumer groups (main trading flow)
2. **PUBSUB**: Fire-and-forget, fan-out (alerts, monitoring)
3. **QUEUE**: Simple FIFO with LPUSH/RPOP (background jobs)
4. **REQUEST_RESPONSE**: RPC pattern with reply channel (control plane)

---

## 📊 Monitoring & Health

### Key Metrics (Redis Streams)

- **`md:*` streams**: Message lag < 1 second
- **`signals:generated`**: P95 processing latency < 500ms
- **`orders:intents`**: Execution fill rate > 95%
- **`events:bus`**: Error rate < 0.1%

### Health Check Pattern

```bash
# Check Redis connection
redis-cli -u $REDIS_URL ping

# Check stream lag
redis-cli -u $REDIS_URL XINFO GROUPS md:trades:BTC-USD

# Check consumer group status
redis-cli -u $REDIS_URL XINFO CONSUMERS md:trades:BTC-USD trades_group
```

### SLO Compliance

See `monitoring/slo_tracker.py` for:
- P95 latency tracking
- Uptime monitoring (target: 99.5%)
- Stream lag alerts (threshold: 1s)
- Duplicate rate (target: <0.1%)

---

## 🔧 Quick Start for Developers

### 1. Setup Environment

```bash
# Activate conda environment
conda activate crypto-bot

# Verify Redis connection
python -c "import redis.asyncio as redis; import asyncio; asyncio.run(redis.from_url('$REDIS_URL').ping())"
```

### 2. Run Example: Signal Scanner

```bash
# Generate signals for 30 seconds (paper mode)
python -m agents.examples.scan_and_publish --pair BTC/USD --duration 30

# Watch signals being published to Redis
redis-cli -u $REDIS_URL XREAD COUNT 10 STREAMS signals:paper:BTC-USD 0-0
```

### 3. Test Risk Router

```bash
# Run unit tests
pytest tests/test_risk_router.py -v

# Check coverage
pytest tests/test_risk_router.py --cov=agents.risk.risk_router
```

### 4. Monitor Streams

```bash
# Watch market data stream
redis-cli -u $REDIS_URL XREAD COUNT 5 STREAMS md:trades:BTC-USD $

# Check stream lengths
redis-cli -u $REDIS_URL XLEN md:trades:BTC-USD
redis-cli -u $REDIS_URL XLEN signals:generated
```

---

## 📚 Additional Resources

- **Project Structure**: [docs/PROJECT_SKELETON.md](PROJECT_SKELETON.md)
- **Examples**: [agents/examples/README.md](../agents/examples/README.md)
- **Quick Start**: [agents/examples/QUICKSTART.md](../agents/examples/QUICKSTART.md)
- **API Schemas**: [mcp/schemas.py](../mcp/schemas.py)
- **Main README**: [README.md](../README.md)

---

## ❓ FAQ

**Q: Where are Redis stream keys defined?**
A: `agents/infrastructure/data_pipeline.py` lines 40-44

**Q: How do I add a new strategy?**
A: Implement in `agents/core/market_scanner.py` and it will auto-publish to `signals:generated`

**Q: What happens if RiskRouter denies a signal?**
A: Returns `RouteResult{allowed=False, reasons=[...]}` and signal is NOT forwarded to execution

**Q: Can I test without Redis Cloud?**
A: Yes! Use `fakeredis` for hermetic tests (see `tests/test_redis_client.py`)

**Q: How do I trace a signal through the entire flow?**
A: Use `correlation_id` field — it propagates from Signal → OrderIntent → Order execution

---

**Total Read Time: ~2 minutes** ⏱️

**You now understand**:
- ✅ How market data flows through the system
- ✅ What each Redis stream contains
- ✅ How the Risk Router gates signals
- ✅ Where to find code for each component
- ✅ How to test and monitor the system

Ready to contribute! 🚀
