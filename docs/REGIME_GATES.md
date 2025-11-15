# Regime Gate Implementation (24/7 Throttling)

## Overview

Regime gates provide 24/7 throttling for trading strategies by filtering bars based on market conditions. Instead of "sleeping" during unfavorable conditions, strategies run continuously but pass fewer bars through.

**Philosophy**: Never sleep, but pass fewer bars in chop or dead liquidity.

## Architecture

### RegimeGate (Base Class)

Common metrics calculated for all gates:
- **EMA50/EMA200**: Exponential moving averages for trend detection
- **ATR(14)**: Average True Range for volatility measurement
- **Trend Strength %**: `|EMA50 - EMA200| / close * 100`
- **ATR %**: `ATR / close * 100`
- **Volume Ratio**: Current volume / average volume
- **Pass Rate**: Tracks `bars_passed / bars_total` for monitoring

### TrendGate (for Momentum/Breakout)

**Used by**: `MomentumStrategy`, `BreakoutStrategy`

**Gate Logic**:
```
PASS if:
  1. (|EMA50-EMA200|/close) > k * (ATR/close)     [strong trend]
  2. min_atr_pct <= ATR% <= max_atr_pct           [moderate volatility]
  3. volume_ratio >= min_volume_ratio             [sufficient volume]
```

**Default Parameters**:
- `k = 1.5` - Trend strength multiplier
- `min_atr_pct = 0.4%` - Minimum volatility floor
- `max_atr_pct = 3.0%` - Maximum volatility ceiling
- `min_volume_ratio = 0.5` - 50% of average volume

**Purpose**: Filter for strong trending markets with moderate volatility.

### ChopGate (for Mean Reversion)

**Used by**: `MeanReversionStrategy`

**Gate Logic** (INVERTED from TrendGate):
```
PASS if:
  1. (|EMA50-EMA200|/close) <= k * (ATR/close)    [weak trend/chop]
  2. ATR% <= max_atr_pct                          [low volatility]
  3. volume_ratio >= min_volume_ratio             [sufficient volume]
```

**Default Parameters**:
- `k = 1.0` - Chop multiplier (lower than TrendGate)
- `max_atr_pct = 1.5%` - Lower ceiling for bounded ranges
- `min_volume_ratio = 0.5` - 50% of average volume

**Purpose**: Filter for choppy/sideways markets with low volatility.

## Integration Examples

### Momentum Strategy

```python
from strategies.momentum_strategy import MomentumStrategy

# Create strategy with regime gate
strategy = MomentumStrategy(
    regime_k=1.5,           # Higher k = stricter trend requirement
    min_atr_pct=0.4,
    max_atr_pct=3.0,
)

# Gate automatically checks before signal generation
signals = strategy.generate_signals(snapshot, ohlcv_df, regime_label)
```

### Breakout Strategy

```python
from strategies.breakout import BreakoutStrategy

# Create strategy with regime gate
strategy = BreakoutStrategy(
    regime_k=1.5,
    min_atr_pct=0.4,
    max_atr_pct=3.0,
)

# Gate automatically checks before signal generation
signals = strategy.generate_signals(snapshot, ohlcv_df, regime_label)
```

### Mean Reversion Strategy

```python
from strategies.mean_reversion import MeanReversionStrategy

# Create strategy with regime gate (INVERTED logic)
strategy = MeanReversionStrategy(
    regime_k=1.0,           # Lower k for chop detection
    regime_max_atr_pct=1.5, # Lower ATR ceiling for bounded ranges
)

# Gate automatically checks before signal generation
signals = strategy.generate_signals(snapshot, ohlcv_df, regime_label)
```

## Monitoring

### Logging

Regime gates log pass rate every 100 bars:

```
INFO: TrendGate: 34/100 bars passed (34.0%)
INFO: ChopGate: 66/100 bars passed (66.0%)
```

### Metrics Access

```python
# Get last calculated metrics
metrics = strategy.trend_gate.get_metrics()

print(f"Trend Strength: {metrics.trend_strength_pct:.2f}%")
print(f"ATR %: {metrics.atr_pct:.2f}%")
print(f"Volume Ratio: {metrics.volume_ratio:.2f}x")
print(f"Pass Rate: {metrics.pass_rate:.1f}%")

# Reset counters
strategy.trend_gate.reset_stats()
```

## Tuning Guidelines

### TrendGate (Momentum/Breakout)

**More Aggressive** (higher throughput):
- Lower `k` (e.g., 1.0) - weaker trend acceptable
- Wider ATR range (e.g., 0.3% - 4.0%)
- Lower volume threshold (e.g., 0.3)

**More Conservative** (lower throughput):
- Higher `k` (e.g., 2.0) - stronger trend required
- Narrower ATR range (e.g., 0.5% - 2.0%)
- Higher volume threshold (e.g., 0.8)

### ChopGate (Mean Reversion)

**More Aggressive** (higher throughput):
- Higher `k` (e.g., 1.5) - allow some trend
- Higher `max_atr_pct` (e.g., 2.0%) - wider ranges OK

**More Conservative** (lower throughput):
- Lower `k` (e.g., 0.7) - very tight chop only
- Lower `max_atr_pct` (e.g., 1.0%) - tight ranges only

## Performance Considerations

1. **Calculation Cost**:
   - EMA/ATR calculations are cached by RegimeGate
   - Metrics computed once per bar
   - Minimal overhead (~1ms per bar)

2. **Data Requirements**:
   - Need minimum 200 bars for EMA200 calculation
   - Strategies gracefully skip regime gate if insufficient data

3. **Memory Footprint**:
   - Each gate stores only last metrics (~100 bytes)
   - No historical data retained

## Testing

All strategies include self-checks that test regime gate integration:

```bash
# Test mean reversion with ChopGate
python strategies/mean_reversion.py

# Test momentum with TrendGate
python strategies/momentum_strategy.py

# Test breakout with TrendGate
python strategies/breakout.py
```

## Implementation Details

### File Locations

- **Base Implementation**: `strategies/filters.py` (lines 435-673)
  - `RegimeGate` base class
  - `TrendGate` class
  - `ChopGate` class
  - `RegimeMetrics` dataclass

- **Strategy Integration**:
  - `strategies/momentum_strategy.py` - TrendGate
  - `strategies/breakout.py` - TrendGate
  - `strategies/mean_reversion.py` - ChopGate

### Key Design Decisions

1. **24/7 Operation**: Gates never fully block trading, just reduce throughput
2. **Dual Filtering**: Regime gate (EMA/ATR) complements existing regime_label checks
3. **Transparent Metrics**: Pass rate logged for visibility
4. **Configurable**: All parameters exposed for tuning
5. **Fail-Safe**: Returns False on calculation errors (conservative)

## Future Enhancements

Potential improvements:
- [ ] Add adaptive `k` based on recent pass rate
- [ ] Incorporate cross-asset correlation filters
- [ ] Add regime transition detection (trend->chop, chop->trend)
- [ ] Implement multi-timeframe regime checks
- [ ] Add ML-based regime classification as alternative gate

## References

- **PRD**: See `PRD_AGENTIC.md` for original requirements
- **Backtesting**: Use `scripts/backtest.py` to test regime gates
- **Config**: Regime gate parameters can be set via YAML configs
