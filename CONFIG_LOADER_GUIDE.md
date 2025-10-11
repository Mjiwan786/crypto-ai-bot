# Configuration Loader Guide

## Overview

The new configuration system uses Pydantic v2 models with support for:
- Environment variable loading
- YAML file configuration
- Precedence: CLI/ENV > YAML > defaults
- Validation for trading modes and live trading confirmation
- Redis TLS connection support

## Quick Start

### Basic Usage

```python
from agents.config.config_loader import load_agent_settings

# Load from environment variables (uses os.environ)
settings = load_agent_settings()

# Access settings
print(settings.mode)  # "paper" or "live"
print(settings.redis.url)
print(settings.kraken.api_key)
print(settings.risk.max_leverage)
```

### Load from YAML File

```python
from pathlib import Path
from agents.config.config_loader import load_agent_settings

# Load with YAML configuration
settings = load_agent_settings(file=Path("config.yaml"))
```

**Example config.yaml:**
```yaml
mode: paper
environment: prod
log_level: INFO

redis:
  url: rediss://redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
  ca_cert_path: /path/to/ca.crt
  socket_timeout: 10.0

kraken:
  api_url: https://api.kraken.com
  rate_limit_calls_per_second: 1.5

risk:
  max_position_size_usd: 5000.0
  max_daily_loss_usd: 250.0
  max_leverage: 2.0

scalper:
  enabled: true
  max_toxicity_score: 0.6
  target_profit_bps: 5.0
```

### Unit Testing

```python
from agents.config.config_loader import load_agent_settings, Settings, RedisSettings

# Method 1: Override via env dict
test_env = {
    "MODE": "paper",
    "REDIS_URL": "redis://testhost:6379",
    "KRAKEN_API_KEY": "test_key",
    "KRAKEN_API_SECRET": "test_secret",
}
settings = load_agent_settings(env=test_env)

# Method 2: Create Settings directly
settings = Settings(
    mode="paper",
    redis=RedisSettings(url="redis://testhost:6379"),
)

# Method 3: Modify after creation (Pydantic v2)
settings = load_agent_settings(env={"MODE": "paper"})
modified = settings.model_copy(update={"environment": "test"})
```

## Environment Variables

### Core Settings

- `MODE`: Trading mode (`paper` or `live`)
- `LIVE_TRADING_CONFIRMATION`: Must be `I-accept-the-risk` for live mode
- `ENVIRONMENT`: Environment name (`dev`, `staging`, `prod`)
- `LOG_LEVEL`: Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)

### Redis Settings

- `REDIS_URL`: Redis connection URL (use `rediss://` for TLS)
- `REDIS_CA_CERT_PATH`: Path to CA certificate for TLS
- `REDIS_CLIENT_CERT_PATH`: Path to client certificate for mTLS
- `REDIS_CLIENT_KEY_PATH`: Path to client key for mTLS
- `REDIS_SOCKET_TIMEOUT`: Socket operation timeout (seconds)
- `REDIS_SOCKET_CONNECT_TIMEOUT`: Socket connection timeout (seconds)
- `REDIS_MAX_CONNECTIONS`: Maximum connections in pool

### Kraken Settings

- `KRAKEN_API_KEY`: Kraken API key (**required for live mode**)
- `KRAKEN_API_SECRET`: Kraken API secret (**required for live mode**)
- `KRAKEN_API_URL`: Kraken API base URL
- `KRAKEN_API_VERSION`: Kraken API version
- `KRAKEN_RATE_LIMIT_CALLS_PER_SECOND`: API call rate limit
- `KRAKEN_RATE_LIMIT_BURST_SIZE`: Rate limiter burst size

### Risk Settings

- `RISK_MAX_POSITION_SIZE_USD`: Maximum position size in USD
- `RISK_MAX_DAILY_LOSS_USD`: Maximum daily loss in USD
- `RISK_MAX_DRAWDOWN_PERCENT`: Maximum drawdown percentage
- `RISK_MAX_LEVERAGE`: Maximum leverage (1.0-10.0)
- `RISK_POSITION_TIMEOUT_SECONDS`: Maximum time to hold position

### Scalper Settings

- `SCALPER_ENABLED`: Enable scalping (`true` or `false`)
- `SCALP_MAX_TOXICITY_SCORE`: Maximum toxicity score (0.0-1.0)
- `SCALP_MAX_ADVERSE_SELECTION_RISK`: Maximum adverse selection risk (0.0-1.0)
- `SCALP_MAX_MARKET_IMPACT_RISK`: Maximum market impact risk (0.0-1.0)
- `SCALP_COOLDOWN_AFTER_LOSS_SECONDS`: Cooldown after loss (seconds)
- `SCALP_MIN_SPREAD_BPS`: Minimum spread in basis points
- `SCALP_TARGET_PROFIT_BPS`: Target profit in basis points

## Redis TLS Connection

### Using to_redis_kwargs()

```python
from agents.config.config_loader import load_agent_settings
import redis.asyncio as redis

# Load settings with Redis TLS
settings = load_agent_settings(env={
    "REDIS_URL": "rediss://redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818",
    "REDIS_CA_CERT_PATH": "/path/to/ca.crt",
})

# Get Redis connection kwargs with TLS context
redis_kwargs = settings.redis.to_redis_kwargs()

# Create Redis client
client = redis.from_url(settings.redis.url, **redis_kwargs)
```

### Example with mTLS

```python
settings = load_agent_settings(env={
    "REDIS_URL": "rediss://secure.redis.com:6379",
    "REDIS_CA_CERT_PATH": "/path/to/ca.crt",
    "REDIS_CLIENT_CERT_PATH": "/path/to/client.crt",
    "REDIS_CLIENT_KEY_PATH": "/path/to/client.key",
})

redis_kwargs = settings.redis.to_redis_kwargs()
# This will include SSL context with client certificates
```

## Live Trading Validation

### Requirements

Live mode requires:
1. `MODE="live"`
2. `LIVE_TRADING_CONFIRMATION="I-accept-the-risk"`
3. `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` must be set

### Example

```python
# This will raise ValueError
settings = load_agent_settings(env={
    "MODE": "live",
    # Missing LIVE_TRADING_CONFIRMATION
})
# ValueError: Live trading requires LIVE_TRADING_CONFIRMATION='I-accept-the-risk'

# This will raise ValueError
settings = load_agent_settings(env={
    "MODE": "live",
    "LIVE_TRADING_CONFIRMATION": "I-accept-the-risk",
    # Missing Kraken credentials
})
# ValueError: Live trading requires Kraken API credentials

# This works
settings = load_agent_settings(env={
    "MODE": "live",
    "LIVE_TRADING_CONFIRMATION": "I-accept-the-risk",
    "KRAKEN_API_KEY": "your-api-key",
    "KRAKEN_API_SECRET": "your-api-secret",
})
```

## Precedence Rules

Configuration values are loaded in this order (later values override earlier ones):

1. **Defaults** (defined in Pydantic models)
2. **YAML file** (if provided)
3. **Environment variables**

### Example

```yaml
# config.yaml
redis:
  url: redis://yamlhost:6379
  socket_timeout: 10.0
```

```bash
# Environment
export REDIS_URL="redis://envhost:6379"
```

```python
settings = load_agent_settings(file=Path("config.yaml"))

# Results:
# - redis.url = "redis://envhost:6379" (from ENV, overrides YAML)
# - redis.socket_timeout = 10.0 (from YAML, no ENV override)
# - redis.decode_responses = False (default, not in YAML or ENV)
```

## Migration from Old Config

### Old Code

```python
from agents.config.config_loader import get_config

config = get_config()
value = config.get("SCALP_MAX_TOXICITY_SCORE", 0.6)
```

### New Code

```python
from agents.config.config_loader import load_agent_settings

settings = load_agent_settings()
value = settings.scalper.max_toxicity_score  # Type-safe!
```

### Legacy Compatibility

The old `get_config()` function still works for backward compatibility:

```python
from agents.config.config_loader import get_config

config = get_config()  # Returns SimpleConfig wrapper
value = config.get("SCALP_MAX_TOXICITY_SCORE")
```

## Validation

Pydantic automatically validates:

- Type correctness (strings, floats, ints, bools)
- Value ranges (e.g., leverage must be 1.0-10.0)
- Required fields
- Custom validation rules

### Examples

```python
# Invalid mode
settings = load_agent_settings(env={"MODE": "invalid"})
# ValidationError: mode must be 'paper' or 'live'

# Invalid leverage
settings = load_agent_settings(env={"RISK_MAX_LEVERAGE": "15"})
# ValidationError: max_leverage must be <= 10 for safety

# Invalid risk score
settings = load_agent_settings(env={"SCALP_MAX_TOXICITY_SCORE": "1.5"})
# ValidationError: Risk scores must be between 0 and 1
```

## Best Practices

1. **Use environment variables for secrets** (API keys, passwords)
2. **Use YAML for non-secret configuration** (URLs, timeouts, limits)
3. **Never commit secrets to version control**
4. **Always validate in production** (Pydantic does this automatically)
5. **Use type hints** (leverage Pydantic's type safety)

## Complete Example

```python
from pathlib import Path
from agents.config.config_loader import load_agent_settings
import redis.asyncio as redis

# Load configuration
settings = load_agent_settings(
    file=Path("config.yaml"),  # Base configuration
    # env will default to os.environ, which includes secrets
)

# Validate live trading
if settings.mode == "live":
    print("Live trading mode enabled!")
    print(f"Max position size: ${settings.risk.max_position_size_usd}")
    print(f"Max daily loss: ${settings.risk.max_daily_loss_usd}")

# Connect to Redis with TLS
redis_client = redis.from_url(
    settings.redis.url,
    **settings.redis.to_redis_kwargs()
)

# Use Kraken settings
print(f"Kraken API URL: {settings.kraken.api_url}")
print(f"Rate limit: {settings.kraken.rate_limit_calls_per_second} calls/sec")

# Access scalper settings
if settings.scalper.enabled:
    print(f"Scalping enabled with toxicity threshold: {settings.scalper.max_toxicity_score}")
```

## Testing

Run the test suite:

```bash
python test_config_loader.py
```

This validates:
- ✓ Basic imports
- ✓ Default settings
- ✓ Environment variable overrides
- ✓ YAML file loading
- ✓ Precedence rules (ENV > YAML > defaults)
- ✓ Live mode validation
- ✓ Redis TLS kwargs
- ✓ Unit test override capability
- ✓ Invalid input rejection
