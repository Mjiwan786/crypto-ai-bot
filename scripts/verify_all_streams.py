#!/usr/bin/env python3
"""
Stream Verification Script - PRD-001 Compliance Check

Verifies that all 5 trading pairs have fresh signals and PnL is being published.

Usage:
    python scripts/verify_all_streams.py
    python scripts/verify_all_streams.py --env-file .env.paper

Checks:
    1. All 5 PRD-001 pairs have fresh signal streams (< 5 min old)
    2. pnl:paper:equity_curve stream is updating
    3. pnl:paper:performance stream is updating

Exit codes:
    0 = All checks passed
    1 = Some checks failed
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Use ASCII icons for Windows compatibility
ICON_OK = "[OK]"
ICON_FAIL = "[FAIL]"
ICON_WARN = "[WARN]"
ICON_INFO = "[INFO]"

from dotenv import load_dotenv
import redis.asyncio as redis


# PRD-001 Required Pairs
PRD_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]

# Freshness thresholds
SIGNAL_MAX_AGE_SEC = 300  # 5 minutes
PNL_MAX_AGE_SEC = 120  # 2 minutes


async def check_signal_streams(
    client: redis.Redis,
    mode: str = "paper",
) -> Tuple[bool, Dict[str, Dict]]:
    """
    Check all 5 PRD-001 signal streams for freshness.

    Returns:
        (all_fresh, results_dict)
    """
    results = {}
    all_fresh = True

    print(f"\n{'='*60}")
    print(f" SIGNAL STREAMS CHECK (mode={mode})")
    print(f"{'='*60}")

    for pair in PRD_PAIRS:
        stream_pair = pair.replace("/", "-")
        stream_key = f"signals:{mode}:{stream_pair}"

        try:
            length = await client.xlen(stream_key)

            if length > 0:
                messages = await client.xrevrange(stream_key, count=1)
                if messages:
                    msg_id, data = messages[0]
                    ts_ms = int(msg_id.split('-')[0])
                    dt = datetime.fromtimestamp(ts_ms / 1000)
                    age_sec = (datetime.now().timestamp() * 1000 - ts_ms) / 1000

                    is_fresh = age_sec < SIGNAL_MAX_AGE_SEC
                    status = "FRESH" if is_fresh else "STALE"
                    icon = ICON_OK if is_fresh else ICON_FAIL

                    if not is_fresh:
                        all_fresh = False

                    results[pair] = {
                        "stream": stream_key,
                        "length": length,
                        "last_update": dt.isoformat(),
                        "age_sec": round(age_sec, 1),
                        "status": status,
                    }

                    print(f"  {icon} {pair:12s} | {length:6d} msgs | age: {age_sec:6.1f}s | {status}")
            else:
                all_fresh = False
                results[pair] = {
                    "stream": stream_key,
                    "length": 0,
                    "status": "EMPTY",
                }
                print(f"  {ICON_FAIL} {pair:12s} | EMPTY STREAM")

        except Exception as e:
            all_fresh = False
            results[pair] = {
                "stream": stream_key,
                "status": "ERROR",
                "error": str(e),
            }
            print(f"  {ICON_FAIL} {pair:12s} | ERROR: {e}")

    return all_fresh, results


async def check_pnl_streams(
    client: redis.Redis,
    mode: str = "paper",
) -> Tuple[bool, Dict[str, Dict]]:
    """
    Check PnL streams for freshness.

    Returns:
        (all_fresh, results_dict)
    """
    results = {}
    all_fresh = True

    print(f"\n{'='*60}")
    print(f" PNL STREAMS CHECK (mode={mode})")
    print(f"{'='*60}")

    pnl_streams = [
        f"pnl:{mode}:equity_curve",
        f"pnl:{mode}:performance",
    ]

    for stream_key in pnl_streams:
        try:
            key_type = await client.type(stream_key)

            if key_type == "stream":
                length = await client.xlen(stream_key)

                if length > 0:
                    messages = await client.xrevrange(stream_key, count=1)
                    if messages:
                        msg_id, data = messages[0]
                        ts_ms = int(msg_id.split('-')[0])
                        dt = datetime.fromtimestamp(ts_ms / 1000)
                        age_sec = (datetime.now().timestamp() * 1000 - ts_ms) / 1000

                        is_fresh = age_sec < PNL_MAX_AGE_SEC
                        status = "FRESH" if is_fresh else "STALE"
                        icon = ICON_OK if is_fresh else ICON_FAIL

                        if not is_fresh:
                            all_fresh = False

                        results[stream_key] = {
                            "length": length,
                            "last_update": dt.isoformat(),
                            "age_sec": round(age_sec, 1),
                            "status": status,
                        }

                        print(f"  {icon} {stream_key:30s} | {length:6d} msgs | age: {age_sec:6.1f}s | {status}")
                else:
                    all_fresh = False
                    results[stream_key] = {"length": 0, "status": "EMPTY"}
                    print(f"  {ICON_FAIL} {stream_key:30s} | EMPTY")
            else:
                all_fresh = False
                results[stream_key] = {"status": f"NOT_A_STREAM (type={key_type})"}
                print(f"  {ICON_WARN}  {stream_key:30s} | NOT A STREAM (type={key_type})")

        except Exception as e:
            all_fresh = False
            results[stream_key] = {"status": "ERROR", "error": str(e)}
            print(f"  {ICON_FAIL} {stream_key:30s} | ERROR: {e}")

    return all_fresh, results


async def check_pnl_latest_endpoint_keys(
    client: redis.Redis,
    mode: str = "paper",
) -> Tuple[bool, Dict[str, Dict]]:
    """
    Check keys that /v1/pnl/latest/paper API endpoint reads.
    """
    results = {}
    all_ok = True

    print(f"\n{'='*60}")
    print(f" PNL LATEST KEYS CHECK (for API /v1/pnl/latest/{mode})")
    print(f"{'='*60}")

    # Keys the API might read
    latest_keys = [
        f"pnl:{mode}:summary",
        f"pnl:{mode}:performance:latest",
        f"bot:performance:current",
    ]

    for key in latest_keys:
        try:
            key_type = await client.type(key)

            if key_type == "none":
                results[key] = {"status": "NOT_EXISTS"}
                print(f"  {ICON_WARN}  {key:35s} | NOT EXISTS")
            elif key_type == "string":
                value = await client.get(key)
                if value:
                    results[key] = {"status": "OK", "type": "string", "has_value": True}
                    print(f"  {ICON_OK} {key:35s} | STRING with value")
                else:
                    results[key] = {"status": "EMPTY", "type": "string"}
                    print(f"  {ICON_WARN}  {key:35s} | STRING but empty")
            else:
                results[key] = {"status": "OK", "type": key_type}
                print(f"  {ICON_INFO}  {key:35s} | type={key_type}")

        except Exception as e:
            all_ok = False
            results[key] = {"status": "ERROR", "error": str(e)}
            print(f"  {ICON_FAIL} {key:35s} | ERROR: {e}")

    return all_ok, results


async def main():
    parser = argparse.ArgumentParser(description="Verify all streams for PRD-001 compliance")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=project_root / ".env.paper",
        help="Environment file (default: .env.paper)",
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode (default: paper)",
    )
    args = parser.parse_args()

    # Load environment
    if args.env_file.exists():
        load_dotenv(args.env_file)
        print(f"Loaded environment from {args.env_file}")

    # Get Redis connection
    redis_url = os.getenv("REDIS_URL", "")
    ca_cert_path = os.getenv("REDIS_CA_CERT") or os.getenv(
        "REDIS_SSL_CA_CERT",
        str(project_root / "config" / "certs" / "redis_ca.pem")
    )

    if not redis_url:
        print("ERROR: REDIS_URL not set")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f" STREAM VERIFICATION - PRD-001 COMPLIANCE")
    print(f"{'='*60}")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Mode: {args.mode}")
    print(f"Redis: {redis_url[:40]}...")

    # Connect to Redis
    try:
        conn_params = {
            "socket_connect_timeout": 10,
            "decode_responses": True,
        }

        if redis_url.startswith("rediss://") and os.path.exists(ca_cert_path):
            conn_params["ssl_ca_certs"] = ca_cert_path
            conn_params["ssl_cert_reqs"] = "required"

        client = redis.from_url(redis_url, **conn_params)
        await client.ping()
        print(f"{ICON_OK} Redis connected")

    except Exception as e:
        print(f"{ICON_FAIL} Redis connection failed: {e}")
        sys.exit(1)

    # Run checks
    try:
        signals_ok, signals_results = await check_signal_streams(client, args.mode)
        pnl_ok, pnl_results = await check_pnl_streams(client, args.mode)
        latest_ok, latest_results = await check_pnl_latest_endpoint_keys(client, args.mode)

        # Summary
        print(f"\n{'='*60}")
        print(f" SUMMARY")
        print(f"{'='*60}")

        all_ok = signals_ok and pnl_ok

        if all_ok:
            print(f"  {ICON_OK} ALL CHECKS PASSED")
            print(f"     - All 5 PRD-001 pairs have fresh signals")
            print(f"     - PnL streams are updating")
            exit_code = 0
        else:
            print(f"  {ICON_FAIL} SOME CHECKS FAILED")
            if not signals_ok:
                stale_pairs = [p for p, r in signals_results.items() if r.get("status") != "FRESH"]
                print(f"     - Stale/missing signal pairs: {stale_pairs}")
            if not pnl_ok:
                print(f"     - PnL streams not updating properly")
            exit_code = 1

        print()

    finally:
        await client.aclose()

    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
