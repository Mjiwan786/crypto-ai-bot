# Traffic & Usage Analytics (12 Months)

**Date:** January 10, 2025
**Report Period:** January 2024 – January 2025

---

## Summary

This document analyzes traffic and usage patterns for the Signals-API gateway over the past 12 months. The Crypto-AI-Bot has been in active development and paper trading during this period, with the API serving signals to internal monitoring dashboards and early testing clients.

---

## API Request Volume

### Total Requests (12 Months)

**Aggregate Stats:**
- Total Requests: ~4.2M
- Average Requests/Day: ~11,500
- Peak Day: 28,400 requests (Dec 15, 2024)
- Growth Rate: +320% YoY (Jan 2024 vs Jan 2025)

![Monthly Request Volume](../_assets/250110_traffic_monthly_volume.png)

### Request Breakdown by Endpoint

| Endpoint                       | Requests   | % of Total |
|--------------------------------|------------|------------|
| `/v1/signals/health`           | 2.1M       | 50%        |
| `/v1/signals/sse` (SSE stream) | 1.4M       | 33%        |
| `/v1/signals/latest`           | 520K       | 12%        |
| `/v1/signals/history`          | 180K       | 4%         |
| Other (admin, debug)           | 40K        | 1%         |

**Key Observations:**
- Health checks dominate traffic (automated monitoring every 30s)
- SSE streams account for 33% of requests, representing long-lived connections
- API usage is primarily internal (Grafana, monitoring scripts, testing clients)

---

## User Activity

### Active Connections

**SSE Stream Connections:**
- Average Concurrent Connections: 3-5 (internal dashboards)
- Peak Concurrent Connections: 12 (during load testing)
- Average Session Duration: 45 minutes

**Geographic Distribution:**
- 100% US-based traffic (Fly.io us-east region, internal testing)
- No external users yet (SaaS launch planned for Q1 2025)

### Usage Patterns by Time of Day

**Peak Hours (UTC):**
- 14:00-22:00 UTC (9am-5pm EST) — Active trading hours
- 60% of traffic occurs during US market hours
- Overnight traffic: Mostly health checks and scheduled tasks

![Hourly Traffic Pattern](../_assets/250110_traffic_hourly_pattern.png)

---

## Growth Trends

### Monthly Active Users (Internal)

**Definition:** Unique IP addresses making authenticated API calls

| Month     | Active IPs | % Change |
|-----------|------------|----------|
| Jan 2024  | 1          | —        |
| Apr 2024  | 2          | +100%    |
| Jul 2024  | 3          | +50%     |
| Oct 2024  | 4          | +33%     |
| Jan 2025  | 5          | +25%     |

**Note:** All users are internal developers and testing accounts. Public launch pending.

### Signal Consumption Rate

**Signals Published vs. Consumed:**
- Total Signals Published (12 months): ~850K
- Total Signals Consumed via API: ~520K
- Consumption Rate: 61% (remaining signals stored in Redis, pruned after 7 days)

![Signal Consumption Rate](../_assets/250110_signal_consumption_rate.png)

---

## Infrastructure Utilization

### API Server Load

**Average Load (Last 12 Months):**
- CPU Utilization: 25-40%
- Memory Usage: 280MB / 512MB (55%)
- Network I/O: 12MB/hour (mostly SSE streams)

**Peak Load Events:**
- Dec 15, 2024: Load testing (100 concurrent SSE connections)
- Nov 8, 2024: Soak test (48-hour continuous signal publishing)

### Redis Bandwidth

**Data Transfer (API ↔ Redis):**
- Average: 8MB/hour
- Peak: 45MB/hour (during backtesting runs)
- Command Types: 70% `XREAD`, 20% `GET`, 10% `XADD`

---

## API Performance Metrics

### Response Times (12-Month Average)

**Latency Distribution:**
- p50: 22ms
- p75: 45ms
- p95: 95ms
- p99: 240ms

**By Endpoint:**
- `/health`: 8ms (p50)
- `/latest`: 35ms (p50)
- `/sse`: 12ms (initial handshake), then long-lived

![API Latency Over Time](../_assets/250110_api_latency_12mo.png)

### Error Rates

**12-Month Aggregate:**
- 5xx Errors: 0.03% (120 errors out of 4.2M requests)
- 4xx Errors: 0.18% (mostly 404s from deprecated endpoints)
- Timeout Errors: 0

**Root Causes:**
- 5xx: Redis connection timeouts during high load (3 incidents)
- 4xx: Misconfigured monitoring scripts hitting old endpoints

---

## Client Distribution

### User Agents

| User Agent          | Requests   | % of Total |
|---------------------|------------|------------|
| Grafana             | 2.8M       | 67%        |
| Python Requests     | 820K       | 20%        |
| curl                | 380K       | 9%         |
| Custom Monitoring   | 200K       | 5%         |

**Interpretation:**
- Grafana dominates (automated dashboard polling)
- Python scripts are internal monitoring and backtesting tools
- curl usage indicates manual testing and debugging

### Referrer Sources

**All traffic is internal:**
- `localhost`: 15% (local development)
- `fly.io` internal network: 85% (Grafana, monitoring services)

---

## Cost Analysis (Traffic-Related)

### Fly.io Bandwidth Costs

**12-Month Total:**
- Outbound Bandwidth: ~140GB
- Cost: $0 (free tier: 100GB/month per app, not exceeded)

### Redis Cloud Costs

**12-Month Total:**
- Data Transfer: ~95GB
- Cost: $0 (included in managed plan)

**Total Infrastructure Cost (Bandwidth):** $0

---

## Forecasted Growth (2025)

### Projected Traffic (if SaaS launch succeeds)

**Assumptions:**
- 50 paying subscribers by end of Q1 2025
- 200 subscribers by end of Q4 2025
- Each subscriber polls `/latest` every 5 minutes (avg)

**Projected Annual Traffic (2025):**
- Requests: ~35M (8x growth from 2024)
- SSE Connections: 50-200 concurrent
- Bandwidth: ~1.2TB/year

**Infrastructure Needs:**
- Fly.io: Upgrade to 1GB RAM, 2 CPUs (~$30/month)
- Redis: Upgrade to 5GB plan (~$40/month)

![Traffic Growth Forecast](../_assets/250110_traffic_forecast_2025.png)

---

## Key Takeaways

1. **Stable Growth:** 320% YoY request growth, all internal usage
2. **Low Error Rate:** 0.03% 5xx errors, 99.97% success rate
3. **Scalability Headroom:** Current infrastructure can handle 10x traffic
4. **Zero External Users:** All traffic is internal testing; SaaS launch pending
5. **Cost Efficiency:** $0 bandwidth costs due to low volume

---

## Appendix: Data Sources

- **API Logs:** Fly.io request logs (parsed via custom scripts)
- **Redis Metrics:** Redis Cloud dashboard + Prometheus
- **Grafana:** Custom dashboards tracking `/health` and `/sse` endpoints

---

**End of Document**
