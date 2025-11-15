# Paper Trading Trial - E2E Deployment Guide

**Step 11: Paper Trading Trial (14-21 Days)**

Complete end-to-end deployment guide for running the paper trading trial with full monitoring, metrics, and validation.

---

## Quick Start

### Prerequisites

1. **Redis Cloud Connection**
   ```bash
   export REDIS_URL="redis://default:********@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
   ```

2. **Redis CA Certificate**
   - Location: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem`
   - Verify exists: `test -f config/certs/redis_ca.pem && echo "✓ Found"`

3. **Conda Environment**
   ```bash
   conda activate crypto-bot
   ```

---

## Deployment Methods

### Method 1: Direct Python (Recommended for Testing)

```bash
# Activate conda environment
conda activate crypto-bot

# Set environment variables
export REDIS_URL="redis://default:********@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
export TRADING_PAIRS="BTC/USD,ETH/USD"
export TIMEFRAMES="5m"
export SPREAD_BPS_MAX="5.0"
export LATENCY_MS_MAX="500.0"
export METRICS_PORT="9108"
export LOG_LEVEL="INFO"

# Run paper trial
python scripts/run_paper_trial.py
```

### Method 2: Docker Compose (Recommended for Production)

```bash
# Create .env file
cat > .env << EOF
REDIS_URL=redis://default:********@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
TRADING_PAIRS=BTC/USD,ETH/USD
TIMEFRAMES=5m
SPREAD_BPS_MAX=5.0
LATENCY_MS_MAX=500.0
METRICS_PORT=9108
LOG_LEVEL=INFO
EOF

# Deploy with docker-compose
docker-compose --profile paper up -d

# View logs
docker-compose --profile paper logs -f paper-bot

# Stop
docker-compose --profile paper down
```

---

## Monitoring

### 1. Real-Time Dashboard

Open a second terminal and run the monitoring script:

```bash
conda activate crypto-bot
python scripts/monitor_paper_trial.py
```

**Output shows:**
- ✅ Signals published total
- ✅ Avg publish latency (target: <500ms)
- ✅ Last heartbeat
- ✅ Bot uptime
- ✅ Redis connection status
- ✅ Latest signals in stream
- ✅ DoD status

### 2. Prometheus Metrics

Access metrics endpoint:
```bash
curl http://localhost:9108/metrics
```

**Key Metrics:**
- `signals_published_total{agent,stream,symbol}` - Total signals by agent/stream/symbol
- `publish_latency_ms_bucket` - Histogram of publish latency
- `ingestor_disconnects_total{source}` - Ingestor disconnections
- `redis_publish_errors_total{stream}` - Redis publish failures
- `bot_heartbeat_seconds` - Last heartbeat timestamp
- `bot_uptime_seconds` - Bot uptime in seconds
- `stream_lag_seconds{stream,consumer}` - Stream processing lag

### 3. Grafana Dashboard

Import the dashboard:

```bash
# Dashboard file
cat monitoring/grafana/paper_trial_dashboard.json
```

**Dashboard URL:** `http://localhost:3000/dashboards` (if Grafana is running)

**Panels:**
1. Signals Published Total (rate)
2. Publish Latency p95/p50 (with <500ms alert)
3. Circuit Breaker Trips (with alert)
4. Bot Heartbeat & Uptime
5. Stream Lag (with alert)
6. Signals by Symbol (pie chart)
7. Total Signals (24h)
8. Avg Latency (24h)

### 4. Redis Stream Inspection

Check signals in Redis:

```bash
# Connect to Redis
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem

# Get stream length
XLEN signals:paper

# Get latest 10 signals
XREVRANGE signals:paper + - COUNT 10

# Read all fields of latest signal
XREVRANGE signals:paper + - COUNT 1

# Subscribe to new signals (blocking)
XREAD BLOCK 0 STREAMS signals:paper $
```

---

## Signal Contract Verification

### SignalDTO Schema

Every signal published to `signals:paper` contains:

```json
{
  "id": "a1b2c3d4e5f6...",
  "ts": 1730000000000,
  "pair": "BTC-USD",
  "side": "long",
  "entry": 64321.1,
  "sl": 63500.0,
  "tp": 65500.0,
  "strategy": "momentum_v1",
  "confidence": 0.78,
  "mode": "paper"
}
```

### Fields for signals-api/signals-site

✅ **strategy** - Strategy name (e.g., "momentum_v1", "mean_reversion")
✅ **confidence** - Signal confidence [0, 1]
✅ **entry, sl, tp** - Entry, stop loss, take profit prices
✅ **Risk/Reward (RR)** - Calculate: `(tp - entry) / (entry - sl)`

**Example RR Calculation:**
```python
entry = 64321.1
sl = 63500.0
tp = 65500.0

risk = entry - sl  # 821.1
reward = tp - entry  # 1178.9
rr = reward / risk  # 1.44 (1:1.44 RR)
```

### Verify Signal Fields

```bash
# Test signal creation
python -c "
from models.signal_dto import create_signal_dto
import json

signal = create_signal_dto(
    ts_ms=1730000000000,
    pair='BTC-USD',
    side='long',
    entry=64321.1,
    sl=63500.0,
    tp=65500.0,
    strategy='momentum_v1',
    confidence=0.78,
    mode='paper'
)

print(json.dumps(signal.to_dict(), indent=2))
"
```

---

## Performance Validation

### Daily Validation

Run daily to check progress:

```bash
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2025-10-23 \
  --end-date $(date +%Y-%m-%d)
```

### Weekly Validation (Day 7, 14)

```bash
# Day 7 checkpoint
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2025-10-23 \
  --end-date 2025-10-30 \
  --output reports/paper_validation_day7.txt

# Day 14 final
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2025-10-23 \
  --end-date 2025-11-06 \
  --output reports/paper_validation_day14.txt
```

---

## Definition of Done (DoD)

**Must meet ALL criteria:**

### Performance
- ✅ **Profit Factor ≥ 1.5** OR **Win-rate ≥ 60%**
- ✅ **Max Drawdown ≤ 15%**

### Execution
- ✅ **No missed publishes** (redis_publish_errors_total = 0)
- ✅ **Latency p95 < 500ms** (publish_latency_ms p95)

### Reliability
- ✅ **Duration: 14-21 days**
- ✅ **Uptime ≥ 99.5%** (minimal disconnects)

### Validation Commands

```bash
# 1. Check performance metrics
python scripts/validate_paper_trading.py --from-redis

# 2. Check latency p95
curl http://localhost:9108/metrics | grep publish_latency_ms_bucket

# 3. Check missed publishes
curl http://localhost:9108/metrics | grep redis_publish_errors_total

# 4. Check uptime
curl http://localhost:9108/metrics | grep bot_uptime_seconds
```

---

## Alerting Setup

### Prometheus Alerts

Create `prometheus_alerts.yml`:

```yaml
groups:
  - name: crypto_bot_paper_trial
    interval: 60s
    rules:
      - alert: HighPublishLatency
        expr: histogram_quantile(0.95, rate(publish_latency_ms_bucket[5m])) > 500
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Publish latency p95 exceeded 500ms"
          description: "Current p95: {{ $value }}ms"

      - alert: CircuitBreakerTripped
        expr: rate(ingestor_disconnects_total[5m]) > 0.1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Circuit breaker tripped"
          description: "Source: {{ $labels.source }}"

      - alert: RedisPublishErrors
        expr: rate(redis_publish_errors_total[5m]) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Redis publish errors detected"
          description: "Stream: {{ $labels.stream }}"

      - alert: BotHeartbeatMissing
        expr: (time() - bot_heartbeat_seconds) > 120
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Bot heartbeat missing"
          description: "Last heartbeat: {{ $value }}s ago"

      - alert: HighStreamLag
        expr: stream_lag_seconds > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High stream lag detected"
          description: "Stream: {{ $labels.stream }}, Consumer: {{ $labels.consumer }}, Lag: {{ $value }}s"
```

---

## Troubleshooting

### Bot Not Starting

```bash
# Check logs
tail -f logs/paper_trial_*.log

# Verify Redis connection
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem PING

# Check conda environment
conda env list | grep crypto-bot
```

### No Signals Published

```bash
# Check OHLCV cache filling
# Requires ~100 bars = ~8 hours for 5m timeframe
grep "OHLCV cache" logs/paper_trial_*.log

# Check circuit breakers
curl http://localhost:9108/metrics | grep breaker
```

### High Latency

```bash
# Check Redis latency
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem --latency

# Check system resources
docker stats paper-bot  # If using Docker
```

### Metrics Not Available

```bash
# Check metrics server
curl http://localhost:9108/metrics

# Check if port is in use
netstat -an | grep 9108

# Restart with verbose logging
export LOG_LEVEL=DEBUG
python scripts/run_paper_trial.py
```

---

## Go-Live Checklist

After 14-21 days, if DoD is met:

- [ ] All performance criteria passed (PF ≥1.5 OR WR ≥60%, DD ≤15%)
- [ ] Latency p95 < 500ms consistently
- [ ] No missed publishes (redis_publish_errors_total = 0)
- [ ] Uptime ≥ 99.5%
- [ ] Grafana dashboards configured
- [ ] Alerts configured and tested
- [ ] signals-api reading from signals:paper stream
- [ ] signals-site displaying all fields (strategy, confidence, RR, SL/TP)
- [ ] Operations runbook reviewed
- [ ] Team trained on monitoring

**Next Steps:**
1. Review final validation report
2. Get stakeholder approval
3. Set `MODE=live` and deploy to production
4. Monitor closely for first 24-48 hours

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/run_paper_trial.py` | Main paper trial deployment script |
| `scripts/monitor_paper_trial.py` | Real-time monitoring dashboard |
| `docker-compose.yml` | Docker deployment (--profile paper) |
| `monitoring/grafana/paper_trial_dashboard.json` | Grafana dashboard |
| `monitoring/metrics_exporter.py` | Prometheus metrics exporter |
| `streams/publisher.py` | Redis signal publisher |
| `models/signal_dto.py` | Signal schema/contract |
| `scripts/validate_paper_trading.py` | Performance validation |

---

## Support

- **Documentation**: See `PRD.md` for full system architecture
- **Issues**: Create issue at project repo
- **Operations**: See `OPERATIONS_RUNBOOK.md`

---

**Last Updated**: 2025-10-23
**Status**: Ready for 14-21 day trial deployment
