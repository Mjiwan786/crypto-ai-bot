# Smoke Tests - Buyer Verification

Quick verification steps to confirm the system is operational after acquisition.

**Time Required:** ~10 minutes

## Prerequisites

- Docker and Docker Compose installed
- `.env` file configured (see `docs/ENVIRONMENT_MATRIX.md`)
- Network access to Redis Cloud (if using remote Redis)

## Step 1: Environment Setup

```bash
# Clone repository (if not already done)
git clone <repository-url>
cd crypto-ai-bot

# Copy environment template
cp .env.paper.example .env

# Edit with your credentials
# (At minimum: KRAKEN_API_KEY, KRAKEN_API_SECRET, REDIS_URL)
```

**Expected:** `.env` file exists with required variables set.

## Step 2: Docker Health Check

```bash
# Start services
docker compose up -d

# Wait for startup (30 seconds)
sleep 30

# Check container status
docker compose ps
```

**Expected Output:**
```
NAME                STATUS
crypto-ai-bot       Up (healthy)
redis               Up
```

## Step 3: API Health Endpoint

```bash
# Check health endpoint
curl http://localhost:9000/health
```

**Expected Output:**
```json
{
  "status": "healthy",
  "redis": "connected",
  "mode": "paper"
}
```

## Step 4: Metrics Endpoint

```bash
# Check Prometheus metrics
curl http://localhost:9090/metrics | head -20
```

**Expected:** Returns Prometheus-format metrics (lines starting with `# HELP` or `# TYPE`).

## Step 5: Log Verification

```bash
# Check application logs
docker compose logs --tail=50 crypto-ai-bot
```

**Expected:** No ERROR or CRITICAL messages. Should see:
- "Starting trading system..."
- "Redis connection established"
- "Health check: OK"

## Quick Pass/Fail Checklist

| Check | Command | Pass Criteria |
|-------|---------|---------------|
| Containers running | `docker compose ps` | All containers "Up" |
| Health endpoint | `curl localhost:9000/health` | Returns `{"status": "healthy"}` |
| Metrics available | `curl localhost:9090/metrics` | Returns metric data |
| No critical errors | `docker compose logs` | No ERROR/CRITICAL lines |
| Redis connected | Health endpoint | `"redis": "connected"` |

## Troubleshooting

### Container Won't Start
```bash
# Check logs
docker compose logs crypto-ai-bot

# Common issues:
# - Missing .env file
# - Invalid API credentials
# - Redis connection failed
```

### Health Check Fails
```bash
# Verify Redis connectivity
docker compose exec crypto-ai-bot python -c "import redis; r = redis.from_url('$REDIS_URL'); print(r.ping())"
```

### Metrics Not Available
```bash
# Check if port is exposed
docker compose port crypto-ai-bot 9090
```

## Next Steps

After passing smoke tests:

1. Review `docs/SECURITY_TRANSFER.md` for credential setup
2. Read `HANDOFF.md` for complete acquisition guide
3. Complete `docs/DUE_DILIGENCE_CHECKLIST.md`

## Support

If smoke tests fail after following all steps, check:
- `docs/TROUBLESHOOTING.md` (if exists)
- GitHub Issues
- Post-sale support contact (see `HANDOFF.md`)
