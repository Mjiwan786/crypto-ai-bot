# Health Checks Documentation

This document describes the health check scripts available for the crypto AI bot system. All scripts should be run in the `crypto-bot` conda environment.

## Prerequisites

1. **Conda Environment**: Ensure you're in the `crypto-bot` conda environment:
   ```bash
   conda activate crypto-bot
   ```

2. **Install Dependencies**: Install required packages for health checks:
   ```bash
   # Install health check dependencies
   pip install -r requirements_health_checks.txt
   
   # Or install individual packages
   pip install redis websockets python-dotenv psutil pydantic PyYAML ccxt numpy pandas scikit-learn joblib
   ```

3. **Environment Variables**: Ensure your `.env` file is properly configured with:
   - `REDIS_URL` (for Redis Cloud TLS connection)
   - `REDIS_PASSWORD` (if required)
   - `REDIS_CA_CERT` (path to CA certificate)
   - `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` (for exchange connectivity)
   - Other required environment variables

## Health Check Scripts

### 1. Basic Preflight Check
**Script**: `python scripts/preflight.py`

**Purpose**: Core environment validation and Redis connectivity check.

**What it checks**:
- Environment variable validation (mandatory keys, types, risk/allocations invariants)
- Redis Cloud TLS connectivity via `rediss://` URL
- Stream creation and retention policy setup
- Stream read/write smoke test (XADD/XREAD)
- Signal sources readiness for Signal Analyst
- Optional Kraken WebSocket reachability

**Usage**:
```bash
# Basic check
python scripts/preflight.py

# Verbose output
python scripts/preflight.py --verbose

# Quick check (skip slower operations)
python scripts/preflight.py --quick

# Skip network checks
python scripts/preflight.py --no-network
```

**Exit Codes**:
- `0`: All checks passed
- `2`: Soft warnings (non-fatal)
- `3`: Hard failure (fix required)

### 2. Comprehensive Preflight Check
**Script**: `python scripts/preflight_comprehensive.py`

**Purpose**: Full system readiness assessment for production deployment.

**What it checks**:
- System environment (Python version, OS, memory, disk space)
- Critical and optional dependencies
- Network connectivity and DNS resolution
- File system permissions
- Configuration validation
- Exchange connectivity and market data
- Database connections (Redis, SQL)
- Clock drift and bar alignment
- Market metadata enforcement
- Fees and slippage realism
- WebSocket readiness
- Data quality (NaN/gap scanning)
- Strategy components and indicators
- Risk management systems
- Performance benchmarks

**Usage**:
```bash
# Full comprehensive check
python scripts/preflight_comprehensive.py --full-check

# Quick check (skip performance benchmarks)
python scripts/preflight_comprehensive.py --quick

# Test specific pairs
python scripts/preflight_comprehensive.py --pairs BTC/USD ETH/USD

# Test specific exchange
python scripts/preflight_comprehensive.py --exchange kraken

# Production-grade checks
python scripts/preflight_comprehensive.py --production-grade
```

**Outputs**:
- `reports/live_readiness/preflight_comprehensive.txt` - Detailed report
- `reports/live_readiness/system_metrics.json` - Machine-readable metrics
- `reports/live_readiness/ohlcv_samples.csv` - Market data samples

### 3. Redis TLS Check
**Script**: `python scripts/check_redis_tls.py`

**Purpose**: Deep TLS validation for Redis Cloud connections.

**What it checks**:
- SSLConnection usage confirmation
- CA file and hostname verification
- Handshake metadata (protocol, version)
- Basic Redis operations (PING, KV, Streams)
- Connection pool validation

**Usage**:
```bash
python scripts/check_redis_tls.py
```

**Exit Codes**:
- `0`: TLS check passed
- `1`: TLS check failed

### 4. Redis Cloud Smoke Test
**Script**: `python scripts/redis_cloud_smoke.py`

**Purpose**: Comprehensive Redis Cloud TLS smoke test with continuous monitoring.

**What it checks**:
- Basic Redis Cloud connection
- Health check functionality
- Basic operations (SET/GET/DELETE)
- Integration helper functions
- Stream operations (XADD/XREAD)
- Continuous health monitoring

**Usage**:
```bash
# Basic smoke test
python scripts/redis_cloud_smoke.py

# Verbose output
python scripts/redis_cloud_smoke.py --verbose

# Extended duration test
python scripts/redis_cloud_smoke.py --duration 60

# Custom Redis configuration
python scripts/redis_cloud_smoke.py --url rediss://... --ca-cert /path/to/ca.pem
```

**Exit Codes**:
- `0`: All tests passed
- `1`: One or more tests failed

### 5. Kraken WebSocket Health Check
**Script**: `python scripts/kraken_ws_health.py`

**Purpose**: WebSocket connectivity and data flow validation for Kraken.

**What it checks**:
- WebSocket connection establishment
- Subscription to trade and spread channels
- Heartbeat and data freshness monitoring
- Ping/pong latency measurement
- System status detection
- Reconnect logic with jittered backoff

**Usage**:
```bash
# Basic health check
python scripts/kraken_ws_health.py

# Custom configuration
python scripts/kraken_ws_health.py --pairs BTC/USD ETH/USD --test-duration 60
```

**Exit Codes**:
- `0`: WebSocket health check passed
- `1`: WebSocket health check failed

### 6. Kraken WebSocket Test
**Script**: `python scripts/test_kraken_ws.py`

**Purpose**: Simple WebSocket connection test for Kraken.

**What it checks**:
- Basic WebSocket connection to Kraken
- Subscription to trade channel
- Message reception and display

**Usage**:
```bash
python scripts/test_kraken_ws.py
```

**Note**: This script runs indefinitely until interrupted (Ctrl+C).

### 7. ML Predictor Test
**Script**: `python -m agents.ml.predictor`

**Purpose**: Test ML model loading and prediction functionality.

**What it checks**:
- Model artifact loading
- Feature validation
- Prediction execution
- Model metadata retrieval

**Usage**:
```bash
python -m agents.ml.predictor
```

**Note**: If no model artifacts exist, the script will create test artifacts automatically.

## Running All Health Checks

To run all health checks in sequence:

```bash
# Activate conda environment
conda activate crypto-bot

# Run all health checks
echo "Running basic preflight check..."
python scripts/preflight.py --verbose

echo "Running comprehensive preflight check..."
python scripts/preflight_comprehensive.py --quick

echo "Running Redis TLS check..."
python scripts/check_redis_tls.py

echo "Running Redis Cloud smoke test..."
python scripts/redis_cloud_smoke.py --duration 30

echo "Running Kraken WebSocket health check..."
python scripts/kraken_ws_health.py

echo "Running ML predictor test..."
python -m agents.ml.predictor

echo "All health checks completed!"
```

## Troubleshooting

### Common Issues

1. **Redis Connection Failures**:
   - Verify `REDIS_URL` starts with `rediss://`
   - Check `REDIS_CA_CERT` path is correct
   - Ensure Redis Cloud firewall allows your IP

2. **Kraken API Issues**:
   - Verify API keys are set in `.env`
   - Check API key permissions
   - Ensure network connectivity to `api.kraken.com`

3. **Model Artifact Issues**:
   - Check `models/` directory exists
   - Verify model files are present and valid
   - Run with `--verbose` for detailed error messages

4. **Environment Issues**:
   - Ensure all required environment variables are set
   - Check Python version compatibility (3.8+)
   - Verify all dependencies are installed

### Log Files

Health check results are typically logged to:
- `reports/live_readiness/preflight_comprehensive.txt`
- Console output with timestamps
- System logs (if configured)

## Exit Code Reference

- `0`: Success
- `1`: General failure
- `2`: Conditional pass (warnings present)
- `3`: Hard failure (fix required)
- `130`: Interrupted by user (Ctrl+C)

## Best Practices

1. **Run health checks before deployment**
2. **Monitor health check results in CI/CD pipelines**
3. **Set up alerts for health check failures**
4. **Regularly update health check scripts as system evolves**
5. **Document any custom health check requirements**
