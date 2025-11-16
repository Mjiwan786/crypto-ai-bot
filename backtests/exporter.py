"""
backtests/exporter.py - Per-Pair Backtest Exporter

Converts backtest results to TradingView-style JSON artifacts for UI consumption.

Functionality:
- Converts BacktestResult to BacktestFile schema
- Generates per-pair JSON exports (data/backtests/{symbol}.json)
- CLI for running backtests and exporting results
- Production-safe: timezone-aware UTC, Docker/Fly.io compatible

Usage:
    # Export backtest for BTC/USD
    python -m backtests.exporter --symbol BTC/USD --timeframe 1h --output data/backtests

    # Export for multiple pairs
    python -m backtests.exporter --symbol BTC/USD,ETH/USD,SOL/USD --timeframe 1h

    # Custom parameters
    python -m backtests.exporter \\
        --symbol ETH/USD \\
        --timeframe 1m \\
        --lookback-days 90 \\
        --capital 10000 \\
        --output data/backtests

Author: Crypto AI Bot Team
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

import pandas as pd

from backtests.runner import BacktestRunner, BacktestConfig, BacktestResult
from backtests.metrics import Trade as RunnerTrade, EquityPoint as RunnerEquityPoint
from backtests.schema import (
    BacktestFile,
    Trade,
    EquityPoint,
    TradeSide,
    ExitReason,
    normalize_symbol,
    get_backtest_file_path,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONVERSION FUNCTIONS
# =============================================================================

def convert_equity_point(point: RunnerEquityPoint) -> EquityPoint:
    """
    Convert runner EquityPoint to export schema EquityPoint.

    Args:
        point: Runner equity point

    Returns:
        Export schema equity point
    """
    # Ensure timestamp is timezone-aware UTC
    ts = point.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    return EquityPoint(
        ts=ts,
        equity=float(point.equity),
        balance=float(point.cash) if point.cash is not None else None,
        unrealized_pnl=float(point.position_value) if point.position_value is not None else None,
    )


def convert_trade(trade: RunnerTrade, trade_id: int, cumulative_pnl: float) -> Trade:
    """
    Convert runner Trade to export schema Trade.

    Args:
        trade: Runner trade
        trade_id: Sequential trade ID
        cumulative_pnl: Cumulative P&L after this trade

    Returns:
        Export schema trade
    """
    # Ensure timestamps are timezone-aware UTC
    ts_entry = trade.entry_time
    ts_exit = trade.exit_time
    if ts_entry.tzinfo is None:
        ts_entry = ts_entry.replace(tzinfo=timezone.utc)
    if ts_exit.tzinfo is None:
        ts_exit = ts_exit.replace(tzinfo=timezone.utc)

    # Convert side
    side = TradeSide.LONG if trade.side.lower() == "long" else TradeSide.SHORT

    # Infer exit reason (not stored in runner trade)
    # For now, we'll use a simple heuristic based on P&L
    exit_reason = None
    if float(trade.pnl) > 0:
        exit_reason = ExitReason.TAKE_PROFIT
    elif float(trade.pnl) < 0:
        exit_reason = ExitReason.STOP_LOSS
    else:
        exit_reason = ExitReason.TIME_EXIT

    return Trade(
        id=trade_id,
        ts_entry=ts_entry,
        ts_exit=ts_exit,
        side=side,
        entry_price=float(trade.entry_price),
        exit_price=float(trade.exit_price),
        size=float(trade.size),
        net_pnl=float(trade.pnl),
        runup=None,  # Not tracked by runner
        drawdown=None,  # Not tracked by runner
        cumulative_pnl=cumulative_pnl,
        signal=trade.strategy if hasattr(trade, 'strategy') else None,
        exit_reason=exit_reason,
    )


def convert_backtest_result(result: BacktestResult, symbol: str) -> BacktestFile:
    """
    Convert BacktestResult to BacktestFile export schema.

    Args:
        result: Backtest result from runner
        symbol: Trading symbol (e.g., "BTC/USD")

    Returns:
        Export schema backtest file
    """
    # Ensure timestamps are timezone-aware UTC
    start_ts = result.start_date
    end_ts = result.end_date
    if start_ts.tzinfo is None:
        start_ts = start_ts.replace(tzinfo=timezone.utc)
    if end_ts.tzinfo is None:
        end_ts = end_ts.replace(tzinfo=timezone.utc)

    # Convert equity curve
    equity_curve = [convert_equity_point(point) for point in result.equity_curve]

    # Convert trades with cumulative P&L tracking
    trades = []
    cumulative_pnl = 0.0
    for idx, runner_trade in enumerate(result.trades, start=1):
        cumulative_pnl += float(runner_trade.pnl)
        export_trade = convert_trade(runner_trade, trade_id=idx, cumulative_pnl=cumulative_pnl)
        trades.append(export_trade)

    # Extract metrics
    metrics = result.metrics

    return BacktestFile(
        symbol=symbol,
        symbol_id=normalize_symbol(symbol),
        timeframe=result.timeframe,
        start_ts=start_ts,
        end_ts=end_ts,
        equity_curve=equity_curve,
        trades=trades,
        initial_capital=float(metrics.initial_capital),
        final_equity=float(metrics.final_capital),
        total_return_pct=float(metrics.total_return_pct),
        sharpe_ratio=float(metrics.sharpe_ratio),
        max_drawdown_pct=float(metrics.max_drawdown),
        win_rate_pct=float(metrics.win_rate),
        total_trades=metrics.total_trades,
        profit_factor=float(metrics.profit_factor),
    )


# =============================================================================
# EXPORT FUNCTIONS
# =============================================================================

def export_backtest_to_json(
    backtest_file: BacktestFile,
    output_dir: str = "data/backtests",
    indent: int = 2,
) -> Path:
    """
    Export BacktestFile to JSON file.

    Args:
        backtest_file: Backtest data to export
        output_dir: Output directory (default: data/backtests)
        indent: JSON indentation (default: 2)

    Returns:
        Path to created file
    """
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Get file path
    file_path = output_path / f"{backtest_file.symbol_id}.json"

    # Convert to dict and serialize
    data = backtest_file.model_dump(mode='json')

    # Write to file
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=indent, default=str)

    logger.info(f"Exported backtest to {file_path}")
    return file_path


# =============================================================================
# BACKTEST EXECUTION + EXPORT
# =============================================================================

def run_and_export_backtest(
    symbol: str,
    timeframe: str = "1h",
    lookback_days: int = 90,
    initial_capital: float = 10000.0,
    output_dir: str = "data/backtests",
) -> Path:
    """
    Run backtest for a symbol and export to JSON.

    This is a convenience function that:
    1. Loads historical data
    2. Runs backtest via BacktestRunner
    3. Converts to export schema
    4. Writes JSON file

    Args:
        symbol: Trading pair (e.g., "BTC/USD")
        timeframe: Candle timeframe (default: "1h")
        lookback_days: Days of history to backtest (default: 90)
        initial_capital: Starting capital (default: 10000.0)
        output_dir: Output directory (default: "data/backtests")

    Returns:
        Path to exported JSON file

    Raises:
        ValueError: If data loading or backtest fails
    """
    logger.info(f"Running backtest: {symbol} @ {timeframe} for {lookback_days} days")

    # Load historical data (placeholder - you'll need to implement data loading)
    # For now, we'll assume data is already available
    try:
        from backtesting.data_loader import DataLoader

        loader = DataLoader(exchange="kraken")
        end_date = datetime.now(timezone.utc)
        start_date = end_date - pd.Timedelta(days=lookback_days)

        ohlcv_data = loader.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
        )

        logger.info(f"Loaded {len(ohlcv_data)} candles")

    except ImportError:
        logger.error("DataLoader not available. Please implement data loading.")
        raise ValueError("Data loading not implemented")
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        raise

    # Run backtest
    config = BacktestConfig(
        initial_capital=Decimal(str(initial_capital)),
        random_seed=42,
    )

    runner = BacktestRunner(config=config)

    result = runner.run(
        ohlcv_data={symbol: ohlcv_data},
        pairs=[symbol],
        timeframe=timeframe,
        lookback_days=lookback_days,
    )

    # Convert to export schema
    export_data = convert_backtest_result(result, symbol)

    # Export to JSON
    file_path = export_backtest_to_json(export_data, output_dir=output_dir)

    return file_path


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Export per-pair backtests to TradingView-style JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--symbol",
        type=str,
        required=True,
        help="Trading pair(s) to backtest (comma-separated, e.g., 'BTC/USD,ETH/USD')",
    )

    parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        choices=["1m", "5m", "15m", "1h", "4h", "1d"],
        help="Candle timeframe (default: 1h)",
    )

    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="Days of history to backtest (default: 90)",
    )

    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Initial capital in USD (default: 10000)",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="data/backtests",
        help="Output directory (default: data/backtests)",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    return parser.parse_args()


def main():
    """Main CLI entry point"""
    args = parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("=" * 70)
    logger.info("BACKTEST EXPORTER - Per-Pair JSON Export")
    logger.info("=" * 70)

    # Parse symbols
    symbols = [s.strip() for s in args.symbol.split(",")]
    logger.info(f"Symbols: {symbols}")
    logger.info(f"Timeframe: {args.timeframe}")
    logger.info(f"Lookback: {args.lookback_days} days")
    logger.info(f"Capital: ${args.capital:,.2f}")
    logger.info(f"Output: {args.output}")
    logger.info("")

    # Run backtests
    success_count = 0
    fail_count = 0

    for symbol in symbols:
        try:
            logger.info(f"Processing {symbol}...")
            file_path = run_and_export_backtest(
                symbol=symbol,
                timeframe=args.timeframe,
                lookback_days=args.lookback_days,
                initial_capital=args.capital,
                output_dir=args.output,
            )
            logger.info(f"✓ Success: {file_path}")
            success_count += 1

        except Exception as e:
            logger.error(f"✗ Failed: {symbol} - {e}")
            fail_count += 1
            import traceback
            traceback.print_exc()

    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"SUMMARY: {success_count} succeeded, {fail_count} failed")
    logger.info("=" * 70)

    # Exit code
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "convert_equity_point",
    "convert_trade",
    "convert_backtest_result",
    "export_backtest_to_json",
    "run_and_export_backtest",
]
