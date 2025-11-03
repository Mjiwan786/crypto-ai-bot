#!/usr/bin/env python3
"""
Kraken API Connectivity Check

Tests Kraken public REST API connectivity and basic functionality.
Does not require API keys - uses public endpoints only.

Usage:
    python scripts/check_kraken_api.py
    python scripts/check_kraken_api.py --verbose

Exit Codes:
    0: All checks passed
    1: API connectivity failed
    2: Rate limit exceeded
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Tuple

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
    import aiohttp
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ Missing required packages: {e}")
    print("Run: pip install aiohttp python-dotenv")
    sys.exit(1)

# Load environment variables
env_file = project_root / ".env.prod"
if env_file.exists():
    load_dotenv(env_file)

# Configuration
KRAKEN_API_URL = os.getenv("KRAKEN_API_URL", "https://api.kraken.com")
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


async def check_kraken_server_time() -> Tuple[bool, Dict[str, Any]]:
    """
    Test Kraken /0/public/Time endpoint.

    Returns:
        Tuple of (success: bool, metadata: dict)
    """
    print_header("Kraken API - Server Time Check")

    endpoint = f"{KRAKEN_API_URL}/0/public/Time"
    print_info(f"Endpoint: {endpoint}")

    try:
        start_time = time.time()

        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint, timeout=aiohttp.ClientTimeout(total=10)) as response:
                elapsed = (time.time() - start_time) * 1000

                if response.status != 200:
                    print_error(f"HTTP {response.status}: {response.reason}")
                    return False, {"error": f"HTTP {response.status}", "status_code": response.status}

                data = await response.json()

                if "error" in data and data["error"]:
                    print_error(f"API Error: {data['error']}")
                    return False, {"error": data["error"]}

                if "result" not in data:
                    print_error("Unexpected response format")
                    return False, {"error": "Invalid response"}

                server_time = data["result"]["unixtime"]
                server_rfc = data["result"]["rfc1123"]

                print_success(f"Server time: {server_rfc}")
                print_success(f"Response time: {elapsed:.2f}ms")

                # Check time drift
                local_time = int(time.time())
                time_drift = abs(server_time - local_time)

                if time_drift > 60:
                    print_warning(f"Time drift detected: {time_drift}s (should be <60s)")

                return True, {
                    "server_time": server_time,
                    "server_rfc": server_rfc,
                    "latency_ms": round(elapsed, 2),
                    "time_drift_seconds": time_drift,
                }

    except asyncio.TimeoutError:
        print_error("Request timed out (>10s)")
        return False, {"error": "Timeout"}

    except aiohttp.ClientError as e:
        print_error(f"Connection error: {e}")
        return False, {"error": f"Connection error: {str(e)}"}

    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return False, {"error": f"Unexpected error: {str(e)}"}


async def check_kraken_asset_pairs() -> Tuple[bool, Dict[str, Any]]:
    """
    Test Kraken /0/public/AssetPairs endpoint.

    Returns:
        Tuple of (success: bool, metadata: dict)
    """
    print_header("Kraken API - Asset Pairs Check")

    # Check specific pairs used by the bot
    test_pairs = ["XBTUSD", "ETHUSD", "SOLUSD"]
    endpoint = f"{KRAKEN_API_URL}/0/public/AssetPairs"
    print_info(f"Endpoint: {endpoint}")
    print_info(f"Test pairs: {', '.join(test_pairs)}")

    try:
        start_time = time.time()

        async with aiohttp.ClientSession() as session:
            params = {"pair": ",".join(test_pairs)}
            async with session.get(
                endpoint, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                elapsed = (time.time() - start_time) * 1000

                if response.status != 200:
                    print_error(f"HTTP {response.status}: {response.reason}")
                    return False, {"error": f"HTTP {response.status}", "status_code": response.status}

                data = await response.json()

                if "error" in data and data["error"]:
                    print_error(f"API Error: {data['error']}")
                    return False, {"error": data["error"]}

                if "result" not in data:
                    print_error("Unexpected response format")
                    return False, {"error": "Invalid response"}

                pairs_data = data["result"]
                pairs_found = list(pairs_data.keys())

                print_success(f"Found {len(pairs_found)} trading pairs")
                print_success(f"Response time: {elapsed:.2f}ms")

                for pair in pairs_found:
                    pair_info = pairs_data[pair]
                    wsname = pair_info.get("wsname", "N/A")
                    status = pair_info.get("status", "unknown")
                    print_info(f"  {pair} ({wsname}): {status}")

                return True, {
                    "pairs_found": len(pairs_found),
                    "pairs": pairs_found,
                    "latency_ms": round(elapsed, 2),
                }

    except asyncio.TimeoutError:
        print_error("Request timed out (>10s)")
        return False, {"error": "Timeout"}

    except aiohttp.ClientError as e:
        print_error(f"Connection error: {e}")
        return False, {"error": f"Connection error: {str(e)}"}

    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return False, {"error": f"Unexpected error: {str(e)}"}


async def check_kraken_system_status() -> Tuple[bool, Dict[str, Any]]:
    """
    Test Kraken /0/public/SystemStatus endpoint.

    Returns:
        Tuple of (success: bool, metadata: dict)
    """
    print_header("Kraken API - System Status Check")

    endpoint = f"{KRAKEN_API_URL}/0/public/SystemStatus"
    print_info(f"Endpoint: {endpoint}")

    try:
        start_time = time.time()

        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint, timeout=aiohttp.ClientTimeout(total=10)) as response:
                elapsed = (time.time() - start_time) * 1000

                if response.status != 200:
                    print_error(f"HTTP {response.status}: {response.reason}")
                    return False, {"error": f"HTTP {response.status}", "status_code": response.status}

                data = await response.json()

                if "error" in data and data["error"]:
                    print_error(f"API Error: {data['error']}")
                    return False, {"error": data["error"]}

                if "result" not in data:
                    print_error("Unexpected response format")
                    return False, {"error": "Invalid response"}

                status_info = data["result"]
                status = status_info.get("status", "unknown")
                timestamp = status_info.get("timestamp", "N/A")

                if status == "online":
                    print_success(f"System status: {status}")
                elif status == "maintenance":
                    print_warning(f"System status: {status} (maintenance mode)")
                elif status in ["cancel_only", "post_only"]:
                    print_warning(f"System status: {status} (limited functionality)")
                else:
                    print_error(f"System status: {status}")

                print_success(f"Response time: {elapsed:.2f}ms")

                return True, {
                    "status": status,
                    "timestamp": timestamp,
                    "latency_ms": round(elapsed, 2),
                }

    except asyncio.TimeoutError:
        print_error("Request timed out (>10s)")
        return False, {"error": "Timeout"}

    except aiohttp.ClientError as e:
        print_error(f"Connection error: {e}")
        return False, {"error": f"Connection error: {str(e)}"}

    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return False, {"error": f"Unexpected error: {str(e)}"}


def print_summary(results: Dict[str, Tuple[bool, Dict[str, Any]]]) -> int:
    """
    Print summary of all checks.

    Args:
        results: Dictionary of check results

    Returns:
        Exit code (0 if all passed, non-zero otherwise)
    """
    print_header("Summary")

    # Summary table
    print(f"{'Check':<30} {'Status':<10} {'Details':<30}")
    print("-" * 70)

    exit_code = 0

    for check_name, (success, metadata) in results.items():
        status = f"{Colors.GREEN}PASS{Colors.END}" if success else f"{Colors.RED}FAIL{Colors.END}"

        # Format details
        if success:
            latency = metadata.get("latency_ms", "N/A")
            details = f"Latency: {latency}ms"
        else:
            details = metadata.get("error", "Unknown error")[:30]
            exit_code = max(exit_code, 1)

        print(f"{check_name:<30} {status:<20} {details:<30}")

    print("-" * 70)

    if exit_code == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ All Kraken API checks passed!{Colors.END}")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ Some Kraken API checks failed!{Colors.END}")

    return exit_code


async def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code
    """
    print(f"\n{Colors.BOLD}Kraken API Connectivity Checks{Colors.END}")
    print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
    print(f"API URL: {KRAKEN_API_URL}\n")

    # Run all checks
    results = {}

    # Check 1: Server time
    success, metadata = await check_kraken_server_time()
    results["Server Time"] = (success, metadata)

    # Check 2: Asset pairs
    success, metadata = await check_kraken_asset_pairs()
    results["Asset Pairs"] = (success, metadata)

    # Check 3: System status
    success, metadata = await check_kraken_system_status()
    results["System Status"] = (success, metadata)

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
