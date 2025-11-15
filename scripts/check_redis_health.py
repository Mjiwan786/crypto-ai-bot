"""
Quick Redis Health Check Script

Checks Redis Cloud health metrics and streams.
"""
import os
import asyncio
import redis.asyncio as redis
from datetime import datetime

# Set Redis URL
os.environ['REDIS_URL'] = 'rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818'


async def check_redis_health():
    """Check Redis Cloud health."""
    print("=" * 80)
    print("REDIS CLOUD HEALTH CHECK")
    print("=" * 80)

    try:
        # Connect to Redis
        client = await redis.from_url(
            os.getenv('REDIS_URL'),
            ssl_cert_reqs='required',
            decode_responses=True,
            socket_timeout=10
        )

        # Test connection
        await client.ping()
        print("\n[OK] Connection: SUCCESS")

        # Memory info
        print("\n" + "-" * 80)
        print("MEMORY USAGE")
        print("-" * 80)
        info = await client.info('memory')
        used_mb = int(info['used_memory']) / 1024 / 1024
        peak_mb = int(info.get('used_memory_peak', 0)) / 1024 / 1024
        print(f"Used Memory: {used_mb:.2f} MB")
        print(f"Peak Memory: {peak_mb:.2f} MB")
        print(f"Memory Fragmentation: {info.get('mem_fragmentation_ratio', 'N/A')}")

        # Keyspace info
        print("\n" + "-" * 80)
        print("KEYSPACE")
        print("-" * 80)
        keyspace = await client.info('keyspace')
        if keyspace:
            for db, stats in keyspace.items():
                print(f"{db}: {stats}")
        else:
            print("No keys in database")

        # Check Kraken streams
        print("\n" + "-" * 80)
        print("KRAKEN STREAMS")
        print("-" * 80)

        streams_to_check = [
            'kraken:trade:BTC-USD',
            'kraken:trade:ETH-USD',
            'kraken:spread:BTC-USD',
            'kraken:spread:ETH-USD',
            'kraken:health'
        ]

        for stream in streams_to_check:
            try:
                info = await client.xinfo_stream(stream)
                length = info['length']
                first_entry = info.get('first-entry')
                last_entry = info.get('last-entry')

                print(f"\n{stream}:")
                print(f"  Length: {length} messages")

                if first_entry:
                    print(f"  First: {first_entry[0].decode() if isinstance(first_entry[0], bytes) else first_entry[0]}")
                if last_entry:
                    print(f"  Last: {last_entry[0].decode() if isinstance(last_entry[0], bytes) else last_entry[0]}")

            except Exception as e:
                print(f"\n{stream}: Not found or error ({str(e)[:50]})")

        # Check latest health metrics
        print("\n" + "-" * 80)
        print("LATEST HEALTH METRICS")
        print("-" * 80)

        try:
            health_entries = await client.xrevrange('kraken:health', count=1)
            if health_entries:
                entry_id, data = health_entries[0]
                print(f"Timestamp: {entry_id}")

                metrics = [
                    'messages_received',
                    'trades_per_minute',
                    'circuit_breaker_trips',
                    'errors',
                    'running'
                ]

                for metric in metrics:
                    if metric in data:
                        print(f"  {metric}: {data[metric]}")

        except Exception as e:
            print(f"No health metrics found: {e}")

        # Close connection
        await client.aclose()
        print("\n" + "=" * 80)
        print("[OK] HEALTH CHECK COMPLETE")
        print("=" * 80)

    except Exception as e:
        print(f"\n[ERROR]: {e}")
        return False

    return True


if __name__ == '__main__':
    asyncio.run(check_redis_health())
