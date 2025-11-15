"""
scripts/test_redis.py

Production-ready Redis Cloud connectivity test (TLS).
- Uses ConnectionPool.from_url with rediss:// and ssl_* kwargs (redis-py v5)
- Verifies: PING, KV SET/GET, XADD/XREAD, cleanup

⚠️ SAFETY: No live trading unless MODE=live and confirmation set.
This script tests Redis Cloud connectivity only - no trading operations.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import redis
from dotenv import load_dotenv

# Resolve project root and load .env
ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("test_redis")


def build_client():
    """
    Build a Redis client using a secure ConnectionPool.
    NOTE: Do NOT pass `ssl=True` to from_url on redis-py v5.
    The `rediss://` scheme selects SSLConnection for us; we only pass ssl_* args.
    """
    redis_url = os.getenv("REDIS_URL")  # must be rediss://...
    redis_password = os.getenv("REDIS_PASSWORD")
    # Your explicit CA path:
    ca_path = os.getenv("REDIS_CA_CERT") or str(ROOT_DIR / "config" / "certs" / "redis_ca.pem")

    if not redis_url or not redis_password:
        raise RuntimeError("Missing REDIS_URL or REDIS_PASSWORD in .env")

    if not redis_url.startswith("rediss://"):
        raise RuntimeError("REDIS_URL must start with rediss:// for TLS")

    # Create a TLS-enabled pool. ssl_* kwargs are accepted by SSLConnection.
    pool = redis.ConnectionPool.from_url(
        redis_url,
        password=redis_password,
        # SSL/TLS settings
        ssl_cert_reqs="required",
        ssl_ca_certs=ca_path,
        ssl_check_hostname=True,
        # Connection behavior
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=10,
        health_check_interval=15,
        # RESP3 is fine; omit to default. Add protocol=3 if you explicitly want RESP3.
        # protocol=3,
    )
    return redis.Redis(connection_pool=pool)


def smoke(r: redis.Redis):
    log.info("PING -> %s", r.ping())

    ok = r.set("foo", "bar", ex=30)
    val = r.get("foo")
    log.info("SET foo -> %s | GET foo -> %s", ok, val)

    stream = "test:connectivity"
    sid = r.xadd(stream, {"msg": "hello"})
    log.info("XADD id -> %s", sid)
    # Read one entry from beginning
    entries = r.xread({stream: "0-0"}, block=1000, count=1)
    log.info("XREAD -> %s", entries)
    r.delete(stream)

    # Optional: small INFO sample to verify server details
    info = r.info(section="server")
    log.info("Server: %s %s", info.get("server"), info.get("redis_version"))


def main() -> int:
    try:
        r = build_client()
        smoke(r)
        log.info("✅ Redis Cloud connectivity test passed")
        return 0
    except Exception as e:
        log.error("❌ Redis connectivity test failed: %r", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
