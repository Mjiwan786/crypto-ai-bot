# Crypto-AI-Bot Publisher Runbook

> **📋 System Requirements Specification: [PRD-001: Crypto AI Bot - Core Intelligence Engine](docs/PRD-001-CRYPTO-AI-BOT.md)**

## Overview

Production operations guide for **crypto-ai-bot publisher** - a continuous signal publishing service with health monitoring and rate limiting.

**Purpose**: Publishes trading signals, PnL points, and heartbeats to Redis streams for consumption by signals-api.

**Health Endpoint**: http://localhost:8080/health (when running locally)

**Note**: All operational procedures must comply with the requirements, SLOs, and safety standards defined in PRD-001.

---

## Running the Publisher

### Local Development

```bash
# Activate conda environment
conda activate crypto-bot

# Run publisher with health server
python publisher_with_health.py

# Verify health
curl http://localhost:8080/health
```

### Background Process

```bash
# Run in background with nohup
nohup python publisher_with_health.py > publisher.log 2>&1 &

# Get process ID
echo $! > publisher.pid

# Check status
ps aux | grep publisher_with_health

# View logs
tail -f publisher.log

# Stop publisher
kill $(cat publisher.pid)
```

### Systemd Service (Linux)

Create `/etc/systemd/system/crypto-publisher.service`:

```ini
[Unit]
Description=Crypto AI Bot Signal Publisher
After=network.target

[Service]
Type=simple
User=<your_user>
WorkingDirectory=/path/to/crypto_ai_bot
Environment="PATH=/opt/conda/envs/crypto-bot/bin"
ExecStart=/opt/conda/envs/crypto-bot/bin/python publisher_with_health.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable crypto-publisher
sudo systemctl start crypto-publisher

# Check status
sudo systemctl status crypto-publisher

# View logs
sudo journalctl -u crypto-publisher -f

# Restart service
sudo systemctl restart crypto-publisher
```

### Windows Service (Optional)

Use **NSSM** (Non-Sucking Service Manager):

```cmd
# Install NSSM
choco install nssm

# Create service
nssm install CryptoPublisher "C:\path\to\conda\envs\crypto-bot\python.exe" "publisher_with_health.py"
nssm set CryptoPublisher AppDirectory "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot"

# Start service
nssm start CryptoPublisher

# Check status
nssm status CryptoPublisher

# Stop service
nssm stop CryptoPublisher
```

---

## Configuration

### Environment Variables

Required secrets in `.env.prod`:

| Variable | Purpose | Example |
|----------|---------|---------|
| `REDIS_URL` | Redis Cloud connection | `rediss://default:<pass>@host:port` |
| `REDIS_CA_CERT` | Path to Redis CA certificate | `./config/certs/redis_ca.pem` |

### Publisher Settings

Configured in `publisher_with_health.py`:

```python
MAX_PUBLISH_RATE = 2.0  # signals per second
MIN_PUBLISH_INTERVAL = 0.5  # seconds
MAX_BACKOFF_SECONDS = 60  # max exponential backoff
HEALTH_PORT = 8080  # health server port
```

### Stream Bounds

```python
# Signals stream
maxlen=10000  # Keep last 10k signals

# PnL stream
maxlen=1000  # Keep last 1k PnL points

# Heartbeat stream
maxlen=100  # Keep last 100 heartbeats
```

---

## Secrets & Rotation

### View Current Configuration

```bash
# Check .env.prod (DO NOT commit this file)
cat .env.prod

# Test Redis connection
redis-cli -u "redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" --tls --cacert "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem" PING
```

### Rotate Redis Credentials

```bash
# 1. Get new credentials from Redis Cloud dashboard
# URL: https://app.redislabs.com/

# 2. Update .env.prod
nano .env.prod

# Change REDIS_URL to:
# REDIS_URL=rediss://default:<new_encoded_password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818

# 3. URL-encode special characters:
#   * -> %2A
#   $ -> %24
#   @ -> %40
#   : -> %3A

# Example password: &lt;REDIS_PASSWORD&gt;**$$
# Encoded: &lt;REDIS_PASSWORD&gt;%2A%2A%24%24

# 4. Restart publisher
pkill -f publisher_with_health
python publisher_with_health.py &
```

### Update Redis CA Certificate

```bash
# 1. Download new certificate from Redis Cloud dashboard
# Save to: config/certs/redis_ca_new.pem

# 2. Test connection with new cert
redis-cli -u "$REDIS_URL" --tls --cacert "config/certs/redis_ca_new.pem" PING

# 3. Replace old certificate
cp config/certs/redis_ca.pem config/certs/redis_ca_backup.pem
cp config/certs/redis_ca_new.pem config/certs/redis_ca.pem

# 4. Update .env.prod if path changed
# REDIS_CA_CERT=./config/certs/redis_ca.pem

# 5. Restart publisher
```

---

## Redis TLS Troubleshooting

### Connection Issues

**Error: "SSL: CERTIFICATE_VERIFY_FAILED"**

```python
# Fix 1: Use absolute path to CA cert
REDIS_CA_CERT = "C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot\\config\\certs\\redis_ca.pem"

# Fix 2: Download fresh CA cert from Redis Cloud dashboard
# Settings -> Security -> Download CA certificate

# Fix 3: Use certifi (for Docker/production)
import certifi
ssl_ca_certs=certifi.where()
```

**Error: "ConnectionRefusedError"**

```bash
# Check Redis is accessible
nc -zv redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com 19818

# Check firewall rules
# Redis Cloud: Settings -> Security -> Allow your IP address
```

**Error: "Authentication failed"**

```bash
# Password not URL-encoded correctly
# Use Python to encode:
python -c "from urllib.parse import quote; print(quote('&lt;REDIS_PASSWORD&gt;**\$\$', safe=''))"

# Output: &lt;REDIS_PASSWORD&gt;%2A%2A%24%24

# Update REDIS_URL:
# rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

### Test Redis Connection

```bash
# Method 1: redis-cli
redis-cli -u "redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818" \
  --tls \
  --cacert "C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem" \
  PING

# Expected: PONG

# Method 2: Python
python << 'EOF'
import redis
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv('.env.prod')
ca_cert = Path('config/certs/redis_ca.pem').absolute()

client = redis.from_url(
    os.getenv('REDIS_URL'),
    decode_responses=True,
    ssl_cert_reqs='required',
    ssl_ca_certs=str(ca_cert)
)

print(f"PING: {client.ping()}")
print(f"Redis version: {client.info('server')['redis_version']}")
EOF
```

### Check Stream Status

```bash
# Activate environment
conda activate crypto-bot

# Check signals stream
python -c "
import redis, os
from dotenv import load_dotenv
load_dotenv('.env.prod')
r = redis.from_url(os.getenv('REDIS_URL'), decode_responses=True, ssl_cert_reqs='required', ssl_ca_certs='config/certs/redis_ca.pem')
info = r.execute_command('XINFO', 'STREAM', 'signals:paper')
print('signals:paper length:', [v for k,v in zip(info[::2], info[1::2]) if k == 'length'][0])
"

# Check PnL stream
python -c "
import redis, os
from dotenv import load_dotenv
load_dotenv('.env.prod')
r = redis.from_url(os.getenv('REDIS_URL'), decode_responses=True, ssl_cert_reqs='required', ssl_ca_certs='config/certs/redis_ca.pem')
print('metrics:pnl:equity length:', r.xlen('metrics:pnl:equity'))
"

# Check heartbeat stream
python -c "
import redis, os
from dotenv import load_dotenv
load_dotenv('.env.prod')
r = redis.from_url(os.getenv('REDIS_URL'), decode_responses=True, ssl_cert_reqs='required', ssl_ca_certs='config/certs/redis_ca.pem')
print('ops:heartbeat length:', r.xlen('ops:heartbeat'))
"
```

---

## Chaos Testing

### Test 1: Publisher Crash & Recovery

**Purpose**: Verify exponential backoff and auto-reconnect to Redis.

```bash
# 1. Start publisher
python publisher_with_health.py &
PUBLISHER_PID=$!

# 2. Monitor health
watch -n 1 curl -s http://localhost:8080/health

# 3. Kill publisher
kill $PUBLISHER_PID

# 4. Restart after 30 seconds
sleep 30
python publisher_with_health.py &

# 5. Verify recovery
curl http://localhost:8080/health

# Expected: status=healthy, total_published increasing
```

**Expected Behavior:**
- Publisher exits cleanly on SIGTERM
- Closes Redis connection properly
- On restart, resumes publishing immediately
- No duplicate signals (Redis stream IDs are unique)

### Test 2: Redis Connection Loss

**Purpose**: Verify exponential backoff prevents hammering Redis.

```bash
# 1. Start publisher
python publisher_with_health.py &

# 2. Simulate Redis outage (firewall block or pause in Redis Cloud dashboard)
# Wait 2-3 minutes

# 3. Check health degradation
curl http://localhost:8080/health

# Expected: status=degraded, last_publish_seconds_ago > 30

# 4. Restore Redis

# 5. Verify auto-recovery within 60 seconds
sleep 60
curl http://localhost:8080/health

# Expected: status=healthy, total_errors increased but publishing resumed
```

**Expected Behavior:**
- Consecutive errors trigger exponential backoff: 1s → 2s → 4s → 8s → ... → 60s max
- Health status degrades after 30s without publish
- Auto-reconnect when Redis restored
- No data loss (just delayed publishing)

### Test 3: Rate Limiting Verification

**Purpose**: Ensure publisher doesn't exceed 2 signals/second.

```bash
# 1. Start publisher
python publisher_with_health.py &

# 2. Monitor publish rate
watch -n 5 'curl -s http://localhost:8080/health | jq .total_published'

# 3. Calculate rate over 60 seconds
# Formula: (total_published_t60 - total_published_t0) / 60

# Expected: ~2.0 signals/second (±0.1)
```

**Expected Behavior:**
- Publish rate never exceeds 2.0/sec
- MIN_PUBLISH_INTERVAL enforced between publishes
- No bursts or spikes

---

## Health Monitoring

### Health Check Endpoint

```bash
# Check health
curl http://localhost:8080/health

# Expected output:
{
  "status": "healthy",  # or "degraded"
  "reason": "Publishing normally",
  "last_publish_seconds_ago": 0.45,
  "uptime_seconds": 3421.88,
  "total_published": 6843,
  "total_errors": 0,
  "publish_rate": "2/sec"
}
```

### Health Status Transitions

| Status | Condition | Reason |
|--------|-----------|--------|
| `healthy` | Last publish < 30s ago | Publishing normally |
| `degraded` | Last publish > 30s ago | No publish in Xs (>30s threshold) |

### Monitor Logs

```bash
# Real-time logs
tail -f publisher.log

# Search for errors
grep "ERROR" publisher.log

# Count signals published
grep "BTC-USD\|ETH-USD" publisher.log | wc -l

# Check heartbeats
grep "💓 Heartbeat sent" publisher.log
```

---

## Deployment (Optional: Fly.io)

**Note**: Currently publisher runs locally. If deploying to Fly.io:

```bash
# Create Fly app
fly apps create crypto-ai-bot-publisher

# Set secrets
fly secrets set REDIS_URL="<rediss_url>" -a crypto-ai-bot-publisher

# Deploy
fly deploy -a crypto-ai-bot-publisher

# Check status
fly status -a crypto-ai-bot-publisher

# View logs
fly logs -a crypto-ai-bot-publisher

# SSH into machine
fly ssh console -a crypto-ai-bot-publisher
```

---

## Common Issues

### Issue: Health status `degraded` but publisher is running

**Symptoms:**
- Health returns `status: "degraded"`
- `last_publish_seconds_ago > 30`

**Diagnosis:**

```bash
# Check publisher logs for errors
tail -n 50 publisher.log | grep -E "ERROR|FAIL"

# Test Redis connection
redis-cli -u "$REDIS_URL" --tls --cacert "config/certs/redis_ca.pem" PING
```

**Fix:**

```bash
# 1. Check Redis is accessible
curl https://app.redislabs.com/

# 2. Verify REDIS_URL is correct in .env.prod
cat .env.prod | grep REDIS_URL

# 3. Restart publisher
pkill -f publisher_with_health
python publisher_with_health.py &
```

---

### Issue: "SSL: CERTIFICATE_VERIFY_FAILED"

**Symptoms:**
- Publisher fails to connect to Redis
- Logs show SSL certificate errors

**Diagnosis:**

```bash
# Check if CA cert file exists
ls -lh config/certs/redis_ca.pem

# Verify file is not empty
cat config/certs/redis_ca.pem
```

**Fix:**

```bash
# 1. Re-download CA cert from Redis Cloud dashboard
# Settings -> Security -> Download CA certificate

# 2. Save to config/certs/redis_ca.pem

# 3. Update path in .env.prod
# REDIS_CA_CERT=./config/certs/redis_ca.pem

# 4. Restart publisher
```

---

### Issue: "Total errors" increasing

**Symptoms:**
- Health shows `total_errors` > 0 and growing
- `consecutive_errors` in logs

**Diagnosis:**

```bash
# Check error pattern in logs
grep -A 5 "✗ ERROR" publisher.log | tail -30

# Common causes:
# - Redis connection timeout
# - Authentication failure
# - Network issues
```

**Fix:**

```bash
# 1. Verify Redis is up
redis-cli -u "$REDIS_URL" --tls --cacert "config/certs/redis_ca.pem" PING

# 2. Check Redis Cloud dashboard for alerts

# 3. Increase backoff if transient errors:
# Edit publisher_with_health.py:
# MAX_BACKOFF_SECONDS = 120  # Increase from 60

# 4. Restart publisher
```

---

## Monitoring

### Key Metrics

```bash
# Publish rate
curl -s http://localhost:8080/health | jq '.total_published'

# Error rate
curl -s http://localhost:8080/health | jq '.total_errors'

# Health status
curl -s http://localhost:8080/health | jq '.status'

# Stream lag (from signals-api)
curl -s https://signals-api-gateway.fly.dev/health | jq '.stream_lag_ms'
```

### Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| `last_publish_seconds_ago` | > 30s | > 120s |
| `status` | `degraded` | N/A |
| `total_errors` rate | > 5/min | > 20/min |
| Health endpoint | Timeout | Down |

---

## References

- **PRD**: `PRD-001 – Crypto-AI-Bot Core Intelligence Engine`
- **Redis Cloud Dashboard**: https://app.redislabs.com/
- **Signals-API Health**: https://signals-api-gateway.fly.dev/health
- **Conda Environment**: `crypto-bot`

---

## Emergency Contacts

- **On-Call Engineer**: [Add contact info]
- **Redis Cloud Support**: support@redis.com
- **Redis Cloud Dashboard**: https://app.redislabs.com/
