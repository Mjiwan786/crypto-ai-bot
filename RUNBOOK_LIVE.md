# RUNBOOK: Live Trading Operations

> **📋 System Requirements: [PRD-001: Crypto AI Bot - Core Intelligence Engine](docs/PRD-001-CRYPTO-AI-BOT.md)**

**Environment**: PRODUCTION
**Mode**: LIVE TRADING (Real Money)
**Status**: ⚠️ USE WITH EXTREME CAUTION
**Last Updated**: 2025-11-11

---

## ⚠️ CRITICAL WARNING

**This runbook is for LIVE TRADING with REAL MONEY.**
- All trades execute on live markets with real capital
- Losses are real and irreversible
- Always verify paper trading results first
- Have a kill switch plan ready
- **All operations must comply with PRD-001 requirements** (risk limits, SLOs, testing standards)

---

## Quick Reference: GO LIVE Checklist

**One-Line GO LIVE Checklist:**
```
✅ .env.prod configured → ✅ Paper trial passed → ✅ Metrics healthy → ✅ Kill switch tested → ✅ Set LIVE_MODE=true → 🚀 GO
```

**Rollback (Emergency Stop):**
```bash
# IMMEDIATE STOP
export LIVE_MODE=false
pkill -f run_live_scalper.py

# Or edit .env.prod:
LIVE_MODE=false
```

---

## Table of Contents

1. [Environment Setup](#1-environment-setup)
2. [Pre-Flight Checklist](#2-pre-flight-checklist)
3. [Starting Live Trading](#3-starting-live-trading)
4. [Health Checks](#4-health-checks)
5. [Monitoring](#5-monitoring)
6. [Troubleshooting](#6-troubleshooting)
7. [Emergency Procedures](#7-emergency-procedures)
8. [Maintenance](#8-maintenance)

---

## 1. Environment Setup

### 1.1 Environment Variables (.env.prod)

Create `.env.prod` with the following configuration:

```bash
# =============================================================================
# TRADING MODE (CRITICAL)
# =============================================================================
LIVE_MODE=true                    # ⚠️ Set to true for LIVE TRADING
TRADING_MODE=live                 # Must be "live" for production

# =============================================================================
# REDIS CLOUD CONNECTION (TLS)
# =============================================================================
REDIS_URL=rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_SSL=true
REDIS_SSL_CA_CERT=config/certs/redis_ca.pem

# Redis streams
REDIS_SIGNAL_STREAM=signals:live:BTC_USD:15s
REDIS_METRICS_STREAM=metrics:live:scalper
REDIS_HEARTBEAT_STREAM=metrics:live:heartbeat

# =============================================================================
# KRAKEN API CREDENTIALS (LIVE)
# =============================================================================
KRAKEN_API_KEY=<YOUR_LIVE_API_KEY>
KRAKEN_API_SECRET=<YOUR_LIVE_API_SECRET>

# Kraken settings
KRAKEN_TIER=Intermediate          # Or "Pro" if you have higher tier
KRAKEN_RATE_LIMIT_BUFFER_MS=100   # Safety buffer for rate limits

# =============================================================================
# TRADING PAIRS
# =============================================================================
TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD
TIMEFRAMES=15s,1m,5m

# =============================================================================
# RISK MANAGEMENT (LIVE)
# =============================================================================
# Capital allocation
LIVE_STARTING_CAPITAL_USD=10000.0  # ⚠️ YOUR ACTUAL CAPITAL
MAX_POSITION_SIZE_USD=500.0        # Max per position
MAX_PORTFOLIO_HEAT_PCT=15.0        # Max total exposure

# Position sizing
POSITION_SIZE_PCT=2.0              # % of capital per trade
MIN_POSITION_SIZE_USD=10.0         # Minimum position
MAX_POSITION_SIZE_PCT=5.0          # Max % of capital

# Stop loss / Take profit
DEFAULT_STOP_LOSS_PCT=1.5          # Default SL distance
DEFAULT_TAKE_PROFIT_PCT=3.0        # Default TP distance
TRAILING_STOP_ENABLED=true
TRAILING_STOP_ACTIVATION_PCT=1.0
TRAILING_STOP_DISTANCE_PCT=0.5

# =============================================================================
# SAFETY GATES (LIVE)
# =============================================================================
# Daily loss limit
MAX_DAILY_LOSS_USD=200.0           # ⚠️ HARD STOP
MAX_DAILY_LOSS_PCT=2.0

# Drawdown protection
MAX_DRAWDOWN_PCT=5.0               # Stop if DD > 5%
CIRCUIT_BREAKER_ENABLED=true
CIRCUIT_BREAKER_LOSS_STREAK=3      # Stop after 3 consecutive losses

# Trade limits
MAX_TRADES_PER_DAY=20              # Daily trade limit
MAX_TRADES_PER_HOUR=5              # Hourly trade limit
MIN_SECONDS_BETWEEN_TRADES=60      # Cooldown between trades

# =============================================================================
# LATENCY & FRESHNESS (LIVE)
# =============================================================================
MAX_EVENT_AGE_MS=500               # Reject signals older than 500ms
MAX_INGEST_LAG_MS=200              # Max processing lag
CLOCK_DRIFT_THRESHOLD_MS=2000      # Alert if clock drift > 2s

# =============================================================================
# SIGNAL FILTERING (LIVE)
# =============================================================================
MIN_SIGNAL_CONFIDENCE=0.75         # Only trade high-confidence signals
ML_GATE_ENABLED=true               # Use ML model gating
ML_CONFIDENCE_THRESHOLD=0.70

# =============================================================================
# MONITORING (LIVE)
# =============================================================================
PROMETHEUS_PORT=9108               # Metrics exporter port
HEARTBEAT_INTERVAL_SEC=15.0        # Heartbeat frequency
LOG_LEVEL=INFO                     # INFO for production

# Alert thresholds
ALERT_NO_SIGNALS_TIMEOUT_SEC=300   # Alert if no signals for 5 min
ALERT_HIGH_LAG_MS=1000             # Alert if lag > 1s
ALERT_POSITION_STUCK_MIN=60        # Alert if position stuck > 1 hour

# =============================================================================
# EXCHANGE SETTINGS (KRAKEN)
# =============================================================================
EXCHANGE=kraken
ENABLE_5S_BARS=false               # Kraken doesn't support 5s
SCALPER_MAX_TRADES_PER_MINUTE=4    # Respect Kraken rate limits

# Order execution
ORDER_TYPE=limit                   # Use limit orders
LIMIT_ORDER_OFFSET_BPS=5           # 5 bps from mid
ORDER_TIMEOUT_SEC=30               # Cancel unfilled after 30s

# =============================================================================
# BACKUP & RECOVERY
# =============================================================================
ENABLE_STATE_BACKUP=true
BACKUP_INTERVAL_MIN=15
BACKUP_PATH=backups/live

# =============================================================================
# NOTIFICATIONS (OPTIONAL)
# =============================================================================
DISCORD_WEBHOOK_URL=<YOUR_WEBHOOK_URL>
ENABLE_DISCORD_ALERTS=true
ENABLE_EMAIL_ALERTS=false
```

### 1.2 Redis TLS Configuration

**Redis Connection String:**
```
rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

**Certificate Path:**
```
C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem
```

**Test Redis Connection:**
```bash
# Windows
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem ping

# Should return: PONG
```

**Verify Redis Streams:**
```bash
# Check if Redis is accessible
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem info server

# Check signal streams
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem XLEN signals:live:BTC_USD:15s
```

### 1.3 Kraken API Credentials

**Setup Kraken API Keys:**

1. Log in to Kraken: https://www.kraken.com
2. Navigate to: Settings → API
3. Create new API key with permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders
   - ✅ Query Closed Orders
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ Withdraw Funds (DO NOT enable)

4. Copy API Key and Secret to `.env.prod`:
   ```bash
   KRAKEN_API_KEY=<your_api_key>
   KRAKEN_API_SECRET=<your_api_secret>
   ```

**Test Kraken Connection:**
```bash
# Activate environment
conda activate crypto-bot

# Test Kraken API
python -c "
import ccxt
import os
from dotenv import load_dotenv

load_dotenv('.env.prod')
exchange = ccxt.kraken({
    'apiKey': os.getenv('KRAKEN_API_KEY'),
    'secret': os.getenv('KRAKEN_API_SECRET'),
})
balance = exchange.fetch_balance()
print(f'Connected! USD Balance: {balance[\"USD\"][\"free\"]}')
"
```

---

## 2. Pre-Flight Checklist

**Complete this checklist BEFORE going live:**

### 2.1 Paper Trading Verification
```
□ Paper trading ran for at least 48 hours
□ Win rate ≥ 55%
□ Profit factor ≥ 1.5
□ Max drawdown < 5%
□ No critical errors in logs
□ All circuit breakers tested
```

### 2.2 Configuration Review
```
□ .env.prod created and reviewed
□ LIVE_MODE=true set
□ TRADING_MODE=live set
□ Kraken API credentials verified
□ Redis connection tested
□ Capital limits set correctly
□ Risk parameters configured
```

### 2.3 Infrastructure Health
```
□ Redis Cloud accessible
□ Kraken API accessible
□ Prometheus metrics exporter running
□ Logs directory writable
□ Backup directory created
□ Sufficient disk space (>10GB)
```

### 2.4 Safety Mechanisms
```
□ MAX_DAILY_LOSS_USD configured
□ MAX_DRAWDOWN_PCT configured
□ Circuit breaker enabled
□ Kill switch tested
□ Rollback procedure documented
□ Emergency contact list ready
```

### 2.5 Monitoring Setup
```
□ Metrics endpoint accessible (http://localhost:9108/metrics)
□ Dashboard configured (Grafana/custom)
□ Alerts configured (Discord/email)
□ Log monitoring active
□ PnL tracking verified
```

---

## 3. Starting Live Trading

### 3.1 Activate Environment

```bash
# Activate conda environment
conda activate crypto-bot

# Verify Python version
python --version  # Should be 3.10+

# Verify dependencies
pip list | grep -E "ccxt|redis|prometheus"
```

### 3.2 Load Configuration

```bash
# Set environment to production
export ENV=prod

# Load .env.prod
set -a
source .env.prod
set +a

# Verify critical variables
echo "LIVE_MODE: $LIVE_MODE"
echo "TRADING_MODE: $TRADING_MODE"
echo "REDIS_URL: $REDIS_URL"
```

### 3.3 Pre-Flight Checks (Automated)

```bash
# Run pre-flight validation
python scripts/preflight_check.py --env prod

# Expected output:
# ✅ Redis connection: OK
# ✅ Kraken API: OK
# ✅ Configuration: OK
# ✅ Risk limits: OK
# ✅ Safety gates: OK
# ✅ All checks passed - READY TO GO LIVE
```

### 3.4 Start Live Trading

**Option 1: Direct Execution**
```bash
# Start live scalper
python scripts/run_live_scalper.py --config config/enhanced_scalper_config.yaml --env prod

# With logging
python scripts/run_live_scalper.py --config config/enhanced_scalper_config.yaml --env prod 2>&1 | tee logs/live_scalper_$(date +%Y%m%d_%H%M%S).log
```

**Option 2: Background Process (Linux/Mac)**
```bash
# Start in background with nohup
nohup python scripts/run_live_scalper.py --config config/enhanced_scalper_config.yaml --env prod > logs/live_scalper.log 2>&1 &

# Save PID for later
echo $! > live_scalper.pid
```

**Option 3: Using PM2 (Recommended for Production)**
```bash
# Install PM2 globally
npm install -g pm2

# Start with PM2
pm2 start scripts/run_live_scalper.py --name live-scalper --interpreter python -- --config config/enhanced_scalper_config.yaml --env prod

# Save PM2 configuration
pm2 save

# Auto-restart on system reboot
pm2 startup
```

### 3.5 Verify Startup

```bash
# Check process is running
ps aux | grep run_live_scalper

# Check logs for startup messages
tail -f logs/live_scalper.log

# Expected log output:
# [INFO] Loading configuration: config/enhanced_scalper_config.yaml
# [INFO] Environment: prod (LIVE MODE)
# [INFO] Connecting to Redis Cloud...
# [INFO] Redis connected: OK
# [INFO] Connecting to Kraken...
# [INFO] Kraken connected: OK (Balance: $10000.00)
# [INFO] Starting signal queue...
# [INFO] Starting live scalper...
# [INFO] Live trading ACTIVE - Monitoring 5 pairs
```

---

## 4. Health Checks

### 4.1 Metrics Endpoint

**Check Prometheus Metrics:**
```bash
# Verify metrics exporter is running
curl http://localhost:9108/metrics | head -20

# Key metrics to check:
curl http://localhost:9108/metrics | grep -E "signals_published|heartbeats_total|last_signal_age"
```

**Expected Metrics:**
```
# TYPE signals_published_total counter
signals_published_total{symbol="BTC_USD",timeframe="15s",side="long"} 142

# TYPE heartbeats_total counter
heartbeats_total 95

# TYPE last_signal_age_ms gauge
last_signal_age_ms 1250.0

# TYPE event_age_ms gauge
event_age_ms{symbol="BTC_USD",timeframe="15s"} 87.5
```

### 4.2 Heartbeat Check

**Check Heartbeat Stream:**
```bash
# Get latest heartbeat
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE metrics:live:heartbeat + - COUNT 1

# Expected output:
# 1) "1699123456789-0"
# 2) 1) "kind"
#    2) "heartbeat"
#    3) "now_ms"
#    4) "1699123456789"
#    5) "queue_depth"
#    6) "3"
#    7) "signals_published"
#    8) "142"
```

**Heartbeat Health Criteria:**
- ✅ Heartbeat received within last 30 seconds
- ✅ `queue_depth < 100` (not backed up)
- ✅ `signals_published` increasing
- ✅ No errors in `last_error` field

### 4.3 Signal Freshness

**Check Last Signal Age:**
```bash
# Via metrics endpoint
curl -s http://localhost:9108/metrics | grep last_signal_age_ms

# Should be < 60000 (1 minute)
```

**Check Signal Stream:**
```bash
# Get latest signal
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE signals:live:BTC_USD:15s + - COUNT 1

# Extract timestamp and compare with current time
```

**Freshness Criteria:**
- ✅ Last signal within 5 minutes (normal market)
- ✅ Event age < 500ms
- ✅ Ingest lag < 200ms
- ⚠️ Alert if no signals for >10 minutes

### 4.4 Trading Activity

**Check Open Positions:**
```bash
# Via Kraken API
python -c "
import ccxt
import os
from dotenv import load_dotenv

load_dotenv('.env.prod')
exchange = ccxt.kraken({
    'apiKey': os.getenv('KRAKEN_API_KEY'),
    'secret': os.getenv('KRAKEN_API_SECRET'),
})

positions = exchange.fetch_open_orders()
print(f'Open positions: {len(positions)}')
for pos in positions:
    print(f'  {pos[\"symbol\"]}: {pos[\"side\"]} @ {pos[\"price\"]}')
"
```

**Check Recent Trades:**
```bash
# Via logs
tail -100 logs/live_scalper.log | grep "TRADE_EXECUTED"

# Via Redis
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE trades:live + - COUNT 10
```

### 4.5 P&L Monitoring

**Check Current P&L:**
```bash
# Via performance metrics stream
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE metrics:performance + - COUNT 1

# Extract total_pnl_usd, win_rate, profit_factor
```

**Daily P&L Report:**
```bash
# Run daily P&L aggregator
python scripts/generate_pnl_report.py --date today

# Output: reports/pnl_daily_20251111.json
```

---

## 5. Monitoring

### 5.1 Real-Time Dashboard

**Launch Monitoring Dashboard:**
```bash
# Start unified status dashboard
python scripts/unified_status_dashboard.py --env prod

# Access at: http://localhost:8050
```

**Dashboard Sections:**
- 📊 Live P&L (real-time)
- 📈 Open positions
- 🔔 Recent signals
- ⚡ System health (heartbeat, latency, lag)
- 🚨 Alerts and warnings

### 5.2 Key Metrics to Monitor

| Metric | Threshold | Action if Exceeded |
|--------|-----------|-------------------|
| `last_signal_age_ms` | < 60000 | Check signal generator |
| `event_age_ms` | < 500 | Check Kraken latency |
| `ingest_lag_ms` | < 200 | Check Redis performance |
| `queue_depth` | < 100 | Check backpressure |
| `signals_shed` | 0 | Investigate signal volume |
| `daily_pnl_usd` | > -MAX_DAILY_LOSS | EMERGENCY STOP |
| `drawdown_pct` | < MAX_DRAWDOWN | EMERGENCY STOP |

### 5.3 Alert Configuration

**Discord Alerts (if enabled):**
```python
# Alerts are sent automatically to Discord webhook
# Configure in .env.prod:
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
ENABLE_DISCORD_ALERTS=true
```

**Alert Types:**
- 🚨 **CRITICAL**: Daily loss limit reached, max drawdown exceeded
- ⚠️ **WARNING**: High latency, no signals, clock drift
- ℹ️ **INFO**: Circuit breaker trip, position opened/closed

### 5.4 Log Monitoring

**Monitor Live Logs:**
```bash
# Tail logs in real-time
tail -f logs/live_scalper.log

# Filter for errors
tail -f logs/live_scalper.log | grep ERROR

# Filter for trades
tail -f logs/live_scalper.log | grep TRADE

# Filter for alerts
tail -f logs/live_scalper.log | grep ALERT
```

**Log Rotation:**
```bash
# Logs auto-rotate daily
# Old logs: logs/live_scalper.log.20251111
# Current: logs/live_scalper.log
```

---

## 6. Troubleshooting

### 6.1 High Lag (event_age_ms > 1000ms)

**Symptoms:**
- `event_age_ms` metric > 1000ms
- Stale signals being rejected
- Trades executing on old prices

**Diagnosis:**
```bash
# Check Kraken API latency
python -c "
import time
import ccxt

exchange = ccxt.kraken()
start = time.time()
ticker = exchange.fetch_ticker('BTC/USD')
latency = (time.time() - start) * 1000
print(f'Kraken API latency: {latency:.1f}ms')
"

# Check Redis latency
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  --latency

# Check system time sync
timedatectl status  # Linux
w32tm /query /status  # Windows
```

**Resolution:**
1. **If Kraken latency high (>500ms)**:
   - Check internet connection
   - Try different Kraken endpoint (kraken.com vs api.kraken.com)
   - Reduce request frequency

2. **If Redis latency high (>100ms)**:
   - Check Redis Cloud status
   - Verify network connectivity
   - Consider switching Redis region

3. **If system time drift**:
   ```bash
   # Linux: sync time
   sudo ntpdate -s time.nist.gov

   # Windows: sync time
   w32tm /resync /force
   ```

### 6.2 No Signals (last_signal_age_ms > 300000)

**Symptoms:**
- No signals for >5 minutes
- `signals_published_total` not increasing
- Empty signal streams

**Diagnosis:**
```bash
# Check signal generator process
ps aux | grep signal

# Check signal stream
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  XLEN signals:live:BTC_USD:15s

# Check Kraken data feed
python -c "
import ccxt
exchange = ccxt.kraken()
ticker = exchange.fetch_ticker('BTC/USD')
print(f'BTC/USD: {ticker[\"last\"]} (timestamp: {ticker[\"timestamp\"]})')
"
```

**Resolution:**
1. **If signal generator not running**:
   ```bash
   # Restart signal generator
   python scripts/run_live_scalper.py --config config/enhanced_scalper_config.yaml --env prod
   ```

2. **If Kraken data feed stale**:
   - Kraken may be experiencing issues
   - Check Kraken status: https://status.kraken.com
   - Wait for recovery or switch to backup exchange

3. **If signals being filtered out**:
   - Check `MIN_SIGNAL_CONFIDENCE` threshold
   - Review ML gate settings
   - Lower confidence threshold temporarily:
     ```bash
     export MIN_SIGNAL_CONFIDENCE=0.65
     ```

### 6.3 Clock Drift Alerts

**Symptoms:**
- Warnings: "Clock drift detected"
- `clock_drift_ms` > 2000ms
- Signals rejected due to timestamp issues

**Diagnosis:**
```bash
# Check system time vs NTP
ntpq -p  # Linux
w32tm /query /peers  # Windows

# Check time sync status
timedatectl  # Linux
w32tm /query /status  # Windows
```

**Resolution:**
```bash
# Force time sync (Linux)
sudo systemctl stop ntpd
sudo ntpdate -s time.nist.gov
sudo systemctl start ntpd

# Force time sync (Windows)
w32tm /resync /force
```

### 6.4 Circuit Breaker Tripped

**Symptoms:**
- Log message: "Circuit breaker activated"
- Trading halted
- No new positions opened

**Diagnosis:**
```bash
# Check recent trades
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE trades:live + - COUNT 10

# Check P&L
python scripts/generate_pnl_report.py --date today
```

**Resolution:**
1. **If losing streak**:
   - Review recent trades for patterns
   - Check market conditions (high volatility, news events)
   - Consider pausing trading temporarily
   - Review and adjust strategy parameters

2. **Reset circuit breaker** (only after investigation):
   ```bash
   # Reset circuit breaker flag
   redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
     --tls --cacert config/certs/redis_ca.pem \
     SET circuit_breaker:active false
   ```

### 6.5 High Queue Depth (queue_depth > 100)

**Symptoms:**
- `queue_depth` metric > 100
- Signals being shed (backpressure)
- Warnings: "Backpressure event"

**Diagnosis:**
```bash
# Check queue stats
curl -s http://localhost:9108/metrics | grep queue

# Check publisher performance
tail -100 logs/live_scalper.log | grep "PUBLISHED"
```

**Resolution:**
1. **If publisher slow**:
   - Check Redis connection latency
   - Verify no network issues
   - Consider increasing queue size in config

2. **If signal volume too high**:
   - Increase `MIN_SIGNAL_CONFIDENCE` to filter more
   - Reduce number of trading pairs
   - Increase signal interval

### 6.6 Order Execution Failures

**Symptoms:**
- Log errors: "Order placement failed"
- Positions not opening despite signals
- Kraken API errors

**Diagnosis:**
```bash
# Check Kraken balance
python -c "
import ccxt
import os
from dotenv import load_dotenv

load_dotenv('.env.prod')
exchange = ccxt.kraken({
    'apiKey': os.getenv('KRAKEN_API_KEY'),
    'secret': os.getenv('KRAKEN_API_SECRET'),
})
balance = exchange.fetch_balance()
print(f'USD: {balance[\"USD\"][\"free\"]}')
print(f'BTC: {balance[\"BTC\"][\"free\"]}')
"

# Check Kraken API status
curl -s https://api.kraken.com/0/public/SystemStatus | python -m json.tool
```

**Resolution:**
1. **If insufficient funds**:
   - Deposit more capital
   - Reduce position sizes
   - Close some positions to free capital

2. **If Kraken API rate limit**:
   - Increase `KRAKEN_RATE_LIMIT_BUFFER_MS`
   - Reduce trading frequency
   - Upgrade Kraken tier

3. **If Kraken API down**:
   - Check https://status.kraken.com
   - Wait for recovery
   - Consider emergency manual intervention

---

## 7. Emergency Procedures

### 7.1 EMERGENCY STOP (Kill Switch)

**Immediate Shutdown:**
```bash
# METHOD 1: Set LIVE_MODE=false
export LIVE_MODE=false

# METHOD 2: Kill process
pkill -f run_live_scalper.py

# METHOD 3: Stop via PM2 (if using PM2)
pm2 stop live-scalper

# METHOD 4: Emergency stop script
python scripts/emergency_stop.py --confirm
```

**Verify Stop:**
```bash
# Check process killed
ps aux | grep run_live_scalper
# Should return nothing

# Check no new signals
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  XLEN signals:live:BTC_USD:15s
# Length should stop increasing
```

### 7.2 Close All Positions

**Close All Open Positions (Manual):**
```bash
# Run position closer script
python scripts/close_all_positions.py --exchange kraken --env prod --confirm

# Expected output:
# Closing 3 open positions...
# ✅ Closed BTC/USD long @ 45123.50 (+$12.34)
# ✅ Closed ETH/USD short @ 3001.20 (-$5.67)
# ✅ Closed SOL/USD long @ 151.30 (+$8.90)
# All positions closed. Total P&L: +$15.57
```

### 7.3 Rollback to Paper Trading

**Switch to Paper Mode:**
```bash
# Edit .env.prod
sed -i 's/LIVE_MODE=true/LIVE_MODE=false/' .env.prod
sed -i 's/TRADING_MODE=live/TRADING_MODE=paper/' .env.prod

# Restart with paper mode
pkill -f run_live_scalper
python scripts/run_live_scalper.py --config config/enhanced_scalper_config.yaml --env prod
```

**Verify Paper Mode:**
```bash
# Check logs for paper mode confirmation
tail -20 logs/live_scalper.log | grep "PAPER MODE"

# Expected:
# [INFO] PAPER MODE ACTIVE - No real trades will execute
```

### 7.4 System Recovery

**After Emergency Stop:**

1. **Assess Damage:**
   ```bash
   # Generate P&L report
   python scripts/generate_pnl_report.py --date today

   # Check final positions
   python -c "
   import ccxt
   import os
   from dotenv import load_dotenv

   load_dotenv('.env.prod')
   exchange = ccxt.kraken({
       'apiKey': os.getenv('KRAKEN_API_KEY'),
       'secret': os.getenv('KRAKEN_API_SECRET'),
   })
   positions = exchange.fetch_open_orders()
   balance = exchange.fetch_balance()
   print(f'Open positions: {len(positions)}')
   print(f'USD Balance: {balance[\"USD\"][\"free\"]}')
   "
   ```

2. **Review Logs:**
   ```bash
   # Extract errors from logs
   grep ERROR logs/live_scalper.log > logs/errors_$(date +%Y%m%d).log

   # Extract all trades
   grep TRADE logs/live_scalper.log > logs/trades_$(date +%Y%m%d).log
   ```

3. **Post-Mortem Analysis:**
   - What triggered the emergency stop?
   - Were safety gates effective?
   - What can be improved?
   - Document findings in `INCIDENTS_LOG.md`

4. **Decide Next Steps:**
   - ✅ Fix issues and restart
   - ⚠️ Switch to paper trading
   - 🛑 Pause trading indefinitely

---

## 8. Maintenance

### 8.1 Daily Checklist

**Every Day (Before Market Open):**
```
□ Check overnight P&L
□ Review error logs
□ Verify heartbeat active
□ Check Redis connection
□ Verify Kraken API status
□ Review circuit breaker status
□ Check disk space
□ Backup logs and data
```

### 8.2 Weekly Checklist

**Every Week:**
```
□ Generate weekly P&L report
□ Review strategy performance
□ Update configuration if needed
□ Review and clear old logs
□ Check for system updates
□ Test emergency procedures
□ Review risk parameters
```

### 8.3 Log Management

**Rotate Logs:**
```bash
# Auto-rotation is configured, but manual rotation:
cd logs
mkdir archive_$(date +%Y%m)
mv live_scalper.log.2025* archive_$(date +%Y%m)/
gzip archive_$(date +%Y%m)/*
```

**Backup Logs:**
```bash
# Backup to cloud storage (example with AWS S3)
aws s3 sync logs/ s3://my-trading-logs/crypto-bot/$(date +%Y%m%d)/ \
  --exclude "*.log" --include "*.log.*"
```

### 8.4 Database Maintenance

**Clean Old Redis Data:**
```bash
# Remove old signals (keep last 24 hours)
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  XTRIM signals:live:BTC_USD:15s MAXLEN ~ 10000

# Remove old metrics (keep last 7 days)
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls --cacert config/certs/redis_ca.pem \
  XTRIM metrics:performance MAXLEN ~ 10080
```

### 8.5 System Updates

**Update Dependencies:**
```bash
# Activate environment
conda activate crypto-bot

# Update packages
pip install --upgrade ccxt redis prometheus-client

# Verify no breaking changes
python -c "import ccxt; print(ccxt.__version__)"
```

**Update Configuration:**
```bash
# Backup current config
cp config/enhanced_scalper_config.yaml config/enhanced_scalper_config.yaml.backup

# Edit config
nano config/enhanced_scalper_config.yaml

# Validate config
python scripts/validate_config.py --config config/enhanced_scalper_config.yaml
```

---

## Appendix A: Command Reference

### Quick Commands

```bash
# Start live trading
python scripts/run_live_scalper.py --config config/enhanced_scalper_config.yaml --env prod

# Stop live trading
pkill -f run_live_scalper.py

# Check metrics
curl http://localhost:9108/metrics | grep -E "signals|heartbeat|pnl"

# Check heartbeat
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem XREVRANGE metrics:live:heartbeat + - COUNT 1

# Check P&L
python scripts/generate_pnl_report.py --date today

# Close all positions
python scripts/close_all_positions.py --exchange kraken --env prod --confirm

# Emergency stop
export LIVE_MODE=false && pkill -f run_live_scalper
```

---

## Appendix B: Contact Information

**Emergency Contacts:**
- Primary: [Your Contact]
- Backup: [Backup Contact]
- Kraken Support: https://support.kraken.com

**Resources:**
- Kraken API Docs: https://docs.kraken.com/rest/
- Redis Cloud Support: https://redis.com/support/
- System Status: https://status.kraken.com

---

## Appendix C: Incident Log Template

**Record all incidents in `INCIDENTS_LOG.md`:**

```markdown
## Incident YYYY-MM-DD HH:MM

**Severity**: Critical / High / Medium / Low
**Type**: Trading Loss / System Failure / Data Issue / Other

### Description
[Brief description of what happened]

### Timeline
- HH:MM - Event detected
- HH:MM - Response initiated
- HH:MM - Issue resolved

### Impact
- Financial: $XXX loss/gain
- Positions affected: X positions
- Downtime: X minutes

### Root Cause
[Analysis of why it happened]

### Resolution
[What was done to fix it]

### Prevention
[Steps taken to prevent recurrence]
```

---

## Document Version

**Version**: 1.0
**Last Updated**: 2025-11-11
**Next Review**: 2025-12-11
**Owner**: Trading Operations Team

---

**⚠️ REMEMBER: LIVE TRADING INVOLVES REAL MONEY. ALWAYS VERIFY BEFORE EXECUTING. ⚠️**
