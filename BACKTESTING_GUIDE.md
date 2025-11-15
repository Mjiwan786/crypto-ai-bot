# Backtesting Guide - Crypto AI Bot

## Quick Answer: How to Evaluate $10,000 Profitability

**TL;DR:** The bot has no historical profitability yet. You must backtest first.

```bash
# Test with $10,000 starting capital over 1 year
conda activate crypto-bot
python -m backtesting.run_backtest --symbol BTC/USD --capital 10000
```

This will show you what would have happened if you ran the strategy for the past year.

---

## What is Backtesting?

Backtesting simulates your strategy against historical data to estimate:
- Expected returns
- Risk (drawdowns, volatility)
- Win rate and profit factor
- Whether the strategy is profitable at all

**Critical:** Backtesting uses the **exact same logic** as live trading (same pure functions from `ai_engine/` and `orchestration/`), so results are representative of real behavior.

---

## Getting Started (5 Minutes)

### Step 1: Quick Test (1 Year, Default Settings)

```bash
conda activate crypto-bot

# BTC with $10,000 starting capital
python -m backtesting.run_backtest --symbol BTC/USD --capital 10000

# ETH with $10,000 starting capital
python -m backtesting.run_backtest --symbol ETH/USD --capital 10000
```

**What you'll see:**
```
======================================================================
BACKTEST RESULTS SUMMARY
======================================================================

Configuration:
  Symbol: BTC/USD
  Period: 2024-01-12 to 2025-01-12
  Initial Capital: $10,000.00
  Final Equity: $12,450.00
  Timeframe: 1h

Returns:
  Total Return: $2,450.00 (+24.50%)
  Annualized Return: +24.50%

Risk Metrics:
  Sharpe Ratio: 1.82
  Sortino Ratio: 2.15
  Max Drawdown: -$850.00 (-8.50%)
  Max DD Duration: 12 days
  Volatility (Annual): 18.50%

Trade Statistics:
  Total Trades: 48
  Winning Trades: 28 (58.3%)
  Losing Trades: 20
  Avg Win: $125.50
  Avg Loss: -$45.20
  Profit Factor: 2.15
  Expectancy: $51.04

Risk-Adjusted Metrics:
  Calmar Ratio: 2.88
  Recovery Factor: 2.88
======================================================================
```

### Step 2: Interpret Results

**Profitability Check:**
- ✅ Total Return > 0%: Strategy made money
- ❌ Total Return < 0%: Strategy lost money

**Risk Assessment:**
| Metric | Your Result | Target | Pass? |
|--------|-------------|--------|-------|
| Total Return | +24.50% | >20%/year | ✅ |
| Sharpe Ratio | 1.82 | >1.5 | ✅ |
| Max Drawdown | -8.50% | <20% | ✅ |
| Win Rate | 58.3% | >50% | ✅ |
| Profit Factor | 2.15 | >1.5 | ✅ |

**Decision:**
- ✅ **All targets met** → Proceed to extended backtesting (2+ years)
- ⚠️ **Some targets missed** → Adjust strategy parameters
- ❌ **Most targets missed** → Strategy needs major revision

---

## Step 3: Extended Backtesting (2+ Years)

Test across multiple market conditions:

```bash
# 2-year backtest (2022-2024: bull, bear, sideways)
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --start-date 2022-01-01 \
  --end-date 2024-01-01 \
  --capital 10000 \
  --timeframe 1h \
  --output results/btc_2yr_backtest.json

# 3-year backtest (even better)
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --start-date 2021-01-01 \
  --end-date 2024-01-01 \
  --capital 10000 \
  --timeframe 1h \
  --output results/btc_3yr_backtest.json
```

**Why 2+ years?**
- Includes different market regimes (bull, bear, chop)
- Reduces overfitting risk
- More reliable performance estimates

---

## Step 4: Parameter Optimization

Tune risk parameters for better performance:

```bash
# Conservative (2% position, tight stops)
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --capital 10000 \
  --position-size 0.02 \
  --stop-loss 0.015 \
  --take-profit 0.03 \
  --output results/conservative.json

# Balanced (5% position, normal stops)
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --capital 10000 \
  --position-size 0.05 \
  --stop-loss 0.02 \
  --take-profit 0.04 \
  --output results/balanced.json

# Aggressive (10% position, wide stops)
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --capital 10000 \
  --position-size 0.10 \
  --stop-loss 0.03 \
  --take-profit 0.06 \
  --output results/aggressive.json
```

**Compare results:**
```bash
# Compare JSON results
python -c "
import json
from pathlib import Path

for f in Path('results').glob('*.json'):
    with open(f) as file:
        data = json.load(file)
        print(f'{f.stem:20s} | Return: {data[\"performance\"][\"total_return_pct\"]:+6.2f}% | Sharpe: {data[\"risk\"][\"sharpe_ratio\"]:5.2f} | Drawdown: {data[\"risk\"][\"max_drawdown_pct\"]:6.2f}%')
"
```

---

## Step 5: Multiple Symbols

Test across different assets:

```bash
# Create a test suite
for symbol in "BTC/USD" "ETH/USD" "SOL/USD"; do
  python -m backtesting.run_backtest \
    --symbol "$symbol" \
    --capital 10000 \
    --start-date 2023-01-01 \
    --end-date 2024-01-01 \
    --output "results/${symbol//\//_}_backtest.json"
done

# View results
ls -lh results/
```

**Why multiple symbols?**
- Strategy should work across different assets
- Reduces risk of overfitting to one instrument
- Diversification improves portfolio returns

---

## Understanding Key Metrics

### 1. Total Return
**What:** Total profit/loss as percentage of starting capital
**Good:** >20% per year
**Example:** $10,000 → $12,000 = +20%

### 2. Sharpe Ratio
**What:** Risk-adjusted returns (higher = better)
**Good:** >1.5
**Formula:** (Returns - Risk-Free Rate) / Volatility
**Interpretation:**
- <1.0: Poor (high risk for returns)
- 1.0-2.0: Good
- >2.0: Excellent

### 3. Max Drawdown
**What:** Largest peak-to-trough decline
**Good:** <20%
**Example:** Portfolio drops from $12,000 to $10,000 = -16.7% drawdown
**Why important:** Shows worst-case scenario

### 4. Win Rate
**What:** Percentage of profitable trades
**Good:** >50%
**Note:** Can still be profitable with <50% if wins are bigger than losses

### 5. Profit Factor
**What:** Gross profit / Gross loss
**Good:** >1.5
**Example:** $10,000 in wins, $5,000 in losses = 2.0 profit factor
**Interpretation:**
- <1.0: Losing strategy
- 1.0-1.5: Marginal
- >1.5: Strong

### 6. Expectancy
**What:** Average profit per trade
**Good:** >$0
**Example:** $51.04 expectancy = expect to make $51 per trade on average

---

## Advanced Usage

### Custom Timeframes

```bash
# 5-minute scalping
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --capital 10000 \
  --timeframe 5m \
  --position-size 0.01 \
  --stop-loss 0.005 \
  --take-profit 0.01

# Daily swing trading
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --capital 10000 \
  --timeframe 1d \
  --position-size 0.10 \
  --stop-loss 0.05 \
  --take-profit 0.15
```

### Transaction Costs

Realistic simulation includes:
- **Commission:** 0.1% per trade (default)
- **Slippage:** 0.05% per trade (default)

```bash
# High-frequency (higher costs)
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --capital 10000 \
  --timeframe 5m \
  --commission 0.002 \
  --slippage 0.001

# Low-frequency (lower costs)
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --capital 10000 \
  --timeframe 1d \
  --commission 0.0005 \
  --slippage 0.0002
```

---

## Next Steps After Backtesting

### If Profitable (Total Return > 20%/year, Sharpe > 1.5):

**1. Paper Trading (3 months minimum)**
```bash
conda activate crypto-bot
export TRADING_MODE=PAPER
python -m orchestration.master_orchestrator
```

Monitor:
- Actual vs expected returns
- Slippage impact
- Latency issues
- System reliability

**2. Live Trading (start small)**
```bash
# Start with $500-1000 (5-10% of capital)
export TRADING_MODE=LIVE
export LIVE_CONFIRMATION="YES_I_WANT_LIVE_TRADING"
export POSITION_SIZE_PCT=0.02
python -m orchestration.master_orchestrator --config config/overrides/prod.yaml
```

**3. Scale Gradually**
- Month 1: $500
- Month 2: $1,000 (if profitable)
- Month 3: $2,000 (if still profitable)
- Month 4+: Scale to full capital

### If Not Profitable:

**Options:**
1. **Adjust Parameters:** Try different position sizes, stops, timeframes
2. **Different Symbols:** Some assets may work better than others
3. **Strategy Revision:** Modify regime detection or fusion weights
4. **Wait for Better Market Conditions:** Strategy may work in specific regimes

---

## Backtesting Limitations

### What Backtesting CAN'T Tell You:

❌ **Future Performance**
Past results don't guarantee future success. Markets change.

❌ **Exact Fills**
Backtest assumes you always get filled at the price you want. Reality has slippage.

❌ **Black Swan Events**
Backtest can't predict unexpected crashes or regulatory changes.

❌ **Psychological Impact**
Watching real money fluctuate is different from simulations.

### Overfitting Risk

**Problem:** Strategy works on past data but fails on new data

**How to avoid:**
- Test on 2+ years of data
- Test multiple symbols
- Use out-of-sample validation (train on 2022-2023, test on 2024)
- Don't over-optimize parameters

---

## Troubleshooting

### "Insufficient data: need at least 300 candles"

**Solution:** Extend date range or use smaller timeframe
```bash
# Change from 1 week to 1 month
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --start-date 2024-11-01 \
  --end-date 2024-12-01 \
  --capital 10000
```

### "Failed to fetch data from exchange"

**Possible causes:**
- Rate limiting (wait 1 minute, try again)
- Invalid symbol format (use "BTC/USD", not "BTCUSD")
- Exchange API down

**Solution:**
```bash
# Use different exchange
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --capital 10000 \
  --exchange binance
```

### Strategy never opens positions

**Possible causes:**
- Confidence threshold too high
- Position size too large
- Insufficient data

**Solution:**
```bash
# Lower confidence threshold
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --capital 10000 \
  --min-confidence-open 0.45 \
  --position-size 0.05
```

---

## Summary: Answering "What's the profitability with $10,000?"

**Steps:**

1. **Run 1-year backtest** (5 minutes)
   ```bash
   python -m backtesting.run_backtest --symbol BTC/USD --capital 10000
   ```

2. **Check key metrics:**
   - Total Return: ____%
   - Sharpe Ratio: ____
   - Max Drawdown: ____%
   - Win Rate: ____%

3. **If profitable** (>20% return, >1.5 Sharpe):
   - Run 2-year backtest
   - Test multiple symbols
   - Paper trade for 3 months
   - Start live with $500-1000

4. **If not profitable:**
   - Adjust parameters
   - Try different timeframes
   - Test different market periods
   - Consider strategy revision

**Remember:** Crypto trading is risky. Only invest what you can afford to lose entirely.

---

## Contact & Support

Questions about backtesting? Check:
- README.md (main documentation)
- config/CONFIG_USAGE.md (configuration guide)
- docs/AGENTS_OVERVIEW.md (architecture overview)

**Running into issues?** Enable debug logging:
```bash
python -m backtesting.run_backtest \
  --symbol BTC/USD \
  --capital 10000 \
  --log-level DEBUG
```
