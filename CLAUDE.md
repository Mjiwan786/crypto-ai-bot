# crypto-ai-bot — CLAUDE.md

## Ecosystem

| Repo | Role | Stack | Hosting |
|------|------|-------|---------|
| **crypto-ai-bot** | Trading engine, ML, strategies | Python 3.10+ / Conda `crypto-bot` | Fly.io (`iad`) |
| signals-api | REST API, bots, billing | FastAPI / Conda `signals-api` | Fly.io |
| signals-site | User-facing dashboard | Next.js 14 / TypeScript | Vercel |

## What This Repo Does

Multi-agent AI trading engine: ingests market data via Kraken WebSocket, runs strategy selection through ML models, generates trade signals, publishes to Redis Cloud streams. Operates on 15-second scalping intervals targeting 10 basis point profit per trade.

## Directory Structure

```
agents/core/          — 7 core agents (execution, market_scanner, regime_detector, etc.)
agents/infrastructure/ — Redis publishers, circuit breakers, rate limiters, validators
agents/ml/            — Feature engineering, model training, prediction, strategy selection
agents/risk/          — Drawdown, compliance, exposure, portfolio balancing
agents/special/       — Flash loan, arbitrage, whale watching, on-chain
strategies/           — Trend following, breakout, mean reversion, momentum, sideways, MA
strategies/indicator/ — Technical indicators (RSI, MACD, EMA, breakout)
market_data/          — Kraken/Binance feeds, OHLCV aggregation, price engine
exchange/             — CCXT adapters, rate limiters, WebSocket adapters
flash_loan_system/    — Execution optimizer, historical analyzer, opportunity scorer
mcp/                  — Multi-agent coordination protocol, Redis pub/sub
shared_contracts/     — Canonical types shared with signals-api (NEVER modify without syncing)
config/               — YAML settings, exchange configs, trading pairs
pnl/                  — Paper fill simulator, rolling PnL
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

- `REDIS_URL` — `rediss://` required (TLS)
- `ENGINE_MODE` — `paper` or `live` (controls stream separation)
- `KRAKEN_API_KEY`, `KRAKEN_API_SECRET` — exchange credentials
- `TRADING_PAIRS` — comma-separated, e.g. `BTC/USD,ETH/USD,SOL/USD`

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

### Sprint 3 — PLANNED
- [ ] Deploy to Fly.io and validate signals flowing end-to-end
- [ ] Enable ONCHAIN_FAMILY_ENABLED=true after CoinGlass data validated
- [ ] ML confidence scoring (trainer/, Family E)
- [ ] SSE streaming verification on signals-site dashboard
