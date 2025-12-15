# Week 2: Schema & Contract Alignment Report

**Date:** 2025-01-27  
**Status:** In Progress  
**Owner:** Senior Python Engineer + AI Architect + SRE

---

## Executive Summary

This document tracks the alignment between `crypto-ai-bot` (producer), `signals-api` (gateway), and `signals-site` (frontend) to ensure clean data flow without hacks.

**Goal:** Ensure `crypto-ai-bot` produces PRD-001 compliant data that `signals-api` and `signals-site` can consume without transformation.

---

## Schema Comparison Analysis

### PRD-001 (crypto-ai-bot) Signal Schema

```json
{
  "signal_id": "UUID v4",
  "timestamp": "ISO8601 UTC",
  "pair": "BTC/USD",
  "side": "LONG" | "SHORT",
  "strategy": "SCALPER" | "TREND" | "MEAN_REVERSION" | "BREAKOUT",
  "regime": "TRENDING_UP" | "TRENDING_DOWN" | "RANGING" | "VOLATILE",
  "entry_price": float,
  "take_profit": float,
  "stop_loss": float,
  "position_size_usd": float,
  "confidence": float (0.0-1.0),
  "risk_reward_ratio": float,
  "indicators": {
    "rsi_14": float,
    "macd_signal": "BULLISH" | "BEARISH" | "NEUTRAL",
    "atr_14": float,
    "volume_ratio": float
  },
  "metadata": {
    "model_version": string,
    "backtest_sharpe": float,
    "latency_ms": int
  }
}
```

### PRD-002 (signals-api) Expected Schema

```json
{
  "id": "sig_2025111412345678",
  "symbol": "BTCUSDT",
  "signal_type": "LONG" | "SHORT",
  "price": float,
  "timestamp": "ISO8601 UTC",
  "confidence": float (0.0-1.0),
  "stop_loss": float (optional),
  "take_profit": float (optional),
  "metadata": object (optional)
}
```

### Schema Mismatches Identified

| PRD-001 Field | PRD-002 Field | Status | Action Required |
|---------------|---------------|--------|-----------------|
| `signal_id` | `id` | ❌ Mismatch | Add `id` alias or mapping |
| `pair` | `symbol` | ❌ Mismatch | Add `symbol` (normalize BTC/USD → BTCUSDT) |
| `side` | `signal_type` | ❌ Mismatch | Add `signal_type` alias |
| `entry_price` | `price` | ❌ Mismatch | Add `price` alias |
| `strategy` | Not in API | ✅ OK | Keep for UI filtering |
| `regime` | Not in API | ✅ OK | Keep for UI display |
| `indicators` | Not in API | ✅ OK | Keep in metadata |
| `position_size_usd` | Not in API | ✅ OK | Keep for UI display |

---

## Resolution Strategy

### Option 1: Add API-Compatible Fields (Recommended)

**Approach:** Extend `PRDSignal` to include both PRD-001 and PRD-002 compatible fields.

**Pros:**
- No breaking changes to existing code
- API can consume directly
- UI gets all fields it needs
- Single source of truth maintained

**Cons:**
- Slightly larger payload (minimal impact)

**Implementation:**
- Add computed properties: `id`, `symbol`, `signal_type`, `price`
- These are derived from existing fields (no duplication of data)

### Option 2: API Transformation Layer

**Approach:** Keep PRD-001 schema, let API transform.

**Pros:**
- Bot stays pure PRD-001
- Single schema in bot

**Cons:**
- API needs transformation logic (hack)
- Risk of bugs in transformation
- Not aligned with Week 2 goal

---

## Recommended Implementation

### 1. Extend PRDSignal Model

Add computed properties for API compatibility:

```python
class PRDSignal(BaseModel):
    # ... existing fields ...
    
    @property
    def id(self) -> str:
        """API-compatible ID (alias for signal_id)"""
        return self.signal_id
    
    @property
    def symbol(self) -> str:
        """API-compatible symbol (BTC/USD → BTCUSDT)"""
        return self.pair.replace("/", "").replace("-USD", "USDT")
    
    @property
    def signal_type(self) -> str:
        """API-compatible signal type (alias for side)"""
        return str(self.side)
    
    @property
    def price(self) -> float:
        """API-compatible price (alias for entry_price)"""
        return self.entry_price
```

### 2. Update to_redis_dict() Method

Include both PRD-001 and API-compatible fields in Redis dict:

```python
def to_redis_dict(self) -> Dict[str, str]:
    """Convert to Redis-compatible dict with both PRD-001 and API fields"""
    data = self.model_dump(exclude_none=True)
    result = {}
    
    # Add PRD-001 fields
    for key, value in data.items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                result[f"{key}_{nested_key}"] = str(nested_value)
        else:
            result[key] = str(value)
    
    # Add API-compatible aliases
    result["id"] = self.id
    result["symbol"] = self.symbol
    result["signal_type"] = self.signal_type
    result["price"] = str(self.price)
    
    return result
```

### 3. Add UI-Friendly Metadata Fields

Add minimal metadata to simplify UI rendering:

```python
class PRDMetadata(BaseModel):
    """PRD-001 Metadata nested object"""
    model_version: str = Field(description="ML model version")
    backtest_sharpe: Optional[float] = Field(None, description="Backtest Sharpe ratio")
    latency_ms: Optional[int] = Field(None, ge=0, description="Processing latency in ms")
    
    # UI-friendly additions
    strategy_tag: Optional[str] = Field(None, description="Human-readable strategy tag")
    mode: Optional[str] = Field(None, description="Trading mode (paper/live)")
    timeframe: Optional[str] = Field(None, description="Signal timeframe (e.g., 5m, 15s)")
```

---

## PnL Schema Alignment

### PRD-001 PnL Schema

```json
{
  "timestamp": "ISO8601 UTC",
  "equity": float,
  "realized_pnl": float,
  "unrealized_pnl": float,
  "num_positions": int,
  "drawdown_pct": float
}
```

### PRD-002 Expected PnL Schema

```json
{
  "timestamp": "ISO8601 UTC",
  "total_pnl": float,
  "total_trades": int,
  "win_rate": float,
  "equity_curve": [
    {"timestamp": "...", "equity": float}
  ]
}
```

### PnL Mismatches

| PRD-001 Field | PRD-002 Field | Status | Action |
|---------------|---------------|--------|--------|
| `equity` | `equity_curve[].equity` | ✅ Compatible | API aggregates |
| `realized_pnl` | `total_pnl` (partial) | ⚠️ Partial | API calculates from signals |
| `num_positions` | Not in API | ✅ OK | Keep for internal use |
| `drawdown_pct` | Not in API | ✅ OK | Keep for internal use |

**Resolution:** PnL schema is compatible. API aggregates equity curve from stream. No changes needed.

---

## Stream Naming Verification

### PRD-001 Stream Names

- Signal streams: `signals:paper:<PAIR>` or `signals:live:<PAIR>`
- PnL streams: `pnl:paper:equity_curve` or `pnl:live:equity_curve`

### Current Implementation

✅ **Verified:** `agents/infrastructure/prd_publisher.py` uses correct stream names:
- `signal.get_stream_key("paper")` → `signals:paper:BTC-USD`
- `signal.get_stream_key("live")` → `signals:live:BTC-USD`
- PnL: `pnl:{mode}:equity_curve`

**Note:** Pair normalization converts `BTC/USD` → `BTC-USD` for Redis key safety. API should handle both formats.

---

## Action Items

### Phase 1: Schema Extensions (Priority: HIGH)

- [ ] Add `id`, `symbol`, `signal_type`, `price` properties to `PRDSignal`
- [ ] Update `to_redis_dict()` to include API-compatible fields
- [ ] Add `strategy_tag`, `mode`, `timeframe` to `PRDMetadata`
- [ ] Update tests to verify both PRD-001 and API fields present

### Phase 2: Validation & Testing (Priority: HIGH)

- [ ] Create integration test: bot publishes → API consumes → verify fields
- [ ] Verify API can parse signals without transformation
- [ ] Verify UI receives all required fields
- [ ] Test with real Redis Cloud connection

### Phase 3: Documentation (Priority: MEDIUM)

- [ ] Update PRD-001 to note API compatibility fields
- [ ] Document field mapping in API docs
- [ ] Create schema migration guide if needed

---

## Testing Checklist

### Signal Schema Test

```python
def test_signal_api_compatibility():
    """Verify signal includes both PRD-001 and API fields"""
    signal = PRDSignal(
        pair="BTC/USD",
        side="LONG",
        strategy="SCALPER",
        regime="TRENDING_UP",
        entry_price=50000.0,
        take_profit=52000.0,
        stop_loss=49000.0,
        confidence=0.85,
        position_size_usd=100.0,
    )
    
    redis_dict = signal.to_redis_dict()
    
    # PRD-001 fields
    assert "signal_id" in redis_dict
    assert "pair" in redis_dict
    assert "side" in redis_dict
    assert "entry_price" in redis_dict
    
    # API-compatible fields
    assert "id" in redis_dict
    assert "symbol" in redis_dict
    assert "signal_type" in redis_dict
    assert "price" in redis_dict
    
    # Verify values match
    assert redis_dict["id"] == redis_dict["signal_id"]
    assert redis_dict["symbol"] == "BTCUSDT"
    assert redis_dict["signal_type"] == "LONG"
    assert redis_dict["price"] == "50000.0"
```

### End-to-End Test

```python
async def test_e2e_signal_flow():
    """Test: bot publishes → API consumes → UI receives"""
    # 1. Bot publishes signal
    publisher = PRDPublisher(mode="paper")
    await publisher.connect()
    
    signal = create_prd_signal(...)
    entry_id = await publisher.publish_signal(signal)
    assert entry_id is not None
    
    # 2. API reads from Redis
    redis_client = await get_prd_redis_client()
    messages = await redis_client.xread(
        streams={"signals:paper:BTC-USD": "0"},
        count=1
    )
    
    # 3. Verify API can parse
    signal_data = messages[0][1][0][1]  # Extract fields
    assert "id" in signal_data
    assert "symbol" in signal_data
    assert "signal_type" in signal_data
    assert "price" in signal_data
```

---

## Success Criteria

✅ **Week 2 Complete When:**

1. All signals include both PRD-001 and API-compatible fields
2. API can consume signals without transformation
3. UI receives all required fields (pair, side, strategy, confidence, entry, SL/TP, timestamps)
4. Stream names match PRD-001 exactly
5. PnL data flows correctly
6. End-to-end test passes
7. No schema-related errors in API logs

---

## Notes

- **PRD-001 is authoritative** for bot schema
- **API compatibility fields are additions**, not replacements
- **No breaking changes** to existing code
- **Minimal payload increase** (< 5% overhead)
- **Future-proof** for API schema evolution

---

**Next Steps:** Implement Phase 1 schema extensions.


