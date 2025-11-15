#!/usr/bin/env python3
"""
K1 - Parameter Grid Optimizer for bar_reaction_5m

Sweeps parameter grid:
- timeframe: 5m (fixed)
- trigger_bps: {8, 10, 12, 15}
- min_atr_pct: {0.2, 0.3, 0.4}
- sl_atr: {0.5, 0.6}
- tp2_atr: {1.6, 1.8}
- maker_only: true (fixed)

Ranks by:
1. Profit Factor (desc)
2. Sharpe Ratio (desc)
3. Max Drawdown (asc)

Outputs:
- reports/opt_grid.csv - Full results ranked by PF desc, Sharpe, MaxDD asc
- reports/best_params.json - Best parameter set

Usage:
    conda activate crypto-bot
    python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 180d
    python scripts/run_backtest.py --from-json reports/best_params.json
    python scripts/B6_quality_gates.py
"""

from __future__ import annotations

import itertools
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtesting.bar_reaction_engine import (
    BarReactionBacktestEngine,
    BarReactionBacktestConfig,
)
from backtesting.metrics import BacktestResults

# Import data loading from run_backtest
from scripts.run_backtest import fetch_ohlcv, parse_lookback

logger = logging.getLogger(__name__)

# --- Configuration ---
REPORTS_DIR = project_root / "reports"

# K1 Grid parameters (per PRD spec)
GRID_PARAMS = {
    "timeframe": ["5m"],  # Fixed
    "trigger_bps": [8.0, 10.0, 12.0, 15.0],
    "min_atr_pct": [0.2, 0.3, 0.4],
    "sl_atr": [0.5, 0.6],
    "tp2_atr": [1.6, 1.8],
    "maker_only": [True],  # Fixed
}

# Fixed params from bar_reaction_5m.yaml
FIXED_PARAMS = {
    "mode": "trend",
    "trigger_mode": "open_to_close",
    "max_atr_pct": 3.0,
    "atr_window": 14,
    "tp1_atr": 1.0,
    "risk_per_trade_pct": 0.6,
    "spread_bps_cap": 8.0,
    "maker_fee_bps": 16,
    "slippage_bps": 1,
    "queue_bars": 1,
}

# Defaults
DEFAULT_LOOKBACK_DAYS = 180
INITIAL_CAPITAL = 10000.0


# --- Grid Search Functions ---


def generate_grid() -> List[Dict[str, Any]]:
    """
    Generate parameter grid from GRID_PARAMS.

    Returns:
        List of parameter dictionaries
    """
    keys = list(GRID_PARAMS.keys())
    values = list(GRID_PARAMS.values())

    # Cartesian product
    grid = []
    for combination in itertools.product(*values):
        params = dict(zip(keys, combination))

        # Set trigger_bps_down = trigger_bps (symmetric)
        params["trigger_bps_down"] = params["trigger_bps"]

        # Merge with fixed params
        params.update(FIXED_PARAMS)

        grid.append(params)

    return grid


def run_grid_point(
    pair: str,
    params: Dict[str, Any],
    start_date: str,
    end_date: str,
    capital: float,
) -> Tuple[BacktestResults, Dict]:
    """
    Run backtest for single grid point.

    Args:
        pair: Trading pair
        params: Parameter dict
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        capital: Initial capital

    Returns:
        Tuple of (BacktestResults, params_dict)
    """
    # Load data (1m for rollup to 5m)
    data = fetch_ohlcv(pair, "1m", start_date, end_date)

    if len(data) < 500:
        raise ValueError(f"Insufficient data for {pair}: {len(data)} candles")

    # Configure backtest
    config = BarReactionBacktestConfig(
        symbol=pair,
        start_date=start_date,
        end_date=end_date,
        initial_capital=capital,
        mode=params["mode"],
        trigger_mode=params["trigger_mode"],
        trigger_bps_up=params["trigger_bps"],
        trigger_bps_down=params["trigger_bps_down"],
        min_atr_pct=params["min_atr_pct"],
        max_atr_pct=params["max_atr_pct"],
        atr_window=params["atr_window"],
        sl_atr=params["sl_atr"],
        tp1_atr=params["tp1_atr"],
        tp2_atr=params["tp2_atr"],
        risk_per_trade_pct=params["risk_per_trade_pct"],
        maker_only=params["maker_only"],
        spread_bps_cap=params["spread_bps_cap"],
        maker_fee_bps=params["maker_fee_bps"],
        slippage_bps=params["slippage_bps"],
        queue_bars=params["queue_bars"],
    )

    # Run backtest
    engine = BarReactionBacktestEngine(config)
    results: BacktestResults = engine.run(data)

    # Build params dict for tracking
    params_out = {
        "pair": pair,
        "timeframe": "5m",
        "trigger_bps": params["trigger_bps"],
        "min_atr_pct": params["min_atr_pct"],
        "sl_atr": params["sl_atr"],
        "tp1_atr": params["tp1_atr"],
        "tp2_atr": params["tp2_atr"],
        "maker_only": params["maker_only"],
        "risk_per_trade_pct": params["risk_per_trade_pct"],
        "spread_bps_cap": params["spread_bps_cap"],
        "maker_fee_bps": params["maker_fee_bps"],
        "slippage_bps": params["slippage_bps"],
        "queue_bars": params["queue_bars"],
    }

    return results, params_out


def run_grid_search(
    pairs: List[str],
    grid: List[Dict[str, Any]],
    start_date: str,
    end_date: str,
    capital: float,
) -> pd.DataFrame:
    """
    Run grid search across all parameter combinations.

    Args:
        pairs: List of trading pairs
        grid: List of parameter dicts
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        capital: Initial capital

    Returns:
        DataFrame with all results
    """
    total_combinations = len(grid) * len(pairs)
    logger.info(f"Testing {total_combinations} combinations ({len(grid)} params x {len(pairs)} pairs)")
    logger.info("")

    results_list = []
    start_time = time.time()

    for params in grid:
        for pair in pairs:
            idx = len(results_list) + 1

            try:
                # Run backtest
                logger.info(
                    f"[{idx}/{total_combinations}] {pair} | "
                    f"trig={params['trigger_bps']}bps | "
                    f"min_atr={params['min_atr_pct']} | "
                    f"sl={params['sl_atr']} | "
                    f"tp2={params['tp2_atr']}"
                )

                results, params_out = run_grid_point(
                    pair=pair,
                    params=params,
                    start_date=start_date,
                    end_date=end_date,
                    capital=capital,
                )

                # Build result row
                row = {
                    # Parameters
                    "pair": pair,
                    "timeframe": params_out["timeframe"],
                    "trigger_bps": params_out["trigger_bps"],
                    "min_atr_pct": params_out["min_atr_pct"],
                    "sl_atr": params_out["sl_atr"],
                    "tp1_atr": params_out["tp1_atr"],
                    "tp2_atr": params_out["tp2_atr"],
                    "maker_only": params_out["maker_only"],
                    "risk_per_trade_pct": params_out["risk_per_trade_pct"],

                    # Performance metrics
                    "profit_factor": results.profit_factor,
                    "sharpe_ratio": results.sharpe_ratio,
                    "sortino_ratio": results.sortino_ratio,
                    "max_dd_pct": abs(results.max_drawdown_pct),
                    "total_return_pct": results.total_return_pct,
                    "cagr_pct": results.annualized_return_pct,
                    "win_rate_pct": results.win_rate_pct,

                    # Trade stats
                    "total_trades": results.total_trades,
                    "avg_win_usd": results.avg_win,
                    "avg_loss_usd": abs(results.avg_loss),

                    # Risk metrics
                    "volatility_pct": results.volatility_annualized_pct,

                    # Costs
                    "maker_fee_bps": params_out["maker_fee_bps"],
                    "slippage_bps": params_out["slippage_bps"],
                }

                results_list.append(row)

                # Quick status
                logger.info(
                    f"  Result: {results.total_trades} trades | "
                    f"PF={results.profit_factor:.2f} | "
                    f"Sharpe={results.sharpe_ratio:.2f} | "
                    f"MaxDD={abs(results.max_drawdown_pct):.2f}% | "
                    f"Return={results.total_return_pct:+.2f}%"
                )

            except Exception as e:
                logger.error(f"  [FAIL] {pair}: {e}")
                # Continue with next combination

    elapsed = time.time() - start_time
    logger.info(f"\nGrid search complete in {elapsed:.1f}s")
    logger.info(f"Successful runs: {len(results_list)}/{total_combinations}")

    # Convert to DataFrame
    df = pd.DataFrame(results_list)

    return df


def rank_results(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rank results by Profit Factor desc, then Sharpe, then MaxDD asc.

    Args:
        df: DataFrame with backtest results

    Returns:
        Sorted DataFrame
    """
    # Sort by: PF desc, Sharpe desc, MaxDD asc
    df_ranked = df.sort_values(
        by=["profit_factor", "sharpe_ratio", "max_dd_pct"],
        ascending=[False, False, True],  # PF↓, Sharpe↓, MaxDD↑
    ).reset_index(drop=True)

    # Add rank column
    df_ranked.insert(0, "rank", range(1, len(df_ranked) + 1))

    return df_ranked


def save_grid_csv(df: pd.DataFrame) -> Path:
    """
    Save grid search results to CSV.

    Args:
        df: DataFrame with results

    Returns:
        Path to saved CSV
    """
    csv_path = REPORTS_DIR / "opt_grid.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(csv_path, index=False, float_format="%.4f")
    logger.info(f"Saved grid results to {csv_path}")

    return csv_path


def save_best_params_json(df: pd.DataFrame, start_date: str, end_date: str) -> Path:
    """
    Save best parameter set to JSON (compatible with run_backtest.py --from-json).

    Args:
        df: Ranked DataFrame (best row = row 0)
        start_date: Optimization start date
        end_date: Optimization end date

    Returns:
        Path to saved JSON
    """
    if len(df) == 0:
        raise ValueError("No results to save")

    best = df.iloc[0].to_dict()

    # Build JSON structure for run_backtest.py --from-json
    params_json = {
        "optimization_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "optimized_on": f"{start_date} to {end_date}",
        "rank": int(best["rank"]),
        "pair": best["pair"],
        "timeframe": best["timeframe"],

        # Bar reaction 5m parameters
        "trigger_bps_up": float(best["trigger_bps"]),
        "trigger_bps_down": float(best["trigger_bps"]),
        "min_atr_pct": float(best["min_atr_pct"]),
        "sl_atr": float(best["sl_atr"]),
        "tp1_atr": float(best["tp1_atr"]),
        "tp2_atr": float(best["tp2_atr"]),
        "maker_only": bool(best["maker_only"]),
        "risk_per_trade_pct": float(best["risk_per_trade_pct"]),

        # For compatibility with run_backtest.py --from-json
        "position_size_pct": float(best["risk_per_trade_pct"]),
        "sl_pct": float(best["sl_atr"]) * 0.01,  # Approximate
        "tp2_pct": float(best["tp2_atr"]) * 0.01,  # Approximate

        # Performance
        "profit_factor": float(best["profit_factor"]),
        "sharpe_ratio": float(best["sharpe_ratio"]),
        "max_dd_pct": float(best["max_dd_pct"]),
        "total_return_pct": float(best["total_return_pct"]),
        "cagr_pct": float(best["cagr_pct"]),
        "win_rate_pct": float(best["win_rate_pct"]),
        "total_trades": int(best["total_trades"]),

        # Costs
        "maker_fee_bps": int(best["maker_fee_bps"]),
        "slippage_bps": int(best["slippage_bps"]),
    }

    json_path = REPORTS_DIR / "best_params.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)

    with open(json_path, "w") as f:
        json.dump(params_json, f, indent=2)

    logger.info(f"Saved best params to {json_path}")

    return json_path


def print_top_results(df: pd.DataFrame, n: int = 10) -> None:
    """
    Print top N results.

    Args:
        df: Ranked DataFrame
        n: Number of top results to show
    """
    print("\n" + "=" * 110)
    print(f"TOP {min(n, len(df))} PARAMETER COMBINATIONS")
    print("=" * 110)

    # Print header
    print(f"{'Rank':<5} {'Pair':<10} {'Trig':<6} {'MinATR':<8} {'SL':<6} {'TP2':<6} "
          f"{'PF':<7} {'Sharpe':<7} {'MaxDD%':<8} {'Return%':<9} {'Trades':<7}")
    print("-" * 110)

    # Print rows
    for _, row in df.head(n).iterrows():
        print(f"{int(row['rank']):<5} "
              f"{row['pair']:<10} "
              f"{row['trigger_bps']:<6.0f} "
              f"{row['min_atr_pct']:<8.2f} "
              f"{row['sl_atr']:<6.1f} "
              f"{row['tp2_atr']:<6.1f} "
              f"{row['profit_factor']:<7.2f} "
              f"{row['sharpe_ratio']:<7.2f} "
              f"{row['max_dd_pct']:<8.2f} "
              f"{row['total_return_pct']:<9.2f} "
              f"{int(row['total_trades']):<7}")

    print("=" * 110)


def parse_args():
    """Parse command-line arguments"""
    import argparse

    parser = argparse.ArgumentParser(
        description="K1 - Parameter Grid Optimizer for bar_reaction_5m",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single pair, 180 days
  python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 180d

  # Multiple pairs, 90 days
  python scripts/optimize_grid.py --pairs "BTC/USD,ETH/USD,SOL/USD" --lookback 90d

  # Custom capital
  python scripts/optimize_grid.py --pairs "BTC/USD" --lookback 180d --capital 50000
        """,
    )

    parser.add_argument(
        "--pairs",
        type=str,
        default="BTC/USD",
        help='Trading pairs (comma-separated, e.g., "BTC/USD,ETH/USD") (default: BTC/USD)',
    )

    parser.add_argument(
        "--lookback",
        type=str,
        default="180d",
        help="Lookback period (e.g., 180d, 1y) (default: 180d)",
    )

    parser.add_argument(
        "--capital",
        type=float,
        default=INITIAL_CAPITAL,
        help=f"Initial capital in USD (default: {INITIAL_CAPITAL})",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print("\n" + "=" * 80)
    print("K1 - PARAMETER GRID OPTIMIZER")
    print("=" * 80)
    print(f"Strategy: bar_reaction_5m")
    print(f"Maker-only execution with realistic cost model")
    print("")

    # Parse lookback
    try:
        lookback_delta = parse_lookback(args.lookback)
        end_date = datetime.now()
        start_date = end_date - lookback_delta

        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

    except ValueError as e:
        logger.error(f"Invalid lookback: {e}")
        return 1

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(",")]

    logger.info(f"Pairs: {', '.join(pairs)}")
    logger.info(f"Backtest period: {start_date_str} to {end_date_str} ({args.lookback})")
    logger.info(f"Initial capital: ${args.capital:,.0f}")
    logger.info(f"Maker fee: {FIXED_PARAMS['maker_fee_bps']}bps | Slippage: {FIXED_PARAMS['slippage_bps']}bps")
    logger.info("")

    # Generate grid
    grid = generate_grid()
    total_combinations = len(grid) * len(pairs)

    print(f"Grid Configuration:")
    print(f"  timeframe: {GRID_PARAMS['timeframe']}")
    print(f"  trigger_bps: {GRID_PARAMS['trigger_bps']}")
    print(f"  min_atr_pct: {GRID_PARAMS['min_atr_pct']}")
    print(f"  sl_atr: {GRID_PARAMS['sl_atr']}")
    print(f"  tp2_atr: {GRID_PARAMS['tp2_atr']}")
    print()
    print(f"Total combinations: {len(grid)} params x {len(pairs)} pairs = {total_combinations}")
    print()

    # Run grid search
    df_results = run_grid_search(
        pairs=pairs,
        grid=grid,
        start_date=start_date_str,
        end_date=end_date_str,
        capital=args.capital,
    )

    if len(df_results) == 0:
        logger.error("No successful backtests. Exiting.")
        return 1

    # Rank results
    logger.info("\nRanking results...")
    df_ranked = rank_results(df_results)

    # Save outputs
    logger.info("\nSaving outputs...")
    csv_path = save_grid_csv(df_ranked)
    json_path = save_best_params_json(df_ranked, start_date_str, end_date_str)

    # Print top results
    print_top_results(df_ranked, n=15)

    # Print best params
    best = df_ranked.iloc[0]
    print("\n" + "=" * 80)
    print("BEST PARAMETER SET")
    print("=" * 80)
    print(f"Pair: {best['pair']}")
    print(f"Timeframe: {best['timeframe']}")
    print(f"Trigger BPS: {best['trigger_bps']}")
    print(f"Min ATR %: {best['min_atr_pct']}")
    print(f"ATR multiples: SL={best['sl_atr']:.1f}x, TP1={best['tp1_atr']:.1f}x, TP2={best['tp2_atr']:.1f}x")
    print(f"Risk per trade: {best['risk_per_trade_pct']:.1f}%")
    print(f"Maker-only: {best['maker_only']}")
    print("")
    print("Performance:")
    print(f"  Profit Factor: {best['profit_factor']:.2f}")
    print(f"  Sharpe Ratio: {best['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {best['max_dd_pct']:.2f}%")
    print(f"  Total Return: {best['total_return_pct']:+.2f}%")
    print(f"  CAGR: {best['cagr_pct']:+.2f}%")
    print(f"  Win Rate: {best['win_rate_pct']:.1f}%")
    print(f"  Total Trades: {int(best['total_trades'])}")
    print("")
    print(f"Saved to: {json_path}")
    print("=" * 80)

    # Next steps
    print("\n" + "=" * 80)
    print("NEXT STEPS (K2)")
    print("=" * 80)
    print(f"1. Review results: cat {csv_path} | head -10")
    print(f"2. Run backtest with best params:")
    print(f"   python scripts/run_backtest.py --strategy bar_reaction_5m --pairs \"{best['pair']}\" --lookback {args.lookback}")
    print(f"3. Run quality gates:")
    print(f"   python scripts/B6_quality_gates.py")
    print("=" * 80 + "\n")

    logger.info("Optimization complete!")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Optimization failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
