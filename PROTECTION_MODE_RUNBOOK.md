# Protection Mode Runbook

**Version**: v1.1
**Date**: 2025-11-08
**Feature**: Automatic Capital Preservation System

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [Configuration](#configuration)
4. [Activation Triggers](#activation-triggers)
5. [Parameter Adjustments](#parameter-adjustments)
6. [Manual Override](#manual-override)
7. [Monitoring](#monitoring)
8. [Testing](#testing)
9. [Troubleshooting](#troubleshooting)
10. [FAQ](#faq)

---

## Overview

**Protection Mode** is an automatic capital preservation system that activates when your account equity nears the target ($20k). It reduces risk by:

- **Halving position sizes** (risk_multiplier: 0.5)
- **Tightening stop losses** (sl_multiplier: 0.7)
- **Reducing trade frequency** (rate_multiplier: 0.5)
- **Optional tighter take profits** (tp_multiplier: configurable)

### Why Protection Mode?

When you're **80% of the way to your target** (equity ≥ $18k), the priority shifts from aggressive growth to **capital preservation**. Protection Mode automatically makes trading more conservative to lock in gains.

### Key Features

✅ **Automatic activation** based on equity or win streak
✅ **Manual override** via YAML config or API
✅ **Seamless integration** with existing strategies
✅ **Real-time monitoring** via Redis and Prometheus
✅ **Full audit trail** of activations/deactivations

---

## How It Works

### Activation Triggers

Protection Mode activates when **EITHER** condition is met:

1. **Equity Threshold**: `current_equity ≥ $18,000`
2. **Win Streak**: `consecutive_wins ≥ 5`

### What Happens When Activated

When protection mode activates, the system:

1. **Logs activation** with trigger reason
2. **Applies multipliers** to strategy parameters
3. **Publishes state** to Redis (`protection:mode:state`)
4. **Sends alert** to configured channels (Discord, Prometheus)
5. **Starts tracking** trades since activation

### Example

**Before Protection Mode** (Normal aggressive mode):
```yaml
risk_per_trade_pct: 1.2%
sl_atr: 1.5
tp1_atr: 2.5
max_trades_per_minute: 10
```

**After Protection Mode Activates** (Conservative):
```yaml
risk_per_trade_pct: 0.6%  # 1.2% × 0.5
sl_atr: 1.05              # 1.5 × 0.7
tp1_atr: 2.5              # unchanged (tp_multiplier: 1.0)
max_trades_per_minute: 5  # 10 × 0.5
```

**Net Effect**: Risk cut in half, stops tightened, fewer trades.

---

## Configuration

### YAML Config

Add to your strategy config (e.g., `bar_reaction_5m_aggressive.yaml`):

```yaml
protection_mode:
  enabled: true
  force_enabled: null  # Manual override: true/false/null (auto)

  # Activation triggers
  equity_threshold_usd: 18000.0  # Activate when equity ≥ $18k
  win_streak_threshold: 5  # Activate after 5 consecutive wins

  # Protection adjustments (multipliers applied to base params)
  risk_multiplier: 0.5  # Halve position sizes
  sl_multiplier: 0.7    # Tighten stops to 70%
  tp_multiplier: 1.0    # Keep targets same (or 0.8 to tighten)
  rate_multiplier: 0.5  # Reduce max trades/min to 50%

  # Deactivation criteria
  deactivate_on_loss: false  # Stay in protection mode even after a loss
  deactivate_below_equity: 17000.0  # Re-enable aggression if equity drops below $17k

  # Alerts
  alert_on_activation: true
  alert_on_deactivation: true
```

### Config Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | bool | `true` | Enable/disable protection mode globally |
| `force_enabled` | bool\|null | `null` | Manual override (true/false/null for auto) |
| `equity_threshold_usd` | float | `18000.0` | Equity level to trigger protection mode |
| `win_streak_threshold` | int | `5` | Consecutive wins to trigger protection mode |
| `risk_multiplier` | float | `0.5` | Multiply risk_per_trade_pct by this (0.5 = half) |
| `sl_multiplier` | float | `0.7` | Multiply stop loss by this (0.7 = tighter) |
| `tp_multiplier` | float | `1.0` | Multiply take profit by this (1.0 = unchanged) |
| `rate_multiplier` | float | `0.5` | Multiply max trades/min by this (0.5 = half) |
| `deactivate_on_loss` | bool | `false` | Deactivate after a loss? |
| `deactivate_below_equity` | float | `17000.0` | Deactivate if equity drops below this |
| `alert_on_activation` | bool | `true` | Send alert when activating |
| `alert_on_deactivation` | bool | `true` | Send alert when deactivating |

---

## Activation Triggers

### Trigger 1: Equity Threshold

**Condition**: `current_equity ≥ equity_threshold_usd`

**Default**: $18,000 (80% of way from $10k to $20k)

**When it activates**:
- Bot checks equity after every trade
- When equity crosses $18k, protection mode activates
- Remains active as long as equity ≥ $18k (or until deactivated)

**Example**:
```
Trade #42: +$50 profit → Equity now $17,950 → Protection mode: OFF
Trade #43: +$75 profit → Equity now $18,025 → Protection mode: ON ✅
```

### Trigger 2: Win Streak

**Condition**: `consecutive_wins ≥ win_streak_threshold`

**Default**: 5 consecutive winning trades

**When it activates**:
- Bot tracks win/loss streak
- After 5 consecutive wins, protection mode activates
- Streak resets to 0 after any loss

**Example**:
```
Trade #1: +$50  → Win streak: 1
Trade #2: +$30  → Win streak: 2
Trade #3: +$40  → Win streak: 3
Trade #4: +$20  → Win streak: 4
Trade #5: +$35  → Win streak: 5 → Protection mode: ON ✅
Trade #6: -$15  → Win streak: 0 → Protection mode: OFF (if deactivate_on_loss: true)
```

---

## Parameter Adjustments

### How Adjustments Work

Protection mode multipliers are applied to **base strategy parameters**:

```python
# Normal mode
risk_per_trade_pct = 1.2

# Protection mode applies risk_multiplier = 0.5
adjusted_risk = 1.2 * 0.5 = 0.6
```

### Supported Parameters

| Parameter | Adjustment | Effect |
|-----------|------------|--------|
| `risk_per_trade_pct` | × risk_multiplier | Smaller positions |
| `sl_atr` | × sl_multiplier | Tighter stops |
| `stop_loss_bps` | × sl_multiplier | Tighter stops (bps-based) |
| `tp1_atr` | × tp_multiplier | Optional tighter targets |
| `tp2_atr` | × tp_multiplier | Optional tighter targets |
| `target_bps` | × tp_multiplier | Optional tighter targets (bps-based) |
| `max_trades_per_minute` | × rate_multiplier | Fewer trades |
| `max_trades_per_hour` | × rate_multiplier | Fewer trades |

### Example Calculation

**Base Strategy** (bar_reaction_5m_aggressive):
```yaml
risk_per_trade_pct: 1.2
sl_atr: 1.5
tp1_atr: 2.5
max_trades_per_minute: 10
```

**Protection Mode Config**:
```yaml
risk_multiplier: 0.5
sl_multiplier: 0.7
tp_multiplier: 1.0
rate_multiplier: 0.5
```

**Adjusted Parameters**:
```
risk_per_trade_pct = 1.2 × 0.5 = 0.6%
sl_atr = 1.5 × 0.7 = 1.05
tp1_atr = 2.5 × 1.0 = 2.5 (unchanged)
max_trades_per_minute = 10 × 0.5 = 5
```

---

## Manual Override

### Method 1: YAML Config

Set `force_enabled` in config:

```yaml
protection_mode:
  force_enabled: true   # Force ON
  # OR
  force_enabled: false  # Force OFF
  # OR
  force_enabled: null   # Automatic (default)
```

**Restart required**: Yes (reload config)

### Method 2: Redis Override

Set Redis key `protection:mode:override`:

```powershell
# Force enable
redis-cli -u rediss://... --tls --cacert ... SET protection:mode:override "force_enabled"

# Force disable
redis-cli -u rediss://... --tls --cacert ... SET protection:mode:override "force_disabled"

# Clear override (return to automatic)
redis-cli -u rediss://... --tls --cacert ... DEL protection:mode:override
```

**Restart required**: No (takes effect immediately)

### Method 3: API Endpoint

**Enable protection mode**:
```powershell
curl -X POST https://signals-api-gateway.fly.dev/protection-mode/override `
  -H "Content-Type: application/json" `
  -d '{"action": "enable", "reason": "Locking in gains before weekend"}'
```

**Disable protection mode**:
```powershell
curl -X POST https://signals-api-gateway.fly.dev/protection-mode/override `
  -H "Content-Type: application/json" `
  -d '{"action": "disable", "reason": "Re-enabling aggression after dip"}'
```

**Clear override**:
```powershell
curl -X DELETE https://signals-api-gateway.fly.dev/protection-mode/override
```

**Check status**:
```powershell
curl https://signals-api-gateway.fly.dev/protection-mode/status
```

**Restart required**: No (immediate effect)

---

## Monitoring

### Redis State

**Key**: `protection:mode:state` (hash)

**Check status**:
```powershell
redis-cli -u rediss://... --tls --cacert ... HGETALL protection:mode:state
```

**Fields**:
- `status`: `enabled`, `disabled`, `force_enabled`, `force_disabled`
- `trigger`: `equity_threshold`, `win_streak`, `manual_override`, `none`
- `activated_at`: ISO timestamp
- `current_equity`: Current account equity
- `current_win_streak`: Current consecutive wins
- `trades_since_activation`: Trade count since activated
- `pnl_since_activation`: P&L since activated
- `risk_multiplier`: Current risk multiplier
- `sl_multiplier`: Current SL multiplier
- `tp_multiplier`: Current TP multiplier
- `rate_multiplier`: Current rate multiplier

### Redis Events Stream

**Stream**: `protection:mode:events`

**Read recent events**:
```powershell
redis-cli -u rediss://... --tls --cacert ... XREVRANGE protection:mode:events + - COUNT 10
```

**Events include**:
- Activation (with trigger reason)
- Deactivation
- Manual overrides

### API Monitoring

**Get current status**:
```powershell
curl https://signals-api-gateway.fly.dev/protection-mode/status
```

**Get recent events**:
```powershell
curl https://signals-api-gateway.fly.dev/protection-mode/events?limit=20
```

### Prometheus Metrics

**Metrics available** (if configured):
- `protection_mode_active{status="enabled|disabled"}`
- `protection_mode_risk_multiplier`
- `protection_mode_sl_multiplier`
- `protection_mode_rate_multiplier`
- `protection_mode_trades_since_activation`
- `protection_mode_pnl_since_activation`

**Query**:
```powershell
curl http://localhost:9108/metrics | Select-String -Pattern "protection_mode"
```

### Bot Logs

Protection mode events are logged with emoji indicators:

```
🛡️  PROTECTION MODE ACTIVATED | Trigger: equity_threshold | Equity: $18,125.45 | Win Streak: 3 | Adjustments: Risk×0.5, SL×0.7, Rate×0.5
⚔️  PROTECTION MODE DEACTIVATED | Equity: $16,850.23 | Trades: 15 | P&L: +$125.45
```

---

## Testing

### Quick Test

Run the test suite:

```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot
conda activate crypto-bot
python scripts/test_protection_mode.py --test all
```

### Individual Tests

**Test equity threshold**:
```powershell
python scripts/test_protection_mode.py --test equity
```

**Test win streak**:
```powershell
python scripts/test_protection_mode.py --test win-streak
```

**Test manual override**:
```powershell
python scripts/test_protection_mode.py --test override
```

**Test parameter adjustments**:
```powershell
python scripts/test_protection_mode.py --test params
```

**Test API endpoints**:
```powershell
python scripts/test_protection_mode.py --test api
```

### Expected Results

```
================================================================================
PROTECTION MODE TEST SUITE
================================================================================
🔧 Setting up test environment...
✅ Connected to Redis
✅ Cleared test keys

📊 Test: Equity Threshold Activation
  ✅ Status is DISABLED when equity < $18k
  ✅ Status is ENABLED when equity = $18k
  ✅ Trigger is EQUITY_THRESHOLD
  ✅ Risk multiplier is 0.5 (halved)
  ...

================================================================================
TEST SUMMARY
================================================================================
✅ Passed: 28
❌ Failed: 0
📊 Total:  28
================================================================================

✅ ALL TESTS PASSED
```

---

## Troubleshooting

### Issue: Protection Mode Not Activating

**Symptoms**: Equity > $18k but protection mode still disabled

**Debug Steps**:

1. **Check if enabled in config**:
   ```powershell
   cat config/bar_reaction_5m_aggressive.yaml | Select-String -Pattern "protection_mode" -Context 5
   ```
   Verify: `enabled: true`

2. **Check for force_disabled override**:
   ```powershell
   redis-cli -u rediss://... --tls --cacert ... GET protection:mode:override
   ```
   If returns `force_disabled`, protection mode is overridden OFF

3. **Check current state**:
   ```powershell
   curl https://signals-api-gateway.fly.dev/protection-mode/status
   ```

4. **Check bot logs**:
   ```powershell
   cat logs/*.log | Select-String -Pattern "Protection Mode"
   ```

### Issue: Protection Mode Stuck ON

**Symptoms**: Equity dropped but protection mode still active

**Debug Steps**:

1. **Check deactivation threshold**:
   ```yaml
   # In config
   deactivate_below_equity: 17000.0
   ```
   Protection mode stays active until equity < $17k

2. **Check for force_enabled override**:
   ```powershell
   redis-cli -u rediss://... --tls --cacert ... GET protection:mode:override
   ```
   If returns `force_enabled`, protection mode is overridden ON

3. **Manually disable**:
   ```powershell
   curl -X POST https://signals-api-gateway.fly.dev/protection-mode/override `
     -H "Content-Type: application/json" `
     -d '{"action": "disable"}'
   ```

### Issue: Adjustments Not Applied

**Symptoms**: Protection mode active but positions still large

**Debug Steps**:

1. **Check multipliers in config**:
   ```yaml
   risk_multiplier: 0.5  # Should be < 1.0
   ```

2. **Check if strategy is reading protection mode**:
   Look for this in strategy code:
   ```python
   adjusted_params = protection_manager.get_adjusted_params(base_params)
   ```

3. **Check current state multipliers**:
   ```powershell
   redis-cli -u rediss://... --tls --cacert ... HGET protection:mode:state risk_multiplier
   ```

### Issue: API Endpoints Not Working

**Symptoms**: 404 or 500 errors on API calls

**Debug Steps**:

1. **Check if signals-api is running**:
   ```powershell
   curl https://signals-api-gateway.fly.dev/health
   ```

2. **Check if router is registered**:
   Look for this in `app/main.py`:
   ```python
   app.include_router(protection_mode.router)
   ```

3. **Check logs**:
   ```powershell
   fly logs -a crypto-signals-api | Select-String -Pattern "protection"
   ```

---

## FAQ

### Q: When should I manually override?

**A**: Manual override is useful for:
- **Before major news events**: Force enable to reduce risk
- **After drawdown**: Force disable to re-enable aggression
- **Testing**: Verify protection mode behavior

### Q: Should I keep protection mode enabled during soak test?

**A**: Yes! Protection mode is part of the production config. It should be tested during the 48h soak test to ensure it activates correctly when equity approaches $18k.

### Q: What if I want to change the equity threshold?

**A**: Update `equity_threshold_usd` in config:
```yaml
equity_threshold_usd: 19000.0  # Activate at $19k instead of $18k
```

Then restart the bot.

### Q: Can I have different protection mode settings per strategy?

**A**: Yes! Each strategy config can have its own `protection_mode` section with different multipliers.

Example:
```yaml
# bar_reaction_5m_aggressive.yaml
protection_mode:
  risk_multiplier: 0.5  # Conservative for 5m

# turbo_scalper_15s.yaml
protection_mode:
  risk_multiplier: 0.3  # More conservative for scalper
```

### Q: Does protection mode affect open positions?

**A**: No. Protection mode only affects **new trades**. Existing open positions keep their original stops/targets.

### Q: What happens if both triggers activate simultaneously?

**A**: The trigger listed first in the check logic wins (equity threshold takes precedence). Both are logged in events.

### Q: How do I disable protection mode completely?

**A**: Set `enabled: false` in config and restart bot. Or use API:
```powershell
curl -X POST https://signals-api-gateway.fly.dev/protection-mode/override `
  -d '{"action": "disable"}'
```

---

## Quick Reference

### Enable/Disable Commands

| Action | Command |
|--------|---------|
| Force enable (API) | `curl -X POST https://signals-api-gateway.fly.dev/protection-mode/override -d '{"action":"enable"}'` |
| Force disable (API) | `curl -X POST https://signals-api-gateway.fly.dev/protection-mode/override -d '{"action":"disable"}'` |
| Clear override (API) | `curl -X DELETE https://signals-api-gateway.fly.dev/protection-mode/override` |
| Check status (API) | `curl https://signals-api-gateway.fly.dev/protection-mode/status` |
| Force enable (Redis) | `redis-cli -u rediss://... SET protection:mode:override "force_enabled"` |
| Force disable (Redis) | `redis-cli -u rediss://... SET protection:mode:override "force_disabled"` |
| Clear override (Redis) | `redis-cli -u rediss://... DEL protection:mode:override` |

### Monitoring Commands

| Check | Command |
|-------|---------|
| Current state | `redis-cli -u rediss://... HGETALL protection:mode:state` |
| Recent events | `redis-cli -u rediss://... XREVRANGE protection:mode:events + - COUNT 10` |
| Status via API | `curl https://signals-api-gateway.fly.dev/protection-mode/status` |
| Bot logs | `cat logs/*.log \| Select-String -Pattern "Protection Mode"` |

---

**Last Updated**: 2025-11-08
**Version**: v1.1
**Status**: ✅ PRODUCTION READY
