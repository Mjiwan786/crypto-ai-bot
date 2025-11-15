#!/usr/bin/env python3
"""
Trade Close Seeder - Crypto AI Bot

Writes fake trade close events to Redis stream "trades:closed" for testing
and verification of the PnL aggregation pipeline.

Usage:
    python scripts/seed_closed_trades.py
    python scripts/seed_closed_trades.py --count 20 --interval 1.0
    python scripts/seed_closed_trades.py --dry-run

Environment Variables:
    REDIS_URL - Redis connection string (default: redis://localhost:6379/0)
"""

import argparse
import os
import random
import sys
import time
from typing import List

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from agents.infrastructure.pnl_publisher import publish_trade_close
except ImportError as e:
    print(f"ERROR: Could not import pnl_publisher: {e}")
    print("Ensure you're in the project root or PYTHONPATH is set correctly.")
    sys.exit(1)

try:
    import redis
except ImportError:
    print("ERROR: redis package not installed. Run: pip install redis")
    sys.exit(1)


# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def generate_fake_trades(count: int = 10, start_ts: int = None) -> List[dict]:
    """
    Generate fake trade close events.

    Args:
        count: Number of trades to generate
        start_ts: Starting timestamp in milliseconds (default: now)

    Returns:
        List of trade event dictionaries
    """
    if start_ts is None:
        start_ts = int(time.time() * 1000)

    pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD"]
    sides = ["long", "short"]

    trades = []

    for i in range(count):
        pair = random.choice(pairs)
        side = random.choice(sides)

        # Generate realistic prices based on pair
        if pair == "BTC/USD":
            entry = random.uniform(40000, 50000)
            exit_price = entry * random.uniform(0.98, 1.03)  # ±3%
        elif pair == "ETH/USD":
            entry = random.uniform(2000, 3000)
            exit_price = entry * random.uniform(0.97, 1.04)  # ±4%
        elif pair == "SOL/USD":
            entry = random.uniform(80, 150)
            exit_price = entry * random.uniform(0.95, 1.06)  # ±6%
        else:  # AVAX/USD
            entry = random.uniform(30, 60)
            exit_price = entry * random.uniform(0.94, 1.07)  # ±7%

        # Calculate PnL
        qty = random.uniform(0.05, 0.2)  # Position size
        if side == "long":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        # Create trade event
        trade = {
            "id": f"seed_trade_{i:03d}",
            "ts": start_ts + (i * 500),  # 500ms apart
            "pair": pair,
            "side": side,
            "entry": round(entry, 2),
            "exit": round(exit_price, 2),
            "qty": round(qty, 4),
            "pnl": round(pnl, 2),
        }

        trades.append(trade)

    return trades


def seed_trades(
    trades: List[dict],
    interval: float = 0.5,
    dry_run: bool = False,
    verbose: bool = True,
) -> int:
    """
    Seed trades into Redis stream.

    Args:
        trades: List of trade events
        interval: Time between publishes in seconds
        dry_run: Preview without publishing
        verbose: Enable verbose output

    Returns:
        Number of trades published
    """
    if dry_run:
        print("\n🔍 DRY RUN - Preview trades:")
        print("=" * 60)
        for i, trade in enumerate(trades, start=1):
            print(
                f"{i:2d}. {trade['pair']:8s} {trade['side']:5s} "
                f"${trade['entry']:8,.2f} → ${trade['exit']:8,.2f} "
                f"PnL: ${trade['pnl']:+8.2f}"
            )
        print("=" * 60)
        print(f"\nTotal trades: {len(trades)}")
        print(f"Interval: {interval}s")
        print(f"Duration: {len(trades) * interval:.1f}s")
        return 0

    if verbose:
        print("\n" + "=" * 60)
        print("SEEDING TRADES")
        print("=" * 60)
        print(f"Trades to publish: {len(trades)}")
        print(f"Interval: {interval}s")
        print(f"Redis URL: {REDIS_URL}")
        print("=" * 60 + "\n")

    published = 0

    for i, trade in enumerate(trades, start=1):
        # Publish trade
        publish_trade_close(trade)
        published += 1

        if verbose:
            print(
                f"📤 {i:2d}/{len(trades)}: {trade['pair']:8s} {trade['side']:5s} "
                f"${trade['entry']:8,.2f} → ${trade['exit']:8,.2f} "
                f"PnL: ${trade['pnl']:+8.2f}"
            )

        # Wait before next trade (except for last one)
        if i < len(trades):
            time.sleep(interval)

    if verbose:
        print("\n" + "=" * 60)
        print(f"✅ Seeded {published} trades successfully")
        print("=" * 60 + "\n")

    return published


def verify_seeding(verbose: bool = True) -> bool:
    """
    Verify that trades were published to Redis.

    Args:
        verbose: Enable verbose output

    Returns:
        True if verification passed
    """
    if verbose:
        print("🔍 Verifying seeded data...\n")

    try:
        client = redis.from_url(
            REDIS_URL,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.ping()

        # Check stream length
        stream_len = client.xlen("trades:closed")

        if verbose:
            print(f"✅ Redis connection OK")
            print(f"✅ Stream 'trades:closed' has {stream_len} messages")

        # Read last 3 messages
        messages = client.xrevrange("trades:closed", "+", "-", count=3)

        if messages and verbose:
            print(f"✅ Latest 3 trades:")
            for msg_id, fields in messages:
                msg_id_str = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id
                print(f"   - ID: {msg_id_str}")

        return True

    except Exception as e:
        if verbose:
            print(f"❌ Verification failed: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Seed fake trade close events for testing PnL aggregation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Seed 10 trades over 5 seconds (default)
    python scripts/seed_closed_trades.py

    # Seed 20 trades over 10 seconds
    python scripts/seed_closed_trades.py --count 20 --interval 0.5

    # Preview without publishing
    python scripts/seed_closed_trades.py --dry-run

    # Seed quickly (100ms interval)
    python scripts/seed_closed_trades.py --count 50 --interval 0.1

Workflow:
    1. Start aggregator: python -m monitoring.pnl_aggregator
    2. Seed trades: python scripts/seed_closed_trades.py
    3. Check health: python scripts/health_check_pnl.py --verbose
    4. Verify Redis: python scripts/seed_closed_trades.py --verify-only
        """,
    )

    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of trades to generate (default: 10)",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Time between trades in seconds (default: 0.5)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview trades without publishing",
    )

    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify Redis connection and data",
    )

    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress verbose output",
    )

    args = parser.parse_args()

    verbose = not args.quiet

    # Verify-only mode
    if args.verify_only:
        success = verify_seeding(verbose=verbose)
        return 0 if success else 1

    # Generate trades
    start_ts = int(time.time() * 1000)
    trades = generate_fake_trades(count=args.count, start_ts=start_ts)

    # Seed trades
    try:
        published = seed_trades(
            trades=trades,
            interval=args.interval,
            dry_run=args.dry_run,
            verbose=verbose,
        )

        if args.dry_run:
            return 0

        # Verify seeding
        if verbose:
            print("\n" + "=" * 60)
            print("VERIFICATION")
            print("=" * 60 + "\n")

        success = verify_seeding(verbose=verbose)

        if success and verbose:
            print("\n" + "=" * 60)
            print("NEXT STEPS")
            print("=" * 60)
            print("\n1. Check aggregator logs:")
            print("   (Should show trades being processed)\n")
            print("2. Run health check:")
            print("   python scripts/health_check_pnl.py --verbose\n")
            print("3. Verify equity stream:")
            print("   python -c \"import os,redis; r=redis.from_url(os.getenv('REDIS_URL','redis://localhost:6379/0'),decode_responses=False); print(r.xrevrange('pnl:equity','+','-',count=3))\"\n")
            print("4. Check latest equity:")
            print("   python -c \"import os,redis,json; r=redis.from_url(os.getenv('REDIS_URL','redis://localhost:6379/0')); data=json.loads(r.get('pnl:equity:latest')); print(f'Equity: ${data[\\\"equity\\\"]:,.2f}, Daily PnL: ${data[\\\"daily_pnl\\\"]:+,.2f}')\"\n")
            print("=" * 60 + "\n")

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n\n⏹️  Interrupted by user")
        return 130
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
