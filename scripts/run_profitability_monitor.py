"""
Run Profitability Monitor in Production

Continuously monitors trading performance and triggers adaptations:
- Tracks rolling 7d and 30d metrics
- Auto-triggers parameter tuning when below targets
- Auto-enables protection mode when above targets
- Publishes to Redis for dashboard consumption

Usage:
    python scripts/run_profitability_monitor.py [--dry-run] [--no-auto-adapt]

Author: Crypto AI Bot Team
Date: 2025-11-09
"""

import os
import sys
import asyncio
import argparse
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.monitoring import ProfitabilityMonitor


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)


async def main(args):
    """Main execution."""

    logger.info("="*80)
    logger.info("PROFITABILITY MONITOR - PRODUCTION")
    logger.info("="*80)
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Auto-adapt: {args.auto_adapt}")
    logger.info(f"Check interval: {args.check_interval_seconds}s")

    # Initialize monitor
    monitor = ProfitabilityMonitor(
        initial_capital=args.initial_capital,
        redis_url=os.getenv('REDIS_URL'),
        auto_adapt=args.auto_adapt,
        dry_run=args.dry_run,
    )

    await monitor.initialize()

    try:
        logger.info("\nStarting monitoring loop...")

        while True:
            # Update metrics and check for adaptations
            signal = await monitor.update_and_check()

            if signal:
                logger.info(
                    f"\n{'='*80}\n"
                    f"ADAPTATION SIGNAL\n"
                    f"{'='*80}\n"
                    f"Action: {signal.action}\n"
                    f"Reason: {signal.reason}\n"
                    f"Severity: {signal.severity}\n"
                    f"{'='*80}\n"
                )

            # Sleep until next check
            await asyncio.sleep(args.check_interval_seconds)

    except KeyboardInterrupt:
        logger.info("\n\nShutting down profitability monitor...")

    except Exception as e:
        logger.error(f"Monitor error: {e}", exc_info=True)

    finally:
        await monitor.shutdown()
        logger.info("Monitor stopped.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run profitability monitor')

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode (no actual adaptations)'
    )

    parser.add_argument(
        '--no-auto-adapt',
        dest='auto_adapt',
        action='store_false',
        default=True,
        help='Disable automatic adaptations'
    )

    parser.add_argument(
        '--initial-capital',
        type=float,
        default=10000.0,
        help='Initial capital in USD (default: 10000)'
    )

    parser.add_argument(
        '--check-interval-seconds',
        type=int,
        default=300,  # 5 minutes
        help='Interval between checks in seconds (default: 300)'
    )

    args = parser.parse_args()

    asyncio.run(main(args))
