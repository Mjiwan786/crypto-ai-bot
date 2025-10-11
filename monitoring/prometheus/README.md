# Prometheus Configuration for Crypto AI Bot

This directory contains the Prometheus configuration for monitoring the crypto AI bot.

## Configuration

The `prometheus.yml` file is configured to scrape metrics from:

- **crypto-ai-bot**: Main bot metrics endpoint (port 9108)
- **prometheus**: Self-monitoring (port 9090)

## Environment Adaptation

The configuration includes commented sections for different deployment environments:

### Docker Desktop (Windows/Mac)
```yaml
- targets: ['host.docker.internal:9108']
```

### Docker Compose (Co-located)
```yaml
- targets: ['bot:9108']
```

### Staging Environment
```yaml
- targets: ['staging-bot.example.com:9108']
```

### Production Environment
```yaml
- targets: ['bot.example.com:9108']
```

### Local Development
```yaml
- targets: ['localhost:9108']
```

## Usage

### Start Prometheus with Docker Compose

```bash
# Start only Prometheus
docker compose --profile monitoring up -d prometheus

# Start both Prometheus and Grafana
docker compose --profile monitoring up -d

# View logs
docker compose --profile monitoring logs -f prometheus
```

### Access Prometheus UI

- **URL**: http://localhost:9090
- **Targets**: http://localhost:9090/targets
- **Metrics**: http://localhost:9090/metrics

### Verify Bot Metrics

1. Ensure the crypto AI bot is running with metrics enabled
2. Check that the bot target shows as "UP" in Prometheus targets
3. Query bot metrics in the Prometheus UI:
   - `signals_published_total`
   - `publish_latency_ms_bucket`
   - `ingestor_disconnects_total`
   - `redis_publish_errors_total`
   - `bot_heartbeat_seconds`

## Configuration Details

- **Scrape Interval**: 15 seconds
- **Retention**: 15 days or 1GB (whichever comes first)
- **Self-Monitoring**: Enabled
- **Admin API**: Enabled for configuration reloads

## Troubleshooting

### Bot Target Shows as "DOWN"

1. Verify the bot is running: `docker compose ps`
2. Check bot logs: `docker compose logs bot`
3. Verify metrics endpoint: `curl http://localhost:9108/metrics`
4. Check network connectivity between containers

### Prometheus Can't Connect to Bot

1. **Docker Desktop**: Use `host.docker.internal:9108`
2. **Docker Compose**: Use `bot:9108` (service name)
3. **External**: Use actual hostname/IP address

### Configuration Changes

After modifying `prometheus.yml`:

```bash
# Reload configuration
curl -X POST http://localhost:9090/-/reload

# Or restart the container
docker compose --profile monitoring restart prometheus
```

## Metrics Available

The bot exposes the following metrics:

- `signals_published_total{agent,stream,symbol}` - Total signals published
- `publish_latency_ms_bucket{agent,stream}` - Publish latency histogram
- `ingestor_disconnects_total{source}` - Ingestor disconnections
- `redis_publish_errors_total{stream}` - Redis publish errors
- `bot_heartbeat_seconds` - Bot heartbeat timestamp

Plus standard process and Python metrics from prometheus_client.
