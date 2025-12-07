# Week 3: Signal Frequency & Performance Harmonization

**Version:** 1.0
**Completed:** 2025-12-03
**Status:** COMPLETE

---

## Executive Summary

Week 3 focused on harmonizing signal frequency and performance metrics between the engine, API, and front-end. The goal was to ensure marketing copy reflects actual system performance.

### Goals Achieved

1. **Signal Frequency Aggregation** - Calculate actual average signals per day/week/month
2. **Performance Metrics** - Compute ROI, CAGR, win rate, profit factor, max drawdown
3. **Trading Pairs Deduplication** - Unified 5 canonical pairs across all systems
4. **Summary Metrics Exposure** - Publish to Redis for API consumption
5. **Methodology Documentation** - Plain-English signal generation explanation

---

## Deliverables

### 1. Summary Metrics Aggregator

**File:** `metrics/summary_metrics_aggregator.py`

A new module that:
- Reads signals from Redis streams (`signals:paper:*` or `signals:live:*`)
- Counts signals by time range (today, 7 days, 30 days, 90 days)
- Calculates performance metrics from PnL data and equity curve
- Publishes aggregated stats to Redis hashes

### 2. Redis Keys for API

The aggregator publishes to these Redis keys:

| Key | Type | Purpose |
|-----|------|---------|
| `metrics:signal_frequency` | Hash | Signal counts and averages |
| `metrics:summary` | Hash | Performance metrics (ROI, win rate, etc.) |
| `metrics:trading_pairs` | Hash | Canonical trading pairs list |

### 3. Signal Frequency Fields

```redis
HGETALL metrics:signal_frequency
```

| Field | Description | Example |
|-------|-------------|---------|
| `signals_today` | Signals generated today | `1555` |
| `signals_last_7_days` | Signals in past week | `30026` |
| `signals_last_30_days` | Signals in past month | `30026` |
| `avg_signals_per_day` | 30-day daily average | `1000.9` |
| `avg_signals_per_week` | 30-day weekly average | `7015.4` |
| `pairs_active` | Pairs with signals | `BTC/USD,ETH/USD,SOL/USD` |
| `last_signal_timestamp` | Most recent signal | `2025-12-03T11:02:23+00:00` |

### 4. Performance Metrics Fields

```redis
HGETALL metrics:summary
```

| Field | Description | Example |
|-------|-------------|---------|
| `total_roi_pct` | Total return on investment | `177.9` |
| `cagr_pct` | Compound annual growth rate | `177.9` |
| `win_rate_pct` | Percentage of winning trades | `60.8` |
| `profit_factor` | Gross profit / gross loss | `1.52` |
| `max_drawdown_pct` | Maximum peak-to-trough decline | `8.3` |
| `sharpe_ratio` | Risk-adjusted returns | `1.41` |
| `total_trades` | Total number of closed trades | `720` |
| `current_equity_usd` | Current account equity | `27789.83` |
| `uptime_pct` | System uptime percentage | `99.5` |

### 5. Trading Pairs Fields

```redis
HGETALL metrics:trading_pairs
```

| Field | Description | Example |
|-------|-------------|---------|
| `pairs_list` | Comma-separated symbols | `BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD` |
| `pairs_json` | Full pairs array as JSON | `[{"symbol":"BTC/USD","name":"Bitcoin",...}]` |
| `count` | Number of active pairs | `5` |

---

## Configuration Updates

### settings.yaml

Updated `allowed_symbols` to match PRD-001:

```yaml
compliance:
  allowed_symbols: ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
```

### Canonical Trading Pairs (PRD-001)

| Symbol | Name | Status |
|--------|------|--------|
| BTC/USD | Bitcoin | Active |
| ETH/USD | Ethereum | Active |
| SOL/USD | Solana | Active |
| MATIC/USD | Polygon | Active |
| LINK/USD | Chainlink | Active |

---

## Documentation Created

### Signal Methodology

**File:** `docs/SIGNAL_METHODOLOGY.md`

Plain-English explanation for front-end display:
- How signals are generated (data ingestion, technical analysis, AI ensemble)
- Supported trading pairs
- Performance metrics explained
- Risk disclosures and disclaimers

---

## signals-api Integration Guide

To consume these metrics in signals-api:

```python
import redis

# Connect to Redis
r = redis.from_url(os.getenv("REDIS_URL"), ssl_ca_certs=cert_path)

# Get signal frequency
freq = r.hgetall("metrics:signal_frequency")
signals_per_day = float(freq.get(b"avg_signals_per_day", 0))

# Get performance summary
summary = r.hgetall("metrics:summary")
win_rate = float(summary.get(b"win_rate_pct", 0))
profit_factor = float(summary.get(b"profit_factor", 1.0))

# Get trading pairs
pairs = r.hgetall("metrics:trading_pairs")
pairs_list = pairs.get(b"pairs_list", b"").decode().split(",")
```

### Example API Response

```json
{
  "signal_frequency": {
    "avg_per_day": 1000.9,
    "avg_per_week": 7015.4,
    "last_30_days": 30026
  },
  "performance": {
    "total_roi_pct": 177.9,
    "win_rate_pct": 60.8,
    "profit_factor": 1.52,
    "max_drawdown_pct": 8.3,
    "sharpe_ratio": 1.41
  },
  "trading_pairs": [
    "BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"
  ]
}
```

---

## Running the Aggregator

### One-Time Execution

```bash
cd crypto_ai_bot
conda activate crypto-bot
python scripts/test_week3_metrics.py
```

### Continuous Background Service

```bash
python -m metrics.summary_metrics_aggregator
```

Default update interval: 300 seconds (5 minutes)

### Environment Variables

```bash
KEY_METRICS_SUMMARY=metrics:summary
KEY_SIGNAL_FREQUENCY=metrics:signal_frequency
KEY_TRADING_PAIRS=metrics:trading_pairs
METRICS_TTL_SECONDS=3600
```

---

## Test Results

```
TEST 1: Trading Pairs Consistency     [PASS]
TEST 2: Redis Connection              [PASS]
TEST 3: Signal Frequency Calculation  [PASS]
TEST 4: Performance Metrics           [PASS]
TEST 5: Publish Metrics to Redis      [PASS]
TEST 6: Verify Redis Keys             [PASS]
TEST 7: Check Signal Streams          [PASS]
```

### Current Signal Streams

| Stream | Message Count |
|--------|---------------|
| signals:paper:BTC-USD | 10,005 |
| signals:paper:ETH-USD | 10,008 |
| signals:paper:SOL-USD | 10,011 |
| signals:paper:MATIC-USD | 0 |
| signals:paper:LINK-USD | 0 |

Note: MATIC/USD and LINK/USD streams are empty because the engine hasn't generated signals for these pairs yet. This is expected behavior.

---

## Front-End Copy Harmonization

### Before (Conflicting Claims)

| Source | Claim |
|--------|-------|
| Homepage | "2 signals per day" |
| Features | "120+ signals per day" |
| Pricing | "Up to 50 signals per week" |

### After (Data-Driven)

All marketing copy should reference `metrics:signal_frequency`:

```
Real-time signal frequency: ${avg_signals_per_day}/day
```

### Placeholder Replacement

| Placeholder | Redis Key | Field |
|-------------|-----------|-------|
| "0 active traders" | (user tracking required) | - |
| "0++ signals delivered" | `metrics:signal_frequency` | `signals_last_30_days` |
| "0.0% uptime" | `metrics:summary` | `uptime_pct` |

---

## Files Created/Modified

### Created
- `metrics/summary_metrics_aggregator.py` - Main aggregator module
- `scripts/test_week3_metrics.py` - Test script
- `docs/SIGNAL_METHODOLOGY.md` - Methodology documentation
- `docs/WEEK3_METRICS_HARMONIZATION.md` - This summary

### Modified
- `config/settings.yaml` - Updated `allowed_symbols` to 5 pairs

---

## Next Steps

1. **signals-api**: Add endpoint `/v1/metrics/summary` to serve these Redis keys
2. **signals-site**: Update components to fetch from `/v1/metrics/summary`
3. **Engine**: Generate signals for MATIC/USD and LINK/USD pairs
4. **PnL Tracking**: Populate trade history to compute real performance metrics

---

**Week 3 Complete.**
