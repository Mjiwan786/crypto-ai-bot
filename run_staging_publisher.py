"""
Staging Signal Publisher - For testing new trading pairs
Publishes to signals:paper:staging stream (isolated from production)

Usage:
    python run_staging_publisher.py

Environment:
    Loads from .env.staging automatically
    Uses A2 feature flags (PUBLISH_MODE, EXTRA_PAIRS)
"""

import os
import sys
from dotenv import load_dotenv

# Load staging environment FIRST
load_dotenv('.env.staging', override=True)

# Verify staging mode (using A2 feature flags)
publish_mode = os.getenv('PUBLISH_MODE', 'paper')
redis_stream_name = os.getenv('REDIS_STREAM_NAME')
trading_pairs = os.getenv('TRADING_PAIRS', 'BTC/USD,ETH/USD')
extra_pairs = os.getenv('EXTRA_PAIRS', '')

# Determine target stream (same logic as signal_processor.py)
if redis_stream_name:
    target_stream = redis_stream_name
elif publish_mode == 'staging':
    target_stream = 'signals:paper:staging'
elif publish_mode == 'live':
    target_stream = 'signals:live'
else:
    target_stream = os.getenv('STREAM_SIGNALS_PAPER', 'signals:paper')

print("=" * 60)
print("STAGING SIGNAL PUBLISHER")
print("=" * 60)
print(f"PUBLISH_MODE: {publish_mode}")
print(f"Target Stream: {target_stream}")
print(f"Base Pairs: {trading_pairs}")
print(f"Extra Pairs: {extra_pairs}")
print("=" * 60)

# Safety check
if publish_mode != 'staging':
    print("ERROR: PUBLISH_MODE must be 'staging'!")
    print(f"Expected: staging")
    print(f"Got: {publish_mode}")
    sys.exit(1)

if target_stream != 'signals:paper:staging':
    print("ERROR: Target stream is not staging!")
    print(f"Expected: signals:paper:staging")
    print(f"Got: {target_stream}")
    sys.exit(1)

print("\nStarting signal processor in STAGING mode...")
print("Press Ctrl+C to stop\n")

# Import and run the signal processor
import asyncio
from mcp.redis_manager import AsyncRedisManager
from agents.core.signal_processor import SignalProcessor

async def run_staging_publisher():
    """Run staging publisher with Redis manager"""
    # Create Redis manager with staging configuration
    redis_manager = AsyncRedisManager(url=os.getenv('REDIS_URL'))

    # Connect to Redis
    print("Connecting to Redis Cloud...", flush=True)
    connected = await redis_manager.aconnect()
    if not connected:
        print("ERROR: Failed to connect to Redis!", flush=True)
        sys.exit(1)
    print("[OK] Redis connected\n", flush=True)

    # Create and initialize signal processor with Redis manager
    processor = SignalProcessor(redis_manager=redis_manager)

    try:
        await processor.initialize()
        print("[OK] Signal Processor initialized\n", flush=True)

        # Start processing signals
        print("[INFO] Starting signal processing (will run until timeout or Ctrl+C)...\n", flush=True)
        await processor.start()

    except KeyboardInterrupt:
        print("\n\nStopping staging publisher...", flush=True)
    finally:
        # Cleanup
        if processor.running:
            await processor.stop()
        await redis_manager.aclose()
        print("Staging stream preserved for analysis", flush=True)

if __name__ == '__main__':
    try:
        asyncio.run(run_staging_publisher())
    except KeyboardInterrupt:
        print("\n\nShutdown complete")
        sys.exit(0)
