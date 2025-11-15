# PnL Pipeline Architecture - Crypto AI Bot

**Production-grade profit/loss tracking and equity aggregation system.**

## Overview

The PnL pipeline provides real-time equity tracking and historical PnL data without requiring a web dashboard. It consists of three main components:

```
┌─────────────────────────────────────────────────────────┐
│  PUBLISHER (agents/infrastructure/pnl_publisher.py)     │
│                                                         │
│  publish_trade_close(event) → trades:closed            │
│  publish_equity_point(ts, equity, daily_pnl)           │
│                           → pnl:equity                  │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  REDIS STREAMS                                          │
│                                                         │
│  Stream: trades:closed    (individual trade results)   │
│  Stream: pnl:equity       (aggregated equity curve)    │
│  Key:    pnl:equity:latest (current equity snapshot)   │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  AGGREGATOR (monitoring/pnl_aggregator.py)              │
│                                                         │
│  Consumes: trades:closed                                │
│  Aggregates: equity += pnl                              │
│  Detects: UTC day boundaries                            │
│  Publishes: pnl:equity + pnl:equity:latest              │
│  Optional: pandas statistics (win_rate, sharpe, etc)    │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. Publisher (`agents/infrastructure/pnl_publisher.py`)

**Purpose**: Emit trade close events and equity snapshots to Redis streams.

**Functions**:

#### `publish_trade_close(event: dict) -> None`

Publishes a trade close event to Redis stream `trades:closed`.

**Required event fields**:
```python
{
    "id": str,           # Unique trade identifier
    "ts": int,           # Timestamp in milliseconds
    "pair": str,         # Trading pair (e.g., "BTC/USD")
    "side": str,         # "long" or "short"
    "entry": float,      # Entry price
    "exit": float,       # Exit price
    "qty": float,        # Quantity traded
    "pnl": float,        # Realized profit/loss in USD
}
```

**Example**:
```python
from agents.infrastructure.pnl_publisher import publish_trade_close

publish_trade_close({
    "id": "trade_12345",
    "ts": 1704067200000,
    "pair": "BTC/USD",
    "side": "long",
    "entry": 45000.0,
    "exit": 46000.0,
    "qty": 0.1,
    "pnl": 100.0,
})
```

**Behavior**:
- Validates all required fields and types
- Serializes event to JSON using orjson (or stdlib json)
- Publishes to Redis stream `trades:closed` with field `json`
- **Silent failure**: Returns without error if Redis unavailable

#### `publish_equity_point(ts_ms: int, equity: float, daily_pnl: float) -> None`

Publishes an equity snapshot to Redis stream `pnl:equity` and updates latest value.

**Parameters**:
- `ts_ms`: Timestamp in milliseconds
- `equity`: Current account equity in USD
- `daily_pnl`: Today's profit/loss in USD

**Example**:
```python
from agents.infrastructure.pnl_publisher import publish_equity_point

publish_equity_point(
    ts_ms=1704067200000,
    equity=10500.0,
    daily_pnl=500.0,
)
```

**Behavior**:
- Creates snapshot: `{"ts": ts_ms, "equity": equity, "daily_pnl": daily_pnl}`
- Publishes to stream `pnl:equity` with field `json`
- Updates key `pnl:equity:latest` with same snapshot
- **Silent failure**: Returns without error if Redis unavailable

**Redis Connection**:
- Singleton client created via `redis.from_url(os.getenv("REDIS_URL"))`
- Connection timeout: 2 seconds
- Automatically retries once on connection failure
- All exceptions caught and suppressed (no logging spam)

### 2. Aggregator (`monitoring/pnl_aggregator.py`)

**Purpose**: Consume trade close events, accumulate equity, detect day boundaries, and publish aggregated data.

**Main Function**: `run_pnl_aggregator()`

**Configuration (Environment Variables)**:
```bash
REDIS_URL=rediss://...             # Redis connection string
START_EQUITY=10000.0               # Initial equity in USD
POLL_MS=500                        # Polling interval in milliseconds
STATE_KEY=pnl:agg:last_id          # Redis key for resume state
PNL_METRICS_PORT=                  # Prometheus port (optional)
USE_PANDAS=false                   # Enable pandas statistics
STATS_WINDOW_SIZE=5000             # Rolling window size
```

**Behavior**:

1. **Connect to Redis**: Pings Redis and exits if unreachable
2. **Resume from checkpoint**: Reads `STATE_KEY` to get last processed message ID (default: "0-0")
3. **Restore equity**: Reads `pnl:equity:latest` to restore current equity and daily PnL
4. **Main loop**:
   - Polls `trades:closed` stream with `XREAD` (blocking, count=200)
   - For each trade:
     - Extracts `pnl` and `ts` from event
     - Checks for UTC day boundary crossing
     - If new day: resets `daily_pnl` to 0
     - Updates: `equity += pnl`, `daily_pnl = equity - day_start_equity`
     - Publishes equity point via `_publish_equity_point()`
     - Updates Prometheus metrics (if enabled)
   - Saves checkpoint: `SET STATE_KEY last_id`
5. **Graceful shutdown**: Saves final state on Ctrl+C

**Day Boundary Detection**:
```python
def _get_current_day_start_ms() -> int:
    """Get current UTC day start timestamp in milliseconds."""
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(day_start.timestamp() * 1000)
```

**Example output**:
```
============================================================
PNL AGGREGATOR SERVICE
============================================================
Redis URL: rediss://...
Start Equity: $10,000.00
Poll Interval: 500ms
State Key: pnl:agg:last_id
============================================================
✅ Connected to Redis
📍 Resuming from last ID: 0-0
🚀 Starting aggregator loop...

📈 Trade 1: PnL +$100.00 → Equity $10,100.00 (daily: +$100.00)
📈 Trade 2: PnL +$50.00 → Equity $10,150.00 (daily: +$150.00)
📅 Day boundary crossed! Resetting daily PnL. Previous: $150.00
📈 Trade 3: PnL +$75.00 → Equity $10,225.00 (daily: +$75.00)
```

**Optional: Pandas Statistics**:

When `USE_PANDAS=true`, the aggregator calculates and publishes rolling statistics:

```bash
# Enable statistics
export USE_PANDAS=true
export STATS_WINDOW_SIZE=5000

# Statistics published to Redis keys:
pnl:stats:win_rate         # Percentage of winning trades
pnl:stats:max_drawdown     # Maximum cumulative drawdown
pnl:stats:sharpe           # Naive Sharpe ratio (mean/std)
```

**Example**:
```python
# Read statistics
import redis
r = redis.from_url(os.getenv("REDIS_URL"))
win_rate = float(r.get("pnl:stats:win_rate"))
max_drawdown = float(r.get("pnl:stats:max_drawdown"))
sharpe = float(r.get("pnl:stats:sharpe"))

print(f"Win Rate: {win_rate:.1%}")
print(f"Max Drawdown: ${max_drawdown:,.2f}")
print(f"Sharpe Ratio: {sharpe:.2f}")
```

### 3. Backfill Tool (`scripts/backfill_pnl_from_fills.py`)

**Purpose**: Generate historical equity data from past trade fills.

**Usage**: See [PNL_BACKFILL.md](PNL_BACKFILL.md) for details.

**Quick example**:
```bash
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv --start-equity 10000
```

## Redis Keys & Streams

### Streams

#### `trades:closed`
**Purpose**: Individual trade close events (source of truth)

**Format**: Stream with field `json` containing serialized trade event

**Message structure**:
```python
{
    "id": "trade_12345",
    "ts": 1704067200000,
    "pair": "BTC/USD",
    "side": "long",
    "entry": 45000.0,
    "exit": 46000.0,
    "qty": 0.1,
    "pnl": 100.0,
}
```

**Lifecycle**:
- Written by: Publisher (`publish_trade_close`)
- Read by: Aggregator
- Retention: Unlimited (Redis Streams persist until manually trimmed)

#### `pnl:equity`
**Purpose**: Aggregated equity curve (time series)

**Format**: Stream with field `json` containing equity snapshot

**Message structure**:
```python
{
    "ts": 1704067200000,     # Timestamp in ms
    "equity": 10100.0,       # Current equity
    "daily_pnl": 100.0,      # Today's PnL
}
```

**Lifecycle**:
- Written by: Aggregator, Backfill tool
- Read by: Dashboards, analytics, health checks
- Retention: Unlimited (can be trimmed with XTRIM for memory management)

### Keys

#### `pnl:equity:latest`
**Type**: String (JSON blob)

**Purpose**: Latest equity snapshot for quick access

**Format**:
```json
{
    "ts": 1704067200000,
    "equity": 10100.0,
    "daily_pnl": 100.0
}
```

**Lifecycle**:
- Written by: Aggregator (on every trade), Backfill tool
- Read by: Health checks, dashboards, monitoring
- Updated: Real-time as trades process

#### `pnl:agg:last_id`
**Type**: String

**Purpose**: Resume checkpoint for aggregator

**Format**: Redis stream message ID (e.g., `"1704067200000-0"`)

**Lifecycle**:
- Written by: Aggregator (after each batch)
- Read by: Aggregator (on startup)
- Updated: After processing each batch (count=200)

#### `pnl:backfill:done`
**Type**: String

**Purpose**: Marker to prevent duplicate backfills

**Format**: `"true"`

**Lifecycle**:
- Written by: Backfill tool (on completion)
- Read by: Backfill tool (on startup)
- Cleared: Manually or with `--force` flag

#### `pnl:stats:*` (Optional)
**Type**: String (numeric values)

**Purpose**: Rolling statistics (when pandas enabled)

**Keys**:
- `pnl:stats:win_rate` - Win rate (0.0 to 1.0)
- `pnl:stats:max_drawdown` - Max drawdown in USD
- `pnl:stats:sharpe` - Sharpe ratio

**Lifecycle**:
- Written by: Aggregator (when `USE_PANDAS=true`)
- Read by: Dashboards, analytics
- Updated: After each batch of trades

## Service Level Objectives (SLOs)

### Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Publish Latency (P95)** | < 500ms | Time from `publish_trade_close()` call to Redis write |
| **Aggregation Latency (P95)** | < 500ms | Time from trade in stream to equity point published |
| **Batch Processing** | 200 trades < 500ms | Time to process full batch from XREAD |
| **Data Freshness** | < 5 minutes | Age of latest equity point |
| **Uptime** | > 99.5% | Aggregator service availability |
| **Message Loss** | 0% | All trades result in equity points |

### How SLOs Are Tested

**1. Unit Tests** (`tests/smoke/test_slo_pnl_latency.py`):
```bash
pytest tests/smoke/test_slo_pnl_latency.py -v
```

**Tests**:
- `test_publish_100_trades_under_1_second()` - Validates publish throughput
- `test_p95_latency_under_500ms()` - Validates P95 publish latency
- `test_no_message_loss()` - Validates 100% reliability
- `test_aggregator_processes_batch_under_500ms()` - Validates batch processing
- `test_aggregator_end_to_end_latency()` - Validates E2E latency
- `test_equity_data_freshness_under_5_minutes()` - Validates data freshness

**2. Health Checks** (`scripts/health_check_pnl.py`):
```bash
python scripts/health_check_pnl.py --verbose
```

**Checks**:
- Redis connectivity
- Stream activity (trades:closed, pnl:equity)
- P95 publish latency (calculated from timestamps)
- Data freshness (latest equity age)
- Latest equity value availability

**3. Prometheus Metrics** (when enabled):
```bash
export PNL_METRICS_PORT=9309
python -m monitoring.pnl_aggregator

# Check metrics
curl http://localhost:9309/metrics | grep pnl_aggregator
```

**Metrics**:
- `pnl_aggregator_equity_usd` (Gauge) - Current equity
- `pnl_aggregator_daily_pnl_usd` (Gauge) - Daily PnL
- `pnl_aggregator_trades_closed_total` (Counter) - Trades processed

### SLO Monitoring

**Automated (CI/CD)**:
```yaml
# .github/workflows/ci.yml
- name: Run SLO tests
  run: pytest tests/smoke/test_slo_pnl_latency.py -v
```

**Manual (Production)**:
```bash
# Run health check every 60 seconds
while true; do
  python scripts/health_check_pnl.py --json
  sleep 60
done
```

**Alerting (Prometheus)**:
```yaml
# Alert if equity hasn't updated in 5 minutes
- alert: PnLDataStale
  expr: time() - pnl_aggregator_last_update_seconds > 300
  for: 5m
  labels:
    severity: warning
```

## Safety Toggles

### Disable PnL Emission

**Environment Variable**: `EMIT_PNL_EVENTS`

**Purpose**: Disable trade close publishing without code changes

**Usage**:
```bash
# Disable PnL events
export EMIT_PNL_EVENTS=false

# Re-enable (default)
export EMIT_PNL_EVENTS=true
```

**Implementation** (example integration):
```python
# In your trading agent or position close handler
import os
from agents.infrastructure.pnl_publisher import publish_trade_close

def on_position_close(position, fill):
    """Called when a position closes."""

    # Calculate PnL
    pnl = calculate_pnl(position, fill)

    # Conditionally emit PnL event
    emit_enabled = os.getenv("EMIT_PNL_EVENTS", "true").lower() in ("true", "1", "yes")

    if emit_enabled:
        publish_trade_close({
            "id": position.id,
            "ts": int(time.time() * 1000),
            "pair": position.pair,
            "side": position.side,
            "entry": position.entry_price,
            "exit": fill.price,
            "qty": position.quantity,
            "pnl": pnl,
        })
    else:
        # Log that PnL emission is disabled (optional)
        logger.debug(f"PnL emission disabled for trade {position.id}")

    # Continue with rest of close logic
    update_account_balance(pnl)
    notify_risk_manager(position)
```

**When to disable**:
- **Development**: Testing position logic without polluting Redis
- **Debugging**: Isolating issues in trading system
- **Migration**: Switching between Redis instances
- **Maintenance**: Temporarily pausing PnL tracking

**Important**: Disabling PnL emission does NOT affect trading operations. It only stops publishing events to Redis streams.

### Disable Aggregator Statistics

**Environment Variable**: `USE_PANDAS`

**Purpose**: Disable pandas-based statistics calculation

**Usage**:
```bash
# Disable statistics (default)
export USE_PANDAS=false

# Enable statistics
export USE_PANDAS=true
export STATS_WINDOW_SIZE=5000  # Optional: set window size
```

**When to disable**:
- **Production**: If pandas not installed or not needed
- **Performance**: Reduce CPU usage for high-frequency trading
- **Memory**: Avoid keeping rolling window in memory

### Disable Prometheus Metrics

**Environment Variable**: `PNL_METRICS_PORT`

**Purpose**: Disable Prometheus metrics endpoint

**Usage**:
```bash
# Disable metrics (default)
unset PNL_METRICS_PORT

# Enable metrics
export PNL_METRICS_PORT=9309
```

**When to disable**:
- **Development**: When Prometheus not needed
- **Port conflicts**: If port 9309 already in use
- **Security**: Reduce exposed endpoints

## Integration Patterns

### Pattern 1: Post-Close Hook (Recommended)

**Where**: In your position manager or execution agent

**When**: After position is closed and PnL calculated

**Example**:
```python
from agents.infrastructure.pnl_publisher import publish_trade_close

class PositionManager:
    def close_position(self, position_id: str, fill_price: float):
        """Close a position and emit PnL event."""

        # 1. Get position details
        position = self.positions[position_id]

        # 2. Calculate PnL
        if position.side == "long":
            pnl = (fill_price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - fill_price) * position.quantity

        # 3. Update internal state
        self.update_equity(pnl)
        del self.positions[position_id]

        # 4. Emit PnL event (non-blocking, silent failure)
        publish_trade_close({
            "id": position_id,
            "ts": int(time.time() * 1000),
            "pair": position.pair,
            "side": position.side,
            "entry": position.entry_price,
            "exit": fill_price,
            "qty": position.quantity,
            "pnl": pnl,
        })

        # 5. Continue with other close logic
        self.notify_observers(position_id, pnl)
```

**Benefits**:
- Non-invasive (one function call)
- Silent failure (doesn't break trading if Redis down)
- Real-time emission (no batching delays)

### Pattern 2: Batch Emission (High-Frequency Trading)

**Where**: In a dedicated PnL reporting service

**When**: After accumulating N trades or every T seconds

**Example**:
```python
from agents.infrastructure.pnl_publisher import publish_trade_close

class BatchPnLEmitter:
    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size
        self.pending_trades = []

    def record_trade(self, trade_data: dict):
        """Record a trade for later emission."""
        self.pending_trades.append(trade_data)

        if len(self.pending_trades) >= self.batch_size:
            self.flush()

    def flush(self):
        """Emit all pending trades."""
        for trade in self.pending_trades:
            publish_trade_close(trade)

        self.pending_trades = []
```

**Benefits**:
- Reduces Redis write load
- Batches network calls
- Good for > 1000 trades/second

**Trade-offs**:
- Introduces latency (trades not immediately visible)
- Requires flush on shutdown

### Pattern 3: Async Emission (Event-Driven)

**Where**: In an event bus or message queue consumer

**When**: Consuming trade close events from internal queue

**Example**:
```python
import asyncio
from agents.infrastructure.pnl_publisher import publish_trade_close

class AsyncPnLEmitter:
    async def process_trade_events(self):
        """Consume trade events from queue and emit to Redis."""

        while True:
            # Get next trade from internal event queue
            trade_event = await self.trade_queue.get()

            # Emit to Redis (async-friendly, doesn't block)
            await asyncio.to_thread(publish_trade_close, trade_event)
```

**Benefits**:
- Decouples trading logic from PnL emission
- Non-blocking for trading system
- Can buffer during Redis outages

## Deployment

### Local Development

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Set Redis URL
export REDIS_URL=rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0

# 3. Start aggregator
python -m monitoring.pnl_aggregator
```

### Docker Compose

```bash
# Start PnL services
docker-compose up -d pnl-aggregator pnl-health

# Check logs
docker-compose logs -f pnl-aggregator

# Check health
docker-compose exec pnl-aggregator python scripts/health_check_pnl.py
```

### Process Manager (Foreman/Goreman)

```bash
# Start all PnL services
foreman start -f procfiles/pnl_all.proc
```

### Production Checklist

- [ ] Redis Cloud TLS connection configured
- [ ] `REDIS_URL` environment variable set
- [ ] Aggregator has auto-restart policy (`restart: unless-stopped`)
- [ ] Health checks configured (every 60s)
- [ ] Prometheus metrics enabled (optional)
- [ ] Backfill historical data (if needed)
- [ ] Test with `scripts/seed_closed_trades.py`
- [ ] Verify with `scripts/health_check_pnl.py`
- [ ] Monitor logs for errors
- [ ] Set up alerting for stale data (optional)

## Troubleshooting

### Common Issues

**"Redis connection failed"**
- Check `REDIS_URL` is set correctly
- Verify Redis Cloud is accessible
- Test with: `redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt PING`

**"pnl:equity stream is empty"**
- Ensure aggregator is running
- Check aggregator logs for errors
- Seed test trades: `python scripts/seed_closed_trades.py`

**"Aggregator not processing trades"**
- Check aggregator is polling correctly (logs should show XREAD calls)
- Verify trades are being published: `redis-cli XLEN trades:closed`
- Check for errors in aggregator logs

**"P95 latency too high (> 10s)"**
- Check network latency to Redis Cloud
- Consider using local Redis for development
- Reduce `POLL_MS` if needed (lower = more frequent polls)

**"Day boundary not resetting daily PnL"**
- Verify system clock is correct (UTC)
- Check aggregator logs for "Day boundary crossed!" message
- Ensure trades span multiple UTC days

## Related Documentation

- [PNL_VERIFICATION.md](PNL_VERIFICATION.md) - End-to-end verification guide
- [PNL_BACKFILL.md](PNL_BACKFILL.md) - Historical data backfilling
- [OPERATIONS.md](OPERATIONS.md) - General operations guide
- [CI_PIPELINE.md](CI_PIPELINE.md) - CI/CD pipeline details

---

**Last Updated**: 2025-01-13
**Conda Environment**: crypto-bot
**Python Version**: 3.10.18
**Redis Cloud**: redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 (TLS)
