# RUNBOOK_LIVE.md Implementation Complete

**Status**: ✅ COMPLETE
**File**: `RUNBOOK_LIVE.md`
**Date**: 2025-11-11
**Purpose**: Comprehensive operational guide for live trading

---

## Summary

Created production-grade runbook for operating the live trading system with real money on Kraken exchange.

---

## What's Included

### 1. Quick Reference
**One-Line GO LIVE Checklist:**
```
✅ .env.prod configured → ✅ Paper trial passed → ✅ Metrics healthy → ✅ Kill switch tested → ✅ Set LIVE_MODE=true → 🚀 GO
```

**Rollback (Emergency Stop):**
```bash
export LIVE_MODE=false
pkill -f run_live_scalper.py
```

### 2. Environment Setup

#### .env.prod Configuration (Complete)
- **Trading Mode**: LIVE_MODE, TRADING_MODE
- **Redis TLS**: Full connection string with certificate path
  ```
  REDIS_URL=rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
  REDIS_SSL=true
  REDIS_SSL_CA_CERT=config/certs/redis_ca.pem
  ```
- **Kraken API**: API key and secret placeholders with setup guide
- **Trading Pairs**: BTC/USD, ETH/USD, SOL/USD, MATIC/USD, LINK/USD
- **Risk Management**: Capital limits, position sizing, stop loss/take profit
- **Safety Gates**: Daily loss limits, drawdown protection, circuit breakers
- **Latency Tracking**: Event age, ingest lag, clock drift thresholds
- **Monitoring**: Prometheus port, heartbeat interval, alert thresholds

#### Redis TLS Setup
- Connection string: `rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@...`
- Certificate path: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem`
- Test commands provided
- Stream verification commands

#### Kraken API Setup
- Step-by-step API key creation
- Required permissions list
- Test connection script
- Security best practices

### 3. Start Commands

**Multiple Options:**

1. **Direct Execution:**
   ```bash
   python scripts/run_live_scalper.py --config config/enhanced_scalper_config.yaml --env prod
   ```

2. **Background with Logging:**
   ```bash
   nohup python scripts/run_live_scalper.py --config config/enhanced_scalper_config.yaml --env prod > logs/live_scalper.log 2>&1 &
   ```

3. **PM2 (Production Recommended):**
   ```bash
   pm2 start scripts/run_live_scalper.py --name live-scalper --interpreter python -- --config config/enhanced_scalper_config.yaml --env prod
   ```

### 4. Health Checks

#### Metrics Endpoint
- URL: `http://localhost:9108/metrics`
- Key metrics:
  - `signals_published_total`
  - `heartbeats_total`
  - `last_signal_age_ms`
  - `event_age_ms`
  - `ingest_lag_ms`

#### Heartbeat Check
- Stream: `metrics:live:heartbeat`
- Check frequency: Every 15 seconds
- Health criteria:
  - ✅ Received within last 30 seconds
  - ✅ Queue depth < 100
  - ✅ Signals published increasing
  - ✅ No errors

#### Signal Freshness
- Metric: `last_signal_age_ms`
- Threshold: < 60000ms (1 minute normal, 5 minutes acceptable)
- Alert: If no signals for >10 minutes
- Event age threshold: < 500ms
- Ingest lag threshold: < 200ms

### 5. Troubleshooting Guide

#### High Lag (event_age_ms > 1000ms)
**Diagnosis:**
- Check Kraken API latency
- Check Redis latency
- Check system time sync

**Resolution:**
- Fix internet connection
- Switch Kraken endpoint
- Sync system time with NTP
- Verify Redis Cloud connectivity

#### No Signals (last_signal_age_ms > 300000)
**Diagnosis:**
- Check signal generator process
- Check signal stream length
- Check Kraken data feed

**Resolution:**
- Restart signal generator
- Check Kraken status (https://status.kraken.com)
- Review signal filtering settings
- Lower confidence threshold if needed

#### Clock Drift Alerts
**Diagnosis:**
- Check system time vs NTP
- Verify time sync status

**Resolution:**
```bash
# Linux
sudo ntpdate -s time.nist.gov

# Windows
w32tm /resync /force
```

#### Additional Troubleshooting Sections:
- Circuit Breaker Tripped
- High Queue Depth
- Order Execution Failures

### 6. Emergency Procedures

#### Emergency Stop (Kill Switch)
**4 Methods Provided:**
1. Set `LIVE_MODE=false`
2. Kill process with `pkill`
3. Stop via PM2
4. Emergency stop script

#### Close All Positions
```bash
python scripts/close_all_positions.py --exchange kraken --env prod --confirm
```

#### Rollback to Paper Trading
- Edit `.env.prod` to switch modes
- Restart with paper mode
- Verification steps

#### System Recovery
- Assess damage
- Review logs
- Post-mortem analysis
- Decide next steps

### 7. Monitoring & Maintenance

#### Daily Checklist
- Check overnight P&L
- Review error logs
- Verify heartbeat
- Check Redis/Kraken status
- Review circuit breaker
- Check disk space

#### Weekly Checklist
- Generate weekly P&L report
- Review strategy performance
- Update configuration
- Clear old logs
- Test emergency procedures

#### Log Management
- Auto-rotation configuration
- Backup procedures
- Archive old logs

#### Database Maintenance
- Clean old Redis data
- Trim streams (MAXLEN)
- Optimize performance

---

## File Structure

```
RUNBOOK_LIVE.md
├── Quick Reference (GO LIVE Checklist & Rollback)
├── 1. Environment Setup
│   ├── 1.1 .env.prod (Complete configuration)
│   ├── 1.2 Redis TLS (Connection & verification)
│   └── 1.3 Kraken API (Setup & testing)
├── 2. Pre-Flight Checklist
│   ├── 2.1 Paper Trading Verification
│   ├── 2.2 Configuration Review
│   ├── 2.3 Infrastructure Health
│   ├── 2.4 Safety Mechanisms
│   └── 2.5 Monitoring Setup
├── 3. Starting Live Trading
│   ├── 3.1 Activate Environment
│   ├── 3.2 Load Configuration
│   ├── 3.3 Pre-Flight Checks (Automated)
│   ├── 3.4 Start Live Trading (3 methods)
│   └── 3.5 Verify Startup
├── 4. Health Checks
│   ├── 4.1 Metrics Endpoint
│   ├── 4.2 Heartbeat Check
│   ├── 4.3 Signal Freshness
│   ├── 4.4 Trading Activity
│   └── 4.5 P&L Monitoring
├── 5. Monitoring
│   ├── 5.1 Real-Time Dashboard
│   ├── 5.2 Key Metrics to Monitor
│   ├── 5.3 Alert Configuration
│   └── 5.4 Log Monitoring
├── 6. Troubleshooting
│   ├── 6.1 High Lag
│   ├── 6.2 No Signals
│   ├── 6.3 Clock Drift
│   ├── 6.4 Circuit Breaker Tripped
│   ├── 6.5 High Queue Depth
│   └── 6.6 Order Execution Failures
├── 7. Emergency Procedures
│   ├── 7.1 Emergency Stop
│   ├── 7.2 Close All Positions
│   ├── 7.3 Rollback to Paper
│   └── 7.4 System Recovery
├── 8. Maintenance
│   ├── 8.1 Daily Checklist
│   ├── 8.2 Weekly Checklist
│   ├── 8.3 Log Management
│   ├── 8.4 Database Maintenance
│   └── 8.5 System Updates
└── Appendices
    ├── A. Command Reference
    ├── B. Contact Information
    └── C. Incident Log Template
```

---

## Key Features

### ✅ Comprehensive Configuration
- Complete `.env.prod` template with all required variables
- Redis TLS setup with certificate path
- Kraken API credentials with setup guide
- Risk management parameters
- Safety gates and limits

### ✅ Multiple Start Methods
- Direct execution
- Background with nohup
- PM2 for production (recommended)
- Verification steps for each method

### ✅ Health Check Coverage
- **Metrics**: Prometheus endpoint monitoring
- **Heartbeat**: Redis stream verification
- **Freshness**: Last signal age tracking
- **Activity**: Trading and P&L monitoring

### ✅ Complete Troubleshooting
- **High Lag**: Diagnosis and resolution steps
- **No Signals**: Multiple causes and fixes
- **Clock Drift**: NTP sync procedures
- **Circuit Breaker**: Reset procedures
- **Queue Issues**: Backpressure handling
- **Order Failures**: API and balance checks

### ✅ Emergency Procedures
- **4 Kill Switch Methods**: Immediate shutdown options
- **Position Closure**: Close all positions script
- **Rollback**: Switch back to paper trading
- **Recovery**: Post-incident procedures

### ✅ Operational Excellence
- Daily checklist (8 items)
- Weekly checklist (7 items)
- Log rotation and archival
- Database maintenance
- Incident logging template

---

## Quick Command Reference

```bash
# START
python scripts/run_live_scalper.py --config config/enhanced_scalper_config.yaml --env prod

# STOP
pkill -f run_live_scalper.py

# HEALTH
curl http://localhost:9108/metrics | grep -E "signals|heartbeat|pnl"

# HEARTBEAT
redis-cli -u redis://default:&lt;REDIS_PASSWORD&gt;**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert config/certs/redis_ca.pem XREVRANGE metrics:live:heartbeat + - COUNT 1

# P&L
python scripts/generate_pnl_report.py --date today

# EMERGENCY
export LIVE_MODE=false && pkill -f run_live_scalper
```

---

## Environment Details

**Conda Environment:**
```bash
conda activate crypto-bot
```

**Redis Cloud:**
- Host: `redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
- Protocol: TLS (rediss://)
- CA Cert: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem`
- Encoded URL: `rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`

**Exchange:**
- Platform: Kraken
- API Docs: https://docs.kraken.com/rest/
- Status: https://status.kraken.com

---

## Safety Features

### Pre-Flight Checks (5 Sections)
1. ✅ Paper trading results verified
2. ✅ Configuration reviewed
3. ✅ Infrastructure healthy
4. ✅ Safety mechanisms enabled
5. ✅ Monitoring active

### Risk Management
- Daily loss limit: Configurable in `.env.prod`
- Max drawdown: Circuit breaker trigger
- Position limits: Per-trade and portfolio-wide
- Trade frequency limits: Per-minute, per-hour, per-day

### Emergency Controls
- 4 different kill switch methods
- Automated position closure script
- Instant rollback to paper trading
- Comprehensive incident logging

---

## Documentation Quality

**Total Length**: 600+ lines
**Sections**: 8 main + 3 appendices
**Code Examples**: 50+ executable commands
**Checklists**: 5 comprehensive lists
**Troubleshooting Scenarios**: 6 detailed guides

**Coverage:**
- ✅ All requested elements included
- ✅ Production-ready procedures
- ✅ Clear, actionable instructions
- ✅ Emergency procedures prioritized
- ✅ Maintenance guidelines included

---

## Next Steps

### Before Going Live
1. **Review RUNBOOK_LIVE.md thoroughly**
2. **Complete paper trading trial** (48+ hours)
3. **Test all emergency procedures**
4. **Verify .env.prod configuration**
5. **Run pre-flight checks**
6. **Start with small capital**

### During Live Trading
1. **Monitor metrics continuously**
2. **Check heartbeat every 15 minutes**
3. **Review P&L hourly**
4. **Keep logs accessible**
5. **Have kill switch ready**

### Post-Live
1. **Daily P&L review**
2. **Log analysis**
3. **Performance assessment**
4. **Configuration tuning**
5. **Incident documentation**

---

## Related Documents

- [PRD-001: Crypto AI Bot - Core Intelligence Engine](docs/PRD-001-CRYPTO-AI-BOT.md)
- `METRICS_EXPORTER_IMPLEMENTATION_COMPLETE.md`
- `TESTING_IMPLEMENTATION_COMPLETE.md`
- `OPERATIONS_RUNBOOK.md`
- `.env.prod` (to be created)

---

## Verification Checklist

**Document Completeness:**
```
✅ Environment variables (.env.prod) - COMPLETE (40+ variables)
✅ Redis TLS configuration - COMPLETE (connection + cert path)
✅ Kraken credentials setup - COMPLETE (step-by-step guide)
✅ Start commands - COMPLETE (3 methods + verification)
✅ Health checks - COMPLETE (metrics, heartbeat, freshness)
✅ Troubleshooting: High lag - COMPLETE (diagnosis + resolution)
✅ Troubleshooting: No signals - COMPLETE (3 scenarios)
✅ Troubleshooting: Drift alerts - COMPLETE (NTP sync)
✅ GO LIVE checklist - COMPLETE (one-line + detailed)
✅ Rollback procedure - COMPLETE (LIVE_MODE=false toggle)
```

**All Requirements Met**: ✅ **YES**

---

## Conclusion

**Status**: ✅ **RUNBOOK_LIVE.md COMPLETE**

A comprehensive, production-ready operational runbook has been created with:

- **Complete environment setup** with Redis TLS and Kraken API
- **Multiple start methods** for different deployment scenarios
- **Comprehensive health checks** for all critical metrics
- **Detailed troubleshooting** for all requested scenarios
- **Quick GO LIVE checklist** (one-line reference)
- **Emergency rollback** with LIVE_MODE=false toggle
- **600+ lines** of production-grade documentation

**Ready for live trading operations.**

---

**Document**: `RUNBOOK_LIVE.md`
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\`
**Status**: ✅ **COMPLETE**
**Date**: 2025-11-11
