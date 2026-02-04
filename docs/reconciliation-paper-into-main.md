# Reconciliation: Paper Trading Module into Main

**Date:** 2026-02-04
**Branch:** `chore/reconcile-paper-into-main`
**Source:** `phase2-step2.2-complete-hotfix` (SHA: `334bd83`)

## Background: Why Hotfix Diverged

The `hotfix/pycares-fly-deploy` branch was created to:

1. Fix `pycares` dependency compatibility for Fly.io deployments
2. Develop the paper trading module in parallel with production stability fixes
3. Implement Phase 2 controls (kill switches, dynamic risk enforcement)

The branch accumulated significant paper trading functionality that was deployed
to production via Fly.io while `main` remained stable for other development.

## What Was Imported

### Paper Trading Module (`paper/`)
Core paper trading engine with dynamic risk enforcement:
- `paper/__init__.py` - Module exports
- `paper/engine.py` - Main paper trading engine
- `paper/kill_switch.py` - Kill switch manager (immediate enforcement)
- `paper/publisher.py` - Redis stream publisher for decisions
- `paper/risk_limits_provider.py` - Dynamic risk limits from Redis (15s cache TTL)
- `paper/smoke.py` - Production smoke runner
- `paper/state.py` - Account state manager

### Backtest Module (`backtest/`)
Backtest parity with paper trading:
- `backtest/__init__.py` - Module exports
- `backtest/models.py` - Data models
- `backtest/risk_evaluator.py` - Risk evaluation (shared with paper)
- `backtest/runner.py` - Backtest runner
- `backtest/simulator.py` - Trade simulation

### Strategy Evaluators (`strategies/indicator/`)
Required dependency for paper engine strategy evaluation:
- `strategies/indicator/__init__.py`
- `strategies/indicator/base.py`
- `strategies/indicator/registry.py`
- `strategies/indicator/rsi.py`
- `strategies/indicator/ema.py`
- `strategies/indicator/macd.py`
- `strategies/indicator/breakout.py`
- `strategies/indicator/indicators.py`

### Tests
- `tests/paper/__init__.py`
- `tests/paper/test_dynamic_risk_enforcement.py` - 17 tests
- `tests/test_paper_engine.py` - 17 tests
- `tests/test_backtest_runner.py` - 16 tests
- `tests/fixtures/` - OHLCV and indicator fixtures

## Guarantees

### Redis Key Schemas Unchanged
The following Redis key patterns match production exactly:
- `kill:global:paper` - Global kill switch
- `kill:account:{account_id}` - Account kill switch
- `kill:bot:{bot_id}` - Bot kill switch
- `paper:risk:account:{account_id}` - Account risk limits
- `paper:risk:bot:{bot_id}` - Bot risk limits
- `paper:account:{account_id}:state` - Account state
- `events:paper:controls` - Audit stream

### Behavior Matches Production
- Kill switches: Immediate enforcement
- Risk limits: Dynamic enforcement within 15-second cache TTL
- Fail-safe blocking: Redis errors block trading (RISK_LIMITS_UNAVAILABLE)
- Merge logic: Most restrictive value wins per field

### Dependencies

The imported modules require `shared_contracts` package which is maintained
separately in the monorepo root. Install with:

```bash
pip install -e ../shared_contracts
```

## Test Results

All 50 tests pass:
- `tests/test_paper_engine.py`: 17 passed
- `tests/paper/test_dynamic_risk_enforcement.py`: 17 passed
- `tests/test_backtest_runner.py`: 16 passed

## Next Steps: Fly Cutover Plan

**DO NOT CHANGE FLY DEPLOYMENT SOURCE YET.**

The cutover plan (separate step) will:
1. Merge this PR into main
2. Tag main with production version
3. Update Fly.io deployment to build from main
4. Verify production behavior matches

## Reference

- Hotfix tag: `phase2-step2.2-complete-hotfix`
- Hotfix SHA: `334bd83`
- Main HEAD at import: `6cbdd53`
- Hotfix HEAD at time of reconciliation: `7da18e0`
