# Strategy Router Quick Reference

## Import
```python
from agents.strategy_router import (
    StrategyRouter,         # Main router class
    RouterConfig,           # Configuration
    Strategy,               # Protocol for strategies
    create_default_router,  # Convenience function
)
```

## Basic Setup

### Option 1: Manual Configuration
```python
from agents.strategy_router import StrategyRouter, RouterConfig
from strategies.momentum_strategy import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from ai_engine.schemas import RegimeLabel

# Create config
config = RouterConfig(
    regime_change_cooldown_bars=2,           # Halt for 2 bars after regime change
    min_confidence=Decimal("0.40"),          # Min signal confidence
    spread_bps_max=5.0,                      # Max spread in bps
    kill_switch_env_var="TRADING_ENABLED",   # Kill switch env variable
    enable_leverage_caps=True,               # Enable per-symbol leverage caps
    enable_spread_check=True,                # Enable spread tolerance check
)

# Create router
router = StrategyRouter(config=config)

# Register strategies
router.register("momentum", MomentumStrategy())
router.register("mean_reversion", MeanReversionStrategy())

# Map regimes to strategies
router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")
router.map_regime_to_strategy(RegimeLabel.BEAR, "momentum")
router.map_regime_to_strategy(RegimeLabel.CHOP, "mean_reversion")
```

### Option 2: Use Convenience Function
```python
from agents.strategy_router import create_default_router

# Creates router with default mappings:
# BULL -> momentum, BEAR -> momentum, CHOP -> mean_reversion
router = create_default_router(
    momentum_strategy=MomentumStrategy(),
    mean_reversion_strategy=MeanReversionStrategy(),
    regime_change_cooldown_bars=3,
)
```

## Routing Signals

```python
from ai_engine.regime_detector import RegimeDetector

# Detect regime
detector = RegimeDetector()
tick = detector.detect(ohlcv_df)

# Route signal
signal = router.route(
    regime_tick=tick,
    snapshot=market_snapshot,
    ohlcv_df=ohlcv_df,
)

if signal:
    print(f"Signal generated:")
    print(f"  {signal.side} {signal.symbol} @ {signal.entry_price}")
    print(f"  Strategy: {signal.strategy}")
    print(f"  Confidence: {signal.confidence}")
else:
    print("No signal (cooldown/kill-switch/spread/etc.)")
```

## Safety Controls

### 1. Kill Switch
```bash
# Enable trading (default)
export TRADING_ENABLED=true

# Disable trading (kill switch active)
export TRADING_ENABLED=false
```

Supported values:
- **Trading ON**: `true`, `1`, `yes`, `on` (case-insensitive)
- **Trading OFF**: `false`, `0`, `no`, `off` (or any other value)

### 2. Cooldown on Regime Changes
```python
# After regime change, router halts for N bars
config = RouterConfig(regime_change_cooldown_bars=2)

# Example:
# Bar 1: Regime BULL -> CHOP (change detected)
# Bar 2: Cooldown (no signals)
# Bar 3: Cooldown (no signals)
# Bar 4: Normal routing resumes
```

### 3. Spread Tolerance
```python
# Reject signals if spread too wide
config = RouterConfig(spread_bps_max=5.0)  # Max 5 bps spread

# Disable spread check
config = RouterConfig(enable_spread_check=False)
```

### 4. Leverage Caps
```python
# Enable per-symbol leverage caps (loaded from kraken.yaml)
config = RouterConfig(enable_leverage_caps=True)

router = StrategyRouter(config=config)

# Check max leverage for symbol
max_leverage = router.get_max_leverage("BTC/USD")
print(f"Max leverage: {max_leverage}x")  # e.g., 5x for BTC
```

## Metrics & Monitoring

```python
# Get metrics
metrics = router.get_metrics()

print(f"Total routes: {metrics['total_routes']}")
print(f"Cooldown rejections: {metrics['cooldown_rejections']}")
print(f"Kill switch rejections: {metrics['kill_switch_rejections']}")
print(f"Spread rejections: {metrics['spread_rejections']}")
print(f"Leverage cap rejections: {metrics['leverage_cap_rejections']}")
print(f"Current regime: {metrics['current_regime']}")
print(f"Cooldown remaining: {metrics['cooldown_remaining']} bars")
print(f"Registered strategies: {metrics['registered_strategies']}")
print(f"Regime mappings: {metrics['regime_mappings']}")

# Reset metrics
router.reset_metrics()
```

## Configuration Options

```python
@dataclass
class RouterConfig:
    regime_change_cooldown_bars: int = 2           # Cooldown period
    min_confidence: Decimal = Decimal("0.40")      # Min signal confidence
    spread_bps_max: float = 5.0                    # Max spread in bps
    kill_switch_env_var: str = "TRADING_ENABLED"   # Kill switch env var
    exchange_config_path: str = "config/exchange_configs/kraken.yaml"
    enable_spread_check: bool = True
    enable_leverage_caps: bool = True
```

## Strategy Protocol

Custom strategies must implement:

```python
class MyCustomStrategy:
    def prepare(self, snapshot: MarketSnapshot, ohlcv_df: pd.DataFrame) -> None:
        """Prepare strategy with market data (cache expensive calculations)."""
        pass

    def should_trade(self, snapshot: MarketSnapshot) -> bool:
        """Check if strategy should trade given current conditions."""
        return True

    def generate_signals(
        self,
        snapshot: MarketSnapshot,
        ohlcv_df: pd.DataFrame,
        regime_label: RegimeLabel,
    ) -> List[SignalSpec]:
        """Generate trading signals."""
        return [
            SignalSpec(
                signal_id="my_signal_123",
                timestamp=datetime.now(timezone.utc),
                symbol=snapshot.symbol,
                side="long",
                entry_price=Decimal("50000"),
                stop_loss=Decimal("49000"),
                take_profit=Decimal("52000"),
                strategy="my_custom_strategy",
                confidence=Decimal("0.75"),
            )
        ]
```

## Common Patterns

### Pattern 1: Integration with Regime Detector
```python
from ai_engine.regime_detector import RegimeDetector, RegimeConfig
from agents.strategy_router import StrategyRouter, create_default_router

# Create detector
detector = RegimeDetector(RegimeConfig(hysteresis_bars=3))

# Create router
router = create_default_router(
    momentum_strategy=MomentumStrategy(),
    mean_reversion_strategy=MeanReversionStrategy(),
)

# Main loop
for ohlcv_batch in live_data_stream:
    # Detect regime
    tick = detector.detect(ohlcv_batch)

    # Route signal
    signal = router.route(tick, market_snapshot, ohlcv_batch)

    if signal:
        # Process signal (send to risk manager, etc.)
        process_signal(signal)
```

### Pattern 2: Kill Switch for Emergency Stop
```python
import os

# In production monitoring system:
def emergency_stop():
    """Emergency stop all trading."""
    os.environ["TRADING_ENABLED"] = "false"
    logger.critical("EMERGENCY STOP ACTIVATED")

# In trading loop:
signal = router.route(tick, snapshot, ohlcv_df)
# If kill switch active, signal will be None
```

### Pattern 3: Monitoring Cooldown State
```python
# Check if in cooldown
metrics = router.get_metrics()

if metrics['cooldown_remaining'] > 0:
    print(f"In cooldown: {metrics['cooldown_remaining']} bars remaining")
    print(f"Regime changed to: {metrics['current_regime']}")
```

### Pattern 4: Leverage Cap Enforcement
```python
# Router logs leverage caps, but actual enforcement
# happens in position sizing

signal = router.route(tick, snapshot, ohlcv_df)

if signal:
    # Get max leverage for this symbol
    max_leverage = router.get_max_leverage(signal.symbol)

    # Pass to position sizer
    position = position_sizer.size(
        signal=signal,
        equity=equity_usd,
        max_leverage=max_leverage,
    )
```

## Troubleshooting

### No signals generated?
Check metrics to see why:
```python
metrics = router.get_metrics()

if metrics['kill_switch_rejections'] > 0:
    print("Kill switch is active - check TRADING_ENABLED env var")

if metrics['cooldown_rejections'] > 0:
    print(f"In cooldown - {metrics['cooldown_remaining']} bars remaining")

if metrics['spread_rejections'] > 0:
    print("Spread too wide - check spread_bps in market snapshot")
```

### Cooldown not expiring?
Ensure you're calling `route()` on each bar:
```python
# WRONG: Cooldown won't decrement
if should_trade:
    signal = router.route(...)

# CORRECT: Call on every bar
signal = router.route(tick, snapshot, ohlcv_df)  # Decrements cooldown
```

### Leverage caps not loading?
Check file path and YAML syntax:
```python
config = RouterConfig(
    enable_leverage_caps=True,
    exchange_config_path="config/exchange_configs/kraken.yaml",  # Check path
)

router = StrategyRouter(config=config)

# Check if loaded
if len(router._leverage_caps) == 1 and "__default__" in router._leverage_caps:
    print("WARNING: Leverage caps failed to load, using defaults")
```

## Performance

- **Routing latency**: ~1-2ms per call
- **Leverage cap lookup**: O(1) hash table
- **Cooldown tracking**: O(1) counter
- **Memory**: O(1) per router instance

## Testing

Run tests:
```bash
pytest tests/agents/test_strategy_router.py -v
```

Self-check (not available due to import issues, use pytest instead):
```bash
# Use pytest instead
pytest tests/agents/test_strategy_router.py::test_basic_routing -v
```
