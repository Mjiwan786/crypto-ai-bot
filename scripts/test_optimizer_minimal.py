#!/usr/bin/env python3
"""
Minimal Grid Optimizer Test

Tests optimizer with small parameter grid to validate functionality:
- 1 pair (BTC/USD)
- 2 timeframes (3m, 5m)
- 2 kelly values (0.2, 0.25)
- 1 ATR combination (a=0.6, b=1.0, c=1.8)
- Total: 4 backtests

Usage:
    python scripts/test_optimizer_minimal.py
"""

from __future__ import annotations

import itertools
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtesting.engine import BacktestEngine, BacktestConfig
from scripts.run_backtest import fetch_ohlcv

logger = logging.getLogger(__name__)

# Minimal grid for testing
PAIRS = ["BTC/USD"]
TIMEFRAMES = ["3m", "5m"]
KELLY_KS = [0.2, 0.25]
ATR_SLS = [0.6]
ATR_TP1S = [1.0]
ATR_TP2S = [1.8]

MAKER_FEE_BPS = 16
SLIPPAGE_BPS = 1
LOOKBACK_DAYS = 30  # Just 1 month for quick test
INITIAL_CAPITAL = 10000.0


def bps_to_pct(bps: float) -> float:
    """Convert basis points to percentage."""
    return bps / 10000.0


def main():
    """Run minimal grid test."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print("\n" + "=" * 80)
    print("MINIMAL GRID OPTIMIZER TEST")
    print("=" * 80)
    print("Quick validation of optimizer functionality")
    print("")

    # Calculate dates
    end_date = datetime.now()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    logger.info(f"Period: {start_date_str} to {end_date_str} ({LOOKBACK_DAYS}d)")
    logger.info(f"Capital: ${INITIAL_CAPITAL:,.0f}")
    logger.info(f"Costs: Maker={MAKER_FEE_BPS}bps, Slippage={SLIPPAGE_BPS}bps")
    logger.info("")

    # Generate combinations
    combinations = list(itertools.product(
        PAIRS, TIMEFRAMES, KELLY_KS, ATR_SLS, ATR_TP1S, ATR_TP2S
    ))

    total = len(combinations)
    logger.info(f"Testing {total} parameter combinations")
    logger.info(f"  Pairs: {len(PAIRS)}")
    logger.info(f"  Timeframes: {len(TIMEFRAMES)}")
    logger.info(f"  Kelly k: {len(KELLY_KS)}")
    logger.info(f"  ATR: a={ATR_SLS}, b={ATR_TP1S}, c={ATR_TP2S}")
    logger.info("")

    results_list = []
    start_time = time.time()

    for idx, (pair, tf, k, a, b, c) in enumerate(combinations, 1):
        try:
            logger.info(f"[{idx}/{total}] Testing {pair} {tf} k={k} a={a} b={b} c={c}")

            # Estimate ATR
            atr_pct = 0.02
            sl_pct = a * atr_pct
            tp_pct = c * atr_pct
            position_size_pct = k * 0.05

            # Load data
            data = fetch_ohlcv(pair, tf, start_date_str, end_date_str)

            if len(data) < 300:
                logger.warning(f"  [SKIP] Insufficient data: {len(data)} candles")
                continue

            # Configure backtest
            config = BacktestConfig(
                symbol=pair,
                start_date=start_date_str,
                end_date=end_date_str,
                initial_capital=INITIAL_CAPITAL,
                timeframe=tf,
                position_size_pct=position_size_pct,
                max_positions=1,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                commission_pct=bps_to_pct(MAKER_FEE_BPS),
                slippage_pct=bps_to_pct(SLIPPAGE_BPS),
            )

            # Run backtest
            engine = BacktestEngine(config)
            results = engine.run(data)

            # Store results
            row = {
                "pair": pair,
                "timeframe": tf,
                "kelly_k": k,
                "atr_sl_a": a,
                "atr_tp1_b": b,
                "atr_tp2_c": c,
                "profit_factor": results.profit_factor,
                "sharpe_ratio": results.sharpe_ratio,
                "max_dd_pct": abs(results.max_drawdown_pct),
                "total_return_pct": results.total_return_pct,
                "trades": results.total_trades,
            }

            results_list.append(row)

            logger.info(f"  Result: PF={results.profit_factor:.2f}, "
                       f"Sharpe={results.sharpe_ratio:.2f}, "
                       f"MaxDD={abs(results.max_drawdown_pct):.2f}%, "
                       f"Trades={results.total_trades}")

        except Exception as e:
            logger.error(f"  [FAIL] {pair} {tf}: {e}")

    elapsed = time.time() - start_time

    logger.info(f"\nTest complete in {elapsed:.1f}s")
    logger.info(f"Successful runs: {len(results_list)}/{total}")

    if len(results_list) == 0:
        logger.error("No successful backtests")
        sys.exit(1)

    # Rank results
    df = pd.DataFrame(results_list)
    df_ranked = df.sort_values(
        by=["profit_factor", "sharpe_ratio", "max_dd_pct"],
        ascending=[False, False, True]
    ).reset_index(drop=True)

    df_ranked.insert(0, "rank", range(1, len(df_ranked) + 1))

    # Print results
    print("\n" + "=" * 100)
    print("RESULTS")
    print("=" * 100)

    print(f"{'Rank':<5} {'Pair':<10} {'TF':<5} {'k':<6} {'a':<6} {'b':<6} {'c':<6} "
          f"{'PF':<7} {'Sharpe':<7} {'MaxDD%':<8} {'Return%':<9} {'Trades':<7}")
    print("-" * 100)

    for _, row in df_ranked.iterrows():
        print(f"{int(row['rank']):<5} "
              f"{row['pair']:<10} "
              f"{row['timeframe']:<5} "
              f"{row['kelly_k']:<6.2f} "
              f"{row['atr_sl_a']:<6.1f} "
              f"{row['atr_tp1_b']:<6.1f} "
              f"{row['atr_tp2_c']:<6.1f} "
              f"{row['profit_factor']:<7.2f} "
              f"{row['sharpe_ratio']:<7.2f} "
              f"{row['max_dd_pct']:<8.2f} "
              f"{row['total_return_pct']:<9.2f} "
              f"{int(row['trades']):<7}")

    # Best params
    best = df_ranked.iloc[0]
    print("\n" + "=" * 80)
    print("BEST PARAMETERS")
    print("=" * 80)
    print(f"Pair: {best['pair']}")
    print(f"Timeframe: {best['timeframe']}")
    print(f"Kelly k: {best['kelly_k']:.2f}")
    print(f"ATR: a={best['atr_sl_a']:.1f}, b={best['atr_tp1_b']:.1f}, c={best['atr_tp2_c']:.1f}")
    print("")
    print(f"Profit Factor: {best['profit_factor']:.2f}")
    print(f"Sharpe Ratio: {best['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {best['max_dd_pct']:.2f}%")
    print(f"Total Return: {best['total_return_pct']:+.2f}%")
    print(f"Trades: {int(best['trades'])}")
    print("=" * 80)

    print("\n[PASS] Minimal Grid Optimizer Test Complete\n")
    logger.info("Test successful!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
