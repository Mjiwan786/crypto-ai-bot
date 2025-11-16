#!/usr/bin/env python
"""
scripts/demo_backtest_export.py - Demo backtest export generation

Creates sample per-pair backtest exports to demonstrate schema and format.
Useful for testing the API and UI without running full backtests.

Usage:
    python scripts/demo_backtest_export.py

Generates:
    data/backtests/BTC-USD.json
    data/backtests/ETH-USD.json

Author: Crypto AI Bot Team
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from backtests.schema import (
    BacktestFile,
    EquityPoint,
    Trade,
    TradeSide,
    ExitReason,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_sample_equity_curve(
    initial_capital: float,
    num_points: int,
    total_return_pct: float,
    start_date: datetime,
) -> list[EquityPoint]:
    """
    Generate a sample equity curve with realistic ups and downs.

    Args:
        initial_capital: Starting equity
        num_points: Number of points in curve
        total_return_pct: Total return percentage
        start_date: Start timestamp

    Returns:
        List of equity points
    """
    equity_curve = []
    current_equity = initial_capital
    final_equity = initial_capital * (1 + total_return_pct / 100)

    # Calculate growth per point (with some randomness)
    import random
    random.seed(42)

    for i in range(num_points):
        # Progressive growth toward final equity
        target_equity = initial_capital + (final_equity - initial_capital) * (i / num_points)

        # Add some noise (±2% volatility)
        noise = random.uniform(-0.02, 0.02) * current_equity
        current_equity = target_equity + noise

        # Clamp to reasonable bounds
        current_equity = max(initial_capital * 0.8, current_equity)
        current_equity = min(final_equity * 1.1, current_equity)

        # Timestamp (hourly)
        ts = start_date + timedelta(hours=i)

        equity_curve.append(
            EquityPoint(
                ts=ts,
                equity=round(current_equity, 2),
                balance=round(current_equity * 0.7, 2),  # 70% in cash
                unrealized_pnl=round(current_equity * 0.3, 2),  # 30% in positions
            )
        )

    # Ensure final point matches target
    equity_curve[-1] = EquityPoint(
        ts=start_date + timedelta(hours=num_points - 1),
        equity=round(final_equity, 2),
        balance=round(final_equity, 2),
        unrealized_pnl=0.0,
    )

    return equity_curve


def generate_sample_trades(
    num_trades: int,
    start_date: datetime,
    win_rate_pct: float,
) -> list[Trade]:
    """
    Generate sample trades with realistic entry/exit patterns.

    Args:
        num_trades: Number of trades to generate
        start_date: Start timestamp
        win_rate_pct: Win rate percentage

    Returns:
        List of trades
    """
    import random
    random.seed(42)

    trades = []
    cumulative_pnl = 0.0

    for i in range(num_trades):
        # Determine if win or loss based on win rate
        is_win = random.random() < (win_rate_pct / 100)

        # Random entry time (within backtest period)
        hours_offset = int(i * (90 * 24 / num_trades))  # Spread over 90 days
        ts_entry = start_date + timedelta(hours=hours_offset)

        # Random hold time (1-12 hours)
        hold_hours = random.randint(1, 12)
        ts_exit = ts_entry + timedelta(hours=hold_hours)

        # Random side
        side = random.choice([TradeSide.LONG, TradeSide.SHORT])

        # Random entry price (BTC range: 40k-50k)
        entry_price = random.uniform(40000, 50000)

        # Calculate exit price based on win/loss
        if is_win:
            # Win: 0.5-2% profit
            pct_gain = random.uniform(0.005, 0.02)
            exit_price = entry_price * (1 + pct_gain) if side == TradeSide.LONG else entry_price * (1 - pct_gain)
            exit_reason = ExitReason.TAKE_PROFIT
        else:
            # Loss: 0.3-1% loss
            pct_loss = random.uniform(0.003, 0.01)
            exit_price = entry_price * (1 - pct_loss) if side == TradeSide.LONG else entry_price * (1 + pct_loss)
            exit_reason = ExitReason.STOP_LOSS

        # Random size (0.01-0.05 BTC)
        size = random.uniform(0.01, 0.05)

        # Calculate P&L
        if side == TradeSide.LONG:
            net_pnl = (exit_price - entry_price) * size
        else:
            net_pnl = (entry_price - exit_price) * size

        # Round P&L
        net_pnl = round(net_pnl, 2)
        cumulative_pnl += net_pnl

        trades.append(
            Trade(
                id=i + 1,
                ts_entry=ts_entry,
                ts_exit=ts_exit,
                side=side,
                entry_price=round(entry_price, 2),
                exit_price=round(exit_price, 2),
                size=round(size, 8),
                net_pnl=net_pnl,
                cumulative_pnl=round(cumulative_pnl, 2),
                signal="scalper" if random.random() < 0.6 else "momentum",
                exit_reason=exit_reason,
            )
        )

    return trades


def create_sample_backtest(
    symbol: str,
    initial_capital: float = 10000.0,
    total_return_pct: float = 5.0,
    sharpe_ratio: float = 1.8,
    max_drawdown_pct: float = -2.5,
    win_rate_pct: float = 55.0,
    num_trades: int = 100,
    lookback_days: int = 90,
) -> BacktestFile:
    """
    Create a sample backtest file with realistic data.

    Args:
        symbol: Trading pair (e.g., "BTC/USD")
        initial_capital: Starting capital
        total_return_pct: Total return percentage
        sharpe_ratio: Sharpe ratio
        max_drawdown_pct: Max drawdown percentage (negative)
        win_rate_pct: Win rate percentage
        num_trades: Number of trades
        lookback_days: Backtest period in days

    Returns:
        BacktestFile instance
    """
    # Calculate dates
    end_ts = datetime.now(timezone.utc).replace(microsecond=0)
    start_ts = end_ts - timedelta(days=lookback_days)

    # Generate equity curve
    num_equity_points = lookback_days * 24  # Hourly points
    equity_curve = generate_sample_equity_curve(
        initial_capital=initial_capital,
        num_points=num_equity_points,
        total_return_pct=total_return_pct,
        start_date=start_ts,
    )

    # Generate trades
    trades = generate_sample_trades(
        num_trades=num_trades,
        start_date=start_ts,
        win_rate_pct=win_rate_pct,
    )

    # Calculate metrics
    final_equity = initial_capital * (1 + total_return_pct / 100)
    winning_trades = len([t for t in trades if t.net_pnl > 0])
    losing_trades = len([t for t in trades if t.net_pnl < 0])
    gross_profit = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    # Create backtest file
    return BacktestFile(
        symbol=symbol,
        symbol_id=symbol.replace("/", "-"),
        timeframe="1h",
        start_ts=start_ts,
        end_ts=end_ts,
        equity_curve=equity_curve,
        trades=trades,
        initial_capital=initial_capital,
        final_equity=round(final_equity, 2),
        total_return_pct=total_return_pct,
        sharpe_ratio=sharpe_ratio,
        max_drawdown_pct=max_drawdown_pct,
        win_rate_pct=win_rate_pct,
        total_trades=num_trades,
        profit_factor=round(profit_factor, 2),
    )


def main():
    """Generate sample backtest exports"""
    logger.info("=" * 70)
    logger.info("DEMO BACKTEST EXPORT GENERATOR")
    logger.info("=" * 70)

    # Create output directory
    output_dir = Path("data/backtests")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sample configurations
    configs = [
        {
            "symbol": "BTC/USD",
            "total_return_pct": 5.0,
            "sharpe_ratio": 1.8,
            "max_drawdown_pct": -2.5,
            "win_rate_pct": 55.0,
            "num_trades": 100,
        },
        {
            "symbol": "ETH/USD",
            "total_return_pct": 8.0,
            "sharpe_ratio": 2.1,
            "max_drawdown_pct": -3.2,
            "win_rate_pct": 58.0,
            "num_trades": 120,
        },
    ]

    # Generate backtests
    for config in configs:
        logger.info(f"\nGenerating backtest for {config['symbol']}...")

        # Create backtest
        backtest = create_sample_backtest(**config)

        # Export to JSON
        file_path = output_dir / f"{backtest.symbol_id}.json"
        data = backtest.model_dump(mode='json')

        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"✓ Exported to: {file_path}")
        logger.info(f"  - Total Return: {backtest.total_return_pct:.2f}%")
        logger.info(f"  - Sharpe Ratio: {backtest.sharpe_ratio:.2f}")
        logger.info(f"  - Max Drawdown: {backtest.max_drawdown_pct:.2f}%")
        logger.info(f"  - Win Rate: {backtest.win_rate_pct:.2f}%")
        logger.info(f"  - Total Trades: {backtest.total_trades}")
        logger.info(f"  - Equity Points: {len(backtest.equity_curve)}")

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"SUCCESS: Generated {len(configs)} sample backtests")
    logger.info(f"Location: {output_dir}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
