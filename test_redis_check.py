#!/usr/bin/env python
"""Test Redis connection and check existing data."""

import os
import sys
import asyncio

# Add path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def check_redis():
    """Check Redis connection and existing data."""
    import redis.asyncio as redis

    redis_url = 'rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818'
    ca_cert = 'config/certs/redis_ca.pem'

    print('=== Redis Connection Check ===')
    print(f'Using CA cert: {ca_cert}')
    print(f'CA cert exists: {os.path.exists(ca_cert)}')

    try:
        conn_params = {
            'socket_connect_timeout': 10,
            'decode_responses': True,
        }
        if os.path.exists(ca_cert):
            conn_params['ssl_ca_certs'] = ca_cert
            conn_params['ssl_cert_reqs'] = 'required'

        r = redis.from_url(redis_url, **conn_params)

        # Test connection
        pong = await r.ping()
        print(f'PING: {pong}')

        # List all keys
        print('\n=== All Redis Keys (pattern: *) ===')
        keys = await r.keys('*')
        for k in sorted(keys)[:50]:
            key_type = await r.type(k)
            print(f'  {k} ({key_type})')

        # Check signal streams
        print('\n=== Checking Signal Streams ===')
        signal_keys = [k for k in keys if k.startswith('signals:')]
        if not signal_keys:
            print('  No signal streams found!')
        for sk in signal_keys[:10]:
            length = await r.xlen(sk)
            print(f'  {sk}: {length} entries')
            if length > 0:
                # Get latest entry
                entries = await r.xrevrange(sk, count=1)
                if entries:
                    entry_id, data = entries[0]
                    print(f'    Latest entry ({entry_id}):')
                    for field in ['signal_id', 'id', 'pair', 'symbol', 'side', 'signal_type', 'entry_price', 'price', 'timestamp', 'confidence', 'strategy', 'regime']:
                        if field in data:
                            print(f'      {field}: {data[field]}')

        # Check PnL streams
        print('\n=== Checking PnL Streams ===')
        pnl_keys = [k for k in keys if k.startswith('pnl:')]
        if not pnl_keys:
            print('  No PnL streams found!')
        for pk in pnl_keys[:5]:
            length = await r.xlen(pk)
            print(f'  {pk}: {length} entries')
            if length > 0:
                entries = await r.xrevrange(pk, count=1)
                if entries:
                    entry_id, data = entries[0]
                    print(f'    Latest entry ({entry_id}): {list(data.keys())}')

        # Check telemetry hashes
        print('\n=== Checking Telemetry Keys ===')
        for tk in ['engine:last_signal_meta', 'engine:last_pnl_meta']:
            if tk in keys:
                data = await r.hgetall(tk)
                print(f'  {tk}: {data}')
            else:
                print(f'  {tk}: NOT FOUND')

        await r.aclose()
        print('\nConnection closed successfully')
        return True

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = asyncio.run(check_redis())
    sys.exit(0 if success else 1)
