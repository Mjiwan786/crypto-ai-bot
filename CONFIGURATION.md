# Crypto AI Bot - Configuration Reference

Complete environment variable reference for all deployment modes.

**PRD Reference**: [PRD-001: Crypto AI Bot - Core Intelligence Engine](docs/PRD-001-CRYPTO-AI-BOT.md)

---

## Table of Contents

1. [Critical Configuration (Required)](#critical-configuration-required)
2. [Optional Configuration](#optional-configuration)
3. [Environment-Specific Examples](#environment-specific-examples)
4. [Validation & Fail-Fast](#validation--fail-fast)
5. [Security Best Practices](#security-best-practices)

---

## Critical Configuration (Required)

These variables **MUST** be set for the system to start.

### Redis Cloud (TLS Required)

| Variable | Purpose | Example | Validation |
|----------|---------|---------|------------|
| `REDIS_URL` | Redis connection string with TLS | `rediss://default:PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818` | Must start with `redis://` or `rediss://`. TLS (`rediss://`) enforced in staging/prod. |
| `REDIS_TLS` | Enable TLS encryption | `true` (auto-detected from `rediss://`) | Boolean. Auto-set to `true` if URL starts with `rediss://`. |
| `REDIS_CA_CERT` | Path to CA certificate | `config/certs/redis_ca.pem` | File must exist if provided. Required for production TLS verification. |

**Fail-Fast**: System refuses to start if `REDIS_URL` is missing or invalid.

### Kraken API

| Variable | Purpose | Example | Validation |
|----------|---------|---------|------------|
| `KRAKEN_API_KEY` | Kraken API key | `(from kraken.com/u/settings/api)` | Min 20 characters. Required for live trading. |
| `KRAKEN_API_SECRET` | Kraken API secret | `(from kraken.com/u/settings/api)` | Min 20 characters. Required for live trading. |
| `KRAKEN_SANDBOX` | Use Kraken sandbox | `true` (dev/staging), `false` (prod) | Boolean. Prevents accidental live trading in dev. |

**Fail-Fast**: LIVE mode requires valid Kraken credentials (validated on startup).

### Trading Mode & Safety Guards

| Variable | Purpose | Example | Validation |
|----------|---------|---------|------------|
| `TRADING_MODE` | Trading execution mode | `PAPER` or `LIVE` | Must be exactly `PAPER` or `LIVE` (case-insensitive). Default: `PAPER`. |
| `LIVE_CONFIRMATION` | Required confirmation for LIVE mode | `YES_I_WANT_LIVE_TRADING` | LIVE mode **WILL FAIL** unless this exact string is set. Safety guard against accidental live trading. |

**Fail-Fast**:
- LIVE mode without `LIVE_CONFIRMATION="YES_I_WANT_LIVE_TRADING"` → **Hard error, system exits**
- Missing `KRAKEN_API_KEY` or `KRAKEN_API_SECRET` in LIVE mode → **Hard error**

---

## Optional Configuration

These variables have sensible defaults but can be overridden.

### Logging

| Variable | Purpose | Default | Options |
|----------|---------|---------|---------|
| `LOG_LEVEL` | Logging verbosity | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_FORMAT` | Log output format | `json` | `json` (structured), `text` (human-readable) |

### Stream Names

| Variable | Purpose | Default |
|----------|---------|---------|
| `STREAM_PREFIX` | Redis stream prefix | `crypto` |
| `SIGNALS_PAPER_STREAM` | Paper trading signals stream | `signals:paper` |
| `SIGNALS_LIVE_STREAM` | Live trading signals stream | `signals:live` |
| `METRICS_LATENCY_STREAM` | Latency metrics stream | `metrics:latency` |
| `STATUS_HEALTH_STREAM` | Health status stream | `status:health` |

### Trading Parameters

| Variable | Purpose | Default | Range |
|----------|---------|---------|-------|
| `TRADING_PAIRS` | Comma-separated trading pairs | `BTCUSDT` | CSV: `BTCUSDT,ETHUSDT` |
| `POSITION_SIZE_PCT` | Position size as % of capital | `0.5` | `0.0` to `1.0` |
| `SL_MULTIPLIER` | Stop-loss ATR multiplier | `1.5` | `> 0.0` |
| `TP_MULTIPLIER` | Take-profit ATR multiplier | `2.0` | `> 0.0` |
| `MAX_CONCURRENT` | Max concurrent positions | `2` | `>= 1` |

### Redis Connection Tuning

| Variable | Purpose | Default |
|----------|---------|---------|
| `REDIS_MAX_CONNECTIONS` | Connection pool size | `10` |
| `REDIS_SOCKET_TIMEOUT` | Socket timeout (seconds) | `5` |
| `REDIS_SOCKET_CONNECT_TIMEOUT` | Connect timeout (seconds) | `3` |

---

## Environment-Specific Examples

### Development (.env.dev)

```bash
# Development - Local/Paper Trading
REDIS_URL=rediss://default:YOUR_PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_TLS=true
KRAKEN_SANDBOX=true
TRADING_MODE=PAPER
LOG_LEVEL=DEBUG
ENVIRONMENT=development
```

### Staging (.env.staging)

```bash
# Staging - Pre-Production Paper Trading
REDIS_URL=rediss://default:YOUR_PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_TLS=true
REDIS_CA_CERT=config/certs/redis_ca.pem
KRAKEN_SANDBOX=true
TRADING_MODE=PAPER
LOG_LEVEL=INFO
LOG_FORMAT=json
ENVIRONMENT=staging
```

### Production (.env.prod)

```bash
# Production - LIVE TRADING (REAL MONEY)
REDIS_URL=rediss://default:YOUR_PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_TLS=true
REDIS_CA_CERT=config/certs/redis_ca.pem
KRAKEN_API_KEY=YOUR_PRODUCTION_API_KEY
KRAKEN_API_SECRET=YOUR_PRODUCTION_API_SECRET
KRAKEN_SANDBOX=false
TRADING_MODE=LIVE
LIVE_CONFIRMATION=YES_I_WANT_LIVE_TRADING
LOG_LEVEL=INFO
LOG_FORMAT=json
ENVIRONMENT=production
```

---

## Validation & Fail-Fast

The system validates configuration on startup and **fails immediately** if critical requirements are not met.

### Startup Validation Sequence

1. **Environment Loading** (`config/unified_config_loader.py`)
   - Load `.env` file
   - Apply environment variables
   - Merge with YAML configs (if provided)

2. **Schema Validation** (Pydantic models)
   - Type checking (bool/int/Decimal/list coercion)
   - Range validation (e.g., port 1-65535)
   - Format validation (e.g., Redis URL pattern)

3. **Business Logic Validation**
   - **LIVE Mode Guard**: Check `LIVE_CONFIRMATION` matches exactly
   - **TLS Enforcement**: Staging/prod must use `rediss://`
   - **Kraken Credentials**: Validate length and format in LIVE mode

4. **Runtime Checks** (`scripts/preflight.py`)
   - Redis connectivity test (with TLS)
   - Certificate file existence
   - Port availability
   - File permissions

### Fail-Fast Examples

```python
# Example 1: Missing REDIS_URL
❌ ConfigValidationError: REDIS_URL is required
   Status: NOT READY (exit code 1)

# Example 2: LIVE mode without confirmation
❌ ValueError: LIVE mode requires LIVE_CONFIRMATION='YES_I_WANT_LIVE_TRADING'
   Status: NOT READY (exit code 1)

# Example 3: Non-TLS in production
❌ ValueError: REDIS_URL must use TLS (rediss://) in production environment
   Status: NOT READY (exit code 1)

# Example 4: Invalid Kraken credentials
❌ ValidationError: KRAKEN_API_KEY too short (must be >= 20 characters)
   Status: NOT READY (exit code 1)
```

### Validation Commands

```powershell
# Dry-run validation (no trading, only config check)
python scripts/start_trading_system.py --mode paper --dry-run

# Preflight checks (comprehensive validation)
python scripts/preflight.py

# Test Redis connectivity with TLS
python scripts/redis_cloud_smoke.py
```

---

## Security Best Practices

### ✅ DO

1. **Use `.env.*` files** for environment-specific configs
2. **Store secrets in environment variables**, never in code
3. **Use TLS (`rediss://`)** for all Redis connections (enforced in staging/prod)
4. **Rotate credentials regularly** (Kraken API keys, Redis passwords)
5. **Use Kraken sandbox** for development and testing
6. **Enable LIVE mode guard** (require explicit confirmation)
7. **Limit Kraken API permissions** (no withdrawals, only trading)
8. **Monitor logs** for failed authentication attempts
9. **Use different Redis databases** for dev/staging/prod (`/0`, `/1`, `/2`)
10. **Keep CA certificates** in version control (`config/certs/redis_ca.pem`)

### ❌ DON'T

1. **Never commit `.env`, `.env.dev`, `.env.staging`, `.env.prod`** (gitignored)
2. **Never hardcode passwords** in code (use `os.getenv()`)
3. **Never use plaintext Redis** (`redis://`) in staging/prod
4. **Never skip LIVE_CONFIRMATION** check (safety-critical)
5. **Never share Kraken API keys** between dev/prod
6. **Never disable TLS** for production Redis
7. **Never log sensitive values** (Redis passwords, API keys)
8. **Never bypass validation** (e.g., no `try/except` around config loading)

### Secret Masking in Logs

Secrets are automatically masked in logs:

```python
# Logger masks sensitive keys
logger.info(f"Redis URL: {redis_url}")
# Output: Redis URL: rediss://default:***...kn8@redis-19818...

# Kraken credentials never logged
logger.debug(f"Kraken config: api_key={kraken_config.api_key[:4]}...")
# Output: Kraken config: api_key=ab12...
```

---

## Configuration Precedence

Settings are merged in this order (highest to lowest priority):

1. **Overrides** (programmatic, e.g., test fixtures)
2. **Environment variables** (`REDIS_URL`, `TRADING_MODE`, etc.)
3. **YAML files** (`config/settings.yaml`, `config/overrides/*.yaml`)
4. **Pydantic defaults** (fallback values in schema)

Example:
```python
# YAML: redis.url = "redis://localhost:6379"
# ENV:  REDIS_URL = "rediss://production-host:6379"
# Result: rediss://production-host:6379 (ENV wins)
```

---

## Testing Configuration

### Unit Tests

```python
from config import load_settings

# Test default values
settings = load_settings()
assert settings.trading_mode.mode == "PAPER"

# Test environment override
settings = load_settings(env={"TRADING_MODE": "LIVE", "LIVE_CONFIRMATION": "YES_I_WANT_LIVE_TRADING"})
assert settings.trading_mode.mode == "LIVE"

# Test validation failure
try:
    load_settings(env={"TRADING_MODE": "LIVE"})  # Missing confirmation
    assert False, "Should have raised ValueError"
except ValueError as e:
    assert "YES_I_WANT_LIVE_TRADING" in str(e)
```

### Integration Tests

```powershell
# Test Redis connectivity
python scripts/redis_cloud_smoke.py

# Test full startup sequence
python scripts/start_trading_system.py --mode paper --dry-run

# Test preflight checks
python scripts/preflight.py
```

---

## Troubleshooting

### Redis Connection Failures

```
Error: redis.exceptions.ConnectionError
```

**Fix**:
1. Verify `REDIS_URL` format: `rediss://default:PASSWORD@HOST:PORT`
2. Check TLS is enabled: `REDIS_TLS=true`
3. Test manually:
   ```powershell
   redis-cli -u rediss://default:PASSWORD@HOST:PORT --tls --cacert config/certs/redis_ca.pem PING
   ```

### LIVE Mode Blocked

```
ValueError: LIVE mode requires LIVE_CONFIRMATION='YES_I_WANT_LIVE_TRADING'
```

**Fix**:
1. Set exact confirmation string:
   ```bash
   export LIVE_CONFIRMATION="YES_I_WANT_LIVE_TRADING"
   ```
2. Verify with dry-run:
   ```powershell
   python scripts/start_trading_system.py --mode live --dry-run
   ```

### Invalid Kraken Credentials

```
ValidationError: KRAKEN_API_KEY too short
```

**Fix**:
1. Generate new API key at kraken.com/u/settings/api
2. Ensure key permissions: `Query Funds`, `Create & Modify Orders` (no withdrawals!)
3. Set in `.env`:
   ```bash
   KRAKEN_API_KEY=your_long_api_key_here
   KRAKEN_API_SECRET=your_long_secret_here
   ```

---

## References

- **Unified Config Loader**: `config/unified_config_loader.py:258`
- **Preflight Script**: `scripts/preflight.py`
- **Startup Script**: `scripts/start_trading_system.py:84`
- **Redis Smoke Test**: `scripts/redis_cloud_smoke.py`
- **PRD**: [PRD-001: Crypto AI Bot - Core Intelligence Engine](docs/PRD-001-CRYPTO-AI-BOT.md)

---

## Support

For configuration questions or issues:

1. Check `SETUP.md` for environment recreation
2. Run `python scripts/preflight.py` for diagnostic checks
3. Review logs in `logs/trading_system_*.log`
4. Validate config with `--dry-run` flag

**Environment Variables Summary**: 20+ variables (8 critical, 12+ optional)
**Fail-Fast Enforcement**: 5 critical validations (Redis URL, TLS, LIVE confirmation, Kraken creds, environment match)
**Security**: TLS enforced, secrets masked, LIVE mode guarded
