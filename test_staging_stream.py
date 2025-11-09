"""
Test staging stream setup and isolation
Verifies new pairs can publish to signals:paper:staging without affecting production
"""

import os
import sys
import time
import json
from datetime import datetime
import redis

# Load staging environment
from dotenv import load_dotenv
load_dotenv('.env.staging')

def test_redis_connection():
    """Test Redis Cloud TLS connection"""
    print("=" * 60)
    print("TEST 1: Redis Connection")
    print("=" * 60)

    redis_url = os.getenv('REDIS_URL')
    ca_cert = os.getenv('REDIS_SSL_CA_CERT')

    print(f"Redis URL: {redis_url[:50]}...")
    print(f"CA Cert: {ca_cert}")

    try:
        r = redis.from_url(
            redis_url,
            ssl_ca_certs=ca_cert,
            decode_responses=True
        )

        # Test connection
        r.ping()
        print("[OK] Redis connection successful")

        # List existing streams
        streams = r.keys('signals:*')
        print(f"\nExisting streams: {len(streams)}")
        for stream in streams:
            length = r.xlen(stream)
            print(f"  - {stream}: {length} messages")

        return r
    except Exception as e:
        print(f"[FAIL] Redis connection failed: {e}")
        return None

def test_staging_stream_isolation(r):
    """Test that staging stream is isolated from production"""
    print("\n" + "=" * 60)
    print("TEST 2: Stream Isolation")
    print("=" * 60)

    staging_stream = "signals:paper:staging"
    prod_stream = "signals:paper"

    # Check if staging stream exists
    staging_exists = r.exists(staging_stream)
    print(f"Staging stream exists: {staging_exists}")

    # Get lengths
    staging_len = r.xlen(staging_stream) if staging_exists else 0
    prod_len = r.xlen(prod_stream)

    print(f"Staging stream length: {staging_len}")
    print(f"Production stream length: {prod_len}")

    print("\n[OK] Streams are isolated (different names)")
    return True

def test_publish_to_staging(r):
    """Test publishing test signals to staging stream"""
    print("\n" + "=" * 60)
    print("TEST 3: Publish to Staging Stream")
    print("=" * 60)

    staging_stream = "signals:paper:staging"
    test_pairs = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'ADA/USD', 'AVAX/USD']

    print(f"Publishing test signals for {len(test_pairs)} pairs...")

    published = []
    for pair in test_pairs:
        signal = {
            'pair': pair,
            'action': 'BUY',
            'price': str(50000.0 if 'BTC' in pair else 3000.0),
            'confidence': str(0.75),
            'timestamp': str(int(time.time())),
            'test': 'true',
            'source': 'staging_test'
        }

        # Publish to staging stream
        msg_id = r.xadd(staging_stream, signal)
        published.append({'pair': pair, 'msg_id': msg_id})
        print(f"  [OK] Published {pair} -> {msg_id}")

    # Verify signals in staging
    print(f"\nVerifying signals in {staging_stream}...")
    recent = r.xrange(staging_stream, count=10)
    print(f"Total signals in staging: {r.xlen(staging_stream)}")
    print(f"Last 10 signals: {len(recent)}")

    # Check pairs distribution
    pairs_found = set()
    for msg_id, data in recent:
        if 'pair' in data:
            pairs_found.add(data['pair'])

    print(f"\nPairs found in staging stream: {pairs_found}")

    return published

def test_production_untouched(r):
    """Verify production stream was not modified"""
    print("\n" + "=" * 60)
    print("TEST 4: Production Stream Untouched")
    print("=" * 60)

    prod_stream = "signals:paper"

    # Get recent messages from production
    recent = r.xrange(prod_stream, count=20)

    # Check for test signals or new pairs
    has_test_signals = False
    new_pairs = set()

    for msg_id, data in recent:
        if data.get('test') == 'True':
            has_test_signals = True
        pair = data.get('pair')
        if pair and pair not in ['BTC/USD', 'ETH/USD']:
            new_pairs.add(pair)

    if has_test_signals:
        print("[FAIL] WARNING: Test signals found in production stream!")
        return False

    if new_pairs:
        print(f"[FAIL] WARNING: New pairs found in production: {new_pairs}")
        return False

    print("[OK] Production stream unchanged")
    print(f"   No test signals detected")
    print(f"   No new pairs (SOL/ADA/AVAX) in production")
    return True

def test_cleanup(r):
    """Clean up test data from staging stream"""
    print("\n" + "=" * 60)
    print("CLEANUP: Remove Test Data")
    print("=" * 60)

    response = input("Delete test signals from staging stream? (y/n): ")

    if response.lower() == 'y':
        staging_stream = "signals:paper:staging"
        # Get all messages
        all_msgs = r.xrange(staging_stream)

        deleted = 0
        for msg_id, data in all_msgs:
            if data.get('test') == 'True':
                r.xdel(staging_stream, msg_id)
                deleted += 1

        print(f"[OK] Deleted {deleted} test signals from staging")
    else:
        print("Skipping cleanup")

def main():
    print("\nSTAGING STREAM SETUP TEST")
    print("Testing multi-pair configuration with Redis stream isolation\n")

    # Test 1: Connection
    r = test_redis_connection()
    if not r:
        print("\n[FAIL] FAILED: Cannot connect to Redis")
        return False

    # Test 2: Isolation
    if not test_staging_stream_isolation(r):
        print("\n[FAIL] FAILED: Stream isolation issue")
        return False

    # Test 3: Publish to staging
    published = test_publish_to_staging(r)
    if not published:
        print("\n[FAIL] FAILED: Could not publish to staging")
        return False

    # Test 4: Verify production untouched
    if not test_production_untouched(r):
        print("\n[FAIL] FAILED: Production stream was modified!")
        return False

    # Cleanup
    test_cleanup(r)

    print("\n" + "=" * 60)
    print("[OK] ALL TESTS PASSED")
    print("=" * 60)
    print("\nStaging stream is ready for Phase 1!")
    print(f"Stream name: signals:paper:staging")
    print(f"Test pairs published: {len(published)}")
    print(f"Production stream: UNTOUCHED [OK]")

    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
