# H) Backtest Engine Integration - COMPLETE

**Status:** ✅ All steps H1-H5 complete

**Implementation Date:** 2025-10-20

---

## Overview

Implemented a realistic, maker-only backtest engine for the bar_reaction_5m strategy with:
- Limit order simulation with bar touch detection
- ATR-based risk management
- Dual profit targets (TP1/TP2 with partial exits)
- Realistic cost model (16 bps maker fee + 1 bps slippage)
- Comprehensive test coverage

---

## H1 — Strategy Plug ✅

### Files Created/Modified:
- `config/bar_reaction_5m.yaml` - Strategy configuration
- `scripts/run_backtest.py` - Extended to support bar_reaction_5m

### Implementation:
```bash
python scripts/run_backtest.py --strategy bar_reaction_5m --pairs "BTC/USD" --lookback 180d
```

### Features:
- **YAML Configuration**: All strategy parameters loaded from `config/bar_reaction_5m.yaml`
- **5m Bar Rollup**: Native 1m data rolled up to 5m bars using pandas resample
- **ATR(14) Precomputation**: Wilder's ATR method with 14-period window
- **Feature Engineering**:
  - `move_bps`: Bar move in basis points (open→close or prev_close→close)
  - `atr_pct`: ATR as percentage of close price
  - Volatility gates: min_atr_pct (0.25%) to max_atr_pct (3.0%)

---

## H2 — Fill Model (Maker) ✅

### Files Created:
- `backtesting/bar_reaction_engine.py` - Core backtest engine

### Fill Logic:
```
Limit sits at decision price
Fill if next bar's range touches the limit price:
  - Long: fill if bar.low <= limit_price
  - Short: fill if bar.high >= limit_price

If not touched in next bar:
  - Treat as queued & cancelled (or allow --queue_bars to roll another bar)

Boundary Slippage:
  - Add +/- 1 bps if limit is touched exactly at high/low boundary
  - Long at low: fill_price = limit * (1 + 0.0001) = limit + 1 bps
  - Short at high: fill_price = limit * (1 - 0.0001) = limit - 1 bps
```

### Queue Management:
- **queue_bars**: Configurable parameter (default: 1)
- Orders expire after N bars if not filled
- Pending orders tracked separately from open positions
- Example:
  - Created at bar 10 with queue_bars=1
  - Expires at bar 11 if not filled
  - Cancelled and removed from pending queue

---

## H3 — Costs ✅

### Cost Model:
```yaml
maker_fee_bps: 16      # 0.16% maker fee (Kraken)
taker_fee_bps: 26      # 0.26% taker fee (not used in maker-only)
slippage_bps: 1        # 1 bps slippage (optimistic for makers)
spread_bps_cap: 8      # Skip if spread > 8 bps
```

### Calculation:
```python
# Entry
notional = fill_price * position_size
maker_fee = notional * 0.0016
total_cost = notional + maker_fee

# Exit (same)
proceeds = exit_price * position_size - maker_fee
```

### PnL After Fees:
- All trades include maker fees on both entry and exit
- Slippage applied only at boundary touches
- Spread cap enforced by strategy's `should_trade()` filter

---

## H4 — Outputs ✅

### File Structure:
```
reports/
├── backtest_summary.csv              # Append-only summary
├── trades_bar_reaction_5m_{pair}_5m.csv   # Detailed trade log
├── equity_bar_reaction_5m_{pair}_5m.json  # Equity curve
├── config_bar_reaction_5m_{pair}_5m.json  # Run configuration
└── backtest_readme.md                # Human-readable summary
```

### Summary CSV Columns:
```
run_ts,strategy,pair,tf,trades,win_rate,pf,total_return_pct,cagr_pct,
avg_trade_pct,max_dd_pct,sharpe,sortino,exposure_pct
```

### Trade CSV Columns:
```
entry_time,exit_time,side,entry_price,exit_price,quantity,pnl_pct,pnl_usd,status,
atr_value,sl_atr_multiple,tp1_atr_multiple,tp2_atr_multiple,
initial_stop_loss,current_stop_loss,tp1_price,tp2_price,
stop_moved_to_be,tp1_hit,highest_price,lowest_price,remaining_size_pct
```

### Equity JSON Format:
```json
[
  {"timestamp": "2024-01-01 00:00:00", "equity": 10000.00},
  {"timestamp": "2024-01-01 00:05:00", "equity": 10025.50},
  ...
]
```

---

## H5 — Tests ✅

### Test File:
- `tests/test_bar_reaction_standalone.py`

### Test Coverage:

#### 1. Fill Logic Simulation
```
✓ Long: fill if bar.low <= limit_price
✓ Short: fill if bar.high >= limit_price
✓ Boundary detection and slippage
```

#### 2. Queue Expiration
```
✓ Orders expire after queue_bars
✓ Pending orders cancelled if not filled
```

#### 3. Slippage Calculation
```
✓ Long at boundary: +1 bps
✓ Short at boundary: -1 bps
✓ No slippage if not at boundary
```

#### 4. Cost Model
```
✓ Maker fee: 16 bps on notional
✓ Total cost includes fee
```

#### 5. Dual Profit Targets
```
✓ TP1: Close 50% of position
✓ TP2: Close remaining 50%
✓ Stop moves to breakeven after TP1
```

#### 6. Edge Cases
```
✓ Gap through TP/SL (exits at defined level, not gap)
✓ Exactly touch limit (slippage applied)
✓ High spread cap (strategy filter)
✓ ATR computation (Wilder's method)
✓ 1m → 5m bar rollup (OHLC logic)
```

### Test Results:
```
======================================================================
SUMMARY: 7 passed, 0 failed out of 7 tests
======================================================================
```

---

## Usage Examples

### Basic Backtest:
```bash
python scripts/run_backtest.py \
  --strategy bar_reaction_5m \
  --pairs "BTC/USD" \
  --lookback 180d \
  --capital 10000
```

### Multi-Pair Backtest:
```bash
python scripts/run_backtest.py \
  --strategy bar_reaction_5m \
  --pairs "BTC/USD,ETH/USD,SOL/USD" \
  --lookback 90d \
  --capital 50000
```

### Custom Config:
Edit `config/bar_reaction_5m.yaml` to adjust:
- Trigger thresholds (trigger_bps_up/down)
- ATR gates (min/max_atr_pct)
- Risk management (sl_atr, tp1_atr, tp2_atr)
- Position sizing (risk_per_trade_pct)
- Cost model (maker_fee_bps, slippage_bps)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ scripts/run_backtest.py                                 │
│  ├─ Load YAML config                                    │
│  ├─ Route to BarReactionBacktestEngine                  │
│  └─ Save outputs (CSV, JSON, MD)                        │
└──────────────────┬──────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────┐
│ backtesting/bar_reaction_engine.py                      │
│  ├─ Rollup 1m → 5m bars                                 │
│  ├─ Compute ATR(14), move_bps, atr_pct                  │
│  ├─ Generate signals (via BarReaction5mStrategy)        │
│  ├─ Place limit orders (PendingOrder queue)             │
│  ├─ Check fills (bar touch detection)                   │
│  ├─ Check exits (SL, TP1, TP2 with partials)            │
│  └─ Calculate metrics                                   │
└──────────────────┬──────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────┐
│ strategies/bar_reaction_5m.py                           │
│  ├─ Signal generation (trend/revert modes)              │
│  ├─ ATR-based SL/TP calculation                         │
│  ├─ Position sizing (risk-based)                        │
│  └─ Volatility gates (min/max ATR%)                     │
└─────────────────────────────────────────────────────────┘
```

---

## Configuration Reference

### Strategy Config (`config/bar_reaction_5m.yaml`):
```yaml
strategy:
  mode: "trend"              # "trend" or "revert"
  trigger_mode: "open_to_close"  # or "prev_close_to_close"
  trigger_bps_up: 12.0       # Long trigger threshold
  trigger_bps_down: 12.0     # Short trigger threshold
  min_atr_pct: 0.25          # Min volatility gate
  max_atr_pct: 3.0           # Max volatility gate
  atr_window: 14             # ATR period
  sl_atr: 0.6                # Stop loss (0.6x ATR)
  tp1_atr: 1.0               # First target (1.0x ATR)
  tp2_atr: 1.8               # Second target (1.8x ATR)
  risk_per_trade_pct: 0.6    # Risk per trade (0.6% of equity)
  maker_only: true           # Enforce maker-only
  spread_bps_cap: 8.0        # Max spread

backtest:
  maker_fee_bps: 16          # 0.16% maker fee
  slippage_bps: 1            # 1 bps slippage
  queue_bars: 1              # Order queue duration
  lookback_days: 180         # Historical data period
  warmup_bars: 50            # Indicator warmup
```

---

## Quality Gates

### Profitability Targets (from PRD):
- **Profit Factor**: ≥ 1.35
- **Sharpe Ratio**: ≥ 1.0
- **Max Drawdown**: ≤ 20%
- **Win Rate**: Target 70% (with 1:1.5+ RR)

### Implemented in Config:
```yaml
backtest:
  min_profit_factor: 1.35
  min_sharpe_ratio: 1.0
  max_drawdown_pct: 20.0
```

---

## Performance Characteristics

### Expected Behavior:
- **Trade Frequency**: 40-120 trades/day across pairs (per PRD)
- **Hold Time**: ~5-30 minutes (5m bar reaction)
- **Risk per Trade**: 0.6% of equity (ATR-based)
- **R:R Ratio**: 1.5:3.0 (blended TP1/TP2)

### Realistic Costs:
- **Maker Fill Rate**: ~80-90% (assuming good liquidity)
- **Slippage**: 1 bps (optimistic for makers)
- **Fees**: 16 bps per side = 32 bps round trip
- **Spread Impact**: Filtered by 8 bps cap

---

## Next Steps

### Recommended Workflow:
1. **Initial Backtest**: Run on BTC/USD, ETH/USD, SOL/USD (180d)
2. **Parameter Optimization**: Use `scripts/optimize_grid.py` (if available)
3. **Quality Gates**: Verify PF ≥ 1.35, Sharpe ≥ 1.0, DD ≤ 20%
4. **Walk-Forward Testing**: Split data into train/test periods
5. **Live Paper Trading**: Test on real market data (paper mode)
6. **Production Deployment**: Deploy with live trading controls

### Quality Assurance:
```bash
# Run tests
python tests/test_bar_reaction_standalone.py

# Run backtest
python scripts/run_backtest.py --strategy bar_reaction_5m --pairs "BTC/USD" --lookback 180d

# Check quality gates
python scripts/B6_quality_gates.py
```

---

## File Manifest

### New Files Created:
```
config/bar_reaction_5m.yaml                    # Strategy configuration
backtesting/bar_reaction_engine.py             # Core backtest engine
tests/test_bar_reaction_standalone.py          # Comprehensive tests
H_BACKTEST_ENGINE_COMPLETE.md                  # This summary
```

### Modified Files:
```
scripts/run_backtest.py                        # Added bar_reaction_5m routing
```

### Output Files (Generated):
```
reports/backtest_summary.csv
reports/trades_bar_reaction_5m_{pair}_5m.csv
reports/equity_bar_reaction_5m_{pair}_5m.json
reports/config_bar_reaction_5m_{pair}_5m.json
reports/backtest_readme.md
```

---

## Verification Checklist

- [x] H1: Strategy plug (YAML parsing + 5m bars + ATR)
- [x] H1: Precompute move_bps, atr_pct for all bars
- [x] H2: Maker fill model (limit order + bar touch)
- [x] H2: Queue bars parameter (expiration logic)
- [x] H3: Cost model (16 bps maker + 1 bps slip)
- [x] H4: CSV output (backtest_summary.csv)
- [x] H4: Trade log CSV (trades_bar_reaction_5m_*.csv)
- [x] H4: Equity curve JSON (equity_bar_reaction_5m_*.json)
- [x] H5: Fill/skip tests (synthetic bars)
- [x] H5: Edge case tests (gap, touch, spread)
- [x] H5: Dual profit targets (TP1/TP2 partials)

---

## Technical Notes

### Fill Model Realism:
- **Optimistic**: Assumes fills at limit price when touched
- **Realistic**: Adds 1 bps slippage at exact boundary
- **Conservative**: Could add random fill probability (80-90%)

### Future Enhancements:
- [ ] Partial fills (queue size tracking)
- [ ] Order book depth simulation
- [ ] Latency modeling (execution delay)
- [ ] Multiple concurrent positions
- [ ] Dynamic spread modeling

### Redis Integration:
- Current: Standalone backtest (no Redis)
- Future: Could load native 5m bars from Redis streams
- Stream: `kraken:ohlc:5m:{pair}`

---

## Contact & Support

**Reference Document**: `PRD_AGENTIC.md` (Section 10: Backtesting)

**Conda Environment**: `crypto-bot`

**Redis Cloud**: Available at `redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818`

**TLS Cert**: `config/certs/redis_ca.pem`

---

**Status**: ✅ COMPLETE - All H1-H5 requirements implemented and tested

**Date**: 2025-10-20

**Next**: Ready for live backtesting on historical data
