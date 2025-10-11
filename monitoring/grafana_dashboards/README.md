# Grafana Dashboards for Crypto AI Bot

This directory contains Grafana dashboard configurations for monitoring the crypto AI bot.

## Dashboards

### crypto-ai-bot.json
Main operational dashboard with key metrics and performance indicators.

## Import Instructions

### Method 1: Grafana UI Import

1. **Access Grafana:**
   - Open http://localhost:3000 (or your Grafana URL)
   - Login with admin credentials (default: admin/admin123)

2. **Import Dashboard:**
   - Click the "+" icon in the sidebar
   - Select "Import"
   - Click "Upload JSON file"
   - Select `crypto-ai-bot.json`
   - Click "Load"

3. **Configure Data Source:**
   - Select "Prometheus" as the data source
   - Ensure the Prometheus URL is correct (http://prometheus:9090 for Docker Compose)
   - Click "Import"

### Method 2: Docker Compose with Provisioning

The dashboard is automatically provisioned when using Docker Compose with the monitoring profile:

```bash
# Start Grafana with dashboard provisioning
docker compose --profile monitoring up -d grafana
```

The dashboard will be available at: http://localhost:3000/d/crypto-ai-bot/crypto-ai-bot

## Dashboard Panels

### 1. Signals Published Rate
- **Query**: `rate(signals_published_total[5m])`
- **Description**: Shows the rate of signals being published by agent and stream
- **Unit**: requests per second

### 2. Publish Latency (95th & 50th percentile)
- **Query**: `histogram_quantile(0.95, sum(rate(publish_latency_ms_bucket[5m])) by (le))`
- **Description**: Shows latency percentiles for signal publishing
- **Unit**: milliseconds
- **Thresholds**: 
  - Green: < 100ms
  - Yellow: 100-500ms
  - Red: > 500ms

### 3. Ingestor Disconnects Rate
- **Query**: `rate(ingestor_disconnects_total[5m])`
- **Description**: Shows the rate of data source disconnections
- **Unit**: disconnects per second
- **Grouped by**: source (e.g., kraken_ws)

### 4. Redis Publish Errors Rate
- **Query**: `rate(redis_publish_errors_total[5m])`
- **Description**: Shows the rate of Redis publish failures
- **Unit**: errors per second
- **Grouped by**: stream

### 5. Bot Heartbeat (Last Value)
- **Query**: `bot_heartbeat_seconds`
- **Description**: Shows the last heartbeat timestamp
- **Type**: Single stat
- **Unit**: Unix timestamp

### 6. Bot Status (Up/Down)
- **Query**: `up{job="crypto-ai-bot"}`
- **Description**: Shows whether the bot is reachable by Prometheus
- **Values**: 1 = Up, 0 = Down

## Configuration

### Data Source Setup

Ensure Prometheus is configured as a data source in Grafana:

1. Go to Configuration → Data Sources
2. Add Prometheus data source
3. Set URL to: `http://prometheus:9090` (for Docker Compose)
4. Test and save

### Dashboard Settings

- **Refresh Interval**: 5 seconds
- **Time Range**: Last 1 hour (default)
- **Theme**: Dark
- **Tags**: crypto, trading, bot, monitoring

## Troubleshooting

### No Data in Panels

1. **Check Prometheus Targets:**
   - Go to http://localhost:9090/targets
   - Verify crypto-ai-bot target is "UP"

2. **Verify Metrics Endpoint:**
   ```bash
   curl http://localhost:9108/metrics
   ```

3. **Check Data Source:**
   - Verify Prometheus data source is configured correctly
   - Test the connection in Grafana

### Import Issues

1. **JSON Validation:**
   - Ensure the JSON file is valid
   - Check for any syntax errors

2. **Permissions:**
   - Ensure you have admin access to Grafana
   - Check file permissions if using provisioning

### Performance Issues

1. **Reduce Refresh Rate:**
   - Change from 5s to 30s or 1m for better performance

2. **Adjust Time Range:**
   - Use shorter time ranges for better responsiveness

## Customization

### Adding New Panels

1. Edit the JSON file
2. Add new panel configuration
3. Update the grid positions accordingly
4. Re-import the dashboard

### Modifying Queries

1. Open the dashboard in Grafana
2. Click on a panel title
3. Select "Edit"
4. Modify the query in the Query tab
5. Save the panel

### Changing Thresholds

1. Edit the panel
2. Go to "Field" tab
3. Modify the threshold values
4. Update colors as needed
5. Save changes

## Monitoring Best Practices

1. **Set up Alerts:**
   - Configure alerts for critical metrics
   - Use Discord webhook for notifications

2. **Regular Review:**
   - Check dashboard daily for anomalies
   - Monitor trends over time

3. **Capacity Planning:**
   - Track signal rates and latency trends
   - Plan for scaling based on metrics

4. **Incident Response:**
   - Use dashboard during troubleshooting
   - Correlate metrics with system events
