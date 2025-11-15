# 15-Minute Smoke Test - Pre-Flight Checklist

**Status**: Ready to Run ✅
**Date**: 2025-11-08
**Phase**: Production Validation - Smoke Test

---

## Overview

This smoke test validates that 15s synthetic bars are production-ready by:
- Monitoring bar generation for 15 minutes
- Verifying latency < 150ms E2E
- Ensuring no circuit breaker trips
- Confirming rate limiting works correctly

---

## Pre-Flight Checklist

### 1. Environment Configuration ✅

**Required Environment Variables:**

```bash
# Redis Connection
export REDIS_URL="rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
export REDIS_SSL=true
export REDIS_SSL_CA_CERT="config/certs/redis_ca.pem"

# Feature Flags (15s only for smoke test)
export ENABLE_5S_BARS=false

# Rate Limiting (conservative for smoke test)
export SCALPER_MAX_TRADES_PER_MINUTE=4

# Latency Budgets
export LATENCY_MS_MAX=100.0
export ENABLE_LATENCY_TRACKING=true

# Trading Mode
export TRADING_MODE=paper
```

**Verification:**
```bash
# Check all variables are set
env | grep -E "REDIS|ENABLE_5S|SCALPER_MAX|LATENCY|TRADING_MODE"

# Verify Redis connection
redis-cli -u $REDIS_URL --tls --cacert $REDIS_SSL_CA_CERT PING
# Expected: PONG
```

---

### 2. Test Results Verification ✅

**All tests must pass before smoke test:**

```bash
# Run synthetic bar tests
pytest tests/test_synthetic_bars.py -v

# Expected: 16/16 passed ✅

# Run rate limiter tests
pytest tests/test_rate_limiter.py -v

# Expected: 16/16 passed ✅
```

**Current Status**: All 32 tests passing ✅

---

### 3. Configuration Files ✅

**Verify configurations are correct:**

**kraken_ohlcv.yaml:**
- ✅ 15s timeframe configured
- ✅ 5s timeframe feature-gated
- ✅ Consumer groups include scalper_agents
- ✅ Latency budgets set (100ms for 15s)

**enhanced_scalper_config.yaml:**
- ✅ Dynamic target_bps (10 → 20)
- ✅ max_trades_per_minute env-tunable
- ✅ enable_5s_bars: false
- ✅ max_e2e_latency_ms: 150

---

### 4. Redis Stream Setup

**Check Redis streams are clean:**

```bash
# Check if 15s stream exists
redis-cli -u $REDIS_URL --tls --cacert $REDIS_SSL_CA_CERT \
  EXISTS kraken:ohlc:15s:BTC-USD

# If stream exists, check length
redis-cli -u $REDIS_URL --tls --cacert $REDIS_SSL_CA_CERT \
  XLEN kraken:ohlc:15s:BTC-USD

# Optional: Clear old data (only if needed)
# redis-cli -u $REDIS_URL --tls --cacert $REDIS_SSL_CA_CERT \
#   DEL kraken:ohlc:15s:BTC-USD
```

---

### 5. WSS Client Health

**Ensure Kraken WebSocket client is ready:**

```bash
# Check if WSS client is running
ps aux | grep kraken_ws

# If not running, start it
python -m utils.kraken_ws &

# Wait 30 seconds for connection to establish
sleep 30

# Verify trade ticks are flowing
redis-cli -u $REDIS_URL --tls --cacert $REDIS_SSL_CA_CERT \
  XLEN kraken:trades:BTC-USD

# Expected: > 0 (trade ticks are being received)
```

---

## Running the Smoke Test

### Step 1: Activate Environment

```bash
# Windows
conda activate crypto-bot

# Verify Python version
python --version
# Expected: Python 3.10+
```

---

### Step 2: Start WSS Client (if not already running)

```bash
# Start in background
python -m utils.kraken_ws &

# Check logs for successful connection
# Expected: "Connected to Kraken WebSocket"
```

---

### Step 3: Run Smoke Test

```bash
# Run 15-minute smoke test
python scripts/run_15min_smoke_test.py

# What to expect:
# - Test countdown (5 seconds)
# - Bar monitoring begins
# - Progress updates every 60 seconds
# - Final report after 15 minutes
```

---

### Step 4: Monitor Output

**During Test (Real-time):**

```
✅ Bar #1: BTC/USD close=50000.00 vol=0.5 latency=98.2ms
✅ Bar #2: BTC/USD close=50100.00 vol=0.3 latency=102.5ms
✅ Bar #3: BTC/USD close=49950.00 vol=0.7 latency=95.1ms

──────────────────────────────────────────────────────────────────────
⏱️  Progress: 60s / 900s
📊 Bars received: 4
⚡ Avg latency: 98.5ms (max: 102.5ms)
❌ Latency violations: 0
──────────────────────────────────────────────────────────────────────
```

**After 15 Minutes (Final Report):**

```
======================================================================
📋 SMOKE TEST FINAL REPORT
======================================================================

⏱️  Test Duration: 900.0s (15.0 minutes)

📊 Bars Received: 60
   Expected: ~60 bars (1 per 15s)
   Rate: 4.0 bars/min

⚡ Latency Metrics:
   Average: 98.5ms
   Maximum: 125.3ms
   Budget: 150ms
   P95: 112.1ms

❌ Violations:
   Latency violations: 0
   Circuit breaker trips: 0
   Redis errors: 0

======================================================================
✅ SMOKE TEST PASSED

✨ 15s bars are production ready!
   Next step: 24-hour paper trial
======================================================================
```

---

## Success Criteria

**The smoke test PASSES if:**

- ✅ Bars received: > 0 (ideally ~60 bars in 15 minutes)
- ✅ Average latency: < 150ms
- ✅ Maximum latency: < 200ms (with buffer)
- ✅ Latency violations: 0
- ✅ Circuit breaker trips: 0
- ✅ Redis errors: 0 or minimal

**The smoke test FAILS if:**

- ❌ No bars received (WSS client issue)
- ❌ Average latency >= 150ms
- ❌ Latency violations > 0
- ❌ Circuit breaker trips > 0
- ❌ Redis connection errors

---

## Troubleshooting

### Issue 1: No Bars Received

**Symptoms**: `Bars received: 0` after 5+ minutes

**Possible Causes:**
1. WSS client not running
2. Redis connection issue
3. Stream key mismatch
4. No trade volume on BTC/USD

**Fixes:**
```bash
# Check WSS client
ps aux | grep kraken_ws

# Check trade ticks
redis-cli -u $REDIS_URL --tls --cacert $REDIS_SSL_CA_CERT \
  XLEN kraken:trades:BTC-USD

# Check WSS client logs
tail -f logs/kraken_ws.log
```

---

### Issue 2: High Latency

**Symptoms**: Average latency > 150ms

**Possible Causes:**
1. Network latency (Redis Cloud distance)
2. System resource constraints
3. Redis connection pool size too small

**Fixes:**
```bash
# Increase Redis connection pool
export REDIS_CONNECTION_POOL_SIZE=20

# Check system resources
top
# Ensure CPU < 80%, Memory < 80%

# Check network latency
ping redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com
```

---

### Issue 3: Circuit Breaker Trips

**Symptoms**: Circuit breaker trips > 0

**Possible Causes:**
1. Spread too wide (> 5 bps)
2. Redis errors
3. Rate limit exceeded

**Fixes:**
```bash
# Check spread threshold
export SPREAD_BPS_MAX=10.0  # Relax if needed

# Check rate limit
export SCALPER_MAX_TRADES_PER_MINUTE=3  # More conservative
```

---

### Issue 4: Redis Connection Errors

**Symptoms**: Redis errors > 0

**Possible Causes:**
1. TLS certificate issue
2. Connection timeout
3. Network instability

**Fixes:**
```bash
# Verify certificate exists
ls -l config/certs/redis_ca.pem

# Test connection
redis-cli -u $REDIS_URL --tls --cacert $REDIS_SSL_CA_CERT PING

# Increase timeout
export REDIS_SOCKET_TIMEOUT=30
```

---

## After Smoke Test

### If Test PASSED ✅

**Next Steps:**

1. **Commit Changes**
   ```bash
   git add .
   git commit -m "feat(bars): sub-minute bars implementation complete - smoke test passed"
   ```

2. **Document Results**
   - Save smoke test output to `logs/smoke_test_results.txt`
   - Update `TASKLOG.md` with completion

3. **Prepare for 24-Hour Trial**
   - Review `SUB_MINUTE_BARS_DEPLOYMENT_GUIDE.md` Section 5
   - Set up monitoring (Grafana dashboards)
   - Plan 24-hour paper trading trial

4. **Enable 24/7 Monitoring**
   ```bash
   # Start monitoring dashboard
   python scripts/unified_status_dashboard.py
   ```

---

### If Test FAILED ❌

**Next Steps:**

1. **Analyze Failures**
   - Review final report for specific issues
   - Check logs for errors
   - Identify root cause

2. **Fix Issues**
   - Follow troubleshooting guide above
   - Adjust configuration if needed
   - Re-run unit tests

3. **Re-run Smoke Test**
   ```bash
   # After fixes
   python scripts/run_15min_smoke_test.py
   ```

4. **Document Issues**
   - Add to `INCIDENTS_LOG.md`
   - Update troubleshooting guide

---

## Quick Reference Commands

```bash
# Set environment (copy-paste all)
export REDIS_URL="rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
export REDIS_SSL=true
export REDIS_SSL_CA_CERT="config/certs/redis_ca.pem"
export ENABLE_5S_BARS=false
export SCALPER_MAX_TRADES_PER_MINUTE=4
export TRADING_MODE=paper

# Verify setup
redis-cli -u $REDIS_URL --tls --cacert $REDIS_SSL_CA_CERT PING

# Run tests
pytest tests/test_synthetic_bars.py tests/test_rate_limiter.py -v

# Start WSS client
python -m utils.kraken_ws &

# Run smoke test
python scripts/run_15min_smoke_test.py
```

---

## Smoke Test Timeline

| Time | Action | Expected Result |
|------|--------|----------------|
| T-5m | Set environment variables | All vars set ✅ |
| T-3m | Run unit tests | 32/32 passing ✅ |
| T-2m | Start WSS client | Connected ✅ |
| T-1m | Verify trade ticks | Ticks flowing ✅ |
| T+0m | Start smoke test | Countdown begins |
| T+1m | First progress update | ~4 bars received |
| T+2m | Second progress update | ~8 bars received |
| T+15m | Final report | Test complete |

**Total Duration**: 15 minutes active + 5 minutes setup = **20 minutes**

---

**Implementation Date**: 2025-11-08
**Status**: Ready to Execute ✅
**Next Milestone**: Run 15-minute smoke test → 24-hour paper trial

---

## Notes

- This is a **production validation** test, not a development test
- 15s bars only (5s bars disabled for safety)
- Conservative settings (4 trades/min)
- Paper trading mode only
- Monitor output closely for any anomalies
- Save all output for documentation

---

**Ready to begin? Run the smoke test now!**

```bash
python scripts/run_15min_smoke_test.py
```
