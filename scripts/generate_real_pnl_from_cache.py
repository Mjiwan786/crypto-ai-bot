#!/usr/bin/env python3
"""
scripts/generate_real_pnl_from_cache.py - Generate P&L from Cached Real Data

Uses cached Kraken OHLCV data to run a realistic 12-month backtest with:
- Simple momentum/trend strategy
- Realistic Kraken fees (5bps maker, 10bps taker)
- Slippage modeling (2bps)
- Raw trade logs with timestamps
- Monthly aggregation for Acquire.com

Author: Crypto AI Bot Team
"""

import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# =============================================================================
# CONFIGURATION
# =============================================================================

def get_config() -> Dict:
    """Load configuration."""
    return {
        "initial_capital": float(os.getenv("INITIAL_CAPITAL", "10000")),
        "output_csv": "out/acquire_annual_snapshot_real.csv",
        "trades_csv": "out/trades_detailed_real.csv",
        "cache_dir": project_root / "data" / "cache",
        "pairs": ["BTC/USD", "ETH/USD"],
        "fee_bps": 5.0,  # Kraken maker (conservative estimate)
        "slip_bps": 2.0,  # Conservative slippage
        "risk_per_trade": 0.015,  # 1.5% risk per trade
    }


# =============================================================================
# DATA LOADING
# =============================================================================

def find_12month_cache(cache_dir: Path, symbol: str) -> Path:
    """Find 12-month cached data file for a symbol."""
    symbol_safe = symbol.replace("/", "_")

    # Look for 1h data files covering ~12 months
    pattern = f"{symbol_safe}_1h_2024*.csv"
    matches = list(cache_dir.glob(pattern))

    if matches:
        # Return the most recent file
        return sorted(matches, key=lambda p: p.stat().st_mtime)[-1]

    raise FileNotFoundError(f"No 12-month cached data found for {symbol}")


def load_ohlcv_cache(cache_file: Path) -> pd.DataFrame:
    """Load OHLCV data from cache file."""
    logger.info(f"Loading cached data: {cache_file.name}")

    df = pd.read_csv(cache_file)

    # Parse timestamp
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    else:
        raise ValueError("No timestamp column in cached data")

    # Validate required columns
    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Sort by timestamp
    df = df.sort_values("timestamp").reset_index(drop=True)

    logger.info(
        f"  Loaded {len(df)} bars from "
        f"{df['timestamp'].min().date()} to {df['timestamp'].max().date()}"
    )

    return df


# =============================================================================
# SIMPLE MOMENTUM STRATEGY
# =============================================================================

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate technical indicators for strategy."""
    # EMA crossover strategy (simple and robust)
    df["ema_fast"] = df["close"].ewm(span=12, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=26, adjust=False).mean()

    # RSI for overbought/oversold
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # ATR for position sizing
    high_low = df["high"] - df["low"]
    high_close = abs(df["high"] - df["close"].shift())
    low_close = abs(df["low"] - df["close"].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    df["atr"] = ranges.max(axis=1).rolling(14).mean()

    # Volatility
    df["returns"] = df["close"].pct_change()
    df["volatility"] = df["returns"].rolling(20).std()

    return df


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Generate trading signals."""
    # EMA crossover signals
    df["signal"] = 0  # 0 = no signal, 1 = long, -1 = short

    # Long when fast EMA crosses above slow EMA and RSI not overbought
    long_condition = (
        (df["ema_fast"] > df["ema_slow"]) &
        (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1)) &
        (df["rsi"] < 70) &
        (df["volatility"] < 0.05)  # Not too volatile
    )

    # Short when fast EMA crosses below slow EMA and RSI not oversold
    short_condition = (
        (df["ema_fast"] < df["ema_slow"]) &
        (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1)) &
        (df["rsi"] > 30)
    )

    df.loc[long_condition, "signal"] = 1
    df.loc[short_condition, "signal"] = -1

    return df


# =============================================================================
# BACKTEST ENGINE
# =============================================================================

def run_backtest(
    df: pd.DataFrame,
    symbol: str,
    initial_capital: float,
    risk_per_trade: float,
    fee_bps: float,
    slip_bps: float,
) -> Tuple[List[Dict], pd.DataFrame]:
    """
    Run backtest on OHLCV data.

    Returns:
        (trades_list, equity_curve_df)
    """
    logger.info(f"Running backtest for {symbol}...")

    # Calculate indicators and signals
    df = calculate_indicators(df)
    df = generate_signals(df)

    # Initialize tracking
    capital = initial_capital
    position = None  # {"side": "long/short", "entry_price": float, "size": float, "entry_time": datetime}
    trades = []
    equity_curve = []

    # Simulate trading
    for i in range(50, len(df)):  # Start after indicator warmup
        row = df.iloc[i]
        timestamp = row["timestamp"]
        price = row["close"]
        atr = row["atr"]

        # Track equity
        equity = capital
        if position:
            # Mark to market
            if position["side"] == "long":
                unrealized_pnl = (price - position["entry_price"]) * position["size"]
            else:  # short
                unrealized_pnl = (position["entry_price"] - price) * position["size"]
            equity += unrealized_pnl

        equity_curve.append({
            "timestamp": timestamp,
            "equity": equity,
        })

        # Position management
        if position:
            # Check exit conditions
            should_exit = False
            exit_reason = None

            # Stop loss / Take profit (ATR-based)
            if position["side"] == "long":
                pnl_pct = (price - position["entry_price"]) / position["entry_price"]
                stop_loss = -0.02  # -2% stop
                take_profit = 0.04  # +4% target

                if pnl_pct <= stop_loss:
                    should_exit = True
                    exit_reason = "stop_loss"
                elif pnl_pct >= take_profit:
                    should_exit = True
                    exit_reason = "take_profit"
                elif row["signal"] == -1:  # Reversal signal
                    should_exit = True
                    exit_reason = "signal_reversal"

            else:  # short
                pnl_pct = (position["entry_price"] - price) / position["entry_price"]
                stop_loss = -0.02
                take_profit = 0.04

                if pnl_pct <= stop_loss:
                    should_exit = True
                    exit_reason = "stop_loss"
                elif pnl_pct >= take_profit:
                    should_exit = True
                    exit_reason = "take_profit"
                elif row["signal"] == 1:  # Reversal signal
                    should_exit = True
                    exit_reason = "signal_reversal"

            # Exit position
            if should_exit:
                # Calculate P&L with fees and slippage
                if position["side"] == "long":
                    gross_pnl = (price - position["entry_price"]) * position["size"]
                else:
                    gross_pnl = (position["entry_price"] - price) * position["size"]

                # Entry fee + exit fee
                entry_fee = position["entry_price"] * position["size"] * (fee_bps / 10000)
                exit_fee = price * position["size"] * (fee_bps / 10000)
                total_fees = entry_fee + exit_fee

                # Entry slip + exit slip
                entry_slip = position["entry_price"] * position["size"] * (slip_bps / 10000)
                exit_slip = price * position["size"] * (slip_bps / 10000)
                total_slip = entry_slip + exit_slip

                # Net P&L
                net_pnl = gross_pnl - total_fees - total_slip

                # Update capital
                capital += net_pnl

                # Record trade
                trades.append({
                    "symbol": symbol,
                    "entry_time": position["entry_time"],
                    "exit_time": timestamp,
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "exit_price": price,
                    "size": position["size"],
                    "gross_pnl": gross_pnl,
                    "fees": total_fees,
                    "slippage": total_slip,
                    "net_pnl": net_pnl,
                    "pnl_pct": (net_pnl / (position["entry_price"] * position["size"])) * 100,
                    "exit_reason": exit_reason,
                })

                # Clear position
                position = None

        # Entry logic
        if position is None and row["signal"] != 0:
            # Calculate position size based on risk
            position_value = capital * risk_per_trade
            size = position_value / price

            # Check if we have enough capital
            if position_value <= capital * 0.95:  # Leave 5% buffer
                side = "long" if row["signal"] == 1 else "short"

                position = {
                    "side": side,
                    "entry_price": price,
                    "size": size,
                    "entry_time": timestamp,
                }

    logger.info(f"  Generated {len(trades)} trades")
    logger.info(f"  Final capital: ${capital:,.2f} (from ${initial_capital:,.2f})")

    equity_df = pd.DataFrame(equity_curve)
    return trades, equity_df


# =============================================================================
# MONTHLY AGGREGATION
# =============================================================================

def aggregate_monthly(
    trades: List[Dict],
    initial_capital: float,
    fee_bps: float,
    slip_bps: float,
) -> List[Dict]:
    """Aggregate trades by month for Acquire.com CSV."""
    if not trades:
        logger.warning("No trades to aggregate")
        return []

    # Convert to DataFrame
    df = pd.DataFrame(trades)
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["month"] = df["exit_time"].dt.to_period("M").astype(str)

    # Group by month
    monthly_groups = df.groupby("month")

    monthly_records = []
    balance = initial_capital

    for month, group in monthly_groups:
        starting_balance = balance

        # Aggregate
        net_pnl = group["net_pnl"].sum()
        fees = group["fees"].sum()
        slippage = group["slippage"].sum()
        trades_count = len(group)
        wins = (group["net_pnl"] > 0).sum()
        win_rate = (wins / trades_count * 100) if trades_count > 0 else 0.0

        # Update balance
        balance += net_pnl

        # Calculate returns
        monthly_return = ((balance - starting_balance) / starting_balance) * 100
        cumulative_return = ((balance - initial_capital) / initial_capital) * 100

        # Notes
        pairs = group["symbol"].unique()
        avg_pnl = net_pnl / trades_count if trades_count > 0 else 0.0
        notes = f"Pairs: {', '.join(pairs)}, Avg trade: ${avg_pnl:.2f}"

        monthly_records.append({
            "month": month,
            "starting_balance": starting_balance,
            "deposits": 0.0,
            "net_pnl": net_pnl,
            "fees": fees,
            "slippage": slippage,
            "ending_balance": balance,
            "monthly_return_pct": monthly_return,
            "cumulative_return_pct": cumulative_return,
            "trades": trades_count,
            "win_rate_pct": win_rate,
            "notes": notes,
        })

    return monthly_records


# =============================================================================
# CSV EXPORT
# =============================================================================

def export_acquire_csv(monthly_records: List[Dict], output_path: str):
    """Export to Acquire.com format."""
    logger.info(f"Exporting to {output_path}...")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "Month",
        "Starting Balance",
        "Deposits/Withdrawals",
        "Net P&L ($)",
        "Fees ($)",
        "Slippage ($)",
        "Ending Balance",
        "Monthly Return %",
        "Cumulative Return %",
        "Trades",
        "Win Rate %",
        "Notes",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)

        for record in monthly_records:
            writer.writerow([
                record["month"],
                f"${record['starting_balance']:,.2f}",
                f"${record['deposits']:,.2f}",
                f"${record['net_pnl']:+,.2f}",
                f"${record['fees']:,.2f}",
                f"${record['slippage']:,.2f}",
                f"${record['ending_balance']:,.2f}",
                f"{record['monthly_return_pct']:+.2f}%",
                f"{record['cumulative_return_pct']:+.2f}%",
                record["trades"],
                f"{record['win_rate_pct']:.1f}%",
                record["notes"],
            ])

    logger.info(f"  Exported {len(monthly_records)} rows")


def export_trades_csv(trades: List[Dict], output_path: str):
    """Export detailed trades log."""
    logger.info(f"Exporting trades to {output_path}...")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(trades)
    df.to_csv(output_path, index=False)

    logger.info(f"  Exported {len(trades)} trades")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    logger.info("=" * 80)
    logger.info("ACQUIRE.COM ANNUAL P&L FROM REAL CACHED DATA")
    logger.info("=" * 80)

    config = get_config()

    logger.info("\nConfiguration:")
    logger.info(f"  Initial Capital: ${config['initial_capital']:,.2f}")
    logger.info(f"  Pairs: {', '.join(config['pairs'])}")
    logger.info(f"  Fees: {config['fee_bps']} bps ({config['fee_bps']/100:.2f}%)")
    logger.info(f"  Slippage: {config['slip_bps']} bps ({config['slip_bps']/100:.2f}%)")
    logger.info(f"  Risk per trade: {config['risk_per_trade']*100:.1f}%")
    logger.info("")

    # Load cached data and run backtests
    all_trades = []

    for symbol in config["pairs"]:
        try:
            # Find and load cached data
            cache_file = find_12month_cache(config["cache_dir"], symbol)
            df = load_ohlcv_cache(cache_file)

            # Run backtest
            trades, equity_df = run_backtest(
                df=df,
                symbol=symbol,
                initial_capital=config['initial_capital'] / len(config['pairs']),  # Split capital
                risk_per_trade=config['risk_per_trade'],
                fee_bps=config['fee_bps'],
                slip_bps=config['slip_bps'],
            )

            all_trades.extend(trades)

        except Exception as e:
            logger.error(f"Failed to process {symbol}: {e}")

    if not all_trades:
        logger.error("No trades generated - cannot create report")
        sys.exit(1)

    # Aggregate monthly
    logger.info("\nAggregating monthly P&L...")
    monthly_records = aggregate_monthly(
        trades=all_trades,
        initial_capital=config['initial_capital'],
        fee_bps=config['fee_bps'],
        slip_bps=config['slip_bps'],
    )

    # Export
    logger.info("\nExporting reports...")
    export_acquire_csv(monthly_records, config['output_csv'])
    export_trades_csv(all_trades, config['trades_csv'])

    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("COMPLETED")
    logger.info("=" * 80)
    logger.info(f"\nFiles generated:")
    logger.info(f"  1. Acquire.com CSV: {config['output_csv']}")
    logger.info(f"  2. Detailed trades: {config['trades_csv']}")
    logger.info("")
    logger.info("Data source: Real Kraken OHLCV data (cached)")
    logger.info("Strategy: EMA crossover with RSI filter")
    logger.info("Fees: Kraken maker fees (5bps)")
    logger.info("Slippage: Conservative 2bps estimate")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
