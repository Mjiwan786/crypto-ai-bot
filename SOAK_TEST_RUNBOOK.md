# 48-Hour Soak Test Deployment Runbook

**Version**: v1.0
**Date**: 2025-11-08
**Mode**: PAPER (48h validation before PROD promotion)
**Purpose**: Validate turbo_scalper_15s + bar_reaction_5m for production readiness

---

## Table of Contents

1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Deployment Steps](#deployment-steps)
3. [Monitoring & Alerting](#monitoring--alerting)
4. [Emergency Procedures](#emergency-procedures)
5. [Validation & Promotion](#validation--promotion)
6. [Troubleshooting](#troubleshooting)

---

## Pre-Deployment Checklist

### ✅ Environment Setup

- [ ] **Redis Cloud**: Connection verified and healthy
  ```powershell
  redis-cli -u rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
    --tls --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem `
    PING
  ```
  Expected: `PONG`

- [ ] **Conda Environment**: Activated
  ```powershell
  conda activate crypto-bot
  python --version  # Should be 3.9+
  ```

- [ ] **Dependencies**: All installed
  ```powershell
  pip install -r requirements.txt
  pip install redis[hiredis] prometheus-client requests pyyaml
  ```

- [ ] **Configuration Files**: All in place
  - `config/soak_test_48h_turbo.yaml` ✅
  - `config/turbo_scalper_15s.yaml` ✅
  - `config/bar_reaction_5m_aggressive.yaml` ✅

- [ ] **Monitoring Scripts**: Ready
  - `scripts/soak_test_monitor.py` ✅
  - `scripts/soak_test_validator.py` ✅

### ✅ Configuration Verification

- [ ] **Soak Test Config**: Review settings
  ```powershell
  cat config/soak_test_48h_turbo.yaml | Select-String -Pattern "mode:|enable_trading:|paper_trading_enabled:"
  ```
  Verify:
  - `mode: "PAPER"` ✅
  - `enable_trading: true` ✅
  - `paper_trading_enabled: true` ✅

- [ ] **Success Gates**: Confirm thresholds
  ```yaml
  min_net_pnl_usd: 0.01
  min_profit_factor: 1.25
  max_circuit_breaker_trips_per_hour: 3
  max_scalper_lag_messages: 5
  max_portfolio_heat_pct: 80.0
  max_latency_p95_ms: 500
  max_redis_lag_seconds: 2.0
  ```

- [ ] **Strategy Allocation**: 60% bar_reaction, 40% turbo_scalper
- [ ] **News Overrides**: OFF by default (enable manually for 4h test)
- [ ] **5s Bars**: OFF by default (auto-enable if latency < 50ms)

### ✅ Baseline Metrics

Record current state before soak test:

```powershell
# Check current equity
redis-cli -u rediss://... --tls --cacert ... XREVRANGE metrics:performance + - COUNT 1

# Check existing trade count
redis-cli -u rediss://... --tls --cacert ... XLEN trades:paper

# Check stream health
redis-cli -u rediss://... --tls --cacert ... XLEN signals:paper
```

Record baseline:
- **Starting Equity**: $10,000 (paper)
- **Total Trades (before)**: _________
- **Current P&L**: _________

---

## Deployment Steps

### Step 1: Start Monitoring Script (Terminal 1)

```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# Start soak test monitor (runs in foreground)
python scripts/soak_test_monitor.py --config config/soak_test_48h_turbo.yaml
```

**Expected Output**:
```
✅ Loaded soak test config: config/soak_test_48h_turbo.yaml
✅ Connected to Redis
✅ Started Prometheus exporter on :9109
🚀 Starting 48-hour soak test monitoring...
```

**Verify Prometheus**:
```powershell
# Open browser to http://localhost:9109/metrics
# Should see metrics like:
# soak_test_net_pnl_usd
# soak_test_profit_factor
# soak_test_portfolio_heat_pct
```

### Step 2: Start Trading Bot (Terminal 2)

```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# Start bot with soak test config
python main.py run --config config/soak_test_48h_turbo.yaml --mode paper
```

**Expected Output**:
```
✅ Loaded config: soak_test_48h_turbo.yaml
✅ Connected to Redis Cloud (TLS)
✅ Connected to Kraken WebSocket
✅ Strategies loaded: bar_reaction_5m, turbo_scalper_15s
🚀 Bot started in PAPER mode
```

**Verify Bot Health**:
```powershell
# Check bot logs (in Terminal 2)
# Look for:
# - "Strategy: bar_reaction_5m ACTIVE"
# - "Strategy: turbo_scalper_15s ACTIVE"
# - "WebSocket: CONNECTED"
# - "Redis: HEALTHY"
```

### Step 3: Verify Data Flow

Wait 2-3 minutes, then verify:

```powershell
# 1. Check signals stream is receiving data
redis-cli -u rediss://... --tls --cacert ... XLEN signals:paper
# Should be increasing

# 2. Check soak test stream is being written
redis-cli -u rediss://... --tls --cacert ... XLEN soak_test:v1
# Should have entries

# 3. Check latest signal
redis-cli -u rediss://... --tls --cacert ... XREVRANGE signals:paper + - COUNT 1

# 4. Check Prometheus metrics are updating
curl http://localhost:9108/metrics | Select-String -Pattern "current_equity_usd"
```

### Step 4: Enable News Overrides (4-Hour Test Window)

**⚠️ MANUAL STEP - Do this after initial stability (e.g., 12 hours in)**

Edit `config/soak_test_48h_turbo.yaml`:
```yaml
news_overrides:
  enabled: true
  test_window_enabled: true
  test_window_start_time: "2025-11-08T12:00:00Z"  # Set to current UTC time
```

Restart bot (Ctrl+C in Terminal 2, then re-run):
```powershell
python main.py run --config config/soak_test_48h_turbo.yaml --mode paper
```

**Observe**: Bot should now react to high-impact news events by closing positions or reducing size.

After 4 hours, disable again:
```yaml
news_overrides:
  enabled: false
  test_window_enabled: false
```

---

## Monitoring & Alerting

### Real-Time Dashboards

1. **Soak Test Monitor** (Terminal 1)
   - Shows live threshold checks
   - Alerts on violations
   - Checkpoint reports every 6 hours

2. **Prometheus Metrics**
   - Bot metrics: `http://localhost:9108/metrics`
   - Soak test metrics: `http://localhost:9109/metrics`

3. **signals-api Dashboards**
   - Visit: `https://crypto-signals-api.fly.dev/metrics/performance`
   - Live SSE stream: `https://crypto-signals-api.fly.dev/metrics/performance/stream`

4. **signals-site Dashboard** (if deployed)
   - Visit: `https://aipredictedsignals.cloud`
   - Should show PerformanceMetricsWidget with live updates

### Alert Channels

Alerts will be sent to:

1. **Terminal Output** (Monitor script - Terminal 1)
2. **Discord** (if configured in config)
3. **Redis Stream** (`metrics:alerts`)
   ```powershell
   # Monitor alerts stream
   redis-cli -u rediss://... --tls --cacert ... XREAD BLOCK 0 STREAMS metrics:alerts 0
   ```

### Alert Thresholds

| Metric | Threshold | Action |
|--------|-----------|--------|
| Portfolio Heat | >80% | 🔴 ALERT + close losing positions |
| Latency p95 | >500ms | 🔴 ALERT + reject trades |
| Redis Lag | >2.0s | 🔴 ALERT + pause turbo scalper |
| Circuit Breaker Trips | >3/hour | 🟡 WARNING |
| Daily Loss | >5% | 🔴 ALERT + pause trading |

### Checkpoint Reports

Monitor script generates reports every 6 hours:

- **6h checkpoint**: `reports/checkpoint_6h_*.json`
- **12h checkpoint**: `reports/checkpoint_12h_*.json`
- **18h checkpoint**: `reports/checkpoint_18h_*.json`
- **24h checkpoint**: `reports/checkpoint_24h_*.json`
- **30h checkpoint**: `reports/checkpoint_30h_*.json`
- **36h checkpoint**: `reports/checkpoint_36h_*.json`
- **42h checkpoint**: `reports/checkpoint_42h_*.json`
- **48h final**: `reports/soak_test_48h_*.json` (full validation)

Review these checkpoints to track progress:
```powershell
# View latest checkpoint
cat reports/checkpoint_*.json | ConvertFrom-Json | Format-List
```

---

## Emergency Procedures

### Emergency Stop (Kill Switch)

If you need to immediately halt trading:

**Terminal 2** (Bot):
```
Ctrl+C
```

**Terminal 1** (Monitor):
```
Ctrl+C
```

**Verify Shutdown**:
```powershell
# Check no Python processes running
Get-Process python

# Verify no new trades being written
redis-cli -u rediss://... --tls --cacert ... XLEN trades:paper
# Should stop increasing
```

### Emergency Scenarios

#### Scenario 1: Portfolio Heat > 80%

**Symptoms**:
- Alert in Terminal 1: "🔴 Portfolio heat exceeded threshold"
- Dashboard shows heat at 80%+

**Action**:
1. Monitor closes losing positions automatically
2. If heat doesn't decrease in 5 minutes, EMERGENCY STOP
3. Review open positions:
   ```powershell
   redis-cli -u rediss://... --tls --cacert ... XREVRANGE positions:open + - COUNT 10
   ```

#### Scenario 2: Latency Spike > 500ms

**Symptoms**:
- Alert: "🔴 High latency detected"
- Trades being rejected

**Action**:
1. Check network connection
2. Check Kraken WebSocket status in bot logs
3. Check Redis Cloud dashboard for issues
4. If latency doesn't recover in 10 minutes, EMERGENCY STOP

#### Scenario 3: Redis Lag > 2.0s

**Symptoms**:
- Alert: "🔴 Redis lag detected"
- Turbo scalper paused

**Action**:
1. Check Redis Cloud dashboard
2. Check stream sizes:
   ```powershell
   redis-cli -u rediss://... --tls --cacert ... XLEN signals:paper
   redis-cli -u rediss://... --tls --cacert ... XLEN trades:paper
   ```
3. If streams are too large (>10,000 entries), trim:
   ```powershell
   redis-cli -u rediss://... --tls --cacert ... XTRIM signals:paper MAXLEN 5000
   ```

#### Scenario 4: Daily Loss > 5%

**Symptoms**:
- Alert: "🔴 Daily loss threshold exceeded"
- Trading paused by circuit breaker

**Action**:
1. Bot automatically pauses for 60 minutes
2. Review losing trades:
   ```powershell
   redis-cli -u rediss://... --tls --cacert ... XREVRANGE trades:paper + - COUNT 20
   ```
3. Check if pattern (e.g., all losses from one strategy)
4. Consider manually stopping if losses are systematic

#### Scenario 5: Bot Crashes

**Symptoms**:
- Terminal 2 exits unexpectedly
- No new signals being written

**Action**:
1. Check error logs in Terminal 2 (scroll up)
2. Check bot logs:
   ```powershell
   cat logs/soak_test_48h_*.log | Select-String -Pattern "ERROR|CRITICAL"
   ```
3. If recoverable error, restart bot:
   ```powershell
   python main.py run --config config/soak_test_48h_turbo.yaml --mode paper
   ```
4. If crash persists, ABORT soak test and debug

---

## Validation & Promotion

### After 48 Hours

Once 48 hours have elapsed:

#### Step 1: Stop Bot & Monitor

**Terminal 2** (Bot):
```
Ctrl+C
```

**Terminal 1** (Monitor):
```
Ctrl+C
```

#### Step 2: Run Validation Script

```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# Run validation (dry-run, no auto-promotion)
python scripts/soak_test_validator.py --config config/soak_test_48h_turbo.yaml
```

**Expected Output**:
```
🚀 Starting 48-hour soak test validation...
✅ Connected to Redis
📊 Fetching metrics from Redis...
🔍 Validating success gates...
📝 Generating final report...

================================================================================
48-HOUR SOAK TEST VALIDATION REPORT
================================================================================
Start Time: 2025-11-08T00:00:00
End Time:   2025-11-10T00:00:00
Duration:   48.0 hours

🟢 RESULT: PASSED ✅

SUMMARY METRICS
--------------------------------------------------------------------------------
Net P&L:          $127.45
Profit Factor:    1.38
Win Rate:         42.3%
Total Trades:     87
CB Trips:         12
Portfolio Heat:   68.2%
Latency p95:      245ms
Redis Lag:        0.42s

SUCCESS GATE VALIDATION
--------------------------------------------------------------------------------
✅ PASS | Net P&L: $127.45 (threshold: $0.01)
✅ PASS | Profit Factor: 1.38 (threshold: 1.25)
✅ PASS | CB trips/hour: 0.25 (max: 3)
✅ PASS | Scalper lag messages: 2 (max: 5)
✅ PASS | Portfolio heat: 68.2% (max: 80.0%)
✅ PASS | Latency p95: 245ms (max: 500ms)
✅ PASS | Redis lag: 0.42s (max: 2.0s)

================================================================================
```

#### Step 3: Review Final Report

```powershell
# Open JSON report
cat reports/soak_test_48h_*.json | ConvertFrom-Json | Format-List
```

Review:
- [ ] All success gates PASSED
- [ ] No systematic issues in recommendations
- [ ] Profit factor ≥ 1.25
- [ ] Net P&L positive
- [ ] No excessive circuit breaker trips

#### Step 4: Promote to PROD Candidate

If validation passed, run with auto-promote:

```powershell
python scripts/soak_test_validator.py --config config/soak_test_48h_turbo.yaml --auto-promote
```

**Expected Output**:
```
🎉 Soak test PASSED! Executing promotion logic...
✅ Exported Prometheus snapshot: reports/prometheus_snapshot_20251108_120000.json
✅ Tagged config as PROD-CANDIDATE-v20251108_120000: config/soak_test_48h_turbo_PROD-CANDIDATE-v20251108_120000_20251108_120000.yaml
✅ Updated symlink: config/soak_test_48h_turbo_PROD_LATEST.yaml

🚀 Ready for PRODUCTION deployment!
```

**Files Created**:
- `config/soak_test_48h_turbo_PROD-CANDIDATE-vXXX_YYYYMMDD_HHMMSS.yaml` (tagged config)
- `config/soak_test_48h_turbo_PROD_LATEST.yaml` (symlink to latest)
- `reports/prometheus_snapshot_YYYYMMDD_HHMMSS.json` (Prometheus export)

#### Step 5: Deploy to Production

**⚠️ CRITICAL: Only proceed if soak test PASSED**

1. **Update Production Config**:
   ```yaml
   # In config/production.yaml, change:
   bot:
     mode: "LIVE"  # Was "PAPER"
     paper_trading_enabled: false  # Was true
   ```

2. **Enable Strategies**:
   ```yaml
   strategies:
     active:
       - "bar_reaction_5m"
       - "turbo_scalper_15s"  # Now enabled in PROD
   ```

3. **Start Production Bot**:
   ```powershell
   # ⚠️ REAL MONEY - VERIFY EVERYTHING TWICE
   python main.py run --config config/production.yaml --mode live
   ```

4. **Monitor Closely**:
   - Watch first 10 trades very carefully
   - Verify fills are correct
   - Check P&L matches expectations
   - Have kill switch ready (Ctrl+C)

---

## Troubleshooting

### Issue: No Trades Being Generated

**Symptoms**: 48 hours elapsed, total trades = 0

**Debug**:
```powershell
# 1. Check if signals are being generated
redis-cli -u rediss://... --tls --cacert ... XREVRANGE signals:paper + - COUNT 10

# 2. Check strategy logs
cat logs/soak_test_48h_*.log | Select-String -Pattern "signal_generated"

# 3. Check if filters are too strict
cat config/turbo_scalper_15s.yaml | Select-String -Pattern "min_momentum_bps|max_spread_bps"
```

**Possible Causes**:
- Filters too strict (momentum threshold too high)
- Market conditions not met (regime filters)
- WebSocket not receiving data

### Issue: Monitor Script Not Alerting

**Symptoms**: Threshold exceeded but no alert

**Debug**:
```powershell
# 1. Check if monitor is running
Get-Process python | Where-Object {$_.CommandLine -like "*soak_test_monitor*"}

# 2. Check monitor logs
# Look at Terminal 1 output

# 3. Verify alert channels configured
cat config/soak_test_48h_turbo.yaml | Select-String -Pattern "alerts_enabled|alert_channels"
```

### Issue: Validation Script Fails

**Symptoms**: `soak_test_validator.py` throws errors

**Debug**:
```powershell
# 1. Check Redis connection
redis-cli -u rediss://... --tls --cacert ... PING

# 2. Check if soak test stream exists
redis-cli -u rediss://... --tls --cacert ... EXISTS soak_test:v1

# 3. Run with verbose output
python scripts/soak_test_validator.py --config config/soak_test_48h_turbo.yaml -v
```

### Issue: Turbo Scalper Not Trading

**Symptoms**: bar_reaction_5m is trading, turbo_scalper_15s is not

**Debug**:
```powershell
# 1. Check if turbo scalper is enabled
cat config/soak_test_48h_turbo.yaml | Select-String -Pattern "turbo_scalper" -Context 5

# 2. Check if latency is too high (5s bars disabled)
curl http://localhost:9108/metrics | Select-String -Pattern "latency_p95_ms"

# 3. Check for lag alerts
redis-cli -u rediss://... --tls --cacert ... XREVRANGE metrics:alerts + - COUNT 10
```

**Solution**: If latency > 50ms, 5s bars stay disabled. Consider:
- Optimizing network connection
- Reducing message load
- Accepting 15s timeframe only

---

## Quick Reference Commands

### Redis Health Check
```powershell
redis-cli -u rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem `
  PING
```

### Check Stream Lengths
```powershell
redis-cli -u rediss://... --tls --cacert ... XLEN signals:paper
redis-cli -u rediss://... --tls --cacert ... XLEN trades:paper
redis-cli -u rediss://... --tls --cacert ... XLEN soak_test:v1
redis-cli -u rediss://... --tls --cacert ... XLEN metrics:alerts
```

### View Latest Metrics
```powershell
redis-cli -u rediss://... --tls --cacert ... XREVRANGE metrics:performance + - COUNT 1
```

### Check Bot Prometheus
```powershell
curl http://localhost:9108/metrics | Select-String -Pattern "current_equity|profit_factor|win_rate"
```

### Check Monitor Prometheus
```powershell
curl http://localhost:9109/metrics | Select-String -Pattern "soak_test"
```

### Trim Large Streams
```powershell
redis-cli -u rediss://... --tls --cacert ... XTRIM signals:paper MAXLEN 5000
redis-cli -u rediss://... --tls --cacert ... XTRIM trades:paper MAXLEN 5000
```

---

## Success Criteria Summary

| Gate | Threshold | Target |
|------|-----------|--------|
| Net P&L | ≥ $0.01 | Positive |
| Profit Factor | ≥ 1.25 | >1.0 |
| CB Trips/Hour | ≤ 3 | <1.0 |
| Scalper Lag Msgs | ≤ 5 | <3 |
| Portfolio Heat | ≤ 80% | <60% |
| Latency p95 | ≤ 500ms | <300ms |
| Redis Lag | ≤ 2.0s | <1.0s |

**ALL gates must PASS for PROD promotion.**

---

## Support & Documentation

- **Full Config**: `config/soak_test_48h_turbo.yaml`
- **Strategy Configs**: `config/turbo_scalper_15s.yaml`, `config/bar_reaction_5m_aggressive.yaml`
- **Performance Metrics Guide**: `PERFORMANCE_METRICS_GUIDE.md`
- **Optimization Strategy**: `OPTIMIZATION_STRATEGY_FINAL.md`

---

**Last Updated**: 2025-11-08
**Version**: v1.0
**Status**: ✅ READY FOR DEPLOYMENT
