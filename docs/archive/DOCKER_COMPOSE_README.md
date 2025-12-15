# Docker Compose Configuration

This document describes the Docker Compose setup for the crypto AI bot with staging and production profiles.

## 🚀 Quick Start

### Prerequisites
1. Copy environment template and configure it:
   ```bash
   cp compose.env.example .env.staging
   cp compose.env.example .env.prod
   # Edit .env.staging and .env.prod with your actual values
   ```

2. Ensure Docker and Docker Compose are installed

### Running the Bot

#### Staging (Paper Trading)
```bash
# Start staging bot with paper trading
docker-compose --profile staging up -d

# View logs
docker-compose --profile staging logs -f bot

# Stop staging
docker-compose --profile staging down
```

#### Production (Live Trading)
```bash
# Start production bot with live trading
docker-compose --profile prod up -d

# View logs
docker-compose --profile prod logs -f bot-prod

# Stop production
docker-compose --profile prod down
```

#### Development (with local Redis)
```bash
# Start with local Redis for development
docker-compose --profile dev up -d

# This starts both the bot and a local Redis instance
```

## 📋 Profiles

### `staging` Profile
- **Bot Service**: `bot`
- **Mode**: PAPER trading
- **Environment**: staging
- **Port**: 9000
- **Data Volume**: `bot_data`
- **Env File**: `.env.staging`

### `prod` Profile
- **Bot Service**: `bot-prod`
- **Mode**: LIVE trading
- **Environment**: production
- **Port**: 9001 (to avoid conflicts)
- **Data Volume**: `bot_data_prod`
- **Env File**: `.env.prod`

### `dev` Profile
- **Redis Service**: `redis`
- **Purpose**: Local development Redis instance
- **Port**: 6379
- **Password**: Set via `REDIS_PASSWORD` env var

## 🔧 Configuration

### Environment Files

#### `.env.staging`
- Copy from `compose.env.example`
- Configure with staging API keys
- Set `PAPER_TRADING_ENABLED=true`
- Leave `LIVE_TRADING_CONFIRMATION` blank
- Use conservative risk settings

#### `.env.prod`
- Copy from `compose.env.example`
- Configure with production API keys
- Set `PAPER_TRADING_ENABLED=false`
- Set `LIVE_TRADING_CONFIRMATION` to enable live trading
- Use production risk settings

### Health Checks

Both staging and production bots use the same health check:
```yaml
healthcheck:
  test: ["CMD", "python", "scripts/healthcheck.py"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

The health check verifies:
- Environment variables
- Redis connectivity
- Configuration loading
- Strategy allocations

### Logging

All services use JSON file logging with rotation:
```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```

## 📊 Monitoring

### Prometheus
- **Port**: 9090
- **Config**: `monitoring/prometheus/`
- **Data**: `prometheus_data` volume

### Grafana
- **Port**: 3000
- **Default User**: admin
- **Default Password**: admin123
- **Dashboards**: `monitoring/grafana/dashboards/`

## 🗂️ Volumes

- `bot_data`: Staging bot data
- `bot_data_prod`: Production bot data
- `redis_data`: Local Redis data (dev profile)
- `prometheus_data`: Prometheus metrics
- `grafana_data`: Grafana dashboards and config
- `postgres_data`: Database data (database profile)

## 🔒 Security

### Production Considerations
1. **API Keys**: Store production API keys securely
2. **Redis**: Use SSL-enabled Redis (`rediss://`)
3. **Networks**: Bot runs in isolated `crypto-network`
4. **Volumes**: Data volumes are persistent and isolated
5. **Logs**: Logs are rotated to prevent disk space issues

### Environment Variables
- Never commit `.env.staging` or `.env.prod` to version control
- Use strong passwords for Redis and databases
- Rotate API keys regularly

### Redis Cloud Connection
The example includes Redis Cloud connection details:
- **Host**: redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com
- **Port**: 19818
- **TLS**: Enabled (rediss://)
- **Connection String**: `rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0`

To test the connection:
```bash
redis-cli -u redis://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 --tls --cacert <path_to_ca_certfile>
```

## 🚨 Troubleshooting

### Common Issues

1. **Health Check Failing**
   ```bash
   # Check health check manually
   docker-compose exec bot python scripts/healthcheck.py
   ```

2. **Redis Connection Issues**
   ```bash
   # Check Redis connectivity
   docker-compose exec bot python scripts/wait_for_redis.py
   ```

3. **Configuration Issues**
   ```bash
   # Validate configuration
   docker-compose exec bot python -c "from config.merge_config import load_config; print(load_config())"
   ```

### Logs
```bash
# View all logs
docker-compose logs

# View specific service logs
docker-compose logs bot
docker-compose logs bot-prod

# Follow logs in real-time
docker-compose logs -f bot
```

### Cleanup
```bash
# Stop and remove containers
docker-compose down

# Remove volumes (WARNING: deletes data)
docker-compose down -v

# Remove images
docker-compose down --rmi all
```

## 📝 Examples

### Full Staging Stack
```bash
docker-compose --profile staging --profile database up -d
```

### Production with Monitoring
```bash
docker-compose --profile prod up -d
# Prometheus and Grafana start automatically
```

### Development Environment
```bash
docker-compose --profile dev --profile database up -d
# Includes local Redis and PostgreSQL
```
