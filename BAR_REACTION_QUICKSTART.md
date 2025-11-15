# Bar Reaction 5M - Quick Start Guide

**Status**: ✅ Production Ready | **Tests**: 146/146 passing (100%)

---

## 1-Minute Setup

### Prerequisites
```bash
# Conda environment
conda activate crypto-bot  # Python 3.10.18

# Redis Cloud connection
export REDIS_URL="rediss://default:******@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
```

### Run System
```bash
python scripts/run_bar_reaction_system.py \
    --config config/enhanced_scalper_config.yaml \
    --redis-url "$REDIS_URL"
```

---

## What It Does

Fires trading signals on **exact 5-minute UTC boundaries** with:
- ✅ ATR-based risk management (SL/TP)
- ✅ Maker-only execution (earn rebates)
- ✅ Spread/liquidity guards (skip bad conditions)
- ✅ Cooldown & concurrency controls
- ✅ Redis state management

---

## Test Coverage

```bash
# Run all 146 tests
pytest tests/test_bar_reaction_*.py -v

# Phase-specific tests
pytest tests/test_bar_reaction_config.py -v      # 49 tests (Config)
pytest tests/test_bar_reaction_agent.py -v       # 41 tests (Strategy)
pytest tests/test_bar_clock.py -v                # 26 tests (Scheduler)
pytest tests/test_bar_reaction_execution.py -v   # 30 tests (Execution)
```

---

## Configuration (config/enhanced_scalper_config.yaml)

```yaml
bar_reaction_5m:
  enabled: true
  mode: "trend"                    # "trend" or "revert"
  pairs: ["BTC/USD", "ETH/USD"]
  trigger_bps_up: 12               # 0.12% min move
  spread_bps_cap: 8                # Skip if spread > 8 bps
  min_atr_pct: 0.25                # ATR gates: 0.25% - 3.0%
  max_atr_pct: 3.0
  sl_atr: 0.6                      # Stop: 0.6x ATR
  tp1_atr: 1.0                     # Target1: 1.0x ATR
  tp2_atr: 1.8                     # Target2: 1.8x ATR
  cooldown_minutes: 15             # 15 min between signals per pair
  max_concurrent_per_pair: 2       # Max 2 open positions per pair
```

---

## Key Files

| File | Purpose | Lines |
|------|---------|-------|
| `agents/scheduler/bar_clock.py` | 5m scheduler, debouncing | 716 |
| `agents/strategies/bar_reaction_5m.py` | Strategy core, signals | 892 |
| `agents/strategies/bar_reaction_execution.py` | Maker-only execution | 628 |
| `strategies/bar_reaction_data.py` | Market data pipeline | 770 |
| `config/enhanced_scalper_config.yaml` | Configuration | - |
| `scripts/run_bar_reaction_system.py` | Integration script | 197 |

---

## Programmatic Usage

```python
import asyncio
from scripts.run_bar_reaction_system import create_system

async def main():
    # Create system (scheduler + strategy + Redis)
    system = await create_system(
        config_path="config/enhanced_scalper_config.yaml",
        redis_url="rediss://..."
    )

    # Run system (blocks until SIGTERM/SIGINT)
    await system.run()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Execution Flow

```
5m Boundary (e.g., 12:05:00)
    ↓
BarClock emits bar_close:5m event
    ↓
BarReaction5M receives event
    ↓
Check ATR gates (0.25%-3.0%)
    ↓
Check move_bps (≥ 12 bps)
    ↓
Check microstructure (spread ≤ 8 bps, notional ≥ $100k)
    ↓
Check cooldowns (15 min)
    ↓
Generate signal (long/short)
    ↓
BarReactionExecutionAgent receives signal
    ↓
Pre-execution guards (spread, notional)
    ↓
Calculate maker price (close ± 0.5*spread)
    ↓
Submit limit order (post_only=True)
    ↓
Queue for 10s max
    ↓
Filled (maker rebate) OR Cancelled (timeout)
```

---

## Monitoring

### Get Statistics
```python
# Strategy stats
strategy_stats = bar_reaction_agent.get_stats()
print(f"Signals generated: {strategy_stats['signals_generated']}")
print(f"ATR rejections: {strategy_stats['atr_rejections']}")

# Execution stats
exec_stats = execution_agent.get_execution_stats()
print(f"Fill rate: {exec_stats['fill_rate_pct']}%")
print(f"Maker %: {exec_stats['maker_percentage']}%")
print(f"Rebate earned: ${exec_stats['total_rebate_earned_usd']:.2f}")
```

### Redis Keys
```bash
# Debouncing (6 min TTL)
bar_clock:processed:BTC/USD:2025-01-01T12:05:00+00:00

# Cooldowns (persistent)
bar_reaction:cooldown:BTC/USD
bar_reaction:open_positions:BTC/USD
bar_reaction:daily_count:BTC/USD:20250101

# Execution records (24h TTL)
bar_reaction_exec:order:<order_id>
```

---

## Common Adjustments

### More Conservative
```yaml
trigger_bps_up: 15              # Higher threshold
spread_bps_cap: 5               # Tighter spread
min_rolling_notional_usd: 250000  # Higher liquidity
cooldown_minutes: 20            # Longer cooldown
```

### More Aggressive
```yaml
trigger_bps_up: 8               # Lower threshold
spread_bps_cap: 12              # Wider spread tolerance
min_rolling_notional_usd: 50000   # Lower liquidity
cooldown_minutes: 10            # Shorter cooldown
```

### Backtest Mode
```yaml
# In execution config:
backtest_mode: true             # Disable async queueing
max_queue_s: 300                # Queue until next bar (5 min)
```

---

## Troubleshooting

### No signals generated?
- Check ATR is within [0.25%, 3.0%]: `print(bar_data['atr_pct'])`
- Check move_bps >= threshold: `print(bar_data['move_bps'])`
- Check spread <= cap: `print(bar_data['spread_bps'])`
- Check cooldown expired: Check Redis key `bar_reaction:cooldown:{pair}`

### Orders not filling?
- Maker orders may queue up to 10s
- Check fill rate: `exec_stats['fill_rate_pct']` (target: >70%)
- Check spread rejections: `exec_stats['spread_rejections']`
- Adjust `max_queue_s` or `spread_improvement_factor`

### Clock skew warnings?
- Check system time sync: `timedatectl status`
- Warnings trigger after >2s drift
- System backs off 10s after 3 consecutive skews

### Duplicate events after restart?
- Redis debouncing prevents this automatically
- Check key exists: `bar_clock:processed:{pair}:{ts}`
- TTL: 360 seconds (6 minutes)

---

## Documentation

- **Complete System**: `BAR_REACTION_COMPLETE_SYSTEM.md`
- **Phase B (Config)**: See test file header
- **Phase C (Data)**: `strategies/bar_reaction_data.py` docstrings
- **Phase D (Strategy)**: `agents/strategies/bar_reaction_5m.py` docstrings
- **Phase E (Scheduler)**: `E_BAR_CLOCK_SCHEDULER_COMPLETE.md`
- **Phase F (Execution)**: `F_EXECUTION_POLICY_COMPLETE.md`

---

## Support

### Run Tests
```bash
# All tests (146 total)
pytest tests/test_bar_reaction_*.py -v

# Specific test
pytest tests/test_bar_reaction_execution.py::test_maker_enforcement_rejects_market_orders -v
```

### Check Logs
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python scripts/run_bar_reaction_system.py --config config/enhanced_scalper_config.yaml
```

### Validate Config
```python
from config.enhanced_scalper_loader import EnhancedScalperConfigLoader

loader = EnhancedScalperConfigLoader("config/enhanced_scalper_config.yaml")
config = loader.load_config()  # Raises ValueError on validation failure
print("Config valid!")
```

---

## Quick Reference

| Feature | Default | Range/Options |
|---------|---------|---------------|
| Timeframe | 5m | Must be "5m" |
| Trigger BPS | 12 | 1-100 bps |
| ATR Range | 0.25%-3.0% | 0.01%-10.0% |
| SL ATR | 0.6x | >0 |
| TP1 ATR | 1.0x | >0 |
| TP2 ATR | 1.8x | >0 |
| Spread Cap | 8 bps | 1-100 bps |
| Notional Floor | $100k | Any USD amount |
| Cooldown | 15 min | 1-1440 min |
| Max Concurrent | 2 | 1-10 |
| Maker Only | True | true/false |
| Queue Timeout | 10s | 1-300s |

---

**Phases Complete**: B, C, D, E, F
**Tests Passing**: 146/146 (100%)
**Production Ready**: ✅ Yes
**Documentation**: ✅ Complete

For detailed implementation, see `BAR_REACTION_COMPLETE_SYSTEM.md`
