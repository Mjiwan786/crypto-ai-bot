"""
PRD-001 Section 6.4 Backtest Automation Script

Command-line interface for running PRD-compliant backtests.

Usage:
    # Run backtest for scalper strategy with 365 days
    python scripts/run_prd_backtest.py --strategy scalper --period 365

    # Run backtest for multiple pairs
    python scripts/run_prd_backtest.py --strategy momentum --pairs "BTC/USD,ETH/USD" --period 180

    # Generate HTML report
    python scripts/run_prd_backtest.py --strategy scalper --pair BTC/USD --period 365 --html

    # Enforce acceptance criteria (exit with error if failed)
    python scripts/run_prd_backtest.py --strategy scalper --period 365 --strict

Author: Crypto AI Bot Team
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtesting.prd_backtest_runner import PRDBacktestRunner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PRD-001 compliant backtest automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run scalper backtest with 365 days of data
  python scripts/run_prd_backtest.py --strategy scalper --period 365

  # Run momentum backtest for ETH/USD with 180 days
  python scripts/run_prd_backtest.py --strategy momentum --pair ETH/USD --period 180

  # Run backtest with HTML report generation
  python scripts/run_prd_backtest.py --strategy scalper --period 365 --html

  # Run backtest with strict acceptance criteria enforcement (CI mode)
  python scripts/run_prd_backtest.py --strategy scalper --period 365 --strict

  # Run for multiple pairs
  python scripts/run_prd_backtest.py --strategy scalper --pairs "BTC/USD,ETH/USD,SOL/USD" --period 365
        """
    )

    parser.add_argument(
        '--strategy',
        type=str,
        required=True,
        help='Strategy to backtest (e.g., scalper, momentum, mean_reversion)'
    )

    parser.add_argument(
        '--pair',
        type=str,
        default='BTC/USD',
        help='Trading pair (default: BTC/USD)'
    )

    parser.add_argument(
        '--pairs',
        type=str,
        default=None,
        help='Multiple trading pairs comma-separated (e.g., "BTC/USD,ETH/USD")'
    )

    parser.add_argument(
        '--period',
        type=int,
        default=365,
        help='Backtest period in days (default: 365)'
    )

    parser.add_argument(
        '--timeframe',
        type=str,
        default='1h',
        choices=['1m', '5m', '15m', '1h', '4h', '1d'],
        help='Candle timeframe (default: 1h)'
    )

    parser.add_argument(
        '--capital',
        type=float,
        default=10000.0,
        help='Initial capital in USD (default: 10000)'
    )

    parser.add_argument(
        '--html',
        action='store_true',
        help='Generate HTML report with equity curve'
    )

    parser.add_argument(
        '--strict',
        action='store_true',
        help='Enforce acceptance criteria (exit with error if failed)'
    )

    parser.add_argument(
        '--no-latest',
        action='store_true',
        help='Do not use latest market data (use cached data only)'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()

    # Set log level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine pairs to backtest
    if args.pairs:
        pairs = [p.strip() for p in args.pairs.split(',')]
    else:
        pairs = [args.pair]

    logger.info("=" * 80)
    logger.info("PRD-001 AUTOMATED BACKTEST")
    logger.info("=" * 80)
    logger.info(f"Strategy: {args.strategy}")
    logger.info(f"Pairs: {', '.join(pairs)}")
    logger.info(f"Period: {args.period} days")
    logger.info(f"Timeframe: {args.timeframe}")
    logger.info(f"Initial Capital: ${args.capital:,.2f}")
    logger.info(f"HTML Report: {'Yes' if args.html else 'No'}")
    logger.info(f"Strict Mode: {'Yes' if args.strict else 'No'}")
    logger.info("")

    # Initialize runner
    runner = PRDBacktestRunner()

    # Run backtests for each pair
    all_results = []
    all_passed = True

    for pair in pairs:
        try:
            logger.info(f"\n{'='*80}")
            logger.info(f"BACKTESTING: {args.strategy} | {pair}")
            logger.info('='*80)

            # Run backtest
            results = runner.run_backtest(
                strategy=args.strategy,
                pair=pair,
                period_days=args.period,
                timeframe=args.timeframe,
                initial_capital=args.capital,
                use_latest_data=not args.no_latest
            )

            all_results.append((pair, results))

            # Check acceptance
            if not results.acceptance_result.passed:
                all_passed = False

            # Generate HTML report if requested
            if args.html:
                logger.info(f"\nGenerating HTML report...")
                html_path = runner.generate_html_report(
                    results, args.strategy, pair
                )
                logger.info(f"✓ HTML report: {html_path}")

        except Exception as e:
            logger.error(f"❌ Backtest failed for {pair}: {e}", exc_info=args.debug)
            all_passed = False

    # Summary
    logger.info(f"\n{'='*80}")
    logger.info("BACKTEST SUMMARY")
    logger.info('='*80)

    if not all_results:
        logger.error("No successful backtests")
        sys.exit(1)

    for pair, results in all_results:
        status = "✓ PASS" if results.acceptance_result.passed else "✗ FAIL"
        logger.info(
            f"{pair:12} | Return: {results.metrics.total_return_pct:+7.2f}% | "
            f"Sharpe: {results.metrics.sharpe_ratio:6.2f} | "
            f"Trades: {results.metrics.total_trades:4d} | {status}"
        )

    # Exit with error if strict mode and any failed
    if args.strict and not all_passed:
        logger.error("\n❌ ACCEPTANCE CRITERIA FAILED - Blocking deployment")
        logger.error("Backtests did not meet PRD-001 Section 6.3 acceptance criteria")
        sys.exit(1)

    logger.info(f"\n✓ All backtests complete. Results saved to out/backtests/")
    sys.exit(0)


if __name__ == "__main__":
    main()
