# Environment Matrix

This document describes environment configurations for PAPER and LIVE trading modes.

## Trading Modes

| Mode | Description | Risk Level | Use Case |
|------|-------------|------------|----------|
| **PAPER** | Simulated trading, no real orders | None | Development, testing, validation |
| **LIVE** | Real trading with actual funds | High | Production trading |

## Required Environment Variables

These variables MUST be set for the system to function:

| Variable | Description | Required For |
|----------|-------------|--------------|
| `KRAKEN_API_KEY` | Kraken API key | All modes |
| `KRAKEN_API_SECRET` | Kraken API secret | All modes |
| `REDIS_URL` | Redis connection string | All modes |
| `TRADING_MODE` | `paper` or `live` | All modes |

### Live Trading Additional Requirements

| Variable | Description |
|----------|-------------|
| `LIVE_TRADING_CONFIRMATION` | Must be set to `I-accept-the-risk` |
| `REDIS_PASSWORD` | Redis password (if not in URL) |

## Optional Integrations

### Redis (Required for Production)

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_URL` | Connection string (`redis://` or `rediss://`) | `redis://localhost:6379` |
| `REDIS_PASSWORD` | Password (if not in URL) | None |
| `REDIS_CA_CERT` | Path to CA certificate for TLS | None |

**Certificate Path:** `config/certs/redis-ca.crt`

### Prometheus Monitoring

| Variable | Description | Default |
|----------|-------------|---------|
| `PROMETHEUS_ENABLED` | Enable metrics export | `true` |
| `PROMETHEUS_PORT` | Metrics port | `9090` |
| `METRICS_PREFIX` | Metric name prefix | `crypto_bot` |

### OpenAI Integration

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key for AI features | None |
| `OPENAI_MODEL` | Model to use | `gpt-4` |

### Discord Alerting

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_WEBHOOK_URL` | Webhook for alerts | None |
| `DISCORD_ALERT_LEVEL` | Minimum alert level | `WARNING` |

## Environment Files

| File | Purpose |
|------|---------|
| `.env.dev.example` | Development template |
| `.env.paper.example` | Paper trading template |
| `.env.live.example` | Live trading template |
| `.env.local.example` | Local development template |
| `.env.prod.example` | Production template |

**Usage:**
```bash
# Copy appropriate template
cp .env.paper.example .env

# Edit with your credentials
nano .env
```

## Certificate Paths

| Certificate | Path | Purpose |
|-------------|------|---------|
| Redis CA | `config/certs/redis-ca.crt` | Redis Cloud TLS |
| Custom certs | `config/certs/*.pem` | Additional TLS certs |

**Note:** All certificate files are git-ignored. See `docs/SECURITY_TRANSFER.md` for setup instructions.

## Environment Comparison

| Setting | DEV | PAPER | LIVE |
|---------|-----|-------|------|
| Trading Mode | paper | paper | live |
| Redis | Local | Cloud TLS | Cloud TLS |
| Position Limit | 0.5% | 2% | 5% |
| Max Daily Loss | 1% | 2% | 5% |
| Logging Level | DEBUG | INFO | WARNING |
| Prometheus | Optional | Enabled | Enabled |
| Discord Alerts | Disabled | Optional | Required |

## Validation

Run preflight checks before starting:

```bash
# Validate environment
python scripts/preflight_check.py

# Expected output:
# [OK] KRAKEN_API_KEY set
# [OK] REDIS_URL valid
# [OK] Trading mode: paper
# [OK] All checks passed
```
