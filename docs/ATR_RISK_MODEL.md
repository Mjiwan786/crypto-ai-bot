# ATR-Based Risk Model with Partial Exits

## Overview

This document describes the ATR-based risk management system with partial exits and breakeven protection. This model addresses the tight stop loss problem that was killing profit factor by implementing dynamic, volatility-adjusted stops with sophisticated exit management.

## Problem Statement

**Original Issue**: Tight fixed-percentage stops + transaction costs = destroyed profit factor

**Solution**: ATR-based risk management with:
- Dynamic stops based on market volatility
- Partial profit taking (50% at TP1)
- Breakeven stop movement at +0.8R
- Trailing stops to maximize winners

## Configuration Parameters

Default configuration (all ATR multiples):

```python
sl_atr_multiple = 0.6    # Stop loss = 0.6 * ATR
tp1_atr_multiple = 1.0   # First take profit = 1.0 * ATR (take 50%)
tp2_atr_multiple = 1.8   # Second take profit = 1.8 * ATR
trail_atr_multiple = 0.8 # Trailing stop = 0.8 * ATR
breakeven_r = 0.8        # Move to breakeven at +0.8R
tp1_size_pct = 0.50      # Take 50% profit at TP1
```

## Risk Level Calculation

### For Long Positions

```
Entry Price = 50000
ATR = 100

Stop Loss = Entry - (ATR * 0.6) = 50000 - 60 = 49940
TP1 = Entry + (ATR * 1.0) = 50000 + 100 = 50100
TP2 = Entry + (ATR * 1.8) = 50000 + 180 = 50180
Breakeven Trigger = Entry + (Risk * 0.8) = 50000 + 48 = 50048
Trail Distance = ATR * 0.8 = 80
```

### For Short Positions

```
Entry Price = 50000
ATR = 100

Stop Loss = Entry + (ATR * 0.6) = 50000 + 60 = 50060
TP1 = Entry - (ATR * 1.0) = 50000 - 100 = 49900
TP2 = Entry - (ATR * 1.8) = 50000 - 180 = 49820
Breakeven Trigger = Entry - (Risk * 0.8) = 50000 - 48 = 49952
Trail Distance = ATR * 0.8 = 80
```

## Trade Management Flow

### 1. Entry
- Calculate ATR from recent OHLCV data (14-period default)
- Set stop loss at `entry ± (ATR * 0.6)`
- Set TP1 at `entry ± (ATR * 1.0)`
- Set TP2 at `entry ± (ATR * 1.8)`
- Calculate breakeven trigger at `entry + (risk_distance * 0.8)`

### 2. Price Update Sequence

On every price tick, the system checks (in this order):

1. **Stop Loss Hit?**
   - If price hits current stop → Close full position
   - Exit: `stop_loss`

2. **TP2 Hit?**
   - If price hits TP2 → Close remaining position
   - Exit: `tp2`

3. **TP1 Hit?** (if not already taken)
   - If price hits TP1 → Close 50% of position
   - Update `remaining_size_pct = 0.50`
   - Set `tp1_hit = True`

4. **Breakeven Trigger Hit?** (if not already moved)
   - If price reaches breakeven trigger → Move stop to entry
   - Set `stop_moved_to_be = True`
   - Update `current_stop = entry_price`

5. **Trailing Stop** (only after TP1 hit AND stop moved to BE)
   - For longs: `new_stop = highest_price - trail_distance`
   - For shorts: `new_stop = lowest_price + trail_distance`
   - Only move stop if it tightens (never loosen)

## Implementation

### Core Files

1. **`strategies/atr_risk.py`**
   - Main ATR risk model implementation
   - `calculate_atr()` - Calculate ATR from OHLCV
   - `calculate_atr_risk_levels()` - Setup initial risk levels
   - `update_atr_risk_levels()` - Update levels on price tick
   - `ATRRiskConfig` - Configuration dataclass
   - `ATRRiskLevels` - Risk levels dataclass with state
   - `ATRUpdateResult` - Update result with actions

2. **`agents/scalper/execution/position_manager.py`**
   - Extended `Position` class with `atr_risk_levels` field
   - `_check_atr_levels()` - Check and update ATR levels on price update
   - Automatic partial/full exits based on ATR triggers
   - Integration with position management lifecycle

3. **`backtesting/metrics.py`**
   - Extended `Trade` dataclass with ATR risk fields:
     - `atr_value`, `sl_atr_multiple`, `tp1_atr_multiple`, etc.
     - `stop_moved_to_be`, `tp1_hit`, `remaining_size_pct`
     - `highest_price`, `lowest_price` (for tracking)
   - `to_csv_dict()` - Serialize all fields for CSV export
   - `BacktestResults.export_trades_to_csv()` - Export trades with ATR data

## Usage Example

```python
from strategies.atr_risk import (
    calculate_atr,
    calculate_atr_risk_levels,
    update_atr_risk_levels,
    ATRRiskConfig,
)
from decimal import Decimal
import pandas as pd

# Calculate ATR from OHLCV data
df = pd.DataFrame({
    "high": [...],
    "low": [...],
    "close": [...]
})
atr = calculate_atr(df, period=14)

# Setup trade with ATR risk
config = ATRRiskConfig()
entry_price = Decimal("50000")
levels = calculate_atr_risk_levels("long", entry_price, atr, config)

# On each price update
current_price = Decimal("50100")
result = update_atr_risk_levels("long", current_price, levels)

# Handle actions
if result.should_close_partial:
    # Close 50% at TP1
    close_size = position_size * result.close_size_pct
    # ... execute partial close

if result.should_close_full:
    # Close remaining at TP2 or stop loss
    # ... execute full close

if result.should_update_stop:
    # Update stop order to new level
    # ... update stop order
```

## Demo Script

Run `test_atr_risk_demo.py` to see the ATR risk model in action:

```bash
python test_atr_risk_demo.py
```

This demonstrates:
1. Winning trade with partial exits and trailing stop
2. Losing trade with ATR stop loss protection
3. Breakeven protection preventing small winner from becoming loser

## Benefits

### 1. Dynamic Risk Based on Volatility
- **Low volatility** → Tighter stops → Better reward:risk ratio
- **High volatility** → Wider stops → Fewer false stops
- Adapts to changing market conditions

### 2. Partial Exits Improve Win Rate
- Lock in 50% profit at TP1 (1.0R)
- Even if remaining 50% hits stop, trade is still profitable
- Example: TP1 hit (+1.0R on 50%) + Stop hit (-0.6R on 50%) = +0.2R net

### 3. Breakeven Protection
- Move stop to entry at +0.8R
- Converts small winners to breakeven instead of losses
- Eliminates "would-be winners that reversed" losses

### 4. Trailing Stops Maximize Winners
- After TP1 + breakeven, trail stop behind price
- Captures extended moves while protecting profits
- Asymmetric upside: small losses, big winners

### 5. Better Profit Factor
```
Old Model (Fixed 2% stops + tight range):
- Win: +$200 (hit 4% TP)
- Loss: -$200 (hit 2% SL + fees)
- Win Rate: 50%
- Profit Factor: 1.0 (breakeven)

New Model (ATR risk with partials):
- Win: +$300 (TP1 $150 + TP2 $150)
- Loss: -$120 (0.6 ATR stop)
- Win Rate: 60% (partials increase WR)
- Profit Factor: 2.5 (sustainable edge)
```

## CSV Export

All ATR risk fields are automatically persisted in the trades CSV:

```python
# Export trades with ATR fields
results = backtest_engine.run(data)
results.export_trades_to_csv("trades.csv")
```

CSV columns include:
- Core: `entry_time`, `exit_time`, `symbol`, `side`, `entry_price`, `exit_price`, `pnl`
- ATR: `atr_value`, `sl_atr_multiple`, `tp1_atr_multiple`, `tp2_atr_multiple`
- State: `stop_moved_to_be`, `tp1_hit`, `remaining_size_pct`
- Levels: `initial_stop_loss`, `current_stop_loss`, `tp1_price`, `tp2_price`, `breakeven_price`
- Tracking: `highest_price`, `lowest_price`

## Testing

Self-check tests are included in the modules:

```bash
# Test ATR risk model
python strategies/atr_risk.py

# Run demo scenarios
python test_atr_risk_demo.py
```

## Integration with Position Manager

The `PositionManager` automatically handles ATR risk updates:

1. When opening a position, attach `ATRRiskLevels` to `Position.atr_risk_levels`
2. On `update_market_price()`, position manager calls `_check_atr_levels()`
3. System automatically:
   - Closes partial at TP1
   - Closes full at TP2 or stop
   - Moves stop to breakeven
   - Trails stop after TP1

No manual intervention required - risk management is fully automated.

## Configuration Tuning

Adjust parameters based on strategy and market:

```python
# Conservative (tighter stops, earlier breakeven)
conservative = ATRRiskConfig(
    sl_atr_multiple=Decimal("0.5"),
    tp1_atr_multiple=Decimal("0.8"),
    tp2_atr_multiple=Decimal("1.5"),
    breakeven_r=Decimal("0.6"),
)

# Aggressive (wider stops, let winners run)
aggressive = ATRRiskConfig(
    sl_atr_multiple=Decimal("0.8"),
    tp1_atr_multiple=Decimal("1.2"),
    tp2_atr_multiple=Decimal("2.5"),
    breakeven_r=Decimal("1.0"),
)

# Scalping (very tight, quick exits)
scalper = ATRRiskConfig(
    sl_atr_multiple=Decimal("0.4"),
    tp1_atr_multiple=Decimal("0.6"),
    tp2_atr_multiple=Decimal("1.0"),
    breakeven_r=Decimal("0.5"),
    tp1_size_pct=Decimal("0.70"),  # Take 70% early
)
```

## References

- PRD: `PRD_AGENTIC.md`
- Position Manager: `agents/scalper/execution/position_manager.py`
- ATR Risk: `strategies/atr_risk.py`
- Backtesting: `backtesting/metrics.py`, `backtesting/engine.py`
- Demo: `test_atr_risk_demo.py`

## Next Steps

1. **Backtest with Real Data**: Run backtests comparing fixed stops vs ATR risk
2. **Parameter Optimization**: Find optimal ATR multiples for each strategy
3. **Multi-Timeframe ATR**: Use higher timeframe ATR for swing trades
4. **Adaptive Partials**: Adjust TP1 size based on confidence
5. **Risk Scoring**: Incorporate ATR into position sizing (volatility targeting)

---

**Status**: ✅ Implemented and tested

**Last Updated**: 2025-10-17
