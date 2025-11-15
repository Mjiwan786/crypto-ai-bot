#!/usr/bin/env python3
"""
Production wrapper for Kraken Data Pipeline.
Runs continuously with proper environment configuration and Redis Cloud support.
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Configure UTF-8 encoding for Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(project_root / ".env.dev")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Import pipeline after env is loaded
from agents.infrastructure.data_pipeline import DataPipeline, DataPipelineConfig
from agents.infrastructure.redis_client import create_data_pipeline_redis_client
import aiohttp


# Global shutdown flag
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


async def run_pipeline_forever():
    """Run the data pipeline indefinitely until shutdown"""
    global shutdown_requested

    # Load configuration
    try:
        config = DataPipelineConfig.from_env()
        logger.info("✅ Configuration loaded successfully")
        logger.info(f"   Pairs: {config.pairs}")
        logger.info(f"   Timeframes: {config.timeframes}")
        logger.info(f"   Redis URL: {config.redis_url[:50]}...")
    except Exception as e:
        logger.error(f"❌ Configuration error: {e}")
        sys.exit(1)

    # Validate environment
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        logger.error("❌ REDIS_URL environment variable not set")
        sys.exit(1)

    # Create Redis connection
    try:
        redis_client = await create_data_pipeline_redis_client()
        await redis_client.ping()
        logger.info("✅ Redis Cloud connection successful")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        sys.exit(1)

    # Create HTTP session and pipeline
    async with aiohttp.ClientSession() as http:
        def metric_handler(name: str, value: float, tags: dict) -> None:
            """Log metrics"""
            if name in ["trades_ingested", "candles_ingested", "circuit_breaker_opened"]:
                logger.info(f"📊 METRIC: {name}={value} {tags}")

        def event_handler(event: dict) -> None:
            """Log important events"""
            event_type = event.get("type", "unknown")
            if event_type in ["pipeline.started", "pipeline.stopped", "pipeline.error"]:
                logger.info(f"📢 EVENT: {event_type}")

        # Create pipeline
        pipeline = DataPipeline(
            config, redis_client, http,
            on_metric=metric_handler,
            on_event=event_handler
        )

        try:
            logger.info("🚀 Starting Kraken Data Pipeline (24/7 mode)...")
            await pipeline.start()

            # Run forever until shutdown
            while not shutdown_requested:
                await asyncio.sleep(1)

            logger.info("⚠️ Shutdown requested, stopping pipeline...")

        except KeyboardInterrupt:
            logger.info("⚠️ Interrupted by user, stopping pipeline...")
        except Exception as e:
            logger.error(f"❌ Pipeline error: {e}", exc_info=True)
        finally:
            await pipeline.stop()
            try:
                await redis_client.aclose()
            except Exception:
                pass
            logger.info("✅ Data pipeline stopped cleanly")


if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("=" * 80)
    logger.info("🚀 Kraken Data Pipeline - Production Mode")
    logger.info("=" * 80)

    try:
        asyncio.run(run_pipeline_forever())
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)

    logger.info("👋 Data pipeline shutdown complete")
