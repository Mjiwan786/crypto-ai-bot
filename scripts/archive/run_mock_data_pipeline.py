#!/usr/bin/env python3
"""
Mock Data Pipeline Runner for Staging

Simple mock data pipeline that generates test market data for staging testing.
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import redis.asyncio as redis


async def main():
    """Main entry point for mock data pipeline"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger("mock_data_pipeline")
    
    try:
        # Get configuration from environment
        trading_pairs = os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD,SOL/USD").split(",")
        timeframes = os.getenv("TIMEFRAMES", "1m,5m").split(",")
        
        logger.info(f"Starting mock data pipeline for pairs: {trading_pairs}")
        
        # Create Redis client
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Test Redis connection
        await redis_client.ping()
        logger.info("✅ Redis connection established")
        
        # Set ready flag
        await redis_client.set("md:ready:data_pipeline", "true", ex=300)
        logger.info("✅ Mock data pipeline ready")
        
        # Mock data generation loop
        message_count = 0
        while True:
            try:
                current_time = int(time.time() * 1000)
                message_count += 1
                
                # Generate mock market data for each pair
                for pair in trading_pairs:
                    # Mock orderbook data
                    orderbook_data = {
                        "symbol": pair,
                        "timestamp": str(current_time),
                        "bids": [["50000.00", "1.5"], ["49999.50", "2.0"]],
                        "asks": [["50001.00", "1.2"], ["50001.50", "1.8"]],
                        "source": "mock"
                    }
                    await redis_client.xadd("md:orderbook", orderbook_data)
                    
                    # Mock trades data
                    trades_data = {
                        "symbol": pair,
                        "timestamp": str(current_time),
                        "price": "50000.50",
                        "quantity": "0.1",
                        "side": "buy" if message_count % 2 == 0 else "sell",
                        "source": "mock"
                    }
                    await redis_client.xadd("md:trades", trades_data)
                    
                    # Mock spread data
                    spread_data = {
                        "symbol": pair,
                        "timestamp": str(current_time),
                        "spread": "1.00",
                        "spread_bps": "2.0",
                        "source": "mock"
                    }
                    await redis_client.xadd("md:spread", spread_data)
                
                logger.info(f"📊 Generated mock market data #{message_count} for {len(trading_pairs)} pairs")
                
                # Wait before next batch
                await asyncio.sleep(5)  # Generate data every 5 seconds
                
            except Exception as e:
                logger.error(f"Error generating market data: {e}")
                await asyncio.sleep(5)
        
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Mock data pipeline error: {e}")
        sys.exit(1)
    finally:
        if 'redis_client' in locals():
            await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())








