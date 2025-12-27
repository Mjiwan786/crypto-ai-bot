# STEP 1 — Prep & Context Pack: COMPLETE ✅

## Summary

Senior Python/AI architect analysis of `crypto-ai-bot` repo completed. A comprehensive 6-PR implementation plan has been prepared based on PRD.md requirements, without writing any code.

---

## Deliverables

### 1. **IMPLEMENTATION_PLAN.md**
Comprehensive 6-PR implementation plan with:
- **Executive Summary**: $10k → $15k goal, regime-adaptive strategies, AI/ML support, Redis publishing
- **Gap Analysis**: 8 missing modules identified and documented
- **6-PR Plan**: Detailed scope, file paths, tests, success criteria for each PR
- **Quick Reference**: Redis Cloud connection, conda env, file paths

### 2. **TASKLOG.md**
Task tracking skeleton with:
- Detailed checklist for each PR (1-6)
- Acceptance criteria per PRD §15
- Run history template for tracking test results
- Environment setup reference
- Dependencies between PRs

---

## Analysis Results

### Current State (What Exists)
✅ **Config plane**: Unified loaders, hot-reload, caching, agent integration
- `config/unified_config_loader.py`
- `config/optimized_config_loader.py`
- `config/agent_integration.py`

✅ **Data plane**: Kraken WS client, Redis streams, OHLCV buckets, rate limits
- `utils/kraken_ws.py`
- `config/exchange_configs/kraken.yaml`
- `config/exchange_configs/kraken_rate_limits.py`

✅ **Partial AI engine**: Regime detector stub, strategy selector with fusion
- `ai_engine/regime_detector/__init__.py` (stub only)
- `ai_engine/strategy_selector.py` (TA/Macro/Sentiment fusion working)
- `ai_engine/regime_detector/deep_ta_analyzer.py`
- `ai_engine/regime_detector/macro_analyzer.py`
- `ai_engine/regime_detector/sentiment_analyzer.py`

✅ **Partial strategies**: Regime-based router, momentum, mean-reversion, breakout, scalper
- `strategies/regime_based_router.py`
- `strategies/momentum_strategy.py`
- `strategies/mean_reversion.py`
- `strategies/breakout.py`
- `strategies/scalper.py`

✅ **Partial risk**: Scalper risk manager, drawdown protector, portfolio balancer
- `agents/scalper/risk/risk_manager.py`
- `agents/risk/drawdown_protector.py`
- `agents/risk/portfolio_balancer.py`

✅ **Backtesting**: Multiple engines present
- `backtesting/engine.py`
- `backtesting/bar_reaction_engine.py`
- `backtesting/microreactor_engine.py`

### Missing Modules (What Needs Building)

❌ **1. Enhanced Regime Detector** (PRD §5)
- Full `ai_engine/regime_detector.py` with ADX/Aroon/RSI/ATR
- Hysteresis logic to prevent flip-flop
- Optional ML classifier
- `RegimeTick` dataclass emission

❌ **2. Unified Strategy Router** (PRD §6, §14)
- Top-level `agents/strategy_router.py`
- Consumes `RegimeTick`, routes to strategies
- Enforces leverage caps per symbol
- Halt-on-regime-change policy

❌ **3. Top-Level Risk Manager** (PRD §8, §14)
- `agents/risk_manager.py`
- Per-trade risk sizing (1-2% via SL distance)
- Portfolio exposure caps (≤4% total)
- Drawdown breakers (pause on DD > 10%)
- Venue safety (price bands, cancel-all on disconnect)

❌ **4. Signal Publisher** (PRD §4, §14)
- `agents/publisher.py`
- Publishes to `signals:live` / `signals:paper`
- Idempotent IDs (UUID), <500ms latency
- Circuit breaker on failures

❌ **5. Main Engine Loop** (PRD §3, §9, §14)
- `orchestration/main_engine.py`
- Event-driven loop: Kraken WS → regime → router → risk → publisher
- Config hot-reload, kill switch, mode switching

❌ **6. ML Filter Integration** (PRD §7)
- Enhance `ai_engine/strategy_selector.py`
- Ensemble predictors (direction classifier, magnitude regressor)
- Confidence scoring [0,1], alignment filtering

❌ **7. Unified Backtest Harness** (PRD §12)
- `backtesting/unified_backtest.py`
- Full stack simulation (regime → router → risk)
- 2-3y data, KPI validation (ROI ≥10%, DD ≤20%)

❌ **8. Strategy Integration**
- Wire strategies under unified router
- Enforce leverage caps, spread tolerance
- Trailing stops (trend), multi-exit TP (mean-reversion)

---

## 6-PR Implementation Plan

### **PR #1: Enhanced Regime Detector** (Week 1)
**Scope**: Complete `ai_engine/regime_detector.py` with TA/Macro/Sentiment integration, hysteresis, ML classifier.

**Key Files**:
- `ai_engine/regime_detector.py` (create)
- `ai_engine/regime_detector/__init__.py` (update)
- `tests/ai_engine/test_regime_detector.py` (create)

**Success**: `detect_regime()` returns `RegimeTick` with confidence > 0.5, hysteresis prevents flip-flop.

---

### **PR #2: Unified Strategy Router & Risk Manager** (Week 2)
**Scope**: Build `agents/strategy_router.py` and `agents/risk_manager.py` to coordinate regime → strategy → risk sizing.

**Key Files**:
- `agents/strategy_router.py` (create)
- `agents/risk_manager.py` (create)
- `tests/agents/test_strategy_router.py` (create)
- `tests/agents/test_risk_manager.py` (create)

**Success**: Leverage caps enforced, per-trade risk 1-2%, DD breaker triggers on DD > 10%.

---

### **PR #3: Signal Publisher & Redis Integration** (Week 3)
**Scope**: Build `agents/publisher.py` to publish `SignalDTO` to Redis with <500ms latency.

**Key Files**:
- `agents/publisher.py` (create)
- `tests/agents/test_publisher.py` (create)
- `scripts/test_signal_publishing.py` (create)

**Success**: Signal published to Redis, latency p95 < 500ms, idempotent IDs, circuit breaker functional.

---

### **PR #4: Main Engine Loop & Orchestration** (Week 4)
**Scope**: Build `orchestration/main_engine.py` to coordinate regime → router → risk → publisher in real-time.

**Key Files**:
- `orchestration/main_engine.py` (create)
- `tests/orchestration/test_main_engine.py` (create)
- `scripts/start_trading_system.py` (update)

**Success**: Engine subscribes to Kraken WS, pipeline functional, config hot-reload works, kill switch halts entries.

---

### **PR #5: ML Filter Integration & Confidence Scoring** (Week 5)
**Scope**: Integrate ML predictors into `ai_engine/strategy_selector.py` for confidence-based filtering.

**Key Files**:
- `ai_engine/strategy_selector.py` (enhance)
- `agents/ml/predictor.py` (enhance)
- `tests/ai_engine/test_ml_filter.py` (create)

**Success**: ML filter suppresses trades < 0.4 confidence, alignment check prevents regime/ML conflicts.

---

### **PR #6: Unified Backtest Harness & Validation** (Week 6)
**Scope**: Build `backtesting/unified_backtest.py` with full stack integration, 2-3y validation.

**Key Files**:
- `backtesting/unified_backtest.py` (create)
- `tests/backtesting/test_unified_backtest.py` (create)
- `docs/BACKTEST_RESULTS.md` (create)

**Success**: Backtest runs on BTC/ETH/SOL 2022-2024, monthly ROI ≥10%, DD ≤20%, PF ≥1.5 or Win-rate ≥60%.

---

## Environment Details

### Conda Environment
- **Name**: `crypto-bot`
- **Activate**: `conda activate crypto-bot`

### Redis Cloud
- **Host**: `redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
- **TLS**: Required
- **Cert Path**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem`
- **Connection Test**:
  ```bash
  redis-cli -u redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem PING
  ```

### Stream Keys (PRD Appendix A)
- **OHLCV**: `kraken:ohlc:{tf}:{PAIR}` (e.g., `kraken:ohlc:1m:BTC-USD`)
- **Signals**: `signals:paper` / `signals:live`
- **Market data**: `kraken:trade`, `kraken:book`, `kraken:spread`, `kraken:scalp`

---

## Key PRD References

All tasks mapped to PRD sections:
- **§3**: System Architecture
- **§4**: Signal Contract & Publishing
- **§5**: Regime Detection
- **§6**: Strategy Stack (§6.1 Trend, §6.2 Range, §6.3 Scalper)
- **§7**: AI/ML Decision Support
- **§8**: Risk & Leverage Policy
- **§9**: Execution & Exchange Integration
- **§10**: Config & Hot-Reload
- **§12**: Testing & Validation
- **§14**: Files & Ownership (file paths)
- **§15**: Acceptance Criteria Checklist

---

## Acceptance Criteria (PRD §15)

Final Go/No-Go checklist:
- ✅ Monthly ROI backtest ≥10% with DD ≤20% on ≥3 assets (BTC/USD, ETH/USD, SOL/USD)
- ✅ Paper trading 14+ days: PF ≥1.5 OR Win-rate ≥60%, DD ≤15%
- ✅ Decision→Redis publish p95 < 500ms; API stream lag p95 < 200ms
- ✅ Drawdown breaker triggers & cools down as configured
- ✅ Config hot-reload passes; rollback works
- ✅ Kraken rate limits never violated (no exchange bans)

---

## Next Steps

1. **Review** `IMPLEMENTATION_PLAN.md` and `TASKLOG.md`
2. **Start with PR #1**: Enhanced Regime Detector (Week 1)
3. **Track progress** in `TASKLOG.md` (update run history after each PR)
4. **Follow dependencies**: #1 → #2 → (#3 || #4) → #5 → #6

---

## Files Created (Step 1)

1. `IMPLEMENTATION_PLAN.md` - Comprehensive 6-PR plan with gap analysis, scope, tests, success criteria
2. `TASKLOG.md` - Task tracking skeleton with checklists, run history, environment reference
3. `STEP1_SUMMARY.md` - This summary document

**Total**: 3 new files, 0 modified (planning phase only, no code written)

---

## Status

✅ **STEP 1 COMPLETE** - Ready to proceed to implementation (PR #1: Enhanced Regime Detector)

No code has been written. All deliverables are planning/documentation only, as requested.
