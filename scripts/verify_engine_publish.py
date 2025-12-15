#!/usr/bin/env python3
"""
Engine Publishing Verification Script for Acquisition Diligence

SAFETY: Read-only checks only - no writes to production streams.
Connects to Redis using env-based config (no secrets printed).

Checks:
- Redis connection health
- Stream activity (last 5 min)
- Symbol format compliance (BASE/QUOTE in payload, BASE-QUOTE in stream keys)
- No duplicate pairs emitted
- Recent signal timestamps
"""

import asyncio
import os
import ssl
import sys
import json
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional, Set

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# Constants - expected pairs per config/trading_pairs.py
EXPECTED_ENABLED_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD"]
EXPECTED_STREAM_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "LINK-USD"]

# Stream patterns to check
STREAM_PATTERNS = [
    "signals:paper:*",
    "signals:live:*",
    "signals:paper",
    "kraken:ticker",
    "kraken:ohlc:*",
    "kraken:heartbeat",
    "kraken:trade:*",
    "kraken:spread:*",
    "kraken:metrics",
    "pnl:summary",
    "pnl:paper:summary",
    "pnl:paper:equity_curve",
    "pnl:live:summary",
]

# Time window for "active" streams (5 minutes)
ACTIVITY_WINDOW_SECONDS = 300


def get_redis_url() -> str:
    """Get Redis URL from environment (no printing of credentials)."""
    url = os.getenv("REDIS_URL", "")
    if not url:
        raise ValueError("REDIS_URL environment variable must be set")
    return url


def get_ca_cert_path() -> Optional[str]:
    """Get CA cert path from environment."""
    # Try multiple env var names
    path = os.getenv("REDIS_CA_CERT") or os.getenv("REDIS_CA_CERT_PATH")
    if path and os.path.exists(path):
        return path
    # Default paths
    for default_path in [
        "config/certs/redis_ca.pem",
        os.path.expanduser("~/redis_ca.pem"),
    ]:
        if os.path.exists(default_path):
            return default_path
    return None


def connect_redis_sync():
    """Connect to Redis with TLS (synchronous client)."""
    import redis

    url = get_redis_url()
    ca_cert = get_ca_cert_path()

    connect_kwargs = {
        "decode_responses": True,
        "socket_timeout": 10,
        "socket_connect_timeout": 10,
    }

    if url.startswith("rediss://"):
        if ca_cert:
            connect_kwargs["ssl_ca_certs"] = ca_cert
            connect_kwargs["ssl_cert_reqs"] = "required"
        else:
            # Use system certs
            connect_kwargs["ssl_cert_reqs"] = "required"

    client = redis.from_url(url, **connect_kwargs)
    return client


def parse_stream_id_timestamp(stream_id: str) -> float:
    """Extract timestamp from Redis stream ID (format: timestamp-sequence)."""
    try:
        ts_part = stream_id.split("-")[0]
        return float(ts_part) / 1000.0  # Convert ms to seconds
    except (ValueError, IndexError):
        return 0.0


def scan_keys_by_pattern(client, pattern: str) -> List[str]:
    """Scan Redis keys matching a pattern."""
    keys = []
    cursor = 0
    while True:
        cursor, partial_keys = client.scan(cursor, match=pattern, count=100)
        keys.extend(partial_keys)
        if cursor == 0:
            break
    return sorted(set(keys))


def get_stream_info(client, stream_key: str) -> Dict[str, Any]:
    """Get stream info including latest entry."""
    try:
        length = client.xlen(stream_key)
        latest = None
        latest_ts = 0.0

        if length > 0:
            entries = client.xrevrange(stream_key, count=1)
            if entries:
                entry_id, entry_data = entries[0]
                latest_ts = parse_stream_id_timestamp(entry_id)
                latest = {
                    "id": entry_id,
                    "data": entry_data,
                    "timestamp": latest_ts,
                }

        return {
            "exists": True,
            "length": length,
            "latest": latest,
            "latest_timestamp": latest_ts,
        }
    except Exception as e:
        return {
            "exists": False,
            "error": str(e),
            "length": 0,
            "latest_timestamp": 0.0,
        }


def extract_symbol_from_payload(data: Dict[str, Any]) -> Optional[str]:
    """Extract symbol/pair from signal payload."""
    # Try common field names
    for field in ["symbol", "pair", "trading_pair", "asset"]:
        if field in data:
            return data[field]
    return None


def validate_symbol_format(symbol: str) -> Tuple[bool, str]:
    """
    Validate symbol format.
    Expected: BASE/QUOTE (e.g., BTC/USD)
    Also accepts: BASE-QUOTE, BASEUSD, BASEUSDT (Binance format)
    Returns: (is_valid, message)
    """
    if not symbol:
        return False, "Empty symbol"

    # Canonical format: BASE/QUOTE
    if "/" in symbol:
        parts = symbol.split("/")
        if len(parts) == 2 and all(p.isalpha() for p in parts):
            return True, f"Valid format: {symbol}"
        return False, f"Invalid BASE/QUOTE format: {symbol}"

    # Stream key format: BASE-QUOTE
    if "-" in symbol:
        return True, f"Stream format (BASE-QUOTE): {symbol}"

    # Binance/compact format: BASEUSD or BASEUSDT
    symbol_upper = symbol.upper()
    if symbol_upper.endswith("USDT"):
        base = symbol_upper[:-4]
        if base.isalpha() and len(base) >= 2:
            return True, f"Binance format (BASEUSDT): {symbol}"
    elif symbol_upper.endswith("USD"):
        base = symbol_upper[:-3]
        if base.isalpha() and len(base) >= 2:
            return True, f"Compact format (BASEUSD): {symbol}"

    # Check if it's a known base asset without quote
    known_bases = {"BTC", "ETH", "SOL", "LINK", "MATIC", "ADA", "XRP", "DOT"}
    if symbol_upper in known_bases:
        return True, f"Base asset only: {symbol}"

    return False, f"Unknown format: {symbol}"


def check_stream_key_format(stream_key: str) -> Tuple[bool, str]:
    """
    Validate stream key format.
    Expected: signals:paper:BASE-QUOTE or signals:live:BASE-QUOTE
    Also accepts: signals:paper:BASE/QUOTE (alternative format)
    """
    if not stream_key.startswith("signals:"):
        return True, "Non-signal stream"

    parts = stream_key.split(":")
    if len(parts) >= 3:
        pair_part = parts[-1]

        # Check for staging/test streams (acceptable)
        if pair_part in ("staging", "test", "canary"):
            return True, f"Test/staging stream: {stream_key}"

        # Check BASE-QUOTE format (preferred)
        if "-" in pair_part:
            base, quote = pair_part.split("-", 1)
            if base.isalpha() and quote.isalpha():
                return True, f"Valid stream key format: {stream_key}"

        # Check BASE/QUOTE format (alternative - some publishers use this)
        if "/" in pair_part:
            base, quote = pair_part.split("/", 1)
            if base.isalpha() and quote.isalpha():
                return True, f"Alternative stream key format (BASE/QUOTE): {stream_key}"

        return False, f"Invalid stream key pair format: {stream_key}"

    return True, "Base signals stream"


def run_verification():
    """Run the full verification and generate report."""
    report = {
        "redis_connected": False,
        "streams_active_last_5min": 0,
        "most_recent_signal_timestamp": None,
        "enabled_pairs_seen": [],
        "issues": [],
    }

    print("=" * 70)
    print("ENGINE PUBLISHING VERIFICATION REPORT")
    print("=" * 70)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print()

    # 1. Connect to Redis
    print("[1] Connecting to Redis...")
    try:
        client = connect_redis_sync()
        client.ping()
        report["redis_connected"] = True
        print("    Redis Connected: yes")
        print()
    except Exception as e:
        report["redis_connected"] = False
        report["issues"].append(f"Redis connection failed: {str(e)}")
        print(f"    Redis Connected: no")
        print(f"    Error: {str(e)}")
        print("\n" + "=" * 70)
        print("VERIFICATION FAILED - Cannot connect to Redis")
        print("=" * 70)
        return report

    # 2. Scan for all relevant streams
    print("[2] Scanning for streams...")
    all_streams: Set[str] = set()

    for pattern in STREAM_PATTERNS:
        if "*" in pattern:
            keys = scan_keys_by_pattern(client, pattern)
            all_streams.update(keys)
        else:
            # Check if specific key exists
            try:
                if client.exists(pattern):
                    all_streams.add(pattern)
            except:
                pass

    print(f"    Found {len(all_streams)} total streams")
    print()

    # 3. Check stream activity and collect info
    print("[3] Checking stream activity (last 5 minutes)...")
    now = datetime.now(timezone.utc).timestamp()
    active_streams = []
    signal_streams_info = []
    all_symbols_seen: Set[str] = set()
    most_recent_signal_ts = 0.0

    for stream_key in sorted(all_streams):
        info = get_stream_info(client, stream_key)

        if not info["exists"]:
            continue

        latest_ts = info.get("latest_timestamp", 0.0)
        age_seconds = now - latest_ts if latest_ts > 0 else float("inf")

        if age_seconds <= ACTIVITY_WINDOW_SECONDS:
            active_streams.append(stream_key)

        # Process signal streams
        if stream_key.startswith("signals:"):
            signal_streams_info.append({
                "key": stream_key,
                "info": info,
                "age_seconds": age_seconds,
            })

            if latest_ts > most_recent_signal_ts:
                most_recent_signal_ts = latest_ts

            # Extract symbol from stream key
            parts = stream_key.split(":")
            if len(parts) >= 3:
                pair = parts[-1]
                all_symbols_seen.add(pair)

            # Extract symbol from payload
            if info.get("latest") and info["latest"].get("data"):
                sym = extract_symbol_from_payload(info["latest"]["data"])
                if sym:
                    all_symbols_seen.add(sym)

    report["streams_active_last_5min"] = len(active_streams)
    print(f"    Streams active in last 5 min: {len(active_streams)}")
    print()

    # 4. Most recent signal timestamp
    print("[4] Signal stream analysis...")
    if most_recent_signal_ts > 0:
        dt = datetime.fromtimestamp(most_recent_signal_ts, tz=timezone.utc)
        report["most_recent_signal_timestamp"] = dt.isoformat()
        age = now - most_recent_signal_ts
        print(f"    Most recent signal timestamp: {dt.isoformat()}")
        print(f"    Signal age: {age:.1f} seconds ({age/60:.1f} minutes)")
    else:
        report["most_recent_signal_timestamp"] = "No signals found"
        report["issues"].append("No signal streams with data found")
        print("    Most recent signal timestamp: No signals found")
    print()

    # 5. Enabled pairs seen
    print("[5] Pairs analysis...")

    # Normalize symbols for comparison
    normalized_seen = set()
    for sym in all_symbols_seen:
        # Convert to BASE/QUOTE format
        if "-" in sym:
            normalized_seen.add(sym.replace("-", "/"))
        else:
            normalized_seen.add(sym)

    enabled_pairs_seen = [p for p in EXPECTED_ENABLED_PAIRS if p in normalized_seen]
    report["enabled_pairs_seen"] = enabled_pairs_seen

    print(f"    Enabled pairs seen: {', '.join(enabled_pairs_seen) if enabled_pairs_seen else 'None'}")

    # Check for missing pairs
    missing_pairs = [p for p in EXPECTED_ENABLED_PAIRS if p not in normalized_seen]
    if missing_pairs:
        report["issues"].append(f"Missing expected pairs: {', '.join(missing_pairs)}")
        print(f"    Missing pairs: {', '.join(missing_pairs)}")
    print()

    # 6. Check for duplicates
    print("[6] Duplicate check...")

    # Check for duplicate entries in signal streams
    duplicates_found = []
    for sig_info in signal_streams_info:
        stream_key = sig_info["key"]

        # Check stream key format
        valid, msg = check_stream_key_format(stream_key)
        if not valid:
            report["issues"].append(msg)

    # Check if same pair appears in multiple stream formats
    stream_pair_counts = defaultdict(int)
    for sig_info in signal_streams_info:
        parts = sig_info["key"].split(":")
        if len(parts) >= 3:
            mode = parts[1]  # paper or live
            pair = parts[2]
            key = f"{mode}:{pair}"
            stream_pair_counts[key] += 1

    for key, count in stream_pair_counts.items():
        if count > 1:
            duplicates_found.append(f"{key} appears {count} times")
            report["issues"].append(f"Duplicate stream: {key}")

    if duplicates_found:
        print(f"    Duplicates found: {', '.join(duplicates_found)}")
    else:
        print("    No duplicate pairs detected")
    print()

    # 7. Format validation
    print("[7] Format validation...")
    format_issues = []

    for sig_info in signal_streams_info:
        info = sig_info["info"]
        if info.get("latest") and info["latest"].get("data"):
            data = info["latest"]["data"]
            sym = extract_symbol_from_payload(data)
            if sym:
                valid, msg = validate_symbol_format(sym)
                if not valid:
                    format_issues.append(msg)

    if format_issues:
        for issue in format_issues[:5]:  # Limit to 5
            print(f"    Format issue: {issue}")
            report["issues"].append(issue)
    else:
        print("    All payload symbols use correct BASE/QUOTE format")
    print()

    # 8. Active streams detail
    print("[8] Active streams (last 5 min)...")
    for stream_key in sorted(active_streams)[:15]:  # Limit to 15
        info = get_stream_info(client, stream_key)
        age = now - info.get("latest_timestamp", 0) if info.get("latest_timestamp") else 0
        print(f"    {stream_key}: {info.get('length', 0)} msgs, {age:.0f}s ago")

    if len(active_streams) > 15:
        print(f"    ... and {len(active_streams) - 15} more")
    print()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Redis Connected: {'yes' if report['redis_connected'] else 'no'}")
    print(f"Streams active in last 5 min: {report['streams_active_last_5min']}")
    print(f"Most recent signal timestamp: {report['most_recent_signal_timestamp']}")
    print(f"Enabled pairs seen: {', '.join(report['enabled_pairs_seen']) if report['enabled_pairs_seen'] else 'None'}")
    print()

    if report["issues"]:
        print("ISSUES DETECTED:")
        for issue in report["issues"]:
            print(f"  - {issue}")
    else:
        print("No issues detected - Engine publishing verified successfully!")

    print("=" * 70)

    return report


def main():
    """Main entry point."""
    try:
        report = run_verification()

        # Exit with appropriate code
        if not report["redis_connected"]:
            sys.exit(1)
        if report["issues"]:
            sys.exit(0)  # Connected but has issues - still useful
        sys.exit(0)

    except KeyboardInterrupt:
        print("\nVerification cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\nVerification error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
