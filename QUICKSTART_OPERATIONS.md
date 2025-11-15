# Quick Start Guide - Operations

**Get started with the trading system in under 5 minutes**

## Prerequisites

- ✅ Conda environment `crypto-bot` activated
- ✅ `.env` file configured with REDIS_URL
- ✅ Kraken API credentials (for LIVE mode only)

## Step 1: Activate Environment

```bash
conda activate crypto-bot
```

## Step 2: Health Check

```bash
python scripts/monitor_redis_streams.py --health
```

**Expected output:**
```
✓ HEALTH CHECK PASSED
```

## Step 3: Start Trading System (PAPER Mode)

```bash
# Dry run first (validates config, doesn't start)
python scripts/start_trading_system.py --mode paper --dry-run

# Start system
python scripts/start_trading_system.py --mode paper
```

## Step 4: Monitor Streams

**Open a second terminal:**

```bash
conda activate crypto-bot
python scripts/monitor_redis_streams.py --tail
```

You should see real-time events like:
- ✓ Signal generation on `signals:paper`
- ✓ Status events on `kraken:status`
- ❌ Circuit breaker trips (if any)
- 🚨 Emergency stops (if any)

## Step 5: View Dashboard

**Open a third terminal:**

```bash
conda activate crypto-bot
python scripts/monitor_redis_streams.py
```

Shows statistics and recent entries for all streams.

---

## Common Commands

### Check Current Mode

```bash
redis-cli -u $REDIS_URL GET ACTIVE_SIGNALS
```

- `signals:paper` = Paper trading
- `signals:live` = Live trading ⚠️

### Emergency Stop

```bash
# Activate
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# Deactivate
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch
```

### View Recent Signals

```bash
python scripts/monitor_redis_streams.py --streams signals:paper --count 20
```

### Tail Specific Streams

```bash
python scripts/monitor_redis_streams.py --tail --streams signals:paper kraken:status
```

---

## Troubleshooting

### "REDIS_URL not set"

```bash
# Check .env file exists
cat .env | grep REDIS_URL

# Or set manually
export REDIS_URL="rediss://default:PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
```

### "Health check failed"

```bash
# Test Redis connection
redis-cli -u $REDIS_URL --tls PING

# Check logs
tail -50 logs/trading_system_*.log
```

### System won't start

```bash
# Verify conda env
conda info --envs | grep crypto-bot

# Check config
python scripts/start_trading_system.py --mode paper --dry-run

# Review errors in output
```

---

## Next Steps

1. **Monitor for 24-48 hours in PAPER mode**
   - Watch `signals:paper` for signal quality
   - Check circuit breakers aren't triggering frequently
   - Verify no unexpected errors

2. **Review Performance**
   ```bash
   # Check signal generation rate
   python scripts/monitor_redis_streams.py --streams signals:paper --count 100
   ```

3. **Set up monitoring dashboard** (optional)
   - Grafana for metrics visualization
   - Alerting for circuit breakers and emergencies

4. **Only when ready for LIVE:**
   - Review `OPERATIONS_RUNBOOK.md`
   - Follow "PAPER → LIVE" checklist
   - **Get authorization from trading lead**
   - Start with conservative limits

---

## Emergency?

**See:** `EMERGENCY_KILLSWITCH_QUICKREF.md`

**Fastest kill-switch:**
```bash
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| `OPERATIONS_RUNBOOK.md` | Complete operations guide |
| `EMERGENCY_KILLSWITCH_QUICKREF.md` | Emergency procedures |
| `docs/GO_LIVE_CONTROLS.md` | Technical documentation |
| `GO_LIVE_IMPLEMENTATION_SUMMARY.md` | Implementation details |

---

**You're ready to start!** 🚀

Run the health check and start the system in PAPER mode.
