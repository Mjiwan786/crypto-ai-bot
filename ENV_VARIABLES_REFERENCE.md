# Environment Variables Reference

**Quick reference for all tunable environment variables in crypto-ai-bot**

---

## Sub-Minute Bars & Scalping

### ENABLE_5S_BARS
- **Type**: Boolean
- **Default**: `false`
- **Values**: `true` | `false`
- **Description**: Enable 5-second synthetic bars (feature-gated for stability)
- **Usage**: Set to `true` only after 15s bars proven stable for 7+ days
- **Example**: `export ENABLE_5S_BARS=false`

### SCALPER_MAX_TRADES_PER_MINUTE
- **Type**: Integer
- **Default**: `4`
- **Range**: `1-60`
- **Description**: Maximum trades per minute for scalping agent
- **Usage**: Rate limiter for preventing over-trading
- **Tuning**:
  - Conservative: `3-4` trades/min
  - Moderate: `6-8` trades/min
  - Aggressive: `10-12` trades/min (not recommended)
- **Example**: `export SCALPER_MAX_TRADES_PER_MINUTE=4`
- **Related Config**: `config/enhanced_scalper_config.yaml:scalper.max_trades_per_minute`

---

## Redis Connection

### REDIS_URL
- **Type**: String (URL)
- **Default**: `redis://localhost:6379/0`
- **Description**: Redis connection URL (use `rediss://` for TLS)
- **Production**: `rediss://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
- **Example**: `export REDIS_URL="rediss://..."`

### REDIS_SSL
- **Type**: Boolean
- **Default**: `false`
- **Values**: `true` | `false`
- **Description**: Enable SSL/TLS for Redis connection
- **Production**: `true`
- **Example**: `export REDIS_SSL=true`

### REDIS_SSL_CA_CERT
- **Type**: String (Path)
- **Default**: None
- **Description**: Path to Redis CA certificate for TLS verification
- **Production**: `config/certs/redis_ca.pem`
- **Example**: `export REDIS_SSL_CA_CERT="config/certs/redis_ca.pem"`

### REDIS_CONNECTION_POOL_SIZE
- **Type**: Integer
- **Default**: `10`
- **Range**: `1-100`
- **Description**: Redis connection pool size
- **Tuning**:
  - Low traffic: `5-10`
  - Medium traffic: `10-20`
  - High traffic: `20-50`
- **Example**: `export REDIS_CONNECTION_POOL_SIZE=10`

### REDIS_SOCKET_TIMEOUT
- **Type**: Integer (seconds)
- **Default**: `10`
- **Range**: `5-120`
- **Description**: Redis socket timeout in seconds
- **Example**: `export REDIS_SOCKET_TIMEOUT=10`

---

## Kraken WebSocket

### WEBSOCKET_RECONNECT_DELAY
- **Type**: Integer (seconds)
- **Default**: `3`
- **Range**: `1-60`
- **Description**: Delay between WebSocket reconnection attempts
- **Example**: `export WEBSOCKET_RECONNECT_DELAY=3`

### WEBSOCKET_MAX_RETRIES
- **Type**: Integer
- **Default**: `5`
- **Range**: `1-100`
- **Description**: Maximum WebSocket reconnection attempts
- **Example**: `export WEBSOCKET_MAX_RETRIES=5`

### WEBSOCKET_PING_INTERVAL
- **Type**: Integer (seconds)
- **Default**: `20`
- **Range**: `5-60`
- **Description**: WebSocket ping interval (keepalive)
- **Example**: `export WEBSOCKET_PING_INTERVAL=20`

### WEBSOCKET_CLOSE_TIMEOUT
- **Type**: Integer (seconds)
- **Default**: `5`
- **Range**: `1-30`
- **Description**: Timeout for WebSocket close handshake
- **Example**: `export WEBSOCKET_CLOSE_TIMEOUT=5`

---

## Latency & Performance

### LATENCY_MS_MAX
- **Type**: Float (milliseconds)
- **Default**: `100.0`
- **Range**: `10-5000`
- **Description**: Maximum allowed WebSocket latency before circuit breaker
- **Tuning**:
  - Ultra-low latency: `50-100ms`
  - Standard: `100-200ms`
  - Relaxed: `200-500ms`
- **Example**: `export LATENCY_MS_MAX=100.0`

### ENABLE_LATENCY_TRACKING
- **Type**: Boolean
- **Default**: `true`
- **Values**: `true` | `false`
- **Description**: Enable latency tracking and metrics
- **Example**: `export ENABLE_LATENCY_TRACKING=true`

### ENABLE_HEALTH_MONITORING
- **Type**: Boolean
- **Default**: `true`
- **Values**: `true` | `false`
- **Description**: Enable health monitoring and metrics
- **Example**: `export ENABLE_HEALTH_MONITORING=true`

### METRICS_INTERVAL
- **Type**: Integer (seconds)
- **Default**: `15`
- **Range**: `5-300`
- **Description**: Interval for publishing metrics to Redis
- **Example**: `export METRICS_INTERVAL=15`

---

## Scalping Settings

### SCALP_ENABLED
- **Type**: Boolean
- **Default**: `true`
- **Values**: `true` | `false`
- **Description**: Enable scalping mode in WebSocket client
- **Example**: `export SCALP_ENABLED=true`

### SCALP_MIN_VOLUME
- **Type**: Float
- **Default**: `0.1`
- **Range**: `0.001-inf`
- **Description**: Minimum trade volume for scalping signals
- **Example**: `export SCALP_MIN_VOLUME=0.1`

---

## Circuit Breakers

### SPREAD_BPS_MAX
- **Type**: Float (basis points)
- **Default**: `5.0`
- **Range**: `0.1-100.0`
- **Description**: Maximum spread before circuit breaker triggers
- **Example**: `export SPREAD_BPS_MAX=5.0`

### CIRCUIT_BREAKER_REDIS_ERRORS
- **Type**: Integer
- **Default**: `3`
- **Range**: `1-50`
- **Description**: Maximum consecutive Redis errors before circuit breaker
- **Example**: `export CIRCUIT_BREAKER_REDIS_ERRORS=3`

### CIRCUIT_BREAKER_COOLDOWN_SECONDS
- **Type**: Integer (seconds)
- **Default**: `45`
- **Range**: `10-600`
- **Description**: Circuit breaker cooldown period
- **Example**: `export CIRCUIT_BREAKER_COOLDOWN_SECONDS=45`

---

## Data Streams

### TRADING_PAIRS
- **Type**: String (comma-separated)
- **Default**: `BTC/USD,ETH/USD,SOL/USD,ADA/USD`
- **Description**: Trading pairs to monitor
- **Example**: `export TRADING_PAIRS="BTC/USD,ETH/USD"`

### TIMEFRAMES
- **Type**: String (comma-separated)
- **Default**: `15s,1m,3m,5m`
- **Description**: Timeframes to generate synthetic bars for
- **Example**: `export TIMEFRAMES="15s,1m,5m"`

---

## Redis Stream Configuration

### REDIS_STREAM_BATCH_SIZE
- **Type**: Integer
- **Default**: `25`
- **Range**: `1-100`
- **Description**: Batch size for Redis stream operations
- **Example**: `export REDIS_STREAM_BATCH_SIZE=25`

---

## Logging

### LOG_LEVEL
- **Type**: String
- **Default**: `INFO`
- **Values**: `DEBUG` | `INFO` | `WARNING` | `ERROR` | `CRITICAL`
- **Description**: Logging level for application
- **Example**: `export LOG_LEVEL=INFO`

---

## Trading Mode

### TRADING_MODE
- **Type**: String
- **Default**: `paper`
- **Values**: `paper` | `live`
- **Description**: Trading mode (paper trading vs live)
- **Production**: Use `paper` for testing, `live` for production
- **Example**: `export TRADING_MODE=paper`

---

## Quick Setup Examples

### Development Setup
```bash
export REDIS_URL="redis://localhost:6379/0"
export REDIS_SSL=false
export ENABLE_5S_BARS=false
export SCALPER_MAX_TRADES_PER_MINUTE=4
export LOG_LEVEL=DEBUG
export TRADING_MODE=paper
```

### Production Setup (15s bars, conservative)
```bash
export REDIS_URL="rediss://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
export REDIS_SSL=true
export REDIS_SSL_CA_CERT="config/certs/redis_ca.pem"
export ENABLE_5S_BARS=false
export SCALPER_MAX_TRADES_PER_MINUTE=4
export LATENCY_MS_MAX=100.0
export SPREAD_BPS_MAX=5.0
export LOG_LEVEL=INFO
export TRADING_MODE=paper
```

### Production Setup (5s bars, aggressive)
```bash
export REDIS_URL="rediss://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
export REDIS_SSL=true
export REDIS_SSL_CA_CERT="config/certs/redis_ca.pem"
export ENABLE_5S_BARS=true
export SCALPER_MAX_TRADES_PER_MINUTE=8
export LATENCY_MS_MAX=50.0
export SPREAD_BPS_MAX=3.0
export REDIS_CONNECTION_POOL_SIZE=20
export LOG_LEVEL=INFO
export TRADING_MODE=paper
```

---

## .env File Template

Create a `.env` file in project root:

```bash
# Redis Connection
REDIS_URL=rediss://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_SSL=true
REDIS_SSL_CA_CERT=config/certs/redis_ca.pem
REDIS_CONNECTION_POOL_SIZE=10
REDIS_SOCKET_TIMEOUT=10

# Feature Flags
ENABLE_5S_BARS=false

# Rate Limiting
SCALPER_MAX_TRADES_PER_MINUTE=4

# Latency
LATENCY_MS_MAX=100.0
ENABLE_LATENCY_TRACKING=true
ENABLE_HEALTH_MONITORING=true

# WebSocket
WEBSOCKET_PING_INTERVAL=20
WEBSOCKET_RECONNECT_DELAY=3
WEBSOCKET_MAX_RETRIES=5

# Circuit Breakers
SPREAD_BPS_MAX=5.0
CIRCUIT_BREAKER_COOLDOWN_SECONDS=45

# Scalping
SCALP_ENABLED=true
SCALP_MIN_VOLUME=0.1

# Logging
LOG_LEVEL=INFO

# Trading Mode
TRADING_MODE=paper
```

---

## Verification

```bash
# Print all crypto-ai-bot env variables
env | grep -E "REDIS|SCALPER|ENABLE|LATENCY|WEBSOCKET|CIRCUIT|SCALP|LOG_LEVEL|TRADING"

# Verify Redis connection
redis-cli -u $REDIS_URL --tls --cacert $REDIS_SSL_CA_CERT PING

# Check if 5s bars enabled
echo "5s bars enabled: $ENABLE_5S_BARS"

# Check rate limit
echo "Max trades per minute: $SCALPER_MAX_TRADES_PER_MINUTE"
```

---

**Last Updated**: 2025-11-08
**Related Docs**: `SUB_MINUTE_BARS_DEPLOYMENT_GUIDE.md`, `DYNAMIC_SIZING_IMPLEMENTATION.md`
