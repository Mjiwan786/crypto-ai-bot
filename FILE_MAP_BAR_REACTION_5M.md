# File Map: bar_reaction_5m Strategy Implementation

## Overview
Implementation plan for the `bar_reaction_5m` strategy with precise 5-minute bar-close triggers, optional intra-bar probes, and maker-only execution with microstructure guards.

**Environment**: conda env `crypto-bot`, Python 3.10.18
**Redis**: TLS connection to Redis Cloud (redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818)
**Reference**: `PRD_AGENTIC.md`

---

## Files to Create/Modify

### 1. Configuration Layer

#### `config/enhanced_scalper_config.yaml` ✅ EXISTS
**Status**: Needs update
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\enhanced_scalper_config.yaml`
**Action**: Add `bar_reaction_5m` strategy configuration block

**New Configuration Block**:
```yaml
# Bar Reaction 5m Strategy (precise bar-close entries)
bar_reaction_5m:
  pairs: ["BTC/USD", "ETH/USD", "ADA/USD", "SOL/USD"]
  timeframe: "5m"                    # Precise 5-minute bars

  # Bar-close trigger settings
  bar_close_trigger:
    enabled: true
    alignment_tolerance_ms: 100      # Allow 100ms tolerance for bar boundaries
    require_full_bar: true            # Only trigger on completed bars

  # Optional intra-bar probes (disabled by default)
  intra_bar_probes:
    enabled: false                    # Set to true for microreactor_5m
    probe_interval_s: 30              # Probe every 30s within bar
    max_probes_per_bar: 9             # Max 9 probes (every 30s in 5m bar)

  # Technical indicators (calculated on bar close)
  indicators:
    ema_fast: 8
    ema_slow: 21
    atr_period: 14
    rsi_period: 14
    volume_ema: 20

  # Entry conditions
  entry_conditions:
    min_ema_separation_pct: 0.002    # 0.2% min EMA separation
    min_volume_ratio: 1.2            # Volume must be 1.2x the EMA
    max_atr_pct: 0.012               # 1.2% max ATR (avoid volatile conditions)
    min_atr_pct: 0.004               # 0.4% min ATR (avoid dead markets)
    rsi_range: [35, 65]              # RSI must be in moderate range

  # Risk management
  risk:
    target_rr: 2.0                   # 2:1 risk-reward ratio
    sl_atr_multiple: 1.5             # Stop loss at 1.5x ATR
    tp_atr_multiple: 3.0             # Take profit at 3x ATR
    max_hold_bars: 12                # Max 12 bars (1 hour)

  # Execution settings (maker-only)
  execution:
    order_type: "limit"
    post_only: true                  # Maker-only (earn rebates)
    max_spread_bps: 5.0              # Max 5bps spread for entry
    min_liquidity_usd: 300000000.0   # Min $300M 24h volume
    queue_timeout_s: 8               # Cancel if not filled in 8s

  # Position sizing
  sizing:
    target_vol_annual: 0.10
    kelly_cap: 0.20                  # Conservative Kelly cap
    max_position_pct: 0.03           # Max 3% of equity per trade

  # Strategy-specific limits
  limits:
    max_trades_per_day: 50
    max_trades_per_hour: 6
    min_time_between_trades_s: 300   # Min 5 minutes between trades
    cooldown_after_loss_s: 600       # 10 min cooldown after loss
    consecutive_loss_threshold: 3

# Microreactor 5m Strategy (optional intra-bar probes)
microreactor_5m:
  pairs: ["BTC/USD", "ETH/USD"]
  timeframe: "5m"

  # Intra-bar configuration (DIFFERENT from bar_reaction_5m)
  intra_bar_probes:
    enabled: true
    probe_interval_s: 30              # Probe every 30s
    max_probes_per_bar: 9
    require_momentum_shift: true      # Only probe if momentum detected
    min_momentum_shift_bps: 5         # Min 5bps move to trigger probe

  # Inherit most settings from bar_reaction_5m but adjust for speed
  indicators:
    ema_fast: 5                       # Faster EMAs for intra-bar
    ema_slow: 13
    atr_period: 14

  execution:
    order_type: "limit"
    post_only: true
    max_spread_bps: 3.0               # TIGHTER spread for intra-bar
    queue_timeout_s: 5                # Faster cancel (5s)

  risk:
    target_rr: 1.5                    # Lower RR for faster exits
    sl_atr_multiple: 1.0
    tp_atr_multiple: 1.5
    max_hold_bars: 6                  # Max 30 minutes

  limits:
    max_trades_per_day: 80            # Higher frequency
    max_trades_per_hour: 10
    min_time_between_trades_s: 60     # Min 1 minute
```

**Changes**:
- Add `bar_reaction_5m` strategy config block
- Add `microreactor_5m` strategy config block (optional)
- Add to `strategy_router.allocations` if using router

---

### 2. Strategy Implementation Layer

#### `strategies/bar_reaction_5m.py` ❌ NEW FILE
**Status**: To be created
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\strategies\bar_reaction_5m.py`
**Purpose**: Core bar-close reaction strategy logic

**Key Features**:
- Precise 5-minute bar-close detection
- EMA crossover + volume confirmation
- ATR-based dynamic stops
- Maker-only execution with spread guards
- Signal generation following `strategies/api.py` contract

**Interface**:
```python
class BarReaction5mStrategy:
    def prepare(snapshot, ohlcv_df) -> None
    def should_trade(snapshot) -> bool
    def generate_signals(snapshot, ohlcv_df, regime_label) -> list[SignalSpec]
    def size_positions(signals, equity, volatility) -> list[PositionSpec]
```

**Dependencies**:
- `strategies/api.py` (SignalSpec, PositionSpec)
- `strategies/filters.py` (spread_check, volume_check, regime_check)
- `strategies/sizing.py` (kelly_fraction, vol_target_size)
- `ai_engine/schemas.py` (MarketSnapshot, RegimeLabel)

---

#### `strategies/microreactor_5m.py` ❌ NEW FILE (OPTIONAL)
**Status**: To be created
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\strategies\microreactor_5m.py`
**Purpose**: Intra-bar probe strategy for faster reaction times

**Key Features**:
- Probes market every 30s within 5m bar
- Detects momentum shifts before bar close
- Same execution standards (maker-only, spread guards)
- Lower RR targets for faster exits

**Differences from bar_reaction_5m**:
- Checks market mid-bar (every 30s)
- Faster indicators (EMA 5/13 vs 8/21)
- Tighter spread requirements (3bps vs 5bps)
- Lower hold time (max 6 bars vs 12 bars)

---

### 3. Scheduler/Infrastructure Layer

#### `agents/scheduler/bar_clock.py` ❌ NEW FILE
**Status**: To be created
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\agents\scheduler\bar_clock.py`
**Purpose**: Precise 5-minute boundary event generation

**Note**: `agents/scheduler/` directory does NOT exist yet - needs creation

**Key Features**:
- Align with UTC 5-minute boundaries (00:00, 00:05, 00:10, etc.)
- Emit `bar_close` events to Redis stream
- Handle clock drift and NTP sync
- Support both bar-close and intra-bar probe events

**Redis Stream Output**:
- Stream key: `events:bar_clock:5m`
- Event schema: `{event_type, timestamp_ms, timeframe, bar_number, alignment_error_ms}`

**Event Types**:
- `bar_close` - 5-minute boundary aligned event
- `intra_bar_probe` - Mid-bar probe event (if microreactor enabled)

**Implementation Notes**:
```python
class BarClock:
    """Precise bar-close event generator for time-based strategies"""

    async def start(self):
        """Start clock with alignment to UTC 5m boundaries"""

    async def wait_for_next_bar_close(self) -> BarCloseEvent:
        """Block until next 5m boundary, return event"""

    def get_next_bar_close_timestamp(self) -> int:
        """Calculate next 5m boundary in milliseconds"""

    def emit_bar_close_event(self, timestamp_ms: int):
        """Publish bar_close event to Redis stream"""
```

---

### 4. Execution Layer

#### `agents/core/execution_agent.py` ✅ EXISTS
**Status**: Needs minor update
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\agents\core\execution_agent.py`
**Current State**: Already has maker-only support and microstructure guards

**Changes Needed**:
1. Add `bar_reaction_5m` strategy tag to execution priorities
2. Ensure spread guards compatible with 5bps max
3. Add bar-close timestamp validation (optional)

**Existing Features (already compatible)**:
- ✅ Maker-only execution (`post_only=True`)
- ✅ Spread caps (`spread_bps_cap = 8`, supports 5bps)
- ✅ Queue timeout (`max_queue_s = 10`, supports 8s)
- ✅ IOC and post-only order types
- ✅ Real-time slippage modeling

**Minimal Changes**:
```python
# Add to strategy priority mapping (if exists)
STRATEGY_PRIORITIES = {
    "scalper": "high",
    "micro_trend": "normal",
    "mean_reversion": "normal",
    "bar_reaction_5m": "normal",      # NEW
    "microreactor_5m": "high",         # NEW (optional)
}
```

---

### 5. Backtesting Layer

#### `scripts/backtest.py` ✅ EXISTS
**Status**: Needs update
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\scripts\backtest.py`
**Also exists**: `scripts/run_backtest.py` (check which one is canonical)

**Changes Needed**:
1. Add `bar_reaction_5m` to strategy registry
2. Add 5-minute bar alignment logic
3. Add maker fee model (negative fees for maker orders)
4. Add spread/slippage model for limit orders

**New Backtest Mode**:
```bash
# Run bar_reaction_5m backtest
python scripts/backtest.py agent BTC/USD \
  --strategy bar_reaction_5m \
  --start 2024-01-01 \
  --end 2024-03-01 \
  --fee-bps -0.5 \         # Maker rebate (-0.5bps)
  --slip-bps 0.5 \          # Minimal slippage for limit orders
  --plot \
  --out reports/bar_reaction_5m_btc.json
```

**Fill Model Requirements**:
- Maker-only fills (assume filled if within spread)
- Queue timeout simulation (cancel after 8s if not filled)
- Realistic spread modeling (reject if spread > 5bps)
- Bar-close alignment (only evaluate strategy at 5m boundaries)

---

### 6. Testing Layer

#### `strategies/tests/test_bar_reaction_5m.py` ❌ NEW FILE
**Status**: To be created
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\strategies\tests\test_bar_reaction_5m.py`

**Note**: `strategies/tests/` directory does NOT exist yet - needs creation

**Test Coverage**:
- ✅ Initialization with valid config
- ✅ Bar-close detection accuracy
- ✅ EMA crossover signal generation
- ✅ Volume confirmation logic
- ✅ ATR-based stop/target calculation
- ✅ Spread guard rejection
- ✅ Position sizing with Kelly + vol targeting
- ✅ Signal deduplication (idempotent IDs)

**Example Test**:
```python
def test_bar_close_signal_generation():
    """Test signal generation only at 5m boundaries"""
    strategy = BarReaction5mStrategy()

    # Create OHLCV data with EMA crossover at bar close
    ohlcv_df = create_test_data_with_crossover()
    snapshot = create_test_snapshot(spread_bps=4.0)

    signals = strategy.generate_signals(snapshot, ohlcv_df, RegimeLabel.BULL)

    assert len(signals) == 1
    assert signals[0].strategy == "bar_reaction_5m"
    assert signals[0].side in ["long", "short"]
```

---

#### `strategies/tests/test_microreactor_5m.py` ❌ NEW FILE (OPTIONAL)
**Status**: To be created (if implementing microreactor)
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\strategies\tests\test_microreactor_5m.py`

**Test Coverage**:
- ✅ Intra-bar probe timing (every 30s)
- ✅ Momentum shift detection
- ✅ Faster indicator calculations
- ✅ Tighter spread requirements

---

#### `agents/risk/tests/test_bar_reaction_risk.py` ❌ NEW FILE
**Status**: To be created
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\agents\risk\tests\test_bar_reaction_risk.py`

**Note**: `agents/risk/tests/` directory does NOT exist yet - needs creation

**Test Coverage**:
- ✅ Trade frequency caps (max 50/day, 6/hour)
- ✅ Min time between trades (5 minutes)
- ✅ Cooldown after loss (10 minutes)
- ✅ Consecutive loss threshold (3 losses → pause)
- ✅ Position size limits (max 3% equity)

---

#### `agents/scheduler/tests/test_bar_clock.py` ❌ NEW FILE
**Status**: To be created
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\agents\scheduler\tests\test_bar_clock.py`

**Test Coverage**:
- ✅ 5m boundary alignment (UTC)
- ✅ Clock drift handling
- ✅ Event emission to Redis
- ✅ Intra-bar probe timing
- ✅ Bar number calculation

---

### 7. Reports/Output Layer

#### `reports/` ✅ EXISTS
**Status**: Ready for use
**Location**: `C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\reports\`

**Output Files** (generated by backtests):
- `reports/bar_reaction_5m_btc_usd.json` - Backtest results JSON
- `reports/bar_reaction_5m_btc_usd.csv` - Trade log CSV
- `reports/bar_reaction_5m_equity_curve.png` - Equity chart
- `reports/bar_reaction_5m_quality_gates.json` - Quality metrics (Sharpe, DD, etc.)

**CSV Schema** (trade log):
```csv
timestamp,pair,side,entry,exit,qty,pnl,strategy,confidence,rr,atr,bar_number
2024-01-01T00:05:00Z,BTC/USD,long,50000,50500,0.05,25.00,bar_reaction_5m,0.75,2.0,0.008,1
```

---

## Directory Structure (New Files)

```
crypto_ai_bot/
├── config/
│   └── enhanced_scalper_config.yaml          [UPDATE]
├── strategies/
│   ├── bar_reaction_5m.py                    [NEW]
│   ├── microreactor_5m.py                    [NEW - OPTIONAL]
│   └── tests/                                [NEW DIR]
│       ├── __init__.py                       [NEW]
│       ├── test_bar_reaction_5m.py           [NEW]
│       └── test_microreactor_5m.py           [NEW - OPTIONAL]
├── agents/
│   ├── scheduler/                            [NEW DIR]
│   │   ├── __init__.py                       [NEW]
│   │   ├── bar_clock.py                      [NEW]
│   │   └── tests/                            [NEW DIR]
│   │       ├── __init__.py                   [NEW]
│   │       └── test_bar_clock.py             [NEW]
│   ├── core/
│   │   └── execution_agent.py                [UPDATE - MINOR]
│   └── risk/
│       └── tests/                            [NEW DIR]
│           ├── __init__.py                   [NEW]
│           └── test_bar_reaction_risk.py     [NEW]
├── scripts/
│   └── backtest.py                           [UPDATE]
└── reports/                                  [EXISTS]
    └── (backtest outputs will be created here)
```

---

## Implementation Order (Recommended)

### Phase 1: Core Strategy (Day 1)
1. ✅ File map complete
2. ⬜ Update `config/enhanced_scalper_config.yaml`
3. ⬜ Create `strategies/bar_reaction_5m.py`
4. ⬜ Create `strategies/tests/test_bar_reaction_5m.py`
5. ⬜ Run unit tests: `pytest strategies/tests/test_bar_reaction_5m.py -v`

### Phase 2: Scheduler/Infrastructure (Day 1-2)
6. ⬜ Create `agents/scheduler/` directory structure
7. ⬜ Create `agents/scheduler/bar_clock.py`
8. ⬜ Create `agents/scheduler/tests/test_bar_clock.py`
9. ⬜ Run tests: `pytest agents/scheduler/tests/ -v`

### Phase 3: Execution & Risk (Day 2)
10. ⬜ Minor update to `agents/core/execution_agent.py`
11. ⬜ Create `agents/risk/tests/test_bar_reaction_risk.py`
12. ⬜ Run risk tests: `pytest agents/risk/tests/test_bar_reaction_risk.py -v`

### Phase 4: Backtesting (Day 2-3)
13. ⬜ Update `scripts/backtest.py` with bar_reaction_5m
14. ⬜ Add maker fee model and bar-close alignment
15. ⬜ Run smoke backtest: `python scripts/backtest.py smoke --quick`
16. ⬜ Run full backtest: `python scripts/backtest.py agent BTC/USD --strategy bar_reaction_5m`

### Phase 5: Quality Gates & Reports (Day 3)
17. ⬜ Verify backtest outputs in `reports/`
18. ⬜ Generate quality gate metrics (Sharpe > 1.5, DD < 15%, etc.)
19. ⬜ Run integration tests: `pytest -v`
20. ⬜ Document results in `reports/bar_reaction_5m_analysis.md`

### Phase 6: Optional Microreactor (Day 4+)
21. ⬜ Create `strategies/microreactor_5m.py`
22. ⬜ Create `strategies/tests/test_microreactor_5m.py`
23. ⬜ Update `agents/scheduler/bar_clock.py` with intra-bar probes
24. ⬜ Run comparative backtest (bar_reaction vs microreactor)

---

## Redis Streams Used

### Input Streams (consumed by strategy)
- `md:trades` - Real-time trade feed
- `md:orderbook` - Order book snapshots
- `events:bar_clock:5m` - Bar-close events from BarClock

### Output Streams (produced by strategy)
- `signals:paper` - Paper trading signals (mode=PAPER)
- `signals:live` - Live trading signals (mode=LIVE)
- `metrics:bar_reaction_5m` - Strategy performance metrics

---

## Signal Schema (Redis)

```json
{
  "id": "abc123...",
  "ts": 1704099900000,
  "pair": "BTC/USD",
  "side": "long",
  "entry": 50000.00,
  "sl": 49250.00,
  "tp": 51500.00,
  "strategy": "bar_reaction_5m",
  "confidence": 0.75,
  "rr": 2.0,
  "atr": 400.00,
  "move_bps": 50,
  "atr_pct": 0.008,
  "mode": "paper",
  "bar_number": 1234,
  "timeframe": "5m",
  "indicators": {
    "ema_fast": 50100.00,
    "ema_slow": 49900.00,
    "volume_ratio": 1.5
  }
}
```

---

## Quality Gates (Backtesting)

Before deploying to paper trading, ensure:
- ✅ Sharpe Ratio > 1.5
- ✅ Max Drawdown < 15%
- ✅ Win Rate > 50%
- ✅ Profit Factor > 1.5
- ✅ Total Return > 20% annualized
- ✅ All unit tests passing
- ✅ No critical errors in logs

---

## Deployment Checklist

### Paper Trading (Staging)
1. ⬜ All tests passing (`pytest -v`)
2. ⬜ Backtest quality gates met
3. ⬜ Config updated with `TRADING_MODE=PAPER`
4. ⬜ Redis connection verified (TLS)
5. ⬜ Deploy to staging: `python scripts/start_trading_system.py --mode paper --strategy bar_reaction_5m`
6. ⬜ Monitor for 72 hours minimum
7. ⬜ Verify signal quality in `signals:paper` stream

### Live Trading (Production) - DO NOT RUSH
1. ⬜ Paper trading burn-in complete (72h+)
2. ⬜ Manual review of all paper trades
3. ⬜ Set `TRADING_MODE=LIVE`
4. ⬜ Set `LIVE_CONFIRMATION=YES_I_WANT_LIVE_TRADING`
5. ⬜ Start with small position sizes (5-10% of normal)
6. ⬜ Monitor for 1 week minimum before scaling up

---

## References

- **PRD**: `PRD_AGENTIC.md`
- **Config Guide**: `config/CONFIG_USAGE.md`
- **Operations**: `OPERATIONS_RUNBOOK.md`
- **Strategy API**: `strategies/api.py`
- **Existing Strategies**: `strategies/momentum_strategy.py`, `strategies/scalper.py`

---

**Status**: File map complete ✅
**Next Step**: Proceed to Phase 1 (Core Strategy Implementation)
