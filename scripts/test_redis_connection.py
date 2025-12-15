#!/usr/bin/env python3
"""Quick test of Redis connection fix."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig

async def test():
    try:
        config = RedisCloudConfig()
        client = RedisCloudClient(config)
        await client.connect()
        print("[OK] Redis connection successful!")
        await client.ping()
        print("[OK] Redis ping successful!")
        await client.disconnect()
        print("[OK] Redis disconnect successful!")
        return True
    except Exception as e:
        print(f"[FAIL] Redis connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test())
    sys.exit(0 if success else 1)
