# Live Scalper - Complete Guide

**Version:** 1.0
**Last Updated:** 2025-01-11
**Status:** ✅ Production Ready

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Configuration](#configuration)
4. [Safety Rails](#safety-rails)
5. [Preflight Checks](#preflight-checks)
6. [Running the Scalper](#running-the-scalper)
7. [Monitoring](#monitoring)
8. [Troubleshooting](#troubleshooting)
9. [Advanced Topics](#advanced-topics)

---

## Overview

### What is Live Scalper?

The Live Scalper is a production-ready, high-frequency trading system with comprehensive safety rails:

- **LIVE_MODE Toggle**: Environment variable + YAML configuration
- **Safety Rails**: Portfolio heat (75% max), daily stops (-6%), profit targets (+2.5%)
- **Per-Pair Limits**: Notional caps for each trading pair
- **Preflight Checks**: Fail-fast validation of Redis TLS and Kraken WSS
- **Startup Summary**: Comprehensive logging of configuration
- **Single Entrypoint**: `scripts/run_live_scalper.py`

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  run_live_scalper.py                        │
│  - Load config (YAML + environment variables)               │
│  - Run preflight checks (Redis TLS, Kraken WSS)             │
│  - Initialize safety rails                                  │
│  - Log startup summary                                      │
│  - Start trading loop                                       │
└─────────────────┬───────────────────────────────────────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌────────┐   ┌─────────┐   ┌──────────┐
│ Config │   │ Safety  │   │Preflight │
│ YAML   │   │  Rails  │   │  Checks  │
└────────┘   └─────────┘   └──────────┘
```

### Key Features

| Feature | Description |
|---------|-------------|
| **LIVE_MODE Toggle** | Environment variable + YAML config |
| **Safety Rails** | Portfolio heat, daily stops, per-pair limits |
| **Preflight Checks** | Redis TLS, Kraken WSS, balance validation |
| **Startup Summary** | Pairs, TFs, risk caps, Redis keys |
| **Fail-Fast** | Stops immediately if critical checks fail |

---

## Quick Start

### Prerequisites

- ✅ Conda environment: `crypto-bot`
- ✅ Redis Cloud account with TLS certificate
- ✅ Kraken API credentials (for live mode)
- ✅ Configuration files

### 5-Minute Setup (Paper Mode)

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Copy environment file
cp .env.paper.live .env.scalper

# 3. Edit environment (add your Redis URL)
nano .env.scalper

# 4. Run preflight checks (dry run)
python scripts/run_live_scalper.py --dry-run

# 5. Start scalper (paper mode)
python scripts/run_live_scalper.py
```

### Starting in Live Mode

⚠️ **WARNING: LIVE MODE TRADES REAL MONEY**

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Copy live environment file
cp .env.live.example .env.live

# 3. Add your credentials
nano .env.live
# - REDIS_URL
# - KRAKEN_API_KEY
# - KRAKEN_API_SECRET

# 4. Set environment variables
export LIVE_MODE=true
export LIVE_TRADING_CONFIRMATION="I confirm live trading"

# 5. Run preflight checks
python scripts/run_live_scalper.py --dry-run --env-file .env.live

# 6. Start live trading (monitor closely!)
python scripts/run_live_scalper.py --env-file .env.live
```

---

## Configuration

### YAML Configuration

**File:** `config/live_scalper_config.yaml`

#### Key Sections

```yaml
# Mode configuration
mode:
  live_mode: ${LIVE_MODE:false}
  live_trading_confirmation: "${LIVE_TRADING_CONFIRMATION:}"

# Safety rails
safety_rails:
  portfolio:
    max_heat_pct: 75.0
  daily_limits:
    max_loss_pct: -6.0
    profit_target_pct: 2.5
  per_pair_limits:
    BTC/USD:
      max_notional: 5000.0
      max_position_pct: 0.20

# Trading configuration
trading:
  pairs:
    - BTC/USD
    - ETH/USD
    - SOL/USD
    - MATIC/USD
    - LINK/USD
  timeframes:
    primary: 15s
    secondary: 1m
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LIVE_MODE` | No | `false` | Set to `true` for live trading |
| `LIVE_TRADING_CONFIRMATION` | Yes (live) | - | Must be "I confirm live trading" |
| `REDIS_URL` | Yes | - | Redis Cloud URL (rediss://) |
| `REDIS_CA_CERT` | No | `config/certs/redis_ca.pem` | TLS certificate path |
| `KRAKEN_API_KEY` | Yes (live) | - | Kraken API key |
| `KRAKEN_API_SECRET` | Yes (live) | - | Kraken API secret |
| `TRADING_PAIRS` | No | See config | Comma-separated pairs |

### Configuration Validation

The system validates:
- ✅ Live mode confirmation matches exactly
- ✅ Redis URL uses `rediss://` (TLS)
- ✅ At least one trading pair configured
- ✅ Safety rails present in live mode
- ✅ TLS certificate file exists

---

## Safety Rails

### Overview

Safety rails **prevent catastrophic losses** by enforcing strict limits:

### 1. Portfolio Heat Limit

**Maximum: 75%**

Portfolio heat = sum of position risks / portfolio value

```
Heat = Σ(position_notional × stop_distance_pct) / portfolio_value × 100
```

**Behavior:**
- **< 70%**: Normal trading
- **70-75%**: Warning - approaching limit
- **≥ 75%**: No new positions allowed

### 2. Daily Stop Loss

**Limit: -6%**

Stops all trading if daily loss reaches -6%.

**Example:**
- Start of day: $10,000
- Loss threshold: $9,400 (-$600)
- Current: $9,350 → **STOP TRIGGERED**

### 3. Daily Profit Target

**Target: +2.5%**

Stops trading (to preserve gains) if daily profit reaches +2.5%.

**Example:**
- Start of day: $10,000
- Target: $10,250 (+$250)
- Current: $10,280 → **TARGET REACHED, STOP TRADING**

### 4. Per-Pair Notional Limits

Maximum position size per trading pair:

| Pair | Max Notional | Max Portfolio % |
|------|--------------|-----------------|
| BTC/USD | $5,000 | 20% |
| ETH/USD | $3,000 | 15% |
| SOL/USD | $2,000 | 10% |
| MATIC/USD | $1,500 | 8% |
| LINK/USD | $1,500 | 8% |

### 5. Circuit Breakers

Automated pauses on losing streaks:

| Trigger | Action | Duration |
|---------|--------|----------|
| 3 losses in row | Reduce size 50% | 30 min |
| 5 losses in row | Pause trading | 60 min |
| Daily loss -6% | Stop trading | Rest of day |

### Safety Rails Status

Check current status:

```python
from agents.risk.live_safety_rails import LiveSafetyRails

rails = LiveSafetyRails(config)
status = rails.get_status_summary()

print(f"Daily PnL: {status['daily_pnl_pct']}%")
print(f"Portfolio Heat: {status['portfolio_heat_pct']}%")
print(f"Trades Today: {status['trades_today']}")
```

---

## Preflight Checks

### What are Preflight Checks?

Automated validation **before trading starts** to ensure:
- ✅ Redis Cloud connection works
- ✅ Redis TLS is configured correctly
- ✅ Kraken WebSocket is accessible
- ✅ Kraken REST API is online
- ✅ Trading pairs are valid
- ✅ Safety rails are configured

### Running Preflight Checks

```bash
# Dry run (checks only, no trading)
python scripts/run_live_scalper.py --dry-run

# Skip checks (NOT RECOMMENDED for live mode)
python scripts/run_live_scalper.py --skip-preflight
```

### Check Details

#### 1. Redis Connection

**Test:** Connect to Redis Cloud and ping

**Pass Criteria:**
- Connection successful
- PING returns PONG

**Failure:** Exits immediately

#### 2. Redis TLS

**Test:** Validate TLS configuration

**Pass Criteria:**
- URL uses `rediss://`
- CA certificate file exists
- Certificate is valid

**Failure:** Exits immediately

#### 3. Kraken WebSocket

**Test:** Connect to `wss://ws.kraken.com`

**Pass Criteria:**
- WebSocket connection established
- Server responds to ping

**Failure:** Exits immediately

#### 4. Kraken REST API

**Test:** Query `/0/public/SystemStatus`

**Pass Criteria:**
- API is online
- Status is "online"

**Failure:** Exits immediately

#### 5. Trading Pairs

**Test:** Validate pairs on Kraken

**Pass Criteria:**
- All configured pairs exist on Kraken
- Pairs are tradeable

**Failure:** Exits immediately

#### 6. Safety Rails

**Test:** Validate safety rails configuration

**Pass Criteria:**
- Daily stop loss is negative
- Portfolio heat is 0-100%
- Per-pair limits configured

**Failure:** Exits immediately

### Preflight Output

```
================================================================================
                        PREFLIGHT CHECKS
================================================================================

✓ PASS      Redis Connection          Connected successfully
✓ PASS      Redis TLS                 TLS configured correctly
✓ PASS      Kraken WebSocket          Connected successfully
✓ PASS      Kraken REST API           API online (status: online)
✓ PASS      Trading Pairs             5 pairs validated
✓ PASS      Safety Rails              Configuration valid

================================================================================
✅ All preflight checks PASSED
================================================================================
```

---

## Running the Scalper

### Command-Line Interface

```bash
python scripts/run_live_scalper.py [OPTIONS]

Options:
  --config PATH        Configuration file (default: config/live_scalper_config.yaml)
  --env-file PATH      Environment file (default: .env.paper)
  --skip-preflight     Skip preflight checks (not recommended)
  --dry-run            Validate config and run checks only
  -h, --help           Show help message
```

### Startup Sequence

1. **Load Environment** - Read `.env.paper` or `.env.live`
2. **Load Configuration** - Parse YAML with variable expansion
3. **Validate Config** - Check for errors
4. **Run Preflight Checks** - Validate connections
5. **Initialize Safety Rails** - Set up risk limits
6. **Log Startup Summary** - Display configuration
7. **Enter Trading Loop** - Start scalping

### Startup Summary

```
================================================================================
                   LIVE SCALPER STARTUP SUMMARY
================================================================================

🚦 MODE: PAPER TRADING
   ✓  Safe mode - no real money

💱 TRADING PAIRS (5):
   - BTC/USD
   - ETH/USD
   - SOL/USD
   - MATIC/USD
   - LINK/USD

⏱️  TIMEFRAMES:
   Primary:   15s
   Secondary: 1m
   5s bars:   Disabled

🛡️  RISK LIMITS:
   Daily Stop:        -6.0%
   Daily Target:      +2.5%
   Max Portfolio Heat: 75.0%
   Max Positions:     5
   Max Trades/Day:    150

💰 PER-PAIR NOTIONAL CAPS:
   BTC/USD      $5,000
   ETH/USD      $3,000
   SOL/USD      $2,000
   MATIC/USD    $1,500
   LINK/USD     $1,500

📊 REDIS STREAMS:
   Signals:   signals:paper:BTC-USD
   Positions: positions:live
   Risk:      risk:events
   Heartbeat: ops:heartbeat

🚨 SAFETY RAILS: ENABLED
   Portfolio heat monitoring: ✓
   Daily stop loss: ✓
   Per-pair limits: ✓
   Circuit breakers: ✓

🕐 STARTED: 2025-01-11T10:30:00.000000Z

================================================================================
```

### Graceful Shutdown

Press `Ctrl+C` to stop the scalper gracefully:

```
^C
Received shutdown signal
Shutting down scalper...
Shutdown complete
```

---

## Monitoring

### Health Endpoint

```bash
# Check health status
curl http://localhost:8080/health | jq .
```

**Response:**
```json
{
  "status": "healthy",
  "mode": "paper",
  "daily_pnl_pct": -2.5,
  "portfolio_heat_pct": 45.2,
  "open_positions": 3,
  "trades_today": 42
}
```

### Prometheus Metrics

```bash
# Scrape metrics endpoint
curl http://localhost:9108/metrics
```

**Key Metrics:**
- `signals_generated_total`
- `trades_executed_total`
- `pnl_realized_usd`
- `daily_pnl_pct`
- `portfolio_heat_pct`
- `positions_open_count`
- `safety_rails_triggered_total`

### Log Files

```bash
# Main log
tail -f logs/live_scalper.log

# Trades log
tail -f logs/live_scalper_trades.log

# Risk events
tail -f logs/live_scalper_risk.log

# Audit trail
tail -f logs/live_scalper_audit.log
```

### Redis Monitoring

```bash
# Check signals stream
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE signals:paper:BTC-USD + - COUNT 10

# Check position stream
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE positions:live + - COUNT 5

# Check heartbeat
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE ops:heartbeat + - COUNT 1
```

---

## Troubleshooting

### Common Issues

#### 1. "Configuration validation failed"

**Error:**
```
CRITICAL - Configuration validation failed:
  - Live mode requires LIVE_TRADING_CONFIRMATION='I confirm live trading'
```

**Fix:**
```bash
export LIVE_TRADING_CONFIRMATION="I confirm live trading"
```

#### 2. "Redis connection failed"

**Error:**
```
✗ FAIL      Redis Connection          Connection timeout
```

**Fix:**
- Check `REDIS_URL` is correct
- Verify Redis Cloud is accessible
- Check firewall/IP whitelist

#### 3. "Redis URL must use TLS"

**Error:**
```
✗ FAIL      Redis TLS                 URL must use rediss://
```

**Fix:**
```bash
# Change from redis:// to rediss://
export REDIS_URL="rediss://default:password@host:port"
```

#### 4. "CA certificate not found"

**Error:**
```
✗ FAIL      Redis TLS                 CA cert not found: /path/to/cert
```

**Fix:**
```bash
# Verify certificate exists
ls -la config/certs/redis_ca.pem

# Or specify full path
export REDIS_CA_CERT=/full/path/to/redis_ca.pem
```

#### 5. "Kraken WebSocket failed"

**Error:**
```
✗ FAIL      Kraken WebSocket          Connection timeout
```

**Fix:**
- Check internet connection
- Verify `wss://ws.kraken.com` is accessible
- Check firewall rules

#### 6. "Invalid pairs"

**Error:**
```
✗ FAIL      Trading Pairs             Invalid pairs: ['XYZ/USD']
```

**Fix:**
```bash
# Use valid Kraken pairs only:
export TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD
```

#### 7. "Daily stop loss reached"

**Warning:**
```
🚨 DAILY STOP LOSS TRIGGERED: -6.05%
   Trading STOPPED for the rest of the day
```

**Explanation:** Safety rail triggered to prevent further losses.

**Action:** Wait until next trading day for automatic reset.

---

## Advanced Topics

### Custom Configuration

Create a custom config file:

```bash
cp config/live_scalper_config.yaml config/my_scalper.yaml
nano config/my_scalper.yaml
```

Run with custom config:

```bash
python scripts/run_live_scalper.py --config config/my_scalper.yaml
```

### Overriding Environment Variables

Environment variables override YAML values:

```bash
# Override pairs
export TRADING_PAIRS=BTC/USD,ETH/USD

# Override daily stop
export DAILY_STOP_LOSS=-4.0

# Override max heat
export MAX_PORTFOLIO_HEAT=60.0

python scripts/run_live_scalper.py
```

### Testing Safety Rails

Test the safety rails module directly:

```bash
cd /c/Users/Maith/OneDrive/Desktop/crypto_ai_bot
python agents/risk/live_safety_rails.py
```

**Output:**
```
================================================================================
                    SAFETY RAILS CONFIGURATION
================================================================================

📊 Daily Limits:
   Stop Loss:           -6.0%
   Profit Target:       +2.5%
   ...

================================================================================
TESTING SAFETY RAILS
================================================================================

Test 1: Can trade initially? True
Test 2: Can trade at -5% PnL? True
Test 3: Can trade at -6.5% PnL? False
   Reason: Daily stop loss reached: -6.50%
...
```

### Production Deployment

#### Using systemd (Linux)

Create service file: `/etc/systemd/system/live-scalper.service`

```ini
[Unit]
Description=Live Scalper Trading Bot
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/crypto_ai_bot
Environment="PATH=/home/trader/miniconda3/envs/crypto-bot/bin"
ExecStart=/home/trader/miniconda3/envs/crypto-bot/bin/python scripts/run_live_scalper.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable live-scalper
sudo systemctl start live-scalper
sudo systemctl status live-scalper
```

#### Using Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "scripts/run_live_scalper.py"]
```

Build and run:

```bash
docker build -t live-scalper:latest .

docker run -d \
  --name live-scalper \
  -e LIVE_MODE=false \
  -e REDIS_URL="rediss://..." \
  -v ./config:/app/config \
  -v ./logs:/app/logs \
  -p 8080:8080 \
  -p 9108:9108 \
  live-scalper:latest
```

---

## Safety Checklist

Before going live:

- [ ] Run preflight checks in paper mode
- [ ] Monitor paper trading for 7 days
- [ ] Verify safety rails trigger correctly
- [ ] Test emergency shutdown (Ctrl+C)
- [ ] Set up monitoring alerts
- [ ] Start with small positions
- [ ] Monitor closely for first 24 hours
- [ ] Have emergency contact ready

---

## Support

- **Documentation**: This guide
- **Configuration**: `config/live_scalper_config.yaml`
- **Safety Rails**: `agents/risk/live_safety_rails.py`
- **Entrypoint**: `scripts/run_live_scalper.py`

---

**Last Updated:** 2025-01-11
**Version:** 1.0
**Status:** ✅ Production Ready
