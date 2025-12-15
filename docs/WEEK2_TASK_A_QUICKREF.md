# Week 2 Task A: Quick Reference Guide

**Canonical DTOs for Signal & PnL Publishing**

---

## Quick Start

### Create and Publish Signal

```python
from models.canonical_signal_dto import create_canonical_signal
import redis.asyncio as redis

# 1. Create signal
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

# 2. Get Redis payload
payload = signal.to_redis_payload()

# 3. Get stream key
stream_key = signal.get_stream_key("paper")  # "signals:paper:BTC-USD"

# 4. Publish to Redis
redis_client = await redis.from_url("rediss://...")
entry_id = await redis_client.xadd(stream_key, payload, maxlen=10000)
```

### Create and Publish PnL

```python
from models.canonical_pnl_dto import create_canonical_pnl
import redis.asyncio as redis

# 1. Create PnL update
pnl = create_canonical_pnl(
    equity=12500.0,
    realized_pnl=2500.0,
    unrealized_pnl=0.0,
    num_positions=0,
    mode="paper",
    initial_balance=10000.0,
    total_trades=142,
    win_rate=0.64,
)

# 2. Get Redis payload
payload = pnl.to_redis_payload()

# 3. Get stream key
stream_key = pnl.get_stream_key("paper")  # "pnl:paper:equity_curve"

# 4. Publish to Redis
redis_client = await redis.from_url("rediss://...")
entry_id = await redis_client.xadd(stream_key, payload, maxlen=50000)
```

---

## Field Reference

### Signal Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `signal_id` | UUID | Auto | PRD-001 canonical ID |
| `timestamp` | ISO8601 | Auto | PRD-001 timestamp |
| `pair` | str | ✅ | Trading pair (BTC/USD) |
| `side` | enum | ✅ | LONG or SHORT |
| `strategy` | enum | ✅ | SCALPER, TREND, etc. |
| `regime` | enum | ✅ | TRENDING_UP, RANGING, etc. |
| `entry_price` | float | ✅ | Entry price |
| `take_profit` | float | ✅ | Take profit |
| `stop_loss` | float | ✅ | Stop loss |
| `confidence` | float | ✅ | 0.0-1.0 |
| `position_size_usd` | float | ✅ | Max 2000 |
| `risk_reward_ratio` | float | Auto | Auto-calculated |
| `id` | UUID | Auto | API alias (PRD-002) |
| `symbol` | str | Auto | API alias (BTCUSDT) |
| `signal_type` | str | Auto | API alias (PRD-002) |
| `price` | float | Auto | API alias (PRD-002) |
| `strategy_label` | str | Auto | UI-friendly (PRD-003) |
| `timeframe` | str | Optional | UI filtering (PRD-003) |
| `mode` | str | Optional | UI display (PRD-003) |

### PnL Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `timestamp` | ISO8601 | Auto | PRD-001 timestamp |
| `equity` | float | ✅ | Current equity |
| `realized_pnl` | float | ✅ | Realized PnL |
| `unrealized_pnl` | float | ✅ | Unrealized PnL |
| `num_positions` | int | ✅ | Open positions |
| `drawdown_pct` | float | ✅ | Drawdown % |
| `total_pnl` | float | Auto | Auto-calculated (PRD-002) |
| `total_trades` | int | Optional | PRD-002 API field |
| `win_rate` | float | Optional | PRD-002 API field |
| `total_roi` | float | Auto | Auto-calculated (PRD-003) |
| `profit_factor` | float | Optional | PRD-003 UI field |
| `sharpe_ratio` | float | Optional | PRD-003 UI field |
| `max_drawdown` | float | Auto | Auto-calculated (PRD-003) |
| `mode` | str | Optional | UI display (PRD-003) |
| `initial_balance` | float | Optional | For ROI calculation |

---

## Stream Keys

### Signal Streams
- Paper: `signals:paper:<PAIR>` (e.g., `signals:paper:BTC-USD`)
- Live: `signals:live:<PAIR>` (e.g., `signals:live:BTC-USD`)

### PnL Streams
- Paper: `pnl:paper:equity_curve`
- Live: `pnl:live:equity_curve`

---

## Auto-Calculated Fields

### Signal
- `risk_reward_ratio`: (take_profit - entry_price) / (entry_price - stop_loss) for LONG
- `strategy_label`: Auto-generated from strategy enum

### PnL
- `total_pnl`: realized_pnl + unrealized_pnl
- `total_roi`: ((equity - initial_balance) / initial_balance) * 100 (if initial_balance provided)
- `max_drawdown`: abs(drawdown_pct)

---

## Validation Rules

### Signal
- LONG: take_profit > entry_price, stop_loss < entry_price
- SHORT: take_profit < entry_price, stop_loss > entry_price
- confidence: 0.0 ≤ confidence ≤ 1.0
- position_size_usd: 0 < position_size_usd ≤ 2000

### PnL
- equity: > 0
- num_positions: ≥ 0
- win_rate: 0.0 ≤ win_rate ≤ 1.0 (if provided)

---

## Testing

```bash
# Run tests
conda activate crypto-bot
pytest tests/unit/test_canonical_dtos.py -v

# Run with coverage
pytest tests/unit/test_canonical_dtos.py --cov=models.canonical_signal_dto --cov=models.canonical_pnl_dto
```

---

## Migration Guide

### For Existing Code

**Option 1: Continue using existing models (no changes needed)**
- `PRDSignal` and `PRDPnLUpdate` still work
- No breaking changes

**Option 2: Migrate to canonical DTOs (recommended for new code)**
- Replace `PRDSignal` → `CanonicalSignalDTO`
- Replace `PRDPnLUpdate` → `CanonicalPnLDTO`
- Use `to_redis_payload()` instead of `to_redis_dict()`

---

**See `docs/WEEK2_TASK_A_COMPLETE.md` for full documentation.**


