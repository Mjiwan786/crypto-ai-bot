#!/usr/bin/env python3
"""
Preflight Check - Verify Live Trading Configuration
====================================================

Checks all critical settings before going live.
Run this BEFORE starting live trading.

Usage:
    python scripts/preflight_check.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env file if it exists
env_file = project_root / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
        print(f"[Loaded .env from {env_file}]")
    except ImportError:
        # Manual load if python-dotenv not available
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ[key.strip()] = value.strip()
        print(f"[Loaded .env from {env_file}]")


def check_env_var(name: str, expected: str = None, required: bool = True) -> tuple:
    """Check an environment variable."""
    value = os.getenv(name, "")

    if required and not value:
        return False, f"NOT SET (required)"

    if expected and value.lower() != expected.lower():
        return False, f"'{value}' (expected: '{expected}')"

    # Mask sensitive values
    if "KEY" in name or "SECRET" in name or "PASSWORD" in name:
        masked = value[:4] + "****" + value[-4:] if len(value) > 8 else "****"
        return True, masked

    return True, value


def main():
    print("\n" + "=" * 70)
    print("LIVE TRADING PREFLIGHT CHECK")
    print("=" * 70)

    checks = []

    # Critical mode settings
    print("\n[1] MODE CONFIGURATION")
    print("-" * 40)

    checks.append(("LIVE_TRADING_ENABLED", *check_env_var("LIVE_TRADING_ENABLED", "true")))
    checks.append(("MODE", *check_env_var("MODE", "live")))
    checks.append(("LIVE_TRADING_CONFIRMATION", *check_env_var("LIVE_TRADING_CONFIRMATION", "I-accept-the-risk")))
    checks.append(("SHADOW_EXECUTION", *check_env_var("SHADOW_EXECUTION", "false", required=False)))
    checks.append(("EMERGENCY_STOP", *check_env_var("EMERGENCY_STOP", "false")))

    for name, ok, value in checks[-5:]:
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {status} {name}: {value}")

    # API Credentials
    print("\n[2] API CREDENTIALS")
    print("-" * 40)

    checks.append(("KRAKEN_API_KEY", *check_env_var("KRAKEN_API_KEY")))
    checks.append(("KRAKEN_API_SECRET", *check_env_var("KRAKEN_API_SECRET")))

    for name, ok, value in checks[-2:]:
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {status} {name}: {value}")

    # Risk limits
    print("\n[3] RISK LIMITS")
    print("-" * 40)

    capital = os.getenv("TRADING_CAPITAL_USD", "100")
    max_pos = os.getenv("MAX_POSITION_SIZE_USD", "25")
    max_loss = os.getenv("MAX_DAILY_LOSS_USD", "2")
    max_trades = os.getenv("MAX_TRADES_PER_DAY", "8")

    print(f"  TRADING_CAPITAL_USD: ${capital}")
    print(f"  MAX_POSITION_SIZE_USD: ${max_pos}")
    print(f"  MAX_DAILY_LOSS_USD: ${max_loss}")
    print(f"  MAX_TRADES_PER_DAY: {max_trades}")

    # Summary
    print("\n" + "=" * 70)

    failed = [c for c in checks if not c[1]]

    if failed:
        print("PREFLIGHT FAILED - Fix the following:")
        print("-" * 40)
        for name, _, value in failed:
            print(f"  - {name}: {value}")
        print("\n[!] DO NOT GO LIVE until all checks pass")
        print("=" * 70)
        return 1
    else:
        print("PREFLIGHT PASSED - All checks OK")
        print("-" * 40)
        print(f"  Capital: ${capital}")
        print(f"  Max Position: ${max_pos}")
        print(f"  Max Daily Loss: ${max_loss}")
        print(f"  Max Trades/Day: {max_trades}")
        print("\n[OK] System ready for LIVE TRADING")
        print("=" * 70)
        return 0


if __name__ == "__main__":
    sys.exit(main())
