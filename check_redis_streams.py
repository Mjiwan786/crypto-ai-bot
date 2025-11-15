#!/usr/bin/env python3
"""Quick script to check Redis stream status."""

import asyncio
import os
from dotenv import load_dotenv
import redis.asyncio as redis

load_dotenv('.env.prod')

async def check_streams():
    redis_url = os.getenv('REDIS_URL')
    redis_cert = os.getenv('REDIS_TLS_CERT_PATH')

    client = redis.from_url(
        redis_url,
        ssl_cert_reqs='required',
        ssl_ca_certs=redis_cert,
        decode_responses=False
    )

    streams = [
        'system:metrics',
        'kraken:health',
        'ops:heartbeat',
        'signals:paper',
        'metrics:pnl:equity'
    ]

    print("Redis Stream Status:")
    print("=" * 60)
    for stream in streams:
        try:
            length = await client.xlen(stream)
            print(f"{stream:25} {length:>10} messages")

            if length > 0:
                # Get latest entry
                entries = await client.xrevrange(stream, '+', '-', count=1)
                if entries:
                    msg_id, fields = entries[0]
                    print(f"  Latest: {msg_id.decode()} ")
        except Exception as e:
            print(f"{stream:25} ERROR: {e}")

    await client.aclose()

asyncio.run(check_streams())
