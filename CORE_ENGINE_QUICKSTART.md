# Core Engine Improvements - Quick Start Guide

**Last Updated:** 2025-11-08
**Prerequisites:** Python 3.10+, conda environment activated

---

## 🚀 Quick Commands

### Self-Checks (Verify Installation)

```bash
# Test whale detection
python ai_engine/whale_detection.py

# Test liquidations tracker
python ai_engine/liquidations_tracker.py

# Test enhanced predictor
python ml/predictor_v2.py

# Test adaptive regime router
python agents/adaptive_regime_router.py
```

**Expected:** All should print "Self-check passed!" ✅

---

### Train Enhanced Predictor

```bash
# Basic training (BTC/ETH, 180 days)
python scripts/train_predictor_v2.py

# Advanced training (all pairs, 365 days)
python scripts/train_predictor_v2.py --pairs BTC/USD,ETH/USD,SOL/USD,ADA/USD --days 365

# Custom output
python scripts/train_predictor_v2.py --output models/my_predictor.pkl
```

**Output:** `models/predictor_v2.pkl` (or custom path)

---

### Compare Predictor Performance

```bash
# Compare v1 vs v2 (180 days)
python scripts/compare_predictor_performance.py

# Extended comparison (365 days)
python scripts/compare_predictor_performance.py --days 365

# Custom model
python scripts/compare_predictor_performance.py --model-v2 models/my_predictor.pkl
```

**Output:** `out/predictor_comparison.json` + console summary

---

## 📊 Usage Examples

### 1. Adaptive Regime Router

```python
from agents.adaptive_regime_router import AdaptiveRegimeRouter
import pandas as pd

# Initialize
router = AdaptiveRegimeRouter(config_path="config/regime_map.yaml")

# Load your OHLCV data
df = pd.read_csv("data/BTC_5m.csv")

# Add required indicators
df["atr"] = df["close"] * 0.02  # 2% ATR
df["ema_50"] = df["close"].ewm(span=50).mean()
df["ema_200"] = df["close"].ewm(span=200).mean()

# Detect regime
regime = router.detect_regime(
    ohlcv_df=df,
    funding_rate=0.0001,  # Current funding rate
    sentiment=0.3,        # Optional sentiment score
)

print(f"Regime: {regime.dominant_regime}")
print(f"Confidence: {regime.confidence:.2%}")
print(f"Volatility: {regime.volatility_index:.1f}")
print(f"Trend: {regime.trend_strength:.2f}")

# Get strategy weights
strategies = router.get_weighted_strategies(regime)
for s in strategies:
    print(f"{s.strategy_name}: {s.final_weight:.2%}")

# Get risk multiplier
risk_mult = router.get_risk_multiplier(regime)
print(f"Position size multiplier: {risk_mult:.2f}x")
```

---

### 2. Enhanced ML Predictor

```python
from ml.predictor_v2 import EnhancedPredictorV2
from pathlib import Path

# Load trained model
predictor = EnhancedPredictorV2(
    model_path=Path("models/predictor_v2.pkl")
)

# Create context
ctx = {
    "ohlcv_df": df,                    # Your OHLCV data
    "current_price": 50000.0,
    "timeframe": "5m",
    "funding_rate": 0.0001,            # Optional
    "sentiment_df": sentiment_df,      # Optional
    "bid_depth": {49990: 1000},        # Optional
    "ask_depth": {50010: 300},         # Optional
}

# Get prediction
prob = predictor.predict_proba(ctx)
print(f"Upward probability: {prob:.1%}")

# Decision logic
if prob >= 0.65:
    print("HIGH confidence - Enter long")
elif prob >= 0.55:
    print("MEDIUM confidence - Enter long (smaller size)")
elif prob <= 0.35:
    print("HIGH confidence - Enter short")
else:
    print("NEUTRAL - No trade")

# Feature importance
importance = predictor.get_feature_importance()
top_5 = sorted(importance.items(), key=lambda x: -x[1])[:5]
print("\nTop 5 features:")
for feat, score in top_5:
    print(f"  {feat}: {score:.1f}")
```

---

### 3. Whale Detection

```python
from ai_engine.whale_detection import detect_whale_flow, calculate_whale_pressure

# Detect whale activity
metrics = detect_whale_flow(
    df=df,
    price=50000.0,
    volume=150.0,
    bid_depth={49990: 1000, 49980: 500},  # Optional
    ask_depth={50010: 300, 50020: 200},    # Optional
)

print(f"Whale inflow: {metrics.inflow_ratio:.2%}")
print(f"Whale outflow: {metrics.outflow_ratio:.2%}")
print(f"Net flow: {metrics.net_flow:+.2f}")
print(f"Order book imbalance: {metrics.order_book_imbalance:+.2f}")
print(f"Smart money divergence: {metrics.smart_money_divergence:+.2f}")

# Calculate overall pressure
pressure, explanation = calculate_whale_pressure(
    whale_metrics=metrics,
    funding_rate=0.0001,
)

print(f"\nWhale pressure: {pressure:+.2f}")
print(f"Explanation: {explanation}")
```

---

### 4. Liquidations Tracker

```python
from ai_engine.liquidations_tracker import LiquidationsTracker, interpret_liquidation_signal

# Initialize tracker
tracker = LiquidationsTracker(
    window_minutes=60,
    cascade_threshold=5,
)

# Add liquidation events (from exchange feed)
tracker.add_liquidation_event(
    timestamp=1641234567000,
    side="long",
    amount_usd=100000,
    price=49500,
)

tracker.add_liquidation_event(
    timestamp=1641234627000,
    side="long",
    amount_usd=150000,
    price=49300,
)

# Add funding rate
tracker.add_funding_rate(0.0001)

# Analyze
metrics = tracker.analyze_liquidations(
    current_timestamp=1641234687000,
    current_funding_rate=0.00015,
)

print(f"Long liquidations: ${metrics.long_liquidations:,.0f}")
print(f"Short liquidations: ${metrics.short_liquidations:,.0f}")
print(f"Imbalance: {metrics.imbalance:+.2f}")
print(f"Cascade detected: {metrics.cascade_detected}")
print(f"Liquidation pressure: {metrics.liquidation_pressure:+.2f}")

# Interpretation
interpretation = interpret_liquidation_signal(metrics)
print(f"\nInterpretation: {interpretation}")

# Estimate liquidation levels
levels = tracker.estimate_liquidation_levels(
    current_price=50000,
    leverage_levels=[10, 20, 50, 100],
)
print(f"Long liq levels: {levels['long_liquidation_levels']}")
print(f"Short liq levels: {levels['short_liquidation_levels']}")
```

---

## 🔧 Configuration

### Regime Map (config/regime_map.yaml)

Customize regime detection thresholds:

```yaml
detection:
  volatility:
    low_threshold: 20      # VIX < 20 = low vol
    normal_max: 40
    elevated_max: 60
    high_max: 80

  trend:
    strong_bull: 0.7       # Trend > 0.7 = strong bull
    moderate_bull: 0.4
    moderate_bear: 0.3
    strong_bear: 0.0

  funding:
    very_bullish: 0.0001   # > 0.01% per 8h
    bullish: 0.00005
    neutral_min: -0.00005
    bearish: -0.0001
```

Customize strategy preferences per regime:

```yaml
regimes:
  hyper_bull:
    strategies:
      primary:
        - name: "trend_following"
          weight: 0.6        # 60% allocation
          config:
            trigger_bps: 8.0
            sl_atr: 1.2
            tp_atr: 2.5
```

Customize adaptive blending:

```yaml
adaptive_blending:
  lookback_days: 90
  metrics:
    sharpe_weight: 0.4      # 40% weight to Sharpe
    profit_factor_weight: 0.4
    win_rate_weight: 0.2
  thresholds:
    min_sharpe: 0.5         # Disable if Sharpe < 0.5
    min_profit_factor: 1.0  # Disable if PF < 1.0
```

---

## 🎯 Integration Patterns

### Pattern 1: Regime-Based Strategy Selection

```python
# In your main trading loop
regime = router.detect_regime(ohlcv_df, funding_rate, sentiment)
strategies = router.get_weighted_strategies(regime)

# Execute top 3 strategies
for strategy_weight in strategies[:3]:
    if strategy_weight.final_weight >= 0.1:  # Min 10% weight
        position_size = base_position_size * strategy_weight.final_weight
        risk_mult = router.get_risk_multiplier(regime)

        execute_strategy(
            name=strategy_weight.strategy_name,
            config=strategy_weight.config,
            position_size=position_size * risk_mult,
        )
```

### Pattern 2: ML-Based Signal Filtering

```python
# In signal generation
def should_enter_trade(signal, ctx):
    # Get ML probability
    prob = predictor.predict_proba(ctx)

    # Filter low confidence
    if prob < 0.55:
        logger.info("ML rejected signal (prob=%.2f)", prob)
        return False

    # Boost position size for high confidence
    if prob >= 0.65:
        signal["position_multiplier"] = 1.5
    elif prob >= 0.60:
        signal["position_multiplier"] = 1.2
    else:
        signal["position_multiplier"] = 1.0

    return True
```

### Pattern 3: Whale Flow Confirmation

```python
# Add whale flow as confirmation signal
whale_metrics = detect_whale_flow(df, price, volume, bid_depth, ask_depth)
pressure, _ = calculate_whale_pressure(whale_metrics, funding_rate)

# Require whale confirmation for entries
if signal_direction == "long" and pressure > 0.3:
    # Whales buying, confirm long
    confidence_boost = 1.2
elif signal_direction == "short" and pressure < -0.3:
    # Whales selling, confirm short
    confidence_boost = 1.2
else:
    # No whale confirmation, reduce size
    confidence_boost = 0.7

signal["position_multiplier"] *= confidence_boost
```

### Pattern 4: Liquidation-Based Risk Management

```python
# Reduce exposure during liquidation cascades
liq_metrics = tracker.analyze_liquidations(current_timestamp, funding_rate)

if liq_metrics.cascade_detected:
    if liq_metrics.cascade_severity > 0.7:
        # Extreme cascade - pause trading
        logger.warning("Extreme liquidation cascade, pausing trades")
        return None
    else:
        # Moderate cascade - reduce size
        signal["position_multiplier"] *= 0.5

# Use liquidation pressure as signal
if abs(liq_metrics.liquidation_pressure) > 0.5:
    # Strong pressure in one direction
    if signal_direction == "long" and liq_metrics.liquidation_pressure > 0.5:
        # Shorts liquidating, boost long
        signal["position_multiplier"] *= 1.3
```

---

## 📈 Performance Monitoring

### Track Regime Performance

```python
# After each trade closes
await router.update_strategy_performance(
    strategy_name="trend_following",
    sharpe=1.45,
    profit_factor=1.82,
    win_rate=58.3,
    total_trades=120,
)

# This updates Redis and adjusts future weights automatically
```

### Monitor Feature Importance

```python
# Periodically check which features are most predictive
importance = predictor.get_feature_importance()

print("Feature importance:")
for feat, score in sorted(importance.items(), key=lambda x: -x[1]):
    print(f"  {feat}: {score:.1f}")

# If importance shifts dramatically, consider retraining
```

---

## 🐛 Troubleshooting

### Issue: "LightGBM not available"

```bash
# Install LightGBM
pip install lightgbm

# Verify
python -c "import lightgbm; print('OK')"
```

### Issue: "Model file not found"

```bash
# Train model first
python scripts/train_predictor_v2.py

# Verify model exists
ls -lh models/predictor_v2.pkl
```

### Issue: "Insufficient data for regime detection"

```python
# Ensure OHLCV has enough bars (100+ recommended)
print(f"OHLCV bars: {len(df)}")

# Add required indicators
df["atr"] = df["close"] * 0.02
df["ema_50"] = df["close"].ewm(span=50).mean()
df["ema_200"] = df["close"].ewm(span=200).mean()
```

### Issue: "Redis connection failed"

```python
# Router works without Redis (uses in-memory cache)
router = AdaptiveRegimeRouter(
    config_path="config/regime_map.yaml",
    redis_url=None,  # Disable Redis
)
```

---

## 📚 Further Reading

- **Full Implementation:** `PROMPT_1-2_IMPLEMENTATION_COMPLETE.md`
- **Profitability Plan:** `PROFITABILITY_OPTIMIZATION_PLAN.md`
- **Gap Analysis:** `PROFITABILITY_GAP_ANALYSIS.md`
- **Regime Map Config:** `config/regime_map.yaml`

---

## ✅ Next Actions

1. **Run self-checks** to verify all modules work
2. **Train predictor** on your historical data
3. **Run comparison** to measure uplift
4. **Integrate** into your main trading system
5. **Monitor** performance and adjust weights

**Questions?** Review full documentation in `PROMPT_1-2_IMPLEMENTATION_COMPLETE.md`

---

**End of Quick Start Guide**
