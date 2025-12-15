# Week-4 Operations Runbook
## Crypto AI Bot Engine - Production Operations Guide

**Version:** 1.0.0  
**Last Updated:** 2025-01-XX  
**Environment:** crypto-bot conda environment  
**Deployment:** Fly.io (paper mode, 24/7)  
**Redis:** Redis Cloud with TLS

---

## Table of Contents

1. [Quick Reference](#quick-reference)
2. [System Overview](#system-overview)
3. [Daily Operations](#daily-operations)
4. [Monitoring & Health Checks](#monitoring--health-checks)
5. [Reconnection & Stability](#reconnection--stability)
6. [Metrics & Logging](#metrics--logging)
7. [Incident Response](#incident-response)
8. [Maintenance Procedures](#maintenance-procedures)
9. [Troubleshooting](#troubleshooting)

---

## Quick Reference

### Essential Commands

```bash
# Activate conda environment
conda activate crypto-bot

# Start engine (paper mode)
python main_engine.py

# Check health endpoint
curl http://localhost:8080/health

# View Redis metrics
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.hgetall('engine:summary_metrics'))"

# Check latest signals
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.xrevrange('signals:paper:BTC/USD', count=5))"

# Emergency stop (if needed)
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true
```

### Critical Redis Keys

| Key | Type | Purpose | TTL |
|-----|------|---------|-----|
| `engine:summary_metrics` | Hash | Investor-facing metrics (ROI, win rate, etc.) | 7 days |
| `engine:heartbeat` | String | Engine heartbeat (ISO timestamp) | 60s |
| `engine:status` | String | Engine status JSON | 60s |
| `signals:paper:<PAIR>` | Stream | Paper trading signals per pair | 7 days |
| `kraken:metrics` | Stream | WebSocket operational metrics | 7 days |

---

## System Overview

### Architecture

```
Kraken WebSocket → Engine → Redis Streams → signals-api → signals-site
                              ↓
                    engine:summary_metrics (investor metrics)
```

### Components

1. **Main Engine** (`main_engine.py`): Entry point, task supervision, health publishing
2. **Kraken WebSocket** (`utils/kraken_ws.py`): Market data ingestion with reconnection logic
3. **Signal Generation**: Multi-agent AI engine producing trading signals
4. **Metrics Publisher**: Publishes to `engine:summary_metrics` for investor dashboard
5. **Health Publisher**: Publishes heartbeat and status to Redis

### Mode

- **Current Mode**: Paper (24/7 operation)
- **Stream Pattern**: `signals:paper:<PAIR>` (e.g., `signals:paper:BTC/USD`)
- **Metrics Key**: `engine:summary_metrics` (Redis Hash)

---

## Daily Operations

### Morning Checklist (Before Market Open)

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Check engine health
curl http://localhost:8080/health | jq

# 3. Verify Redis connection
python -c "import redis; r=redis.from_url('$REDIS_URL'); print('Redis:', 'OK' if r.ping() else 'FAIL')"

# 4. Check latest heartbeat
python -c "import redis; r=redis.from_url('$REDIS_URL'); print('Heartbeat:', r.get('engine:heartbeat'))"

# 5. Verify metrics are updating
python -c "import redis; r=redis.from_url('$REDIS_URL'); m=r.hgetall('engine:summary_metrics'); print('Metrics timestamp:', m.get('timestamp', 'MISSING'))"

# 6. Check for recent signals
python -c "import redis; r=redis.from_url('$REDIS_URL'); sigs=r.xrevrange('signals:paper:BTC/USD', count=1); print('Latest signal:', sigs[0] if sigs else 'NONE')"
```

**Expected Results:**
- Health check: `{"status": "healthy", ...}`
- Redis: `OK`
- Heartbeat: Recent timestamp (< 60s old)
- Metrics timestamp: Recent (< 1 hour old)
- Latest signal: Present (< 10 min old during market hours)

### Evening Checklist

```bash
# 1. Review daily metrics
python -c "import redis; r=redis.from_url('$REDIS_URL'); m=r.hgetall('engine:summary_metrics'); print('Signals today:', m.get('signals_per_day', 'N/A')); print('ROI 30d:', m.get('roi_30d', 'N/A'), '%')"

# 2. Check error logs
tail -n 100 logs/crypto_ai_bot.log | grep -i "error\|warning" | tail -20

# 3. Verify uptime
curl http://localhost:8080/health | jq '.uptime_seconds' | awk '{print "Uptime:", $1/3600, "hours"}'
```

---

## Monitoring & Health Checks

### Health Endpoint

**URL:** `http://localhost:8080/health` (or Fly.io app URL)

**Response Format:**
```json
{
  "status": "healthy|degraded|unhealthy",
  "timestamp": "2025-01-XXT...",
  "uptime_seconds": 12345,
  "redis": {
    "connected": true,
    "latency_ms": 12.5
  },
  "environment": "paper",
  "version": "0.5.0"
}
```

**Status Codes:**
- `200 OK`: Healthy or degraded
- `503 Service Unavailable`: Unhealthy

**Health Criteria:**
- **Healthy**: Redis connected, heartbeat fresh (< 60s), signals recent (< 10 min)
- **Degraded**: Redis connected but signals stale (> 10 min)
- **Unhealthy**: Redis disconnected or heartbeat stale (> 60s)

### Prometheus Metrics

**Endpoint:** `http://localhost:8000/metrics` (if enabled)

**Key Metrics:**
- `kraken_ws_reconnects_total`: Total reconnection attempts
- `signals_published_total{pair, strategy}`: Signals published per pair/strategy
- `signal_generation_latency_ms`: Signal generation latency histogram

### Redis Metrics

**Investor Metrics** (`engine:summary_metrics`):
```bash
# View all metrics
redis-cli -u $REDIS_URL HGETALL engine:summary_metrics

# Key fields:
# - roi_30d: 30-day ROI percentage
# - win_rate_pct: Win rate percentage
# - signals_per_day: Average signals per day
# - sharpe_ratio: Sharpe ratio
# - max_drawdown_pct: Maximum drawdown percentage
```

**Operational Metrics** (`engine:heartbeat`, `engine:status`):
```bash
# Check heartbeat freshness
redis-cli -u $REDIS_URL GET engine:heartbeat

# Check engine status
redis-cli -u $REDIS_URL GET engine:status | jq
```

---

## Reconnection & Stability

### WebSocket Reconnection Logic

The engine implements PRD-001 compliant reconnection:

1. **Exponential Backoff**: Starts at 1s, doubles each attempt, max 60s
2. **Jitter**: ±20% randomization to prevent thundering herd
3. **Max Retries**: 10 attempts before marking unhealthy
4. **Automatic Resubscription**: Re-subscribes to all channels on reconnect

**Configuration** (via environment):
- `WEBSOCKET_RECONNECT_DELAY`: Initial delay (default: 1s)
- `WEBSOCKET_MAX_RETRIES`: Max attempts (default: 10)
- `WEBSOCKET_PING_INTERVAL`: Ping interval (default: 30s)

### Connection Health Tracking

The engine tracks:
- Connection state: `CONNECTED`, `DISCONNECTED`, `RECONNECTING`
- Reconnection attempts: Per-pair and total
- Downtime: Time spent disconnected
- Last successful connection: Timestamp

**Monitoring:**
```bash
# Check reconnection count (via Prometheus if enabled)
curl http://localhost:8000/metrics | grep kraken_ws_reconnects_total

# Check connection state (via Redis if published)
redis-cli -u $REDIS_URL HGETALL kraken:status
```

### Graceful Degradation

On failures:
- **Transient Redis failure**: Queue publishes in memory (max 1000), retry every 5s
- **Transient Kraken failure**: Serve cached data, mark stale after 5 min
- **Persistent failure (> 5 min)**: Mark unhealthy, trigger alert

---

## Metrics & Logging

### Investor-Ready Metrics

**Key:** `engine:summary_metrics` (Redis Hash)

**Fields:**
- `mode`: "paper" or "live"
- `timestamp`: ISO timestamp of last update
- `signals_per_day`: Average signals per day
- `roi_30d`: 30-day ROI percentage
- `win_rate_pct`: Win rate percentage
- `sharpe_ratio`: Sharpe ratio
- `max_drawdown_pct`: Maximum drawdown percentage
- `total_trades`: Total trades in period
- `trading_pairs`: Comma-separated list of pairs
- `performance_30d_json`: Detailed 30-day performance (JSON)
- `performance_90d_json`: Detailed 90-day performance (JSON)
- `performance_365d_json`: Detailed 365-day performance (JSON)

**Update Frequency:** Hourly (via `analysis/metrics_summary.py`)

**Verification:**
```bash
# Check metrics freshness
python -c "
import redis
from datetime import datetime
r = redis.from_url('$REDIS_URL')
ts = r.hget('engine:summary_metrics', 'timestamp')
if ts:
    dt = datetime.fromisoformat(ts.decode())
    age = (datetime.now() - dt).total_seconds() / 3600
    print(f'Metrics age: {age:.1f} hours')
else:
    print('Metrics timestamp missing')
"
```

### Structured Logging

**Format:** JSON (when `LOG_FORMAT=json`) or structured text

**Log Levels:**
- `DEBUG`: Detailed debugging (development only)
- `INFO`: Normal operations, signal generation
- `WARNING`: Reconnections, circuit breaker trips
- `ERROR`: Failures, exceptions
- `CRITICAL`: System failures, max retries exceeded

**Log Locations:**
- `stdout`: Fly.io logs (primary)
- `logs/crypto_ai_bot.log`: File logs (if `LOG_TO_FILE=true`)

**Key Log Messages:**
- `"Kraken WS connected"`: Successful connection
- `"Kraken WS reconnect triggered"`: Reconnection started
- `"Signal published"`: Signal generated and published
- `"Max reconnection attempts reached"`: Critical failure

**Log Rotation:**
- Max size: 100MB (configurable via `LOG_MAX_SIZE`)
- Retention: 7 days (configurable via `LOG_MAX_FILES`)

---

## Incident Response

### WebSocket Disconnection

**Symptoms:**
- Health check shows `"status": "unhealthy"`
- No new signals
- Logs show `"Kraken WS reconnect triggered"`

**Investigation:**
```bash
# 1. Check reconnection attempts
tail -n 50 logs/crypto_ai_bot.log | grep -i "reconnect"

# 2. Check connection state
curl http://localhost:8080/health | jq '.redis'

# 3. Verify Kraken service status
curl https://status.kraken.com/api/v2/status.json | jq
```

**Resolution:**
- **Automatic**: Engine will reconnect automatically (up to 10 attempts)
- **Manual**: If max retries exceeded, restart engine:
  ```bash
  # On Fly.io
  fly ssh console -a crypto-bot-engine
  # Then restart the process
  ```

### Redis Connection Failure

**Symptoms:**
- Health check shows Redis disconnected
- Metrics not updating
- Signals not publishing

**Investigation:**
```bash
# 1. Test Redis connection
python -c "import redis; r=redis.from_url('$REDIS_URL'); print('PING:', r.ping())"

# 2. Check Redis Cloud status
# Visit: https://redis.com/status

# 3. Verify certificate
ls -la config/certs/redis_ca.pem
```

**Resolution:**
- **Automatic**: Engine will retry Redis connection
- **Manual**: If persistent, verify:
  - Redis Cloud service status
  - Certificate validity
  - Network connectivity

### Stale Signals

**Symptoms:**
- Health check shows `"status": "degraded"`
- No signals in last 10+ minutes
- Metrics timestamp old

**Investigation:**
```bash
# 1. Check latest signal
python -c "
import redis
r = redis.from_url('$REDIS_URL')
sigs = r.xrevrange('signals:paper:BTC/USD', count=1)
if sigs:
    print('Latest signal:', sigs[0])
else:
    print('No signals found')
"

# 2. Check WebSocket connection
tail -n 20 logs/crypto_ai_bot.log | grep -i "kraken\|websocket"

# 3. Check for errors
tail -n 50 logs/crypto_ai_bot.log | grep -i "error"
```

**Resolution:**
- Check if market is active (crypto is 24/7, but low volatility periods may have fewer signals)
- Verify WebSocket connection is active
- Check for circuit breaker trips

### Metrics Not Updating

**Symptoms:**
- `engine:summary_metrics` timestamp stale (> 1 hour)
- Dashboard shows old data

**Investigation:**
```bash
# 1. Check metrics timestamp
python -c "
import redis
from datetime import datetime
r = redis.from_url('$REDIS_URL')
ts = r.hget('engine:summary_metrics', 'timestamp')
print('Timestamp:', ts.decode() if ts else 'MISSING')
"

# 2. Check if metrics calculator is running
ps aux | grep metrics_summary

# 3. Check for errors in metrics calculation
tail -n 50 logs/crypto_ai_bot.log | grep -i "metrics\|summary"
```

**Resolution:**
- Metrics are calculated hourly; wait for next cycle
- If stale > 2 hours, manually trigger:
  ```bash
  python -m analysis.metrics_summary
  ```

---

## Maintenance Procedures

### Restart Engine

**Graceful Restart:**
```bash
# On Fly.io
fly ssh console -a crypto-bot-engine
# Send SIGTERM to main process
kill -TERM <pid>
# Wait for graceful shutdown (30s timeout)
# Process will restart automatically
```

**Force Restart:**
```bash
# On Fly.io
fly apps restart crypto-bot-engine
```

### Update Configuration

**Environment Variables:**
```bash
# On Fly.io
fly secrets set LOG_LEVEL=INFO
fly secrets set WEBSOCKET_MAX_RETRIES=10
# Restart required for changes to take effect
fly apps restart crypto-bot-engine
```

### Deploy New Version

```bash
# 1. Test locally
conda activate crypto-bot
python main_engine.py --health-only

# 2. Deploy to Fly.io
fly deploy

# 3. Verify deployment
fly status
fly logs

# 4. Check health
curl https://crypto-bot-engine.fly.dev/health | jq
```

---

## Troubleshooting

### Engine Won't Start

**Check:**
1. Environment variables set correctly
2. Redis connection string valid
3. Certificate file exists
4. Port 8080 available

**Debug:**
```bash
# Run with verbose logging
LOG_LEVEL=DEBUG python main_engine.py

# Check for import errors
python -c "import main_engine; print('OK')"
```

### High Reconnection Rate

**Symptoms:**
- Frequent `"Kraken WS reconnect triggered"` messages
- `kraken_ws_reconnects_total` increasing rapidly

**Possible Causes:**
- Network instability
- Kraken service issues
- Firewall/proxy blocking WebSocket

**Investigation:**
```bash
# Check reconnection frequency
tail -n 100 logs/crypto_ai_bot.log | grep -c "reconnect"

# Check network connectivity
ping ws.kraken.com

# Check Kraken status
curl https://status.kraken.com/api/v2/status.json | jq
```

### Memory Leaks

**Symptoms:**
- Memory usage increasing over time
- Process killed by OOM killer

**Investigation:**
```bash
# Monitor memory usage
watch -n 5 'ps aux | grep main_engine | awk "{print \$6/1024 \" MB\"}"'

# Check for memory leaks in logs
grep -i "memory\|leak\|oom" logs/crypto_ai_bot.log
```

**Resolution:**
- Restart engine periodically (daily/weekly)
- Review code for unbounded data structures
- Check Redis stream sizes (MAXLEN should prevent unbounded growth)

---

## Emergency Contacts

| Role | Contact | Responsibility |
|------|---------|----------------|
| On-call Engineer | [TBD] | System operations, incident response |
| DevOps | [TBD] | Infrastructure, Redis, Fly.io |
| Trading Lead | [TBD] | Trading decisions, risk management |

---

## Appendix: Environment Variables

**Required:**
- `ENGINE_MODE`: "paper" or "live"
- `REDIS_URL`: Redis Cloud connection string (rediss://...)
- `REDIS_CA_CERT`: Path to CA certificate

**Optional:**
- `LOG_LEVEL`: "DEBUG", "INFO", "WARNING", "ERROR" (default: INFO)
- `LOG_FORMAT`: "json" or text format string
- `WEBSOCKET_RECONNECT_DELAY`: Initial reconnect delay (default: 1)
- `WEBSOCKET_MAX_RETRIES`: Max reconnection attempts (default: 10)
- `HEARTBEAT_INTERVAL_SEC`: Heartbeat interval (default: 30)
- `TRADING_PAIRS`: Comma-separated pairs (default: "BTC/USD,ETH/USD,SOL/USD")

---

**Document Status:** Active  
**Next Review:** After Week-4 completion  
**Owner:** Engineering Team

