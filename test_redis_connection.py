#!/usr/bin/env python3
"""
Test Redis Cloud connectivity for crypto-ai-bot
"""
import os
import sys
import redis
import ssl
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_redis_connection():
    """Test connection to Redis Cloud with TLS"""
    try:
        # Get Redis configuration from environment
        redis_url = os.getenv('REDIS_URL')
        ca_cert_path = os.getenv('REDIS_CA_CERT_PATH', 'config/certs/redis_ca.pem')

        print("=" * 60)
        print("REDIS CONNECTION TEST")
        print("=" * 60)
        print(f"Redis URL: {redis_url[:30]}...{redis_url[-30:]}")  # Hide middle part with password
        print(f"CA Cert Path: {ca_cert_path}")
        print("")

        # Create Redis connection with TLS
        r = redis.Redis.from_url(
            redis_url,
            ssl_cert_reqs=ssl.CERT_REQUIRED,
            ssl_ca_certs=ca_cert_path,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=10
        )

        # Test PING
        print("Testing PING...")
        response = r.ping()
        print(f"[OK] PING response: {response}")
        print("")

        # Test INFO
        print("Testing INFO server...")
        info = r.info('server')
        print(f"[OK] Redis Version: {info.get('redis_version', 'N/A')}")
        print(f"[OK] Redis Mode: {info.get('redis_mode', 'N/A')}")
        print(f"[OK] OS: {info.get('os', 'N/A')}")
        print("")

        # Test SET/GET
        print("Testing SET/GET...")
        test_key = "test:connection:crypto-ai-bot"
        test_value = "Connection successful at " + str(__import__('datetime').datetime.now())
        r.set(test_key, test_value, ex=60)  # Expire in 60 seconds
        retrieved = r.get(test_key)
        print(f"[OK] SET/GET test passed: {retrieved}")
        print("")

        # Test stream existence
        print("Checking Redis streams...")
        streams = [
            'md:trades',
            'md:spread',
            'md:orderbook',
            'md:candles',
            'signals:paper',
            'signals:live',
            'events:bus'
        ]

        for stream in streams:
            exists = r.exists(stream)
            length = r.xlen(stream) if exists else 0
            status = "[OK]" if exists else "[MISSING]"
            print(f"{status} {stream}: {'exists' if exists else 'not found'} (length: {length})")

        print("")
        print("=" * 60)
        print("[SUCCESS] REDIS CONNECTION SUCCESSFUL!")
        print("=" * 60)
        return True

    except redis.ConnectionError as e:
        print(f"\n[ERROR] Redis Connection Error: {e}")
        return False
    except ssl.SSLError as e:
        print(f"\n[ERROR] SSL Error: {e}")
        return False
    except Exception as e:
        print(f"\n[ERROR] Unexpected Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_redis_connection()
    sys.exit(0 if success else 1)
