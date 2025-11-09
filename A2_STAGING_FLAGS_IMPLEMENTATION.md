# A2 - Staging Flags Implementation

**Status**: ✅ Complete
**Test Coverage**: 20/20 tests passing
**Backward Compatibility**: ✅ Verified

---

## Summary

Implemented feature flag layer for staging stream and multi-pair support with **zero behavior change by default**. All existing code continues to work unchanged.

---

## New Environment Variables

### 1. PUBLISH_MODE

**Purpose**: High-level mode selector for stream routing

**Values**:
- `paper` (default) → `signals:paper`
- `staging` → `signals:paper:staging`
- `live` → `signals:live`

**Example**:
```bash
PUBLISH_MODE=staging
```

### 2. REDIS_STREAM_NAME

**Purpose**: Direct stream name override (highest priority)

**Value**: Any valid Redis stream key

**Example**:
```bash
REDIS_STREAM_NAME=signals:custom:test
```

### 3. EXTRA_PAIRS

**Purpose**: Additive pairs merged with TRADING_PAIRS

**Value**: CSV list of trading pairs

**Example**:
```bash
TRADING_PAIRS=BTC/USD,ETH/USD
EXTRA_PAIRS=SOL/USD,ADA/USD,AVAX/USD
# Result: BTC/USD,ETH/USD,SOL/USD,ADA/USD,AVAX/USD
```

---

## Priority Hierarchy

### Stream Selection

```
REDIS_STREAM_NAME (highest)
    ↓
PUBLISH_MODE
    ↓
STREAM_SIGNALS_PAPER (legacy)
    ↓
"signals:paper" (default)
```

### Pair Selection

```
TRADING_PAIRS (base, defaults to BTC/USD,ETH/USD)
    +
EXTRA_PAIRS (additive, optional)
    ↓
Merged & deduplicated list
```

---

## Code Changes

### File: `agents/core/signal_processor.py`

#### Change 1: New Method `_load_trading_pairs()`

**Lines**: 493-520

```python
def _load_trading_pairs(self) -> List[str]:
    """
    Load trading pairs with support for EXTRA_PAIRS.

    Priority:
    1. TRADING_PAIRS (base pairs) - defaults to BTC/USD,ETH/USD
    2. EXTRA_PAIRS (additive) - optional additional pairs

    Returns:
        List of unique trading pairs (deduplicated, order preserved)
    """
    # Load base pairs (default: BTC/USD,ETH/USD for backward compatibility)
    base_pairs_str = os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD")
    base_pairs = [p.strip() for p in base_pairs_str.split(",") if p.strip()]

    # Load extra pairs (additive)
    extra_pairs_str = os.getenv("EXTRA_PAIRS", "")
    extra_pairs = [p.strip() for p in extra_pairs_str.split(",") if p.strip()]

    # Merge and deduplicate (preserves order)
    all_pairs = base_pairs + extra_pairs
    unique_pairs = list(dict.fromkeys(all_pairs))

    self.logger.info(f"Trading pairs loaded: {', '.join(unique_pairs)}")
    if extra_pairs:
        self.logger.info(f"  Base pairs: {', '.join(base_pairs)}")
        self.logger.info(f"  Extra pairs: {', '.join(extra_pairs)}")

    return unique_pairs
```

#### Change 2: Stream Selection in `_load_config()`

**Lines**: 522-530

```python
# === FEATURE FLAG: Staging Stream Support ===
# Priority: REDIS_STREAM_NAME > PUBLISH_MODE > STREAM_SIGNALS_PAPER > default
publish_mode = os.getenv("PUBLISH_MODE", "paper")  # paper|staging|live
redis_stream_name = os.getenv("REDIS_STREAM_NAME")  # Optional direct override

if redis_stream_name:
    # Direct override takes highest priority
    processed_signals_stream = redis_stream_name
elif publish_mode == "staging":
    # Staging mode maps to staging stream
    processed_signals_stream = "signals:paper:staging"
elif publish_mode == "live":
    # Live mode maps to live stream
    processed_signals_stream = "signals:live"
else:
    # Default: fallback to STREAM_SIGNALS_PAPER or "signals:paper"
    processed_signals_stream = os.getenv("STREAM_SIGNALS_PAPER", "signals:paper")
```

#### Change 3: Use New Pair Loader

**Lines**: 544-545

```python
# Trading pairs and timeframes
# === FEATURE FLAG: Extra Pairs Support ===
# Merge TRADING_PAIRS (base) + EXTRA_PAIRS (additive)
"trading_pairs": self._load_trading_pairs(),
```

#### Change 4: SignalRouter Integration

**Lines**: 404-416

```python
# Stream mappings
# === FEATURE FLAG: Use same stream selection logic as SignalProcessor ===
publish_mode = os.getenv("PUBLISH_MODE", "paper")
redis_stream_name = os.getenv("REDIS_STREAM_NAME")

if redis_stream_name:
    default_stream = redis_stream_name
elif publish_mode == "staging":
    default_stream = "signals:paper:staging"
elif publish_mode == "live":
    default_stream = "signals:live"
else:
    default_stream = os.getenv("STREAM_SIGNALS_PAPER", "signals:paper")

self.execution_streams = {
    "scalp": "signals:scalp",
    "trend_following": "signals:trend",
    "sideways": "signals:sideways",
    "momentum": "signals:momentum",
    "breakout": "signals:breakout",
    "default": default_stream,
}
```

---

## Test Coverage

### File: `tests/test_staging_feature_flags.py`

**Total Tests**: 20
**Status**: ✅ All passing

### Test Classes

1. **TestPublishModeFlag** (4 tests)
   - Default mode (paper)
   - Explicit paper mode
   - Staging mode
   - Live mode

2. **TestRedisStreamNameOverride** (3 tests)
   - Direct override
   - Override takes priority over PUBLISH_MODE
   - Override takes priority over legacy var

3. **TestBackwardCompatibility** (2 tests)
   - Legacy STREAM_SIGNALS_PAPER still works
   - PUBLISH_MODE overrides legacy when both present

4. **TestExtraPairsFlag** (6 tests)
   - Default pairs
   - TRADING_PAIRS override
   - EXTRA_PAIRS additive merge
   - Deduplication
   - Extra pairs with default base
   - Whitespace handling

5. **TestFeatureFlagPriority** (2 tests)
   - Full priority chain with all 3 vars
   - Priority without direct override

6. **TestStagingConfiguration** (1 test)
   - Complete staging config (mode + pairs)

7. **TestSignalRouterIntegration** (2 tests)
   - Router respects PUBLISH_MODE
   - Router respects REDIS_STREAM_NAME

---

## Backward Compatibility

### ✅ No Breaking Changes

**Default Behavior** (no env vars set):
```python
# Stream: signals:paper (unchanged)
# Pairs: BTC/USD,ETH/USD (unchanged)
```

**Legacy Variables** (still work):
```bash
STREAM_SIGNALS_PAPER=signals:paper  # Still works
TRADING_PAIRS=BTC/USD,ETH/USD       # Still works
```

**New Variables** (optional):
```bash
PUBLISH_MODE=staging                    # New, optional
REDIS_STREAM_NAME=signals:custom        # New, optional
EXTRA_PAIRS=SOL/USD,ADA/USD            # New, optional
```

---

## Usage Examples

### Example 1: Default Production (No Changes)

```bash
# .env (unchanged)
REDIS_URL=rediss://...
# No PUBLISH_MODE, no EXTRA_PAIRS

# Result:
# Stream: signals:paper
# Pairs: BTC/USD, ETH/USD
```

### Example 2: Staging Mode

```bash
# .env.staging
REDIS_URL=rediss://...
PUBLISH_MODE=staging
EXTRA_PAIRS=SOL/USD,ADA/USD,AVAX/USD

# Result:
# Stream: signals:paper:staging
# Pairs: BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD
```

### Example 3: Direct Override

```bash
# .env.custom
REDIS_URL=rediss://...
REDIS_STREAM_NAME=signals:custom:test
TRADING_PAIRS=DOGE/USD,XRP/USD

# Result:
# Stream: signals:custom:test
# Pairs: DOGE/USD, XRP/USD
```

### Example 4: Legacy Compatibility

```bash
# .env.old (existing production config)
REDIS_URL=rediss://...
STREAM_SIGNALS_PAPER=signals:paper
TRADING_PAIRS=BTC/USD,ETH/USD

# Result: Exactly the same as before (100% backward compatible)
# Stream: signals:paper
# Pairs: BTC/USD, ETH/USD
```

---

## Diff Summary

**Files Modified**: 1
**Lines Changed**: ~60 lines (added)
**Lines Deleted**: 0
**Breaking Changes**: 0

```diff
agents/core/signal_processor.py:
+ 493-520: _load_trading_pairs() method
+ 522-530: Stream selection logic in _load_config()
+ 544-545: Use _load_trading_pairs()
+ 404-416: SignalRouter stream selection

tests/test_staging_feature_flags.py:
+ 1-264: Complete test suite (20 tests)
```

---

## Configuration Matrix

| REDIS_STREAM_NAME | PUBLISH_MODE | STREAM_SIGNALS_PAPER | Result Stream |
|-------------------|--------------|----------------------|---------------|
| (not set) | (not set) | (not set) | `signals:paper` |
| (not set) | paper | (not set) | `signals:paper` |
| (not set) | staging | (not set) | `signals:paper:staging` |
| (not set) | live | (not set) | `signals:live` |
| (not set) | (not set) | signals:custom | `signals:custom` |
| (not set) | staging | signals:custom | `signals:paper:staging` |
| signals:override | staging | signals:custom | `signals:override` |

---

## Logging Output

### With Default Config

```
INFO:agents.core.signal_processor:Trading pairs loaded: BTC/USD, ETH/USD
```

### With EXTRA_PAIRS

```
INFO:agents.core.signal_processor:Trading pairs loaded: BTC/USD, ETH/USD, SOL/USD, ADA/USD, AVAX/USD
INFO:agents.core.signal_processor:  Base pairs: BTC/USD, ETH/USD
INFO:agents.core.signal_processor:  Extra pairs: SOL/USD, ADA/USD, AVAX/USD
```

---

## Next Steps

### A3: Start Local Staging Publisher

Use the new flags in `.env.staging`:

```bash
PUBLISH_MODE=staging
TRADING_PAIRS=BTC/USD,ETH/USD
EXTRA_PAIRS=SOL/USD,ADA/USD,AVAX/USD
```

**Command**:
```bash
python run_staging_publisher.py
```

**Expected Stream**: `signals:paper:staging`
**Expected Pairs**: 5 pairs

---

## Rollback

If any issues found:

```bash
# Revert commits
git revert <commit-hash>

# Or use default config (zero impact)
# Just don't set PUBLISH_MODE or EXTRA_PAIRS
```

**Impact**: ZERO (defaults preserve existing behavior)

---

**Status**: ✅ A2 Complete
**Test Results**: 20/20 passing
**Recommendation**: Proceed to A3 (local staging publisher)
