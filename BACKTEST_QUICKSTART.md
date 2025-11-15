# Bar Reaction 5m Backtest - Quick Start Guide

## Prerequisites

```bash
# Activate environment
conda activate crypto-bot

# Verify installation
python -c "import pandas, numpy, yaml; print('OK')"
```

## Basic Usage

### 1. Single Pair Backtest (180 days)

```bash
python scripts/run_backtest.py \
  --strategy bar_reaction_5m \
  --pairs "BTC/USD" \
  --lookback 180d \
  --capital 10000
```

**Expected Output:**
```
reports/
├── backtest_summary.csv
├── trades_bar_reaction_5m_BTC_USD_5m.csv
├── equity_bar_reaction_5m_BTC_USD_5m.json
└── config_bar_reaction_5m_BTC_USD_5m.json
```

### 2. Multi-Pair Backtest

```bash
python scripts/run_backtest.py \
  --strategy bar_reaction_5m \
  --pairs "BTC/USD,ETH/USD,SOL/USD" \
  --lookback 90d \
  --capital 50000
```

### 3. Custom Timeframe

```bash
# 1 year backtest
python scripts/run_backtest.py \
  --strategy bar_reaction_5m \
  --pairs "BTC/USD" \
  --lookback 1y \
  --capital 10000
```

## Configuration

### Quick Config Edits

Edit `config/bar_reaction_5m.yaml`:

```yaml
# Make it more aggressive
strategy:
  trigger_bps_up: 8.0       # Lower threshold (was 12.0)
  trigger_bps_down: 8.0
  risk_per_trade_pct: 1.0   # Higher risk (was 0.6)

# Or more conservative
strategy:
  trigger_bps_up: 15.0      # Higher threshold (was 12.0)
  trigger_bps_down: 15.0
  risk_per_trade_pct: 0.3   # Lower risk (was 0.6)
  sl_atr: 0.8               # Wider stop (was 0.6)
```

## Output Analysis

### 1. Check Summary

```bash
# View latest results
cat reports/backtest_summary.csv | tail -1
```

**Key Metrics:**
- `total_return_pct`: Total return %
- `sharpe`: Sharpe ratio (target: ≥ 1.0)
- `max_dd_pct`: Max drawdown % (target: ≤ 20%)
- `profit_factor`: Profit factor (target: ≥ 1.35)
- `win_rate`: Win rate % (target: ≥ 70%)

### 2. View Trades

```bash
# View first 10 trades
cat reports/trades_bar_reaction_5m_BTC_USD_5m.csv | head -11
```

**Trade CSV Columns:**
- `entry_time`, `exit_time`: Trade timestamps
- `side`: "long" or "short"
- `entry_price`, `exit_price`: Entry/exit prices
- `pnl_pct`: P&L percentage
- `status`: Exit reason (stop_loss, tp1, tp2, etc.)

### 3. Plot Equity Curve

```python
import json
import pandas as pd
import matplotlib.pyplot as plt

# Load equity curve
with open('reports/equity_bar_reaction_5m_BTC_USD_5m.json') as f:
    data = json.load(f)

df = pd.DataFrame(data)
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Plot
plt.figure(figsize=(12, 6))
plt.plot(df['timestamp'], df['equity'])
plt.title('Bar Reaction 5m - Equity Curve')
plt.xlabel('Date')
plt.ylabel('Equity ($)')
plt.grid(True)
plt.show()
```

## Quality Gates

After backtest, check if results meet targets:

```python
import pandas as pd

# Load summary
df = pd.read_csv('reports/backtest_summary.csv')
latest = df.iloc[-1]

# Check gates
pf_pass = latest['profit_factor'] >= 1.35
sharpe_pass = latest['sharpe'] >= 1.0
dd_pass = latest['max_dd_pct'] <= 20.0

print(f"Profit Factor: {latest['profit_factor']:.2f} {'✓' if pf_pass else '✗'}")
print(f"Sharpe Ratio: {latest['sharpe']:.2f} {'✓' if sharpe_pass else '✗'}")
print(f"Max Drawdown: {latest['max_dd_pct']:.2f}% {'✓' if dd_pass else '✗'}")

if pf_pass and sharpe_pass and dd_pass:
    print("\n✅ ALL GATES PASSED")
else:
    print("\n❌ SOME GATES FAILED")
```

## Troubleshooting

### Issue: No trades executed

**Possible causes:**
1. Triggers too tight → Lower `trigger_bps_up/down` in YAML
2. ATR gates too restrictive → Widen `min_atr_pct` / `max_atr_pct`
3. Spread too wide → Increase `spread_bps_cap`

**Debug:**
```bash
python scripts/run_backtest.py \
  --strategy bar_reaction_5m \
  --pairs "BTC/USD" \
  --lookback 7d \
  --debug
```

### Issue: Insufficient data

**Solution:** Ensure at least 500 1m bars (8+ hours)
```bash
# Minimum viable backtest
python scripts/run_backtest.py \
  --strategy bar_reaction_5m \
  --pairs "BTC/USD" \
  --lookback 7d \
  --capital 10000
```

### Issue: Poor performance

**Optimization steps:**
1. Check trade frequency (should be 5-20 trades/day)
2. Check avg hold time (should be 5-30 minutes)
3. Adjust triggers to match volatility
4. Verify cost model is realistic

**Example tune:**
```yaml
# For low volatility (bear market)
strategy:
  trigger_bps_up: 8.0       # Lower threshold
  min_atr_pct: 0.15         # Lower floor

# For high volatility (bull market)
strategy:
  trigger_bps_up: 15.0      # Higher threshold
  max_atr_pct: 5.0          # Higher ceiling
```

## Testing

### Run Unit Tests

```bash
python tests/test_bar_reaction_standalone.py
```

**Expected:**
```
======================================================================
SUMMARY: 7 passed, 0 failed out of 7 tests
======================================================================
[OK] ALL TESTS PASSED
```

## Parameter Sweep (Advanced)

Test multiple configurations:

```bash
# Test different trigger thresholds
for TRIGGER in 8 10 12 15; do
  # Edit YAML
  sed -i "s/trigger_bps_up: .*/trigger_bps_up: $TRIGGER/" config/bar_reaction_5m.yaml

  # Run backtest
  python scripts/run_backtest.py \
    --strategy bar_reaction_5m \
    --pairs "BTC/USD" \
    --lookback 90d \
    --capital 10000

  echo "Completed trigger=$TRIGGER"
done

# Compare results
cat reports/backtest_summary.csv | tail -4
```

## Best Practices

1. **Start Small**: Test on 7-30 days first
2. **Multiple Pairs**: Test on 3+ pairs for robustness
3. **Walk-Forward**: Split into train/test periods
4. **Cost Realism**: Don't over-optimize (16 bps maker is realistic)
5. **Quality Gates**: Always check PF ≥ 1.35, Sharpe ≥ 1.0, DD ≤ 20%

## Quick Commands

```bash
# Full pipeline
python tests/test_bar_reaction_standalone.py && \
python scripts/run_backtest.py --strategy bar_reaction_5m --pairs "BTC/USD" --lookback 180d && \
cat reports/backtest_summary.csv | tail -1

# Clean reports
rm reports/backtest_summary.csv
rm reports/*bar_reaction_5m*

# Check config
cat config/bar_reaction_5m.yaml

# Verify outputs
ls -lh reports/
```

## Support

**Full Documentation**: `H_BACKTEST_ENGINE_COMPLETE.md`

**Configuration Reference**: `config/bar_reaction_5m.yaml`

**Test Suite**: `tests/test_bar_reaction_standalone.py`

---

**Last Updated**: 2025-10-20
