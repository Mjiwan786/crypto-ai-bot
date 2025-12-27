# Acquisition Handoff Guide

This document provides everything a buyer needs to understand, operate, and extend the crypto-ai-bot system.

## What This Repository Owns

### Core Trading Engine
- Multi-agent trading framework (AutoGen + LangGraph orchestration)
- Real-time market data ingestion (Kraken WebSocket)
- Signal generation and strategy execution
- Risk management and position sizing
- Order execution with idempotency guarantees

### Trading Strategies
- Momentum trading
- Mean reversion
- Scalping (Kraken-optimized)
- Bar reaction (5-minute timeframe)
- Overnight momentum
- Flash loan arbitrage (experimental)

### Infrastructure
- Redis Streams data pipeline (TLS-secured)
- Prometheus metrics and monitoring
- Docker Compose deployment
- Health checks and circuit breakers
- Emergency stop mechanisms

### Data & Analytics
- Backtest engine with equity curve export
- PnL tracking and reporting
- Performance metrics dashboard
- Historical trade analysis

## External Dependencies

This system is designed to work with companion repositories:

| Repository | Purpose | Integration Point |
|------------|---------|-------------------|
| `signals-api` | FastAPI backend for signal serving | Consumes `data/backtests/*.json` |
| `signals-site` | Next.js frontend dashboard | Displays via signals-api |

### Third-Party Services

| Service | Purpose | Required |
|---------|---------|----------|
| Kraken | Exchange API (trading) | Yes |
| Redis Cloud | Message broker (streams) | Yes (prod) |
| Prometheus | Metrics collection | Recommended |
| Grafana | Dashboards | Optional |
| Discord | Alerting | Optional |
| OpenAI | AI features | Optional |

## What Buyer Receives

### Code Assets
- Complete source code with git history
- All trading strategies and algorithms
- Test suites (unit, integration, smoke)
- Docker deployment configurations
- Documentation and guides

### Data Assets
- Backtest results and equity curves
- Configuration templates
- Sample monitoring dashboards

### Documentation
- Architecture documentation
- API references
- Deployment guides
- Troubleshooting guides

### NOT Included
- API keys or credentials (buyer must create own)
- TLS certificates (buyer must obtain own)
- Historical market data (must be fetched)
- Active subscriptions (Redis Cloud, etc.)

## 30/60/90 Day Roadmap

### Days 1-30: Foundation

**Week 1: Setup & Verification**
- [ ] Clone repository and verify build
- [ ] Configure environment variables
- [ ] Run smoke tests (`docs/SMOKE_TESTS.md`)
- [ ] Set up Redis Cloud account
- [ ] Configure Kraken API keys

**Week 2: Paper Trading**
- [ ] Deploy in paper trading mode
- [ ] Monitor for 72+ hours
- [ ] Review logs and metrics
- [ ] Validate signal generation
- [ ] Test emergency stop

**Week 3-4: Infrastructure**
- [ ] Set up Prometheus/Grafana
- [ ] Configure Discord alerts
- [ ] Document runbook procedures
- [ ] Train team on operations

### Days 31-60: Optimization

**Week 5-6: Performance Tuning**
- [ ] Analyze backtest results
- [ ] Tune strategy parameters
- [ ] Optimize position sizing
- [ ] Review risk limits

**Week 7-8: Extended Validation**
- [ ] Extended paper trading (2+ weeks)
- [ ] A/B test strategy variants
- [ ] Document performance baselines
- [ ] Prepare live trading checklist

### Days 61-90: Production

**Week 9-10: Live Preparation**
- [ ] Final security audit
- [ ] Live trading checklist review
- [ ] Team sign-off on procedures
- [ ] Incident response plan

**Week 11-12: Controlled Launch**
- [ ] Start with minimal position sizes
- [ ] Monitor intensively (24/7)
- [ ] Gradual position size increase
- [ ] Continuous performance review

## Post-Sale Support Expectations

### Included Support (30 days)

| Support Type | Scope | Response Time |
|--------------|-------|---------------|
| Critical bugs | System won't start | 24 hours |
| Documentation gaps | Missing setup info | 48 hours |
| Architecture Q&A | Design clarification | 72 hours |

### Not Included

- Strategy development or tuning
- New feature development
- Exchange integration additions
- Performance optimization
- Ongoing maintenance

### Extended Support (Optional)

Extended support packages may be negotiated separately:
- Monthly advisory calls
- Priority bug fixes
- Feature development
- Performance consulting

## Key Files Reference

| File | Purpose |
|------|---------|
| `README.md` | Quick start and overview |
| `HANDOFF.md` | This document |
| `docs/PRD-001-CRYPTO-AI-BOT.md` | Product requirements |
| `docs/ENVIRONMENT_MATRIX.md` | Environment configuration |
| `docs/SMOKE_TESTS.md` | Buyer verification |
| `docs/SECURITY_TRANSFER.md` | Credential setup |
| `docs/DUE_DILIGENCE_CHECKLIST.md` | Technical audit |
| `docs/AGENTS_OVERVIEW.md` | System architecture |
| `config/risk_config.yaml` | Risk management settings |

## Contacts

**Technical Questions:** [To be provided at closing]

**Support Email:** [To be provided at closing]

**Emergency Contact:** [To be provided at closing]

---

*This handoff guide was prepared as part of the acquisition package. All information is accurate as of the handoff date.*
