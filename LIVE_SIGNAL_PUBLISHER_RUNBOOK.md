# Live Signal Publisher - Operational Runbook

**Version:** 1.0
**Last Updated:** 2025-01-11
**Owner:** Engineering/DevOps Team

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Configuration](#configuration)
4. [Deployment](#deployment)
5. [Monitoring](#monitoring)
6. [Troubleshooting](#troubleshooting)
7. [Maintenance](#maintenance)
8. [Emergency Procedures](#emergency-procedures)
9. [Validation](#validation)
10. [SLOs & Metrics](#slos--metrics)

---

## Overview

### Purpose

The Live Signal Publisher is a production-grade service that:
- Generates real-time trading signals from market data
- Validates signals using Pydantic schema
- Publishes signals to Redis Cloud streams (per-pair sharding)
- Tracks metrics (latency, freshness, throughput)
- Provides health monitoring endpoints
- Supports both PAPER and LIVE trading modes

### Architecture

```
┌─────────────────────┐
│  Market Data Feed   │
│   (Kraken API)      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐     ┌──────────────────┐
│  Signal Generation  │────▶│ Schema Validation│
│   (Agents/ML)       │     │   (Pydantic)     │
└──────────┬──────────┘     └─────────┬────────┘
           │                          │
           ▼                          ▼
┌─────────────────────────────────────────────┐
│           Live Signal Publisher             │
│  - Mode Toggle (PAPER/LIVE)                 │
│  - Rate Limiting (5 signals/sec)            │
│  - Metrics Tracking                         │
│  - Health Monitoring                        │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│            Redis Cloud (TLS)                │
│  Streams:                                   │
│  - signals:paper:BTC-USD                    │
│  - signals:live:BTC-USD                     │
│  - metrics:publisher                        │
│  - ops:heartbeat                            │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────┐     ┌─────────────────┐
│   signals-api       │────▶│  signals-site   │
│   (Middleware)      │     │   (Frontend)    │
└─────────────────────┘     └─────────────────┘
```

### Key Components

| Component | Purpose |
|-----------|---------|
| `live_signal_publisher.py` | Main publisher service |
| `signals/schema.py` | Signal Pydantic model |
| `signals/publisher.py` | Redis stream publisher |
| `agents/infrastructure/redis_client.py` | Redis Cloud TLS client |
| `scripts/validate_live_signals.py` | Signal validator |

---

## Quick Start

### Prerequisites

1. **Conda Environment**: `crypto-bot`
2. **Redis Cloud**: TLS-enabled instance with credentials
3. **Environment File**: `.env.paper` or `.env.prod`
4. **Certificate**: Redis CA certificate at `config/certs/redis_ca.pem`

### Start Publisher (Paper Mode)

```bash
# Activate conda environment
conda activate crypto-bot

# Ensure logs directory exists
mkdir -p logs

# Load environment
cp .env.paper.example .env.paper
# Edit .env.paper with your REDIS_URL

# Start publisher
python live_signal_publisher.py --mode paper

# Monitor health (different terminal)
curl http://localhost:8080/health
```

### Start Publisher (Live Mode)

⚠️ **WARNING**: Live mode trades real money!

```bash
# Activate conda environment
conda activate crypto-bot

# Set live trading confirmation
export LIVE_TRADING_CONFIRMATION="I confirm live trading"

# Load environment
cp .env.prod.example .env.prod
# Edit .env.prod with production REDIS_URL

# Start publisher
python live_signal_publisher.py \
  --mode live \
  --env-file .env.prod \
  --rate 2.0 \
  --health-port 8080
```

### Validate Signals

```bash
# Validate last 100 signals
python scripts/validate_live_signals.py \
  --mode paper \
  --count 100

# Continuous monitoring
python scripts/validate_live_signals.py \
  --mode paper \
  --continuous \
  --interval 10
```

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_URL` | ✅ Yes | - | Redis Cloud connection URL (rediss://) |
| `REDIS_CA_CERT` | No | `config/certs/redis_ca.pem` | Path to TLS CA certificate |
| `LIVE_TRADING_CONFIRMATION` | For LIVE mode | - | Must be "I confirm live trading" |
| `HEALTH_PORT` | No | 8080 | Health endpoint port |
| `TRADING_PAIRS` | No | BTC/USD,ETH/USD,... | Comma-separated trading pairs |

### Configuration File

The publisher uses `PublisherConfig` with the following options:

```python
PublisherConfig(
    mode="paper",  # or "live"
    trading_pairs=["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"],
    max_signals_per_second=5.0,
    min_signal_interval_ms=200,
    health_port=8080,
    heartbeat_interval_sec=30,
    metrics_publish_interval_sec=60,
    freshness_threshold_sec=30,
    redis_url="rediss://...",
    redis_ca_cert="config/certs/redis_ca.pem",
    stream_maxlen=10000,
    strategy_name="live_momentum_v1",
    confidence_threshold=0.65,
)
```

### Command-Line Options

```bash
python live_signal_publisher.py --help

Options:
  --mode {paper,live}        Trading mode (default: paper)
  --pairs PAIRS              Comma-separated pairs
  --rate RATE                Max signals/sec (default: 5.0)
  --health-port PORT         Health endpoint port (default: 8080)
  --env-file PATH            Environment file (default: .env.paper)
```

---

## Deployment

### Local Development

```bash
# 1. Clone repository
git clone <repo-url>
cd crypto_ai_bot

# 2. Create conda environment
conda create -n crypto-bot python=3.11
conda activate crypto-bot

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.paper.example .env.paper
# Edit REDIS_URL and other variables

# 5. Run tests
pytest tests/test_live_signal_publisher.py -v

# 6. Start publisher
python live_signal_publisher.py --mode paper
```

### Production Deployment (Fly.io)

```bash
# 1. Configure secrets
flyctl secrets set \
  REDIS_URL="rediss://..." \
  LIVE_TRADING_CONFIRMATION="I confirm live trading"

# 2. Deploy
flyctl deploy

# 3. Check health
curl https://<your-app>.fly.dev/health

# 4. Monitor logs
flyctl logs
```

### Docker Deployment

```bash
# Build image
docker build -t crypto-ai-bot:latest .

# Run container
docker run -d \
  --name live-signal-publisher \
  -p 8080:8080 \
  -e REDIS_URL="rediss://..." \
  -e MODE=paper \
  -v ./config:/app/config \
  -v ./logs:/app/logs \
  crypto-ai-bot:latest \
  python live_signal_publisher.py --mode paper
```

---

## Monitoring

### Health Endpoint

```bash
# Check health status
curl http://localhost:8080/health

# Response format:
{
  "status": "healthy",  # or "degraded"
  "reason": "Publishing normally",
  "mode": "paper",
  "metrics": {
    "total_published": 1234,
    "total_errors": 0,
    "signals_by_pair": {
      "BTC/USD": 500,
      "ETH/USD": 450
    },
    "freshness_seconds": 1.23,
    "uptime_seconds": 3600,
    "latency_ms": {
      "signal_generation": {"p50": 12.5, "p95": 45.2, "p99": 89.1},
      "redis_publish": {"p50": 5.2, "p95": 15.8, "p99": 25.3}
    }
  }
}
```

### Redis Streams Monitoring

```bash
# Check stream lengths
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XLEN signals:paper:BTC-USD

# Read latest signals
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE signals:paper:BTC-USD + - COUNT 10

# Check heartbeat
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE ops:heartbeat + - COUNT 1

# Check metrics
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE metrics:publisher + - COUNT 1
```

### Grafana Dashboards

Key metrics to monitor:

1. **Signal Publication Rate**: signals/sec by pair
2. **Latency Distribution**: p50, p95, p99 for generation + Redis
3. **Error Rate**: errors/min
4. **Freshness**: time since last signal
5. **Health Status**: healthy/degraded
6. **Heartbeat**: last heartbeat timestamp

### Alerts

Configure alerts for:

| Alert | Condition | Severity |
|-------|-----------|----------|
| High Error Rate | >5 errors/min for 5 min | Critical |
| Latency SLO Violation | p95 latency >500ms for 10 min | Warning |
| Stale Signals | No signals for >60s | Warning |
| Publisher Down | Health endpoint returns 503 for >2 min | Critical |
| Missing Heartbeat | No heartbeat for >90s | Critical |

---

## Troubleshooting

### Common Issues

#### 1. **Publisher Not Starting**

**Symptoms**: Process exits immediately

**Diagnosis**:
```bash
python live_signal_publisher.py --mode paper 2>&1 | tee logs/startup_error.log
```

**Common Causes**:
- Missing `REDIS_URL` environment variable
- Invalid Redis URL (not using `rediss://`)
- Missing TLS certificate
- Live mode without confirmation

**Solutions**:
```bash
# Check environment
env | grep REDIS

# Verify Redis connectivity
python -c "
import os
from dotenv import load_dotenv
load_dotenv('.env.paper')
print(os.getenv('REDIS_URL'))
"

# Test Redis connection
python scripts/check_redis_health.py
```

#### 2. **No Signals Published**

**Symptoms**: Health status shows "degraded", `total_published=0`

**Diagnosis**:
```bash
# Check logs
tail -f logs/live_publisher.log

# Check signal generation
python -c "
import asyncio
from live_signal_publisher import LiveSignalPublisher, PublisherConfig
from dotenv import load_dotenv

load_dotenv('.env.paper')
config = PublisherConfig(mode='paper')
publisher = LiveSignalPublisher(config)

async def test():
    signal = await publisher.generate_signal('BTC/USD')
    print(f'Generated: {signal}')

asyncio.run(test())
"
```

**Solutions**:
- Check market data feed connectivity
- Verify confidence threshold isn't too high
- Check rate limiting configuration

#### 3. **High Latency (p95 >500ms)**

**Symptoms**: Health endpoint shows high latency percentiles

**Diagnosis**:
```bash
# Check Redis latency
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  --latency

# Check network latency to Redis Cloud
ping <redis-hostname>
```

**Solutions**:
- Move publisher closer to Redis Cloud region
- Reduce signal generation complexity
- Increase Redis connection pool size
- Check for CPU throttling

#### 4. **Schema Validation Errors**

**Symptoms**: Validator shows `invalid_signals > 0`

**Diagnosis**:
```bash
# Run validator with report
python scripts/validate_live_signals.py \
  --mode paper \
  --count 100 \
  --report validation_errors.json

# Check report
cat validation_errors.json | jq '.schema_errors'
```

**Solutions**:
- Review signal generation code
- Ensure all required fields are set
- Check price calculations (no NaN/Inf)
- Verify timestamp generation

#### 5. **Redis Connection Errors**

**Symptoms**: `RedisError` in logs

**Diagnosis**:
```bash
# Test TLS connection
openssl s_client -connect <redis-host>:19818 \
  -CAfile config/certs/redis_ca.pem

# Test with redis-cli
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem PING
```

**Solutions**:
- Verify Redis URL credentials
- Check TLS certificate path
- Verify Redis Cloud IP whitelisting
- Check firewall rules

---

## Maintenance

### Regular Tasks

#### Daily
- ✅ Check health endpoint: `curl http://localhost:8080/health`
- ✅ Verify signal publication rate in Grafana
- ✅ Review error logs: `grep ERROR logs/live_publisher.log`

#### Weekly
- ✅ Run full validation: `python scripts/validate_live_signals.py --mode paper --count 1000 --report weekly_validation.json`
- ✅ Review latency trends
- ✅ Check for duplicate signal IDs
- ✅ Verify stream sizes: `redis-cli XLEN signals:paper:BTC-USD`

#### Monthly
- ✅ Rotate Redis credentials
- ✅ Review and update confidence thresholds
- ✅ Analyze signal quality metrics
- ✅ Update dependencies: `pip list --outdated`

### Log Rotation

```bash
# Configure logrotate
sudo cat > /etc/logrotate.d/crypto-ai-bot <<EOF
/path/to/crypto_ai_bot/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    missingok
    create 0644 user user
}
EOF
```

### Stream Trimming

Redis streams are auto-trimmed to 10,000 entries. To manually trim:

```bash
# Trim to last 5000 entries
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XTRIM signals:paper:BTC-USD MAXLEN ~ 5000
```

---

## Emergency Procedures

### Emergency Shutdown

```bash
# Graceful shutdown (Ctrl+C or kill -TERM)
kill -TERM <pid>

# Force shutdown if unresponsive
kill -KILL <pid>

# Verify no signals being published
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE signals:paper:BTC-USD + - COUNT 1
```

### Kill Switch (Live Mode)

⚠️ **Use only in emergency to stop live trading**

```bash
# 1. Stop publisher
kill -TERM <pid>

# 2. Verify stopped
curl http://localhost:8080/health  # Should fail

# 3. Clear live stream (optional - prevents stale signals)
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  DEL signals:live:BTC-USD \
  DEL signals:live:ETH-USD
```

### Rollback Procedure

If bad signals are published:

```bash
# 1. Stop publisher
kill -TERM <pid>

# 2. Identify bad signal IDs
python scripts/validate_live_signals.py \
  --mode paper \
  --count 1000 \
  --report bad_signals.json

# 3. Delete bad signals (Redis doesn't support XDEL by field)
# Instead, publish corrections or notify downstream consumers

# 4. Restart with fixed configuration
git checkout <previous-commit>
python live_signal_publisher.py --mode paper
```

### Data Recovery

If Redis data is lost:

```bash
# 1. Check Redis persistence
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  LASTSAVE

# 2. Restart publisher to regenerate signals
python live_signal_publisher.py --mode paper

# 3. Backfill from logs (if needed)
# Parse logs/live_publisher.log for signal data
```

---

## Validation

### Pre-Deployment Validation

```bash
# 1. Run unit tests
pytest tests/test_live_signal_publisher.py -v

# 2. Run integration tests (requires Redis)
REDIS_URL=$REDIS_URL pytest tests/test_live_signal_publisher.py::TestPublisherIntegration -v

# 3. Validate configuration
python -c "
from live_signal_publisher import PublisherConfig
config = PublisherConfig(mode='paper')
config.validate()
print('✓ Configuration valid')
"

# 4. Test signal generation
python -c "
import asyncio
from live_signal_publisher import LiveSignalPublisher, PublisherConfig
config = PublisherConfig(mode='paper')
publisher = LiveSignalPublisher(config)
signal = asyncio.run(publisher.generate_signal('BTC/USD'))
print(f'✓ Generated signal: {signal.id}')
"

# 5. Dry run (5 minutes)
timeout 300 python live_signal_publisher.py --mode paper --rate 1.0
```

### Post-Deployment Validation

```bash
# 1. Check health
curl http://localhost:8080/health | jq .

# 2. Validate signals (1 minute)
python scripts/validate_live_signals.py \
  --mode paper \
  --continuous \
  --interval 10 &
VALIDATOR_PID=$!

sleep 60

kill $VALIDATOR_PID

# 3. Check latency SLO
curl http://localhost:8080/health | jq '.metrics.latency_ms'

# 4. Verify heartbeat
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE ops:heartbeat + - COUNT 1
```

### Soak Test (30-60 minutes)

Run the soak test script (see next section) to validate:
- Sustained throughput
- Memory stability (no leaks)
- Latency consistency
- Error rate
- Health status

---

## SLOs & Metrics

### Service Level Objectives (SLOs)

| Metric | SLO | Measurement |
|--------|-----|-------------|
| **Latency (p95)** | <500ms | End-to-end (generation + publish) |
| **Availability** | >99.9% | Health endpoint returns 200 |
| **Throughput** | ≥5 signals/sec | Across all pairs |
| **Error Rate** | <0.1% | Failed publishes / total attempts |
| **Freshness** | <30s | Time since last signal |

### Key Performance Indicators (KPIs)

1. **Signal Quality**
   - Schema validation pass rate: >99.9%
   - Duplicate ID rate: 0%
   - Confidence distribution: median >0.75

2. **Operational Health**
   - Uptime: >99.9%
   - Heartbeat reliability: >99.9%
   - Metrics publication: >99%

3. **Resource Utilization**
   - CPU: <50% average
   - Memory: <2GB RSS
   - Redis connections: <10

### Metrics Collection

All metrics are published to `metrics:publisher` stream every 60 seconds:

```json
{
  "timestamp": 1730000000000,
  "total_published": 5000,
  "total_errors": 2,
  "signals_by_pair": {"BTC/USD": 2000, "ETH/USD": 1800, ...},
  "signals_by_mode": {"paper": 5000},
  "freshness_seconds": 1.23,
  "uptime_seconds": 7200,
  "latency_ms": {
    "signal_generation": {"p50": 12.5, "p95": 45.2, "p99": 89.1},
    "redis_publish": {"p50": 5.2, "p95": 15.8, "p99": 25.3}
  }
}
```

---

## Additional Resources

- **PRD**: [PRD-001: Crypto AI Bot - Core Intelligence Engine](docs/PRD-001-CRYPTO-AI-BOT.md)
- **Schema Documentation**: `signals/schema.py`
- **Redis Client**: `agents/infrastructure/redis_client.py`
- **Signal Validation**: `scripts/validate_live_signals.py`

## Support

- **Issues**: https://github.com/your-org/crypto-ai-bot/issues
- **Slack**: #crypto-ai-bot-ops
- **On-Call**: PagerDuty rotation

---

**Last Reviewed**: 2025-01-11
**Next Review**: 2025-02-11
