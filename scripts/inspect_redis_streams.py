#!/usr/bin/env python3
"""
Redis Streams Inspector for crypto-ai-bot

Inspects Redis streams to verify proper separation between paper and live data.

Usage:
    # Inspect all mode-aware streams
    python scripts/inspect_redis_streams.py

    # Inspect specific mode
    python scripts/inspect_redis_streams.py --mode paper
    python scripts/inspect_redis_streams.py --mode live

    # Show detailed stream contents (last N messages)
    python scripts/inspect_redis_streams.py --mode paper --limit 5
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import after path setup
from dotenv import load_dotenv
from mcp.redis_manager import RedisManager
from config.mode_aware_streams import (
    get_signal_stream,
    get_pnl_stream,
    get_equity_stream,
    get_all_mode_streams,
)

# Load environment
load_dotenv()


def format_timestamp(ts_ms: int) -> str:
    """Format Redis stream timestamp to readable datetime."""
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def inspect_stream(redis: RedisManager, stream_name: str, limit: int = 10) -> Dict[str, Any]:
    """
    Inspect a single Redis stream.

    Returns:
        Dict with stream info: length, first_id, last_id, messages
    """
    try:
        # Get stream length
        length = redis.client.xlen(stream_name)

        if length == 0:
            return {
                "name": stream_name,
                "length": 0,
                "status": "empty",
                "messages": [],
            }

        # Get oldest and newest messages
        oldest = redis.client.xrange(stream_name, count=1)
        newest = redis.client.xrevrange(stream_name, count=limit)

        first_id = oldest[0][0] if oldest else "N/A"
        last_id = newest[0][0] if newest else "N/A"

        # Parse messages
        messages = []
        for msg_id, fields in newest:
            # Convert bytes to strings
            parsed_fields = {
                k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in fields.items()
            }

            messages.append({
                "id": msg_id.decode() if isinstance(msg_id, bytes) else msg_id,
                "timestamp": format_timestamp(int(msg_id.decode().split("-")[0])) if isinstance(msg_id, bytes) else format_timestamp(int(msg_id.split("-")[0])),
                "fields": parsed_fields,
            })

        return {
            "name": stream_name,
            "length": length,
            "first_id": first_id.decode() if isinstance(first_id, bytes) else first_id,
            "last_id": last_id.decode() if isinstance(last_id, bytes) else last_id,
            "status": "active",
            "messages": messages,
        }

    except Exception as e:
        return {
            "name": stream_name,
            "length": 0,
            "status": f"error: {e}",
            "messages": [],
        }


def print_stream_report(stream_info: Dict[str, Any], show_messages: bool = False):
    """Print formatted stream report."""
    print(f"\n{'='*80}")
    print(f"Stream: {stream_info['name']}")
    print(f"{'='*80}")
    print(f"Status:     {stream_info['status']}")
    print(f"Length:     {stream_info['length']:,} messages")

    if stream_info['length'] > 0:
        print(f"First ID:   {stream_info['first_id']}")
        print(f"Last ID:    {stream_info['last_id']}")

        if show_messages and stream_info['messages']:
            print(f"\nLatest Messages ({len(stream_info['messages'])} shown):")
            print("-" * 80)

            for i, msg in enumerate(stream_info['messages'], 1):
                print(f"\n  Message #{i}")
                print(f"  ID:        {msg['id']}")
                print(f"  Timestamp: {msg['timestamp']}")
                print(f"  Fields:    {len(msg['fields'])} fields")

                # Show first few fields
                for j, (k, v) in enumerate(list(msg['fields'].items())[:5], 1):
                    print(f"    {k}: {v}")

                if len(msg['fields']) > 5:
                    print(f"    ... and {len(msg['fields']) - 5} more fields")


def main():
    parser = argparse.ArgumentParser(description="Inspect Redis streams for paper vs live separation")
    parser.add_argument(
        "--mode",
        choices=["paper", "live", "all"],
        default="all",
        help="Which mode to inspect (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of recent messages to show (default: 10)",
    )
    parser.add_argument(
        "--show-messages",
        action="store_true",
        help="Show detailed message contents",
    )

    args = parser.parse_args()

    print("\n" + "="*80)
    print("CRYPTO-AI-BOT REDIS STREAMS INSPECTOR")
    print("="*80)
    print(f"Mode:          {args.mode}")
    print(f"Message Limit: {args.limit}")
    print(f"Redis URL:     {os.getenv('REDIS_URL', 'Not set')[:50]}...")
    print("="*80)

    # Connect to Redis
    redis = RedisManager()
    if not redis.connect():
        print("\n[ERROR] Failed to connect to Redis!")
        sys.exit(1)

    print("\n[SUCCESS] Connected to Redis successfully!")

    # Determine which streams to inspect
    if args.mode == "all":
        modes = ["paper", "live"]
    else:
        modes = [args.mode]

    # Inspect streams for each mode
    for mode in modes:
        streams = get_all_mode_streams(mode=mode)

        print(f"\n\n{'#'*80}")
        print(f"# MODE: {mode.upper()}")
        print(f"{'#'*80}")

        # Inspect each stream
        for stream_type, stream_name in streams.items():
            if stream_type == "mode":
                continue  # Skip the mode field itself

            stream_info = inspect_stream(redis, stream_name, limit=args.limit)
            print_stream_report(stream_info, show_messages=args.show_messages)

    # Summary
    print(f"\n\n{'='*80}")
    print("INSPECTION COMPLETE")
    print("="*80)
    print("\nNOTE: Paper and live streams should be completely separate!")
    print("  - Paper:  signals:paper, pnl:paper")
    print("  - Live:   signals:live, pnl:live")
    print("\nNo data should ever appear in both paper and live streams.")
    print("="*80 + "\n")

    redis.close()


if __name__ == "__main__":
    main()
