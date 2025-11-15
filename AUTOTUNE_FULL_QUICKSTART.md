# Autotune Full - Quickstart Guide

Comprehensive parameter optimization with Bayesian search, quality gates, and automatic rollback.

---

## Features

✅ **Bayesian Optimization** - Efficient parameter search with Gaussian Processes
✅ **Dual Validation** - 180d fast check + 365d confirmation
✅ **Quality Gates** - PF≥1.35, Sharpe≥1.2, MaxDD≤12%, 12-mo net≥25%
✅ **Circuit Breaker Monitoring** - Abort candidates that trip breakers >5x/hour
✅ **Top-3 Selection** - Promotes #1, keeps #2 & #3 as fallbacks
✅ **Automatic Rollback** - Reverts to backup if validation fails
✅ **Markdown Report** - Comprehensive analysis with comparative stats

---

## Prerequisites

### 1. Install Dependencies

```bash
conda activate crypto-bot
pip install scikit-optimize
```

### 2. Verify Backtest Infrastructure

Ensure `strategies/bar_reaction_5m.py` and `run_backtest()` function exist.

---

## Quick Start

### Run Full Optimization

```bash
conda activate crypto-bot
python scripts/autotune_full.py
```

**Expected Runtime:** 2-6 hours (depending on N_ITERATIONS)

### Monitor Progress

```bash
# Follow logs
tail -f logs/autotune_full.log

# Check current iteration
grep "ITERATION" logs/autotune_full.log | tail -5
```

---

## Configuration

Edit `scripts/autotune_full.py` to customize:

```python
class AutotuneConfig:
    # Search space bounds
    TARGET_BPS_RANGE = (10.0, 30.0)
    STOP_BPS_RANGE = (8.0, 35.0)
    BASE_RISK_PCT_RANGE = (0.5, 2.5)
    STREAK_BOOST_PCT_RANGE = (0.0, 0.3)
    HEAT_THRESHOLD_RANGE = (50.0, 85.0)
    MAX_TRADES_PER_MIN_RANGE = (2, 8)

    # Quality gates
    MIN_PROFIT_FACTOR = 1.35
    MIN_SHARPE_RATIO = 1.2
    MAX_DRAWDOWN_PCT = 12.0
    MIN_12MO_NET_PCT = 25.0

    # Optimization settings
    N_INITIAL_POINTS = 10   # Random exploration
    N_ITERATIONS = 50       # Total evaluations
```

---

## Output Files

After completion, you'll have:

```
out/
├── autotune_full_report.md      # Comprehensive analysis
├── autotune_full_results.json   # Raw optimization data

config/
├── enhanced_scalper_config.yaml # Updated with promoted params
└── backups/
    └── enhanced_scalper_config.backup.{timestamp}.yaml
```

---

## Workflow

### Step 1: Bayesian Optimization

The script explores the parameter space efficiently:

1. **Initial Random Sampling** (N_INITIAL_POINTS=10)
   - Explores diverse regions of parameter space
   - Builds initial Gaussian Process model

2. **Exploitation vs Exploration** (N_ITERATIONS=50)
   - Uses acquisition function (Expected Improvement)
   - Balances searching promising regions vs exploring new areas

3. **Dual Validation**
   - Quick 180d backtest (fast filter)
   - Confirmatory 365d backtest (thorough validation)

### Step 2: Gate Validation

Each candidate must pass:

| Gate | Threshold | Purpose |
|------|-----------|---------|
| Profit Factor | ≥ 1.35 | Ensure profitable edge |
| Sharpe Ratio | ≥ 1.2 | Risk-adjusted returns |
| Max Drawdown | ≤ 12% | Capital preservation |
| 12-Mo Net Return | ≥ 25% | Minimum CAGR target |
| Circuit Breakers | < 5/hour | Prevent excessive trips |

### Step 3: Top-3 Selection

Configs ranked by composite score:

```
Score = (CAGR × Sharpe) / MaxDrawdown
```

- **#1 (Promoted):** Written to YAML, becomes active config
- **#2 (Fallback 1):** Kept in results JSON for quick swap
- **#3 (Fallback 2):** Additional safety net

### Step 4: Confirmatory Backtest

Promoted config re-tested on 365d to verify:
- Results are reproducible
- No overfitting to optimization run
- All gates still pass

If confirmatory test fails → **Automatic Rollback**

### Step 5: Report Generation

Markdown report includes:
- Executive summary with promoted params
- Top-3 comparison table
- Optimization history and score distribution
- Deployment recommendations
- Rollback instructions

---

## Example Output

### Terminal Output

```
================================================================================
AUTOTUNE FULL - COMPREHENSIVE PARAMETER OPTIMIZATION
================================================================================
Start time: 2025-11-08 10:30:00

Step 1: Backing up current configuration...
Created backup: config/backups/enhanced_scalper_config.backup.1762614600.yaml

Step 2: Running Bayesian optimization...

================================================================================
ITERATION 1/50
================================================================================
Running 180d backtest: {'target_bps': 18.5, 'stop_bps': 20.0, ...}
  180d: PF=1.45, Sharpe=1.35, DD=9.2%, CAGR=32.5%
[PASS] 180d passed gates, confirming on 365d...
  365d: PF=1.52, Sharpe=1.42, DD=8.9%, CAGR=35.8%
[PASS] 365d confirmed!
[NEW BEST] Score: 5.67

...

================================================================================
OPTIMIZATION COMPLETE
================================================================================
Best score: 6.23
Best params: {'target_bps': 17.2, 'stop_bps': 18.5, ...}

Step 3: Selecting top 3 configurations...
Selected 3 top configurations

Config #1:
  Score: 6.23
  PF: 1.58
  Sharpe: 1.68
  MaxDD: 7.8%
  CAGR: 38.2%

...

Step 7: Generating markdown report...
Report saved to: out/autotune_full_report.md

================================================================================
AUTOTUNE COMPLETE!
================================================================================
```

### Generated Report (Sample)

See `out/autotune_full_report.md`:

```markdown
# Autotune Full - Optimization Report

**Generated:** 2025-11-08 12:45:30

## Executive Summary

### Promoted Configuration (#1)

**Parameters:**
- Target BPS: 17.2
- Stop Loss BPS: 18.5
- Base Risk %: 1.35
- Streak Boost %: 0.12

**365-Day Performance:**
- Profit Factor: **1.58**
- Sharpe Ratio: **1.68**
- Max Drawdown: **7.8%**
- CAGR: **38.2%**
- Win Rate: **62.5%**
- Total Trades: 287

## Top 3 Configurations

| Rank | Target BPS | Stop BPS | Risk % | PF | Sharpe | MaxDD % | CAGR % | Score |
|------|------------|----------|--------|-----|--------|---------|--------|-------|
| 1 | 17.2 | 18.5 | 1.35 | 1.58 | 1.68 | 7.8 | 38.2 | 6.23 |
| 2 | 16.8 | 19.0 | 1.28 | 1.52 | 1.61 | 8.2 | 36.5 | 5.89 |
| 3 | 18.0 | 17.8 | 1.42 | 1.55 | 1.64 | 8.5 | 37.1 | 5.76 |

...
```

---

## Troubleshooting

### Issue: Optimization fails with "No valid configurations"

**Cause:** All candidates failed quality gates

**Solution:**
1. Check if gates are too strict for current market conditions
2. Temporarily lower thresholds in `AutotuneConfig`
3. Review backtest data quality

### Issue: Scikit-optimize import error

**Cause:** Package not installed

**Solution:**
```bash
conda activate crypto-bot
pip install scikit-optimize
```

### Issue: Backtest function not found

**Cause:** Missing or incorrect backtest infrastructure

**Solution:**
- Verify `strategies/bar_reaction_5m.py` exists
- Check `run_backtest()` function signature
- Ensure `BACKTEST_PAIRS` matches available data

### Issue: YAML update fails

**Cause:** File permissions or syntax error

**Solution:**
- Check write permissions on `config/enhanced_scalper_config.yaml`
- Review YAML syntax
- Use backup to restore: `cp config/backups/enhanced_scalper_config.backup.{timestamp}.yaml config/enhanced_scalper_config.yaml`

---

## Advanced Usage

### Custom Search Space

Modify parameter ranges:

```python
class AutotuneConfig:
    # Tighter search for conservative configs
    TARGET_BPS_RANGE = (12.0, 20.0)
    STOP_BPS_RANGE = (12.0, 22.0)
    BASE_RISK_PCT_RANGE = (0.8, 1.5)
```

### Faster Optimization (Quick Test)

```python
class AutotuneConfig:
    N_INITIAL_POINTS = 5   # Fewer random points
    N_ITERATIONS = 20      # Fewer total iterations
    LOOKBACK_PERIODS = [180]  # Skip 365d confirmation
```

### More Thorough Search

```python
class AutotuneConfig:
    N_INITIAL_POINTS = 20   # More exploration
    N_ITERATIONS = 100      # More exploitation
```

---

## Integration with Live Trading

### Deploy Promoted Config

1. **Paper Trading First** (7-14 days)
   ```bash
   # Monitor paper trading performance
   python scripts/monitor_paper_trial.py
   ```

2. **Validate Live Metrics**
   - Check Sharpe ≥ 1.0 after 100 trades
   - Ensure MaxDD < 15%
   - Monitor circuit breaker trips < 5/hour

3. **Fallback Triggers**
   - If live Sharpe < 1.0 → Switch to Config #2
   - If live MaxDD > 15% → Switch to Config #3
   - If both fallbacks fail → Revert to manual params

### Monthly Re-optimization

```bash
# Schedule monthly autotune
0 2 1 * * cd /path/to/crypto_ai_bot && conda run -n crypto-bot python scripts/autotune_full.py
```

---

## Performance Benchmarks

**Typical Runtime (N_ITERATIONS=50):**
- Initial Exploration (10 points): ~30-60 minutes
- Bayesian Iterations (40 points): ~2-4 hours
- Total: **2.5-5 hours**

**Resource Usage:**
- CPU: 1-2 cores (single-threaded backtest)
- Memory: ~2-4 GB
- Disk: ~100 MB (results + backups)

---

## Safety Features

### Automatic Rollback

Script automatically reverts to backup if:
- Optimization produces no valid configs
- YAML update fails
- Confirmatory backtest fails gates
- Any unhandled exception occurs

### Backup Management

Backups stored in `config/backups/` with timestamp:
```
config/backups/
├── enhanced_scalper_config.backup.1762614600.yaml
├── enhanced_scalper_config.backup.1762618200.yaml
└── ...
```

**Retention:** Indefinite (manual cleanup recommended)

### Manual Rollback

```bash
# List backups
ls -lt config/backups/

# Restore specific backup
cp config/backups/enhanced_scalper_config.backup.{timestamp}.yaml config/enhanced_scalper_config.yaml
```

---

## Next Steps

1. ✅ Run initial optimization
2. ✅ Review markdown report
3. ✅ Deploy to paper trading
4. ⏳ Monitor for 7 days
5. ⏳ Validate live metrics
6. ⏳ Promote to production or fallback

---

## Support

- **Documentation:** See [PRD-001: Crypto AI Bot - Core Intelligence Engine](docs/PRD-001-CRYPTO-AI-BOT.md)
- **Backtest Guide:** See `BACKTESTING_GUIDE.md`
- **Issues:** Review `INCIDENTS_LOG.md`

---

*Generated by autotune_full.py - Part of Crypto AI Bot Optimization Suite*
