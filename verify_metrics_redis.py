#!/usr/bin/env python3
"""
Verify metrics were published to Redis.
"""

import asyncio
import os
import orjson
from dotenv import load_dotenv
import redis.asyncio as redis

load_dotenv('.env.prod')


async def main():
    """Verify metrics in Redis."""

    redis_url = os.getenv('REDIS_URL')
    redis_cert = os.getenv('REDIS_TLS_CERT_PATH')

    # Connect
    client = redis.from_url(
        redis_url,
        ssl_cert_reqs='required',
        ssl_ca_certs=redis_cert,
        socket_connect_timeout=5,
        socket_keepalive=True,
        decode_responses=False
    )
    await client.ping()

    print("="*70)
    print("VERIFYING METRICS IN REDIS")
    print("="*70)

    # 1. Check STRING key: engine:metrics:summary
    print("\n[1] Checking engine:metrics:summary (STRING)")
    print("-" * 70)
    summary_data = await client.get('engine:metrics:summary')
    if summary_data:
        summary = orjson.loads(summary_data)
        print(f"Status: FOUND")
        print(f"Timestamp: {summary.get('timestamp_iso')}")
        print(f"Uptime: {summary.get('uptime_s')}s")
        print(f"Messages Received: {summary.get('messages_received')}")
        print(f"Redis OK: {summary.get('redis_ok')}")
        print(f"Redis Lag: {summary.get('redis_lag_estimate')}ms")
        print(f"Stream Count: {len(summary.get('stream_sizes', {}))}")
    else:
        print("Status: NOT FOUND")

    # 2. Check STREAM: engine:metrics:events
    print("\n[2] Checking engine:metrics:events (STREAM)")
    print("-" * 70)
    stream_len = await client.xlen('engine:metrics:events')
    print(f"Stream Length: {stream_len} events")

    if stream_len > 0:
        # Get last 3 events
        entries = await client.xrevrange('engine:metrics:events', count=3)
        print(f"\nLast {len(entries)} events:")
        for entry_id, data in entries:
            ts_ms = int(entry_id.split(b'-')[0])
            from datetime import datetime
            ts = datetime.fromtimestamp(ts_ms/1000).strftime('%H:%M:%S')

            decoded = {k.decode(): v.decode() for k, v in data.items()}
            event_data = orjson.loads(decoded['data'])

            print(f"\n  Time: {ts}")
            print(f"  Uptime: {event_data.get('uptime_s')}s")
            print(f"  Messages: {event_data.get('messages_received')}")
            print(f"  CB Trips: {event_data.get('circuit_breaker_trips')}")

    print("\n" + "="*70)
    print("[OK] Verification complete")
    print("="*70)

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
