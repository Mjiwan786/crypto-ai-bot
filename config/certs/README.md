# Redis TLS Certificates

This directory stores CA certificates for Redis Cloud TLS connections.

## Redis Cloud TLS Setup

### 1. Download CA Certificate

1. Log into your Redis Cloud dashboard
2. Navigate to your database
3. Click "Security" or "TLS"
4. Download the CA certificate bundle
5. Save as `redis-ca.crt` in this directory

### 2. Configure Connection

**Option A: Environment Variable**
```bash
export REDIS_URL="rediss://default:PASSWORD@HOST:PORT"
export REDIS_CA_CERT="config/certs/redis-ca.crt"
```

**Option B: YAML Configuration**
```yaml
# config/settings.yaml or config/overrides/prod.yaml
redis:
  url: rediss://default:PASSWORD@HOST:PORT
  tls: true
  ca_cert_path: config/certs/redis-ca.crt
```

### 3. Test Connection

```bash
# Test with redis-cli
redis-cli -u "rediss://default:PASSWORD@HOST:PORT" \
  --tls \
  --cacert config/certs/redis-ca.crt \
  PING

# Expected output: PONG
```

### 4. Python Connection

The unified config loader automatically handles TLS when it detects a `rediss://` URL:

```python
from config.unified_config_loader import load_settings

settings = load_settings()  # Loads from ENV/YAML

# TLS is auto-detected from rediss:// prefix
assert settings.redis.tls is True  # Auto-set when URL starts with rediss://
```

## Connection String Format

```
rediss://[username]:[password]@[host]:[port]/[db]
```

**Example (Redis Cloud)**:
```
rediss://default:${REDIS_PASSWORD}@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

**Parts**:
- `rediss://` - Protocol (note the 's' for TLS)
- `default` - Username (usually "default" for Redis Cloud)
- `PASSWORD` - Your Redis password
- `HOST` - Redis Cloud host
- `PORT` - Redis Cloud port (usually 19818 or similar)

## Security Notes

⚠️ **DO NOT COMMIT** certificates or connection strings with passwords to git!

Add to `.gitignore`:
```
config/certs/*.crt
config/certs/*.pem
config/.env*
```

## Troubleshooting

### SSL Certificate Verification Failed

If you see SSL errors, ensure:
1. CA certificate path is correct
2. Certificate is not expired
3. Hostname matches certificate

### Connection Timeout

Check:
1. Firewall/network access to Redis Cloud
2. Correct host and port
3. Redis Cloud database is running

### Authentication Failed

Verify:
1. Username (usually "default")
2. Password is correct
3. User has permissions

## Alternative: Skip Certificate Verification (Not Recommended)

If you cannot obtain a CA certificate, you can disable verification (UNSAFE for production):

```python
# NOT RECOMMENDED FOR PRODUCTION
import redis.asyncio as redis

client = redis.from_url(
    "rediss://default:PASSWORD@HOST:PORT",
    ssl_cert_reqs=None,  # Disables certificate verification
)
```

⚠️ This makes you vulnerable to man-in-the-middle attacks. Only use for development/testing.

## See Also

- [CONFIG_USAGE.md](../CONFIG_USAGE.md) - Complete configuration guide
- [unified_config_loader.py](../unified_config_loader.py) - Configuration loader implementation
- [Redis Cloud Documentation](https://redis.io/docs/cloud/)
