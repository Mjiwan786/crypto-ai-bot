# Engine Operations Runbook

**Version:** 1.0.0  
**Last Updated:** 2025-01-27  
**Audience:** Operations Team & Acquire.com Buyers  
**Reference:** PRD-001-CRYPTO-AI-BOT.md

---

## Executive Summary

This runbook provides step-by-step procedures to start, monitor, and safely stop the crypto-ai-bot engine. The engine runs 24/7 in paper mode, generating trading signals and publishing performance metrics for investor display.

**Key Facts:**
- **Entry Point:** `main_engine.py`
- **Deployment:** Fly.io (production) or local Conda environment (development)
- **Mode:** Paper trading (simulated) or Live trading (real money)
- **Health Endpoint:** `http://localhost:8080/health` (local) or Fly.io health check
- **Update Frequency:** Metrics updated hourly, signals generated in real-time

---

## Prerequisites

### Environment Setup

1. **Conda Environment** (local development):
   ```bash
   conda activate crypto-bot
   ```

2. **Environment Variables** (required):
   - `REDIS_URL` - Redis Cloud connection string (rediss:// for TLS)
   - `REDIS_CA_CERT` - Path to CA certificate for TLS (if using Redis Cloud)
   - `ENGINE_MODE` - Trading mode: `paper` or `live` (default: `paper`)
   - `TRADING_PAIRS` - Comma-separated pairs (e.g., `BTC/USD,ETH/USD`) or use defaults
   - `LOG_LEVEL` - Logging level: `INFO`, `DEBUG`, `WARNING` (default: `INFO`)

3. **Optional Environment Variables**:
   - `LOG_FORMAT` - Log format: `json` for structured logs, or default text format
   - `LOG_TO_FILE` - Enable file logging: `true` or `false` (default: `true`)
   - `HEALTH_PORT` - Health check HTTP port (default: `8080`)

---

## Starting the Engine

### Local Development

```bash
# 1. Activate conda environment
conda activate crypto-bot

# 2. Load environment variables (if using .env file)
# Environment variables should already be set in your shell

# 3. Start the engine
python main_engine.py

# Or with explicit mode:
python main_engine.py --mode paper

# Or with custom pairs:
python main_engine.py --pairs BTC/USD,ETH/USD
```

### Production (Fly.io)

The engine runs automatically via Fly.io deployment. To manually trigger:

```bash
# Deploy (if not already deployed)
flyctl deploy

# Check status
flyctl status

# View logs
flyctl logs
```

### Expected Startup Output

```
============================================================
Initializing crypto-ai-bot engine v1.0.0
Mode: paper (streams: signals:paper:<PAIR>)
Pairs: ['BTC/USD', 'ETH/USD', 'SOL/USD', 'LINK/USD', 'DOT/USD']
============================================================
Connecting to Redis...
Redis connection established
Starting health publisher...
Health publisher started on port 8080
Starting signal generation...
Engine running (press Ctrl+C to stop)
```

---

## Monitoring

### Health Checks

**Local:**
```bash
curl http://localhost:8080/health
```

**Production (Fly.io):**
```bash
flyctl status
# Or check health endpoint directly if exposed
```

**Expected Health Response:**
```json
{
  "status": "ok",
  "mode": "paper",
  "uptime_seconds": 3600,
  "redis_connected": true,
  "kraken_connected": true,
  "signals_generated_24h": 150
}
```

### Key Metrics (Redis)

**Investor Performance Metrics:**
```bash
# View summary metrics (published hourly)
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.hgetall('engine:summary_metrics'))"

# Key fields:
# - roi_30d: 30-day ROI percentage
# - win_rate_pct: Win rate percentage
# - sharpe_ratio: Risk-adjusted return metric
# - signals_per_day: Average signals per day
# - total_trades: Total trades in 30-day period
```

**Signal Streams:**
```bash
# Check latest signals for a pair
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.xrevrange('signals:paper:BTC/USD', count=5))"

# Count signals in last hour
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(len(r.xrange('signals:paper:BTC/USD', '-', '+', count=1000)))"
```

**Engine Status:**
```bash
# Check heartbeat (updated every 30 seconds)
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.get('engine:heartbeat'))"

# Check engine status JSON
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.get('engine:status'))"
```

### Log Monitoring

**Local:**
```bash
# View logs in real-time (if LOG_TO_FILE=true)
tail -f logs/crypto_ai_bot.log

# View metrics log
tail -f logs/metrics.log
```

**Production (Fly.io):**
```bash
# Stream logs
flyctl logs

# View last 100 lines
flyctl logs --limit 100
```

### Critical Redis Keys

| Key | Type | Purpose | TTL |
|-----|------|---------|-----|
| `engine:summary_metrics` | Hash | Investor-facing metrics (ROI, win rate, etc.) | 1 hour (auto-refreshed) |
| `engine:heartbeat` | String | Engine heartbeat timestamp | 60 seconds |
| `engine:status` | String | Engine status JSON | 60 seconds |
| `signals:paper:<PAIR>` | Stream | Trading signals per pair | 7 days |
| `signals:live:<PAIR>` | Stream | Live trading signals (if in live mode) | 7 days |

---

## Stopping the Engine

### Graceful Shutdown (Recommended)

**Local:**
```bash
# Press Ctrl+C in the terminal running the engine
# The engine will:
# 1. Stop accepting new signals
# 2. Finish processing current signals
# 3. Close Redis connections
# 4. Stop health publisher
# 5. Exit cleanly
```

**Production (Fly.io):**
```bash
# Scale down (graceful shutdown)
flyctl scale count 0

# Or stop specific app
flyctl apps stop <app-name>
```

### Emergency Stop

**Via Redis Kill Switch:**
```bash
# Set emergency kill switch (if implemented)
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# The engine will detect this and shut down gracefully
```

**Force Stop (Last Resort):**
```bash
# Local: Find and kill process
ps aux | grep main_engine.py
kill -9 <PID>

# Production: Force stop via Fly.io
flyctl apps destroy <app-name> --force
```

---

## Troubleshooting

### Engine Won't Start

**Check Environment Variables:**
```bash
echo $REDIS_URL
echo $ENGINE_MODE
echo $REDIS_CA_CERT
```

**Verify Redis Connection:**
```bash
python -c "import redis; r=redis.from_url('$REDIS_URL'); print('Redis:', 'OK' if r.ping() else 'FAIL')"
```

**Check Logs:**
```bash
# Look for error messages in startup logs
python main_engine.py 2>&1 | tee startup.log
```

### No Signals Generated

**Verify WebSocket Connection:**
```bash
# Check Kraken connection status in logs
grep "Kraken WS" logs/crypto_ai_bot.log | tail -20
```

**Check Signal Streams:**
```bash
# Verify signals are being published
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.xinfo('stream', 'signals:paper:BTC/USD'))"
```

### Metrics Not Updating

**Check Metrics Calculator:**
```bash
# Manually trigger metrics calculation
python -m analysis.metrics_summary

# Verify metrics were published
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.hget('engine:summary_metrics', 'timestamp'))"
```

**Check Update Frequency:**
- Metrics are calculated hourly by default
- Last update timestamp is stored in `engine:summary_metrics` hash

### Health Check Failing

**Check Health Endpoint:**
```bash
curl -v http://localhost:8080/health
```

**Verify Components:**
- Redis connection must be active
- Health publisher must be running on configured port
- Check firewall rules if accessing remotely

---

## Mode Switching

### Paper to Live (Production Only)

**⚠️ WARNING: Live mode trades with real money. Ensure proper authorization.**

1. **Set Environment Variable:**
   ```bash
   export ENGINE_MODE=live
   export LIVE_TRADING_CONFIRMATION=true  # Required safety check
   ```

2. **Restart Engine:**
   ```bash
   # Engine will validate mode and confirm before starting
   python main_engine.py --mode live
   ```

3. **Verify Mode:**
   ```bash
   # Check that signals are published to signals:live:* streams
   python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.keys('signals:live:*'))"
   ```

### Live to Paper

1. **Set Environment Variable:**
   ```bash
   export ENGINE_MODE=paper
   ```

2. **Restart Engine:**
   ```bash
   python main_engine.py --mode paper
   ```

---

## Maintenance Windows

### Scheduled Maintenance

1. **Notify Stakeholders:** Alert investors if metrics will be unavailable
2. **Scale Down:** `flyctl scale count 0` (production)
3. **Perform Maintenance:** Updates, configuration changes, etc.
4. **Scale Up:** `flyctl scale count 1` (production)
5. **Verify:** Check health endpoint and recent signals

### Metrics Recalculation

Metrics are automatically recalculated hourly. To manually trigger:

```bash
python -m analysis.metrics_summary --mode paper
```

---

## Production Checklist

Before deploying to production:

- [ ] Environment variables configured (no secrets in code)
- [ ] Redis Cloud connection tested
- [ ] CA certificate path correct
- [ ] Health endpoint accessible
- [ ] Log rotation configured
- [ ] Monitoring alerts set up
- [ ] Mode verified (paper vs live)
- [ ] Trading pairs configured
- [ ] Fly.io deployment tested (if applicable)

---

## Quick Reference

### Essential Commands

```bash
# Start engine
python main_engine.py

# Health check
curl http://localhost:8080/health

# View metrics
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.hgetall('engine:summary_metrics'))"

# Check signals
python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.xrevrange('signals:paper:BTC/USD', count=5))"

# Stop engine
Ctrl+C  # Graceful shutdown
```

### Support

For issues or questions:
1. Check logs: `logs/crypto_ai_bot.log`
2. Review PRD-001: `docs/PRD-001-CRYPTO-AI-BOT.md`
3. Check architecture: `docs/ARCH_ENGINE_OVERVIEW.md`

---

**Last Updated:** 2025-01-27  
**Maintained By:** Engineering Team

