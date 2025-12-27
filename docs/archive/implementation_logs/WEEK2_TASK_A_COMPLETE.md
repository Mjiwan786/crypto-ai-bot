# Week 2 Task A: Signal & PnL Schema Alignment - COMPLETE ✅

**Date:** 2025-01-27  
**Status:** ✅ Implementation Complete  
**Owner:** Senior Python Engineer + AI Architect + SRE

---

## Executive Summary

Week 2 Task A has been completed. Canonical `SignalDTO` and `PnlDTO` models have been created that unify PRD-001 (crypto-ai-bot), PRD-002 (signals-api), and PRD-003 (signals-site) requirements. These DTOs are the **single source of truth** for all Redis Stream publishing operations.

**Key Achievement:** Zero breaking changes - all existing code continues to work, while new canonical DTOs provide complete API and UI compatibility.

---

## Deliverables

### 1. Canonical Signal DTO (`models/canonical_signal_dto.py`)

**Purpose:** Unified signal model combining PRD-001, PRD-002, and PRD-003 requirements.

**Key Features:**
- ✅ PRD-001 canonical fields (signal_id, pair, side, strategy, regime, entry_price, etc.)
- ✅ PRD-002 API-compatible aliases (id, symbol, signal_type, price)
- ✅ PRD-003 UI-friendly fields (strategy_label, timeframe, mode)
- ✅ Auto-calculation of risk_reward_ratio
- ✅ Auto-generation of strategy_label
- ✅ `to_redis_payload()` method returns flat dict ready for XADD

### 2. Canonical PnL DTO (`models/canonical_pnl_dto.py`)

**Purpose:** Unified PnL model combining PRD-001, PRD-002, and PRD-003 requirements.

**Key Features:**
- ✅ PRD-001 canonical fields (timestamp, equity, realized_pnl, unrealized_pnl, num_positions, drawdown_pct)
- ✅ PRD-002 API-compatible fields (total_pnl, total_trades, win_rate)
- ✅ PRD-003 UI-friendly fields (total_roi, profit_factor, sharpe_ratio, max_drawdown)
- ✅ Auto-calculation of total_pnl, total_roi, max_drawdown
- ✅ `to_redis_payload()` method returns flat dict ready for XADD

### 3. Comprehensive Test Suite (`tests/unit/test_canonical_dtos.py`)

**Coverage:**
- ✅ PRD-001 field validation
- ✅ PRD-002 API compatibility
- ✅ PRD-003 UI field presence
- ✅ Redis payload format verification
- ✅ Auto-calculation logic
- ✅ Stream key generation

---

## Final Signal Payload Structure

### Complete Field List

**PRD-001 Canonical Fields:**
- `signal_id` (UUID v4)
- `timestamp` (ISO8601 UTC)
- `pair` (e.g., "BTC/USD")
- `side` ("LONG" or "SHORT")
- `strategy` ("SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT")
- `regime` ("TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE")
- `entry_price` (float)
- `take_profit` (float)
- `stop_loss` (float)
- `confidence` (float, 0.0-1.0)
- `position_size_usd` (float, max 2000)
- `risk_reward_ratio` (float, auto-calculated)

**PRD-002 API-Compatible Aliases:**
- `id` (alias for signal_id)
- `symbol` (normalized: BTC/USD → BTCUSDT)
- `signal_type` (alias for side)
- `price` (alias for entry_price)

**PRD-001 Optional Indicators:**
- `rsi_14` (float, 0-100)
- `macd_signal` ("BULLISH", "BEARISH", "NEUTRAL")
- `atr_14` (float)
- `volume_ratio` (float)

**PRD-001 Optional Metadata:**
- `model_version` (string)
- `backtest_sharpe` (float)
- `latency_ms` (int)

**PRD-003 UI-Friendly Fields:**
- `strategy_label` (string, e.g., "Scalper v2")
- `timeframe` (string, e.g., "5m", "15s", "1h")
- `mode` ("paper" or "live")

### Sample Signal JSON

```json
{
  "signal_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2025-01-27T12:34:56.789Z",
  "pair": "BTC/USD",
  "side": "LONG",
  "strategy": "SCALPER",
  "regime": "TRENDING_UP",
  "entry_price": "50000.0",
  "take_profit": "52000.0",
  "stop_loss": "49000.0",
  "confidence": "0.85",
  "position_size_usd": "100.0",
  "risk_reward_ratio": "2.0",
  "rsi_14": "58.3",
  "macd_signal": "BULLISH",
  "atr_14": "425.80",
  "volume_ratio": "1.23",
  "model_version": "v2.1.0",
  "backtest_sharpe": "1.85",
  "latency_ms": "127",
  "strategy_label": "Scalper",
  "timeframe": "5m",
  "mode": "paper",
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "symbol": "BTCUSDT",
  "signal_type": "LONG",
  "price": "50000.0"
}
```

**Note:** In Redis Streams, all values are strings (encoded to bytes for XADD). The JSON above shows the decoded representation.

---

## Final PnL Payload Structure

### Complete Field List

**PRD-001 Canonical Fields:**
- `timestamp` (ISO8601 UTC)
- `equity` (float)
- `realized_pnl` (float)
- `unrealized_pnl` (float)
- `num_positions` (int)
- `drawdown_pct` (float)

**PRD-002 API-Compatible Fields:**
- `total_pnl` (float, auto-calculated: realized + unrealized)
- `total_trades` (int)
- `win_rate` (float, 0.0-1.0)

**PRD-003 UI-Friendly Fields:**
- `total_roi` (float, percentage, auto-calculated if initial_balance provided)
- `profit_factor` (float)
- `sharpe_ratio` (float)
- `max_drawdown` (float, auto-calculated: abs(drawdown_pct))
- `mode` ("paper" or "live")
- `initial_balance` (float, for ROI calculation)

### Sample PnL JSON

```json
{
  "timestamp": "2025-01-27T12:34:56.789Z",
  "equity": "12500.0",
  "realized_pnl": "2500.0",
  "unrealized_pnl": "0.0",
  "num_positions": "0",
  "drawdown_pct": "-2.5",
  "total_pnl": "2500.0",
  "total_trades": "142",
  "win_rate": "0.64",
  "total_roi": "25.0",
  "profit_factor": "1.85",
  "sharpe_ratio": "1.92",
  "max_drawdown": "2.5",
  "mode": "paper",
  "initial_balance": "10000.0"
}
```

**Note:** In Redis Streams, all values are strings (encoded to bytes for XADD). The JSON above shows the decoded representation.

---

## Usage Examples

### Creating and Publishing a Signal

```python
from models.canonical_signal_dto import create_canonical_signal
import redis.asyncio as redis

# Create signal
signal = create_canonical_signal(
    pair="BTC/USD",
    side="LONG",
    strategy="SCALPER",
    entry_price=50000.0,
    take_profit=52000.0,
    stop_loss=49000.0,
    confidence=0.85,
    mode="paper",
    timeframe="5m",
    rsi_14=58.3,
    macd_signal="BULLISH",
    atr_14=425.80,
    volume_ratio=1.23,
)

# Get Redis payload (ready for XADD)
redis_payload = signal.to_redis_payload()

# Get stream key
stream_key = signal.get_stream_key("paper")  # "signals:paper:BTC-USD"

# Publish to Redis
redis_client = await redis.from_url("rediss://...")
entry_id = await redis_client.xadd(
    stream_key,
    redis_payload,
    maxlen=10000,
    approximate=True,
)
```

### Creating and Publishing PnL

```python
from models.canonical_pnl_dto import create_canonical_pnl
import redis.asyncio as redis

# Create PnL update
pnl = create_canonical_pnl(
    equity=12500.0,
    realized_pnl=2500.0,
    unrealized_pnl=0.0,
    num_positions=0,
    mode="paper",
    initial_balance=10000.0,
    total_trades=142,
    win_rate=0.64,
    profit_factor=1.85,
    sharpe_ratio=1.92,
)

# Get Redis payload (ready for XADD)
redis_payload = pnl.to_redis_payload()

# Get stream key
stream_key = pnl.get_stream_key("paper")  # "pnl:paper:equity_curve"

# Publish to Redis
redis_client = await redis.from_url("rediss://...")
entry_id = await redis_client.xadd(
    stream_key,
    redis_payload,
    maxlen=50000,
    approximate=True,
)
```

---

## Breaking Changes

### ✅ **NONE - Zero Breaking Changes**

**Rationale:**
- Existing `PRDSignal` and `PRDPnLUpdate` models remain unchanged
- Canonical DTOs are **additions**, not replacements
- All existing code continues to work
- New code can opt-in to canonical DTOs for enhanced compatibility

**Migration Path (Optional):**
- Existing code using `PRDSignal` → Continue using it (no changes needed)
- New code → Use `CanonicalSignalDTO` for full API/UI compatibility
- Gradual migration → Update publishers one at a time

---

## Field Mapping Reference

### Signal Field Mapping

| PRD-001 (Bot) | PRD-002 (API) | PRD-003 (UI) | Canonical DTO |
|---------------|---------------|--------------|---------------|
| `signal_id` | `id` | - | ✅ Both included |
| `pair` | `symbol` | - | ✅ Both included (symbol normalized) |
| `side` | `signal_type` | - | ✅ Both included |
| `entry_price` | `price` | - | ✅ Both included |
| `strategy` | - | `strategy_label` | ✅ Both included |
| - | - | `timeframe` | ✅ Added |
| - | - | `mode` | ✅ Added |
| `confidence` | `confidence` | `confidence` | ✅ Single field |
| `risk_reward_ratio` | - | - | ✅ Auto-calculated |

### PnL Field Mapping

| PRD-001 (Bot) | PRD-002 (API) | PRD-003 (UI) | Canonical DTO |
|---------------|---------------|--------------|---------------|
| `equity` | - | `equity` | ✅ Single field |
| `realized_pnl` | - | - | ✅ Included |
| `unrealized_pnl` | - | - | ✅ Included |
| - | `total_pnl` | `totalPnL` | ✅ Auto-calculated |
| - | `total_trades` | - | ✅ Added |
| - | `win_rate` | `winRate` | ✅ Added |
| `drawdown_pct` | - | `maxDrawdown` | ✅ Both included |
| - | - | `totalROI` | ✅ Auto-calculated |
| - | - | `profitFactor` | ✅ Added |
| - | - | `sharpeRatio` | ✅ Added |
| - | - | `mode` | ✅ Added |

---

## Stream Naming Verification

### ✅ **Verified: Stream names match PRD-001 exactly**

**Signal Streams:**
- Paper: `signals:paper:<PAIR>` (e.g., `signals:paper:BTC-USD`)
- Live: `signals:live:<PAIR>` (e.g., `signals:live:BTC-USD`)

**PnL Streams:**
- Paper: `pnl:paper:equity_curve`
- Live: `pnl:live:equity_curve`

**Implementation:**
```python
# Signal stream key
signal.get_stream_key("paper")  # "signals:paper:BTC-USD"

# PnL stream key
pnl.get_stream_key("paper")  # "pnl:paper:equity_curve"
```

---

## Testing Results

### Unit Tests

**File:** `tests/unit/test_canonical_dtos.py`

**Coverage:**
- ✅ 15+ test cases for SignalDTO
- ✅ 10+ test cases for PnlDTO
- ✅ Integration tests for API compatibility
- ✅ Redis payload format verification

**Run Tests:**
```bash
conda activate crypto-bot
pytest tests/unit/test_canonical_dtos.py -v
```

### Test Results Summary

| Test Category | Status | Notes |
|---------------|--------|-------|
| PRD-001 field validation | ✅ PASS | All canonical fields present |
| PRD-002 API compatibility | ✅ PASS | All API aliases present and correct |
| PRD-003 UI fields | ✅ PASS | All UI-friendly fields present |
| Redis payload format | ✅ PASS | All values encoded to bytes |
| Auto-calculation | ✅ PASS | risk_reward_ratio, total_pnl, total_roi calculated correctly |
| Stream key generation | ✅ PASS | Matches PRD-001 exactly |
| Field validation | ✅ PASS | Invalid signals rejected correctly |

---

## Integration with Existing Code

### Option 1: Use Canonical DTOs Directly (Recommended for New Code)

```python
from models.canonical_signal_dto import create_canonical_signal
from models.canonical_pnl_dto import create_canonical_pnl

# Create and publish signal
signal = create_canonical_signal(...)
payload = signal.to_redis_payload()
await redis_client.xadd(signal.get_stream_key("paper"), payload, maxlen=10000)
```

### Option 2: Adapter Pattern (For Existing Code)

```python
from models.canonical_signal_dto import CanonicalSignalDTO
from agents.infrastructure.prd_publisher import PRDSignal

# Convert existing PRDSignal to CanonicalSignalDTO
def adapt_prd_to_canonical(prd_signal: PRDSignal) -> CanonicalSignalDTO:
    return CanonicalSignalDTO(
        signal_id=prd_signal.signal_id,
        timestamp=prd_signal.timestamp,
        pair=prd_signal.pair,
        side=prd_signal.side,
        strategy=prd_signal.strategy,
        regime=prd_signal.regime,
        entry_price=prd_signal.entry_price,
        take_profit=prd_signal.take_profit,
        stop_loss=prd_signal.stop_loss,
        confidence=prd_signal.confidence,
        position_size_usd=prd_signal.position_size_usd,
        risk_reward_ratio=prd_signal.risk_reward_ratio,
        rsi_14=prd_signal.indicators.rsi_14 if prd_signal.indicators else None,
        macd_signal=prd_signal.indicators.macd_signal if prd_signal.indicators else None,
        atr_14=prd_signal.indicators.atr_14 if prd_signal.indicators else None,
        volume_ratio=prd_signal.indicators.volume_ratio if prd_signal.indicators else None,
        model_version=prd_signal.metadata.model_version if prd_signal.metadata else None,
        backtest_sharpe=prd_signal.metadata.backtest_sharpe if prd_signal.metadata else None,
        latency_ms=prd_signal.metadata.latency_ms if prd_signal.metadata else None,
        timeframe=prd_signal.metadata.timeframe if prd_signal.metadata else None,
        mode=prd_signal.metadata.mode if prd_signal.metadata else None,
    )
```

---

## API Compatibility Matrix

### signals-api Consumption

**PRD-002 Expected Fields:**
- ✅ `id` → Present (alias for signal_id)
- ✅ `symbol` → Present (normalized: BTC/USD → BTCUSDT)
- ✅ `signal_type` → Present (alias for side)
- ✅ `price` → Present (alias for entry_price)
- ✅ `timestamp` → Present
- ✅ `confidence` → Present
- ✅ `stop_loss` → Present
- ✅ `take_profit` → Present

**Result:** ✅ **signals-api can consume signals without transformation**

### signals-site Consumption

**PRD-003 Expected Fields:**
- ✅ `pair` / `symbol` → Present
- ✅ `side` / `signal_type` → Present
- ✅ `strategy` / `strategy_label` → Present
- ✅ `confidence` → Present
- ✅ `entry_price` / `price` → Present
- ✅ `stop_loss` → Present
- ✅ `take_profit` → Present
- ✅ `timestamp` → Present
- ✅ `timeframe` → Present (UI filtering)
- ✅ `mode` → Present (UI display)

**PnL Fields:**
- ✅ `equity` → Present
- ✅ `total_pnl` → Present (auto-calculated)
- ✅ `total_roi` → Present (auto-calculated)
- ✅ `win_rate` → Present
- ✅ `profit_factor` → Present
- ✅ `sharpe_ratio` → Present
- ✅ `max_drawdown` → Present (auto-calculated)
- ✅ `mode` → Present

**Result:** ✅ **signals-site can display all metrics without client-side calculations**

---

## Next Steps for signals-api (Week 2)

### Required Updates

**None - No Breaking Changes Required**

The canonical DTOs include all API-compatible fields, so `signals-api` can consume signals directly without modification.

### Optional Enhancements

1. **Field Mapping Removal:** If `signals-api` currently has field mapping logic, it can be removed (fields are already in API format).

2. **Schema Validation:** Update `signals-api` Pydantic models to accept both PRD-001 and API-compatible field names (for backward compatibility during migration).

3. **Documentation:** Update API docs to reflect that signals include both field naming conventions.

---

## Files Created/Modified

### New Files

1. **`models/canonical_signal_dto.py`** (450+ lines)
   - CanonicalSignalDTO class
   - Convenience functions
   - Auto-calculation logic

2. **`models/canonical_pnl_dto.py`** (250+ lines)
   - CanonicalPnLDTO class
   - Convenience functions
   - Auto-calculation logic

3. **`tests/unit/test_canonical_dtos.py`** (400+ lines)
   - Comprehensive test suite
   - API compatibility tests
   - UI field presence tests

4. **`docs/WEEK2_TASK_A_COMPLETE.md`** (this file)
   - Complete documentation
   - Usage examples
   - Field mapping reference

### Modified Files

**None** - All changes are additive (no breaking changes)

---

## Success Criteria - All Met ✅

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Single canonical SignalDTO | ✅ | `models/canonical_signal_dto.py` |
| Single canonical PnlDTO | ✅ | `models/canonical_pnl_dto.py` |
| PRD-001 compliant | ✅ | All PRD-001 fields present |
| PRD-002 API compatible | ✅ | All API aliases present |
| PRD-003 UI fields | ✅ | All UI-friendly fields present |
| `to_redis_payload()` method | ✅ | Returns flat dict with bytes values |
| Consistent usage | ✅ | Ready for adoption |
| Comprehensive tests | ✅ | 25+ test cases |
| Zero breaking changes | ✅ | Existing code unchanged |
| Documentation complete | ✅ | This document + inline docs |

---

## Summary

Week 2 Task A is **COMPLETE**. The canonical DTOs provide:

1. ✅ **Full PRD Compliance** - All PRD-001, PRD-002, and PRD-003 requirements met
2. ✅ **API Compatibility** - signals-api can consume without transformation
3. ✅ **UI Readiness** - signals-site receives all required fields
4. ✅ **Zero Breaking Changes** - Existing code continues to work
5. ✅ **Production Ready** - Comprehensive tests and documentation

**Next:** Integration testing with real Redis Cloud and API verification.

---

**Status:** ✅ **READY FOR INTEGRATION TESTING**


