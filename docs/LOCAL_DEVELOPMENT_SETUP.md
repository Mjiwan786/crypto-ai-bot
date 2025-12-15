# Local Development Setup Guide

Complete guide for setting up the crypto-ai-bot development environment on Windows.

## Prerequisites

- **Windows 10/11**
- **Anaconda** or Miniconda installed
- **Git** for version control
- **Visual Studio Code** (recommended IDE)
- **Redis Cloud** account (or local Redis server for testing)

## Step 1: Clone Repository

```bash
cd C:\Users\YourUsername\OneDrive\Desktop
git clone https://github.com/your-org/crypto_ai_bot.git
cd crypto_ai_bot
```

## Step 2: Create Conda Environment

The project uses a dedicated conda environment named `crypto-bot`:

```bash
# Create environment with Python 3.10
conda create -n crypto-bot python=3.10 -y

# Activate environment
conda activate crypto-bot
```

**Verify activation:**
```bash
python --version  # Should show Python 3.10.x
which python      # Should point to crypto-bot env
```

## Step 3: Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Verify key packages
pip list | grep -E "redis|websockets|pydantic|ccxt|prometheus|tensorflow"
```

**Key dependencies:**
- `redis[hiredis]==5.0.1` - Redis client with high-performance parser
- `websockets==12.0` - WebSocket client for Kraken
- `pydantic==2.5.0` - Schema validation
- `ccxt==4.1.0` - Exchange API library
- `prometheus-client==0.19.0` - Metrics export
- `tensorflow==2.14.0` - ML models (LSTM)
- `scikit-learn==1.3.2` - ML models (RandomForest)

## Step 4: Configure Environment Variables

### 4.1 Redis Cloud Setup

1. **Get Redis Cloud credentials:**
   - Host: `redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com`
   - Port: `19818`
   - Password: `<REDIS_PASSWORD>`
   - URL-encoded password: `<REDIS_PASSWORD_URL_ENCODED>`

2. **Test Redis connection:**
   ```bash
   redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 --tls --cacert config/certs/redis_ca.pem PING
   ```
   Should return: `PONG`

### 4.2 Create .env File

Copy the example environment file:

```bash
cp .env.example .env.local
```

Edit `.env.local` with your credentials:

```bash
# === TRADING CONFIGURATION ===
TRADING_MODE=paper
BOT_MODE=PAPER
ENABLE_TRADING=false
TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD

# === REDIS CLOUD ===
REDIS_URL=rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818
REDIS_PASSWORD=<REDIS_PASSWORD>
REDIS_SSL=true
REDIS_SSL_CA_CERT_PATH=config/certs/redis_ca.pem
REDIS_MAX_CONNECTIONS=30
REDIS_SOCKET_TIMEOUT=10

# === EXCHANGE - KRAKEN ===
KRAKEN_API_KEY=your_kraken_api_key_here
KRAKEN_API_SECRET=your_kraken_secret_here
KRAKEN_WS_URL=wss://ws.kraken.com

# === LOGGING ===
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_DIR=logs

# === ML MODELS ===
ML_ENABLED=true
ML_MODELS_DIR=models
ML_TREND_MODEL_PATH=models/prod_trend_model_v15.h5
ML_SCALPING_MODEL_PATH=models/prod_scalp_model_v8.h5
```

**Security note:** Never commit `.env.local` to git. It's already in `.gitignore`.

### 4.3 Download Redis CA Certificate

The TLS certificate is included in the repo:

```bash
# Verify certificate exists
ls config/certs/redis_ca.pem
```

If missing, extract from:
```bash
unzip path/to/redis_ca.zip -d config/certs/
```

## Step 5: Verify Installation

### 5.1 Run Preflight Check

```bash
python preflight_check.py
```

**Expected output:**
```
✅ Environment loaded successfully
✅ Redis connection: OK
✅ Kraken API connection: OK
✅ Trading pairs configured: 5
✅ All checks passed!
```

### 5.2 Test WebSocket Connection

```bash
python scripts/test_kraken_ws.py
```

Should connect to Kraken and stream market data.

### 5.3 Test Model Loading

```bash
python -c "from ml.async_ensemble import AsyncEnsemblePredictor; print('✅ Ensemble loaded')"
```

## Step 6: Run Tests

### Unit Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test
pytest tests/unit/test_async_ensemble.py -v
```

### Integration Tests

```bash
# Run integration tests
pytest tests/integration/ -v

# Run signal pipeline tests
pytest tests/integration/test_signal_pipeline.py -v
```

### Coverage Report

```bash
pytest tests/ --cov=agents --cov=ml --cov=models --cov-report=html

# Open coverage report
start htmlcov/index.html  # Windows
```

## Step 7: Start Development Server

### 7.1 Start Signal Pipeline

```bash
# Activate conda environment
conda activate crypto-bot

# Run integrated pipeline
python agents/core/integrated_signal_pipeline.py
```

**Expected output:**
```
INFO:IntegratedSignalPipeline:Starting IntegratedSignalPipeline...
INFO:WebSocket:Connected to wss://ws.kraken.com
INFO:Redis:Connected to Redis Cloud
INFO:Pipeline:Processing signals for 5 pairs...
```

### 7.2 Monitor Redis Streams

In a separate terminal:

```bash
# Activate environment
conda activate crypto-bot

# Watch signals stream
python scripts/watch_redis_stream.py signals:paper
```

### 7.3 Check Metrics

Navigate to: `http://localhost:9108/metrics`

Should show Prometheus metrics:
```
kraken_ws_connections_total{state="connected"} 1
signals_published_total{pair="BTC/USD"} 42
signal_generation_latency_ms_sum 1234.5
```

## Step 8: Development Workflow

### 8.1 Code Style

The project uses:
- **Black** for code formatting
- **Ruff** for linting
- **mypy** for type checking

```bash
# Format code
black agents/ ml/ models/

# Lint code
ruff check agents/ ml/ models/

# Type check
mypy agents/ ml/ models/
```

### 8.2 Pre-commit Hooks

Install pre-commit hooks:

```bash
pip install pre-commit
pre-commit install
```

Hooks will run automatically on `git commit`:
- Code formatting (Black)
- Linting (Ruff)
- Type checking (mypy)
- Test execution

### 8.3 Running Individual Components

**WebSocket only:**
```bash
python utils/kraken_ws.py
```

**Model inference only:**
```bash
python ml/async_ensemble.py
```

**Signal schema validation:**
```bash
python models/prd_signal_schema.py
```

## Step 9: Troubleshooting

### Redis Connection Issues

**Problem:** `ConnectionRefusedError` or `SSL handshake failed`

**Solutions:**
```bash
# 1. Verify credentials
redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 --tls --cacert config/certs/redis_ca.pem PING

# 2. Check certificate path
ls config/certs/redis_ca.pem

# 3. Test without TLS (local Redis only)
redis-cli -h localhost -p 6379 PING

# 4. Check firewall
Test-NetConnection -ComputerName redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com -Port 19818
```

### Kraken WebSocket Errors

**Problem:** `ConnectionClosed` or `TimeoutError`

**Solutions:**
```bash
# 1. Test connectivity
ping ws.kraken.com

# 2. Check trading pairs format
# Kraken uses BTC/USD, NOT BTCUSD

# 3. Increase timeout
# In .env: WEBSOCKET_PING_TIMEOUT=120

# 4. Enable debug logging
# In .env: LOG_LEVEL=DEBUG
```

### Model Loading Failures

**Problem:** `FileNotFoundError` for model files

**Solutions:**
```bash
# 1. Check model directory
ls models/

# 2. Download models (if missing)
# Contact team for model files or train new ones

# 3. Use mock models for testing
# Set ML_ENABLED=false in .env
```

### Import Errors

**Problem:** `ModuleNotFoundError`

**Solutions:**
```bash
# 1. Verify conda environment is activated
conda env list  # * should be next to crypto-bot

# 2. Reinstall dependencies
pip install -r requirements.txt --force-reinstall

# 3. Check PYTHONPATH
echo $PYTHONPATH  # Should include project root

# 4. Add project root to path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"  # Linux/Mac
set PYTHONPATH=%PYTHONPATH%;%CD%          # Windows
```

## Step 10: Useful Commands

### Conda Environment Management

```bash
# List environments
conda env list

# Activate
conda activate crypto-bot

# Deactivate
conda deactivate

# Export environment
conda env export > environment.yml

# Remove environment
conda env remove -n crypto-bot
```

### Git Workflow

```bash
# Create feature branch
git checkout -b feature/new-strategy

# Stage changes
git add .

# Commit (triggers pre-commit hooks)
git commit -m "feat: add new scalping strategy"

# Push to remote
git push origin feature/new-strategy
```

### Database/Redis Operations

```bash
# Clear Redis streams (CAREFUL in production!)
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem FLUSHDB

# List streams
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem --scan --pattern "signals:*"

# Get stream length
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XLEN signals:paper

# Read last 10 signals
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem XREVRANGE signals:paper + - COUNT 10
```

## Additional Resources

- **PRD-001:** [docs/PRD-001-CRYPTO-AI-BOT.md](./PRD-001-CRYPTO-AI-BOT.md)
- **Architecture:** [docs/ARCHITECTURE.md](./ARCHITECTURE.md)
- **Methodology:** [docs/METHODOLOGY.md](./METHODOLOGY.md)
- **API Reference:** [docs/API_REFERENCE.md](./API_REFERENCE.md)

## Support

**Issues:** https://github.com/your-org/crypto_ai_bot/issues
**Slack:** #crypto-bot-dev
**Email:** dev-team@yourcompany.com

---

**Last Updated:** 2025-11-17
**Maintainer:** Crypto AI Bot Team
