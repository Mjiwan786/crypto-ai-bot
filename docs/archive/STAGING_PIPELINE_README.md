# Staging Pipeline for Crypto AI Bot

This document describes the staging pipeline system that brings up the crypto trading bot services in the correct order and verifies plumbing before any live trading.

## Overview

The staging pipeline orchestrates three main stages:

1. **Market Data Ingestors** → publish to `md:*` streams
2. **Signal/Strategy Agents** → read `md:*`, publish to `signals:staging`
3. **Execution Agent (PAPER)** → consumes `signals:staging`, NO live orders

## Quick Start

### Prerequisites

1. **Conda Environment**: Create and activate the `crypto-bot` environment:
   ```bash
   conda create -n crypto-bot python=3.10
   conda activate crypto-bot
   ```

2. **Dependencies**: Install required packages:
   ```bash
   pip install redis pyyaml python-dotenv aiohttp websockets
   ```

3. **Redis**: Ensure Redis is running and accessible

4. **Environment File**: Create `.env.staging` from `env.staging.template`

### Running the Pipeline

#### Windows (PowerShell)
```powershell
# Basic staging run
.\scripts\windows\run_staging.ps1 -DotEnvPath .\.env.staging

# With execution agent
.\scripts\windows\run_staging.ps1 -DotEnvPath .\.env.staging -IncludeExec

# Verbose mode
.\scripts\windows\run_staging.ps1 -DotEnvPath .\.env.staging -Verbose -Timeout 60
```

#### POSIX (Linux/macOS)
```bash
# Basic staging run
bash scripts/run_staging.sh --env .env.staging

# With execution agent
bash scripts/run_staging.sh --env .env.staging --include-exec

# Verbose mode
bash scripts/run_staging.sh --env .env.staging --verbose --timeout 60
```

#### Direct Python
```bash
# Activate conda environment first
conda activate crypto-bot

# Run supervisor directly
python scripts/run_staging.py --env .env.staging --include-exec --verbose
```

## Architecture

### Process Flow

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Ingestors     │    │   Strategies    │    │   Execution     │
│                 │    │                 │    │   (PAPER)       │
│ • Data Pipeline │───▶│ • Scalper       │───▶│ • Paper Orders  │
│ • WebSocket     │    │ • Trend Follow  │    │ • Confirmations │
│ • Redis Streams │    │ • Momentum      │    │ • Monitoring    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
    md:orderbook            signals:staging        exec:paper:confirms
    md:trades
    md:spread
```

### Redis Streams

- **Market Data**: `md:orderbook`, `md:trades`, `md:spread`, `md:candles`
- **Signals**: `signals:staging`
- **Execution**: `exec:paper:confirms`

## Configuration

### Environment Variables

Key environment variables for staging:

```bash
ENVIRONMENT=staging
MODE=PAPER
REDIS_URL=redis://localhost:6379/1
TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD
LOG_LEVEL=INFO
```

### Process Manifests

Process definitions are stored in JSON files:

- `procfiles/staging_ingestors.json` - Market data ingestors
- `procfiles/staging_strategies.json` - Signal/strategy agents
- `procfiles/staging_execution.json` - Execution agents (paper mode)

### Configuration Overrides

Staging-specific configuration is in `config/overrides/staging.yaml`:

- **Safety**: PAPER mode only, conservative risk limits
- **Performance**: Reduced requirements for staging
- **Monitoring**: Staging-specific thresholds
- **Features**: Disabled ML/AI for faster startup

## Health Verification

### Ingestor Health
- ✅ WebSocket connections established
- ✅ Recent data in `md:*` streams (within 30s)
- ✅ Redis publish operations successful

### Strategy Health
- ✅ Agents consuming from `md:*` streams
- ✅ Signals published to `signals:staging`
- ✅ Latency within acceptable limits

### Execution Health
- ✅ Paper mode confirmed (no live orders)
- ✅ Confirmations written to `exec:paper:confirms`
- ✅ No LIVE endpoint references

## Monitoring

### Logs
- Each process logs to `logs/<name>.log`
- Supervisor logs to console
- Log rotation configured for staging

### Metrics
- Heartbeat metrics every 30s
- Redis stream health checks
- Process status monitoring

### Health Checks
- Redis connectivity
- Stream data freshness
- Process readiness verification

## Safety Features

### Staging Safeguards
1. **Environment Validation**: Must be `ENVIRONMENT=staging`
2. **Mode Validation**: Must be `MODE=PAPER`
3. **No Live Orders**: Execution agent runs in paper mode only
4. **Conservative Limits**: Reduced position sizes and risk limits
5. **Dry Run Mode**: All operations are simulated

### Error Handling
- Process failure detection and restart
- Graceful shutdown on signals
- Timeout handling for readiness checks
- Circuit breakers for external services

## Troubleshooting

### Common Issues

1. **Redis Connection Failed**
   ```bash
   # Check Redis is running
   redis-cli ping
   
   # Check URL in .env.staging
   REDIS_URL=redis://localhost:6379/1
   ```

2. **Conda Environment Not Found**
   ```bash
   # Create environment
   conda create -n crypto-bot python=3.10
   conda activate crypto-bot
   ```

3. **Process Not Ready**
   - Check logs in `logs/` directory
   - Verify environment variables
   - Check Redis connectivity

4. **Permission Denied (POSIX)**
   ```bash
   # Make scripts executable
   chmod +x scripts/run_staging.sh
   ```

### Debug Mode

Run with verbose logging:
```bash
python scripts/run_staging.py --env .env.staging --verbose
```

### Manual Process Testing

Test individual processes:
```bash
# Data pipeline
python scripts/run_data_pipeline.py

# Signal analyst
STRATEGY=scalping SYMBOL=BTC/USD python scripts/run_signal_analyst.py

# Execution agent
MODE=PAPER python scripts/run_execution_agent.py
```

## Development

### Adding New Processes

1. Create runner script in `scripts/`
2. Add process definition to appropriate manifest in `procfiles/`
3. Update supervisor if needed

### Modifying Configuration

1. Update `config/overrides/staging.yaml` for staging-specific settings
2. Update `env.staging.template` for environment variables
3. Test with staging pipeline

### Testing Changes

1. Run staging pipeline with changes
2. Verify all health checks pass
3. Check logs for any issues
4. Validate no live orders are placed

## Production Promotion

After successful 24-72h staging run:

1. **Verify Metrics**: All health checks passing
2. **Review Logs**: No errors or warnings
3. **Check Performance**: Latency and throughput acceptable
4. **Validate Safety**: No live orders detected
5. **Update Configuration**: Switch to production settings
6. **Deploy**: Use production deployment process

## Support

For issues or questions:

1. Check logs in `logs/` directory
2. Review this documentation
3. Check configuration files
4. Verify environment setup
5. Test individual components

## File Structure

```
crypto_ai_bot/
├── scripts/
│   ├── run_staging.py              # Main supervisor
│   ├── run_staging.sh              # POSIX wrapper
│   ├── windows/
│   │   └── run_staging.ps1         # Windows wrapper
│   ├── run_data_pipeline.py        # Data pipeline runner
│   ├── run_signal_analyst.py       # Signal analyst runner
│   └── run_execution_agent.py      # Execution agent runner
├── procfiles/
│   ├── staging_ingestors.json      # Ingestor processes
│   ├── staging_strategies.json     # Strategy processes
│   └── staging_execution.json      # Execution processes
├── config/
│   └── overrides/
│       └── staging.yaml            # Staging configuration
├── env.staging.template            # Environment template
└── logs/                           # Process logs
```

