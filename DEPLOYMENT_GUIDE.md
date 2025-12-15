# 24/7 Production Deployment Guide
## AI Predicted Signals - Unified Infrastructure

Complete guide for deploying and monitoring the 3-tier AI trading SaaS system with **99.8% uptime guarantee** and **<500ms latency**.

---

## 📋 Table of Contents

1. [System Architecture](#system-architecture)
2. [Prerequisites](#prerequisites)
3. [Unified Configuration](#unified-configuration)
4. [Repository Setup](#repository-setup)
5. [Secrets Management](#secrets-management)
6. [Deployment](#deployment)
7. [Monitoring & Alerting](#monitoring--alerting)
8. [Troubleshooting](#troubleshooting)
9. [SLA Compliance](#sla-compliance)

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  AI PREDICTED SIGNALS ARCHITECTURE               │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────┐      ┌──────────────────┐      ┌─────────────┐
│ crypto-ai-bot    │─────>│ Redis Cloud      │<─────│ signals-api │
│ (Fly.io)         │      │ (Streams + TLS)  │      │ (Fly.io)    │
│                  │      │                  │      │             │
│ Signal Generator │      │ signals:paper    │      │ REST + SSE  │
│ WebSocket Ingest │      │ signals:live     │      │ <500ms SLA  │
│ ML Ensemble      │      │ pnl:signals      │      │ Edge Runtime│
└──────────────────┘      └──────────────────┘      └─────────────┘
                                                            │
                                                            │
                                                            ▼
                                                    ┌─────────────┐
                                                    │signals-site │
                                                    │(Vercel)     │
                                                    │             │
                                                    │Next.js 15   │
                                                    │Edge Runtime │
                                                    │aipredict... │
                                                    └─────────────┘

Region: us-east-1 (Virginia) - All services co-located for <50ms latency
Health Checks: Every 15s across all services
Auto-scaling: 2-4 instances per service
Uptime SLA: 99.8% (max 87 minutes downtime/month)
```

---

## ⚙️ Prerequisites

### Required Accounts

1. **Fly.io** (crypto-ai-bot + signals-api)
   - Sign up: https://fly.io/signup
   - Install CLI: `curl -L https://fly.io/install.sh | sh`
   - Login: `fly auth login`

2. **Vercel** (signals-site)
   - Sign up: https://vercel.com/signup
   - Install CLI: `npm install -g vercel`
   - Login: `vercel login`

3. **Redis Cloud** (Shared across all)
   - Already configured: `redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818`
   - TLS Required: rediss://
   - CA Certificate: `config/certs/redis_ca.pem`

4. **GitHub** (CI/CD)
   - Repositories:
     - `crypto_ai_bot`
     - `signals_api`
     - `signals-site`

### Required Tools

```bash
# Fly.io CLI
curl -L https://fly.io/install.sh | sh

# Vercel CLI
npm install -g vercel

# GitHub CLI (optional)
brew install gh  # or: apt install gh

# Redis CLI (testing)
apt install redis-tools  # or: brew install redis
```

---

## 🔧 Unified Configuration

### Shared Redis Cloud Connection

**All three repositories use the same Redis Cloud instance:**

```bash
# Redis URL (same for all repos)
REDIS_URL=rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818

# Redis SSL Configuration
REDIS_SSL=true
REDIS_TLS_CERT_PATH=config/certs/redis_ca.pem

# Test connection
redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 --tls --cacert config/certs/redis_ca.pem PING
# Expected: PONG
```

### Shared Stream Names

All services publish/consume from these streams:

| Stream | Purpose | Publisher | Consumer |
|--------|---------|-----------|----------|
| `signals:paper` | Paper trading signals | crypto-ai-bot | signals-api, signals-site |
| `signals:live` | Live trading signals | crypto-ai-bot | signals-api, signals-site |
| `pnl:signals` | PnL updates | crypto-ai-bot | signals-api, signals-site |
| `events:bus` | System events | All | All |

### Trading Pairs (Consistent Across All)

```bash
# All repos must use these 5 pairs (matching live site)
TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD
```

### API Base URL

```bash
# signals-site and signals-api must use this
NEXT_PUBLIC_API_BASE=https://signals-api-gateway.fly.dev
```

---

## 📂 Repository Setup

### 1. crypto-ai-bot (Signal Generation Engine)

```bash
cd crypto_ai_bot

# Create Fly.io app
fly apps create crypto-ai-bot --org personal

# Set secrets
fly secrets set \
  REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818" \
  KRAKEN_API_KEY="<KRAKEN_API_KEY>" \
  KRAKEN_API_SECRET="<KRAKEN_API_SECRET>" \
  OPENAI_API_KEY="<OPENAI_API_KEY>" \
  --app crypto-ai-bot

# Deploy
fly deploy --config fly.toml --dockerfile Dockerfile.production

# Verify
fly status --app crypto-ai-bot
fly logs --app crypto-ai-bot
curl https://crypto-ai-bot.fly.dev/health
```

### 2. signals-api (API Backend)

```bash
cd signals_api

# Create Fly.io app
fly apps create crypto-signals-api --org personal

# Set secrets
fly secrets set \
  REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818" \
  SUPABASE_URL="<SUPABASE_URL>" \
  SUPABASE_SERVICE_ROLE_KEY="<SUPABASE_SERVICE_ROLE_KEY>" \
  STRIPE_SECRET_KEY="<STRIPE_SECRET_KEY>" \
  STRIPE_WEBHOOK_SECRET="<STRIPE_WEBHOOK_SECRET>" \
  --app crypto-signals-api

# Deploy
fly deploy --config fly.toml --dockerfile Dockerfile.production

# Verify
fly status --app crypto-signals-api
curl https://signals-api-gateway.fly.dev/health
curl https://signals-api-gateway.fly.dev/v1/signals/latest
```

### 3. signals-site (Frontend)

```bash
cd signals-site

# Link to Vercel project
vercel link

# Set environment variables
vercel env add NEXT_PUBLIC_API_BASE production
# Enter: https://signals-api-gateway.fly.dev

vercel env add REDIS_URL production
# Enter: rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818

vercel env add NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY production
# Enter: pk_live_...

vercel env add STRIPE_SECRET_KEY production
# Enter: sk_live_...

# Deploy
vercel --prod

# Verify
curl https://aipredictedsignals.cloud
curl https://aipredictedsignals.cloud/api/health
```

---

## 🔐 Secrets Management

### Fly.io Secrets (crypto-ai-bot & signals-api)

```bash
# Set secrets for crypto-ai-bot
fly secrets set \
  REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818" \
  KRAKEN_API_KEY="<KRAKEN_API_KEY>" \
  KRAKEN_API_SECRET="<KRAKEN_API_SECRET>" \
  OPENAI_API_KEY="..." \
  --app crypto-ai-bot

# Set secrets for signals-api
fly secrets set \
  REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818" \
  SUPABASE_URL="..." \
  SUPABASE_SERVICE_ROLE_KEY="..." \
  STRIPE_SECRET_KEY="..." \
  STRIPE_WEBHOOK_SECRET="..." \
  --app crypto-signals-api

# List secrets (values hidden)
fly secrets list --app crypto-ai-bot
fly secrets list --app crypto-signals-api
```

### Vercel Environment Variables (signals-site)

```bash
# Required production variables
vercel env add NEXT_PUBLIC_API_BASE production
vercel env add REDIS_URL production
vercel env add NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY production
vercel env add STRIPE_SECRET_KEY production
vercel env add NEXTAUTH_SECRET production
vercel env add NEXT_PUBLIC_SUPABASE_URL production
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production

# List all variables
vercel env ls
```

### GitHub Secrets (CI/CD)

**Required for all 3 repositories:**

1. **FLY_API_TOKEN** (for crypto-ai-bot & signals-api)
   ```bash
   # Generate token
   fly tokens create deploy --expiry 999999h

   # Add to GitHub secrets
   gh secret set FLY_API_TOKEN --body "FlyV1 ..."
   ```

2. **VERCEL_TOKEN** (for signals-site)
   ```bash
   # Generate at: https://vercel.com/account/tokens
   gh secret set VERCEL_TOKEN --body "..."
   gh secret set VERCEL_ORG_ID --body "..."
   gh secret set VERCEL_PROJECT_ID --body "..."
   ```

3. **Notification Secrets** (optional)
   ```bash
   gh secret set SLACK_WEBHOOK_URL --body "https://hooks.slack.com/..."
   gh secret set DISCORD_WEBHOOK_URL --body "https://discord.com/api/webhooks/..."
   ```

---

## 🚀 Deployment

### Automated Deployment (Recommended)

**All repositories have GitHub Actions workflows:**

1. **Push to `main`** → Deploy to production
2. **Push to `staging`** → Deploy to staging
3. **Create tag `v*.*.*`** → Deploy to production with versioning
4. **Pull request** → Deploy preview (signals-site only)

**Example workflow:**

```bash
# Create feature branch
git checkout -b feature/new-ml-model

# Make changes and commit
git add .
git commit -m "feat: add new LSTM model"

# Push and create PR
git push origin feature/new-ml-model
# GitHub Actions runs tests automatically

# Merge to main → automatic production deployment
gh pr merge --squash
```

### Manual Deployment

#### crypto-ai-bot

```bash
cd crypto_ai_bot

# Deploy to production
fly deploy --config fly.toml --dockerfile Dockerfile.production

# Monitor deployment
fly logs --app crypto-ai-bot

# Health check
curl https://crypto-ai-bot.fly.dev/health
```

#### signals-api

```bash
cd signals_api

# Deploy to production
fly deploy --config fly.toml --dockerfile Dockerfile.production

# Monitor deployment
fly logs --app crypto-signals-api

# Health checks
curl https://signals-api-gateway.fly.dev/health
curl https://signals-api-gateway.fly.dev/livez
curl https://signals-api-gateway.fly.dev/readyz
```

#### signals-site

```bash
cd signals-site

# Deploy to production
vercel --prod

# Verify deployment
curl https://aipredictedsignals.cloud
```

---

## 📊 Monitoring & Alerting

### Health Check Endpoints

**crypto-ai-bot:**
- Health: `https://crypto-ai-bot.fly.dev/health`
- Metrics: `https://crypto-ai-bot.fly.dev/metrics`
- Liveness: `https://crypto-ai-bot.fly.dev/liveness`

**signals-api:**
- Health: `https://signals-api-gateway.fly.dev/health`
- Liveness: `https://signals-api-gateway.fly.dev/livez`
- Readiness: `https://signals-api-gateway.fly.dev/readyz`
- Metrics: `https://signals-api-gateway.fly.dev/metrics`

**signals-site:**
- API Health (proxy): `https://aipredictedsignals.cloud/api/health`

### Fly.io Built-in Monitoring

```bash
# View logs
fly logs --app crypto-ai-bot
fly logs --app crypto-signals-api

# View metrics
fly dashboard crypto-ai-bot
fly dashboard crypto-signals-api

# Check status
fly status --app crypto-ai-bot
fly status --app crypto-signals-api

# View machines
fly machine list --app crypto-ai-bot
fly machine list --app crypto-signals-api
```

### Vercel Built-in Monitoring

Access at:
- Analytics: https://vercel.com/[your-team]/signals-site/analytics
- Logs: https://vercel.com/[your-team]/signals-site/logs
- Speed Insights: https://vercel.com/[your-team]/signals-site/speed-insights

### Redis Cloud Monitoring

Access at: https://app.redislabs.com/

**Monitor:**
- Connection count
- Memory usage
- Stream lengths
- Latency

**Alerts:**
- Memory > 80%
- Connections > 25
- Latency > 100ms

### Custom Monitoring Script

```bash
# Monitor all services
#!/bin/bash

echo "=== Health Check ==="

# crypto-ai-bot
echo -n "crypto-ai-bot: "
curl -sf https://crypto-ai-bot.fly.dev/health && echo "✅" || echo "❌"

# signals-api
echo -n "signals-api: "
curl -sf https://signals-api-gateway.fly.dev/health && echo "✅" || echo "❌"

# signals-site
echo -n "signals-site: "
curl -sf https://aipredictedsignals.cloud && echo "✅" || echo "❌"

# Redis
echo -n "Redis: "
redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 --tls --cacert config/certs/redis_ca.pem PING && echo "✅" || echo "❌"
```

---

## 🔧 Troubleshooting

### crypto-ai-bot Issues

**Problem: WebSocket disconnecting**

```bash
# Check logs
fly logs --app crypto-ai-bot | grep -i websocket

# Check health
curl https://crypto-ai-bot.fly.dev/health

# Restart if needed
fly machine restart --app crypto-ai-bot
```

**Problem: Redis connection errors**

```bash
# Verify Redis secret
fly secrets list --app crypto-ai-bot

# Test Redis connection from machine
fly ssh console --app crypto-ai-bot
redis-cli -u $REDIS_URL PING
```

### signals-api Issues

**Problem: SSE connections timing out**

```bash
# Check SSE configuration
fly logs --app crypto-signals-api | grep -i sse

# Test SSE endpoint
curl -N https://signals-api-gateway.fly.dev/v1/signals/sse

# Check idle_timeout in fly.toml (should be 300s)
```

**Problem: High latency (>500ms)**

```bash
# Check metrics
curl https://signals-api-gateway.fly.dev/metrics | grep latency

# Scale up if needed
fly scale count 4 --app crypto-signals-api
```

### signals-site Issues

**Problem: API calls failing**

```bash
# Check NEXT_PUBLIC_API_BASE
vercel env ls

# Test API proxy
curl https://aipredictedsignals.cloud/api/health

# Check Vercel logs
vercel logs signals-site
```

**Problem: Slow page loads**

```bash
# Run Lighthouse audit
npx lighthouse https://aipredictedsignals.cloud --view

# Check Vercel Speed Insights
# Visit: https://vercel.com/[team]/signals-site/speed-insights
```

### Redis Cloud Issues

**Problem: Connection refused**

```bash
# Test connection with correct password encoding
redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 --tls --cacert config/certs/redis_ca.pem PING

# Check Redis Cloud dashboard
# Visit: https://app.redislabs.com/
```

---

## ✅ SLA Compliance

### 99.8% Uptime Guarantee

**Maximum allowed downtime:** 87 minutes/month

**Achieved through:**
1. **Multi-instance deployment:** 2-4 instances per service
2. **Health checks every 15s:** Auto-restart on failure
3. **Rolling deployments:** Zero-downtime updates
4. **Auto-rollback:** Failed deployments trigger automatic rollback
5. **Regional co-location:** All services in us-east-1 for low latency

### <500ms Latency Guarantee

**Target:** P95 latency < 500ms

**Achieved through:**
1. **Regional co-location:** All services + Redis in us-east-1
2. **Vercel Edge Runtime:** CDN-cached responses
3. **Redis pipelining:** Batch operations
4. **Efficient data structures:** Streams for O(1) reads
5. **Connection pooling:** Reuse connections

**Monitoring:**

```bash
# Test API latency
for i in {1..100}; do
  start=$(date +%s%3N)
  curl -s https://signals-api-gateway.fly.dev/v1/signals/latest > /dev/null
  end=$(date +%s%3N)
  echo "$((end - start))ms"
done | sort -n | awk 'NR==95{print "P95: " $0}'
```

---

## 📞 Support

**Issues:** Open GitHub issue in respective repository
**Monitoring:** Fly.io dashboard + Vercel dashboard
**Alerts:** Discord/Slack webhooks configured in GitHub Actions

---

**Last Updated:** 2025-11-17
**Maintainer:** DevOps Team
**SLA:** 99.8% uptime | <500ms latency
