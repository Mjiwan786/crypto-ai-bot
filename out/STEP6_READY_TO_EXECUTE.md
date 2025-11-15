# STEP 6 — Ready to Execute 🚀

**Status**: ✅ ALL TESTS PASSING | 📋 BACKTEST GUIDE READY | ⚡ READY TO RUN

---

## Quick Summary

STEP 6 (Upgrade Entries/Exits) is **code-complete** and **fully tested**. All components are ready for backtesting.

### What's Done ✅

1. **Centralized Utilities Module** (`strategies/utils.py`)
   - 680 lines of production-ready code
   - SL/TP calculations (ATR-based + percentage-based)
   - Technical indicators (ADX, slope, RSI)
   - Trade throttling, spread/latency guards
   - Trailing stops, partial TP ladder, time-stops
   - 33/33 tests passing ✅

2. **Strategy Integrations**
   - **Momentum** (+101 lines): ADX + slope confirm, trailing stops, partial TP
   - **Mean Reversion** (+42 lines): ADX low check, RSI extremes, time-stop
   - **Scalper** (+63 lines): Spread/latency guards, trade throttling
   - All strategies enhanced with centralized utils

3. **Comprehensive Testing**
   - `tests/strategies/test_utils.py`: 33/33 tests passing ✅ (2.19s)
   - `tests/strategies/test_momentum_strategy.py`: 11/11 tests passing ✅ (0.84s)
   - `tests/strategies/test_mean_reversion_strategy.py`: 11/11 tests passing ✅ (0.85s)
   - `tests/strategies/test_scalper_strategy.py`: 17/17 tests passing ✅ (0.91s)
   - **Total: 72/72 tests passing in 4.79s** ✅

4. **Backtest Infrastructure**
   - Comprehensive execution guide created
   - Ready-to-run backtest script created
   - KPI comparison templates prepared

---

## Next Step: Run Backtests

### Option 1: Quick Test (30 days) — Fastest

Test all three strategies on 30 days of data:

```bash
conda activate crypto-bot
python scripts/run_step6_backtests.py --all --quick
```

**Runtime**: ~2-3 minutes
**Output**: Quick validation that everything works

---

### Option 2: Full Backtest (360 days) — Recommended

Run comprehensive 360-day backtests for final validation:

```bash
conda activate crypto-bot
python scripts/run_step6_backtests.py --all
```

**Runtime**: ~5-10 minutes
**Output**:
- `backtests/step6/momentum_results.json`
- `backtests/step6/mean_reversion_results.json`
- `backtests/step6/scalper_results.json`
- `backtests/step6/step6_comparison.txt` (comparison table)

---

### Option 3: Individual Strategy

Run a single strategy:

```bash
# Momentum only (1h bars)
python scripts/run_step6_backtests.py --strategy momentum

# Mean Reversion only (5m bars)
python scripts/run_step6_backtests.py --strategy mean_reversion

# Scalper only (1m bars)
python scripts/run_step6_backtests.py --strategy scalper
```

---

## Expected Results

### Momentum Strategy

| Metric | Expected Range | Why? |
|--------|----------------|------|
| Profit Factor | 1.5 - 1.8 | ADX filter removes weak trends |
| Max Drawdown | -10% to -15% | Trailing stops capture extended moves |
| Win Rate | 50-55% | Better entry timing with slope confirmation |
| Sharpe Ratio | 1.2 - 1.6 | Overall better risk-adjusted returns |

**Key Filters**:
- ADX ≥ 25.0 (strong trend confirmation)
- Slope ≥ 0.0 (direction confirmation)
- RR ≥ 1.6 (minimum quality threshold)

---

### Mean Reversion Strategy

| Metric | Expected Range | Why? |
|--------|----------------|------|
| Profit Factor | 1.3 - 1.5 | ADX low ensures ranging conditions |
| Max Drawdown | -10% to -15% | Time-stop prevents prolonged losers |
| Win Rate | 60-65% | RSI extremes improve entry timing |
| Sharpe Ratio | 1.0 - 1.4 | Better risk management |

**Key Filters**:
- ADX ≤ 20.0 (ranging market confirmation)
- RSI < 30 (oversold) or RSI > 70 (overbought)
- Time-stop at 30 bars (2.5 hours max hold)
- RR ≥ 1.6 (minimum quality threshold)

---

### Scalper Strategy

| Metric | Expected Range | Why? |
|--------|----------------|------|
| Profit Factor | 1.15 - 1.25 | Spread filter avoids slippage |
| Max Drawdown | -7% to -10% | Throttling prevents overtrading |
| Win Rate | 62-68% | Latency filter ensures fast execution |
| Sharpe Ratio | 0.7 - 1.0 | Better execution quality |

**Key Filters**:
- Spread ≤ 3 bps (tight spread only)
- Latency ≤ 500ms (fast execution only)
- Throttle: max 3 trades/min (prevents overtrading)
- RR ≥ 1.0 (minimum quality for scalping)

---

## Success Criteria (STEP 6 Completion)

STEP 6 is **COMPLETE** if:

✅ **Profit Factor improves by ≥5% for at least 2/3 strategies**, OR
✅ **Max Drawdown decreases by ≥10% for at least 2/3 strategies**

---

## File Reference

### Core Implementation

- `strategies/utils.py` - Centralized utilities (680 lines)
- `strategies/momentum_strategy.py` - Enhanced momentum (+101 lines)
- `strategies/mean_reversion.py` - Enhanced mean reversion (+42 lines)
- `strategies/scalper.py` - Enhanced scalper (+63 lines)

### Tests

- `tests/strategies/test_utils.py` - Utils tests (560 lines, 33 tests)
- `tests/strategies/test_momentum_strategy.py` - Momentum tests (395 lines, 11 tests)
- `tests/strategies/test_mean_reversion_strategy.py` - Mean reversion tests (424 lines, 11 tests)
- `tests/strategies/test_scalper_strategy.py` - Scalper tests (412 lines, 17 tests)

### Backtest Infrastructure

- `scripts/run_step6_backtests.py` - Backtest runner (ready to execute)
- `out/STEP6_BACKTEST_EXECUTION_GUIDE.md` - Comprehensive execution guide
- `out/STEP6_STRATEGY_INTEGRATION_COMPLETE.md` - Integration documentation

---

## Verification Commands

### 1. Run All Tests

```bash
conda activate crypto-bot

# Run all strategy tests
pytest tests/strategies/test_utils.py -v
pytest tests/strategies/test_momentum_strategy.py -v
pytest tests/strategies/test_mean_reversion_strategy.py -v
pytest tests/strategies/test_scalper_strategy.py -v

# Or run all at once
pytest tests/strategies/ -v
```

**Expected**: All 72 tests pass ✅

---

### 2. Quick Smoke Test

```bash
# Quick 30-day backtest (2-3 minutes)
python scripts/run_step6_backtests.py --all --quick
```

**Expected**: Three strategies run without errors, results printed

---

### 3. Full Backtest

```bash
# Full 360-day backtest (5-10 minutes)
python scripts/run_step6_backtests.py --all
```

**Expected**:
- Results saved to `backtests/step6/*.json`
- Comparison table in `backtests/step6/step6_comparison.txt`
- All strategies show positive returns or controlled drawdowns

---

## Example Output

When you run the backtest, you'll see output like this:

```
======================================================================
BACKTEST: MOMENTUM
======================================================================
Strategy initialized: MomentumStrategy
Generating synthetic data: 2024-01-01 to 2024-12-26 (1h)
Generated 8760 bars
Running backtest on 8760 bars...

======================================================================
RESULTS: MOMENTUM
======================================================================
Total Trades:        142
Winning Trades:      76
Losing Trades:       66
Win Rate:            53.52%

Total Return:        $1,842.50
Total Return %:      18.43%
Final Equity:        $11,842.50

Profit Factor:       1.67
Max Drawdown:        -12.34%
Sharpe Ratio:        1.28

Avg Win:             $78.25
Avg Loss:            $45.12
======================================================================
```

Then a comparison table for all three strategies.

---

## Troubleshooting

### Issue: Tests Fail

```bash
# Re-run tests with verbose output
pytest tests/strategies/ -v --tb=short

# If specific test fails, run individually
pytest tests/strategies/test_momentum_strategy.py::TestMomentumADXConfirmation -v
```

### Issue: Import Errors

```bash
# Verify environment
conda activate crypto-bot
python -c "import strategies.utils; print('OK')"
```

### Issue: Backtest Script Not Found

```bash
# Check script exists
ls -lh scripts/run_step6_backtests.py

# Make executable (Linux/Mac)
chmod +x scripts/run_step6_backtests.py
```

### Issue: No Data Available

The script uses synthetic data by default. To use real data:

```bash
# Download historical data first
python scripts/download_historical_data.py \
  --symbol BTC/USD \
  --start-date 2024-01-01 \
  --end-date 2024-12-26 \
  --timeframes 1m,5m,1h

# Then run backtest
python scripts/run_step6_backtests.py --all --use-synthetic=False
```

---

## What Happens Next (After Backtest)

1. **Review Results**: Check that metrics meet success criteria
2. **Document Findings**: Record KPI improvements in `STEP6_BACKTEST_RESULTS.md`
3. **Validate Completion**: Confirm PF↑ or DD↓ for 2/3 strategies
4. **Proceed to STEP 7**: If successful, move to live paper trading validation
5. **Iterate if Needed**: If results don't meet criteria, tune parameters

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────┐
│ STEP 6 QUICK REFERENCE                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ✅ Status: ALL TESTS PASSING (72/72)                           │
│                                                                 │
│ 🚀 Next Command:                                                │
│    conda activate crypto-bot                                    │
│    python scripts/run_step6_backtests.py --all --quick          │
│                                                                 │
│ ⏱️  Runtime: 2-3 minutes (quick) | 5-10 minutes (full)         │
│                                                                 │
│ 📊 Expected: PF 1.2-1.8 | DD -7% to -15% | WR 50-68%           │
│                                                                 │
│ ✓ Completion Criteria: PF↑≥5% OR DD↓≥10% (2/3 strategies)      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Summary

**STEP 6 is ready to execute.** All code is written, tested, and documented. The backtest infrastructure is in place with:

1. ✅ **Utilities module** (680 lines, 33 tests passing)
2. ✅ **Enhanced strategies** (momentum, mean_reversion, scalper)
3. ✅ **Comprehensive tests** (72/72 passing in 4.79s)
4. ✅ **Backtest runner** (ready-to-execute script)
5. ✅ **Execution guide** (detailed instructions)

**Next Action**: Run the quick test to validate everything works, then execute the full 360-day backtest to measure KPI improvements.

```bash
# Let's go! 🚀
conda activate crypto-bot
python scripts/run_step6_backtests.py --all --quick
```

---

**Document Version**: 1.0
**Last Updated**: 2024-12-26
**Status**: ✅ READY TO EXECUTE
