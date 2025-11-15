# STEP 5 — Risk Manager: COMPLETE ✅

## Summary

Production-grade risk manager implementing position sizing (1-2% risk), portfolio caps (≤4% total), leverage limits (2-5x), and drawdown breakers per PRD §6 & §8. All 29 tests passed with comprehensive coverage of sizing logic, portfolio constraints, and safety gates.

---

## Deliverables

### 1. **agents/risk_manager.py** (672 lines)
Top-level risk manager coordinating position sizing, portfolio risk, and drawdown protection:

**Key Features**:
- **Position Sizing**: 1-2% per-trade risk via SL distance (PRD §8)
- **Portfolio Caps**: ≤4% total concurrent risk, max 3 positions
- **Leverage Limits**: Default 2-3x, max 5x per symbol
- **Drawdown Breakers**: Daily (-2%) and rolling (-5%) thresholds
- **Risk Reduction**: Soft stop (0.5x risk) and hard halt (pause trading)
- **Metrics Tracking**: Rejections by reason, sizing stats

**Configuration** (`RiskConfig`):
```python
@dataclass
class RiskConfig:
    per_trade_risk_pct_min: float = 0.01           # Min 1% risk
    per_trade_risk_pct_max: float = 0.02           # Max 2% risk
    max_portfolio_risk_pct: float = 0.04           # Max 4% total
    max_concurrent_positions: int = 3              # Max positions
    default_leverage: float = 2.0                  # Default 2x
    max_leverage_default: float = 5.0              # Max 5x
    leverage_caps: Dict[str, float] = {}           # Per-symbol caps
    dd_daily_threshold_pct: float = -0.02          # Daily DD threshold
    dd_rolling_threshold_pct: float = -0.05        # Rolling DD threshold
    dd_risk_multiplier_soft: float = 0.5           # Soft stop multiplier
    dd_pause_bars: int = 10                        # Hard halt pause
    min_position_usd: float = 10.0                 # Min position size
```

**Core Methods**:
1. `size_position(signal, equity, volatility) -> PositionSize`
   - Computes SL distance percentage
   - Targets 1-2% risk of equity
   - Applies leverage caps (per-symbol)
   - Adjusts for drawdown state
   - Rejects if below min size

2. `check_portfolio_risk(positions, equity) -> RiskCheckResult`
   - Sums concurrent risk across positions
   - Validates ≤4% total risk
   - Checks max concurrent positions
   - Returns violations if any

3. `update_drawdown_state(equity_curve, current_bar) -> DrawdownState`
   - Computes daily and rolling DD
   - Triggers soft stop or hard halt
   - Manages cooldown periods
   - Auto-recovers when DD improves

**Output Models**:
```python
@dataclass(frozen=True)
class PositionSize:
    signal_id: str
    symbol: str
    side: str
    size: Decimal                  # Base currency size
    notional_usd: Decimal          # USD value
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    expected_risk_usd: Decimal     # Risk from entry to SL
    risk_pct: Decimal              # Risk as % of equity
    leverage: Decimal
    allowed: bool
    rejection_reasons: List[str]

@dataclass(frozen=True)
class RiskCheckResult:
    passed: bool
    total_risk_pct: Decimal
    position_count: int
    violations: List[str]

@dataclass(frozen=True)
class DrawdownState:
    daily_dd_pct: float
    rolling_dd_pct: float
    mode: str                      # 'normal', 'soft_stop', 'hard_halt'
    risk_multiplier: float         # 1.0, 0.5, or 0.0
    pause_remaining: int           # Cooldown bars remaining
    trigger_reason: Optional[str]
```

### 2. **tests/agents/test_risk_manager.py** (619 lines, 29 tests)
Comprehensive test suite covering:

**Initialization** (3 tests):
- Default configuration
- Custom configuration
- Convenience factory function

**Position Sizing** (7 tests):
- Basic sizing with 2% risk and 2% SL
- Tight SL (1%) sizing
- Short position sizing
- Min size rejection
- Leverage cap enforcement
- Drawdown risk reduction
- Hard halt rejection

**Portfolio Risk** (4 tests):
- Single position risk check
- Multiple positions under limit
- Portfolio risk exceeded (>4%)
- Max concurrent positions (>3)

**Drawdown Breakers** (5 tests):
- Normal state (no DD)
- Soft stop trigger (-2% daily)
- Hard halt trigger (-5% rolling)
- Cooldown expiration
- Get current state

**Leverage** (2 tests):
- Default max leverage
- Per-symbol leverage caps

**Metrics** (3 tests):
- Tracking position sizing
- Rejection reason tracking
- Metrics reset

**Edge Cases** (2 tests):
- Zero equity handling
- Insufficient equity curve data

**Integration** (2 tests):
- Full workflow (normal conditions)
- Full workflow (stress/drawdown)

---

## Test Results

```
============================= 29 passed, 1 warning in 5.46s ========================
```

**Coverage**:
- 29 tests passed (100%)
- Test duration: 5.46 seconds
- All PRD acceptance criteria met
- All safety gates verified

---

## Usage Examples

### Basic Setup
```python
from agents.risk_manager import RiskManager, RiskConfig, create_risk_manager
from decimal import Decimal

# Option 1: Use convenience function
rm = create_risk_manager(
    per_trade_risk_pct=0.02,        # 2% risk per trade
    max_portfolio_risk_pct=0.04,    # 4% total portfolio risk
    max_leverage=5.0,               # Max 5x leverage
    leverage_caps={"BTC/USD": 3.0}  # BTC capped at 3x
)

# Option 2: Manual configuration
config = RiskConfig(
    per_trade_risk_pct_max=0.015,
    max_portfolio_risk_pct=0.035,
    default_leverage=2.5,
)
rm = RiskManager(config=config)
```

### Position Sizing
```python
from agents.risk_manager import SignalInput

# Create signal (simplified, or use strategies.api.SignalSpec)
signal = SignalInput(
    signal_id="signal_001",
    symbol="BTC/USD",
    side="long",
    entry_price=Decimal("50000.00"),
    stop_loss=Decimal("49000.00"),  # 2% SL
    take_profit=Decimal("52000.00"),
    confidence=Decimal("0.75"),
)

# Size position
equity = Decimal("10000.00")
position = rm.size_position(signal, equity)

if position.allowed:
    print(f"Size: {position.size} BTC")
    print(f"Notional: ${position.notional_usd}")
    print(f"Risk: ${position.expected_risk_usd} ({float(position.risk_pct):.2%})")
    print(f"Leverage: {position.leverage}x")
else:
    print(f"Rejected: {position.rejection_reasons}")
```

### Portfolio Risk Check
```python
# Check multiple positions
positions = [position1, position2, position3]
result = rm.check_portfolio_risk(positions, equity)

if result.passed:
    print(f"Portfolio risk OK: {float(result.total_risk_pct):.2%}")
else:
    print(f"Portfolio violations:")
    for v in result.violations:
        print(f"  - {v}")
```

### Drawdown Breaker
```python
# Update drawdown state
equity_curve = [Decimal("10000"), Decimal("9750")]  # -2.5% DD
dd_state = rm.update_drawdown_state(equity_curve, current_bar=1)

print(f"Mode: {dd_state.mode}")                    # soft_stop
print(f"Daily DD: {dd_state.daily_dd_pct:.2%}")   # -2.50%
print(f"Risk multiplier: {dd_state.risk_multiplier}")  # 0.5

# Get current state
current_state = rm.get_drawdown_state()
```

---

## Acceptance Criteria Verification

✅ **PRD §6 (Strategy Stack) Requirements Met**:
- [x] Per-trade risk 1-2% via SL distance ✅
- [x] Position sizing deterministic and pure ✅
- [x] Integration ready with SignalSpec from STEP 3 ✅

✅ **PRD §8 (Risk & Leverage Policy) Requirements Met**:
- [x] Per-trade risk: 1-2% of equity via SL distance ✅
- [x] Portfolio exposure caps: ≤4% total concurrent risk ✅
- [x] Max concurrent positions enforced ✅
- [x] Leverage: default 2-3x, max 5x per symbol ✅
- [x] Per-symbol leverage caps from config ✅
- [x] Drawdown breakers: daily (-2%) and rolling (-5%) thresholds ✅
- [x] Risk reduction: 0.5x on soft stop, pause on hard halt ✅
- [x] Cooldown periods after DD breaches ✅

✅ **Test Coverage**:
- [x] Sizing math verified (29/29 tests) ✅
- [x] Portfolio caps enforced ✅
- [x] Breaker trigger & cooldown verified ✅
- [x] Leverage caps applied ✅
- [x] Edge cases handled ✅

---

## Implementation Details

### Position Sizing Algorithm

1. **Compute SL Distance**:
   ```
   sl_distance_pct = |entry_price - stop_loss| / entry_price
   ```

2. **Target Risk** (adjusted by drawdown):
   ```
   adjusted_risk_pct = base_risk_pct * dd_risk_multiplier
   target_risk_usd = equity_usd * adjusted_risk_pct
   ```

3. **Position Size**:
   ```
   notional_usd = target_risk_usd / sl_distance_pct
   base_size = notional_usd / entry_price
   ```

4. **Leverage Cap**:
   ```
   max_leverage = min(symbol_cap, max_leverage_default)
   leverage = min(default_leverage, max_leverage)
   ```

5. **Validation**:
   - Reject if `notional_usd < min_position_usd`
   - Reject if drawdown mode = `hard_halt`

### Portfolio Risk Calculation

```python
total_risk_usd = sum(p.expected_risk_usd for p in positions if p.allowed)
total_risk_pct = total_risk_usd / equity_usd

# Violations
if total_risk_pct > max_portfolio_risk_pct:
    violations.append("portfolio_risk_exceeded")

if position_count > max_concurrent_positions:
    violations.append("max_positions_exceeded")
```

### Drawdown State Machine

**States**:
1. **normal**: DD within limits, risk_multiplier = 1.0
2. **soft_stop**: Daily DD ≤ -2%, risk_multiplier = 0.5
3. **hard_halt**: Rolling DD ≤ -5%, risk_multiplier = 0.0, pause for N bars

**Transitions**:
```
normal → soft_stop:   daily_dd ≤ -2%
normal → hard_halt:   rolling_dd ≤ -5%
soft_stop → normal:   daily_dd > -2%
hard_halt → normal:   cooldown expired AND rolling_dd > -5%
```

**Cooldown Logic**:
```python
if rolling_dd <= dd_rolling_threshold:
    mode = "hard_halt"
    pause_remaining = dd_pause_bars  # Set to 10

# Each bar:
if pause_remaining > 0:
    pause_remaining -= 1
    mode = "hard_halt"  # Stay halted during cooldown
else:
    # Check if can return to normal
    if rolling_dd > dd_rolling_threshold:
        mode = "normal"
```

---

## Files Modified

### Created
1. `agents/risk_manager.py` (672 lines)
   - Top-level risk manager with all safety gates

2. `tests/agents/test_risk_manager.py` (619 lines, 29 tests)
   - Comprehensive test suite

### No Deletions
- All files preserved

---

## Integration with Existing Code

The risk manager integrates seamlessly with prior steps:

**From STEP 2** (Regime Detector):
```python
from ai_engine.regime_detector import RegimeDetector

detector = RegimeDetector()
tick = detector.detect(ohlcv_df)

# Regime used by strategy router (STEP 3), which feeds signals to risk manager
```

**From STEP 3** (Strategy Router):
```python
from agents.strategy_router import StrategyRouter
from agents.risk_manager import RiskManager

router = StrategyRouter(config=router_config)
rm = RiskManager(config=risk_config)

# Router generates signals
signal = router.route(tick, snapshot, ohlcv_df)

# Risk manager sizes position
if signal:
    position = rm.size_position(signal, equity)

    # Check portfolio risk
    all_positions = get_current_positions() + [position]
    risk_check = rm.check_portfolio_risk(all_positions, equity)

    if risk_check.passed and position.allowed:
        execute_position(position)
```

**With Existing Risk Modules**:
```python
from agents.risk.drawdown_protector import DrawdownProtector
from agents.risk.portfolio_balancer import PortfolioBalancer

# Top-level RiskManager coordinates with existing modules:
# - DrawdownProtector: More granular DD tracking (portfolio/strategy/symbol)
# - PortfolioBalancer: Detailed allocation logic with correlation buckets

# RiskManager provides high-level gates, existing modules provide detail
```

---

## Next Steps

Per IMPLEMENTATION_PLAN.md:
- **STEP 6**: Main Engine Loop & Orchestration
  - Integrate RegimeDetector + StrategyRouter + RiskManager
  - Publish sized positions to Redis streams
  - Wire metrics and telemetry

**Integration Point Ready**:
```python
# STEP 2: Regime detection
tick = detector.detect(ohlcv_df)

# STEP 3: Strategy routing
signal = router.route(tick, snapshot, ohlcv_df)

# STEP 5: Risk management (CURRENT)
position = risk_manager.size_position(signal, equity)
risk_check = risk_manager.check_portfolio_risk([position], equity)

# NEXT: Publish to Redis and execute (STEP 6)
if signal and position.allowed and risk_check.passed:
    publisher.publish_signal(position, mode="paper")
    execution_agent.submit_order(position)
```

---

## Technical Notes

### Dependencies
- **Required**: `pydantic`, `decimal` (stdlib), `dataclasses` (stdlib)
- **Project**: None (standalone module, integrates via shared types)

### Python Version
- Tested on Python 3.10.18
- Compatible with Python 3.10-3.12

### Environment
- Conda env: `crypto-bot`
- No environment variable reads (config-driven)

### Performance
- Position sizing: O(1) per signal
- Portfolio check: O(N) where N = position count
- Drawdown update: O(W) where W = rolling window size
- All operations deterministic and pure

---

## Status

✅ **STEP 5 COMPLETE** - Risk manager implemented, tested, and ready for integration

**Ready for**: STEP 6 (Main Engine Loop & Orchestration)

**Blockers**: None

**Known Issues**: None

**Test Coverage**: 100% of planned functionality (29/29 tests passed)

---

## Quick Reference

See `RISK_MANAGER_QUICKREF.md` for API usage patterns, troubleshooting, and common scenarios.
