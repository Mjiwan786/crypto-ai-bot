# Crypto AI Bot - Operations Runbook

Production deployment and operations guide for Fly.io 24/7 worker deployment.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Deployment](#deployment)
- [Verification](#verification)
- [Monitoring](#monitoring)
- [Common Operations](#common-operations)
- [Troubleshooting](#troubleshooting)
- [Rollback Procedures](#rollback-procedures)
- [Emergency Procedures](#emergency-procedures)

---

## Prerequisites

### Required Tools

- **Fly.io CLI** (v0.1.0+)
  ```bash
  # Windows (PowerShell)
  iwr https://fly.io/install.ps1 -useb | iex

  # macOS/Linux
  curl -L https://fly.io/install.sh | sh
  ```

- **Docker** (for local testing)
  ```bash
  docker --version  # Should be 20.10+
  ```

- **Git** (for version control)

### Required Credentials

- ✅ Fly.io account (https://fly.io/app/sign-up)
- ✅ Redis Cloud URL with TLS (rediss://)
- ✅ Kraken API credentials (API Key + Secret)
- ✅ Discord bot token (optional, for alerts)
- ✅ Redis CA certificate (`config/certs/redis_ca.pem`)

### Preflight Checklist

Before deploying, run:

```bash
# Run comprehensive preflight checks
make preflight

# Or manually:
python scripts/check_redis_tls.py
python scripts/check_kraken_api.py
```

**All checks must pass before deployment.**

---

## Initial Setup

### 1. Install Fly.io CLI

```bash
# Windows
iwr https://fly.io/install.ps1 -useb | iex

# Verify installation
fly version
```

### 2. Authenticate with Fly.io

```bash
fly auth login
```

This will open your browser for authentication.

### 3. Create Fly.io App

```bash
# Launch app (DO NOT deploy yet)
fly launch --name crypto-ai-bot --no-deploy --region ewr

# This creates fly.toml (already exists in repo)
```

**Important:** Choose region `ewr` (Newark, NJ) - closest to Redis Cloud `us-east-1-4`.

---

## Deployment

### Step 1: Configure Secrets

⚠️ **CRITICAL: Never commit secrets to git!**

```bash
# Required secrets
fly secrets set \
  REDIS_URL="rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0" \
  KRAKEN_API_KEY="your_kraken_api_key_here" \
  KRAKEN_API_SECRET="your_kraken_api_secret_here" \
  DISCORD_BOT_TOKEN="your_discord_bot_token" \
  DISCORD_CHANNEL_ID="your_discord_channel_id"

# Verify secrets are set
fly secrets list
```

**Expected output:**
```
NAME                  DIGEST                    CREATED AT
REDIS_URL             xxxxxxxxxxxxxxxxxxxx      1m ago
KRAKEN_API_KEY        xxxxxxxxxxxxxxxxxxxx      1m ago
KRAKEN_API_SECRET     xxxxxxxxxxxxxxxxxxxx      1m ago
DISCORD_BOT_TOKEN     xxxxxxxxxxxxxxxxxxxx      1m ago
DISCORD_CHANNEL_ID    xxxxxxxxxxxxxxxxxxxx      1m ago
```

### Step 2: Build Docker Image

Test the build locally before deploying:

```bash
# Build image (optional - Fly.io will do this)
docker build -t crypto-ai-bot:latest .

# Test locally (with .env.prod)
docker run --env-file .env.prod -p 8080:8080 crypto-ai-bot:latest
```

### Step 3: Deploy to Fly.io

```bash
# Initial deployment (paper trading mode by default)
fly deploy

# Monitor deployment
fly status
```

**Expected output:**
```
ID              PROCESS VERSION REGION  STATE   CHECKS          RESTARTS
abcd1234        app     1       ewr     running 1 total         0
```

### Step 4: Verify Deployment

```bash
# Check application status
fly status

# View logs (real-time)
fly logs

# Check health endpoint
fly ssh console -C "curl http://localhost:8080/health"
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

---

## Verification

### Check 1: Application Running

```bash
fly status
```

**Expected:** Status = `running`, Checks = `passing`

### Check 2: Health Endpoint

```bash
# From Fly.io SSH
fly ssh console -C "curl -s http://localhost:8080/health | jq"

# Or use Fly.io proxy
fly proxy 8080:8080
# Then visit: http://localhost:8080/health
```

### Check 3: Redis Connectivity

Look for Redis heartbeats in logs:

```bash
fly logs | grep -i redis
```

**Expected log entries:**
```
✓ Redis connected (latency: 12.5ms)
✓ PING successful
✓ Stream operations working
```

### Check 4: Kraken Connectivity

```bash
fly logs | grep -i kraken
```

**Expected log entries:**
```
✓ Kraken API connected
✓ Asset pairs loaded: BTC/USD, ETH/USD, SOL/USD
✓ System status: online
```

### Check 5: Trading System Active

```bash
fly logs | grep -i "trading system"
```

**Expected log entries:**
```
TRADING SYSTEM IS NOW RUNNING
Mode: PAPER
```

---

## Monitoring

### Real-Time Logs

```bash
# Stream all logs
fly logs

# Filter by keyword
fly logs | grep ERROR
fly logs | grep "Redis"
fly logs | grep "signal"

# Last 100 lines
fly logs --tail 100
```

### Health Dashboard

```bash
# Open Fly.io dashboard
fly dashboard

# Or visit: https://fly.io/apps/crypto-ai-bot
```

### Metrics

Access Prometheus metrics:

```bash
# Proxy metrics port
fly proxy 9091:9091

# View metrics
curl http://localhost:9091/metrics
```

**Key metrics to monitor:**
- `trading_signals_total`: Total signals generated
- `orders_executed_total`: Total orders executed
- `redis_connection_status`: Redis health (1=up, 0=down)
- `pnl_realized_total`: Realized PnL

### SSH into Container

```bash
# Open interactive shell
fly ssh console

# Run commands
fly ssh console -C "ps aux"
fly ssh console -C "df -h"
fly ssh console -C "free -m"
```

---

## Common Operations

### Restart Application

```bash
# Graceful restart
fly apps restart crypto-ai-bot

# Or force restart
fly machine restart <machine-id>
```

### Scale Resources

```bash
# Scale to 2GB RAM
fly scale memory 2048

# Scale to 2 CPUs
fly scale count 2

# Check current scaling
fly scale show
```

### Update Application

```bash
# Pull latest code
git pull origin main

# Deploy update
fly deploy

# Monitor deployment
fly status
fly logs
```

### View Application Info

```bash
# App details
fly info

# VM status
fly status

# Scale info
fly scale show

# Secrets (names only)
fly secrets list
```

### Change Secrets

```bash
# Update a secret
fly secrets set KRAKEN_API_KEY="new_api_key"

# Remove a secret
fly secrets unset SECRET_NAME

# Import from file
fly secrets import < secrets.txt
```

---

## Troubleshooting

### Issue: Application Not Starting

**Symptoms:**
- Status shows `pending` or `error`
- Logs show crash loop

**Diagnosis:**
```bash
fly logs | tail -50
fly status
```

**Solutions:**

1. **Check environment variables:**
   ```bash
   fly ssh console -C "env | grep REDIS_URL"
   ```

2. **Verify secrets are set:**
   ```bash
   fly secrets list
   ```

3. **Check health endpoint:**
   ```bash
   fly ssh console -C "curl http://localhost:8080/health"
   ```

4. **Review logs for errors:**
   ```bash
   fly logs | grep -i error
   ```

### Issue: Redis Connection Failed

**Symptoms:**
- Logs show `Connection failed: invalid username-password pair`
- Health endpoint returns `redis_connected: false`

**Solutions:**

1. **Verify Redis URL format:**
   ```bash
   # Should be: rediss:// (with double 's' for TLS)
   fly secrets list | grep REDIS_URL
   ```

2. **Check URL encoding:**
   ```bash
   # Special characters in password must be URL-encoded
   # Example: ** becomes %2A%2A, $$ becomes %24%24
   ```

3. **Test Redis connection:**
   ```bash
   fly ssh console
   python scripts/check_redis_tls.py
   ```

4. **Verify CA certificate exists:**
   ```bash
   fly ssh console -C "ls -la config/certs/redis_ca.pem"
   ```

### Issue: Health Checks Failing

**Symptoms:**
- Fly.io dashboard shows failing health checks
- App keeps restarting

**Solutions:**

1. **Check health endpoint manually:**
   ```bash
   fly ssh console -C "curl -v http://localhost:8080/health"
   ```

2. **Verify port 8080 is exposed:**
   ```bash
   fly ssh console -C "netstat -tlnp | grep 8080"
   ```

3. **Review health.py logs:**
   ```bash
   fly logs | grep health
   ```

### Issue: High Memory Usage

**Symptoms:**
- OOM (Out of Memory) errors in logs
- Application crashes intermittently

**Solutions:**

1. **Check current memory usage:**
   ```bash
   fly ssh console -C "free -m"
   ```

2. **Scale up memory:**
   ```bash
   fly scale memory 2048  # 2GB
   ```

3. **Review memory-intensive operations:**
   ```bash
   fly logs | grep -i memory
   ```

### Issue: Trading System Not Responding

**Symptoms:**
- No signal generation in logs
- No orders being executed

**Solutions:**

1. **Check if kill switch is activated:**
   ```bash
   fly ssh console
   redis-cli -u $REDIS_URL --tls GET control:halt_all
   ```

2. **Verify trading mode:**
   ```bash
   fly logs | grep "Trading mode"
   ```

3. **Check strategy router:**
   ```bash
   fly logs | grep -i strategy
   ```

---

## Rollback Procedures

### Rollback to Previous Version

```bash
# List recent releases
fly releases

# Rollback to previous version
fly releases rollback

# Or specific version
fly releases rollback --version <version-number>
```

### Emergency Shutdown

```bash
# Stop application immediately
fly scale count 0

# Or suspend app
fly apps suspend crypto-ai-bot
```

### Restore from Backup

```bash
# Pull previous git commit
git log --oneline -5
git checkout <commit-hash>

# Redeploy
fly deploy
```

---

## Emergency Procedures

### Kill Switch Activation

**When to use:** Trading anomalies, unexpected losses, system instability

```bash
# Method 1: Via Redis
fly ssh console
redis-cli -u $REDIS_URL --tls SET control:halt_all "EMERGENCY_STOP"

# Method 2: Scale to zero
fly scale count 0

# Method 3: Suspend app
fly apps suspend crypto-ai-bot
```

### Deactivate Kill Switch

```bash
fly ssh console
redis-cli -u $REDIS_URL --tls DEL control:halt_all

# Restart if needed
fly apps restart crypto-ai-bot
```

### Enable Live Trading

⚠️ **EXTREME CAUTION REQUIRED**

```bash
# 1. Verify paper trading performance
fly logs | grep "PnL"

# 2. Set live trading secrets
fly secrets set \
  PAPER_TRADING_ENABLED="false" \
  LIVE_TRADING_CONFIRMATION="I-accept-the-risk"

# 3. Redeploy with live mode
fly deploy

# 4. Monitor closely
fly logs -f
```

### Disable Live Trading (Emergency)

```bash
# Immediately revert to paper trading
fly secrets set PAPER_TRADING_ENABLED="true"

# Or stop trading entirely
fly scale count 0
```

---

## Deployment Checklist

Before each deployment:

- [ ] Run `make preflight` - all checks pass
- [ ] Review recent code changes
- [ ] Test locally with Docker
- [ ] Verify secrets are current
- [ ] Check Redis Cloud connectivity
- [ ] Review Kraken API status
- [ ] Backup current configuration
- [ ] Notify team of deployment
- [ ] Monitor logs for 30 minutes post-deployment
- [ ] Verify health endpoint responds
- [ ] Check trading signals are being generated
- [ ] Confirm Redis heartbeats in logs

---

## Useful Commands Reference

```bash
# === Application Management ===
fly status                           # Check app status
fly apps restart crypto-ai-bot       # Restart app
fly apps suspend crypto-ai-bot       # Stop app
fly apps resume crypto-ai-bot        # Start app
fly scale count 0                    # Scale to zero (emergency stop)

# === Logs & Monitoring ===
fly logs                             # Stream logs
fly logs -f                          # Follow logs
fly logs | grep ERROR                # Filter errors
fly dashboard                        # Open web dashboard

# === Deployment ===
fly deploy                           # Deploy current code
fly deploy --build-only              # Test build without deploying
fly releases                         # List releases
fly releases rollback                # Rollback to previous

# === Secrets Management ===
fly secrets list                     # List secret names
fly secrets set KEY=VALUE            # Set secret
fly secrets unset KEY                # Remove secret
fly secrets import < file.txt        # Import from file

# === SSH & Debugging ===
fly ssh console                      # Interactive shell
fly ssh console -C "command"         # Run command
fly proxy 8080:8080                  # Local port forwarding

# === Scaling ===
fly scale memory 2048                # Scale RAM
fly scale count 2                    # Scale instances
fly scale show                       # Show current scale

# === Health Checks ===
curl http://localhost:8080/health    # Health endpoint (via proxy)
fly ssh console -C "curl http://localhost:8080/health | jq"
```

---

## Support & Escalation

### Level 1: Automated Monitoring

- Health checks (30s interval)
- Discord alerts (errors, trading anomalies)
- Prometheus metrics

### Level 2: Manual Checks

- Review logs daily
- Check PnL metrics
- Verify Redis connectivity
- Monitor resource usage

### Level 3: Incident Response

1. Activate kill switch if needed
2. Scale to zero if critical
3. Review logs for root cause
4. Apply hotfix or rollback
5. Document incident
6. Post-mortem analysis

---

## Maintenance Schedule

### Daily

- Review logs for errors
- Check PnL performance
- Verify health endpoint
- Monitor resource usage

### Weekly

- Update dependencies (if needed)
- Review and optimize strategies
- Analyze trading performance
- Test backup/restore procedures

### Monthly

- Security audit
- Cost optimization review
- Capacity planning
- Update documentation

---

## Version History

| Version | Date       | Changes                           |
|---------|------------|-----------------------------------|
| 1.0.0   | 2025-01-15 | Initial Fly.io deployment runbook |

---

**Last Updated:** 2025-01-15
**Maintained By:** Crypto AI Bot Team
**Emergency Contact:** [Your contact info]
