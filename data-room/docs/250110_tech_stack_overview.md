# Technical Stack Overview

**Date:** January 10, 2025

---

## What It Is

A three-tier crypto trading signals platform: a Python bot generates ML-powered signals from live Kraken data, publishes them to Redis Cloud, and serves them via a Node.js API and Next.js frontend. Everything runs in production on Fly.io with 99%+ uptime.

---

## Repos & Hosting

**crypto-ai-bot** (Python 3.11)
- ML regime detection, multi-strategy signal generation, risk management
- Hosted: Fly.io (`crypto-ai-bot` app, 512MB RAM, US East)
- Conda env: `crypto-bot`
- Key libraries: ccxt, pandas, scikit-learn, redis, pydantic, prometheus-client

**signals-api** (Node.js 20.x)
- REST API + SSE streaming gateway
- Hosted: Fly.io (`crypto-signals-api`, https://signals-api-gateway.fly.dev)
- Conda env: `signals-api` (local dev)
- Key libraries: Express, ioredis, helmet, prom-client

**signals-site** (Next.js 14, TypeScript)
- Frontend dashboard (React, TailwindCSS, SWR)
- Planned: Vercel deployment (not yet live)
- Auth/billing integration in progress

---

## Integrations

**Kraken WebSocket/REST**
- Live market data (15s/1m/5m OHLC, trades, spreads)
- 5 trading pairs: BTC, ETH, SOL, MATIC, LINK
- Auto-reconnect logic, 99.5%+ uptime

**Redis Cloud (TLS)**
- Host: `redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
- Streams: `bot:signals:live`, `bot:pnl:aggregated`, `bot:metrics:freshness`
- TLS cert: `config/certs/redis_ca.pem`
- Daily backups, AOF enabled

**Prometheus/Grafana**
- Metrics: signal latency, trade counts, PnL, API response times
- Dashboards: `monitoring/grafana/paper_trial_dashboard.json`
- Scrape interval: 15s

**Secrets Management**
- Fly.io: `fly secrets set REDIS_URL="rediss://..."`
- Local: `.env.paper`, `.env.live` (gitignored)
- No hardcoded credentials

---

## Signal Flow

```
┌──────────────────┐
│  Kraken WS/REST  │  (Live market data)
└────────┬─────────┘
         │
         v
┌─────────────────────────────────┐
│  crypto-ai-bot (Python)         │
│  • Regime detection (ML)        │
│  • Strategy selection           │
│  • Risk filtering               │
│  • Signal generation            │
└────────┬────────────────────────┘
         │ XADD (Redis Streams)
         v
┌─────────────────────────────────┐
│  Redis Cloud (TLS)              │
│  • bot:signals:live             │
│  • bot:pnl:aggregated           │
│  • TTL: 7 days                  │
└────────┬────────────────────────┘
         │ XREAD
         v
┌─────────────────────────────────┐
│  signals-api (Node.js)          │
│  • GET /v1/signals/latest       │
│  • SSE /v1/signals/sse          │
│  • JSON responses               │
└────────┬────────────────────────┘
         │ HTTPS
         v
┌─────────────────────────────────┐
│  signals-site (Next.js)         │
│  • Real-time dashboard          │
│  • Subscriber auth (planned)    │
│  • Billing (planned)            │
└─────────────────────────────────┘
```

---

## Security & Safety

**Transport Security**
- All Redis connections: TLS 1.2+ (`rediss://` protocol)
- API: HTTPS via Fly.io auto-provisioned certs
- CA certs stored in `config/certs/`

**Risk Controls**
- Daily loss limits: -2% account balance
- Max concurrent trades: 5 per pair
- Max leverage: 1x (spot only, no margin)
- Event guards: news catalysts, liquidity filters, spread filters

**Code Quality**
- Python: `black`, `flake8`, `mypy`, pytest (unit + integration tests)
- TypeScript: `eslint`, `prettier`
- CI: GitHub Actions (automated testing on push)

**Monitoring**
- Health checks: `/health` endpoints on both apps
- Prometheus metrics exported every 15s
- Circuit breakers and killswitches implemented

---

## What a Buyer Gets on Day 1

**Infrastructure Access**
- Full transfer of 2 Fly.io apps (crypto-ai-bot, crypto-signals-api)
- Redis Cloud instance credentials and CA cert
- Domain/DNS records (if applicable)

**Source Code**
- 3 private GitHub repos (crypto-ai-bot, signals-api, signals-site)
- All config files: YAML, .env templates, fly.toml, Dockerfiles
- 18 months of documentation (PRDs, runbooks, deployment guides)

**Operational Assets**
- Grafana dashboards (JSON exports)
- Prometheus scrape configs
- Conda environment specs
- Deployment scripts and CI/CD workflows

**Knowledge Transfer**
- 12 weeks of handover support (5–6 hrs/week)
- Video walkthroughs, architecture diagrams
- Access to seller for troubleshooting during transition

**Cost Structure**
- Current: ~$50/month (Fly.io + Redis Cloud shared plan)
- Scaling to 100 users: ~$70/month (upgrade Redis to 5GB)
- No vendor lock-in, can migrate to AWS/GCP if needed

---

**End of Document**
