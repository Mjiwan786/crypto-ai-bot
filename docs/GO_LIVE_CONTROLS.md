# Go-Live Controls - Production Deployment Safety

## Overview

The Go-Live Controls system provides multi-layer safety checks to prevent accidental real-money trading. It enforces explicit confirmation, emergency stop capabilities, and trading limits before allowing LIVE mode operation.

## Features

1. **Paper/Live Mode Switching** - Single Redis alias (`ACTIVE_SIGNALS`) controls signal routing
2. **LIVE Confirmation Guard** - Requires exact phrase `I-accept-the-risk` to enable LIVE trading
3. **Emergency Kill-Switch** - Instant halt of new entries via env var or Redis key
4. **Pair Whitelist** - Restrict trading to approved pairs only
5. **Notional Caps** - Enforce maximum order size per pair
6. **Circuit Breaker Monitoring** - Auto-stop on latency/spread/rate-limit violations

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ TradingModeController                                       │
│                                                             │
│  ┌──────────────┐        ┌──────────────┐                 │
│  │ PAPER Mode   │  ←────→│  LIVE Mode   │                 │
│  │ signals:paper│        │ signals:live │                 │
│  └──────────────┘        └──────────────┘                 │
│         ↑                        ↑                          │
│         └────── ACTIVE_SIGNALS ──┘                          │
│                                                             │
│  Safety Checks:                                             │
│  ✓ LIVE_TRADING_CONFIRMATION = "I-accept-the-risk"        │
│  ✓ KRAKEN_EMERGENCY_STOP ≠ true                           │
│  ✓ Pair in whitelist                                       │
│  ✓ Notional ≤ cap                                          │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

### Environment Variables

```bash
# Trading mode (default: PAPER)
TRADING_MODE=PAPER

# LIVE mode confirmation (REQUIRED for LIVE trading)
# Must be set to EXACTLY this phrase:
LIVE_TRADING_CONFIRMATION=I-accept-the-risk

# Emergency kill-switch (set to 'true' to halt all entries)
KRAKEN_EMERGENCY_STOP=false

# Pair whitelist (comma-separated, empty = allow all)
TRADING_PAIR_WHITELIST=XBTUSD,ETHUSD

# Notional caps per pair in USD (format: PAIR:CAP,PAIR:CAP)
NOTIONAL_CAPS=XBTUSD:10000,ETHUSD:5000

# Maximum daily volume across all pairs
MAX_DAILY_VOLUME=1000000
```

### Redis Keys

- **`ACTIVE_SIGNALS`** - Points to either `signals:paper` or `signals:live`
- **`kraken:emergency:kill_switch`** - Emergency stop flag (true/false)

### Kraken YAML Config

File: `config/exchange_configs/kraken.yaml`

```yaml
auth:
  security:
    require_live_confirmation: "${LIVE_TRADING_CONFIRMATION:}"

  safety:
    kill_switch_env: "KRAKEN_EMERGENCY_STOP"
    kill_switch_redis_key: "kraken:emergency:kill_switch"
    pair_whitelist: "${TRADING_PAIR_WHITELIST:}"
    notional_caps: "${NOTIONAL_CAPS:}"
```

## Usage

### 1. Initialize Controller

```python
from config.trading_mode_controller import TradingModeController
import redis

# Connect to Redis Cloud
redis_client = redis.from_url(
    "rediss://default:PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818",
    ssl=True,
    decode_responses=True
)

# Initialize controller with safety limits
controller = TradingModeController(
    redis_client=redis_client,
    pair_whitelist=['XBTUSD', 'ETHUSD'],
    notional_caps={'XBTUSD': 10000.0, 'ETHUSD': 5000.0}
)
```

### 2. Check Safety Before Trading

```python
# Comprehensive safety check before placing order
result = controller.check_can_trade(
    pair='XBTUSD',
    notional_usd=5000.0,
    operation='entry'  # or 'exit'
)

if result.passed:
    # Safe to trade
    stream = controller.get_active_signal_stream()
    redis_client.xadd(stream, {
        'signal': 'BUY',
        'pair': 'XBTUSD',
        'notional': 5000.0
    })
else:
    # Blocked by safety checks
    logger.error(f"Trading blocked: {result.errors}")
```

### 3. Switch Modes (PAPER ↔ LIVE)

```python
from config.trading_mode_controller import TradingMode

# Switch to LIVE (requires LIVE_TRADING_CONFIRMATION env var)
success = controller.switch_mode(TradingMode.LIVE)
if success:
    logger.info("Switched to LIVE mode - real money at risk")
else:
    logger.error("Cannot switch to LIVE: missing confirmation")

# Switch back to PAPER
controller.switch_mode(TradingMode.PAPER)
```

### 4. Emergency Stop

```python
# Activate emergency stop (halts all new entries)
controller.activate_emergency_stop(reason="Market anomaly detected")

# Check if emergency stop is active
if controller.is_emergency_stop_active():
    logger.warning("Emergency stop active - no new entries")

# Deactivate when safe to resume
controller.deactivate_emergency_stop()
```

### 5. Circuit Breaker Monitoring

```python
from config.trading_mode_controller import CircuitBreakerMonitor

monitor = CircuitBreakerMonitor(
    redis_client=redis_client,
    mode_controller=controller,
    latency_threshold_ms=1000.0,
    spread_threshold_bps=50.0
)

# Check latency before trading
if not monitor.check_latency(latency_ms=850.0, pair='XBTUSD'):
    logger.error("Latency too high - circuit breaker tripped")

# Check spread before trading
if not monitor.check_spread(spread_bps=25.0, pair='XBTUSD'):
    logger.error("Spread too wide - circuit breaker tripped")

# Report violations (auto-publishes to Redis)
monitor.report_rate_limit_violation('XBTUSD', {'limit': '1 req/sec'})
monitor.report_websocket_disconnect('XBTUSD', {'reason': 'timeout'})
```

## Redis Streams

Circuit breakers and mode changes publish events to Redis for monitoring:

### Stream: `metrics:circuit_breakers`

```json
{
  "event": "circuit_breaker_tripped",
  "breaker_type": "latency",
  "pair": "XBTUSD",
  "latency_ms": 1500.0,
  "threshold_ms": 1000.0,
  "timestamp": "2025-10-18T12:34:56.789Z",
  "mode": "LIVE"
}
```

### Stream: `kraken:status`

```json
{
  "status": "circuit_breaker",
  "event": "circuit_breaker_tripped",
  "breaker_type": "spread",
  "pair": "ETHUSD",
  "spread_bps": 75.0,
  "threshold_bps": 50.0,
  "timestamp": "2025-10-18T12:35:00.000Z"
}
```

### Stream: `metrics:mode_changes`

```json
{
  "event": "trading_mode_changed",
  "old_mode": "PAPER",
  "new_mode": "LIVE",
  "timestamp": "2025-10-18T12:00:00.000Z"
}
```

### Stream: `metrics:emergency`

```json
{
  "event": "emergency_stop_activated",
  "reason": "Auto-stop: rate_limit on XBTUSD",
  "timestamp": "2025-10-18T12:45:00.000Z",
  "mode": "LIVE"
}
```

## Testing

Run the comprehensive test suite:

```bash
# Set up environment
export REDIS_URL="rediss://default:PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"

# Run tests
conda activate crypto-bot
python scripts/test_golive_controls.py
```

Expected output:
```
=== Test 1: Basic Initialization ===
✓ PASS: Controller initializes in PAPER mode
✓ PASS: ACTIVE_SIGNALS points to signals:paper

=== Test 2: LIVE Mode Confirmation ===
✓ PASS: LIVE mode without confirmation is invalid
✓ PASS: Trading blocked without LIVE confirmation
✓ PASS: Correct confirmation phrase is valid

... (more tests)

Test Suite Summary
==================
Passed: 25
Failed: 0
Total:  25
Success Rate: 100.0%

✓ ALL TESTS PASSED
```

## Production Deployment Checklist

Before going LIVE, verify:

- [ ] `TRADING_MODE=PAPER` in `.env` (start in paper mode)
- [ ] `LIVE_TRADING_CONFIRMATION` is **NOT** set initially
- [ ] `KRAKEN_EMERGENCY_STOP=false`
- [ ] `TRADING_PAIR_WHITELIST` contains only approved pairs
- [ ] `NOTIONAL_CAPS` are set conservatively
- [ ] Redis Cloud TLS connection is working
- [ ] All tests pass: `python scripts/test_golive_controls.py`
- [ ] Monitoring dashboard is set up for `metrics:*` and `kraken:status` streams
- [ ] Emergency stop procedures are documented and tested
- [ ] Team is trained on kill-switch activation

### Going LIVE (Step-by-Step)

1. **Paper Trading Validation** - Run in PAPER mode for 24-48 hours
   ```bash
   TRADING_MODE=PAPER python scripts/start_trading_system.py
   ```

2. **Review Performance** - Check PnL, fills, and error rates
   ```bash
   python scripts/health_check_pnl.py
   ```

3. **Enable LIVE Confirmation** - Set the magic phrase in `.env`
   ```bash
   LIVE_TRADING_CONFIRMATION=I-accept-the-risk
   ```

4. **Switch to LIVE Mode**
   ```bash
   TRADING_MODE=LIVE python scripts/start_trading_system.py
   ```

5. **Monitor Closely** - Watch `metrics:*` and `kraken:status` streams
   ```bash
   redis-cli -u $REDIS_URL XREAD STREAMS metrics:circuit_breakers kraken:status $ $
   ```

6. **Emergency Stop if Needed**
   ```bash
   # Environment variable (requires restart)
   export KRAKEN_EMERGENCY_STOP=true

   # Or via Redis (instant)
   redis-cli -u $REDIS_URL SET kraken:emergency:kill_switch true
   ```

## Safety Philosophy

**Defense in Depth:**
1. Env var check (`LIVE_TRADING_CONFIRMATION`)
2. Pair whitelist enforcement
3. Notional cap enforcement
4. Emergency kill-switch (env + Redis)
5. Circuit breaker monitoring
6. Status event publishing for observability

**Fail-Safe Defaults:**
- Default mode: PAPER
- Default emergency stop: inactive
- Default whitelist: empty (block all if misconfigured)
- Circuit breakers: auto-activate emergency stop on critical failures

**Exit Always Allowed:**
- Emergency stops block **entries** only
- **Exits** are always permitted to close positions safely

## Troubleshooting

### "Trading blocked: missing confirmation"

Set the exact phrase in `.env`:
```bash
LIVE_TRADING_CONFIRMATION=I-accept-the-risk
```

### "Emergency stop is active"

Check both sources:
```bash
# Environment variable
echo $KRAKEN_EMERGENCY_STOP

# Redis key
redis-cli -u $REDIS_URL GET kraken:emergency:kill_switch
```

Deactivate:
```bash
export KRAKEN_EMERGENCY_STOP=false
redis-cli -u $REDIS_URL DEL kraken:emergency:kill_switch
```

### "Pair not in whitelist"

Add to `.env`:
```bash
TRADING_PAIR_WHITELIST=XBTUSD,ETHUSD,SOLUSD
```

### "Order exceeds notional cap"

Adjust caps in `.env`:
```bash
NOTIONAL_CAPS=XBTUSD:20000,ETHUSD:10000
```

## References

- **Code**: `config/trading_mode_controller.py`
- **Tests**: `scripts/test_golive_controls.py`
- **Config**: `config/exchange_configs/kraken.yaml`
- **PRD**: `PRD_AGENTIC.md` (Section 9)

---

**Remember**: LIVE mode = real money at risk. Always validate in PAPER mode first.
