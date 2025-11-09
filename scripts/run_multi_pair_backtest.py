#!/usr/bin/env python3
"""
Multi-Pair Backtest Runner

Runs bar_reaction_5m strategy backtest for multiple pairs and aggregates results.

Usage:
    python scripts/run_multi_pair_backtest.py --pairs BTC/USD,ETH/USD,SOL/USD,ADA/USD,AVAX/USD --lookback 180
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)


def run_single_pair_backtest(
    pair: str,
    lookback_days: int,
    capital: float,
    output_dir: Path,
) -> dict:
    """
    Run backtest for a single pair using run_bar_reaction_backtest.py

    Args:
        pair: Trading pair (e.g., "BTC/USD")
        lookback_days: Lookback period in days
        capital: Initial capital
        output_dir: Output directory for results

    Returns:
        Dict with backtest results
    """
    # Clean pair name for filename (BTC/USD -> BTC_USD)
    pair_clean = pair.replace("/", "_")
    output_file = output_dir / f"{pair_clean}_{lookback_days}d.json"

    logger.info(f"Running backtest for {pair} ({lookback_days} days)...")

    # Build command
    cmd = [
        sys.executable,
        "scripts/run_bar_reaction_backtest.py",
        "--lookback", str(lookback_days),
        "--capital", str(capital),
        "--output", str(output_file),
    ]

    # Run backtest
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=project_root,
        )

        # Load results
        if output_file.exists():
            with open(output_file, 'r') as f:
                results = json.load(f)

            logger.info(f"  {pair}: Return={results.get('total_return_pct', 0):.2f}%, Trades={results.get('total_trades', 0)}")
            return results
        else:
            logger.error(f"  {pair}: Output file not created")
            return None

    except subprocess.CalledProcessError as e:
        logger.error(f"  {pair}: Backtest failed")
        logger.error(f"  stdout: {e.stdout}")
        logger.error(f"  stderr: {e.stderr}")
        return None


def aggregate_results(pair_results: dict) -> dict:
    """
    Aggregate results from multiple pairs

    Args:
        pair_results: Dict mapping pair -> results

    Returns:
        Aggregated metrics
    """
    total_trades = sum(r.get('total_trades', 0) for r in pair_results.values() if r)
    total_wins = sum(r.get('winning_trades', 0) for r in pair_results.values() if r)
    total_losses = sum(r.get('losing_trades', 0) for r in pair_results.values() if r)

    # Calculate weighted average return (by number of trades)
    weighted_return = 0.0
    total_weight = 0
    for pair, results in pair_results.items():
        if results and results.get('total_trades', 0) > 0:
            weight = results['total_trades']
            weighted_return += results.get('total_return_pct', 0) * weight
            total_weight += weight

    avg_return = weighted_return / total_weight if total_weight > 0 else 0.0

    # Calculate average metrics
    valid_results = [r for r in pair_results.values() if r]
    avg_win_rate = sum(r.get('win_rate_pct', 0) for r in valid_results) / len(valid_results) if valid_results else 0.0
    avg_profit_factor = sum(r.get('profit_factor', 0) for r in valid_results) / len(valid_results) if valid_results else 0.0
    avg_sharpe = sum(r.get('sharpe_ratio', 0) for r in valid_results) / len(valid_results) if valid_results else 0.0
    max_dd = max((r.get('max_dd_pct', 0) for r in valid_results), default=0.0)

    return {
        'pairs': list(pair_results.keys()),
        'pairs_successful': len(valid_results),
        'pairs_failed': len([r for r in pair_results.values() if not r]),
        'total_trades': total_trades,
        'winning_trades': total_wins,
        'losing_trades': total_losses,
        'avg_return_pct': avg_return,
        'avg_win_rate_pct': avg_win_rate,
        'avg_profit_factor': avg_profit_factor,
        'avg_sharpe_ratio': avg_sharpe,
        'max_drawdown_pct': max_dd,
        'pair_results': pair_results,
        'timestamp': datetime.now().isoformat(),
    }


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Run multi-pair backtest with bar_reaction_5m strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--pairs",
        type=str,
        required=True,
        help="Comma-separated trading pairs (e.g., BTC/USD,ETH/USD,SOL/USD)"
    )

    parser.add_argument(
        "--lookback",
        type=int,
        default=180,
        help="Lookback period in days (default: 180)"
    )

    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Initial capital per pair (default: 10000)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default="out/backtests/multi_pair_results.json",
        help="Output file for aggregated results"
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    logger.info("="*80)
    logger.info("MULTI-PAIR BACKTEST RUNNER")
    logger.info("="*80)

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(",")]
    logger.info(f"Pairs: {pairs}")
    logger.info(f"Lookback: {args.lookback} days")
    logger.info(f"Capital per pair: ${args.capital:.2f}")
    logger.info("")

    # Create output directory
    output_path = Path(args.output)
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run backtests for each pair
    pair_results = {}
    for pair in pairs:
        result = run_single_pair_backtest(
            pair=pair,
            lookback_days=args.lookback,
            capital=args.capital,
            output_dir=output_dir,
        )
        pair_results[pair] = result

    logger.info("")
    logger.info("="*80)
    logger.info("AGGREGATED RESULTS")
    logger.info("="*80)

    # Aggregate results
    aggregated = aggregate_results(pair_results)

    logger.info(f"Pairs successful: {aggregated['pairs_successful']}/{len(pairs)}")
    logger.info(f"Pairs failed: {aggregated['pairs_failed']}/{len(pairs)}")
    logger.info(f"Total trades: {aggregated['total_trades']}")
    logger.info(f"Win rate: {aggregated['avg_win_rate_pct']:.2f}%")
    logger.info(f"Avg return: {aggregated['avg_return_pct']:.2f}%")
    logger.info(f"Avg profit factor: {aggregated['avg_profit_factor']:.2f}")
    logger.info(f"Avg Sharpe: {aggregated['avg_sharpe_ratio']:.2f}")
    logger.info(f"Max drawdown: {aggregated['max_drawdown_pct']:.2f}%")
    logger.info("")

    # Individual pair results
    logger.info("Individual Pair Results:")
    for pair, results in pair_results.items():
        if results:
            logger.info(
                f"  {pair:12s}: Return={results.get('total_return_pct', 0):7.2f}%, "
                f"Trades={results.get('total_trades', 0):4d}, "
                f"Win%={results.get('win_rate_pct', 0):5.2f}%, "
                f"PF={results.get('profit_factor', 0):5.2f}, "
                f"DD={results.get('max_dd_pct', 0):5.2f}%"
            )
        else:
            logger.info(f"  {pair:12s}: FAILED")

    # Save results
    with open(output_path, 'w') as f:
        json.dump(aggregated, f, indent=2)

    logger.info("")
    logger.info(f"Results saved to: {output_path}")
    logger.info("="*80)

    # Exit with success if at least one pair succeeded
    if aggregated['pairs_successful'] > 0:
        sys.exit(0)
    else:
        logger.error("All pairs failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
