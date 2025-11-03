#!/usr/bin/env python3
"""
Redis Cloud TLS Connectivity Verification Script

Tests Redis Cloud connection with TLS/SSL including:
- Basic PING connectivity
- Stream operations (XADD/XREAD)
- TLS certificate verification
- Connection pooling

Usage:
    python scripts/check_redis_tls.py
    python scripts/check_redis_tls.py --verbose

Exit Codes:
    0: All checks passed
    1: Connection failed
    2: TLS certificate verification failed
    3: Stream operations failed
"""

import asyncio
import os
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Tuple
from urllib.parse import urlparse

# Fix Windows console encoding for Unicode characters
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
else:
    print(f"⚠️  .env.prod not found, using environment variables")

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_CA_CERT = os.getenv("REDIS_CA_CERT", "./config/certs/redis_ca.pem")
VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv


class Colors:
    """Terminal colors for output"""

    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def print_header(text: str) -> None:
    """Print section header"""
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}{Colors.END}\n")


def print_success(text: str) -> None:
    """Print success message"""
    print(f"{Colors.GREEN}✓{Colors.END} {text}")


def print_error(text: str) -> None:
    """Print error message"""
    print(f"{Colors.RED}✗{Colors.END} {text}")


def print_warning(text: str) -> None:
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠{Colors.END} {text}")


def print_info(text: str) -> None:
    """Print info message"""
    if VERBOSE:
        print(f"  {text}")


async def check_redis_connection() -> Tuple[bool, Dict[str, Any]]:
    """
    Test basic Redis connection with TLS.

    Returns:
        Tuple of (success: bool, metadata: dict)
    """
    print_header("Redis Cloud TLS Connection Check")

    if not REDIS_URL:
        print_error("REDIS_URL environment variable not set")
        return False, {"error": "REDIS_URL not configured"}

    parsed = urlparse(REDIS_URL)
    use_tls = parsed.scheme == "rediss"

    if not use_tls:
        print_warning("REDIS_URL uses 'redis://' instead of 'rediss://' (TLS disabled)")
        print_warning("Production deployments should use TLS")

    print_info(f"Redis URL: {parsed.netloc}")
    print_info(f"TLS Enabled: {use_tls}")

    # Resolve CA certificate path
    ca_cert_path = Path(REDIS_CA_CERT)
    if not ca_cert_path.is_absolute():
        ca_cert_path = project_root / ca_cert_path

    if use_tls and not ca_cert_path.exists():
        print_error(f"Redis CA certificate not found: {ca_cert_path}")
        return False, {"error": "CA certificate missing"}

    print_info(f"CA Certificate: {ca_cert_path}")

    try:
        # Create Redis client with TLS
        print_info("Creating Redis client...")

        if use_tls:
            print_success("Configuring TLS with certificate verification")

            client = aioredis.from_url(
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
            client = aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=10,
                socket_timeout=10,
            )

        # Test PING
        print_info("Testing PING...")
        start_time = time.time()
        pong = await client.ping()
        latency = (time.time() - start_time) * 1000

        if pong:
            print_success(f"PING successful (latency: {latency:.2f}ms)")
        else:
            print_error("PING failed")
            await client.close()
            return False, {"error": "PING returned False"}

        # Get server info
        print_info("Fetching server info...")
        info = await client.info("server")

        metadata = {
            "connected": True,
            "latency_ms": round(latency, 2),
            "tls_enabled": use_tls,
            "redis_version": info.get("redis_version", "unknown"),
            "tcp_port": info.get("tcp_port", "unknown"),
            "uptime_days": info.get("uptime_in_days", "unknown"),
        }

        print_success(f"Redis version: {metadata['redis_version']}")
        print_success(f"Server uptime: {metadata['uptime_days']} days")

        await client.close()
        return True, metadata

    except ssl.SSLError as e:
        print_error(f"TLS certificate verification failed: {e}")
        return False, {"error": f"SSL error: {str(e)}", "tls_enabled": use_tls}

    except aioredis.ConnectionError as e:
        print_error(f"Connection failed: {e}")
        return False, {"error": f"Connection error: {str(e)}"}

    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return False, {"error": f"Unexpected error: {str(e)}"}


async def check_redis_streams() -> Tuple[bool, Dict[str, Any]]:
    """
    Test Redis Streams operations (XADD/XREAD).

    Returns:
        Tuple of (success: bool, metadata: dict)
    """
    print_header("Redis Streams Operations Check")

    if not REDIS_URL:
        print_error("REDIS_URL environment variable not set")
        return False, {"error": "REDIS_URL not configured"}

    parsed = urlparse(REDIS_URL)
    use_tls = parsed.scheme == "rediss"

    # Resolve CA certificate path
    ca_cert_path = Path(REDIS_CA_CERT)
    if not ca_cert_path.is_absolute():
        ca_cert_path = project_root / ca_cert_path

    try:
        # Create Redis client
        if use_tls:
            client = aioredis.from_url(
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
            client = aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=10,
                socket_timeout=10,
            )

        # Test stream name with timestamp
        test_stream = f"preflight:test:{int(time.time())}"
        test_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "test": "preflight_check",
            "tls": str(use_tls),
        }

        # Test XADD
        print_info(f"Testing XADD on stream: {test_stream}")
        message_id = await client.xadd(test_stream, test_data)
        print_success(f"XADD successful (message ID: {message_id})")

        # Test XREAD
        print_info("Testing XREAD...")
        result = await client.xread({test_stream: "0"}, count=1)

        if result and len(result) > 0:
            stream_name, messages = result[0]
            if messages and len(messages) > 0:
                msg_id, msg_data = messages[0]
                print_success(f"XREAD successful (retrieved {len(messages)} message(s))")
                print_info(f"Message data: {msg_data}")
            else:
                print_error("XREAD returned no messages")
                await client.delete(test_stream)
                await client.close()
                return False, {"error": "XREAD returned empty result"}
        else:
            print_error("XREAD failed")
            await client.delete(test_stream)
            await client.close()
            return False, {"error": "XREAD returned None"}

        # Clean up test stream
        print_info("Cleaning up test stream...")
        await client.delete(test_stream)
        print_success("Test stream deleted")

        metadata = {
            "xadd_success": True,
            "xread_success": True,
            "message_id": message_id,
            "test_stream": test_stream,
        }

        await client.close()
        return True, metadata

    except Exception as e:
        print_error(f"Stream operations failed: {e}")
        return False, {"error": f"Stream error: {str(e)}"}


async def check_redis_pool() -> Tuple[bool, Dict[str, Any]]:
    """
    Test Redis connection pooling.

    Returns:
        Tuple of (success: bool, metadata: dict)
    """
    print_header("Redis Connection Pool Check")

    if not REDIS_URL:
        print_error("REDIS_URL environment variable not set")
        return False, {"error": "REDIS_URL not configured"}

    parsed = urlparse(REDIS_URL)
    use_tls = parsed.scheme == "rediss"

    # Resolve CA certificate path
    ca_cert_path = Path(REDIS_CA_CERT)
    if not ca_cert_path.is_absolute():
        ca_cert_path = project_root / ca_cert_path

    try:
        # Create connection pool
        print_info("Creating connection pool (max_connections=10)...")

        if use_tls:
            pool = aioredis.ConnectionPool.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=10,
                ssl_cert_reqs="required",
                ssl_ca_certs=str(ca_cert_path),
                ssl_check_hostname=True,
            )
        else:
            pool = aioredis.ConnectionPool.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=10,
            )

        client = aioredis.Redis(connection_pool=pool)

        # Test multiple concurrent operations
        print_info("Testing concurrent operations...")
        start_time = time.time()

        tasks = [client.ping() for _ in range(5)]
        results = await asyncio.gather(*tasks)

        elapsed = (time.time() - start_time) * 1000

        if all(results):
            print_success(f"5 concurrent PINGs successful ({elapsed:.2f}ms total)")
        else:
            print_error("Some concurrent PINGs failed")
            await pool.disconnect()
            return False, {"error": "Concurrent operations failed"}

        metadata = {
            "pool_size": 10,
            "concurrent_operations": 5,
            "total_time_ms": round(elapsed, 2),
            "avg_time_ms": round(elapsed / 5, 2),
        }

        await pool.disconnect()
        return True, metadata

    except Exception as e:
        print_error(f"Connection pool test failed: {e}")
        return False, {"error": f"Pool error: {str(e)}"}


def print_summary(results: Dict[str, Tuple[bool, Dict[str, Any]]]) -> int:
    """
    Print summary of all checks.

    Args:
        results: Dictionary of check results

    Returns:
        Exit code (0 if all passed, non-zero otherwise)
    """
    print_header("Preflight Summary")

    # Summary table
    print(f"{'Check':<30} {'Status':<10} {'Details':<30}")
    print("-" * 70)

    exit_code = 0

    for check_name, (success, metadata) in results.items():
        status = f"{Colors.GREEN}PASS{Colors.END}" if success else f"{Colors.RED}FAIL{Colors.END}"

        # Format details
        if success:
            if "latency_ms" in metadata:
                details = f"Latency: {metadata['latency_ms']}ms"
            elif "xadd_success" in metadata:
                details = f"Message ID: {metadata['message_id'][:10]}..."
            elif "pool_size" in metadata:
                details = f"Pool: {metadata['pool_size']}, Avg: {metadata['avg_time_ms']}ms"
            else:
                details = "OK"
        else:
            details = metadata.get("error", "Unknown error")[:30]
            exit_code = max(exit_code, 1)

        print(f"{check_name:<30} {status:<20} {details:<30}")

    print("-" * 70)

    if exit_code == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ All checks passed!{Colors.END}")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ Some checks failed!{Colors.END}")

    return exit_code


async def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code
    """
    print(f"\n{Colors.BOLD}Redis Cloud TLS Preflight Checks{Colors.END}")
    print(f"Timestamp: {datetime.utcnow().isoformat()}Z\n")

    # Run all checks
    results = {}

    # Check 1: Basic connection
    success, metadata = await check_redis_connection()
    results["Redis Connection"] = (success, metadata)

    if not success:
        # If basic connection fails, skip other checks
        print_warning("Skipping remaining checks due to connection failure")
        return print_summary(results)

    # Check 2: Stream operations
    success, metadata = await check_redis_streams()
    results["Stream Operations"] = (success, metadata)

    # Check 3: Connection pooling
    success, metadata = await check_redis_pool()
    results["Connection Pool"] = (success, metadata)

    # Print summary
    return print_summary(results)


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
