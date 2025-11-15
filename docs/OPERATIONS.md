# Operations Guide - Crypto AI Bot

**Quick reference for all operational tasks using canonical scripts.**

## Table of Contents

1. [Environment Setup](#environment-setup)
2. [Daily Operations](#daily-operations)
3. [Pre-Deployment Checks](#pre-deployment-checks)
4. [Backtesting](#backtesting)
5. [System Startup](#system-startup)
6. [Health Monitoring](#health-monitoring)
7. [Troubleshooting](#troubleshooting)
8. [Docker Operations](#docker-operations)

---

## Environment Setup

### Conda Environment: `crypto-bot`

```bash
# Create environment
conda create -n crypto-bot python=3.10.18

# Activate environment
conda activate crypto-bot

# Install dependencies
pip install -e .

# Setup environment (automated)
python scripts/setup_conda_environment.py
```

### Redis Cloud Connection

**Production Connection String:**
```bash
redis://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

**Test Connection with TLS:**
```bash
redis-cli -u redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls \
  --cacert config/certs/ca.crt \
  PING
```

**Expected Response:** `PONG`

### Environment Variables

Required for all environments:
- `REDIS_URL` - Redis Cloud connection string
- `REDIS_TLS=true` - Enable TLS
- `TRADING_MODE=PAPER|LIVE` - Trading mode
- `KRAKEN_API_KEY` - Kraken API key
- `KRAKEN_API_SECRET` - Kraken API secret

Additional for LIVE mode:
- `MODE=live`
- `LIVE_TRADING_CONFIRMATION="I-accept-the-risk"`

---

## Daily Operations

### Morning Routine (Before Market Open)

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Run preflight checks
python scripts/preflight.py --mode prod --strict

# 3. Check Redis connection
python scripts/health.py redis

# 4. Check Kraken API
python scripts/health.py kraken --live

# 5. Verify metrics exporter
python scripts/health.py exporter

# 6. Review system logs
tail -f logs/trading_system_paper.log
```

### During Trading Hours

```bash
# Monitor system health (every 5 minutes)
watch -n 300 python scripts/health.py redis

# Check metrics
curl http://localhost:9308/metrics | grep crypto_ai_bot

# Monitor logs
tail -f logs/trading_system_paper.log | grep -E "ERROR|WARNING|Signal"
```

### End of Day

```bash
# Generate performance report
python scripts/backtest.py smoke --quick

# Backup configuration
cp .env .env.backup.$(date +%Y%m%d)

# Review alerts
python scripts/health.py redis
```

---

## Pre-Deployment Checks

### Development Environment

```bash
# Full validation suite
python scripts/preflight.py --mode dev
python scripts/health.py redis
python scripts/mcp_smoke.py
pytest -q
```

### Staging Environment

```bash
# Staging validation (warnings allowed)
python scripts/preflight.py --mode staging
python scripts/health.py redis
python scripts/health.py kraken --live

# Smoke test backtest
python scripts/backtest.py smoke --quick

# Dry run
python scripts/start_trading_system.py --mode paper --dry-run
```

### Production Environment

```bash
# Strict production validation
python scripts/preflight.py --mode prod --strict

# Full health check
python scripts/health.py redis
python scripts/health.py kraken --live
python scripts/health.py exporter

# Docker verification
python scripts/verify_docker_setup.py --check-metrics

# Schema validation (hermetic)
python scripts/mcp_smoke.py

# Full test suite
pytest -q
```

**Exit Codes:**
- `0` = READY - Safe to deploy
- `1` = NOT_READY - Fix issues before deploying
- `2` = DEGRADED - Warnings present (staging only)

---

## Backtesting

### Quick Smoke Test

```bash
# Test all strategies (no historical data required)
python scripts/backtest.py smoke --quick
```

**Use Case:** Validate strategy implementations before deployment.

### Basic Backtest

```bash
# Backtest single strategy
python scripts/backtest.py basic BTC/USD \
  --strategy momentum \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --fee-bps 5 \
  --slip-bps 2 \
  --plot
```

**Use Case:** Historical performance analysis for a specific strategy.

### Scalper Backtest

```bash
# Backtest scalping strategy with custom fees
python scripts/backtest.py scalper BTC/USD \
  --fee-bps 0.1 \
  --slip-bps 0.05 \
  --plot \
  --out reports/scalper_btc_$(date +%Y%m%d).json
```

**Use Case:** High-frequency trading strategy validation.

### Agent Backtest

```bash
# Backtest with regime-based router
python scripts/backtest.py agent BTC/USD \
  --strategy regime_router \
  --fee-bps 5 \
  --slip-bps 2 \
  --plot \
  --out reports/agent_btc_$(date +%Y%m%d).json
```

**Use Case:** Multi-strategy agent performance analysis.

### Available Strategies

- `breakout` - Breakout trading strategy
- `momentum` - Momentum-based trading
- `mean_reversion` - Mean reversion strategy
- `regime_router` - Multi-regime routing (recommended)

---

## System Startup

### Paper Trading (Safe Mode)

```bash
# Default paper trading
python scripts/start_trading_system.py --mode paper

# With specific strategy
python scripts/start_trading_system.py \
  --mode paper \
  --strategy momentum

# With monitoring
python scripts/start_trading_system.py \
  --mode paper \
  --exporter
```

### Live Trading (Production)

⚠️ **WARNING: Real money at risk**

```bash
# Set required environment variables
export MODE=live
export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"

# Verify preflight
python scripts/preflight.py --mode prod --strict

# Start live trading
python scripts/start_trading_system.py --mode live
```

**Safety Checks:**
1. Preflight must pass with `--strict`
2. `MODE=live` must be set
3. `LIVE_TRADING_CONFIRMATION` must match exactly
4. Kraken API credentials must be valid
5. Redis Cloud connection must be healthy

### Dry Run (Validation Only)

```bash
# Validate configuration without starting
python scripts/start_trading_system.py \
  --mode paper \
  --dry-run
```

**Use Case:** Test configuration changes before deployment.

---

## Health Monitoring

### Redis Health Check

```bash
# Quick Redis ping
python scripts/health.py redis
```

**Output (JSON):**
```json
{
  "status": "healthy",
  "message": "Redis connection OK",
  "redis_url": "rediss://redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818",
  "ssl_enabled": true,
  "redis_version": "7.2.4",
  "latency_ms": 12.34,
  "timestamp": 1704067200
}
```

### Kraken API Health Check

```bash
# Network-free check (skip network call)
python scripts/health.py kraken

# Live check (makes network call)
python scripts/health.py kraken --live
```

**Output (JSON):**
```json
{
  "status": "healthy",
  "message": "Kraken API status: online",
  "kraken_status": "online",
  "latency_ms": 145.67,
  "timestamp": 1704067200
}
```

### Metrics Exporter Health Check

```bash
# Check Prometheus metrics endpoint
python scripts/health.py exporter
```

**Output (JSON):**
```json
{
  "status": "healthy",
  "message": "Prometheus exporter OK",
  "metrics_url": "http://localhost:9308/metrics",
  "metric_count": 42,
  "unique_metrics": 15,
  "latency_ms": 3.21,
  "sample_metrics": ["crypto_ai_bot_signals_total", "..."],
  "timestamp": 1704067200
}
```

### Schema Validation (Hermetic)

```bash
# Test MCP schemas without network
python scripts/mcp_smoke.py

# Verbose output for debugging
python scripts/mcp_smoke.py --verbose
```

**Tests:**
- SignalModel validation and JSON serialization
- MCP Signal schema
- OrderIntent schema
- Fill schema
- ContextSnapshot schema
- Metric schema
- MarketSnapshot schema
- RegimeLabel enum

---

## Troubleshooting

### Redis Connection Issues

```bash
# Test Redis connection
python scripts/health.py redis

# Wait for Redis (with retry)
python scripts/wait_for_redis.py --timeout 15

# Full Redis smoke test
python scripts/redis_cloud_smoke.py
```

### Configuration Issues

```bash
# Validate configuration
python scripts/preflight.py --mode dev

# Check specific issues
python scripts/preflight.py --mode dev --strict

# Dry run to test config
python scripts/start_trading_system.py --mode paper --dry-run
```

### Schema/Marshaling Issues

```bash
# Test all schemas (no network)
python scripts/mcp_smoke.py --verbose
```

### Docker Issues

```bash
# Verify Docker setup
python scripts/verify_docker_setup.py

# Check with metrics
python scripts/verify_docker_setup.py --check-metrics --verbose
```

### Common Error Messages

**"REDIS_URL not set"**
```bash
# Solution: Set Redis Cloud connection string
export REDIS_URL=redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

**"Python version mismatch"**
```bash
# Solution: Use Python 3.10.18 exactly
conda activate crypto-bot
python --version  # Should show 3.10.18
```

**"Live trading confirmation required"**
```bash
# Solution: Set exact confirmation string
export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
```

---

## Docker Operations

### Verify Docker Setup

```bash
# Basic Docker checks
python scripts/verify_docker_setup.py

# Full verification with metrics
python scripts/verify_docker_setup.py --check-metrics

# Verbose debugging
python scripts/verify_docker_setup.py --verbose
```

**Checks Performed:**
- Python 3.10.18 in container
- prometheus_client import available
- Metrics endpoint reachable at :9308
- No .env secrets committed
- Correct non-root UID/GID (Linux)

### Build and Deploy

```bash
# Build Docker image
docker build -t crypto-ai-bot:latest .

# Run container (paper mode)
docker run -d \
  --name crypto-ai-bot \
  --env-file .env.example \
  -p 9308:9308 \
  crypto-ai-bot:latest

# Check container health
docker ps
docker logs crypto-ai-bot

# Verify with script
python scripts/verify_docker_setup.py --check-metrics
```

---

## Script Reference

### Canonical Scripts (10)

| Script | Purpose | Exit Codes |
|--------|---------|------------|
| `preflight.py` | Environment validation | 0=READY, 1=NOT_READY, 2=DEGRADED |
| `health.py` | Health checks (redis, kraken, exporter) | 0=healthy, 1=unhealthy |
| `backtest.py` | Unified backtesting CLI | 0=success, 1=failure |
| `start_trading_system.py` | Trading system startup | 0=success, 1=failure |
| `mcp_smoke.py` | Hermetic schema testing | 0=pass, 1=fail |
| `redis_cloud_smoke.py` | Redis Cloud TLS testing | 0=success, 1=failure |
| `wait_for_redis.py` | Redis connection waiter | 0=connected, 1=timeout |
| `verify_docker_setup.py` | Docker verification | 0=valid, 1=invalid |
| `setup_conda_environment.py` | Conda setup automation | 0=success, 1=failure |
| `__init__.py` | Package marker | N/A |

### Shell Helpers (2)

| Script | Purpose | Environment |
|--------|---------|-------------|
| `entrypoint.sh` | Docker entrypoint | Docker only |
| `clean_repo.sh` | Repository cleanup | All |

---

## Quick Command Reference

**5 Essential Commands:**

```bash
# 1. Preflight check
python scripts/preflight.py --mode dev

# 2. Health check
python scripts/health.py redis

# 3. Backtest
python scripts/backtest.py basic BTC/USD --strategy momentum --start 2024-01-01 --end 2024-02-01

# 4. Start system
python scripts/start_trading_system.py --mode paper

# 5. Docker verify
python scripts/verify_docker_setup.py --check-metrics
```

**90% of operations covered by these 5 commands!**

---

## Environment Cheat Sheet

```bash
# Development
conda activate crypto-bot
export TRADING_MODE=PAPER
export LOG_LEVEL=DEBUG
python scripts/preflight.py --mode dev
python scripts/start_trading_system.py --mode paper

# Staging
conda activate crypto-bot
export TRADING_MODE=PAPER
export LOG_LEVEL=INFO
python scripts/preflight.py --mode staging
python scripts/start_trading_system.py --mode paper --exporter

# Production
conda activate crypto-bot
export MODE=live
export TRADING_MODE=LIVE
export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
export LOG_LEVEL=WARNING
python scripts/preflight.py --mode prod --strict
python scripts/start_trading_system.py --mode live
```

---

**Last Updated:** 2025-01-13
**Conda Environment:** crypto-bot
**Python Version:** 3.10.18
**Redis Cloud:** redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 (TLS)
