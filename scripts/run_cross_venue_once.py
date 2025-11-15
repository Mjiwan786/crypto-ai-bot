"""
Run Cross-Venue Monitor Once

Sets EXTERNAL_VENUE_READS=binance and runs a single update cycle.

Usage:
    python scripts/run_cross_venue_once.py
"""

import os
import sys
from pathlib import Path

# Set feature flag
os.environ["EXTERNAL_VENUE_READS"] = "binance"

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.infrastructure.cross_venue_runner import CrossVenueRunner

def main():
    print("=" * 70)
    print("Cross-Venue Market Data Monitor - Single Cycle Test")
    print("=" * 70)

    # Create runner
    symbols = ["BTC/USD", "ETH/USD", "SOL/USD"]
    runner = CrossVenueRunner(symbols=symbols, update_interval_seconds=10)

    if not runner.enabled:
        print("\n[ERROR] Cross-venue runner not enabled!")
        print("This should not happen - check configuration.")
        return False

    print(f"\n[OK] Cross-venue runner initialized for: {', '.join(symbols)}")
    print("\n[INFO] Running single update cycle...\n")

    # Run single cycle
    runner.run_update_cycle()

    print("\n" + "=" * 70)
    print("[SUCCESS] Cross-venue monitor cycle completed successfully!")
    print("=" * 70)

    # Print summary
    if runner.arb_detector:
        summary = runner.arb_detector.get_opportunity_summary()
        print(f"\nArbitrage Opportunities Summary:")
        print(f"  Active: {summary['active_count']}")
        print(f"  Total Detected: {summary['total_detected']}")

        if summary['active_count'] > 0:
            print(f"  Avg Edge: {summary['avg_edge_bps']:.2f} bps")
            print(f"  Max Edge: {summary['max_edge_bps']:.2f} bps")
            print("\n  Top Opportunities:")
            for opp in summary['opportunities'][:3]:
                print(f"    - {opp['symbol']}: {opp['net_edge_bps']:.1f}bps edge "
                      f"(confidence: {opp['confidence']:.2f})")

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
