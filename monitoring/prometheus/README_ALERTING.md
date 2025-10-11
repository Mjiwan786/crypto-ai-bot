# Prometheus Alerting Configuration for Crypto AI Bot

This directory contains Prometheus alerting rules that mirror the SLO definitions and provide comprehensive monitoring for the crypto AI bot.

## Files

- `slo_alerts.yml` - Main alerting rules file with SLO-based alerts
- `prometheus.yml` - Prometheus configuration (includes rule file reference)
- `README_ALERTING.md` - This documentation file

## Alert Rules Overview

### SLO-Based Alerts

1. **CryptoAIBotHighPublishLatency**
   - **Metric**: `histogram_quantile(0.95, sum(rate(publish_latency_ms_bucket[15m])) by (le))`
   - **Threshold**: > 0.5s (500ms)
   - **Duration**: 10 minutes
   - **SLO**: P95 publish latency under 500ms

2. **CryptoAIBotStreamLagHigh**
   - **Metric**: `avg_over_time(stream_lag_seconds[10m])`
   - **Threshold**: > 1s
   - **Duration**: 10 minutes
   - **SLO**: Stream lag under 1 second

3. **CryptoAIBotUptimeLow**
   - **Metric**: `sum_over_time(bot_heartbeat_seconds[72h] > 0) / (72 * 3600)`
   - **Threshold**: < 0.995 (99.5%)
   - **Duration**: 5 minutes
   - **SLO**: 99.5% uptime over 72 hours

4. **CryptoAIBotDupRateHigh**
   - **Metric**: `(signals_published_total - count by (agent, stream, symbol) (signals_published_total)) / signals_published_total`
   - **Threshold**: > 0.001 (0.1%)
   - **Duration**: 5 minutes
   - **SLO**: Duplicate rate under 0.1%

### Additional Monitoring Alerts

5. **CryptoAIBotHeartbeatMissing** - Bot stops sending heartbeats
6. **CryptoAIBotHighDisconnectRate** - High data source disconnect rate
7. **CryptoAIBotRedisPublishErrors** - Redis connectivity issues
8. **CryptoAIBotDown** - Bot metrics endpoint not responding
9. **CryptoAIBotStarted** - Bot startup notification

## Alertmanager Integration

### Basic Alertmanager Configuration

Create an `alertmanager.yml` file:

```yaml
global:
  smtp_smarthost: 'localhost:587'
  smtp_from: 'alerts@yourcompany.com'

route:
  group_by: ['alertname', 'severity']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'crypto-bot-alerts'
  routes:
    - match:
        severity: critical
      receiver: 'crypto-bot-critical'
    - match:
        severity: warning
      receiver: 'crypto-bot-warning'
    - match:
        severity: info
      receiver: 'crypto-bot-info'

receivers:
  - name: 'crypto-bot-critical'
    discord_configs:
      - webhook_url: 'https://discord.com/api/webhooks/YOUR_CRITICAL_WEBHOOK_URL'
        title: '🚨 CRITICAL: Crypto AI Bot Alert'
        text: |
          {{ range .Alerts }}
          **{{ .Annotations.summary }}**
          {{ .Annotations.description }}
          {{ end }}
    telegram_configs:
      - bot_token: 'YOUR_BOT_TOKEN'
        chat_id: 'YOUR_CRITICAL_CHAT_ID'
        message: |
          🚨 CRITICAL ALERT
          {{ range .Alerts }}
          {{ .Annotations.summary }}
          {{ .Annotations.description }}
          {{ end }}

  - name: 'crypto-bot-warning'
    discord_configs:
      - webhook_url: 'https://discord.com/api/webhooks/YOUR_WARNING_WEBHOOK_URL'
        title: '⚠️ WARNING: Crypto AI Bot Alert'
        text: |
          {{ range .Alerts }}
          **{{ .Annotations.summary }}**
          {{ .Annotations.description }}
          {{ end }}

  - name: 'crypto-bot-info'
    discord_configs:
      - webhook_url: 'https://discord.com/api/webhooks/YOUR_INFO_WEBHOOK_URL'
        title: 'ℹ️ INFO: Crypto AI Bot Alert'
        text: |
          {{ range .Alerts }}
          **{{ .Annotations.summary }}**
          {{ end }}
```

### Discord Webhook Setup

1. Create a Discord webhook in your server
2. Copy the webhook URL
3. Replace `YOUR_*_WEBHOOK_URL` in the Alertmanager config
4. Test with a simple curl command:
   ```bash
   curl -H "Content-Type: application/json" \
        -d '{"content": "Test alert from Crypto AI Bot"}' \
        YOUR_WEBHOOK_URL
   ```

### Telegram Bot Setup

1. Create a Telegram bot via @BotFather
2. Get the bot token
3. Get your chat ID (use @userinfobot)
4. Replace `YOUR_BOT_TOKEN` and `YOUR_CRITICAL_CHAT_ID` in the config

## Docker Compose Integration

Add Alertmanager to your `docker-compose.yml`:

```yaml
services:
  alertmanager:
    image: prom/alertmanager:latest
    container_name: crypto-bot-alertmanager
    ports:
      - "9093:9093"
    volumes:
      - ./monitoring/prometheus/alertmanager.yml:/etc/alertmanager/alertmanager.yml
    command:
      - '--config.file=/etc/alertmanager/alertmanager.yml'
      - '--storage.path=/alertmanager'
      - '--web.external-url=http://localhost:9093'

  prometheus:
    image: prom/prometheus:latest
    container_name: crypto-bot-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./monitoring/prometheus/slo_alerts.yml:/etc/prometheus/slo_alerts.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--web.enable-lifecycle'
      - '--web.external-url=http://localhost:9090'
```

## Testing Alerts

### Manual Alert Testing

1. **Test High Latency Alert**:
   ```bash
   # Simulate high latency by modifying the bot to add delays
   # Or use curl to send test metrics
   ```

2. **Test Missing Heartbeat**:
   ```bash
   # Stop the bot and wait for the alert to fire
   # Or temporarily modify the heartbeat interval
   ```

3. **Test Uptime Alert**:
   ```bash
   # This requires 72 hours of data, so use a shorter test period
   # Modify the alert rule temporarily for testing
   ```

### Alert Validation

Check that alerts are firing correctly:

```bash
# Check Prometheus rules
curl http://localhost:9090/api/v1/rules

# Check Alertmanager alerts
curl http://localhost:9093/api/v1/alerts

# Check specific alert
curl "http://localhost:9090/api/v1/query?query=ALERTS{alertname=\"CryptoAIBotHighPublishLatency\"}"
```

## Customization

### Adjusting Thresholds

Modify thresholds in `slo_alerts.yml` to match your requirements:

```yaml
# More lenient for staging
- alert: CryptoAIBotHighPublishLatency
  expr: histogram_quantile(0.95, sum(rate(publish_latency_ms_bucket[15m])) by (le)) > 1.0  # 1 second instead of 0.5
```

### Adding New Alerts

Add new rules to the appropriate group in `slo_alerts.yml`:

```yaml
- alert: MyCustomAlert
  expr: my_metric > threshold
  for: 5m
  labels:
    severity: warning
    component: my_component
  annotations:
    summary: "Custom alert triggered"
    description: "This is a custom alert for monitoring specific conditions"
```

## Troubleshooting

### Common Issues

1. **Alerts not firing**: Check Prometheus logs for rule evaluation errors
2. **Webhook not working**: Verify Discord/Telegram webhook URLs and permissions
3. **Missing metrics**: Ensure the bot is exporting the required metrics
4. **False positives**: Adjust thresholds or add additional conditions

### Debugging Commands

```bash
# Check Prometheus configuration
curl http://localhost:9090/api/v1/status/config

# Check rule evaluation
curl http://localhost:9090/api/v1/rules

# Check alert state
curl http://localhost:9090/api/v1/query?query=ALERTS

# Check specific metric
curl "http://localhost:9090/api/v1/query?query=publish_latency_ms_bucket"
```

## Monitoring the Monitors

Consider setting up monitoring for your monitoring stack:

- Prometheus uptime
- Alertmanager uptime
- Webhook delivery success rates
- Alert rule evaluation performance

This ensures your alerting system itself is reliable and performing well.
