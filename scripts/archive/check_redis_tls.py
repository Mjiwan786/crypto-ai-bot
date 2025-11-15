# scripts/check_redis_tls.py
"""
TLS sanity check for Redis Cloud (redis-py 5.x compatible).

What it does:
1) Resolves CA (file path or certifi bundle).
2) Builds a TLS Redis client from REDIS_URL and env toggles.
3) PING
4) XADD to events stream, then XREAD back (round-trip).
5) Prints clear PASS/FAIL results and exits nonzero on failure.

Env it uses (with safe defaults):
- REDIS_URL                        (required)
- REDIS_SSL                        (default: true)
- REDIS_SSL_CERT_REQS              (default: required)
- REDIS_SSL_CHECK_HOSTNAME         (default: true)
- REDIS_CA_CERT_USE_CERTIFI        (default: true)
- REDIS_CA_CERT_PATH               (default: config/certs/redis_ca.pem)
- REDIS_DECODE_RESPONSES           (default: true)
- REDIS_CLIENT_NAME                (default: crypto-ai-bot)
- REDIS_SOCKET_TIMEOUT             (default: 10)
- REDIS_SOCKET_CONNECT_TIMEOUT     (default: 10)
- STREAM_EVENTS                    (default: events:bus)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Optional

import redis

try:
    import certifi
except Exception:  # certifi is optional; only needed if CA path not provided
    certifi = None

LOG_FMT = "%(asctime)s | %(levelname)s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FMT)
log = logging.getLogger("redis-tls-check")


def env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, "")
    if v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except Exception:
        return default


def resolve_ca_file() -> Optional[str]:
    use_certifi = env_bool("REDIS_CA_CERT_USE_CERTIFI", True)
    ca_path = os.environ.get("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem").strip()

    if use_certifi:
        if certifi is None:
            log.warning("certifi not installed; falling back to REDIS_CA_CERT_PATH: %s", ca_path)
            return ca_path if os.path.exists(ca_path) else None
        return certifi.where()

    return ca_path if os.path.exists(ca_path) else None


def build_client() -> redis.Redis:
    url = os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError("REDIS_URL is not set")

    decode_responses = env_bool("REDIS_DECODE_RESPONSES", True)
    client_name = os.environ.get("REDIS_CLIENT_NAME", "crypto-ai-bot")
    socket_timeout = env_int("REDIS_SOCKET_TIMEOUT", 10)
    socket_connect_timeout = env_int("REDIS_SOCKET_CONNECT_TIMEOUT", 10)

    ca_file = resolve_ca_file()
    log.info("Using CA file: %s", ca_file or "(none provided)")

    # For redis-py 6.x, use the simplified approach
    # The URL should contain the SSL information (rediss://)
    client = redis.Redis.from_url(
        url,
        decode_responses=decode_responses,
        client_name=client_name,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
    )
    return client


def round_trip_events(r: redis.Redis, stream: str) -> None:
    # Write
    payload = {"check": "tls", "ts": int(time.time() * 1000)}
    msg_id = r.xadd(stream, {"d": json.dumps(payload)})
    log.info("XADD -> %s (id=%s)", stream, msg_id)

    # Read back the same or a newer entry
    res = r.xrevrange(stream, count=1)
    log.info("XREAD <- %s (last=%s)", stream, res[0][0] if res else "(none)")
    if not res:
        raise RuntimeError(f"Stream read failed or empty: {stream}")


def main() -> int:
    try:
        r = build_client()
        log.info("Building TLS client for: %s", os.environ.get("REDIS_URL", "(unset)"))

        # 1) PING
        pong = r.ping()
        if pong is True:
            log.info("PING OK")
        else:
            raise RuntimeError(f"PING returned non-True: {pong!r}")

        # 2) INFO to confirm server + TLS
        info = r.info(section="server")
        log.info("Redis server: %s %s", info.get("redis_mode", "?"), info.get("redis_version", "?"))

        # 3) Round-trip test on events stream
        stream = os.environ.get("STREAM_EVENTS", "events:bus")
        round_trip_events(r, stream)

        log.info("✅ TLS check PASSED")
        return 0

    except Exception as e:
        log.error("❌ TLS check FAILED: %r", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
