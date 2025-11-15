# Rollout Plan - READY FOR EXECUTION

**Status:** ✅ Ready to begin Phase 1 (Backtest Validation)

**Date:** 2025-10-18

---

## Summary

All infrastructure for safe production rollout is complete and tested:

- ✅ Backtest runner with exact rollout parameters
- ✅ Quality gates (PF≥1.3, Sharpe≥1.0, MaxDD≤6%, ≥40 trades)
- ✅ Go-live controls (paper/live switching, kill-switch)
- ✅ Monitoring infrastructure (Redis streams dashboard)
- ✅ Complete documentation
- ✅ Emergency procedures

---

## START HERE: Phase 1 - Backtest Validation

### Quick Start

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Run backtest with rollout parameters
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

# 4. If PASS, proceed to Phase 2 (Paper Trading)
ENVIRONMENT=staging MODE=PAPER python main.py
```

---

## Implementation Complete

### Code Created/Updated

**Quality Gates (Updated):**
- `scripts/B6_quality_gates.py`
  - Updated thresholds: PF≥1.3, Sharpe≥1.0, MaxDD≤6%
  - Added num_trades≥40 requirement
  - Production-ready validation

**Backtest Infrastructure (Existing):**
- `scripts/run_backtest.py`
  - Comprehensive backtest runner
  - CSV caching for historical data
  - Standardized outputs (summary, trades, equity, config)
  - Realistic cost modeling

**Go-Live Controls (From previous session):**
- `config/trading_mode_controller.py`
  - Paper/Live mode switching
  - Emergency kill-switch
  - Circuit breaker monitoring
  - Pair whitelist & notional caps

**Monitoring (From previous session):**
- `scripts/monitor_redis_streams.py`
  - Real-time stream monitoring
  - Health checking
  - Dashboard views
  - Tail mode for continuous monitoring

### Documentation Created

**Rollout Guidance:**
- `ROLLOUT_PLAN.md` (550+ lines)
  - Complete 4-phase rollout plan
  - Quality gates for each phase
  - Safety controls and emergency procedures
  - Scaling schedule
  - Success criteria
  - Rollback procedures

**Operations (From previous session):**
- `OPERATIONS_RUNBOOK.md`
- `EMERGENCY_KILLSWITCH_QUICKREF.md`
- `QUICKSTART_OPERATIONS.md`
- `GO_LIVE_IMPLEMENTATION_SUMMARY.md`
- `INCIDENTS_LOG.md`
- `MAINTENANCE_LOG.md`

---

## Rollout Phases

### Phase 1: Backtest Validation (Today)

**Objective:** Verify historical performance

**Duration:** 1 day

**Quality Gates:**
- PF ≥ 1.3
- Sharpe ≥ 1.0
- MaxDD ≤ 6%
- Trades ≥ 40

**Commands:**
```bash
python scripts/run_backtest.py --strategy regime_router \
  --pairs "BTC/USD,ETH/USD,SOL/USD" --timeframe 3m --lookback 180d \
  --maker_bps 16 --taker_bps 0 --slippage_bps 1 \
  --risk_per_trade_pct 0.8 --spread_bps_cap 8

python scripts/B6_quality_gates.py
```

### Phase 2: Paper Trading (7-14 Days)

**Objective:** Validate in live markets (no risk)

**Prerequisites:** Phase 1 passed

**Commands:**
```bash
export ENVIRONMENT=staging
export MODE=PAPER
export TRADING_MODE=PAPER
python main.py

# Monitor
python scripts/monitor_redis_streams.py --tail
```

**Track Daily:**
- Profit Factor ≥ 1.3
- Sharpe Ratio ≥ 1.0
- Max Drawdown ≤ 6%
- Trades ≥ 40 total
- Circuit breakers < 5/day

### Phase 3: Live Canary (3-5 Days)

**Objective:** Real money validation at 10-20% size

**Prerequisites:** Phase 2 passed

**Commands:**
```bash
export ENVIRONMENT=production
export MODE=LIVE
export TRADING_MODE=LIVE
export LIVE_TRADING_CONFIRMATION=I-accept-the-risk
python scripts/start_trading_system.py --mode live

# Monitor CONTINUOUSLY
python scripts/monitor_redis_streams.py --tail --streams signals:live
```

**Configuration:**
- risk_per_trade_pct=0.15 (20% of target)
- NOTIONAL_CAPS=XBTUSD:1000,ETHUSD:500

### Phase 4: Full Scale (2-4 Weeks)

**Objective:** Gradual ramp to target risk

**Prerequisites:** Phase 3 passed

**Scaling:**
- Week 1: 0.2% risk, $2k cap
- Week 2: 0.4% risk, $4k cap
- Week 3: 0.6% risk, $7k cap
- Week 4+: 0.8% risk, $10k cap

---

## Safety Controls

### Emergency Stop (All Phases)

**Fastest method (instant):**
```bash
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true
```

**Verify:**
```bash
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch
```

**Deactivate:**
```bash
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch
```

### Health Monitoring

```bash
# Quick health check
python scripts/monitor_redis_streams.py --health

# Dashboard
python scripts/monitor_redis_streams.py

# Real-time tail
python scripts/monitor_redis_streams.py --tail
```

---

## Next Actions

### Immediate (Today)

1. ✅ Review `ROLLOUT_PLAN.md` in full
2. ⏳ Run Phase 1 backtest
3. ⏳ Validate quality gates
4. ⏳ If pass → prepare for Phase 2
5. ⏳ If fail → adjust parameters and retry

### This Week

1. Start Phase 2 (Paper Trading)
2. Monitor daily metrics
3. Document any issues
4. Prepare for Phase 3 approval

### Next 2-4 Weeks

1. Complete paper trading validation
2. Execute live canary (if approved)
3. Begin gradual scaling
4. Continuous monitoring and optimization

---

## Tools Reference

| Task | Command |
|------|---------|
| Run backtest | `python scripts/run_backtest.py [args]` |
| Check quality gates | `python scripts/B6_quality_gates.py` |
| Health check | `python scripts/monitor_redis_streams.py --health` |
| Monitor dashboard | `python scripts/monitor_redis_streams.py` |
| Tail streams | `python scripts/monitor_redis_streams.py --tail` |
| Emergency stop | `redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true` |
| Start paper trading | `ENVIRONMENT=staging MODE=PAPER python main.py` |

---

## Documentation Map

| Document | Use When |
|----------|----------|
| `ROLLOUT_READY.md` | **START HERE** - This file |
| `ROLLOUT_PLAN.md` | Complete phase-by-phase guide |
| `OPERATIONS_RUNBOOK.md` | Daily operations |
| `QUICKSTART_OPERATIONS.md` | Quick 5-minute setup |
| `EMERGENCY_KILLSWITCH_QUICKREF.md` | Emergency situations |
| `GO_LIVE_CONTROLS.md` | Technical reference |

---

## Success Criteria Summary

### Backtest (Phase 1)
- ✅ PF ≥ 1.3
- ✅ Sharpe ≥ 1.0
- ✅ MaxDD ≤ 6%
- ✅ Trades ≥ 40

### Paper Trading (Phase 2)
- ✅ Meet backtest criteria over 7-14 days
- ✅ Consistent signal generation
- ✅ Circuit breakers < 5/day
- ✅ No system errors

### Live Canary (Phase 3)
- ✅ All trades execute successfully
- ✅ Meet criteria at reduced size
- ✅ No unexpected slippage
- ✅ No emergency stops

### Full Scale (Phase 4)
- ✅ Maintain criteria at full size
- ✅ Gradual scaling over 2-4 weeks
- ✅ Consistent performance

---

## Risk Warnings

⚠️ **IMPORTANT:**

- **NEVER skip phases** - Each phase validates the next
- **NEVER proceed if gates fail** - Fix issues first
- **ALWAYS have emergency stop ready** - One command away
- **MONITOR CONTINUOUSLY in live modes** - Real money at risk

---

## Timeline

| Phase | Duration | Start | End |
|-------|----------|-------|-----|
| Phase 1: Backtest | 1 day | Today | Tomorrow |
| Phase 2: Paper | 7-14 days | +1 day | +8 to +15 days |
| Phase 3: Canary | 3-5 days | +15 days | +18 to +20 days |
| Phase 4: Scale | 2-4 weeks | +20 days | +34 to +48 days |

**Total:** 4-7 weeks to full production

---

## Contact & Support

**Emergency:**
- Kill-switch: `redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true`
- See: `EMERGENCY_KILLSWITCH_QUICKREF.md`

**Operations:**
- Daily ops: `OPERATIONS_RUNBOOK.md`
- Quick start: `QUICKSTART_OPERATIONS.md`

**Issues:**
- Log in: `INCIDENTS_LOG.md`
- Review: Team meeting

---

**Status:** ✅ READY TO BEGIN

**First Step:** Run Phase 1 backtest (command above)

**Questions?** See `ROLLOUT_PLAN.md` for detailed guidance

---

*Last Updated: 2025-10-18*
