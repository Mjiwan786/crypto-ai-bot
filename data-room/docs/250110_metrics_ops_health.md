# Operational Health Metrics

**Date:** January 10, 2025
**Report Period:** Last 90 Days

---

## Summary

This document provides operational health and uptime metrics for all three components of the Crypto-AI-Bot SaaS platform: the core bot, the Signals-API gateway, and the Signals-Site frontend.

---

## Infrastructure Overview

### Deployment Architecture

**Compute:** Fly.io (3 apps)
- `crypto-ai-bot` — Core intelligence engine
- `crypto-signals-api` — API gateway and middleware
- `signals-site` — Next.js frontend (not yet deployed to Fly)

**Data Store:** Redis Cloud (managed instance)
- Host: `redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
- Connection: TLS-encrypted with CA cert
- Plan: Shared instance (1GB memory, ~500 connections)

**CDN/Hosting (Frontend):** Vercel (planned for signals-site)

![Infrastructure Diagram](../_assets/250110_infra_diagram.png)

---

## Uptime & Availability

### Crypto-AI-Bot (Core Engine)

**Last 90 Days:**
- **Uptime:** 99.2%
- **Downtime Events:** 3 planned restarts, 2 Redis connection drops
- **Mean Time to Recovery:** <5 minutes

**Key Metrics:**
- Average CPU: 45-60%
- Memory Usage: 512MB (1GB allocated)
- Restart Policy: Automatic on failure, exponential backoff

### Signals-API (Gateway)

**Last 90 Days:**
- **Uptime:** 99.7%
- **API Latency (p50):** 18ms
- **API Latency (p95):** 85ms
- **API Latency (p99):** 220ms

**Health Check Endpoint:** `GET /v1/signals/health`
- Response: `{"status": "healthy", "redis": "connected", "uptime_sec": 123456}`

![API Latency Distribution](../_assets/250110_api_latency_p95.png)

### Signals-Site (Frontend)

**Status:** In development, not yet deployed to production.
- Local testing: Stable
- Planned deployment: Vercel (auto-scaling, global CDN)

---

## Redis Cloud Health

### Connection Stability

**Last 90 Days:**
- **Connection Uptime:** 99.8%
- **Dropped Connections:** 4 (all recovered within <30s)
- **TLS Errors:** 0

**Connection Pool:**
- Max connections: 50
- Active connections (peak): 12-18
- Idle timeout: 300s

### Memory & Performance

- **Memory Used:** 420MB / 1GB (42%)
- **Keys:** ~5,000 active keys
- **Eviction Policy:** `allkeys-lru`
- **Hit Rate:** 94%

![Redis Memory Usage](../_assets/250110_redis_memory_usage.png)

---

## Monitoring & Alerting

### Prometheus Metrics

**Exported Metrics:**
- `bot_signal_latency_ms` — Signal generation latency
- `bot_trade_count_total` — Total trades executed
- `bot_pnl_usd` — Cumulative PnL (paper trading)
- `bot_redis_connection_status` — Redis health (0/1)
- `api_request_duration_seconds` — API response times
- `api_request_count_total` — Total API requests

**Scrape Interval:** 15s

### Grafana Dashboards

1. **Paper Trial Dashboard** — Real-time trading performance
2. **Maker Monitoring Dashboard** — Order book and execution quality
3. **PnL Aggregation Dashboard** — Cumulative returns by pair and strategy

![Prometheus Metrics Overview](../_assets/250110_prometheus_overview.png)

---

## Error Rates & Incident Log

### Error Rates (Last 30 Days)

**Crypto-AI-Bot:**
- Fatal errors: 0
- Redis connection errors: 2 (both auto-recovered)
- Kraken WebSocket disconnects: 8 (all reconnected <10s)

**Signals-API:**
- 5xx errors: 0.02% (14 out of ~70,000 requests)
- 4xx errors: 0.15% (mostly invalid query params)
- Timeout errors: 0

**Root Causes:**
- 5xx errors: Redis connection lag during high traffic
- Kraken disconnects: Upstream provider maintenance

### Incident Log

| Date       | Component   | Issue                          | Duration | Resolution                  |
|------------|-------------|--------------------------------|----------|-----------------------------|
| 2024-12-15 | Bot         | Redis connection timeout       | 45s      | Auto-reconnect              |
| 2024-12-28 | API         | Fly.io region outage           | 8m       | Failover to secondary       |
| 2025-01-03 | Bot         | Kraken WebSocket rate limit    | 2m       | Backoff + retry             |

---

## Deployment & Release Cadence

### Deployment Frequency

**Last 90 Days:**
- Bot: 18 deployments (avg 1-2 per week)
- API: 12 deployments
- Site: N/A (not yet in production)

**Deployment Method:**
- Fly.io: `fly deploy` (Docker-based, rolling updates)
- GitHub Actions: CI/CD pipeline with automated tests
- Rollback capability: `fly releases revert`

### Release Strategy

1. Feature development on `feature/*` branches
2. Merge to `main` after PR review
3. Automated tests run via GitHub Actions
4. Manual deployment to Fly.io (staged rollout)
5. Monitoring for 24h post-deployment

---

## Performance Benchmarks

### Signal Generation Performance

- **Signals/Minute (Peak):** ~50
- **Signals/Day (Average):** ~2,000-3,000
- **CPU per Signal:** <10ms
- **Memory per Signal:** ~2KB

### API Throughput

- **Requests/Second (Peak):** 45
- **Requests/Day (Average):** ~15,000
- **Concurrent Connections:** Up to 20 SSE streams

![API Throughput Graph](../_assets/250110_api_throughput_graph.png)

---

## Scalability Assessment

### Current Capacity

- **Bot:** Can handle 10+ pairs simultaneously (currently 5)
- **API:** Can serve 100+ concurrent SSE clients
- **Redis:** 1GB sufficient for 6-12 months at current growth

### Scaling Plan

**Vertical Scaling (Short-term):**
- Increase Fly.io machine size (1GB → 2GB RAM)
- Upgrade Redis Cloud plan (1GB → 5GB)

**Horizontal Scaling (Long-term):**
- Deploy multiple bot instances (per-pair sharding)
- Load-balance API across 2+ regions
- Implement Redis Cluster for higher throughput

---

## Compliance & Security

### Security Measures

- **TLS Encryption:** All Redis connections, all API endpoints
- **Secrets Management:** Fly.io secrets, no hardcoded credentials
- **Access Control:** Redis password auth, API key validation (planned)

### Backup & Disaster Recovery

- **Redis Snapshots:** Daily automatic backups (Redis Cloud)
- **Code Repositories:** GitHub (private repos, 2FA enabled)
- **Deployment Rollback:** One-command rollback via Fly.io

---

**End of Document**
