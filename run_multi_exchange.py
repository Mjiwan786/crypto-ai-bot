"""
Multi-Exchange WebSocket Streamer — Entry Point
=================================================

Run alongside production_engine.py to add multi-exchange feeds.
Public market data only — no API keys required.

Usage:
    # All 7 new exchanges (Kraken handled by production_engine.py)
    python run_multi_exchange.py

    # Specific exchanges
    python run_multi_exchange.py --exchanges coinbase,binance,bybit

    # Custom pairs
    python run_multi_exchange.py --pairs BTC/USD,ETH/USD,SOL/USD

Environment:
    REDIS_URL       — Redis Cloud connection URL (required, rediss://)
    REDIS_CA_CERT   — Path to Redis TLS CA certificate (optional)
    TRADING_PAIRS   — Comma-separated pairs (optional override)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from agents.multi_exchange_signal_generator import MultiExchangeSignalGenerator
from exchange.multi_exchange_streamer import MultiExchangeStreamer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Default: all exchanges EXCEPT Kraken (handled by production_engine.py)
DEFAULT_EXCHANGES = "coinbase,binance,bybit,okx,kucoin,gateio,bitfinex"
DEFAULT_PAIRS = "BTC/USD,ETH/USD,SOL/USD,LINK/USD"
DEFAULT_TIMEFRAMES = "1m,5m,15m,1h"


async def main(args: argparse.Namespace) -> None:
    """Connect to Redis and start the multi-exchange streamer."""
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        logger.error("REDIS_URL environment variable is required")
        sys.exit(1)

    redis_config = RedisCloudConfig(
        url=redis_url,
        ca_cert_path=os.getenv("REDIS_CA_CERT", "") or None,
    )
    redis_client = RedisCloudClient(redis_config)
    await redis_client.connect()

    if not redis_client.is_connected():
        logger.error("Failed to connect to Redis")
        sys.exit(1)

    exchanges = [e.strip() for e in args.exchanges.split(",") if e.strip()]
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    logger.info("Starting multi-exchange streamer")
    logger.info("  Exchanges: %s", exchanges)
    logger.info("  Pairs: %s", pairs)
    logger.info("  Timeframes: %s", timeframes)

    streamer = MultiExchangeStreamer(
        redis_client=redis_client.client,
        exchanges=exchanges,
        pairs=pairs,
        timeframes=timeframes,
    )

    signal_gen = MultiExchangeSignalGenerator(
        redis_client=redis_client.client,
        exchanges=exchanges,
        pairs=pairs,
        mode=args.mode,
        poll_interval=30,
    )

    try:
        # Run streamer (WebSocket → Redis) and signal generator (Redis → signals)
        # concurrently. Streamer feeds OHLCV data, signal gen reads it and publishes signals.
        await asyncio.gather(
            streamer.start(),
            signal_gen.run(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await signal_gen.stop()
        await streamer.stop()
        await redis_client.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Multi-Exchange WebSocket Streamer"
    )
    parser.add_argument(
        "--exchanges",
        default=os.getenv("STREAM_EXCHANGES", DEFAULT_EXCHANGES),
        help="Comma-separated exchange IDs",
    )
    parser.add_argument(
        "--pairs",
        default=os.getenv("TRADING_PAIRS", DEFAULT_PAIRS),
        help="Comma-separated trading pairs",
    )
    parser.add_argument(
        "--timeframes",
        default=os.getenv("STREAM_TIMEFRAMES", DEFAULT_TIMEFRAMES),
        help="Comma-separated OHLCV timeframes",
    )
    parser.add_argument(
        "--mode",
        default=os.getenv("ENGINE_MODE", "paper"),
        help="Signal mode: paper or live",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
