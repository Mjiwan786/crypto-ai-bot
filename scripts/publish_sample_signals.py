#!/usr/bin/env python3
"""
Sample Signal & PnL Publisher

Publishes test signals and PnL metrics to Redis streams to verify end-to-end connectivity.

Streams:
- signals:live - Live trading signals
- signals:paper - Paper trading signals
- metrics:pnl:equity - PnL equity curve data

Usage:
    python scripts/publish_sample_signals.py
    python scripts/publish_sample_signals.py --count 5
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse

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
SIGNAL_COUNT = int(os.getenv("SIGNAL_COUNT", "2"))

# Stream maxlen configuration (prevent unbounded growth)
STREAM_MAXLEN_SIGNALS = int(os.getenv("STREAM_MAXLEN_SIGNALS", "10000"))
STREAM_MAXLEN_PNL = int(os.getenv("STREAM_MAXLEN_PNL", "5000"))

# Override from command line
if "--count" in sys.argv:
    idx = sys.argv.index("--count")
    if idx + 1 < len(sys.argv):
        SIGNAL_COUNT = int(sys.argv[idx + 1])


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
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}{Colors.END}\n")


def print_success(text: str) -> None:
    """Print success message"""
    print(f"{Colors.GREEN}✓{Colors.END} {text}")


def print_error(text: str) -> None:
    """Print error message"""
    print(f"{Colors.RED}✗{Colors.END} {text}")


def generate_signal(pair: str, side: str, mode: str, idx: int = 0) -> Dict[str, Any]:
    """
    Generate a sample signal.

    Args:
        pair: Trading pair (BTC-USD, ETH-USD)
        side: buy or sell
        mode: paper or live
        idx: Signal index for uniqueness

    Returns:
        Signal dictionary
    """
    timestamp = int(time.time() * 1000)

    # Sample prices
    prices = {
        "BTC-USD": {"entry": 45000.0, "sl": 44500.0, "tp": 46000.0},
        "ETH-USD": {"entry": 3000.0, "sl": 2950.0, "tp": 3100.0},
    }

    price_data = prices.get(pair, prices["BTC-USD"])

    signal = {
        "id": f"sample-{timestamp}-{idx}",
        "ts": timestamp,
        "pair": pair,
        "side": side,
        "entry": price_data["entry"],
        "sl": price_data["sl"],
        "tp": price_data["tp"],
        "strategy": "sample_publisher",
        "confidence": 0.85 + (idx * 0.05),  # Vary confidence
        "mode": mode,
        "source": "preflight_test",
    }

    return signal


def generate_pnl_point(equity: float, timestamp: int) -> Dict[str, Any]:
    """
    Generate a PnL equity point.

    Args:
        equity: Current equity value
        timestamp: Unix timestamp in milliseconds

    Returns:
        PnL data dictionary
    """
    return {
        "timestamp": timestamp,
        "equity": equity,
        "balance": equity * 0.95,  # Assume 5% in open positions
        "pnl_24h": equity * 0.02,  # 2% gain in 24h
        "source": "preflight_test",
    }


async def publish_signals(client: aioredis.Redis, count: int) -> Dict[str, int]:
    """
    Publish sample signals to Redis streams.

    Args:
        client: Redis client
        count: Number of signals to publish

    Returns:
        Dictionary with publish counts
    """
    print_header("Publishing Sample Signals")

    stats = {
        "signals:paper": 0,
        "signals:live": 0,
    }

    # Publish to both paper and live streams
    for mode in ["paper", "live"]:
        stream_key = f"signals:{mode}"

        for i in range(count):
            # Alternate between BTC and ETH
            pair = "BTC-USD" if i % 2 == 0 else "ETH-USD"
            # Alternate between buy and sell
            side = "buy" if i % 2 == 0 else "sell"

            signal = generate_signal(pair, side, mode, i)

            # Publish to stream with XTRIM (approximate trim for performance)
            message_id = await client.xadd(
                stream_key,
                {"json": json.dumps(signal)},
                maxlen=STREAM_MAXLEN_SIGNALS,  # Configurable via STREAM_MAXLEN_SIGNALS
            )

            stats[stream_key] += 1

            print_success(
                f"Published {mode.upper()} signal: {pair} {side.upper()} "
                f"@ ${signal['entry']} (ID: {message_id})"
            )

    return stats


async def publish_pnl_metrics(client: aioredis.Redis, count: int) -> int:
    """
    Publish sample PnL equity points.

    Args:
        client: Redis client
        count: Number of points to publish

    Returns:
        Number of points published
    """
    print_header("Publishing Sample PnL Metrics")

    base_equity = 10000.0
    current_time = int(time.time() * 1000)
    published = 0

    for i in range(count):
        # Simulate equity growth
        equity = base_equity + (i * 100)  # +$100 per point
        timestamp = current_time - ((count - i) * 3600000)  # Go back in time by hours

        pnl_point = generate_pnl_point(equity, timestamp)

        # Publish to PnL stream with XTRIM (approximate trim for performance)
        message_id = await client.xadd(
            "metrics:pnl:equity",
            {"json": json.dumps(pnl_point)},
            maxlen=STREAM_MAXLEN_PNL,  # Configurable via STREAM_MAXLEN_PNL
        )

        published += 1

        print_success(
            f"Published PnL point: Equity=${pnl_point['equity']:.2f}, "
            f"PnL 24h=${pnl_point['pnl_24h']:.2f} (ID: {message_id})"
        )

    return published


async def verify_streams(client: aioredis.Redis) -> Dict[str, int]:
    """
    Verify signals exist in streams.

    Args:
        client: Redis client

    Returns:
        Dictionary with stream lengths
    """
    print_header("Verifying Stream Contents")

    streams = ["signals:paper", "signals:live", "metrics:pnl:equity"]
    lengths = {}

    for stream in streams:
        try:
            length = await client.xlen(stream)
            lengths[stream] = length
            print_success(f"{stream}: {length} messages")
        except Exception as e:
            print_error(f"{stream}: Error - {e}")
            lengths[stream] = 0

    return lengths


async def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code
    """
    print(f"\n{Colors.BOLD}Sample Signal & PnL Publisher{Colors.END}")
    print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
    print(f"Signal Count: {SIGNAL_COUNT} per stream\n")

    if not REDIS_URL:
        print_error("REDIS_URL environment variable not set")
        return 1

    parsed = urlparse(REDIS_URL)
    use_tls = parsed.scheme == "rediss"

    print(f"Redis: {parsed.netloc}")
    print(f"TLS: {'Enabled' if use_tls else 'Disabled'}\n")

    # Resolve CA certificate path
    ca_cert_path = Path(REDIS_CA_CERT)
    if not ca_cert_path.is_absolute():
        ca_cert_path = project_root / ca_cert_path

    if use_tls and not ca_cert_path.exists():
        print_error(f"Redis CA certificate not found: {ca_cert_path}")
        return 2

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

        # Test connection
        print("Testing connection...")
        await client.ping()
        print_success("Connected to Redis\n")

        # Publish signals
        signal_stats = await publish_signals(client, SIGNAL_COUNT)

        # Publish PnL metrics
        pnl_count = await publish_pnl_metrics(client, SIGNAL_COUNT)

        # Verify streams
        stream_lengths = await verify_streams(client)

        # Summary
        print_header("Publish Summary")
        print(f"  {'Stream':<30} {'Published':<15} {'Total':<15}")
        print("  " + "-" * 60)
        print(f"  {'signals:paper':<30} {signal_stats['signals:paper']:<15} {stream_lengths.get('signals:paper', 0):<15}")
        print(f"  {'signals:live':<30} {signal_stats['signals:live']:<15} {stream_lengths.get('signals:live', 0):<15}")
        print(f"  {'metrics:pnl:equity':<30} {pnl_count:<15} {stream_lengths.get('metrics:pnl:equity', 0):<15}")
        print("  " + "-" * 60)

        total_published = sum(signal_stats.values()) + pnl_count
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Published {total_published} messages successfully!{Colors.END}\n")

        await client.close()
        return 0

    except Exception as e:
        print_error(f"Failed to publish: {e}")
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
