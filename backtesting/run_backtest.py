"""
Command-line interface for running backtests.

Usage:
    # Quick backtest (1 year, default settings)
    python -m backtesting.run_backtest --symbol BTC/USD --capital 10000

    # Full backtest with custom parameters
    python -m backtesting.run_backtest \\
        --symbol BTC/USD \\
        --start-date 2022-01-01 \\
        --end-date 2024-01-01 \\
        --capital 10000 \\
        --timeframe 1h \\
        --position-size 0.02 \\
        --stop-loss 0.02 \\
        --take-profit 0.04

    # Save results to file
    python -m backtesting.run_backtest \\
        --symbol ETH/USD \\
        --capital 10000 \\
        --output results/eth_backtest.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from backtesting.data_loader import DataLoader
from backtesting.engine import BacktestEngine, BacktestConfig

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run strategy backtest against historical data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required arguments
    parser.add_argument(
        "--symbol",
        type=str,
        required=True,
        help="Trading symbol (e.g., BTC/USD, ETH/USD)",
    )

    parser.add_argument(
        "--capital",
        type=float,
        required=True,
        help="Initial capital in USD",
    )

    # Date range
    parser.add_argument(
        "--start-date",
        type=str,
        default=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
        help="Start date (YYYY-MM-DD). Default: 1 year ago",
    )

    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date (YYYY-MM-DD). Default: today",
    )

    # Trading parameters
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        choices=["1m", "5m", "15m", "1h", "4h", "1d"],
        help="Candle timeframe. Default: 1h",
    )

    parser.add_argument(
        "--position-size",
        type=float,
        default=0.02,
        help="Position size as fraction of capital (0.02 = 2%%). Default: 0.02",
    )

    parser.add_argument(
        "--max-positions",
        type=int,
        default=1,
        help="Maximum concurrent positions. Default: 1",
    )

    parser.add_argument(
        "--stop-loss",
        type=float,
        default=0.02,
        help="Stop loss percentage (0.02 = 2%%). Default: 0.02",
    )

    parser.add_argument(
        "--take-profit",
        type=float,
        default=0.04,
        help="Take profit percentage (0.04 = 4%%). Default: 0.04",
    )

    # Transaction costs
    parser.add_argument(
        "--commission",
        type=float,
        default=0.001,
        help="Commission per trade (0.001 = 0.1%%). Default: 0.001",
    )

    parser.add_argument(
        "--slippage",
        type=float,
        default=0.0005,
        help="Slippage per trade (0.0005 = 0.05%%). Default: 0.0005",
    )

    # Strategy parameters
    parser.add_argument(
        "--min-confidence-open",
        type=float,
        default=0.55,
        help="Minimum confidence to open position (0-1). Default: 0.55",
    )

    parser.add_argument(
        "--min-confidence-close",
        type=float,
        default=0.35,
        help="Minimum confidence to keep position (0-1). Default: 0.35",
    )

    # Data source
    parser.add_argument(
        "--exchange",
        type=str,
        default="kraken",
        help="Exchange for historical data. Default: kraken",
    )

    # Output
    parser.add_argument(
        "--output",
        type=str,
        help="Save results to JSON file (optional)",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level. Default: INFO",
    )

    return parser.parse_args()


def save_results_json(results, output_path: str):
    """Save backtest results to JSON file."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Convert results to dict (some fields need special handling)
    results_dict = {
        "config": {
            "symbol": results.symbol,
            "start_date": results.start_date,
            "end_date": results.end_date,
            "initial_capital": results.initial_capital,
            "timeframe": results.timeframe,
        },
        "performance": {
            "total_return": results.total_return,
            "total_return_pct": results.total_return_pct,
            "annualized_return_pct": results.annualized_return_pct,
        },
        "risk": {
            "sharpe_ratio": results.sharpe_ratio,
            "sortino_ratio": results.sortino_ratio,
            "max_drawdown": results.max_drawdown,
            "max_drawdown_pct": results.max_drawdown_pct,
            "max_drawdown_duration_days": results.max_drawdown_duration_days,
            "volatility_annualized_pct": results.volatility_annualized_pct,
        },
        "trades": {
            "total_trades": results.total_trades,
            "winning_trades": results.winning_trades,
            "losing_trades": results.losing_trades,
            "win_rate_pct": results.win_rate_pct,
            "avg_win": results.avg_win,
            "avg_loss": results.avg_loss,
            "profit_factor": results.profit_factor,
            "expectancy": results.expectancy,
        },
        "ratios": {
            "calmar_ratio": results.calmar_ratio,
            "recovery_factor": results.recovery_factor,
        },
    }

    with open(output_file, "w") as f:
        json.dump(results_dict, f, indent=2)

    logger.info(f"Results saved to: {output_file}")


def main():
    """Main entry point."""
    args = parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("=" * 70)
    logger.info("CRYPTO AI BOT - BACKTESTING")
    logger.info("=" * 70)

    # Validate date range
    try:
        start = datetime.strptime(args.start_date, "%Y-%m-%d")
        end = datetime.strptime(args.end_date, "%Y-%m-%d")

        if start >= end:
            logger.error("Start date must be before end date")
            sys.exit(1)

        days = (end - start).days
        if days < 30:
            logger.warning(f"Short backtest period: {days} days. Recommend at least 90 days.")

    except ValueError as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)

    # Step 1: Load historical data
    logger.info(f"\nStep 1/3: Loading historical data...")
    logger.info(f"  Symbol: {args.symbol}")
    logger.info(f"  Period: {args.start_date} to {args.end_date} ({days} days)")
    logger.info(f"  Timeframe: {args.timeframe}")
    logger.info(f"  Exchange: {args.exchange}")

    try:
        loader = DataLoader(args.exchange)
        data = loader.fetch_ohlcv(
            args.symbol,
            args.timeframe,
            args.start_date,
            args.end_date,
        )

        logger.info(f"  Loaded {len(data)} candles")

        if len(data) < 300:
            logger.error(f"Insufficient data: {len(data)} candles, need at least 300")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 2: Configure and run backtest
    logger.info(f"\nStep 2/3: Running backtest...")
    logger.info(f"  Initial capital: ${args.capital:,.2f}")
    logger.info(f"  Position size: {args.position_size*100:.1f}%")
    logger.info(f"  Max positions: {args.max_positions}")
    logger.info(f"  Stop loss: {args.stop_loss*100:.1f}%")
    logger.info(f"  Take profit: {args.take_profit*100:.1f}%")

    config = BacktestConfig(
        symbol=args.symbol,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.capital,
        timeframe=args.timeframe,
        position_size_pct=args.position_size,
        max_positions=args.max_positions,
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
        commission_pct=args.commission,
        slippage_pct=args.slippage,
        min_confidence_to_open=args.min_confidence_open,
        min_confidence_to_close=args.min_confidence_close,
    )

    try:
        engine = BacktestEngine(config)
        results = engine.run(data)

    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 3: Display and save results
    logger.info(f"\nStep 3/3: Processing results...")

    results.print_summary()

    if args.output:
        save_results_json(results, args.output)

    # Exit with appropriate code
    if results.total_return_pct > 0:
        logger.info("Backtest completed: PROFITABLE")
        sys.exit(0)
    else:
        logger.info("Backtest completed: NOT PROFITABLE")
        sys.exit(1)


if __name__ == "__main__":
    main()
