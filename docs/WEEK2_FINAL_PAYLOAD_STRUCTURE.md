# Week 2 Task A: Final Signal & PnL Payload Structure

**Authoritative Reference for signals-api and signals-site Integration**

---

## Signal Payload Structure

### Redis Stream Format

**Stream Name:** `signals:paper:<PAIR>` or `signals:live:<PAIR>`
- Example: `signals:paper:BTC-USD`, `signals:live:ETH-USD`

**Message Format:** All values are strings (encoded to bytes for XADD)

### Complete Field List

```json
{
  // =========================================================================
  // PRD-001 Canonical Fields (Bot Schema)
  // =========================================================================
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

  // =========================================================================
  // PRD-002 API-Compatible Aliases (signals-api expects these)
  // =========================================================================
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",  // alias for signal_id
  "symbol": "BTCUSDT",  // normalized from pair (BTC/USD → BTCUSDT)
  "signal_type": "LONG",  // alias for side
  "price": "50000.0",  // alias for entry_price

  // =========================================================================
  // PRD-001 Optional Indicators (flattened)
  // =========================================================================
  "rsi_14": "58.3",
  "macd_signal": "BULLISH",
  "atr_14": "425.80",
  "volume_ratio": "1.23",

  // =========================================================================
  // PRD-001 Optional Metadata (flattened)
  // =========================================================================
  "model_version": "v2.1.0",
  "backtest_sharpe": "1.85",
  "latency_ms": "127",

  // =========================================================================
  // PRD-003 UI-Friendly Fields (signals-site expects these)
  // =========================================================================
  "strategy_label": "Scalper",  // Human-readable (auto-generated)
  "timeframe": "5m",  // UI filtering (e.g., "5m", "15s", "1h")
  "mode": "paper"  // UI display ("paper" or "live")
}
```

### Example: Complete Signal Payload

```json
{
  "signal_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2025-01-27T12:34:56.789Z",
  "pair": "BTC/USD",
  "symbol": "BTCUSDT",
  "side": "LONG",
  "signal_type": "LONG",
  "strategy": "SCALPER",
  "strategy_label": "Scalper",
  "regime": "TRENDING_UP",
  "entry_price": "50000.0",
  "price": "50000.0",
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
  "timeframe": "5m",
  "mode": "paper"
}
```

---

## PnL Payload Structure

### Redis Stream Format

**Stream Name:** `pnl:paper:equity_curve` or `pnl:live:equity_curve`

**Message Format:** All values are strings (encoded to bytes for XADD)

### Complete Field List

```json
{
  // =========================================================================
  // PRD-001 Canonical Fields (Bot Schema)
  // =========================================================================
  "timestamp": "2025-01-27T12:34:56.789Z",
  "equity": "12500.0",
  "realized_pnl": "2500.0",
  "unrealized_pnl": "0.0",
  "num_positions": "0",
  "drawdown_pct": "-2.5",

  // =========================================================================
  // PRD-002 API-Compatible Fields (signals-api expects these)
  // =========================================================================
  "total_pnl": "2500.0",  // Auto-calculated: realized + unrealized
  "total_trades": "142",
  "win_rate": "0.64",

  // =========================================================================
  // PRD-003 UI-Friendly Fields (signals-site expects these)
  // =========================================================================
  "total_roi": "25.0",  // Auto-calculated if initial_balance provided
  "profit_factor": "1.85",
  "sharpe_ratio": "1.92",
  "max_drawdown": "2.5",  // Auto-calculated: abs(drawdown_pct)
  "mode": "paper",
  "initial_balance": "10000.0"
}
```

### Example: Complete PnL Payload

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

---

## Field Naming Conventions

### Signal Fields

| Field Name | PRD Source | Purpose | Example |
|------------|------------|---------|---------|
| `signal_id` | PRD-001 | Canonical ID | UUID v4 |
| `id` | PRD-002 | API alias | Same as signal_id |
| `pair` | PRD-001 | Trading pair | "BTC/USD" |
| `symbol` | PRD-002 | API format | "BTCUSDT" |
| `side` | PRD-001 | Trade direction | "LONG" |
| `signal_type` | PRD-002 | API alias | "LONG" |
| `entry_price` | PRD-001 | Entry price | 50000.0 |
| `price` | PRD-002 | API alias | 50000.0 |
| `strategy` | PRD-001 | Strategy enum | "SCALPER" |
| `strategy_label` | PRD-003 | UI display | "Scalper" |
| `timeframe` | PRD-003 | UI filtering | "5m" |
| `mode` | PRD-003 | UI display | "paper" |

### PnL Fields

| Field Name | PRD Source | Purpose | Example |
|------------|------------|---------|---------|
| `equity` | PRD-001 | Current equity | 12500.0 |
| `realized_pnl` | PRD-001 | Realized PnL | 2500.0 |
| `unrealized_pnl` | PRD-001 | Unrealized PnL | 0.0 |
| `total_pnl` | PRD-002 | Total PnL | 2500.0 |
| `total_roi` | PRD-003 | ROI % | 25.0 |
| `win_rate` | PRD-002 | Win rate | 0.64 |
| `profit_factor` | PRD-003 | Profit factor | 1.85 |
| `sharpe_ratio` | PRD-003 | Sharpe ratio | 1.92 |
| `max_drawdown` | PRD-003 | Max drawdown % | 2.5 |
| `mode` | PRD-003 | Trading mode | "paper" |

---

## signals-api Integration

### Expected Signal Fields (PRD-002)

```python
# signals-api can consume these fields directly:
{
    "id": "...",           # ✅ Present (alias for signal_id)
    "symbol": "...",       # ✅ Present (normalized: BTCUSDT)
    "signal_type": "...",  # ✅ Present (alias for side)
    "price": "...",        # ✅ Present (alias for entry_price)
    "timestamp": "...",   # ✅ Present
    "confidence": "...",  # ✅ Present
    "stop_loss": "...",   # ✅ Present
    "take_profit": "..."  # ✅ Present
}
```

**Result:** ✅ **No transformation needed in signals-api**

### Expected PnL Fields (PRD-002)

```python
# signals-api can consume these fields directly:
{
    "timestamp": "...",
    "equity": "...",
    "total_pnl": "...",    # ✅ Present (auto-calculated)
    "total_trades": "...", # ✅ Present
    "win_rate": "..."      # ✅ Present
}
```

**Result:** ✅ **No transformation needed in signals-api**

---

## signals-site Integration

### Expected Signal Fields (PRD-003)

```typescript
// signals-site can consume these fields directly:
interface Signal {
    pair: string;          // ✅ Present
    side: string;          // ✅ Present (LONG/SHORT)
    strategy: string;      // ✅ Present
    strategy_label: string; // ✅ Present (UI-friendly)
    confidence: number;    // ✅ Present
    entry_price: number;   // ✅ Present
    stop_loss: number;     // ✅ Present
    take_profit: number;   // ✅ Present
    timestamp: string;     // ✅ Present
    timeframe: string;     // ✅ Present (UI filtering)
    mode: string;          // ✅ Present (paper/live)
}
```

**Result:** ✅ **No client-side transformations needed**

### Expected PnL Fields (PRD-003)

```typescript
// signals-site can consume these fields directly:
interface PnLMetrics {
    equity: number;         // ✅ Present
    totalPnL: number;       // ✅ Present (as total_pnl)
    totalROI: number;      // ✅ Present (as total_roi)
    winRate: number;       // ✅ Present (as win_rate)
    profitFactor: number;  // ✅ Present (as profit_factor)
    sharpeRatio: number;   // ✅ Present (as sharpe_ratio)
    maxDrawdown: number;   // ✅ Present (as max_drawdown)
    mode: string;          // ✅ Present
}
```

**Result:** ✅ **No client-side calculations needed**

---

## Breaking Changes Summary

### ✅ **ZERO BREAKING CHANGES**

**Rationale:**
- Existing `PRDSignal` and `PRDPnLUpdate` models remain unchanged
- Canonical DTOs are **additions**, not replacements
- All existing code continues to work
- New code can opt-in to canonical DTOs

**Migration:**
- **Optional** - Existing code can continue using current models
- **Recommended** - New code should use canonical DTOs for full compatibility

---

## Usage in Code

### Publishing Signal

```python
from models.canonical_signal_dto import create_canonical_signal

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
)

# Get Redis payload (ready for XADD)
payload = signal.to_redis_payload()

# Publish
stream_key = signal.get_stream_key("paper")
await redis_client.xadd(stream_key, payload, maxlen=10000)
```

### Publishing PnL

```python
from models.canonical_pnl_dto import create_canonical_pnl

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
payload = pnl.to_redis_payload()

# Publish
stream_key = pnl.get_stream_key("paper")
await redis_client.xadd(stream_key, payload, maxlen=50000)
```

---

## Verification Checklist

### For signals-api Team

- [ ] Verify `id` field present (not just `signal_id`)
- [ ] Verify `symbol` field present (normalized format: BTCUSDT)
- [ ] Verify `signal_type` field present (not just `side`)
- [ ] Verify `price` field present (not just `entry_price`)
- [ ] Verify PnL includes `total_pnl`, `total_trades`, `win_rate`
- [ ] Test consuming signals without field mapping
- [ ] Update API documentation to reflect dual field names

### For signals-site Team

- [ ] Verify `strategy_label` present (human-readable)
- [ ] Verify `timeframe` present (for UI filtering)
- [ ] Verify `mode` present (for UI display)
- [ ] Verify PnL includes `total_roi`, `profit_factor`, `sharpe_ratio`, `max_drawdown`
- [ ] Test displaying signals without client-side transformations
- [ ] Test displaying PnL metrics without client-side calculations

---

## Files Reference

- **Canonical DTOs:** `models/canonical_signal_dto.py`, `models/canonical_pnl_dto.py`
- **Tests:** `tests/unit/test_canonical_dtos.py`
- **Documentation:** `docs/WEEK2_TASK_A_COMPLETE.md`
- **Quick Reference:** `docs/WEEK2_TASK_A_QUICKREF.md`

---

**Status:** ✅ **COMPLETE - Ready for Integration**


