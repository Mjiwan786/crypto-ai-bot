# STEP 10 — Quick Start Guide

## Run Parameter Sweep in 1 Command

```bash
python scripts/run_sweep.py --pairs BTC/USD --lookback 365 --method grid
```

---

## Quick Commands

### Grid Search (Exhaustive)
```bash
python scripts/run_sweep.py --pairs BTC/USD --lookback 365 --method grid
```

### Bayesian Search (Fast)
```bash
python scripts/run_sweep.py --pairs BTC/USD --lookback 720 --method bayesian --samples 50
```

### Custom Constraints
```bash
python scripts/run_sweep.py \
    --pairs BTC/USD \
    --lookback 365 \
    --method grid \
    --max-dd 15.0 \
    --min-roi 12.0 \
    --top-k 10
```

### Multi-Pair
```bash
python scripts/run_sweep.py \
    --pairs BTC/USD,ETH/USD \
    --lookback 720 \
    --method grid \
    --top-k 5
```

### Small Parameter Space (Fast Test)
```bash
python scripts/run_sweep.py \
    --pairs BTC/USD \
    --lookback 365 \
    --method grid \
    --ma-short 10,20 \
    --ma-long 50,100 \
    --bb-width 2.0 \
    --rr-min 2.0,2.5 \
    --sl-mult 1.5 \
    --ml-conf 0.55,0.60 \
    --risk-pct 0.015
```

---

## What Gets Generated

### 1. Top-k Parameter YAML Files
Location: `config/params/top/`

Example: `params_rank1_pf3.45.yaml`
```yaml
rank: 1
score: 3.45
meets_constraints: true
params:
  ma_short_period: 10
  ma_long_period: 50
  bb_width: 2.0
  rr_min: 2.5
  sl_multiplier: 1.5
  ml_min_confidence: 0.6
  risk_pct: 0.015
metrics:
  profit_factor: 3.45
  max_drawdown: 6.2
  monthly_roi_mean: 18.3
  sharpe_ratio: 1.95
  total_trades: 47
  win_rate: 72.34
```

### 2. Summary Report
Location: `out/sweep_summary.md`

Contains:
- Sweep configuration
- KPI constraints
- Results summary (total evaluated, % meeting constraints)
- Top-k parameter sets with full metrics
- Parameter values for each rank

---

## Default Parameter Space

```yaml
ma_short_periods: [5, 10, 20]
ma_long_periods: [20, 50, 100]
bb_width: [1.5, 2.0, 2.5]
rr_min: [1.5, 2.0, 2.5, 3.0]
sl_multiplier: [1.0, 1.5, 2.0, 2.5]
ml_min_confidence: [0.50, 0.55, 0.60, 0.65]
risk_pct: [0.01, 0.015, 0.02]

Total combinations: 2,160
```

---

## KPI Constraints

| Constraint | Default | Description |
|------------|---------|-------------|
| Max Drawdown | 20.0% | Maximum equity drawdown allowed |
| Min Monthly ROI | 10.0% | Minimum average monthly return |
| Min Trades | 10 | Minimum number of trades for statistical significance |

Override with:
```bash
--max-dd 15.0 --min-roi 12.0
```

---

## Grid vs Bayesian Search

| Method | Speed | Coverage | When to Use |
|--------|-------|----------|-------------|
| Grid | Slow | 100% | Small space (<1000 combos) |
| Bayesian | Fast | ~10-20% | Large space (>1000 combos) |

**Rule of thumb:**
- Grid: Full optimization, guaranteed best result
- Bayesian: Quick exploration, good enough result

---

## Test Sweep System

```bash
# Test imports
python -c "from tuning import ParameterSweep, SweepConfig, Objective; print('OK')"

# Quick test with minimal space
python scripts/run_sweep.py \
    --pairs BTC/USD \
    --lookback 180 \
    --method grid \
    --ma-short 10 \
    --ma-long 50 \
    --bb-width 2.0 \
    --rr-min 2.0 \
    --sl-mult 1.5 \
    --ml-conf 0.55 \
    --risk-pct 0.015 \
    --top-k 1
```

This creates a 1×1×1×1×1×1×1 = 1 combination space for instant testing.

---

## Expected Results

### Good Sweep
```
Results:
  Total evaluated: 2160
  Meets constraints: 458 (21.2%)

Top result:
  Profit Factor: 3.45
  Max Drawdown: 6.20%
  Monthly ROI: 18.30%
  Sharpe Ratio: 1.95
```

### Bad Sweep
```
Results:
  Total evaluated: 2160
  Meets constraints: 0 (0.0%)

  No parameter set meets KPI constraints!
  Consider relaxing constraints or expanding parameter space.
```

---

## Troubleshooting

### Problem: "No config meets constraints"

**Solution 1:** Relax constraints
```bash
--max-dd 25.0 --min-roi 8.0
```

**Solution 2:** Expand parameter space
```bash
--ma-short 5,10,15,20,25 --ma-long 20,40,60,80,100
```

**Solution 3:** Try different lookback
```bash
--lookback 365  # Instead of 720
```

---

### Problem: "Sweep too slow"

**Solution 1:** Use Bayesian search
```bash
--method bayesian --samples 50
```

**Solution 2:** Reduce parameter space
```bash
--ma-short 10,20 --ma-long 50,100
```

**Solution 3:** Shorter lookback
```bash
--lookback 180
```

---

## Files

```
tuning/
  ├── __init__.py          # Module exports
  ├── sweep.py             # Sweep engine
  └── objectives.py        # Objective functions

scripts/
  └── run_sweep.py         # CLI tool

config/params/top/         # Top-k parameter YAML files

out/
  └── sweep_summary.md     # Sweep report
```

---

## Full Documentation

See: `STEP10_COMPLETE.md`

---

**Ready to optimize parameters!** 🎯
