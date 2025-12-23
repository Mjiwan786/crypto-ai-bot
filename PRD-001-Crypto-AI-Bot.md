# PRD-001: Crypto AI Bot - Core Intelligence Engine

**Document Type:** Derived PRD – Based on Current Implementation
**Version:** 1.2.0
**Status:** Acquisition-Ready
**Last Validated:** 2025-12-19
**Classification:** Diligence Documentation

---

## Document Purpose

This Product Requirements Document describes the **current, verified implementation** of the crypto-ai-bot repository. It is prepared for acquisition due diligence on Acquire.com and reflects the production-ready state of the system as of the validation date.

**Methodology:** This PRD was derived through systematic code analysis, configuration review, and documentation audit. All claims are traceable to implemented code.

---

## 1. Overview / Purpose

### 1.1 What This Repository Does

The `crypto-ai-bot` repository is the **core intelligence and signal generation engine** for a production-grade, AI-driven cryptocurrency trading system. It:

- Consumes real-time market data from Kraken WebSocket APIs
- Processes data through a multi-agent AI architecture
- Generates actionable trading signals with risk management
- Publishes structured signals to Redis Streams for downstream consumption

### 1.2 Role in 3-Repository Architecture

This repository is **Repo 1 of 3** in the complete trading infrastructure:

| Repository | Function | Relationship |
|------------|----------|--------------|
| **crypto-ai-bot** (this repo) | Signal generation engine | Publishes to Redis |
| **signals-api** | REST/SSE API gateway | Consumes from Redis, serves clients |
| **signals-site** | Front-end SaaS portal | Displays signals to end users |

### 1.3 Operational Model

The crypto-ai-bot operates as a **headless, event-driven service**:

- Runs continuously (24/7) in production on Fly.io
- Deployed via `Dockerfile.production` as a single long-lived Python process
- Maintains persistent WebSocket connections to Kraken
- Publishes structured signals to Redis Cloud (TLS-secured)
- Exposes `/health` endpoint for orchestration
- Exposes Prometheus metrics for observability
- Supports paper and live modes via `ENGINE_MODE` environment variable

---

## 2. Core Responsibilities

### 2.1 Kraken WebSocket Ingestion

**Implementation:** `utils/kraken_ws.py`, `production_engine.py`

| Capability | Implementation |
|------------|----------------|
| Channels subscribed | ticker, spread, trade, book (L2), ohlc |
| Supported pairs | BTC/USD, ETH/USD, SOL/USD, LINK/USD (4 active) |
| Heartbeat monitoring | PING/PONG every 30s |
| Auto-reconnect | Exponential backoff: 1s → 60s max, 10 attempts |
| Data validation | Sequence number tracking, timestamp freshness |
| Error handling | Logged at ERROR level, Prometheus metrics |

### 2.2 Redis Streams Publishing

**Implementation:** `agents/infrastructure/redis_client.py`, `agents/infrastructure/prd_publisher.py`

| Capability | Implementation |
|------------|----------------|
| Connection | TLS via `rediss://` scheme, connection pooling (max 10) |
| Stream routing | Paper: `signals:paper:<PAIR>`, Live: `signals:live:<PAIR>` |
| PnL streams | `pnl:paper:equity_curve`, `pnl:live:equity_curve` |
| MAXLEN | 10,000 messages per stream (approximate trimming) |
| Idempotency | `signal_id` (UUID) as message ID |
| Schema validation | Pydantic models before publish |

### 2.3 Multi-Agent ML Engine

**Implementation:** `agents/`, `ai_engine/`

| Agent | Responsibility |
|-------|----------------|
| Regime Detector | Classifies market state (TRENDING_UP/DOWN, RANGING, VOLATILE) |
| Signal Analyst | Generates trade signals (LONG/SHORT, entry/exit prices, confidence) |
| Risk Manager | Validates signals against risk limits |
| Position Manager | Tracks open positions, manages exits |

**Strategies Implemented:**
- Scalper (40% allocation)
- Trend Following (30% allocation)
- Mean Reversion (20% allocation)
- Breakout (10% allocation)

### 2.4 Risk Management Engine

**Implementation:** `config/risk_config.py`, `config/risk_config.yaml`

| Control | Implementation |
|---------|----------------|
| Spread limit | Reject if > 0.5% |
| Volatility adjustment | ATR-based position sizing |
| Daily drawdown | -5% circuit breaker |
| Position limits | $2,000 max per position, $10,000 total exposure |
| Loss streak tracking | Pause after 5 consecutive losses |

---

## 3. Key Functional Requirements

### 3.1 Signal Schema (Canonical)

All signals conform to the following JSON schema:

```json
{
  "signal_id": "UUID v4",
  "timestamp": "ISO8601 UTC",
  "pair": "BTC/USD",
  "side": "LONG | SHORT",
  "strategy": "SCALPER | TREND | MEAN_REVERSION | BREAKOUT",
  "regime": "TRENDING_UP | TRENDING_DOWN | RANGING | VOLATILE",
  "entry_price": 43250.50,
  "take_profit": 43500.00,
  "stop_loss": 43100.00,
  "position_size_usd": 150.00,
  "confidence": 0.72,
  "risk_reward_ratio": 1.67,
  "indicators": {
    "rsi_14": 58.3,
    "macd_signal": "BULLISH | BEARISH | NEUTRAL",
    "atr_14": 425.80,
    "volume_ratio": 1.23
  },
  "metadata": {
    "model_version": "v2.1.0",
    "backtest_sharpe": 1.85,
    "latency_ms": 127
  }
}
```

### 3.2 Data Integrity

| Requirement | Implementation |
|-------------|----------------|
| Timestamp ordering | Monotonically increasing, server-side clock |
| Deduplication | UUID-based, Redis auto-rejects duplicates |
| Sequence validation | Gap detection with alerting |
| Idempotency | signal_id as Redis message ID |

### 3.3 Health & Monitoring

| Endpoint | Port | Purpose |
|----------|------|---------|
| `/health` | 8080 | Fly.io health checks |
| `/metrics` | 9108 | Prometheus scrape endpoint |

**Health Criteria:**
- Kraken WebSocket connected
- Redis connection alive (PING successful)
- Signals published within last 10 minutes

---

## 4. Non-Goals / Out-of-Scope

| Item | Responsibility |
|------|----------------|
| Order execution | Handled by signals-api (Repo 2) |
| User interface | Handled by signals-site (Repo 3) |
| Long-term data storage | API responsibility; bot maintains 24hr window |
| Multi-exchange support | V1 targets Kraken only; Binance integration prepared but not active |
| User authentication | API layer responsibility |

---

## 5. Operational Characteristics

### 5.1 Runtime Behavior

| Characteristic | Value |
|----------------|-------|
| Language | Python 3.10.18 |
| Runtime | Single async process (asyncio) |
| Deployment | Fly.io Machines |
| Region | US East (iad) - closest to Redis Cloud |
| Memory | 2GB allocated |
| CPUs | 2 shared vCPUs |

### 5.2 Statelessness

The engine is designed for stateless operation:

- All state persisted to Redis streams
- Positions stored in Redis: `state:positions:{pair}`
- Regime labels stored in Redis: `state:regime:{pair}`
- TTL: 24 hours for state data
- Restart recovery loads state from Redis

### 5.3 Performance Targets

| Metric | Target |
|--------|--------|
| P50 latency | ≤ 200ms |
| P95 latency | ≤ 500ms |
| P99 latency | ≤ 1000ms |
| Signal publish rate | ≥ 10/hour per pair |
| Uptime | ≥ 99.5% |

---

## 6. Security & Secrets Handling

### 6.1 Secrets Management

**All credentials are managed via environment variables. No secrets are hardcoded in the codebase.**

| Secret | Environment Variable | Storage |
|--------|---------------------|---------|
| Redis URL | `REDIS_URL` | Fly.io Secrets / Platform Secret Store |
| Redis Password | (embedded in REDIS_URL) | Fly.io Secrets |
| Redis CA Certificate | `REDIS_CA_CERT` (path) | File at `/app/config/certs/redis_ca.pem` |
| Kraken API Key | `KRAKEN_API_KEY` | Fly.io Secrets (live mode only) |
| Kraken API Secret | `KRAKEN_API_SECRET` | Fly.io Secrets (live mode only) |
| OpenAI API Key | `OPENAI_API_KEY` | Fly.io Secrets (optional) |

### 6.2 Security Practices

| Practice | Implementation |
|----------|----------------|
| TLS for Redis | Required (`rediss://` scheme enforced) |
| Certificate validation | CA cert verified on connection |
| No secrets in code | All credentials via env vars |
| No secrets in logs | Password redaction in error messages |
| No secrets in fly.toml | Secrets set via `fly secrets set` |

### 6.3 Example Environment Files

The repository includes example files with placeholder values:

- `.env.example` - Template with `<YOUR_REDIS_PASSWORD>`, `<YOUR_KRAKEN_API_KEY>`
- `.env.paper.example` - Paper trading template
- `.env.live.example` - Live trading template

**Actual `.env` files with real credentials are gitignored and never committed.**

### 6.4 Verified: No Secrets in Repository

A security scan of the codebase confirms:
- No hardcoded API keys, passwords, or tokens in source code
- All `*.py` files use `os.getenv()` for credentials
- Configuration files use `${VARIABLE}` syntax for injection
- Example files contain only placeholder values

---

## 7. Ownership Transfer Notes

### 7.1 Credential Rotation Readiness

The system is designed for credential rotation without code changes:

| Credential | Rotation Procedure |
|------------|-------------------|
| Redis password | Update via `fly secrets set REDIS_URL=...`, restart |
| Kraken API keys | Update via `fly secrets set`, restart |
| TLS certificate | Replace file, restart |

### 7.2 Transfer Checklist

**Pre-Transfer (Seller):**
- [ ] Document all active secrets locations
- [ ] Prepare new credential creation instructions
- [ ] Export current configuration (sans secrets)
- [ ] Document Redis Cloud account details

**Transfer (Both Parties):**
- [ ] Buyer creates new Redis Cloud account
- [ ] Buyer creates new Kraken API keys
- [ ] Buyer generates new TLS certificates
- [ ] Update all environment variables
- [ ] Verify system operation

**Post-Transfer (Buyer):**
- [ ] Rotate all inherited credentials
- [ ] Update Fly.io account ownership
- [ ] Update DNS/domain ownership
- [ ] Update GitHub repository ownership
- [ ] Verify monitoring and alerting

### 7.3 Infrastructure Dependencies

| Service | Account Required | Purpose |
|---------|-----------------|---------|
| Fly.io | Yes | Application hosting |
| Redis Cloud | Yes | Data streaming infrastructure |
| Kraken | Yes (live mode) | Market data and trading |
| GitHub | Yes | Source code repository |

### 7.4 Codebase Health Indicators

| Indicator | Status |
|-----------|--------|
| Test suite | pytest with unit/integration tests |
| CI/CD | GitHub Actions configured |
| Documentation | Comprehensive (PRDs, runbooks, architecture) |
| Type hints | Partial coverage, mypy configured |
| Code style | ruff linter, consistent formatting |

---

## 8. Configuration Reference

### 8.1 Required Environment Variables

```bash
# Core
ENGINE_MODE=paper                    # paper | live
REDIS_URL=<REDIS_CONNECTION_STRING>  # rediss://...
REDIS_CA_CERT=/app/config/certs/redis_ca.pem

# Trading
TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD,LINK/USD

# Live mode only
KRAKEN_API_KEY=<API_KEY>
KRAKEN_API_SECRET=<API_SECRET>
LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_REAL_MONEY
```

### 8.2 Key Configuration Files

| File | Purpose |
|------|---------|
| `config/settings.yaml` | Core application settings |
| `config/trading_pairs.py` | Canonical trading pair definitions |
| `config/risk_config.yaml` | Risk management parameters |
| `fly.toml` | Fly.io deployment configuration |
| `Dockerfile.production` | Production container build |

### 8.3 Redis Stream Names

| Stream Pattern | Purpose |
|----------------|---------|
| `signals:paper:<PAIR>` | Paper trading signals |
| `signals:live:<PAIR>` | Live trading signals |
| `pnl:paper:equity_curve` | Paper mode P&L |
| `pnl:live:equity_curve` | Live mode P&L |
| `kraken:metrics` | System health metrics |
| `kraken:heartbeat` | Connection health |

---

## 9. File Structure Summary

```
crypto-ai-bot/
├── agents/                    # Multi-agent system
│   ├── infrastructure/        # Redis, Kraken clients
│   └── config/               # Agent configuration
├── ai_engine/                # ML models and analysis
├── backtesting/              # Backtest framework
├── config/                   # Configuration files
│   ├── settings.yaml         # Core settings
│   ├── trading_pairs.py      # Pair definitions
│   └── certs/               # TLS certificates (gitignored contents)
├── core/                     # Core utilities
├── docs/                     # Documentation
├── monitoring/               # Prometheus integration
├── pnl/                      # P&L tracking
├── strategies/               # Trading strategies
├── tests/                    # Test suite
├── utils/                    # Kraken WebSocket, helpers
├── main_engine.py            # Primary entrypoint
├── production_engine.py      # Production entrypoint
├── fly.toml                  # Fly.io configuration
├── Dockerfile.production     # Production container
└── requirements.txt          # Python dependencies
```

---

## 10. Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.2.0 | 2025-12-19 | Acquisition-ready format: Added Security & Secrets Handling, Ownership Transfer Notes, removed marketing language |
| 1.1.0 | 2025-11-22 | Updated for Redis TLS + Fly.io architecture |
| 1.0.0 | 2025-11-14 | Initial authoritative PRD |

---

## Appendix: Security Verification Statement

This document was prepared with the following security measures:

1. **Secret Scanning:** All source files scanned for hardcoded credentials - none found
2. **Placeholder Verification:** All example files contain only placeholder values
3. **Environment Variable Audit:** All credentials loaded via `os.getenv()` pattern
4. **No Sensitive Data:** This PRD contains no actual API keys, passwords, tokens, or connection strings

**Prepared for Acquire.com due diligence review.**

---

*END OF DOCUMENT*
