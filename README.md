# Crypto AI Bot - Production Trading System

[![CI](https://github.com/maithamali/crypto-ai-bot/workflows/CI/badge.svg)](https://github.com/maithamali/crypto-ai-bot/actions)
[![Python 3.10.18](https://img.shields.io/badge/python-3.10.18-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

**A production-ready, multi-agent crypto trading system with Redis streams, risk management, and real-time monitoring.**

## 🚀 Highlights

• **Multi-Agent Architecture** - AutoGen + LangGraph orchestration with specialized trading agents
• **Real-Time Data Pipeline** - Redis streams with TLS, circuit breakers, and idempotency guarantees
• **Production SLOs** - P95 latency <500ms, 99.5% uptime, <0.1% duplicate rate
• **Risk Management** - Configurable drawdown limits, position sizing, and emergency stops
• **Zero-Config Deployment** - Docker Compose with health checks and monitoring

## 📋 Product Requirements

**👉 [PRD-001: Crypto AI Bot - Core Intelligence Engine](docs/PRD-001-CRYPTO-AI-BOT.md)**

This is the **authoritative product specification** for this repository. It defines:
- Complete functional requirements for all subsystems
- Canonical signal schema (shared across all 3 repos)
- Data integrity & risk management requirements
- ML transparency & testing standards
- Success criteria & measurable KPIs

**All development, testing, and deployment must align with PRD-001.**

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Data Sources  │    │   Redis Cloud   │    │  Trading Agents │
│                 │    │                 │    │                 │
│ • Kraken WS     │───▶│ • Streams       │───▶│ • Risk Manager  │
│ • Market Data   │    │ • Pub/Sub       │    │ • Strategy      │
│ • News/Sentiment│    │ • TLS Security  │    │ • Execution     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Monitoring    │    │   Orchestration │    │   Risk/Safety   │
│                 │    │                 │    │                 │
│ • Prometheus    │    │ • LangGraph     │    │ • Circuit Breaks│
│ • Grafana       │    │ • AutoGen       │    │ • Position Limits│
│ • SLO Tracking  │    │ • State Machine │    │ • Emergency Stop│
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Architecture Deep Dive

For detailed technical documentation:
- **[PRD-001](docs/PRD-001-CRYPTO-AI-BOT.md)** - Authoritative product requirements & system specification
- **[Agents Overview](docs/AGENTS_OVERVIEW.md)** - System dataflow, Redis streams, and component breakdown (2-min read)
- [Project Skeleton](docs/PROJECT_SKELETON.md) - Complete project structure and file organization
- [Architecture Overview](docs/README-ARCH.md) - Design philosophy and directory layout

## Runtime Compatibility

**Targets Python 3.10.18** - Optimized for stability and performance in production environments.

## Quickstart

### Docker (Recommended)

```bash
# Clone and start
git clone <repository-url>
cd crypto-ai-bot
docker compose up -d

# Verify health
docker compose ps
# bot: healthy, redis: running
```

### Local Development

```bash
# Setup conda environment
conda create -n crypto-bot python=3.10
conda activate crypto-bot

# Install dependencies
pip install -e .

# Configure environment
cp env.local.example .env.local
# Edit .env.local with your API keys

# Run preflight checks
python scripts/preflight.py

# Start trading (paper mode)
crypto-ai-bot --mode paper
```

## Environment Matrix

| Environment | Mode | Redis | Risk Limits | Logging |
|-------------|------|-------|-------------|---------|
| **dev** | paper | local | 0.5% position | DEBUG |
| **staging** | paper | Cloud TLS | 2% position | INFO |
| **prod** | live | Cloud TLS | 5% position | WARNING |

## Redis Streams Contract

### Stream Keys
- `market:data` - Real-time price feeds
- `signals:generated` - Trading signals
- `orders:executed` - Order confirmations
- `risk:alerts` - Risk management events

### Payload Shapes
```json
// Market Data
{
  "symbol": "BTC/USD",
  "price": 50000.0,
  "timestamp": "2024-01-01T12:00:00Z",
  "source": "kraken"
}

// Trading Signal
{
  "signal_id": "uuid",
  "symbol": "BTC/USD",
  "action": "BUY|SELL|HOLD",
  "confidence": 0.85,
  "strategy": "momentum",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## Risk & Safety

### Drawdown Protection
- **Max Daily Loss**: 2-10% (configurable per environment)
- **Position Limits**: 0.5-5% of portfolio per trade
- **Circuit Breakers**: Auto-stop on consecutive losses
- **Emergency Stop**: File-based kill switch

### Idempotency
- **Signal Deduplication**: Redis-based dedup with TTL
- **Order Idempotency**: Unique order IDs prevent duplicates
- **State Recovery**: LangGraph state persistence across restarts

### Safety Features
```bash
# Emergency stop
touch /app/emergency_stop.flag

# Circuit breaker config
MAX_CONSECUTIVE_LOSSES=3
CIRCUIT_BREAKER_TIMEOUT=300
```

## SLO & Health

### Service Level Objectives
- **P95 Latency**: <500ms signal processing
- **Uptime**: ≥99.5% availability
- **Stream Lag**: <1s data freshness
- **Duplicate Rate**: <0.1% signal duplication

### Health Monitoring
```bash
# Check system health
curl http://localhost:9000/health

# View metrics
curl http://localhost:9090/metrics

# SLO status
python -m monitoring.slo_tracker --env .env.staging
```

### Monitoring Stack
- **Prometheus**: Metrics collection
- **Grafana**: Dashboards and alerting
- **Redis**: Real-time health checks
- **Discord**: Alert notifications

## Tests & Deployment

### Test Suite
```bash
# Run all tests
pytest -q

# Run with coverage
pytest --cov=agents --cov-report=html

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
```

### Deployment Steps

1. **Staging Burn-in** (72 hours minimum)
   ```bash
   # Deploy to staging
   docker compose -f docker-compose.staging.yml up -d
   
   # Monitor SLOs
   python -m monitoring.slo_tracker --env .env.staging
   ```

2. **Production Deployment**
   ```bash
   # Set production confirmation
   export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
   
   # Deploy to production
   docker compose -f docker-compose.prod.yml up -d
   ```

3. **Post-Deployment Verification**
   ```bash
   # Check health status
   docker compose ps
   
   # Verify SLO compliance
   python monitoring/slo_report.py --env .env.prod
   ```

## Release Steps

For creating a new release:

1. **Tag the version**
   ```bash
   git tag v0.5.0
   git push origin v0.5.0
   ```

2. **Run sale preparation**
   ```bash
   python scripts/sale_prep.py
   ```

3. **Upload release package**
   - Upload `crypto-ai-bot-v0.5.0.zip` to release assets
   - Docker image `crypto-ai-bot:0.5` available for deployment

The sale preparation script performs:
- Secret scanning for exposed credentials
- Code quality checks (ruff, mypy, pytest)
- Docker image build verification
- Release package creation with git archive

## Backtest Export for UI

Generate TradingView-style per-pair backtest artifacts for consumption by `signals-api` and `signals-site`.

### Schema

Per-pair backtest files are stored at `data/backtests/{symbol_normalized}.json`:

```
data/backtests/
  ├── BTC-USD.json
  ├── ETH-USD.json
  ├── SOL-USD.json
  └── ...
```

Each file contains:
- **Equity Curve**: Timestamped equity/PnL points for chart display
- **Trade List**: Entry/exit details for markers and trade table
- **Summary Metrics**: Sharpe, drawdown, win rate, profit factor

**Schema Definition**: See `backtests/schema.py` for full Pydantic models.

### Usage

#### CLI - Single Pair

```bash
# Export BTC/USD backtest (90 days, 1h timeframe)
python -m backtests.exporter --symbol BTC/USD --timeframe 1h --lookback-days 90

# Output: data/backtests/BTC-USD.json
```

#### CLI - Multiple Pairs

```bash
# Export multiple pairs in one command
python -m backtests.exporter \
  --symbol BTC/USD,ETH/USD,SOL/USD \
  --timeframe 1h \
  --lookback-days 90 \
  --capital 10000 \
  --output data/backtests
```

#### Programmatic Usage

```python
from backtests.exporter import run_and_export_backtest

# Run backtest and export to JSON
file_path = run_and_export_backtest(
    symbol="BTC/USD",
    timeframe="1h",
    lookback_days=90,
    initial_capital=10000.0,
    output_dir="data/backtests"
)

print(f"Exported to: {file_path}")
# Output: data/backtests/BTC-USD.json
```

### Integration with API/UI

The exported JSON files are designed for consumption by:

1. **signals-api** (FastAPI backend):
   - Serves backtest data via REST endpoints
   - Example: `GET /api/backtests/BTC-USD`

2. **signals-site** (Next.js frontend):
   - Renders TradingView-style equity charts
   - Displays entry/exit markers on price charts
   - Shows detailed trade table

### File Structure Example

```json
{
  "symbol": "BTC/USD",
  "symbol_id": "BTC-USD",
  "timeframe": "1h",
  "start_ts": "2025-08-01T00:00:00+00:00",
  "end_ts": "2025-11-15T23:59:59+00:00",
  "equity_curve": [
    {
      "ts": "2025-08-01T00:00:00+00:00",
      "equity": 10000.0,
      "balance": 10000.0
    },
    ...
  ],
  "trades": [
    {
      "id": 1,
      "ts_entry": "2025-08-01T12:00:00+00:00",
      "ts_exit": "2025-08-01T14:30:00+00:00",
      "side": "long",
      "entry_price": 43250.50,
      "exit_price": 43500.00,
      "size": 0.02,
      "net_pnl": 4.50,
      "signal": "scalper",
      "exit_reason": "take_profit"
    },
    ...
  ],
  "initial_capital": 10000.0,
  "final_equity": 10500.0,
  "total_return_pct": 5.0,
  "sharpe_ratio": 1.8,
  "max_drawdown_pct": -2.5,
  "win_rate_pct": 55.0,
  "total_trades": 100,
  "profit_factor": 1.6
}
```

### Requirements

- All timestamps are **timezone-aware UTC** (ISO8601 format)
- Works in Docker/Fly.io (relative paths from repo root)
- Floating point values are rounded for JSON serialization
- Schema validated via Pydantic models

## What's Included

### Core System
- ✅ Multi-agent trading framework (AutoGen + LangGraph)
- ✅ Redis streams with TLS security
- ✅ Kraken API integration with rate limiting
- ✅ Risk management and circuit breakers
- ✅ Real-time monitoring and alerting

### Trading Strategies
- ✅ Momentum trading
- ✅ Mean reversion
- ✅ Scalping strategies
- ✅ Flash loan arbitrage
- ✅ Sentiment analysis integration

### Infrastructure
- ✅ Docker Compose with health checks
- ✅ Prometheus + Grafana monitoring
- ✅ Log rotation and management
- ✅ SLO tracking and reporting
- ✅ Discord alerting integration

### Documentation
- ✅ **[PRD-001](docs/PRD-001-CRYPTO-AI-BOT.md)** - Authoritative product requirements
- ✅ Architecture diagrams
- ✅ API documentation
- ✅ Deployment guides
- ✅ Troubleshooting guides
- ✅ SLO compliance reports

## Buyer Handoff

**👉 [HANDOFF.md](HANDOFF.md)** - Complete acquisition guide including:
- What this repository owns
- External dependencies
- 30/60/90 day roadmap
- Post-sale support expectations

See also:
- [docs/ENVIRONMENT_MATRIX.md](docs/ENVIRONMENT_MATRIX.md) - Environment configuration
- [docs/SMOKE_TESTS.md](docs/SMOKE_TESTS.md) - Buyer verification steps
- [docs/DUE_DILIGENCE_CHECKLIST.md](docs/DUE_DILIGENCE_CHECKLIST.md) - Technical audit checklist
- [docs/SECURITY_TRANSFER.md](docs/SECURITY_TRANSFER.md) - Credential setup guide

## Handover Checklist

### Technical Handover
- [ ] All environment files configured
- [ ] API keys and secrets secured
- [ ] Redis Cloud TLS certificates installed
- [ ] Monitoring dashboards imported
- [ ] Alert channels configured

### Operational Readiness
- [ ] SLO burn-in period completed (72h+)
- [ ] All health checks passing
- [ ] Risk limits validated
- [ ] Emergency procedures documented
- [ ] Team training completed

### Production Validation
- [ ] Paper trading validated
- [ ] Live trading confirmation set
- [ ] Monitoring alerts tested
- [ ] Backup procedures verified
- [ ] Incident response plan ready

---

**Ready to deploy in <5 minutes. Production-tested with enterprise-grade monitoring and risk management.**