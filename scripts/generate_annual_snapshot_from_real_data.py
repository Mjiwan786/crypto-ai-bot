#!/usr/bin/env python3
"""
scripts/generate_annual_snapshot_from_real_data.py - Real Data 12-Month Backtest

Generate a 12-month P&L report from REAL Kraken historical data with proper
fee and slippage modeling. Uses actual OHLCV data from data/cache/.

Output: CSV with columns:
- Month (YYYY-MM)
- Starting Balance ($)
- Deposits/Withdrawals ($)
- Net P&L ($)
- Fees ($)
- Slippage ($)
- Ending Balance ($)
- Monthly Return (%)
- Cumulative Return (%)
- Trades (count)
- Win Rate (%)
- Notes

Environment Variables:
    INITIAL_CAPITAL - Starting capital (default: $10,000)
    OUTPUT_PATH - CSV output path (default: out/acquire_annual_snapshot_real_backtest.csv)
    TRADES_LOG_PATH - Trade log CSV path (default: out/trades_detailed_real_backtest.csv)
    FEE_BPS - Trading fee in bps (default: 8 = Kraken standard)
    SLIP_BPS - Slippage in bps (default: 2 = conservative)

Usage:
    python scripts/generate_annual_snapshot_from_real_data.py

Author: Crypto AI Bot Team
"""

import csv
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from strategies.costs import taker_fee_bps, model_slippage, apply_costs

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

def get_config() -> Dict:
    """Load configuration from environment variables."""
    return {
        "initial_capital": float(os.getenv("INITIAL_CAPITAL", "10000")),
        "output_path": os.getenv("OUTPUT_PATH", "out/acquire_annual_snapshot_real_backtest.csv"),
        "trades_log_path": os.getenv("TRADES_LOG_PATH", "out/trades_detailed_real_backtest.csv"),
        "fee_bps": float(os.getenv("FEE_BPS", "8")),  # Kraken actual: 8 bps
        "slip_bps": float(os.getenv("SLIP_BPS", "2")),  # Conservative
    }


# =============================================================================
# DATA LOADING
# =============================================================================

def load_historical_data(pair: str, timeframe: str = "1h") -> pd.DataFrame:
    """
    Load historical OHLCV data from cache.

    Args:
        pair: Trading pair (e.g., "BTC/USD")
        timeframe: Timeframe (default: "1h")

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    # Convert pair to filename format (BTC/USD -> BTC_USD)
    pair_filename = pair.replace("/", "_")

    # Find the file with longest date range
    cache_dir = project_root / "data" / "cache"
    pattern = f"{pair_filename}_{timeframe}_*.csv"

    files = list(cache_dir.glob(pattern))

    if not files:
        raise FileNotFoundError(f"No cached data found for {pair} {timeframe} in {cache_dir}")

    # Use the file with the longest date range (last in sorted order)
    # Files are named like: BTC_USD_1h_2024-10-31_2025-10-26.csv
    files_sorted = sorted(files, key=lambda f: f.name)
    data_file = files_sorted[-1]

    logger.info(f"Loading {pair} data from {data_file.name}")

    # Load CSV
    df = pd.read_csv(data_file)

    # Parse timestamp
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    elif 'time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['time'], utc=True)
        df = df.drop(columns=['time'])

    # Ensure required columns
    required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Sort by timestamp
    df = df.sort_values('timestamp').reset_index(drop=True)

    logger.info(f"  Loaded {len(df)} bars from {df['timestamp'].min()} to {df['timestamp'].max()}")

    return df


# =============================================================================
# SIMPLE STRATEGY (EMA CROSSOVER + RSI)
# =============================================================================

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate technical indicators for trading signals.

    Uses simple EMA crossover + RSI strategy:
    - EMA 12 / EMA 26 crossover
    - RSI(14) overbought/oversold filter
    - ATR(14) for stops/targets

    Args:
        df: OHLCV DataFrame

    Returns:
        DataFrame with added indicator columns
    """
    df = df.copy()

    # EMA
    df['ema_fast'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=26, adjust=False).mean()

    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # ATR
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['atr'] = true_range.rolling(window=14).mean()

    return df


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate buy/sell signals based on indicators.

    Buy Signal:
    - EMA fast crosses above EMA slow
    - RSI < 70 (not overbought)

    Sell Signal:
    - EMA fast crosses below EMA slow
    - RSI > 30 (not oversold)

    Args:
        df: DataFrame with indicators

    Returns:
        DataFrame with 'signal' column (1=buy, -1=sell, 0=hold)
    """
    df = df.copy()

    # Calculate crossovers
    df['ema_cross'] = 0
    df.loc[(df['ema_fast'] > df['ema_slow']) & (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1)), 'ema_cross'] = 1
    df.loc[(df['ema_fast'] < df['ema_slow']) & (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1)), 'ema_cross'] = -1

    # Generate signals with RSI filter
    df['signal'] = 0

    # Buy: EMA bullish cross + RSI not overbought
    df.loc[(df['ema_cross'] == 1) & (df['rsi'] < 70), 'signal'] = 1

    # Sell: EMA bearish cross + RSI not oversold
    df.loc[(df['ema_cross'] == -1) & (df['rsi'] > 30), 'signal'] = -1

    return df


# =============================================================================
# BACKTESTING ENGINE
# =============================================================================

def run_backtest(
    df: pd.DataFrame,
    pair: str,
    initial_capital: float,
    fee_bps: float,
    slip_bps: float,
) -> Tuple[List[Dict], float]:
    """
    Run backtest on historical data.

    Args:
        df: OHLCV DataFrame with signals
        pair: Trading pair
        initial_capital: Starting capital
        fee_bps: Fee in basis points
        slip_bps: Slippage in basis points

    Returns:
        Tuple of (trades list, final balance)
    """
    logger.info(f"Running backtest on {pair}...")

    balance = initial_capital
    position = None
    trades = []

    for i in range(len(df)):
        row = df.iloc[i]

        # Skip if no signal or missing data
        if pd.isna(row['signal']) or pd.isna(row['close']) or pd.isna(row['atr']):
            continue

        timestamp = row['timestamp']
        close = float(row['close'])
        atr = float(row['atr'])
        signal = int(row['signal'])

        # Entry signal
        if signal == 1 and position is None:
            # Calculate position size (risk 1.5% of capital per trade)
            risk_pct = 0.015
            risk_amount = balance * risk_pct

            # Stop loss at 2% or 2x ATR (whichever is larger)
            stop_distance = max(close * 0.02, 2 * atr)
            stop_loss = close - stop_distance

            # Position size based on stop distance
            position_size_usd = min(risk_amount / (stop_distance / close), balance * 0.2)  # Max 20% of capital

            if position_size_usd >= 100:  # Minimum $100 position
                position = {
                    'entry_time': timestamp,
                    'entry_price': close,
                    'size_usd': position_size_usd,
                    'size_units': position_size_usd / close,
                    'stop_loss': stop_loss,
                    'take_profit': close + (2 * stop_distance),  # 2:1 RR
                    'side': 'long',
                }

        # Exit signal or stop/target hit
        elif position is not None:
            should_exit = False
            exit_reason = None

            # Check signal exit
            if signal == -1:
                should_exit = True
                exit_reason = "signal"

            # Check stop loss
            elif float(row['low']) <= position['stop_loss']:
                should_exit = True
                exit_reason = "stop_loss"
                close = position['stop_loss']  # Use stop price

            # Check take profit
            elif float(row['high']) >= position['take_profit']:
                should_exit = True
                exit_reason = "take_profit"
                close = position['take_profit']  # Use target price

            if should_exit:
                # Calculate P&L with costs
                entry_price_dec = Decimal(str(position['entry_price']))
                exit_price_dec = Decimal(str(close))
                size_units_dec = Decimal(str(position['size_units']))

                # Calculate slippage
                entry_notional = Decimal(str(position['size_usd']))
                exit_notional = exit_price_dec * size_units_dec

                entry_slippage = (entry_notional * Decimal(str(slip_bps)) / Decimal("10000"))
                exit_slippage = (exit_notional * Decimal(str(slip_bps)) / Decimal("10000"))

                # Apply costs
                net_pnl = apply_costs(
                    entry_price=entry_price_dec,
                    exit_price=exit_price_dec,
                    size=size_units_dec,
                    side=position['side'],
                    fee_bps=Decimal(str(fee_bps)),
                    slippage_entry=entry_slippage,
                    slippage_exit=exit_slippage,
                )

                # Calculate fees
                fee_multiplier = Decimal(str(fee_bps)) / Decimal("10000")
                entry_fee = entry_notional * fee_multiplier
                exit_fee = exit_notional * fee_multiplier
                total_fees = entry_fee + exit_fee
                total_slippage = entry_slippage + exit_slippage

                # Update balance
                balance += float(net_pnl)

                # Record trade
                trade = {
                    'entry_time': position['entry_time'],
                    'exit_time': timestamp,
                    'pair': pair,
                    'side': position['side'],
                    'entry_price': position['entry_price'],
                    'exit_price': close,
                    'size_usd': position['size_usd'],
                    'size_units': position['size_units'],
                    'gross_pnl': float((exit_price_dec - entry_price_dec) * size_units_dec),
                    'fees': float(total_fees),
                    'slippage': float(total_slippage),
                    'net_pnl': float(net_pnl),
                    'balance': balance,
                    'exit_reason': exit_reason,
                }

                trades.append(trade)

                # Clear position
                position = None

    logger.info(f"  Backtest complete: {len(trades)} trades, Final balance: ${balance:,.2f}")

    return trades, balance


# =============================================================================
# MONTHLY AGGREGATION
# =============================================================================

def aggregate_monthly(
    trades: List[Dict],
    initial_capital: float,
) -> List[Dict]:
    """
    Aggregate trades into monthly P&L records.

    Args:
        trades: List of trade dictionaries
        initial_capital: Starting capital

    Returns:
        List of monthly record dictionaries
    """
    if not trades:
        logger.warning("No trades to aggregate")
        return []

    logger.info("Aggregating trades by month...")

    # Convert to DataFrame
    df = pd.DataFrame(trades)
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    df['month'] = df['exit_time'].dt.to_period('M')

    # Group by month
    monthly_data = []
    balance = initial_capital

    for period, group in df.groupby('month'):
        month_str = str(period)

        # Calculate metrics
        total_trades = len(group)
        wins = len(group[group['net_pnl'] > 0])
        losses = total_trades - wins
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

        net_pnl = group['net_pnl'].sum()
        fees = group['fees'].sum()
        slippage = group['slippage'].sum()

        starting_balance = balance
        ending_balance = starting_balance + net_pnl

        monthly_return = ((ending_balance - starting_balance) / starting_balance * 100) if starting_balance > 0 else 0.0
        cumulative_return = ((ending_balance - initial_capital) / initial_capital * 100)

        # Build record
        monthly_data.append({
            'month': month_str,
            'starting_balance': starting_balance,
            'deposits': 0.0,
            'net_pnl': net_pnl,
            'fees': fees,
            'slippage': slippage,
            'ending_balance': ending_balance,
            'monthly_return_pct': monthly_return,
            'cumulative_return_pct': cumulative_return,
            'trades': total_trades,
            'win_rate_pct': win_rate,
            'notes': f"Pairs: {', '.join(group['pair'].unique())}, Avg trade: ${group['net_pnl'].mean():.2f}",
        })

        balance = ending_balance

    logger.info(f"  Generated {len(monthly_data)} monthly records")

    return monthly_data


# =============================================================================
# CSV EXPORT
# =============================================================================

def export_trades_csv(trades: List[Dict], output_path: str) -> None:
    """Export detailed trade log to CSV."""
    logger.info(f"Exporting {len(trades)} trades to {output_path}")

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if not trades:
        logger.warning("No trades to export")
        return

    columns = [
        'entry_time', 'exit_time', 'pair', 'side',
        'entry_price', 'exit_price', 'size_usd', 'size_units',
        'gross_pnl', 'fees', 'slippage', 'net_pnl',
        'balance', 'exit_reason',
    ]

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(trades)

    logger.info(f"  Exported to {output_file.absolute()}")


def export_monthly_csv(monthly_records: List[Dict], output_path: str) -> None:
    """Export monthly P&L to CSV."""
    logger.info(f"Exporting monthly P&L to {output_path}")

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

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

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)

        for record in monthly_records:
            writer.writerow([
                record['month'],
                f"${record['starting_balance']:,.2f}",
                f"${record['deposits']:,.2f}",
                f"${record['net_pnl']:+,.2f}",
                f"${record['fees']:,.2f}",
                f"${record['slippage']:,.2f}",
                f"${record['ending_balance']:,.2f}",
                f"{record['monthly_return_pct']:+.2f}%",
                f"{record['cumulative_return_pct']:+.2f}%",
                record['trades'],
                f"{record['win_rate_pct']:.1f}%",
                record['notes'],
            ])

    logger.info(f"  Exported to {output_file.absolute()}")


# =============================================================================
# SUMMARY STATISTICS
# =============================================================================

def print_summary(trades: List[Dict], monthly_records: List[Dict], initial_capital: float):
    """Print backtest summary."""
    if not trades or not monthly_records:
        logger.warning("No data to summarize")
        return

    final_balance = monthly_records[-1]['ending_balance']
    total_return = final_balance - initial_capital
    total_return_pct = (total_return / initial_capital) * 100

    # Trade stats
    wins = sum(1 for t in trades if t['net_pnl'] > 0)
    losses = len(trades) - wins
    win_rate = (wins / len(trades) * 100) if trades else 0.0

    total_fees = sum(t['fees'] for t in trades)
    total_slippage = sum(t['slippage'] for t in trades)

    # Monthly stats
    monthly_returns = [r['monthly_return_pct'] for r in monthly_records]
    avg_monthly = np.mean(monthly_returns)
    std_monthly = np.std(monthly_returns)
    sharpe = (avg_monthly / std_monthly) if std_monthly > 0 else 0.0

    logger.info("")
    logger.info("=" * 80)
    logger.info("BACKTEST SUMMARY")
    logger.info("=" * 80)

    logger.info(f"\nPeriod:")
    logger.info(f"  Start: {monthly_records[0]['month']}")
    logger.info(f"  End:   {monthly_records[-1]['month']}")
    logger.info(f"  Duration: {len(monthly_records)} months")

    logger.info(f"\nCapital:")
    logger.info(f"  Initial:  ${initial_capital:,.2f}")
    logger.info(f"  Final:    ${final_balance:,.2f}")
    logger.info(f"  Return:   ${total_return:+,.2f} ({total_return_pct:+.2f}%)")

    logger.info(f"\nTrading Activity:")
    logger.info(f"  Total trades: {len(trades)}")
    logger.info(f"  Wins: {wins} ({win_rate:.1f}%)")
    logger.info(f"  Losses: {losses}")

    logger.info(f"\nCosts:")
    logger.info(f"  Total fees: ${total_fees:,.2f}")
    logger.info(f"  Total slippage: ${total_slippage:,.2f}")
    logger.info(f"  Combined: ${total_fees + total_slippage:,.2f}")

    logger.info(f"\nMonthly Performance:")
    logger.info(f"  Mean: {avg_monthly:+.2f}%")
    logger.info(f"  Std Dev: {std_monthly:.2f}%")
    logger.info(f"  Sharpe: {sharpe:.2f}")
    logger.info(f"  Best: {max(monthly_returns):+.2f}%")
    logger.info(f"  Worst: {min(monthly_returns):+.2f}%")

    logger.info("")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main entry point."""

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    logger.info("=" * 80)
    logger.info("12-MONTH ANNUAL SNAPSHOT - REAL DATA BACKTEST")
    logger.info("=" * 80)

    # Load configuration
    config = get_config()

    logger.info("\nConfiguration:")
    logger.info(f"  Initial Capital: ${config['initial_capital']:,.2f}")
    logger.info(f"  Fee: {config['fee_bps']} bps (Kraken actual)")
    logger.info(f"  Slippage: {config['slip_bps']} bps (conservative)")
    logger.info(f"  Output: {config['output_path']}")
    logger.info(f"  Trades Log: {config['trades_log_path']}")
    logger.info("")

    # Load data for multiple pairs
    pairs = ["BTC/USD", "ETH/USD"]
    all_trades = []

    for pair in pairs:
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing {pair}")
            logger.info(f"{'='*60}")

            # Load historical data
            df = load_historical_data(pair, timeframe="1h")

            # Calculate indicators
            df = calculate_indicators(df)

            # Generate signals
            df = generate_signals(df)

            # Run backtest
            trades, _ = run_backtest(
                df=df,
                pair=pair,
                initial_capital=config['initial_capital'],
                fee_bps=config['fee_bps'],
                slip_bps=config['slip_bps'],
            )

            all_trades.extend(trades)

        except Exception as e:
            logger.error(f"Failed to process {pair}: {e}", exc_info=True)

    if not all_trades:
        logger.error("No trades generated. Exiting.")
        sys.exit(1)

    # Export detailed trade log
    logger.info(f"\n{'='*60}")
    logger.info("Exporting Results")
    logger.info(f"{'='*60}")

    export_trades_csv(all_trades, config['trades_log_path'])

    # Aggregate by month
    monthly_records = aggregate_monthly(all_trades, config['initial_capital'])

    # Export monthly CSV
    export_monthly_csv(monthly_records, config['output_path'])

    # Print summary
    print_summary(all_trades, monthly_records, config['initial_capital'])

    logger.info("=" * 80)
    logger.info("COMPLETED SUCCESSFULLY")
    logger.info("=" * 80)
    logger.info(f"\nOutputs:")
    logger.info(f"  Annual Snapshot: {Path(config['output_path']).absolute()}")
    logger.info(f"  Trade Log: {Path(config['trades_log_path']).absolute()}")
    logger.info("\nThis report uses REAL Kraken historical data with actual fee/slippage costs.")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
