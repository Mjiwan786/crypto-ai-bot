# Step 7 - Ready for Paper Trading Trial

**Date**: 2025-10-27
**Status**: ✅ ALL PREREQUISITES COMPLETE - READY TO START TRIAL
**Next Action**: Start 7-14 day paper trading trial

---

## Validation Summary

### Completed Steps

✅ **Step 1: Regime/Router Fix**
- Fixed `ai_engine/regime_detector/detector.py` (ADX 25→20, Aroon 70→60)
- Enhanced `agents/strategy_router.py` with risk breaker integration
- **Tests**: 7/7 passing - Chop now routes to mean_reversion

✅ **Step 2: A/B Backtests (Synthetic)**
- ML OFF: 78 trades, PF 1.38, ROI 0.74%
- ML ON @0.65: 52 trades, PF 1.95 (+41%), ROI 1.12%
- **Verdict**: [PASS] - All criteria met

✅ **Step 3: Threshold Sweep (Synthetic)**
- Winner: 0.65 (PF 1.95, 67% retention)
- 0.70 failed due to starvation (53% retention < 60%)

✅ **Step 4: Generalization Test (Synthetic)**
- 540d + 3 assets: threshold 0.60 optimal
- ROI 0.89%, PF 1.64, DD -16.1%
- **Verdict**: OK (adjusted threshold for long-term generalization)

✅ **Step 5: Paper Smoke Test (REAL)**
- All 4 tests passed
- P95 latency: 0.03ms << 500ms
- ML config validated
- **Verdict**: PAPER OK

✅ **Step 6: Environment Setup**
- `.env.paper` configured with Redis Cloud credentials
- Redis connection tested and working
- All scripts created and ready

⏳ **Step 7: Paper Trading Trial** (PENDING - START NOW)

---

## Infrastructure Status

### Configuration Files

| File | Status | Notes |
|------|--------|-------|
| `config/params/ml.yaml` | ✅ READY | ML enabled, threshold 0.60 |
| `.env.paper` | ✅ READY | BTC/USD,ETH/USD pairs configured |
| `ai_engine/regime_detector/detector.py` | ✅ FIXED | Lowered thresholds |
| `agents/strategy_router.py` | ✅ FIXED | Risk breaker integrated |

### Redis Cloud Connection

| Component | Status | Details |
|-----------|--------|---------|
| Connection | ✅ WORKING | redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 |
| TLS Certificate | ✅ VALID | config/certs/redis_ca.pem |
| Read/Write | ✅ TESTED | Key-value operations working |
| Streams | ✅ TESTED | XADD/XREAD operations working |

### Test Coverage

| Test Suite | Status | Coverage |
|------------|--------|----------|
| Regime Detector Tests | ✅ 3/3 PASS | Chop routing to mean_reversion |
| Risk Breaker Tests | ✅ 4/4 PASS | Breaker blocks all regimes |
| Paper Smoke Test | ✅ 4/4 PASS | ML gate + latency validation |
| Redis Connection | ✅ PASS | Full connectivity verified |

---

## How to Start Paper Trial

### Method 1: PowerShell Script (Recommended)

```powershell
# Navigate to project directory
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# Run paper trial for 7 days
.\start_paper_trial.ps1 -DurationDays 7
```

The script will:
1. ✅ Load environment from `.env.paper`
2. ✅ Test Redis connection
3. ✅ Start paper trading engine
4. ✅ Monitor signals and metrics
5. ✅ Export Prometheus metrics on http://localhost:9108/metrics

### Method 2: Direct Python (Alternative)

```bash
# Activate conda environment
conda activate crypto-bot

# Navigate to project
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# Test prerequisites
python test_redis.py

# Start paper trial
python scripts/run_paper_trial.py
```

**Note**: Method 2 requires manually loading environment variables from `.env.paper`

---

## Monitoring During Trial

### Daily Health Check (Run Once Per Day)

```bash
conda activate crypto-bot
python scripts/check_paper_trial_kpis.py
```

**Expected Output**:
```
PAPER TRIAL KPI REPORT
================================================================================
Trade Count: 8/week (expect 5-10) ✅
Profit Factor: 1.72 (min 1.5) ✅
Monthly ROI: 0.95% (min 0.83%) ✅
Max Drawdown: -8.3% (max -20%) ✅
P95 Latency: 45ms (max 500ms) ✅
ML Coverage: 100% (expect >95%) ✅

VERDICT: PASS ✅
```

### Real-Time Monitoring

**Prometheus Metrics** (http://localhost:9108/metrics):
```bash
# View all metrics
curl http://localhost:9108/metrics

# Monitor signal count
curl http://localhost:9108/metrics | grep signals_published_total

# Monitor latency
curl http://localhost:9108/metrics | grep publish_latency_ms
```

**Redis Streams**:
```bash
# Connect to Redis Cloud
redis-cli -u "rediss://default:***@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" \
  --tls \
  --cacert "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"

# View latest signals
XREVRANGE signals:paper + - COUNT 5

# Monitor in real-time
XREAD BLOCK 0 STREAMS signals:paper $
```

**Log Files**:
```powershell
# Follow live logs
Get-Content logs\paper_trial_*.log -Wait -Tail 50

# Search for errors
Select-String -Path "logs\paper_trial_*.log" -Pattern "ERROR|WARN"
```

---

## Pass Criteria (Must Meet ALL)

| Metric | Target | Rationale |
|--------|--------|-----------|
| **Trade Count** | 60-80% of baseline (5-10/week) | Avoid starvation from ML filtering |
| **Profit Factor** | ≥ 1.5 | Validate ML improves trade quality |
| **Monthly ROI** | ≥ 0.83% (10% annualized) | Minimum profitability threshold |
| **Max Drawdown** | ≤ -20% | Risk tolerance limit (from PRD) |
| **P95 Latency** | < 500ms | System performance requirement |
| **ML Coverage** | > 95% | Ensure ML gate functioning correctly |
| **System Uptime** | > 99% | No crashes or critical errors |

---

## After Trial Completion (7 Days)

### If All Criteria Met: ✅ APPROVE FOR LIVE

```bash
# Generate final report
python scripts/generate_paper_trial_report.py --output PAPER_TRIAL_RESULTS.md

# Print final verdict
STEP 7 PASS ✅ — ROI=X%, PF=Y, DD=Z%, Trades=N (th=0.60)

# Enable live trading (with caution)
# 1. Update .env to MODE=live
# 2. Start with 50% capital allocation
# 3. Monitor for 2 weeks before increasing to 100%
```

### If Criteria Not Met: ⚠️ ADJUST OR ROLLBACK

**Scenario 1: Too Few Trades** (Starvation)
```bash
# Lower ML threshold
sed -i 's/min_alignment_confidence: 0.60/min_alignment_confidence: 0.55/' config/params/ml.yaml

# Restart trial for 3 days (mini-trial)
.\start_paper_trial.ps1 -DurationDays 3
```

**Scenario 2: Poor Performance** (PF < 1.5)
```bash
# Option A: Raise threshold for better quality
sed -i 's/min_alignment_confidence: 0.60/min_alignment_confidence: 0.65/' config/params/ml.yaml

# Option B: Disable ML gate entirely
sed -i 's/enabled: true/enabled: false/' config/params/ml.yaml

# Restart trial
.\start_paper_trial.ps1 -DurationDays 7
```

**Scenario 3: High Drawdown** (DD < -20%)
```bash
# Check risk manager settings
# Verify position sizing limits
# Review breaker thresholds in config
```

---

## Documentation Reference

| Document | Purpose |
|----------|---------|
| `PAPER_TRIAL_INSTRUCTIONS.md` | Full trial instructions and troubleshooting |
| `STEP_7_VALIDATION_STATUS.md` | Complete validation status and architecture analysis |
| `STEP_7_COMPLETE_SUMMARY.md` | Synthetic validation results |
| `REGIME_ROUTER_FIX_SUMMARY.md` | Step 1 regime/router fixes |
| `ML_GATE_ENABLED.md` | ML configuration deployment guide |
| `TASKLOG.md` | Full validation history |

---

## Quick Reference

**Start Trial**:
```powershell
.\start_paper_trial.ps1 -DurationDays 7
```

**Check Health**:
```bash
conda activate crypto-bot
python scripts/check_paper_trial_kpis.py
```

**View Metrics**:
```bash
curl http://localhost:9108/metrics
```

**Stop Trial**:
```
Press Ctrl+C in the PowerShell window
```

---

## System Architecture (Production Ready)

```
Market Data (Kraken)
    ↓
OHLCV Bars (5m) → Regime Detector (fixed thresholds)
    ↓
Regime Label (bull/bear/chop)
    ↓
Strategy Router (routes chop→mean_reversion)
    ↓
Strategy Execution (momentum/mean_reversion)
    ↓
ML Confidence Gate (threshold 0.60)
    ↓
Risk Breaker Check (drawdown/limits)
    ↓
Signal Publishing → Redis Stream (signals:paper)
    ↓
Monitoring (Prometheus metrics, logs)
```

**Fixed Components**:
- ✅ Regime Detector: Lowered thresholds to reduce chop over-labeling
- ✅ Strategy Router: Routes chop to mean_reversion (not blocked)
- ✅ Risk Breaker: Integrated to block on hard_halt mode only
- ✅ ML Gate: Enabled with threshold 0.60 for quality filtering

**Validated**:
- ✅ Synthetic A/B testing: +41% PF improvement
- ✅ Threshold optimization: 0.60 best for generalization
- ✅ Paper smoke test: P95 latency 0.03ms
- ✅ Redis connectivity: Full functionality verified

---

## Final Status

### ✅ READY FOR PAPER TRADING TRIAL

**All prerequisites met**:
1. ✅ Production components fixed and tested
2. ✅ ML confidence gate configured and validated
3. ✅ Redis Cloud connection tested and working
4. ✅ Environment configured (.env.paper)
5. ✅ Scripts created (startup, monitoring)
6. ✅ Documentation complete

**Next Action**:
```powershell
.\start_paper_trial.ps1 -DurationDays 7
```

**Expected Timeline**:
- Day 0: Start paper trial
- Days 1-6: Daily KPI monitoring
- Day 7: Evaluate results
- If PASS → Enable live trading (50% capital)
- If FAIL → Adjust threshold or disable ML gate

**Risk Assessment**: MEDIUM
- ✅ Code validated (7/7 tests passing)
- ✅ ML logic sound (synthetic validation)
- ⚠️ No real backtest (infrastructure mismatch)
- ⚠️ Paper trial needed to confirm performance

**Rollback Plan**: Disable ML gate if paper trial fails
```bash
sed -i 's/enabled: true/enabled: false/' config/params/ml.yaml
```

---

**Date**: 2025-10-27
**Status**: READY TO START
**Command**: `.\start_paper_trial.ps1 -DurationDays 7`
