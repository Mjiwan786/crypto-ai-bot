# Fly.io Production Deployment Guide

Complete guide for deploying the crypto-ai-bot to Fly.io in production.

## Overview

The crypto-ai-bot uses a 3-tier architecture:

```
crypto-ai-bot (Fly.io) → Redis Cloud Streams → signals-api (Fly.io) → signals-site (Vercel)
```

**This guide covers deploying the crypto-ai-bot** (signal generation engine).

## Prerequisites

- **Fly.io CLI** installed and authenticated
- **Docker** installed (for building images)
- **Redis Cloud** account and credentials
- **Kraken API** keys (for live trading)
- **Git** repository access

## Step 1: Install Fly CLI

### Windows

```powershell
# Using PowerShell (Run as Administrator)
iwr https://fly.io/install.ps1 -useb | iex
```

### Verify Installation

```bash
fly version
# Should show: flyctl v0.2.x or higher
```

## Step 2: Authenticate with Fly.io

```bash
# Login to Fly.io
fly auth login

# Verify authentication
fly auth whoami
```

## Step 3: Configure Fly.io Application

### 3.1 Create `fly.toml`

Create `fly.toml` in the project root:

```toml
# crypto-ai-bot Fly.io configuration
app = "crypto-ai-bot"

[build]
  dockerfile = "Dockerfile"

[env]
  # Application
  NODE_ENV = "production"
  ENVIRONMENT = "prod"
  APP_NAME = "crypto-ai-bot"
  LOG_LEVEL = "INFO"

  # Trading Configuration
  TRADING_MODE = "paper"  # Change to "live" for production
  BOT_MODE = "PAPER"
  ENABLE_TRADING = "false"

  # Trading Pairs (5 live pairs from site)
  TRADING_PAIRS = "BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD"

  # Kraken
  KRAKEN_WS_URL = "wss://ws.kraken.com"

  # Redis (will use secrets for sensitive data)
  REDIS_SSL = "true"
  REDIS_MAX_CONNECTIONS = "30"

  # ML Models
  ML_ENABLED = "true"
  ML_MODELS_DIR = "models"

[deploy]
  release_command = "python preflight_check.py"

[[services]]
  internal_port = 8080
  protocol = "tcp"

  [services.concurrency]
    type = "connections"
    hard_limit = 100
    soft_limit = 80

  [[services.ports]]
    port = 80
    handlers = ["http"]

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

  [[services.http_checks]]
    interval = 30000
    timeout = 5000
    grace_period = "10s"
    method = "GET"
    path = "/health"

[[vm]]
  cpu_kind = "shared"
  cpus = 2
  memory_mb = 2048
```

### 3.2 Create Dockerfile

Create `Dockerfile` in the project root:

```dockerfile
# Multi-stage build for crypto-ai-bot
FROM python:3.10-slim as builder

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Production image
FROM python:3.10-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p logs data/ohlcv models config/certs

# Set environment variable for Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health')"

# Expose metrics port
EXPOSE 8080 9108

# Run the application
CMD ["python", "agents/core/integrated_signal_pipeline.py"]
```

### 3.3 Create `.dockerignore`

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
.venv

# Conda
.conda/

# IDE
.vscode/
.idea/
*.swp

# Git
.git/
.gitignore

# Logs
logs/
*.log

# Data
data/backtests/
data/ohlcv/*.csv

# Environment files
.env*
!.env.example

# Docker
Dockerfile*
docker-compose*
.dockerignore

# Documentation
docs/
*.md
!README.md

# Tests
tests/
pytest.ini
.pytest_cache/

# CI/CD
.github/
.gitlab-ci.yml

# Temporary files
tmp/
temp/
*.tmp
```

## Step 4: Set Secrets

Secrets are stored securely in Fly.io and injected as environment variables:

```bash
# Redis Cloud credentials
fly secrets set \
  REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818" \
  REDIS_PASSWORD="<REDIS_PASSWORD>"

# Kraken API keys
fly secrets set \
  KRAKEN_API_KEY="<KRAKEN_API_KEY>" \
  KRAKEN_API_SECRET="<KRAKEN_API_SECRET>"

# OpenAI API key (if using AI agents)
fly secrets set \
  OPENAI_API_KEY="<OPENAI_API_KEY>"

# Verify secrets (values are hidden)
fly secrets list
```

**Important:** Never commit secrets to git or include in `fly.toml`.

## Step 5: Deploy Application

### 5.1 Initial Deployment

```bash
# Create Fly.io app
fly apps create crypto-ai-bot

# Deploy
fly deploy

# Monitor deployment
fly logs
```

Expected output:
```
==> Building image
[+] Building 127.3s
==> Pushing image to registry
==> Deploying crypto-ai-bot
 ✓ [1/3] Launching VM
 ✓ [2/3] Running release command
 ✓ [3/3] Starting machine
==> Visit https://crypto-ai-bot.fly.dev
```

### 5.2 Verify Deployment

```bash
# Check app status
fly status

# View logs
fly logs

# SSH into machine
fly ssh console

# Check Redis connection
fly ssh console -C "python -c 'from agents.core.real_redis_client import RealRedisClient; import os; client = RealRedisClient.from_url(os.getenv(\"REDIS_URL\")); print(\"Redis OK\")'"

# Check WebSocket connection
fly ssh console -C "python scripts/test_kraken_ws.py"
```

## Step 6: Configure Scaling

### 6.1 Horizontal Scaling

```bash
# Scale to 2 instances (for high availability)
fly scale count 2

# Scale to specific regions
fly scale count 2 --region iad,lax

# Check current scale
fly scale show
```

### 6.2 Vertical Scaling

```bash
# Upgrade to 4 CPUs and 4GB RAM
fly scale vm dedicated-cpu-4x --memory 4096

# Check VM sizes
fly platform vm-sizes

# Current configuration
fly scale show
```

## Step 7: Monitoring and Observability

### 7.1 Logs

```bash
# Stream logs in real-time
fly logs

# Filter by level
fly logs --grep "ERROR"

# Last 100 lines
fly logs -n 100

# Specific time range
fly logs --since=1h
```

### 7.2 Metrics

Fly.io provides built-in metrics:

```bash
# View metrics dashboard
fly dashboard

# Check instance metrics
fly vm status
```

Access Prometheus metrics:
```
https://crypto-ai-bot.fly.dev/metrics
```

### 7.3 Health Checks

```bash
# Check health endpoint
curl https://crypto-ai-bot.fly.dev/health

# Expected response:
# {"status": "healthy", "redis": "connected", "websocket": "connected"}
```

## Step 8: CI/CD Pipeline (GitHub Actions)

Create `.github/workflows/deploy-fly.yml`:

```yaml
name: Deploy to Fly.io

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Fly CLI
        uses: superfly/flyctl-actions/setup-flyctl@master

      - name: Run tests
        run: |
          pip install -r requirements.txt
          pytest tests/ -v

      - name: Deploy to Fly.io
        run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}

      - name: Verify deployment
        run: |
          sleep 30
          curl -f https://crypto-ai-bot.fly.dev/health || exit 1
```

**Setup:**
1. Get Fly.io API token: `fly tokens create deploy`
2. Add to GitHub Secrets: `FLY_API_TOKEN`
3. Push to main branch → automatic deployment

## Step 9: Database/Redis Management

### 9.1 Monitor Redis Streams

```bash
# SSH into Fly machine
fly ssh console

# Check stream length
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XLEN signals:paper

# Read latest signals
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XREVRANGE signals:paper + - COUNT 10

# Monitor new signals in real-time
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem --scan --pattern "signals:*"
```

### 9.2 Clear Streams (Emergency)

```bash
# ⚠️ CAUTION: This deletes all signals
fly ssh console -C "redis-cli -u \$REDIS_URL --tls --cacert config/certs/redis_ca.pem DEL signals:paper"

# Trim stream to last 1000 messages
fly ssh console -C "redis-cli -u \$REDIS_URL --tls --cacert config/certs/redis_ca.pem XTRIM signals:paper MAXLEN 1000"
```

## Step 10: Troubleshooting

### Deployment Failures

**Problem:** Build fails with `ModuleNotFoundError`

**Solution:**
```bash
# Check requirements.txt includes all dependencies
pip freeze > requirements.txt

# Rebuild and redeploy
fly deploy --no-cache
```

**Problem:** Release command fails

**Solution:**
```bash
# Check preflight_check.py runs locally
python preflight_check.py

# View release logs
fly logs --grep "release_command"

# Temporarily disable release command in fly.toml
# [deploy]
#   release_command = ""  # Commented out
```

### Redis Connection Issues

**Problem:** `ConnectionError: Redis not connected`

**Solution:**
```bash
# 1. Verify Redis secret is set
fly secrets list | grep REDIS

# 2. Test connection from Fly machine
fly ssh console -C "redis-cli -u \$REDIS_URL --tls --cacert config/certs/redis_ca.pem PING"

# 3. Check certificate exists in image
fly ssh console -C "ls config/certs/redis_ca.pem"

# 4. Re-add certificate to Dockerfile
# Make sure Dockerfile includes:
# COPY config/certs/redis_ca.pem /app/config/certs/redis_ca.pem
```

### WebSocket Connection Issues

**Problem:** `WebSocketException: Connection refused`

**Solution:**
```bash
# 1. Check Kraken WebSocket is reachable
curl -I https://ws.kraken.com

# 2. Verify trading pairs are correctly formatted
fly ssh console -C "python -c 'import os; print(os.getenv(\"TRADING_PAIRS\"))'"

# 3. Increase WebSocket timeout
fly secrets set WEBSOCKET_PING_TIMEOUT=120

# 4. Check logs for detailed error
fly logs --grep "WebSocket"
```

### High Memory Usage

**Problem:** App crashes with OOMKilled

**Solution:**
```bash
# 1. Check current memory usage
fly vm status

# 2. Increase memory allocation
fly scale vm shared-cpu-2x --memory 4096

# 3. Optimize model loading (load models on-demand)
# In integrated_signal_pipeline.py:
# self.ensemble = None  # Load lazily

# 4. Enable Redis compression
fly secrets set REDIS_COMPRESSION_ENABLED=true
```

## Step 11: Production Checklist

Before going live:

- [ ] **Secrets:** All secrets set via `fly secrets set`
- [ ] **Trading Mode:** Set `TRADING_MODE=live` (if ready for real trading)
- [ ] **Trading Pairs:** Verified 5 pairs: BTC/USD, ETH/USD, SOL/USD, MATIC/USD, LINK/USD
- [ ] **Redis:** Connection tested and streams created
- [ ] **Kraken:** API keys have sufficient permissions
- [ ] **Health Checks:** `/health` endpoint returns 200
- [ ] **Monitoring:** Metrics endpoint accessible
- [ ] **Logs:** Log aggregation configured
- [ ] **Alerts:** Discord/Slack webhooks configured
- [ ] **Backups:** Redis backup strategy in place
- [ ] **Scaling:** Horizontal scaling tested (2+ instances)
- [ ] **CI/CD:** GitHub Actions pipeline deployed successfully
- [ ] **Documentation:** Runbook updated with procedures

## Step 12: Rollback Procedure

If deployment fails or issues arise:

```bash
# 1. Check recent releases
fly releases

# Output:
# VERSION  STATUS    DESCRIPTION                  USER       DATE
# v3       failed    Deploy #123                  user       2025-11-17T10:00:00Z
# v2       deployed  Deploy #122                  user       2025-11-17T09:00:00Z
# v1       deployed  Deploy #121                  user       2025-11-16T10:00:00Z

# 2. Rollback to previous version
fly releases rollback v2

# 3. Verify rollback
fly status

# 4. Check logs
fly logs -n 100
```

## Additional Resources

- **Fly.io Docs:** https://fly.io/docs/
- **Fly.io Status:** https://status.fly.io/
- **Redis Cloud Support:** https://redis.io/docs/latest/operate/rc/
- **Kraken API:** https://docs.kraken.com/websockets/

## Support

**Fly.io Community:** https://community.fly.io/
**Project Issues:** https://github.com/your-org/crypto_ai_bot/issues
**Team Slack:** #crypto-bot-ops

---

**Last Updated:** 2025-11-17
**Maintainer:** DevOps Team
