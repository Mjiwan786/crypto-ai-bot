# Regime Detector Quick Reference

## Import
```python
from ai_engine.regime_detector import (
    RegimeDetector,      # Stateful detector class
    RegimeConfig,        # Configuration model
    RegimeTick,          # Output dataclass
    detect_regime,       # Stateless function
)
```

## Basic Usage

### Stateless (One-Off Detection)
```python
import pandas as pd

ohlcv = pd.DataFrame({
    'high': [...],
    'low': [...],
    'close': [...],
})

tick = detect_regime(ohlcv)
print(f"Regime: {tick.regime}")           # bull/bear/chop
print(f"Volatility: {tick.vol_regime}")   # vol_low/vol_normal/vol_high
print(f"Strength: {tick.strength:.2f}")   # [0, 1]
print(f"Changed: {tick.changed}")         # True/False
```

### Stateful (Production - Maintains Hysteresis)
```python
# Create detector once
config = RegimeConfig(hysteresis_bars=3)
detector = RegimeDetector(config=config)

# Call repeatedly on new bars
for ohlcv_batch in live_stream:
    tick = detector.detect(ohlcv_batch)

    if tick.changed:
        print(f"Regime changed to {tick.regime}!")
```

## Configuration

```python
config = RegimeConfig(
    # Indicator periods
    adx_period=14,                  # ADX period (trend strength)
    aroon_period=25,                # Aroon period (momentum)
    rsi_period=14,                  # RSI period
    atr_period=14,                  # ATR period (volatility)

    # Regime thresholds
    adx_trend_threshold=25.0,       # ADX > 25 = trending
    aroon_bull_threshold=70.0,      # Aroon Up > 70 = bullish
    aroon_bear_threshold=70.0,      # Aroon Down > 70 = bearish

    # Volatility thresholds (ATR percentiles)
    vol_low_percentile=33.0,        # Below 33rd percentile = low vol
    vol_high_percentile=67.0,       # Above 67th percentile = high vol

    # Hysteresis (flip-flop prevention)
    hysteresis_bars=3,              # Require 3 bars persistence to flip
    min_strength_delta=0.15,        # Min strength change to flip

    # Guardrails
    min_rows=100,                   # Min OHLCV rows required
    max_nan_frac=0.05,              # Max 5% NaN allowed
)
```

## RegimeTick Output

```python
tick = detector.detect(ohlcv_df)

tick.regime            # "bull" | "bear" | "chop"
tick.vol_regime        # "vol_low" | "vol_normal" | "vol_high"
tick.strength          # float [0, 1]
tick.changed           # bool (True if regime changed)
tick.timestamp_ms      # int (milliseconds)
tick.components        # dict with ADX, Aroon, RSI, ATR values
tick.explain           # str (human-readable explanation)
```

## Regime Classification Logic

### Bull
- Strong trend (ADX > threshold)
- Aroon Up > 70 AND Aroon Up > Aroon Down + 20
- RSI > 30 (not oversold)

### Bear
- Strong trend (ADX > threshold)
- Aroon Down > 70 AND Aroon Down > Aroon Up + 20
- RSI < 70 (not overbought)

### Chop
- Weak trend (ADX < threshold) OR
- Balanced Aroon (neither Up nor Down dominant)

## Hysteresis Behavior

```python
detector = RegimeDetector(RegimeConfig(hysteresis_bars=3))

# Initial detection
tick1 = detector.detect(bull_data)  # regime=bull, changed=True

# Same data (no flip)
tick2 = detector.detect(bull_data)  # regime=bull, changed=False

# New regime (need 3 bars persistence)
tick3 = detector.detect(bear_data)  # regime=bull, changed=False (not enough persistence)
tick4 = detector.detect(bear_data)  # regime=bull, changed=False (still waiting)
tick5 = detector.detect(bear_data)  # regime=bear, changed=True (flipped after 3 bars!)
```

## Error Handling

```python
try:
    tick = detector.detect(ohlcv_df)
except ValueError as e:
    # Possible errors:
    # - Insufficient data (< min_rows)
    # - Missing required columns (high, low, close)
    # - Excessive NaNs (> max_nan_frac)
    print(f"Error: {e}")
```

## Common Patterns

### Integration with Strategy Router
```python
# Detect regime
tick = detector.detect(ohlcv_df)

# Route to appropriate strategy
if tick.regime == "bull":
    strategy = momentum_strategy
elif tick.regime == "bear":
    strategy = momentum_strategy  # Can short
else:  # chop
    strategy = mean_reversion_strategy
```

### Regime Change Handling
```python
tick = detector.detect(ohlcv_df)

if tick.changed:
    logger.info(f"Regime changed to {tick.regime}")

    # Halt new entries for N cycles (PRD requirement)
    trading_halted_until = time.time() + halt_duration

    # Optionally close positions incongruent with new regime
    if tick.regime == "chop":
        close_all_trending_positions()
```

### Volatility Adjustment
```python
tick = detector.detect(ohlcv_df)

# Adjust position sizing based on volatility
if tick.vol_regime == "vol_high":
    position_size *= 0.5  # Reduce size in high volatility
elif tick.vol_regime == "vol_low":
    position_size *= 1.2  # Increase size in low volatility
```

## Performance

- **Latency**: ~2ms per detection (200-bar OHLCV)
- **Memory**: O(N) where N = OHLCV length
- **CPU**: O(N) for indicator calculations
- **Deterministic**: Same input → same output

## Dependencies

- **Required**: pandas, numpy, pydantic (v2)
- **Optional**: talib (uses fallback if not available)

## Testing

Run tests:
```bash
pytest tests/ai_engine/test_regime_detector.py -v
```

Self-check:
```bash
python ai_engine/regime_detector/detector.py
```
