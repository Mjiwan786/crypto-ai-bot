# Engine Runbook

**Version:** 2.0.0  
**Last Updated:** 2025-01-15  
**Status:** Production Ready (PRD-001 Compliant)  
**PRD Reference:** PRD-001 Section 10 (Health Checks & Monitoring)

---

## Overview

This runbook provides operational guidance for running and maintaining the crypto-ai-bot signal generation engine. The engine runs 24/7 in paper or live mode, generating trading signals and publishing them to Redis Streams.

**Key Features:**
- PRD-001 compliant Prometheus metrics
- Comprehensive health checks (Redis, Kraken WS, signal activity, PnL updates)
- Optimized configuration loading with AgentConfigIntegrator
- Graceful shutdown and restart procedures

## Architecture

```
[Kraken WebSocket] --> [Signal Generation] --> [Risk Filters] --> [Redis Streams]
         |                     |                      |                 |
    Market Data           Strategies              Spread/Vol        signals:paper:*
    OHLCV/Trades          SCALPER/TREND           ATR/DD           pnl:paper:*
                                                                    events:bus
```

## Quick Start

### Prerequisites

- Windows 10/11 or Linux
- Anaconda/Miniconda installed
- Redis Cloud account with TLS certificate
- Python 3.10+

### Environment Setup

```bash
# Activate conda environment
conda activate crypto-bot

# Verify Python version
python --version  # Should be 3.10+

# Verify dependencies
pip list | grep -E "redis|prometheus|pydantic"
```

### Configuration Files

| File | Purpose | Mode |
|------|---------|------|
| `.env.paper` | Paper trading config | Development/Testing |
| `.env.live` | Live trading config | Production |
| `config/certs/redis_ca.pem` | Redis TLS certificate | Required for both |

### Running the Engine

#### Paper Mode (Default - Safe for Testing)

```bash
# Activate environment
conda activate crypto-bot

# Run with paper mode (default)
python main.py run --mode paper

# Or use production_engine.py
python production_engine.py --mode paper
```

#### Live Mode (Production)

```bash
# CAUTION: Live mode publishes to live streams
conda activate crypto-bot

# Verify environment variables
echo $REDIS_URL
echo $ENGINE_MODE

# Set live trading confirmation (required)
export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"

# Run with live mode
python main.py run --mode live
```

#### Health Check Only

```bash
# Run health check and exit (useful for CI/CD)
python main.py health

# Or use the health checker module directly
python -m monitoring.prd_health_checker
```

## Monitoring

### Health Endpoints

The engine exposes HTTP endpoints on port 9108 (configurable via `METRICS_PORT`):

| Endpoint | Description | Healthy Status |
|----------|-------------|----------------|
| `/health` | Full health status (JSON) | 200 OK |
| `/metrics` | Prometheus metrics (Task D compliant) | 200 OK |
| `/readiness` | Ready to serve traffic | 200 OK |
| `/liveness` | Process is alive | 200 OK |

**Example Health Check:**

```bash
# Check health locally
curl http://localhost:9108/health | jq

# Check metrics (Prometheus format)
curl http://localhost:9108/metrics

# Check readiness
curl http://localhost:9108/readiness

# Check liveness
curl http://localhost:9108/liveness
```

**Health Check Components:**
- Redis connectivity (latency < 500ms)
- Kraken WebSocket connectivity (per pair)
- Signal activity (last signal < 5 minutes)
- PnL activity (last update < 10 minutes)

### Prometheus Metrics (Task D Compliant)

**Required Metrics (Task D):**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `signals_published_total` | Counter | `pair`, `strategy`, `side` | Total signals published |
| `signal_generation_latency_ms` | Histogram | - | Signal generation latency (buckets: 10, 25, 50, 100, 250, 500, 1000, 2500, 5000ms) |
| `current_drawdown_pct` | Gauge | - | Current drawdown percentage |
| `active_positions` | Gauge | `pair` | Active positions by pair |
| `risk_rejections_total` | Counter | `pair`, `reason` | Risk filter rejections |

**Additional Observability Metrics:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `redis_connected` | Gauge | - | Redis connection status (1=connected, 0=disconnected) |
| `kraken_ws_connected` | Gauge | `pair` | Kraken WS status by pair |
| `last_signal_age_seconds` | Gauge | - | Seconds since last signal |
| `last_pnl_update_age_seconds` | Gauge | - | Seconds since last PnL update |
| `engine_uptime_seconds` | Gauge | - | Engine uptime |
| `engine_healthy` | Gauge | - | Overall health (1=healthy, 0=unhealthy) |

**Accessing Metrics:**

```bash
# View all metrics
curl http://localhost:9108/metrics

# Filter specific metric
curl http://localhost:9108/metrics | grep signals_published_total

# Query with Prometheus
prometheus_query='signals_published_total{pair="BTC/USD", strategy="SCALPER"}'
```

### Redis Keys

The engine publishes to these Redis keys:

| Key | Type | Description |
|-----|------|-------------|
| `engine:heartbeat` | STRING | ISO timestamp (TTL 60s) |
| `engine:last_signal_ts` | STRING | Epoch timestamp |
| `engine:status` | STRING | JSON status blob |
| `signals:paper:<PAIR>` | STREAM | Paper signals |
| `signals:live:<PAIR>` | STREAM | Live signals |
| `pnl:paper:equity_curve` | STREAM | Paper equity |
| `events:bus` | STREAM | System events |

## Health Checks

### Running Health Checks

```bash
# Run comprehensive health checks (PRD-001 compliant)
python -m monitoring.prd_health_checker

# Or use the internal health checks module
python -m monitoring.internal_health_checks

# Expected output:
# [OK] redis_connectivity: Connected (latency: 25.3ms)
# [OK] kraken_ws: All pairs healthy
# [OK] signal_activity: Last signal 45s ago
# [OK] pnl_activity: Last PnL update 120s ago
```

**Health Check Thresholds:**
- Redis: Latency < 500ms, timeout 5s
- Kraken WS: Last message < 60s per pair
- Signal activity: Last signal < 5 minutes (configurable via `SIGNAL_STALE_THRESHOLD_SEC`)
- PnL activity: Last update < 10 minutes (configurable via `PNL_STALE_THRESHOLD_SEC`)

### Health Check Details

1. **Redis Connectivity**
   - Pings Redis Cloud
   - Measures latency
   - Threshold: < 500ms

2. **Redis Streams**
   - Checks required streams exist
   - Required: `signals:*`, `pnl:*:equity_curve`, `events:bus`

3. **Signal Freshness**
   - Last signal within 5 minutes (configurable)
   - Stale = engine may be stuck

4. **PnL Freshness**
   - Last PnL update within 10 minutes
   - Stale = PnL pipeline not running

5. **Engine Heartbeat**
   - Heartbeat key updated every 30s
   - TTL of 60s ensures stale detection

## Restarting Safely

### Graceful Shutdown

The engine handles `SIGTERM` and `SIGINT` gracefully:

```bash
# Send SIGTERM for graceful shutdown
kill -TERM <pid>

# Or use Ctrl+C if running in foreground
```

### Restart Procedure

1. **Check Current State:**
   ```bash
   curl http://localhost:9108/health
   ```

2. **Stop Engine:**
   ```bash
   # Find process
   ps aux | grep main_engine

   # Graceful stop
   kill -TERM <pid>

   # Wait for "Engine shutdown complete" log
   ```

3. **Verify Stopped:**
   ```bash
   curl http://localhost:9108/health  # Should fail
   ```

4. **Start Engine:**
   ```bash
   conda activate crypto-bot
   python main_engine.py --mode paper
   ```

5. **Verify Running:**
   ```bash
   curl http://localhost:9108/health
   python monitoring/internal_health_checks.py
   ```

### Emergency Restart

If engine is unresponsive:

```bash
# Force kill (last resort)
kill -9 <pid>

# Wait 5 seconds
sleep 5

# Start fresh
python main_engine.py --mode paper
```

## Troubleshooting

### Common Issues

#### 1. Redis Connection Failed

**Symptoms:**
- Health check shows redis_connectivity FAILED
- Logs show "Connection refused" or "Auth error"

**Resolution:**
```bash
# Verify Redis URL
echo $REDIS_URL

# Test connection manually
redis-cli -u "$REDIS_URL" --tls --cacert config/certs/redis_ca.pem PING

# Check certificate exists
ls -la config/certs/redis_ca.pem
```

#### 2. No Signals Being Generated

**Symptoms:**
- signal_freshness shows STALE
- `signals_published_total` not incrementing

**Resolution:**
```bash
# Check Kraken WS connection
curl http://localhost:9108/health | jq '.components.kraken_ws'

# Check for errors in logs
grep -i error logs/crypto_ai_bot.log | tail -20

# Restart signal generator
# (engine will auto-restart the task)
```

#### 3. High Latency

**Symptoms:**
- `signal_generation_latency_ms` P99 > 1000ms
- Signals arriving late

**Resolution:**
```bash
# Check system resources
top -p $(pgrep -f main_engine)

# Check Redis latency
redis-cli -u "$REDIS_URL" --tls --cacert config/certs/redis_ca.pem DEBUG SLEEP 0

# Consider reducing trading pairs
```

#### 4. Memory Growth

**Symptoms:**
- RSS memory continuously increasing
- Eventually OOM killed

**Resolution:**
```bash
# Check memory usage
ps aux | grep main_engine | awk '{print $6}'

# Force restart (fixes most memory leaks)
kill -TERM <pid>
python main_engine.py
```

### Log Locations

| Log | Location | Purpose |
|-----|----------|---------|
| Engine | `logs/crypto_ai_bot.log` | Main engine logs |
| Metrics | `logs/metrics.log` | Prometheus export logs |
| Errors | stderr | Critical errors |

### Useful Commands

```bash
# Watch real-time logs
tail -f logs/crypto_ai_bot.log

# Count signals in last hour
redis-cli -u "$REDIS_URL" --tls --cacert config/certs/redis_ca.pem \
  XLEN signals:paper:BTC-USD

# Check equity curve
redis-cli -u "$REDIS_URL" --tls --cacert config/certs/redis_ca.pem \
  XRANGE pnl:paper:equity_curve - + COUNT 5

# Check engine heartbeat
redis-cli -u "$REDIS_URL" --tls --cacert config/certs/redis_ca.pem \
  GET engine:heartbeat
```

## Tests

### Running Tests

```bash
# Activate environment
conda activate crypto-bot

# Run all tests
pytest tests/ -v

# Run unit tests only (fast)
pytest tests/unit/ -v

# Run integration tests (requires Redis)
pytest tests/integration/ -v -m redis

# Run specific test file
pytest tests/unit/test_prd_pnl.py -v
```

### Test Categories

| Marker | Description |
|--------|-------------|
| `unit` | Fast, no external deps |
| `integration` | Requires Redis |
| `redis` | Requires Redis connection |
| `live` | Against live Kraken |

## Configuration Management

### OptimizedConfigLoader + AgentConfigIntegrator

The engine uses a unified configuration system:

```python
from config.optimized_config_loader import OptimizedConfigManager
from config.agent_integration import AgentConfigIntegrator

# Get optimized config manager
config_manager = OptimizedConfigManager.get_instance()

# Get merged configuration (main + agent configs)
config = config_manager.get_config()

# Get agent-specific configuration
agent_config = config_manager.get_agent_config(strategy="scalper", environment="production")

# Get risk parameters
risk_params = config_manager.get_risk_parameters(strategy="scalper")
```

**Configuration Files:**
- `config/settings.yaml` - Main configuration
- `config/agent_configs/` - Agent-specific configurations
- `config/exchange_configs/kraken.yaml` - Kraken exchange config
- `config/exchange_configs/kraken_ohlcv.yaml` - OHLCV timeframes and pairs

**Environment Variables Override:**
- `ENGINE_MODE` - Trading mode (paper/live)
- `REDIS_URL` - Redis connection URL
- `TRADING_PAIRS` - Comma-separated pairs
- `METRICS_PORT` - Prometheus metrics port (default: 9108)
- `METRICS_ENABLED` - Enable metrics (default: true)

## Known Limitations

1. **Single Instance Only**
   - Engine should run as a single instance
   - Multiple instances will cause duplicate signals

2. **Kraken Rate Limits**
   - Max 1 connection per IP for public WS
   - Max 10 requests/second for REST

3. **Redis Stream MAXLEN**
   - Streams capped at 10,000 entries (PRD-001 compliant)
   - Older entries automatically trimmed

4. **Recovery Time**
   - On restart, may miss signals during downtime
   - No signal replay mechanism

5. **TLS Certificate**
   - Redis CA cert must be valid (`config/certs/redis_ca.pem`)
   - Cert rotation requires restart

6. **Health Check Timeouts**
   - Redis health check timeout: 5s (configurable via `REDIS_HEALTH_TIMEOUT_SEC`)
   - Kraken WS health check timeout: 10s (configurable via `KRAKEN_WS_HEALTH_TIMEOUT_SEC`)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_MODE` | `paper` | paper/live |
| `ENGINE_MODE` | `paper` | Same as TRADING_MODE |
| `REDIS_URL` | Required | Redis connection URL |
| `REDIS_CA_CERT_PATH` | `config/certs/redis_ca.pem` | TLS cert path |
| `TRADING_PAIRS` | `BTC/USD,ETH/USD` | Comma-separated pairs |
| `TIMEFRAMES` | `15s,1m,5m` | OHLCV timeframes |
| `METRICS_ENABLED` | `true` | Enable Prometheus |
| `METRICS_PORT` | `9108` | Prometheus port |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `HEARTBEAT_INTERVAL_SEC` | `30` | Heartbeat frequency |
| `SIGNAL_STALE_THRESHOLD_SEC` | `300` | Stale signal threshold |

## Support

- Issues: https://github.com/anthropics/claude-code/issues
- PRD: `docs/PRD-001-CRYPTO-AI-BOT.md`
- Signal Methodology: `docs/SIGNAL_METHODOLOGY.md`
