#!/usr/bin/env python3
"""
Preflight check script for crypto-ai-bot production startup.
Tests: Redis TLS connection, Kraken WS connection, and basic metrics.
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Load production environment
load_dotenv('.env.prod')

# Check for redis.asyncio
try:
    import redis.asyncio as redis
    print("[OK] redis.asyncio imported successfully")
except ImportError as e:
    print(f"[FAIL] Failed to import redis.asyncio: {e}")
    sys.exit(1)

# Check for websockets
try:
    import websockets
    print("[OK] websockets imported successfully")
except ImportError as e:
    print(f"[FAIL] Failed to import websockets: {e}")
    sys.exit(1)

# Check for orjson
try:
    import orjson
    print("[OK] orjson imported successfully")
except ImportError as e:
    print(f"[FAIL] Failed to import orjson: {e}")
    sys.exit(1)


async def test_redis_tls():
    """Test Redis Cloud TLS connection."""
    print("\n" + "="*60)
    print("PREFLIGHT CHECK 1: Redis Cloud TLS Connection")
    print("="*60)

    redis_url = os.getenv('REDIS_URL')
    redis_cert_path = os.getenv('REDIS_TLS_CERT_PATH')

    if not redis_url:
        print("[FAIL] REDIS_URL not set in .env.prod")
        return False

    if not redis_cert_path:
        print("[FAIL] REDIS_TLS_CERT_PATH not set in .env.prod")
        return False

    if not Path(redis_cert_path).exists():
        print(f"[FAIL] Redis CA certificate not found at: {redis_cert_path}")
        return False

    print(f"[OK] Redis URL configured: {redis_url[:30]}...")
    print(f"[OK] TLS cert found: {redis_cert_path}")

    try:
        # Create Redis client with TLS
        client = redis.from_url(
            redis_url,
            ssl_cert_reqs='required',
            ssl_ca_certs=redis_cert_path,
            socket_connect_timeout=5,
            socket_keepalive=True,
            decode_responses=False
        )

        # Test ping
        print("\nTesting Redis PING...")
        start_time = time.time()
        result = await client.ping()
        latency_ms = (time.time() - start_time) * 1000

        if result:
            print(f"[OK] Redis PING successful (latency: {latency_ms:.2f}ms)")
        else:
            print("[FAIL] Redis PING failed")
            await client.aclose()
            return False

        # Test stream operations
        print("\nTesting Redis stream operations...")
        test_stream = "preflight:test"

        # XADD
        message_id = await client.xadd(test_stream, {"test": "preflight", "timestamp": str(time.time())})
        print(f"[OK] XADD successful: {message_id}")

        # XLEN
        stream_len = await client.xlen(test_stream)
        print(f"[OK] XLEN successful: {stream_len} messages")

        # XREAD
        messages = await client.xread({test_stream: 0}, count=1)
        if messages:
            print(f"[OK] XREAD successful: retrieved {len(messages)} stream(s)")

        # Check existing streams
        print("\nChecking existing Redis streams...")
        streams_to_check = [
            'signals:paper', 'signals:live', 'system:metrics',
            'kraken:health', 'ops:heartbeat', 'metrics:pnl:equity'
        ]

        for stream_name in streams_to_check:
            try:
                length = await client.xlen(stream_name)
                print(f"  {stream_name}: {length} messages")
            except Exception as e:
                print(f"  {stream_name}: not found or error ({e})")

        # Cleanup
        await client.delete(test_stream)
        await client.aclose()

        print("\n[OK] Redis TLS preflight check PASSED")
        return True

    except Exception as e:
        print(f"\n[FAIL] Redis connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_kraken_ws():
    """Test Kraken WebSocket connection."""
    print("\n" + "="*60)
    print("PREFLIGHT CHECK 2: Kraken WebSocket Connection")
    print("="*60)

    kraken_url = os.getenv('KRAKEN_WS_URL', 'wss://ws.kraken.com')
    print(f"Connecting to: {kraken_url}")

    try:
        async with websockets.connect(kraken_url) as ws:
            print("[OK] WebSocket connection established")

            # Subscribe to BTC/USD ticker
            subscribe_msg = {
                "event": "subscribe",
                "pair": ["XBT/USD"],
                "subscription": {"name": "ticker"}
            }

            print("\nSubscribing to BTC/USD ticker...")
            await ws.send(orjson.dumps(subscribe_msg).decode())

            # Wait for subscription confirmation and first message
            message_count = 0
            start_time = time.time()
            timeout = 10  # 10 seconds timeout

            while message_count < 3 and (time.time() - start_time) < timeout:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    data = orjson.loads(msg)
                    message_count += 1

                    if isinstance(data, dict):
                        if data.get('event') == 'systemStatus':
                            print(f"[OK] System status: {data.get('status')}")
                        elif data.get('event') == 'subscriptionStatus':
                            print(f"[OK] Subscription status: {data.get('status')}")
                    else:
                        # Market data message
                        print(f"[OK] Received market data message (#{message_count})")
                        if message_count >= 2:
                            # We've got confirmation + first data message
                            break

                except asyncio.TimeoutError:
                    print("[WARN] Timeout waiting for message")
                    break

            if message_count >= 2:
                print("\n[OK] Kraken WebSocket preflight check PASSED")
                print(f"  - Received {message_count} messages in {time.time() - start_time:.2f}s")
                return True
            else:
                print(f"\n[WARN] Only received {message_count} messages")
                return False

    except Exception as e:
        print(f"\n[FAIL] Kraken WebSocket connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_kraken_ws_client():
    """Test the full KrakenWebSocketClient with latency tracking and circuit breakers."""
    print("\n" + "="*60)
    print("PREFLIGHT CHECK 3: KrakenWebSocketClient Integration Test")
    print("="*60)

    try:
        # Import the KrakenWebSocketClient
        sys.path.insert(0, str(Path(__file__).parent))
        from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig

        print("[OK] KrakenWebSocketClient imported successfully")

        # Create configuration
        config = KrakenWSConfig()
        print(f"[OK] Configuration loaded:")
        print(f"  - Pairs: {config.pairs}")
        print(f"  - Timeframes: {config.timeframes}")
        print(f"  - Latency tracking: {config.enable_latency_tracking}")
        print(f"  - Health monitoring: {config.enable_health_monitoring}")
        print(f"  - Scalping: {config.scalp_enabled}")

        # Create client
        client = KrakenWebSocketClient(config)
        print("[OK] KrakenWebSocketClient instantiated")

        # Test Redis connection initialization
        print("\nTesting Redis initialization...")
        await client.redis_manager.initialize_pool()

        if client.redis_manager.redis_client:
            print("[OK] Redis Cloud connection initialized")

            # Test Redis ping
            start_time = time.time()
            await client.redis_manager.redis_client.ping()
            latency_ms = (time.time() - start_time) * 1000
            print(f"[OK] Redis PING successful (latency: {latency_ms:.2f}ms)")
        else:
            print("[WARN] Redis client not initialized (check REDIS_URL)")

        # Check circuit breakers
        print("\nCircuit breaker status:")
        for name, cb in client.circuit_breakers.items():
            print(f"  {name}: {cb.state.value} (threshold: {cb.failure_threshold})")

        # Check latency tracker
        if client.latency_tracker:
            print(f"[OK] Latency tracker initialized (max samples: {client.latency_tracker.max_samples})")
        else:
            print("[WARN] Latency tracker not initialized")

        # Test WebSocket connection briefly (3 seconds)
        print("\nTesting WebSocket connection for 3 seconds...")

        async def run_client_briefly():
            await asyncio.wait_for(client.start(), timeout=3.0)

        try:
            await run_client_briefly()
        except asyncio.TimeoutError:
            # Expected timeout after 3 seconds
            await client.stop()

            stats = client.get_stats()
            print(f"\n[OK] WebSocket test completed:")
            print(f"  - Messages received: {stats['messages_received']}")
            print(f"  - Reconnects: {stats['reconnects']}")
            print(f"  - Errors: {stats['errors']}")
            print(f"  - Circuit breaker trips: {stats['circuit_breaker_trips']}")

            if stats.get('latency_stats'):
                lat_stats = stats['latency_stats']
                print(f"  - Latency avg: {lat_stats.get('avg', 0):.2f}ms")
                print(f"  - Latency p95: {lat_stats.get('p95', 0):.2f}ms")
                print(f"  - Latency p99: {lat_stats.get('p99', 0):.2f}ms")

            if stats['messages_received'] > 0:
                print("\n[OK] KrakenWebSocketClient integration test PASSED")
                return True
            else:
                print("\n[WARN] No messages received during test")
                return False

    except Exception as e:
        print(f"\n[FAIL] KrakenWebSocketClient test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def check_system_config():
    """Check system configuration."""
    print("\n" + "="*60)
    print("PREFLIGHT CHECK 4: System Configuration")
    print("="*60)

    # Check trading pairs
    trading_pairs = os.getenv('TRADING_PAIRS', '').split(',')
    print(f"Trading pairs: {trading_pairs}")

    # Check trading mode
    trading_mode = os.getenv('TRADING_MODE', 'paper')
    print(f"Trading mode: {trading_mode}")

    # Check feature flags
    features = {
        'Latency Tracking': os.getenv('ENABLE_LATENCY_TRACKING', 'false'),
        'Health Monitoring': os.getenv('ENABLE_HEALTH_MONITORING', 'false'),
        'Stream Sharding': os.getenv('KRAKEN_WS_STREAM_SHARDING', 'false'),
        'Scalping Enabled': os.getenv('SCALP_ENABLED', 'false'),
        'ML Confidence Gate': os.getenv('ENABLE_ML_CONFIDENCE_GATE', 'false'),
        'Regime Detection': os.getenv('ENABLE_REGIME_DETECTION', 'false'),
        'Safety Gates': os.getenv('ENABLE_SAFETY_GATES', 'false'),
    }

    print("\nFeature flags:")
    for name, value in features.items():
        status = "[OK] Enabled" if value.lower() == 'true' else "[FAIL] Disabled"
        print(f"  {name}: {status}")

    # Check circuit breaker settings
    print("\nCircuit breaker thresholds:")
    print(f"  Spread: {os.getenv('CIRCUIT_BREAKER_SPREAD_THRESHOLD', 'N/A')}")
    print(f"  Latency: {os.getenv('CIRCUIT_BREAKER_LATENCY_THRESHOLD', 'N/A')}ms")
    print(f"  Connection: {os.getenv('CIRCUIT_BREAKER_CONNECTION_THRESHOLD', 'N/A')} failures")

    print("\n[OK] System configuration check PASSED")
    return True


async def main():
    """Run all preflight checks."""
    print("\n" + "="*60)
    print("CRYPTO-AI-BOT PREFLIGHT CHECKS")
    print("="*60)
    print(f"Environment: .env.prod")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    results = []

    # Run checks
    results.append(("Redis TLS", await test_redis_tls()))
    results.append(("Kraken WebSocket", await test_kraken_ws()))
    results.append(("KrakenWebSocketClient", await test_kraken_ws_client()))
    results.append(("System Config", await check_system_config()))

    # Summary
    print("\n" + "="*60)
    print("PREFLIGHT CHECK SUMMARY")
    print("="*60)

    for name, passed in results:
        status = "[OK] PASSED" if passed else "[FAIL] FAILED"
        print(f"{name}: {status}")

    all_passed = all(result[1] for result in results)

    if all_passed:
        print("\n[SUCCESS] ALL PREFLIGHT CHECKS PASSED - READY FOR ENGINE START")
        print("="*60)
        return 0
    else:
        print("\n[ERROR] SOME PREFLIGHT CHECKS FAILED - REVIEW ERRORS ABOVE")
        print("="*60)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
