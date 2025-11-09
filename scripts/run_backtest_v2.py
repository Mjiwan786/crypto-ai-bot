#!/usr/bin/env python3
"""
scripts/run_backtest_v2.py - Backtest CLI Tool (Step 8)

Deterministic backtesting harness with comprehensive metrics.

Usage:
    python scripts/run_backtest_v2.py \\
        --pairs BTC/USD,ETH/USD \\
        --tf 5m \\
        --lookback 720 \\
        --capital 10000 \\
        --report out/report.json \\
        --equity out/equity.csv

Features:
- Historical OHLCV replay through same strategies/risk as live
- Monthly ROI, PF, Sharpe, max DD metrics
- Deterministic execution with fixed seed
- JSON report and CSV equity curve export
- Fail-fast on DD > 20%

Per PRD §12:
- 2-3 year data across regimes
- Report monthly ROI, PF, DD, Sharpe
- Fail fast if DD > 20%

Author: Crypto AI Bot Team
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd

from backtests import BacktestConfig, BacktestRunner

logger = logging.getLogger(__name__)


# =============================================================================
# DATA LOADING
# =============================================================================

def load_ohlcv_data(
    pairs: list[str],
    timeframe: str,
    lookback_days: int,
) -> dict[str, pd.DataFrame]:
    """
    Load historical OHLCV data for pairs.

    In production, this would fetch from a data provider (CCXT, database, CSV files).
    For now, generate synthetic data for demonstration.

    Args:
        pairs: List of trading pairs
        timeframe: Timeframe (e.g., "5m")
        lookback_days: Days of historical data

    Returns:
        Dict mapping pair -> OHLCV DataFrame
    """
    logger.info(f"Loading {lookback_days}d of {timeframe} data for {len(pairs)} pairs...")

    # Parse timeframe
    timeframe_minutes = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }

    if timeframe not in timeframe_minutes:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    minutes = timeframe_minutes[timeframe]

    # Calculate number of bars
    bars_per_day = 1440 // minutes
    total_bars = lookback_days * bars_per_day

    # Generate synthetic data for each pair
    ohlcv_data = {}

    for pair in pairs:
        logger.info(f"  Generating {total_bars} bars for {pair}...")

        # Start date
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=lookback_days)

        # Generate timestamps
        timestamps = pd.date_range(
            start=start_date,
            end=end_date,
            freq=f"{minutes}min"
        )[:total_bars]

        # Base price depends on pair
        if "BTC" in pair:
            base_price = 50000.0
            volatility = 0.02
        elif "ETH" in pair:
            base_price = 3000.0
            volatility = 0.025
        elif "SOL" in pair:
            base_price = 100.0
            volatility = 0.03
        elif "ADA" in pair:
            base_price = 0.50
            volatility = 0.035
        elif "AVAX" in pair:
            base_price = 35.0
            volatility = 0.04
        else:
            base_price = 1.0
            volatility = 0.02

        # Generate price series with trend and noise
        np.random.seed(42)  # For determinism

        # Trend component (slow drift)
        trend = np.linspace(0, base_price * 0.1, total_bars)

        # Random walk component
        returns = np.random.normal(0, volatility, total_bars)
        price_multiplier = np.exp(np.cumsum(returns))

        # Close prices
        close_prices = base_price * price_multiplier + trend

        # Generate OHLC from close
        open_prices = close_prices * (1 + np.random.normal(0, volatility / 4, total_bars))
        high_prices = np.maximum(open_prices, close_prices) * (1 + np.abs(np.random.normal(0, volatility / 2, total_bars)))
        low_prices = np.minimum(open_prices, close_prices) * (1 - np.abs(np.random.normal(0, volatility / 2, total_bars)))

        # Volume (random)
        volumes = np.random.lognormal(10, 1, total_bars)

        # Create DataFrame
        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": volumes,
        })

        ohlcv_data[pair] = df

        logger.info(f"    Loaded {len(df)} bars, price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

    return ohlcv_data


# =============================================================================
# MAIN CLI
# =============================================================================

def main():
    """Main CLI entry point"""

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Run deterministic backtest with comprehensive metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic backtest
  python scripts/run_backtest_v2.py --pairs BTC/USD --lookback 365

  # Multi-pair with custom capital
  python scripts/run_backtest_v2.py --pairs BTC/USD,ETH/USD,SOL/USD --capital 50000 --lookback 720

  # Full backtest with reports
  python scripts/run_backtest_v2.py \\
      --pairs BTC/USD,ETH/USD \\
      --tf 5m \\
      --lookback 720 \\
      --capital 10000 \\
      --fee-bps 5 \\
      --slip-bps 2 \\
      --seed 42 \\
      --report out/report.json \\
      --equity out/equity.csv

Reports:
  - JSON report contains: monthly ROI, PF, Sharpe, DD, win rate, trade stats
  - CSV equity curve contains: timestamp, equity, cash, position_value, pnl
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
        "--tf",
        "--timeframe",
        type=str,
        default="5m",
        help="Timeframe (default: 5m, options: 1m, 5m, 15m, 1h, 4h, 1d)"
    )

    parser.add_argument(
        "--lookback",
        type=int,
        default=720,
        help="Lookback period in days (default: 720 = 2 years)"
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
        help="Trading fee in basis points (default: 5 = 0.05%%)"
    )

    parser.add_argument(
        "--slip-bps",
        type=float,
        default=2.0,
        help="Slippage in basis points (default: 2 = 0.02%%)"
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for determinism (default: 42)"
    )

    parser.add_argument(
        "--report",
        type=str,
        help="JSON report output path (e.g., out/report.json)"
    )

    parser.add_argument(
        "--equity",
        type=str,
        help="Equity curve CSV output path (e.g., out/equity.csv)"
    )

    parser.add_argument(
        "--max-dd",
        type=float,
        default=20.0,
        help="Maximum drawdown threshold before failing (default: 20%%)"
    )

    parser.add_argument(
        "--ml",
        "--use-ml",
        action="store_true",
        help="Enable ML confidence filter (default: disabled)"
    )

    parser.add_argument(
        "--ml-min-confidence",
        type=float,
        default=0.55,
        help="ML minimum alignment confidence (default: 0.55, range: 0.0-1.0)"
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
    logger.info("BACKTEST RUNNER")
    logger.info("="*80)

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(",")]

    logger.info(f"Pairs: {pairs}")
    logger.info(f"Timeframe: {args.tf}")
    logger.info(f"Lookback: {args.lookback} days")
    logger.info(f"Capital: ${args.capital:.2f}")
    logger.info(f"Fee: {args.fee_bps} bps ({args.fee_bps/100:.2f}%)")
    logger.info(f"Slippage: {args.slip_bps} bps ({args.slip_bps/100:.2f}%)")
    logger.info(f"Random seed: {args.seed}")
    logger.info(f"Max DD threshold: {args.max_dd}%")
    logger.info(f"ML filter: {'enabled' if args.ml else 'disabled'}")
    if args.ml:
        logger.info(f"  Min confidence: {args.ml_min_confidence:.2f}")
    logger.info("")

    # Load historical data
    try:
        ohlcv_data = load_ohlcv_data(pairs, args.tf, args.lookback)
    except Exception as e:
        logger.error(f"Failed to load OHLCV data: {e}")
        sys.exit(1)

    # Create backtest config
    from ml import MLConfig

    ml_config = MLConfig(
        enabled=args.ml,
        min_alignment_confidence=args.ml_min_confidence,
    ) if args.ml else None

    config = BacktestConfig(
        initial_capital=Decimal(str(args.capital)),
        fee_bps=Decimal(str(args.fee_bps)),
        slippage_bps=Decimal(str(args.slip_bps)),
        max_drawdown_threshold=Decimal(str(args.max_dd)),
        random_seed=args.seed,
        use_ml_filter=args.ml,
        ml_config=ml_config,
    )

    # Run backtest
    logger.info("Starting backtest...")
    logger.info("")

    runner = BacktestRunner(config=config)

    try:
        result = runner.run(
            ohlcv_data=ohlcv_data,
            pairs=pairs,
            timeframe=args.tf,
            lookback_days=args.lookback,
        )

        logger.info("")
        logger.info("="*80)
        logger.info("BACKTEST RESULTS")
        logger.info("="*80)

        # Print summary
        metrics = result.metrics

        logger.info(f"\nPeriod: {metrics.start_date.date()} to {metrics.end_date.date()} ({metrics.duration_days} days)")
        logger.info(f"\nCapital:")
        logger.info(f"  Initial: ${metrics.initial_capital:,.2f}")
        logger.info(f"  Final:   ${metrics.final_capital:,.2f}")
        logger.info(f"  Return:  ${metrics.total_return:,.2f} ({metrics.total_return_pct:.2f}%)")

        logger.info(f"\nMonthly Returns:")
        logger.info(f"  Mean:   {metrics.monthly_roi_mean:.2f}%")
        logger.info(f"  Median: {metrics.monthly_roi_median:.2f}%")
        logger.info(f"  Std:    {metrics.monthly_roi_std:.2f}%")

        logger.info(f"\nTrade Statistics:")
        logger.info(f"  Total trades:   {metrics.total_trades}")
        logger.info(f"  Winning trades: {metrics.winning_trades}")
        logger.info(f"  Losing trades:  {metrics.losing_trades}")
        logger.info(f"  Win rate:       {metrics.win_rate:.2f}%")

        logger.info(f"\nProfit Metrics:")
        logger.info(f"  Gross profit:  ${metrics.gross_profit:,.2f}")
        logger.info(f"  Gross loss:    ${metrics.gross_loss:,.2f}")
        logger.info(f"  Profit factor: {metrics.profit_factor:.2f}")
        logger.info(f"  Avg win:       ${metrics.avg_win:,.2f}")
        logger.info(f"  Avg loss:      ${metrics.avg_loss:,.2f}")
        logger.info(f"  Expectancy:    ${metrics.expectancy:,.2f}")

        logger.info(f"\nRisk Metrics:")
        logger.info(f"  Max drawdown:     {metrics.max_drawdown:.2f}%")
        logger.info(f"  Max DD duration:  {metrics.max_drawdown_duration} bars")
        logger.info(f"  Sharpe ratio:     {metrics.sharpe_ratio:.2f}")
        logger.info(f"  Sortino ratio:    {metrics.sortino_ratio:.2f}")
        logger.info(f"  Calmar ratio:     {metrics.calmar_ratio:.2f}")

        logger.info(f"\nCosts:")
        logger.info(f"  Total fees: ${metrics.total_fees:,.2f} ({metrics.fees_pct:.2f}%)")

        # Save reports
        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            result.save_report(report_path)
            logger.info(f"\n Report saved to: {report_path}")

        if args.equity:
            equity_path = Path(args.equity)
            equity_path.parent.mkdir(parents=True, exist_ok=True)
            result.save_equity_curve(equity_path)
            logger.info(f" Equity curve saved to: {equity_path}")

        logger.info("")
        logger.info("="*80)
        logger.info("BACKTEST COMPLETED SUCCESSFULLY")
        logger.info("="*80)

        sys.exit(0)

    except ValueError as e:
        logger.error("")
        logger.error("="*80)
        logger.error("BACKTEST FAILED")
        logger.error("="*80)
        logger.error(f"Error: {e}")
        logger.error("")
        logger.error("This is likely due to max drawdown exceeding threshold.")
        logger.error("Try adjusting strategy parameters or increasing --max-dd threshold.")
        logger.error("="*80)

        sys.exit(1)

    except Exception as e:
        logger.error("")
        logger.error("="*80)
        logger.error("BACKTEST ERROR")
        logger.error("="*80)
        logger.error(f"Unexpected error: {e}", exc_info=True)
        logger.error("="*80)

        sys.exit(1)


if __name__ == "__main__":
    main()
