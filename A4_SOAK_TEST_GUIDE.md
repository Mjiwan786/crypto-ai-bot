# A4 - Soak Test Publisher Guide

**Purpose**: Run staging publisher for 3-5 minutes and collect evidence
**Target**: Verify new pairs (SOL/USD, ADA/USD, AVAX/USD) are publishing correctly
**Impact**: ZERO on production (staging stream only)

---

## Prerequisites

✅ A1 Complete - Config audit done
✅ A2 Complete - Feature flags implemented (20/20 tests passing)
✅ A3 Complete - Startup scripts ready

---

## Soak Test Procedure

### Step 1: Start Publisher

**Command** (Windows):
```cmd
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
scripts\run_publisher_staging.bat
```

**Command** (Unix/Linux):
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
./scripts/run_publisher_staging.sh
```

**Expected Output**:
```
============================================================
STAGING SIGNAL PUBLISHER - Local Test Mode
============================================================

[1/4] Loading .env.staging configuration...
      ✓ Configuration loaded

[2/4] Verifying configuration...
      PUBLISH_MODE: staging
      TRADING_PAIRS: BTC/USD,ETH/USD
      EXTRA_PAIRS: SOL/USD,ADA/USD,AVAX/USD
      Redis Stream: signals:paper:staging

[3/4] Testing Redis TLS connectivity (dry-run)...
      ✓ Redis PING: OK
      ✓ Staging stream exists: 1

[4/4] Starting signal publisher...

============================================================
Publishing to: signals:paper:staging
Trading Pairs: [BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD]
Mode: PAPER (no real trades)
Impact on Fly.io: ZERO (local process only)
Impact on Production: ZERO (isolated staging stream)
============================================================

Press Ctrl+C to stop publisher

INFO:agents.core.signal_processor:Trading pairs loaded: BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD
INFO:agents.core.signal_processor:  Base pairs: BTC/USD, ETH/USD
INFO:agents.core.signal_processor:  Extra pairs: SOL/USD, ADA/USD, AVAX/USD
```

### Step 2: Monitor for 3-5 Minutes

**Watch for**:
1. Signals publishing successfully
2. All 5 pairs appearing in logs
3. No errors or connection issues
4. Redis stream length increasing

**In a separate terminal**, monitor Redis:
```bash
# Watch stream length grow
watch -n 5 'redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem XLEN signals:paper:staging'

# Or one-time check
redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem XLEN signals:paper:staging
```

### Step 3: Collect Log Evidence

**Save publisher output** to `logs/staging_publisher_canary.txt`:

#### Method 1: Redirect on Start (Recommended)

```bash
# Windows (PowerShell)
scripts\run_publisher_staging.bat 2>&1 | Tee-Object -FilePath logs\staging_publisher_canary.txt

# Unix/Linux
./scripts/run_publisher_staging.sh 2>&1 | tee logs/staging_publisher_canary.txt
```

#### Method 2: Copy After Run

1. Run publisher normally
2. Copy terminal output
3. Paste into `logs/staging_publisher_canary.txt`

### Step 4: Capture Redis Evidence

**Create**: `logs/redis_evidence.txt`

```bash
# Execute these commands and save output to redis_evidence.txt
echo "=== Redis Evidence - Staging Stream ===" > logs/redis_evidence.txt
echo "" >> logs/redis_evidence.txt

# Stream length
echo "Stream Length:" >> logs/redis_evidence.txt
redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem XLEN signals:paper:staging >> logs/redis_evidence.txt
echo "" >> logs/redis_evidence.txt

# Stream info
echo "Stream Info:" >> logs/redis_evidence.txt
redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem XINFO STREAM signals:paper:staging >> logs/redis_evidence.txt
echo "" >> logs/redis_evidence.txt

# Last 20 messages (showing pairs)
echo "Last 20 Messages:" >> logs/redis_evidence.txt
redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem XRANGE signals:paper:staging - + COUNT 20 >> logs/redis_evidence.txt
```

### Step 5: Stop Publisher

**Method 1**: Press `Ctrl+C` in publisher terminal

**Method 2**: Kill process
```bash
# Windows
taskkill /F /IM python.exe

# Unix/Linux
pkill -f run_staging_publisher
```

**Expected Output**:
```
^C
[STOPPED] Staging publisher terminated
Staging stream data preserved for analysis
```

---

## Evidence Checklist

### Required Evidence

- [ ] **Log File**: `logs/staging_publisher_canary.txt` exists
- [ ] **Redis Evidence**: `logs/redis_evidence.txt` exists
- [ ] **Non-BTC/ETH Pairs**: Log shows SOL/USD, ADA/USD, AVAX/USD signals
- [ ] **Stream Growth**: Redis XLEN increased during test
- [ ] **No Errors**: No connection failures or publish errors

### Log Excerpt Requirements

**Must show** at least one signal for each new pair:

```
INFO:agents.core.signal_processor:Processing signal for SOL/USD
INFO:agents.core.signal_processor:Published to signals:paper:staging

INFO:agents.core.signal_processor:Processing signal for ADA/USD
INFO:agents.core.signal_processor:Published to signals:paper:staging

INFO:agents.core.signal_processor:Processing signal for AVAX/USD
INFO:agents.core.signal_processor:Published to signals:paper:staging
```

### Redis Evidence Requirements

**XLEN Output**:
```
(integer) 50  # Or higher (starting from ~6)
```

**XINFO Output** (partial):
```
first-entry
1) "1762649176415-0"
...
length
(integer) 50
...
```

**XRANGE Output** (sample):
```
1) 1) "1762649176471-0"
   2) 1) "pair"
      2) "SOL/USD"
      3) "action"
      4) "BUY"
      5) "price"
      6) "150.25"
      ...

2) 1) "1762649176518-0"
   2) 1) "pair"
      2) "ADA/USD"
      ...
```

---

## Validation Criteria

### ✅ Success Criteria

1. **Publisher Starts**: No errors during initialization
2. **All Pairs Active**: Logs show signals for all 5 pairs (BTC, ETH, SOL, ADA, AVAX)
3. **Stream Growth**: Redis XLEN increases over time
4. **No Connection Errors**: No Redis connection failures
5. **Correct Stream**: All signals go to `signals:paper:staging`
6. **Production Untouched**: `signals:paper` length unchanged

### ❌ Failure Criteria

1. **Startup Failure**: Publisher crashes on start
2. **Missing Pairs**: Only BTC/ETH appear (new pairs not working)
3. **Wrong Stream**: Signals go to `signals:paper` instead of `signals:paper:staging`
4. **Redis Errors**: Connection timeouts or publish failures
5. **Production Contamination**: `signals:paper` length increases

---

## Production Safety Verification

### Before Starting

**Check production stream baseline**:
```bash
redis-cli -u redis://... --tls --cacert config/certs/redis_ca.pem XLEN signals:paper
# Record this number (e.g., 10,009)
```

### After Stopping

**Verify production stream unchanged**:
```bash
redis-cli -u redis://... --tls --cacert config/certs/redis_ca.pem XLEN signals:paper
# Should match baseline (e.g., 10,009)
```

**Check staging stream grew**:
```bash
redis-cli -u redis://... --tls --cacert config/certs/redis_ca.pem XLEN signals:paper:staging
# Should be > 6 (starting value)
```

---

## Troubleshooting

### Issue: No signals appearing for new pairs

**Check 1**: Verify pairs in config
```bash
grep "EXTRA_PAIRS" .env.staging
# Should show: EXTRA_PAIRS=SOL/USD,ADA/USD,AVAX/USD
```

**Check 2**: Check logs for pair loading
```bash
grep "Trading pairs loaded" logs/staging_publisher_canary.txt
# Should show all 5 pairs
```

### Issue: Publisher crashes

**Check 1**: Verify Redis connection
```bash
redis-cli -u redis://... --tls --cacert config/certs/redis_ca.pem PING
# Should return: PONG
```

**Check 2**: Check Python environment
```bash
conda activate crypto-bot
python -c "import agents.core.signal_processor; print('OK')"
```

### Issue: Signals go to wrong stream

**Check 1**: Verify PUBLISH_MODE
```bash
grep "PUBLISH_MODE" .env.staging
# Should show: PUBLISH_MODE=staging
```

**Check 2**: Check logs for stream name
```bash
grep "Published to" logs/staging_publisher_canary.txt
# Should show: signals:paper:staging
```

---

## Commit Evidence

### After successful test:

```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# Add evidence files
git add logs/staging_publisher_canary.txt
git add logs/redis_evidence.txt

# Commit with summary
git commit -m "test(A4): soak test evidence - staging publisher 3-5 min run

Evidence:
- logs/staging_publisher_canary.txt: Publisher output showing all 5 pairs
- logs/redis_evidence.txt: Redis stream evidence (XLEN, XINFO, XRANGE)

Results:
- All pairs active: BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD
- Stream growth: signals:paper:staging increased from 6 to XX messages
- No errors: Clean run, no connection issues
- Production safe: signals:paper unchanged

Duration: X minutes
Status: ✅ PASS

Generated with Claude Code
https://claude.com/claude-code

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Expected Timeline

| Phase | Duration | Activity |
|-------|----------|----------|
| Setup | 1 min | Activate conda, check files |
| Start | 30 sec | Run startup script |
| Soak | 3-5 min | Monitor publisher |
| Collect | 1 min | Save logs, capture Redis evidence |
| Validate | 1 min | Check success criteria |
| **Total** | **6-8 min** | End-to-end |

---

## Next Steps

### After Successful Soak Test

1. ✅ Commit evidence files
2. ✅ Mark A4 as complete
3. ➡️ Proceed to A5 (Rollback Plan)
4. ➡️ Final review of A1-A5
5. ➡️ Await user approval for phase expansion

### If Test Fails

1. ❌ Review failure criteria
2. 🔍 Check troubleshooting section
3. 🛠️ Fix issues
4. 🔄 Re-run test
5. 📝 Document fixes

---

**Status**: Ready to Execute
**Command**: `scripts\run_publisher_staging.bat` or `./scripts/run_publisher_staging.sh`
**Duration**: 3-5 minutes
**Impact**: ZERO on production
