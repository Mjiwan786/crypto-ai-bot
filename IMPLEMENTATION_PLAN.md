# Crypto-AI-Bot: 6-PR Implementation Plan
**Enhanced Profitability PRD Implementation**
**Environment**: `crypto-bot` conda environment
**Redis Cloud**: `redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818` (TLS with cert at `config/certs/redis_ca.pem`)

---

## Executive Summary

This plan implements the PRD.md vision to turn $10k → $15k (50% uplift, ~10% monthly returns) using:
- **Regime-adaptive strategies** (bull/bear/sideways detection)
- **AI/ML decision support** (confidence scoring, alignment filtering)
- **Strict risk controls** (1-2% per-trade risk, DD breakers, leverage caps)
- **Redis-based signal publishing** (sub-500ms latency to `signals:live` / `signals:paper`)
- **Full backtest & paper trading validation** (2-3y data, 2-4 week paper trials)

**Current State Analysis**:
- ✅ **Config plane**: Unified loaders, hot-reload, optimized caching, agent integration present
- ✅ **Data plane**: Kraken WS client, Redis streams, OHLCV buckets, rate limits
- ✅ **Partial AI engine**: `regime_detector` stub, `strategy_selector` with TA/Macro/Sentiment fusion
- ✅ **Partial strategies**: `regime_based_router`, `momentum_strategy`, `mean_reversion`, `breakout`, `scalper`
- ✅ **Partial risk**: Scalper risk manager, drawdown protector, portfolio balancer
- ✅ **Backtesting**: Engines present (`backtesting/engine.py`, `bar_reaction_engine.py`, `microreactor_engine.py`)
- ❌ **Missing**: Full regime detector module, unified strategy router, top-level risk manager, signal publisher, main engine loop, ML filter integration

---

## Gap Analysis: Missing Modules

Reference: PRD §14 "Files & Ownership"

### 1. **Regime Detector** (PRD §5)
**Current**: `ai_engine/regime_detector/__init__.py` has stub `infer_regime()` function; `deep_ta_analyzer.py`, `macro_analyzer.py`, `sentiment_analyzer.py` exist but incomplete.
**Missing**: Full integration into `regime_detector.py` with:
- ADX/Aroon/RSI + ATR/variance indicators
- Hysteresis to avoid flip-flop
- Optional ML classifier
- Emits `RegimeTick{ regime, vol_regime, strength, changed }`
- Unit tests with mock OHLCV fixtures

### 2. **Strategy Router** (PRD §6, §14)
**Current**: `strategies/regime_based_router.py` exists but is strategy-ensemble focused; `ai_engine/strategy_selector.py` exists for regime fusion.
**Missing**: Unified `agents/strategy_router.py` that:
- Consumes `RegimeTick` from regime detector
- Routes to appropriate strategy (trend/range/scalper)
- Enforces per-symbol leverage caps (from `config/exchange_configs/kraken.yaml`)
- Enforces spread tolerance & circuit breakers
- Coordinates halt-on-regime-change policy

### 3. **Strategies** (PRD §6.1-6.3)
**Current**: `strategies/momentum_strategy.py`, `mean_reversion.py`, `breakout.py`, `scalper.py` exist.
**Missing**:
- Full integration with strategy router
- Leverage cap enforcement per symbol
- Trailing stops for trend-following
- Multi-exit TP ladder for mean-reversion
- Scalper sub-minute synthetic bars (15s/30s) integration

### 4. **Risk Manager** (PRD §8, §14)
**Current**: `agents/scalper/risk/risk_manager.py` exists (scalper-specific); `agents/risk/drawdown_protector.py`, `portfolio_balancer.py` exist.
**Missing**: Top-level `agents/risk_manager.py` that:
- Per-trade risk sizing (1-2% of equity via SL distance)
- Portfolio exposure caps (≤4% total concurrent risk)
- Leverage enforcement (default 2-3×, max 5× symbol-specific)
- Drawdown breakers (pause or drop to 0.5× risk on DD thresholds)
- Venue safety (isolate per position, price bands, cancel-all on disconnect)

### 5. **Publisher** (PRD §4, §14)
**Current**: `agents/infrastructure/pnl_publisher.py` exists (PnL-specific).
**Missing**: General `io/publisher.py` or `agents/publisher.py` that:
- XADD to `signals:live` / `signals:paper` streams
- Idempotent IDs (UUID)
- Low-latency (<500ms) publishing
- SignalDTO serialization: `{ id, ts, pair, side, entry, sl, tp, strategy, confidence, mode }`

### 6. **Engine/Loop** (PRD §3, §9, §14)
**Current**: `orchestration/master_orchestrator.py`, `orchestration/graph.py` exist (LangGraph-based agent orchestration).
**Missing**: Main trading engine loop (or adaptation of orchestrator) that:
- Subscribes to Kraken WS data (OHLCV, trade, book)
- Feeds regime detector → strategy router → risk manager → publisher
- Handles config hot-reload events
- Implements kill switch logic
- Mode switching (paper/live)

### 7. **Backtest Harness** (PRD §12)
**Current**: `backtesting/engine.py`, `bar_reaction_engine.py`, `microreactor_engine.py` exist.
**Missing**: Unified harness that:
- Runs 2-3y backtests across regimes
- Reports monthly ROI, PF, DD, Sharpe
- Fail-fast if DD > 20%
- Integrates with full strategy stack (regime detector → router → risk)

### 8. **ML Filter** (PRD §7)
**Current**: `ai_engine/adaptive_learner.py`, `agents/ml/predictor.py`, `feature_engineer.py` exist.
**Missing**: Full integration into strategy selector:
- Ensemble predictors (direction classifier, move magnitude regressor)
- Confidence ∈ [0,1] scoring
- Filter: suppress trades under `MIN_ALIGNMENT_CONFIDENCE`
- Majority vote gating

---

## 6-PR Implementation Plan

### **PR #1: Enhanced Regime Detector (Week 1)**
**Scope**: Complete `ai_engine/regime_detector.py` with full TA/Macro/Sentiment integration, hysteresis, and optional ML classifier.

**References**: PRD §5, §14

**Files to Create/Modify**:
- `ai_engine/regime_detector.py` (create main module)
- `ai_engine/regime_detector/__init__.py` (update exports)
- `ai_engine/regime_detector/deep_ta_analyzer.py` (enhance ADX/Aroon/RSI/ATR)
- `ai_engine/regime_detector/macro_analyzer.py` (enhance macro indicators)
- `ai_engine/regime_detector/sentiment_analyzer.py` (enhance sentiment scoring)
- `tests/ai_engine/test_regime_detector.py` (create unit tests)
- `tests/ai_engine/fixtures/mock_ohlcv.json` (create test data)

**Key Functionality**:
- `RegimeTick` dataclass: `{ regime: RegimeLabel, vol_regime: str, strength: float, changed: bool, timestamp_ms: int }`
- `detect_regime(ohlcv_df: pd.DataFrame, timeframe: str, config: RegimeConfig) -> RegimeTick`
- Indicators: ADX (trend strength), Aroon (momentum), RSI (overbought/oversold), ATR (volatility)
- Hysteresis: Require `MIN_REGIME_STRENGTH_DELTA` (e.g., 0.15) to switch regimes
- Optional ML: `ml_regime_classifier` (sklearn RandomForest) trained on labeled regime data
- Integration with `ai_engine/strategy_selector.py` (already calls TA/Macro/Sentiment analyzers)

**Tests**:
- Unit tests: synthetic uptrend → `RegimeLabel.BULL`, downtrend → `RegimeLabel.BEAR`, choppy → `RegimeLabel.CHOP`
- Hysteresis test: flip-flopping prevented within threshold
- Latency test: computation < 100ms for 500-bar OHLCV

**Success Criteria**:
- ✅ `detect_regime()` returns valid `RegimeTick` with confidence > 0.5 for clear trends
- ✅ Hysteresis prevents regime flip-flop (no switch unless strength delta > threshold)
- ✅ 100% test coverage for `regime_detector.py`
- ✅ Self-check script passes with synthetic data

**Environment**:
```bash
conda activate crypto-bot
pytest tests/ai_engine/test_regime_detector.py -v
python ai_engine/regime_detector.py  # Self-check
```

---

### **PR #2: Unified Strategy Router & Risk Manager (Week 2)**
**Scope**: Build top-level `agents/strategy_router.py` and `agents/risk_manager.py` to coordinate regime → strategy → risk sizing.

**References**: PRD §6, §8, §14

**Files to Create/Modify**:
- `agents/strategy_router.py` (create)
- `agents/risk_manager.py` (create)
- `strategies/regime_based_router.py` (refactor to use new router)
- `config/exchange_configs/kraken.yaml` (verify leverage caps per symbol)
- `tests/agents/test_strategy_router.py` (create)
- `tests/agents/test_risk_manager.py` (create)

**Key Functionality**:

**`agents/strategy_router.py`**:
- `route_strategy(regime_tick: RegimeTick, snapshot: MarketSnapshot, ohlcv_df: pd.DataFrame) -> StrategyAdvice`
- Mapping: `BULL/BEAR → momentum_strategy`, `CHOP → mean_reversion`, `HIGH_VOL → scalper`
- Enforce per-symbol leverage caps from `config/exchange_configs/kraken.yaml` (e.g., BTC max 5×, alts max 3×)
- Check spread tolerance (`SPREAD_BPS_MAX` from env, default 5 bps) and circuit breaker state
- Halt new entries for N cycles on regime change (configurable `REGIME_CHANGE_HALT_CYCLES`, default 2)

**`agents/risk_manager.py`**:
- `size_position(signal: SignalDTO, equity_usd: Decimal, current_volatility: Decimal) -> PositionSpec`
- Per-trade risk: 1-2% of equity (calculate via SL distance: `risk_usd = equity * RISK_PCT_PER_TRADE; qty = risk_usd / (entry - sl)`)
- Portfolio caps: track total concurrent risk, reject if `sum(open_risks) + new_risk > MAX_PORTFOLIO_RISK_PCT * equity` (default 4%)
- Leverage: default 2-3×, max 5× (symbol-specific from Kraken config)
- Drawdown breakers:
  - Daily DD > `MAX_DAILY_DD_PCT` (default 10%): pause new entries, log alert
  - Rolling DD > `MAX_ROLLING_DD_PCT` (default 15%): drop risk to 0.5× per-trade
  - Cooldown period: `DD_COOLDOWN_MINUTES` (default 60)
- Venue safety: enforce price bands (reject if entry > 1.05 × last_price or < 0.95 × last_price), cancel-all on WS disconnect

**Tests**:
- Router: regime change halts new entries for N cycles
- Router: leverage caps enforced (BTC max 5×, alts max 3×)
- Risk: per-trade risk capped at 2% equity
- Risk: portfolio exposure capped at 4% total
- Risk: drawdown breaker triggers on DD > 10%, drops risk to 0.5×

**Success Criteria**:
- ✅ Strategy router maps regimes to strategies correctly
- ✅ Leverage caps enforced per symbol
- ✅ Risk manager sizes positions to 1-2% per-trade risk
- ✅ Drawdown breaker triggers and cools down as configured
- ✅ 100% test coverage

**Environment**:
```bash
conda activate crypto-bot
pytest tests/agents/test_strategy_router.py tests/agents/test_risk_manager.py -v
```

---

### **PR #3: Signal Publisher & Redis Integration (Week 3)**
**Scope**: Build `agents/publisher.py` to publish `SignalDTO` to `signals:live` / `signals:paper` Redis streams with <500ms latency.

**References**: PRD §4, Appendix A

**Files to Create/Modify**:
- `agents/publisher.py` (create)
- `agents/infrastructure/pnl_publisher.py` (refactor for reuse)
- `tests/agents/test_publisher.py` (create)
- `scripts/test_signal_publishing.py` (create demo script)

**Key Functionality**:
- `publish_signal(signal: SignalDTO, mode: str = "paper") -> bool`
- Stream keys: `signals:live` / `signals:paper` (from PRD Appendix A)
- Idempotent IDs: `signal.id = str(uuid.uuid4())`
- Redis XADD with max latency tracking (p95 < 500ms)
- Redis Cloud TLS connection: `redis-cli -u redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem`
- Serialization: `orjson` for speed, fallback to `json`
- Error handling: retry with exponential backoff (max 3 retries), circuit breaker on consecutive failures

**SignalDTO** (from PRD §4):
```python
@dataclass
class SignalDTO:
    id: str  # UUID
    ts: int  # milliseconds
    pair: str  # "BTC-USD"
    side: str  # "long" | "short"
    entry: float
    sl: float
    tp: float
    strategy: str  # "trend_follow_v1", "mean_rev_v1", etc.
    confidence: float  # [0, 1]
    mode: str  # "paper" | "live"
```

**Tests**:
- Publish signal to `signals:paper`, verify XREAD retrieves it
- Latency test: 1000 publishes, p95 < 500ms
- Idempotency: duplicate ID rejected or deduplicated
- Circuit breaker: 3 consecutive failures trigger cooldown

**Success Criteria**:
- ✅ Signal published to Redis with correct schema
- ✅ Latency p95 < 500ms (measured via `time.perf_counter()`)
- ✅ Idempotent IDs (UUID v4)
- ✅ Circuit breaker triggers on 3 consecutive errors
- ✅ 100% test coverage

**Environment**:
```bash
conda activate crypto-bot
# Test Redis connection
redis-cli -u redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem PING

# Run tests
pytest tests/agents/test_publisher.py -v

# Demo script
python scripts/test_signal_publishing.py
```

---

### **PR #4: Main Engine Loop & Orchestration (Week 4)**
**Scope**: Build or adapt `orchestration/master_orchestrator.py` to coordinate regime detection → routing → risk → publishing in real-time.

**References**: PRD §3, §9, §10, §17

**Files to Create/Modify**:
- `orchestration/main_engine.py` (create or adapt from `master_orchestrator.py`)
- `orchestration/master_orchestrator.py` (refactor if needed)
- `config/settings.yaml` (add engine loop config: poll intervals, kill switch, mode)
- `scripts/start_trading_system.py` (update to use new engine)
- `tests/orchestration/test_main_engine.py` (create integration tests)

**Key Functionality**:
- **Data ingestion**: Subscribe to Kraken WS (OHLCV, trade, book) via `utils/kraken_ws.py`
- **Main loop** (async event-driven):
  1. On OHLCV update → trigger regime detector
  2. If regime changed → halt new entries for N cycles
  3. Regime detector → strategy router → strategy selection
  4. Strategy → risk manager → position sizing
  5. Risk manager → publisher → Redis streams
- **Config hot-reload**: Subscribe to `ConfigEvent.UPDATED` from `config/unified_config_loader.py`
- **Kill switch**: Check env flag `TRADING_ENABLED` every loop; if `false`, halt new entries + cancel-all open orders
- **Mode switching**: Read `TRADING_MODE` env (paper/live), route to appropriate Redis stream
- **Circuit breakers**: WS disconnect → cancel-all orders, log alert, reconnect with exponential backoff

**Integration Points**:
- `ai_engine/regime_detector.py` → `detect_regime()`
- `agents/strategy_router.py` → `route_strategy()`
- `agents/risk_manager.py` → `size_position()`
- `agents/publisher.py` → `publish_signal()`
- `utils/kraken_ws.py` → WS callbacks for OHLCV/trade/book

**Tests**:
- Mock WS data stream → engine generates regime tick → publishes signal
- Config hot-reload: change `SPREAD_BPS_MAX` → engine updates breaker threshold
- Kill switch: set `TRADING_ENABLED=false` → no new signals published
- Regime change: `BULL → CHOP` → engine halts entries for N cycles

**Success Criteria**:
- ✅ Engine subscribes to Kraken WS and processes OHLCV updates
- ✅ Regime detector → router → risk → publisher pipeline functional
- ✅ Config hot-reload works (change logged, new config applied)
- ✅ Kill switch halts new entries immediately
- ✅ Mode switching (paper/live) routes to correct Redis stream
- ✅ 100% integration test coverage for happy path + error cases

**Environment**:
```bash
conda activate crypto-bot
# Run in paper mode
TRADING_MODE=paper TRADING_ENABLED=true python scripts/start_trading_system.py

# Monitor Redis streams
redis-cli -u redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem XREAD STREAMS signals:paper 0
```

---

### **PR #5: ML Filter Integration & Confidence Scoring (Week 5)**
**Scope**: Integrate ML predictors into `ai_engine/strategy_selector.py` for confidence-based trade filtering.

**References**: PRD §7

**Files to Create/Modify**:
- `ai_engine/strategy_selector.py` (enhance with ML filter)
- `agents/ml/predictor.py` (enhance ensemble predictors)
- `agents/ml/feature_engineer.py` (verify feature extraction)
- `config/settings.yaml` (add ML filter knobs: `MIN_ALIGNMENT_CONFIDENCE`, `REQUIRE_ALIGNMENT`)
- `tests/ai_engine/test_ml_filter.py` (create)

**Key Functionality**:
- **Ensemble predictors**:
  - Direction classifier: binary (up/down) sklearn RandomForest, input features: RSI, MACD, ATR, volume, regime
  - Move magnitude regressor: sklearn GradientBoostingRegressor, predicts % move over next N bars
- **Confidence scoring**: `confidence = (direction_proba_max + magnitude_confidence) / 2`, range [0, 1]
- **Filter logic** in `strategy_selector.py`:
  1. After regime fusion, get ML predictions
  2. If `REQUIRE_ALIGNMENT=true` and ML disagrees with regime (e.g., regime=BULL, ML=down) → suppress trade
  3. If `confidence < MIN_ALIGNMENT_CONFIDENCE` (default 0.4 from PRD) → suppress trade
  4. Majority vote gating (optional): require 2/3 agreement (TA regime, ML direction, sentiment)
- **Retraining cadence**: monthly or on regime drift (detect via performance degradation)

**Tests**:
- ML filter suppresses low-confidence trades (confidence < 0.4)
- Alignment filter: regime=BULL + ML=down → trade suppressed
- Majority vote: 2/3 agreement required

**Success Criteria**:
- ✅ ML predictors trained and integrated into strategy selector
- ✅ Confidence scoring [0, 1] functional
- ✅ Filter suppresses trades below `MIN_ALIGNMENT_CONFIDENCE`
- ✅ Alignment check prevents regime/ML conflicts
- ✅ 100% test coverage

**Environment**:
```bash
conda activate crypto-bot
# Train models (monthly or on-demand)
python agents/ml/model_trainer.py --train-direction --train-magnitude

# Run with ML filter enabled
MIN_ALIGNMENT_CONFIDENCE=0.4 REQUIRE_ALIGNMENT=true python scripts/start_trading_system.py

# Test
pytest tests/ai_engine/test_ml_filter.py -v
```

---

### **PR #6: Unified Backtest Harness & Validation (Week 6)**
**Scope**: Build unified backtest harness integrating full stack (regime → router → risk) with 2-3y data validation.

**References**: PRD §12, §15

**Files to Create/Modify**:
- `backtesting/unified_backtest.py` (create)
- `backtesting/engine.py` (adapt for full stack integration)
- `scripts/run_backtest.py` (update to use unified harness)
- `tests/backtesting/test_unified_backtest.py` (create)
- `docs/BACKTEST_RESULTS.md` (create report template)

**Key Functionality**:
- **Data loading**: 2-3y OHLCV from Kraken for BTC/USD, ETH/USD, SOL/USD (min 3 assets per PRD §15)
- **Full stack simulation**:
  1. Replay OHLCV bar-by-bar
  2. Feed each bar to regime detector → router → risk manager
  3. Simulate fills (market orders: instant fill @ mid, limit orders: fill if touched)
  4. Track equity, drawdown, PnL, win rate, Profit Factor
- **KPI reporting**:
  - Monthly ROI: avg ≥ 10% (fail-fast if < 8%)
  - Max DD: ≤ 20% (fail-fast if > 20%)
  - Profit Factor: ≥ 1.5 OR Win-rate ≥ 60%
  - Sharpe Ratio: ≥ 1.0
- **Regime coverage**: Ensure backtest spans bull (2023 Q1-Q2), bear (2022 Q2-Q4), chop (2023 Q3-Q4)
- **Slippage model**: 0.1% taker fee (Kraken), 2-5 bps slippage on market orders
- **Output**: JSON report + equity curve chart (matplotlib)

**Tests**:
- Backtest completes without errors
- Monthly ROI ≥ 10% on BTC/USD 2022-2024
- Max DD ≤ 20%
- PF ≥ 1.5 or Win-rate ≥ 60%

**Success Criteria**:
- ✅ Backtest runs on 2-3y data for ≥3 assets (BTC, ETH, SOL)
- ✅ Monthly ROI ≥ 10% avg, DD ≤ 20%
- ✅ PF ≥ 1.5 OR Win-rate ≥ 60%
- ✅ Sharpe ≥ 1.0
- ✅ Report generated with equity curve chart
- ✅ 100% test coverage

**Environment**:
```bash
conda activate crypto-bot
# Run backtest
python scripts/run_backtest.py --pairs BTC/USD,ETH/USD,SOL/USD --start 2022-01-01 --end 2024-12-31

# View results
cat docs/BACKTEST_RESULTS.md
```

---

## TASKLOG.md Skeleton

```markdown
# Implementation Task Log

## PR #1: Enhanced Regime Detector
- [ ] Create `ai_engine/regime_detector.py`
- [ ] Enhance `deep_ta_analyzer.py` (ADX, Aroon, RSI, ATR)
- [ ] Enhance `macro_analyzer.py`
- [ ] Enhance `sentiment_analyzer.py`
- [ ] Add hysteresis logic (MIN_REGIME_STRENGTH_DELTA)
- [ ] Integrate optional ML classifier
- [ ] Create `tests/ai_engine/test_regime_detector.py`
- [ ] Create `tests/ai_engine/fixtures/mock_ohlcv.json`
- [ ] Self-check script passes
- [ ] **Run**: `pytest tests/ai_engine/test_regime_detector.py -v`

## PR #2: Strategy Router & Risk Manager
- [ ] Create `agents/strategy_router.py`
- [ ] Create `agents/risk_manager.py`
- [ ] Refactor `strategies/regime_based_router.py`
- [ ] Verify leverage caps in `config/exchange_configs/kraken.yaml`
- [ ] Create `tests/agents/test_strategy_router.py`
- [ ] Create `tests/agents/test_risk_manager.py`
- [ ] Test regime change halt logic
- [ ] Test drawdown breaker trigger + cooldown
- [ ] **Run**: `pytest tests/agents/ -v`

## PR #3: Signal Publisher
- [ ] Create `agents/publisher.py`
- [ ] Refactor `agents/infrastructure/pnl_publisher.py`
- [ ] Create `tests/agents/test_publisher.py`
- [ ] Create `scripts/test_signal_publishing.py`
- [ ] Test Redis Cloud TLS connection
- [ ] Test latency (p95 < 500ms)
- [ ] Test idempotent IDs
- [ ] Test circuit breaker
- [ ] **Run**: `redis-cli PING && pytest tests/agents/test_publisher.py -v`

## PR #4: Main Engine Loop
- [ ] Create `orchestration/main_engine.py`
- [ ] Refactor `orchestration/master_orchestrator.py` (if needed)
- [ ] Update `config/settings.yaml` (engine config)
- [ ] Update `scripts/start_trading_system.py`
- [ ] Create `tests/orchestration/test_main_engine.py`
- [ ] Test WS data ingestion
- [ ] Test regime → router → risk → publisher pipeline
- [ ] Test config hot-reload
- [ ] Test kill switch
- [ ] Test mode switching (paper/live)
- [ ] **Run**: `TRADING_MODE=paper python scripts/start_trading_system.py`

## PR #5: ML Filter Integration
- [ ] Enhance `ai_engine/strategy_selector.py` (ML filter)
- [ ] Enhance `agents/ml/predictor.py` (ensemble predictors)
- [ ] Verify `agents/ml/feature_engineer.py`
- [ ] Update `config/settings.yaml` (ML filter knobs)
- [ ] Create `tests/ai_engine/test_ml_filter.py`
- [ ] Test confidence scoring [0, 1]
- [ ] Test alignment filter (regime vs ML)
- [ ] Test majority vote gating
- [ ] **Run**: `pytest tests/ai_engine/test_ml_filter.py -v`

## PR #6: Unified Backtest Harness
- [ ] Create `backtesting/unified_backtest.py`
- [ ] Adapt `backtesting/engine.py` (full stack integration)
- [ ] Update `scripts/run_backtest.py`
- [ ] Create `tests/backtesting/test_unified_backtest.py`
- [ ] Create `docs/BACKTEST_RESULTS.md` (report template)
- [ ] Load 2-3y data (BTC, ETH, SOL)
- [ ] Run backtest, verify KPIs (ROI ≥10%, DD ≤20%, PF ≥1.5)
- [ ] Generate equity curve chart
- [ ] **Run**: `python scripts/run_backtest.py --pairs BTC/USD,ETH/USD,SOL/USD`

---

## Completion Checklist (from PRD §15)
- [ ] Monthly ROI backtest ≥10% with DD ≤20% on ≥3 assets
- [ ] Paper trading 14+ days: PF ≥1.5 OR Win-rate ≥60%, DD ≤15%
- [ ] Decision→Redis publish p95 < 500ms; API stream lag p95 < 200ms
- [ ] Drawdown breaker triggers & cools down as configured
- [ ] Config hot-reload passes; rollback works
- [ ] Kraken rate limits never violated (no exchange bans)
```

---

## Quick Reference

### Redis Cloud Connection
```bash
# Test connection
redis-cli -u redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem PING

# Monitor signals
redis-cli -u redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem XREAD STREAMS signals:paper 0
```

### Conda Environment
```bash
# Activate
conda activate crypto-bot

# Verify packages
conda list | grep -E "pandas|redis|orjson|websockets|pydantic"
```

### File Paths Reference (PRD §14)
- **Regime detector**: `ai_engine/regime_detector.py`
- **Strategy router**: `agents/strategy_router.py`
- **Strategies**: `strategies/{momentum_strategy,mean_reversion,breakout,scalper}.py`
- **Risk manager**: `agents/risk_manager.py`
- **Publisher**: `agents/publisher.py`
- **Engine loop**: `orchestration/main_engine.py`
- **Backtest harness**: `backtesting/unified_backtest.py`
- **ML filter**: `ai_engine/strategy_selector.py` + `agents/ml/predictor.py`

---

## Notes
- **No code written yet** (plan only, per instructions)
- All PRs include explicit file paths, tests, and success criteria
- Each PR references PRD section numbers for traceability
- Redis Cloud TLS cert path hardcoded: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem`
- Conda env: `crypto-bot`
- Implementation order: PR #1 → #6 sequentially (dependencies: #1 → #2 → #4 → #5 → #6; #3 can be parallel after #2)
