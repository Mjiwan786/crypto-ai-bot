# Regime/Router Fix Summary - Unblock Real Trades

**Date**: 2025-10-26  
**Goal**: Allow strategies to run in sideways/chop instead of hard-blocking. Only block on risk breakers, not on "chop" alone.

## Changes Made

### 1. Regime Detector Threshold Adjustments (`ai_engine/regime_detector/detector.py`)

**Problem**: Over-labeling markets as "chop" due to aggressive thresholds

**Changes**:
- **ADX threshold**: `25.0 → 20.0` (line 71)
  - Lower threshold allows more markets to be classified as trending
  - 20% reduction makes trend detection less strict
  
- **Aroon thresholds**: `70.0 → 60.0` (lines 72-73)
  - Bull threshold: 70.0 → 60.0
  - Bear threshold: 70.0 → 60.0
  - 14% reduction makes directional classification easier
  
- **Aroon dominance gap**: `+20 → +10` (lines 369, 373)
  - Reduced from requiring 20-point lead to 10-point lead
  - Easier to classify as bull/bear vs chop

**Impact**: Significantly reduces false "chop" classifications, allowing more trending signals to generate.

### 2. Strategy Router Breaker Integration (`agents/strategy_router.py`)

**Problem**: No integration with risk manager breaker state; unclear when to block

**Changes**:

#### a) Config Updates
- Added `enable_risk_breaker_check: bool = True` to RouterConfig (line 67)
- Added `risk_manager` parameter to `__init__` (line 124)
- Added `_risk_breaker_rejections` metric counter (line 156)

#### b) New Method: `_is_risk_breaker_active()`
- Lines 295-321
- Checks if risk_manager.get_drawdown_state().mode == "hard_halt"
- Returns True only when breaker is active (drawdown exceeded critical threshold)
- Gracefully handles missing risk_manager (returns False)

#### c) Routing Logic Update
- Added breaker check BEFORE cooldown check (lines 440-444)
- Priority: kill_switch → risk_breaker → cooldown → spread → strategy routing
- Breaker blocks ALL regimes (bull/bear/chop) when active

#### d) Metrics Updates
- Added `risk_breaker_rejections` to get_metrics() (line 542)
- Added counter reset in reset_metrics() (line 558)

**Impact**: 
- Chop regime no longer blocks by default
- Only blocks when risk manager breaker is active (hard_halt mode)
- Clear separation of concerns: regime routing vs risk blocking

### 3. Test Coverage

#### a) `tests/test_router_chop_allows_range.py`
**Purpose**: Verify chop regime routes to mean_reversion strategy without blocking

**Tests**:
1. `test_chop_regime_routes_to_mean_reversion` - Verifies routing works
2. `test_chop_not_blocked_without_breaker` - Confirms chop doesn't block signals
3. `test_multiple_chop_bars_generate_signals` - Tests consecutive chop bars

**Result**: 3/3 tests passed ✓

#### b) `tests/test_breaker_blocks_all.py`
**Purpose**: Verify risk breaker blocks ALL entries regardless of regime

**Tests**:
1. `test_breaker_blocks_bull_regime` - Breaker blocks in bull market
2. `test_breaker_blocks_chop_regime` - Breaker blocks in chop market
3. `test_normal_mode_allows_entries` - Normal mode allows entries
4. `test_breaker_blocks_multiple_attempts` - Breaker blocks consecutive attempts

**Result**: 4/4 tests passed ✓

## Verification

```bash
# Test 1: Chop allows range
python -m pytest tests/test_router_chop_allows_range.py -v
# Result: 3 passed in 30.57s ✓

# Test 2: Breaker blocks all
python -m pytest tests/test_breaker_blocks_all.py -v
# Result: 4 passed in 5.59s ✓
```

## Diff Summary

| File | Lines Changed | Description |
|------|---------------|-------------|
| `ai_engine/regime_detector/detector.py` | 6 | Lower ADX (25→20), Aroon (70→60), dominance gap (20→10) |
| `agents/strategy_router.py` | 42 | Add risk_manager integration, breaker check, metrics |
| `tests/test_router_chop_allows_range.py` | 254 (new) | Test chop routing without blocking |
| `tests/test_breaker_blocks_all.py` | 413 (new) | Test breaker blocks all regimes |

**Total**: ~715 LOC (4 files modified/created)

## Before vs After

### Before (Broken)
1. ADX=25, Aroon=70 → Most markets labeled "chop"
2. Chop regime → No strategy mapping or signals blocked
3. No risk breaker integration → Unclear when to halt
4. **Result**: 0 trades generated, all signals suppressed

### After (Fixed)
1. ADX=20, Aroon=60, gap=10 → More markets labeled bull/bear
2. Chop regime → Routes to mean_reversion strategy
3. Risk breaker check → Only blocks when hard_halt active
4. **Result**: Trades generated unless breaker is active

## Next Steps

1. ✅ Monitor backtest with new thresholds
2. ✅ Verify real trades are generated in chop markets
3. ✅ Confirm breaker correctly halts on drawdown
4. Document regime distribution in production logs

## Key Insight

**The fundamental principle**: 
- **Regime detection** classifies market conditions (bull/bear/chop)
- **Strategy routing** maps regimes to appropriate strategies
- **Risk breakers** are the ONLY component that should block all entries
- Chop is NOT a failure state—it's a valid regime requiring different strategies (mean reversion, scalping)

**Previous bug**: Treated chop as a "block all trades" condition, violating the separation of concerns between regime classification and risk management.

**Fix**: Restored proper architecture where only risk breakers halt trading, not regime labels.
