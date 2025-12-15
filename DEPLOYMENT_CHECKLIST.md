# Deployment Checklist - crypto-ai-bot Engine

**Date:** 2025-11-23
**Target:** Fly.io (New Account)
**Mode:** Paper → Live (after validation)

---

## ✅ Pre-Deployment Checklist

### Configuration & Code

- [x] **PnL Tracker refactored** - Now uses mode-aware streams (`pnl:{mode}:summary`, `pnl:{mode}:equity_curve`)
- [x] **Signal Publisher verified** - Uses per-pair streams (`signals:{mode}:{pair}`)
- [x] **docker-entrypoint.sh updated** - Runs `production_engine.py` with `ENGINE_MODE`
- [x] **fly.toml verified** - `auto_stop_machines=false`, `min_machines_running=1`
- [x] **Redis CA certificate** - Present at `config/certs/redis_ca.pem`
- [x] **Deployment guide created** - `FLYIO_DEPLOYMENT_GUIDE.md`
- [x] **Inspection script ready** - `scripts/inspect_redis_streams.py`

### Redis Configuration

- [x] **Redis URL** - `rediss://default:<REDIS_PASSWORD>@...` (URL-encoded)
- [x] **TLS enabled** - `REDIS_SSL=true`
- [x] **CA certificate path** - `/app/config/certs/redis_ca.pem` (Docker path)
- [x] **Stream naming** - Paper: `signals:paper:<PAIR>`, Live: `signals:live:<PAIR>`
- [x] **PnL separation** - Paper: `pnl:paper:*`, Live: `pnl:live:*`

### Docker & Fly.io

- [x] **Dockerfile.production** - Multi-stage build with TLS support
- [x] **Health endpoint** - `/health` at port 8080
- [x] **Graceful shutdown** - 30s timeout (SIGTERM handling)
- [x] **Auto-suspend prevention** - `auto_stop_machines="off"` in fly.toml
- [x] **Always running** - `min_machines_running=1` in fly.toml

---

## 🧪 Local Testing (Before Fly.io Deployment)

### Step 1: Environment Setup

**Option A: Using test_local_deployment.bat (Windows)**

```cmd
REM Open Anaconda Prompt
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
test_local_deployment.bat
```

**Option B: Manual Setup**

```bash
# Activate conda environment
conda activate crypto-bot

# Set environment variables (Windows PowerShell)
$env:ENGINE_MODE="paper"
$env:REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818"
$env:REDIS_SSL="true"
$env:REDIS_CA_CERT="config/certs/redis_ca.pem"
$env:TRADING_PAIRS="BTC/USD,ETH/USD,SOL/USD"
$env:LOG_LEVEL="INFO"

# Or use .env.paper file (Linux/macOS)
set -a; source .env.paper; set +a
```

### Step 2: Run Production Engine

```bash
python production_engine.py --mode paper
```

**✅ Expected Output:**
```
================================================================================
Production Engine Starting
================================================================================
Mode: paper
Trading Pairs: BTC/USD, ETH/USD, SOL/USD
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

### Step 3: Verify Stream Writes (New Terminal)

```bash
# Open new terminal/Anaconda Prompt
conda activate crypto-bot
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# Inspect paper mode streams
python scripts\inspect_redis_streams.py --mode paper
```

**✅ Expected Output:**
```
================================================================================
SIGNAL STREAMS (PAPER MODE)
================================================================================

📊 Stream: signals:paper:BTC-USD
   Length: 10+ signals
   Latest signals:
      1. [timestamp] BUY @ 43250.50 | conf=0.72 | production_momentum_v1

💰 PnL Summary: pnl:paper:summary
   Equity: $10,000.00
   Mode: paper
```

### Step 4: Verify Health Endpoint

```bash
# In browser or curl
curl http://localhost:8080/health

# Expected response:
# {"status":"healthy","mode":"paper","metrics":{...}}
```

### Step 5: Local Testing Checklist

- [ ] Engine starts without errors
- [ ] Redis connection successful
- [ ] Kraken WebSocket connects
- [ ] Signals published to `signals:paper:BTC-USD`
- [ ] PnL data in `pnl:paper:summary`
- [ ] NO signals in `signals:live:*` (mode separation confirmed)
- [ ] Health endpoint returns 200 OK
- [ ] Engine runs for 5+ minutes without crashes
- [ ] Graceful shutdown on Ctrl+C

**If all items checked:** ✅ Ready for Fly.io deployment

---

## 🚀 Fly.io Deployment Steps

### Step 1: Authenticate

```bash
# Login to NEW Fly.io account (ignore old suspended apps)
fly auth login

# Verify login
fly auth whoami
```

- [ ] Logged in to correct Fly.io account

### Step 2: Create App

```bash
# Create app (only once)
fly apps create crypto-ai-bot-engine

# Verify creation
fly apps list | grep crypto-ai-bot-engine
```

- [ ] App `crypto-ai-bot-engine` created

### Step 3: Set Secrets

```bash
# Set Redis URL (REQUIRED)
fly secrets set REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818" -a crypto-ai-bot-engine

# Verify secrets (values masked)
fly secrets list -a crypto-ai-bot-engine
```

- [ ] `REDIS_URL` secret set
- [ ] Secrets list shows 1 secret

### Step 4: Deploy

```bash
# Deploy to Fly.io
fly deploy -a crypto-ai-bot-engine

# This will:
# - Build Dockerfile.production
# - Push to Fly.io registry
# - Create machine
# - Start production_engine.py
# - Run health checks
```

**Expected Output:**
```
==> Building image
[+] Building 120s (18/18) FINISHED
==> Pushing image to fly
==> Creating release
--> v1 deployed successfully

Watch your deployment at https://fly.io/apps/crypto-ai-bot-engine/monitoring
```

- [ ] Build succeeded
- [ ] Image pushed
- [ ] Release v1 deployed

### Step 5: Verify Deployment

```bash
# Check app status
fly status -a crypto-ai-bot-engine
```

**✅ Expected:**
```
Machines
PROCESS ID      VERSION REGION  STATE   HEALTH CHECKS       LAST UPDATED
app     abc123  v1      iad     started 1 total, 1 passing  2m ago
```

- [ ] Machine state: `started` (NOT `suspended`)
- [ ] Health checks: `1 total, 1 passing`

### Step 6: Check Logs

```bash
# Tail logs in real-time
fly logs -a crypto-ai-bot-engine
```

**✅ Look for:**
```
Production Engine Starting
Mode: paper
[READY] Production Engine Ready
Signal published: BTC/USD BUY @ 43250.50
```

- [ ] Engine started successfully
- [ ] Redis connection established
- [ ] Kraken WebSocket connected
- [ ] Signals being published

### Step 7: Verify Stream Writes (Local Machine)

```bash
# From local machine with crypto-bot env
conda activate crypto-bot
python scripts\inspect_redis_streams.py --mode paper
```

**✅ Expected:**
- Signals from Fly.io engine appearing in `signals:paper:BTC-USD`
- Length increasing over time (10+ signals after 5 minutes)

- [ ] Signals visible in Redis
- [ ] Stream length growing
- [ ] Mode separation confirmed (no signals in `signals:live:*`)

### Step 8: Health Check

```bash
# Check public health endpoint (if configured)
curl https://crypto-ai-bot-engine.fly.dev/health

# Or SSH into machine
fly ssh console -a crypto-ai-bot-engine
curl http://localhost:8080/health
```

- [ ] Health endpoint returns 200 OK
- [ ] Response: `{"status":"healthy","mode":"paper",...}`

---

## ⏱️ 24-Hour Validation

After deployment, monitor for 24 hours to confirm no auto-suspension:

### Hour 1
- [ ] Machine status: `started`
- [ ] Health checks: passing
- [ ] Signals being published

### Hour 6
- [ ] Machine status: `started` (still running)
- [ ] No unexpected restarts
- [ ] Continuous signal publishing

### Hour 12
- [ ] Machine status: `started` (still running)
- [ ] Memory usage stable (< 1GB)
- [ ] No errors in logs

### Hour 24
- [ ] Machine status: `started` (✅ **NO AUTO-SUSPENSION**)
- [ ] Uptime: ~24 hours
- [ ] Signals: 500+ in each pair stream
- [ ] Health checks: continuous passing

**✅ If all items checked after 24h:** Deployment successful, ready for live mode switch

---

## 🔄 Switching to Live Mode

**⚠️ ONLY after 24h+ paper mode validation**

### Step 1: Set Live Secrets

```bash
fly secrets set KRAKEN_API_KEY="your-live-api-key" -a crypto-ai-bot-engine
fly secrets set KRAKEN_SECRET="your-live-api-secret" -a crypto-ai-bot-engine
fly secrets set LIVE_TRADING_CONFIRMATION="I confirm live trading" -a crypto-ai-bot-engine
```

- [ ] Kraken API keys configured
- [ ] Live trading confirmation set

### Step 2: Update fly.toml

```toml
[env]
  ENGINE_MODE = "live"  # Changed from "paper"
```

- [ ] `ENGINE_MODE` changed to `"live"` in fly.toml

### Step 3: Deploy Live Mode

```bash
fly deploy -a crypto-ai-bot-engine
```

- [ ] Deployment successful
- [ ] Logs show: `Mode: live`

### Step 4: Verify Live Streams

```bash
python scripts\inspect_redis_streams.py --mode live
```

**✅ Expected:**
- Signals in `signals:live:BTC-USD` (NOT `signals:paper:*`)
- PnL in `pnl:live:summary`

- [ ] Signals in live streams only
- [ ] No paper mode signals being generated
- [ ] Mode separation confirmed

---

## 🛠️ Troubleshooting

### Issue: App suspends after 30 minutes

**Check:**
```bash
fly status -a crypto-ai-bot-engine
# If shows "suspended", check fly.toml
```

**Fix:**
- Verify `auto_stop_machines = false` (or `"off"`) in fly.toml
- Redeploy: `fly deploy -a crypto-ai-bot-engine`

### Issue: Health check fails

**Check:**
```bash
fly logs -a crypto-ai-bot-engine | grep health
fly ssh console -a crypto-ai-bot-engine
curl http://localhost:8080/health
```

**Fix:**
- Ensure production_engine.py is running
- Check port 8080 is listening
- Verify health endpoint code is correct

### Issue: No signals published

**Check:**
```bash
fly logs -a crypto-ai-bot-engine | grep "Signal published"
fly logs -a crypto-ai-bot-engine | grep ERROR
```

**Fix:**
- Check Kraken WebSocket connection in logs
- Verify TRADING_PAIRS env var is set
- Inspect local Redis streams to confirm writes

### Issue: Redis connection fails

**Check:**
```bash
fly logs -a crypto-ai-bot-engine | grep -i redis
fly secrets list -a crypto-ai-bot-engine
```

**Fix:**
- Verify REDIS_URL secret is set correctly
- Check CA certificate exists in Docker image:
  ```bash
  fly ssh console -a crypto-ai-bot-engine
  ls -la /app/config/certs/redis_ca.pem
  ```

---

## 📊 Success Metrics

### Deployment Success
- ✅ Status: `started` (never `suspended`)
- ✅ Health: `1 total, 1 passing`
- ✅ Uptime: 24+ hours continuous
- ✅ Logs: No errors or warnings
- ✅ Memory: < 1GB (stable)
- ✅ CPU: < 50% average

### Data Integrity
- ✅ Signals: 10+ per hour per pair
- ✅ Streams: `signals:paper:BTC-USD` has 500+ after 24h
- ✅ PnL: Tracking active and accurate
- ✅ Mode separation: No cross-contamination between paper/live
- ✅ Stream naming: Correct prefixes (`signals:{mode}:{pair}`)

### Performance
- ✅ Latency: < 500ms (data ingestion → signal publish)
- ✅ Health checks: 100% passing rate
- ✅ WebSocket: < 5 reconnects/day
- ✅ Redis: < 20ms publish latency

---

## 📝 Post-Deployment Notes

**Deployment Date:** _____________
**Deployed By:** _____________
**Fly.io App:** crypto-ai-bot-engine
**Mode:** paper / live _(circle one)_

**24h Validation:**
- Start Time: _____________
- End Time: _____________
- Uptime %: _____________
- Total Signals: _____________
- Errors: _____________

**Approval for Live Mode:**
- [ ] 24h paper mode validation passed
- [ ] All metrics within acceptable ranges
- [ ] No errors or issues observed
- [ ] Team approval obtained

**Approved By:** _____________
**Date:** _____________

---

**Last Updated:** 2025-11-23
**Next Review:** After 7 days of continuous operation
