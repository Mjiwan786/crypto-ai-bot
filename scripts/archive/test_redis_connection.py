#!/usr/bin/env python3
"""
Test Redis Connection

Simple script to test Redis connection with TLS support.
"""

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv


def test_redis_connection():
    """Test Redis connection with TLS"""
    print("Testing Redis connection...")
    
    # Load environment
    env_file = PROJECT_ROOT / ".env.staging"
    if env_file.exists():
        load_dotenv(env_file)
    
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    print(f"Redis URL: {redis_url}")
    
    try:
        import redis
        
        # Create Redis client with SSL support
        ssl_enabled = os.getenv("REDIS_SSL_ENABLED", "false").lower() == "true"
        
        if ssl_enabled:
            print("Using SSL connection...")
            # For Redis Cloud with TLS, use rediss:// protocol
            client = redis.from_url(redis_url, decode_responses=True)
        else:
            print("Using non-SSL connection...")
            client = redis.from_url(redis_url, decode_responses=True)
        
        # Test connection
        result = client.ping()
        print(f"PING result: {result}")
        
        # Test basic operations
        client.set("test_key", "test_value", ex=10)
        value = client.get("test_key")
        print(f"SET/GET test: {value}")
        
        # Test stream operations
        stream_name = "test_stream"
        client.xadd(stream_name, {"test": "data"})
        info = client.xinfo_stream(stream_name)
        print(f"Stream info: {info}")
        
        # Cleanup
        client.delete("test_key")
        client.delete(stream_name)
        
        print("SUCCESS: Redis connection working!")
        return True
        
    except Exception as e:
        print(f"ERROR: Redis connection failed: {e}")
        print("Make sure Redis is running and accessible")
        return False

if __name__ == "__main__":
    success = test_redis_connection()
    sys.exit(0 if success else 1)
