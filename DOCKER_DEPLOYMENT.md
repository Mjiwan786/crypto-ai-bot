# Docker Deployment Guide - Crypto AI Bot

Production Docker setup for cloud deployment (Fly.io, AWS, GCP, etc.)

## 📦 Files Overview

- **Dockerfile**: Multi-stage production build using `requirements.txt`
- **health.py**: ASGI health server on port 8080 with Redis checks
- **fly.toml**: Fly.io configuration for worker deployment
- **Procfile**: Process definitions for Heroku/Railway/Render
- **.dockerignore**: Optimized build context (excludes Redis CA cert exception)

## 🏗️ Building the Docker Image

```bash
# Build production image
docker build -t crypto-ai-bot:latest .

# Build with custom tag
docker build -t crypto-ai-bot:v0.5.0 .
```

## 🚀 Running Locally

### Paper Trading (Default - Safe)

```bash
docker run -d \
  --name crypto-bot \
  --env-file .env.prod \
  -p 8080:8080 \
  crypto-ai-bot:latest
```

### Live Trading (⚠️ REAL MONEY)

```bash
docker run -d \
  --name crypto-bot-live \
  -e MODE=live \
  -e LIVE_TRADING_CONFIRMATION="I-accept-the-risk" \
  -e REDIS_URL="rediss://default:password@host:port/0" \
  -e KRAKEN_API_KEY="your_key" \
  -e KRAKEN_API_SECRET="your_secret" \
  -p 8080:8080 \
  crypto-ai-bot:latest \
  python main.py run --mode live
```

## 🏥 Health Checks

The container exposes a health endpoint on port 8080:

```bash
# Check health
curl http://localhost:8080/health

# Liveness probe
curl http://localhost:8080/liveness

# Readiness probe
curl http://localhost:8080/readiness
```

**Response (healthy):**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-15T10:30:00Z",
  "uptime_seconds": 3600,
  "redis": {
    "connected": true,
    "latency_ms": 12.5,
    "url": "redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818",
    "ssl_enabled": true
  },
  "environment": "prod",
  "version": "0.5.0"
}
```

## ☁️ Cloud Deployment

### Fly.io Deployment

1. **Install Fly CLI**
   ```bash
   # macOS/Linux
   curl -L https://fly.io/install.sh | sh

   # Windows (PowerShell)
   iwr https://fly.io/install.ps1 -useb | iex
   ```

2. **Login to Fly**
   ```bash
   fly auth login
   ```

3. **Create App** (first time only)
   ```bash
   fly launch --no-deploy
   # Edit app name in fly.toml if needed
   ```

4. **Set Secrets**
   ```bash
   fly secrets set \
     REDIS_URL="rediss://default:password@host:port/0" \
     KRAKEN_API_KEY="your_key" \
     KRAKEN_API_SECRET="your_secret" \
     DISCORD_BOT_TOKEN="your_token"

   # Optional: For live trading
   fly secrets set \
     MODE=live \
     LIVE_TRADING_CONFIRMATION="I-accept-the-risk"
   ```

5. **Deploy**
   ```bash
   fly deploy
   ```

6. **Monitor**
   ```bash
   # View logs
   fly logs

   # Check status
   fly status

   # Open health dashboard
   fly open /health
   ```

### AWS ECS/Fargate

1. **Push to ECR**
   ```bash
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

   docker tag crypto-ai-bot:latest <account>.dkr.ecr.us-east-1.amazonaws.com/crypto-ai-bot:latest
   docker push <account>.dkr.ecr.us-east-1.amazonaws.com/crypto-ai-bot:latest
   ```

2. **Create ECS Task Definition**
   - Image: `<account>.dkr.ecr.us-east-1.amazonaws.com/crypto-ai-bot:latest`
   - CPU: 512-1024
   - Memory: 1024-2048 MB
   - Port: 8080 (health check)
   - Environment variables: Set from .env.prod

3. **Deploy Service**
   - Launch type: Fargate
   - Task count: 1 (minimum)
   - Health check: HTTP GET `/health` on port 8080

### Google Cloud Run

```bash
# Build and push to GCR
gcloud builds submit --tag gcr.io/PROJECT_ID/crypto-ai-bot

# Deploy
gcloud run deploy crypto-ai-bot \
  --image gcr.io/PROJECT_ID/crypto-ai-bot \
  --platform managed \
  --region us-east1 \
  --memory 1Gi \
  --cpu 1 \
  --port 8080 \
  --no-allow-unauthenticated \
  --set-env-vars="$(cat .env.prod | grep -v '^#' | xargs)"
```

### Heroku/Railway/Render

These platforms auto-detect the `Procfile`:

```bash
# Heroku
heroku create crypto-ai-bot
heroku config:set $(cat .env.prod | grep -v '^#' | xargs)
git push heroku main

# Railway
railway login
railway init
railway up

# Render
# Connect GitHub repo in dashboard
# Set environment variables from .env.prod
```

## 🔒 Security Best Practices

### 1. **Environment Variables**
   - Never commit `.env.prod` to git
   - Use secret management (Fly Secrets, AWS Secrets Manager, etc.)
   - Rotate API keys regularly

### 2. **Redis TLS**
   - Always use `rediss://` (TLS) in production
   - Verify CA certificate is included: `config/certs/redis_ca.pem`
   - Set `REDIS_CA_CERT` environment variable

### 3. **Live Trading Guards**
   - Requires `MODE=live` AND `LIVE_TRADING_CONFIRMATION="I-accept-the-risk"`
   - Start with paper trading, validate for 24-48 hours
   - Monitor logs and metrics continuously

### 4. **Non-Root User**
   - Container runs as `botuser` (UID 10001)
   - No privileged access required

## 📊 Monitoring

### Logs

```bash
# Docker
docker logs -f crypto-bot

# Fly.io
fly logs

# Kubernetes
kubectl logs -f deployment/crypto-ai-bot
```

### Metrics

The bot exports Prometheus metrics on port 9091 (if enabled):

```yaml
# Prometheus scrape config
scrape_configs:
  - job_name: 'crypto-ai-bot'
    static_configs:
      - targets: ['crypto-ai-bot:9091']
```

Key metrics:
- `trading_signals_total`: Total signals generated
- `orders_executed_total`: Total orders executed
- `redis_connection_status`: Redis connection health (1=up, 0=down)
- `pnl_realized_total`: Realized PnL

## 🔧 Troubleshooting

### Redis Connection Fails

```bash
# Test Redis connection manually
docker exec -it crypto-bot redis-cli \
  -u $REDIS_URL \
  --tls \
  --cacert /app/config/certs/redis_ca.pem \
  ping
```

### Health Check Fails

```bash
# Check health endpoint logs
docker exec -it crypto-bot python health.py

# Verify port 8080 is exposed
docker port crypto-bot
```

### Kill Switch Activated

```bash
# Check Redis for halt signal
redis-cli -u $REDIS_URL --tls GET control:halt_all

# Deactivate kill switch
redis-cli -u $REDIS_URL --tls DEL control:halt_all
```

### Memory/CPU Issues

```bash
# Check resource usage
docker stats crypto-bot

# Increase resources in fly.toml or docker run
docker run -d --memory="2g" --cpus="2" ...
```

## 📝 Additional Notes

### Conda Environment

The Docker image does NOT use conda - it uses pip and requirements.txt for faster builds and smaller image size (~500MB vs 2GB+).

If you need conda, modify the Dockerfile base image:
```dockerfile
FROM continuumio/miniconda3:latest
```

### Local Development

For local development, continue using conda:
```bash
conda activate crypto-bot
python main.py run --mode paper
```

Docker is for production deployment only.

## 🚦 Quick Start Commands

```bash
# 1. Build
docker build -t crypto-ai-bot:latest .

# 2. Run paper trading
docker run -d --name crypto-bot --env-file .env.prod -p 8080:8080 crypto-ai-bot:latest

# 3. Check health
curl http://localhost:8080/health

# 4. View logs
docker logs -f crypto-bot

# 5. Stop
docker stop crypto-bot && docker rm crypto-bot
```

## 🆘 Support

- **Issues**: GitHub Issues
- **Documentation**: PRD-001 - Crypto-AI-Bot Core Intelligence Engine
- **Health Dashboard**: http://localhost:8080/health

---

**⚠️ IMPORTANT**: Always start with paper trading in production. Validate for at least 24-48 hours before considering live trading.
