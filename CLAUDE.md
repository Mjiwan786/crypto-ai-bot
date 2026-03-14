# crypto-ai-bot — CLAUDE.md

## Ecosystem

| Repo | Role | Stack | Hosting |
|------|------|-------|---------|
| **crypto-ai-bot** | Trading engine, ML, strategies | Python 3.10+ / Conda `crypto-bot` | Fly.io (`iad`) |
| signals-api | REST API, bots, billing | FastAPI / Conda `signals-api` | Fly.io |
| signals-site | User-facing dashboard | Next.js 14 / TypeScript | Vercel |

## What This Repo Does

Multi-agent AI trading engine: ingests market data from 8 exchanges via CCXT Pro WebSocket (+ REST fallback), runs OHLCV-based consensus + ML scoring pipeline, generates trade signals, publishes to Redis Cloud streams. Operates on 60-second signal intervals with ATR-based TP/SL targeting 220 bps profit per trade.

## Directory Structure

```
signals/              — Signal pipeline (Sprint 1-4B)
  consensus_gate.py   —   3-family consensus (momentum/trend/structure)
  volume_scoring.py   —   Volume ratio + confidence multiplier
  ohlcv_reader.py     —   Redis OHLCV stream reader (3 key formats)
  strategy_orchestrator.py — Wraps 6 strategies, routes by regime
  atr_levels.py       —   ATR-based TP/SL calculator (Sprint 3A)
  exit_manager.py     —   ExitManager: trailing stop, partial TP (Sprint 3B)
  trend_filter.py     —   EMA-cross trend filter (Sprint 3A)
  ml_scorer.py        —   XGBoost ML signal scorer (Sprint 4B)
trainer/              — Offline ML training pipeline (Sprint 4A)
  feature_builder.py  —   30-feature OHLCV feature engineering
  data_exporter.py    —   Redis→CSV export + candle labeling
  models/xgboost_signal.py — XGBoost binary classifier
  evaluation/walk_forward.py — Walk-forward validation with purge gap
  train.py            —   CLI: python -m trainer.train
agents/core/          — 7 core agents (execution, market_scanner, regime_detector, etc.)
agents/infrastructure/ — Redis publishers, circuit breakers, rate limiters, validators
agents/ml/            — Feature engineering (wraps trainer/), ML prediction (wraps ml_scorer)
agents/risk/          — Drawdown, compliance, exposure, portfolio balancing
agents/special/       — Flash loan, arbitrage, whale watching, on-chain data (Redis-backed)
ai_engine/regime_detector/ — Regime detection + technical analysis
  deep_ta_analyzer.py —   Real RSI/MACD/BB/ATR/trend/volatility (Sprint 4B)
  macro_analyzer.py   —   Async Redis macro reads + regime classification (Sprint 4B)
  regime_writer.py    —   Background regime publisher
strategies/           — Trend following, breakout, mean reversion, momentum, sideways, MA
strategies/indicator/ — Technical indicators (RSI, MACD, EMA, breakout)
market_data/          — Multi-exchange feeds, OHLCV aggregation, price engine
exchange/             — CCXT adapters, rate limiters, WebSocket adapters (8 exchanges)
flash_loan_system/    — Execution optimizer, historical analyzer, opportunity scorer
mcp/                  — Multi-agent coordination protocol, Redis pub/sub
shared_contracts/     — Canonical types shared with signals-api (NEVER modify without syncing)
config/               — YAML settings, exchange configs, trading pairs, ml_models.yaml
pnl/                  — Paper fill simulator, rolling PnL
models/               — Trained model artifacts (*.joblib, git-ignored)
```

## Critical Rules

- Use Conda env `crypto-bot` for all commands: `conda run -n crypto-bot <cmd>`
- NEVER modify `shared_contracts/` without running `pytest shared_contracts/tests/`
- All Redis streams use mode-aware keys: `signals:paper` vs `signals:live`
- Every agent must handle `ConnectionError` on Redis & exchange calls
- Circuit breakers are mandatory on all exchange API calls
- Log via `utils/logger.py` — never bare `print()`
- All strategies must implement `BaseStrategy` interface
- Risk limit validation BEFORE any trade execution
- Flash loan operations require `min_confidence >= 0.85` from ML scorer

## Run Commands

```bash
conda run -n crypto-bot python -u production_engine.py --mode paper
conda run -n crypto-bot python -u run_multi_exchange.py --mode paper
conda run -n crypto-bot pytest -v --tb=short
conda run -n crypto-bot pytest shared_contracts/tests/ -v
```

## Environment Variables (Critical)

### Core
- `REDIS_URL` — `rediss://` required (TLS)
- `ENGINE_MODE` — `paper` or `live` (controls stream separation)
- `KRAKEN_API_KEY`, `KRAKEN_API_SECRET` — exchange credentials
- `TRADING_PAIRS` — comma-separated, e.g. `BTC/USD,ETH/USD,SOL/USD`
- `REDIS_MAX_CONNECTIONS` — Redis pool size (default 100, set in fly.toml)

### Signal Pipeline (Sprint 1+)
- `USE_OHLCV_FOR_SIGNALS` — `true`/`false` (default: true) — use OHLCV for signal generation
- `CONSENSUS_GATE_ENABLED` — `true`/`false` (default: true) — 3-family consensus filter
- `VOLUME_CONFIRMATION_ENABLED` — `true`/`false` (default: true) — volume ratio gate
- `PRIMARY_TIMEFRAME_S` — signal interval seconds (default: 60)
- `TP_BPS` — take-profit basis points (default: 220)
- `SL_BPS` — stop-loss basis points (default: 75)

### Risk & Regime (Sprint 3+)
- `REGIME_FILTER_ENABLED` — `true`/`false` (default: true) — regime-based trade blocking
- `REGIME_BLOCKED_REGIMES` — comma-separated regimes to block (default: `high_vol`)
- `TREND_FILTER_ENABLED` — `true`/`false` (default: true) — EMA-cross trend filter
- `ATR_TP_SL_ENABLED` — `true`/`false` (default: true) — ATR-based TP/SL
- `EXIT_MANAGER_ENABLED` — `true`/`false` (default: true) — trailing stop + partial TP

### ML Scorer (Sprint 4B)
- `ML_SCORER_ENABLED` — `true`/`false` (default: false) — enable ML signal scoring
- `ML_MODEL_PATH` — path to .joblib model file (default: `models/signal_model.joblib`)
- `ML_MIN_SCORE` — minimum ML score to pass (default: 0.55)
- `ML_SHADOW_MODE` — `true`/`false` (default: true) — log scores without vetoing

### OHLCV Aggregator
- `OHLCV_AGGREGATOR_ENABLED` — `true`/`false` (default: true)
- `OHLCV_AGGREGATOR_TIMEFRAMES` — comma-separated seconds (default: `15,60,300`)
- `OHLCV_AGGREGATOR_MAXLEN` — max candles per stream (default: 500)

## Deploy

```bash
fly deploy --strategy rolling
fly secrets set REDIS_URL="rediss://..." KRAKEN_API_KEY="..."
```

VM: 2GB RAM, 2 shared CPUs. Two processes: `app` (production_engine) + `streamer` (multi_exchange).

## Gotchas

- Kraken WebSocket uses different pair notation than REST (e.g., `XBT/USD` vs `BTC/USD`)
- `ta-lib` requires C library installed in Docker — see `Dockerfile.production`
- Redis stream maxlen should be capped to prevent memory bloat
- Fly.io machine suspension can kill WebSocket connections — implement reconnect with exponential backoff
- `ENGINE_MODE` must match between crypto-ai-bot & signals-api or streams won't align

## Sprint Status

### Sprint 2 — COMPLETE (70/70 tests)
- [x] Phase 1: Strategy orchestrator + regime writer + engine wiring (22 tests)
- [x] Phase 2: Paper trade consumer (14 tests)
- [x] Phase 3: Relaxed consensus gate + on-chain Family D (34 tests)
- [x] Phase 4: PnL observability + deploy validation

#### Sprint 2 New Modules
| Module | Purpose |
|--------|---------|
| `signals/strategy_orchestrator.py` | Wraps 6 strategies, routes by detected regime |
| `ai_engine/regime_detector/regime_writer.py` | Background task publishing regime to Redis |
| `paper/paper_trader.py` | Consumes signals via XREADGROUP, opens/closes paper positions |
| `market_data/onchain/coinglass_client.py` | CoinGlass OI + L/S ratio, caches in Redis |
| `scripts/smoke_test.py` | Post-deploy Redis health check |

#### Sprint 2 Engine Changes (`production_engine.py`)
- 3-tier signal pipeline: Consensus Gate → Strategy Orchestrator → Legacy Momentum
- Configurable cooldown via `SIGNAL_COOLDOWN_SECONDS`
- CoinglassClient + RegimeWriter background tasks started/stopped with engine

### Sprint 3 — COMPLETE (Signal Foundation)
- [x] OHLCV-based signal pipeline replacing legacy momentum
- [x] 3-family consensus gate (momentum/trend/structure)
- [x] Volume confirmation scoring (+20%/−30% confidence)
- [x] Fee-floor TP/SL: 220 bps TP / 75 bps SL (breakeven WR 44.7%)
- [x] 60s signal interval (was 10s), 97% noise reduction
- [x] `model_version=v3.0.0-sprint1` metadata on all signals
- [x] 39 new tests (volume/consensus/ohlcv/EV math)

### Sprint 3A/3B — COMPLETE (Risk Controls)
- [x] ATR-based TP/SL calculator (`signals/atr_levels.py`)
- [x] ExitManager: trailing stop + partial TP (`signals/exit_manager.py`)
- [x] EMA-cross trend filter (`signals/trend_filter.py`)
- [x] All feature-flag gated, default ON

### Sprint 4A — COMPLETE (ML Training Pipeline, 38 tests)
- [x] `trainer/feature_builder.py` — 30-feature OHLCV feature engineering
- [x] `trainer/data_exporter.py` — Redis→CSV export + GBM synthetic data
- [x] `trainer/models/xgboost_signal.py` — XGBoost binary classifier with StandardScaler
- [x] `trainer/evaluation/walk_forward.py` — Walk-forward validation (3000/500/15 purge)
- [x] `trainer/train.py` — CLI (`python -m trainer.train --synthetic --validate`)
- [x] Go/no-go gate: acc≥0.55, AUC≥0.58, profit_factor≥1.1

### Sprint 4B — COMPLETE (ML Scorer + Stub Replacement, 34 tests)
- [x] `signals/ml_scorer.py` — MLScorer with disabled/shadow/active modes
- [x] Production engine wired: Volume → Consensus → Confidence → Trend → Fee-Floor → ML Scorer → ATR TP/SL
- [x] 5 stub replacements: feature_engineer, predictor, deep_ta_analyzer, macro_analyzer, onchain_data_agent
- [x] `model_version=v4.0.0-sprint4b` on all signals
- [x] ML scorer default OFF (`ML_SCORER_ENABLED=false`), shadow mode default ON

## Signal Pipeline (production_engine.py → `_generate_signal_v2()`)

```
OHLCV (Redis) → Volume Gate → Consensus Gate (2/3 families) → Confidence Check
    → Trend Filter (EMA cross) → Fee-Floor Check (52 bps RT)
    → ML Scorer (if enabled) → ATR TP/SL → Publish to Redis stream
```

Each gate can veto the signal. ML scorer in shadow mode logs but does not veto.

## Deep-Dive References

- `docs/PRD-001-CORE-ENGINE.md` — Product requirements for trading engine
