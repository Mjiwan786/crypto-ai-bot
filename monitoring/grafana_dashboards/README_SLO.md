# SLO Overview Dashboard

This dashboard provides a comprehensive view of Service Level Objectives (SLOs) for the crypto AI trading bot, helping determine production readiness.

## Dashboard Panels

### SingleStat Panels (Top Row)

1. **P95 Publish Latency (72h)**
   - Shows 95th percentile publish latency over 72 hours
   - Threshold: < 500ms
   - Color coding: Green (≤500ms), Red (>500ms)

2. **P95 Stream Lag (72h)**
   - Shows maximum stream lag over 72 hours
   - Threshold: < 1s
   - Color coding: Green (≤1s), Red (>1s)

3. **Uptime Last 72h**
   - Shows system uptime percentage over 72 hours
   - Threshold: ≥ 99.5%
   - Color coding: Green (≥99.5%), Red (<99.5%)

4. **Dup Rate (72h)**
   - Shows duplicate rate over 72 hours
   - Threshold: < 0.1%
   - Color coding: Green (≤0.1%), Red (>0.1%)

### Timeseries Panel (Middle Row)

5. **Latency P95 & Dup Rate Trend (72h)**
   - Line chart showing trends over 72 hours
   - Blue line: P95 Latency
   - Orange line: Dup Rate
   - Helps visualize trend toward SLO eligibility

### Status Panel (Right Side)

6. **Ready for Prod?**
   - Overall SLO status indicator
   - Shows "READY" (green) or "NOT READY" (red)
   - Based on all SLO thresholds being met

### Legend Panel (Bottom)

7. **SLO Legend**
   - Explains all thresholds and color coding
   - Provides API endpoint information

## Data Sources

The dashboard queries Prometheus metrics:

- `publish_latency_ms_bucket` - Latency histogram
- `stream_lag_seconds` - Stream lag gauge
- `up{job="crypto-ai-bot"}` - Bot uptime status
- `redis_publish_errors_total` - Error counter
- `signals_published_total` - Signal counter

## SLO API

A Redis-backed API is available at `/slo/status` for detailed SLO metrics:

```bash
# Get current SLO status
curl http://localhost:9109/slo/status

# Get detailed metrics
curl http://localhost:9109/slo/metrics

# Get thresholds
curl http://localhost:9109/slo/thresholds

# Health check
curl http://localhost:9109/health
```

## Integration

To integrate SLO monitoring into your application:

```python
from monitoring.slo_integration_example import setup_slo_monitoring

# In your main application
slo_collector = await setup_slo_monitoring(redis_client, start_api=True)
```

## Configuration

Environment variables:

- `SLO_API_PORT` - SLO API port (default: 9109)
- `SLO_API_ADDR` - SLO API address (default: 0.0.0.0)
- `SLO_WINDOW_HOURS` - SLO evaluation window (default: 72)

## Thresholds

Current SLO thresholds (configurable in `monitoring/slo_definitions.py`):

- P95 Publish Latency: 500ms
- Max Stream Lag: 1s
- Uptime Target: 99.5%
- Max Duplicate Rate: 0.1%

Staging environment has more lenient thresholds for development.

