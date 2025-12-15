# Fly.io Engine Deployment Guide

Complete guide to deploy crypto-ai-bot engine on your new Fly.io account with proper paper/live stream separation.

## Prerequisites

- Fly.io account (fresh account, old suspended apps ignored)
- Redis Cloud TLS credentials
- Redis CA certificate at `config/certs/redis_ca.pem`
- Conda environment `crypto-bot` configured locally

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    crypto-ai-bot ENGINE                       │
│                  (Fly.io: crypto-ai-bot)                     │
│                                                              │
│  ┌─────────────┐        ┌──────────────┐                   │
│  │  Kraken WS  │───────>│  Signal Gen  │                   │
│  │  Real-time  │        │   AI Agent   │                   │
│  └─────────────┘        └──────────────┘                   │
│                                │                             │
│                                ▼                             │
│                         ┌──────────────┐                    │
│                         │ MODE ROUTER  │                    │
│                         │ (ENGINE_MODE)│                    │
│                         └──────────────┘                    │
│                          /            \                      │
│                    MODE=paper    MODE=live                  │
│                      /                  \                    │
│      ┌──────────────────────┐    ┌──────────────────────┐  │
│      │  Paper Streams       │    │  Live Streams        │  │
│      │  signals:paper       │    │  signals:live        │  │
│      │  pnl:paper           │    │  pnl:live            │  │
│      └──────────────────────┘    └──────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │  Redis Cloud    │
                   │  (TLS Secured)  │
                   └─────────────────┘
                            │
                            ▼
             ┌─────────────────────────────┐
             │     signals-api (Fly.io)    │
             │  Serves both streams to UI  │
             └─────────────────────────────┘
```

## Stream Separation (CRITICAL)

The engine **MUST** maintain complete separation between paper and live data:

### Paper Mode (ENGINE_MODE=paper)
- **Signals**: `signals:paper` stream
- **PnL**: `pnl:paper` stream
- **Equity**: `pnl:paper:equity_curve` stream
- **Use case**: Backtests, marketing materials, performance demos

### Live Mode (ENGINE_MODE=live)
- **Signals**: `signals:live` stream
- **PnL**: `pnl:live` stream
- **Equity**: `pnl:live:equity_curve` stream
- **Use case**: Real-time trading signals for customers

**NO DATA MUST EVER MIX BETWEEN PAPER AND LIVE STREAMS!**

## Deployment Steps

### Step 1: Authenticate with Fly.io

```bash
# Login to your NEW Fly.io account
fly auth login

# Verify logged in
fly auth whoami
# Should show: <your-email>@gmail.com
```

### Step 2: Create Fly.io App

```bash
# Create new app (use exact name: crypto-ai-bot)
fly apps create crypto-ai-bot --org personal

# Verify app created
fly apps list | grep crypto-ai-bot
```

### Step 3: Set Secrets (REQUIRED)

```bash
# Set Redis URL (CRITICAL - must use rediss:// for TLS)
fly secrets set \
  REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818" \
  -a crypto-ai-bot

# For LIVE mode deployment (DANGER - only set when ready for production!)
# fly secrets set ENGINE_MODE="live" TRADING_MODE="live" -a crypto-ai-bot

# Verify secrets set
fly secrets list -a crypto-ai-bot
```

### Step 4: Deploy Engine

```bash
# Deploy from project root
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# First deployment (paper mode by default)
fly deploy -a crypto-ai-bot -f fly.toml

# Watch deployment logs
fly logs -a crypto-ai-bot
```

### Step 5: Verify Deployment

```bash
# Check app status
fly status -a crypto-ai-bot

# Check health endpoint
curl https://crypto-ai-bot.fly.dev/health

# Monitor logs in real-time
fly logs -a crypto-ai-bot --follow

# Check if machines are running
fly machines list -a crypto-ai-bot
```

## Local Testing (Before Deployment)

### Test Paper Mode Locally

```bash
# Activate conda environment
conda activate crypto-bot

# Load .env.paper
export $(cat .env.paper | grep -v '^#' | xargs)

# Verify ENGINE_MODE
echo $ENGINE_MODE
# Should output: paper

# Inspect Redis streams (verify paper streams exist)
python scripts/inspect_redis_streams.py --mode paper --limit 5

# Run local engine test (publish test signals to paper streams)
python production_engine.py --mode paper
```

### Verify Stream Separation

```bash
# Inspect both paper and live streams
python scripts/inspect_redis_streams.py --mode all --show-messages

# Expected output:
#   - signals:paper should have messages
#   - signals:live should be empty (or separate data)
#   - pnl:paper should have messages
#   - pnl:live should be empty (or separate data)
```

## Phase D - Local Validation Results

**Status**: ✅ COMPLETE (Validated on 2025-11-20)

### Validation Summary

Successfully validated Redis TLS connection and stream separation:

**Paper Mode Streams:**
- `signals:paper`: 10,017 messages (active, recent signals)
- `pnl:paper`: Empty (awaiting trade execution)
- `pnl:paper:equity_curve`: Empty (awaiting PnL data)

**Live Mode Streams:**
- `signals:live`: 10,001 messages (active, older signals)
- `pnl:live`: Empty (awaiting trade execution)
- `pnl:live:equity_curve`: Empty (awaiting PnL data)

### Key Findings

1. **Redis SSL Connection**: ✅ Fixed compatibility issue with redis-py 5.x by letting `from_url()` handle SSL automatically for `rediss://` URLs
2. **Stream Separation**: ✅ Confirmed - paper and live streams are completely separate with different message IDs and timestamps
3. **Signal Structure**: ✅ Verified - messages contain: id, timestamp, pair, side, entry, stop_loss, take_profit, etc.
4. **Inspection Tool**: ✅ Working - `scripts/inspect_redis_streams.py` successfully inspects all mode-aware streams

### Technical Fixes Applied

**mcp/redis_manager.py:**
- Updated `RedisManager.connect()` to match async implementation
- Removed manual SSL context building for `rediss://` URLs
- Let redis-py handle SSL automatically (fixes compatibility with redis-py 5.x)

**scripts/inspect_redis_streams.py:**
- Removed emoji characters to fix Windows console encoding errors
- Replaced with ASCII equivalents ([SUCCESS], [ERROR])

### Validation Commands

```bash
# Tested successfully:
conda activate crypto-bot
python scripts/inspect_redis_streams.py --mode paper --limit 3
python scripts/inspect_redis_streams.py --mode live --limit 3
python scripts/inspect_redis_streams.py --mode paper --limit 2 --show-messages
```

### Next Steps

Phase D is complete. Ready to proceed to Fly.io deployment (Phase E).

## Production Checklist

Before deploying to live mode:

- [x] Paper mode tested and validated locally ✅ (Phase D complete)
- [x] Redis TLS connection working ✅ (Validated with Redis Cloud)
- [ ] Health endpoint responding at `/health` (Test after Fly.io deployment)
- [x] Stream separation verified (paper != live) ✅ (Verified via inspection script)
- [ ] Metrics endpoint working at `/metrics` (Test after Fly.io deployment)
- [ ] Kraken WebSocket connection stable (Test after Fly.io deployment)
- [ ] PnL tracking working correctly (Awaiting trade execution)
- [ ] All secrets set in Fly.io (Ready to deploy)
- [ ] Dockerfile.production builds successfully (Ready to test)
- [ ] No errors in `fly logs` (Test after Fly.io deployment)

## Switching to Live Mode

**⚠️ DANGER ZONE - ONLY FOR PRODUCTION TRADING**

```bash
# 1. Verify live trading confirmation
export LIVE_TRADING_CONFIRMATION="I confirm live trading"

# 2. Set ENGINE_MODE to live (CRITICAL - this publishes to signals:live!)
fly secrets set \
  ENGINE_MODE="live" \
  TRADING_MODE="live" \
  LIVE_TRADING_CONFIRMATION="I confirm live trading" \
  -a crypto-ai-bot

# 3. Restart app to pick up new mode
fly apps restart crypto-ai-bot

# 4. Monitor logs carefully
fly logs -a crypto-ai-bot --follow

# 5. Verify signals going to live streams
python scripts/inspect_redis_streams.py --mode live --show-messages
```

## Troubleshooting

### App crashes on startup

```bash
# Check logs
fly logs -a crypto-ai-bot

# SSH into machine
fly ssh console -a crypto-ai-bot

# Check health
curl http://localhost:8080/health
```

### Health check failing

```bash
# Restart app
fly apps restart crypto-ai-bot

# Check machine status
fly machines list -a crypto-ai-bot

# Force restart specific machine
fly machine restart <machine-id> -a crypto-ai-bot
```

### Redis connection issues

```bash
# Verify REDIS_URL secret is set
fly secrets list -a crypto-ai-bot

# Check CA certificate exists in image
fly ssh console -a crypto-ai-bot
ls -la /app/config/certs/redis_ca.pem
```

### Streams not populating

```bash
# Check ENGINE_MODE is set correctly
fly ssh console -a crypto-ai-bot
echo $ENGINE_MODE

# Verify from local machine
python scripts/inspect_redis_streams.py --mode paper
```

## Monitoring

### Health Checks

```bash
# Basic health
curl https://crypto-ai-bot.fly.dev/health

# Readiness probe
curl https://crypto-ai-bot.fly.dev/readiness

# Liveness probe
curl https://crypto-ai-bot.fly.dev/liveness

# Prometheus metrics
curl https://crypto-ai-bot.fly.dev/metrics
```

### Metrics

```bash
# View Prometheus metrics
fly metrics -a crypto-ai-bot

# Watch for resource usage
fly status -a crypto-ai-bot --watch
```

## Rollback

If deployment fails:

```bash
# List recent deployments
fly releases -a crypto-ai-bot

# Rollback to previous version
fly releases revert <version> -a crypto-ai-bot
```

## Scaling

```bash
# Scale to 2 instances for HA
fly scale count 2 -a crypto-ai-bot

# Scale VM resources
fly scale vm shared-cpu-2x --memory 4096 -a crypto-ai-bot
```

## Important Files

- `fly.toml` - Fly.io configuration
- `Dockerfile.production` - Production Docker image
- `docker-entrypoint.sh` - Startup script
- `health_server.py` - Health check endpoints
- `production_engine.py` - Main engine process
- `.env.paper` - Paper mode environment variables
- `config/streams.yaml` - Stream definitions
- `config/mode_aware_streams.py` - Mode-aware stream logic

## Support

For issues:
1. Check logs: `fly logs -a crypto-ai-bot`
2. Verify secrets: `fly secrets list -a crypto-ai-bot`
3. Test locally first with `conda activate crypto-bot`
4. Inspect Redis streams: `python scripts/inspect_redis_streams.py`

## Security Notes

- **NEVER** commit `.env` files to git
- **NEVER** hardcode Redis credentials
- **ALWAYS** use `rediss://` for production (TLS required)
- **ALWAYS** verify ENGINE_MODE before switching to live
- Store Redis URL as Fly.io secret only
- Rotate credentials regularly

---

**Last Updated**: 2025-11-22
**Version**: 1.0.0
