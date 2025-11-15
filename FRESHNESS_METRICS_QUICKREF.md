# Freshness Metrics - Quick Reference

**Version:** 1.0 | **Status:** Production Ready

---

## Metrics

### Event Age
```
event_age_ms = now_server_ms - ts_exchange
```
**Meaning:** How old is the exchange event?
**Threshold:** > 5000ms = stale

### Ingest Lag
```
ingest_lag_ms = now_server_ms - ts_server
```
**Meaning:** How long to process the signal?
**Threshold:** > 1000ms = slow

### Clock Drift
```
exchange_server_delta_ms = ts_server - ts_exchange
```
**Meaning:** Time difference between clocks
**Threshold:** > 2000ms = warning

---

## Quick Start

### Check Freshness
```python
from signals.scalper_schema import ScalperSignal

signal = ScalperSignal(...)
freshness = signal.calculate_freshness_metrics()

print(f"Event age: {freshness['event_age_ms']}ms")
print(f"Ingest lag: {freshness['ingest_lag_ms']}ms")
```

### Check Clock Drift
```python
has_drift, message = signal.check_clock_drift(threshold_ms=2000)

if has_drift:
    logger.warning(f"[CLOCK DRIFT] {message}")
```

### View Prometheus Metrics
```bash
curl http://localhost:9108/metrics | grep signal_
```

---

## Prometheus Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `signal_event_age_ms` | Gauge | Event age (ms) |
| `signal_ingest_lag_ms` | Gauge | Ingest lag (ms) |
| `signal_clock_drift_ms` | Gauge | Clock drift (ms) |
| `signal_clock_drift_warnings_total` | Counter | Drift warnings |

**Endpoint:** `http://localhost:9108/metrics`

---

## Testing

### Run Schema Tests
```bash
python signals/scalper_schema.py
```

### Test Prometheus Exporter
```bash
python agents/monitoring/prometheus_freshness_exporter.py
```

### End-to-End Test
```bash
python scripts/test_freshness_metrics.py
```

### Run Live Scalper
```bash
python scripts/run_live_scalper.py
```

---

## Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Event age | 3000ms | 5000ms |
| Ingest lag | 500ms | 1000ms |
| Clock drift | 2000ms | 5000ms |

---

## Troubleshooting

### High Event Age
- Check exchange status
- Test network connectivity
- Monitor Kraken WebSocket

### High Ingest Lag
- Check CPU usage
- Test Redis latency
- Profile validation code

### Clock Drift
- Check NTP sync: `timedatectl status`
- Compare with exchange time
- Review timestamp code

---

## Monitoring

### Prometheus Queries
```promql
# Stale signals
signal_event_age_ms > 5000

# Slow processing
signal_ingest_lag_ms > 1000

# Clock drift warnings
rate(signal_clock_drift_warnings_total[5m]) > 0
```

### Live Monitoring
```bash
# Watch event age
watch -n 5 "curl -s http://localhost:9108/metrics | grep event_age"

# Check Redis metrics
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem \
  XREVRANGE metrics:scalper + - COUNT 10
```

---

## Files

| File | Purpose |
|------|---------|
| `signals/scalper_schema.py` | Freshness calculation |
| `agents/monitoring/prometheus_freshness_exporter.py` | Prometheus exporter |
| `scripts/run_live_scalper.py` | Live scalper with freshness |
| `scripts/test_freshness_metrics.py` | E2E test |

---

## Documentation

- **Complete Guide**: `FRESHNESS_METRICS_IMPLEMENTATION_COMPLETE.md`
- **Schema Guide**: `SIGNAL_SCHEMA_GUIDE.md`
- **Quick Ref**: This file

---

**Status**: Production Ready
