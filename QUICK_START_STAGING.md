# Quick Start - Multi-Pair Staging Test

**Status**: Infrastructure ready, awaiting your approval
**Time Required**: 5 minutes to start, 2-4 hours to monitor

---

## TL;DR - Start Staging Publisher

```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python run_staging_publisher.py
```

**What it does**: Publishes signals for BTC, ETH, SOL, ADA, AVAX to isolated staging stream
**Impact on production**: ZERO (completely isolated)

---

## Current State

✅ **COMPLETED**:
1. Staging stream configured (`signals:paper:staging`)
2. API endpoints ready (mode=staging)
3. Website UI updated (staging mode dropdown)
4. All changes committed to feature branches
5. Production completely untouched

⏳ **NEXT STEP** (Needs Your Approval):
Start the staging signal publisher to generate signals for new pairs

---

## Repository Status

All 3 repos on `feature/add-trading-pairs` branch:

| Repository | Branch | Commit | Status |
|------------|--------|--------|--------|
| crypto-ai-bot | feature/add-trading-pairs | eed119f | Ready to run |
| signals-api | feature/add-trading-pairs | 4ffa02e | Ready to deploy |
| signals-site | feature/add-trading-pairs | d5fa952 | Ready to deploy |

**Production Impact**: ZERO (no deployments yet, no main branch changes)

---

## Option 1: Start Staging Publisher Now (Recommended)

### Step 1: Verify Environment

```bash
# Check conda environment exists
conda env list | grep crypto-bot

# Activate environment
conda activate crypto-bot

# Verify Redis connection
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
python -c "from dotenv import load_dotenv; load_dotenv('.env.staging'); import redis; import os; r = redis.from_url(os.getenv('REDIS_URL'), ssl_ca_certs=os.getenv('REDIS_SSL_CA_CERT')); print('Redis OK:', r.ping())"
```

**Expected Output**: `Redis OK: True`

---

### Step 2: Start Publisher

```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
python run_staging_publisher.py
```

**Expected Output**:
```
============================================================
STAGING SIGNAL PUBLISHER
============================================================
Stream: signals:paper:staging
Pairs: BTC/USD,ETH/USD,SOL/USD,ADA/USD,AVAX/USD
Staging Mode: true
============================================================

Starting signal processor in STAGING mode...
Press Ctrl+C to stop
```

**What happens**:
- Signals published to `signals:paper:staging` stream only
- Production streams (`signals:paper`, `signals:live`) untouched
- All 5 pairs generating signals
- Real-time market data from Kraken

---

### Step 3: Monitor (in separate terminal)

```bash
# Terminal 2: Monitor staging stream growth
redis-cli -u "rediss://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" --tls --cacert config/certs/redis_ca.pem XLEN signals:paper:staging

# Should increase from ~6 to 100+ over 1 hour
```

---

### Step 4: Verify Production Untouched

```bash
# Check production stream (should be unchanged)
redis-cli -u "rediss://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" --tls --cacert config/certs/redis_ca.pem XLEN signals:paper

# Should remain at 10,016 messages (or whatever current count is)
```

---

### Step 5: Stop Publisher (When Ready)

```
Press Ctrl+C in the publisher terminal
```

**Expected Output**:
```
Stopping staging publisher...
Staging stream preserved for analysis
```

**Note**: Staging stream data is preserved for later testing

---

## Option 2: Wait and Review First

If you want to review the changes before starting:

### Review Documentation

1. **Overall Status**: `MULTI_PAIR_ROLLOUT_STATUS.md`
2. **Staging Tests**: `STAGING_TEST_RESULTS.md`
3. **Rollout Plan**: `MULTI_PAIR_ROLLOUT_PLAN.md`
4. **API Changes**: `../signals_api/API_MULTI_PAIR_CHANGES.md`
5. **UI Changes**: `../signals-site/UI_MULTI_PAIR_CHANGES.md`

### Review Test Results

```bash
# Check staging test results
cat STAGING_TEST_RESULTS.md

# Key findings:
# - 5/5 tests passed
# - Stream isolation verified
# - Production untouched
# - All pairs working
```

### Review Code Changes

```bash
# crypto-ai-bot changes
git diff main feature/add-trading-pairs

# signals-api changes
cd ../signals_api
git diff main feature/add-trading-pairs

# signals-site changes
cd ../signals-site
git diff main feature/add-trading-pairs
```

---

## What Happens After Publisher Runs?

### After 2-4 Hours of Successful Publishing

**You'll be ready for**:
1. Deploy signals-api to Fly.io (adds staging endpoint)
2. Deploy signals-site to Vercel (adds UI for new pairs)
3. Test end-to-end: Website → API → Staging Stream

**Then eventually**:
4. Canary rollout to production stream (10% → 50% → 100%)
5. Comprehensive backtesting (only after your approval)

---

## Safety Features

### Built-in Safety Checks

1. **Stream Name Validation**:
   - Publisher checks `TRADING_STREAM == 'signals:paper:staging'`
   - Exits if incorrect stream configured

2. **Staging Mode Flag**:
   - `STAGING_MODE=true` required in `.env.staging`
   - Warning if not set

3. **Isolated Environment**:
   - Completely separate Redis stream
   - No code path to production streams

4. **Easy Rollback**:
   - Stop publisher: Ctrl+C
   - Delete staging stream: `redis-cli DEL signals:paper:staging`
   - Zero impact on production

---

## Monitoring Checklist

While publisher runs, check these every 30 minutes:

- [ ] Staging stream length increasing (`XLEN signals:paper:staging`)
- [ ] No errors in publisher output
- [ ] Production stream unchanged (`XLEN signals:paper`)
- [ ] All 5 pairs appearing in staging stream
- [ ] Redis connection stable (no disconnects)

---

## FAQ

### Q: Will this affect the live website?
**A**: No. Website currently doesn't have staging mode (not deployed yet). Even after deployment, staging mode will be a separate dropdown option that users must explicitly select.

### Q: Will this affect real trading (signals:live)?
**A**: No. Real trading uses a completely separate stream (`signals:live`) that is never touched by this code.

### Q: Can I stop the publisher anytime?
**A**: Yes. Press Ctrl+C. The staging stream data is preserved, so you can restart later.

### Q: What if I see errors?
**A**: Stop the publisher (Ctrl+C), check logs, fix issue, restart. Zero production impact since it's staging only.

### Q: How long should I run it?
**A**: Minimum 2 hours, recommended 4-6 hours for good data coverage. Can run overnight if desired.

---

## Troubleshooting

### Publisher Won't Start

**Error**: `ModuleNotFoundError: No module named 'agents'`
```bash
# Ensure you're in correct directory
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# Ensure conda environment active
conda activate crypto-bot
```

**Error**: `Redis connection failed`
```bash
# Check .env.staging exists
ls -la .env.staging

# Verify Redis certificate
ls -la config/certs/redis_ca.pem

# Test connection manually
python test_staging_stream.py
```

### No Signals Appearing

**Check**:
1. Kraken API accessible (firewall/proxy issues?)
2. No rate limiting errors in output
3. Redis stream writable (`XADD` permission)

**Debug**:
```bash
# Check last error in Redis
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XINFO STREAM signals:paper:staging
```

---

## Next Steps After Publisher Runs

### Immediate (While Running)
1. Monitor staging stream growth
2. Verify no errors
3. Check all 5 pairs appearing

### After 2+ Hours
1. Review metrics
2. Get your approval for API deployment
3. Deploy signals-api to Fly.io
4. Test staging endpoint

### After API Deployed
1. Get your approval for website deployment
2. Create PR for signals-site
3. Test Vercel preview
4. Merge to main (if approved)

### After Website Deployed
1. Test staging mode on live website
2. Run for 48 hours
3. Get your approval for canary rollout
4. Gradually migrate to production stream

### Only When You Approve
1. Run comprehensive backtests on all pairs
2. Analyze performance metrics
3. Optimize parameters if needed

---

## Commands Reference

### Start
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python run_staging_publisher.py
```

### Monitor
```bash
# Staging stream length
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XLEN signals:paper:staging

# View recent signals
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XRANGE signals:paper:staging - + COUNT 10
```

### Stop
```
Ctrl+C in publisher terminal
```

### Cleanup (if needed)
```bash
# Delete staging stream
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem DEL signals:paper:staging
```

---

**Ready to start?** Run the command in "Option 1: Step 2" above.

**Want to review first?** See "Option 2: Wait and Review First" above.

**Questions?** Check `MULTI_PAIR_ROLLOUT_STATUS.md` for comprehensive details.

---

Generated with Claude Code
https://claude.com/claude-code
