# Fly.io Deployment - Quick Start Guide

Deploy crypto-ai-bot to Fly.io as a 24/7 worker in 5 minutes.

## Prerequisites

- Fly.io account: https://fly.io/app/sign-up
- Redis Cloud URL (TLS): `rediss://...`
- Kraken API credentials
- Git repository cloned locally

## Step 1: Install Fly.io CLI

```bash
# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex

# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh

# Verify
fly version
```

## Step 2: Authenticate

```bash
fly auth login
```

This opens your browser for authentication.

## Step 3: Run Pre-Deployment Checklist

```bash
# Comprehensive check
python scripts/deploy_checklist.py

# Or quick check
python scripts/check_redis_tls.py
python scripts/check_kraken_api.py
```

**All checks must pass before deployment.**

## Step 4: Create Fly.io App

```bash
# Create app (DO NOT deploy yet)
fly launch --name crypto-ai-bot --no-deploy --region ewr

# Region 'ewr' (Newark, NJ) is closest to Redis Cloud us-east-1-4
```

**Note:** This command creates `fly.toml` (already exists in repo).

## Step 5: Set Secrets

⚠️ **CRITICAL:** Never commit secrets to git!

```bash
# Set all required secrets
fly secrets set \
  REDIS_URL="rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0" \
  KRAKEN_API_KEY="your_kraken_api_key_here" \
  KRAKEN_API_SECRET="your_kraken_api_secret_here" \
  DISCORD_BOT_TOKEN="your_discord_bot_token" \
  DISCORD_CHANNEL_ID="your_discord_channel_id"
```

**Important notes:**
- Use `rediss://` (double 's') for TLS
- URL-encode special characters in password:
  - `*` → `%2A`
  - `$` → `%24`
  - Example: `**$$` → `%2A%2A%24%24`

**Verify secrets:**

```bash
fly secrets list
```

Expected output:
```
NAME                  DIGEST                    CREATED AT
REDIS_URL             xxxxxxxxxxxxxxxxxxxx      1m ago
KRAKEN_API_KEY        xxxxxxxxxxxxxxxxxxxx      1m ago
KRAKEN_API_SECRET     xxxxxxxxxxxxxxxxxxxx      1m ago
DISCORD_BOT_TOKEN     xxxxxxxxxxxxxxxxxxxx      1m ago
DISCORD_CHANNEL_ID    xxxxxxxxxxxxxxxxxxxx      1m ago
```

## Step 6: Deploy

```bash
# Deploy application
fly deploy

# Monitor deployment
fly status
```

**Expected output:**
```
ID              PROCESS VERSION REGION  STATE   CHECKS
abcd1234        app     1       ewr     running 1 passing
```

## Step 7: Verify Deployment

### Check Application Status

```bash
fly status
```

### View Logs

```bash
# Real-time logs
fly logs

# Filter logs
fly logs | grep "Redis"
fly logs | grep "Trading"
```

**Expected log entries:**
```
✓ Redis connected (latency: 12.5ms)
✓ Kraken API connected
TRADING SYSTEM IS NOW RUNNING
Mode: PAPER
```

### Test Health Endpoint

```bash
# Method 1: Via SSH
fly ssh console -C "curl -s http://localhost:8080/health | jq"

# Method 2: Via proxy
fly proxy 8080:8080
# Then visit: http://localhost:8080/health
```

**Expected health response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-15T10:30:00Z",
  "uptime_seconds": 120,
  "redis": {
    "connected": true,
    "latency_ms": 12.5,
    "ssl_enabled": true
  },
  "environment": "prod",
  "version": "0.5.0"
}
```

## Step 8: Monitor Application

```bash
# Stream logs
fly logs -f

# Open dashboard
fly dashboard
```

---

## Common Commands

```bash
# Status
fly status                          # App status
fly info                            # App details
fly scale show                      # Scaling info

# Logs
fly logs                            # Stream logs
fly logs -f                         # Follow logs
fly logs | grep ERROR               # Filter errors

# Deployment
fly deploy                          # Deploy updates
fly releases                        # List releases
fly releases rollback               # Rollback

# Secrets
fly secrets list                    # List secrets
fly secrets set KEY=VALUE           # Set secret
fly secrets unset KEY               # Remove secret

# SSH & Debugging
fly ssh console                     # Interactive shell
fly ssh console -C "curl http://localhost:8080/health"

# Scaling
fly scale count 2                   # Scale instances
fly scale memory 2048               # Scale RAM (2GB)
fly apps restart crypto-ai-bot      # Restart app

# Emergency
fly scale count 0                   # Stop app (emergency)
fly apps suspend crypto-ai-bot      # Suspend app
fly apps resume crypto-ai-bot       # Resume app
```

---

## Troubleshooting

### Issue: Deployment Fails

```bash
# Check build logs
fly logs

# Verify secrets
fly secrets list

# Test locally first
docker build -t crypto-ai-bot .
docker run --env-file .env.prod -p 8080:8080 crypto-ai-bot
```

### Issue: Redis Connection Failed

**Symptoms:** Logs show `invalid username-password pair`

**Solution:**

1. Verify URL format: `rediss://` (double 's')
2. Check URL encoding of password
3. Test connection:
   ```bash
   fly ssh console
   python scripts/check_redis_tls.py
   ```

### Issue: Health Checks Failing

```bash
# Check health endpoint manually
fly ssh console -C "curl -v http://localhost:8080/health"

# Verify port 8080 is exposed
fly ssh console -C "netstat -tlnp | grep 8080"

# Review logs
fly logs | grep health
```

### Issue: App Keeps Restarting

```bash
# Check logs for errors
fly logs | tail -50

# Review resource usage
fly ssh console -C "free -m"

# Scale up if needed
fly scale memory 2048
```

---

## Next Steps

### Enable Live Trading (⚠️ EXTREME CAUTION)

1. **Verify paper trading performance** (monitor for 24-48 hours)
   ```bash
   fly logs | grep "PnL"
   ```

2. **Set live trading secrets**
   ```bash
   fly secrets set \
     PAPER_TRADING_ENABLED="false" \
     LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
   ```

3. **Redeploy**
   ```bash
   fly deploy
   ```

4. **Monitor closely**
   ```bash
   fly logs -f
   ```

### Emergency Stop

```bash
# Method 1: Kill switch (via Redis)
fly ssh console
redis-cli -u $REDIS_URL --tls SET control:halt_all "EMERGENCY_STOP"

# Method 2: Scale to zero
fly scale count 0

# Method 3: Suspend app
fly apps suspend crypto-ai-bot
```

### Rollback to Previous Version

```bash
# List releases
fly releases

# Rollback
fly releases rollback
```

---

## Cost Optimization

### Current Configuration

- **VM:** 1 shared CPU, 1GB RAM
- **Region:** ewr (Newark, NJ)
- **Estimated cost:** ~$5-10/month

### Scale Down (Lower Cost)

```bash
# Reduce to 512MB RAM (if sufficient)
fly scale memory 512
```

### Scale Up (Better Performance)

```bash
# Increase to 2GB RAM
fly scale memory 2048

# Add dedicated CPU
fly scale vm dedicated-cpu-1x
```

---

## Monitoring & Alerts

### Prometheus Metrics

```bash
# Access metrics endpoint
fly proxy 9091:9091

# View metrics
curl http://localhost:9091/metrics
```

### Discord Alerts

Alerts are automatically sent to Discord channel (if configured):

- Trading errors
- Redis connection issues
- Significant PnL changes
- Kill switch activations

---

## Documentation

- **RUNBOOK.md:** Comprehensive operations guide
- **DOCKER_DEPLOYMENT.md:** Docker deployment guide
- **Fly.io Docs:** https://fly.io/docs/

---

## Support

**Deployment Issues:**
1. Run `python scripts/deploy_checklist.py`
2. Check logs: `fly logs`
3. Review RUNBOOK.md troubleshooting section

**Trading Issues:**
1. Activate kill switch if needed
2. Review logs for anomalies
3. Scale to zero if critical

**Emergency Contact:**
- Slack: #crypto-ai-bot-alerts
- Email: crypto-bot-team@example.com

---

**Deployment Date:** 2025-01-15
**Version:** 0.5.0
**Status:** ✅ Ready for Production
