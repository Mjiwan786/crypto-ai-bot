"""
Canary Publisher for D3 Promotion
Publishes SOL/USD, ADA/USD to PRODUCTION stream (signals:paper)
WITHOUT touching Fly.io deployment

Safety:
- Runs locally alongside Fly.io publisher
- Instant rollback via process kill
- Logs all activity to logs/canary_deployment.log
"""
import os
import sys
import asyncio
import time
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load canary environment
load_dotenv('.env.canary')

print("=" * 70, flush=True)
print("CANARY PUBLISHER - D3 PROMOTION", flush=True)
print("=" * 70, flush=True)
print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
print(f"Mode: {os.getenv('PUBLISH_MODE', 'UNKNOWN')}", flush=True)
print(f"Stream: {os.getenv('REDIS_STREAM_NAME', 'UNKNOWN')}", flush=True)
print(f"Base Pairs: {os.getenv('TRADING_PAIRS', 'UNKNOWN')}", flush=True)
print(f"Extra Pairs: {os.getenv('EXTRA_PAIRS', 'UNKNOWN')}", flush=True)
print("=" * 70, flush=True)
print("", flush=True)

# Verify targeting production stream
stream_name = os.getenv('REDIS_STREAM_NAME', '')
if stream_name != 'signals:paper':
    print(f"ERROR: Expected signals:paper, got {stream_name}", flush=True)
    print("Canary must target PRODUCTION stream", flush=True)
    sys.exit(1)

# Verify we have EXTRA_PAIRS
extra_pairs = os.getenv('EXTRA_PAIRS', '')
if not extra_pairs:
    print("ERROR: EXTRA_PAIRS not set", flush=True)
    print("Canary requires SOL/USD,ADA/USD", flush=True)
    sys.exit(1)

print("[OK] Configuration validated", flush=True)
print(f"[OK] Targeting production stream: {stream_name}", flush=True)
print(f"[OK] Canary pairs: {extra_pairs}", flush=True)
print("", flush=True)

# Import signal processor
try:
    from mcp.redis_manager import AsyncRedisManager
    from agents.core.signal_processor import SignalProcessor
    print("[OK] Modules imported successfully", flush=True)
except ImportError as e:
    print(f"ERROR: Failed to import modules: {e}", flush=True)
    sys.exit(1)

async def run_canary():
    """Run canary publisher"""
    # Create Redis manager
    redis_url = os.getenv('REDIS_URL')
    if not redis_url:
        print("ERROR: REDIS_URL not set", flush=True)
        sys.exit(1)

    redis_manager = AsyncRedisManager(url=redis_url)

    print("Connecting to Redis Cloud...", flush=True)
    connected = await redis_manager.aconnect()
    if not connected:
        print("ERROR: Failed to connect to Redis", flush=True)
        sys.exit(1)
    print("[OK] Redis connected", flush=True)
    print("", flush=True)

    # Create signal processor
    processor = SignalProcessor(redis_manager=redis_manager)

    try:
        print("Initializing Signal Processor...", flush=True)
        await processor.initialize()
        print("[OK] Signal Processor initialized", flush=True)
        print("", flush=True)

        print("=" * 70, flush=True)
        print("CANARY ACTIVE - Publishing to signals:paper", flush=True)
        print("Pairs: BTC-USD, ETH-USD (from Fly.io) + SOL-USD, ADA-USD (canary)", flush=True)
        print("Press Ctrl+C to stop canary deployment", flush=True)
        print("=" * 70, flush=True)
        print("", flush=True)

        # Start publisher
        await processor.start()
    except KeyboardInterrupt:
        print("", flush=True)
        print("=" * 70, flush=True)
        print("CANARY STOPPED - Keyboard Interrupt", flush=True)
        print("=" * 70, flush=True)
    except Exception as e:
        print("", flush=True)
        print("=" * 70, flush=True)
        print(f"CANARY ERROR: {e}", flush=True)
        print("=" * 70, flush=True)
        raise
    finally:
        if processor.running:
            print("Stopping Signal Processor...", flush=True)
            await processor.stop()
        await redis_manager.aclose()
        print("[OK] Canary shutdown complete", flush=True)
        print("", flush=True)
        print("Production stream preserved (signals:paper)", flush=True)
        print("Fly.io publisher continues with BTC-USD, ETH-USD", flush=True)

if __name__ == "__main__":
    print("Starting canary publisher...", flush=True)
    print("", flush=True)
    asyncio.run(run_canary())
