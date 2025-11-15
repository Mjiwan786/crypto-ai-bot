#!/usr/bin/env python3
import asyncio
import redis.asyncio as redis
import os
import time
from dotenv import load_dotenv

load_dotenv(".env.prod")

async def check_latest():
    r = redis.from_url(os.getenv("REDIS_URL"), ssl_cert_reqs='required', decode_responses=False)

    # Check signals:paper
    result = await r.xrevrange('signals:paper', '+', '-', count=1)
    if result:
        msg_id = result[0][0].decode()
        ts_ms = int(msg_id.split("-")[0])
        age_sec = (time.time() * 1000 - ts_ms) / 1000

        print(f"[OK] Latest signal: {msg_id}")
        print(f"[OK] Age: {age_sec:.1f}s ago")

        # Parse signal data
        fields = result[0][1]
        if b'json' in fields:
            import json
            signal_data = json.loads(fields[b'json'].decode())
            print(f"[OK] Signal: {signal_data.get('pair', 'N/A')} - {signal_data.get('signal', 'N/A')}")
    else:
        print("[WARN] No signals found")

    await r.aclose()

if __name__ == "__main__":
    asyncio.run(check_latest())
