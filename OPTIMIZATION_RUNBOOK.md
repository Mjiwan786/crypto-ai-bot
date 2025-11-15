# P&L Optimization Runbook
**Goal**: Improve 12-month P&L from +0.36% to ≥25% while keeping Max DD ≤12%

## Success Gates (ALL must pass)
- ✅ Profit Factor ≥ 1.35
- ✅ Sharpe ≥ 1.2 (net of fees/slippage)
- ✅ Max DD ≤ 12%
- ✅ Net Return ≥ +25% / 12mo
- ✅ 48h live dry-run positive expectancy, heat <8%

---

## Current Baseline (FAILED)
From `out/latest.json` and `out/bar_reaction.json`:

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| **Total Return** | -99.91% | +25% | ❌ FAIL |
| **Profit Factor** | 0.47 | ≥1.35 | ❌ FAIL |
| **Max DD** | -100% | ≤12% | ❌ FAIL |
| **Win Rate** | 27.9% | ~50% | ❌ FAIL |
| **Sharpe** | 4.41* | ≥1.2 | ❌ MISLEADING |
| **Expectancy** | -$0.55 | >$0 | ❌ FAIL |

*Sharpe misleading due to death spiral

---

## Root Cause Analysis

### 1. Death Spiral (Position Sizing)
**Problem**: Proportional sizing compounds losses
- Start: $10,000 @ 0.8% risk = $80 position
- After -50% loss: $5,000 @ 0.8% = $40 position
- After -75% loss: $2,500 @ 0.8% = $20 position
- Eventually: Positions too small to recover

**Fix**: Add `min_position_usd` floor

### 2. Low Win Rate (27.9%)
**Problem**: 12bps trigger = noise trades on 5m bars
- Bid-ask spread ~5bps
- Normal volatility ~10bps
- 12bps threshold catches too much noise

**Fix**: Increase to 18bps+ for quality signals

### 3. Profit Factor 0.47 (Losses 2x Wins)
**Problem**:
- Stop: 0.8 ATR = $80
- Target: 1.25 ATR = $125
- R:R = 1.56:1 (theoretical)
- But tight stop hit more often → actual R:R inverted

**Fix**:
- Widen stop to 1.2 ATR
- Stretch target to 2.0-3.5 ATR
- Better R:R = 2.5:1 minimum

### 4. No Regime Filtering
**Problem**: Trading in chop/sideways (50% of time)
- Momentum strategy fails in chop
- Gets whipsawed repeatedly

**Fix**: Only trade bull/bear regimes with confidence >0.55

---

## Optimization Iterations

### Iteration 1: Survival (Prevent Death Spiral)
**Config**: `config/bar_reaction_5m_aggressive.yaml`

**Changes**:
1. ✅ `min_position_usd: 50.0` (prevent shrinking to zero)
2. ✅ `max_position_usd: 2000.0` (cap max exposure)
3. ✅ `trigger_bps: 18.0` (reduce noise)
4. ✅ `sl_atr: 1.2` (wider stops)
5. ✅ `tp1_atr: 2.0, tp2_atr: 3.5` (better R:R)
6. ✅ `max_daily_loss_pct: 8.0` (circuit breaker)

**Expected**: Profit Factor 0.8-1.1, DD ~15%, still not passing

### Iteration 2: Quality Signals
**Additional Changes**:
1. ✅ Enable regime filtering (`allowed_regimes: ["bull", "bear"]`)
2. ✅ Increase trigger to 22bps
3. ✅ Add `min_regime_confidence: 0.55`
4. ✅ Reduce max daily trades to 20

**Expected**: Profit Factor 1.2-1.4, DD ~10%, Win Rate 40-45%

### Iteration 3: Fine-Tuning (If needed)
**Knobs to Adjust**:
- `trigger_bps`: ±2-3 bps (trades vs quality tradeoff)
- `sl_atr`: ±0.1-0.2 (win rate vs R:R)
- `risk_per_trade_pct`: ±0.2% (returns vs DD)
- `min_regime_confidence`: ±0.05 (trade frequency)

**Iteration Loop**:
```bash
# 1. Update config
# 2. Backtest 180d
python scripts/run_backtest_v2.py --pairs BTC/USD,ETH/USD --lookback 180 --capital 10000 --report out/iter_X.json

# 3. Check gates
python scripts/validate_gates.py out/iter_X.json

# 4. If fail → adjust smallest-blast-radius knob
# 5. Repeat until all gates GREEN
```

---

## Backtest Commands

### Baseline (Current)
```bash
python scripts/run_backtest.py \\
  --config config/bar_reaction_5m.yaml \\
  --lookback 180 \\
  --capital 10000 \\
  --report out/baseline_current.json
```

### Iteration 1 (Aggressive)
```bash
python scripts/run_backtest.py \\
  --config config/bar_reaction_5m_aggressive.yaml \\
  --lookback 180 \\
  --capital 10000 \\
  --report out/iter1_aggressive.json

# Also run 365d for annual validation
python scripts/run_backtest.py \\
  --config config/bar_reaction_5m_aggressive.yaml \\
  --lookback 365 \\
  --capital 10000 \\
  --report out/iter1_aggressive_365d.json
```

### Success Gate Validation
```bash
# Extract metrics and check against gates
python scripts/validate_gates.py \\
  out/iter1_aggressive.json \\
  --pf-min 1.35 \\
  --sharpe-min 1.2 \\
  --dd-max 12.0 \\
  --return-min 25.0
```

---

## Parameter Sensitivity Matrix

| Parameter | Current | Iter1 | Conservative | Turbo | Impact |
|-----------|---------|-------|--------------|-------|--------|
| `trigger_bps` | 13 | 18 | 22 | 15 | Trade frequency |
| `sl_atr` | 0.8 | 1.2 | 1.5 | 1.0 | Win rate vs R:R |
| `tp1_atr` | 1.25 | 2.0 | 1.8 | 2.5 | Profit per win |
| `risk_pct` | 0.8 | 1.0 | 0.6 | 1.5 | Returns vs DD |
| `max_dd_pct` | 20 | 12 | 10 | 15 | Safety limit |
| `regime_filter` | off | on | on | on | Trade quality |

**Tuning Rules**:
1. **If DD > 12%**: Increase `trigger_bps`, decrease `risk_pct`, enable `regime_filter`
2. **If PF < 1.35**: Widen `sl_atr`, stretch `tp_atr`, add regime filter
3. **If Sharpe < 1.2**: Reduce trade frequency (higher `trigger_bps`)
4. **If Return < 25% but PF/DD good**: Increase `risk_pct` or `max_concurrent_positions`

---

## Live Dry-Run (48h)

After backtests pass:

```bash
# 1. Deploy to paper trading
export BOT_MODE=PAPER
export LIVE_TRADING_CONFIRMATION=""
export CONFIG_PATH=config/bar_reaction_5m_aggressive.yaml

python scripts/run_paper_trial.py --duration 48h

# 2. Monitor in real-time
python scripts/monitor_paper_trial.py

# 3. Check KPIs after 48h
python scripts/check_paper_trial_kpis.py \\
  --start-date $(date -d '48 hours ago' +%Y-%m-%d) \\
  --output reports/paper_trial_48h.json
```

**48h Success Criteria**:
- ✅ Positive P&L or within -2% (expectancy confirmed)
- ✅ Max heat (unrealized DD) < 8%
- ✅ No safety circuit breakers triggered
- ✅ Fill quality: >80% maker fills
- ✅ Latency: <500ms p95

---

## Emergency Rollback

If live system shows issues:

```bash
# 1. Immediate stop
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \\
  SET 'killswitch:active' 'true'

# 2. Revert config
git checkout config/bar_reaction_5m.yaml

# 3. Redeploy baseline
fly deploy --ha=false
```

---

## Deliverables

### crypto-ai-bot
- ✅ `config/bar_reaction_5m_aggressive.yaml` - New config
- ✅ `strategies/bar_reaction_5m.py` - Position sizing fix (min_position_usd)
- ✅ `strategies/regime_filter.py` - Regime filtering logic
- ✅ `scripts/validate_gates.py` - Automated gate checking
- ✅ Tests for new features
- ✅ Updated README/RUNBOOK

### signals-api
- ✅ Add `config_version` field to signals
- ✅ Expose `/metrics/backtest_results` endpoint
- ✅ Update schema for new signal fields

### signals-site
- ✅ Display active config version
- ✅ Show live P&L vs targets
- ✅ Alert when gates exceeded

---

## Timeline

1. **Hour 0-2**: Implement Iteration 1 changes + tests
2. **Hour 2-3**: Run backtests (180d + 365d)
3. **Hour 3-4**: Validate gates, iterate if needed
4. **Hour 4-5**: Deploy to paper trading
5. **Hour 5-53**: Monitor 48h dry-run
6. **Hour 53-54**: Final validation
7. **Hour 54+**: Go LIVE if all gates GREEN

**Iteration Budget**: 2-3 iterations expected to hit gates

---

**Last Updated**: 2025-11-08
**Owner**: Quant/DevOps Team
**Status**: Ready for Iteration 1 execution
