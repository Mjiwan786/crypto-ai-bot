# Safety Controls and Risk Management

**Version:** 1.0.0
**Last Updated:** 2025-11-17
**Platform:** AI-Predicted-Signals

---

## Table of Contents

1. [Overview](#overview)
2. [Risk Management Framework](#risk-management-framework)
3. [Position Sizing](#position-sizing)
4. [Stop-Loss Enforcement](#stop-loss-enforcement)
5. [Drawdown Protection](#drawdown-protection)
6. [Confidence Thresholds](#confidence-thresholds)
7. [API Rate Limiting](#api-rate-limiting)
8. [Performance Monitoring](#performance-monitoring)
9. [Circuit Breakers](#circuit-breakers)
10. [Emergency Procedures](#emergency-procedures)
11. [Configuration](#configuration)
12. [Best Practices](#best-practices)

---

## Overview

The AI-Predicted-Signals platform implements comprehensive safety controls and risk management to protect traders from excessive losses and ensure system stability.

**Key Principles:**

1. **Capital Preservation**: Limit maximum loss to preserve trading capital
2. **Risk-Adjusted Position Sizing**: Size positions based on confidence and account equity
3. **Automatic Stop-Loss**: Enforce stop-losses on all positions
4. **Drawdown Limits**: Halt trading if maximum drawdown exceeded
5. **Performance Monitoring**: Continuous monitoring for anomalies
6. **Graceful Degradation**: Safe operation even under adverse conditions

**Protection Layers:**

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Confidence Filtering (60% minimum)             │
├─────────────────────────────────────────────────────────┤
│ Layer 2: Position Sizing (0.5% - 5% per trade)          │
├─────────────────────────────────────────────────────────┤
│ Layer 3: Stop-Loss Enforcement (0.5% - 5% max)          │
├─────────────────────────────────────────────────────────┤
│ Layer 4: Drawdown Limits (10% maximum)                  │
├─────────────────────────────────────────────────────────┤
│ Layer 5: Circuit Breakers (consecutive loss limits)     │
├─────────────────────────────────────────────────────────┤
│ Layer 6: Emergency Stop (manual kill switch)            │
└─────────────────────────────────────────────────────────┘
```

---

## Risk Management Framework

### 1. Three-Tier Risk Model

The platform uses a three-tier risk classification system:

#### Conservative (Paper Trading Default)

- **Max Position Size**: 0.5% of equity per trade
- **Stop Loss**: 0.5% - 1.0%
- **Confidence Threshold**: 75%
- **Max Drawdown**: 5%
- **Max Exposure**: 1.5% of equity (3 positions)

#### Moderate (Recommended for Live Trading)

- **Max Position Size**: 2.0% of equity per trade
- **Stop Loss**: 1.0% - 2.0%
- **Confidence Threshold**: 70%
- **Max Drawdown**: 10%
- **Max Exposure**: 6% of equity (3 positions)

#### Aggressive (Experienced Traders Only)

- **Max Position Size**: 5.0% of equity per trade
- **Stop Loss**: 2.0% - 5.0%
- **Confidence Threshold**: 60%
- **Max Drawdown**: 15%
- **Max Exposure**: 15% of equity (3 positions)

**Default Configuration:** Conservative (can be changed via environment variables)

### 2. Dynamic Risk Adjustment

Position sizes and stop-losses adjust dynamically based on:

1. **Signal Confidence**: Higher confidence = larger position size
2. **Market Volatility**: Higher volatility = wider stop-loss
3. **Current Drawdown**: Larger drawdown = smaller positions
4. **Regime Detection**: Different regimes = different risk parameters

---

## Position Sizing

### Confidence-Based Position Sizing

Position size is calculated based on signal confidence:

```python
# Position Sizing Formula
if confidence >= 0.85:
    position_size = 0.75  # 75% of max allowed
elif confidence >= 0.75:
    position_size = 0.60  # 60% of max allowed
elif confidence >= 0.65:
    position_size = 0.40  # 40% of max allowed
else:
    position_size = 0.25  # 25% of max allowed (or filtered)

# Apply max position limit
position_size = min(position_size, MAX_POSITION_SIZE)
```

**Example:**

```
Max Position Size: 2.0% of equity
Current Equity: $10,000
Signal Confidence: 85%

Calculated Position Size: 0.75 * 0.02 * $10,000 = $150
```

### Maximum Exposure Limit

Total exposure across all open positions is capped:

```python
total_exposure = sum([position.size for position in open_positions])

if total_exposure >= MAX_TOTAL_EXPOSURE:
    reject_new_position()
```

**Default Limits:**

- **Conservative**: 1.5% total exposure (max 3 positions @ 0.5% each)
- **Moderate**: 6% total exposure (max 3 positions @ 2% each)
- **Aggressive**: 15% total exposure (max 3 positions @ 5% each)

### Position Size Validation

Before entering any position:

```python
def validate_position_size(position_size, equity):
    """Validate position size against limits"""

    # Check minimum
    if position_size < MIN_POSITION_SIZE:
        return False, "Position too small"

    # Check maximum
    if position_size > MAX_POSITION_SIZE * equity:
        return False, "Position exceeds maximum"

    # Check total exposure
    total_exposure = calculate_total_exposure()
    if total_exposure + position_size > MAX_TOTAL_EXPOSURE * equity:
        return False, "Total exposure limit exceeded"

    return True, "Valid"
```

---

## Stop-Loss Enforcement

### Automatic Stop-Loss Calculation

Every signal includes calculated stop-loss based on:

1. **Volatility**: ATR (Average True Range) for the trading pair
2. **Confidence**: Higher confidence = tighter stop-loss
3. **Regime**: Different regimes require different stop-losses

```python
def calculate_stop_loss(volatility, confidence, regime):
    """Calculate dynamic stop-loss"""

    # Base stop-loss from volatility
    base_sl = volatility * 2.0  # 2x ATR

    # Adjust for confidence
    if confidence >= 0.85:
        confidence_multiplier = 0.8  # Tighter SL for high confidence
    elif confidence >= 0.75:
        confidence_multiplier = 1.0
    else:
        confidence_multiplier = 1.2  # Wider SL for lower confidence

    # Adjust for regime
    if regime in ["volatile", "trending"]:
        regime_multiplier = 1.2  # Wider SL in volatile markets
    else:
        regime_multiplier = 1.0

    stop_loss = base_sl * confidence_multiplier * regime_multiplier

    # Enforce limits
    stop_loss = max(MIN_STOP_LOSS, min(stop_loss, MAX_STOP_LOSS))

    return stop_loss
```

**Example:**

```
Volatility (ATR): 1.0%
Confidence: 80%
Regime: Trending

Base SL: 1.0% * 2.0 = 2.0%
Confidence Adj: 2.0% * 1.0 = 2.0%
Regime Adj: 2.0% * 1.2 = 2.4%

Final Stop-Loss: 2.4%
```

### Stop-Loss Types

The platform supports multiple stop-loss types:

1. **Fixed Percentage Stop**
   - Fixed % below entry price
   - Simple and predictable
   - Example: 2% stop-loss

2. **Trailing Stop**
   - Adjusts upward as price moves favorably
   - Locks in profits while allowing upside
   - Example: 2% trailing stop

3. **ATR-Based Stop**
   - Based on Average True Range
   - Adapts to volatility
   - Example: 2x ATR

4. **Support/Resistance Stop**
   - Placed below/above key levels
   - Reduces false stops
   - Example: Below recent swing low

**Default:** Fixed Percentage Stop (most reliable)

### Stop-Loss Validation

Before entering position:

```python
def validate_stop_loss(entry_price, stop_loss_price, side):
    """Validate stop-loss is valid"""

    if side == "LONG":
        stop_loss_pct = abs((stop_loss_price - entry_price) / entry_price)

        if stop_loss_price >= entry_price:
            return False, "Stop-loss must be below entry for LONG"

    elif side == "SHORT":
        stop_loss_pct = abs((entry_price - stop_loss_price) / entry_price)

        if stop_loss_price <= entry_price:
            return False, "Stop-loss must be above entry for SHORT"

    # Validate within limits
    if stop_loss_pct < MIN_STOP_LOSS:
        return False, f"Stop-loss too tight (min: {MIN_STOP_LOSS}%)"

    if stop_loss_pct > MAX_STOP_LOSS:
        return False, f"Stop-loss too wide (max: {MAX_STOP_LOSS}%)"

    return True, "Valid"
```

---

## Drawdown Protection

### Maximum Drawdown Limit

Trading halts automatically if maximum drawdown is exceeded:

```python
def check_drawdown(current_equity, peak_equity):
    """Check if drawdown limit exceeded"""

    drawdown = (peak_equity - current_equity) / peak_equity
    drawdown_pct = drawdown * 100

    if drawdown_pct >= MAX_DRAWDOWN_PCT:
        halt_trading()
        send_alert(f"Maximum drawdown exceeded: {drawdown_pct:.2f}%")
        return True

    return False
```

**Default Limits:**

- **Conservative**: 5% maximum drawdown
- **Moderate**: 10% maximum drawdown
- **Aggressive**: 15% maximum drawdown

**Example:**

```
Peak Equity: $10,000
Current Equity: $9,000
Drawdown: ($10,000 - $9,000) / $10,000 = 10%

Action: If max drawdown = 10%, trading HALTS
```

### Drawdown Recovery Mode

After hitting maximum drawdown:

1. **Trading Halts**: No new positions opened
2. **Existing Positions**: Closed or allowed to hit stop-loss
3. **Alert Sent**: Notification to user and monitoring systems
4. **Manual Review Required**: User must manually re-enable trading
5. **Recovery Period**: System enters reduced-risk mode

**Re-enabling Trading After Drawdown:**

```bash
# Manual confirmation required
export DRAWDOWN_OVERRIDE="confirmed"

# Restart system
python main.py --mode paper --recovery-mode

# System enters recovery mode:
# - Reduced position sizes (50% of normal)
# - Higher confidence threshold (80%)
# - Tighter stop-losses (50% of normal)
```

---

## Confidence Thresholds

### Minimum Confidence Filter

Signals below confidence threshold are automatically filtered:

```python
def filter_by_confidence(signal, min_confidence):
    """Filter signals by minimum confidence"""

    if signal["confidence"] < min_confidence:
        logger.info(f"Signal filtered: confidence {signal['confidence']:.2f} < {min_confidence:.2f}")
        return None

    return signal
```

**Default Thresholds:**

- **Conservative**: 75% minimum confidence
- **Moderate**: 70% minimum confidence
- **Aggressive**: 60% minimum confidence

### Confidence Levels

Signals are classified into confidence tiers:

```python
def get_confidence_level(confidence):
    """Classify signal confidence"""

    if confidence >= 0.85:
        return "very_high"
    elif confidence >= 0.75:
        return "high"
    elif confidence >= 0.65:
        return "medium"
    elif confidence >= 0.55:
        return "low"
    else:
        return "very_low"
```

**Recommended Actions:**

- **Very High (>85%)**: Trade with maximum position size
- **High (75-85%)**: Trade with standard position size
- **Medium (65-75%)**: Trade with reduced position size or skip
- **Low (<65%)**: Skip (automatically filtered)

---

## API Rate Limiting

### Rate Limit Configuration

Protects API from abuse and ensures fair access:

```python
# Rate Limits
PUBLIC_ENDPOINT_LIMIT = 100  # requests per minute per IP
PROTECTED_ENDPOINT_LIMIT = 60  # requests per minute per user
SSE_CONNECTION_LIMIT = 5  # concurrent SSE connections per IP
```

### Rate Limit Implementation

```python
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/v1/signals")
@limiter.limit("100/minute")
async def get_signals(request: Request, n: int = 500):
    """Get trading signals with rate limit"""
    ...
```

### Rate Limit Responses

When rate limit exceeded:

```json
{
  "detail": "Rate limit exceeded. Try again in 60 seconds.",
  "status_code": 429,
  "headers": {
    "X-RateLimit-Limit": "100",
    "X-RateLimit-Remaining": "0",
    "X-RateLimit-Reset": "1640995260"
  }
}
```

### Bypass Rate Limits (Authenticated Users)

Authenticated users get higher rate limits:

```python
@app.get("/v1/user/signals")
@limiter.limit("300/minute")  # 3x normal limit
async def get_user_signals(request: Request, token: str = Depends(verify_jwt)):
    """Get signals with higher rate limit for authenticated users"""
    ...
```

---

## Performance Monitoring

### Real-Time Metrics

The platform continuously monitors:

1. **Model Inference Latency**: <100ms target
2. **API Response Time**: <500ms target
3. **End-to-End Signal Flow**: <1s target
4. **Redis Stream Lag**: <1s target
5. **Error Rate**: <0.1% target
6. **Signal Accuracy**: Tracked vs. actual outcomes

### Anomaly Detection

Automatic detection of anomalies:

```python
def detect_anomaly(metric_name, current_value, historical_mean, historical_std):
    """Detect if metric is anomalous (>3 std deviations)"""

    z_score = abs((current_value - historical_mean) / historical_std)

    if z_score > 3.0:
        send_alert(f"Anomaly detected: {metric_name} = {current_value} (z-score: {z_score:.2f})")
        return True

    return False
```

**Monitored Anomalies:**

- Sudden drop in signal confidence
- Spike in error rate
- Increase in latency (>2x normal)
- Unusual trading volume
- Abnormal win/loss ratio

### Alert Thresholds

```python
# Alert Configuration
ALERT_THRESHOLDS = {
    "model_latency_ms": 200,        # Alert if >200ms
    "api_latency_ms": 1000,         # Alert if >1s
    "error_rate_pct": 1.0,          # Alert if >1%
    "redis_lag_s": 5,               # Alert if >5s lag
    "win_rate_drop_pct": 20,        # Alert if win rate drops >20%
    "drawdown_warning_pct": 7.5,    # Alert at 75% of max drawdown
}
```

### Monitoring Dashboard

Access real-time metrics:

```bash
# Prometheus metrics
curl https://signals-api-gateway.fly.dev/metrics

# Service metrics (JSON)
curl https://signals-api-gateway.fly.dev/metrics/service
```

---

## Circuit Breakers

### Consecutive Loss Circuit Breaker

Halts trading after consecutive losses:

```python
def check_consecutive_losses(recent_trades):
    """Check for consecutive losses and trigger circuit breaker"""

    consecutive_losses = 0

    for trade in recent_trades:
        if trade["pnl"] < 0:
            consecutive_losses += 1
        else:
            consecutive_losses = 0

        if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            activate_circuit_breaker("consecutive_losses")
            return True

    return False
```

**Default Limit:** 3 consecutive losses

**Action:**

1. Trading halted for cooldown period (default: 5 minutes)
2. Alert sent to user
3. System review required before resuming

### Rapid Loss Circuit Breaker

Halts trading if losses accumulate too quickly:

```python
def check_rapid_loss(equity_history, time_window_minutes=60):
    """Check for rapid loss within time window"""

    start_equity = equity_history.get_equity_at(time.now() - timedelta(minutes=time_window_minutes))
    current_equity = equity_history.current_equity

    loss_pct = ((start_equity - current_equity) / start_equity) * 100

    if loss_pct >= RAPID_LOSS_THRESHOLD:
        activate_circuit_breaker("rapid_loss")
        return True

    return False
```

**Default Threshold:** 5% loss in 60 minutes

### Circuit Breaker Recovery

After circuit breaker activation:

```bash
# Circuit breaker active for cooldown period
[2025-11-17 12:00:00] WARNING: Circuit breaker activated: consecutive_losses
[2025-11-17 12:00:00] INFO: Cooldown period: 5 minutes
[2025-11-17 12:00:00] INFO: Trading halted

# After cooldown
[2025-11-17 12:05:00] INFO: Cooldown period expired
[2025-11-17 12:05:00] INFO: Manual review required before resuming

# Manual resume (if conditions OK)
export CIRCUIT_BREAKER_OVERRIDE="confirmed"
python main.py --mode paper
```

---

## Emergency Procedures

### Emergency Stop

Immediate halt of all trading activities:

**Method 1: File-Based Kill Switch**

```bash
# Create emergency stop file
touch /app/emergency_stop.flag

# System detects and halts
[2025-11-17 12:00:00] CRITICAL: Emergency stop detected
[2025-11-17 12:00:00] INFO: Closing all positions
[2025-11-17 12:00:00] INFO: Halting signal generation
[2025-11-17 12:00:00] INFO: System shutdown initiated
```

**Method 2: Environment Variable**

```bash
# Set emergency stop
export EMERGENCY_STOP=true

# Restart system (will halt immediately)
python main.py
```

**Method 3: API Endpoint (if available)**

```bash
# POST to emergency stop endpoint
curl -X POST https://signals-api-gateway.fly.dev/admin/emergency-stop \
  -H "Authorization: Bearer <admin_token>"
```

### Position Liquidation

Close all open positions:

```bash
# Close all positions immediately (market orders)
python scripts/close_all_positions.py --mode immediate

# Close all positions gradually (limit orders)
python scripts/close_all_positions.py --mode gradual
```

### System Recovery

After emergency stop:

1. **Review logs** for cause of emergency
2. **Analyze positions** closed during emergency
3. **Verify system integrity** (models, data, connectivity)
4. **Adjust risk parameters** if needed
5. **Test in paper mode** before resuming live
6. **Manual confirmation** required to resume

```bash
# Resume after emergency stop
rm /app/emergency_stop.flag  # Remove kill switch
export EMERGENCY_STOP=false  # Clear env var

# Restart in paper mode for validation
python main.py --mode paper --validation-period 3600  # 1 hour

# After validation, resume live trading
python main.py --mode live
```

---

## Configuration

### Environment Variables

All safety controls are configurable via environment variables:

```bash
# Position Sizing
MAX_POSITION_SIZE=0.02              # 2% per trade
MIN_POSITION_SIZE=0.001             # 0.1% minimum
MAX_TOTAL_EXPOSURE=0.06             # 6% total

# Stop-Loss
MIN_STOP_LOSS=0.005                 # 0.5% minimum
MAX_STOP_LOSS=0.05                  # 5% maximum

# Drawdown
MAX_DRAWDOWN_PCT=10.0               # 10% maximum

# Confidence
CONFIDENCE_THRESHOLD=0.70           # 70% minimum

# Circuit Breakers
MAX_CONSECUTIVE_LOSSES=3            # 3 losses
RAPID_LOSS_THRESHOLD=5.0            # 5% in 1 hour
CIRCUIT_BREAKER_COOLDOWN=300        # 5 minutes

# Monitoring
ENABLE_LATENCY_TRACKING=true
LATENCY_MS_MAX=100.0
ENABLE_ANOMALY_DETECTION=true
```

### Risk Profiles

Pre-configured risk profiles:

**Conservative Profile:**

```bash
cp config/risk_conservative.env .env.risk
```

**Moderate Profile:**

```bash
cp config/risk_moderate.env .env.risk
```

**Aggressive Profile:**

```bash
cp config/risk_aggressive.env .env.risk
```

### Custom Configuration

Create custom risk profile:

```bash
# Copy template
cp config/risk_template.env .env.risk.custom

# Edit parameters
nano .env.risk.custom

# Apply custom profile
export RISK_PROFILE=custom
python main.py --risk-config .env.risk.custom
```

---

## Best Practices

### For Paper Trading

1. ✅ Start with conservative risk settings
2. ✅ Monitor performance for at least 30 days
3. ✅ Track win rate, Sharpe ratio, max drawdown
4. ✅ Adjust risk parameters based on results
5. ✅ Test different confidence thresholds
6. ✅ Validate stop-loss effectiveness

### For Live Trading

1. ✅ Complete at least 30 days of paper trading
2. ✅ Start with smallest allowed position sizes
3. ✅ Never exceed recommended risk limits
4. ✅ Always use stop-losses (no exceptions)
5. ✅ Monitor drawdown closely
6. ✅ Have emergency stop procedure ready
7. ✅ Keep sufficient capital reserves (don't use all funds)
8. ✅ Review performance weekly

### For System Operators

1. ✅ Enable all monitoring and alerts
2. ✅ Set up Prometheus + Grafana dashboards
3. ✅ Configure alert notifications (Discord, email, SMS)
4. ✅ Regularly review logs for anomalies
5. ✅ Test circuit breakers in paper mode
6. ✅ Document all emergency procedures
7. ✅ Maintain backup configurations
8. ✅ Keep system updated with latest fixes

### General Guidelines

1. ✅ **Never disable safety controls** in production
2. ✅ **Always test changes** in paper mode first
3. ✅ **Keep detailed logs** of all trades and system events
4. ✅ **Regularly back up** configuration and data
5. ✅ **Monitor continuously** for anomalies
6. ✅ **Adjust risk** based on market conditions
7. ✅ **Respect drawdown limits** - don't override without good reason
8. ✅ **Have an exit strategy** - know when to stop

---

## Support

### Documentation

- **[PLATFORM_OVERVIEW.md](../../PLATFORM_OVERVIEW.md)** - Platform overview
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System architecture
- **[SETUP_GUIDE.md](SETUP_GUIDE.md)** - Setup instructions

### Contact

- **GitHub Issues**: Report issues with `[SAFETY]` prefix
- **Email Support**: Support email provided in handoff package
- **30-Day Support**: Contact support team

### Emergency Contact

For critical issues requiring immediate attention:

- **Emergency Email**: Provided in handoff package
- **Emergency Stop**: See [Emergency Procedures](#emergency-procedures)

---

**Document Version:** 1.0.0
**Last Updated:** 2025-11-17
**Status:** ✅ PRODUCTION READY

**IMPORTANT:** Safety controls are designed to protect your capital. Never disable or circumvent them without fully understanding the risks.
