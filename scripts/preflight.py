#!/usr/bin/env python3
"""
Crypto AI Bot - Production Preflight Check

⚠️ SAFETY WARNING:
This script validates environment configuration before trading operations.
Never bypass preflight checks in production. Live trading requires:
- Python 3.10.18 exactly
- Valid Redis Cloud TLS connection
- Kraken API credentials (live mode only)
- Proper environment templates without secrets committed

Exit codes:
  0 = READY (all critical checks passed)
  1 = NOT_READY (critical failures)
  2 = DEGRADED (warnings but operational)

Usage examples:
  python scripts/preflight.py --mode dev
  python scripts/preflight.py --mode staging --strict
  python scripts/preflight.py --mode prod --strict
"""

from __future__ import annotations

import argparse
import os
import platform
import socket
import stat
import sys
import time
import urllib.parse
from pathlib import Path
from typing import List, Tuple

# --- Constants ---
READY = 0
DEGRADED = 2
NOT_READY = 1

REQUIRED_PYTHON_VERSION = "3.10.18"
REQUIRED_ENV_TEMPLATES = [".env.example", ".env.staging.example", ".env.prod.example"]
FORBIDDEN_ENV_FILES = [".env", ".env.local", ".env.staging", ".env.prod"]
REQUIRED_PORTS = [9308]  # Prometheus exporter

# Environment variables required for all modes
BASE_ENV_VARS = ["ENVIRONMENT", "REDIS_URL", "LOG_LEVEL"]
# Additional variables required for live mode
LIVE_ENV_VARS = ["KRAKEN_API_KEY", "KRAKEN_API_SECRET", "LIVE_TRADING_CONFIRMATION"]

# --- Helper Functions ---

def check_python_version() -> Tuple[bool, str]:
    """Check Python version matches exactly 3.10.18"""
    current_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    if current_version == REQUIRED_PYTHON_VERSION:
        return True, f"Python {current_version}"
    else:
        return False, f"Python {current_version} (expected {REQUIRED_PYTHON_VERSION})"


def check_env_templates() -> Tuple[bool, str]:
    """Check that environment templates exist"""
    root = Path.cwd()
    missing = []

    for template in REQUIRED_ENV_TEMPLATES:
        if not (root / template).exists():
            missing.append(template)

    if missing:
        return False, f"Missing templates: {', '.join(missing)}"
    return True, f"All {len(REQUIRED_ENV_TEMPLATES)} env templates present"


def check_no_real_env() -> Tuple[bool, str]:
    """Verify NO real .env files exist (only examples allowed)"""
    root = Path.cwd()
    found = []

    for env_file in FORBIDDEN_ENV_FILES:
        if (root / env_file).exists():
            found.append(env_file)

    if found:
        return False, f"Found real env files (use examples only): {', '.join(found)}"
    return True, "No real .env files (examples only)"


def check_redis_url_format() -> Tuple[bool, str]:
    """Verify Redis URL format if set"""
    redis_url = os.getenv("REDIS_URL")

    if not redis_url:
        return True, "REDIS_URL not set (will skip connection check)"

    try:
        parsed = urllib.parse.urlparse(redis_url)

        if parsed.scheme not in ["redis", "rediss"]:
            return False, f"Invalid Redis URL scheme: {parsed.scheme} (expected redis:// or rediss://)"

        if not parsed.hostname:
            return False, "Redis URL missing hostname"

        if parsed.scheme == "rediss":
            return True, f"Redis TLS URL: {parsed.hostname}:{parsed.port or 6380}"
        else:
            return True, f"Redis URL: {parsed.hostname}:{parsed.port or 6379}"

    except Exception as e:
        return False, f"Invalid Redis URL format: {e}"


def check_kraken_keys(mode: str) -> Tuple[bool, str]:
    """Verify Kraken keys present ONLY in live mode"""
    kraken_key = os.getenv("KRAKEN_API_KEY")
    kraken_secret = os.getenv("KRAKEN_API_SECRET")

    if mode == "prod":
        # Live mode: require credentials
        if not kraken_key or not kraken_secret:
            return False, "KRAKEN_API_KEY and KRAKEN_API_SECRET required for live mode"

        # Check key format (basic sanity)
        if len(kraken_key) < 20 or len(kraken_secret) < 20:
            return False, "Kraken credentials appear invalid (too short)"

        return True, f"Kraken credentials present (key len={len(kraken_key)})"
    else:
        # Dev/staging: credentials optional but warn if present
        if kraken_key or kraken_secret:
            return True, "Warning: Kraken credentials set in non-live mode"

        return True, "No Kraken credentials (not required for dev/staging)"


def check_ports_free() -> Tuple[bool, str]:
    """Check required ports are free"""
    blocked = []

    for port in REQUIRED_PORTS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex(("127.0.0.1", port))

                if result == 0:
                    # Port is in use
                    blocked.append(port)
        except Exception:
            # Assume port is free if check fails
            pass

    if blocked:
        return False, f"Ports blocked: {', '.join(map(str, blocked))}"

    return True, f"All {len(REQUIRED_PORTS)} required ports free"


def check_file_permissions() -> Tuple[bool, str]:
    """Check file permissions sanity on Windows"""
    if platform.system() != "Windows":
        return True, "File permissions check skipped (non-Windows)"

    # On Windows, just check we can write to logs directory
    logs_dir = Path.cwd() / "logs"

    try:
        logs_dir.mkdir(exist_ok=True)

        # Test write
        test_file = logs_dir / ".preflight_test"
        test_file.write_text("test")
        test_file.unlink()

        return True, "Logs directory writable"

    except Exception as e:
        return False, f"Cannot write to logs directory: {e}"


def check_conda_environment() -> Tuple[bool, str]:
    """Check conda environment"""
    conda_env = os.environ.get("CONDA_DEFAULT_ENV")

    if not conda_env:
        return True, "No conda environment (not required)"

    if conda_env == "crypto-bot":
        return True, f"Conda environment: {conda_env}"
    else:
        return True, f"Warning: Conda environment is '{conda_env}' (expected 'crypto-bot')"


def check_env_variables(mode: str) -> Tuple[bool, str]:
    """Check required environment variables"""
    missing = []

    # Check base variables
    for var in BASE_ENV_VARS:
        if not os.getenv(var):
            missing.append(var)

    # Check live mode variables
    if mode == "prod":
        for var in LIVE_ENV_VARS:
            if not os.getenv(var):
                missing.append(var)

    if missing:
        return False, f"Missing environment variables: {', '.join(missing)}"

    return True, f"All required environment variables present"


# --- Main Execution ---

def run_preflight_checks(mode: str, strict: bool) -> int:
    """
    Run preflight checks for specified mode.

    Args:
        mode: Deployment mode (dev, staging, prod)
        strict: If True, treat warnings as failures

    Returns:
        Exit code (0=READY, 1=NOT_READY, 2=DEGRADED)
    """
    start_time = time.time()

    print(f"# Crypto AI Bot - Preflight Check")
    print(f"Mode: {mode}")
    print(f"Strict: {strict}")
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version}")
    print()

    failures = []
    warnings = []

    # Check 1: Python version
    print("## Python Version")
    ok, msg = check_python_version()
    print(f"- {msg}")
    if not ok:
        failures.append(msg)
    print()

    # Check 2: Environment templates
    print("## Environment Templates")
    ok, msg = check_env_templates()
    print(f"- {msg}")
    if not ok:
        failures.append(msg)
    print()

    # Check 3: No real .env files
    print("## Environment Files")
    ok, msg = check_no_real_env()
    print(f"- {msg}")
    if not ok:
        warnings.append(msg)
    print()

    # Check 4: Redis URL format
    print("## Redis Configuration")
    ok, msg = check_redis_url_format()
    print(f"- {msg}")
    if not ok:
        failures.append(msg)
    print()

    # Check 5: Kraken keys
    print("## Kraken API Credentials")
    ok, msg = check_kraken_keys(mode)
    print(f"- {msg}")
    if not ok:
        failures.append(msg)
    elif "Warning" in msg:
        warnings.append(msg)
    print()

    # Check 6: Required ports
    print("## Required Ports")
    ok, msg = check_ports_free()
    print(f"- {msg}")
    if not ok:
        warnings.append(msg)
    print()

    # Check 7: File permissions
    print("## File Permissions")
    ok, msg = check_file_permissions()
    print(f"- {msg}")
    if not ok:
        failures.append(msg)
    print()

    # Check 8: Conda environment
    print("## Conda Environment")
    ok, msg = check_conda_environment()
    print(f"- {msg}")
    if "Warning" in msg:
        warnings.append(msg)
    print()

    # Check 9: Environment variables
    print("## Environment Variables")
    ok, msg = check_env_variables(mode)
    print(f"- {msg}")
    if not ok:
        failures.append(msg)
    print()

    # Summary
    elapsed = time.time() - start_time
    print("## Summary")
    print(f"- Checks completed in {elapsed:.2f}s")
    print(f"- Failures: {len(failures)}")
    print(f"- Warnings: {len(warnings)}")
    print()

    # Determine exit code
    if failures:
        print("**Status: NOT READY**")
        print()
        print("### Failures")
        for i, failure in enumerate(failures, 1):
            print(f"{i}. {failure}")
        return NOT_READY

    if warnings:
        if strict:
            print("**Status: NOT READY (strict mode)**")
            print()
            print("### Warnings Treated as Failures")
            for i, warning in enumerate(warnings, 1):
                print(f"{i}. {warning}")
            return NOT_READY
        else:
            print("**Status: DEGRADED**")
            print()
            print("### Warnings")
            for i, warning in enumerate(warnings, 1):
                print(f"{i}. {warning}")
            return DEGRADED

    print("**Status: READY**")
    return READY


def main() -> int:
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Crypto AI Bot Production Preflight Check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/preflight.py --mode dev
  python scripts/preflight.py --mode staging --strict
  python scripts/preflight.py --mode prod --strict
        """
    )

    parser.add_argument(
        "--mode",
        choices=["dev", "staging", "prod"],
        default="dev",
        help="Deployment mode (default: dev)"
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures"
    )

    args = parser.parse_args()

    try:
        return run_preflight_checks(args.mode, args.strict)
    except KeyboardInterrupt:
        print("\n[Preflight] Interrupted by user")
        return NOT_READY
    except Exception as e:
        print(f"\n[Preflight] Unexpected error: {e}")
        return NOT_READY


if __name__ == "__main__":
    raise SystemExit(main())
