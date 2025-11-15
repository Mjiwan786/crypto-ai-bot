# Emergency Kill-Switch - Quick Reference Card

**KEEP THIS ACCESSIBLE DURING LIVE TRADING**

## Emergency Stop Activation

### Method 1: Redis (Instant - No Restart Required) ⚡ FASTEST

```bash
# Using redis-cli
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# Full command with credentials
redis-cli -u rediss://default:PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls SET kraken:emergency:kill_switch true
```

### Method 2: Environment Variable (Requires Restart)

```bash
# Set in .env file
KRAKEN_EMERGENCY_STOP=true

# Or export in shell
export KRAKEN_EMERGENCY_STOP=true

# Then restart trading system
```

### Method 3: Python API

```python
from config.trading_mode_controller import TradingModeController
import redis

redis_client = redis.from_url(os.getenv('REDIS_URL'), ...)
controller = TradingModeController(redis_client=redis_client)

controller.activate_emergency_stop(reason="Market anomaly detected")
```

## Verify Emergency Stop is Active

```bash
# Check Redis
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch

# Check environment
echo $KRAKEN_EMERGENCY_STOP

# Check via Python
python -c "from config.trading_mode_controller import TradingModeController; import redis; import os; r = redis.from_url(os.getenv('REDIS_URL')); c = TradingModeController(r); print('ACTIVE' if c.is_emergency_stop_active() else 'INACTIVE')"
```

## Deactivate Emergency Stop

### Method 1: Redis

```bash
# Delete the key
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch
```

### Method 2: Environment Variable

```bash
# Unset or set to false
export KRAKEN_EMERGENCY_STOP=false

# Or remove from .env
# Then restart
```

### Method 3: Python API

```python
controller.deactivate_emergency_stop()
```

## What Emergency Stop Does

### Blocked ❌
- **New entries** - All new position-opening orders blocked
- **Signal generation** - Signals fail safety checks
- **Order submissions** - Entry orders rejected by controller

### Allowed ✅
- **Position exits** - Closing existing positions still allowed
- **Order cancellations** - Can cancel open orders
- **Market data** - Continues to flow
- **Monitoring** - Health checks continue

## Emergency Stop Triggers

Emergency stop auto-activates on:
1. **Rate limit violation** - Exchange API rate limit hit
2. **WebSocket disconnect** - Critical data feed lost

Manual activation recommended for:
- Unexpected market behavior
- Strategy malfunction
- Risk limit breach
- Exchange maintenance
- Regulatory concerns
- System issues

## Monitoring Emergency Stop Events

```bash
# Watch emergency events stream
redis-cli -u $REDIS_URL XREAD STREAMS metrics:emergency $

# Watch status stream
redis-cli -u $REDIS_URL XREAD STREAMS kraken:status $

# Get last emergency event
redis-cli -u $REDIS_URL XREVRANGE metrics:emergency + - COUNT 1
```

## Common Emergency Scenarios

### Scenario 1: Unexpected Market Spike

```bash
# Immediate stop
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# Verify active
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch
# Output: true

# Monitor positions
# Close positions manually if needed

# When safe, deactivate
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch
```

### Scenario 2: Exchange Maintenance

```bash
# Before maintenance window
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# Close all positions gracefully (exits still work)

# During maintenance
# System can continue running, no new entries

# After maintenance
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch
```

### Scenario 3: Strategy Malfunction

```bash
# Stop immediately
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# Review logs
tail -f logs/kraken.log

# Check recent signals
redis-cli -u $REDIS_URL XREVRANGE signals:live + - COUNT 10

# Fix issue
# Test in paper mode
# When validated, deactivate
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch
```

## Status Verification

```bash
# Get full controller status
python -c "
from config.trading_mode_controller import TradingModeController
import redis, os, json

r = redis.from_url(os.getenv('REDIS_URL'))
c = TradingModeController(r)
status = c.get_status()
print(json.dumps(status, indent=2))
"
```

Expected output:
```json
{
  "mode": "LIVE",
  "active_signal_stream": "signals:live",
  "emergency_stop_active": false,
  "live_confirmation_valid": true,
  "pair_whitelist": ["XBTUSD", "ETHUSD"],
  "notional_caps": {"XBTUSD": 10000.0},
  "timestamp": "2025-10-18T12:00:00.000Z"
}
```

## Emergency Contact Chain

1. **Immediate Action**: Activate kill-switch (see methods above)
2. **Log Incident**: Record reason, time, and actions taken
3. **Notify Team**: Alert relevant stakeholders
4. **Assess Impact**: Check positions, orders, PnL
5. **Root Cause**: Investigate trigger
6. **Resolution**: Fix issue, test in paper mode
7. **Deactivate**: Only when safe to resume
8. **Post-Mortem**: Document lessons learned

## Pre-Flight Checklist (Before Going LIVE)

- [ ] Verify Redis connection: `redis-cli -u $REDIS_URL PING`
- [ ] Test kill-switch activation: Set and verify flag
- [ ] Test kill-switch deactivation: Delete and verify removal
- [ ] Verify emergency events stream: Check `metrics:emergency` exists
- [ ] Document incident response procedure
- [ ] Train team on kill-switch activation
- [ ] Set up monitoring alerts for emergency events
- [ ] Test in paper mode first

## Troubleshooting

### Kill-Switch Not Activating

```bash
# Check Redis connection
redis-cli -u $REDIS_URL PING

# Manually set key
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# Verify set
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch

# Check controller reads it
python -c "from config.trading_mode_controller import TradingModeController; import redis, os; r = redis.from_url(os.getenv('REDIS_URL')); c = TradingModeController(r); print(c.is_emergency_stop_active())"
```

### Kill-Switch Stuck Active

```bash
# Force delete Redis key
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch

# Unset environment variable
unset KRAKEN_EMERGENCY_STOP

# Restart trading system
```

### Can't Connect to Redis

```bash
# Test connection
redis-cli -u $REDIS_URL --tls PING

# Check credentials in .env
cat .env | grep REDIS_URL

# Verify TLS certificate (if using custom CA)
openssl s_client -connect redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

## Important Notes

⚠️ **Emergency stop blocks NEW ENTRIES only**
✅ **Exits are ALWAYS allowed** - You can close positions even with emergency stop active
⚡ **Redis method is INSTANT** - No system restart needed
📊 **All events are logged** - Check `metrics:emergency` stream for audit trail
🔄 **Safe to test** - Activate/deactivate freely in paper mode

## Quick Commands Summary

```bash
# Activate (instant)
redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true

# Deactivate
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch

# Check status
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch

# Watch events
redis-cli -u $REDIS_URL XREAD BLOCK 0 STREAMS metrics:emergency $
```

---

**Keep this reference accessible at all times during live trading.**

**For detailed documentation, see:** `docs/GO_LIVE_CONTROLS.md`
**For implementation details, see:** `config/trading_mode_controller.py`
**For tests, see:** `scripts/test_golive_controls.py`
