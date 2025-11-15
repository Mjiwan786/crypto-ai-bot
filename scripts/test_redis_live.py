# -*- coding: utf-8 -*-
"""
Simple Redis Cloud TLS Connectivity Test

Tests connection to Redis Cloud with TLS and verifies signal stream configuration.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import redis
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing dependencies: {e}")
    print("Install with: pip install redis python-dotenv")
    sys.exit(1)

def main():
    print("\n" + "="*70)
    print(" Redis Cloud TLS Connectivity Test")
    print("="*70 + "\n")

    # Load .env
    env_file = project_root / ".env"
    if not env_file.exists():
        print("[ERROR] .env file not found")
        return False

    load_dotenv(env_file)
    print(f"[OK] Loaded .env file")

    # Get Redis URL
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("[ERROR] REDIS_URL not set")
        return False

    print(f"[OK] Redis URL: {redis_url[:30]}...")

    # Get CA cert
    ca_cert = os.getenv("REDIS_CA_CERT_PATH") or os.getenv("REDIS_CA_CERT")
    if ca_cert:
        ca_cert_path = project_root / ca_cert
        if ca_cert_path.exists():
            print(f"[OK] CA certificate: {ca_cert}")
        else:
            print(f"[WARNING] CA certificate not found: {ca_cert}")
            print(f"          Will use certifi")

    # Try to connect
    print("\n[TEST] Connecting to Redis Cloud...")

    try:
        conn_params = {
            "decode_responses": True,
            "socket_timeout": 5,
            "socket_connect_timeout": 5,
        }

        # For rediss:// URLs, SSL is automatically enabled
        # Just add CA cert path if available
        if redis_url.startswith("rediss://") and ca_cert and ca_cert_path.exists():
            conn_params["ssl_ca_certs"] = str(ca_cert_path)

        client = redis.from_url(redis_url, **conn_params)

        # Test PING
        client.ping()
        print("[OK] Connection successful (PING OK)")

        # Get info
        info = client.info("server")
        print(f"[OK] Redis version: {info.get('redis_version', 'unknown')}")

        # Check current mode
        mode = os.getenv("MODE") or os.getenv("TRADING_MODE") or os.getenv("BOT_MODE", "PAPER")
        print(f"\n[INFO] Trading mode: {mode}")

        # Check ACTIVE_SIGNALS
        active = client.get("ACTIVE_SIGNALS")
        if active:
            active_str = active.decode() if isinstance(active, bytes) else active
            print(f"[OK] ACTIVE_SIGNALS -> {active_str}")
        else:
            print("[INFO] ACTIVE_SIGNALS not set in Redis")

        # Check streams
        print("\n[TEST] Checking signal streams...")

        for stream in ["signals:paper", "signals:live"]:
            try:
                length = client.xlen(stream)
                print(f"[OK] {stream} exists (length: {length})")
            except:
                print(f"[INFO] {stream} does not exist (will be created on first write)")

        # Write test signal
        print("\n[TEST] Writing test signal...")
        test_stream = f"signals:{mode.lower()}"
        test_signal = {
            "id": "test_connection",
            "ts": "1730000000",
            "pair": "BTC-USD",
            "side": "long",
            "entry": "50000",
            "sl": "49000",
            "tp": "52000",
            "strategy": "test",
            "confidence": "0.99",
            "mode": mode.lower()
        }

        entry_id = client.xadd(test_stream, test_signal, maxlen=10000, approximate=True)
        print(f"[OK] Test signal written to {test_stream}")
        print(f"     Entry ID: {entry_id}")

        # Verify read
        signals = client.xrevrange(test_stream, count=1)
        if signals:
            print(f"[OK] Test signal verified in {test_stream}")

        # Close
        client.close()

        print("\n" + "="*70)
        print("[SUCCESS] All Redis tests passed")
        print("="*70 + "\n")

        return True

    except redis.ConnectionError as e:
        print(f"\n[ERROR] Connection failed: {e}")
        return False
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
