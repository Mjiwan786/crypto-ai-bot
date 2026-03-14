"""
One-shot script to export training data from Redis.
Run on laptop with Redis access.

Usage:
    conda activate crypto-bot
    python scripts/export_training_data.py --pairs BTC/USD,ETH/USD,SOL/USD --output data/
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from trainer.data_exporter import DataExporter
from utils.logger import get_logger

logger = get_logger(__name__)


async def _run(args: argparse.Namespace) -> None:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from redis.asyncio import Redis

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        redis_client = Redis.from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        logger.info("Connected to Redis")
    except Exception as e:
        logger.error("Cannot connect to Redis: %s", e)
        logger.info("Use --synthetic flag with trainer/train.py instead")
        sys.exit(1)

    exporter = DataExporter()
    pairs = [p.strip() for p in args.pairs.split(",")]

    for pair in pairs:
        try:
            ohlcv_path = await exporter.export_ohlcv(
                redis_client,
                pair,
                args.timeframe,
                output_path=str(output_dir / f"ohlcv_{pair.replace('/', '_')}_{args.timeframe}s.csv"),
                max_entries=args.max_entries,
            )
            logger.info("Exported OHLCV for %s to %s", pair, ohlcv_path)
        except Exception as e:
            logger.error("Failed to export OHLCV for %s: %s", pair, e)

        try:
            trades_path = await exporter.export_trade_outcomes(
                redis_client,
                pair,
                output_path=str(output_dir / f"trades_{pair.replace('/', '_')}.csv"),
            )
            logger.info("Exported trades for %s to %s", pair, trades_path)
        except Exception as e:
            logger.error("Failed to export trades for %s: %s", pair, e)

    await redis_client.aclose()
    logger.info("Export complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export training data from Redis")
    parser.add_argument("--pairs", type=str, default="BTC/USD", help="Comma-separated pairs")
    parser.add_argument("--output", type=str, default="data/", help="Output directory")
    parser.add_argument("--timeframe", type=int, default=60, help="Timeframe in seconds")
    parser.add_argument("--max-entries", type=int, default=50000, help="Max entries per export")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
