# B1.3 - Metrics Monitoring & Incident Recovery

**Last Updated**: 2025-11-01
**Status**: Production Ready
**Version**: 1.0

---

## Table of Contents

1. [Metrics Overview](#metrics-overview)
2. [Accessing Metrics](#accessing-metrics)
3. [Key Performance Indicators](#key-performance-indicators)
4. [Alert Thresholds](#alert-thresholds)
5. [How to Read Bot Metrics](#how-to-read-bot-metrics)
6. [Incident Recovery Procedures](#incident-recovery-procedures)
7. [Troubleshooting by Metric](#troubleshooting-by-metric)
8. [Prometheus Queries](#prometheus-queries)

---

## Metrics Overview

The crypto-ai-bot exposes Prometheus-compatible metrics on port **9108** (configurable via `METRICS_PORT` env var).

### B1.3 Required Metrics

| Metric | Type | Description | Labels | SLO |
|--------|------|-------------|--------|-----|
| `ingest_latency_ms` | Histogram | Latency from Kraken event to processing | `source`, `symbol` | p95 ≤ 50ms |
| `signals_published_total` | Counter | Total signals published | `agent`, `stream`, `symbol` | - |
| `errors_total` | Counter | Total errors by type | `component`, `error_type` | < 5/min steady state |
| `reconnects_total` | Counter | Total reconnection attempts | `source`, `reason` | < 1/hour |
| `end_to_end_latency_ms` | Histogram | Market data → signal publish latency | `agent`, `symbol` | p95 ≤ 500ms |

### Additional System Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `publish_latency_ms` | Histogram | Redis publish latency |
| `ingestor_disconnects_total` | Counter | Ingestor disconnections |
| `redis_publish_errors_total` | Counter | Redis publish failures |
| `bot_heartbeat_seconds` | Gauge | Last heartbeat timestamp |
| `stream_lag_seconds` | Gauge | Redis stream lag |
| `bot_uptime_seconds` | Gauge | Bot uptime |

---

## Accessing Metrics

### 1. Prometheus Endpoint

**URL**: `http://localhost:9108/metrics`

```bash
# View all metrics
curl http://localhost:9108/metrics

# Filter specific metric
curl http://localhost:9108/metrics | grep ingest_latency

# Check if metrics server is running
curl -I http://localhost:9108/metrics
```

### 2. Start Metrics Server

Metrics server should start automatically with the main trading system. To start manually:

```python
# In your main application
from monitoring.metrics_exporter import start_metrics_server, heartbeat

# Start server on port 9108
start_metrics_server()

# Update heartbeat periodically (every 30s recommended)
import asyncio

async def metrics_heartbeat():
    while True:
        heartbeat()
        await asyncio.sleep(30)

asyncio.create_task(metrics_heartbeat())
```

### 3. Prometheus Configuration

Add to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'crypto-ai-bot'
    static_configs:
      - targets: ['localhost:9108']
    scrape_interval: 15s
    scrape_timeout: 10s
```

### 4. Grafana Dashboard

Import dashboard ID `14467` or create custom dashboard with queries from [Prometheus Queries](#prometheus-queries) section.

---

## Key Performance Indicators

### Normal Operating Ranges

| Metric | Healthy Range | Warning | Critical |
|--------|--------------|---------|----------|
| **Ingest Latency (p95)** | < 20ms | 20-50ms | > 50ms |
| **End-to-End Latency (p95)** | < 200ms | 200-500ms | > 500ms |
| **Signals/Min** | 5-50 | 1-5 or 50-100 | < 1 or > 100 |
| **Errors/Min** | 0-2 | 2-5 | > 5 |
| **Reconnects/Hour** | 0 | 1-2 | > 2 |
| **Stream Lag** | < 1s | 1-5s | > 5s |
| **Heartbeat Age** | < 60s | 60-120s | > 120s |

### System Health Scoring

**Overall Health = (Latency Score × 0.4) + (Error Score × 0.3) + (Availability Score × 0.3)**

- **Latency Score**:
  - 100: p95 < 100ms
  - 75: p95 100-200ms
  - 50: p95 200-500ms
  - 0: p95 > 500ms

- **Error Score**:
  - 100: 0 errors/min
  - 75: 1-2 errors/min
  - 50: 3-5 errors/min
  - 0: > 5 errors/min

- **Availability Score**:
  - 100: 0 reconnects, heartbeat fresh
  - 75: 1 reconnect/hour, heartbeat < 60s
  - 50: 2 reconnects/hour, heartbeat < 120s
  - 0: > 2 reconnects/hour or heartbeat > 120s

**Health Grades**:
- **Excellent**: Score ≥ 90
- **Good**: Score 75-89
- **Fair**: Score 50-74
- **Poor**: Score < 50 → **Take action**

---

## How to Read Bot Metrics

### 1. Check Overall System Health

```bash
# Quick health check
curl http://localhost:9108/metrics | grep -E "(bot_heartbeat|bot_uptime|errors_total)"
```

**What to look for**:
- `bot_heartbeat_seconds`: Should be within last 60 seconds
- `bot_uptime_seconds`: System uptime
- `errors_total`: Should be low (< 5/min)

### 2. Monitor Ingest Latency

```bash
# Check ingest latency percentiles
curl http://localhost:9108/metrics | grep ingest_latency_ms_bucket
```

**Example output**:
```
ingest_latency_ms_bucket{source="kraken",symbol="BTC/USD",le="5"} 234
ingest_latency_ms_bucket{source="kraken",symbol="BTC/USD",le="10"} 567
ingest_latency_ms_bucket{source="kraken",symbol="BTC/USD",le="20"} 892
ingest_latency_ms_bucket{source="kraken",symbol="BTC/USD",le="50"} 950
ingest_latency_ms_bucket{source="kraken",symbol="BTC/USD",le="+Inf"} 1000
```

**Interpretation**:
- Most observations (950/1000) are under 50ms → **Healthy**
- If most observations are in higher buckets → **Investigate network or processing delays**

**Prometheus Query for p95**:
```promql
histogram_quantile(0.95,
  rate(ingest_latency_ms_bucket[5m])
)
```

### 3. Track Signal Publishing Rate

```bash
# Check signals published
curl http://localhost:9108/metrics | grep signals_published_total
```

**Example output**:
```
signals_published_total{agent="scalper",stream="ticker",symbol="BTC/USD"} 1250
signals_published_total{agent="bar_reaction",stream="signals",symbol="ETH/USD"} 450
```

**Interpretation**:
- Steady increase → System operating normally
- Sudden stop → **Check agent health and market data flow**
- Spike → **Verify signal quality, may indicate false positives**

### 4. Monitor Error Rates

```bash
# Check error counts
curl http://localhost:9108/metrics | grep errors_total
```

**Example output**:
```
errors_total{component="kraken_ws",error_type="connection_timeout"} 2
errors_total{component="signal_processor",error_type="validation_error"} 0
errors_total{component="redis",error_type="publish_failed"} 1
```

**Interpretation**:
- `connection_timeout`: Transient → OK if < 5/hour
- `validation_error`: **Critical** → Check signal schema compliance
- `publish_failed`: **High priority** → Check Redis connectivity

### 5. Track Reconnection Events

```bash
# Check reconnects
curl http://localhost:9108/metrics | grep reconnects_total
```

**Example output**:
```
reconnects_total{source="kraken",reason="ping_timeout"} 3
reconnects_total{source="kraken",reason="connection_lost"} 1
reconnects_total{source="kraken",reason="auth_failed"} 0
```

**Interpretation**:
- `ping_timeout`: Normal if < 1/hour
- `connection_lost`: Investigate if > 2/day
- `auth_failed`: **Critical** → Check API credentials immediately

### 6. Measure End-to-End Latency

```bash
# Check end-to-end latency
curl http://localhost:9108/metrics | grep end_to_end_latency_ms_bucket
```

**Prometheus Query for p95**:
```promql
histogram_quantile(0.95,
  rate(end_to_end_latency_ms_bucket[5m])
)
```

**Acceptable Ranges**:
- p50: < 100ms
- p95: < 500ms
- p99: < 1000ms

**If latency is high**:
1. Check `ingest_latency_ms` - is data ingest slow?
2. Check `publish_latency_ms` - is Redis publish slow?
3. Check CPU/memory - is system under load?

---

## Alert Thresholds

### Critical Alerts (Page Immediately)

```yaml
- alert: HighEndToEndLatency
  expr: histogram_quantile(0.95, rate(end_to_end_latency_ms_bucket[5m])) > 500
  for: 5m
  annotations:
    summary: "p95 end-to-end latency > 500ms"
    action: "Check system load, Redis latency, network"

- alert: HighErrorRate
  expr: rate(errors_total[5m]) > 5
  for: 5m
  annotations:
    summary: "Error rate > 5/min"
    action: "Check logs, component health"

- alert: FrequentReconnects
  expr: rate(reconnects_total[1h]) > 2
  for: 10m
  annotations:
    summary: "Reconnects > 2/hour"
    action: "Check network stability, exchange status"

- alert: BotHeartbeatStale
  expr: (time() - bot_heartbeat_seconds) > 120
  for: 2m
  annotations:
    summary: "Bot heartbeat > 120s old"
    action: "Bot may be hung or crashed - restart immediately"

- alert: HighStreamLag
  expr: stream_lag_seconds > 5
  for: 5m
  annotations:
    summary: "Redis stream lag > 5s"
    action: "Check Redis performance, consumer processing"
```

### Warning Alerts (Investigate Soon)

```yaml
- alert: ModerateLatency
  expr: histogram_quantile(0.95, rate(ingest_latency_ms_bucket[5m])) > 50
  for: 10m
  annotations:
    summary: "p95 ingest latency > 50ms"

- alert: LowSignalRate
  expr: rate(signals_published_total[5m]) < 0.1
  for: 15m
  annotations:
    summary: "Signal rate < 1/min"

- alert: OccasionalErrors
  expr: rate(errors_total[5m]) > 2
  for: 10m
  annotations:
    summary: "Error rate 2-5/min"
```

---

## Incident Recovery Procedures

### Incident Classification

| Severity | Examples | Response Time | Actions |
|----------|----------|---------------|---------|
| **P0 (Critical)** | Bot crashed, heartbeat dead, signals stopped | < 5 minutes | Emergency stop, page on-call, investigate |
| **P1 (High)** | High error rate (> 5/min), frequent reconnects | < 15 minutes | Check logs, restart if needed |
| **P2 (Medium)** | High latency (> 500ms), low signal rate | < 1 hour | Monitor, tune if persists |
| **P3 (Low)** | Occasional errors, moderate latency | < 4 hours | Log for future analysis |

### P0: Bot Crashed / Heartbeat Dead

**Symptoms**:
- `bot_heartbeat_seconds` > 120s old
- No new metrics updates
- Signals stopped publishing

**Recovery Steps**:

1. **Immediate - Activate Kill Switch** (< 60 seconds)
   ```bash
   redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true
   ```

2. **Check Process Status**
   ```bash
   # Check if process is running
   ps aux | grep python | grep crypto_ai_bot

   # Check last error in logs
   tail -50 logs/bot.log | grep -i error
   ```

3. **Attempt Graceful Restart**
   ```bash
   # Stop current process
   pkill -f "python.*crypto_ai_bot"

   # Wait for cleanup
   sleep 5

   # Check Redis state
   redis-cli -u $REDIS_URL PING

   # Restart bot
   python scripts/start_trading_system.py --mode PAPER
   ```

4. **Verify Recovery**
   ```bash
   # Check heartbeat is fresh
   curl http://localhost:9108/metrics | grep bot_heartbeat

   # Check signals resuming
   python scripts/monitor_redis_streams.py --tail
   ```

5. **Root Cause Analysis**
   - Check system logs: `tail -100 logs/bot.log`
   - Check system resources: `htop`, `free -h`
   - Check Redis: `redis-cli -u $REDIS_URL INFO`
   - Document in `INCIDENTS_LOG.md`

### P1: High Error Rate

**Symptoms**:
- `errors_total` increasing rapidly (> 5/min)
- Multiple error types appearing

**Recovery Steps**:

1. **Identify Error Source** (< 2 minutes)
   ```bash
   # Check error breakdown
   curl http://localhost:9108/metrics | grep errors_total | sort -t'=' -k2 -n

   # Check recent logs
   tail -50 logs/bot.log | grep ERROR
   ```

2. **Component-Specific Actions**:

   **Kraken WebSocket Errors** (`component="kraken_ws"`):
   ```bash
   # Check reconnect count
   curl http://localhost:9108/metrics | grep reconnects_total

   # If > 3 reconnects in 5 min, restart WS connection
   redis-cli -u $REDIS_URL PUBLISH kraken:control "reconnect"
   ```

   **Signal Processor Errors** (`component="signal_processor"`):
   ```bash
   # Check validation errors
   grep "validation_error" logs/bot.log | tail -20

   # If schema errors, verify PRD-001 compliance
   python scripts/validate_prd_compliance.py
   ```

   **Redis Errors** (`component="redis"`):
   ```bash
   # Test Redis connectivity
   redis-cli -u $REDIS_URL PING

   # Check Redis memory
   redis-cli -u $REDIS_URL INFO memory

   # If memory full, flush old streams
   redis-cli -u $REDIS_URL XTRIM signals:priority MAXLEN 10000
   ```

3. **Monitor Recovery**
   ```bash
   # Watch error rate decrease
   watch -n 5 'curl -s http://localhost:9108/metrics | grep errors_total'
   ```

### P1: Frequent Reconnects

**Symptoms**:
- `reconnects_total` > 2/hour
- `ingestor_disconnects_total` increasing

**Recovery Steps**:

1. **Check External Status** (< 1 minute)
   ```bash
   # Check Kraken status
   curl https://status.kraken.com/api/v2/status.json

   # Check network connectivity
   ping api.kraken.com
   ```

2. **Analyze Reconnect Reasons**
   ```bash
   curl http://localhost:9108/metrics | grep reconnects_total
   ```

   **By Reason**:
   - `ping_timeout`: Network latency → Check VPN/ISP
   - `connection_lost`: Unstable connection → Restart network
   - `auth_failed`: Credentials issue → Check API keys
   - `rate_limit`: Too many requests → Increase throttling

3. **Network Troubleshooting**
   ```bash
   # Check network quality
   mtr api.kraken.com

   # Check DNS
   nslookup api.kraken.com

   # Test WebSocket connection
   python -c "import websocket; websocket.enableTrace(True); ws = websocket.create_connection('wss://ws.kraken.com'); print(ws.recv()); ws.close()"
   ```

4. **If Network is Unstable**
   ```bash
   # Increase reconnect delay
   redis-cli -u $REDIS_URL SET kraken:config:reconnect_delay 10

   # Enable connection keepalive
   redis-cli -u $REDIS_URL SET kraken:config:keepalive_enabled true
   ```

### P2: High Latency

**Symptoms**:
- `end_to_end_latency_ms` p95 > 500ms
- `ingest_latency_ms` p95 > 50ms

**Recovery Steps**:

1. **Identify Bottleneck** (< 5 minutes)
   ```bash
   # Check each stage
   curl http://localhost:9108/metrics | grep -E "(ingest_latency|publish_latency|end_to_end)" > /tmp/latency.txt

   # Analyze percentiles
   cat /tmp/latency.txt
   ```

2. **If Ingest Latency is High**:
   ```bash
   # Check network latency to Kraken
   ping -c 10 api.kraken.com

   # Check system CPU
   top -n 1 | head -20

   # Reduce subscription load if needed
   redis-cli -u $REDIS_URL SET kraken:subscriptions:limit 5
   ```

3. **If Publish Latency is High**:
   ```bash
   # Check Redis latency
   redis-cli -u $REDIS_URL --latency

   # Check Redis slow log
   redis-cli -u $REDIS_URL SLOWLOG GET 10

   # Check stream sizes
   redis-cli -u $REDIS_URL XLEN signals:priority
   ```

4. **System-Level Optimization**:
   ```bash
   # Check memory
   free -h

   # Check disk I/O
   iostat -x 1 5

   # Restart bot if memory leak suspected
   python scripts/start_trading_system.py --restart
   ```

### P3: Occasional Errors

**Symptoms**:
- `errors_total` 1-2/min
- Isolated error types

**Actions**:
- Log errors: `tail -f logs/bot.log | grep ERROR > errors.log`
- Monitor trend: Check if error rate is increasing
- Schedule investigation during next maintenance window
- Document in `MAINTENANCE_LOG.md`

---

## Troubleshooting by Metric

### `ingest_latency_ms` High

**Possible Causes**:
1. Network latency to Kraken
2. CPU overload
3. JSON parsing bottleneck
4. Too many subscriptions

**Diagnostic Steps**:
```bash
# 1. Check network
ping -c 20 api.kraken.com
traceroute api.kraken.com

# 2. Check CPU
top -n 1 | grep python

# 3. Check subscription count
redis-cli -u $REDIS_URL GET kraken:active_subscriptions

# 4. Profile ingest code
python -m cProfile -s cumtime utils/kraken_ws.py
```

**Solutions**:
- Reduce subscriptions
- Optimize JSON parsing (use `ujson`)
- Scale horizontally (multiple ingest processes)
- Use faster network connection

### `signals_published_total` Not Increasing

**Possible Causes**:
1. No market data arriving
2. Agent not generating signals
3. Signal validation failing
4. Redis publish errors

**Diagnostic Steps**:
```bash
# 1. Check ingest
python scripts/monitor_redis_streams.py --stream raw_feed --tail

# 2. Check agent health
curl http://localhost:9108/metrics | grep bot_heartbeat

# 3. Check validation errors
grep "validation" logs/bot.log | tail -20

# 4. Check Redis errors
curl http://localhost:9108/metrics | grep redis_publish_errors
```

**Solutions**:
- Restart ingest pipeline
- Check agent configuration
- Fix signal schema issues
- Verify Redis connectivity

### `errors_total` Increasing

See [P1: High Error Rate](#p1-high-error-rate) section above.

### `reconnects_total` Increasing

See [P1: Frequent Reconnects](#p1-frequent-reconnects) section above.

### `stream_lag_seconds` High

**Possible Causes**:
1. Consumer processing too slow
2. High message rate
3. Consumer not running
4. CPU/memory bottleneck

**Diagnostic Steps**:
```bash
# 1. Check consumer status
ps aux | grep consumer

# 2. Check stream length
redis-cli -u $REDIS_URL XLEN signals:priority

# 3. Check consumer group lag
redis-cli -u $REDIS_URL XINFO GROUPS signals:priority

# 4. Check system resources
htop
```

**Solutions**:
- Scale consumers horizontally
- Optimize consumer processing
- Trim old messages: `XTRIM signals:priority MAXLEN 10000`
- Increase consumer parallelism

---

## Prometheus Queries

### Latency Queries

```promql
# p50 ingest latency
histogram_quantile(0.50, rate(ingest_latency_ms_bucket[5m]))

# p95 ingest latency
histogram_quantile(0.95, rate(ingest_latency_ms_bucket[5m]))

# p99 ingest latency
histogram_quantile(0.99, rate(ingest_latency_ms_bucket[5m]))

# p95 end-to-end latency by agent
histogram_quantile(0.95,
  rate(end_to_end_latency_ms_bucket[5m])
) by (agent)

# p95 publish latency
histogram_quantile(0.95, rate(publish_latency_ms_bucket[5m]))
```

### Rate Queries

```promql
# Signals published per second
rate(signals_published_total[1m])

# Signals published per second by agent
rate(signals_published_total[1m]) by (agent)

# Error rate per minute
rate(errors_total[5m]) * 60

# Reconnect rate per hour
rate(reconnects_total[1h]) * 3600

# Redis publish error rate
rate(redis_publish_errors_total[5m])
```

### Availability Queries

```promql
# Bot uptime (hours)
bot_uptime_seconds / 3600

# Time since last heartbeat
time() - bot_heartbeat_seconds

# Stream lag
stream_lag_seconds

# Bot is alive (1 = alive, 0 = dead)
(time() - bot_heartbeat_seconds) < 120
```

### Alerting Queries

```promql
# SLO violation: p95 latency > 500ms
histogram_quantile(0.95, rate(end_to_end_latency_ms_bucket[5m])) > 500

# Error rate violation: > 5 errors/min
rate(errors_total[5m]) * 60 > 5

# Reconnect rate violation: > 2/hour
rate(reconnects_total[1h]) * 3600 > 2

# Heartbeat stale: > 2 minutes
(time() - bot_heartbeat_seconds) > 120

# Stream lag critical: > 5 seconds
stream_lag_seconds > 5
```

---

## Grafana Dashboard Example

### Panel 1: System Overview

```json
{
  "title": "System Health",
  "targets": [
    {
      "expr": "(time() - bot_heartbeat_seconds) < 120",
      "legendFormat": "Bot Alive"
    },
    {
      "expr": "rate(errors_total[5m]) * 60",
      "legendFormat": "Errors/Min"
    },
    {
      "expr": "rate(signals_published_total[1m])",
      "legendFormat": "Signals/Sec"
    }
  ]
}
```

### Panel 2: Latency Distribution

```json
{
  "title": "End-to-End Latency Percentiles",
  "targets": [
    {
      "expr": "histogram_quantile(0.50, rate(end_to_end_latency_ms_bucket[5m]))",
      "legendFormat": "p50"
    },
    {
      "expr": "histogram_quantile(0.95, rate(end_to_end_latency_ms_bucket[5m]))",
      "legendFormat": "p95"
    },
    {
      "expr": "histogram_quantile(0.99, rate(end_to_end_latency_ms_bucket[5m]))",
      "legendFormat": "p99"
    }
  ]
}
```

### Panel 3: Error Breakdown

```json
{
  "title": "Errors by Component",
  "targets": [
    {
      "expr": "rate(errors_total[5m]) by (component)",
      "legendFormat": "{{component}}"
    }
  ],
  "type": "graph",
  "stack": true
}
```

---

## Quick Reference Card

### Emergency Commands

```bash
# Emergency stop
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# Check bot health
curl http://localhost:9108/metrics | grep bot_heartbeat

# Check error rate
curl http://localhost:9108/metrics | grep errors_total

# Check latency
curl http://localhost:9108/metrics | grep end_to_end_latency

# Restart bot
python scripts/start_trading_system.py --restart

# Monitor signals
python scripts/monitor_redis_streams.py --tail
```

### Metrics Interpretation Cheatsheet

| Metric Value | Meaning | Action |
|--------------|---------|--------|
| p95 latency < 200ms | ✅ Excellent | None |
| p95 latency 200-500ms | ⚠️ Warning | Monitor |
| p95 latency > 500ms | ❌ Critical | Investigate |
| Errors < 2/min | ✅ Normal | None |
| Errors 2-5/min | ⚠️ Warning | Check logs |
| Errors > 5/min | ❌ Critical | Fix immediately |
| Reconnects < 1/hour | ✅ Normal | None |
| Reconnects 1-2/hour | ⚠️ Warning | Monitor network |
| Reconnects > 2/hour | ❌ Critical | Fix network |

---

## Maintenance Checklist

### Daily

- [ ] Check `bot_heartbeat_seconds` - should be fresh
- [ ] Check `errors_total` - should be low
- [ ] Check `end_to_end_latency_ms` p95 - should be < 500ms
- [ ] Verify signals publishing regularly
- [ ] Check no critical alerts fired

### Weekly

- [ ] Review error trends
- [ ] Review latency trends
- [ ] Check reconnect frequency
- [ ] Verify SLOs met (95% of time)
- [ ] Update `MAINTENANCE_LOG.md`

### Monthly

- [ ] Full metrics analysis
- [ ] SLO compliance report
- [ ] Performance optimization review
- [ ] Incident postmortems
- [ ] Update alert thresholds if needed

---

## Support & Escalation

| Issue Type | First Response | Escalation |
|------------|----------------|------------|
| P0 (Bot Down) | On-call engineer (< 5 min) | Engineering lead |
| P1 (High Errors) | On-call engineer (< 15 min) | Trading lead |
| P2 (Performance) | DevOps (< 1 hour) | Engineering lead |
| P3 (Minor) | DevOps (< 4 hours) | None |

**On-Call Rotation**: See `OPERATIONS_RUNBOOK.md` § Emergency Contacts

---

**Document Version**: 1.0
**Last Updated**: 2025-11-01
**Maintained By**: Platform Engineering Team
**B1.3 Compliance**: COMPLETE

