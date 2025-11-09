# Multi-Pair Rollout Plan

**Date**: 2025-11-08
**Branch**: `feature/add-trading-pairs`
**Goal**: Add SOL/USD, ADA/USD, AVAX/USD to production safely

---

## Current State

**Production Pairs**: BTC/USD, ETH/USD
**Stream**: `signals:paper` (public demo)
**Status**: ✅ Live and stable

**New Pairs to Add**:
- SOL/USD (Solana)
- ADA/USD (Cardano)
- AVAX/USD (Avalanche)

---

## Staging-First Approach

### Phase 1: Staging Stream Setup (Day 1)

**Stream**: `signals:paper:staging`

1. ✅ Create feature branches in all 3 repos
2. ⏳ Configure `.env.staging` with new pairs
3. ⏳ Test signal publication to staging stream
4. ⏳ Verify Redis stream isolation
5. ⏳ Monitor for 2 hours minimum

**Success Criteria**:
- Signals appear in `signals:paper:staging`
- NO signals appear in `signals:paper` (production isolation)
- All 5 pairs generating signals
- No errors in logs

**Rollback**: Simply stop the staging process - no impact on production

---

### Phase 2: API Support (Day 1-2)

**Changes**: signals-api

1. ⏳ Add staging stream support
2. ⏳ Implement pair filtering
3. ⏳ Add pair metadata endpoint
4. ⏳ Deploy to Fly.io with feature flag (NO restart)

**Success Criteria**:
- `/v1/signals?stream=staging&pair=SOL/USD` works
- Production stream unaffected
- Response time < 200ms

**Rollback**:
```bash
# Disable feature flag via env var
fly secrets set ENABLE_MULTI_PAIR=false
# OR revert deploy
fly deploy --image previous-image-id
```

---

### Phase 3: Website UI (Day 2)

**Changes**: signals-site

1. ⏳ Add pair selector dropdown
2. ⏳ Update signal display with pair badges
3. ⏳ Test with staging API endpoint
4. ⏳ Deploy to Vercel preview

**Success Criteria**:
- Pair selector shows all 5 pairs
- Filtering works correctly
- Mobile responsive
- No UI glitches

**Rollback**:
```bash
# Via Vercel dashboard
git revert <commit-hash>
git push origin feature/add-trading-pairs
```

---

### Phase 4: Canary Rollout (Day 3)

**10% Traffic**: Route 10% of paper stream to new pairs

1. ⏳ Configure weighted stream publishing
2. ⏳ 90% BTC/ETH, 10% SOL/ADA/AVAX
3. ⏳ Monitor for 6 hours
4. ⏳ Check error rates, latency, user feedback

**Success Criteria**:
- Error rate < 0.1%
- Latency increase < 20ms
- No user complaints
- Signal quality maintained

**Rollback**:
```python
# In crypto-ai-bot config
pairs:
  - BTC/USD  # weight: 90
  - ETH/USD  # weight: 90
  - SOL/USD  # weight: 0  ← Disable
```

---

### Phase 5: Full Rollout (Day 4)

**100% Traffic**: All pairs equally weighted

1. ⏳ Update config to equal weights
2. ⏳ Switch staging stream to production stream
3. ⏳ Monitor for 24 hours
4. ⏳ Merge to main branches

**Success Criteria**:
- All metrics stable
- User engagement increases
- No performance degradation
- Backtest results validated

**Rollback**:
```bash
# Emergency: revert to BTC/ETH only
export TRADING_PAIRS=BTC/USD,ETH/USD
pkill -f signal_processor
python -m agents.core.signal_processor
```

---

## Redis Stream Strategy

### Stream Naming Convention

```
signals:paper:staging  ← Phase 1-3 (isolated testing)
signals:paper          ← Phase 4-5 (production)
signals:live           ← UNTOUCHED (real trading)
```

### Stream Isolation

**Staging Stream**:
- Completely separate from production
- Can be deleted/reset without impact
- Used for integration testing

**Production Stream**:
- Only modified after staging validation
- Gradual rollout with canary
- Monitored 24/7

**Live Stream**:
- NEVER TOUCHED during this rollout
- Remains BTC/USD, ETH/USD only
- Separate approval process required

---

## Verification Commands

### Check Staging Stream

```bash
# Connect to Redis
redis-cli -u redis://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem

# List streams
KEYS signals:*

# Check staging stream
XLEN signals:paper:staging
XRANGE signals:paper:staging - + COUNT 10

# Verify pair distribution
XREAD COUNT 100 STREAMS signals:paper:staging 0 | grep "pair"
```

### Check Production Isolation

```bash
# Ensure no new pairs in production stream
XRANGE signals:paper - + COUNT 100 | grep -E "SOL|ADA|AVAX"
# Should return nothing during Phase 1-3
```

### Monitor Signal Quality

```bash
# Count signals per pair (staging)
python scripts/analyze_stream.py --stream signals:paper:staging --metric pair_distribution

# Expected output:
# BTC/USD: 40 signals
# ETH/USD: 35 signals
# SOL/USD: 25 signals
# ADA/USD: 20 signals
# AVAX/USD: 18 signals
```

---

## Rollback Procedures

### Emergency Rollback (Any Phase)

**Symptoms**: High error rate, latency spike, user complaints

**Action**:
```bash
# 1. Stop staging publisher
cd crypto-ai-bot
conda activate crypto-bot
pkill -f signal_processor

# 2. Revert to production config
cp .env.paper .env
export TRADING_PAIRS=BTC/USD,ETH/USD

# 3. Restart with prod pairs only
python -m agents.core.signal_processor

# 4. Flush staging stream (optional)
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem
DEL signals:paper:staging
```

**Verification**:
```bash
# Check only BTC/ETH in production stream
XRANGE signals:paper - + COUNT 20 | grep pair
```

---

### Partial Rollback (Remove One Pair)

**Example**: SOL/USD causing issues

```bash
# Update config
export TRADING_PAIRS=BTC/USD,ETH/USD,ADA/USD,AVAX/USD  # Removed SOL
# Restart without full stop
python -m agents.core.signal_processor --reload
```

---

## Monitoring Checklist

### Pre-Rollout (Before Phase 1)

- [ ] All 3 repos on feature branches
- [ ] `.env.staging` configured
- [ ] Redis stream isolated
- [ ] Backups of production configs
- [ ] Rollback scripts tested

### During Phase 1 (Staging)

- [ ] `signals:paper:staging` receiving data
- [ ] All 5 pairs generating signals
- [ ] Production stream unchanged
- [ ] No error spikes
- [ ] Latency < 100ms

### During Phase 4 (Canary)

- [ ] 10% traffic to new pairs
- [ ] Error rate monitored
- [ ] User feedback collected
- [ ] Performance metrics stable

### Post-Rollout (Phase 5+)

- [ ] All pairs in production
- [ ] Metrics dashboard updated
- [ ] Documentation complete
- [ ] Backtests validated
- [ ] User guides updated

---

## Success Metrics

| Metric | Baseline (BTC/ETH) | Target (5 Pairs) | Acceptable Range |
|--------|-------------------|------------------|------------------|
| **Avg Latency** | 85ms | < 120ms | 80-150ms |
| **Error Rate** | 0.05% | < 0.15% | < 0.2% |
| **Signals/Hour** | 40-60 | 100-150 | 80-180 |
| **Win Rate** | 54.5% | > 50% | 48-60% |
| **User Engagement** | 100% | +30% | +15-50% |

---

## Timeline

| Phase | Duration | Start | End | Status |
|-------|----------|-------|-----|--------|
| **Phase 1**: Staging | 4 hours | Day 1 09:00 | Day 1 13:00 | ⏳ |
| **Phase 2**: API | 6 hours | Day 1 14:00 | Day 1 20:00 | ⏳ |
| **Phase 3**: Website | 4 hours | Day 2 09:00 | Day 2 13:00 | ⏳ |
| **Phase 4**: Canary | 12 hours | Day 3 09:00 | Day 3 21:00 | ⏳ |
| **Phase 5**: Full Rollout | 24 hours | Day 4 09:00 | Day 5 09:00 | ⏳ |
| **Backtest All Pairs** | TBD | After approval | - | ⏳ |

**Total**: 3-4 days from start to production

---

## Communication Plan

### Stakeholders

**Internal Team**:
- Notify before each phase
- Share metrics after each phase
- Escalate any issues immediately

**Users (if applicable)**:
- Announce new pairs after Phase 5
- Highlight in Discord/Twitter
- Update documentation

---

## Next Steps

1. ✅ Create `.env.staging`
2. ⏳ Test signal publisher with staging stream
3. ⏳ Verify Redis isolation
4. ⏳ Proceed to Phase 2 after validation

---

**Status**: Phase 1 Setup Complete
**Next**: Test staging signal publisher
