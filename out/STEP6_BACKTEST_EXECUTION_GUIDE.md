# STEP 6 — Backtest Execution Guide

**Objective**: Run 360-day backtests per strategy to validate STEP 6 enhancements and measure KPI improvements (PF↑ and/or DD↓).

**Status**: Ready to Execute
**Test Coverage**: 72/72 tests passing ✅
**Strategies**: Momentum, Mean Reversion, Scalper

---

## Executive Summary

This guide provides ready-to-execute commands for running comprehensive 360-day backtests on all three strategies with STEP 6 enhancements:

- **Momentum Strategy**: ADX + slope confirmation, trailing stops, partial TP ladder
- **Mean Reversion Strategy**: ADX low check, RSI extremes, time-stop
- **Scalper Strategy**: Spread/latency guards, trade throttling

**Expected Improvements**:
- Profit Factor (PF): +10-20% improvement
- Max Drawdown (DD): -15-25% reduction
- Win Rate: +5-10% improvement
- Sharpe Ratio: +0.2-0.5 improvement

---

## Prerequisites

### 1. Environment Setup

```bash
# Activate conda environment
conda activate crypto-bot

# Verify Python packages
python -c "import pandas, numpy, pytest, redis; print('All packages OK')"
```

### 2. Redis Cloud Connection

```bash
# Test Redis connection
redis-cli -u redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls \
  --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem \
  PING
# Expected: PONG
```

### 3. Historical Data Requirements

**Required Data**:
- Symbol: BTC/USD
- Period: 360 days (2024-01-01 to 2024-12-26)
- Timeframes:
  - Momentum: 1h bars
  - Mean Reversion: 5m bars
  - Scalper: 1m bars

**Verify Data Availability**:

```bash
# Check if historical data exists
ls -lh data/cache/BTC_USD_*.csv

# Expected files:
# BTC_USD_1m.csv  (for Scalper)
# BTC_USD_5m.csv  (for Mean Reversion)
# BTC_USD_1h.csv  (for Momentum)
```

**If Data Missing** (see Data Preparation section below)

---

## Backtest Execution Commands

### Strategy 1: Momentum (Trend-Following)

**STEP 6 Enhancements**:
- ✅ ADX confirmation (min 25.0)
- ✅ Slope confirmation (min 0.0)
- ✅ Trailing stops (2% trail, 1% min profit)
- ✅ Partial TP ladder (1.5x, 2.5x, 3.5x ATR)
- ✅ RR validation (min 1.6)

**Command**:

```bash
python scripts/backtest.py \
  --strategy momentum \
  --symbol BTC/USD \
  --timeframe 1h \
  --start-date 2024-01-01 \
  --end-date 2024-12-26 \
  --initial-capital 10000 \
  --output-dir backtests/step6/momentum \
  --enable-step6-enhancements \
  --verbose
```

**Expected Runtime**: 3-5 minutes

**Output Files**:
- `backtests/step6/momentum/trades.csv` - All trades
- `backtests/step6/momentum/equity_curve.csv` - Equity progression
- `backtests/step6/momentum/metrics.json` - KPI summary

---

### Strategy 2: Mean Reversion (Range-Trading)

**STEP 6 Enhancements**:
- ✅ ADX low check (max 20.0)
- ✅ RSI extreme detection (oversold <30, overbought >70)
- ✅ Time-stop (max 30 bars = 2.5 hours)
- ✅ Percentage-based SL/TP (2% SL, 4% TP)
- ✅ RR validation (min 1.6)

**Command**:

```bash
python scripts/backtest.py \
  --strategy mean_reversion \
  --symbol BTC/USD \
  --timeframe 5m \
  --start-date 2024-01-01 \
  --end-date 2024-12-26 \
  --initial-capital 10000 \
  --output-dir backtests/step6/mean_reversion \
  --enable-step6-enhancements \
  --verbose
```

**Expected Runtime**: 8-12 minutes (more bars)

**Output Files**:
- `backtests/step6/mean_reversion/trades.csv`
- `backtests/step6/mean_reversion/equity_curve.csv`
- `backtests/step6/mean_reversion/metrics.json`

---

### Strategy 3: Scalper (High-Frequency)

**STEP 6 Enhancements**:
- ✅ Spread check (max 3 bps)
- ✅ Latency check (max 500ms)
- ✅ Trade throttling (max 3 trades/min)
- ✅ ATR-based SL/TP (1.0x SL, 1.2x TP)
- ✅ RR validation (min 1.0)

**Command**:

```bash
python scripts/backtest.py \
  --strategy scalper \
  --symbol BTC/USD \
  --timeframe 1m \
  --start-date 2024-01-01 \
  --end-date 2024-12-26 \
  --initial-capital 10000 \
  --output-dir backtests/step6/scalper \
  --enable-step6-enhancements \
  --verbose
```

**Expected Runtime**: 15-20 minutes (most bars)

**Output Files**:
- `backtests/step6/scalper/trades.csv`
- `backtests/step6/scalper/equity_curve.csv`
- `backtests/step6/scalper/metrics.json`

---

## KPI Comparison Table Template

### Momentum Strategy

| Metric | Before STEP 6 | After STEP 6 | Change | Status |
|--------|---------------|--------------|--------|--------|
| **Profit Factor** | ___ | ___ | ___% | ⬜ |
| **Max Drawdown** | ___% | ___% | ___% | ⬜ |
| **Total Return** | ___% | ___% | ___% | ⬜ |
| **Win Rate** | ___% | ___% | ___% | ⬜ |
| **Sharpe Ratio** | ___ | ___ | ___ | ⬜ |
| **Total Trades** | ___ | ___ | ___ | ⬜ |
| **Avg Trade** | $__ | $__ | $__ | ⬜ |
| **Best Trade** | $__ | $__ | $__ | ⬜ |
| **Worst Trade** | $__ | $__ | $__ | ⬜ |

**Key Filters Active (STEP 6)**:
- ADX ≥ 25.0: ___ trades rejected
- Slope ≥ 0.0: ___ trades rejected
- RR < 1.6: ___ trades rejected
- Trailing stops triggered: ___ trades
- Partial TP used: ___ trades

---

### Mean Reversion Strategy

| Metric | Before STEP 6 | After STEP 6 | Change | Status |
|--------|---------------|--------------|--------|--------|
| **Profit Factor** | ___ | ___ | ___% | ⬜ |
| **Max Drawdown** | ___% | ___% | ___% | ⬜ |
| **Total Return** | ___% | ___% | ___% | ⬜ |
| **Win Rate** | ___% | ___% | ___% | ⬜ |
| **Sharpe Ratio** | ___ | ___ | ___ | ⬜ |
| **Total Trades** | ___ | ___ | ___ | ⬜ |
| **Avg Trade** | $__ | $__ | $__ | ⬜ |
| **Best Trade** | $__ | $__ | $__ | ⬜ |
| **Worst Trade** | $__ | $__ | $__ | ⬜ |

**Key Filters Active (STEP 6)**:
- ADX ≤ 20.0: ___ trades rejected
- RSI extreme (OB/OS): ___ trades accepted
- Time-stop (30 bars): ___ trades closed early
- RR < 1.6: ___ trades rejected

---

### Scalper Strategy

| Metric | Before STEP 6 | After STEP 6 | Change | Status |
|--------|---------------|--------------|--------|--------|
| **Profit Factor** | ___ | ___ | ___% | ⬜ |
| **Max Drawdown** | ___% | ___% | ___% | ⬜ |
| **Total Return** | ___% | ___% | ___% | ⬜ |
| **Win Rate** | ___% | ___% | ___% | ⬜ |
| **Sharpe Ratio** | ___ | ___ | ___ | ⬜ |
| **Total Trades** | ___ | ___ | ___ | ⬜ |
| **Avg Trade** | $__ | $__ | $__ | ⬜ |
| **Best Trade** | $__ | $__ | $__ | ⬜ |
| **Worst Trade** | $__ | $__ | $__ | ⬜ |

**Key Filters Active (STEP 6)**:
- Spread > 3 bps: ___ trades rejected
- Latency > 500ms: ___ trades rejected
- Throttled (>3/min): ___ trades rejected
- RR < 1.0: ___ trades rejected

---

## Execution Steps

### Step 1: Create Output Directories

```bash
mkdir -p backtests/step6/{momentum,mean_reversion,scalper}
mkdir -p backtests/baseline/{momentum,mean_reversion,scalper}
```

### Step 2: Run Baseline Backtests (Optional)

If you need "before" metrics, run backtests WITHOUT `--enable-step6-enhancements`:

```bash
# Momentum baseline
python scripts/backtest.py \
  --strategy momentum \
  --symbol BTC/USD \
  --timeframe 1h \
  --start-date 2024-01-01 \
  --end-date 2024-12-26 \
  --initial-capital 10000 \
  --output-dir backtests/baseline/momentum

# Mean Reversion baseline
python scripts/backtest.py \
  --strategy mean_reversion \
  --symbol BTC/USD \
  --timeframe 5m \
  --start-date 2024-01-01 \
  --end-date 2024-12-26 \
  --initial-capital 10000 \
  --output-dir backtests/baseline/mean_reversion

# Scalper baseline
python scripts/backtest.py \
  --strategy scalper \
  --symbol BTC/USD \
  --timeframe 1m \
  --start-date 2024-01-01 \
  --end-date 2024-12-26 \
  --initial-capital 10000 \
  --output-dir backtests/baseline/scalper
```

### Step 3: Run STEP 6 Enhanced Backtests

Execute the three commands from the "Backtest Execution Commands" section above.

### Step 4: Generate KPI Comparison

```bash
python scripts/compare_backtest_results.py \
  --baseline-dir backtests/baseline \
  --step6-dir backtests/step6 \
  --output-file backtests/step6_comparison.md
```

This will generate a comparison table with all metrics.

### Step 5: Validate Completion Criteria

**STEP 6 is COMPLETE if**:
- ✅ Profit Factor improves by ≥5% for at least 2/3 strategies, OR
- ✅ Max Drawdown decreases by ≥10% for at least 2/3 strategies

**Expected Outcomes**:

| Strategy | Expected PF Change | Expected DD Change |
|----------|-------------------|-------------------|
| Momentum | +15-25% | -20-30% |
| Mean Reversion | +10-15% | -15-20% |
| Scalper | +5-10% | -10-15% |

---

## Data Preparation (If Needed)

### Option 1: Download from Kraken API

```bash
python scripts/download_historical_data.py \
  --symbol BTC/USD \
  --start-date 2024-01-01 \
  --end-date 2024-12-26 \
  --timeframes 1m,5m,1h \
  --output-dir data/cache
```

### Option 2: Use Existing Data Ingestion

```bash
# Start data pipeline
python scripts/run_data_pipeline.py \
  --symbol BTC/USD \
  --backfill-days 360 \
  --timeframes 1m,5m,1h
```

### Option 3: Generate Synthetic Data (Testing Only)

```bash
python scripts/generate_synthetic_ohlcv.py \
  --symbol BTC/USD \
  --days 360 \
  --timeframes 1m,5m,1h \
  --output-dir data/cache
```

---

## Troubleshooting

### Issue 1: Redis Connection Failed

```bash
# Test connection
redis-cli -u redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 \
  --tls \
  --cacert C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem \
  PING

# If fails, check:
# 1. Network connectivity
# 2. Certificate path is correct
# 3. Password is correct
```

### Issue 2: Missing Historical Data

```bash
# Check data files
ls -lh data/cache/BTC_USD_*.csv

# If missing, run data preparation (see above)
```

### Issue 3: Backtest Script Not Found

```bash
# Check if script exists
ls -lh scripts/backtest.py

# If missing, you may need to create it or use alternative:
python -m backtesting.run_backtest --help
```

### Issue 4: Out of Memory (Scalper)

If the 1m backtest runs out of memory:

```bash
# Option A: Reduce date range
python scripts/backtest.py \
  --strategy scalper \
  --start-date 2024-07-01 \
  --end-date 2024-12-26 \
  # ... other params

# Option B: Use chunked processing
python scripts/backtest.py \
  --strategy scalper \
  --chunk-size 30 \
  # ... other params
```

---

## Expected Results Analysis

### Momentum Strategy

**Before STEP 6** (Typical Baseline):
- PF: 1.2-1.4
- DD: -15% to -20%
- Win Rate: 45-50%
- Sharpe: 0.8-1.2

**After STEP 6** (Expected):
- PF: 1.5-1.8 (+15-25%)
- DD: -10% to -15% (-20-30% reduction)
- Win Rate: 50-55% (+5-10%)
- Sharpe: 1.2-1.6 (+0.4-0.5)

**Why Improvements Expected**:
- ADX filter removes weak trends (fewer false entries)
- Slope confirms direction (better entry timing)
- Trailing stops capture extended moves (larger winners)
- Partial TP locks in profits (reduces giveback)

---

### Mean Reversion Strategy

**Before STEP 6** (Typical Baseline):
- PF: 1.1-1.3
- DD: -12% to -18%
- Win Rate: 55-60%
- Sharpe: 0.6-1.0

**After STEP 6** (Expected):
- PF: 1.3-1.5 (+10-15%)
- DD: -10% to -15% (-15-20% reduction)
- Win Rate: 60-65% (+5-10%)
- Sharpe: 1.0-1.4 (+0.4-0.5)

**Why Improvements Expected**:
- ADX low filter ensures ranging conditions (better setup)
- RSI extremes improve entry timing (buy dips, sell rips)
- Time-stop prevents prolonged losers (cuts tail risk)
- Higher RR (1.6 vs 1.0) enforces better trade quality

---

### Scalper Strategy

**Before STEP 6** (Typical Baseline):
- PF: 1.05-1.15
- DD: -8% to -12%
- Win Rate: 60-65%
- Sharpe: 0.5-0.8

**After STEP 6** (Expected):
- PF: 1.15-1.25 (+5-10%)
- DD: -7% to -10% (-10-15% reduction)
- Win Rate: 62-68% (+2-5%)
- Sharpe: 0.7-1.0 (+0.2-0.3)

**Why Improvements Expected**:
- Spread filter avoids slippage (better fill quality)
- Latency filter ensures fast execution (reduced adverse selection)
- Throttling prevents overtrading (fewer marginal trades)
- RR validation (1.0) removes worst setups

---

## Success Criteria Checklist

- [ ] All three strategies backtest successfully
- [ ] Trades CSV files generated for each strategy
- [ ] Equity curves show smooth progression
- [ ] Profit Factor improves for ≥2/3 strategies
- [ ] Max Drawdown decreases for ≥2/3 strategies
- [ ] Win Rate improves or stays stable
- [ ] Sharpe Ratio improves
- [ ] Filter rejection counts are reasonable (10-30% of signals)
- [ ] No crashes or data errors
- [ ] Results match expected ranges

---

## Next Steps After Backtest Completion

1. **Analyze Results**: Fill in the KPI comparison tables above
2. **Validate Completion**: Check if PF↑ or DD↓ criteria met
3. **Document Findings**: Create `STEP6_BACKTEST_RESULTS.md`
4. **Proceed to STEP 7**: If successful, move to live paper trading validation
5. **Iterate if Needed**: If results don't meet criteria, tune parameters

---

## Quick Start (TL;DR)

```bash
# 1. Activate environment
conda activate crypto-bot

# 2. Create directories
mkdir -p backtests/step6/{momentum,mean_reversion,scalper}

# 3. Run all three backtests
python scripts/backtest.py --strategy momentum --symbol BTC/USD --timeframe 1h \
  --start-date 2024-01-01 --end-date 2024-12-26 --initial-capital 10000 \
  --output-dir backtests/step6/momentum --enable-step6-enhancements --verbose

python scripts/backtest.py --strategy mean_reversion --symbol BTC/USD --timeframe 5m \
  --start-date 2024-01-01 --end-date 2024-12-26 --initial-capital 10000 \
  --output-dir backtests/step6/mean_reversion --enable-step6-enhancements --verbose

python scripts/backtest.py --strategy scalper --symbol BTC/USD --timeframe 1m \
  --start-date 2024-01-01 --end-date 2024-12-26 --initial-capital 10000 \
  --output-dir backtests/step6/scalper --enable-step6-enhancements --verbose

# 4. Compare results
python scripts/compare_backtest_results.py \
  --baseline-dir backtests/baseline \
  --step6-dir backtests/step6 \
  --output-file backtests/step6_comparison.md

# 5. Check completion
cat backtests/step6_comparison.md
```

---

## File Reference

**Input Files**:
- `data/cache/BTC_USD_1h.csv` - 360 days of hourly data
- `data/cache/BTC_USD_5m.csv` - 360 days of 5-min data
- `data/cache/BTC_USD_1m.csv` - 360 days of 1-min data

**Output Files**:
- `backtests/step6/momentum/trades.csv`
- `backtests/step6/momentum/equity_curve.csv`
- `backtests/step6/momentum/metrics.json`
- `backtests/step6/mean_reversion/trades.csv`
- `backtests/step6/mean_reversion/equity_curve.csv`
- `backtests/step6/mean_reversion/metrics.json`
- `backtests/step6/scalper/trades.csv`
- `backtests/step6/scalper/equity_curve.csv`
- `backtests/step6/scalper/metrics.json`
- `backtests/step6_comparison.md` - Final comparison report

---

**Guide Version**: 1.0
**Last Updated**: 2024-12-26
**Contact**: See PRD.md for team info
