#!/usr/bin/env python3
"""
Metrics Publisher for crypto-ai-bot engine.

Publishes compact JSON metrics to Redis:
- engine:metrics:summary (STRING) - Latest metrics snapshot
- engine:metrics:events (STREAM) - Historical metrics events

Usage:
    python -m metrics.publisher              # Run continuously (10s interval)
    python -m metrics.publisher --once       # Publish once and exit
    python -m metrics.publisher --interval 5 # Custom interval
"""

import asyncio
import os
import sys
import time
import logging
import argparse
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

import orjson
import redis.asyncio as redis
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.kraken_ws import KrakenWebSocketClient


logger = logging.getLogger(__name__)


class MetricsPublisher:
    """
    Publishes engine metrics to Redis for consumption by signals-api and signals-site.

    Publishes to:
    - engine:metrics:summary (STRING): Latest metrics JSON
    - engine:metrics:events (STREAM): Time-series metrics events
    """

    def __init__(
        self,
        redis_url: str,
        redis_cert_path: Optional[str] = None,
        ws_client: Optional[KrakenWebSocketClient] = None
    ):
        """
        Initialize MetricsPublisher.

        Args:
            redis_url: Redis connection URL (rediss:// for TLS)
            redis_cert_path: Path to Redis TLS certificate
            ws_client: Optional KrakenWebSocketClient instance to monitor
        """
        self.redis_url = redis_url
        self.redis_cert_path = redis_cert_path
        self.ws_client = ws_client
        self.redis_client: Optional[redis.Redis] = None

        # Metrics state
        self.start_time = time.time()
        self.last_heartbeat = time.time()
        self.last_signal_ts: Optional[float] = None

        # Stream names from config (or defaults)
        self.trading_pairs = os.getenv('TRADING_PAIRS', 'BTC/USD,ETH/USD,SOL/USD,ADA/USD').split(',')
        self.stream_prefix = 'kraken'

    async def connect_redis(self):
        """Connect to Redis Cloud with TLS."""
        try:
            connect_kwargs = {
                'socket_connect_timeout': 5,
                'socket_keepalive': True,
                'decode_responses': False
            }

            if self.redis_url.startswith('rediss://') and self.redis_cert_path:
                connect_kwargs['ssl_cert_reqs'] = 'required'
                connect_kwargs['ssl_ca_certs'] = self.redis_cert_path

            self.redis_client = redis.from_url(
                self.redis_url,
                **connect_kwargs
            )

            # Test connection
            await self.redis_client.ping()
            logger.info("Connected to Redis Cloud")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return False

    async def get_stream_sizes(self) -> Dict[str, int]:
        """Get sizes of all monitored Redis streams."""
        stream_sizes = {}

        # Kraken trade streams (sharded by pair)
        for pair in self.trading_pairs:
            stream_key = pair.replace('/', '-')
            for stream_type in ['trade', 'spread', 'book', 'ohlc']:
                stream_name = f'{self.stream_prefix}:{stream_type}:{stream_key}'
                try:
                    length = await self.redis_client.xlen(stream_name)
                    stream_sizes[stream_name] = length
                except:
                    stream_sizes[stream_name] = 0

        # Other system streams
        for stream_name in ['kraken:health', 'signals:paper', 'signals:live', 'metrics:pnl:equity']:
            try:
                length = await self.redis_client.xlen(stream_name)
                stream_sizes[stream_name] = length
            except:
                stream_sizes[stream_name] = 0

        return stream_sizes

    async def estimate_redis_lag(self) -> float:
        """Estimate Redis latency by measuring PING round-trip time."""
        try:
            start = time.time()
            await self.redis_client.ping()
            lag_ms = (time.time() - start) * 1000
            return round(lag_ms, 2)
        except:
            return -1.0

    async def collect_metrics(self) -> Dict[str, Any]:
        """
        Collect comprehensive metrics from engine components.

        Returns:
            Dict containing all metrics for publishing
        """
        metrics = {
            'timestamp': time.time(),
            'timestamp_iso': datetime.utcnow().isoformat() + 'Z',
            'uptime_s': round(time.time() - self.start_time, 2),
            'last_heartbeat_ts': self.last_heartbeat
        }

        # Kraken WebSocket stats (if client provided)
        if self.ws_client:
            stats = self.ws_client.get_stats()

            # Latency stats
            latency_stats = stats.get('latency_stats', {})
            metrics['ws_latency_ms'] = {
                'avg': round(latency_stats.get('avg', 0), 2),
                'p50': round(latency_stats.get('p50', 0), 2),
                'p95': round(latency_stats.get('p95', 0), 2),
                'p99': round(latency_stats.get('p99', 0), 2),
                'max': round(latency_stats.get('max', 0), 2)
            }

            # Connection stats
            metrics['messages_received'] = stats.get('messages_received', 0)
            metrics['reconnects'] = stats.get('reconnects', 0)
            metrics['circuit_breaker_trips'] = stats.get('circuit_breaker_trips', 0)
            metrics['errors'] = stats.get('errors', 0)
            metrics['trades_per_minute'] = stats.get('trades_per_minute', 0)

            # Running status
            metrics['running'] = stats.get('running', False)

            # Circuit breaker states
            metrics['circuit_breakers'] = stats.get('circuit_breakers', {})

        else:
            # Defaults when no WS client
            metrics['ws_latency_ms'] = {'avg': 0, 'p50': 0, 'p95': 0, 'p99': 0, 'max': 0}
            metrics['messages_received'] = 0
            metrics['reconnects'] = 0
            metrics['circuit_breaker_trips'] = 0
            metrics['errors'] = 0
            metrics['trades_per_minute'] = 0
            metrics['running'] = False
            metrics['circuit_breakers'] = {}

        # Last signal timestamp (if available)
        metrics['last_signal_ts'] = self.last_signal_ts

        # Redis health
        if self.redis_client:
            redis_lag = await self.estimate_redis_lag()
            stream_sizes = await self.get_stream_sizes()

            metrics['redis_ok'] = redis_lag >= 0
            metrics['redis_lag_estimate'] = redis_lag
            metrics['stream_sizes'] = stream_sizes
        else:
            metrics['redis_ok'] = False
            metrics['redis_lag_estimate'] = -1.0
            metrics['stream_sizes'] = {}

        return metrics

    async def publish_metrics(self, metrics: Dict[str, Any]):
        """
        Publish metrics to Redis.

        Publishes to:
        - engine:metrics:summary (STRING): Latest snapshot
        - engine:metrics:events (STREAM): Historical events
        """
        if not self.redis_client:
            logger.error("Redis client not connected")
            return

        try:
            # Serialize metrics to JSON
            metrics_json = orjson.dumps(metrics)

            # 1. Publish to STRING key (latest snapshot)
            await self.redis_client.set('engine:metrics:summary', metrics_json)

            # 2. Append to STREAM (historical events)
            stream_data = {
                'timestamp': str(metrics['timestamp']),
                'data': metrics_json.decode('utf-8')
            }

            await self.redis_client.xadd(
                'engine:metrics:events',
                stream_data,
                maxlen=1000  # Keep last 1000 events
            )

            logger.info(
                f"Published metrics: {metrics['messages_received']} msgs, "
                f"{metrics['circuit_breaker_trips']} CB trips, "
                f"latency avg {metrics['ws_latency_ms']['avg']:.1f}ms"
            )

        except Exception as e:
            logger.error(f"Failed to publish metrics: {e}")

    async def publish_once(self):
        """Collect and publish metrics once."""
        self.last_heartbeat = time.time()
        metrics = await self.collect_metrics()
        await self.publish_metrics(metrics)
        return metrics

    async def run_continuous(self, interval: int = 10):
        """
        Run metrics publisher continuously.

        Args:
            interval: Publish interval in seconds (default: 10)
        """
        logger.info(f"Starting metrics publisher (interval: {interval}s)")

        try:
            while True:
                await self.publish_once()
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            logger.info("Metrics publisher stopped")
        except Exception as e:
            logger.error(f"Error in metrics publisher: {e}")
            raise

    async def close(self):
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.aclose()
            logger.info("Redis connection closed")


async def main():
    """CLI entry point for metrics publisher."""

    # Parse arguments
    parser = argparse.ArgumentParser(description='Crypto-AI-Bot Metrics Publisher')
    parser.add_argument(
        '--once',
        action='store_true',
        help='Publish metrics once and exit'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=10,
        help='Publish interval in seconds (default: 10)'
    )
    parser.add_argument(
        '--env-file',
        type=str,
        default='.env.prod',
        help='Environment file to load (default: .env.prod)'
    )
    parser.add_argument(
        '--with-ws-client',
        action='store_true',
        help='Run with live KrakenWebSocketClient for real stats'
    )
    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load environment
    load_dotenv(args.env_file)

    redis_url = os.getenv('REDIS_URL')
    redis_cert = os.getenv('REDIS_TLS_CERT_PATH')

    if not redis_url:
        logger.error("REDIS_URL not set in environment")
        sys.exit(1)

    # Create publisher
    ws_client = None
    if args.with_ws_client:
        logger.info("Initializing KrakenWebSocketClient for live stats...")
        from utils.kraken_ws import KrakenWSConfig
        config = KrakenWSConfig()
        ws_client = KrakenWebSocketClient(config)

        # Start WS client in background
        asyncio.create_task(ws_client.start())
        await asyncio.sleep(2)  # Let it connect

    publisher = MetricsPublisher(
        redis_url=redis_url,
        redis_cert_path=redis_cert,
        ws_client=ws_client
    )

    # Connect to Redis
    if not await publisher.connect_redis():
        logger.error("Failed to connect to Redis")
        sys.exit(1)

    try:
        if args.once:
            # Publish once and exit
            metrics = await publisher.publish_once()
            print("\n" + "="*70)
            print("METRICS PUBLISHED")
            print("="*70)
            print(orjson.dumps(metrics, option=orjson.OPT_INDENT_2).decode('utf-8'))
            print("="*70)
        else:
            # Run continuously
            await publisher.run_continuous(interval=args.interval)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        if ws_client:
            await ws_client.stop()
        await publisher.close()


if __name__ == '__main__':
    asyncio.run(main())
