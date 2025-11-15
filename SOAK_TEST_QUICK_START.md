# 48-Hour Soak Test - Quick Start Guide

**Status**: ✅ READY TO LAUNCH
**Date**: 2025-11-08
**Mode**: PAPER (48h validation)

---

## 🚀 Launch in 3 Steps (5 minutes)

### Step 1: Start Monitor (Terminal 1)
```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python scripts/soak_test_monitor.py --config config/soak_test_48h_turbo.yaml
```

### Step 2: Start Trading Bot (Terminal 2)
```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python main.py run --config config/soak_test_48h_turbo.yaml --mode paper
```

### Step 3: Verify
```powershell
# Check Prometheus metrics
curl http://localhost:9108/metrics | Select-String -Pattern "current_equity"

# Check Redis streams
redis-cli -u rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 `
  --tls --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem `
  XLEN signals:paper
```

✅ **You're live!** Monitor Terminal 1 for alerts. Let it run for 48 hours.

---

## 📊 What's Running?

### Active Strategies
1. **bar_reaction_5m** (60% capital)
   - 5-minute timeframe
   - Optimized parameters from backtest tuning
   - Config: `config/bar_reaction_5m_aggressive.yaml`

2. **turbo_scalper_15s** (40% capital)
   - 15-second timeframe
   - 5s bars: OFF (auto-enable if latency < 50ms)
   - Config: `config/turbo_scalper_15s.yaml`

### Monitoring
- **Portfolio heat**: Alert if >80%
- **Latency p95**: Alert if >500ms
- **Redis lag**: Alert if >2.0s
- **Circuit breakers**: Alert if >3 trips/hour
- **Checkpoint reports**: Every 6 hours

### Dashboards
- **Bot metrics**: http://localhost:9108/metrics
- **Soak metrics**: http://localhost:9109/metrics
- **Live API**: https://crypto-signals-api.fly.dev/metrics/performance
- **Web dashboard**: https://aipredictedsignals.cloud

---

## ⏰ Timeline

| Time | Action |
|------|--------|
| **T+0h** | Start bot + monitor |
| **T+6h** | Review checkpoint report |
| **T+12h** | *(Optional)* Enable news overrides for 4h test |
| **T+16h** | Disable news overrides |
| **T+24h** | Review checkpoint (halfway) |
| **T+48h** | **Stop bot, run validation** |

---

## ✅ After 48 Hours

### Run Validation
```powershell
# Stop bot (Ctrl+C in both terminals)

# Run validation
python scripts/soak_test_validator.py --config config/soak_test_48h_turbo.yaml
```

### If PASSED ✅
```powershell
# Auto-promote to PROD candidate
python scripts/soak_test_validator.py --config config/soak_test_48h_turbo.yaml --auto-promote

# Files created:
# - config/soak_test_48h_turbo_PROD-CANDIDATE-vXXX.yaml
# - config/soak_test_48h_turbo_PROD_LATEST.yaml
# - reports/prometheus_snapshot_*.json
# - reports/soak_test_48h_*.json
```

**Ready for PRODUCTION!** 🚀

### If FAILED ❌
Review recommendations in validation report:
```powershell
cat reports/soak_test_48h_*.json
```

Adjust parameters and re-run soak test.

---

## 🔴 Emergency Stop

**Ctrl+C in both terminals**

Verify shutdown:
```powershell
Get-Process python
# Should not show soak_test_monitor or main.py
```

---

## 📈 Success Criteria

**ALL must PASS**:
- ✅ Net P&L ≥ $0.01 (positive)
- ✅ Profit Factor ≥ 1.25
- ✅ Circuit Breaker Trips ≤ 3/hour
- ✅ Scalper Lag Messages ≤ 5
- ✅ Portfolio Heat ≤ 80%
- ✅ Latency p95 ≤ 500ms
- ✅ Redis Lag ≤ 2.0s

---

## 📁 Key Files Created

| File | Purpose |
|------|---------|
| `config/soak_test_48h_turbo.yaml` | Main soak test config |
| `config/turbo_scalper_15s.yaml` | Turbo scalper strategy |
| `scripts/soak_test_monitor.py` | Real-time monitoring + alerts |
| `scripts/soak_test_validator.py` | Post-test validation + promotion |
| `SOAK_TEST_RUNBOOK.md` | Full deployment guide (detailed) |
| `SOAK_TEST_QUICK_START.md` | This file (quick reference) |

---

## 🆘 Troubleshooting

### No trades after 1 hour?
```powershell
# Check if signals are being generated
redis-cli -u rediss://... --tls --cacert ... XREVRANGE signals:paper + - COUNT 10

# Check strategy logs
cat logs/soak_test_48h_*.log | Select-String -Pattern "signal"
```

### Monitor not alerting?
```powershell
# Check if monitor is running
Get-Process python | Where-Object {$_.CommandLine -like "*monitor*"}

# Restart monitor if needed
python scripts/soak_test_monitor.py --config config/soak_test_48h_turbo.yaml
```

### Bot crashed?
```powershell
# Check error logs
cat logs/soak_test_48h_*.log | Select-String -Pattern "ERROR"

# Restart bot
python main.py run --config config/soak_test_48h_turbo.yaml --mode paper
```

---

## 📚 Full Documentation

For complete details, see:
- **Deployment Runbook**: `SOAK_TEST_RUNBOOK.md` (comprehensive guide)
- **Performance Metrics**: `PERFORMANCE_METRICS_GUIDE.md`
- **Performance Quick Ref**: `PERFORMANCE_METRICS_QUICK_REFERENCE.md`
- **Optimization Strategy**: `OPTIMIZATION_STRATEGY_FINAL.md`

---

## 🎯 Next Steps After Validation

1. **If PASSED**: Deploy to PRODUCTION with `mode: "LIVE"`
2. **If FAILED**: Review recommendations, adjust parameters, re-test
3. **Monitor PROD closely**: First 10 trades, then first 24 hours
4. **Track performance**: Use live dashboards and performance metrics

---

**Status**: ✅ ALL INFRASTRUCTURE READY
**Action**: Run Step 1-3 above to start your 48-hour soak test!

---

**Last Updated**: 2025-11-08
