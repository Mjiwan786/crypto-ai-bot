# A3 - Staging Publisher Ready

**Status**: ✅ Ready to Run
**Impact on Fly.io**: ZERO (local process only)
**Impact on Production**: ZERO (isolated staging stream)

---

## Summary

Created startup scripts for local staging publisher with safety checks and dry-run validation. Publisher will publish to `signals:paper:staging` stream with 5 trading pairs, completely isolated from production.

---

## Files Created

### 1. Windows Script

**File**: `scripts/run_publisher_staging.bat`

**Features**:
- Loads `.env.staging` configuration
- Validates `PUBLISH_MODE=staging`
- Tests Redis TLS connectivity (dry-run)
- Displays configuration banner
- Starts publisher with safety checks

### 2. Unix/Linux Script

**File**: `scripts/run_publisher_staging.sh`

**Features**:
- Same as Windows version
- Executable permissions set
- Bash compatible

### 3. Updated Staging Environment

**File**: `.env.staging`

**Changes**:
- Now uses A2 feature flags (`PUBLISH_MODE`, `EXTRA_PAIRS`)
- Base pairs: `BTC/USD, ETH/USD`
- Extra pairs: `SOL/USD, ADA/USD, AVAX/USD`
- Backward compatible with legacy vars

---

## Usage

### Quick Start (Windows)

```cmd
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
scripts\run_publisher_staging.bat
```

### Quick Start (Unix/Linux)

```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
./scripts/run_publisher_staging.sh
```

### Alternative (Direct)

```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python run_staging_publisher.py
```

---

## Startup Flow

### Step 1: Configuration Loading

```
[1/4] Loading .env.staging configuration...
      ✓ Configuration loaded
```

**Loads**:
- `PUBLISH_MODE=staging`
- `TRADING_PAIRS=BTC/USD,ETH/USD`
- `EXTRA_PAIRS=SOL/USD,ADA/USD,AVAX/USD`
- `REDIS_URL=rediss://...`
- `REDIS_SSL_CA_CERT=config/certs/redis_ca.pem`

### Step 2: Configuration Verification

```
[2/4] Verifying configuration...
      PUBLISH_MODE: staging
      TRADING_PAIRS: BTC/USD,ETH/USD
      EXTRA_PAIRS: SOL/USD,ADA/USD,AVAX/USD
      Redis Stream: signals:paper:staging
```

**Validates**:
- `PUBLISH_MODE` must equal `"staging"`
- All required env vars present
- Stream name correct

### Step 3: Redis Connectivity Test (Dry-Run)

```
[3/4] Testing Redis TLS connectivity (dry-run)...
      ✓ Redis PING: OK
      ✓ Staging stream exists: 1
```

**Tests**:
- Redis Cloud TLS connection
- Certificate validation
- PING command succeeds
- Staging stream accessible

### Step 4: Start Publisher

```
[4/4] Starting signal publisher...

============================================================
Publishing to: signals:paper:staging
Trading Pairs: [BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD]
Mode: PAPER (no real trades)
Impact on Fly.io: ZERO (local process only)
Impact on Production: ZERO (isolated staging stream)
============================================================

Press Ctrl+C to stop publisher
```

**Banner Shows**:
- Target stream: `signals:paper:staging`
- All 5 trading pairs
- Safety confirmations (no Fly.io, no production impact)

---

## Safety Checks

### 1. Environment Validation

**Check**: `.env.staging` file exists

```batch
if not exist ".env.staging" (
    echo [ERROR] .env.staging not found!
    exit /b 1
)
```

**Error**: Exits if file missing

### 2. Publish Mode Validation

**Check**: `PUBLISH_MODE=staging`

```batch
if not "%PUBLISH_MODE%"=="staging" (
    echo [ERROR] PUBLISH_MODE must be 'staging'
    exit /b 1
)
```

**Error**: Exits if wrong mode (prevents accidental production publishing)

### 3. Redis Connectivity Test

**Check**: TLS connection + PING

```python
r = redis.from_url(
    os.getenv('REDIS_URL'),
    ssl_ca_certs=os.getenv('REDIS_SSL_CA_CERT')
)
print('OK' if r.ping() else 'FAILED')
```

**Error**: Exits if Redis unreachable

---

## Configuration Details

### .env.staging (Updated with A2 Flags)

```bash
# === A2 FEATURE FLAGS ===
PUBLISH_MODE=staging                    # Routes to signals:paper:staging
TRADING_PAIRS=BTC/USD,ETH/USD           # Base pairs
EXTRA_PAIRS=SOL/USD,ADA/USD,AVAX/USD    # Additive pairs

# Redis Cloud TLS
REDIS_URL=rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_SSL=true
REDIS_SSL_CA_CERT=config/certs/redis_ca.pem

# Feature flags
ENABLE_MULTI_PAIR=true
STAGING_MODE=true
```

### Result Configuration

**Stream**: `signals:paper:staging` (from `PUBLISH_MODE=staging`)
**Pairs**: `[BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD]` (base + extra)

---

## Expected Behavior

### Publisher Starts

```
INFO:agents.core.signal_processor:Trading pairs loaded: BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD
INFO:agents.core.signal_processor:  Base pairs: BTC/USD, ETH/USD
INFO:agents.core.signal_processor:  Extra pairs: SOL/USD, ADA/USD, AVAX/USD
INFO:agents.core.signal_processor:Using shared AsyncRedisManager connection
INFO:agents.core.signal_processor:Signal Processor initialized successfully
INFO:agents.core.signal_processor:Starting Signal Processor...
```

### Signals Published

```
INFO:agents.core.signal_processor:Processing signal for BTC/USD
INFO:agents.core.signal_processor:Published to signals:paper:staging
INFO:agents.core.signal_processor:Processing signal for SOL/USD
INFO:agents.core.signal_processor:Published to signals:paper:staging
...
```

### Stop Publisher

```
^C
[STOPPED] Staging publisher terminated
Staging stream data preserved for analysis
```

---

## Verification Commands

### Check Staging Stream Growth

```bash
redis-cli -u "redis://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" \
  --tls --cacert config/certs/redis_ca.pem \
  XLEN signals:paper:staging
```

**Expected**: Incrementing count (e.g., 6 → 20 → 50 → 100)

### Check Production Stream (Should Be Unchanged)

```bash
redis-cli -u "redis://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" \
  --tls --cacert config/certs/redis_ca.pem \
  XLEN signals:paper
```

**Expected**: Stable count (e.g., 10,009 → 10,009)

### View Recent Staging Signals

```bash
redis-cli -u "redis://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" \
  --tls --cacert config/certs/redis_ca.pem \
  XRANGE signals:paper:staging - + COUNT 10
```

**Expected**: Mix of BTC, ETH, SOL, ADA, AVAX signals

---

## Troubleshooting

### Error: ".env.staging not found"

**Cause**: File missing or wrong directory
**Fix**:
```bash
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
ls .env.staging  # Should exist
```

### Error: "PUBLISH_MODE must be 'staging'"

**Cause**: Wrong value in `.env.staging`
**Fix**:
```bash
# Edit .env.staging
PUBLISH_MODE=staging  # Ensure this line exists
```

### Error: "Redis connectivity test failed"

**Cause**: Redis unreachable or certificate issue
**Fix**:
```bash
# Test manually
redis-cli -u "redis://..." --tls --cacert config/certs/redis_ca.pem PING
# Should return: PONG
```

### Error: "conda: command not found" (Windows)

**Cause**: Conda not in PATH
**Fix**:
```bash
# Use full path to python
/c/Users/Maith/.conda/envs/crypto-bot/python.exe run_staging_publisher.py
```

---

## Next Steps

### A4: Soak Test Publisher (3-5 minutes)

**After** starting the publisher:

1. Let it run for 3-5 minutes
2. Collect log excerpts showing non-BTC/ETH pairs (SOL, ADA, AVAX)
3. Capture Redis `XINFO` / `XLEN` evidence
4. Save to `logs/staging_publisher_canary.txt`
5. Commit evidence

### A5: Rollback Plan

Create `RUNBOOK_ROLLBACK.md` with:
- Kill command (Ctrl+C or `pkill python`)
- No prod streams touched confirmation
- Branch revert instructions

---

## Production Safety

### What This Does NOT Touch

✅ **Fly.io**: No changes to deployed app
✅ **signals:paper**: Production stream unchanged
✅ **signals:live**: Live trading stream unchanged
✅ **Main branch**: No git changes to main
✅ **Deployed configs**: No deploy hooks triggered

### What This DOES Touch

⚠️ **signals:paper:staging**: Isolated staging stream (new signals added)
⚠️ **Local process**: Python publisher runs on your machine
⚠️ **Feature branch**: Changes committed to `feature/add-trading-pairs`

---

## Rollback

### Stop Publisher

**Method 1**: Press `Ctrl+C` in terminal

**Method 2**: Kill process
```bash
# Windows
tasklist | findstr python
taskkill /PID <pid> /F

# Linux
pkill -f run_staging_publisher
```

### Clean Staging Stream (Optional)

```bash
redis-cli -u "redis://..." --tls --cacert config/certs/redis_ca.pem \
  DEL signals:paper:staging
```

**Impact**: ZERO (staging data deleted, production untouched)

---

**Status**: ✅ A3 Complete - Ready to Run
**Next**: A4 (Run for 3-5 minutes and collect evidence)
**Command**: `scripts\run_publisher_staging.bat` or `./scripts/run_publisher_staging.sh`
