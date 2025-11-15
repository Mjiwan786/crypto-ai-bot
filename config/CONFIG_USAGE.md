# Configuration System Usage Guide

**Single Unified Configuration Loader with Strict Precedence**

This guide helps you configure dev/staging/prod in <5 minutes.

## Table of Contents
1. [Precedence Rules](#precedence-rules)
2. [Environment Variables Mapping](#environment-variables-mapping)
3. [Quick Start Examples](#quick-start-examples)
4. [YAML Configuration](#yaml-configuration)
5. [Stream Registry](#stream-registry)
6. [Redis TLS Setup](#redis-tls-setup)

---

## Precedence Rules

Configuration is loaded with **strict precedence** (highest to lowest):

```
overrides > ENV variables > YAML (left→right) > defaults
```

**Examples**:
```python
# Precedence in action:
# 1. Defaults: PAPER mode
# 2. YAML sets: mode=LIVE
# 3. ENV sets: TRADING_MODE=PAPER  → PAPER (ENV wins over YAML)
# 4. Override sets: {"trading_mode": {"mode": "LIVE"}}  → LIVE (Override wins)
```

---

## Environment Variables Mapping

All ENV variables and their mapping to settings:

| Environment Variable | Settings Path | Type | Description |
|---------------------|---------------|------|-------------|
| **Redis** |  |  |  |
| `REDIS_URL` | `redis.url` | str | Redis connection URL (redis:// or rediss://) |
| `REDIS_TLS` | `redis.tls` | bool | Enable TLS (auto-detected from rediss://) |
| `REDIS_CA_CERT` | `redis.ca_cert_path` | str | Path to CA certificate |
| `REDIS_MAX_CONNECTIONS` | `redis.max_connections` | int | Max connection pool size |
| **Kraken** |  |  |  |
| `KRAKEN_API_KEY` | `kraken.api_key` | str | Kraken API key |
| `KRAKEN_API_SECRET` | `kraken.api_secret` | str | Kraken API secret |
| `KRAKEN_SANDBOX` | `kraken.sandbox` | bool | Use sandbox (true/false) |
| `KRAKEN_RATE_LIMIT_CALLS` | `kraken.rate_limit_calls` | int | Rate limit calls per window |
| **Trading Mode** |  |  |  |
| `TRADING_MODE` | `trading_mode.mode` | str | **PAPER** or **LIVE** |
| `LIVE_CONFIRMATION` | `trading_mode.live_confirmation` | str | **Required for LIVE mode** |
| **Streams** |  |  |  |
| `STREAM_PREFIX` | `streams.prefix` | str | Stream name prefix |
| `SIGNALS_PAPER_STREAM` | `streams.signals_paper` | str | Paper signals stream |
| `SIGNALS_LIVE_STREAM` | `streams.signals_live` | str | Live signals stream |
| **Logging** |  |  |  |
| `LOG_LEVEL` | `logging.level` | str | DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `LOG_FORMAT` | `logging.format` | str | Python logging format string |
| **Trading** |  |  |  |
| `TRADING_PAIRS` | `trading.pairs` | list | Comma-separated pairs (e.g., BTCUSDT,ETHUSDT) |
| `POSITION_SIZE_PCT` | `trading.position_size_pct` | Decimal | Position size 0.0-1.0 |
| `SL_MULTIPLIER` | `trading.sl_multiplier` | Decimal | Stop-loss multiplier |
| `TP_MULTIPLIER` | `trading.tp_multiplier` | Decimal | Take-profit multiplier |

---

## Quick Start Examples

### Development (.env file)

```bash
# config/.env.dev
TRADING_MODE=PAPER
REDIS_URL=redis://localhost:6379
KRAKEN_SANDBOX=true
LOG_LEVEL=DEBUG
TRADING_PAIRS=BTCUSDT,ETHUSDT
```

**Load in Python**:
```python
from pathlib import Path
from config.unified_config_loader import load_settings
from dotenv import load_dotenv

load_dotenv("config/.env.dev")
settings = load_settings()

print(f"Mode: {settings.trading_mode.mode}")  # PAPER
print(f"Redis: {settings.redis.url}")         # redis://localhost:6379
```

### Staging (ENV + YAML override)

```bash
# config/.env.staging
REDIS_URL=rediss://redis-staging.example.com:6379
KRAKEN_API_KEY=your-staging-key
KRAKEN_API_SECRET=your-staging-secret
KRAKEN_SANDBOX=true
TRADING_MODE=PAPER
LOG_LEVEL=INFO
```

```python
# Load staging config
from pathlib import Path
from config.unified_config_loader import load_with_overrides

settings = load_with_overrides(
    base_yaml=Path("config/settings.yaml"),
    overrides_yaml=Path("config/overrides/staging.yaml")
)
```

### Production (LIVE mode with confirmation)

```bash
# config/.env.prod
REDIS_URL=rediss://redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_CA_CERT=config/certs/redis-ca.crt
KRAKEN_API_KEY=your-prod-key
KRAKEN_API_SECRET=your-prod-secret
KRAKEN_SANDBOX=false
TRADING_MODE=LIVE
LIVE_CONFIRMATION=YES_I_WANT_LIVE_TRADING
LOG_LEVEL=WARNING
TRADING_PAIRS=BTCUSDT
```

⚠️ **LIVE MODE SAFETY GUARD**: You MUST set `LIVE_CONFIRMATION=YES_I_WANT_LIVE_TRADING` to enable live trading. This prevents accidental live trading.

```python
# Load production config
settings = load_with_overrides(
    base_yaml=Path("config/settings.yaml"),
    overrides_yaml=Path("config/overrides/prod.yaml")
)

# Will raise ValueError if LIVE_CONFIRMATION not set correctly
assert settings.trading_mode.mode == "LIVE"
```

---

## YAML Configuration

### settings.yaml (Base Configuration)

```yaml
# config/settings.yaml - Base settings with sensible defaults

redis:
  url: redis://localhost:6379
  tls: false
  max_connections: 10
  retry_on_timeout: true
  health_check_interval: 30

kraken:
  sandbox: true
  rate_limit_calls: 15
  rate_limit_window_s: 3

trading_mode:
  mode: PAPER

streams:
  prefix: crypto
  signals_paper: signals:paper
  signals_live: signals:live
  metrics_latency: metrics:latency
  status_health: status:health

logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

trading:
  pairs:
    - BTCUSDT
  position_size_pct: 0.5
  sl_multiplier: 1.5
  tp_multiplier: 2.0
  max_concurrent: 2
```

### overrides/staging.yaml

```yaml
# config/overrides/staging.yaml - Staging-specific overrides

redis:
  url: rediss://redis-staging.example.com:6379
  tls: true
  ca_cert_path: config/certs/redis-ca.crt

kraken:
  sandbox: true

logging:
  level: INFO

trading:
  pairs:
    - BTCUSDT
    - ETHUSDT
```

### overrides/prod.yaml

```yaml
# config/overrides/prod.yaml - Production-specific overrides

redis:
  url: rediss://redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
  tls: true
  ca_cert_path: config/certs/redis-ca.crt
  max_connections: 20

kraken:
  sandbox: false
  rate_limit_calls: 10

trading_mode:
  mode: LIVE
  live_confirmation: YES_I_WANT_LIVE_TRADING

logging:
  level: WARNING

trading:
  pairs:
    - BTCUSDT
  position_size_pct: 0.3
  sl_multiplier: 1.2
  tp_multiplier: 1.8
  max_concurrent: 1
```

---

## Stream Registry

Canonical stream keys and payload schemas are defined in `streams_schema.py`.

### Stream Names

| Stream | Purpose | Payload Schema |
|--------|---------|---------------|
| `signals:paper` | Paper trading signals | `SignalPayload` |
| `signals:live` | Live trading signals | `SignalPayload` |
| `metrics:latency` | Latency metrics (p50/p95/p99) | `LatencyMetricsPayload` |
| `status:health` | System health checks | `HealthStatusPayload` |

### Publishing Signals (Example)

```python
from config.streams_schema import validate_signal_payload
from decimal import Decimal

# Create signal payload
signal_data = {
    "id": "abc123",
    "ts": 1234567890000,
    "pair": "BTCUSDT",
    "side": "long",
    "entry": Decimal("50000.0"),
    "sl": Decimal("49000.0"),
    "tp": Decimal("52000.0"),
    "strategy": "momentum",
    "confidence": 0.85,
}

# Validate before publishing
signal = validate_signal_payload(signal_data)

# Publish to Redis (via orchestrator)
# orchestrator.redis.publish_signal("signals:paper", signal.model_dump())
```

**Validation Guarantees**:
- ✅ SL/TP prices consistent with trade direction (long/short)
- ✅ All required fields present
- ✅ Type safety (Decimal for prices, float for confidence)
- ✅ Raises `ValidationError` for bad payloads

---

## Redis TLS Setup

### Using Redis Cloud with TLS

**Connection URL Format**:
```
rediss://default:PASSWORD@HOST:PORT
```

Example:
```
rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

### CA Certificate

If your Redis Cloud instance requires a CA certificate:

1. Download CA certificate from Redis Cloud dashboard
2. Save to `config/certs/redis-ca.crt`
3. Set environment variable:
   ```bash
   REDIS_CA_CERT=config/certs/redis-ca.crt
   ```

### Testing Connection

```bash
# Test Redis connection with redis-cli
redis-cli -u rediss://default:PASSWORD@HOST:PORT --tls --cacert config/certs/redis-ca.crt

# Should see:
# HOST:PORT>
```

### Python Connection (via Orchestrator)

```python
from orchestration import MasterOrchestrator, OrchestratorConfig

config = OrchestratorConfig(
    redis_url="rediss://default:PASSWORD@HOST:PORT",
    redis_tls=True,
    redis_ca_cert="config/certs/redis-ca.crt",
)

orchestrator = MasterOrchestrator(config)
await orchestrator.initialize()  # Connects to Redis with TLS
```

---

## Type Coercion

Environment variables are automatically coerced to the correct type:

| Type | ENV Examples | Coerced Value |
|------|-------------|---------------|
| `bool` | "true", "1", "yes", "on" | `True` |
|  | "false", "0", "no", "off" | `False` |
| `int` | "10", "100" | `10`, `100` |
| `Decimal` | "0.5", "1.25" | `Decimal("0.5")` |
| `list` | "BTCUSDT,ETHUSDT,SOL USDT" | `["BTCUSDT", "ETHUSDT", "SOLUSDT"]` |

---

## Migration from Old Loaders

**Deprecated loaders** (C2 requirement):
- `config/loader.py` → Use `unified_config_loader.py`
- `config/optimized_config_loader.py` → Use `unified_config_loader.py`
- `config/config_loader.py` → Use `unified_config_loader.py`

**Migration**:
```python
# OLD
from config.loader import load_config
config = load_config("settings.yaml")

# NEW
from config.unified_config_loader import load_from_yaml
from pathlib import Path
settings = load_from_yaml(Path("config/settings.yaml"))
```

---

## Summary

✅ **One canonical loader**: `unified_config_loader.py`
✅ **Strict precedence**: overrides > ENV > YAML (left→right) > defaults
✅ **Type safety**: Pydantic v2 schemas with validation
✅ **LIVE mode guard**: Requires explicit confirmation
✅ **Stream schemas**: Validated payloads with `ValidationError` on bad data
✅ **Redis TLS**: Auto-detected from `rediss://` URLs

**Configure in <5 minutes**: Copy `.env` example, update credentials, load settings.

For questions, see `config/unified_config_loader.py` docstrings or run self-checks:
```bash
python config/unified_config_loader.py
python config/streams_schema.py
```
