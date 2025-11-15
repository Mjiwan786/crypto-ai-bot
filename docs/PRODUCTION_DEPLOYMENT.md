# Production Deployment Guide - Maker-Only Execution System

## Overview

This guide covers the complete deployment of the maker-only execution system with:

1. **Spread Calculator** - Real-time bid-ask spread calculation from orderbook
2. **Order State Publisher** - Redis stream publishing for fill/order events
3. **Execution Agent** - Maker-only execution with spread filtering
4. **Regime Gates** - 24/7 throttling based on EMA/ATR
5. **Grafana Monitoring** - Real-time dashboards for maker %

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                     KRAKEN WEBSOCKET                           │
│                                                                │
│  ┌──────────┐      ┌──────────┐       ┌──────────┐           │
│  │ Orderbook│──┬──>│  Spread  │──────>│  Redis   │           │
│  │  Stream  │  │   │Calculator│       │ Streams  │           │
│  └──────────┘  │   └──────────┘       └──────────┘           │
│                │                              │                │
│                └──────────────────────────────┘                │
└────────────────────────────────────────────────────────────────┘
                                                 │
                                                 v
┌────────────────────────────────────────────────────────────────┐
│                   EXECUTION PIPELINE                           │
│                                                                │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌─────────┐│
│  │ Regime   │───>│ Strategy │───>│Execution │───>│ Order   ││
│  │  Gates   │    │ Signals  │    │  Agent   │    │Publisher││
│  │(EMA/ATR) │    │          │    │(Maker %) │    │         ││
│  └──────────┘    └──────────┘    └──────────┘    └─────────┘│
│                                        │                       │
│                                        v                       │
│                                   ┌──────────┐                │
│                                   │  Redis   │                │
│                                   │  Fills   │                │
│                                   └──────────┘                │
└────────────────────────────────────────────────────────────────┘
                                        │
                                        v
┌────────────────────────────────────────────────────────────────┐
│                     MONITORING                                 │
│                                                                │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                │
│  │ Grafana  │<───│  Redis   │<───│  Alerts  │                │
│  │Dashboard │    │  Streams │    │  (Slack) │                │
│  └──────────┘    └──────────┘    └──────────┘                │
└────────────────────────────────────────────────────────────────┘
```

## Prerequisites

### Environment

```bash
# Conda environment
conda activate crypto-bot

# Python 3.10+
python --version

# Redis Cloud
redis-cli -u rediss://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls PING
```

### Dependencies

```bash
# Core dependencies (already in requirements.txt)
pip install redis orjson pydantic websockets
pip install pandas numpy

# Monitoring
pip install grafana-client

# Testing
pip install pytest pytest-asyncio
```

## Step 1: Configure Environment Variables

Create `.env` file from `.env.example`:

```bash
cp .env.example .env
```

Edit `.env` with production values:

```bash
# Redis Cloud (TLS required)
REDIS_URL=rediss://default:<YOUR_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_TLS=true
REDIS_MAX_CONNECTIONS=20
REDIS_SOCKET_TIMEOUT=5

# Kraken API
KRAKEN_API_KEY=<YOUR_API_KEY>
KRAKEN_API_SECRET=<YOUR_API_SECRET>
KRAKEN_SANDBOX=true  # Set to false for production

# Trading Mode
TRADING_MODE=PAPER  # Or LIVE with confirmation
# LIVE_CONFIRMATION=YES_I_WANT_LIVE_TRADING

# Trading Pairs
TRADING_PAIRS=BTCUSDT,ETHUSDT

# Maker-Only Execution
MAKER_ONLY=true
MAX_QUEUE_S=10
SPREAD_BPS_CAP=8

# Regime Gates
REGIME_K_TREND=1.5
MIN_ATR_PCT=0.4
MAX_ATR_PCT=3.0
REGIME_K_CHOP=1.0

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

## Step 2: Deploy Spread Stream Publisher

Wire spread calculator to Kraken WebSocket:

```python
# In your main trading script
from agents.infrastructure.spread_stream_publisher import SpreadStreamPublisher
from utils.kraken_ws import KrakenWebSocketClient
import redis.asyncio as redis

# Initialize Redis
redis_client = redis.from_url(
    os.getenv("REDIS_URL"),
    ssl_cert_reqs='required',
    decode_responses=False,
)

# Create spread publisher
spread_publisher = SpreadStreamPublisher(redis_client=redis_client)

# Create Kraken WS client
kraken_client = KrakenWebSocketClient()

# Wire spread publisher to orderbook callback
kraken_client.register_callback("book", spread_publisher.on_orderbook_update)

# Start streaming
await kraken_client.start()
```

**Verify Spread Streams**:
```bash
# Check spread data
redis-cli -u $REDIS_URL --tls XLEN kraken:spread:BTC-USD

# Read recent spreads
redis-cli -u $REDIS_URL --tls XREVRANGE kraken:spread:BTC-USD + - COUNT 10
```

## Step 3: Deploy Execution Agent with Order Publishing

Initialize execution agent with Redis:

```python
from agents.core.execution_agent import EnhancedExecutionAgent
import redis.asyncio as redis

# Initialize Redis
redis_client = redis.from_url(
    os.getenv("REDIS_URL"),
    ssl_cert_reqs='required',
    decode_responses=False,
)

# Configure execution engine
execution_config = {
    "maker_only": True,
    "max_queue_s": 10,
    "spread_bps_cap": 8,
}

# Create execution agent with Redis publishing
execution_agent = EnhancedExecutionAgent(
    config=execution_config,
    redis_client=redis_client,
)

# Execute signals (will automatically publish fills to Redis)
fill = await execution_agent.execute_signal(signal_data)
```

**Verify Fill Publishing**:
```bash
# Check fills stream
redis-cli -u $REDIS_URL --tls XLEN kraken:fills:BTC-USD

# Read recent fills
redis-cli -u $REDIS_URL --tls XREVRANGE kraken:fills:BTC-USD + - COUNT 10
```

## Step 4: Deploy Regime Gates

Regime gates are already integrated into strategies. Verify configuration:

```python
from strategies.momentum_strategy import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy

# Momentum with TrendGate
momentum = MomentumStrategy(
    regime_k=1.5,          # Strong trend required
    min_atr_pct=0.4,       # Min 0.4% ATR
    max_atr_pct=3.0,       # Max 3.0% ATR
)

# Mean reversion with ChopGate (inverted)
mean_rev = MeanReversionStrategy(
    regime_k=1.0,              # Lower k for chop
    regime_max_atr_pct=1.5,    # Lower ATR ceiling
)
```

**Monitor Regime Gates**:
```python
# Check TrendGate metrics
metrics = momentum.trend_gate.get_metrics()
print(f"Pass rate: {metrics.pass_rate:.1f}%")
print(f"Trend strength: {metrics.trend_strength_pct:.2f}%")
print(f"ATR %: {metrics.atr_pct:.2f}%")
```

## Step 5: Deploy Grafana Dashboard

### Install Grafana

**Docker**:
```bash
docker run -d \
  --name=grafana \
  -p 3000:3000 \
  -e "GF_INSTALL_PLUGINS=redis-datasource" \
  grafana/grafana-enterprise
```

### Configure Redis Data Source

1. Navigate to http://localhost:3000
2. Login (admin/admin)
3. Go to **Configuration** > **Data Sources**
4. Add **Redis** data source
5. Configure:
   - URL: redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
   - TLS: Enabled
   - Username: default
   - Password: <YOUR_PASSWORD>

### Import Dashboard

```bash
# Via Grafana UI
# 1. Go to Dashboards > Import
# 2. Upload monitoring/grafana/maker_monitoring_dashboard.json
# 3. Select Redis Cloud as data source
# 4. Click Import

# Or via API
curl -X POST http://localhost:3000/api/dashboards/db \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -H "Content-Type: application/json" \
  -d @monitoring/grafana/maker_monitoring_dashboard.json
```

### Configure Alerts

1. **Low Maker %**: Alert when <80%
2. **High Spread Rejections**: Alert when >50/hour
3. **Circuit Breaker**: Alert on all trips

## Step 6: Run Complete System

### Development Mode (Paper Trading)

```bash
# Start trading system
conda activate crypto-bot
python scripts/start_trading_system.py \
  --mode paper \
  --strategies momentum,mean_reversion,breakout \
  --pairs BTCUSDT,ETHUSDT
```

### Production Mode (Live Trading)

**WARNING**: Only enable live trading after thorough testing!

```bash
# Set environment
export TRADING_MODE=LIVE
export LIVE_CONFIRMATION=YES_I_WANT_LIVE_TRADING

# Start with maker-only execution
conda activate crypto-bot
python scripts/start_trading_system.py \
  --mode live \
  --strategies momentum,mean_reversion,breakout \
  --pairs BTCUSDT,ETHUSDT \
  --maker-only \
  --max-queue-s 10 \
  --spread-bps-cap 8
```

## Step 7: Monitor System Health

### Real-time Monitoring

1. **Grafana Dashboard**: http://localhost:3000
   - Maker % should be >90%
   - Rebates should be accumulating
   - Spread rejections should be <50/hour

2. **Redis Streams**:
```bash
# Check stream health
redis-cli -u $REDIS_URL --tls INFO STREAM

# Monitor fill rate
watch -n 1 'redis-cli -u $REDIS_URL --tls XLEN kraken:fills:BTC-USD'
```

3. **Logs**:
```bash
# Tail execution agent logs
tail -f logs/execution_agent.log | grep -E "(maker=|spread_bps=)"

# Tail regime gate logs
tail -f logs/strategies.log | grep -E "(TrendGate|ChopGate)"
```

### Key Metrics

| Metric | Target | Alert |
|--------|--------|-------|
| Maker % | >90% | <80% |
| Avg Queue Time | <5s | >8s |
| Spread Rejections | <50/hr | >100/hr |
| Fill Rate | >70% | <50% |
| Regime Pass Rate (Trend) | 30-40% | <20% |
| Regime Pass Rate (Chop) | 60-70% | <40% |

## Step 8: Backtest Validation

Before live trading, validate with historical data:

```bash
# Run backtest with maker-only execution
python scripts/backtest.py scalper \
  --symbol BTC/USD \
  --start 2024-01-01 \
  --end 2024-01-31 \
  --maker-only \
  --max-queue-s 10 \
  --spread-bps-cap 8 \
  --output results/maker_only_backtest.json
```

**Validate Results**:
- Maker % should be >90%
- Rebates should offset taker fees
- Spread filtering should reduce bad entries
- Sharpe ratio should improve vs. baseline

## Step 9: A/B Testing

Run A/B test to measure maker-only impact:

```bash
# Test A: Maker-only
python scripts/backtest.py scalper \
  --symbol BTC/USD \
  --start 2024-01-01 \
  --end 2024-01-31 \
  --maker-only \
  --output results/test_a_maker_only.json

# Test B: Mixed execution
python scripts/backtest.py scalper \
  --symbol BTC/USD \
  --start 2024-01-01 \
  --end 2024-01-31 \
  --output results/test_b_mixed.json

# Compare results
python scripts/compare_backtests.py \
  results/test_a_maker_only.json \
  results/test_b_mixed.json
```

**Expected Improvements**:
- Lower net fees (rebates earned)
- Higher Sharpe ratio
- Lower turnover
- Better fill quality

## Troubleshooting

### Issue: Low Maker %

**Symptoms**: Maker % <80%

**Diagnosis**:
```bash
# Check spread conditions
redis-cli -u $REDIS_URL --tls XREVRANGE kraken:spread:BTC-USD + - COUNT 100 | grep spread_bps

# Check queue times
redis-cli -u $REDIS_URL --tls XREVRANGE kraken:fills:BTC-USD + - COUNT 100 | grep exec_time_ms
```

**Solutions**:
1. Increase `max_queue_s` (10s → 15s)
2. Widen `spread_bps_cap` (8bps → 12bps)
3. Check for illiquid pairs (switch to BTC/ETH only)

### Issue: High Spread Rejections

**Symptoms**: >100 rejections/hour

**Diagnosis**:
```bash
# Check circuit breaker events
redis-cli -u $REDIS_URL --tls XREVRANGE kraken:circuit_breaker:BTC-USD + - COUNT 10
```

**Solutions**:
1. Increase `spread_bps_cap` (8bps → 12bps)
2. Add pair-specific caps
3. Pause trading during high volatility

### Issue: Regime Gates Rejecting Too Many Bars

**Symptoms**: <20% pass rate on TrendGate

**Diagnosis**:
```python
metrics = strategy.trend_gate.get_metrics()
print(f"Pass rate: {metrics.pass_rate:.1f}%")
print(f"Trend strength: {metrics.trend_strength_pct:.2f}%")
print(f"ATR %: {metrics.atr_pct:.2f}%")
```

**Solutions**:
1. Lower `regime_k` (1.5 → 1.0)
2. Widen ATR range (0.4-3.0% → 0.3-4.0%)
3. Lower volume threshold

## Production Checklist

- [ ] Environment variables configured
- [ ] Redis Cloud connection tested
- [ ] Spread publisher deployed and verified
- [ ] Execution agent integrated with Redis
- [ ] Grafana dashboard imported
- [ ] Alerts configured (Slack/Discord)
- [ ] Backtests validated
- [ ] A/B test completed
- [ ] Dry run in paper mode (1 week)
- [ ] Risk limits set
- [ ] Emergency stop procedures documented

## Next Steps

1. **Historical Analysis**: Export Redis streams to ClickHouse for long-term storage
2. **ML Enhancement**: Train ML model on spread patterns for better filtering
3. **Multi-Exchange**: Extend to Binance, Coinbase for comparison
4. **Adaptive Parameters**: Auto-tune spread_bps_cap based on market conditions
5. **Latency Optimization**: Move to AWS/GCP closer to exchanges

## References

- **Regime Gates**: `docs/REGIME_GATES.md`
- **PnL Pipeline**: `docs/PNL_PIPELINE.md`
- **Grafana Setup**: `monitoring/grafana/README.md`
- **PRD**: `PRD_AGENTIC.md`
- **Config Guide**: `config/CONFIG_USAGE.md`
