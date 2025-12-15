# Crypto-AI-Bot Setup Guide

**Version:** 1.0.0
**Last Updated:** 2025-11-17
**Platform:** AI-Predicted-Signals

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Environment Configuration](#environment-configuration)
5. [Local Development](#local-development)
6. [Production Deployment](#production-deployment)
7. [Verification](#verification)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The **Crypto-AI-Bot** is the ML inference and signal generation engine of the AI-Predicted-Signals platform. It:

- Ingests real-time market data from exchanges (Kraken WebSocket)
- Engineers 128 features from price, volume, and order book data
- Runs ML ensemble (LSTM + Transformer + CNN) for signal prediction
- Publishes probability-rich signals to Redis streams

This guide provides step-by-step instructions for setting up and running the system locally and in production.

---

## Prerequisites

### System Requirements

- **Operating System**: Windows 10/11, Linux (Ubuntu 20.04+), or macOS 12+
- **RAM**: Minimum 8GB (16GB recommended for training)
- **Storage**: Minimum 5GB free space
- **CPU**: Multi-core processor (4+ cores recommended)
- **GPU**: Optional (NVIDIA GPU with CUDA for faster inference)

### Required Software

1. **Python 3.10+**
   - Download: https://www.python.org/downloads/
   - Verify: `python --version` should show 3.10 or higher

2. **Conda** (Recommended for environment management)
   - Download Miniconda: https://docs.conda.io/en/latest/miniconda.html
   - Or Anaconda: https://www.anaconda.com/download
   - Verify: `conda --version`

3. **Git**
   - Download: https://git-scm.com/downloads
   - Verify: `git --version`

4. **Redis CLI** (Optional, for testing Redis connection)
   - Windows: https://github.com/microsoftarchive/redis/releases
   - Linux: `sudo apt-get install redis-tools`
   - macOS: `brew install redis`

### Required Accounts & Credentials

1. **Redis Cloud** (Managed Redis instance)
   - URL: `rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818`
   - SSL/TLS encryption enabled
   - Certificate file provided in handoff package

2. **Kraken API** (Optional - for live trading)
   - API Key and Private Key
   - Provided in handoff package

3. **AWS S3** (Optional - for model storage)
   - Access Key and Secret Key
   - Provided in handoff package

---

## Installation

### Step 1: Clone Repository

```bash
# Clone the repository
git clone <repository-url>
cd crypto_ai_bot

# Verify you're in the correct directory
pwd
# Should show: /path/to/crypto_ai_bot
```

### Step 2: Create Conda Environment

```bash
# Create new conda environment with Python 3.10
conda create -n crypto-bot python=3.10 -y

# Activate environment
conda activate crypto-bot

# Verify activation
which python  # Linux/Mac
where python  # Windows
# Should point to conda env: /path/to/conda/envs/crypto-bot/bin/python
```

### Step 3: Install PyTorch

**For CPU-only (recommended for most users):**

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

**For GPU (NVIDIA CUDA 11.8):**

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

**For GPU (NVIDIA CUDA 12.1):**

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

Verify PyTorch installation:

```bash
python -c "import torch; print(f'PyTorch version: {torch.__version__}')"
# Expected: PyTorch version: 2.1.0+cpu (or +cu118, +cu121)
```

### Step 4: Install Dependencies

```bash
# Install core dependencies
pip install pandas numpy scikit-learn scipy redis

# Install additional libraries
pip install boto3 tqdm requests ta-lib ccxt websocket-client

# Install development and testing tools
pip install pytest pytest-cov pytest-timeout pytest-xdist
pip install sseclient-py psutil

# Install in development mode (enables editing code)
pip install -e .
```

Verify installation:

```bash
python -c "import pandas, numpy, sklearn, redis; print('All dependencies installed successfully')"
```

### Step 5: Download Pre-trained Models

The ML models are stored in the `ml/models/` directory. If not present:

**Option 1: Download from AWS S3 (if provided)**

```bash
# Set AWS credentials
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"

# Download models
python scripts/download_models.py --source s3 --bucket crypto-ai-bot-models
```

**Option 2: Use provided models**

Models should be included in the handoff package:

```bash
# Verify models exist
ls -la ml/models/
# Should show:
# - lstm_model.pt
# - transformer_model.pt
# - cnn_model.pt
# - feature_scaler.pkl
```

If models are not present, contact support for access.

---

## Environment Configuration

### Step 1: Copy Environment Template

```bash
# Copy example environment file
cp .env.example .env

# Or for specific environments
cp env.prod.example .env.prod
cp env.staging.example .env.staging
```

### Step 2: Configure Environment Variables

Edit `.env` file with your credentials:

```bash
# Open in your preferred editor
nano .env       # Linux/Mac
notepad .env    # Windows
code .env       # VS Code
```

**Required Variables:**

```bash
# ============================================
# REDIS CONFIGURATION (REQUIRED)
# ============================================
REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818"
REDIS_SSL=true
REDIS_SSL_CA_CERT="config/certs/redis_ca.pem"

# ============================================
# TRADING MODE (REQUIRED)
# ============================================
# Options: paper, live
TRADING_MODE=paper

# ============================================
# TRADING PAIRS (REQUIRED)
# ============================================
# Comma-separated list of trading pairs
TRADING_PAIRS="BTC/USDT,ETH/USDT,SOL/USDT"

# ============================================
# TIMEFRAMES (REQUIRED)
# ============================================
# Comma-separated list of timeframes
TIMEFRAMES="15s,1m,5m,15m"

# ============================================
# ML MODELS (REQUIRED)
# ============================================
LSTM_MODEL_PATH="ml/models/lstm_model.pt"
TRANSFORMER_MODEL_PATH="ml/models/transformer_model.pt"
CNN_MODEL_PATH="ml/models/cnn_model.pt"
FEATURE_SCALER_PATH="ml/models/feature_scaler.pkl"

# ============================================
# KRAKEN API (OPTIONAL - for live trading)
# ============================================
KRAKEN_API_KEY=""
KRAKEN_PRIVATE_KEY=""

# ============================================
# RISK MANAGEMENT (REQUIRED)
# ============================================
MAX_POSITION_SIZE=0.75          # 75% of capital per position
CONFIDENCE_THRESHOLD=0.60       # Minimum 60% confidence
MAX_DRAWDOWN_PCT=10.0           # 10% max drawdown
STOP_LOSS_PCT=2.0               # 2% stop loss
TAKE_PROFIT_PCT=4.0             # 4% take profit

# ============================================
# PERFORMANCE (OPTIONAL)
# ============================================
ENABLE_LATENCY_TRACKING=true
LATENCY_MS_MAX=100.0
LOG_LEVEL=INFO

# ============================================
# AWS S3 (OPTIONAL - for model storage)
# ============================================
AWS_ACCESS_KEY_ID=""
AWS_SECRET_ACCESS_KEY=""
S3_MODEL_BUCKET="crypto-ai-bot-models"
```

### Step 3: Install Redis SSL Certificate

The Redis Cloud instance requires SSL/TLS encryption. Install the certificate:

```bash
# Create certs directory
mkdir -p config/certs

# Copy certificate file (provided in handoff package)
cp /path/to/redis_ca.pem config/certs/

# Verify certificate exists
ls -la config/certs/redis_ca.pem

# Set permissions (Linux/Mac only)
chmod 600 config/certs/redis_ca.pem
```

### Step 4: Test Redis Connection

```bash
# Test connection with redis-cli
redis-cli -u "rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818" \
  --tls \
  --cacert config/certs/redis_ca.pem \
  ping

# Expected output: PONG
```

Or test with Python:

```bash
python -c "
import redis
import os
from dotenv import load_dotenv

load_dotenv()
redis_url = os.getenv('REDIS_URL')
r = redis.from_url(redis_url, ssl_cert_reqs='required', ssl_ca_certs='config/certs/redis_ca.pem')
print(r.ping())
# Expected: True
"
```

---

## Local Development

### Step 1: Activate Environment

```bash
# Always activate conda environment before running
conda activate crypto-bot
```

### Step 2: Run Preflight Checks

```bash
# Run system checks
python scripts/preflight.py

# This verifies:
# - Python version (3.10+)
# - All dependencies installed
# - Environment variables set
# - Redis connection working
# - ML models present
# - Disk space available
```

Expected output:

```
✅ Python version: 3.10.18
✅ All dependencies installed
✅ Environment variables configured
✅ Redis connection: CONNECTED
✅ ML models found: 4/4
✅ Disk space: 15GB available
✅ All checks passed!
```

### Step 3: Start Signal Generator (Paper Mode)

```bash
# Start in paper trading mode
python main.py --mode paper

# Or with explicit config
python main.py --config .env --mode paper --pairs BTC/USDT,ETH/USDT
```

Expected output:

```
[2025-11-17 12:00:00] INFO: Crypto-AI-Bot v1.0.0 starting...
[2025-11-17 12:00:00] INFO: Mode: PAPER
[2025-11-17 12:00:00] INFO: Trading pairs: BTC/USDT, ETH/USDT
[2025-11-17 12:00:00] INFO: Redis connected: redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818
[2025-11-17 12:00:01] INFO: Loading LSTM model... ✓
[2025-11-17 12:00:02] INFO: Loading Transformer model... ✓
[2025-11-17 12:00:03] INFO: Loading CNN model... ✓
[2025-11-17 12:00:04] INFO: Subscribing to Kraken WebSocket...
[2025-11-17 12:00:05] INFO: Signal generation active
```

### Step 4: Monitor Signal Generation

**In another terminal:**

```bash
# Activate environment
conda activate crypto-bot

# Monitor Redis streams
python scripts/monitor_signals.py

# Or use redis-cli
redis-cli -u "$REDIS_URL" --tls --cacert config/certs/redis_ca.pem XREAD COUNT 10 STREAMS ml_signals:BTC/USDT:15m 0
```

### Step 5: Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test categories
pytest tests/test_signal_generation.py -v    # Unit tests
pytest tests/test_integration.py -v          # Integration tests
pytest tests/test_performance.py -v          # Performance tests
pytest tests/test_end_to_end.py -v           # E2E tests

# Run with coverage
pytest tests/ --cov=ml --cov-report=html

# Open coverage report
open htmlcov/index.html  # Mac
start htmlcov/index.html # Windows
```

### Step 6: View Logs

```bash
# Tail main log file
tail -f logs/crypto_ai_bot.log

# View signal generation logs
tail -f logs/signals.log

# View error logs
tail -f logs/errors.log

# On Windows
type logs\crypto_ai_bot.log
```

---

## Production Deployment

### Option 1: Docker Deployment (Recommended)

#### Step 1: Build Docker Image

```bash
# Build image
docker build -t crypto-ai-bot:latest .

# Verify image
docker images | grep crypto-ai-bot
```

#### Step 2: Create Production Environment File

```bash
# Copy production template
cp env.prod.example .env.prod

# Edit with production credentials
nano .env.prod
```

#### Step 3: Run with Docker Compose

```bash
# Start in detached mode
docker compose -f docker-compose.prod.yml up -d

# View logs
docker compose logs -f crypto-ai-bot

# Check health
docker compose ps
# Should show: crypto-ai-bot (healthy)
```

#### Step 4: Monitor Production

```bash
# View real-time logs
docker compose logs -f

# Check resource usage
docker stats crypto-ai-bot

# Restart if needed
docker compose restart crypto-ai-bot
```

### Option 2: Direct Python Deployment

#### Step 1: Setup Production Server

```bash
# SSH into production server
ssh user@your-production-server.com

# Clone repository
git clone <repository-url>
cd crypto_ai_bot

# Create conda environment
conda create -n crypto-bot python=3.10 -y
conda activate crypto-bot

# Install dependencies (same as local installation)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

#### Step 2: Configure Production Environment

```bash
# Copy production config
cp env.prod.example .env.prod

# Edit with production credentials
nano .env.prod

# Install Redis certificate
mkdir -p config/certs
cp /path/to/redis_ca.pem config/certs/
chmod 600 config/certs/redis_ca.pem
```

#### Step 3: Run as Systemd Service (Linux)

Create systemd service file:

```bash
sudo nano /etc/systemd/system/crypto-ai-bot.service
```

Add the following:

```ini
[Unit]
Description=Crypto AI Bot - Signal Generator
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/crypto_ai_bot
Environment="PATH=/path/to/conda/envs/crypto-bot/bin"
EnvironmentFile=/path/to/crypto_ai_bot/.env.prod
ExecStart=/path/to/conda/envs/crypto-bot/bin/python main.py --mode paper
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start service:

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable crypto-ai-bot

# Start service
sudo systemctl start crypto-ai-bot

# Check status
sudo systemctl status crypto-ai-bot

# View logs
sudo journalctl -u crypto-ai-bot -f
```

#### Step 4: Run as PM2 Process (Alternative)

```bash
# Install PM2
npm install -g pm2

# Create PM2 config
cat > ecosystem.config.js << 'EOF'
module.exports = {
  apps: [{
    name: 'crypto-ai-bot',
    script: 'main.py',
    interpreter: '/path/to/conda/envs/crypto-bot/bin/python',
    args: '--mode paper',
    env: {
      REDIS_URL: 'rediss://...',
      TRADING_MODE: 'paper',
      // ... other env vars
    },
    autorestart: true,
    max_restarts: 10,
    min_uptime: '10s'
  }]
}
EOF

# Start with PM2
pm2 start ecosystem.config.js

# View logs
pm2 logs crypto-ai-bot

# Monitor
pm2 monit

# Save PM2 config to restart on boot
pm2 save
pm2 startup
```

### Option 3: Cloud Deployment (Fly.io)

While the signals-api is deployed on Fly.io, the crypto-ai-bot typically runs on a dedicated server or local machine for lower latency. However, if you want to deploy on Fly.io:

#### Step 1: Install Fly CLI

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Login
fly auth login
```

#### Step 2: Create Fly App

```bash
# Initialize Fly app
fly launch --name crypto-ai-bot-ml

# Don't deploy yet, configure first
```

#### Step 3: Set Secrets

```bash
# Set environment secrets
fly secrets set REDIS_URL="rediss://..." -a crypto-ai-bot-ml
fly secrets set TRADING_MODE="paper" -a crypto-ai-bot-ml
fly secrets set KRAKEN_API_KEY="..." -a crypto-ai-bot-ml
fly secrets set KRAKEN_PRIVATE_KEY="..." -a crypto-ai-bot-ml
```

#### Step 4: Deploy

```bash
# Deploy to Fly.io
fly deploy -a crypto-ai-bot-ml

# Check status
fly status -a crypto-ai-bot-ml

# View logs
fly logs -a crypto-ai-bot-ml
```

---

## Verification

### Step 1: Health Check

```bash
# Check system is running
python scripts/health_check.py

# Expected output:
# ✅ System Status: RUNNING
# ✅ Redis: CONNECTED
# ✅ Models: LOADED (3/3)
# ✅ Signal Generation: ACTIVE
# ✅ Last Signal: 5 seconds ago
```

### Step 2: Verify Signal Publishing

```bash
# Monitor Redis streams
python scripts/monitor_signals.py --stream ml_signals:BTC/USDT:15m --count 10

# Expected: List of recent signals with timestamps
```

### Step 3: Check Latency

```bash
# Run latency test
python scripts/latency_test.py

# Expected output:
# ✅ Feature Engineering: 45ms
# ✅ ML Inference: 62ms
# ✅ Redis Publish: 18ms
# ✅ Total E2E Latency: 125ms (target: <500ms)
```

### Step 4: Run Integration Tests

```bash
# Run full integration test suite
pytest tests/test_integration.py -v

# Should see all tests passing
```

---

## Troubleshooting

### Issue 1: Redis Connection Error

**Error:**

```
redis.ConnectionError: Error connecting to Redis
```

**Solutions:**

1. **Verify Redis URL:**

```bash
echo $REDIS_URL
# Should show: rediss://default:<REDIS_PASSWORD>@redis-19818...
```

2. **Check certificate:**

```bash
ls -la config/certs/redis_ca.pem
# Should exist and be readable
```

3. **Test connection:**

```bash
redis-cli -u "$REDIS_URL" --tls --cacert config/certs/redis_ca.pem ping
# Expected: PONG
```

4. **Check firewall:**

```bash
# Ensure port 19818 is open
telnet redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com 19818
```

### Issue 2: Model Not Found

**Error:**

```
FileNotFoundError: [Errno 2] No such file or directory: 'ml/models/lstm_model.pt'
```

**Solutions:**

1. **Verify models exist:**

```bash
ls -la ml/models/
```

2. **Download models:**

```bash
python scripts/download_models.py --source s3 --bucket crypto-ai-bot-models
```

3. **Check environment variables:**

```bash
echo $LSTM_MODEL_PATH
# Should point to: ml/models/lstm_model.pt
```

### Issue 3: Import Errors

**Error:**

```
ModuleNotFoundError: No module named 'ml'
```

**Solutions:**

1. **Verify conda environment:**

```bash
conda activate crypto-bot
which python  # Should point to crypto-bot env
```

2. **Reinstall in development mode:**

```bash
pip install -e .
```

3. **Add to PYTHONPATH:**

```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Issue 4: High Latency

**Issue:** Signal generation taking >500ms

**Solutions:**

1. **Check model device:**

```python
# Ensure models are on GPU if available
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

2. **Reduce batch size:**

```bash
# Edit config
export BATCH_SIZE=1
```

3. **Disable debug logging:**

```bash
export LOG_LEVEL=WARNING
```

4. **Check CPU usage:**

```bash
top  # Linux/Mac
# Look for python process using high CPU
```

### Issue 5: Memory Errors

**Error:**

```
RuntimeError: CUDA out of memory
```

**Solutions:**

1. **Switch to CPU:**

```bash
export DEVICE=cpu
```

2. **Reduce sequence length:**

```bash
export SEQUENCE_LENGTH=50  # Default: 100
```

3. **Clear cache:**

```python
import torch
torch.cuda.empty_cache()
```

### Issue 6: WebSocket Connection Drops

**Error:**

```
WebSocket connection closed unexpectedly
```

**Solutions:**

1. **Check internet connection:**

```bash
ping api.kraken.com
```

2. **Verify API credentials:**

```bash
echo $KRAKEN_API_KEY
# Should not be empty if using live mode
```

3. **Enable reconnection:**

```bash
export ENABLE_WS_RECONNECT=true
export WS_RECONNECT_DELAY=5
```

### Issue 7: Signals Not Appearing in Redis

**Issue:** System running but no signals in Redis

**Solutions:**

1. **Check confidence threshold:**

```bash
# Lower threshold for testing
export CONFIDENCE_THRESHOLD=0.50
```

2. **Verify stream keys:**

```bash
redis-cli -u "$REDIS_URL" --tls --cacert config/certs/redis_ca.pem KEYS "ml_signals:*"
```

3. **Check logs for errors:**

```bash
tail -f logs/errors.log
```

4. **Monitor signal generation:**

```bash
python scripts/monitor_signals.py --verbose
```

---

## Support

### Documentation

- **[PLATFORM_OVERVIEW.md](../../PLATFORM_OVERVIEW.md)** - Complete platform overview
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Detailed architecture
- **[API_REFERENCE.md](API_REFERENCE.md)** - API documentation
- **[QA_TESTING_COMPLETE.md](QA_TESTING_COMPLETE.md)** - Testing documentation

### Contact

- **30-Day Support**: Contact support team with any issues
- **GitHub Issues**: Create issue with `[SETUP]` prefix
- **Email**: Support email provided in handoff package

---

## Next Steps

After successful setup:

1. **Setup signals-api**: Follow [signals-api setup guide](../../signals_api/docs/SETUP_GUIDE.md)
2. **Setup signals-site**: Follow [signals-site setup guide](../../signals-site/docs/SETUP_GUIDE.md)
3. **Configure monitoring**: Setup Prometheus and Grafana
4. **Test end-to-end**: Verify complete signal flow
5. **Deploy to production**: Follow production deployment checklist

---

**Document Version:** 1.0.0
**Last Updated:** 2025-11-17
**Status:** ✅ PRODUCTION READY
