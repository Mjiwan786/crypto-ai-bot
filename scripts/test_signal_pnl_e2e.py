#!/usr/bin/env python3
"""
End-to-End Signal → PnL Test (scripts/test_signal_pnl_e2e.py)

Tests the complete signal to PnL pipeline:
    1. Emit signal to Redis (signals:paper:<PAIR>)
    2. Fill simulator processes signal
    3. PnL tracker updates equity
    4. Verify all Redis keys are updated

USAGE:
    python scripts/test_signal_pnl_e2e.py
"""

import asyncio
import logging
import os
import time
from dotenv import load_dotenv

from signals.schema import create_signal
from signals.publisher import SignalPublisher
from pnl.rolling_pnl import PnLTracker
from pnl.paper_fill_simulator import PaperFillSimulator

load_dotenv(".env.prod")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_end_to_end():
    """Run end-to-end signal → PnL test."""
    print("=" * 70)
    print(" " * 15 + "SIGNAL -> PNL END-TO-END TEST")
    print("=" * 70)

    redis_url = os.getenv("REDIS_URL")
    redis_cert = os.getenv("REDIS_TLS_CERT_PATH")

    # STEP 1: Initialize components
    print("\n[STEP 1] Initialize components")
    print("-" * 70)

    signal_publisher = SignalPublisher(
        redis_url=redis_url, redis_cert_path=redis_cert
    )
    pnl_tracker = PnLTracker(
        redis_url=redis_url,
        redis_cert_path=redis_cert,
        initial_balance=10000.0,
        mode="paper",
    )
    fill_simulator = PaperFillSimulator(
        redis_url=redis_url, redis_cert_path=redis_cert, trading_pairs=["BTC/USD"]
    )

    # Connect all components
    await signal_publisher.connect()
    await pnl_tracker.connect()
    await fill_simulator.connect()

    # Reset PnL tracker for clean test
    await pnl_tracker.reset()

    print("  [OK] Signal Publisher: Connected")
    print("  [OK] PnL Tracker: Connected (equity=$10000.00)")
    print("  [OK] Fill Simulator: Connected")

    # STEP 2: Get initial PnL state
    print("\n[STEP 2] Get initial PnL state")
    print("-" * 70)

    initial_pnl = await pnl_tracker.get_summary()
    print(f"  Initial Equity: ${initial_pnl.equity:.2f}")
    print(f"  Initial Positions: {len(initial_pnl.positions)}")
    print(f"  Initial Realized PnL: ${initial_pnl.realized_pnl:.2f}")

    # STEP 3: Emit test signal
    print("\n[STEP 3] Emit test signal")
    print("-" * 70)

    signal = create_signal(
        pair="BTC/USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="e2e_test",
        confidence=0.85,
        mode="paper",
    )

    entry_id = await signal_publisher.publish(signal)

    print(f"  [OK] Published signal to {signal.get_stream_key()}")
    print(f"  Signal ID: {signal.id}")
    print(f"  Entry ID: {entry_id}")
    print(f"  Pair: {signal.pair}")
    print(f"  Side: {signal.side}")
    print(f"  Entry: ${signal.entry:.2f}")

    # STEP 4: Start fill simulator (runs for 3 seconds to process signal)
    print("\n[STEP 4] Run fill simulator (3 seconds)")
    print("-" * 70)

    print("  Waiting for fill simulator to process signal...")
    await fill_simulator.run(duration=3)

    fill_metrics = fill_simulator.get_metrics()
    print(f"  [OK] Fills processed: {fill_metrics['total_fills']}")

    # STEP 5: Verify PnL was updated
    print("\n[STEP 5] Verify PnL was updated")
    print("-" * 70)

    # Reload state from Redis (fill simulator used a different PnL tracker instance)
    await pnl_tracker._load_state()
    updated_pnl = await pnl_tracker.get_summary()

    print(f"  Updated Equity: ${updated_pnl.equity:.2f}")
    print(f"  Open Positions: {len(updated_pnl.positions)}")
    print(f"  Realized PnL: ${updated_pnl.realized_pnl:.2f}")
    print(f"  Unrealized PnL: ${updated_pnl.unrealized_pnl:.2f}")

    if len(updated_pnl.positions) > 0:
        for pair, pos in updated_pnl.positions.items():
            print(f"\n  Position: {pair}")
            print(f"    Side: {pos.side}")
            print(f"    Quantity: {pos.quantity}")
            print(f"    Avg Entry: ${pos.avg_entry:.2f}")
            print(f"    Unrealized PnL: ${pos.unrealized_pnl:.2f}")

    # STEP 6: Verify Redis keys
    print("\n[STEP 6] Verify Redis keys")
    print("-" * 70)

    # Check pnl:summary
    pnl_summary_data = await pnl_tracker.redis_client.get("pnl:summary")
    print(f"  [OK] pnl:summary: {'FOUND' if pnl_summary_data else 'NOT FOUND'}")

    # Check pnl:equity_curve
    equity_curve_len = await pnl_tracker.redis_client.xlen("pnl:equity_curve")
    print(f"  [OK] pnl:equity_curve: {equity_curve_len} events")

    # Check signals:paper:BTC-USD
    signal_stream_len = await signal_publisher.redis_client.xlen(
        "signals:paper:BTC-USD"
    )
    print(f"  [OK] signals:paper:BTC-USD: {signal_stream_len} signals")

    # Check fills:paper
    fills_stream_len = await pnl_tracker.redis_client.xlen("fills:paper")
    print(f"  [OK] fills:paper: {fills_stream_len} fills")

    # STEP 7: Test summary
    print("\n" + "=" * 70)
    print("                      TEST SUMMARY")
    print("=" * 70)

    success = True
    checks = []

    # Check 1: Signal was published
    if signal_stream_len > 0:
        checks.append(("Signal published to Redis", "PASS"))
    else:
        checks.append(("Signal published to Redis", "FAIL"))
        success = False

    # Check 2: Fill was processed
    if fill_metrics["total_fills"] > 0:
        checks.append(("Fill simulator processed signal", "PASS"))
    else:
        checks.append(("Fill simulator processed signal", "FAIL"))
        success = False

    # Check 3: PnL was updated
    if len(updated_pnl.positions) > 0 or updated_pnl.realized_pnl != 0:
        checks.append(("PnL tracker updated", "PASS"))
    else:
        checks.append(("PnL tracker updated", "FAIL"))
        success = False

    # Check 4: Redis keys exist
    if (
        pnl_summary_data
        and equity_curve_len > 0
        and signal_stream_len > 0
        and fills_stream_len > 0
    ):
        checks.append(("All Redis keys present", "PASS"))
    else:
        checks.append(("All Redis keys present", "FAIL"))
        success = False

    # Print checks
    for check_name, status in checks:
        status_marker = "[OK]" if status == "PASS" else "[FAIL]"
        print(f"  {status_marker} {check_name}")

    print("\n" + "=" * 70)
    if success:
        print("                  [OK] ALL TESTS PASSED")
    else:
        print("                 [FAIL] SOME TESTS FAILED")
    print("=" * 70)

    # Cleanup
    await signal_publisher.close()
    await pnl_tracker.close()
    await fill_simulator.close()

    return 0 if success else 1


async def main():
    """Main entry point."""
    try:
        exit_code = await test_end_to_end()
        return exit_code
    except Exception as e:
        print(f"\n[ERROR] Test failed with exception: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
