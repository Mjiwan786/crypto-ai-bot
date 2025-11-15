# Crypto AI Bot - Development Environment Setup

## Prerequisites

- **Python**: 3.10+ (Currently using 3.10.18)
- **Conda**: Anaconda or Miniconda installed
- **Git**: For version control
- **Redis Cloud**: Account with TLS certificate

## Quick Start (Windows)

### 1. Create Conda Environment from Scratch

```powershell
# Create new conda environment with Python 3.10
conda create -n crypto-bot python=3.10 -y

# Activate environment
conda activate crypto-bot

# Navigate to project directory
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration

```powershell
# Copy the example environment file
copy .env.example .env

# Edit .env with your credentials (use notepad, VS Code, etc.)
notepad .env
```

**Required Environment Variables:**

| Variable | Description | Example/Notes |
|----------|-------------|---------------|
| `REDIS_URL` | Redis Cloud connection string (TLS) | `rediss://default:PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818` |
| `REDIS_TLS` | Enable TLS (auto-detected from rediss://) | `true` |
| `REDIS_CA_CERT_PATH` | Path to Redis CA certificate | `config/certs/redis_ca.pem` |
| `KRAKEN_API_KEY` | Kraken API key | Get from kraken.com/u/settings/api |
| `KRAKEN_API_SECRET` | Kraken API secret | Get from kraken.com/u/settings/api |
| `KRAKEN_SANDBOX` | Use sandbox for testing | `true` (safe), `false` (production) |
| `TRADING_MODE` | Trading mode | `PAPER` (safe), `LIVE` (real money) |
| `LOG_LEVEL` | Logging level | `INFO`, `DEBUG`, `WARNING`, `ERROR` |

**For LIVE Trading (⚠️ REAL MONEY):**
```bash
TRADING_MODE=LIVE
LIVE_TRADING_CONFIRMATION=I-accept-the-risk
KRAKEN_SANDBOX=false
```

### 3. Redis Cloud TLS Certificate Setup

```powershell
# Ensure certificate exists at the correct path
dir config\certs\redis_ca.pem

# If missing, download from Redis Cloud dashboard:
# 1. Log into Redis Cloud: https://app.redislabs.com
# 2. Navigate to your database
# 3. Download CA certificate
# 4. Save to: config\certs\redis_ca.pem
```

### 4. Verify Installation

```powershell
# Check Python version
python --version
# Expected: Python 3.10.18 (or 3.10+)

# Verify conda environment is active
conda info --envs
# crypto-bot should have an asterisk (*)

# Test imports
python -c "import redis, ccxt, pandas, numpy; print('✅ Core dependencies OK')"

# Run preflight checks
python scripts/preflight.py
```

### 5. Local Run Commands

#### Paper Trading (Safe - Simulated Trades)
```powershell
# Activate conda environment
conda activate crypto-bot

# Dry run (config validation only)
python scripts/start_trading_system.py --mode paper --dry-run

# Start paper trading system
python scripts/start_trading_system.py --mode paper

# Start with debug logging
python scripts/start_trading_system.py --mode paper --debug

# Start with specific strategy
python scripts/start_trading_system.py --mode paper --strategy momentum
```

#### Live Trading (⚠️ REAL MONEY - Requires Confirmation)
```powershell
# Set environment variables (PowerShell)
$env:MODE="live"
$env:LIVE_TRADING_CONFIRMATION="I-accept-the-risk"

# Start live trading
python scripts/start_trading_system.py --mode live
```

#### Backtesting
```powershell
# Run backtest with bar reaction strategy
python scripts/run_backtest.py

# Run backtest with specific parameters
python scripts/backtest.py --strategy bar_reaction_5m --start 2025-01-01 --end 2025-01-31
```

#### Health Checks
```powershell
# Check Redis connectivity
python scripts/redis_cloud_smoke.py

# Run comprehensive health checks
python scripts/health.py

# Monitor Redis streams
python scripts/monitor_redis_streams.py
```

## Project Structure

```
crypto_ai_bot/
├── agents/              # Trading agents (execution, risk, scheduler)
├── ai_engine/           # ML models, regime detection, strategy selection
├── backtesting/         # Backtesting engine and results
├── config/              # Configuration files (YAML, env loaders)
│   └── certs/          # TLS certificates (redis_ca.pem)
├── orchestration/       # Master orchestrator & LangGraph workflow
├── scripts/             # Utility scripts (startup, health, backtest)
├── strategies/          # Trading strategies (breakout, momentum, etc.)
├── tests/               # Unit and integration tests
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (DO NOT COMMIT)
└── .env.example         # Example environment template
```

## Dependency Management

### Core Dependencies
```txt
ccxt==4.4.98              # Exchange integration
redis==5.0.8              # Redis client with TLS support
pandas==2.3.1             # Data manipulation
numpy==2.1.3              # Numerical computing
ta-lib==0.6.4             # Technical analysis indicators
scikit-learn==1.7.1       # Machine learning
xgboost==3.0.3            # Gradient boosting
```

### Installing Additional Dependencies
```powershell
# Install from requirements.txt
pip install -r requirements.txt

# Install specific package
pip install package-name==version

# Freeze current environment
pip freeze > requirements-lock.txt
```

## Troubleshooting

### Conda Environment Not Found
```powershell
# List all conda environments
conda env list

# If crypto-bot doesn't exist, create it:
conda create -n crypto-bot python=3.10 -y
conda activate crypto-bot
pip install -r requirements.txt
```

### Redis Connection Issues
```powershell
# Test Redis connection with redis-cli
redis-cli -u rediss://default:PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config\certs\redis_ca.pem PING

# Expected output: PONG

# Test with Python script
python scripts/redis_cloud_smoke.py
```

### Import Errors
```powershell
# Ensure you're in the correct conda environment
conda activate crypto-bot

# Reinstall requirements
pip install --upgrade -r requirements.txt

# Check for missing packages
python -c "import MODULE_NAME"
```

### TA-Lib Installation (Windows)
```powershell
# If ta-lib fails to install, download precompiled wheel:
# 1. Visit: https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib
# 2. Download: TA_Lib‑0.6.4‑cp310‑cp310‑win_amd64.whl
# 3. Install: pip install TA_Lib‑0.6.4‑cp310‑cp310‑win_amd64.whl
```

## Testing

```powershell
# Run all tests
pytest

# Run specific test module
pytest tests/test_bar_reaction_agent.py

# Run with coverage
pytest --cov=. --cov-report=html

# Run integration tests only
pytest tests/smoke/
```

## Docker Alternative (Optional)

```powershell
# Build Docker image
docker-compose build

# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

## Emergency Stop

If the system is running and you need to stop immediately:

1. **Keyboard Interrupt**: Press `Ctrl+C` in the terminal
2. **Environment Variable**: Set `KRAKEN_EMERGENCY_STOP=true` in `.env`
3. **Redis Killswitch**: Set key `emergency:stop` in Redis

## Next Steps

1. ✅ Setup conda environment
2. ✅ Configure `.env` with credentials
3. ✅ Verify Redis connectivity
4. ✅ Run preflight checks
5. ✅ Start paper trading system
6. 📊 Monitor logs and Redis streams
7. 🎯 Review backtest results
8. ⚠️ Only enable LIVE trading after thorough testing

## Support & References

- **PRD**: [PRD-001: Crypto AI Bot - Core Intelligence Engine](docs/PRD-001-CRYPTO-AI-BOT.md)
- **Operations Runbook**: `OPERATIONS_RUNBOOK.md`
- **Backtesting Guide**: `BACKTESTING_GUIDE.md`
- **Paper Trading Guide**: `PAPER_TRADING_QUICKSTART.md`

## KPI Monitoring

Key metrics to track (see `docs/OPERATIONS.md`):
- **Latency**: Signal generation to Redis publish < 100ms
- **Uptime**: System availability > 99.5%
- **Stream Lag**: Redis consumer lag < 1s
- **Error Rate**: < 0.1% of operations fail

## Environment Recreation (Clean Slate)

```powershell
# Remove existing environment
conda deactivate
conda env remove -n crypto-bot

# Recreate from scratch
conda create -n crypto-bot python=3.10 -y
conda activate crypto-bot
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
pip install -r requirements.txt

# Reconfigure
copy .env.example .env
notepad .env

# Verify
python scripts/preflight.py
```

---

**PRD Compliance**: This setup guide satisfies PRD-001 requirements:
- ✅ Python 3.10+ runtime environment
- ✅ Redis Cloud TLS connectivity
- ✅ Kraken API integration
- ✅ Paper/Live trading modes with safety gates
- ✅ Comprehensive configuration management
- ✅ Testing and validation workflows
