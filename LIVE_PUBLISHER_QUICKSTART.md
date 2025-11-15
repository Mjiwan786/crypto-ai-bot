# Live Signal Publisher - Quick Start Guide

Get the live signal publisher running in **under 5 minutes**!

---

## Prerequisites Checklist

- ✅ Conda environment `crypto-bot` activated
- ✅ Redis Cloud URL and credentials
- ✅ Redis CA certificate at `config/certs/redis_ca.pem`
- ✅ Environment file (`.env.paper` or `.env.prod`)

---

## 5-Minute Setup

### Step 1: Activate Environment

```bash
conda activate crypto-bot
```

### Step 2: Configure Environment

```bash
# Copy environment template
cp .env.paper.example .env.paper

# Edit with your Redis credentials
nano .env.paper
```

Required variables:
```bash
REDIS_URL=rediss://default:YOUR_PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_CA_CERT=config/certs/redis_ca.pem
```

### Step 3: Test Redis Connection

```bash
# Quick test
python -c "
import os
from dotenv import load_dotenv
load_dotenv('.env.paper')
print('REDIS_URL:', os.getenv('REDIS_URL')[:50] + '...')
"
```

### Step 4: Start Publisher

```bash
# Paper mode (safe for testing)
python live_signal_publisher.py --mode paper
```

You should see:
```
2025-01-11 10:30:00 - INFO - Connecting to Redis Cloud...
2025-01-11 10:30:01 - INFO - ✓ Connected to Redis Cloud (mode=paper)
2025-01-11 10:30:01 - INFO - Health server started on http://0.0.0.0:8080/health
2025-01-11 10:30:01 - INFO - Starting live signal publisher (mode=paper)
2025-01-11 10:30:02 - INFO - Published signal: BTC/USD long @ 45234.50 (confidence=0.78, id=...)
```

### Step 5: Verify Health

Open a new terminal:

```bash
# Check health endpoint
curl http://localhost:8080/health | jq .
```

Expected output:
```json
{
  "status": "healthy",
  "reason": "Publishing normally",
  "mode": "paper",
  "metrics": {
    "total_published": 12,
    "total_errors": 0,
    "freshness_seconds": 1.5,
    "uptime_seconds": 30.2,
    "latency_ms": {
      "signal_generation": { "p50": 12.5, "p95": 45.2, "p99": 89.1 },
      "redis_publish": { "p50": 5.2, "p95": 15.8, "p99": 25.3 }
    }
  }
}
```

✅ **You're done!** The publisher is now running and publishing signals to Redis.

---

## Next Steps

### Validate Signals

```bash
# Open another terminal
conda activate crypto-bot

# Validate last 50 signals
python scripts/validate_live_signals.py --mode paper --count 50
```

### Monitor in Real-Time

```bash
# Continuous validation (updates every 10 seconds)
python scripts/validate_live_signals.py --mode paper --continuous --interval 10
```

### Check Redis Streams

```bash
# Use redis-cli to inspect streams
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE signals:paper:BTC-USD + - COUNT 5
```

---

## Common Commands

### Start with Custom Configuration

```bash
# Custom trading pairs
python live_signal_publisher.py \
  --mode paper \
  --pairs "BTC/USD,ETH/USD" \
  --rate 10.0 \
  --health-port 8080
```

### Run Smoke Test (2 minutes)

```bash
# Quick verification test
timeout 120 python live_signal_publisher.py --mode paper --rate 2.0
```

### Run Soak Test (30 minutes)

```bash
# Comprehensive stability test
python scripts/run_live_publisher_soak_test.py \
  --duration 30 \
  --report soak_test_report.json
```

### View Logs

```bash
# Real-time logs
tail -f logs/live_publisher.log

# Search for errors
grep ERROR logs/live_publisher.log
```

---

## Troubleshooting Quick Fixes

### ❌ "REDIS_URL environment variable is required"

**Fix:**
```bash
# Ensure .env file exists and is loaded
ls -la .env.paper
source .env.paper  # or use: export $(cat .env.paper | xargs)
```

### ❌ "Redis Cloud requires TLS connection"

**Fix:**
```bash
# Check your REDIS_URL uses rediss:// (with double 's')
echo $REDIS_URL | grep "rediss://"

# If it shows redis:// (single 's'), update to rediss://
```

### ❌ "CA certificate not found"

**Fix:**
```bash
# Verify certificate exists
ls -la config/certs/redis_ca.pem

# If missing, download from Redis Cloud dashboard
# or copy from the provided path
```

### ❌ "Live trading requires environment variable"

**Fix:**
```bash
# For live mode, you must explicitly confirm
export LIVE_TRADING_CONFIRMATION="I confirm live trading"

# Then start publisher
python live_signal_publisher.py --mode live
```

### ❌ Health endpoint returns 503 (degraded)

**Check:**
```bash
# View health details
curl http://localhost:8080/health | jq '.reason'

# Common reasons:
# - "No signal published in 35s" → Check logs for errors
# - Rate limiting too strict → Increase --rate parameter
# - Market data feed down → Verify upstream data source
```

---

## File Structure

```
crypto_ai_bot/
├── live_signal_publisher.py          # Main publisher
├── signals/
│   ├── schema.py                      # Signal Pydantic model
│   └── publisher.py                   # Redis stream publisher
├── scripts/
│   ├── validate_live_signals.py       # Validator
│   └── run_live_publisher_soak_test.py # Soak test
├── tests/
│   └── test_live_signal_publisher.py  # Unit tests
├── config/
│   └── certs/
│       └── redis_ca.pem              # Redis TLS certificate
├── logs/
│   └── live_publisher.log            # Publisher logs
├── .env.paper                         # Paper mode env vars
├── .env.prod                          # Production env vars
├── LIVE_PUBLISHER_QUICKSTART.md      # This file
└── LIVE_SIGNAL_PUBLISHER_RUNBOOK.md  # Detailed operations guide
```

---

## Production Deployment

Ready for production? See the [Runbook](LIVE_SIGNAL_PUBLISHER_RUNBOOK.md) for:

- ✅ Production deployment (Fly.io, Docker, systemd)
- ✅ Monitoring & alerting setup
- ✅ SLO tracking (latency, uptime, error rate)
- ✅ Emergency procedures
- ✅ Maintenance schedules

---

## Support

- **Documentation**: `LIVE_SIGNAL_PUBLISHER_RUNBOOK.md`
- **Tests**: `tests/test_live_signal_publisher.py`
- **Validation**: `scripts/validate_live_signals.py`
- **Issues**: Report at GitHub issues page

---

**Last Updated**: 2025-01-11
**Version**: 1.0
