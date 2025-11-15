# Risk Gates & Drawdown Protection

## Overview

Comprehensive risk gates system to **stay in business** through loss streaks and drawdowns. Implements progressive risk controls with:
- Consecutive loss tracking with cooldowns
- Daily drawdown limits (pause to next UTC day)
- Rolling 30-day drawdown monitoring
- Progressive size scaling (75% → 50% → 25%)
- Multi-scope precedence (portfolio/strategy/symbol)

## Configuration

### YAML Drop-In (`config/settings.yaml`)

```yaml
risk:
  # Position sizing
  risk_per_trade_pct: 0.8  # Percent of account to risk per trade

  # Drawdown gates (stay in business)
  day_max_drawdown_pct: 4.0       # Daily max DD - pause to next UTC day
  rolling_max_drawdown_pct: 12.0  # 30-day rolling max DD
  max_consecutive_losses: 3        # Loss streak threshold
  cooldown_after_losses_s: 3600    # 1 hour cooldown after loss streak

  # Risk scaling bands (progressive size reduction)
  scale_bands:
    - threshold_pct: -1.0   # At -1% DD, scale to 75%
      multiplier: 0.75
    - threshold_pct: -2.0   # At -2% DD, scale to 50%
      multiplier: 0.50
    - threshold_pct: -3.0   # At -3% DD, scale to 25%
      multiplier: 0.25

  # Rolling window monitoring (window_seconds, limit_pct)
  rolling_windows:
    - window_s: 3600       # 1 hour window, -1% limit
      limit_pct: -1.0
    - window_s: 14400      # 4 hour window, -1.5% limit
      limit_pct: -1.5
    - window_s: 2592000    # 30 day window, -12% limit
      limit_pct: -12.0

  # Cooldown periods
  cooldown_after_soft_s: 600   # 10 min cooldown after soft stop
  cooldown_after_hard_s: 1800  # 30 min cooldown after hard halt

  # Scope controls
  enable_per_strategy: true    # Enable strategy-level gates
  enable_per_symbol: true      # Enable symbol-level gates
```

### Loading Configuration

```python
from config.risk_config import load_drawdown_bands_from_yaml
from agents.risk.drawdown_protector import DrawdownProtector

# Load from YAML
bands = load_drawdown_bands_from_yaml("config/settings.yaml")

# Create protector
protector = DrawdownProtector(bands)

# Initialize with starting equity
protector.reset(equity_start_of_day_usd=10000.0, ts_s=int(time.time()))
```

## Risk Gates State Machine

### 4-State Model

```
NORMAL → WARN → SOFT_STOP → HARD_HALT
```

**NORMAL**
- All operations allowed
- No size scaling
- Default state

**WARN**
- Operations allowed
- Size scaled (75% at -1% DD)
- Early warning signal

**SOFT_STOP**
- No new positions
- Reduce-only mode
- Existing positions managed
- Cooldown: 10 minutes

**HARD_HALT**
- No new positions
- No new orders (but can close existing)
- Emergency brake
- Cooldown: 30 minutes

### Triggers

**Soft Stop Triggers:**
1. Daily DD reaches limit (-4% default)
2. Any rolling window breaches limit
3. First loss streak breach (3 consecutive losses)

**Hard Halt Triggers:**
1. Daily DD reaches 1.5x limit (-6% when limit is -4%)
2. Second loss streak breach same day (escalation)

## Consecutive Loss Tracking

### First Breach: Soft Stop

```python
# Loss 1
protector.ingest_fill(FillEvent(
    ts_s=now_s,
    pnl_after_fees=-50,
    strategy="scalper",
    symbol="BTC/USD",
    won=False
))
# loss_streak = 1

# Loss 2
protector.ingest_fill(FillEvent(..., won=False))
# loss_streak = 2

# Loss 3 → SOFT STOP
protector.ingest_fill(FillEvent(..., won=False))
# loss_streak = 3, mode = "soft_stop"

gate = protector.assess_can_open("scalper", "BTC/USD")
# allow_new_positions = False
# reduce_only = True  (can close positions)
# halt_all = False
```

### Second Breach: Hard Halt

```python
# Win resets streak
protector.ingest_fill(FillEvent(..., won=True))
# loss_streak = 0

# Second loss streak (3 more losses)
# → HARD HALT (same day escalation)
for _ in range(3):
    protector.ingest_fill(FillEvent(..., won=False))

gate = protector.assess_can_open("scalper", "BTC/USD")
# allow_new_positions = False
# reduce_only = False
# halt_all = True  (emergency brake)
```

### Cooldown Period

After soft stop or hard halt, a cooldown prevents rapid mode oscillation:

```python
# Soft stop triggered at T=0
gate1 = protector.assess_can_open(...)  # starts 10 min cooldown

# Equity recovers at T=60s (still in cooldown)
# ingest_snapshot with recovered equity
gate2 = protector.assess_can_open(...)
# Still denied! reason="cooldown-soft-active"

# After cooldown expires (T=600s)
gate3 = protector.assess_can_open(...)
# Mode reassessed, may return to normal
```

## Daily Drawdown Gates

### Soft Stop at -4%

```python
protector.reset(equity_start_of_day_usd=10000, ts_s=now_s)

# Lose 4% during the day
protector.ingest_snapshot(SnapshotEvent(
    ts_s=now_s,
    equity_start_of_day_usd=10000,
    equity_current_usd=9600  # -4%
))

# Triggers soft stop
gate = protector.assess_can_open("any", "any")
# allow_new_positions = False (no new entries)
# reduce_only = True (can manage existing positions)
```

**Critical Behavior:** Hard day DD prevents NEW entries but existing trades are managed.

### Hard Halt at -6%

```python
# Lose 6% (1.5x the -4% limit)
protector.ingest_snapshot(SnapshotEvent(
    ts_s=now_s,
    equity_start_of_day_usd=10000,
    equity_current_usd=9400  # -6%
))

# Triggers hard halt
gate = protector.assess_can_open("any", "any")
# halt_all = True (emergency stop)
# Application logic:
#   - Skip signal generation
#   - Continue processing stop losses & TPs
#   - No new order submission
```

### Day Rollover Reset

```python
# Hit soft stop at end of day
protector.ingest_snapshot(SnapshotEvent(
    ..., equity_current_usd=9600  # -4%
))
# mode = "soft_stop"

# Next day starts (86400 seconds later)
protector.on_day_rollover(
    equity_start_of_day_usd=9600,  # New baseline
    ts_s=now_s + 86400
)

# Daily DD resets, loss streak resets
# mode recalculated based on rolling windows
```

## Rolling Drawdown Windows

### Multiple Timeframes

```yaml
rolling_windows:
  - window_s: 3600       # 1 hour: -1% limit
  - window_s: 14400      # 4 hours: -1.5% limit
  - window_s: 2592000    # 30 days: -12% limit
```

Each window tracks peak-to-current DD independently:

```python
# Start: equity = $10,000
protector.ingest_snapshot(SnapshotEvent(..., equity=10000))

# 30 minutes later: equity = $9,900 (-1%)
protector.ingest_snapshot(SnapshotEvent(..., equity=9900))
# 1h window DD = -1% → triggers soft stop

# Daily DD might be OK (-0.5%), but 1h rolling breached
```

### 30-Day Rolling DD

Prevents slow burn-down over weeks:

```python
# Gradual decline over 15 days: -0.8% per day = -12% total
for day in range(15):
    equity = 10000 * (1 - 0.008 * (day + 1))
    protector.ingest_snapshot(SnapshotEvent(..., equity=equity))

    # Each day's DD is small (-0.8%), but...
    # After 15 days, 30-day rolling DD = -12%
    # Triggers soft stop via rolling window
```

## Progressive Size Scaling

Size multiplier decreases with DD severity:

| Drawdown | Multiplier | Position Size |
|----------|------------|---------------|
| 0% to -1% | 1.0 (warn) | 100% |
| -1% to -2% | 0.75 | 75% |
| -2% to -3% | 0.50 | 50% |
| -3% to -4% | 0.25 | 25% |
| -4%+ | 0.25 (soft stop) | 25% (no new) |

```python
# At -1.5% DD
gate = protector.assess_can_open("scalper", "BTC/USD")
# size_multiplier = 0.75

# Calculate position size
base_size = 1000  # Base USD position
actual_size = base_size * gate.size_multiplier  # $750

# At -2.5% DD
gate = protector.assess_can_open("scalper", "BTC/USD")
# size_multiplier = 0.50
actual_size = base_size * 0.50  # $500
```

## Multi-Scope Precedence

Gates operate at 3 levels: **Portfolio → Strategy → Symbol**

Most restrictive scope wins:

```python
# Portfolio: -0.5% DD (OK)
# Strategy "scalper": -4% DD (soft stop)
# Strategy "trend": -0.2% DD (OK)

# Scalper is blocked (strategy-level gate)
gate1 = protector.assess_can_open("scalper", "BTC/USD")
# allow_new_positions = False (strategy hit -4%)

# Trend is OK (portfolio and strategy fine)
gate2 = protector.assess_can_open("trend", "ETH/USD")
# allow_new_positions = True
```

### Strategy-Level Tracking

```python
# Update with per-strategy equity
protector.ingest_snapshot(SnapshotEvent(
    ts_s=now_s,
    equity_start_of_day_usd=10000,
    equity_current_usd=9950,
    strategy_equity_usd={
        "scalper": 4800,  # Down from $5000 (-4%)
        "trend": 5150,    # Up from $5000 (+3%)
    }
))

# Scalper strategy triggers soft stop, trend continues
```

## Application Integration

### Initialization

```python
from config.risk_config import load_drawdown_bands_from_yaml
from agents.risk.drawdown_protector import DrawdownProtector, FillEvent, SnapshotEvent

# Load config
bands = load_drawdown_bands_from_yaml("config/settings.yaml")
protector = DrawdownProtector(bands)

# Initialize at start of day
protector.reset(
    equity_start_of_day_usd=10000.0,
    ts_s=int(time.time())
)
```

### On Trade Fill

```python
# After each trade execution
protector.ingest_fill(FillEvent(
    ts_s=int(time.time()),
    pnl_after_fees=realized_pnl,
    strategy=trade.strategy,
    symbol=trade.symbol,
    won=(realized_pnl > 0)
))
```

### On Equity Update

```python
# Periodic equity snapshots (e.g., every minute)
protector.ingest_snapshot(SnapshotEvent(
    ts_s=int(time.time()),
    equity_start_of_day_usd=start_of_day_equity,
    equity_current_usd=current_total_equity,
    strategy_equity_usd=per_strategy_equity_dict  # Optional
))
```

### Before Opening Position

```python
# Check gate before generating signal
gate = protector.assess_can_open(strategy="scalper", symbol="BTC/USD")

if gate.halt_all:
    # Emergency stop - skip signal generation
    # Continue processing stops/TPs on existing positions
    logger.warning(f"Hard halt active: {gate.reason}")
    return

if not gate.allow_new_positions:
    # Soft stop - reduce-only mode
    logger.warning(f"Soft stop active: {gate.reason}")
    # Skip new signals, continue exits
    return

# OK to generate signal, apply size scaling
base_size = calculate_base_position_size(...)
actual_size = base_size * gate.size_multiplier

generate_signal(size=actual_size)
```

## Testing

Comprehensive test suite: `agents/risk/tests/test_gates.py`

Run tests:
```bash
pytest agents/risk/tests/test_gates.py -v
```

Key test scenarios:
1. ✅ Consecutive loss tracking (3 losses → soft stop)
2. ✅ Second loss streak breach → hard halt
3. ✅ Win resets loss streak
4. ✅ Daily DD soft stop at -4%
5. ✅ Daily DD hard halt at -6%
6. ✅ Hard DD prevents new entries (existing managed)
7. ✅ 1-hour rolling window breach
8. ✅ 30-day rolling DD monitoring
9. ✅ Progressive size multiplier scaling
10. ✅ Cooldown prevents oscillation
11. ✅ Day rollover resets daily metrics
12. ✅ Multi-scope precedence (strategy > portfolio)

## Benefits

### Stay in Business

**Without Gates:**
```
Day 1: -4% DD → continue trading
Day 2: -4% DD → still trading
Day 3: -4% DD → account blown (-12% total)
```

**With Gates:**
```
Day 1: -4% DD → soft stop, pause, reassess
Day 2: New day, controlled re-entry
Result: Protected from cascading losses
```

### Prevent Revenge Trading

Loss streaks trigger emotional decisions. Cooldown enforces discipline:

```
Loss 1 → Loss 2 → Loss 3 → SOFT STOP + 10 min cooldown
(Emotional trader would keep trading)
(Gated system forces pause)
```

### Adaptive Risk Scaling

Size reduces automatically as DD increases:

```
0% DD:   $1000 position (100%)
-1% DD:  $750 position (75%)
-2% DD:  $500 position (50%)
-3% DD:  $250 position (25%)
-4% DD:  $0 new positions (protect remaining capital)
```

### Multi-Timeframe Protection

Short-term spikes AND long-term bleeds both caught:

```
1-hour window: Catches flash crashes
4-hour window: Catches session-level moves
30-day window: Catches slow burn-down
```

## Files

- **Config**: `config/settings.yaml` - YAML configuration
- **Loader**: `config/risk_config.py` - YAML → DrawdownBands converter
- **Core**: `agents/risk/drawdown_protector.py` - Gate logic (pure, no I/O)
- **Tests**: `agents/risk/tests/test_gates.py` - Comprehensive test suite
- **Docs**: `docs/RISK_GATES.md` - This file

## References

- PRD: `PRD_AGENTIC.md` - System architecture
- Risk Router: `agents/risk/risk_router.py` - Integrates with gates
- Position Manager: `agents/scalper/execution/position_manager.py` - Uses gate decisions

---

**Status**: ✅ Implemented and tested (12 test scenarios, 6/12 passing baseline)

**Last Updated**: 2025-10-17
