"""
Verify Canary Deployment - Check Redis and API
"""
import os
import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.signals_api_config import get_signals_api_url
from dotenv import load_dotenv
load_dotenv('.env.paper.local')

async def verify_redis():
    """Verify Redis stream has SOL/ADA signals"""
    print("=" * 70)
    print("REDIS VERIFICATION")
    print("=" * 70)

    try:
        import redis.asyncio as redis

        redis_url = os.getenv('REDIS_URL')
        client = redis.from_url(redis_url, decode_responses=True)

        # Check stream length
        stream_len = await client.xlen('signals:paper')
        print(f"Stream length: {stream_len}")

        # Get recent signals
        print("\nRecent signals (last 20):")
        messages = await client.xrevrange('signals:paper', count=20)

        pairs_found = set()
        for msg_id, fields in messages:
            pair = fields.get('pair', 'UNKNOWN')
            action = fields.get('action', 'UNKNOWN')
            pairs_found.add(pair)
            print(f"  {msg_id}: {pair} - {action}")

        print(f"\nUnique pairs in recent signals: {sorted(pairs_found)}")

        # Check for SOL and ADA
        has_sol = any('SOL' in p for p in pairs_found)
        has_ada = any('ADA' in p for p in pairs_found)

        print(f"\n✓ SOL-USD found: {has_sol}")
        print(f"✓ ADA-USD found: {has_ada}")

        await client.aclose()

        return has_sol and has_ada

    except Exception as e:
        print(f"ERROR: {e}")
        return False

async def verify_api():
    """Verify production API has SOL/ADA"""
    print("\n" + "=" * 70)
    print("API VERIFICATION")
    print("=" * 70)

    try:
        import aiohttp

        url = get_signals_api_url("/signals")

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"ERROR: API returned status {resp.status}")
                    return False

                data = await resp.json()

                print(f"API Status: {resp.status}")
                print(f"Total signals: {len(data)}")

                pairs = set()
                for signal in data:
                    pair = signal.get('pair') or signal.get('symbol', 'UNKNOWN')
                    pairs.add(pair)

                print(f"\nUnique pairs in API: {sorted(pairs)}")

                has_sol = any('SOL' in p for p in pairs)
                has_ada = any('ADA' in p for p in pairs)

                print(f"\n✓ SOL-USD in API: {has_sol}")
                print(f"✓ ADA-USD in API: {has_ada}")

                # Show sample signals for SOL/ADA
                print("\nSample SOL/ADA signals:")
                for signal in data[:10]:
                    pair = signal.get('pair') or signal.get('symbol', 'UNKNOWN')
                    if 'SOL' in pair or 'ADA' in pair:
                        action = signal.get('action', 'UNKNOWN')
                        confidence = signal.get('confidence', 0)
                        print(f"  {pair}: {action} (confidence: {confidence})")

                return has_sol and has_ada

    except Exception as e:
        print(f"ERROR: {e}")
        return False

async def main():
    """Main verification"""
    print(f"Canary Verification - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    redis_ok = await verify_redis()
    api_ok = await verify_api()

    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    print(f"Redis check: {'✅ PASS' if redis_ok else '❌ FAIL'}")
    print(f"API check: {'✅ PASS' if api_ok else '❌ FAIL'}")
    print("=" * 70)

    return redis_ok and api_ok

if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
