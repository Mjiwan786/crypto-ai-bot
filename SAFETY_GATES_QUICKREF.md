# Safety Gates Quick Reference

## Emergency Actions

### Stop All Trading Immediately
```bash
# Method 1: Environment variable
export KRAKEN_EMERGENCY_STOP=true

# Method 2: Redis
redis-cli -u $REDIS_URL set kraken:emergency:kill_switch "true"

# Method 3: Python
python -c "
from protections.safety_gates import EmergencyKillSwitch
import redis
r = redis.from_url('$REDIS_URL')
emergency = EmergencyKillSwitch(r)
emergency.activate('Manual stop')
"
```

### Resume Trading
```bash
# Method 1: Environment
unset KRAKEN_EMERGENCY_STOP

# Method 2: Redis
redis-cli -u $REDIS_URL del kraken:emergency:kill_switch

# Method 3: Python
emergency.deactivate()
```

## Mode Switching

### Check Current Mode
```bash
echo $MODE  # Should be PAPER or LIVE
redis-cli -u $REDIS_URL get ACTIVE_SIGNALS  # shows target stream
```

### Switch to PAPER
```bash
export MODE=PAPER
# Restart system
```

### Switch to LIVE
```bash
export MODE=LIVE
export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
# Restart system
```

## Pair Management

### Restrict Trading Pairs
```bash
# Only allow BTC and ETH
export TRADING_PAIR_WHITELIST="XBTUSD,ETHUSD"
```

### Set Notional Caps
```bash
# Cap BTC at $10k, ETH at $5k
export NOTIONAL_CAPS="XBTUSD:10000,ETHUSD:5000"
```

### Check Pair Status
```python
from protections.safety_gates import PairWhitelistEnforcer

enforcer = PairWhitelistEnforcer()
print(enforcer.is_pair_allowed("XBTUSD"))
print(enforcer.get_limits("XBTUSD"))
```

## Circuit Breakers

### Check Active Breakers
```python
from protections.safety_gates import CircuitBreaker

breaker = CircuitBreaker(redis_client)
active = breaker.get_all_active()

for key, status in active.items():
    print(f"{key}: resumes at {status.resume_time}")
```

### Monitor from Redis
```bash
# Watch circuit breaker events
redis-cli -u $REDIS_URL XREAD STREAMS metrics:circuit_breakers 0
```

## Safety Check Before Trade

```python
from protections.safety_gates import SafetyController

controller = SafetyController(redis_client)

result = controller.check_can_enter_trade(
    pair="XBTUSD",
    notional_usd=5000.0,
    spread_bps=30.0,
    latency_ms=400.0
)

if not result.can_trade:
    print("BLOCKED:")
    for error in result.errors:
        print(f"  - {error}")
else:
    print("OK to trade")
```

## Status Monitoring

### Check All Safety Gates
```python
controller = SafetyController(redis_client)

# MODE
mode = controller.mode_switch.get_mode_config()
print(f"Mode: {mode.mode}, Stream: {mode.active_signal_stream}")

# Emergency
emergency = controller.emergency_stop.get_status()
print(f"Emergency: {emergency.is_active}, Reason: {emergency.reason}")

# Pairs
pairs = controller.pair_enforcer.get_all_whitelisted_pairs()
print(f"Whitelisted pairs: {pairs}")

# Breakers
active_breakers = controller.circuit_breaker.get_all_active()
print(f"Active breakers: {len(active_breakers)}")
```

### Redis Streams to Monitor
```bash
# Status events
redis-cli -u $REDIS_URL XREAD STREAMS kraken:status 0

# Emergency events
redis-cli -u $REDIS_URL XREAD STREAMS metrics:emergency 0

# Circuit breakers
redis-cli -u $REDIS_URL XREAD STREAMS metrics:circuit_breakers 0

# Mode changes
redis-cli -u $REDIS_URL XREAD STREAMS metrics:mode_changes 0
```

## Common Issues

### Issue: LIVE mode blocked

**Cause:** Missing confirmation

**Fix:**
```bash
export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
```

### Issue: Pair blocked

**Cause:** Not in whitelist or YAML config

**Fix:**
```bash
# Add to whitelist
export TRADING_PAIR_WHITELIST="XBTUSD,ETHUSD,YOUR_PAIR"

# Or remove whitelist to allow all configured pairs
unset TRADING_PAIR_WHITELIST
```

### Issue: Circuit breaker stuck

**Cause:** Waiting for auto-recovery

**Fix:**
```python
# Check resume time
status = breaker.get_status("spread_XBTUSD")
print(f"Resumes at: {status.resume_time}")

# Or manually clear (not recommended)
breaker._clear_breaker("spread_XBTUSD")
```

## Testing

### Run Test Suite
```bash
python tests/test_safety_gates_j1_j3.py
```

### Test Emergency Stop
```bash
# Activate
export KRAKEN_EMERGENCY_STOP=true

# Verify (should be blocked)
python -c "
from protections.safety_gates import EmergencyKillSwitch
e = EmergencyKillSwitch()
print(e.is_active())  # True
"

# Deactivate
unset KRAKEN_EMERGENCY_STOP
```

## Production Checklist

Before going live:

- [ ] MODE=LIVE set
- [ ] LIVE_TRADING_CONFIRMATION set correctly
- [ ] KRAKEN_EMERGENCY_STOP=false
- [ ] TRADING_PAIR_WHITELIST configured (if using)
- [ ] NOTIONAL_CAPS set appropriately
- [ ] Redis connection working
- [ ] ACTIVE_SIGNALS pointing to signals:live
- [ ] Test emergency stop works
- [ ] Monitor kraken:status stream
- [ ] Grafana dashboards set up

## Support

**Full Documentation:** `J_SAFETY_KILLSWITCHES_COMPLETE.md`

**Test Suite:** `tests/test_safety_gates_j1_j3.py`

**Module:** `protections/safety_gates.py`

---

**Emergency Contact:** Check OPERATIONS_RUNBOOK.md for incident response procedures
