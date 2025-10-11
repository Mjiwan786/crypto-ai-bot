# Crypto AI Bot - Docker Deployment

## 🚀 Quick Start

### 1. Setup Environment
```bash
# Copy environment template
cp env.example .env

# Edit .env with your configuration
# - Add your Kraken API credentials
# - Set your Redis Cloud URL
# - Configure other settings as needed
```

### 2. Deploy Everything
```bash
# Build and start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f bot
```

### 3. Access Services
- **Grafana Dashboard**: http://localhost:3000 (admin/admin123)
- **Prometheus Metrics**: http://localhost:9090
- **Bot Health**: http://localhost:9000/health
- **Bot Metrics**: http://localhost:9000/metrics

## 📊 Services Overview

### Core Services
- **crypto-ai-bot**: Main trading bot with conda environment
- **crypto-prometheus**: Metrics collection and storage
- **crypto-grafana**: Monitoring dashboards and visualization

### Optional Services (Profiles)
- **redis-local**: Local Redis for development (profile: local)
- **postgres**: Database for trade history (profile: database)

## 🔧 Configuration

### Environment Variables
Key variables in `.env`:
```bash
# Trading
PAPER_TRADING_ENABLED=true
KRAKEN_API_KEY=your_key
KRAKEN_API_SECRET=your_secret

# Redis Cloud
REDIS_URL=redis://username:password@host:port

# Monitoring
GRAFANA_USER=admin
GRAFANA_PASSWORD=admin123
```

### Docker Compose Profiles
```bash
# Core services only (default)
docker compose up -d

# With local Redis
docker compose --profile local up -d

# With database
docker compose --profile database up -d

# All services
docker compose --profile local --profile database up -d
```

## 📈 Monitoring

### Grafana Dashboards
- **Crypto AI Bot Overview**: Real-time trading metrics
- **Bot Status**: Uptime and health monitoring
- **Trading Activity**: Trades per minute, PnL tracking
- **Performance**: Latency and system metrics

### Prometheus Metrics
- `up{job="crypto-ai-bot"}`: Bot availability
- `bot_latency_ms`: Response times
- `trades_per_minute`: Trading frequency
- `pnl_usd`: Profit and loss

## 🛠️ Management Commands

### Container Management
```bash
# Start services
docker compose up -d

# Stop services
docker compose down

# Restart bot only
docker compose restart bot

# View logs
docker compose logs -f bot
docker compose logs -f prometheus
docker compose logs -f grafana

# Execute commands in bot container
docker compose exec bot bash
```

### Data Persistence
```bash
# View volumes
docker volume ls

# Backup data
docker run --rm -v crypto-ai-bot_prometheus_data:/data -v $(pwd):/backup alpine tar czf /backup/prometheus-backup.tar.gz -C /data .
docker run --rm -v crypto-ai-bot_grafana_data:/data -v $(pwd):/backup alpine tar czf /backup/grafana-backup.tar.gz -C /data .
```

### Updates
```bash
# Rebuild and restart
docker compose down
docker compose build --no-cache
docker compose up -d

# Update specific service
docker compose pull prometheus
docker compose up -d prometheus
```

## 🔒 Security

### Production Considerations
1. **Change default passwords** in `.env`
2. **Use Redis Cloud** instead of local Redis
3. **Enable TLS** for external connections
4. **Restrict network access** to monitoring ports
5. **Regular security updates** of base images

### Network Security
```bash
# Restrict Grafana access (example)
# Add to docker-compose.yml:
# ports:
#   - "127.0.0.1:3000:3000"
```

## 🐛 Troubleshooting

### Common Issues
1. **Bot won't start**: Check `.env` configuration
2. **No metrics**: Verify bot exposes `/metrics` endpoint
3. **Grafana can't connect**: Check Prometheus is running
4. **Permission errors**: Ensure proper file ownership

### Debug Commands
```bash
# Check container health
docker compose ps

# Inspect bot container
docker compose exec bot bash
conda activate crypto-bot
python --version

# Check Prometheus targets
curl http://localhost:9090/api/v1/targets

# Test bot health
curl http://localhost:9000/health
```

### Logs Analysis
```bash
# Follow all logs
docker compose logs -f

# Filter by service
docker compose logs -f bot | grep ERROR
docker compose logs -f prometheus | grep WARN
```

## 📁 File Structure
```
.
├── docker-compose.yml          # Main orchestration
├── docker/
│   ├── Dockerfile             # Bot container definition
│   └── entrypoint.sh          # Container startup script
├── monitoring/
│   ├── prometheus/
│   │   └── prometheus.yml     # Prometheus configuration
│   └── grafana/
│       ├── datasources/       # Grafana datasource configs
│       ├── dashboards/        # Dashboard provisioning
│       └── json/              # Dashboard definitions
├── .env                       # Environment variables
├── env.example               # Environment template
└── .dockerignore             # Docker build exclusions
```

## 🚀 Production Deployment

### Prerequisites
- Docker Engine 20.10+
- Docker Compose 2.0+
- 4GB+ RAM recommended
- 10GB+ disk space

### Deployment Steps
1. Clone repository
2. Copy `env.example` to `.env`
3. Configure environment variables
4. Run `docker compose up -d`
5. Access Grafana at http://localhost:3000
6. Monitor bot health and metrics

### Scaling
```bash
# Scale bot instances (if supported)
docker compose up -d --scale bot=3

# Use external load balancer
# Configure nginx/traefik for high availability
```

## 📞 Support

For issues and questions:
1. Check logs: `docker compose logs -f`
2. Verify configuration: `docker compose config`
3. Test connectivity: `curl http://localhost:9000/health`
4. Review monitoring: Grafana dashboards
