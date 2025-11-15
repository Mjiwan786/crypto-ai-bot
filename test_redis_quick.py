#!/usr/bin/env python3
"""Quick Redis Cloud connectivity test"""
import asyncio
import sys
import os
from pathlib import Path

# Load .env.prod
from dotenv import load_dotenv
load_dotenv(".env.prod")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig

async def test_connection():
    """Test Redis Cloud connection"""
    print("[*] Testing Redis Cloud connectivity...")
    print(f"Redis URL: {os.getenv('REDIS_URL', 'NOT SET')}")
    print(f"CA Cert: {os.getenv('REDIS_TLS_CERT_PATH', 'NOT SET')}")

    try:
        # Create config
        config = RedisCloudConfig(
            url=os.getenv("REDIS_URL", ""),
            ca_cert_path="config/certs/redis_ca.pem"
        )

        print(f"\n[OK] Config created: {config.url[:50]}...")

        # Test connection
        async with RedisCloudClient(config) as client:
            print("[OK] Client connected")

            # Test ping
            result = await client.ping()
            print(f"[OK] PING: {result}")

            # Test set/get
            await client.set("test:crypto-ai-bot", "connected")
            value = await client.get("test:crypto-ai-bot")
            print(f"[OK] SET/GET: {value}")

            print("\n[PASS] All tests passed! Redis Cloud is working!")
            return True

    except Exception as e:
        print(f"\n[FAIL] Connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_connection())
    sys.exit(0 if result else 1)
