"""
Scalper CLI

Command-line interface for multi-pair scalper with allocation management.

Flags:
  --enable-alts: Enable alt-coin pairs (SOL, ADA)
  --core-only: Trade only core pairs (BTC, ETH)
  --turbo-mode: Enable aggressive sizing
  --max-pairs: Maximum concurrent pairs
  --allocation-cap: Per-pair allocation cap (%)

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import argparse
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.infrastructure.allocation_router import AllocationRouter
from agents.infrastructure.trading_specs_validator import TradingSpecsValidator

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Multi-Pair Scalper with Allocation Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Core pairs only (BTC, ETH)
  python cli/scalper_cli.py --core-only

  # Include alt-coins (SOL, ADA)
  python cli/scalper_cli.py --enable-alts

  # Turbo mode with 3 pairs max
  python cli/scalper_cli.py --turbo-mode --max-pairs 3

  # Custom allocation cap
  python cli/scalper_cli.py --allocation-cap 8.0

  # Conservative mode, core only
  python cli/scalper_cli.py --core-only --mode conservative

  # Paper trading with all pairs
  python cli/scalper_cli.py --enable-alts --mode paper
        """,
    )

    # Pair selection flags
    parser.add_argument(
        "--enable-alts",
        action="store_true",
        help="Enable alt-coin pairs (SOL/USD, ADA/USD)",
    )

    parser.add_argument(
        "--core-only",
        action="store_true",
        help="Trade only core pairs (BTC/USD, ETH/USD)",
    )

    # Trading mode
    parser.add_argument(
        "--mode",
        choices=["turbo", "conservative", "paper"],
        default="turbo",
        help="Trading mode (default: turbo)",
    )

    parser.add_argument(
        "--turbo-mode",
        action="store_true",
        help="Enable turbo mode (aggressive sizing)",
    )

    # Allocation settings
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=None,
        help="Maximum concurrent trading pairs (default: from config)",
    )

    parser.add_argument(
        "--allocation-cap",
        type=float,
        default=None,
        help="Per-pair allocation cap in %% (default: 10.0)",
    )

    # Capital settings
    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Total trading capital in USD (default: 10000)",
    )

    # Validation
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip trading specs validation (dangerous!)",
    )

    parser.add_argument(
        "--fail-fast",
        action="store_true",
        default=True,
        help="Skip invalid pairs instead of halting (default: True)",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print configuration and exit (don't start trading)",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    return parser.parse_args()


def validate_args(args):
    """Validate argument combinations."""
    errors = []

    # Can't use both --enable-alts and --core-only
    if args.enable_alts and args.core_only:
        errors.append("Cannot use both --enable-alts and --core-only")

    # Allocation cap must be positive and <= 100
    if args.allocation_cap is not None:
        if args.allocation_cap <= 0 or args.allocation_cap > 100:
            errors.append(f"Allocation cap must be between 0 and 100, got {args.allocation_cap}")

    # Max pairs must be positive
    if args.max_pairs is not None:
        if args.max_pairs <= 0:
            errors.append(f"Max pairs must be positive, got {args.max_pairs}")

    # Capital must be positive
    if args.capital <= 0:
        errors.append(f"Capital must be positive, got {args.capital}")

    if errors:
        for error in errors:
            logger.error(error)
        sys.exit(1)


def apply_args_to_env(args):
    """Apply CLI args to environment variables."""

    # Pair selection
    if args.enable_alts:
        os.environ["ENABLE_ALT_PAIRS"] = "true"
    elif args.core_only:
        os.environ["CORE_PAIRS_ONLY"] = "true"

    # Mode
    if args.turbo_mode or args.mode == "turbo":
        os.environ["TURBO_MODE_ENABLED"] = "true"
    os.environ["TRADING_MODE"] = args.mode

    # Allocation settings
    if args.max_pairs is not None:
        os.environ["MAX_CONCURRENT_PAIRS"] = str(args.max_pairs)

    if args.allocation_cap is not None:
        os.environ["MAX_ALLOCATION_PER_PAIR"] = str(args.allocation_cap)

    logger.info("Applied CLI args to environment")


def print_configuration(args, router, summary):
    """Print configuration summary."""
    print("\n" + "=" * 70)
    print(" " * 20 + "SCALPER CONFIGURATION")
    print("=" * 70)

    print("\n## Trading Mode ##")
    print(f"  Mode: {args.mode.upper()}")
    print(f"  Turbo: {'Yes' if args.turbo_mode or args.mode == 'turbo' else 'No'}")
    print(f"  Paper trading: {'Yes' if args.mode == 'paper' else 'No'}")

    print("\n## Capital Allocation ##")
    print(f"  Total capital: ${summary['total_capital_usd']:,.0f}")
    print(f"  Allocated: ${summary['allocated_capital_usd']:,.0f}")
    print(f"  Available: ${summary['available_capital_usd']:,.0f}")
    print(f"  Allocation rate: {(summary['allocated_capital_usd']/summary['total_capital_usd']*100):.1f}%")

    print("\n## Pair Selection ##")
    print(f"  Core only: {'Yes' if args.core_only else 'No'}")
    print(f"  Include alts: {'Yes' if args.enable_alts else 'No'}")
    print(f"  Active pairs: {summary['active_pairs_count']}")
    print(f"  Max concurrent: {router.max_concurrent_pairs}")

    print("\n## Active Pairs ##")
    for symbol, alloc in summary['pair_allocations'].items():
        print(
            f"  {symbol:12s} | "
            f"{alloc['allocation_pct']:5.1f}% | "
            f"${alloc['allocation_usd']:10,.0f} | "
            f"Priority {alloc['priority']}"
        )

    print("\n## Allocation Limits ##")
    print(f"  Per-pair cap: {router.max_allocation_per_pair:.1f}%")
    if args.allocation_cap:
        print(f"  Custom cap: {args.allocation_cap:.1f}% (override)")

    print("\n## Validation ##")
    print(f"  Skip validation: {'Yes (DANGEROUS!)' if args.skip_validation else 'No'}")
    print(f"  Fail-fast: {'Yes' if args.fail_fast else 'No'}")

    print("\n" + "=" * 70)


def main():
    """Main CLI entry point."""

    # Parse arguments
    args = parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Starting multi-pair scalper CLI")

    # Validate args
    validate_args(args)

    # Apply to environment
    apply_args_to_env(args)

    # Create allocation router
    router = AllocationRouter(
        total_capital_usd=args.capital,
        mode=args.mode,
    )

    # Override max_pairs if specified
    if args.max_pairs is not None:
        router.max_concurrent_pairs = args.max_pairs

    # Override allocation cap if specified
    if args.allocation_cap is not None:
        router.max_allocation_per_pair = args.allocation_cap

    # Get enabled pairs
    enabled_pairs = router.get_enabled_pairs(
        include_alts=args.enable_alts,
        core_only=args.core_only,
    )

    if not enabled_pairs:
        logger.error("No pairs enabled! Check configuration.")
        sys.exit(1)

    # Validate pairs (unless skipped)
    if not args.skip_validation:
        logger.info("Validating trading pairs...")

        # In production, you'd fetch real spread/liquidity data here
        # For now, using mock data
        spread_data = {
            "XBTUSD": 3.5,
            "ETHUSD": 6.0,
            "SOLUSD": 10.0,
            "ADAUSD": 12.0,
        }

        liquidity_data = {
            "XBTUSD": 2000000,
            "ETHUSD": 800000,
            "SOLUSD": 300000,
            "ADAUSD": 150000,
        }

        # Allocate capital
        state = router.allocate_capital(
            enabled_pairs,
            spread_data,
            liquidity_data,
        )

    else:
        logger.warning("Skipping validation - proceeding without checks!")

        # Allocate without validation
        state = router.allocate_capital(enabled_pairs)

    # Get summary
    summary = router.get_allocation_summary()

    # Print configuration
    print_configuration(args, router, summary)

    # Dry run check
    if args.dry_run:
        print("\n[DRY RUN] Exiting without starting trading.")
        sys.exit(0)

    # In production, this would start the actual scalper
    print("\n[INFO] Configuration complete. Ready to start trading.")
    print("[TODO] Start scalper agent with configured allocations...")

    # Return router for programmatic use
    return router, state


if __name__ == "__main__":
    main()
