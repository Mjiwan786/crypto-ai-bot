#!/usr/bin/env python3
"""
Crypto AI Bot - Health Check Utility

⚠️ SAFETY WARNING:
This script performs health checks on trading system components.
Use appropriate flags to avoid network calls in offline environments.

Subcommands:
  redis    - Check Redis Cloud connection (if REDIS_URL set)
  kraken   - Check Kraken API status (--live flag for network calls)
  exporter - Check Prometheus metrics exporter

Exit codes:
  0 = Healthy
  1 = Unhealthy
  2 = Degraded

Usage examples:
  python scripts/health.py redis
  python scripts/health.py kraken --live
  python scripts/health.py exporter
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Dict

# --- Constants ---
EXIT_HEALTHY = 0
EXIT_UNHEALTHY = 1
EXIT_DEGRADED = 2

REDIS_TIMEOUT = 5  # seconds
KRAKEN_TIMEOUT = 10  # seconds
EXPORTER_TIMEOUT = 5  # seconds


# --- Redis Health Check ---

def check_redis() -> int:
    """
    Check Redis connection if REDIS_URL is set.

    Returns:
        Exit code (0=healthy, 1=unhealthy, 2=not configured)
    """
    redis_url = os.getenv("REDIS_URL")

    if not redis_url:
        result = {
            "status": "skipped",
            "message": "REDIS_URL not set",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_HEALTHY  # Not configured is OK

    try:
        import redis
    except ImportError:
        result = {
            "status": "error",
            "message": "redis module not available",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_UNHEALTHY

    try:
        # Parse Redis URL
        parsed = urllib.parse.urlparse(redis_url)
        ssl_enabled = parsed.scheme == "rediss"

        # Configure Redis client
        start_time = time.time()

        if ssl_enabled:
            r = redis.Redis.from_url(
                redis_url,
                ssl_cert_reqs=None,  # Redis Cloud doesn't require custom certs
                socket_timeout=REDIS_TIMEOUT,
                socket_connect_timeout=REDIS_TIMEOUT
            )
        else:
            r = redis.Redis.from_url(
                redis_url,
                socket_timeout=REDIS_TIMEOUT,
                socket_connect_timeout=REDIS_TIMEOUT
            )

        # PING test
        ping_result = r.ping()
        latency_ms = (time.time() - start_time) * 1000

        if not ping_result:
            result = {
                "status": "unhealthy",
                "message": "Redis PING failed",
                "redis_url": f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 6379}",
                "ssl_enabled": ssl_enabled,
                "timestamp": int(time.time())
            }
            print(json.dumps(result, indent=2))
            return EXIT_UNHEALTHY

        # Get server info
        info = r.info("server")
        redis_version = info.get("redis_version", "unknown")

        result = {
            "status": "healthy",
            "message": "Redis connection OK",
            "redis_url": f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 6379}",
            "ssl_enabled": ssl_enabled,
            "redis_version": redis_version,
            "latency_ms": round(latency_ms, 2),
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_HEALTHY

    except redis.exceptions.ConnectionError as e:
        result = {
            "status": "unhealthy",
            "message": f"Redis connection failed: {e}",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_UNHEALTHY

    except redis.exceptions.TimeoutError as e:
        result = {
            "status": "unhealthy",
            "message": f"Redis timeout: {e}",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_UNHEALTHY

    except Exception as e:
        result = {
            "status": "error",
            "message": f"Redis error: {e}",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_UNHEALTHY


# --- Kraken Health Check ---

def check_kraken(live: bool) -> int:
    """
    Check Kraken API status.

    Args:
        live: If True, make network call. If False, skip with code 0.

    Returns:
        Exit code (0=healthy, 1=unhealthy, 2=skipped)
    """
    if not live:
        result = {
            "status": "skipped",
            "message": "Kraken check skipped (use --live to enable)",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_HEALTHY

    kraken_url = os.getenv("KRAKEN_API_URL", "https://api.kraken.com")
    status_url = f"{kraken_url}/0/public/SystemStatus"

    try:
        start_time = time.time()

        # Make HTTP request
        req = urllib.request.Request(
            status_url,
            headers={"User-Agent": "crypto-ai-bot/1.0"}
        )

        with urllib.request.urlopen(req, timeout=KRAKEN_TIMEOUT) as response:
            data = json.loads(response.read().decode())
            latency_ms = (time.time() - start_time) * 1000

        # Parse response
        if "result" in data and "status" in data["result"]:
            status = data["result"]["status"]

            if status in ["online", "healthy", "operational"]:
                result = {
                    "status": "healthy",
                    "message": f"Kraken API status: {status}",
                    "kraken_status": status,
                    "latency_ms": round(latency_ms, 2),
                    "timestamp": int(time.time())
                }
                print(json.dumps(result, indent=2))
                return EXIT_HEALTHY
            else:
                result = {
                    "status": "degraded",
                    "message": f"Kraken API status: {status}",
                    "kraken_status": status,
                    "timestamp": int(time.time())
                }
                print(json.dumps(result, indent=2))
                return EXIT_DEGRADED
        else:
            result = {
                "status": "unhealthy",
                "message": "Invalid Kraken API response format",
                "timestamp": int(time.time())
            }
            print(json.dumps(result, indent=2))
            return EXIT_UNHEALTHY

    except urllib.error.HTTPError as e:
        result = {
            "status": "unhealthy",
            "message": f"Kraken HTTP error: {e.code} {e.reason}",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_UNHEALTHY

    except urllib.error.URLError as e:
        result = {
            "status": "unhealthy",
            "message": f"Kraken connection failed: {e.reason}",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_UNHEALTHY

    except Exception as e:
        result = {
            "status": "error",
            "message": f"Kraken error: {e}",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_UNHEALTHY


# --- Prometheus Exporter Health Check ---

def check_exporter() -> int:
    """
    Check Prometheus metrics exporter.

    Fetches http://localhost:9308/metrics and ensures crypto_ai_bot metrics present.

    Returns:
        Exit code (0=healthy, 1=unhealthy)
    """
    metrics_url = "http://localhost:9308/metrics"

    try:
        start_time = time.time()

        # Make HTTP request
        req = urllib.request.Request(
            metrics_url,
            headers={"User-Agent": "crypto-ai-bot/1.0"}
        )

        with urllib.request.urlopen(req, timeout=EXPORTER_TIMEOUT) as response:
            content = response.read().decode()
            latency_ms = (time.time() - start_time) * 1000

        # Check for crypto_ai_bot metrics
        lines = content.splitlines()
        crypto_metrics = [line for line in lines if "crypto_ai_bot" in line and not line.startswith("#")]

        if not crypto_metrics:
            result = {
                "status": "unhealthy",
                "message": "No crypto_ai_bot metrics found",
                "metrics_url": metrics_url,
                "timestamp": int(time.time())
            }
            print(json.dumps(result, indent=2))
            return EXIT_UNHEALTHY

        # Count metric types
        metric_names = set()
        for line in crypto_metrics:
            if "{" in line:
                metric_name = line.split("{")[0]
            else:
                metric_name = line.split()[0]
            metric_names.add(metric_name)

        result = {
            "status": "healthy",
            "message": "Prometheus exporter OK",
            "metrics_url": metrics_url,
            "metric_count": len(crypto_metrics),
            "unique_metrics": len(metric_names),
            "latency_ms": round(latency_ms, 2),
            "sample_metrics": list(metric_names)[:5],
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_HEALTHY

    except urllib.error.HTTPError as e:
        result = {
            "status": "unhealthy",
            "message": f"Exporter HTTP error: {e.code} {e.reason}",
            "metrics_url": metrics_url,
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_UNHEALTHY

    except urllib.error.URLError as e:
        result = {
            "status": "unhealthy",
            "message": f"Exporter connection failed: {e.reason}",
            "metrics_url": metrics_url,
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_UNHEALTHY

    except Exception as e:
        result = {
            "status": "error",
            "message": f"Exporter error: {e}",
            "metrics_url": metrics_url,
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2))
        return EXIT_UNHEALTHY


# --- Main ---

def main() -> int:
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Crypto AI Bot Health Check Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/health.py redis
  python scripts/health.py kraken --live
  python scripts/health.py exporter
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Health check command")

    # Redis subcommand
    redis_parser = subparsers.add_parser("redis", help="Check Redis connection")

    # Kraken subcommand
    kraken_parser = subparsers.add_parser("kraken", help="Check Kraken API status")
    kraken_parser.add_argument(
        "--live",
        action="store_true",
        help="Enable network call (default: no network)"
    )

    # Exporter subcommand
    exporter_parser = subparsers.add_parser("exporter", help="Check Prometheus exporter")

    args = parser.parse_args()

    # Dispatch to appropriate check
    try:
        if args.command == "redis":
            return check_redis()
        elif args.command == "kraken":
            return check_kraken(args.live)
        elif args.command == "exporter":
            return check_exporter()
        else:
            parser.print_help()
            return EXIT_UNHEALTHY

    except KeyboardInterrupt:
        result = {
            "status": "interrupted",
            "message": "Health check interrupted by user",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2), file=sys.stderr)
        return EXIT_UNHEALTHY

    except Exception as e:
        result = {
            "status": "error",
            "message": f"Unexpected error: {e}",
            "timestamp": int(time.time())
        }
        print(json.dumps(result, indent=2), file=sys.stderr)
        return EXIT_UNHEALTHY


if __name__ == "__main__":
    raise SystemExit(main())
