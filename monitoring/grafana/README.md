# Grafana Dashboard Setup for Maker-Only Execution Monitoring

## Overview

This directory contains Grafana dashboard configurations for monitoring maker-only execution quality, including:

- **Maker %**: Real-time maker/taker ratio
- **Rebates Earned**: Total USD rebates from maker fills
- **Spread Monitoring**: Track spread rejections and distribution
- **Execution Quality**: Queue times, fill rates, latency
- **Circuit Breaker Events**: Wide spread alerts

## Prerequisites

1. **Redis Cloud** - Running and configured
2. **Grafana** - v9.0+ (with Redis data source)
3. **Redis Data Source Plugin** - For Grafana

## Installation

### 1. Install Grafana

**Docker (Recommended)**:
```bash
docker run -d \
  --name=grafana \
  -p 3000:3000 \
  -e "GF_INSTALL_PLUGINS=redis-datasource" \
  grafana/grafana-enterprise
```

**Conda (Alternative)**:
```bash
conda activate crypto-bot
pip install grafana-client
```

### 2. Install Redis Data Source Plugin

Navigate to Grafana UI (http://localhost:3000):
1. Go to **Configuration** > **Plugins**
2. Search for "Redis"
3. Install **Redis Data Source** plugin
4. Enable the plugin

### 3. Configure Redis Data Source

1. Go to **Configuration** > **Data Sources**
2. Click **Add data source**
3. Select **Redis**
4. Configure connection:

```yaml
Name: Redis Cloud
URL: redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
TLS: Enabled
Auth:
  Username: default
  Password: <YOUR_REDIS_PASSWORD>
Connection Timeout: 10s
```

5. Click **Save & Test**

### 4. Import Dashboard

**Via UI**:
1. Go to **Dashboards** > **Import**
2. Click **Upload JSON file**
3. Select `maker_monitoring_dashboard.json`
4. Select **Redis Cloud** as data source
5. Click **Import**

**Via API**:
```bash
# Set Grafana API key
export GRAFANA_API_KEY=<your_api_key>

# Import dashboard
curl -X POST http://localhost:3000/api/dashboards/db \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -H "Content-Type: application/json" \
  -d @maker_monitoring_dashboard.json
```

## Dashboard Panels

### 1. Maker % (Real-time)
- **Query**: Aggregate maker fills from `kraken:fills:*` streams
- **Threshold**: Green >90%, Yellow 70-90%, Red <70%
- **Purpose**: Monitor maker-only execution quality

### 2. Total Rebates Earned (USD)
- **Query**: Sum negative fees (rebates) from maker fills
- **Format**: Currency USD
- **Purpose**: Track rebate earnings vs. taker fees

### 3. Spread Rejections
- **Query**: Count entries in `kraken:circuit_breaker:*`
- **Threshold**: Green <10, Yellow 10-50, Red >50
- **Purpose**: Monitor spread filtering effectiveness

### 4. Avg Queue Time (ms)
- **Query**: Average execution_time_ms for maker fills
- **Threshold**: Green <5s, Yellow 5-10s, Red >10s
- **Purpose**: Track maker order queue times

### 5. Maker vs Taker Fills (Time Series)
- **Query**: Time-series of fills colored by maker status
- **Colors**: Green = maker, Red = taker
- **Purpose**: Visualize maker/taker fill distribution over time

### 6. Spread BPS Distribution
- **Query**: Histogram of spread_bps from `kraken:spread:*`
- **Purpose**: Understand spread conditions when trading

### 7. Fill Rate by Symbol
- **Query**: Fills per symbol as bar gauge
- **Purpose**: Identify which symbols have best fill rates

### 8. Execution Time Distribution
- **Query**: Time series of execution_time_ms
- **Purpose**: Monitor execution latency

### 9. Circuit Breaker Events (Table)
- **Query**: Recent circuit breaker events
- **Columns**: Timestamp, Pair, Event, Spread (bps), Threshold (bps), Action
- **Purpose**: Audit wide spread rejections

### 10. Rebates vs Fees (Cumulative)
- **Query**: Stacked time series of rebates (negative) vs fees (positive)
- **Purpose**: Track cumulative P&L from maker rebates

## Redis Stream Keys

The dashboard queries these Redis streams:

```
kraken:fills:{symbol}         # Fill events with maker/taker tags
kraken:spread:{symbol}        # Real-time spread data
kraken:circuit_breaker:{symbol}  # Wide spread alerts
kraken:orders:{symbol}        # Order lifecycle events
kraken:health                 # System health metrics
```

## Alerting

### Configure Alerts

1. **Low Maker %** - Alert when maker percentage drops below 80%
2. **High Spread Rejections** - Alert when rejections exceed 50 per hour
3. **Slow Execution** - Alert when avg queue time exceeds 8 seconds
4. **Circuit Breaker Trips** - Alert on any circuit breaker event

**Example Alert (Grafana UI)**:
```yaml
Name: Low Maker Percentage
Condition: avg() of query(A, 5m, now) IS BELOW 80
For: 5m
Annotations:
  message: "Maker percentage dropped to {{value}}% - check spread conditions"
```

## Variables

Add dashboard variables for dynamic filtering:

1. **$symbol** - Dropdown of trading pairs
   - Query: `kraken:fills:*` (extract unique symbols)
   - Multi-value: Yes

2. **$timerange** - Time range selector
   - Options: 5m, 15m, 1h, 6h, 24h, 7d

3. **$interval** - Aggregation interval
   - Auto-calculated based on time range

## Performance Tips

1. **Limit Time Range**: Use shorter time ranges (5-60 min) for real-time monitoring
2. **Increase Aggregation**: Use 1-min aggregation for longer time ranges
3. **Set Max Data Points**: Limit to 1000 points per panel
4. **Use Redis XRANGE**: More efficient than full stream reads

## Troubleshooting

### Dashboard Not Loading

1. Check Redis connection:
```bash
redis-cli -u redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls PING
```

2. Verify streams exist:
```bash
redis-cli -u <redis_url> --tls XLEN kraken:fills:BTC-USD
```

3. Check Grafana logs:
```bash
docker logs grafana
```

### No Data in Panels

1. Ensure trading system is running and publishing to Redis
2. Check stream key format matches dashboard queries
3. Verify time range selector (data may be outside range)
4. Test queries in Grafana Explore view

### Slow Dashboard

1. Reduce time range
2. Increase aggregation interval
3. Limit data points per panel
4. Add stream MAXLEN limits in Redis

## Next Steps

1. **Extend Monitoring**: Add panels for PnL, drawdown, Sharpe ratio
2. **Custom Metrics**: Integrate with Prometheus for system metrics
3. **Alerting Channels**: Configure Slack/Discord/PagerDuty notifications
4. **Historical Analysis**: Export data to ClickHouse for long-term storage

## References

- **Grafana Docs**: https://grafana.com/docs/grafana/latest/
- **Redis Data Source**: https://grafana.com/grafana/plugins/redis-datasource/
- **Redis Streams**: https://redis.io/docs/data-types/streams/
- **Project Docs**: See `docs/PNL_PIPELINE.md` for PnL calculations
