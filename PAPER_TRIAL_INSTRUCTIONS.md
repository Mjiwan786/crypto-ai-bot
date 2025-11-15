# Paper Trading Trial Instructions - Step 7 Validation

**Duration**: 7-14 days
**Purpose**: Validate ML confidence gate performance in live-like conditions before enabling real trading
**Status**: Ready to start

---

## Quick Start

### Option 1: PowerShell Script (Recommended)

```powershell
# Start 7-day paper trial
.\start_paper_trial.ps1 -DurationDays 7
```

The script will:
1. Load environment from `.env.paper`
2. Test Redis connection
3. Start paper trading engine
4. Monitor signals and metrics

### Option 2: Manual Start

```bash
# Activate conda environment
conda activate crypto-bot

# Set environment variables
$env:REDIS_URL = "rediss://default:***@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
$env:REDIS_CA_CERT = "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"
$env:MODE = "paper"
$env:TRADING_PAIRS = "BTC/USD,ETH/USD"
$env:TIMEFRAMES = "5m"

# Start paper trial
python scripts/run_paper_trial.py
```

---

## Monitoring

### Daily Health Check

Run daily to check if paper trial is on track:

```bash
conda activate crypto-bot
python scripts/check_paper_trial_kpis.py
```

**Expected Output**:
```
✅ PAPER TRIAL: PASS

KEY PERFORMANCE INDICATORS:
  Trade Count: 8 (expect 5-10 per week)
  Profit Factor: 1.72 (min 1.5) ✅
  Monthly ROI: 0.95% (min 0.83%) ✅
  Max Drawdown: -8.3% (max -20%) ✅
  P95 Latency: 45ms (max 500ms) ✅
  ML Coverage: 100.0% (expect >95%) ✅
```

### Real-Time Monitoring

#### 1. Prometheus Metrics

```bash
# View metrics endpoint
curl http://localhost:9108/metrics

# Monitor specific metrics
curl http://localhost:9108/metrics | grep signals_published
curl http://localhost:9108/metrics | grep publish_latency
curl http://localhost:9108/metrics | grep breaker
```

**Key Metrics**:
- `signals_published_total` - Total signals generated
- `publish_latency_ms_bucket` - Latency distribution (check P95)
- `breaker_trips_total` - Circuit breaker activations
- `stream_lag_seconds` - Redis stream lag

#### 2. Redis Streams

```bash
# Connect to Redis Cloud
redis-cli -u "rediss://default:***@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" --tls --cacert "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"

# Check latest signals
XREVRANGE signals:paper + - COUNT 5

# Monitor stream length
XLEN signals:paper

# Monitor in real-time
XREAD BLOCK 0 STREAMS signals:paper $
```

**Expected Signal Format**:
```json
{
  "symbol": "BTC/USD",
  "side": "long",
  "entry_price": 67500.0,
  "confidence": 0.72,
  "strategy": "momentum",
  "sl_price": 67100.0,
  "tp_price": 68200.0,
  "metadata": {
    "ml_confidence": 0.72,
    "ml_enabled": true,
    "ml_threshold": 0.60
  }
}
```

#### 3. Log Files

```bash
# View latest log
Get-ChildItem logs\paper_trial_*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content -Tail 50

# Follow live logs (PowerShell)
Get-Content logs\paper_trial_*.log -Wait

# Search for errors
Select-String -Path "logs\paper_trial_*.log" -Pattern "ERROR|WARN"
```

---

## Pass Criteria

The paper trial must meet ALL criteria for approval to live trading:

| Metric | Target | Reason |
|--------|--------|--------|
| **Trade Count** | 60-80% of baseline (5-10/week) | Avoid starvation, ensure ML not too restrictive |
| **Profit Factor** | ≥ 1.5 | Validate ML improves trade quality |
| **Monthly ROI** | ≥ 0.83% (10% annualized) | Minimum profitability threshold |
| **Max Drawdown** | ≤ -20% | Risk tolerance limit |
| **P95 Latency** | < 500ms | System performance requirement |
| **ML Coverage** | > 95% | Ensure ML gate functioning |
| **System Uptime** | > 99% | No crashes or errors |

---

## Troubleshooting

### Issue: No Trades Generated

**Symptoms**: `signals_published_total` = 0 after 24 hours

**Diagnosis**:
```bash
# Check regime detection
grep "TA regime" logs/paper_trial_*.log | tail -20

# Check ML filtering
grep "ml_confidence" logs/paper_trial_*.log | tail -20
```

**Solutions**:
1. **If all regimes = "chop"**: Regime detector too strict
   ```bash
   # Already fixed in Step 1, but verify:
   grep "adx_trend_threshold" ai_engine/regime_detector/detector.py
   # Should be 20.0, not 25.0
   ```

2. **If ML filtering all signals**: Threshold too high
   ```bash
   # Lower threshold 0.60 → 0.55
   sed -i 's/min_alignment_confidence: 0.60/min_alignment_confidence: 0.55/' config/params/ml.yaml

   # Restart paper trial
   ```

3. **If no market data**: Check Kraken connection
   ```bash
   python -c "import ccxt; k = ccxt.kraken(); print(k.fetch_ohlcv('BTC/USD', '5m', limit=5))"
   ```

---

### Issue: Poor Performance (PF < 1.5)

**Symptoms**: Win rate < 50% or losing money

**Diagnosis**:
```bash
# Analyze trades
python scripts/analyze_paper_trades.py

# Check if ML actually helping
grep "ml_confidence" logs/paper_trial_*.log | sort -t'=' -k2 -n
```

**Solutions**:
1. **ML not selective enough**: Raise threshold
   ```bash
   # Increase threshold 0.60 → 0.65
   sed -i 's/min_alignment_confidence: 0.60/min_alignment_confidence: 0.65/' config/params/ml.yaml
   ```

2. **Regime routing broken**: Check strategy router
   ```bash
   # Verify chop → mean_reversion routing
   python -m pytest tests/test_router_chop_allows_range.py -v
   ```

3. **Risk breaker not working**: Verify breaker integration
   ```bash
   # Check breaker tests
   python -m pytest tests/test_breaker_blocks_all.py -v
   ```

---

### Issue: High Latency (P95 > 500ms)

**Symptoms**: Slow signal generation

**Diagnosis**:
```bash
# Check latency distribution
curl http://localhost:9108/metrics | grep publish_latency_ms_bucket
```

**Solutions**:
1. **Reduce OHLCV window**: Lower from 300 to 150 bars
2. **Optimize indicators**: Check if any slow calculations
3. **Check system resources**: CPU/memory usage

---

### Issue: Redis Connection Errors

**Symptoms**: `ConnectionError: Error connecting to Redis`

**Diagnosis**:
```bash
# Test Redis connection
redis-cli -u "rediss://default:***@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" --tls --cacert "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem" PING
```

**Solutions**:
1. **Check certificate**: Verify `redis_ca.pem` exists and is valid
2. **Check credentials**: Verify password in REDIS_URL
3. **Check firewall**: Ensure port 19818 not blocked
4. **Check Redis Cloud status**: Visit Redis Cloud dashboard

---

## Decision Tree After Trial

```
After 7 Days:
│
├─ All criteria met?
│  ├─ YES → ✅ APPROVE FOR LIVE TRADING
│  │         - Update mode: paper → live
│  │         - Start with 50% capital allocation
│  │         - Monitor for 2 weeks
│  │         - Increase to 100% if stable
│  │
│  └─ NO → Evaluate failures:
│     │
│     ├─ Too few trades (starvation)?
│     │  └─ Lower threshold (0.60 → 0.55) and retry 3 days
│     │
│     ├─ Poor PF/ROI?
│     │  ├─ If PF 1.2-1.4: Raise threshold (0.60 → 0.65)
│     │  └─ If PF < 1.2: ❌ DISABLE ML GATE
│     │                  (enabled: true → false)
│     │
│     ├─ High drawdown?
│     │  └─ Check risk manager settings
│     │     - Verify position sizing
│     │     - Check breaker thresholds
│     │
│     └─ Technical issues?
│        └─ Fix and restart trial
```

---

## Final Approval Process

### After Successful Paper Trial (All Criteria Met):

1. **Generate Final Report**:
   ```bash
   python scripts/generate_paper_trial_report.py --output PAPER_TRIAL_RESULTS.md
   ```

2. **Review Metrics**:
   - Total trades: Should be 40-80 (7-14 days)
   - PF: ≥ 1.5
   - Monthly ROI: ≥ 0.83%
   - Max DD: ≤ -20%
   - ML coverage: > 95%

3. **Print Final Verdict**:
   ```
   STEP 7 PASS ✅ — ROI=0.95%, PF=1.72, DD=-8.3%, Trades=56 (th=0.60)
   ```

4. **Enable Live Trading** (with caution):
   ```bash
   # Update mode in config
   sed -i 's/MODE=paper/MODE=live/' .env

   # Start with reduced capital
   sed -i 's/CAPITAL=10000/CAPITAL=5000/' .env  # 50% allocation

   # Start live trading
   python scripts/start_trading_system.py --mode live --confirm
   ```

5. **Monitor Live Trading** (first 2 weeks):
   - Daily KPI checks
   - Weekly performance review
   - Increase capital allocation if stable

---

## Rollback Plan

### If Paper Trial Fails:

**Option 1: Disable ML Gate**
```bash
# Revert to regime/router fixes only (no ML)
sed -i 's/enabled: true/enabled: false/' config/params/ml.yaml

# Restart paper trial without ML
.\start_paper_trial.ps1 -DurationDays 7
```

**Option 2: Adjust Threshold**
```bash
# Lower threshold for more trades
sed -i 's/min_alignment_confidence: 0.60/min_alignment_confidence: 0.55/' config/params/ml.yaml

# Or raise threshold for better quality
sed -i 's/min_alignment_confidence: 0.60/min_alignment_confidence: 0.65/' config/params/ml.yaml

# Restart with new threshold
.\start_paper_trial.ps1 -DurationDays 3  # Mini-trial to test adjustment
```

**Option 3: Fix Infrastructure**
```bash
# If fundamental issues found (e.g., backtest mismatch)
# 1. Fix production code
# 2. Re-run Step 7 validation
# 3. Restart paper trial
```

---

## Files and Resources

**Configuration**:
- `.env.paper` - Environment variables for paper mode
- `config/params/ml.yaml` - ML confidence gate settings

**Scripts**:
- `start_paper_trial.ps1` - Start paper trial (PowerShell)
- `scripts/run_paper_trial.py` - Main paper trading engine
- `scripts/check_paper_trial_kpis.py` - Daily health check
- `scripts/monitor_paper_trial.py` - Real-time monitoring

**Logs**:
- `logs/paper_trial_*.log` - Detailed system logs

**Metrics**:
- `http://localhost:9108/metrics` - Prometheus metrics endpoint

**Documentation**:
- `STEP_7_VALIDATION_STATUS.md` - Full validation status
- `STEP_7_COMPLETE_SUMMARY.md` - Synthetic validation results
- `PAPER_TRIAL_INSTRUCTIONS.md` - This file

---

## Support

**Common Questions**:

**Q: How long should I run the paper trial?**
A: Minimum 7 days, recommended 14 days for statistical significance.

**Q: Can I stop and restart the trial?**
A: Yes, but metrics will reset. Better to let it run continuously.

**Q: What if I need to change ML threshold mid-trial?**
A: Acceptable for mini-trials (3 days) to test adjustments. For final approval, run full 7-day trial with chosen threshold.

**Q: Can I run multiple trials in parallel?**
A: No, only one paper trial should run at a time to avoid resource conflicts.

**Q: What happens if my computer restarts?**
A: Paper trial will stop. Restart with `.\start_paper_trial.ps1`. Consider using a VPS for uninterrupted trials.

---

**Next Steps**: Run `.\start_paper_trial.ps1` to begin validation
