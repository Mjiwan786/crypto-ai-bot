# Protection Mode - Integration Guide

Quick integration guide for Protection Mode v1.0

---

## Quick Start

### 1. Install & Test

```bash
conda activate crypto-bot

# Run tests
python scripts/test_protection_mode.py

# Expected: 9/9 tests passing
```

### 2. Check Current Status

```python
from config.protection_mode_controller import get_protection_controller

controller = get_protection_controller()
print(controller.get_status_summary())
```

---

## Trading Agent Integration

### Minimal Integration (5 minutes)

```python
from config.protection_mode_controller import get_protection_controller

class TradingAgent:
    def __init__(self):
        # Get protection controller
        self.protection_controller = get_protection_controller()

    def execute_trade(self, params):
        # Adjust parameters based on protection mode
        adjusted_params = self.protection_controller.get_adjusted_parameters(params)

        # Use adjusted_params for trading
        return self.place_order(adjusted_params)

    def on_trade_close(self, trade):
        # Update equity
        equity = self.get_account_equity()
        self.protection_controller.update_equity(equity)

        # Update win streak
        if trade.pnl > 0:
            self.win_streak += 1
        else:
            self.win_streak = 0
        self.protection_controller.update_win_streak(self.win_streak)
```

### Full Integration with Callbacks

```python
from config.protection_mode_controller import get_protection_controller

class TradingAgent:
    def __init__(self):
        self.protection_controller = get_protection_controller()

        # Register callback for protection mode changes
        self.protection_controller.register_callback(self._on_protection_change)

        # Initialize with current config
        self._apply_protection_config(self.protection_controller.get_current_config())

    def _on_protection_change(self, param_name, new_value):
        """Hot-reload on protection mode changes."""
        if param_name == 'protection_mode_enabled':
            if new_value:
                self.logger.warning("[PROTECTION MODE ENABLED]")
                self.logger.warning("  Position sizes: 0.5x")
                self.logger.warning("  Stops: -30% tighter")
                self.logger.warning("  Max trades/min: -50%")
            else:
                self.logger.info("[PROTECTION MODE DISABLED]")
                self.logger.info("  Returning to normal risk parameters")

            # Refresh configuration
            self._apply_protection_config(self.protection_controller.get_current_config())

    def _apply_protection_config(self, config):
        """Apply protection mode configuration."""
        self.protection_enabled = config['enabled']
        self.position_multiplier = config['position_size_multiplier'] if config['enabled'] else 1.0
        self.stop_tightening = config['stop_loss_tightening_pct'] if config['enabled'] else 0.0

    def calculate_position_size(self, base_size_usd):
        """Calculate position size with protection mode applied."""
        if self.protection_controller.config.enabled:
            return base_size_usd * 0.5  # Halve size
        return base_size_usd

    def calculate_stop_loss(self, base_stop_bps):
        """Calculate stop loss with protection mode applied."""
        if self.protection_controller.config.enabled:
            return base_stop_bps * 0.7  # Tighten by 30%
        return base_stop_bps

    def get_max_trades_per_minute(self):
        """Get max trades/min with protection mode applied."""
        base_rate = 8
        if self.protection_controller.config.enabled:
            return int(base_rate * 0.5)  # Reduce by 50%
        return base_rate

    def execute_trade(self, signal):
        """Execute trade with protection mode adjustments."""
        # Calculate base parameters
        base_params = {
            'position_size_usd': 1000.0,
            'base_risk_pct': 1.5,
            'stop_loss_bps': 20.0,
            'max_trades_per_minute': 8,
        }

        # Get adjusted parameters
        adjusted_params = self.protection_controller.get_adjusted_parameters(base_params)

        # Execute with adjusted params
        self.logger.info(f"Position size: ${adjusted_params['position_size_usd']:.2f}")
        self.logger.info(f"Stop loss: {adjusted_params['stop_loss_bps']:.1f} bps")

        return self.place_order(adjusted_params)

    def on_trade_close(self, trade):
        """Handle trade close - update protection mode triggers."""
        # Update equity
        equity = self.get_account_equity()
        self.protection_controller.update_equity(equity)

        # Update win streak
        if trade.pnl > 0:
            self.win_streak += 1
        else:
            self.win_streak = 0
        self.protection_controller.update_win_streak(self.win_streak)

        # Optionally publish status to Redis
        asyncio.create_task(self.protection_controller.publish_status_update())
```

---

## Redis Integration

### Publishing Status Updates

```python
import asyncio
from config.protection_mode_controller import get_protection_controller

async def publish_protection_status():
    controller = get_protection_controller()

    # Connect to Redis
    await controller.connect_redis()

    # Publish status
    await controller.publish_status_update()
```

### Subscribing to Commands

```python
import asyncio
from config.protection_mode_controller import get_protection_controller

async def monitor_protection_commands():
    controller = get_protection_controller()

    # Connect to Redis
    await controller.connect_redis()

    # Subscribe to commands (blocking)
    await controller.subscribe_to_commands()

# Run in background task
asyncio.create_task(monitor_protection_commands())
```

### Manual Commands via Redis

```bash
# Enable protection mode
redis-cli -u $REDIS_URL XADD protection:commands * command enable

# Disable protection mode
redis-cli -u $REDIS_URL XADD protection:commands * command disable

# Enable manual override
redis-cli -u $REDIS_URL XADD protection:commands * command enable_manual_override

# Update equity
redis-cli -u $REDIS_URL XADD protection:commands * command update_equity equity_usd 20000

# Update win streak
redis-cli -u $REDIS_URL XADD protection:commands * command update_win_streak win_streak 6
```

---

## Configuration

### config/protection_mode.yaml

```yaml
# Mode control
enabled: false  # Current state (auto-managed)
auto_enable: true  # Auto-enable based on triggers
manual_override: false  # Manual override (ignores triggers)

# Triggers
triggers:
  equity_threshold_usd: 18000.0  # Protect profits at $18k
  win_streak_threshold: 5  # Reduce risk after 5 consecutive wins

# Protection parameters (applied when enabled)
parameters:
  position_size_multiplier: 0.5  # Halve all position sizes
  stop_loss_tightening_pct: 0.3  # Tighten stops by 30%
  max_trades_per_minute_reduction_pct: 0.5  # Reduce by 50%

# Hysteresis (prevent oscillation)
hysteresis:
  equity_exit_pct: 0.95  # Exit protection at 95% of threshold ($17,100)
  win_streak_exit: 0  # Exit when streak breaks
```

---

## Examples

### Example 1: Basic Usage

```python
from config.protection_mode_controller import get_protection_controller

# Get controller
controller = get_protection_controller()

# Simulate trading
equity = 15000.0  # Starting equity

# Trade 1: Win (+$500)
equity += 500
controller.update_equity(equity)
controller.update_win_streak(1)
print(f"Trade 1: Equity=${equity:.2f}, Protection={controller.config.enabled}")

# Trade 2: Win (+$600)
equity += 600
controller.update_equity(equity)
controller.update_win_streak(2)
print(f"Trade 2: Equity=${equity:.2f}, Protection={controller.config.enabled}")

# ... continue winning trades ...

# Trade 5: Win (+$550) -> Crosses $18k AND hits 5-win streak
equity += 550  # Now $18,150
controller.update_equity(equity)
controller.update_win_streak(5)
print(f"Trade 5: Equity=${equity:.2f}, Protection={controller.config.enabled}")
# Output: Trade 5: Equity=$18150.00, Protection=True

# Trade 6: Win (+$200) -> Protection mode active, halved size
equity += 200  # Smaller win due to halved position
controller.update_equity(equity)
controller.update_win_streak(6)
print(f"Trade 6: Equity=${equity:.2f}, Protection={controller.config.enabled}")
# Output: Trade 6: Equity=$18350.00, Protection=True
```

### Example 2: Parameter Adjustment

```python
from config.protection_mode_controller import get_protection_controller

controller = get_protection_controller()

# Simulate $20k equity (triggers protection mode)
controller.update_equity(20000.0)

# Base trading parameters
base_params = {
    'position_size_usd': 1000.0,
    'base_risk_pct': 1.5,
    'stop_loss_bps': 20.0,
    'max_trades_per_minute': 8,
}

print("Base parameters:")
for k, v in base_params.items():
    print(f"  {k}: {v}")

# Get adjusted parameters
adjusted = controller.get_adjusted_parameters(base_params)

print("\nProtection Mode adjusted parameters:")
for k, v in adjusted.items():
    print(f"  {k}: {v}")

# Output:
# Base parameters:
#   position_size_usd: 1000.0
#   base_risk_pct: 1.5
#   stop_loss_bps: 20.0
#   max_trades_per_minute: 8
#
# Protection Mode adjusted parameters:
#   position_size_usd: 500.0    <- Halved
#   base_risk_pct: 0.75         <- Halved
#   stop_loss_bps: 14.0         <- 30% tighter
#   max_trades_per_minute: 4    <- 50% reduced
```

### Example 3: Change Callbacks

```python
from config.protection_mode_controller import get_protection_controller

controller = get_protection_controller()

# Define callback
def on_protection_change(param_name, new_value):
    print(f"[CALLBACK] {param_name} = {new_value}")

    if param_name == 'protection_mode_enabled':
        if new_value:
            print("  Switching to conservative risk parameters")
        else:
            print("  Switching to normal risk parameters")

# Register callback
controller.register_callback(on_protection_change)

# Trigger protection mode (will call callback)
controller.update_equity(20000.0)

# Output:
# [CALLBACK] protection_mode_enabled = True
#   Switching to conservative risk parameters
```

---

## Testing

### Run Full Test Suite

```bash
python scripts/test_protection_mode.py
```

**Expected output:**
```
[PASS] yaml_loading
[PASS] equity_trigger
[PASS] win_streak_trigger
[PASS] hysteresis
[PASS] manual_override
[PASS] parameter_adjustment
[PASS] change_callbacks
[PASS] singleton_pattern
[PASS] redis_integration

Total: 9/9 tests passed
```

### Manual Testing

```python
from config.protection_mode_controller import ProtectionModeController

# Create controller
controller = ProtectionModeController()
controller.load_from_yaml()

# Test equity trigger
print("Testing equity trigger...")
controller.update_equity(20000.0)
assert controller.config.enabled == True
print("[PASS] Enabled at $20k")

# Test hysteresis
print("\nTesting hysteresis...")
controller.update_equity(17500.0)
assert controller.config.enabled == True
print("[PASS] Still enabled at $17.5k (hysteresis)")

controller.update_equity(16000.0)
assert controller.config.enabled == False
print("[PASS] Disabled at $16k (below hysteresis)")

# Test manual override
print("\nTesting manual override...")
controller.enable_manual_override()
controller.update_equity(10000.0)
assert controller.config.enabled == True
print("[PASS] Manual override keeps protection ON")

controller.disable_manual_override()
assert controller.config.enabled == False
print("[PASS] Manual override disabled, auto mode resumed")
```

---

## Troubleshooting

### Issue: Protection mode not enabling

**Check auto_enable flag:**
```python
from config.protection_mode_controller import get_protection_controller

controller = get_protection_controller()
print(f"Auto enable: {controller.config.auto_enable}")

# If False, enable it
controller.config.auto_enable = True
```

**Manually trigger:**
```bash
redis-cli -u $REDIS_URL XADD protection:commands * command enable
```

### Issue: Protection mode stuck ON

**Check manual override:**
```python
from config.protection_mode_controller import get_protection_controller

controller = get_protection_controller()
print(f"Manual override: {controller.config.manual_override}")

# Disable manual override
controller.disable_manual_override()
```

### Issue: Want different thresholds

**Edit config:**
```bash
vim config/protection_mode.yaml

# Change equity_threshold_usd to 20000.0 (or desired value)
# Change win_streak_threshold to 7 (or desired value)

# Restart trading system
```

---

## Next Steps

1. ✅ Test protection mode: `python scripts/test_protection_mode.py`
2. ✅ Integrate with trading agent (update equity & win streak)
3. ✅ Test in paper trading environment
4. ✅ Monitor protection mode events
5. ✅ Deploy to production

---

*Protection Mode Integration Guide - v1.0*
*Status: Production Ready | Tests: 9/9 Passing*
