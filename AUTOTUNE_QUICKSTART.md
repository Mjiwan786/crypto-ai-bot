# Backtest Autotune Loop - Quick Start Guide

## Overview

The `scripts/autotune_week1.py` script performs **automated parameter optimization** using grid search with adaptive aggression control.

## Features

✅ **Grid Search Optimization**
- target_bps: 12..22
- stop_bps: 10..25
- base_risk_pct: 0.8..1.8
- streak_boost_pct: 0..0.2

✅ **Constraint Validation**
- Profit Factor (PF) ≥ 1.35
- Sharpe Ratio ≥ 1.2
- Max Drawdown ≤ 12%

✅ **Objective Function**
- Maximize: CAGR - heat_penalty
- heat_penalty = 0 if heat < 80%, else (heat - 80) * 10

✅ **Adaptive Aggression**
- Shrinks parameter ranges on failures
- Expands parameter ranges on successes
- Self-tuning exploration strategy

✅ **Multi-Period Validation**
- Run on 180d first (fast)
- Confirm on 365d (thorough)
- Only persist if both pass

✅ **Auto-Persistence**
- Saves best config to `enhanced_scalper_config.yaml`
- Creates backup before overwriting
- Adds metadata for tracking

## Usage

### Basic Run

```bash
# Default: BTC/USD, ETH/USD, 50 iterations
python scripts/autotune_week1.py
```

### Custom Pairs

```bash
# Single pair
python scripts/autotune_week1.py --pairs BTC/USD

# Multiple pairs
python scripts/autotune_week1.py --pairs BTC/USD,ETH/USD,SOL/USD
```

### Quick Test

```bash
# Small grid for testing (2x2x2x2 = 16 combinations)
python scripts/autotune_week1.py --iterations 5 --grid-points 2
```

### Production Run

```bash
# Full grid search (5x5x5x5 = 625 combinations)
python scripts/autotune_week1.py \
  --pairs BTC/USD,ETH/USD \
  --iterations 100 \
  --grid-points 5 \
  --capital 100000 \
  --output out/autotune_production_results.json
```

### With Logging

```bash
# Debug mode for troubleshooting
python scripts/autotune_week1.py --log-level DEBUG
```

## Command-Line Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--pairs` | `BTC/USD,ETH/USD` | Trading pairs (comma-separated) |
| `--timeframe` | `5m` | Timeframe for backtests |
| `--iterations` | `50` | Number of grid search iterations |
| `--grid-points` | `5` | Grid points per dimension |
| `--capital` | `10000.0` | Initial capital in USD |
| `--output` | `out/autotune_week1_results.json` | Output file for results |
| `--log-level` | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR) |

## Workflow

1. **Grid Generation**
   - Creates parameter combinations
   - Filters invalid combinations (e.g., stop > target)
   - Adaptive refinement around best results

2. **180d Backtest**
   - Fast validation on 6 months
   - Check constraints
   - Skip if fails

3. **365d Confirmation**
   - Only run if 180d passes
   - Thorough validation on 1 year
   - Update aggression based on result

4. **Adaptive Learning**
   - Success → increase aggression (expand search)
   - Failure → decrease aggression (shrink search)
   - Converge to optimal region

5. **Best Config Selection**
   - Maximize objective score
   - Must pass all constraints
   - Prefer 365d over 180d

6. **Persistence**
   - Save to YAML with backup
   - Add metadata (timestamp, source, params)
   - Generate JSON report with all results

## Output

### Console

```
================================================================================
BEST CONFIGURATION:
  target_bps: 17.0
  stop_bps: 17.5
  base_risk_pct: 1.3
  streak_boost_pct: 0.1

METRICS:
  PF: 1.82
  Sharpe: 1.94
  MaxDD: 8.75%
  CAGR: 40.58%
  Avg Heat: 50.3%
  Win Rate: 64.8%
  Total Trades: 341
  Final Equity: $14,058
  Objective Score: 40.58
================================================================================
```

### Files Generated

1. **`enhanced_scalper_config.yaml`**
   - Updated with best parameters
   - Backup created automatically

2. **`out/autotune_week1_results.json`**
   - Metadata (timestamp, pairs, iterations)
   - Best result with full metrics
   - All results (for analysis)

## Configuration Updates

The script updates these fields in `enhanced_scalper_config.yaml`:

```yaml
scalper:
  target_bps: 17.0              # Optimized
  stop_loss_bps: 17.5           # Optimized

dynamic_sizing:
  base_risk_pct_small: 1.3      # Optimized
  base_risk_pct_large: 1.04     # 80% of base_risk_pct_small
  streak_boost_pct: 0.1         # Optimized

autotune_metadata:
  last_updated: "2025-11-08T12:50:21+00:00"
  parameters:
    target_bps: 17.0
    stop_bps: 17.5
    base_risk_pct: 1.3
    streak_boost_pct: 0.1
  source: autotune_week1.py
```

## Constraints

### Hard Constraints (Must Pass)

- **Profit Factor** ≥ 1.35
- **Sharpe Ratio** ≥ 1.2
- **Max Drawdown** ≤ 12%

### Soft Penalties

- **Portfolio Heat** > 80% → apply penalty to objective score
- Penalty = (heat - 80) * 10 per %

## Objective Function

```python
objective_score = CAGR - heat_penalty

where:
  heat_penalty = 0                          if avg_heat < 80%
  heat_penalty = (avg_heat - 80) * 10      if avg_heat ≥ 80%
  heat_penalty += (max_heat - 80) * 5      if max_heat ≥ 80%
```

## Adaptive Aggression Algorithm

```python
# On Success
success_count += 1
aggression_multiplier *= 1.05  # Expand search
aggression_multiplier = min(1.5, aggression_multiplier)

# On Failure
failed_count += 1
aggression_multiplier *= 0.95  # Shrink search
aggression_multiplier = max(0.5, aggression_multiplier)

# Grid Refinement
refinement_factor = 0.3 * aggression_multiplier
new_min = best_value * (1 - refinement_factor)
new_max = best_value * (1 + refinement_factor)
```

## Example Runs

### Quick Test (2 minutes)

```bash
python scripts/autotune_week1.py \
  --pairs BTC/USD \
  --iterations 3 \
  --grid-points 2 \
  --log-level INFO
```

**Expected Output:**
- 12-24 backtests
- ~2 minutes runtime
- Best config found (likely)

### Medium Run (10 minutes)

```bash
python scripts/autotune_week1.py \
  --pairs BTC/USD,ETH/USD \
  --iterations 10 \
  --grid-points 3 \
  --log-level INFO
```

**Expected Output:**
- 200-400 backtests
- ~10 minutes runtime
- High-quality config found

### Production Run (1-2 hours)

```bash
python scripts/autotune_week1.py \
  --pairs BTC/USD,ETH/USD \
  --iterations 50 \
  --grid-points 5 \
  --capital 100000 \
  --output out/autotune_production.json \
  --log-level INFO
```

**Expected Output:**
- 1000-2000 backtests
- 1-2 hours runtime
- Optimal config with high confidence

## Monitoring

### Live Progress

The script logs:
- Current iteration
- Parameters being tested
- 180d metrics (PF, Sharpe, DD, CAGR, Heat, Score)
- Constraint pass/fail
- 365d metrics (if 180d passed)
- Best result so far
- Aggression multiplier changes

### Example Log

```
ITERATION 5/50
  Running backtest: target_bps=17.0, stop_bps=15.0, base_risk_pct=1.2, streak_boost_pct=0.1
  180d: PF=1.45, Sharpe=1.62, DD=9.2%, CAGR=38.5%, Heat=65.3%, Score=38.5
  [PASS] 180d passed constraints, confirming on 365d...
  365d: PF=1.52, Sharpe=1.58, DD=8.9%, CAGR=35.2%, Heat=63.1%, Score=35.2
  Success #12: Increasing aggression to 1.15
  [PASS] 365d CONFIRMED!

BEST RESULT SO FAR:
  Params: target_bps=17.0, stop_bps=15.0, base_risk_pct=1.2, streak_boost_pct=0.1
  CAGR: 35.2%
  Objective Score: 35.2
```

## Troubleshooting

### No Valid Configuration Found

**Cause:** Constraints too strict or parameter ranges too narrow

**Solution:**
```bash
# Relax constraints temporarily
# Edit check_constraints() in the script
# Or expand parameter ranges
```

### Too Slow

**Cause:** Too many grid points or iterations

**Solution:**
```bash
# Reduce grid resolution
python scripts/autotune_week1.py --grid-points 3 --iterations 20
```

### All Configs Failing Constraints

**Cause:** Unrealistic constraint values or bad simulation

**Solution:**
1. Check constraint values in `check_constraints()`
2. Verify simulation quality metrics in `run_single_backtest()`
3. Review grid parameter ranges

## Next Steps

1. **Run Production Autotune**
   ```bash
   python scripts/autotune_week1.py --iterations 100 --grid-points 5
   ```

2. **Review Results**
   ```bash
   cat out/autotune_week1_results.json | python -m json.tool
   ```

3. **Apply Best Config**
   - Already applied automatically to `enhanced_scalper_config.yaml`
   - Backup created at `enhanced_scalper_config.backup.<timestamp>.yaml`

4. **Run Live/Paper Trading**
   ```bash
   # Test with paper trading first
   python scripts/run_paper_trial.py
   ```

5. **Monitor Performance**
   - Compare live metrics to backtest expectations
   - Re-run autotune monthly or after regime changes

## Integration with Real Backtests

**Current Status:** Uses simulated metrics for demonstration

**TODO for Production:**

1. Replace simulated metrics in `run_single_backtest()`:
   ```python
   # Replace this:
   pf = np.random.uniform(1.1, 1.3) + overall_quality * 0.6

   # With this:
   runner = BacktestRunner(config)
   result = runner.run(ohlcv_data, pairs=pairs)
   pf = result.metrics.profit_factor
   ```

2. Ensure strategies accept parameter injection:
   ```python
   config.risk_config.target_bps = params.target_bps
   config.risk_config.stop_bps = params.stop_bps
   ```

3. Load real OHLCV data instead of synthetic:
   ```python
   # Replace load_ohlcv_data() with real data fetch
   from data_provider import fetch_historical_ohlcv
   ohlcv_data = fetch_historical_ohlcv(pairs, timeframe, lookback_days)
   ```

## Author

Crypto AI Bot Team

## Last Updated

2025-11-08
