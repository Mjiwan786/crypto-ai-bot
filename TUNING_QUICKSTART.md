# Parameter Tuning & Volume Optimization — Quick Start

**Fast track guide for optimizing bar_reaction_5m parameters**

---

## Quick Start (3 Commands)

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Run parameter optimization (48 combinations, ~10-30 min)
python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 180d

# 3. Validate results against quality gates
python scripts/B6_quality_gates.py
```

---

## What Happens

### Step 1: Parameter Grid Search

Tests **48 combinations** of:
- `trigger_bps`: {8, 10, 12, 15}
- `min_atr_pct`: {0.2, 0.3, 0.4}
- `sl_atr`: {0.5, 0.6}
- `tp2_atr`: {1.6, 1.8}

**Outputs**:
- `reports/opt_grid.csv`: All results ranked by Profit Factor → Sharpe → MaxDD
- `reports/best_params.json`: Best parameter set (rank 1)

### Step 2: Quality Gate Validation

Checks if best params meet production criteria:
- ✅ Profit Factor ≥ 1.3
- ✅ Sharpe Ratio ≥ 1.0
- ✅ Max Drawdown ≤ 6%
- ✅ Total Trades ≥ 40
- ✅ Total Return > 0%

---

## Reading Results

### Check Top 5 Params

```bash
cat reports/opt_grid.csv | head -6
```

Example:
```
rank,pair,timeframe,trigger_bps,min_atr_pct,sl_atr,tp2_atr,profit_factor,sharpe_ratio,max_dd_pct,total_trades
1,BTC/USD,5m,10.0,0.30,0.6,1.8,1.85,1.42,4.20,87
2,BTC/USD,5m,12.0,0.30,0.6,1.8,1.78,1.35,4.85,72
3,BTC/USD,5m,8.0,0.30,0.5,1.8,1.72,1.28,5.10,103
```

**Best params**: Row 1 (rank=1)

### Inspect Best Params JSON

```bash
cat reports/best_params.json
```

Shows:
- Parameters: trigger_bps, min_atr_pct, sl_atr, tp2_atr
- Performance: profit_factor, sharpe_ratio, max_dd_pct, total_trades
- Metadata: optimization_run, optimized_on

---

## Quality Gates Result

```bash
$ python scripts/B6_quality_gates.py

BTC/USD:
  Overall: PASS [OK]
  - Total Return: PASS (+12.50% vs >0%)
  - Profit Factor: PASS (1.85 vs >=1.3)
  - Max Drawdown: PASS (4.20% vs <=6%)
  - Sharpe Ratio: PASS (1.42 vs >=1.0)
  - Num Trades: PASS (87 vs >=40)

OVERALL: PASS [OK] - All pairs meet quality gates
```

---

## If Quality Gates PASS ✅

**Deploy to config**:

1. Update `config/bar_reaction_5m.yaml`:
   ```yaml
   strategy:
     trigger_bps_up: 10.0      # From best_params.json
     trigger_bps_down: 10.0
     min_atr_pct: 0.30
     sl_atr: 0.6
     tp2_atr: 1.8
   ```

2. Run paper trading for 7 days:
   ```bash
   export MODE=PAPER
   export TRADING_PAIR_WHITELIST="XBTUSD"
   python scripts/start_trading_system.py
   ```

3. Monitor via `kraken:status` stream

4. Go LIVE (if paper mode successful):
   ```bash
   export MODE=LIVE
   export LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
   python scripts/start_trading_system.py
   ```

---

## If Quality Gates FAIL ❌

### Problem: Too Few Trades (<40)

**Solution: Lower trigger thresholds**

Edit `config/bar_reaction_5m.yaml`:
```yaml
strategy:
  trigger_bps_up: 8.0      # Lower from 12.0
  trigger_bps_down: 8.0
  min_atr_pct: 0.20        # Lower from 0.25
  max_atr_pct: 3.5         # Raise from 3.0
```

Then re-run:
```bash
python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 180d
```

### Problem: Low Profit Factor (<1.3)

**Actions**:
1. Test on different time period:
   ```bash
   python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 90d
   ```

2. Try different pairs:
   ```bash
   python scripts/optimize_grid.py --pairs "ETH/USD" --lookback 180d
   ```

3. Tighten cost model for safety:
   ```yaml
   backtest:
     maker_fee_bps: 18      # Increase from 16
   ```

### Problem: High Drawdown (>6%)

**Solution: Tighter stops or lower risk**

```yaml
strategy:
  sl_atr: 0.5              # Tighter stop (was 0.6)
  risk_per_trade_pct: 0.5  # Lower risk (was 0.6)
```

---

## Multi-Pair Optimization

Test on multiple pairs simultaneously:

```bash
python scripts/optimize_grid.py --pairs "BTC/USD,ETH/USD,SOL/USD" --lookback 90d
```

**Grid**: 48 params × 3 pairs = **144 combinations**

**Runtime**: ~30-60 minutes (with caching)

---

## Advanced Options

### Custom Lookback Period

```bash
# 1 year backtest
python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 1y

# 30 days (quick test)
python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 30d
```

### Custom Initial Capital

```bash
python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 180d --capital 50000
```

### Debug Mode

```bash
python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 180d --debug
```

Shows:
- Detailed logs per backtest
- Data fetch progress
- Full stack traces on errors

---

## Interpreting Metrics

### Profit Factor

**Definition**: Gross profit / Gross loss

- **< 1.0**: Losing strategy
- **1.0 - 1.3**: Marginal edge
- **1.3 - 1.5**: Good edge (production threshold)
- **1.5 - 2.0**: Strong edge
- **> 2.0**: Exceptional

### Sharpe Ratio

**Definition**: (Return - RiskFreeRate) / Volatility

- **< 0.5**: Poor risk-adjusted returns
- **0.5 - 1.0**: Acceptable
- **1.0 - 1.5**: Good (production threshold)
- **1.5 - 2.0**: Excellent
- **> 2.0**: Outstanding

### Max Drawdown %

**Definition**: Largest peak-to-trough decline

- **< 5%**: Excellent
- **5% - 10%**: Good
- **10% - 15%**: Acceptable
- **15% - 20%**: Risky
- **> 20%**: Too high for production

### Total Trades

**Definition**: Number of completed trades

- **< 40**: Insufficient sample size
- **40 - 80**: Minimum viable
- **80 - 150**: Good
- **150+**: High frequency

---

## File Locations

| File | Purpose |
|------|---------|
| `reports/opt_grid.csv` | Full grid results (48+ rows) |
| `reports/best_params.json` | Best parameter set |
| `reports/quality_gates.txt` | Quality gate report |
| `config/bar_reaction_5m.yaml` | Strategy config (update after validation) |

---

## Common Issues

### "Insufficient data for BTC/USD: 450 candles"

**Fix**: Increase lookback
```bash
python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 30d
```

### "No successful backtests. Exiting."

**Fix**: Clear cache and retry
```bash
rm -rf data/cache/*
python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 180d --debug
```

### Best params have 0 trades

**Fix**: Apply K3 adjustments (see K_TUNING_VOLUME_COMPLETE.md section K3)

---

## Next Steps

1. **Optimize**: Run grid search
2. **Validate**: Check quality gates
3. **Deploy**: Update config if gates pass
4. **Test**: Paper trade for 7 days
5. **Monitor**: Watch `kraken:status` stream
6. **Go Live**: Enable with safety gates (J1-J3)

---

**Full Documentation**: `K_TUNING_VOLUME_COMPLETE.md`

**Support Files**:
- `BACKTEST_QUICKSTART.md` — Backtest usage
- `SAFETY_GATES_QUICKREF.md` — Emergency controls
- `OPERATIONS_RUNBOOK.md` — Production procedures

---

**Last Updated**: 2025-10-20

