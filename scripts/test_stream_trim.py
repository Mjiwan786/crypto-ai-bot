#!/usr/bin/env python3
"""
Test Stream Trimming

Verifies that Redis streams are properly trimmed to prevent unbounded growth.

Test:
1. Seed 12k messages to signals:live stream
2. Verify XINFO STREAM shows length <= maxlen + epsilon
3. Verify XTRIM is working as expected

Usage:
    python scripts/test_stream_trim.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import after path setup
try:
    import redis.asyncio as aioredis
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ Missing required packages: {e}")
    print("Run: pip install redis python-dotenv")
    sys.exit(1)

# Load environment variables
env_file = project_root / ".env.prod"
if env_file.exists():
    load_dotenv(env_file)

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_CA_CERT = os.getenv("REDIS_CA_CERT", "./config/certs/redis_ca.pem")
STREAM_MAXLEN_SIGNALS = int(os.getenv("STREAM_MAXLEN_SIGNALS", "10000"))
STREAM_MAXLEN_PNL = int(os.getenv("STREAM_MAXLEN_PNL", "5000"))

# Test configuration
TEST_MESSAGE_COUNT = 12000
EPSILON_TOLERANCE = 100  # Allow up to 100 messages over limit (Redis approximate trim)


class Colors:
    """Terminal colors"""
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def print_header(text: str) -> None:
    """Print section header"""
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}{Colors.END}\n")


def print_success(text: str) -> None:
    """Print success message"""
    print(f"{Colors.GREEN}✓{Colors.END} {text}")


def print_error(text: str) -> None:
    """Print error message"""
    print(f"{Colors.RED}✗{Colors.END} {text}")


def print_warning(text: str) -> None:
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠{Colors.END} {text}")


async def seed_messages(client: aioredis.Redis, stream_key: str, count: int, maxlen: int) -> int:
    """
    Seed messages to a stream with XTRIM.

    Args:
        client: Redis client
        stream_key: Stream name
        count: Number of messages to publish
        maxlen: Maximum stream length

    Returns:
        Number of messages published
    """
    print(f"Seeding {count} messages to {stream_key} (maxlen={maxlen})...")

    published = 0
    start_time = time.time()

    for i in range(count):
        message = {
            "id": f"test-{int(time.time()*1000)}-{i}",
            "ts": int(time.time() * 1000),
            "data": f"test_message_{i}",
            "index": i
        }

        # Publish with XTRIM
        await client.xadd(
            stream_key,
            {"json": json.dumps(message)},
            maxlen=maxlen  # Use approximate trim
        )

        published += 1

        # Progress indicator every 1000 messages
        if (i + 1) % 1000 == 0:
            print(f"  Published {i + 1}/{count} messages...")

    elapsed = time.time() - start_time
    print(f"  Completed in {elapsed:.2f}s ({published/elapsed:.1f} msg/s)")

    return published


async def verify_stream_length(client: aioredis.Redis, stream_key: str, expected_maxlen: int, epsilon: int) -> bool:
    """
    Verify stream length is within expected bounds.

    Args:
        client: Redis client
        stream_key: Stream name
        expected_maxlen: Expected maximum length
        epsilon: Tolerance for approximate trim

    Returns:
        True if length is within bounds, False otherwise
    """
    try:
        # Get stream length
        actual_length = await client.xlen(stream_key)

        # Get detailed stream info
        info = await client.execute_command("XINFO", "STREAM", stream_key)

        # Parse info (returned as list of [key, value, key, value, ...])
        info_dict = {}
        for i in range(0, len(info), 2):
            key = info[i].decode('utf-8') if isinstance(info[i], bytes) else info[i]
            value = info[i+1]
            if isinstance(value, bytes):
                value = value.decode('utf-8')
            info_dict[key] = value

        print(f"\nStream: {stream_key}")
        print(f"  Length: {actual_length}")
        print(f"  Expected maxlen: {expected_maxlen}")
        print(f"  Tolerance: ±{epsilon}")
        print(f"  First entry: {info_dict.get('first-entry', 'N/A')}")
        print(f"  Last entry: {info_dict.get('last-entry', 'N/A')}")

        # Check if within bounds
        if actual_length <= expected_maxlen + epsilon:
            print_success(f"Stream length {actual_length} is within bounds (≤ {expected_maxlen + epsilon})")
            return True
        else:
            print_error(f"Stream length {actual_length} exceeds bounds (> {expected_maxlen + epsilon})")
            return False

    except Exception as e:
        print_error(f"Failed to verify stream: {e}")
        return False


async def test_signals_stream(client: aioredis.Redis) -> bool:
    """Test signals:live stream trimming"""
    print_header("Test 1: signals:live Stream Trimming")

    stream_key = "signals:live"

    # Seed messages
    published = await seed_messages(client, stream_key, TEST_MESSAGE_COUNT, STREAM_MAXLEN_SIGNALS)
    print_success(f"Published {published} messages to {stream_key}")

    # Verify stream length
    passed = await verify_stream_length(client, stream_key, STREAM_MAXLEN_SIGNALS, EPSILON_TOLERANCE)

    return passed


async def test_pnl_stream(client: aioredis.Redis) -> bool:
    """Test metrics:pnl:equity stream trimming"""
    print_header("Test 2: metrics:pnl:equity Stream Trimming")

    stream_key = "metrics:pnl:equity"

    # Seed half as many messages for PnL (since it has lower maxlen)
    test_count = min(TEST_MESSAGE_COUNT, STREAM_MAXLEN_PNL * 2)

    # Seed messages
    published = await seed_messages(client, stream_key, test_count, STREAM_MAXLEN_PNL)
    print_success(f"Published {published} messages to {stream_key}")

    # Verify stream length
    passed = await verify_stream_length(client, stream_key, STREAM_MAXLEN_PNL, EPSILON_TOLERANCE)

    return passed


async def main() -> int:
    """
    Main test entry point.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    print(f"\n{Colors.BOLD}Stream Trimming Test{Colors.END}")
    print(f"Test Message Count: {TEST_MESSAGE_COUNT}")
    print(f"Signal Stream Maxlen: {STREAM_MAXLEN_SIGNALS}")
    print(f"PnL Stream Maxlen: {STREAM_MAXLEN_PNL}")
    print(f"Epsilon Tolerance: {EPSILON_TOLERANCE}\n")

    if not REDIS_URL:
        print_error("REDIS_URL environment variable not set")
        return 1

    # Resolve CA certificate path
    ca_cert_path = Path(REDIS_CA_CERT)
    if not ca_cert_path.is_absolute():
        ca_cert_path = project_root / ca_cert_path

    use_tls = REDIS_URL.startswith("rediss://")

    if use_tls and not ca_cert_path.exists():
        print_error(f"Redis CA certificate not found: {ca_cert_path}")
        return 2

    try:
        # Create Redis client
        if use_tls:
            client = await aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                ssl_cert_reqs="required",
                ssl_ca_certs=str(ca_cert_path),
                ssl_check_hostname=True,
                socket_connect_timeout=10,
                socket_timeout=10,
            )
        else:
            client = await aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=10,
                socket_timeout=10,
            )

        # Test connection
        await client.ping()
        print_success("Connected to Redis\n")

        # Run tests
        test_results = []

        # Test 1: signals:live
        result1 = await test_signals_stream(client)
        test_results.append(("signals:live trimming", result1))

        # Test 2: metrics:pnl:equity
        result2 = await test_pnl_stream(client)
        test_results.append(("metrics:pnl:equity trimming", result2))

        # Summary
        print_header("Test Summary")

        passed_count = sum(1 for _, passed in test_results if passed)
        total_count = len(test_results)

        for test_name, passed in test_results:
            status = f"{Colors.GREEN}PASS{Colors.END}" if passed else f"{Colors.RED}FAIL{Colors.END}"
            print(f"  [{status}] {test_name}")

        print(f"\n  {passed_count}/{total_count} tests passed\n")

        await client.aclose()

        # Return 0 if all tests passed, 1 otherwise
        return 0 if passed_count == total_count else 1

    except Exception as e:
        print_error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Interrupted by user{Colors.END}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Colors.RED}Fatal error: {e}{Colors.END}")
        sys.exit(1)
