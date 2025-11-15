#!/usr/bin/env python3
"""
Demo: Run metrics publisher with live Kraken WebSocket client for 15 seconds.
Shows real-time metrics being collected and published.
"""

import asyncio
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig
from metrics.publisher import MetricsPublisher

load_dotenv('.env.prod')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Run live demo."""

    print("="*70)
    print(" " * 15 + "METRICS PUBLISHER LIVE DEMO")
    print("="*70)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: 15 seconds")
    print("="*70)

    # Create Kraken WS client
    logger.info("Initializing Kraken WebSocket client...")
    config = KrakenWSConfig()
    ws_client = KrakenWebSocketClient(config)

    # Create metrics publisher
    redis_url = os.getenv('REDIS_URL')
    redis_cert = os.getenv('REDIS_TLS_CERT_PATH')

    publisher = MetricsPublisher(
        redis_url=redis_url,
        redis_cert_path=redis_cert,
        ws_client=ws_client  # Pass WS client for real stats
    )

    # Connect to Redis
    await publisher.connect_redis()

    # Start WS client
    ws_task = asyncio.create_task(ws_client.start())

    # Wait for WS to connect
    logger.info("Waiting for WebSocket to connect...")
    await asyncio.sleep(3)

    # Publish metrics every 5 seconds for 15 seconds total
    print("\n" + "-"*70)
    print("Publishing metrics every 5 seconds...")
    print("-"*70)

    for i in range(3):
        await asyncio.sleep(5)

        # Publish metrics
        metrics = await publisher.publish_once()

        print(f"\n[Metrics #{i+1} at {datetime.now().strftime('%H:%M:%S')}]")
        print(f"  Messages Received: {metrics['messages_received']}")
        print(f"  Errors: {metrics['errors']}")
        print(f"  Circuit Breaker Trips: {metrics['circuit_breaker_trips']}")
        print(f"  Trades/min: {metrics['trades_per_minute']}")
        print(f"  Latency avg: {metrics['ws_latency_ms']['avg']:.2f}ms")
        print(f"  Latency p95: {metrics['ws_latency_ms']['p95']:.2f}ms")
        print(f"  Latency p99: {metrics['ws_latency_ms']['p99']:.2f}ms")
        print(f"  Redis Lag: {metrics['redis_lag_estimate']:.2f}ms")
        print(f"  Running: {metrics['running']}")

    # Stop
    print("\n" + "-"*70)
    print("Stopping demo...")
    await ws_client.stop()
    ws_task.cancel()
    try:
        await ws_task
    except asyncio.CancelledError:
        pass

    await publisher.close()

    print("\n" + "="*70)
    print("[OK] Demo complete - Metrics published to Redis")
    print("="*70)
    print("\nCheck Redis keys:")
    print("  - engine:metrics:summary (STRING)")
    print("  - engine:metrics:events (STREAM)")
    print("="*70)


if __name__ == '__main__':
    asyncio.run(main())
