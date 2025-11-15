# Step 11: Paper Trading Trial (E2E) - COMPLETE ✅

**Status:** Ready for 14-21 day deployment
**Date:** 2025-10-23
**Environment:** crypto-bot conda environment
**Redis:** Redis Cloud with TLS

---

## Summary

Complete E2E paper trading trial infrastructure has been implemented with:

✅ **Docker Compose Profile** - `--profile paper` for containerized deployment
✅ **Prometheus Metrics** - `/metrics` endpoint with all required counters
✅ **Grafana Dashboard** - Full monitoring dashboard with alerts
✅ **Monitoring Scripts** - Real-time dashboard and validation tools
✅ **Deployment Guide** - Complete step-by-step instructions
✅ **Signal Contract** - Verified SignalDTO with strategy, confidence, RR, SL/TP

---

## Files Created

### Deployment
| File | Purpose |
|------|---------|
| `docker-compose.yml` | Updated with `paper-bot` service (--profile paper) |
| `.env.paper.example` | Environment configuration template |
| `scripts/run_paper_trial.py` | Main paper trial deployment script |
| `scripts/setup_paper_trial.py` | Interactive setup wizard |

### Monitoring
| File | Purpose |
|------|---------|
| `scripts/monitor_paper_trial.py` | Real-time monitoring dashboard |
| `monitoring/grafana/paper_trial_dashboard.json` | Grafana dashboard definition |
| `monitoring/metrics_exporter.py` | Prometheus metrics (already existed) |

### Documentation
| File | Purpose |
|------|---------|
| `PAPER_TRIAL_E2E_GUIDE.md` | Complete deployment guide |
| `STEP11_PAPER_TRIAL_COMPLETE.md` | This summary document |

---

## Quick Start

### Option 1: Python Direct (Recommended for Initial Testing)

```bash
# 1. Setup
conda activate crypto-bot
python scripts/setup_paper_trial.py

# 2. Deploy
python scripts/run_paper_trial.py

# 3. Monitor (in separate terminal)
python scripts/monitor_paper_trial.py
```

### Option 2: Docker Compose (Recommended for Production)

```bash
# 1. Create .env file
cp .env.paper.example .env.paper
# Edit .env.paper with your Redis URL

# 2. Deploy
docker-compose --profile paper up -d

# 3. Monitor
docker-compose --profile paper logs -f paper-bot
python scripts/monitor_paper_trial.py
```

---

## Metrics Exposed

### Prometheus Endpoint: `http://localhost:9108/metrics`

**Required Counters (from Claude mini-prompt):**
- ✅ `signals_published_total{agent,stream,symbol}` - Total signals published
- ✅ `publish_latency_ms_bucket` - Publish latency histogram (p50, p95, p99)

**Additional Monitoring:**
- ✅ `ingestor_disconnects_total{source}` - WebSocket disconnections
- ✅ `redis_publish_errors_total{stream}` - Redis publish failures
- ✅ `bot_heartbeat_seconds` - Last heartbeat timestamp
- ✅ `bot_uptime_seconds` - Bot uptime since start
- ✅ `stream_lag_seconds{stream,consumer}` - Stream processing lag

---

## Signal Contract (Verified)

### SignalDTO Fields

All signals published to `signals:paper` include:

```json
{
  "id": "a1b2c3d4...",           // Idempotent signal ID
  "ts": 1730000000000,            // Timestamp (ms)
  "pair": "BTC-USD",              // Trading pair
  "side": "long",                 // long | short
  "entry": 64321.1,               // ✅ Entry price
  "sl": 63500.0,                  // ✅ Stop loss
  "tp": 65500.0,                  // ✅ Take profit
  "strategy": "momentum_v1",      // ✅ Strategy name
  "confidence": 0.78,             // ✅ Confidence [0,1]
  "mode": "paper"                 // paper | live
}
```

### Risk/Reward Calculation (for signals-site)

```python
risk = entry - sl       # 821.1
reward = tp - entry     # 1178.9
rr = reward / risk      # 1.44 (1:1.44 RR)
```

**signals-api** can read all fields directly from Redis stream.
**signals-site** can display: strategy, confidence, RR, SL/TP.

---

## Latency Verification

### E2E Latency Target: <500ms (p95)

**Measurement Points:**
1. **Decision → Publish**: Tracked internally in engine
2. **Publish → Redis**: Measured by `publish_latency_ms` metric
3. **Redis → API**: Stream lag measured by `stream_lag_seconds`
4. **API → Site**: Client-side monitoring (external)

**Verification:**
```bash
# Check p95 latency
curl http://localhost:9108/metrics | grep publish_latency_ms_bucket

# Expected output:
# publish_latency_ms_bucket{le="500",...} > 0.95
```

**Alert:** Grafana dashboard alerts if p95 > 500ms for 5+ minutes.

---

## Definition of Done (DoD)

### Performance (from PRD §2)
- [ ] **Profit Factor ≥ 1.5** OR **Win-rate ≥ 60%**
- [ ] **Max Drawdown ≤ 15%**

### Execution
- [ ] **No missed publishes** (redis_publish_errors_total = 0)
- [ ] **Latency p95 < 500ms** (publish_latency_ms)

### Reliability
- [ ] **Duration: 14-21 days**
- [ ] **Uptime ≥ 99.5%**

### Validation Command
```bash
python scripts/validate_paper_trading.py --from-redis
```

---

## Monitoring Dashboards

### 1. Real-Time CLI Dashboard
```bash
python scripts/monitor_paper_trial.py
```

**Shows:**
- Signals published total
- Avg publish latency
- Bot heartbeat & uptime
- Redis connection status
- Latest signals
- DoD status

**Refreshes:** Every 30 seconds

### 2. Grafana Dashboard

**Import:** `monitoring/grafana/paper_trial_dashboard.json`

**Panels:**
1. Signals Published Total (rate chart)
2. Publish Latency p95/p50 (with 500ms alert)
3. Circuit Breaker Trips (with alert)
4. Bot Heartbeat & Uptime (gauges)
5. Stream Lag (with alert)
6. Signals by Symbol (pie chart)
7. Total Signals (24h counter)
8. Avg Latency (24h gauge with thresholds)

**Alerts Configured:**
- High Publish Latency (>500ms for 5m)
- Circuit Breaker Tripped (>0.1/sec for 2m)
- Redis Publish Errors (>0 for 1m)
- Bot Heartbeat Missing (>120s for 2m)
- High Stream Lag (>5s for 5m)

### 3. Prometheus Metrics

**Access:** `http://localhost:9108/metrics`

**Key Queries:**
```promql
# Signals published rate
rate(signals_published_total[5m])

# Publish latency p95
histogram_quantile(0.95, rate(publish_latency_ms_bucket[5m]))

# Breaker trip rate
rate(ingestor_disconnects_total[5m])

# Bot health
time() - bot_heartbeat_seconds
```

---

## Alerting

### Prometheus Alert Rules

File: `prometheus_alerts.yml` (see PAPER_TRIAL_E2E_GUIDE.md)

**Configured Alerts:**
1. HighPublishLatency (p95 > 500ms for 5m) → Warning
2. CircuitBreakerTripped (rate > 0.1 for 2m) → Critical
3. RedisPublishErrors (rate > 0 for 1m) → Critical
4. BotHeartbeatMissing (>120s for 2m) → Critical
5. HighStreamLag (>5s for 5m) → Warning

**Integration:** Connect to PagerDuty, Slack, or email via Alertmanager.

---

## Validation Workflow

### Daily Check (Every Morning)
```bash
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2025-10-23 \
  --end-date $(date +%Y-%m-%d)
```

### Weekly Checkpoints

**Day 7:**
```bash
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2025-10-23 \
  --end-date 2025-10-30 \
  --output reports/paper_validation_day7.txt
```

**Day 14 (Final):**
```bash
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2025-10-23 \
  --end-date 2025-11-06 \
  --output reports/paper_validation_day14.txt
```

### Go-Live Decision

**If ALL DoD criteria pass:** ✅ Ready for LIVE
**If ANY criteria fail:** ❌ Continue paper trading or re-optimize

---

## Redis Cloud Connection

### Connection String (TLS Required)
```bash
export REDIS_URL="redis://default:********@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
```

### CA Certificate
**Path:** `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem`

**Test Connection:**
```bash
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem PING
```

**Expected:** `PONG`

### Stream Keys
- `signals:paper` - Paper mode signals
- `signals:live` - Live mode signals (future)
- `pnl:equity` - PnL aggregation stream
- `trades:closed` - Closed trade events

---

## Troubleshooting

### Bot Not Starting
```bash
# Check logs
tail -f logs/paper_trial_*.log

# Verify Redis
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem PING

# Check conda env
conda activate crypto-bot
```

### No Signals Published
- **Cause:** OHLCV cache filling (needs ~100 bars = 8 hours for 5m)
- **Check:** `grep "OHLCV cache" logs/paper_trial_*.log`
- **Wait:** Continue running for 8+ hours

### High Latency
```bash
# Check Redis latency
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem --latency

# Check system resources
docker stats paper-bot
```

### Metrics Not Available
```bash
# Test endpoint
curl http://localhost:9108/metrics

# Check port
netstat -an | grep 9108

# Restart with debug logging
export LOG_LEVEL=DEBUG
python scripts/run_paper_trial.py
```

---

## Next Steps

1. **Run Setup Wizard:**
   ```bash
   conda activate crypto-bot
   python scripts/setup_paper_trial.py
   ```

2. **Deploy Paper Trial:**
   ```bash
   python scripts/run_paper_trial.py
   ```

3. **Monitor Real-Time:**
   ```bash
   python scripts/monitor_paper_trial.py
   ```

4. **Validate Daily:**
   ```bash
   python scripts/validate_paper_trading.py --from-redis
   ```

5. **After 14-21 Days:**
   - Review final validation report
   - Check DoD criteria
   - If passed → Go LIVE (set MODE=live)

---

## Supporting Documentation

- **Full Guide:** `PAPER_TRIAL_E2E_GUIDE.md`
- **PRD:** `PRD.md` (§11: Paper Trading Trial)
- **Paper Trading:** `PAPER_TRADING_QUICKSTART.md`
- **Operations:** `OPERATIONS_RUNBOOK.md`
- **Validation:** `M1_PAPER_CRITERIA_COMPLETE.md`

---

## Summary Checklist

- ✅ Docker Compose profile created (`--profile paper`)
- ✅ Prometheus metrics endpoint added (`/metrics` on port 9108)
- ✅ Required counters: `signals_published_total`, `publish_latency_ms`
- ✅ Grafana dashboard with alerts configured
- ✅ Monitoring scripts (real-time + validation)
- ✅ Signal contract verified (strategy, confidence, RR, SL/TP)
- ✅ E2E latency tracking (<500ms p95 target)
- ✅ Redis Cloud connection with TLS
- ✅ Deployment guide and runbook
- ✅ Setup wizard for easy deployment

**Status:** ✅ **READY FOR 14-21 DAY PAPER TRIAL**

---

**Last Updated:** 2025-10-23
**Author:** Crypto AI Bot Team
**Environment:** crypto-bot conda, Redis Cloud (TLS)
