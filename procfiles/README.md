# Procfiles - Process Orchestration

**Simple process management for local development.**

## Overview

Procfiles provide a standardized way to run multiple services locally using process managers like [Foreman](https://github.com/ddollar/foreman) or [Goreman](https://github.com/mattn/goreman).

## Available Procfiles

| File | Services | Purpose |
|------|----------|---------|
| `pnl_aggregator.proc` | 1 service | Run PnL aggregator only |
| `pnl_backfill.proc` | 1 service (one-time) | Backfill historical data |
| `pnl_all.proc` | 2 services | Aggregator + health checks |

## Prerequisites

### Install Process Manager

**Option 1: Foreman (Ruby)**
```bash
gem install foreman
```

**Option 2: Goreman (Go)**
```bash
go install github.com/mattn/goreman@latest
```

**Option 3: Honcho (Python)**
```bash
pip install honcho
```

### Set Environment Variables

Create a `.env` file in the project root:

```bash
# Copy example
cp .env.example .env

# Required variables
export REDIS_URL=rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0
export START_EQUITY=10000
export POLL_MS=500
```

Or set directly in your shell:

```bash
# For Redis Cloud (TLS)
export REDIS_URL=rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0

# For local Redis
export REDIS_URL=redis://localhost:6379/0
```

## Usage

### Run PnL Aggregator Only

**With Foreman:**
```bash
foreman start -f procfiles/pnl_aggregator.proc
```

**With Goreman:**
```bash
goreman -f procfiles/pnl_aggregator.proc start
```

**With Honcho:**
```bash
honcho -f procfiles/pnl_aggregator.proc start
```

### Run Backfill (One-Time)

```bash
# With Foreman
foreman run -f procfiles/pnl_backfill.proc pnl-backfill

# Or run directly
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv --start-equity 10000
```

### Run Complete PnL Infrastructure

```bash
# With Foreman
foreman start -f procfiles/pnl_all.proc

# With Goreman
goreman -f procfiles/pnl_all.proc start
```

**This starts**:
- PnL aggregator (continuous)
- Health check monitor (every 60s)

## Typical Workflow

### Initial Setup

```bash
# 1. Activate conda environment
conda activate crypto-bot

# 2. Set environment variables
export REDIS_URL=rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0
export START_EQUITY=10000

# 3. Run backfill (one-time)
python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv

# 4. Verify backfill
python scripts/health_check_pnl.py --verbose
```

### Daily Development

```bash
# Activate environment
conda activate crypto-bot

# Start all PnL services
foreman start -f procfiles/pnl_all.proc

# Or just the aggregator
foreman start -f procfiles/pnl_aggregator.proc
```

### Production

For production, use Docker Compose instead:

```bash
# Start PnL services with Docker
docker-compose up -d pnl-aggregator pnl-health

# Check logs
docker-compose logs -f pnl-aggregator

# Check health
docker-compose exec pnl-aggregator python scripts/health_check_pnl.py
```

## Configuration

### pnl_aggregator.proc

**Environment variables**:
```bash
REDIS_URL                 # Redis connection string (required)
START_EQUITY=10000        # Initial equity in USD
POLL_MS=500              # Polling interval in milliseconds
STATE_KEY=pnl:agg:last_id # Resume state key
USE_PANDAS=false         # Enable pandas statistics
STATS_WINDOW_SIZE=5000   # Rolling window size
PNL_METRICS_PORT=9309    # Prometheus metrics port (optional)
```

### pnl_backfill.proc

**Environment variables**:
```bash
REDIS_URL                 # Redis connection string (required)
```

**Command arguments**:
- `--file` - Path to fills file (CSV or JSONL)
- `--start-equity` - Initial equity (default: 10000)
- `--force` - Override backfill marker
- `--dry-run` - Preview without writing

### pnl_all.proc

**Runs multiple services**:
1. `pnl-aggregator` - Main aggregation service
2. `pnl-health` - Health check monitor (every 60s)

**Environment variables**: Combined from above

## Process Management

### View Status

**With Foreman:**
```bash
# Process will show status in terminal
# Use Ctrl+C to stop all services
```

**With Goreman:**
```bash
# In separate terminal while running
goreman run status
```

### Stop Services

**All processes:**
```bash
# Press Ctrl+C in the terminal running Foreman/Goreman
```

**Specific service (Goreman only):**
```bash
goreman run stop pnl-aggregator
```

### Restart Service (Goreman only)

```bash
goreman run restart pnl-aggregator
```

### View Logs

**With Foreman:**
```bash
# Logs are displayed in terminal with color coding
# Format: [timestamp] service | message
```

**With Goreman:**
```bash
# Logs shown in terminal with service prefix
# Can filter by service name using grep
foreman start -f procfiles/pnl_all.proc | grep pnl-aggregator
```

## Troubleshooting

### "Connection refused" on Redis

**Cause**: Redis not running or wrong URL

**Solution**:
```bash
# Check Redis URL
echo $REDIS_URL

# Test connection
redis-cli -u $REDIS_URL --tls --cacert config/certs/ca.crt PING

# For local Redis, start it first
docker run -d -p 6379:6379 redis:7
```

### "Command not found: foreman"

**Cause**: Process manager not installed

**Solution**:
```bash
# Install Foreman
gem install foreman

# Or use Goreman
go install github.com/mattn/goreman@latest

# Or use Honcho
pip install honcho
```

### "No such file or directory: .env"

**Cause**: Environment variables not set

**Solution**:
```bash
# Create .env file
cat > .env << EOF
REDIS_URL=rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0
START_EQUITY=10000
POLL_MS=500
EOF

# Or export directly
export REDIS_URL=...
```

### Service crashes immediately

**Cause**: Python module import error or missing dependencies

**Solution**:
```bash
# Activate conda environment
conda activate crypto-bot

# Install dependencies
pip install -e .

# Test imports
python -c "import monitoring.pnl_aggregator"
python -c "from agents.infrastructure.pnl_publisher import publish_trade_close"
```

## Advanced Usage

### Custom Port for Metrics

```bash
# Edit pnl_aggregator.proc
# Change line to:
# pnl-aggregator: PNL_METRICS_PORT=9309 python -m monitoring.pnl_aggregator

# Then start
foreman start -f procfiles/pnl_aggregator.proc
```

### Enable Pandas Statistics

```bash
# Edit pnl_aggregator.proc
# Change line to:
# pnl-aggregator: USE_PANDAS=true STATS_WINDOW_SIZE=5000 python -m monitoring.pnl_aggregator

# Then start
foreman start -f procfiles/pnl_aggregator.proc
```

### Custom Concurrency

**With Foreman:**
```bash
# Run 2 instances of aggregator (for testing)
foreman start -f procfiles/pnl_aggregator.proc -c pnl-aggregator=2
```

**Note**: Only run one aggregator instance in production to avoid duplicate processing.

## Comparison: Procfile vs Docker Compose

| Feature | Procfile | Docker Compose |
|---------|----------|----------------|
| **Setup** | Quick, no containers | Requires Docker |
| **Dependencies** | Uses local Python | Isolated environment |
| **Logs** | Terminal output | Docker logs |
| **Restart** | Manual | Automatic (`restart: unless-stopped`) |
| **Health checks** | Manual | Built-in |
| **Production** | Not recommended | Recommended |
| **Development** | ✅ Best choice | ✅ Also good |

**Recommendation**:
- **Local dev**: Use Procfiles for quick iteration
- **Staging/Prod**: Use Docker Compose for isolation and restart policies

## Integration with Trading System

The PnL infrastructure is designed to run alongside the main trading system:

```
┌─────────────────────────────────────────────────┐
│  Trading System (Main)                          │
│  - Signal generation                            │
│  - Order execution                              │
│  - Position management                          │
│  └─> Publishes to: trades:closed (on close)    │
└─────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  PnL Aggregator (Separate Process)              │
│  - Consumes: trades:closed                      │
│  - Aggregates equity                            │
│  - Detects day boundaries                       │
│  └─> Publishes to: pnl:equity                   │
└─────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  Dashboard / Analytics                          │
│  - Reads: pnl:equity                            │
│  - Renders equity curve                         │
│  - Shows statistics                             │
└─────────────────────────────────────────────────┘
```

**To run both**:
```bash
# Terminal 1: Main trading system
python scripts/start_trading_system.py --mode paper

# Terminal 2: PnL infrastructure
foreman start -f procfiles/pnl_all.proc
```

Or use a combined Procfile (advanced):
```bash
# Create procfiles/full_system.proc
trading-system: python scripts/start_trading_system.py --mode paper
pnl-aggregator: python -m monitoring.pnl_aggregator
pnl-health: while true; do python scripts/health_check_pnl.py --verbose; sleep 60; done

# Run all together
foreman start -f procfiles/full_system.proc
```

---

**Last Updated**: 2025-01-13
**Conda Environment**: crypto-bot
**Python Version**: 3.10.18
**Redis Cloud**: redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 (TLS)
