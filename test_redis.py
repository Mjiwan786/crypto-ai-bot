"""Quick Redis connection test"""
import redis
import sys
import os
from urllib.parse import urlparse

# Load from .env.paper
env_file = r"C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\.env.paper"
with open(env_file) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#"):
            if "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

redis_url = os.getenv("REDIS_URL")
ca_cert = os.getenv("REDIS_CA_CERT")

print(f"Testing Redis connection...")
print(f"URL: {redis_url[:50]}...")
print(f"CA Cert: {ca_cert}")

try:
    parsed = urlparse(redis_url)
    r = redis.Redis(
        host=parsed.hostname,
        port=parsed.port,
        password=parsed.password,
        ssl=True,
        ssl_ca_certs=ca_cert,
        decode_responses=True
    )

    # Test ping
    r.ping()
    print("[OK] Redis connection successful")

    # Test write/read
    r.set("paper_trial:test", "ok", ex=10)
    val = r.get("paper_trial:test")
    if val == "ok":
        print("[OK] Redis read/write working")
    else:
        print("[FAIL] Redis read/write failed")
        sys.exit(1)

    # Test stream write
    r.xadd("paper_trial:health", {"status": "ok", "ts": "test"}, maxlen=10)
    print("[OK] Redis streams working")

    print("\n[SUCCESS] Redis Cloud connection fully functional!")
    sys.exit(0)

except Exception as e:
    print(f"[FAIL] Redis connection failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
