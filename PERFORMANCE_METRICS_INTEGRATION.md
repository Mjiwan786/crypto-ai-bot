# Performance Metrics Integration Guide

## Overview

Real-time performance metrics for monitoring trading system health and progress towards equity targets.

**Metrics Calculated:**
1. **Aggressive Mode Score** = `(win_rate * avg_win) / (loss_rate * avg_loss)`
   - Risk-adjusted performance measure
   - Higher is better (>2.0 = Excellent)

2. **Velocity to Target** = `(current_equity - starting) / (target - starting)`
   - Progress towards equity goal (0.0 to 1.0+)
   - Example: 0.045 = 4.5% progress

3. **Days Remaining Estimate** = `(target - current) / daily_rate`
   - Projected time to reach target
   - Based on current daily profit rate

## Quick Start

### 1. Enable Feature Flag

Add to `.env` or set in environment:

```bash
# Enable performance metrics
ENABLE_PERFORMANCE_METRICS=true

# Configure equity targets
STARTING_EQUITY_USD=10000
TARGET_EQUITY_USD=20000
```

### 2. Integration Example

```python
from metrics import create_metrics_publisher

# In your main orchestrator or agent initialization
def initialize_trading_system():
    # ... existing setup ...

    # Create metrics publisher
    metrics_publisher = create_metrics_publisher(
        redis_manager=redis_client,
        trade_manager=trade_manager,
        equity_tracker=equity_tracker,
        logger=logger,
        update_interval=30,  # Update every 30 seconds
        auto_start=True,     # Start background publishing
    )

    # Store reference for shutdown
    self.metrics_publisher = metrics_publisher
```

### 3. Shutdown Handling

```python
def shutdown(self):
    # Stop metrics publishing
    if hasattr(self, 'metrics_publisher'):
        self.metrics_publisher.stop()
```

## Full Integration

### Option 1: With Trade Manager & Equity Tracker

```python
import logging
from metrics import MetricsPublisher
from agents.infrastructure.redis_client import RedisCloudClient

# Initialize components
redis_client = RedisCloudClient(...)
trade_manager = TradeManager(...)
equity_tracker = EquityTracker(...)
logger = logging.getLogger(__name__)

# Create metrics publisher
metrics_publisher = MetricsPublisher(
    redis_manager=redis_client,
    trade_manager=trade_manager,
    equity_tracker=equity_tracker,
    logger=logger,
    update_interval=30,
)

# Start publishing
metrics_publisher.start()

# Get latest metrics on-demand
summary = metrics_publisher.get_latest_summary()
print(f"Aggressive Score: {summary['aggressive_mode_score']['value']:.2f}")
print(f"Velocity: {summary['velocity_to_target']['percent']:.1f}%")
```

### Option 2: Standalone (Redis-Only)

If you don't have trade_manager or equity_tracker:

```python
from metrics import MetricsPublisher

# Publisher will fall back to reading trades from Redis
metrics_publisher = MetricsPublisher(
    redis_manager=redis_client,
    trade_manager=None,      # Falls back to Redis
    equity_tracker=None,     # Calculates from trades
    logger=logger,
    update_interval=30,
)

metrics_publisher.start()
```

### Option 3: Manual Updates

For one-time calculations without background thread:

```python
from metrics import PerformanceMetricsCalculator

calculator = PerformanceMetricsCalculator(
    redis_manager=redis_client,
    starting_equity=10000.0,
    target_equity=20000.0,
)

# Get trades and current equity
trades = trade_manager.get_closed_trades()
current_equity = equity_tracker.get_current_equity()

# Calculate metrics
metrics = calculator.calculate_metrics(trades, current_equity)

print(f"Aggressive Score: {metrics.aggressive_mode_score:.2f}")
print(f"Velocity: {metrics.velocity_to_target:.1%}")
print(f"Days Remaining: {metrics.days_remaining_estimate:.1f}")
```

## Redis Streams Published

The metrics are published to the following Redis streams:

```
metrics:performance              # Complete metrics snapshot
metrics:aggressive_mode_score    # Individual metric
metrics:velocity_to_target       # Individual metric
metrics:days_remaining           # Individual metric
```

**Event Format:**

```json
{
  "timestamp": 1699999999.0,
  "aggressive_mode_score": 2.60,
  "win_rate": 0.60,
  "loss_rate": 0.40,
  "avg_win_usd": 61.0,
  "avg_loss_usd": 35.25,
  "velocity_to_target": 0.045,
  "current_equity_usd": 10450.0,
  "target_equity_usd": 20000.0,
  "starting_equity_usd": 10000.0,
  "days_remaining_estimate": 106.1,
  "daily_rate_usd": 90.0,
  "days_elapsed": 5.0,
  "total_trades": 20,
  "winning_trades": 12,
  "losing_trades": 8,
  "total_pnl_usd": 450.0
}
```

## Prometheus Metrics

The following metrics are exported at `/metrics`:

```prometheus
# Aggressive mode score (risk-adjusted performance)
aggressive_mode_score 2.60

# Velocity to target (0.0 to 1.0+)
velocity_to_target 0.045

# Days remaining estimate
days_remaining_estimate 106.1

# Current equity in USD
current_equity_usd 10450.0

# Daily profit rate in USD
daily_rate_usd 90.0

# Win rate percentage
win_rate_percent 60.0
```

## Configuration

### Environment Variables

```bash
# Feature flag (default: true)
ENABLE_PERFORMANCE_METRICS=true

# Equity targets (default: 10k -> 20k)
STARTING_EQUITY_USD=10000
TARGET_EQUITY_USD=20000
```

### Constructor Parameters

```python
MetricsPublisher(
    redis_manager=None,      # Redis client for publishing
    trade_manager=None,      # Trade manager for getting closed trades
    equity_tracker=None,     # Equity tracker for current balance
    logger=None,             # Logger instance
    update_interval=30,      # Update frequency in seconds
)
```

## Integration Points

### In Main Orchestrator

```python
# orchestration/master_orchestrator.py

class MasterOrchestrator:
    def __init__(self, ...):
        # ... existing setup ...

        # Add metrics publisher
        from metrics import create_metrics_publisher
        self.metrics_publisher = create_metrics_publisher(
            redis_manager=self.redis,
            trade_manager=self.trade_manager,
            equity_tracker=self.equity_tracker,
            logger=self.logger,
            update_interval=30,
            auto_start=True,
        )

    def shutdown(self):
        # ... existing shutdown ...

        # Stop metrics
        if self.metrics_publisher:
            self.metrics_publisher.stop()
```

### In Enhanced Trading Agent

```python
# base/enhanced_trading_agent.py

class EnhancedTradingAgent:
    def __init__(self, ...):
        # ... existing setup ...

        # Add metrics publisher
        from metrics import create_metrics_publisher
        self.metrics_publisher = create_metrics_publisher(
            redis_manager=self.redis,
            trade_manager=self.trade_manager,
            equity_tracker=None,  # Will calculate from trades
            logger=self.logger,
            update_interval=30,
            auto_start=True,
        )
```

### Standalone Service

```python
# scripts/run_metrics_publisher.py

import os
import time
import logging
from metrics import create_metrics_publisher
from agents.infrastructure.redis_client import RedisCloudClient

# Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

redis_client = RedisCloudClient()

# Create publisher (Redis-only mode)
publisher = create_metrics_publisher(
    redis_manager=redis_client,
    trade_manager=None,      # Falls back to Redis
    equity_tracker=None,     # Calculates from trades
    logger=logger,
    update_interval=30,
    auto_start=True,
)

logger.info("Metrics publisher started")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logger.info("Shutting down...")
    publisher.stop()
```

## Testing

### Run Test Script

```bash
python scripts/test_performance_metrics.py
```

Expected output:
```
[OK] Calculator initialized
[OK] Created 20 sample trades
[OK] Metrics calculated
Aggressive Mode Score: 2.60
Velocity to Target: 4.5%
Days Remaining Estimate: 106.1 days
[SUCCESS] All performance metrics tests passed!
```

### Manual Test with Redis

```python
import os
os.environ["ENABLE_PERFORMANCE_METRICS"] = "true"

from metrics import create_metrics_publisher
from agents.infrastructure.redis_client import RedisCloudClient

redis_client = RedisCloudClient()

# Create and start publisher
publisher = create_metrics_publisher(
    redis_manager=redis_client,
    update_interval=10,  # Update every 10 seconds
)

# Let it run for a bit
import time
time.sleep(30)

# Check latest metrics
summary = publisher.get_latest_summary()
print(summary)

# Cleanup
publisher.stop()
```

### Verify Redis Streams

```bash
# Check metrics stream
redis-cli XREAD COUNT 10 STREAMS metrics:performance 0-0

# Check individual metric
redis-cli XREAD COUNT 10 STREAMS metrics:aggressive_mode_score 0-0
```

## Troubleshooting

### Metrics Not Publishing

**Check feature flag:**
```bash
echo $ENABLE_PERFORMANCE_METRICS
# Should output: true
```

**Check logs:**
```python
# Should see:
# "MetricsPublisher initialized: update_interval=30s"
# "Metrics publisher started"
# "Performance Metrics: Aggressive=2.60, Velocity=4.5%, ..."
```

### "No trades" Warning

If you see baseline metrics (all zeros), it means:
- No closed trades found in trade manager
- No trades in Redis stream `trades:closed`

**Solution:** Run the trading system and wait for trades to complete.

### Prometheus Metrics Not Showing

**Install prometheus_client:**
```bash
pip install prometheus-client
```

**Check /metrics endpoint:**
```bash
curl http://localhost:8000/metrics | grep aggressive_mode_score
```

## Metric Interpretations

### Aggressive Mode Score

| Score | Interpretation |
|-------|----------------|
| ≥ 2.0 | Excellent - Strong risk-adjusted returns |
| ≥ 1.5 | Very Good - Positive risk profile |
| ≥ 1.0 | Good - Balanced performance |
| ≥ 0.5 | Fair - Room for improvement |
| < 0.5 | Poor - Review strategy |

### Velocity to Target

- **0.0** = At starting equity
- **0.5** = Halfway to target (50%)
- **1.0** = Reached target
- **>1.0** = Exceeded target

### Days Remaining

- **< 7 days** = Target within a week
- **< 30 days** = On track
- **< 90 days** = Moderate pace
- **≥ 90 days** = Slow progress
- **inf** = Not making progress (negative or zero daily rate)

## Next Steps

1. ✅ Test calculator: `python scripts/test_performance_metrics.py`
2. ⚠️ Integrate into main system (orchestrator or agent)
3. 📊 Add to signals-api endpoints
4. 🎨 Add to signals-site dashboard
5. 📈 Set up Prometheus/Grafana dashboards
6. 🚨 Configure alerts for metrics thresholds

## Files

**Core:**
- `metrics/performance_metrics.py` - Calculator with formulas
- `metrics/metrics_publisher.py` - Background publisher
- `metrics/__init__.py` - Module exports

**Tests:**
- `scripts/test_performance_metrics.py` - Test script

**Docs:**
- `PERFORMANCE_METRICS_INTEGRATION.md` - This file

## Status

**Version:** 1.0.0
**Status:** ✅ TESTED & READY
**Date:** 2025-11-08

---

For signals-api and signals-site integration, see next sections.
