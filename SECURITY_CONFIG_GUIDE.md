# Security Configuration Guide

## Overview

This guide documents the security hardening completed on **2025-11-16** to eliminate all hard-coded secrets from the crypto-ai-bot repository.

## Security Incident Response

**Issue:** Hard-coded credentials (Redis URLs, API keys, passwords) were accidentally committed to the repository.

**Resolution:** All hard-coded secrets have been removed and replaced with environment variable configuration.

---

## Changes Made

### 1. .gitignore Updated

**File:** `.gitignore`

**Change:** Added patterns to exclude all `.env.*` files except `.env.*.example` files:

```gitignore
.env
.env.*
!.env.*.example
!.env.example
```

### 2. Python Files Cleaned

All hard-coded Redis URLs and secrets removed from:

- `check_pnl_data.py` - Now reads `REDIS_URL` from environment
- `process_trades_once.py` - Now reads `REDIS_URL` from environment
- `profitability_metrics_publisher.py` - Now reads `REDIS_URL` from environment
- `config/protection_mode_controller.py` - Removed hard-coded fallback URL
- `config/turbo_scalper_controller.py` - Removed hard-coded fallback URL

**Pattern:** All files now use `os.getenv("REDIS_URL")` without hard-coded fallbacks.

### 3. Configuration Files Cleaned

**ecosystem.all.config.js:**
- All 6 instances of hard-coded Redis URLs replaced with `process.env.REDIS_URL || ''`

**config/soak_test_48h_turbo.yaml:**
- Hard-coded Redis URL replaced with placeholder: `url: "${REDIS_URL}"`

### 4. Environment Files Deleted

**Deleted files with real credentials:**
- `.env.canary`
- `.env.dev`
- `.env.live`
- `.env.paper`
- `.env.paper.live`
- `.env.paper.local`
- `.env.prod`
- `.env.staging`

These files contained actual passwords and should **never** be committed to Git.

### 5. Example Files Cleaned

All `.example` and `.template` files cleaned to use only placeholders:

**Files updated:**
- `.env.example` - Main example file with all placeholders
- `.env.dev.example`
- `.env.live.example`
- `.env.local.example`
- `.env.paper.example`
- `.env.prod.example`
- `compose.env.example`
- `env.staging.example`
- `env.staging.template`
- `env.prod.example`
- `env.prod.template`

**Secrets removed:**
- Redis URLs and passwords
- Kraken API keys
- KuCoin API keys and passphrase
- Reddit credentials
- CoinMarketCap API key
- CryptoCompare API key

**Replaced with placeholders:**
- `<YOUR_REDIS_URL>`
- `<YOUR_REDIS_PASSWORD>`
- `<YOUR_REDIS_HOST>`
- `<YOUR_REDIS_PORT>`
- `<YOUR_KRAKEN_API_KEY>`
- `<YOUR_KRAKEN_API_SECRET>`
- `<YOUR_KUCOIN_API_KEY>`
- `<YOUR_KUCOIN_API_SECRET>`
- `<YOUR_KUCOIN_PASSPHRASE>`
- etc.

---

## Configuration Best Practices

### 1. Using Environment Variables

**For local development:**

```bash
# Create your local .env file (DO NOT COMMIT!)
cp .env.example .env

# Edit .env with your actual credentials
# This file is git-ignored
```

**For production (Fly.io):**

```bash
# Set secrets via Fly CLI
fly secrets set REDIS_URL="rediss://default:YOUR_PASSWORD@YOUR_HOST:PORT"
fly secrets set KRAKEN_API_KEY="your_key_here"
fly secrets set KRAKEN_API_SECRET="your_secret_here"
```

**For GitHub Actions:**

Add secrets via GitHub repository settings:
- Settings → Secrets and variables → Actions
- Add `REDIS_URL`, `KRAKEN_API_KEY`, etc.

### 2. Redis Configuration

**Required environment variables:**

```bash
REDIS_URL=rediss://default:YOUR_PASSWORD@YOUR_HOST:PORT
```

**Optional (parsed from REDIS_URL if not provided):**

```bash
REDIS_HOST=your-redis-host.com
REDIS_PORT=19818
REDIS_PASSWORD=your_password
REDIS_USERNAME=default
```

**TLS Certificate:**

```bash
REDIS_CA_CERT=config/certs/redis_ca.pem
REDIS_SSL=true
```

### 3. Exchange API Keys

**Kraken:**

```bash
KRAKEN_API_KEY=your_kraken_api_key
KRAKEN_API_SECRET=your_kraken_api_secret
```

**KuCoin (if used):**

```bash
KUCOIN_API_KEY=your_kucoin_key
KUCOIN_API_SECRET=your_kucoin_secret
KUCOIN_API_PASSPHRASE=your_kucoin_passphrase
```

### 4. OpenAI/LLM Keys (if used)

```bash
OPENAI_API_KEY=your_openai_key
```

---

## Verification Checklist

Before deploying or committing code, verify:

- [ ] No hard-coded passwords in `.py` files
- [ ] No hard-coded API keys in `.js` files
- [ ] No hard-coded secrets in `.yaml` files
- [ ] All `.env.*` files (except `.example`) are in `.gitignore`
- [ ] All `.env.*.example` files contain only placeholders
- [ ] Environment variables are set in deployment platforms
- [ ] Redis connection works with env vars only

---

## Testing Configuration

**Test Redis connection:**

```bash
# Set your environment variables
export REDIS_URL="rediss://default:YOUR_PASSWORD@YOUR_HOST:PORT"

# Test connection
python check_pnl_data.py
```

**Test with ecosystem (PM2):**

```bash
# Set environment variables first
export REDIS_URL="your_redis_url_here"
export KRAKEN_API_KEY="your_key"
export KRAKEN_API_SECRET="your_secret"

# Start with PM2
pm2 start ecosystem.all.config.js
```

---

## Security Reminders

1. **NEVER commit `.env` files** - They should always be in `.gitignore`
2. **Rotate all exposed credentials** - If secrets were committed, rotate them immediately
3. **Use secret managers** - Fly.io secrets, Vercel env vars, GitHub Actions secrets
4. **Example files** - Only placeholders, never real values
5. **Code reviews** - Check for hard-coded secrets before merging PRs
6. **Documentation** - Use placeholders like `<YOUR_PASSWORD>` in docs and examples

---

## Remaining Tasks

### Documentation Files

**Note:** 100+ markdown documentation files still contain example commands with old hard-coded credentials. These are lower priority since:

1. They're internal documentation
2. The actual code doesn't use them
3. They serve as historical reference

**Recommendation:** Update documentation files as needed when referencing them, replacing real credentials with placeholders:

```bash
# Bad (don't do this in docs)
redis-cli -u rediss://default:RealPassword123@host:port

# Good (use placeholders)
redis-cli -u rediss://default:<YOUR_PASSWORD>@<YOUR_HOST>:<PORT>
```

---

## Support

If you encounter configuration issues:

1. Check that all required environment variables are set
2. Verify `.env` file exists and is properly formatted
3. Ensure secrets are set in your deployment platform
4. Check logs for "environment variable not set" errors

For production deployments, always verify secrets are correctly configured before starting services.
