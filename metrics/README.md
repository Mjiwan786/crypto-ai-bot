# Metrics Publisher

Compact, production-ready metrics publisher for crypto-ai-bot engine → Redis → signals-api → signals-site pipeline.

## Overview

The metrics publisher collects real-time statistics from the Kraken WebSocket client and publishes compact JSON metrics to Redis for consumption by the signals-api and signals-site.

## Redis Keys

### 1. `engine:metrics:summary` (STRING)
Latest metrics snapshot in JSON format. Overwritten on each publish.

### 2. `engine:metrics:events` (STREAM)
Historical metrics events with automatic trimming (maxlen: 1000).

## Metrics Schema

```json
{
  "timestamp": 1762516964.589386,
  "timestamp_iso": "2025-11-07T12:02:44Z",
  "uptime_s": 123.45,
  "last_heartbeat_ts": 1762516964.589386,

  "ws_latency_ms": {
    "avg": 45.2,
    "p50": 40.0,
    "p95": 95.3,
    "p99": 128.5,
    "max": 150.0
  },

  "messages_received": 1000,
  "reconnects": 0,
  "circuit_breaker_trips": 15,
  "errors": 0,
  "trades_per_minute": 10,
  "running": true,

  "circuit_breakers": {
    "spread": "closed",
    "latency": "closed",
    "connection": "closed"
  },

  "last_signal_ts": 1762516960.123,

  "redis_ok": true,
  "redis_lag_estimate": 45.2,

  "stream_sizes": {
    "kraken:trade:BTC-USD": 100,
    "kraken:spread:ETH-USD": 500,
    "kraken:book:SOL-USD": 1809,
    "kraken:health": 34,
    "signals:paper": 10000,
    "metrics:pnl:equity": 1000
  }
}
```

## Usage

### CLI

```bash
# Publish once and exit
python -m metrics.publisher --once

# Run continuously (10s interval)
python -m metrics.publisher

# Custom interval
python -m metrics.publisher --interval 5

# With live Kraken WS client
python -m metrics.publisher --with-ws-client

# Custom environment file
python -m metrics.publisher --env-file .env.local

# Adjust logging
python -m metrics.publisher --log-level DEBUG
```

### Programmatic

```python
from metrics.publisher import MetricsPublisher
from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig

# Create WS client
config = KrakenWSConfig()
ws_client = KrakenWebSocketClient(config)

# Create publisher
publisher = MetricsPublisher(
    redis_url=os.getenv('REDIS_URL'),
    redis_cert_path=os.getenv('REDIS_TLS_CERT_PATH'),
    ws_client=ws_client
)

# Connect to Redis
await publisher.connect_redis()

# Publish once
metrics = await publisher.publish_once()

# Run continuously (10s interval)
await publisher.run_continuous(interval=10)

# Close
await publisher.close()
```

## Configuration

Uses environment variables from `.env.prod`:

```bash
# Redis Connection
REDIS_URL=rediss://default:password@host:port
REDIS_TLS_CERT_PATH=/path/to/cert.pem

# Trading Pairs (comma-separated)
TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD,ADA/USD
```

## Testing

### Unit Tests

```bash
# Run all tests
pytest tests/test_metrics_publisher.py -v

# Run with coverage
pytest tests/test_metrics_publisher.py --cov=metrics

# Run integration tests (requires Redis)
pytest -m integration tests/test_metrics_publisher.py
```

### Verification

```bash
# Verify metrics were published
python verify_metrics_redis.py
```

### Live Demo

```bash
# 15-second demo with live Kraken WS client
python demo_metrics_live.py
```

## Integration with signals-api

The signals-api can consume metrics from Redis:

```python
# Read latest summary
summary = await redis.get('engine:metrics:summary')
metrics = json.loads(summary)

# Stream historical events
events = await redis.xrevrange('engine:metrics:events', count=10)
for event_id, data in events:
    event_data = json.loads(data['data'])
    # Process event
```

## Monitoring

Key metrics to monitor:

- **`messages_received`**: Should be increasing if engine is running
- **`errors`**: Should be 0
- **`circuit_breaker_trips`**: Check if exceeding thresholds
- **`ws_latency_ms.p99`**: Should be < 200ms
- **`redis_ok`**: Should be true
- **`redis_lag_estimate`**: Should be < 100ms
- **`running`**: Should be true

## Performance

- **Publish interval**: 10 seconds (configurable)
- **Redis operations**: 2 per publish (SET + XADD)
- **Data size**: ~1-2KB per metrics snapshot
- **Stream retention**: Last 1000 events (~2.7 hours at 10s interval)

## Architecture

```
┌─────────────────────┐
│ KrakenWebSocketClient│
│  - Latency tracker   │
│  - Circuit breakers  │
│  - Connection stats  │
└──────────┬──────────┘
           │
           ▼
    ┌─────────────┐
    │   Metrics   │
    │  Publisher  │
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │Redis Cloud  │
    │  (TLS)      │
    └──────┬──────┘
           │
           ├─► engine:metrics:summary (STRING)
           └─► engine:metrics:events (STREAM)
```

## Files

- **`metrics/publisher.py`**: Main publisher implementation
- **`metrics/__init__.py`**: Package initialization
- **`metrics/__main__.py`**: CLI entry point
- **`tests/test_metrics_publisher.py`**: Comprehensive test suite
- **`verify_metrics_redis.py`**: Verification script
- **`demo_metrics_live.py`**: Live demo script

## Example Output

### `--once` mode:

```json
{
  "timestamp": 1762516964.589386,
  "timestamp_iso": "2025-11-07T12:02:44Z",
  "uptime_s": 0.36,
  "messages_received": 0,
  "circuit_breaker_trips": 0,
  "redis_ok": true,
  "redis_lag_estimate": 30.29,
  "stream_sizes": {
    "kraken:trade:BTC-USD": 0,
    "kraken:spread:ETH-USD": 405,
    "kraken:book:SOL-USD": 1941,
    "kraken:health": 34,
    "signals:paper": 10014
  }
}
```

### Live demo output:

```
[Metrics #1 at 07:05:32]
  Messages Received: 139
  Circuit Breaker Trips: 14
  Latency avg: 37.54ms
  Latency p95: 94.50ms
  Redis Lag: 26.31ms
  Running: True

[Metrics #2 at 07:05:39]
  Messages Received: 242
  Circuit Breaker Trips: 32
  Latency avg: 47.79ms
  Latency p95: 104.59ms
  Redis Lag: 61.25ms
  Running: True

[Metrics #3 at 07:05:45]
  Messages Received: 357
  Circuit Breaker Trips: 46
  Latency avg: 51.27ms
  Latency p99: 134.52ms
  Redis Lag: 116.53ms
  Running: True
```

## See Also

- [KrakenWebSocketClient](../utils/kraken_ws.py) - Source of metrics
- [crypto-ai-bot PRD](../docs/PRD-001-CRYPTO-AI-BOT.md) - Core intelligence engine (this repo)
- signals-api PRD - Consumer of metrics (see signals_api repository)
- signals-site PRD - Dashboard visualization (see signals-site repository)
