#!/usr/bin/env python3
"""
Check Engine Telemetry Keys

Verifies that engine:last_signal_meta and engine:last_pnl_meta are properly set
and can be read by signals-api.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import redis

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Load environment
project_root = Path(__file__).parent
load_dotenv(project_root / ".env.paper", override=False)
load_dotenv(project_root / ".env.prod", override=False)

# Connect to Redis
redis_url = os.getenv("REDIS_URL")
redis_ca_cert = os.getenv(
    "REDIS_CA_CERT",
    os.getenv("REDIS_CA_CERT_PATH", str(project_root / "config" / "certs" / "redis_ca.pem"))
)

if not redis_url:
    print("ERROR: REDIS_URL not set")
    sys.exit(1)

print("=" * 80)
print("ENGINE TELEMETRY KEYS VERIFICATION")
print("=" * 80)
print()

try:
    client = redis.from_url(
        redis_url,
        ssl_cert_reqs='required',
        ssl_ca_certs=redis_ca_cert if os.path.exists(redis_ca_cert) else None,
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=10,
    )
    
    client.ping()
    print("[OK] Connected to Redis")
    print()
    
    # Check engine:last_signal_meta
    print("=" * 80)
    print("1. engine:last_signal_meta")
    print("=" * 80)
    
    key = "engine:last_signal_meta"
    exists = client.exists(key)
    key_type = client.type(key)
    ttl = client.ttl(key)
    
    print(f"Exists: {bool(exists)}")
    print(f"Type: {key_type}")
    print(f"TTL: {ttl} seconds ({ttl // 3600} hours remaining)" if ttl > 0 else f"TTL: {ttl}")
    print()
    
    if exists and key_type == "hash":
        data = client.hgetall(key)
        print("Fields:")
        for k, v in sorted(data.items()):
            print(f"  {k:20} = {v}")
    elif exists:
        print(f"[WARN] Key exists but wrong type: {key_type} (expected: hash)")
        print(f"Value: {client.get(key)}")
    else:
        print("[WARN] Key does not exist - engine may not be running or no signals published yet")
    
    print()
    
    # Check engine:last_pnl_meta
    print("=" * 80)
    print("2. engine:last_pnl_meta")
    print("=" * 80)
    
    key = "engine:last_pnl_meta"
    exists = client.exists(key)
    key_type = client.type(key)
    ttl = client.ttl(key)
    
    print(f"Exists: {bool(exists)}")
    print(f"Type: {key_type}")
    print(f"TTL: {ttl} seconds ({ttl // 3600} hours remaining)" if ttl > 0 else f"TTL: {ttl}")
    print()
    
    if exists and key_type == "hash":
        data = client.hgetall(key)
        print("Fields:")
        for k, v in sorted(data.items()):
            print(f"  {k:20} = {v}")
    elif exists:
        print(f"[WARN] Key exists but wrong type: {key_type} (expected: hash)")
        print(f"Value: {client.get(key)}")
    else:
        print("[WARN] Key does not exist - engine may not be running or no PnL updates published yet")
    
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    signal_exists = client.exists("engine:last_signal_meta") and client.type("engine:last_signal_meta") == "hash"
    pnl_exists = client.exists("engine:last_pnl_meta") and client.type("engine:last_pnl_meta") == "hash"
    
    if signal_exists and pnl_exists:
        print("[OK] Both telemetry keys exist and are properly formatted")
        print("[OK] signals-api can read these keys using HGETALL")
    elif signal_exists:
        print("[WARN] Only signal telemetry exists - PnL telemetry missing")
    elif pnl_exists:
        print("[WARN] Only PnL telemetry exists - signal telemetry missing")
    else:
        print("[ERROR] No telemetry keys found - engine may not be running")
        print("        Run test_prd_signal_publisher.py to generate test signals")
    
    print()
    print("Redis CLI Commands (for manual inspection):")
    print("  HGETALL engine:last_signal_meta")
    print("  HGETALL engine:last_pnl_meta")
    print("  TTL engine:last_signal_meta")
    print("  TTL engine:last_pnl_meta")
    
except Exception as e:
    print(f"[ERROR] Failed to check telemetry keys: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

