#!/usr/bin/env python3
"""
Run the Kraken WebSocket engine for 30 seconds with live monitoring.
"""

import asyncio
import os
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load production environment
load_dotenv('.env.prod')

# Import the KrakenWebSocketClient
from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def monitor_stats(client: KrakenWebSocketClient, duration: int = 30):
    """Monitor client stats every 5 seconds."""
    start_time = time.time()
    interval = 5

    print("\n" + "="*70)
    print("ENGINE MONITORING - Stats every 5 seconds")
    print("="*70)

    while time.time() - start_time < duration:
        await asyncio.sleep(interval)

        elapsed = time.time() - start_time
        stats = client.get_stats()

        print(f"\n[TIME] Elapsed: {elapsed:.1f}s / {duration}s")
        print(f"[MSGS] Messages: {stats['messages_received']}")
        print(f"[CONN] Reconnects: {stats['reconnects']}")
        print(f"[ERR]  Errors: {stats['errors']}")
        print(f"[CB]   Circuit breaker trips: {stats['circuit_breaker_trips']}")
        print(f"[TPM]  Trades/min: {stats.get('trades_per_minute', 0)}")

        if stats.get('latency_stats'):
            lat = stats['latency_stats']
            print(f"[LAT]  Latency - avg: {lat['avg']:.2f}ms, p95: {lat['p95']:.2f}ms, p99: {lat['p99']:.2f}ms, max: {lat['max']:.2f}ms")

        if stats.get('circuit_breakers'):
            cb_status = ", ".join([f"{k}:{v}" for k, v in stats['circuit_breakers'].items()])
            print(f"[CB]   Circuit Breakers: {cb_status}")

        print("-" * 70)


async def main():
    """Run engine for 30 seconds with monitoring."""
    print("\n" + "="*70)
    print("STARTING CRYPTO-AI-BOT ENGINE")
    print("="*70)
    print(f"Environment: prod")
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: 30 seconds")
    print("="*70)

    # Create configuration
    config = KrakenWSConfig()
    logger.info(f"Configuration loaded:")
    logger.info(f"  Pairs: {config.pairs}")
    logger.info(f"  Timeframes: {config.timeframes}")
    logger.info(f"  Redis: {config.redis_url[:40]}...")
    logger.info(f"  Latency tracking: {config.enable_latency_tracking}")
    logger.info(f"  Health monitoring: {config.enable_health_monitoring}")
    logger.info(f"  Scalping: {config.scalp_enabled}")

    # Create client
    client = KrakenWebSocketClient(config)

    # Register callbacks for live monitoring
    async def trade_callback(pair: str, trades: list):
        """Log significant trades."""
        for trade in trades:
            if trade['volume'] >= 0.01:
                logger.info(f"[TRADE] {pair} {trade['side'].upper()} {trade['volume']:.4f} @ ${trade['price']:.2f}")

    async def spread_callback(pair: str, spread_data: dict):
        """Log tight spreads."""
        spread_bps = spread_data['spread_bps']
        if spread_bps <= 2.0:
            logger.info(f"[SPREAD] {pair} Tight spread: {spread_bps:.2f} bps")

    async def circuit_breaker_callback(breaker_name: str, reason: str):
        """Log circuit breaker trips."""
        logger.warning(f"[CIRCUIT BREAKER] {breaker_name} - {reason}")

    client.register_callback("trade", trade_callback)
    client.register_callback("spread", spread_callback)
    client.register_callback("circuit_breaker", circuit_breaker_callback)

    # Create tasks
    engine_task = asyncio.create_task(client.start())
    monitor_task = asyncio.create_task(monitor_stats(client, duration=30))

    try:
        # Run for 30 seconds
        await asyncio.wait_for(asyncio.gather(engine_task, monitor_task), timeout=32)
    except asyncio.TimeoutError:
        logger.info("[TIMEOUT] 30-second monitoring period complete")
    except KeyboardInterrupt:
        logger.info("[INTERRUPT] Interrupted by user")
    finally:
        # Stop the engine
        logger.info("Stopping engine...")
        await client.stop()

        # Final stats
        stats = client.get_stats()
        print("\n" + "="*70)
        print("FINAL ENGINE STATISTICS")
        print("="*70)
        print(f"Total messages: {stats['messages_received']}")
        print(f"Total reconnects: {stats['reconnects']}")
        print(f"Total errors: {stats['errors']}")
        print(f"Circuit breaker trips: {stats['circuit_breaker_trips']}")

        if stats.get('latency_stats'):
            lat = stats['latency_stats']
            print(f"\nLatency Statistics:")
            print(f"  Average: {lat['avg']:.2f}ms")
            print(f"  P50 (median): {lat['p50']:.2f}ms")
            print(f"  P95: {lat['p95']:.2f}ms")
            print(f"  P99: {lat['p99']:.2f}ms")
            print(f"  Max: {lat['max']:.2f}ms")

        if stats.get('circuit_breakers'):
            print(f"\nCircuit Breaker Status:")
            for name, state in stats['circuit_breakers'].items():
                print(f"  {name}: {state}")

        print("\n[OK] Engine stopped cleanly")
        print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
