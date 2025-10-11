#!/usr/bin/env python3
"""
Execution Agent Runner for Staging (Paper Mode)

Simple runner script for the execution agent that runs in paper mode
for staging testing.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.core.execution_agent import EnhancedExecutionAgent
from config.merge_config import load_config
import redis.asyncio as redis


async def main():
    """Main entry point for execution agent"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger("execution_agent")
    
    try:
        # Get configuration from environment
        input_stream = os.getenv("INPUT_STREAM", "signals:staging")
        output_stream = os.getenv("OUTPUT_STREAM", "exec:paper:confirms")
        mode = os.getenv("MODE", "PAPER")
        
        # Validate mode
        if mode != "PAPER":
            logger.error(f"❌ Execution agent must run in PAPER mode for staging, got: {mode}")
            sys.exit(1)
        
        # Load configuration
        config = load_config("staging")
        logger.info(f"Starting execution agent in {mode} mode")
        
        # Create Redis client
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        ssl_enabled = os.getenv("REDIS_SSL_ENABLED", "false").lower() == "true"
        
        # For Redis Cloud with TLS, use rediss:// protocol
        redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Test Redis connection
        await redis_client.ping()
        logger.info("✅ Redis connection established")
        
        # Create execution agent
        agent = EnhancedExecutionAgent(config)
        
        # Set ready flag
        await redis_client.set("md:ready:execution_agent", "true", ex=300)
        logger.info("✅ Execution agent ready (PAPER mode - no live orders)")
        
        # Run execution agent in paper mode
        await run_paper_mode(agent, redis_client, input_stream, output_stream)
        
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Execution agent error: {e}")
        sys.exit(1)
    finally:
        if 'redis_client' in locals():
            await redis_client.close()


async def run_paper_mode(agent, redis_client, input_stream, output_stream):
    """Run execution agent in paper mode"""
    logger = logging.getLogger("execution_agent")
    
    # Create consumer group
    consumer_group = "execution_paper_group"
    consumer_name = "execution_paper_1"
    
    try:
        await redis_client.xgroup_create(input_stream, consumer_group, id='0', mkstream=True)
    except redis.ResponseError:
        pass  # Group already exists
    
    logger.info(f"Consuming signals from {input_stream}")
    logger.info(f"Publishing confirmations to {output_stream}")
    
    # Main processing loop
    while True:
        try:
            # Read signals
            messages = await redis_client.xreadgroup(
                consumer_group,
                consumer_name,
                {input_stream: '>'},
                count=1,
                block=1000
            )
            
            for stream_name, stream_messages in messages:
                for message_id, fields in stream_messages:
                    # Process signal in paper mode
                    signal_data = {
                        "signal": fields.get("signal", "{}"),
                        "timestamp": fields.get("timestamp", ""),
                        "symbol": fields.get("symbol", ""),
                        "strategy": fields.get("strategy", ""),
                        "side": fields.get("side", ""),
                        "confidence": fields.get("confidence", "0.0")
                    }
                    
                    # Simulate execution (paper mode)
                    confirmation = {
                        "order_id": f"paper_{int(asyncio.get_event_loop().time() * 1000)}",
                        "symbol": signal_data["symbol"],
                        "side": signal_data["side"],
                        "strategy": signal_data["strategy"],
                        "status": "filled",
                        "price": "0.00",  # Paper mode
                        "quantity": "0.00",  # Paper mode
                        "timestamp": str(int(asyncio.get_event_loop().time() * 1000)),
                        "paper_mode": "true",
                        "execution_time_ms": "1.0"
                    }
                    
                    # Publish confirmation
                    await redis_client.xadd(output_stream, confirmation)
                    logger.info(f"📝 Paper execution: {signal_data['symbol']} {signal_data['side']} ({signal_data['strategy']})")
                    
                    # Acknowledge signal
                    await redis_client.xack(input_stream, consumer_group, message_id)
                    
        except redis.ConnectionError:
            logger.error("Redis connection lost, reconnecting...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error processing signal: {e}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
