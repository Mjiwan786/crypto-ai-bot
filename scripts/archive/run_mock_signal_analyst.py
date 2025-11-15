#!/usr/bin/env python3
"""
Mock Signal Analyst Runner for Staging

Simple mock signal analyst that generates test signals for staging testing.
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
    """Main entry point for mock signal analyst"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger("mock_signal_analyst")
    
    try:
        # Get configuration from environment
        symbol = os.getenv("SYMBOL", "BTC/USD")
        strategy = os.getenv("STRATEGY", "scalping")
        output_stream = os.getenv("OUTPUT_STREAM", "signals:staging")
        
        logger.info(f"Starting mock signal analyst: {strategy} on {symbol}")
        
        # Create Redis client
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Test Redis connection
        await redis_client.ping()
        logger.info("✅ Redis connection established")
        
        # Set ready flag
        await redis_client.set(f"md:ready:signal_analyst_{strategy}", "true", ex=300)
        logger.info(f"✅ Mock signal analyst ready: {strategy} on {symbol}")
        
        # Mock signal generation loop
        signal_count = 0
        while True:
            try:
                # Generate mock signal
                signal_count += 1
                signal_data = {
                    "signal": f'{{"action": "buy", "confidence": 0.75, "timestamp": {int(time.time() * 1000)}}}',
                    "timestamp": str(int(time.time() * 1000)),
                    "symbol": symbol,
                    "strategy": strategy,
                    "side": "buy" if signal_count % 2 == 0 else "sell",
                    "confidence": "0.75"
                }
                
                # Publish signal
                await redis_client.xadd(output_stream, signal_data)
                logger.info(f"📊 Generated mock signal #{signal_count}: {symbol} {signal_data['side']} ({strategy})")
                
                # Wait before next signal
                await asyncio.sleep(30)  # Generate signal every 30 seconds
                
            except Exception as e:
                logger.error(f"Error generating signal: {e}")
                await asyncio.sleep(5)
        
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Mock signal analyst error: {e}")
        sys.exit(1)
    finally:
        if 'redis_client' in locals():
            await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())

