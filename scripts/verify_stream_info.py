#!/usr/bin/env python3
"""
Verify Stream Info - Redis CLI equivalent commands

Executes:
- XRANGE signals:live - + COUNT 5
- XINFO STREAM signals:live
- XLEN signals:live
- XLEN signals:paper
- XLEN metrics:pnl:equity
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import redis.asyncio as aioredis
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ Missing packages: {e}")
    sys.exit(1)

# Load environment
env_file = project_root / ".env.prod"
if env_file.exists():
    load_dotenv(env_file)

REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_CA_CERT = os.getenv("REDIS_CA_CERT", "./config/certs/redis_ca.pem")


async def main():
    """Run Redis CLI equivalent commands"""

    if not REDIS_URL:
        print("❌ REDIS_URL not set")
        return 1

    # Resolve CA cert
    ca_cert_path = Path(REDIS_CA_CERT)
    if not ca_cert_path.is_absolute():
        ca_cert_path = project_root / ca_cert_path

    use_tls = REDIS_URL.startswith("rediss://")

    if use_tls and not ca_cert_path.exists():
        print(f"❌ Redis CA cert not found: {ca_cert_path}")
        return 2

    try:
        # Create client
        if use_tls:
            client = await aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                ssl_cert_reqs="required",
                ssl_ca_certs=str(ca_cert_path),
                ssl_check_hostname=True,
                socket_connect_timeout=10,
                socket_timeout=10,
            )
        else:
            client = await aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=10,
                socket_timeout=10,
            )

        await client.ping()
        print("✅ Connected to Redis\n")

        # Command 1: XRANGE signals:live - + COUNT 5
        print("=" * 70)
        print("Command: XRANGE signals:live - + COUNT 5")
        print("=" * 70)
        messages = await client.xrange("signals:live", "-", "+", count=5)
        for msg_id, fields in messages:
            print(f"Message ID: {msg_id}")
            for key, value in fields.items():
                if len(value) > 200:
                    value = value[:200] + "..."
                print(f"  {key}: {value}")
            print()

        # Command 2: XLEN signals:live
        print("=" * 70)
        print("Command: XLEN signals:live")
        print("=" * 70)
        length = await client.xlen("signals:live")
        print(f"Stream length: {length}\n")

        # Command 3: XINFO STREAM signals:live
        print("=" * 70)
        print("Command: XINFO STREAM signals:live")
        print("=" * 70)
        info = await client.execute_command("XINFO", "STREAM", "signals:live")

        # Parse info (returned as list of [key, value, ...])
        info_dict = {}
        for i in range(0, len(info), 2):
            key = info[i].decode('utf-8') if isinstance(info[i], bytes) else info[i]
            value = info[i+1]
            if isinstance(value, bytes):
                value = value.decode('utf-8')
            info_dict[key] = value

        for key, value in info_dict.items():
            # Skip complex nested structures for readability
            if key in ['first-entry', 'last-entry']:
                if isinstance(value, (list, tuple)) and len(value) > 0:
                    print(f"{key}: [{value[0]}]")
                else:
                    print(f"{key}: {value}")
            else:
                print(f"{key}: {value}")
        print()

        # Additional: Check other streams
        print("=" * 70)
        print("Stream Lengths Summary")
        print("=" * 70)
        for stream in ["signals:live", "signals:paper", "metrics:pnl:equity", "ops:heartbeat"]:
            try:
                length = await client.xlen(stream)
                maxlen = {
                    "signals:live": int(os.getenv("STREAM_MAXLEN_SIGNALS", "10000")),
                    "signals:paper": int(os.getenv("STREAM_MAXLEN_SIGNALS", "10000")),
                    "metrics:pnl:equity": int(os.getenv("STREAM_MAXLEN_PNL", "5000")),
                    "ops:heartbeat": int(os.getenv("STREAM_MAXLEN_HEARTBEAT", "1000")),
                }
                expected = maxlen.get(stream, 10000)
                status = "✅ BOUNDED" if length <= expected + 100 else "⚠️ OVER LIMIT"
                print(f"{stream:<25} {length:>6} / {expected:>6}  {status}")
            except Exception as e:
                print(f"{stream:<25} ERROR: {e}")

        await client.aclose()
        return 0

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n❌ Interrupted")
        sys.exit(130)
