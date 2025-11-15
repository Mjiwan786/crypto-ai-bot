# Paper Trading Validation — Quick Start

**Fast track guide for M1 paper trading validation**

---

## What Is M1 Paper Trading?

**7-14 day paper trading validation** before going live. Must pass ALL criteria:

### Performance (ALL required)
- ✅ Profit Factor ≥ 1.30
- ✅ Sharpe Ratio ≥ 1.0
- ✅ Max Drawdown ≤ 6%
- ✅ Total Trades ≥ 60

### Execution (ALL required)
- ✅ Maker Fill Ratio ≥ 65%
- ✅ Spread Skip Ratio < 25%

### Risk (ALL required)
- ✅ Max Loss Streak ≤ 3
- ✅ Cooldown Violations = 0

---

## Quick Start

### 1. Start Paper Trading

```bash
# Set MODE=PAPER
export MODE=PAPER
export TRADING_PAIR_WHITELIST="XBTUSD"

# Start system
conda activate crypto-bot
python scripts/start_trading_system.py
```

### 2. Monitor Daily

```bash
# Check current validation status
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2024-10-01 \
  --end-date $(date +%Y-%m-%d)
```

### 3. Validate After 7 Days

```bash
# Day 7 validation
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2024-10-01 \
  --end-date 2024-10-08 \
  --output reports/paper_validation_day7.txt

# Check result
cat reports/paper_validation_day7.txt
```

**If PASS**: Continue to day 14
**If FAIL**: Review and adjust

### 4. Final Validation (Day 14)

```bash
# Day 14 final validation
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2024-10-01 \
  --end-date 2024-10-15 \
  --output reports/paper_validation_day14.txt
```

**If PASS**: ✅ Ready for LIVE
**If FAIL**: Continue paper trading

---

## Reading the Report

### Example: ALL PASS

```
M1 - PAPER TRADING VALIDATION REPORT
Period: 2024-10-01 to 2024-10-14
Duration: 14 days (min: 7)

PERFORMANCE CRITERIA
  Profit Factor: 1.65 >= 1.30 → PASS
  Sharpe Ratio: 1.42 >= 1.0 → PASS
  Max Drawdown: 4.20% <= 6.0% → PASS
  Total Trades: 87 >= 60 → PASS
  → Performance: PASS [OK]

EXECUTION QUALITY
  Maker Fill Ratio: 68.97% >= 65.0% → PASS
  Spread Skip Ratio: 18.52% <= 25.0% → PASS
  → Execution: PASS [OK]

RISK CONTROLS
  Max Loss Streak: 2 <= 3 → PASS
  Cooldown Violations: 0 = 0 → PASS
  → Risk: PASS [OK]

OVERALL VERDICT
[OK] ALL CRITERIA PASSED - READY FOR LIVE TRADING
```

### Example: FAIL

```
PERFORMANCE CRITERIA
  Profit Factor: 1.15 >= 1.30 → FAIL
  Total Trades: 45 >= 60 → FAIL
  → Performance: FAIL [X]

OVERALL VERDICT
[X] CRITERIA NOT MET - CONTINUE PAPER TRADING
  - Performance criteria failed
```

---

## Common Failures & Fixes

### Profit Factor < 1.30

**Fix**: Re-optimize parameters
```bash
python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 180d
# Update config with best params
# Restart paper trading
```

### Sharpe < 1.0

**Fix**: Reduce risk/volatility
```yaml
# config/bar_reaction_5m.yaml
strategy:
  risk_per_trade_pct: 0.4  # Lower from 0.6
  sl_atr: 0.5              # Tighter from 0.6
```

### Max Drawdown > 6%

**Fix**: Tighter stops, lower size
```yaml
strategy:
  risk_per_trade_pct: 0.4
  sl_atr: 0.5
```

### Total Trades < 60

**Fix**: Lower triggers, widen ATR
```yaml
strategy:
  trigger_bps_up: 8.0      # Lower from 12.0
  min_atr_pct: 0.20        # Lower from 0.25
```

### Maker Fill Ratio < 65%

**Fix**: Increase queue time
```yaml
backtest:
  queue_bars: 2  # Increase from 1
```

### Spread Skip > 25%

**Fix**: Widen spread cap
```yaml
strategy:
  spread_bps_cap: 12.0  # Widen from 8.0
```

### Loss Streak > 3

**Problem**: Strategy hitting consecutive losses

**Actions**:
- Check if cooldown is working (should pause after 3 losses)
- Review trades during streak
- May need parameter re-optimization
- Consider regime filters

---

## CSV Format (Alternative to Redis)

If not using Redis, track trades in CSV:

### paper_trades.csv

```csv
entry_time,exit_time,pnl,pnl_pct,status,fill_type,initial_capital
2024-10-01 10:00:00,2024-10-01 10:15:00,25.50,0.25,closed,maker,10000
2024-10-01 11:00:00,2024-10-01 11:20:00,-15.00,-0.15,stop_loss,maker,10000
2024-10-01 13:00:00,2024-10-01 13:10:00,40.00,0.40,tp2,maker,10000
```

### paper_signals.csv

```csv
timestamp,action,reason
2024-10-01 10:00:00,signal_generated,
2024-10-01 10:05:00,signal_skipped,spread_too_wide
2024-10-01 11:00:00,signal_generated,
```

### Validate from CSV

```bash
python scripts/validate_paper_trading.py \
  --trades reports/paper_trades.csv \
  --signals reports/paper_signals.csv
```

---

## Cooldown Logic

**Loss Streak Monitor**:
- Tracks consecutive losses
- After **3 consecutive losses** → 30-minute cooldown
- No trading during cooldown
- Resets on first win

**Example**:
```
10:00 → Loss 1 (streak = 1)
10:15 → Loss 2 (streak = 2)
10:30 → Loss 3 (streak = 3) → COOLDOWN UNTIL 11:00
10:45 → Signal → BLOCKED (cooldown violation)
11:00 → Cooldown expires
11:05 → Win → Streak resets to 0
```

**Violations**: Trading during cooldown is a **FAILURE**

---

## Daily Monitoring Workflow

### Morning Check (9:00 AM)

```bash
# Check paper status
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2024-10-01 \
  --end-date $(date +%Y-%m-%d)
```

### Evening Review (5:00 PM)

```bash
# Check trades today
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREAD STREAMS pnl:closed_trades $(date +%s)000-0

# Check current equity
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  GET account:equity
```

### Weekly Validation (Day 7, 14)

```bash
# Full validation
python scripts/validate_paper_trading.py \
  --from-redis \
  --start-date 2024-10-01 \
  --end-date $(date +%Y-%m-%d) \
  --output reports/paper_validation_$(date +%Y%m%d).txt

# Review report
cat reports/paper_validation_$(date +%Y%m%d).txt
```

---

## Go-Live Decision

### After Day 7

**If ALL PASS**:
- ✅ Continue to day 14 for confidence
- Monitor daily for any degradation

**If ANY FAIL**:
- ❌ Review failure reasons
- Apply fixes (see above)
- Restart paper trading from day 0

### After Day 14

**If ALL PASS**:
- ✅ **READY FOR LIVE TRADING**
- Proceed to go-live checklist
- Set MODE=LIVE

**If ANY FAIL**:
- ❌ Continue paper trading
- Re-evaluate strategy
- May need full re-optimization (K1)

---

## Go-Live Checklist

Before setting MODE=LIVE:

- [ ] M1 validation PASSED for 14 days
- [ ] All 3 criteria groups passed (Performance, Execution, Risk)
- [ ] No cooldown violations
- [ ] Safety gates (J1-J3) tested
- [ ] Emergency stop verified
- [ ] Redis monitoring active
- [ ] Grafana dashboards ready
- [ ] Operations runbook reviewed
- [ ] Team notified

**Command**:
```bash
export MODE=LIVE
export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
python scripts/start_trading_system.py
```

---

## Files

| File | Purpose |
|------|---------|
| `monitoring/paper_trading_validator.py` | Validation engine |
| `scripts/validate_paper_trading.py` | Validation script |
| `M1_PAPER_CRITERIA_COMPLETE.md` | Full documentation |
| `reports/paper_validation.txt` | Validation report |

---

**Full Documentation**: `M1_PAPER_CRITERIA_COMPLETE.md`

**Next Steps**: If M1 passes → Go LIVE with full safety gates active

---

**Last Updated**: 2025-10-20

