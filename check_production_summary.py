#!/usr/bin/env python3
"""
Check Production Summary - Verify signals and PnL in Redis

This script checks Redis streams and provides a summary of what's available
for signals-api and the front-end to consume.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
import redis

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Load environment
project_root = Path(__file__).parent
load_dotenv(project_root / ".env.paper", override=False)
load_dotenv(project_root / ".env.prod", override=False)

# Redis connection
redis_url = os.getenv("REDIS_URL")
redis_ca_cert = os.getenv(
    "REDIS_CA_CERT",
    os.getenv("REDIS_CA_CERT_PATH", str(project_root / "config" / "certs" / "redis_ca.pem"))
)

MODE = os.getenv("ENGINE_MODE", "paper")
TRADING_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]

print("=" * 80)
print("PRODUCTION DATA SUMMARY")
print("=" * 80)
print(f"Mode: {MODE}")
print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
print()

if not redis_url:
    print("ERROR: REDIS_URL not set")
    sys.exit(1)

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
    
    # Check signal streams
    print("=" * 80)
    print("SIGNAL STREAMS")
    print("=" * 80)
    
    total_signals = 0
    active_streams = []
    
    for pair in TRADING_PAIRS:
        safe_pair = pair.replace("/", "-")
        stream_key = f"signals:{MODE}:{safe_pair}"
        
        try:
            length = client.xlen(stream_key)
            total_signals += length
            
            if length > 0:
                active_streams.append((stream_key, length))
                
                # Get latest signal
                entries = client.xrevrange(stream_key, "+", "-", count=1)
                if entries:
                    entry_id, fields = entries[0]
                    signal_id = fields.get("signal_id", "N/A")
                    timestamp = fields.get("timestamp", "N/A")
                    side = fields.get("side", "N/A")
                    strategy = fields.get("strategy", "N/A")
                    
                    print(f"  {stream_key:35} {length:>10} messages")
                    print(f"    Latest: {signal_id[:36]}... | {side} | {strategy} | {timestamp[:19]}")
            else:
                print(f"  {stream_key:35} {length:>10} messages (empty)")
        except Exception as e:
            print(f"  {stream_key:35} {'ERROR':>10} - {e}")
    
    print(f"\n  {'Total signals:':35} {total_signals:>10}")
    
    # Check PnL streams
    print()
    print("=" * 80)
    print("PNL STREAMS")
    print("=" * 80)
    
    pnl_streams = [
        f"pnl:{MODE}:equity_curve",
        f"pnl:{MODE}:signals",
    ]
    
    for stream_key in pnl_streams:
        try:
            length = client.xlen(stream_key)
            if length > 0:
                entries = client.xrevrange(stream_key, "+", "-", count=1)
                if entries:
                    entry_id, fields = entries[0]
                    equity = fields.get("equity", "N/A")
                    timestamp = fields.get("timestamp", "N/A")
                    
                    print(f"  {stream_key:35} {length:>10} messages")
                    print(f"    Latest: Equity=${equity} | {timestamp[:19]}")
            else:
                print(f"  {stream_key:35} {length:>10} messages (empty)")
        except Exception as e:
            print(f"  {stream_key:35} {'ERROR':>10} - {e}")
    
    # Check telemetry keys
    print()
    print("=" * 80)
    print("TELEMETRY KEYS")
    print("=" * 80)
    
    telemetry_keys = [
        "engine:last_signal_meta",
        "engine:last_pnl_meta",
    ]
    
    for key in telemetry_keys:
        try:
            exists = client.exists(key)
            if exists:
                key_type = client.type(key)
                ttl = client.ttl(key)
                
                if key_type == "hash":
                    data = client.hgetall(key)
                    print(f"  {key:35} [OK] Hash with {len(data)} fields, TTL: {ttl}s")
                    if "pair" in data:
                        print(f"    Last signal: {data.get('pair', 'N/A')} {data.get('side', 'N/A')} @ {data.get('timestamp', 'N/A')[:19]}")
                    elif "equity" in data:
                        print(f"    Last PnL: Equity=${data.get('equity', 'N/A')} @ {data.get('timestamp', 'N/A')[:19]}")
                else:
                    print(f"  {key:35} [WARN] Wrong type: {key_type}")
            else:
                print(f"  {key:35} [MISSING]")
        except Exception as e:
            print(f"  {key:35} [ERROR] - {e}")
    
    # Summary
    print()
    print("=" * 80)
    print("SUMMARY FOR FRONT-END CONSUMPTION")
    print("=" * 80)
    
    if total_signals > 0:
        print(f"✅ {total_signals} signals available in Redis streams")
        print(f"   Active streams: {len(active_streams)}")
        print(f"   Ready for signals-api consumption")
    else:
        print("⚠️  No signals found in Redis streams")
        print("   Engine may not be running or not publishing signals")
    
    pnl_equity_length = client.xlen(f"pnl:{MODE}:equity_curve")
    if pnl_equity_length > 0:
        print(f"✅ {pnl_equity_length} PnL updates available")
        print(f"   Ready for signals-api consumption")
    else:
        print("⚠️  No PnL updates found")
    
    # Sample signal for verification
    if active_streams:
        stream_key, _ = active_streams[0]
        entries = client.xrevrange(stream_key, "+", "-", count=1)
        if entries:
            entry_id, fields = entries[0]
            print()
            print("=" * 80)
            print("SAMPLE SIGNAL (Latest from first active stream)")
            print("=" * 80)
            print(f"Stream: {stream_key}")
            print(f"Entry ID: {entry_id}")
            print()
            for k, v in sorted(fields.items()):
                if len(str(v)) > 100:
                    print(f"  {k:25} = {str(v)[:100]}...")
                else:
                    print(f"  {k:25} = {v}")
    
    print()
    print("=" * 80)
    print("REDIS CLI COMMANDS (for manual inspection)")
    print("=" * 80)
    print("# Check signal stream:")
    if active_streams:
        stream_key, _ = active_streams[0]
        print(f"redis-cli -u rediss://default:...@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 \\")
        print(f"  --tls --cacert config/certs/redis_ca.pem \\")
        print(f"  XREVRANGE {stream_key} + - COUNT 5")
    print()
    print("# Check PnL stream:")
    print(f"redis-cli -u rediss://default:...@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 \\")
    print(f"  --tls --cacert config/certs/redis_ca.pem \\")
    print(f"  XREVRANGE pnl:{MODE}:equity_curve + - COUNT 5")
    print()
    print("# Check telemetry:")
    print(f"redis-cli -u rediss://default:...@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818 \\")
    print(f"  --tls --cacert config/certs/redis_ca.pem \\")
    print(f"  HGETALL engine:last_signal_meta")

except Exception as e:
    print(f"[ERROR] Failed to check production data: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

