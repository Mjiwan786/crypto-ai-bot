#!/usr/bin/env python3
"""Check Kraken data flowing into Redis streams"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(".env.prod")

sys.path.insert(0, str(Path(__file__).parent))

from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig

async def check_kraken_streams():
    """Check if Kraken data is flowing"""
    print("[*] Checking Kraken data streams in Redis...")

    try:
        config = RedisCloudConfig(
            url=os.getenv("REDIS_URL", ""),
            ca_cert_path="config/certs/redis_ca.pem"
        )

        async with RedisCloudClient(config) as client:
            print("[OK] Connected to Redis Cloud")

            # Check Kraken streams
            kraken_streams = [
                "kraken:trade:BTC-USD",
                "kraken:trade:ETH-USD",
                "kraken:spread:BTC-USD",
                "kraken:ohlc:BTC-USD",
                "kraken:health"
            ]

            for stream in kraken_streams:
                try:
                    # Check stream length
                    length = await client.client.xlen(stream)

                    if length > 0:
                        # Get latest message
                        messages = await client.client.xrevrange(stream, '+', '-', count=1)
                        if messages:
                            msg_id, fields = messages[0]
                            timestamp_ms = int(msg_id.decode('utf-8').split('-')[0])
                            age_sec = (asyncio.get_event_loop().time() * 1000 - timestamp_ms) / 1000

                            print(f"[OK] {stream}: {length} messages, latest {age_sec:.1f}s ago")
                        else:
                            print(f"[WARN] {stream}: {length} messages but couldn't read latest")
                    else:
                        print(f"[EMPTY] {stream}: No messages")

                except Exception as e:
                    print(f"[ERROR] {stream}: {e}")

            # Check signals stream too
            signals_stream = "signals:paper"
            try:
                length = await client.client.xlen(signals_stream)
                messages = await client.client.xrevrange(signals_stream, '+', '-', count=1)
                if messages:
                    msg_id, fields = messages[0]
                    timestamp_ms = int(msg_id.decode('utf-8').split('-')[0])
                    age_sec = (asyncio.get_event_loop().time() * 1000 - timestamp_ms) / 1000
                    print(f"\n[OK] {signals_stream}: {length} signals, latest {age_sec:.1f}s ago")
                else:
                    print(f"\n[WARN] {signals_stream}: No messages")
            except Exception as e:
                print(f"\n[ERROR] {signals_stream}: {e}")

            print("\n[PASS] Stream check complete!")
            return True

    except Exception as e:
        print(f"\n[FAIL] Stream check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(check_kraken_streams())
    sys.exit(0 if result else 1)
