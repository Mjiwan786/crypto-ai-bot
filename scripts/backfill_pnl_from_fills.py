#!/usr/bin/env python3
"""
Backfill PnL from Historical Fills - Crypto AI Bot

Generates equity history from historical fill data to bootstrap PnL charts.
Safe to re-run with marker key tracking.

Features:
- Supports CSV and JSONL input formats
- Computes per-trade PnL and running equity
- Publishes spaced time series to Redis stream "pnl:equity"
- Idempotent with marker key "pnl:backfill:done"
- --force flag to override marker

Input Format (CSV):
    timestamp,pair,side,entry_price,exit_price,quantity,pnl
    1704067200000,BTC/USD,long,45000.0,46000.0,0.1,100.0

Input Format (JSONL):
    {"ts":1704067200000,"pair":"BTC/USD","side":"long","entry":45000.0,"exit":46000.0,"qty":0.1,"pnl":100.0}

Environment Variables:
    REDIS_URL - Redis connection string (default: redis://localhost:6379/0)

Usage:
    python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv --start-equity 10000
    python scripts/backfill_pnl_from_fills.py --file data/fills/sample.jsonl --start-equity 10000 --force
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterator, List

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
BACKFILL_MARKER_KEY = "pnl:backfill:done"
DEFAULT_START_EQUITY = 10000.0


def parse_csv_fills(file_path: Path) -> Iterator[Dict]:
    """Parse CSV fill data."""
    with open(file_path, "r") as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                yield {
                    "ts": int(row["timestamp"]),
                    "pair": row["pair"],
                    "side": row["side"],
                    "entry": float(row["entry_price"]),
                    "exit": float(row["exit_price"]),
                    "qty": float(row["quantity"]),
                    "pnl": float(row["pnl"]),
                }
            except (KeyError, ValueError) as e:
                print(f"⚠️  Skipping invalid CSV row: {e}")
                continue


def parse_jsonl_fills(file_path: Path) -> Iterator[Dict]:
    """Parse JSONL fill data."""
    with open(file_path, "r") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                if orjson:
                    data = orjson.loads(line)
                else:
                    data = json.loads(line)

                # Normalize field names
                yield {
                    "ts": int(data.get("ts") or data.get("timestamp")),
                    "pair": data.get("pair") or data.get("symbol"),
                    "side": data.get("side"),
                    "entry": float(data.get("entry") or data.get("entry_price")),
                    "exit": float(data.get("exit") or data.get("exit_price")),
                    "qty": float(data.get("qty") or data.get("quantity")),
                    "pnl": float(data.get("pnl")),
                }
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                print(f"⚠️  Skipping invalid JSONL line {line_num}: {e}")
                continue


def load_fills(file_path: Path) -> List[Dict]:
    """Load and parse fill data from file."""
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return []

    suffix = file_path.suffix.lower()

    fills = []

    if suffix == ".csv":
        print(f"📄 Parsing CSV file: {file_path}")
        fills = list(parse_csv_fills(file_path))
    elif suffix in (".jsonl", ".json"):
        print(f"📄 Parsing JSONL file: {file_path}")
        fills = list(parse_jsonl_fills(file_path))
    else:
        print(f"❌ Unsupported file format: {suffix}")
        return []

    # Sort by timestamp
    fills.sort(key=lambda f: f["ts"])

    print(f"✅ Loaded {len(fills)} fills")
    return fills


def validate_fill(fill: Dict) -> bool:
    """Validate fill has required fields."""
    required_fields = ["ts", "pair", "side", "entry", "exit", "qty", "pnl"]

    for field in required_fields:
        if field not in fill:
            return False

    # Validate types
    try:
        assert isinstance(fill["ts"], int), "ts must be int"
        assert isinstance(fill["pair"], str), "pair must be str"
        assert fill["side"] in ("long", "short"), "side must be long/short"
        assert isinstance(fill["entry"], (int, float)), "entry must be numeric"
        assert isinstance(fill["exit"], (int, float)), "exit must be numeric"
        assert isinstance(fill["qty"], (int, float)), "qty must be numeric"
        assert isinstance(fill["pnl"], (int, float)), "pnl must be numeric"
    except AssertionError as e:
        return False

    return True


def publish_equity_point(client: redis.Redis, ts_ms: int, equity: float, daily_pnl: float) -> None:
    """Publish equity snapshot to Redis stream."""
    snapshot = {
        "ts": ts_ms,
        "equity": equity,
        "daily_pnl": daily_pnl,
    }

    # Serialize
    if orjson and hasattr(orjson, "dumps"):
        json_bytes = orjson.dumps(snapshot)
    else:
        json_bytes = json.dumps(snapshot).encode("utf-8")

    # Publish to stream with explicit message ID based on timestamp
    # Format: <timestamp_ms>-<sequence> where sequence is 0 for backfill
    msg_id = f"{ts_ms}-0"

    try:
        # Use XADD with explicit ID for historical data
        # Note: Redis requires IDs to be monotonically increasing
        client.execute_command("XADD", "pnl:equity", msg_id, "json", json_bytes)
    except redis.ResponseError:
        # If explicit ID fails (duplicate or out of order), use auto-generated
        client.xadd("pnl:equity", {"json": json_bytes})


def backfill_pnl(
    client: redis.Redis,
    fills: List[Dict],
    start_equity: float,
    force: bool = False,
) -> int:
    """
    Backfill PnL data from fills.

    Args:
        client: Redis client
        fills: List of fill dictionaries
        start_equity: Starting equity
        force: Force backfill even if marker exists

    Returns:
        Number of equity points published
    """
    # Check marker
    if not force and client.get(BACKFILL_MARKER_KEY):
        print("⚠️  Backfill already completed. Use --force to override.")
        return 0

    if not fills:
        print("⚠️  No fills to process.")
        return 0

    print("\n" + "=" * 60)
    print("STARTING BACKFILL")
    print("=" * 60)
    print(f"Fills to process: {len(fills)}")
    print(f"Start equity: ${start_equity:,.2f}")
    print("=" * 60 + "\n")

    equity = start_equity
    day_start_equity = start_equity
    current_day_ts = None
    points_published = 0

    for i, fill in enumerate(fills, start=1):
        # Validate fill
        if not validate_fill(fill):
            print(f"⚠️  Skipping invalid fill {i}: {fill}")
            continue

        ts_ms = fill["ts"]
        pnl = float(fill["pnl"])

        # Detect day boundary (simple: check if day changed)
        if current_day_ts is None:
            current_day_ts = ts_ms // 86400000  # Day number
        else:
            fill_day_ts = ts_ms // 86400000
            if fill_day_ts > current_day_ts:
                # Day crossed - reset daily PnL
                day_start_equity = equity
                current_day_ts = fill_day_ts

        # Update equity
        equity += pnl
        daily_pnl = equity - day_start_equity

        # Publish equity point
        publish_equity_point(client, ts_ms, equity, daily_pnl)
        points_published += 1

        # Log progress (every 100 fills or last fill)
        if i % 100 == 0 or i == len(fills):
            print(
                f"📈 Processed {i}/{len(fills)}: "
                f"Equity ${equity:,.2f} "
                f"(daily: ${daily_pnl:+,.2f})"
            )

    # Update latest equity
    final_snapshot = {
        "ts": fills[-1]["ts"],
        "equity": equity,
        "daily_pnl": daily_pnl,
    }

    if orjson and hasattr(orjson, "dumps"):
        json_bytes = orjson.dumps(final_snapshot)
    else:
        json_bytes = json.dumps(final_snapshot).encode("utf-8")

    client.set("pnl:equity:latest", json_bytes)

    # Set marker
    client.set(BACKFILL_MARKER_KEY, "true")

    print("\n" + "=" * 60)
    print("BACKFILL COMPLETE")
    print("=" * 60)
    print(f"✅ Published {points_published} equity points")
    print(f"✅ Final equity: ${equity:,.2f}")
    print(f"✅ Daily PnL: ${daily_pnl:+,.2f}")
    print(f"✅ Marker key set: {BACKFILL_MARKER_KEY}")
    print("=" * 60 + "\n")

    return points_published


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill PnL from historical fills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Backfill from CSV
    python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv --start-equity 10000

    # Backfill from JSONL
    python scripts/backfill_pnl_from_fills.py --file data/fills/sample.jsonl --start-equity 10000

    # Force re-run
    python scripts/backfill_pnl_from_fills.py --file data/fills/sample.csv --force

    # Check backfill status
    redis-cli GET pnl:backfill:done
        """,
    )

    parser.add_argument(
        "--file",
        type=Path,
        help="Path to fills file (CSV or JSONL)",
    )

    parser.add_argument(
        "--start-equity",
        type=float,
        default=DEFAULT_START_EQUITY,
        help=f"Starting equity in USD (default: {DEFAULT_START_EQUITY})",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force backfill even if marker exists",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse fills but don't write to Redis",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("PNL BACKFILL - CRYPTO AI BOT")
    print("=" * 60)
    print(f"Redis URL: {REDIS_URL}")
    print(f"Start Equity: ${args.start_equity:,.2f}")
    if args.force:
        print("⚠️  Force mode: ENABLED")
    if args.dry_run:
        print("🔍 Dry run mode: ENABLED")
    print("=" * 60 + "\n")

    # Check for fills file
    if not args.file:
        # Auto-discover fills in data/fills/
        fills_dir = Path("data/fills")
        if not fills_dir.exists():
            print(f"⚠️  No fills directory found: {fills_dir}")
            print("ℹ️  Create directory and add fills files:")
            print(f"   mkdir -p {fills_dir}")
            print(f"   # Add CSV or JSONL files to {fills_dir}/")
            return 0

        # Find first CSV or JSONL file
        fill_files = list(fills_dir.glob("*.csv")) + list(fills_dir.glob("*.jsonl")) + list(fills_dir.glob("*.json"))

        if not fill_files:
            print(f"⚠️  No fills files found in {fills_dir}")
            print("ℹ️  Expected file formats: CSV (.csv) or JSONL (.jsonl, .json)")
            return 0

        args.file = fill_files[0]
        print(f"ℹ️  Auto-discovered fills file: {args.file}\n")

    # Load fills
    fills = load_fills(args.file)

    if not fills:
        print("⚠️  No valid fills found. Exiting.")
        return 0

    # Dry run mode
    if args.dry_run:
        print("\n🔍 DRY RUN - Preview fills:")
        print("=" * 60)

        equity = args.start_equity
        for i, fill in enumerate(fills[:10], start=1):  # Show first 10
            equity += fill["pnl"]
            print(
                f"{i}. {fill['pair']} {fill['side']} @ {fill['ts']}: "
                f"PnL ${fill['pnl']:+,.2f} → Equity ${equity:,.2f}"
            )

        if len(fills) > 10:
            print(f"... and {len(fills) - 10} more fills")

        print("=" * 60)
        print("✅ Dry run complete. Use without --dry-run to publish to Redis.")
        return 0

    # Connect to Redis
    try:
        client = redis.from_url(
            REDIS_URL,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.ping()
        print("✅ Connected to Redis\n")
    except Exception as e:
        print(f"❌ Failed to connect to Redis: {e}")
        return 1

    # Run backfill
    try:
        points_published = backfill_pnl(
            client=client,
            fills=fills,
            start_equity=args.start_equity,
            force=args.force,
        )

        if points_published > 0:
            print("✅ Backfill successful!")
            print("\nVerify with Redis CLI:")
            print("  redis-cli XLEN pnl:equity")
            print("  redis-cli GET pnl:equity:latest")
            print("  redis-cli GET pnl:backfill:done")
            return 0
        else:
            return 0

    except Exception as e:
        print(f"\n❌ Backfill failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
