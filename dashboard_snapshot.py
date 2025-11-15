#!/usr/bin/env python3
"""
Dashboard Snapshot - Single frame view of current metrics.
"""

import asyncio
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import redis.asyncio as redis

load_dotenv('.env.prod')


async def main():
    """Get a snapshot of current metrics."""

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

    print("="*80)
    print(" " * 25 + "CRYPTO-AI-BOT DASHBOARD SNAPSHOT")
    print("="*80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    # Get health
    print("\n[ENGINE HEALTH]")
    print("-" * 80)
    try:
        entries = await client.xrevrange('kraken:health', count=1)
        if entries:
            entry_id, data = entries[0]
            health = {k.decode(): v.decode() for k, v in data.items()}

            print(f"Status: [RUNNING]")
            print(f"Messages Processed: {health.get('messages_received', '0')}")
            print(f"Errors: {health.get('errors', '0')}")
            print(f"Circuit Breaker Trips: {health.get('circuit_breaker_trips', '0')}")
            print(f"Latency: avg {float(health.get('latency_avg', 0)):.1f}ms | " +
                  f"p95 {float(health.get('latency_p95', 0)):.1f}ms | " +
                  f"p99 {float(health.get('latency_p99', 0)):.1f}ms")
            print(f"Redis Latency: {float(health.get('redis_latency_ms', 0)):.1f}ms")
        else:
            print("Status: [NO DATA]")
    except Exception as e:
        print(f"Error: {e}")

    # Get market data
    print("\n[MARKET DATA - LATEST TRADES & SPREADS]")
    print("-" * 80)
    print(f"{'Pair':<12} {'Side':<6} {'Volume':<12} {'Price':<15} {'Spread (bps)'}")
    print("-" * 80)

    pairs = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'ADA-USD']
    for pair in pairs:
        try:
            # Get trade
            trade_entries = await client.xrevrange(f'kraken:trade:{pair}', count=1)
            trade_str = "N/A"
            if trade_entries:
                _, data = trade_entries[0]
                decoded = {k.decode(): v.decode() for k, v in data.items()}
                trades = json.loads(decoded.get('trades', '[]'))
                if trades:
                    t = trades[0]
                    side = t.get('side', 'N/A').upper()
                    volume = float(t.get('volume', 0))
                    price = float(t.get('price', 0))
                    trade_str = f"{side:<6} {volume:<12.4f} ${price:<14.2f}"

            # Get spread
            spread_entries = await client.xrevrange(f'kraken:spread:{pair}', count=1)
            spread_bps = "N/A"
            if spread_entries:
                _, data = spread_entries[0]
                decoded = {k.decode(): v.decode() for k, v in data.items()}
                spread_bps = float(decoded.get('spread_bps', 0))
                spread_bps = f"{spread_bps:.2f}"

            if trade_str != "N/A":
                print(f"{pair:<12} {trade_str} {spread_bps}")
            else:
                print(f"{pair:<12} {'N/A':<6} {'N/A':<12} {'N/A':<15} {spread_bps}")

        except Exception as e:
            print(f"{pair:<12} Error: {str(e)[:50]}")

    # Stream stats
    print("\n[REDIS STREAMS STATISTICS]")
    print("-" * 80)

    streams = {
        'Trades (BTC)': 'kraken:trade:BTC-USD',
        'Trades (ETH)': 'kraken:trade:ETH-USD',
        'Trades (SOL)': 'kraken:trade:SOL-USD',
        'Trades (ADA)': 'kraken:trade:ADA-USD',
        'Spreads (ETH)': 'kraken:spread:ETH-USD',
        'Spreads (SOL)': 'kraken:spread:SOL-USD',
        'Order Books (ETH)': 'kraken:book:ETH-USD',
        'Health Metrics': 'kraken:health',
        'Paper Signals': 'signals:paper',
        'PnL Equity': 'metrics:pnl:equity'
    }

    for name, stream in streams.items():
        try:
            length = await client.xlen(stream)
            print(f"{name:<25} {length:>10} messages")
        except:
            print(f"{name:<25} {'ERROR':>10}")

    print("\n" + "="*80)

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
