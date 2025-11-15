#!/usr/bin/env python3
"""
PnL Health Check - Crypto AI Bot

Production-grade health monitoring for PnL infrastructure.

Checks:
- Redis connectivity
- Trade stream activity (trades:closed)
- Equity stream activity (pnl:equity)
- Publish latency (P95)
- Data freshness

Exit Codes:
    0 - Healthy (all checks passed)
    1 - Unhealthy (critical failure)
    2 - Degraded (warnings present)

Environment Variables:
    REDIS_URL - Redis connection string (default: redis://localhost:6379/0)
    HEALTH_CHECK_TIMEOUT - Max age for fresh data in seconds (default: 300)

Usage:
    python scripts/health_check_pnl.py
    python scripts/health_check_pnl.py --verbose
    python scripts/health_check_pnl.py --json
"""

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    import orjson
except ImportError:
    orjson = None  # type: ignore

try:
    import redis
except ImportError:
    print("ERROR: redis package not installed. Run: pip install redis")
    sys.exit(1)


# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
HEALTH_CHECK_TIMEOUT = int(os.getenv("HEALTH_CHECK_TIMEOUT", "300"))  # 5 minutes


class HealthCheckResult:
    """Health check result."""

    def __init__(self):
        self.checks: Dict[str, bool] = {}
        self.messages: Dict[str, str] = {}
        self.metrics: Dict[str, float] = {}
        self.warnings: List[str] = []

    def add_check(self, name: str, passed: bool, message: str):
        """Add a check result."""
        self.checks[name] = passed
        self.messages[name] = message

    def add_metric(self, name: str, value: float):
        """Add a metric."""
        self.metrics[name] = value

    def add_warning(self, message: str):
        """Add a warning."""
        self.warnings.append(message)

    @property
    def is_healthy(self) -> bool:
        """Check if all critical checks passed."""
        return all(self.checks.values())

    @property
    def has_warnings(self) -> bool:
        """Check if any warnings present."""
        return len(self.warnings) > 0

    def get_status(self) -> str:
        """Get overall status."""
        if self.is_healthy and not self.has_warnings:
            return "healthy"
        elif self.is_healthy and self.has_warnings:
            return "degraded"
        else:
            return "unhealthy"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "status": self.get_status(),
            "checks": self.checks,
            "messages": self.messages,
            "metrics": self.metrics,
            "warnings": self.warnings,
            "timestamp": int(time.time() * 1000),
        }


def check_redis_connection(client: redis.Redis, result: HealthCheckResult) -> bool:
    """Check Redis connectivity."""
    try:
        client.ping()
        result.add_check("redis_connection", True, "Redis connection OK")
        return True
    except Exception as e:
        result.add_check("redis_connection", False, f"Redis connection failed: {e}")
        return False


def check_stream_activity(
    client: redis.Redis,
    stream_name: str,
    result: HealthCheckResult,
    count: int = 5,
) -> Tuple[bool, List[dict]]:
    """
    Check stream activity and return recent messages.

    Returns:
        (success, messages)
    """
    check_name = f"{stream_name}_activity"

    try:
        # Check if stream exists
        stream_len = client.xlen(stream_name)

        if stream_len == 0:
            result.add_check(
                check_name,
                False,
                f"Stream '{stream_name}' is empty",
            )
            return False, []

        result.add_metric(f"{stream_name}_length", float(stream_len))

        # Read last N messages using XREVRANGE (reverse order)
        messages = client.xrevrange(stream_name, "+", "-", count=count)

        if not messages:
            result.add_check(
                check_name,
                False,
                f"Stream '{stream_name}' exists but no messages readable",
            )
            return False, []

        # Parse messages
        parsed_messages = []
        for msg_id, fields in messages:
            # Decode message ID
            msg_id_str = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id

            # Parse JSON field
            json_bytes = fields.get(b"json") or fields.get("json")
            if json_bytes:
                try:
                    if orjson and hasattr(orjson, "loads"):
                        data = orjson.loads(json_bytes)
                    else:
                        if isinstance(json_bytes, bytes):
                            json_bytes = json_bytes.decode("utf-8")
                        data = json.loads(json_bytes)

                    parsed_messages.append({"id": msg_id_str, "data": data})
                except Exception:
                    continue

        result.add_check(
            check_name,
            True,
            f"Stream '{stream_name}' active ({stream_len} messages, {len(parsed_messages)} parsed)",
        )

        return True, parsed_messages

    except Exception as e:
        result.add_check(
            check_name,
            False,
            f"Failed to check stream '{stream_name}': {e}",
        )
        return False, []


def calculate_publish_latency(
    messages: List[dict],
    result: HealthCheckResult,
    stream_name: str,
) -> Optional[float]:
    """
    Calculate P95 publish latency (naive: now - message timestamp).

    Returns:
        P95 latency in milliseconds, or None if insufficient data
    """
    now_ms = int(time.time() * 1000)
    latencies = []

    for msg in messages:
        ts = msg["data"].get("ts")
        if ts:
            latency_ms = now_ms - int(ts)
            latencies.append(latency_ms)

    if not latencies:
        result.add_warning(f"No timestamps found in {stream_name} for latency calculation")
        return None

    # Calculate P95 (naive: sort and take 95th percentile)
    latencies.sort()
    p95_index = int(len(latencies) * 0.95)
    p95_latency = latencies[p95_index] if p95_index < len(latencies) else latencies[-1]

    result.add_metric(f"{stream_name}_p95_latency_ms", float(p95_latency))

    # Check freshness
    latest_latency = latencies[0] if latencies else None
    if latest_latency and latest_latency > (HEALTH_CHECK_TIMEOUT * 1000):
        result.add_warning(
            f"{stream_name} data is stale (latest: {latest_latency / 1000:.1f}s ago, "
            f"threshold: {HEALTH_CHECK_TIMEOUT}s)"
        )

    return p95_latency


def run_health_check(verbose: bool = False) -> HealthCheckResult:
    """Run all health checks."""
    result = HealthCheckResult()

    if verbose:
        print("=" * 60)
        print("PNL HEALTH CHECK")
        print("=" * 60)
        print(f"Redis URL: {REDIS_URL}")
        print(f"Timeout: {HEALTH_CHECK_TIMEOUT}s")
        print("=" * 60 + "\n")

    # Connect to Redis
    try:
        client = redis.from_url(
            REDIS_URL,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    except Exception as e:
        result.add_check("redis_connection", False, f"Failed to create Redis client: {e}")
        return result

    # Check 1: Redis connection
    if verbose:
        print("🔍 Checking Redis connection...")
    if not check_redis_connection(client, result):
        if verbose:
            print(f"❌ {result.messages['redis_connection']}\n")
        return result

    if verbose:
        print(f"✅ {result.messages['redis_connection']}\n")

    # Check 2: Trade stream activity
    if verbose:
        print("🔍 Checking trade stream (trades:closed)...")
    trades_ok, trade_messages = check_stream_activity(
        client, "trades:closed", result, count=5
    )

    if verbose:
        if trades_ok:
            print(f"✅ {result.messages['trades:closed_activity']}")
            print(f"   Latest trades: {len(trade_messages)}")
        else:
            print(f"⚠️  {result.messages['trades:closed_activity']}")
        print()

    # Check 3: Equity stream activity
    if verbose:
        print("🔍 Checking equity stream (pnl:equity)...")
    equity_ok, equity_messages = check_stream_activity(
        client, "pnl:equity", result, count=5
    )

    if not equity_ok:
        if verbose:
            print(f"❌ {result.messages['pnl:equity_activity']}\n")
        # Critical failure - equity stream must exist
        return result

    if verbose:
        print(f"✅ {result.messages['pnl:equity_activity']}")
        print(f"   Latest equity points: {len(equity_messages)}")
        print()

    # Check 4: Publish latency (trades)
    if trades_ok and trade_messages:
        if verbose:
            print("🔍 Calculating trade publish latency (P95)...")
        trades_p95 = calculate_publish_latency(trade_messages, result, "trades:closed")

        if verbose:
            if trades_p95:
                print(f"📊 Trade P95 latency: {trades_p95 / 1000:.2f}s")
            else:
                print("⚠️  Could not calculate trade latency")
            print()

    # Check 5: Publish latency (equity)
    if equity_ok and equity_messages:
        if verbose:
            print("🔍 Calculating equity publish latency (P95)...")
        equity_p95 = calculate_publish_latency(equity_messages, result, "pnl:equity")

        if verbose:
            if equity_p95:
                print(f"📊 Equity P95 latency: {equity_p95 / 1000:.2f}s")
            else:
                print("⚠️  Could not calculate equity latency")
            print()

    # Check 6: Latest equity value
    if verbose:
        print("🔍 Checking latest equity value...")

    try:
        latest_bytes = client.get("pnl:equity:latest")
        if latest_bytes:
            if orjson and hasattr(orjson, "loads"):
                latest_data = orjson.loads(latest_bytes)
            else:
                latest_data = json.loads(latest_bytes.decode("utf-8"))

            equity = latest_data.get("equity", 0)
            daily_pnl = latest_data.get("daily_pnl", 0)

            result.add_metric("current_equity", float(equity))
            result.add_metric("daily_pnl", float(daily_pnl))

            if verbose:
                print(f"✅ Latest equity: ${equity:,.2f} (daily PnL: ${daily_pnl:+,.2f})")
        else:
            result.add_warning("Latest equity value not found (pnl:equity:latest)")
            if verbose:
                print("⚠️  Latest equity value not found")
    except Exception as e:
        result.add_warning(f"Failed to read latest equity: {e}")
        if verbose:
            print(f"⚠️  Failed to read latest equity: {e}")

    return result


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PnL Health Check - Production-grade monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic health check
    python scripts/health_check_pnl.py

    # Verbose output
    python scripts/health_check_pnl.py --verbose

    # JSON output (for monitoring tools)
    python scripts/health_check_pnl.py --json

Exit codes:
    0 - Healthy (all checks passed)
    1 - Unhealthy (critical failure)
    2 - Degraded (warnings present)
        """,
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    # Run health check
    result = run_health_check(verbose=args.verbose and not args.json)

    # Output results
    if args.json:
        # JSON output
        output = result.to_dict()
        if orjson and hasattr(orjson, "dumps"):
            print(orjson.dumps(output, option=orjson.OPT_INDENT_2).decode("utf-8"))
        else:
            print(json.dumps(output, indent=2))
    else:
        # Human-readable summary
        if not args.verbose:
            status = result.get_status()
            if status == "healthy":
                print("✅ PnL infrastructure: HEALTHY")
            elif status == "degraded":
                print("⚠️  PnL infrastructure: DEGRADED")
                for warning in result.warnings:
                    print(f"   - {warning}")
            else:
                print("❌ PnL infrastructure: UNHEALTHY")
                for check_name, passed in result.checks.items():
                    if not passed:
                        print(f"   - {result.messages[check_name]}")
        else:
            # Verbose mode already printed everything
            print("=" * 60)
            print("HEALTH CHECK SUMMARY")
            print("=" * 60)
            print(f"Status: {result.get_status().upper()}")
            print(f"Checks: {sum(result.checks.values())}/{len(result.checks)} passed")
            if result.warnings:
                print(f"Warnings: {len(result.warnings)}")
            print("=" * 60)

    # Exit with appropriate code
    status = result.get_status()
    if status == "healthy":
        return 0
    elif status == "degraded":
        return 2
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
