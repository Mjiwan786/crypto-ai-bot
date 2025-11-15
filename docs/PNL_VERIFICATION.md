# PnL Pipeline Verification Guide - Crypto AI Bot

**Complete end-to-end verification of the PnL aggregation pipeline.**

## Overview

This guide walks through verifying the entire PnL loop without a web dashboard:

```
1. Publisher → trades:closed stream
2. Aggregator → consumes trades, publishes to pnl:equity
3. Redis → stores equity history and latest values
4. Health checks → validates all components
```

## Quick Verification (5 Steps)

### Prerequisites

```bash
# Activate conda environment
conda activate crypto-bot

# Set Redis URL
export REDIS_URL=rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0
```

### Step 1: Start Aggregator

```bash
# Terminal 1: Start aggregator
python -m monitoring.pnl_aggregator
```

**Expected output**:
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
📍 Starting fresh from: 0-0
🚀 Starting aggregator loop...
```

### Step 2: Seed Test Trades

```bash
# Terminal 2: Seed trades
python scripts/seed_closed_trades.py
```

**Expected output**:
```
============================================================
SEEDING TRADES
============================================================
Trades to publish: 10
Interval: 0.5s
Redis URL: rediss://...
============================================================

📤  1/10: BTC/USD  long  $45,234.50 → $46,123.00 PnL: +$88.85
📤  2/10: ETH/USD  short $2,456.20 → $2,398.10 PnL: +$58.10
...
📤 10/10: SOL/USD  long  $112.30 → $117.40 PnL: +$51.00

============================================================
✅ Seeded 10 trades successfully
============================================================
```

**Check Terminal 1** - Should show aggregator processing:
```
📈 Trade 1: PnL +$88.85 → Equity $10,088.85 (daily: +$88.85)
📈 Trade 2: PnL +$58.10 → Equity $10,146.95 (daily: +$146.95)
...
📈 Trade 10: PnL +$51.00 → Equity $10,512.40 (daily: +$512.40)
```

### Step 3: Health Check

```bash
# Terminal 2: Run health check
python scripts/health_check_pnl.py --verbose
```

**Expected output**:
```
============================================================
PNL HEALTH CHECK
============================================================

🔍 Checking Redis connection...
✅ Redis connection OK

🔍 Checking trade stream (trades:closed)...
✅ Stream 'trades:closed' active (10 messages, 5 parsed)
   Latest trades: 5

🔍 Checking equity stream (pnl:equity)...
✅ Stream 'pnl:equity' active (10 messages, 5 parsed)
   Latest equity points: 5

🔍 Calculating trade publish latency (P95)...
📊 Trade P95 latency: 2.45s

🔍 Calculating equity publish latency (P95)...
📊 Equity P95 latency: 2.48s

🔍 Checking latest equity value...
✅ Latest equity: $10,512.40 (daily PnL: +$512.40)

============================================================
HEALTH CHECK SUMMARY
============================================================
Status: HEALTHY
Checks: 2/2 passed
============================================================
```

### Step 4: Manual Redis Check

```bash
# Verify equity stream has data
python -c "import os,redis; r=redis.from_url(os.getenv('REDIS_URL','redis://localhost:6379/0'),decode_responses=False); print(r.xrevrange('pnl:equity','+','-',count=3))"
```

**Expected output** (example):
```
[(b'1704067200500-0', {b'json': b'{"ts":1704067200500,"equity":10088.85,"daily_pnl":88.85}'}),
 (b'1704067201000-0', {b'json': b'{"ts":1704067201000,"equity":10146.95,"daily_pnl":146.95}'}),
 (b'1704067201500-0', {b'json': b'{"ts":1704067201500,"equity":10195.30,"daily_pnl":195.30}'})]
```

**You should see**:
- 3 entries with message IDs (timestamps)
- Each entry has `b'json'` field with serialized equity data
- Equity values increasing over time
- Daily PnL accumulating

### Step 5: Verify Latest Equity

```bash
# Check latest equity value
python -c "import os,redis,json; r=redis.from_url(os.getenv('REDIS_URL','redis://localhost:6379/0')); data=json.loads(r.get('pnl:equity:latest')); print(f'Equity: \${data[\"equity\"]:,.2f}, Daily PnL: \${data[\"daily_pnl\"]:+,.2f}')"
```

**Expected output**:
```
Equity: $10,512.40, Daily PnL: +$512.40
```

## Automated Verification

### Using verify_pnl_loop.py

```bash
# Run automated verification
python scripts/verify_pnl_loop.py --verbose
```

**Expected output**:
```
============================================================
PNL LOOP VERIFICATION
============================================================
Redis URL: rediss://...
============================================================

✅ Redis connection OK

────────────────────────────────────────────────────────────
Checking: Trades Stream
────────────────────────────────────────────────────────────

✅ trades:closed stream: 10 messages

   Latest 3 trades:
   - 9-0: BTC/USD long PnL +$45.20
   - 8-0: ETH/USD short PnL +$32.10
   - 7-0: SOL/USD long PnL -$12.50

────────────────────────────────────────────────────────────
Checking: Equity Stream
────────────────────────────────────────────────────────────

✅ pnl:equity stream: 10 messages

   Latest 3 equity points:
   - 1704067205000-0: Equity $10,512.40, Daily PnL +$512.40
   - 1704067204500-0: Equity $10,461.40, Daily PnL +$461.40
   - 1704067204000-0: Equity $10,429.30, Daily PnL +$429.30

────────────────────────────────────────────────────────────
Checking: Latest Equity
────────────────────────────────────────────────────────────

✅ pnl:equity:latest:
   Equity: $10,512.40
   Daily PnL: +$512.40
   Timestamp: 1704067205000

────────────────────────────────────────────────────────────
Checking: Data Consistency
────────────────────────────────────────────────────────────

✅ Data consistency check passed
   Stream equity: $10,512.40
   Latest equity: $10,512.40

============================================================
VERIFICATION SUMMARY
============================================================
Checks passed: 4/4

✅ All checks passed! PnL loop is working correctly.
```

## Manual Redis CLI Verification

### Using Redis Cloud with TLS

```bash
# Set connection details
REDIS_HOST="redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com"
REDIS_PORT=19818
REDIS_PASSWORD="${REDIS_PASSWORD}"
REDIS_URL="redis://default:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}"

# 1. Check stream lengths
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt XLEN trades:closed
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt XLEN pnl:equity

# 2. Read last 3 trades
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt XREVRANGE trades:closed + - COUNT 3

# 3. Read last 3 equity points
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt XREVRANGE pnl:equity + - COUNT 3

# 4. Get latest equity
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt GET pnl:equity:latest

# 5. Check backfill marker
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt GET pnl:backfill:done

# 6. Check aggregator state
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt GET pnl:agg:last_id
```

### Using Local Redis (No TLS)

```bash
# 1. Check stream lengths
redis-cli XLEN trades:closed
redis-cli XLEN pnl:equity

# 2. Read streams
redis-cli XREVRANGE trades:closed + - COUNT 3
redis-cli XREVRANGE pnl:equity + - COUNT 3

# 3. Get latest equity
redis-cli GET pnl:equity:latest

# 4. Check markers
redis-cli GET pnl:backfill:done
redis-cli GET pnl:agg:last_id
```

## Prometheus Metrics Verification (Optional)

### Enable Metrics

```bash
# Start aggregator with metrics
export PNL_METRICS_PORT=9309
python -m monitoring.pnl_aggregator
```

### Check Metrics Endpoint

```bash
# Using curl
curl http://localhost:9309/metrics

# Filter for PnL metrics
curl http://localhost:9309/metrics | grep pnl_aggregator
```

**Expected output**:
```
# HELP pnl_aggregator_equity_usd Current account equity in USD
# TYPE pnl_aggregator_equity_usd gauge
pnl_aggregator_equity_usd 10512.4

# HELP pnl_aggregator_daily_pnl_usd Daily profit/loss in USD
# TYPE pnl_aggregator_daily_pnl_usd gauge
pnl_aggregator_daily_pnl_usd 512.4

# HELP pnl_aggregator_trades_closed_total Total trades processed
# TYPE pnl_aggregator_trades_closed_total counter
pnl_aggregator_trades_closed_total 10.0
```

### Using Python

```python
import requests

# Fetch metrics
response = requests.get("http://localhost:9309/metrics")

# Parse for equity gauge
for line in response.text.split('\n'):
    if 'pnl_aggregator_equity_usd' in line and not line.startswith('#'):
        print(f"Current equity: {line}")
    if 'pnl_aggregator_daily_pnl_usd' in line and not line.startswith('#'):
        print(f"Daily PnL: {line}")
    if 'pnl_aggregator_trades_closed_total' in line and not line.startswith('#'):
        print(f"Trades processed: {line}")
```

## Verification Scenarios

### Scenario 1: Fresh Setup

```bash
# 1. Start aggregator (fresh state)
python -m monitoring.pnl_aggregator

# 2. Seed 10 trades
python scripts/seed_closed_trades.py

# 3. Verify
python scripts/verify_pnl_loop.py --verbose

# Expected: All checks pass, equity = $10,000 + PnL
```

### Scenario 2: With Backfill

```bash
# 1. Backfill historical data
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv

# 2. Start aggregator (resumes from backfill)
python -m monitoring.pnl_aggregator

# 3. Seed new trades
python scripts/seed_closed_trades.py

# 4. Verify
python scripts/verify_pnl_loop.py --verbose

# Expected: Equity continues from backfilled value
```

### Scenario 3: Aggregator Restart

```bash
# 1. Start aggregator
python -m monitoring.pnl_aggregator

# 2. Seed trades
python scripts/seed_closed_trades.py --count 5

# 3. Stop aggregator (Ctrl+C)

# 4. Seed more trades
python scripts/seed_closed_trades.py --count 5

# 5. Restart aggregator
python -m monitoring.pnl_aggregator

# Expected: Aggregator resumes from last_id, processes new trades
```

### Scenario 4: Day Boundary

```bash
# 1. Start aggregator
python -m monitoring.pnl_aggregator

# 2. Seed trades (today)
python scripts/seed_closed_trades.py

# 3. Wait for UTC midnight or simulate by advancing time

# 4. Seed more trades (next day)
python scripts/seed_closed_trades.py

# Expected: Daily PnL resets at midnight
```

## Troubleshooting

### "pnl:equity stream is empty"

**Cause**: Aggregator not running or not processing trades

**Solution**:
```bash
# Check if aggregator is running
ps aux | grep pnl_aggregator

# Start aggregator
python -m monitoring.pnl_aggregator

# Seed trades
python scripts/seed_closed_trades.py

# Wait 1-2 seconds
sleep 2

# Verify
python scripts/verify_pnl_loop.py
```

### "trades:closed stream is empty"

**Cause**: No trades published

**Solution**:
```bash
# Seed trades
python scripts/seed_closed_trades.py

# Verify stream
redis-cli XLEN trades:closed
```

### "Redis connection failed"

**Cause**: Wrong REDIS_URL or Redis not accessible

**Solution**:
```bash
# Check Redis URL
echo $REDIS_URL

# Test connection
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt PING

# For local Redis, ensure it's running
docker run -d -p 6379:6379 redis:7
```

### "Data consistency mismatch"

**Cause**: Aggregator still processing (not actually an error)

**Solution**:
```bash
# Wait a few seconds for processing
sleep 3

# Verify again
python scripts/verify_pnl_loop.py
```

### "P95 latency too high"

**Cause**: Network latency to Redis Cloud or system performance

**Expected**: P95 < 5 seconds is normal for Redis Cloud

**If > 10 seconds**:
```bash
# Check network latency
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt PING --latency

# Consider using local Redis for development
export REDIS_URL=redis://localhost:6379/0
```

## Complete Workflow Example

### Full Setup and Verification

```bash
# ========================================
# SETUP
# ========================================

# 1. Activate environment
conda activate crypto-bot

# 2. Set Redis URL
export REDIS_URL=rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0

# 3. Clean slate (optional - clears all data)
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt DEL trades:closed
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt DEL pnl:equity
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt DEL pnl:equity:latest
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt DEL pnl:agg:last_id
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt DEL pnl:backfill:done

# ========================================
# OPTIONAL: BACKFILL
# ========================================

# 4. Backfill historical data
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv

# ========================================
# RUN SERVICES
# ========================================

# 5. Start aggregator (Terminal 1)
python -m monitoring.pnl_aggregator

# ========================================
# SEED TRADES
# ========================================

# 6. Seed trades (Terminal 2)
python scripts/seed_closed_trades.py --count 20 --interval 0.5

# ========================================
# VERIFICATION
# ========================================

# 7. Health check
python scripts/health_check_pnl.py --verbose

# 8. Automated verification
python scripts/verify_pnl_loop.py --verbose

# 9. Manual Redis check
python -c "import os,redis; r=redis.from_url(os.getenv('REDIS_URL','redis://localhost:6379/0'),decode_responses=False); print(r.xrevrange('pnl:equity','+','-',count=3))"

# 10. Check latest equity
python -c "import os,redis,json; r=redis.from_url(os.getenv('REDIS_URL','redis://localhost:6379/0')); data=json.loads(r.get('pnl:equity:latest')); print(f'Equity: \${data[\"equity\"]:,.2f}, Daily PnL: \${data[\"daily_pnl\"]:+,.2f}')"

# ========================================
# SUCCESS!
# ========================================
```

## Expected Timeline

```
Time  | Action                           | Result
------|----------------------------------|----------------------------------
0s    | Start aggregator                 | Connects to Redis, waits for trades
5s    | Seed 10 trades (0.5s interval)   | Publishes over 5 seconds
5s    | Aggregator processes             | Processes immediately as received
6s    | Health check                     | Shows 10 trades, 10 equity points
7s    | Verification                     | All checks pass
```

**Total time: ~10 seconds from start to verification**

---

**Last Updated**: 2025-01-13
**Conda Environment**: crypto-bot
**Python Version**: 3.10.18
**Redis Cloud**: redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 (TLS)
