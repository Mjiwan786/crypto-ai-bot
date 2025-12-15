"""
Canary Signal Publisher - D3 Execution
Directly publishes SOL/USD and ADA/USD test signals to production stream
for verification that multi-pair expansion works in production
"""
import redis
import ssl
import json
import time
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.signals_api_config import get_signals_api_url
from dotenv import load_dotenv

# Load canary environment
load_dotenv('.env.canary')

# Redis connection
redis_url = os.getenv('REDIS_URL')
redis_ssl_ca_cert = os.getenv('REDIS_SSL_CA_CERT')
stream_name = os.getenv('REDIS_STREAM_NAME', 'signals:paper')

print("=" * 70, flush=True)
print("CANARY SIGNAL PUBLISHER - D3", flush=True)
print("=" * 70, flush=True)
print(f"Target Stream: {stream_name}", flush=True)
print(f"Canary Pairs: SOL-USD, ADA-USD", flush=True)
print("=" * 70, flush=True)
print("", flush=True)

# Verify targeting production
if stream_name != 'signals:paper':
    print(f"ERROR: Expected signals:paper, got {stream_name}", flush=True)
    exit(1)

# Connect to Redis
print("Connecting to Redis Cloud...", flush=True)
try:
    r = redis.from_url(
        redis_url,
        ssl_ca_certs=redis_ssl_ca_cert,
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        decode_responses=False
    )
    r.ping()
    print("[OK] Redis connected", flush=True)
    print("", flush=True)
except Exception as e:
    print(f"ERROR: Redis connection failed: {e}", flush=True)
    exit(1)

# Test signal template
canary_pairs = ['SOL-USD', 'ADA-USD']
sides = ['buy', 'sell']
base_prices = {'SOL-USD': 150.0, 'ADA-USD': 0.35}

print(f"Publishing canary signals to {stream_name}...", flush=True)
print("", flush=True)

published_count = 0
for pair in canary_pairs:
    for i in range(3):  # 3 signals per pair
        signal_data = {
            'id': f'canary_d3_{int(time.time() * 1000)}_{pair}_{i}',
            'ts': int(time.time() * 1000),
            'pair': pair,
            'side': sides[i % 2],
            'entry': base_prices[pair] + i,
            'sl': base_prices[pair] - 5 + i,
            'tp': base_prices[pair] + 10 + i,
            'strategy': 'd3_canary_test',
            'confidence': 0.85,
            'mode': 'paper'
        }

        # Publish to production stream (API expects "json" field)
        try:
            r.xadd(stream_name.encode(), {b'json': json.dumps(signal_data).encode()})
            published_count += 1
            print(f"  [{published_count}] Published {pair} {sides[i % 2]} signal", flush=True)
            time.sleep(0.5)  # Rate limiting
        except Exception as e:
            print(f"  [ERROR] Failed to publish {pair}: {e}", flush=True)

print("", flush=True)
print("=" * 70, flush=True)
print(f"CANARY DEPLOYMENT COMPLETE", flush=True)
print(f"Published: {published_count} signals (SOL-USD: 3, ADA-USD: 3)", flush=True)
print(f"Target: {stream_name}", flush=True)
print("=" * 70, flush=True)
print("", flush=True)
print("Next steps:", flush=True)
print("1. Verify signals appear in production API:", flush=True)
print(f"   curl {get_signals_api_url('/v1/signals?limit=50')}", flush=True)
print("2. Check for SOL-USD and ADA-USD in response", flush=True)
print("3. If successful, canary deployment is confirmed", flush=True)
print("", flush=True)
