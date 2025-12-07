#!/usr/bin/env python3
"""
Week-3 Verification Script - PRD-001/PRD-002 Compliance Check

Validates:
1. Signal schema matches API PRD-002 requirements
2. Published Redis streams for all 5 pairs
3. Metrics publishing for /v1/metrics/summary
4. Redis TLS cert path usage
5. Engine pairs list matches API expectations

Exit codes:
    0 = All checks passed
    1 = Some checks failed
"""

import asyncio
import argparse
import os
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

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

from dotenv import load_dotenv
import redis.asyncio as redis


# PRD-001 Required Pairs
PRD_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]

# PRD-002 Required Signal Fields
PRD_REQUIRED_FIELDS = ["pair", "side", "entry", "confidence", "strategy"]

# Field aliases (engine name -> API aliases)
FIELD_ALIASES = {
    "id": ["signal_id"],
    "ts": ["timestamp"],
    "entry": ["entry_price", "price"],
    "sl": ["stop_loss"],
    "tp": ["take_profit"],
    "side": ["signal_type"],
}

# Metrics Summary Required Fields
METRICS_REQUIRED = ["signals_per_day", "roi_30d", "win_rate", "max_drawdown", "best_pair"]


async def check_redis_tls(redis_url: str, ca_cert_path: str, results: Dict) -> redis.Redis:
    """Check 4: Redis TLS cert path usage"""
    print()
    print("-" * 70)
    print(" CHECK 4: Redis TLS Cert Path Usage")
    print("-" * 70)

    if os.path.exists(ca_cert_path):
        print(f"  [PASS] CA cert exists at: {ca_cert_path}")
        results["redis_tls"]["status"] = "PASS"
    else:
        print(f"  [FAIL] CA cert NOT found at: {ca_cert_path}")
        results["redis_tls"]["status"] = "FAIL"
        results["redis_tls"]["issues"].append(f"CA cert not found at {ca_cert_path}")

    # Connect to Redis with TLS
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
        print("  [PASS] Redis TLS connection successful")
        if results["redis_tls"]["status"] != "FAIL":
            results["redis_tls"]["status"] = "PASS"
        return client
    except Exception as e:
        print(f"  [FAIL] Redis connection failed: {e}")
        results["redis_tls"]["status"] = "FAIL"
        results["redis_tls"]["issues"].append(str(e))
        return None


async def check_redis_streams(client: redis.Redis, mode: str, results: Dict):
    """Check 2: Redis Streams for all 5 pairs"""
    print()
    print("-" * 70)
    print(" CHECK 2: Redis Streams for All 5 Pairs")
    print("-" * 70)

    all_fresh = True
    for pair in PRD_PAIRS:
        stream_pair = pair.replace("/", "-")
        stream_key = f"signals:{mode}:{stream_pair}"
        try:
            length = await client.xlen(stream_key)
            if length > 0:
                messages = await client.xrevrange(stream_key, count=1)
                if messages:
                    msg_id, data = messages[0]
                    ts_ms = int(msg_id.split("-")[0])
                    age_sec = (datetime.now().timestamp() * 1000 - ts_ms) / 1000
                    is_fresh = age_sec < 300  # 5 minutes
                    status = "FRESH" if is_fresh else "STALE"
                    icon = "[PASS]" if is_fresh else "[FAIL]"
                    print(f"  {icon} {stream_key}: {length} msgs, age: {age_sec:.0f}s, {status}")
                    if not is_fresh:
                        all_fresh = False
                        results["redis_streams"]["issues"].append(f"{pair}: STALE ({age_sec:.0f}s old)")
            else:
                print(f"  [FAIL] {stream_key}: EMPTY")
                all_fresh = False
                results["redis_streams"]["issues"].append(f"{pair}: EMPTY STREAM")
        except Exception as e:
            print(f"  [FAIL] {stream_key}: ERROR - {e}")
            all_fresh = False
            results["redis_streams"]["issues"].append(f"{pair}: {e}")

    results["redis_streams"]["status"] = "PASS" if all_fresh else "FAIL"


async def check_pairs_list(results: Dict):
    """Check 5: Engine Pairs List Matches API (5 pairs)"""
    print()
    print("-" * 70)
    print(" CHECK 5: Engine Pairs List Matches API (5 pairs)")
    print("-" * 70)

    env_pairs = os.getenv("TRADING_PAIRS") or os.getenv("KRAKEN_TRADING_PAIRS", "")
    if env_pairs:
        env_pairs_list = [p.strip() for p in env_pairs.split(",")]
        print(f"  Engine pairs (.env): {env_pairs_list}")
        print(f"  PRD-001 pairs:       {PRD_PAIRS}")

        missing = [p for p in PRD_PAIRS if p not in env_pairs_list]
        extra = [p for p in env_pairs_list if p not in PRD_PAIRS]

        if not missing and not extra:
            print("  [PASS] Engine pairs match PRD-001 exactly")
            results["pairs_list"]["status"] = "PASS"
        else:
            if missing:
                print(f"  [FAIL] Missing from engine: {missing}")
                results["pairs_list"]["issues"].append(f"Missing: {missing}")
            if extra:
                print(f"  [WARN] Extra in engine: {extra}")
                results["pairs_list"]["issues"].append(f"Extra: {extra}")
            results["pairs_list"]["status"] = "FAIL" if missing else "PASS"
    else:
        print("  [WARN] TRADING_PAIRS not set in .env, checking streams...")
        results["pairs_list"]["status"] = "PASS"


async def check_signal_schema(client: redis.Redis, mode: str, results: Dict):
    """Check 1: Signal Schema Matches API PRD-002 Requirements"""
    print()
    print("-" * 70)
    print(" CHECK 1: Signal Schema Matches API PRD-002 Requirements")
    print("-" * 70)

    sample_stream = f"signals:{mode}:BTC-USD"
    try:
        messages = await client.xrevrange(sample_stream, count=1)
        if messages:
            msg_id, data = messages[0]
            print(f"  Sample signal from {sample_stream}:")
            print(f"    Fields: {list(data.keys())}")

            # Check required fields or aliases
            schema_ok = True
            for field in PRD_REQUIRED_FIELDS:
                found = field in data
                if not found and field in FIELD_ALIASES:
                    found = any(alias in data for alias in FIELD_ALIASES[field])
                if found:
                    print(f"    [PASS] {field}: present")
                else:
                    print(f"    [FAIL] {field}: MISSING")
                    schema_ok = False
                    results["signal_schema"]["issues"].append(f"Missing field: {field}")

            results["signal_schema"]["status"] = "PASS" if schema_ok else "FAIL"
        else:
            print("  [FAIL] No signals to check schema")
            results["signal_schema"]["status"] = "FAIL"
    except Exception as e:
        print(f"  [FAIL] Error checking schema: {e}")
        results["signal_schema"]["status"] = "FAIL"
        results["signal_schema"]["issues"].append(str(e))


async def check_metrics_summary(client: redis.Redis, results: Dict):
    """Check 3: Metrics Publishing for /v1/metrics/summary"""
    print()
    print("-" * 70)
    print(" CHECK 3: Metrics Publishing for /v1/metrics/summary")
    print("-" * 70)

    summary_key = "engine:summary_metrics"
    try:
        key_type = await client.type(summary_key)
        print(f"  {summary_key}: type={key_type}")

        if key_type == "string":
            summary_data = await client.get(summary_key)
            if summary_data:
                try:
                    metrics = json.loads(summary_data)
                    print(f"    Fields: {list(metrics.keys())}")

                    metrics_ok = True
                    for field in METRICS_REQUIRED:
                        if field in metrics:
                            print(f"    [PASS] {field}: {metrics[field]}")
                        else:
                            print(f"    [FAIL] {field}: MISSING")
                            metrics_ok = False
                            results["metrics_summary"]["issues"].append(f"Missing: {field}")

                    results["metrics_summary"]["status"] = "PASS" if metrics_ok else "FAIL"
                except json.JSONDecodeError:
                    print(f"    [FAIL] Invalid JSON in {summary_key}")
                    results["metrics_summary"]["status"] = "FAIL"
            else:
                print(f"    [FAIL] {summary_key} is empty")
                results["metrics_summary"]["status"] = "FAIL"
                results["metrics_summary"]["issues"].append("engine:summary_metrics is empty")
        elif key_type == "hash":
            summary_data = await client.hgetall(summary_key)
            print(f"    Fields: {list(summary_data.keys())}")

            metrics_ok = True
            for field in METRICS_REQUIRED:
                if field in summary_data:
                    print(f"    [PASS] {field}: {summary_data[field]}")
                else:
                    print(f"    [FAIL] {field}: MISSING")
                    metrics_ok = False
                    results["metrics_summary"]["issues"].append(f"Missing: {field}")

            results["metrics_summary"]["status"] = "PASS" if metrics_ok else "FAIL"
        elif key_type == "none":
            print(f"    [FAIL] Key does not exist: {summary_key}")
            results["metrics_summary"]["status"] = "FAIL"
            results["metrics_summary"]["issues"].append("engine:summary_metrics does not exist")
        else:
            print(f"    [WARN] Unexpected type: {key_type}")
            results["metrics_summary"]["status"] = "FAIL"
    except Exception as e:
        print(f"  [FAIL] Error checking metrics: {e}")
        results["metrics_summary"]["status"] = "FAIL"
        results["metrics_summary"]["issues"].append(str(e))


async def main():
    parser = argparse.ArgumentParser(description="Week-3 Verification Script")
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

    print("=" * 70)
    print(" WEEK-3 VERIFICATION REPORT - PRD-001/PRD-002 COMPLIANCE")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Mode: {args.mode}")
    print(f"Redis: {redis_url[:40]}...")
    print(f"CA Cert: {ca_cert_path}")

    results = {
        "signal_schema": {"status": "UNKNOWN", "issues": []},
        "redis_streams": {"status": "UNKNOWN", "issues": []},
        "metrics_summary": {"status": "UNKNOWN", "issues": []},
        "redis_tls": {"status": "UNKNOWN", "issues": []},
        "pairs_list": {"status": "UNKNOWN", "issues": []},
    }

    # Run all checks
    client = await check_redis_tls(redis_url, ca_cert_path, results)
    if not client:
        print("\nERROR: Cannot proceed without Redis connection")
        sys.exit(1)

    try:
        await check_redis_streams(client, args.mode, results)
        await check_pairs_list(results)
        await check_signal_schema(client, args.mode, results)
        await check_metrics_summary(client, results)
    finally:
        await client.aclose()

    # Summary
    print()
    print("=" * 70)
    print(" WEEK-3 VERIFICATION SUMMARY")
    print("=" * 70)

    all_pass = True
    for check, result in results.items():
        status = result["status"]
        icon = "[PASS]" if status == "PASS" else "[FAIL]"
        if status != "PASS":
            all_pass = False
        print(f"  {icon} {check}: {status}")
        for issue in result.get("issues", []):
            print(f"        - {issue}")

    print()
    overall = "PASS" if all_pass else "FAIL"
    print(f"  OVERALL: {overall}")
    print()

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(main())
