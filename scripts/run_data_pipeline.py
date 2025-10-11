#!/usr/bin/env python3
"""
Data Pipeline Runner for Staging

Simple runner script for the data pipeline that can be used
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

from agents.infrastructure.data_pipeline import DataPipeline, DataPipelineConfig
import aiohttp


async def main():
    """Main entry point for data pipeline"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger("data_pipeline")
    
    try:
        # Load configuration
        config = DataPipelineConfig.from_env()
        logger.info(f"Starting data pipeline with config: {config}")
        
        # Create Redis client
        import redis.asyncio as redis
        ssl_enabled = os.getenv("REDIS_SSL_ENABLED", "false").lower() == "true"
        
        # For Redis Cloud with TLS, use rediss:// protocol
        redis_client = redis.from_url(config.redis_url, decode_responses=config.decode_responses)
        
        # Test Redis connection
        await redis_client.ping()
        logger.info("✅ Redis connection established")
        
        # Create HTTP session
        async with aiohttp.ClientSession() as http_session:
            # Create and run pipeline
            pipeline = DataPipeline(config, redis_client, http_session)
            
            # Set ready flag
            await redis_client.set("md:ready:data_pipeline", "true", ex=300)
            logger.info("✅ Data pipeline ready")
            
            # Run pipeline
            await pipeline.run()
            
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        sys.exit(1)
    finally:
        if 'redis_client' in locals():
            await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
