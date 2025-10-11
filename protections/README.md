# Security & Safety Protection System

## Overview

This protection system implements comprehensive safety measures to prevent accidental live trading and provide emergency controls for the crypto trading bot.

## Features

### 1. Live Trading Guards

Prevents accidental live trading through dual environment variable checks:

- **MODE**: Must be set to `"live"` for live trading
- **LIVE_TRADING_CONFIRMATION**: Must be set to `"I-accept-the-risk"` for live trading

Both checks must pass for live trading to be enabled.

### 2. Global Kill Switch

Emergency halt system with multiple activation methods:

#### Activation Methods:

1. **Redis Key** (Recommended for remote control)
   ```bash
   # Activate with Redis CLI
   redis-cli SET control:halt_all "Emergency halt" EX 3600

   # Deactivate
   redis-cli DEL control:halt_all
   ```

2. **Environment Variable**
   ```bash
   export EMERGENCY_HALT=true
   ```

3. **Programmatic**
   ```python
   from protections.kill_switches import GlobalKillSwitch

   kill_switch = GlobalKillSwitch(redis_client)
   await kill_switch.activate(reason="Market crash", ttl_seconds=3600)
   ```

### 3. Paper Mode Enforcement

Decorator to ensure functions only execute in paper mode:

```python
from protections.kill_switches import enforce_paper_mode

@enforce_paper_mode(allow_live=False)
def sensitive_operation():
    # This will only run in paper mode
    pass
```

## Security Checks Summary

| Check | Purpose | Failure Behavior |
|-------|---------|------------------|
| MODE != "live" | Prevent live trading in paper mode | Block execution, exit with error |
| LIVE_TRADING_CONFIRMATION | Explicit acknowledgment required | Block execution, exit with error |
| Redis control:halt_all | Remote emergency stop | Pause trading, log alert |
| EMERGENCY_HALT env var | Local emergency stop | Pause trading, log alert |
| No hardcoded credentials | Prevent credential leaks | N/A - prevented by design |

## Setup

### 1. Configure Environment Variables

For **paper mode** (default, safe):
```bash
export MODE=paper
export LIVE_TRADING_CONFIRMATION=""
```

For **live mode** (DANGER - real money):
```bash
export MODE=live
export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
```

### 2. Redis Connection (Optional but Recommended)

For remote kill switch control:
```bash
export REDIS_URL="rediss://username:password@host:port/db"
```

**IMPORTANT**: NEVER hardcode Redis credentials in source code. Always use environment variables.

## Usage Examples

### Check Trading Mode

```python
from protections.kill_switches import get_trading_mode

mode = get_trading_mode()
print(f"Mode: {mode.mode}")              # "paper" or "live"
print(f"Paper mode: {mode.paper_mode}")  # True/False
print(f"Live allowed: {mode.is_live_allowed}")  # True/False
```

### Validate Live Trading

```python
from protections.kill_switches import check_live_trading_allowed

allowed, error = check_live_trading_allowed()
if not allowed:
    logger.error(f"Live trading blocked: {error}")
    sys.exit(1)
```

### Use Kill Switch in Trading Loop

```python
from protections.kill_switches import GlobalKillSwitch

kill_switch = GlobalKillSwitch(redis_client)

while True:
    # Check before each trading cycle
    if not await kill_switch.is_trading_allowed():
        status = kill_switch.get_status()
        logger.critical(f"Trading halted: {status['reason']}")
        await asyncio.sleep(10)
        continue

    # Execute trading logic
    await execute_trades()
```

### Activate Kill Switch via Redis

From anywhere with Redis access:

```bash
# Halt trading for 1 hour (3600 seconds)
redis-cli SET control:halt_all "Market volatility detected" EX 3600

# Check status
redis-cli GET control:halt_all

# Resume trading (remove halt)
redis-cli DEL control:halt_all
```

## Testing

Run the comprehensive test suite:

```bash
# Activate conda environment
conda activate crypto-bot

# Run tests
python -m protections.test_kill_switch
```

Test coverage:
- ✅ MODE validation
- ✅ LIVE_TRADING_CONFIRMATION validation
- ✅ Kill switch activation/deactivation
- ✅ Redis control key (if Redis available)
- ✅ Paper mode decorator
- ✅ Environment variable handling

## Integration with Main Bot

The protections are integrated into `main.py`:

```python
from protections.kill_switches import (
    check_live_trading_allowed,
    get_trading_mode,
    GlobalKillSwitch
)

# 1. Check mode before startup
trading_mode = get_trading_mode()
if args.mode == "live":
    allowed, error = check_live_trading_allowed()
    if not allowed:
        logger.error(f"Live trading blocked: {error}")
        sys.exit(1)

# 2. Initialize kill switch
kill_switch = GlobalKillSwitch()
kill_switch.set_redis_client(orchestrator.redis_client)

# 3. Check before each trading cycle
while not shutdown_requested:
    if not await kill_switch.is_trading_allowed():
        logger.critical("Trading halted by kill switch")
        await asyncio.sleep(10)
        continue

    # Execute trading...
```

## Security Audit Results

### ✅ Fixed Issues

1. **Removed hardcoded Redis credentials** from `utils/kraken_ws.py`:
   - Line 275: Changed to use environment variable
   - Line 1287: Changed to use environment variable

### ✅ Verified Safe

- `compose.env.example`: Contains example credentials (safe - it's a template)
- All other files: No hardcoded secrets found

## Emergency Procedures

### Emergency Stop (Multiple Methods)

#### Method 1: Redis (Fastest for Remote Control)
```bash
redis-cli SET control:halt_all "EMERGENCY STOP" EX 86400
```

#### Method 2: Environment Variable
```bash
export EMERGENCY_HALT=true
# Restart the bot
```

#### Method 3: Stop Bot Process
```bash
# Graceful shutdown
kill -SIGTERM <pid>

# Force shutdown (if needed)
kill -SIGKILL <pid>
```

### Verify Trading is Stopped

Check the logs for:
```
🚨 TRADING HALTED BY KILL SWITCH: [reason]
Trading paused. Deactivate kill switch to resume.
```

## Best Practices

1. **Always start in paper mode** and verify behavior before switching to live
2. **Keep Redis credentials in environment variables** - NEVER in code
3. **Set reasonable TTL on kill switch** to prevent indefinite halts
4. **Monitor logs** for kill switch activations
5. **Test kill switch regularly** to ensure it works when needed
6. **Have multiple kill switch methods** configured for redundancy

## Troubleshooting

### Live Trading Won't Enable

Check these in order:
1. `MODE` environment variable is set to "live"
2. `LIVE_TRADING_CONFIRMATION` is exactly "I-accept-the-risk" (case-sensitive)
3. No EMERGENCY_HALT environment variable is set
4. Redis control:halt_all key doesn't exist
5. Check logs for specific error messages

### Kill Switch Not Working

1. Verify Redis connection:
   ```bash
   redis-cli PING
   ```

2. Check if key exists:
   ```bash
   redis-cli GET control:halt_all
   ```

3. Verify bot is checking kill switch (check logs for "Kill switch" messages)

### Paper Mode Still Places Live Orders

This should be **impossible** with proper integration. If this happens:

1. **STOP THE BOT IMMEDIATELY**
2. Check MODE environment variable: `echo $MODE`
3. Review exchange API configuration
4. File a bug report with logs

## API Reference

### `check_live_trading_allowed() -> Tuple[bool, str]`
Returns whether live trading is allowed and error message if not.

### `get_trading_mode() -> TradingMode`
Returns current trading mode configuration.

### `GlobalKillSwitch`

#### Methods:
- `__init__(redis_client=None)` - Initialize kill switch
- `set_redis_client(client)` - Set/update Redis client
- `async activate(reason, ttl_seconds)` - Activate kill switch
- `async deactivate()` - Deactivate kill switch
- `async is_trading_allowed() -> bool` - Check if trading is allowed
- `get_status() -> dict` - Get current status

#### Status Dict:
```python
{
    "is_active": bool,
    "reason": str,
    "activation_time": float,
    "duration_seconds": float,
    "redis_key": str,
    "redis_connected": bool
}
```

### `@enforce_paper_mode(allow_live=False)`
Decorator to enforce paper mode on functions.

## License

Part of crypto_ai_bot project. Use at your own risk.

## Support

For issues or questions:
1. Check logs for error messages
2. Run test suite: `python -m protections.test_kill_switch`
3. Review this documentation
4. Check main bot documentation
