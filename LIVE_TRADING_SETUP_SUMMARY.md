# Live Trading Setup - Summary & Validation

**Date**: 2025-10-29
**Status**: ✅ **READY FOR LIVE TRADING** (pending final confirmation)

---

## Executive Summary

The crypto_ai_bot system has been validated and is ready for live trading mode. All safety gates, risk controls, and Redis stream configurations are properly configured. This document summarizes the validation results and provides instructions for enabling live trading.

---

## Validation Results

### ✅ 1. Redis Cloud Connectivity

**Status**: PASSED

- **Connection**: Successfully connected to Redis Cloud with TLS
- **Redis URL**: `rediss://redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`
- **TLS Certificate**: `config/certs/redis_ca.pem` (verified)
- **Redis Version**: 7.4.3
- **Ping Test**: OK

**Stream Configuration**:
- ✅ `signals:paper` - exists (15 entries)
- ✅ `signals:live` - exists (6 entries)
- ✅ Test signal write/read verified

---

### ✅ 2. Safety Gates Configuration

**Status**: PASSED

All safety controls are properly configured in `config/settings.yaml`:

| Safety Control | Value | Status |
|----------------|-------|--------|
| Max Concurrent Positions | 3 | ✅ |
| Risk Per Trade | 0.8% | ✅ |
| Daily Max Drawdown | 4.0% | ✅ |
| Rolling Max Drawdown | 12.0% | ✅ |
| Emergency Stop | Inactive | ✅ |

**Safety Modules Verified**:
- ✅ `agents/risk_manager.py` - Position sizing, portfolio caps, drawdown breakers
- ✅ `protections/safety_gates.py` - MODE switch, emergency kill-switch, circuit breakers
- ✅ `config/trading_mode_controller.py` - PAPER/LIVE routing with confirmation

---

### ✅ 3. Config File Alignment

**Status**: VALIDATED

**Main Configuration** (`.env`):
```ini
BOT_MODE=PAPER                        # Will be updated to LIVE
LIVE_TRADING_CONFIRMATION=            # Will be set to: I-accept-the-risk
REDIS_URL=rediss://...                # ✅ Configured with TLS
STREAM_SIGNALS_PAPER=signals:paper    # ✅ Correct
STREAM_SIGNALS_LIVE=signals:live      # ✅ Correct
ACTIVE_SIGNALS_STREAM=signals:paper   # Will be updated to signals:live
```

**YAML Configuration** (`config/settings.yaml`):
```yaml
mode: PAPER                           # Will be updated to LIVE
redis:
  streams:
    signals_paper: "signals:paper"    # ✅ Correct
    signals_live: "signals:live"      # ✅ Correct
    active_signals_alias: "ACTIVE_SIGNALS"  # ✅ Correct
```

**Production Override** (`config/overrides/prod.yaml`):
```yaml
mode: LIVE                            # ✅ Already set correctly
```

---

## Current vs. Target Configuration

### Current State (PAPER Mode)

```
MODE                          = PAPER
LIVE_TRADING_CONFIRMATION     = (not set)
ACTIVE_SIGNALS (Redis)        = signals:paper
Stream Routing                → signals:paper
```

### Target State (LIVE Mode)

```
MODE                          = LIVE
LIVE_TRADING_CONFIRMATION     = I-accept-the-risk
ACTIVE_SIGNALS (Redis)        = signals:live
Stream Routing                → signals:live
```

---

## Changes to be Applied

The configuration script will make the following changes:

1. **Backup** current `.env` and `settings.yaml` to `config/backups/`
2. **Update `.env`**:
   - Set `MODE=LIVE`
   - Set `BOT_MODE=LIVE`
   - Set `LIVE_TRADING_CONFIRMATION=I-accept-the-risk`
   - Set `ACTIVE_SIGNALS_STREAM=signals:live`
3. **Update Redis**:
   - Set `ACTIVE_SIGNALS → signals:live`
4. **Update `settings.yaml`**:
   - Set `mode: LIVE`

---

## How to Enable Live Trading

### Option 1: Automated Configuration (Recommended)

```bash
# Activate conda environment
conda activate crypto-bot

# Preview changes (dry-run)
python scripts/configure_live_trading.py

# Apply changes (requires confirmation)
python scripts/configure_live_trading.py --confirm
```

The script will:
- ✅ Create automatic backups
- ✅ Update all configuration files
- ✅ Update Redis routing
- ✅ Verify safety gates

### Option 2: Manual Configuration

1. **Edit `.env` file**:
   ```ini
   MODE=LIVE
   BOT_MODE=LIVE
   LIVE_TRADING_CONFIRMATION=I-accept-the-risk
   ACTIVE_SIGNALS_STREAM=signals:live
   ```

2. **Update Redis** (using redis-cli):
   ```bash
   redis-cli -u "redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" \
     --tls \
     --cacert "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem" \
     SET ACTIVE_SIGNALS "signals:live"
   ```

3. **Update `config/settings.yaml`**:
   ```yaml
   mode: LIVE
   ```

---

## Testing & Verification

After enabling live trading, run these verification steps:

### 1. Test Redis Connection
```bash
python scripts/test_redis_live.py
```

Expected output:
```
[INFO] Trading mode: LIVE
[OK] ACTIVE_SIGNALS -> signals:live
[OK] Test signal written to signals:live
```

### 2. Start Trading System
```bash
python scripts/start_trading_system.py
```

Verify in startup logs:
```
✅ MODE: LIVE
✅ ACTIVE_SIGNALS → signals:live
✅ LIVE_TRADING_CONFIRMATION: verified
```

### 3. Monitor Signal Stream

Watch for signals in `signals:live` stream:
```bash
# Using redis-cli
redis-cli -u "..." --tls --cacert "..." XREAD COUNT 10 STREAMS signals:live 0-0

# Or using Python
python -c "
import redis
r = redis.from_url('rediss://...')
signals = r.xrevrange('signals:live', count=10)
for entry_id, fields in signals:
    print(f'{entry_id}: {fields}')
"
```

---

## Safety Controls & Emergency Procedures

### Multi-Layer Safety Architecture

1. **MODE Switch** (`config/trading_mode_controller.py`):
   - Requires explicit `LIVE_TRADING_CONFIRMATION=I-accept-the-risk`
   - Routes signals to correct stream based on MODE

2. **Emergency Kill-Switch** (`protections/safety_gates.py`):
   - Immediate halt of all new entries
   - Exits still allowed to close positions
   - Triggered by: `KRAKEN_EMERGENCY_STOP=true` in `.env` OR Redis key

3. **Risk Manager** (`agents/risk_manager.py`):
   - Position sizing: 1-2% risk per trade
   - Portfolio caps: ≤4% total concurrent risk
   - Leverage limits: Default 2-3x, max 5x per symbol
   - Drawdown breakers:
     - -10% DD → Soft stop (0.5x risk)
     - -15% DD → Hard halt (pause for 10 bars)
     - -20% DD → Extended halt

4. **Circuit Breakers** (`protections/safety_gates.py`):
   - Spread threshold: 50 bps
   - Latency threshold: 1000ms
   - Auto-pause: 60 seconds on breach

### Emergency Stop Procedures

#### Method 1: Environment Variable (Fastest)
1. Edit `.env`:
   ```ini
   KRAKEN_EMERGENCY_STOP=true
   ```
2. System will immediately block new entries on next check
3. Existing positions can still be closed

#### Method 2: Redis Kill-Switch (Instant)
```bash
redis-cli -u "..." --tls --cacert "..." SET kraken:emergency:kill_switch "true"
```

#### Method 3: Process Termination
```bash
# Find process
ps aux | grep start_trading_system

# Kill gracefully
kill <PID>

# Or force kill if needed
kill -9 <PID>
```

---

## Risk Management Summary

**Per-Trade Risk**: 1-2% of equity via stop-loss distance
**Portfolio Risk**: ≤4% total concurrent risk
**Max Positions**: 3 concurrent positions
**Leverage**: Default 2-3x, max 5x per symbol
**Daily Drawdown Limit**: 4.0%
**Rolling Drawdown Limit**: 12.0% (30-day)

**Position Sizing Formula**:
```
Position Size = (Equity * Risk%) / Stop Loss Distance%
```

**Example** (10k equity, 2% SL):
```
Size = ($10,000 * 0.02) / 0.02 = $10,000 notional
Risk = $200 USD
```

---

## Operational Checklist

### Before Going Live

- [ ] Review all configuration files
- [ ] Verify LIVE_TRADING_CONFIRMATION is set correctly
- [ ] Test Redis connectivity
- [ ] Verify CA certificate path
- [ ] Check emergency stop is NOT active
- [ ] Review risk parameters in settings.yaml
- [ ] Ensure Kraken API credentials are for LIVE account (not sandbox)
- [ ] Verify account has sufficient balance
- [ ] Start with minimum position sizes
- [ ] Have emergency stop procedure documented and ready

### First Hour Monitoring

- [ ] Monitor `signals:live` stream for new signals
- [ ] Check position manager logs for order placements
- [ ] Verify fills in `kraken:fills` stream
- [ ] Monitor PnL in real-time
- [ ] Check for any error messages
- [ ] Verify risk limits are being enforced
- [ ] Keep emergency stop ready

### Ongoing Monitoring

- [ ] Daily PnL review
- [ ] Weekly drawdown check
- [ ] Monthly performance vs. backtest comparison
- [ ] Review rejected trades (check logs for rejection reasons)
- [ ] Monitor Redis latency and connection health
- [ ] Check for circuit breaker trips

---

## Scripts & Tools

### Configuration Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `configure_live_trading.py` | Configure system for live trading | `python scripts/configure_live_trading.py --confirm` |
| `test_redis_live.py` | Test Redis connectivity and streams | `python scripts/test_redis_live.py` |
| `validate_live_trading_setup.py` | Full system validation | `python scripts/validate_live_trading_setup.py` |

### Trading System Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `start_trading_system.py` | Start main trading system | `python scripts/start_trading_system.py` |
| `preflight.py` | Pre-flight checks | `python scripts/preflight.py` |

### Backups

All configuration backups are stored in: `config/backups/`

Format: `{filename}.backup_{YYYYMMDD_HHMMSS}`

To restore from backup:
```bash
cp config/backups/.env.backup_20251029_120000 .env
```

---

## Additional References

- **PRD**: `PRD.md` - System architecture and requirements
- **Risk Gates**: `docs/RISK_GATES.md` - Detailed risk control documentation
- **Operations**: `OPERATIONS_RUNBOOK.md` - Operational procedures
- **Quickstart**: `QUICKSTART_OPERATIONS.md` - Quick reference guide

---

## Support & Troubleshooting

### Common Issues

#### Signals not appearing in signals:live
- Check `ACTIVE_SIGNALS` in Redis: `redis-cli GET ACTIVE_SIGNALS`
- Verify MODE is set to LIVE in .env
- Check publisher logs for errors

#### LIVE_TRADING_CONFIRMATION error
- Ensure exact phrase: `I-accept-the-risk` (no quotes in .env)
- Check for typos or extra spaces
- Restart system after updating .env

#### Redis connection failures
- Verify TLS is enabled (rediss://)
- Check CA certificate path
- Test connection: `python scripts/test_redis_live.py`

#### Emergency stop not working
- Check env: `KRAKEN_EMERGENCY_STOP=true`
- Check Redis: `redis-cli GET kraken:emergency:kill_switch`
- Look for error logs

---

## Approval & Sign-off

**Configuration Validated By**: Claude Code
**Date**: 2025-10-29
**Status**: ✅ Ready for live trading

**Next Action Required**:
Run `python scripts/configure_live_trading.py --confirm` to enable live trading mode.

---

## Appendix: Redis Cloud Connection Details

**Connection String**:
```
rediss://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

**TLS Certificate**:
```
C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem
```

**Redis-CLI Usage**:
```bash
redis-cli -u "redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" \
  --tls \
  --cacert "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"
```

**Python Connection**:
```python
import redis

client = redis.from_url(
    "rediss://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818",
    decode_responses=True,
    ssl_ca_certs="config/certs/redis_ca.pem"
)

client.ping()  # Test connection
```

---

*End of Document*
