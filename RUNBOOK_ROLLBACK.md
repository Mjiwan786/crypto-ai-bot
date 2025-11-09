# Rollback Runbook - Staging Publisher

**Purpose**: Emergency rollback procedures for staging publisher
**Scope**: Local publisher process only (no Fly.io or production streams affected)
**Impact**: ZERO on production systems

---

## Quick Rollback (One-Liner)

### Stop Staging Publisher

**Windows**:
```cmd
taskkill /F /FI "WINDOWTITLE eq *staging*" 2>nul || echo "No staging publisher running"
```

**Unix/Linux**:
```bash
pkill -f run_staging_publisher || echo "No staging publisher running"
```

**Result**: Local process killed, staging stream data preserved, **no prod streams touched**.

---

## Detailed Rollback Procedures

### 1. Stop Publisher Process

#### Method A: Graceful Shutdown (Recommended)

**Action**: Press `Ctrl+C` in publisher terminal

**Expected Output**:
```
^C
INFO:agents.core.signal_processor:Shutdown signal received
INFO:agents.core.signal_processor:Stopping gracefully...
[STOPPED] Staging publisher terminated
Staging stream data preserved for analysis
```

**Duration**: 1-2 seconds

#### Method B: Force Kill

**Windows PowerShell**:
```powershell
# Find process
tasklist | Select-String python

# Kill by name
taskkill /F /IM python.exe

# Or kill by PID
taskkill /F /PID <pid>
```

**Unix/Linux**:
```bash
# Find process
ps aux | grep run_staging_publisher

# Kill by name
pkill -f run_staging_publisher

# Or kill by PID
kill -9 <pid>
```

**Duration**: Immediate

### 2. Verify Process Stopped

**Windows**:
```cmd
tasklist | findstr python
```

**Unix/Linux**:
```bash
ps aux | grep run_staging_publisher
```

**Expected**: No results (process terminated)

---

## Data Rollback (Optional)

### Option A: Preserve Staging Data (Recommended)

**Action**: Do nothing

**Result**: Staging stream data remains for analysis

**Reason**: Useful for debugging and verification

### Option B: Delete Staging Stream

**Warning**: This deletes all staging test data

**Command**:
```bash
redis-cli -u redis://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  DEL signals:paper:staging
```

**Verification**:
```bash
# Should return 0
redis-cli -u redis://... --tls --cacert config/certs/redis_ca.pem \
  XLEN signals:paper:staging
```

---

## Code Rollback (If Needed)

### Scenario: Feature flags causing issues

#### Revert to Specific Commit

**Find last good commit**:
```bash
git log --oneline
```

**Revert A2 changes** (if feature flags problematic):
```bash
git revert 7e56946  # A2 commit hash
git push origin feature/add-trading-pairs
```

#### Return to Main Branch

**Abandon feature branch**:
```bash
git checkout main
git branch -D feature/add-trading-pairs
```

**Impact**: ZERO (feature branch only, no production code affected)

---

## Verification After Rollback

### 1. Confirm Publisher Stopped

```bash
# Windows
tasklist | findstr python
# Should be empty or no staging publisher

# Linux
ps aux | grep run_staging_publisher
# Should be empty
```

### 2. Verify Production Streams Untouched

**Check signals:paper** (public demo):
```bash
redis-cli -u redis://... --tls --cacert config/certs/redis_ca.pem \
  XLEN signals:paper
# Compare to baseline (should be unchanged)
```

**Check signals:live** (real trading):
```bash
redis-cli -u redis://... --tls --cacert config/certs/redis_ca.pem \
  XLEN signals:live
# Compare to baseline (should be unchanged)
```

### 3. Verify No Fly.io Impact

**Check deployed app**:
```bash
# No deployment occurred from A1-A5
# Fly.io app still running production code
fly status
```

---

## Impact Assessment

### What Rollback Affects

| Component | Impact | Recovery |
|-----------|--------|----------|
| Local publisher process | ✅ Stopped | Instant |
| signals:paper:staging | ⚠️ Preserved (or deleted if opted) | N/A |
| Feature branch commits | ✅ Revertable | git revert |

### What Rollback Does NOT Affect

| Component | Status | Confirmation |
|-----------|--------|--------------|
| signals:paper (production) | ✅ Untouched | XLEN unchanged |
| signals:live (real trading) | ✅ Untouched | XLEN unchanged |
| Fly.io deployment | ✅ Untouched | No deploy triggered |
| Main branch | ✅ Untouched | No merges performed |
| Production configs | ✅ Untouched | No .env changes |

---

## Emergency Contacts (If Needed)

### Self-Service Checks

1. **Redis health**:
   ```bash
   redis-cli -u redis://... --tls --cacert config/certs/redis_ca.pem PING
   ```
   Expected: `PONG`

2. **Fly.io app health**:
   ```bash
   fly status
   fly checks list
   ```
   Expected: All checks passing

3. **Production signal flow**:
   ```bash
   # Check recent production signals
   curl "https://crypto-signals-api.fly.dev/v1/signals?mode=paper&limit=5"
   ```
   Expected: JSON array with recent signals

---

## Rollback Scenarios

### Scenario 1: Publisher Won't Stop

**Symptoms**:
- Ctrl+C doesn't work
- Process hangs

**Solution**:
```bash
# Force kill
taskkill /F /IM python.exe   # Windows
kill -9 <pid>                # Linux
```

### Scenario 2: Wrong Stream Published To

**Symptoms**:
- Signals going to `signals:paper` instead of `signals:paper:staging`

**Immediate Action**:
```bash
# 1. Stop publisher immediately
pkill -f run_staging_publisher

# 2. Check PUBLISH_MODE
grep PUBLISH_MODE .env.staging
# Should show: PUBLISH_MODE=staging

# 3. Verify production stream didn't grow
redis-cli ... XLEN signals:paper
```

**Recovery**:
1. Fix `.env.staging` (ensure `PUBLISH_MODE=staging`)
2. Review logs to confirm contamination extent
3. If contamination occurred, contact maintainer

### Scenario 3: Redis Connection Lost

**Symptoms**:
- Publisher errors: "Connection refused"
- Can't reach Redis

**Solution**:
```bash
# 1. Stop publisher
pkill -f run_staging_publisher

# 2. Test Redis connectivity
redis-cli -u redis://... --tls --cacert config/certs/redis_ca.pem PING

# 3. Check certificate
ls -la config/certs/redis_ca.pem

# 4. Wait for Redis recovery or check network
```

---

## Post-Rollback Actions

### Immediate (< 1 minute)

- [ ] Verify publisher process stopped
- [ ] Confirm no errors in terminal
- [ ] Check production streams unchanged

### Short-term (< 5 minutes)

- [ ] Review logs for root cause
- [ ] Document issue in `INCIDENTS_LOG.md`
- [ ] Determine if re-run needed

### Medium-term (< 1 hour)

- [ ] Fix underlying issue (if identified)
- [ ] Update runbook with lessons learned
- [ ] Re-test if changes made

---

## Prevention

### Before Running Publisher

1. ✅ Verify `.env.staging` has `PUBLISH_MODE=staging`
2. ✅ Test Redis connection first (dry-run)
3. ✅ Check production stream baselines
4. ✅ Use startup script (includes safety checks)

### During Publisher Run

1. ✅ Monitor logs for errors
2. ✅ Check staging stream growth (not production)
3. ✅ Keep terminal visible for quick Ctrl+C

### After Publisher Run

1. ✅ Verify production streams unchanged
2. ✅ Review logs for anomalies
3. ✅ Document test results

---

## FAQ

### Q: What if I accidentally published to production stream?

**A**:
1. Stop publisher immediately (Ctrl+C or kill)
2. Check extent: `redis-cli ... XLEN signals:paper`
3. If small contamination (<10 signals), note it and continue
4. If large contamination, contact maintainer for stream cleanup

**Prevention**: Always use startup script (validates PUBLISH_MODE=staging)

### Q: Can I delete staging stream and start over?

**A**: Yes, zero impact on production
```bash
redis-cli ... DEL signals:paper:staging
# Then re-run publisher
```

### Q: What if Fly.io app goes down during staging test?

**A**: Staging test is local only - Fly.io status doesn't affect it. Publisher publishes to Redis Cloud directly.

### Q: How do I know if rollback was successful?

**A**:
1. Publisher process not running ✅
2. signals:paper XLEN unchanged from baseline ✅
3. signals:live XLEN unchanged from baseline ✅
4. No ongoing Redis writes from publisher ✅

---

## Rollback Checklist

### Pre-Rollback

- [ ] Note current state (running/stopped, errors present, etc.)
- [ ] Record production stream lengths (baseline)

### During Rollback

- [ ] Stop publisher process (Ctrl+C or kill)
- [ ] Verify process terminated
- [ ] (Optional) Delete staging stream if needed

### Post-Rollback Verification

- [ ] Publisher process stopped
- [ ] signals:paper length matches baseline
- [ ] signals:live length matches baseline
- [ ] No orphaned Python processes
- [ ] Terminal shows clean stop message

### Documentation

- [ ] Log rollback reason in `INCIDENTS_LOG.md`
- [ ] Update this runbook if new scenario discovered
- [ ] Note lessons learned for next attempt

---

## Summary

**Rollback Command**: `Ctrl+C` or `pkill -f run_staging_publisher`

**Impact**: Local process only, **no prod streams touched**

**Recovery Time**: < 1 minute

**Data Loss**: None (staging data preserved unless explicitly deleted)

**Risk Level**: **ZERO** (staging is completely isolated)

---

**Last Updated**: 2025-11-08
**Maintained By**: Claude Code + User
**Related Docs**: A1-A5 implementation guides
