# Phase G: Risk & Trade Management (ATR SL/TP/BE/Trail) - COMPLETE

**Status**: ✅ ALL STEPS COMPLETE (G1, G2, G3)
**Total Tests**: 28/28 passing (100%)
**Date**: 2025-10-19

---

## Executive Summary

Phase G implements comprehensive **risk and trade management** for the bar_reaction_5m strategy with ATR-based stops, partial profit-taking, trailing stops, and global risk gates. The system ensures disciplined risk management through automated stop adjustments and drawdown protection.

---

## Implementation Steps

### G1: ATR-Based Stops ✅

**Goal**: Implement dynamic risk management using ATR multiples

**Stop Loss & Take Profits**:
```python
# G1: ATR-based level calculation
SL = entry ± sl_atr * ATR         # 0.6x ATR (default)
TP1 = entry ± tp1_atr * ATR       # 1.0x ATR (close 50%)
TP2 = entry ± tp2_atr * ATR       # 1.8x ATR (trail remaining)
```

**Example** (Long Position):
```
Entry: $50,000
ATR: $500
sl_atr: 0.6, tp1_atr: 1.0, tp2_atr: 1.8

SL  = 50000 - (0.6 * 500) = $49,700  (-$300, -0.6%)
TP1 = 50000 + (1.0 * 500) = $50,500  (+$500, +1.0%)
TP2 = 50000 + (1.8 * 500) = $50,900  (+$900, +1.8%)

Risk/Reward:
- To SL:  -$300 (1R)
- To TP1: +$500 (1.67R)
- To TP2: +$900 (3.00R)
```

**Break-Even Move**:
```python
# G1: Move stop to break-even at unrealized >= 0.5R
if unrealized_profit_per_unit >= (sl_distance * break_even_at_r):
    current_sl = entry_price  # Lock in break-even
```

**Trailing Stop**:
```python
# G1: Trail after TP1 hit
trail_distance = ATR * trail_atr  # 0.8x ATR (default)

# For longs
new_trail_sl = current_price - trail_distance
if new_trail_sl > current_sl:
    current_sl = new_trail_sl  # Only move up, never down

# For shorts
new_trail_sl = current_price + trail_distance
if new_trail_sl < current_sl:
    current_sl = new_trail_sl  # Only move down, never up
```

**Partial Profit-Taking**:
```python
# G1: TP1 closes 50% of position
at TP1:
    close_quantity = remaining_quantity * tp1_close_pct  # 50%
    remaining_quantity = remaining_quantity - close_quantity
    start_trailing = True  # Begin trailing remainder
```

**Test Coverage**: 15 tests
- ✅ ATR-based SL/TP calculation (long/short)
- ✅ Break-even threshold (only triggers at >=0.5R)
- ✅ TP1 partial close (correct quantity math)
- ✅ TP2 final close
- ✅ Trailing stop (starts after TP1, moves favorably only)
- ✅ Stop loss hit handling

---

### G2: Stacking & Caps ✅

**Goal**: Global risk gates and position limits

**Concurrent Limits**:
```python
# G2: Max one concurrent per pair (default)
max_concurrent_per_pair = 1

# Prevent over-exposure to single pair
if current_open_positions[pair] >= max_concurrent_per_pair:
    reject("Concurrent limit reached")
```

**Drawdown Gates**:
```python
# G2: Daily drawdown gate (5% default)
day_dd_pct = abs(daily_pnl) / daily_start_equity * 100
if day_dd_pct > day_max_drawdown_pct:  # 5.0%
    reject("Day drawdown limit exceeded")

# G2: Rolling drawdown gate (10% default)
rolling_dd_pct = abs(rolling_pnl) / rolling_start_equity * 100
if rolling_dd_pct > rolling_max_drawdown_pct:  # 10.0%
    reject("Rolling drawdown limit exceeded")
```

**Consecutive Losses Cooldown**:
```python
# G2: Cooldown after 3 consecutive losses
if consecutive_losses >= max_consecutive_losses:  # 3
    cooldown_until = now + cooldown_after_losses_seconds  # 3600s (1 hour)
    reject("Cooldown after consecutive losses")

# Reset on win
on_winning_trade:
    consecutive_losses = 0
    cooldown_until = None
```

**Test Coverage**: 13 tests
- ✅ Concurrent limit (allows first, rejects second for same pair)
- ✅ Concurrent limit freed after position closes
- ✅ Different pairs allowed simultaneously
- ✅ Day drawdown gate (allows below 5%, rejects above)
- ✅ Rolling drawdown gate (allows below 10%, rejects above)
- ✅ Cooldown after 3 losses
- ✅ Cooldown reset on win
- ✅ No cooldown after 1-2 losses

---

### G3: Comprehensive Tests ✅

**Goal**: Verify specific requirements

**G3 Requirements Tested**:

1. **Breakeven fires ONLY after threshold** (4 tests):
   ```python
   # Does NOT fire below 0.5R
   current_price = $50,100  # Profit = $100, threshold = $150
   assert breakeven_set is False

   # DOES fire at/above 0.5R
   current_price = $50,150  # Profit = $150, threshold = $150
   assert breakeven_set is True
   assert current_sl == entry_price
   ```

2. **Partial TP correct quantity math** (3 tests):
   ```python
   # TP1 closes 50% exactly
   original_quantity = 1.0 BTC
   at_tp1:
       close_quantity = 0.5 BTC  # 50% of 1.0
       remaining_quantity = 0.5 BTC
       realized_pnl = profit_per_unit * 0.5

   # TP2 closes remaining 50%
   at_tp2:
       close_quantity = 0.5 BTC  # Remaining 50%
       status = "closed"
   ```

3. **Cooldown after 3 losses** (4 tests):
   ```python
   # No cooldown after 1 or 2 losses
   assert consecutive_losses == 2
   assert can_open_position() is True

   # Cooldown triggers after 3rd loss
   assert consecutive_losses == 3
   assert can_open_position() is False
   assert "Cooldown" in rejection_reason

   # Reset on win
   on_winning_trade:
       assert consecutive_losses == 0
       assert can_open_position() is True
   ```

**Total Tests**: 28 comprehensive tests covering all G1/G2/G3 requirements

---

## Configuration

### TradeConfig

```python
@dataclass
class TradeConfig:
    # G1: ATR-based stops
    sl_atr: float = 0.6           # Stop loss: 0.6x ATR
    tp1_atr: float = 1.0          # Take profit 1: 1.0x ATR
    tp2_atr: float = 1.8          # Take profit 2: 1.8x ATR
    trail_atr: float = 0.8        # Trailing stop: 0.8x ATR
    break_even_at_r: float = 0.5  # Move to BE at 0.5R

    # TP1 partial close
    tp1_close_pct: float = 0.5    # Close 50% at TP1

    # G2: Concurrent limits
    max_concurrent_per_pair: int = 1

    # G2: Drawdown gates
    day_max_drawdown_pct: float = 5.0          # 5% max daily DD
    rolling_max_drawdown_pct: float = 10.0     # 10% max rolling DD
    max_consecutive_losses: int = 3
    cooldown_after_losses_seconds: int = 3600  # 1 hour
```

---

## Usage

### Basic Usage

```python
import redis.asyncio as redis
from agents.strategies.bar_reaction_trade_manager import (
    BarReactionTradeManager,
    TradeConfig,
)

# Create Redis client
redis_client = await redis.from_url("rediss://...", decode_responses=True)

# Configure trade manager
config = TradeConfig(
    sl_atr=0.6,
    tp1_atr=1.0,
    tp2_atr=1.8,
    trail_atr=0.8,
    break_even_at_r=0.5,
    max_concurrent_per_pair=1,
    day_max_drawdown_pct=5.0,
    rolling_max_drawdown_pct=10.0,
    max_consecutive_losses=3,
)

# Initialize manager
manager = BarReactionTradeManager(config, redis_client)

# Check if can open position
can_open, reason = await manager.can_open_position("BTC/USD")
if not can_open:
    print(f"Cannot open: {reason}")
    return

# Open position
signal = {
    "id": "signal_123",
    "pair": "BTC/USD",
    "side": "long",
    "strategy": "bar_reaction_5m",
}

position = await manager.open_position(
    signal=signal,
    entry_price=Decimal("50000"),
    quantity=Decimal("0.1"),
    atr=Decimal("500"),
)

print(f"Position opened: {position.position_id}")
print(f"SL: {position.sl}, TP1: {position.tp1}, TP2: {position.tp2}")
```

### Update Position

```python
# On each price update
current_price = Decimal("50300")

update = await manager.update_position(
    position.position_id,
    current_price,
)

if update.action == "move_be":
    print(f"Moved to breakeven: {update.new_sl}")
elif update.action == "tp1_close":
    print(f"TP1 hit! Closed {update.close_quantity}, PnL: ${update.realized_pnl}")
elif update.action == "tp2_close":
    print(f"TP2 hit! Position closed, PnL: ${update.realized_pnl}")
elif update.action == "sl_hit":
    print(f"Stop loss hit, PnL: ${update.realized_pnl}")
elif update.action == "trail_update":
    print(f"Trailing stop updated to: {update.new_sl}")
```

### Get Statistics

```python
stats = manager.get_stats()

print(f"Total trades: {stats['total_trades']}")
print(f"Win rate: {stats['win_rate_pct']}%")
print(f"Total PnL: ${stats['total_realized_pnl']}")
print(f"Breakeven moves: {stats['breakeven_moves']}")
print(f"TP1 hits: {stats['tp1_hits']}")
print(f"TP2 hits: {stats['tp2_hits']}")
print(f"Trail updates: {stats['trail_updates']}")
print(f"Consecutive losses: {stats['consecutive_losses']}")
print(f"In cooldown: {stats['in_cooldown']}")
```

---

## Position Lifecycle

```
1. OPEN
   ├─ Calculate ATR-based levels (SL, TP1, TP2)
   ├─ Check concurrent limit
   ├─ Check drawdown gates
   └─ Track in active_positions

2. UPDATE (each price tick)
   ├─ Check SL hit → CLOSE (loss)
   ├─ Check TP1 hit → PARTIAL CLOSE (50%) + Start trailing
   ├─ Check TP2 hit → CLOSE (win)
   ├─ Check breakeven threshold → MOVE SL to entry
   └─ Update trailing stop (if TP1 hit)

3. PARTIAL CLOSE (TP1)
   ├─ Close 50% of position
   ├─ Realize partial profit
   ├─ Start trailing remaining 50%
   └─ Update drawdown state

4. FINAL CLOSE (TP2 or SL)
   ├─ Close remaining position
   ├─ Realize final PnL
   ├─ Update drawdown state
   ├─ Update consecutive losses
   ├─ Check cooldown trigger
   └─ Free concurrent slot
```

---

## Risk/Reward Analysis

### Standard Setup (Default Config)

```
ATR multiples:
- SL:  0.6x ATR
- TP1: 1.0x ATR (close 50%)
- TP2: 1.8x ATR (trail remaining)

Risk/Reward:
- To SL:  1.00R (risk)
- To TP1: 1.67R (reward on 50%)
- To TP2: 3.00R (reward on remaining 50%)

Average RR (if both TPs hit):
- TP1 contributes: 1.67R * 0.5 = 0.835R
- TP2 contributes: 3.00R * 0.5 = 1.500R
- Total reward: 2.335R
- Net RR: 2.335:1

Breakeven:
- Moves to BE at 0.5R (50% of risk)
- Locks in 0R once price moves $150 on $300 risk
```

### Conservative Setup

```python
config = TradeConfig(
    sl_atr=0.8,           # Wider stop (0.8x ATR)
    tp1_atr=1.2,          # Conservative TP1 (1.2x ATR)
    tp2_atr=2.0,          # Conservative TP2 (2.0x ATR)
    trail_atr=1.0,        # Wider trailing (1.0x ATR)
    break_even_at_r=0.7,  # Later BE (0.7R)
)

Risk/Reward:
- To SL:  1.00R
- To TP1: 1.50R
- To TP2: 2.50R
- Average: 2.00R
```

### Aggressive Setup

```python
config = TradeConfig(
    sl_atr=0.5,           # Tighter stop (0.5x ATR)
    tp1_atr=0.8,          # Closer TP1 (0.8x ATR)
    tp2_atr=1.5,          # Closer TP2 (1.5x ATR)
    trail_atr=0.6,        # Tighter trailing (0.6x ATR)
    break_even_at_r=0.3,  # Earlier BE (0.3R)
)

Risk/Reward:
- To SL:  1.00R
- To TP1: 1.60R
- To TP2: 3.00R
- Average: 2.30R
```

---

## Drawdown Protection

### Daily Drawdown

```python
# Reset at start of each day
manager.reset_daily_state()

# Tracks cumulative PnL for the day
daily_pnl = sum(all_trades_today)
day_dd_pct = abs(daily_pnl) / daily_start_equity * 100

# Example:
# Daily start equity: $100,000
# Cumulative losses: -$6,000
# Day DD: 6.0% > 5.0% limit → STOP TRADING
```

### Rolling Drawdown

```python
# Tracks cumulative PnL over rolling window
rolling_pnl = sum(all_trades_since_equity_peak)
rolling_dd_pct = abs(rolling_pnl) / rolling_start_equity * 100

# Example:
# Rolling start equity: $100,000
# Cumulative losses: -$12,000
# Rolling DD: 12.0% > 10.0% limit → STOP TRADING
```

### Consecutive Losses

```python
# Track losing streak
consecutive_losses = 0

on_losing_trade:
    consecutive_losses += 1
    if consecutive_losses >= 3:
        cooldown_until = now + 3600  # 1 hour
        STOP TRADING until cooldown expires

on_winning_trade:
    consecutive_losses = 0
    cooldown_until = None
    RESUME TRADING
```

---

## Statistics & Monitoring

### Trade Metrics

```python
{
    "total_trades": 50,
    "active_positions": 2,
    "winning_trades": 32,
    "losing_trades": 18,
    "win_rate_pct": 64.0,

    "breakeven_moves": 12,      # Positions moved to BE
    "tp1_hits": 28,              # TP1 reached
    "tp2_hits": 15,              # TP2 reached
    "sl_hits": 18,               # Stop loss hit
    "trail_updates": 145,        # Trailing stop adjustments

    "total_realized_pnl": 2450.50,
}
```

### Risk Metrics

```python
{
    "concurrent_limit_rejections": 5,
    "drawdown_rejections": 2,

    "daily_pnl": -250.00,
    "rolling_pnl": 1200.00,
    "consecutive_losses": 1,
    "in_cooldown": false,
}
```

### Configuration

```python
{
    "config": {
        "sl_atr": 0.6,
        "tp1_atr": 1.0,
        "tp2_atr": 1.8,
        "trail_atr": 0.8,
        "break_even_at_r": 0.5,
        "max_concurrent_per_pair": 1,
        "day_max_drawdown_pct": 5.0,
        "rolling_max_drawdown_pct": 10.0,
        "max_consecutive_losses": 3,
    }
}
```

---

## Files Created/Modified

### Created

```
agents/strategies/bar_reaction_trade_manager.py   (657 lines)
tests/test_bar_reaction_trade_manager.py          (693 lines)
G_RISK_TRADE_MANAGEMENT_COMPLETE.md               (this file)
```

**Total Lines**: ~1,350+ lines of production code + tests + documentation

---

## Testing

### Run Trade Manager Tests

```bash
# All trade manager tests (28 total)
pytest tests/test_bar_reaction_trade_manager.py -v

# Specific test categories
pytest tests/test_bar_reaction_trade_manager.py -k "breakeven" -v
pytest tests/test_bar_reaction_trade_manager.py -k "partial" -v
pytest tests/test_bar_reaction_trade_manager.py -k "cooldown" -v
pytest tests/test_bar_reaction_trade_manager.py -k "trailing" -v
```

### Run All Bar Reaction Tests

```bash
# All bar_reaction tests (174 total)
pytest tests/test_bar_reaction_*.py tests/test_bar_clock.py -v

# Result:
# ======================== 174 passed, 1 warning in 4.89s ========================
```

---

## Complete System Integration

**Phases Completed**:
- ✅ Phase B: Configuration & Validation (49 tests)
- ✅ Phase C: Market Data Plumbing (bars + features)
- ✅ Phase D: Strategy Core (41 tests)
- ✅ Phase E: Scheduler (26 tests)
- ✅ Phase F: Execution Policy (30 tests)
- ✅ Phase G: Risk & Trade Management (28 tests)

**Total Tests**: **174/174 passing (100%)**

---

## Conclusion

Phase G risk and trade management is **production-ready** with:

✅ G1: ATR-based stops (SL, TP1, TP2, Break-Even, Trailing)
✅ G2: Stacking & caps (concurrent limits, drawdown gates)
✅ G3: Comprehensive tests (28/28 passing, 100%)
✅ Breakeven fires only after threshold
✅ Partial TP correct quantity math
✅ Cooldown after 3 losses
✅ Full position lifecycle management
✅ Redis state persistence
✅ Statistics and monitoring

The system delivers disciplined risk management through:
- Dynamic ATR-based risk/reward ratios
- Automated break-even protection
- Trailing stops after partial profits
- Global drawdown gates
- Consecutive loss protection
- Concurrent position limits

---

**Implementation Date**: 2025-10-19
**Test Status**: 28/28 passing (100%)
**Total System Tests**: 174/174 passing (100%)
**Python Version**: 3.10.18
**Conda Environment**: crypto-bot
**Redis**: Cloud TLS (rediss://...)
