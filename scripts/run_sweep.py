#!/usr/bin/env python3
"""
scripts/run_sweep.py - Parameter Sweep CLI Tool (Step 10)

Automated parameter optimization with grid and Bayesian search.

Usage:
    # Grid search (exhaustive)
    python scripts/run_sweep.py --pairs BTC/USD --lookback 365 --method grid

    # Bayesian search (sample-efficient)
    python scripts/run_sweep.py --pairs BTC/USD --lookback 720 --method bayesian --samples 50

    # Custom constraints
    python scripts/run_sweep.py \
        --pairs BTC/USD,ETH/USD \
        --lookback 720 \
        --method grid \
        --max-dd 15.0 \
        --min-roi 12.0 \
        --top-k 10

Features:
- Grid search: exhaustive search over parameter space
- Bayesian search: quasi-random Sobol sampling
- KPI constraint validation (DD ≤ 20%, ROI ≥ 10%)
- Saves top-k parameter sets to YAML files
- Generates markdown summary report
- Progress logging

Per PRD §10:
- Maximize PF subject to DD ≤ 20% and monthly ROI ≥ 10%
- Search MA lengths, BB width, RR min, SL multipliers, ML confidence threshold
- Save top-k param sets to config/params/top/
- Generate out/sweep_summary.md report

Author: Crypto AI Bot Team
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tuning import ParameterSweep, ParameterSpace, SweepConfig

logger = logging.getLogger(__name__)


# =============================================================================
# MAIN CLI
# =============================================================================

def main():
    """Main CLI entry point"""

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Run parameter sweep with grid or Bayesian search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick grid search (small parameter space)
  python scripts/run_sweep.py --pairs BTC/USD --lookback 365 --method grid

  # Bayesian search (sample-efficient)
  python scripts/run_sweep.py --pairs BTC/USD --lookback 720 --method bayesian --samples 50

  # Multi-pair with custom constraints
  python scripts/run_sweep.py \
      --pairs BTC/USD,ETH/USD \
      --lookback 720 \
      --method grid \
      --max-dd 15.0 \
      --min-roi 12.0 \
      --top-k 10 \
      --output config/params/top \
      --report out/sweep_summary.md

  # Define custom parameter space
  python scripts/run_sweep.py \
      --pairs BTC/USD \
      --lookback 365 \
      --method grid \
      --ma-short 5,10,20 \
      --ma-long 20,50,100 \
      --bb-width 1.5,2.0,2.5 \
      --rr-min 1.5,2.0,2.5,3.0 \
      --sl-mult 1.0,1.5,2.0 \
      --ml-conf 0.50,0.55,0.60,0.65 \
      --risk-pct 0.01,0.015,0.02

Results:
  - Top-k parameter sets saved to: config/params/top/
  - Summary report saved to: out/sweep_summary.md
  - Each param set includes metrics, constraints, and configuration
        """
    )

    # Required arguments
    parser.add_argument(
        "--pairs",
        type=str,
        required=True,
        help="Comma-separated trading pairs (e.g., BTC/USD,ETH/USD)"
    )

    # Optional arguments
    parser.add_argument(
        "--method",
        type=str,
        choices=["grid", "bayesian"],
        default="grid",
        help="Search method (default: grid)"
    )

    parser.add_argument(
        "--lookback",
        type=int,
        default=720,
        help="Lookback period in days (default: 720)"
    )

    parser.add_argument(
        "--tf",
        "--timeframe",
        type=str,
        default="5m",
        help="Timeframe (default: 5m)"
    )

    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Initial capital (default: 10000)"
    )

    parser.add_argument(
        "--fee-bps",
        type=float,
        default=5.0,
        help="Trading fee in basis points (default: 5)"
    )

    parser.add_argument(
        "--slip-bps",
        type=float,
        default=2.0,
        help="Slippage in basis points (default: 2)"
    )

    parser.add_argument(
        "--max-dd",
        type=float,
        default=20.0,
        help="Maximum drawdown constraint (default: 20%%)"
    )

    parser.add_argument(
        "--min-roi",
        type=float,
        default=10.0,
        help="Minimum monthly ROI constraint (default: 10%%)"
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of top parameter sets to save (default: 5)"
    )

    parser.add_argument(
        "--samples",
        type=int,
        help="Number of samples for Bayesian search (default: grid_size/10)"
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default="config/params/top",
        help="Output directory for parameter YAML files (default: config/params/top)"
    )

    parser.add_argument(
        "--report",
        type=str,
        default="out/sweep_summary.md",
        help="Report output path (default: out/sweep_summary.md)"
    )

    # Parameter space definition
    parser.add_argument(
        "--ma-short",
        type=str,
        help="MA short periods (comma-separated, e.g., 5,10,20)"
    )

    parser.add_argument(
        "--ma-long",
        type=str,
        help="MA long periods (comma-separated, e.g., 20,50,100)"
    )

    parser.add_argument(
        "--bb-width",
        type=str,
        help="Bollinger Band widths (comma-separated, e.g., 1.5,2.0,2.5)"
    )

    parser.add_argument(
        "--rr-min",
        type=str,
        help="Risk-reward ratios (comma-separated, e.g., 1.5,2.0,2.5,3.0)"
    )

    parser.add_argument(
        "--sl-mult",
        type=str,
        help="Stop-loss multipliers (comma-separated, e.g., 1.0,1.5,2.0)"
    )

    parser.add_argument(
        "--ml-conf",
        type=str,
        help="ML confidence thresholds (comma-separated, e.g., 0.50,0.55,0.60)"
    )

    parser.add_argument(
        "--risk-pct",
        type=str,
        help="Risk percentages (comma-separated, e.g., 0.01,0.015,0.02)"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    logger.info("="*80)
    logger.info("PARAMETER SWEEP")
    logger.info("="*80)

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(",")]

    logger.info(f"Pairs: {pairs}")
    logger.info(f"Method: {args.method}")
    logger.info(f"Lookback: {args.lookback} days")
    logger.info(f"Timeframe: {args.tf}")
    logger.info(f"Capital: ${args.capital:,.2f}")
    logger.info(f"Constraints: DD ≤ {args.max_dd}%, ROI ≥ {args.min_roi}%")
    logger.info(f"Top-k: {args.top_k}")
    logger.info("")

    # Create parameter space
    param_space = ParameterSpace()

    # Override with custom values if provided
    if args.ma_short:
        param_space.ma_short_periods = [int(x) for x in args.ma_short.split(",")]
    if args.ma_long:
        param_space.ma_long_periods = [int(x) for x in args.ma_long.split(",")]
    if args.bb_width:
        param_space.bb_width = [float(x) for x in args.bb_width.split(",")]
    if args.rr_min:
        param_space.rr_min = [float(x) for x in args.rr_min.split(",")]
    if args.sl_mult:
        param_space.sl_multiplier = [float(x) for x in args.sl_mult.split(",")]
    if args.ml_conf:
        param_space.ml_min_confidence = [float(x) for x in args.ml_conf.split(",")]
    if args.risk_pct:
        param_space.risk_pct = [float(x) for x in args.risk_pct.split(",")]

    logger.info("Parameter space:")
    logger.info(f"  MA short: {param_space.ma_short_periods}")
    logger.info(f"  MA long: {param_space.ma_long_periods}")
    logger.info(f"  BB width: {param_space.bb_width}")
    logger.info(f"  RR min: {param_space.rr_min}")
    logger.info(f"  SL multiplier: {param_space.sl_multiplier}")
    logger.info(f"  ML confidence: {param_space.ml_min_confidence}")
    logger.info(f"  Risk %: {param_space.risk_pct}")
    logger.info(f"  Total combinations: {param_space.grid_size()}")
    logger.info("")

    # Create sweep config
    config = SweepConfig(
        pairs=pairs,
        lookback_days=args.lookback,
        timeframe=args.tf,
        initial_capital=args.capital,
        fee_bps=args.fee_bps,
        slippage_bps=args.slip_bps,
        max_dd_threshold=args.max_dd,
        min_monthly_roi=args.min_roi,
        top_k=args.top_k,
        random_seed=args.seed,
        param_space=param_space,
    )

    # Run sweep
    try:
        logger.info("Initializing sweep engine...")
        sweep = ParameterSweep(config=config)

        logger.info(f"Running {args.method} search...")
        logger.info("")

        results = sweep.run(method=args.method, n_samples=args.samples)

        logger.info("")
        logger.info("="*80)
        logger.info("SWEEP COMPLETED")
        logger.info("="*80)

        # Summary statistics
        total_evaluated = len(results)
        meets_constraints = sum(1 for r in results if r.meets_constraints)

        logger.info(f"\nResults:")
        logger.info(f"  Total evaluated: {total_evaluated}")
        logger.info(f"  Meets constraints: {meets_constraints} ({meets_constraints/max(1,total_evaluated)*100:.1f}%)")

        if meets_constraints > 0:
            logger.info(f"\n Top result:")
            top = results[0]
            logger.info(f"    Profit Factor: {top.profit_factor:.2f}")
            logger.info(f"    Max Drawdown: {top.max_drawdown:.2f}%")
            logger.info(f"    Monthly ROI: {top.monthly_roi_mean:.2f}%")
            logger.info(f"    Sharpe Ratio: {top.sharpe_ratio:.2f}")
            logger.info(f"    Total Trades: {top.total_trades}")
            logger.info(f"    Win Rate: {top.win_rate:.2f}%")
        else:
            logger.warning("\n  No parameter set meets KPI constraints!")
            logger.warning("  Consider relaxing constraints or expanding parameter space.")

        # Save results
        logger.info("")
        logger.info("Saving results...")

        sweep.save_top_params(args.output)
        sweep.generate_report(args.report)

        logger.info("")
        logger.info(f" Parameter sets saved to: {args.output}/")
        logger.info(f" Report saved to: {args.report}")

        logger.info("")
        logger.info("="*80)
        logger.info("SWEEP COMPLETED SUCCESSFULLY")
        logger.info("="*80)

        sys.exit(0)

    except Exception as e:
        logger.error("")
        logger.error("="*80)
        logger.error("SWEEP FAILED")
        logger.error("="*80)
        logger.error(f"Error: {e}", exc_info=True)
        logger.error("="*80)

        sys.exit(1)


if __name__ == "__main__":
    main()
