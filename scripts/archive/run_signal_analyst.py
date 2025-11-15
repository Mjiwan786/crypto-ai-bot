#!/usr/bin/env python3
"""
Signal Analyst Runner for Staging

Simple runner script for the signal analyst that can be used
as a standalone process in the staging pipeline.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import redis.asyncio as redis

from agents.core.signal_analyst import SignalAnalyst
from config.merge_config import load_config


async def main():
    """Main entry point for signal analyst"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger("signal_analyst")
    
    try:
        # Get configuration from environment
        symbol = os.getenv("SYMBOL", "BTC/USD")
        strategy = os.getenv("STRATEGY", "scalping")
        output_stream = os.getenv("OUTPUT_STREAM", "signals:staging")
        
        # Load configuration
        config = load_config("staging")
        logger.info(f"Starting signal analyst: {strategy} on {symbol}")
        
        # Create a simple config object for the signal analyst
        class SimpleConfig:
            def __init__(self, config_dict):
                self.log_level = config_dict.get("logging", {}).get("level", "INFO")
                self.dry_run = config_dict.get("dev_overrides", {}).get("dry_run", True)
                self.feature_window = 100
                self.streams = {"out_signals": output_stream}
        
        simple_config = SimpleConfig(config)
        
        # Create Redis client
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        ssl_enabled = os.getenv("REDIS_SSL_ENABLED", "false").lower() == "true"
        
        # For Redis Cloud with TLS, use rediss:// protocol
        redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Test Redis connection
        await redis_client.ping()
        logger.info("✅ Redis connection established")
        
        # Create signal analyst
        analyst = SignalAnalyst(
            redis=redis_client,
            symbol=symbol,
            strategy=strategy,
            config=simple_config,
            stream_out=output_stream
        )
        
        # Set ready flag
        await redis_client.set(f"md:ready:signal_analyst_{strategy}", "true", ex=300)
        logger.info(f"✅ Signal analyst ready: {strategy} on {symbol}")
        
        # Run analyst
        await analyst.run()
        
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Signal analyst error: {e}")
        sys.exit(1)
    finally:
        if 'redis_client' in locals():
            await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
