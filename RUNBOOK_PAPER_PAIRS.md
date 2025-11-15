# Runbook: Adding Trading Pairs Without Fly.io Deployment

## Overview

This runbook describes how to add new trading pairs (SOL/USD, ADA/USD) to the production `signals:paper` stream **without touching Fly.io deployment**. The approach uses a local canary publisher running alongside the existing Fly.io publisher.

**Target Stream:** `signals:paper` (PRODUCTION)
**Deployment Model:** Local canary + Fly.io continuous (both write to same stream)
**Rollback:** Instant (Ctrl+C to stop canary process)

---

## Architecture

### Current State (Before Canary)
```
Fly.io continuous_publisher → signals:paper (BTC-USD, ETH-USD)
                                      ↓
                            crypto-signals-api (reads)
                                      ↓
                         aipredictedsignals.cloud (displays)
```

### Canary State (With Local Publisher)
```
Fly.io continuous_publisher ────┐
                                ├──→ signals:paper (BTC, ETH, SOL, ADA)
Local canary_publisher   ───────┘                   ↓
                                        crypto-signals-api (reads)
                                                    ↓
                                     aipredictedsignals.cloud (displays)
```

**Key Properties:**
- Both publishers write to **same stream** (`signals:paper`)
- No Fly.io changes required
- No API changes required
- No frontend changes required
- Instant rollback (stop canary = back to BTC/ETH only)

---

## Prerequisites

1. **Environment:** Windows with conda
2. **Conda env:** `crypto-bot` (Python 3.10)
3. **Redis access:** Production Redis Cloud credentials
4. **CA Certificate:** `config/certs/redis_ca.pem`
5. **Files created:**
   - `.env.paper.local` (environment configuration)
   - `canary_continuous_publisher.py` (publisher script)
   - `scripts/run_publisher_paper.bat` (Windows runner)
   - `scripts/run_publisher_paper.sh` (Bash runner)

---

## Step-by-Step Deployment

### Step 1: Verify Prerequisites

```powershell
# Check conda environment exists
conda env list | findstr crypto-bot

# Verify files exist
dir .env.paper.local
dir canary_continuous_publisher.py
dir config\certs\redis_ca.pem
```

**Expected:** All files exist, conda environment present ✓

---

### Step 2: Review Configuration

Check `.env.paper.local`:

```bash
PUBLISH_MODE=paper
REDIS_STREAM_NAME=signals:paper      # PRODUCTION stream
TRADING_PAIRS=BTC/USD,ETH/USD        # Base pairs (from Fly.io)
EXTRA_PAIRS=SOL/USD,ADA/USD          # NEW canary pairs
REDIS_URL=rediss://default:...       # Production Redis
```

**Critical Checks:**
- ✅ `REDIS_STREAM_NAME=signals:paper` (production)
- ✅ `EXTRA_PAIRS` includes `SOL/USD,ADA/USD`
- ✅ CA cert path is correct

---

### Step 3: Start Canary Publisher

**Windows:**
```batch
scripts\run_publisher_paper.bat
```

**Bash/Linux:**
```bash
./scripts/run_publisher_paper.sh
```

**Or direct Python:**
```bash
conda activate crypto-bot
python canary_continuous_publisher.py
```

**Expected Output:**
```
======================================================================
CANARY CONTINUOUS PUBLISHER
======================================================================
Target Stream: signals:paper (PRODUCTION)
Canary Pairs: SOL-USD, ADA-USD
Rate Limit: 2.0 signals/sec
======================================================================

[OK] Connected to Redis
[OK] Publishing canary signals at max 2.0/sec

Press Ctrl+C to stop and rollback to BTC/ETH only
======================================================================

[0] Published: SOL-USD buy (ID: 1762660693780-0)
[1] Published: ADA-USD sell (ID: 1762660694280-0)
...
```

**Duration:** Run for 5-10 minutes minimum (or longer for extended testing)

---

### Step 4: Verify End-to-End (E2E)

Run verification while canary is active:

```python
python -c "
import redis
import json
import os
from dotenv import load_dotenv

load_dotenv('.env.paper.local')
redis_url = os.getenv('REDIS_URL')

client = redis.from_url(redis_url, decode_responses=True)

# Check last 10 signals
messages = client.xrevrange('signals:paper', count=10)

print('Last 10 signals:')
for msg_id, fields in messages:
    data = json.loads(fields['json'])
    pair = data.get('pair', 'UNKNOWN')
    strategy = data.get('strategy', 'UNKNOWN')
    print(f'  {pair} ({strategy})')

client.close()
"
```

**Expected Output:**
```
Last 10 signals:
  SOL-USD (canary_publisher)
  ADA-USD (canary_publisher)
  BTC-USD (continuous_publisher)
  ETH-USD (continuous_publisher)
  ...
```

**API Verification:**
```bash
curl https://crypto-signals-api.fly.dev/v1/signals | python -m json.tool | grep -E "pair.*SOL|pair.*ADA"
```

**Expected:** SOL-USD and ADA-USD in API response ✓

**Site Verification:**
```bash
curl -sL https://aipredictedsignals.cloud | grep -E "SOL|ADA"
```

**Expected:** SOL/USDT and ADA/USDT visible on site ✓

---

### Step 5: Promotion Decision

After verification (5-10 minutes minimum):

**Option A: Promote (Keep Running)**
- If all checks pass and no issues observed
- Keep canary publisher running indefinitely
- Monitor logs for errors
- Document decision in `logs/paper_promotion_decision.txt`

**Option B: Rollback (Stop Canary)**
- If any errors or unexpected behavior
- Press **Ctrl+C** in canary publisher terminal
- Verify BTC/ETH continue from Fly.io
- Document reason in `logs/paper_rollback_decision.txt`

---

## Rollback Procedure

### Instant Rollback (Emergency)

**Single Command:**
```
Ctrl+C (in canary publisher terminal)
```

**What Happens:**
1. Canary publisher stops immediately
2. SOL-USD and ADA-USD signals stop
3. BTC-USD and ETH-USD continue from Fly.io
4. API returns to 2 pairs (BTC, ETH)
5. Site returns to 2 pairs

**Verification After Rollback:**
```python
# Check Redis (should only see BTC-USD, ETH-USD)
python -c "
import redis, json, os
from dotenv import load_dotenv
load_dotenv('.env.paper.local')
client = redis.from_url(os.getenv('REDIS_URL'), decode_responses=True)
messages = client.xrevrange('signals:paper', count=5)
for msg_id, fields in messages:
    data = json.loads(fields['json'])
    print(f'{data[\"pair\"]} ({data[\"strategy\"]})')
client.close()
"
```

**Expected:** Only BTC-USD and ETH-USD (continuous_publisher) ✓

---

## Monitoring

### Health Checks

**1. Publisher Health:**
```bash
# Check process is running
ps aux | grep canary_continuous_publisher
```

**2. Redis Health:**
```python
import redis, os
from dotenv import load_dotenv

load_dotenv('.env.paper.local')
client = redis.from_url(os.getenv('REDIS_URL'), decode_responses=True)

print(f"Stream length: {client.xlen('signals:paper')}")
print(f"Redis ping: {client.ping()}")
client.close()
```

**3. API Health:**
```bash
curl https://crypto-signals-api.fly.dev/health
```

**Expected:** `redis_ok: true`, `status: healthy`

### Log Files

**Canary Publisher Logs:**
- Location: `logs/paper_local_canary.txt`
- Check for errors, reconnections, or high error rates

**Verification Evidence:**
- Location: `logs/paper_e2e_check.txt`
- Contains snapshot of Redis, API, Site verification

---

## Troubleshooting

### Issue: Canary Publisher Won't Start

**Symptoms:**
- Script exits immediately
- Error: "CA cert not found"

**Solution:**
```bash
# Verify CA cert exists
dir config\certs\redis_ca.pem

# Check permissions
icacls config\certs\redis_ca.pem
```

---

### Issue: No SOL/ADA Signals in Redis

**Symptoms:**
- Canary publisher shows "Published" messages
- But only BTC/ETH in Redis stream

**Solution:**
```bash
# Check publisher is targeting correct stream
grep REDIS_STREAM_NAME .env.paper.local
# Should be: signals:paper

# Check for errors in publisher output
# Look for "ERROR" or "Backing off"
```

---

### Issue: High Error Rate in Publisher

**Symptoms:**
- Many "ERROR" messages in publisher output
- Frequent reconnections
- Exponential backoff messages

**Solution:**
```bash
# Check Redis connectivity
curl https://crypto-signals-api.fly.dev/health
# Check redis_ok field

# Verify credentials in .env.paper.local
# Try manual Redis connection:
redis-cli -u "rediss://..." --tls --cacert config/certs/redis_ca.pem PING
```

---

### Issue: SOL/ADA Not Visible on Site

**Symptoms:**
- SOL/ADA in Redis ✓
- SOL/ADA in API ✓
- SOL/ADA NOT on site ✗

**Solution:**
```bash
# Check site is reading from correct API
curl -sL https://aipredictedsignals.cloud | grep "crypto-signals-api"

# Verify API endpoint returns SOL/ADA
curl https://crypto-signals-api.fly.dev/v1/signals | python -m json.tool | grep pair | head -20

# Clear browser cache and reload
# Site may have cached pair list
```

---

## Configuration Reference

### Environment Variables (`.env.paper.local`)

| Variable | Value | Description |
|----------|-------|-------------|
| `PUBLISH_MODE` | `paper` | Publishing mode (paper/staging/live) |
| `REDIS_STREAM_NAME` | `signals:paper` | Target stream (PRODUCTION) |
| `TRADING_PAIRS` | `BTC/USD,ETH/USD` | Base pairs (from Fly.io) |
| `EXTRA_PAIRS` | `SOL/USD,ADA/USD` | Canary pairs (local only) |
| `REDIS_URL` | `rediss://...` | Production Redis Cloud URL |
| `REDIS_SSL_CA_CERT` | `config/certs/redis_ca.pem` | TLS CA certificate |
| `RATE_LIMIT_ENABLED` | `true` | Enable E1 rate controls |
| `RATE_LIMIT_GLOBAL_PER_SEC` | `10.0` | Global throughput limit |
| `RATE_LIMIT_PER_PAIR_PER_SEC` | `3.0` | Per-pair throughput limit |
| `METRICS_ENABLED` | `false` | Prometheus metrics (off by default) |

### Signal Format (Redis Stream)

```json
{
  "id": "canary-1762660693780-0",
  "ts": 1762660693780,
  "pair": "SOL-USD",
  "side": "buy",
  "entry": 100.0,
  "sl": 98.0,
  "tp": 104.0,
  "strategy": "canary_publisher",
  "confidence": 0.85,
  "mode": "paper"
}
```

**Field `strategy` Identifies Source:**
- `continuous_publisher` = Fly.io (BTC/ETH)
- `canary_publisher` = Local (SOL/ADA)

---

## Success Criteria

### Canary Deployment Success

- ✅ Canary publisher starts without errors
- ✅ SOL-USD signals appear in Redis stream
- ✅ ADA-USD signals appear in Redis stream
- ✅ API returns 4 pairs (BTC, ETH, SOL, ADA)
- ✅ Site displays SOL/USDT and ADA/USDT
- ✅ No increase in error rates
- ✅ Publisher runs for 5+ minutes without crashes

### Promotion Success

- ✅ All canary success criteria met
- ✅ No errors in logs
- ✅ Decision documented
- ✅ Canary continues running indefinitely

### Rollback Success

- ✅ Canary stopped cleanly (Ctrl+C)
- ✅ Only BTC/ETH signals in Redis (last 10)
- ✅ API returns 2 pairs (BTC, ETH)
- ✅ Site shows only BTC/ETH
- ✅ Reason documented

---

## Appendix: File Locations

| File | Purpose | Location |
|------|---------|----------|
| `.env.paper.local` | Canary environment configuration | Project root |
| `canary_continuous_publisher.py` | Canary publisher script | Project root |
| `scripts/run_publisher_paper.bat` | Windows runner | `scripts/` |
| `scripts/run_publisher_paper.sh` | Bash runner | `scripts/` |
| `logs/paper_local_canary.txt` | Canary publisher logs | `logs/` |
| `logs/paper_e2e_check.txt` | Verification evidence | `logs/` |
| `config/certs/redis_ca.pem` | Redis TLS CA certificate | `config/certs/` |

---

## Appendix: Related Documentation

- **E1-E3 Hardening:** `E1_E2_E3_COMPLETE.md`
- **Rate Limiting:** `E1_RATE_CONTROLS_COMPLETE.md`
- **Prometheus Metrics:** `E2_PROMETHEUS_COMPLETE.md`
- **CI Checks:** `.github/workflows/test.yml`

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2025-11-08 | Initial runbook created | Claude Code |
| 2025-11-08 | Canary deployment successful | Claude Code |
| 2025-11-08 | E2E verification passed | Claude Code |

---

## Contact

For issues or questions:
- **GitHub Issues:** https://github.com/anthropics/claude-code/issues
- **Discord:** (Add your Discord link)
- **Runbook Owner:** Maith

---

**Last Updated:** 2025-11-08
**Version:** 1.0
**Status:** Production-Ready ✅
