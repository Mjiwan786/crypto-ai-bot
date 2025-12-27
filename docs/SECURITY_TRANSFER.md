# Security Transfer Guide

This document explains how to set up credentials and certificates after acquiring this codebase.

## Pre-Transfer Security State

The repository has been cleaned to ensure:
- No API keys, passwords, or secrets are committed
- No TLS certificates or private keys are tracked
- Only `.env.*.example` template files are included (not actual `.env` files)
- The `config/certs/` directory contains only placeholder documentation

## Post-Acquisition Setup

### 1. Environment Variables

Copy the appropriate example file and populate with your credentials:

```bash
# For development
cp .env.dev.example .env

# For paper trading
cp .env.paper.example .env

# For live trading
cp .env.live.example .env
```

Required environment variables (see example files for full list):
- `KRAKEN_API_KEY` - Your Kraken API key
- `KRAKEN_API_SECRET` - Your Kraken API secret
- `REDIS_URL` - Redis connection string (use `rediss://` for TLS)
- `REDIS_PASSWORD` - Redis password (if not in URL)

### 2. TLS Certificates

#### Redis TLS (Required for Redis Cloud)

1. Download your CA certificate from your Redis Cloud dashboard
2. Save to `config/certs/redis-ca.crt`
3. Set environment variable or config:
   ```bash
   export REDIS_CA_CERT="config/certs/redis-ca.crt"
   ```

See `config/certs/README.md` for detailed Redis TLS setup instructions.

#### Other Certificates

Place any additional TLS certificates in `config/certs/`:
- Files matching `*.pem`, `*.key`, `*.crt`, `*.p12` are git-ignored
- Only `README.md` and `__init__.py` are tracked

### 3. API Keys

#### Kraken API

1. Log into Kraken
2. Navigate to Settings > API
3. Create a new API key with required permissions:
   - Query Funds
   - Query Open Orders & Trades
   - Query Closed Orders & Trades
   - Create & Modify Orders (for live trading)
4. Add to your `.env` file

#### Other Exchanges (if applicable)

Follow similar process for any additional exchange APIs.

### 4. Verification Checklist

Before running in production:

- [ ] `.env` file created and populated (not committed)
- [ ] Redis TLS certificate in place (if using Redis Cloud)
- [ ] API keys have correct permissions
- [ ] Test connection with paper trading mode first
- [ ] Run `python -m pytest tests/` to verify setup
- [ ] Check `git status` confirms no secrets are staged

### 5. Security Best Practices

- Never commit `.env` files or certificates
- Use separate API keys for development/paper/live
- Restrict API key permissions to minimum required
- Rotate credentials periodically
- Monitor API key usage in exchange dashboards

## Files to Create (Not Included)

| File | Purpose |
|------|---------|
| `.env` | Active environment configuration |
| `config/certs/redis-ca.crt` | Redis Cloud CA certificate |
| `config/certs/*.pem` | Any additional certificates |

## Support

For questions about credential setup, refer to:
- `config/certs/README.md` - Redis TLS details
- `.env.*.example` files - Required environment variables
- Exchange API documentation for key setup
