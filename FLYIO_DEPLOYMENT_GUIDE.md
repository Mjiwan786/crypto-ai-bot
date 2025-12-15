# Fly.io Deployment Guide - crypto-ai-bot Engine

**Last Updated:** 2025-11-23
**Status:** Production-Ready
**App Name:** `crypto-ai-bot-engine`

---

## Overview

This guide covers deploying the crypto-ai-bot signal generation engine to Fly.io with:
- ✅ **24/7 uptime** (no auto-suspension)
- ✅ **Paper/Live mode separation** (independent data streams)
- ✅ **Redis Cloud TLS** (secure connection)
- ✅ **Health monitoring** (automatic restarts)
- ✅ **Graceful shutdown** (30s timeout)

---

## Architecture

```
crypto-ai-bot Engine (Fly.io)
    ↓ WebSocket
Kraken API (wss://ws.kraken.com)
    ↓ OHLCV data
Production Engine
    ↓ Signals & PnL
Redis Cloud (TLS)
    ↓ Streams
signals-api (reads streams)
    ↓ REST/SSE
signals-site (Vercel)
```

**Redis Streams (Mode-Aware):**
- Paper mode: `signals:paper:<PAIR>`, `pnl:paper:equity_curve`
- Live mode: `signals:live:<PAIR>`, `pnl:live:equity_curve`

---

## Prerequisites

### 1. Local Environment

```bash
# Activate conda environment
conda activate crypto-bot

# Verify Python version
python --version  # Should be 3.10+

# Install Fly CLI (if not installed)
# Windows (PowerShell):
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"

# macOS/Linux:
curl -L https://fly.io/install.sh | sh

# Verify Fly CLI
fly version
```

### 2. Redis Cloud Credentials

Ensure you have:
- Redis URL: `rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818`
- CA Certificate: `config/certs/redis_ca.pem` ✅ (already in place)

### 3. Environment Variables

Create `.env.paper` for local testing:

```bash
# Paper mode configuration
ENGINE_MODE=paper
REDIS_URL=rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818
REDIS_SSL=true
REDIS_CA_CERT=config/certs/redis_ca.pem
LOG_LEVEL=INFO
TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD
TIMEFRAMES=15s,1m,5m
```

---

## Local Testing (Before Deployment)

### Step 1: Test Engine Locally

```bash
# Activate environment
conda activate crypto-bot

# Load environment variables
set -a; source .env.paper; set +a  # Linux/macOS
# OR
# Load manually in Windows (see .env.paper)

# Run production engine in paper mode
python production_engine.py --mode paper
```

**Expected output:**
```
================================================================================
Production Engine Starting
================================================================================
Mode: paper
Trading Pairs: BTC/USD, ETH/USD, SOL/USD, MATIC/USD, LINK/USD
OHLCV Timeframes: [1, 5, 15, 60]
================================================================================
[1/4] Connecting to Redis Cloud...
[OK] Redis Cloud connected
[2/4] Initializing signal publisher...
[OK] Signal publisher ready
[3/4] Initializing PnL tracker...
[OK] PnL tracker ready (initial balance: $10,000.00)
[4/4] Starting Kraken WebSocket...
[OK] Kraken WebSocket started in background
================================================================================
[READY] Production Engine Ready
================================================================================
```

### Step 2: Inspect Redis Streams

After running for 30-60 seconds, verify stream writes:

```bash
# In a new terminal (keep engine running)
conda activate crypto-bot

# Inspect paper mode streams
python scripts/inspect_redis_streams.py --mode paper

# Watch streams in real-time
python scripts/inspect_redis_streams.py --mode paper --watch
```

**Expected output:**
```
================================================================================
SIGNAL STREAMS (PAPER MODE)
================================================================================

📊 Stream: signals:paper:BTC-USD
   Length: 5 signals
   Latest signals:
      1. [1732345678-0] BUY @ 43250.50 | conf=0.72 | production_momentum_v1 | 2025-11-23 12:34:38 UTC
      2. [1732345650-0] SELL @ 43180.20 | conf=0.68 | production_momentum_v1 | 2025-11-23 12:34:10 UTC
      ...

================================================================================
PNL STREAMS (PAPER MODE)
================================================================================

💰 PnL Summary: pnl:paper:summary
   Equity: $10,000.00
   Realized PnL: $0.00
   Unrealized PnL: $0.00
   Total PnL: $0.00
   Num Trades: 0
   Win Rate: 0.0%
   Mode: paper
```

**✅ Verification:**
- Signals published to `signals:paper:BTC-USD`, `signals:paper:ETH-USD`, etc.
- PnL published to `pnl:paper:summary` and `pnl:paper:equity_curve`
- NO signals in `signals:live:*` (mode separation confirmed)

### Step 3: Stop Engine

```bash
# Ctrl+C in engine terminal
# Should see:
# [Shutdown] Received shutdown signal...
# [Shutdown] Cleanup complete. Exiting.
```

---

## Fly.io Deployment

### Step 1: Authenticate to Fly.io

```bash
# Login to your NEW Fly.io account (ignore old suspended apps)
fly auth login

# Verify login
fly auth whoami
```

### Step 2: Create Fly App

```bash
# Create new app (only needed once)
fly apps create crypto-ai-bot-engine

# Verify app created
fly apps list
```

**Expected output:**
```
NAME                    OWNER           STATUS
crypto-ai-bot-engine    personal        pending
```

### Step 3: Set Secrets

**CRITICAL:** Never commit secrets to Git. Use `fly secrets set`:

```bash
# Set Redis URL (required)
fly secrets set REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818" -a crypto-ai-bot-engine

# For live mode (optional, only when switching to live trading):
# fly secrets set KRAKEN_API_KEY="your-api-key" -a crypto-ai-bot-engine
# fly secrets set KRAKEN_SECRET="your-api-secret" -a crypto-ai-bot-engine
# fly secrets set LIVE_TRADING_CONFIRMATION="I confirm live trading" -a crypto-ai-bot-engine

# Verify secrets (values will be masked)
fly secrets list -a crypto-ai-bot-engine
```

### Step 4: Deploy

```bash
# Deploy to Fly.io
fly deploy -a crypto-ai-bot-engine

# This will:
# 1. Build Dockerfile.production
# 2. Push image to Fly.io registry
# 3. Create machine with fly.toml config
# 4. Start production_engine.py in paper mode
# 5. Run health checks every 30s
```

**Expected output:**
```
==> Building image
[+] Building 120.5s (18/18) FINISHED
...
==> Pushing image to fly
...
==> Creating release
--> v1 deployed successfully
```

### Step 5: Verify Deployment

```bash
# Check app status
fly status -a crypto-ai-bot-engine

# Expected output:
# Machines
# PROCESS ID              VERSION REGION  STATE   HEALTH CHECKS       LAST UPDATED
# app     abc123          v1      iad     started 1 total, 1 passing  2m ago

# View real-time logs
fly logs -a crypto-ai-bot-engine

# Expected in logs:
# Production Engine Starting
# Mode: paper
# [READY] Production Engine Ready
```

### Step 6: Health Check

```bash
# Get app URL
fly status -a crypto-ai-bot-engine

# Or directly check health (if publicly accessible)
curl https://crypto-ai-bot-engine.fly.dev/health

# Expected response:
# {
#   "status": "healthy",
#   "mode": "paper",
#   "metrics": {
#     "signals_published": 42,
#     "ohlcv_received": 1230,
#     "errors": 0,
#     "uptime_seconds": 3600
#   }
# }
```

---

## Post-Deployment Validation

### 1. Verify Stream Writes (from local machine)

```bash
# Activate conda environment
conda activate crypto-bot

# Inspect paper mode streams (engine should be writing to Redis)
python scripts/inspect_redis_streams.py --mode paper

# You should see signals published by the Fly.io engine
# Stream: signals:paper:BTC-USD
# Length: 50+ signals (growing over time)
```

### 2. Monitor Logs

```bash
# Tail logs in real-time
fly logs -a crypto-ai-bot-engine

# Look for:
# ✅ "Signal published: BTC/USD BUY @ 43250.50"
# ✅ "Heartbeat published"
# ✅ "Metrics: signals=50, ohlcv=2000, errors=0"
# ❌ NO errors or reconnection attempts (unless network issue)
```

### 3. Verify No Auto-Suspension

```bash
# Check machine status (should always be "started")
fly status -a crypto-ai-bot-engine

# Wait 10 minutes, check again
# Should still be "started" (not "suspended")
# This confirms auto_stop_machines = "off" is working
```

---

## Configuration Summary

### fly.toml Settings

```toml
app = "crypto-ai-bot-engine"
primary_region = "iad"

[env]
  ENGINE_MODE = "paper"  # Change to "live" for production
  REDIS_SSL = "true"
  REDIS_CA_CERT = "/app/config/certs/redis_ca.pem"

[http_service]
  internal_port = 8080
  auto_stop_machines = false  # CRITICAL: Prevents suspension
  auto_start_machines = true
  min_machines_running = 1    # CRITICAL: Always 1 machine running

[[http_service.checks]]
  interval = "30s"
  path = "/health"

[[vm]]
  cpus = 1
  memory_mb = 1024
```

### Environment Variables (Fly Secrets)

| Variable | Value | Set via |
|----------|-------|---------|
| `REDIS_URL` | `rediss://default:...` | `fly secrets set` |
| `ENGINE_MODE` | `paper` | `fly.toml [env]` |
| `REDIS_SSL` | `true` | `fly.toml [env]` |
| `REDIS_CA_CERT` | `/app/config/certs/redis_ca.pem` | `fly.toml [env]` |
| `TRADING_PAIRS` | `BTC/USD,ETH/USD,SOL/USD,...` | `fly.toml [env]` |

---

## Switching to Live Mode

**⚠️ WARNING:** Live mode trades with real money. Only switch after thorough testing in paper mode.

### Step 1: Set Live Secrets

```bash
fly secrets set KRAKEN_API_KEY="your-live-api-key" -a crypto-ai-bot-engine
fly secrets set KRAKEN_SECRET="your-live-api-secret" -a crypto-ai-bot-engine
fly secrets set LIVE_TRADING_CONFIRMATION="I confirm live trading" -a crypto-ai-bot-engine
```

### Step 2: Update fly.toml

```toml
[env]
  ENGINE_MODE = "live"  # Changed from "paper"
```

### Step 3: Redeploy

```bash
fly deploy -a crypto-ai-bot-engine
```

### Step 4: Verify Live Mode

```bash
# Check logs
fly logs -a crypto-ai-bot-engine

# Should see:
# Mode: live
# [OK] Kraken API credentials validated

# Inspect live streams (from local machine)
python scripts/inspect_redis_streams.py --mode live

# Should see signals in:
# - signals:live:BTC-USD
# - signals:live:ETH-USD
# - pnl:live:equity_curve
```

---

## Troubleshooting

### Issue: App suspends after 30 minutes

**Cause:** `auto_stop_machines` not set correctly.

**Fix:**
```bash
# Verify fly.toml has:
# auto_stop_machines = false  # NOT "off" (use false)

# Or use string:
# auto_stop_machines = "off"

# Redeploy
fly deploy -a crypto-ai-bot-engine
```

### Issue: Health check fails

**Cause:** Port mismatch or health endpoint not responding.

**Fix:**
```bash
# Check logs for errors
fly logs -a crypto-ai-bot-engine

# SSH into machine
fly ssh console -a crypto-ai-bot-engine

# Inside machine:
curl http://localhost:8080/health

# Should return JSON with status
```

### Issue: Redis connection fails

**Cause:** CA certificate missing or incorrect REDIS_URL.

**Fix:**
```bash
# Verify CA cert exists in Docker image
fly ssh console -a crypto-ai-bot-engine
ls -la /app/config/certs/redis_ca.pem

# Verify REDIS_URL secret
fly secrets list -a crypto-ai-bot-engine

# Update secret if needed
fly secrets set REDIS_URL="rediss://..." -a crypto-ai-bot-engine
```

### Issue: No signals published

**Cause:** Kraken WebSocket not connecting or strategy not generating signals.

**Fix:**
```bash
# Check logs for WebSocket errors
fly logs -a crypto-ai-bot-engine | grep -i "kraken"

# Look for:
# ✅ "Kraken WebSocket connected"
# ✅ "Subscribed to BTC/USD ticker"
# ❌ "WebSocket connection failed" (network issue)
```

---

## Rollback Procedure

If deployment fails:

```bash
# View release history
fly releases -a crypto-ai-bot-engine

# Rollback to previous version
fly releases revert <version> -a crypto-ai-bot-engine

# Example:
# fly releases revert v2 -a crypto-ai-bot-engine
```

---

## Monitoring

### Real-time Logs

```bash
# Tail logs
fly logs -a crypto-ai-bot-engine

# Filter for errors
fly logs -a crypto-ai-bot-engine | grep -i error

# Filter for signals
fly logs -a crypto-ai-bot-engine | grep "Signal published"
```

### Health Checks

```bash
# Check machine status
fly status -a crypto-ai-bot-engine

# SSH into machine (for debugging)
fly ssh console -a crypto-ai-bot-engine
```

### Redis Inspection

```bash
# From local machine with .env.paper loaded
python scripts/inspect_redis_streams.py --mode paper --watch

# Real-time monitoring of streams
```

---

## Maintenance

### Update Deployment

```bash
# After code changes:
git add .
git commit -m "feat: update signal generation logic"
git push

# Deploy to Fly.io
fly deploy -a crypto-ai-bot-engine
```

### Scale Resources

```bash
# Increase memory (if ML models need more RAM)
fly scale memory 2048 -a crypto-ai-bot-engine

# Verify
fly status -a crypto-ai-bot-engine
```

### Restart Machine

```bash
# Restart (triggers graceful shutdown)
fly machine restart <machine-id> -a crypto-ai-bot-engine

# Get machine ID:
fly status -a crypto-ai-bot-engine
```

---

## Success Criteria

Deployment is successful when:

- ✅ App status: `started` (not `suspended`)
- ✅ Health checks: `1 total, 1 passing`
- ✅ Logs show: `[READY] Production Engine Ready`
- ✅ Redis streams populated: `signals:paper:BTC-USD` has 10+ signals
- ✅ PnL tracker active: `pnl:paper:summary` exists
- ✅ Uptime: Machine runs continuously for 24+ hours without suspension
- ✅ Mode separation: No signals in `signals:live:*` when running in paper mode

---

## Additional Resources

- **Fly.io Docs:** https://fly.io/docs/
- **PRD-001:** `docs/PRD-001-CRYPTO-AI-BOT.md`
- **Redis Cloud:** https://redis.com/redis-enterprise-cloud/
- **Kraken API:** https://docs.kraken.com/websockets/

---

## Support

For issues or questions:
1. Check logs: `fly logs -a crypto-ai-bot-engine`
2. Inspect streams: `python scripts/inspect_redis_streams.py`
3. Review PRD-001 for architecture details
4. Open GitHub issue: https://github.com/your-org/crypto-ai-bot/issues

---

**Last Updated:** 2025-11-23
**Next Review:** After first 7 days of 24/7 operation
