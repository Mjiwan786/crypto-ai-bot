# Production Rollout Plan - Safe & Fast Deployment

**Objective:** Deploy trading system to production with rigorous validation and risk controls

Based on PRD_AGENTIC.md Section 10 - Rollout Plan

---

## Overview

This rollout follows a 4-phase approach with strict quality gates at each stage:

1. **Backtest Validation** - Historical performance verification
2. **Paper Trading** - 7-14 days live simulation
3. **Live Canary** - 10-20% size for 3-5 days
4. **Full Scale** - Gradual ramp to target risk

---

## Phase 1: Backtest Validation (Today)

### Objective
Verify strategy performance on historical data meets production thresholds.

### Parameters

```bash
Strategy: regime_based_router (adaptive strategy selection)
Pairs: BTC/USD, ETH/USD, SOL/USD
Timeframe: 3m (180 candles/hour, maker-only)
Lookback: 180 days
Fees:
  - Maker: 16 bps (Kraken default tier)
  - Taker: 0 bps (maker-only execution)
Slippage: 1 bps
Risk per trade: 0.8%
Spread cap: 8 bps (skip entry if spread > 8bps)
```

### Quality Gates (MUST PASS)

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| Profit Factor | ≥ 1.3 | Wins 30% larger than losses |
| Sharpe Ratio | ≥ 1.0 | Risk-adjusted returns |
| Max Drawdown | ≤ 6% | Capital preservation |
| Num Trades | ≥ 40 | Statistical significance |

### Execution

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Run backtest with exact rollout parameters
python scripts/run_backtest.py \
  --strategy regime_router \
  --pairs "BTC/USD,ETH/USD,SOL/USD" \
  --timeframe 3m \
  --lookback 180d \
  --maker_bps 16 \
  --taker_bps 0 \
  --slippage_bps 1 \
  --risk_per_trade_pct 0.8 \
  --spread_bps_cap 8

# 3. Validate quality gates
python scripts/B6_quality_gates.py

# 4. Review results
cat reports/backtest_summary.csv
cat reports/quality_gates.txt
```

### Success Criteria

- ✅ All pairs pass quality gates
- ✅ Backtest summary saved to `reports/backtest_summary.csv`
- ✅ Quality gates report shows "PASS [OK]"
- ✅ No critical errors in backtest execution

### If Gates FAIL

**DO NOT PROCEED TO PAPER TRADING**

Actions:
1. Review backtest results in detail
2. Identify failing metrics
3. Options:
   - Adjust strategy parameters
   - Reduce risk per trade
   - Tighten spread cap
   - Change timeframe
   - Re-run backtest
4. Must pass gates before proceeding

---

## Phase 2: Paper Trading (7-14 Days)

### Objective
Validate strategy in live market conditions without risk.

### Prerequisites

- ✅ Phase 1 backtest passed all quality gates
- ✅ Go-live controls tested
- ✅ Monitoring infrastructure operational
- ✅ Redis Cloud connection verified

### Configuration

```bash
# Environment: Staging (paper mode)
ENVIRONMENT=staging
MODE=PAPER
TRADING_MODE=PAPER

# Safety: Emergency stop inactive
KRAKEN_EMERGENCY_STOP=false

# Pairs: Same as backtest
TRADING_PAIR_WHITELIST=XBTUSD,ETHUSD,SOLUSD

# Notional caps: Conservative
NOTIONAL_CAPS=XBTUSD:5000,ETHUSD:3000,SOLUSD:2000
```

### Execution

```bash
# 1. Set environment variables
export ENVIRONMENT=staging
export MODE=PAPER
export TRADING_MODE=PAPER

# 2. Start paper trading
python main.py

# Or use start script:
python scripts/start_trading_system.py --mode paper

# 3. Monitor in separate terminals
# Terminal 1: Real-time streams
python scripts/monitor_redis_streams.py --tail

# Terminal 2: Health checks
watch -n 300 "python scripts/monitor_redis_streams.py --health"

# Terminal 3: Dashboard
python scripts/monitor_redis_streams.py
```

### Monitoring Metrics (Track Daily)

| Metric | Target | Alert If |
|--------|--------|----------|
| Profit Factor | ≥ 1.3 | < 1.2 for 3+ days |
| Sharpe Ratio | ≥ 1.0 | < 0.8 for 3+ days |
| Max Drawdown | ≤ 6% | > 6% any time |
| Num Trades | ≥ 40 over period | < 3 per day average |
| Win Rate | ~50-60% | < 40% for 3+ days |
| Circuit Breakers | < 5 per day | > 10 per day |
| Emergency Stops | 0 | Any unplanned activation |

### Success Criteria

After 7-14 days:
- ✅ PF ≥ 1.3
- ✅ Sharpe ≥ 1.0
- ✅ MaxDD ≤ 6%
- ✅ ≥ 40 trades total
- ✅ No system errors
- ✅ Circuit breakers < 5/day average
- ✅ Consistent signal generation

### If Metrics FAIL

**DO NOT PROCEED TO LIVE**

Actions:
1. Analyze failure mode:
   - Strategy not performing? Adjust parameters
   - Too many circuit breakers? Increase thresholds
   - Low trade count? Check entry filters
2. Extend paper trading period
3. Consider reducing risk per trade
4. Must meet all criteria before LIVE

---

## Phase 3: Live Canary (3-5 Days)

### Objective
Test LIVE execution with minimal capital risk.

### Prerequisites

- ✅ Phase 2 paper trading passed all metrics
- ✅ Team approval obtained
- ✅ Emergency procedures documented
- ✅ Kill-switch tested
- ✅ Kraken API credentials verified

### Configuration

```bash
# Environment: Production (live mode)
ENVIRONMENT=production
MODE=LIVE
TRADING_MODE=LIVE

# CRITICAL: LIVE confirmation required
LIVE_TRADING_CONFIRMATION=I-accept-the-risk

# Kraken credentials
KRAKEN_API_KEY=[your_key]
KRAKEN_API_SECRET=[your_secret]

# Canary sizing: 10-20% of target
# If target risk_per_trade = 0.8%, use 0.1-0.2% for canary
risk_per_trade_pct=0.15  # 20% of 0.8%

# Conservative caps for canary
TRADING_PAIR_WHITELIST=XBTUSD,ETHUSD  # Start with 2 pairs only
NOTIONAL_CAPS=XBTUSD:1000,ETHUSD:500  # Small size
```

### Execution

```bash
# 1. Final safety check
python scripts/monitor_redis_streams.py --health

# 2. Set LIVE mode
export TRADING_MODE=LIVE
export LIVE_TRADING_CONFIRMATION=I-accept-the-risk

# 3. Dry run validation
python scripts/start_trading_system.py --mode live --dry-run

# 4. Start LIVE trading
python scripts/start_trading_system.py --mode live

# 5. MONITOR CONTINUOUSLY
# Terminal 1: Live signals
python scripts/monitor_redis_streams.py --tail --streams signals:live kraken:status

# Terminal 2: Emergency ready
redis-cli -u $REDIS_URL
# Keep ready to: SET kraken:emergency:kill_switch true
```

### Monitoring (CONTINUOUS during canary)

- ⚠️ **Monitor every trade** for first 24 hours
- ⚠️ Verify fills are at expected prices
- ⚠️ Check spreads are within 8bps cap
- ⚠️ Confirm maker rebates being earned (not taking)
- ⚠️ Watch for slippage anomalies

### Success Criteria

After 3-5 days:
- ✅ All trades executed successfully
- ✅ No unexpected slippage
- ✅ Fills near mid-price (maker-only)
- ✅ PF ≥ 1.3 maintained
- ✅ Sharpe ≥ 1.0 maintained
- ✅ MaxDD ≤ 6%
- ✅ No emergency stops triggered

### If Issues Occur

**Immediate Actions:**
1. Activate emergency stop: `redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true`
2. Close all positions manually via Kraken UI
3. Document the issue in `INCIDENTS_LOG.md`
4. Investigate root cause
5. Fix and re-test in paper mode
6. Do NOT proceed to full scale

---

## Phase 4: Full Scale (Gradual Ramp)

### Objective
Scale to full target risk over 2-4 weeks.

### Prerequisites

- ✅ Phase 3 canary completed successfully
- ✅ All metrics maintained
- ✅ Team confidence high
- ✅ No incidents during canary

### Scaling Schedule

| Week | Risk % | Notional Cap (XBTUSD) | Notes |
|------|--------|----------------------|-------|
| 1 | 0.2% | $2,000 | Canary continued |
| 2 | 0.4% | $4,000 | 2x scale-up |
| 3 | 0.6% | $7,000 | Monitor closely |
| 4+ | 0.8% | $10,000 | Target size |

### Scaling Rules

1. **Only scale if:**
   - PF ≥ 1.3 for previous week
   - Sharpe ≥ 1.0 for previous week
   - MaxDD ≤ 6% cumulative
   - No major incidents

2. **Pause scaling if:**
   - Any metric falls below threshold
   - > 3 circuit breakers in one day
   - Unexpected market conditions
   - Exchange issues

3. **Reduce size if:**
   - PF < 1.2 for 3+ days
   - Sharpe < 0.8 for 3+ days
   - MaxDD > 5% in one day
   - Emergency stop triggered

### Full Scale Configuration

```bash
# Final production configuration
ENVIRONMENT=production
MODE=LIVE
TRADING_MODE=LIVE
LIVE_TRADING_CONFIRMATION=I-accept-the-risk

# Full pairs
TRADING_PAIR_WHITELIST=XBTUSD,ETHUSD,SOLUSD

# Target caps
NOTIONAL_CAPS=XBTUSD:10000,ETHUSD:7000,SOLUSD:5000

# Target risk
risk_per_trade_pct=0.8
```

---

## Safety Controls (All Phases)

### Pre-Flight Checklist

Before ANY phase:
- [ ] Health check passes
- [ ] Redis connection verified
- [ ] Emergency stop procedures reviewed
- [ ] Monitoring dashboards open
- [ ] Kill-switch commands ready
- [ ] Team notified
- [ ] Incident log template ready

### During Operations

- ✅ Monitor `signals:*` streams continuously
- ✅ Watch `metrics:circuit_breakers` for anomalies
- ✅ Check `kraken:status` for exchange issues
- ✅ Review `metrics:emergency` for unexpected stops
- ✅ Daily performance review
- ✅ Weekly risk review

### Emergency Stop Triggers

Automatically activate if:
- Rate limit violations
- WebSocket disconnections
- Kraken exchange issues

Manually activate if:
- Metrics degrading (PF < 1.1, Sharpe < 0.7)
- Unexpected market behavior
- >10 circuit breakers in 1 hour
- Any system malfunction

### Emergency Stop Procedure

```bash
# 1. IMMEDIATE: Activate kill-switch
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# 2. Verify active
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch
# Expected: "true"

# 3. Close positions (manually via Kraken UI if needed)

# 4. Document incident
echo "$(date): Emergency stop - [reason]" >> INCIDENTS_LOG.md

# 5. Investigate and resolve

# 6. Only deactivate when safe
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch
```

---

## Rollback Plan

### Phase 2 → Phase 1
- Stop paper trading: `Ctrl+C` or kill process
- Re-run backtest with adjusted parameters
- Pass quality gates before re-starting paper

### Phase 3 → Phase 2
- Activate emergency stop
- Close all LIVE positions
- Switch to PAPER mode
- Investigate issues
- Re-validate in paper for 3-5 days

### Phase 4 → Phase 3 or 2
- Reduce position sizes to canary levels
- If issues persist, return to paper mode
- Full diagnostic review

---

## Success Metrics Tracking

### Daily Log Template

```
Date: YYYY-MM-DD
Phase: [1/2/3/4]
Mode: [BACKTEST/PAPER/LIVE]

Performance:
- Profit Factor: X.XX
- Sharpe Ratio: X.XX
- Max Drawdown: X.XX%
- Trades: XX

System Health:
- Circuit Breakers: X
- Emergency Stops: X
- Errors: X

Notes:
- [Any observations]

Status: [ON TRACK / NEEDS ATTENTION / ISSUE]
```

### Phase Transition Checklist

Before moving to next phase:
- [ ] All metrics meet thresholds
- [ ] Full period completed (no shortcuts)
- [ ] Team review conducted
- [ ] Risks documented
- [ ] Emergency procedures tested
- [ ] Monitoring verified
- [ ] Approval obtained

---

## Tools & Commands

### Health Check
```bash
python scripts/monitor_redis_streams.py --health
```

### View Dashboard
```bash
python scripts/monitor_redis_streams.py
```

### Tail Streams
```bash
python scripts/monitor_redis_streams.py --tail
```

### Emergency Stop
```bash
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true
```

### Check Mode
```bash
redis-cli -u $REDIS_URL GET ACTIVE_SIGNALS
```

---

## Timeline Estimate

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 1: Backtest | 1 day | Day 1 |
| Phase 2: Paper | 7-14 days | Day 8-15 |
| Phase 3: Canary | 3-5 days | Day 11-20 |
| Phase 4: Scale | 2-4 weeks | Day 25-48 |

**Total:** 4-7 weeks from start to full production

---

## Documentation References

| Document | Purpose |
|----------|---------|
| `ROLLOUT_PLAN.md` | This file - complete rollout guide |
| `OPERATIONS_RUNBOOK.md` | Daily operations procedures |
| `EMERGENCY_KILLSWITCH_QUICKREF.md` | Emergency procedures |
| `QUICKSTART_OPERATIONS.md` | Quick start guide |
| `GO_LIVE_CONTROLS.md` | Technical go-live documentation |
| `INCIDENTS_LOG.md` | Incident tracking |
| `MAINTENANCE_LOG.md` | Maintenance history |

---

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2025-10-18 | 1.0 | Initial rollout plan |

---

**REMEMBER:** Safety first. Never skip phases. If in doubt, return to paper mode.

**Emergency Contact:** [See OPERATIONS_RUNBOOK.md]
