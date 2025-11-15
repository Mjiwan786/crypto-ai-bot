# Performance Metrics Integration Patch

This patch enables real-time performance metrics publishing without impacting the running paper trial.

## What's Already Built

The complete metrics system exists in:
- `metrics/performance_metrics.py` - Calculator for all 3 metrics
- `metrics/metrics_publisher.py` - Background publisher
- Config: `config/performance_metrics.yaml` - Feature flags

##  Metrics Calculated

1. **aggressive_mode_score** = (win_rate × avg_win) / (loss_rate × avg_loss)
2. **velocity_to_target** = (equity - $10k) / ($20k - $10k)
3. **days_remaining_estimate** = based on current daily rate

## Integration Steps

### 1. Enable in Environment (.env)

Add to `.env`:
```bash
ENABLE_PERFORMANCE_METRICS=true
STARTING_EQUITY_USD=10000
TARGET_EQUITY_USD=20000
```

### 2. Update main.py (after line 189)

After `await orchestrator.start()`, add:

```python
# Start performance metrics publisher
try:
    from metrics.metrics_publisher import create_metrics_publisher

    metrics_publisher = create_metrics_publisher(
        redis_manager=orchestrator.redis_manager if hasattr(orchestrator, 'redis_manager') else None,
        trade_manager=orchestrator.trade_manager if hasattr(orchestrator, 'trade_manager') else None,
        equity_tracker=orchestrator.equity_tracker if hasattr(orchestrator, 'equity_tracker') else None,
        logger=_logger,
        update_interval=30,
        auto_start=True,
    )
    _logger.info("✅ Performance metrics publisher started")
except Exception as e:
    _logger.warning(f"Performance metrics publisher not started: {e}")
```

### 3. Update orchestration/master_orchestrator.py

Add to `MasterOrchestrator.__init__`:

```python
# Initialize metrics publisher
from metrics.metrics_publisher import create_metrics_publisher
self.metrics_publisher = create_metrics_publisher(
    redis_manager=self.redis_manager,
    trade_manager=self.trade_manager if hasattr(self, 'trade_manager') else None,
    equity_tracker=self.equity_tracker if hasattr(self, 'equity_tracker') else None,
    logger=self.logger,
    update_interval=int(os.getenv("METRICS_UPDATE_INTERVAL", "30")),
    auto_start=False,  # Start manually
)
```

Add to `MasterOrchestrator.start()`:

```python
# Start metrics publisher
if hasattr(self, 'metrics_publisher'):
    self.metrics_publisher.start()
    self.logger.info("Metrics publisher started")
```

Add to `MasterOrchestrator.stop()`:

```python
# Stop metrics publisher
if hasattr(self, 'metrics_publisher'):
    self.metrics_publisher.stop()
    self.logger.info("Metrics publisher stopped")
```

### 4. Expose in /health Endpoint (main.py)

Update health_handler to include metrics:

```python
# Add performance metrics if available
if orchestrator and hasattr(orchestrator, 'metrics_publisher'):
    try:
        metrics_summary = orchestrator.metrics_publisher.get_latest_summary()
        if metrics_summary and metrics_summary.get("available"):
            response["performance_metrics"] = {
                "aggressive_mode_score": metrics_summary["aggressive_mode_score"]["value"],
                "velocity_to_target": metrics_summary["velocity_to_target"]["percent"],
                "days_remaining": metrics_summary["days_remaining_estimate"]["value"],
            }
    except Exception as e:
        _logger.warning(f"Could not fetch performance metrics: {e}")
```

## Verification

After deployment, check:

```bash
# 1. Health endpoint includes metrics
curl https://crypto-ai-bot.fly.dev/health | jq .performance_metrics

# 2. Redis streams populated
redis-cli XLEN metrics:performance
redis-cli XREVRANGE metrics:aggressive_mode_score + - COUNT 1

# 3. Prometheus metrics
curl https://crypto-ai-bot.fly.dev/metrics | grep aggressive_mode_score
```

## Deploy Without Interruption

```bash
# Build and deploy
fly deploy --ha=false

# Monitor logs for "Metrics publisher started"
fly logs | grep -i metrics
```

## Rollback If Needed

Metrics are feature-flagged. To disable:

```bash
# Set environment variable
fly secrets set ENABLE_PERFORMANCE_METRICS=false

# Or remove integration code
git revert <commit>
fly deploy
```

---

**Status**: Ready to deploy
**Risk**: Low (feature-flagged, non-blocking)
**Testing**: Verify health endpoint and Redis streams after deployment
