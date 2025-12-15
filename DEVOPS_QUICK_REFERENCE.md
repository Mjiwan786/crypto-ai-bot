# DevOps Quick Reference Card

## 🚨 Emergency Contacts

| Service | Health Check | Logs | Restart |
|---------|-------------|------|---------|
| crypto-ai-bot | `curl https://crypto-ai-bot.fly.dev/health` | `fly logs --app crypto-ai-bot` | `fly machine restart --app crypto-ai-bot` |
| signals-api | `curl https://signals-api-gateway.fly.dev/health` | `fly logs --app crypto-signals-api` | `fly machine restart --app crypto-signals-api` |
| signals-site | `curl https://aipredictedsignals.cloud` | `vercel logs signals-site` | `vercel rollback` |
| Redis Cloud | `redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 --tls --cacert config/certs/redis_ca.pem PING` | https://app.redislabs.com/ | N/A (Managed) |

## 🔑 Secrets

```bash
# Fly.io
fly secrets list --app crypto-ai-bot
fly secrets list --app crypto-signals-api

# Vercel
vercel env ls

# GitHub
gh secret list
```

## 🚀 Deploy Commands

```bash
# crypto-ai-bot
fly deploy --app crypto-ai-bot

# signals-api
fly deploy --app crypto-signals-api

# signals-site
vercel --prod

# Rollback
fly releases rollback --app <app-name>
vercel rollback
```

## 📊 Monitoring URLs

- Fly.io Dashboard: https://fly.io/dashboard
- Vercel Dashboard: https://vercel.com/dashboard
- Redis Cloud: https://app.redislabs.com/
- Metrics: https://crypto-ai-bot.fly.dev/metrics

## 🔧 Common Issues

### Service Down
```bash
fly status --app crypto-ai-bot
fly logs --app crypto-ai-bot | tail -100
fly machine restart --app crypto-ai-bot
```

### High Latency
```bash
# Check metrics
curl https://signals-api-gateway.fly.dev/metrics | grep latency

# Scale up
fly scale count 4 --app crypto-signals-api
```

### Redis Issues
```bash
# Test connection
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem PING

# Check stream lengths
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XLEN signals:paper
```

## 📞 Escalation

1. Check health endpoints
2. Review logs
3. Check recent deployments
4. Scale if under load
5. Rollback if recent deploy
6. Contact on-call if unresolved after 15 min

## 🎯 SLA Targets

- **Uptime:** 99.8% (87 min downtime/month max)
- **Latency:** P95 < 500ms
- **Health Checks:** Every 15s
- **Auto-restart:** After 3 failures
