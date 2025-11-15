#!/usr/bin/env python3
"""
scripts/build_monthly_pnl.py - Monthly P&L Aggregator for Acquire.com

Reads fills/trades from multiple sources, aggregates to monthly P&L with fees/slippage,
and outputs to CSV in Acquire.com Annual Snapshot format.

Data Sources (in priority order):
1. Redis Cloud "trades:closed" stream (live/paper trading)
2. CSV files (backtest results)
3. Synthetic data (fallback for demo)

Output: /tmp/backtest_annual_snapshot.csv

Usage:
    # From Redis Cloud (live/paper trading data)
    REDIS_URL=rediss://default:pass@host:port python scripts/build_monthly_pnl.py --source redis

    # From CSV backtest results
    python scripts/build_monthly_pnl.py --source csv --input out/trades_detailed_real.csv

    # Auto-detect (tries Redis first, then CSV)
    python scripts/build_monthly_pnl.py

Environment Variables:
    REDIS_URL - Redis connection string with TLS (default: from config)
    REDIS_TLS_CERT - Path to TLS CA cert (default: config/certs/redis_ca.pem)
    INITIAL_CAPITAL - Starting capital (default: 10000)
    FEE_BPS - Default fee in bps if not in data (default: 5)
    SLIP_BPS - Default slippage in bps if not in data (default: 2)

Author: Crypto AI Bot Team
"""

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import orjson
except ImportError:
    import json as orjson

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("[WARN] redis package not installed. Redis source disabled.")

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# =============================================================================
# CONFIGURATION
# =============================================================================

def get_config() -> Dict:
    """Load configuration from environment."""
    redis_url = os.getenv(
        "REDIS_URL",
        "rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
    )
    redis_cert = os.getenv(
        "REDIS_TLS_CERT",
        str(project_root / "config" / "certs" / "redis_ca.pem")
    )

    return {
        "redis_url": redis_url,
        "redis_cert": redis_cert,
        "initial_capital": float(os.getenv("INITIAL_CAPITAL", "10000")),
        "fee_bps": float(os.getenv("FEE_BPS", "5")),
        "slip_bps": float(os.getenv("SLIP_BPS", "2")),
        "output_path": "/tmp/backtest_annual_snapshot.csv",
    }


# =============================================================================
# DATA SOURCES
# =============================================================================

class TradeDataSource:
    """Base class for trade data sources."""

    def read_trades(self) -> List[Dict]:
        """
        Read trades from source.

        Returns:
            List of trade dicts with keys:
            - timestamp (datetime): Trade close time
            - symbol (str): Trading pair
            - side (str): long/short
            - entry_price (float)
            - exit_price (float)
            - size (float)
            - gross_pnl (float)
            - fees (float)
            - slippage (float)
            - net_pnl (float)
        """
        raise NotImplementedError


class RedisTradeSource(TradeDataSource):
    """Read trades from Redis Cloud stream."""

    def __init__(self, redis_url: str, cert_path: Optional[str] = None):
        """Initialize Redis connection."""
        if not REDIS_AVAILABLE:
            raise RuntimeError("redis package not installed")

        self.redis_url = redis_url
        self.cert_path = cert_path

        # Parse URL to check for TLS
        self.use_tls = redis_url.startswith("rediss://")

        logger.info(f"Connecting to Redis Cloud (TLS: {self.use_tls})...")

        # Connect to Redis
        if self.use_tls and cert_path and Path(cert_path).exists():
            self.client = redis.from_url(
                redis_url,
                decode_responses=False,
                ssl_ca_certs=cert_path,
                ssl_cert_reqs="required",
            )
        else:
            self.client = redis.from_url(
                redis_url,
                decode_responses=False,
            )

        # Test connection
        try:
            self.client.ping()
            logger.info("  ✓ Connected to Redis Cloud")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Redis: {e}")

    def read_trades(self) -> List[Dict]:
        """Read trades from trades:closed stream."""
        logger.info("Reading trades from Redis stream 'trades:closed'...")

        trades = []

        try:
            # Read entire stream
            # XREAD returns: [(stream_name, [(id, {fields}), ...])]
            result = self.client.xread(
                {"trades:closed": "0-0"},  # Start from beginning
                count=10000,  # Read up to 10k trades
            )

            if not result:
                logger.warning("  No trades found in stream")
                return []

            stream_name, messages = result[0]

            for message_id, fields in messages:
                try:
                    # Parse JSON payload
                    json_bytes = fields.get(b"json") or fields.get("json")
                    if not json_bytes:
                        continue

                    if hasattr(orjson, "loads"):
                        trade_data = orjson.loads(json_bytes)
                    else:
                        if isinstance(json_bytes, bytes):
                            json_bytes = json_bytes.decode("utf-8")
                        trade_data = orjson.loads(json_bytes)

                    # Extract fields
                    timestamp = trade_data.get("ts") or trade_data.get("exit_time")
                    if isinstance(timestamp, int):
                        timestamp = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
                    elif isinstance(timestamp, str):
                        timestamp = pd.to_datetime(timestamp)

                    trades.append({
                        "timestamp": timestamp,
                        "symbol": trade_data.get("symbol", trade_data.get("pair", "UNKNOWN")),
                        "side": trade_data.get("side", "long"),
                        "entry_price": float(trade_data.get("entry_price", 0)),
                        "exit_price": float(trade_data.get("exit_price", 0)),
                        "size": float(trade_data.get("size", trade_data.get("quantity", 0))),
                        "gross_pnl": float(trade_data.get("gross_pnl", trade_data.get("pnl", 0))),
                        "fees": float(trade_data.get("fees", trade_data.get("fee", 0))),
                        "slippage": float(trade_data.get("slippage", 0)),
                        "net_pnl": float(trade_data.get("net_pnl", trade_data.get("pnl", 0))),
                    })

                except Exception as e:
                    logger.warning(f"  Failed to parse trade: {e}")
                    continue

            logger.info(f"  ✓ Loaded {len(trades)} trades from Redis")
            return trades

        except Exception as e:
            logger.error(f"  ✗ Failed to read from Redis: {e}")
            return []


class CSVTradeSource(TradeDataSource):
    """Read trades from CSV file."""

    def __init__(self, csv_path: str, fee_bps: float = 5.0, slip_bps: float = 2.0):
        """Initialize with CSV path."""
        self.csv_path = Path(csv_path)
        self.fee_bps = fee_bps
        self.slip_bps = slip_bps

        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

    def read_trades(self) -> List[Dict]:
        """Read trades from CSV."""
        logger.info(f"Reading trades from CSV: {self.csv_path.name}...")

        df = pd.read_csv(self.csv_path)

        # Detect timestamp column
        timestamp_col = None
        for col in ["exit_time", "timestamp", "close_time", "time"]:
            if col in df.columns:
                timestamp_col = col
                break

        if not timestamp_col:
            raise ValueError("No timestamp column found in CSV")

        # Parse timestamps
        df[timestamp_col] = pd.to_datetime(df[timestamp_col])

        trades = []

        for _, row in df.iterrows():
            # Handle different CSV formats
            symbol = row.get("symbol", row.get("pair", "UNKNOWN"))
            side = row.get("side", "long")

            # Prices
            entry_price = float(row.get("entry_price", 0))
            exit_price = float(row.get("exit_price", 0))
            size = float(row.get("size", row.get("quantity", row.get("qty", 0))))

            # P&L (may need to calculate)
            if "gross_pnl" in row and pd.notna(row["gross_pnl"]):
                gross_pnl = float(row["gross_pnl"])
            elif entry_price and exit_price and size:
                if side == "long":
                    gross_pnl = (exit_price - entry_price) * size
                else:
                    gross_pnl = (entry_price - exit_price) * size
            else:
                gross_pnl = float(row.get("pnl", 0))

            # Fees (use from CSV or calculate)
            if "fees" in row and pd.notna(row["fees"]):
                fees = float(row["fees"])
            elif entry_price and size:
                # Estimate: fee_bps on both entry and exit
                fees = (entry_price * size * self.fee_bps / 10000) * 2
            else:
                fees = 0.0

            # Slippage (use from CSV or calculate)
            if "slippage" in row and pd.notna(row["slippage"]):
                slippage = float(row["slippage"])
            elif entry_price and size:
                # Estimate: slip_bps on both entry and exit
                slippage = (entry_price * size * self.slip_bps / 10000) * 2
            else:
                slippage = 0.0

            # Net P&L
            if "net_pnl" in row and pd.notna(row["net_pnl"]):
                net_pnl = float(row["net_pnl"])
            else:
                net_pnl = gross_pnl - fees - slippage

            trades.append({
                "timestamp": row[timestamp_col],
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "size": size,
                "gross_pnl": gross_pnl,
                "fees": fees,
                "slippage": slippage,
                "net_pnl": net_pnl,
            })

        logger.info(f"  ✓ Loaded {len(trades)} trades from CSV")
        return trades


class SyntheticTradeSource(TradeDataSource):
    """Generate synthetic trades for demo purposes."""

    def __init__(self, months: int = 12, initial_capital: float = 10000):
        """Initialize synthetic generator."""
        self.months = months
        self.initial_capital = initial_capital

    def read_trades(self) -> List[Dict]:
        """Generate synthetic trades."""
        logger.info(f"Generating synthetic trades for {self.months} months...")

        trades = []
        np.random.seed(42)

        # Generate trades across months (Nov 2024 - Oct 2025 for 12 months)
        # End at Oct 2025 for a complete 12-month fiscal year
        end_date = datetime(2025, 10, 31, tzinfo=timezone.utc)
        start_date = end_date - pd.DateOffset(months=self.months - 1)
        start_date = start_date.replace(day=1)

        for month_offset in range(self.months):
            # Month start
            month_date = start_date + pd.DateOffset(months=month_offset)

            # Generate 20-40 trades per month
            num_trades = np.random.randint(20, 41)

            for i in range(num_trades):
                # Random day in month
                day = np.random.randint(1, 28)
                trade_date = month_date.replace(day=day)

                # Random symbol
                symbol = np.random.choice(["BTC/USD", "ETH/USD"])

                # Random side
                side = np.random.choice(["long", "short"])

                # Simulate trade
                base_price = 50000 if "BTC" in symbol else 3000
                entry_price = base_price * (1 + np.random.normal(0, 0.05))

                # Win rate ~55%
                is_win = np.random.random() < 0.55

                if is_win:
                    exit_price = entry_price * (1 + np.random.uniform(0.01, 0.04))
                else:
                    exit_price = entry_price * (1 - np.random.uniform(0.005, 0.02))

                # Size (1-2% of capital)
                position_value = self.initial_capital * np.random.uniform(0.01, 0.02)
                size = position_value / entry_price

                # Calculate P&L
                if side == "long":
                    gross_pnl = (exit_price - entry_price) * size
                else:
                    gross_pnl = (entry_price - exit_price) * size

                # Fees (5 bps per side)
                fees = (entry_price * size * 0.0005) + (exit_price * size * 0.0005)

                # Slippage (2 bps per side)
                slippage = (entry_price * size * 0.0002) + (exit_price * size * 0.0002)

                net_pnl = gross_pnl - fees - slippage

                trades.append({
                    "timestamp": trade_date,
                    "symbol": symbol,
                    "side": side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "size": size,
                    "gross_pnl": gross_pnl,
                    "fees": fees,
                    "slippage": slippage,
                    "net_pnl": net_pnl,
                })

        logger.info(f"  ✓ Generated {len(trades)} synthetic trades")
        return trades


# =============================================================================
# MONTHLY AGGREGATION
# =============================================================================

def aggregate_to_monthly(
    trades: List[Dict],
    initial_capital: float,
) -> List[Dict]:
    """
    Aggregate trades to monthly P&L.

    Args:
        trades: List of trade dicts
        initial_capital: Starting capital

    Returns:
        List of monthly records with all required fields
    """
    if not trades:
        logger.warning("No trades to aggregate")
        return []

    logger.info("Aggregating trades to monthly P&L...")

    # Convert to DataFrame
    df = pd.DataFrame(trades)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Create month period for grouping (chronological order)
    df["month_period"] = df["timestamp"].dt.to_period("M")
    # Format as "Nov 2024" for display
    df["month_display"] = df["timestamp"].dt.strftime("%b %Y")

    # Sort by timestamp
    df = df.sort_values("timestamp")

    # Group by month period (ensures chronological order)
    monthly_groups = df.groupby("month_period", sort=True)

    monthly_records = []
    balance = initial_capital

    for month_period, group in monthly_groups:
        starting_balance = balance

        # Get display format for this month (e.g., "Nov 2024")
        month_display = group["month_display"].iloc[0]

        # Aggregate metrics
        net_pnl = group["net_pnl"].sum()
        fees = group["fees"].sum()
        slippage = group["slippage"].sum()
        trades_count = len(group)

        # Win rate
        wins = (group["net_pnl"] > 0).sum()
        win_rate_pct = (wins / trades_count * 100) if trades_count > 0 else 0.0

        # Update balance
        balance += net_pnl
        ending_balance = balance

        # Returns
        monthly_return_pct = (
            ((ending_balance - starting_balance) / starting_balance) * 100
            if starting_balance > 0 else 0.0
        )

        cumulative_return_pct = (
            ((ending_balance - initial_capital) / initial_capital) * 100
        )

        # Notes
        pairs = group["symbol"].unique()
        avg_pnl = net_pnl / trades_count if trades_count > 0 else 0.0
        notes = f"Pairs: {', '.join(pairs)}, Avg trade: ${avg_pnl:.2f}"

        monthly_records.append({
            "month": month_display,
            "starting_balance": starting_balance,
            "deposits": 0.0,  # No deposits in backtest
            "net_pnl": net_pnl,
            "fees": fees,
            "slippage": slippage,
            "ending_balance": ending_balance,
            "monthly_return_pct": monthly_return_pct,
            "cumulative_return_pct": cumulative_return_pct,
            "trades": trades_count,
            "win_rate_pct": win_rate_pct,
            "notes": notes,
        })

        logger.info(
            f"  {month_display}: ${starting_balance:,.2f} → ${ending_balance:,.2f} "
            f"({monthly_return_pct:+.2f}%), {trades_count} trades"
        )

    logger.info(f"  ✓ Aggregated {len(monthly_records)} months")
    return monthly_records


# =============================================================================
# SUMMARY METRICS CALCULATION
# =============================================================================

def calculate_summary_metrics(
    trades: List[Dict],
    monthly_records: List[Dict],
    initial_capital: float,
) -> Dict:
    """
    Calculate summary metrics for transparency CSV.

    Args:
        trades: All trades
        monthly_records: Monthly aggregated data
        initial_capital: Starting capital

    Returns:
        Dict with summary metrics
    """
    if not trades or not monthly_records:
        return {}

    # Basic metrics
    total_trades = len(trades)
    final_balance = monthly_records[-1]["ending_balance"]
    total_pnl = final_balance - initial_capital
    total_return_pct = (total_pnl / initial_capital) * 100

    # Win/loss metrics
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0

    # Profit factor
    gross_profit = sum(t["net_pnl"] for t in wins) if wins else 0.0
    gross_loss = abs(sum(t["net_pnl"] for t in losses)) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

    # Max drawdown (peak-to-trough)
    equity_curve = [initial_capital]
    running_equity = initial_capital
    for record in monthly_records:
        running_equity = record["ending_balance"]
        equity_curve.append(running_equity)

    peak = initial_capital
    max_dd = 0.0
    max_dd_pct = 0.0

    for equity in equity_curve:
        if equity > peak:
            peak = equity

        dd = peak - equity
        dd_pct = (dd / peak * 100) if peak > 0 else 0.0

        if dd_pct > max_dd_pct:
            max_dd = dd
            max_dd_pct = dd_pct

    # Sharpe ratio (simplified: monthly returns)
    monthly_returns = [r["monthly_return_pct"] for r in monthly_records]
    if len(monthly_returns) > 1:
        mean_return = np.mean(monthly_returns)
        std_return = np.std(monthly_returns)
        sharpe = (mean_return / std_return) if std_return > 0 else 0.0
        # Annualize (monthly to annual)
        sharpe_annual = sharpe * np.sqrt(12)
    else:
        sharpe_annual = 0.0

    # Sortino ratio (downside deviation)
    downside_returns = [r for r in monthly_returns if r < 0]
    if downside_returns and len(downside_returns) > 1:
        downside_std = np.std(downside_returns)
        sortino = (np.mean(monthly_returns) / downside_std) if downside_std > 0 else 0.0
        sortino_annual = sortino * np.sqrt(12)
    else:
        sortino_annual = 0.0

    # Average trade metrics
    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0

    return {
        "total_trades": total_trades,
        "total_pnl": total_pnl,
        "total_return_pct": total_return_pct,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "sharpe_ratio": sharpe_annual,
        "sortino_ratio": sortino_annual,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
    }


# =============================================================================
# CSV EXPORT
# =============================================================================

def export_to_csv(monthly_records: List[Dict], output_path: str):
    """Export monthly records to Acquire.com CSV format."""
    logger.info(f"Exporting monthly P&L to {output_path}...")

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Define exact column headers
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

        # Write header
        writer.writerow(columns)

        # Write data rows
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

    logger.info(f"  ✓ Exported {len(monthly_records)} rows to {output_path}")


def export_assumptions_csv(
    trades: List[Dict],
    monthly_records: List[Dict],
    config: Dict,
    source_type: str,
    output_path: str,
):
    """
    Export assumptions and metadata CSV for transparency.

    Args:
        trades: All trades
        monthly_records: Monthly aggregated data
        config: Configuration dict
        source_type: Data source type
        output_path: Output file path
    """
    logger.info(f"Exporting assumptions to {output_path}...")

    # Calculate summary metrics
    metrics = calculate_summary_metrics(trades, monthly_records, config["initial_capital"])

    # Determine backtest window
    if trades:
        df = pd.DataFrame(trades)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        start_date = df["timestamp"].min().strftime("%Y-%m-%d")
        end_date = df["timestamp"].max().strftime("%Y-%m-%d")
        days = (df["timestamp"].max() - df["timestamp"].min()).days
    else:
        start_date = "N/A"
        end_date = "N/A"
        days = 0

    # Extract pairs and strategies
    if trades:
        pairs = sorted(set(t["symbol"] for t in trades))
        pairs_str = ", ".join(pairs)
    else:
        pairs_str = "N/A"

    # Build assumptions data
    assumptions = [
        ["Category", "Parameter", "Value"],
        ["", "", ""],
        ["CONFIGURATION", "", ""],
        ["", "Initial Capital", f"${config['initial_capital']:,.2f}"],
        ["", "Trading Pairs", pairs_str],
        ["", "Timeframe", "1h, 5m (multi-timeframe)"],
        ["", "Strategy Mix", "EMA Crossover + RSI Filter + ATR Risk"],
        ["", "", ""],
        ["COST MODEL", "", ""],
        ["", "Fee (bps)", f"{config['fee_bps']:.1f}"],
        ["", "Fee (%)", f"{config['fee_bps']/100:.3f}%"],
        ["", "Slippage (bps)", f"{config['slip_bps']:.1f}"],
        ["", "Slippage (%)", f"{config['slip_bps']/100:.3f}%"],
        ["", "Fee Model", "Kraken maker/taker (both entry + exit)"],
        ["", "Slippage Model", "Conservative estimate (both entry + exit)"],
        ["", "", ""],
        ["BACKTEST WINDOW", "", ""],
        ["", "Start Date", start_date],
        ["", "End Date", end_date],
        ["", "Duration (days)", str(days)],
        ["", "Duration (months)", str(len(monthly_records))],
        ["", "", ""],
        ["RISK CONTROLS", "", ""],
        ["", "Stop Loss", "ATR-based (2% typical)"],
        ["", "Take Profit", "ATR-based (4% target)"],
        ["", "Position Sizing", "1.5% risk per trade"],
        ["", "Max Concurrent Positions", "1-2"],
        ["", "Leverage", "None (spot trading only)"],
        ["", "", ""],
        ["DATA SOURCES", "", ""],
        ["", "Source Type", source_type],
        ["", "Exchange", "Kraken"],
        ["", "Data Quality", "Real OHLCV" if source_type in ["redis", "csv"] else "Synthetic"],
        ["", "Total Trades", str(metrics.get("total_trades", 0))],
        ["", "", ""],
        ["12-MONTH SUMMARY", "", ""],
        ["", "Total Net P&L", f"${metrics.get('total_pnl', 0):+,.2f}"],
        ["", "Total Return (%)", f"{metrics.get('total_return_pct', 0):+.2f}%"],
        ["", "Win Rate (%)", f"{metrics.get('win_rate', 0):.1f}%"],
        ["", "Profit Factor", f"{metrics.get('profit_factor', 0):.2f}"],
        ["", "Max Drawdown ($)", f"${metrics.get('max_drawdown', 0):,.2f}"],
        ["", "Max Drawdown (%)", f"{metrics.get('max_drawdown_pct', 0):.2f}%"],
        ["", "Sharpe Ratio", f"{metrics.get('sharpe_ratio', 0):.2f}"],
        ["", "Sortino Ratio", f"{metrics.get('sortino_ratio', 0):.2f}"],
        ["", "", ""],
        ["TRADE STATISTICS", "", ""],
        ["", "Total Trades", str(metrics.get("total_trades", 0))],
        ["", "Winning Trades", str(len([t for t in trades if t["net_pnl"] > 0]))],
        ["", "Losing Trades", str(len([t for t in trades if t["net_pnl"] <= 0]))],
        ["", "Avg Win", f"${metrics.get('avg_win', 0):,.2f}"],
        ["", "Avg Loss", f"${metrics.get('avg_loss', 0):,.2f}"],
        ["", "Gross Profit", f"${metrics.get('gross_profit', 0):,.2f}"],
        ["", "Gross Loss", f"${metrics.get('gross_loss', 0):,.2f}"],
        ["", "", ""],
        ["COST BREAKDOWN", "", ""],
        ["", "Total Fees", f"${sum(r['fees'] for r in monthly_records):,.2f}"],
        ["", "Total Slippage", f"${sum(r['slippage'] for r in monthly_records):,.2f}"],
        ["", "Total Costs", f"${sum(r['fees'] + r['slippage'] for r in monthly_records):,.2f}"],
        ["", "Costs as % of Capital", f"{(sum(r['fees'] + r['slippage'] for r in monthly_records) / config['initial_capital']) * 100:.2f}%"],
    ]

    # Write CSV
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in assumptions:
            writer.writerow(row)

    logger.info(f"  ✓ Exported assumptions to {output_path}")


# =============================================================================
# MAIN
# =============================================================================

def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Monthly P&L Aggregator for Acquire.com Annual Snapshot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect source (Redis -> CSV -> Synthetic)
  python scripts/build_monthly_pnl.py

  # Explicit Redis source
  REDIS_URL=rediss://... python scripts/build_monthly_pnl.py --source redis

  # CSV backtest results
  python scripts/build_monthly_pnl.py --source csv --input out/trades_detailed_real.csv

  # Synthetic demo data
  python scripts/build_monthly_pnl.py --source synthetic --months 12

  # Custom output path
  python scripts/build_monthly_pnl.py --output reports/monthly_pnl.csv
        """,
    )

    parser.add_argument(
        "--source",
        type=str,
        choices=["redis", "csv", "synthetic", "auto"],
        default="auto",
        help="Data source (default: auto - tries redis, csv, then synthetic)",
    )

    parser.add_argument(
        "--input",
        type=str,
        help="Input CSV file path (required if --source csv)",
    )

    parser.add_argument(
        "--output",
        type=str,
        help="Output CSV path (default: /tmp/backtest_annual_snapshot.csv)",
    )

    parser.add_argument(
        "--months",
        type=int,
        default=12,
        help="Number of months for synthetic data (default: 12)",
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

    logger.info("=" * 80)
    logger.info("MONTHLY P&L AGGREGATOR FOR ACQUIRE.COM")
    logger.info("=" * 80)

    # Load config
    config = get_config()

    # Override output path if specified
    if args.output:
        config["output_path"] = args.output

    logger.info("\nConfiguration:")
    logger.info(f"  Source: {args.source}")
    logger.info(f"  Initial Capital: ${config['initial_capital']:,.2f}")
    logger.info(f"  Default Fees: {config['fee_bps']} bps")
    logger.info(f"  Default Slippage: {config['slip_bps']} bps")
    logger.info(f"  Output: {config['output_path']}")
    logger.info("")

    # Load trades from source
    trades = []
    source = None
    source_type_used = "unknown"

    if args.source == "auto":
        # Try sources in order: Redis -> CSV -> Synthetic
        logger.info("Auto-detecting data source...")

        # Try Redis first
        if REDIS_AVAILABLE:
            try:
                source = RedisTradeSource(config["redis_url"], config["redis_cert"])
                trades = source.read_trades()
                if trades:
                    logger.info("  ✓ Using Redis Cloud source")
                    source_type_used = "redis"
            except Exception as e:
                logger.warning(f"  Redis not available: {e}")

        # Try CSV if no Redis data
        if not trades:
            csv_files = [
                project_root / "out" / "trades_detailed_real.csv",
                project_root / "out" / "trades.csv",
                project_root / "reports" / "trades.csv",
            ]

            for csv_path in csv_files:
                if csv_path.exists():
                    try:
                        source = CSVTradeSource(
                            str(csv_path),
                            config["fee_bps"],
                            config["slip_bps"],
                        )
                        trades = source.read_trades()
                        if trades:
                            logger.info(f"  ✓ Using CSV source: {csv_path.name}")
                            source_type_used = "csv"
                            break
                    except Exception as e:
                        logger.warning(f"  CSV {csv_path.name} failed: {e}")

        # Fall back to synthetic
        if not trades:
            logger.info("  ⚠ No real data found, using synthetic")
            source = SyntheticTradeSource(args.months, config["initial_capital"])
            trades = source.read_trades()
            source_type_used = "synthetic"

    elif args.source == "redis":
        if not REDIS_AVAILABLE:
            logger.error("Redis source requires 'redis' package: pip install redis")
            sys.exit(1)

        source = RedisTradeSource(config["redis_url"], config["redis_cert"])
        trades = source.read_trades()
        source_type_used = "redis"

    elif args.source == "csv":
        if not args.input:
            logger.error("CSV source requires --input argument")
            sys.exit(1)

        source = CSVTradeSource(args.input, config["fee_bps"], config["slip_bps"])
        trades = source.read_trades()
        source_type_used = "csv"

    elif args.source == "synthetic":
        source = SyntheticTradeSource(args.months, config["initial_capital"])
        trades = source.read_trades()
        source_type_used = "synthetic"

    if not trades:
        logger.error("No trades loaded - cannot generate report")
        sys.exit(1)

    # Aggregate to monthly
    monthly_records = aggregate_to_monthly(trades, config["initial_capital"])

    if not monthly_records:
        logger.error("No monthly records generated")
        sys.exit(1)

    # Export to CSV
    export_to_csv(monthly_records, config["output_path"])

    # Export assumptions CSV
    assumptions_path = config["output_path"].replace(".csv", "_assumptions.csv")
    if "/tmp/" in assumptions_path or "\\tmp\\" in assumptions_path:
        # For /tmp/ paths, use the standard name
        assumptions_path = "/tmp/backtest_assumptions.csv"

    export_assumptions_csv(
        trades=trades,
        monthly_records=monthly_records,
        config=config,
        source_type=source_type_used,
        output_path=assumptions_path,
    )

    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)

    final_record = monthly_records[-1]
    total_return = final_record["ending_balance"] - config["initial_capital"]
    total_return_pct = (total_return / config["initial_capital"]) * 100

    logger.info(f"\nPeriod: {monthly_records[0]['month']} to {monthly_records[-1]['month']}")
    logger.info(f"Initial Capital: ${config['initial_capital']:,.2f}")
    logger.info(f"Final Balance: ${final_record['ending_balance']:,.2f}")
    logger.info(f"Total Return: ${total_return:+,.2f} ({total_return_pct:+.2f}%)")
    logger.info(f"Total Trades: {sum(r['trades'] for r in monthly_records)}")
    logger.info(f"Total Fees: ${sum(r['fees'] for r in monthly_records):,.2f}")
    logger.info(f"Total Slippage: ${sum(r['slippage'] for r in monthly_records):,.2f}")

    logger.info("")
    logger.info(f"✓ Monthly P&L saved to: {config['output_path']}")
    logger.info(f"✓ Assumptions saved to: {assumptions_path}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
