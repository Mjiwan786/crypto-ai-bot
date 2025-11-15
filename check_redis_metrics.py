#!/usr/bin/env python3
"""
Check Redis streams for published metrics from the engine.
"""

import asyncio
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import redis.asyncio as redis

# Load production environment
load_dotenv('.env.prod')


async def check_redis_streams():
    """Check all Redis streams for published metrics."""

    redis_url = os.getenv('REDIS_URL')
    redis_cert = os.getenv('REDIS_TLS_CERT_PATH')

    print("="*70)
    print("REDIS STREAMS INSPECTION")
    print("="*70)
    print(f"Redis URL: {redis_url[:40]}...")
    print(f"TLS Cert: {redis_cert}")
    print("="*70)

    try:
        # Connect to Redis
        client = redis.from_url(
            redis_url,
            ssl_cert_reqs='required',
            ssl_ca_certs=redis_cert,
            socket_connect_timeout=5,
            socket_keepalive=True,
            decode_responses=False
        )

        # Test connection
        await client.ping()
        print("\n[OK] Connected to Redis Cloud\n")

        # Streams to check
        streams_to_check = [
            # Kraken data streams (sharded by pair)
            'kraken:trade:BTC-USD',
            'kraken:trade:ETH-USD',
            'kraken:trade:SOL-USD',
            'kraken:trade:ADA-USD',
            'kraken:spread:BTC-USD',
            'kraken:spread:ETH-USD',
            'kraken:spread:SOL-USD',
            'kraken:spread:ADA-USD',
            'kraken:book:BTC-USD',
            'kraken:book:ETH-USD',
            'kraken:ohlc:BTC-USD',
            'kraken:ohlc:ETH-USD',
            # Health and system metrics
            'kraken:health',
            'system:metrics',
            'ops:heartbeat',
            # Existing streams
            'signals:paper',
            'signals:live',
            'metrics:pnl:equity'
        ]

        print("STREAM STATISTICS")
        print("-" * 70)
        print(f"{'Stream Name':<35} {'Length':<10} {'Last Entry'}")
        print("-" * 70)

        stream_data = {}
        for stream_name in streams_to_check:
            try:
                # Get stream length
                length = await client.xlen(stream_name)

                # Get last entry if stream has data
                last_entry_time = "N/A"
                if length > 0:
                    entries = await client.xrevrange(stream_name, count=1)
                    if entries:
                        entry_id, data = entries[0]
                        # Parse entry ID to get timestamp
                        ts_ms = int(entry_id.split(b'-')[0])
                        last_entry_time = datetime.fromtimestamp(ts_ms/1000).strftime('%H:%M:%S')

                print(f"{stream_name:<35} {length:<10} {last_entry_time}")
                stream_data[stream_name] = length

            except Exception as e:
                print(f"{stream_name:<35} {'ERROR':<10} {str(e)[:30]}")

        print("-" * 70)

        # Show detailed content for key streams
        print("\n\nDETAILED STREAM CONTENT")
        print("="*70)

        # Check kraken:health stream
        print("\n[KRAKEN HEALTH STREAM]")
        print("-" * 70)
        try:
            entries = await client.xrevrange('kraken:health', count=3)
            if entries:
                print(f"Found {len(entries)} recent health entries:")
                for entry_id, data in entries:
                    ts_ms = int(entry_id.split(b'-')[0])
                    ts = datetime.fromtimestamp(ts_ms/1000).strftime('%H:%M:%S')

                    # Decode data
                    decoded = {k.decode(): v.decode() for k, v in data.items()}

                    print(f"\n  Time: {ts}")
                    print(f"  Messages: {decoded.get('messages_received', 'N/A')}")
                    print(f"  Errors: {decoded.get('errors', 'N/A')}")
                    print(f"  Circuit breaker trips: {decoded.get('circuit_breaker_trips', 'N/A')}")
                    print(f"  Latency avg: {decoded.get('latency_avg', 'N/A')} ms")
                    print(f"  Latency p95: {decoded.get('latency_p95', 'N/A')} ms")
                    print(f"  Latency p99: {decoded.get('latency_p99', 'N/A')} ms")
                    print(f"  Redis connected: {decoded.get('redis_connected', 'N/A')}")
                    print(f"  Redis latency: {decoded.get('redis_latency_ms', 'N/A')} ms")
            else:
                print("  No entries found")
        except Exception as e:
            print(f"  Error reading stream: {e}")

        # Check kraken:trade streams
        print("\n\n[KRAKEN TRADE STREAMS]")
        print("-" * 70)
        for pair in ['BTC-USD', 'ETH-USD', 'SOL-USD', 'ADA-USD']:
            stream_name = f'kraken:trade:{pair}'
            try:
                entries = await client.xrevrange(stream_name, count=1)
                if entries:
                    entry_id, data = entries[0]
                    ts_ms = int(entry_id.split(b'-')[0])
                    ts = datetime.fromtimestamp(ts_ms/1000).strftime('%H:%M:%S')

                    decoded = {k.decode(): v.decode() for k, v in data.items()}

                    # Parse trades JSON
                    trades_json = decoded.get('trades', '[]')
                    trades = json.loads(trades_json)

                    print(f"\n  {pair} - Last update: {ts}")
                    print(f"  Batch size: {len(trades)} trades")
                    if trades:
                        trade = trades[0]
                        print(f"  Latest: {trade.get('side', 'N/A').upper()} {trade.get('volume', 0):.4f} @ ${trade.get('price', 0):.2f}")
            except Exception as e:
                print(f"  {pair}: Error - {str(e)[:50]}")

        # Check kraken:spread streams
        print("\n\n[KRAKEN SPREAD STREAMS]")
        print("-" * 70)
        for pair in ['BTC-USD', 'ETH-USD', 'SOL-USD', 'ADA-USD']:
            stream_name = f'kraken:spread:{pair}'
            try:
                entries = await client.xrevrange(stream_name, count=1)
                if entries:
                    entry_id, data = entries[0]
                    ts_ms = int(entry_id.split(b'-')[0])
                    ts = datetime.fromtimestamp(ts_ms/1000).strftime('%H:%M:%S')

                    decoded = {k.decode(): v.decode() for k, v in data.items()}
                    spread_bps = decoded.get('spread_bps', 'N/A')

                    print(f"  {pair}: {spread_bps} bps (Last update: {ts})")
            except Exception as e:
                print(f"  {pair}: Error - {str(e)[:50]}")

        print("\n" + "="*70)
        print("SUMMARY")
        print("="*70)

        total_messages = sum(stream_data.values())
        print(f"Total messages across all streams: {total_messages}")
        print(f"Kraken trade streams: {sum(v for k, v in stream_data.items() if 'kraken:trade' in k)}")
        print(f"Kraken spread streams: {sum(v for k, v in stream_data.items() if 'kraken:spread' in k)}")
        print(f"Kraken book streams: {sum(v for k, v in stream_data.items() if 'kraken:book' in k)}")
        print(f"Health metrics: {stream_data.get('kraken:health', 0)}")

        # Close connection
        await client.aclose()
        print("\n[OK] Redis connection closed")

    except Exception as e:
        print(f"\n[ERROR] Failed to connect to Redis: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(check_redis_streams())
