#!/usr/bin/env python3
"""
M1 - Paper Trading Validation Script

Loads paper trading results and validates against M1 criteria:
- Performance: PF ≥ 1.30, Sharpe ≥ 1.0, MaxDD ≤ 6%, ≥ 60 trades
- Execution: Maker fill ratio ≥ 65%, spread skips < 25%
- Risk: No >3 loss streak without cooldown

Usage:
    python scripts/validate_paper_trading.py --trades reports/paper_trades.csv --signals reports/paper_signals.csv
    python scripts/validate_paper_trading.py --start-date 2024-10-01 --end-date 2024-10-14
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import redis

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from monitoring.paper_trading_validator import (
    PaperTradingValidator,
    PaperTradingCriteria,
)

logger = logging.getLogger(__name__)


def load_trades_from_csv(csv_path: Path) -> pd.DataFrame:
    """
    Load trades from CSV file.

    Expected columns: entry_time, exit_time, pnl, pnl_pct, status, fill_type
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Trades CSV not found: {csv_path}")

    df = pd.read_csv(csv_path, parse_dates=["entry_time", "exit_time"])

    logger.info(f"Loaded {len(df)} trades from {csv_path}")

    return df


def load_signals_from_csv(csv_path: Path) -> pd.DataFrame:
    """
    Load signals from CSV file.

    Expected columns: timestamp, action, reason
    """
    if not csv_path.exists():
        logger.warning(f"Signals CSV not found: {csv_path}, creating empty DataFrame")
        return pd.DataFrame(columns=["timestamp", "action", "reason"])

    df = pd.read_csv(csv_path, parse_dates=["timestamp"])

    logger.info(f"Loaded {len(df)} signals from {csv_path}")

    return df


def load_from_redis(
    redis_url: str,
    tls_ca_cert: str,
    start_date: datetime,
    end_date: datetime,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load trades and signals from Redis streams.

    Args:
        redis_url: Redis connection URL
        tls_ca_cert: Path to TLS CA certificate
        start_date: Start date for data
        end_date: End date for data

    Returns:
        Tuple of (trades_df, signals_df)
    """
    logger.info(f"Connecting to Redis: {redis_url}")

    # Connect to Redis
    r = redis.from_url(
        redis_url,
        ssl_ca_certs=tls_ca_cert,
        decode_responses=True,
    )

    # Load closed trades from stream
    trades_stream = "pnl:closed_trades"
    trades_data = []

    try:
        # Read all trades from stream
        messages = r.xrange(trades_stream, "-", "+")

        for msg_id, data in messages:
            # Parse timestamp from message ID
            ts_ms = int(msg_id.split("-")[0])
            timestamp = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

            if start_date <= timestamp <= end_date:
                # Convert Redis hash to trade dict
                trade = {
                    "entry_time": pd.to_datetime(data.get("entry_time")),
                    "exit_time": pd.to_datetime(data.get("exit_time")),
                    "pnl": float(data.get("pnl", 0)),
                    "pnl_pct": float(data.get("pnl_pct", 0)),
                    "status": data.get("status", "closed"),
                    "fill_type": data.get("fill_type", "maker"),
                    "initial_capital": float(data.get("initial_capital", 10000)),
                }
                trades_data.append(trade)

        logger.info(f"Loaded {len(trades_data)} trades from Redis")

    except Exception as e:
        logger.error(f"Failed to load trades from Redis: {e}")

    # Load signals from stream
    signals_stream = "metrics:paper_signals"
    signals_data = []

    try:
        messages = r.xrange(signals_stream, "-", "+")

        for msg_id, data in messages:
            ts_ms = int(msg_id.split("-")[0])
            timestamp = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

            if start_date <= timestamp <= end_date:
                signal = {
                    "timestamp": timestamp,
                    "action": data.get("action", "signal"),
                    "reason": data.get("reason", ""),
                }
                signals_data.append(signal)

        logger.info(f"Loaded {len(signals_data)} signals from Redis")

    except Exception as e:
        logger.error(f"Failed to load signals from Redis: {e}")

    # Convert to DataFrames
    trades_df = pd.DataFrame(trades_data) if trades_data else pd.DataFrame(columns=["entry_time", "exit_time", "pnl", "pnl_pct", "status", "fill_type"])
    signals_df = pd.DataFrame(signals_data) if signals_data else pd.DataFrame(columns=["timestamp", "action", "reason"])

    return trades_df, signals_df


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="M1 - Paper Trading Validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # From CSV files
  python scripts/validate_paper_trading.py \\
      --trades reports/paper_trades.csv \\
      --signals reports/paper_signals.csv

  # From Redis (7-day period)
  python scripts/validate_paper_trading.py \\
      --from-redis \\
      --start-date 2024-10-01 \\
      --end-date 2024-10-08

  # Custom criteria
  python scripts/validate_paper_trading.py \\
      --trades reports/paper_trades.csv \\
      --min-profit-factor 1.5 \\
      --min-sharpe 1.2
        """,
    )

    # Data sources
    parser.add_argument(
        "--trades",
        type=str,
        help="Path to trades CSV file",
    )

    parser.add_argument(
        "--signals",
        type=str,
        help="Path to signals CSV file",
    )

    parser.add_argument(
        "--from-redis",
        action="store_true",
        help="Load data from Redis streams",
    )

    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date (YYYY-MM-DD) for Redis data",
    )

    parser.add_argument(
        "--end-date",
        type=str,
        help="End date (YYYY-MM-DD) for Redis data (default: today)",
    )

    # Redis connection
    parser.add_argument(
        "--redis-url",
        type=str,
        default="redis://default:***@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818",
        help="Redis connection URL",
    )

    parser.add_argument(
        "--redis-tls-cert",
        type=str,
        default="config/certs/redis_ca.pem",
        help="Path to Redis TLS CA certificate",
    )

    # Criteria overrides
    parser.add_argument(
        "--min-profit-factor",
        type=float,
        default=1.30,
        help="Minimum profit factor (default: 1.30)",
    )

    parser.add_argument(
        "--min-sharpe",
        type=float,
        default=1.0,
        help="Minimum Sharpe ratio (default: 1.0)",
    )

    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=6.0,
        help="Maximum drawdown %% (default: 6.0)",
    )

    parser.add_argument(
        "--min-trades",
        type=int,
        default=60,
        help="Minimum number of trades (default: 60)",
    )

    parser.add_argument(
        "--min-maker-fill",
        type=float,
        default=0.65,
        help="Minimum maker fill ratio (default: 0.65)",
    )

    parser.add_argument(
        "--max-spread-skip",
        type=float,
        default=0.25,
        help="Maximum spread skip ratio (default: 0.25)",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="reports/paper_validation.txt",
        help="Output report path (default: reports/paper_validation.txt)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point"""
    args = parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print("=" * 80)
    print("M1 - PAPER TRADING VALIDATION")
    print("=" * 80)
    print()

    # Load data
    if args.from_redis:
        # Parse dates
        if not args.start_date:
            logger.error("--start-date required when using --from-redis")
            return 1

        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        if args.end_date:
            end_date = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            end_date = datetime.now(timezone.utc)

        # Load from Redis
        tls_cert = project_root / args.redis_tls_cert
        trades_df, signals_df = load_from_redis(
            args.redis_url,
            str(tls_cert),
            start_date,
            end_date,
        )

    else:
        # Load from CSV
        if not args.trades:
            logger.error("--trades required when not using --from-redis")
            return 1

        trades_path = project_root / args.trades
        trades_df = load_trades_from_csv(trades_path)

        if args.signals:
            signals_path = project_root / args.signals
            signals_df = load_signals_from_csv(signals_path)
        else:
            signals_df = pd.DataFrame(columns=["timestamp", "action", "reason"])

        # Infer dates from trades
        if len(trades_df) > 0:
            start_date = trades_df["entry_time"].min()
            end_date = trades_df["exit_time"].max()
        else:
            start_date = datetime.now(timezone.utc)
            end_date = datetime.now(timezone.utc)

    # Create criteria
    criteria = PaperTradingCriteria(
        min_profit_factor=args.min_profit_factor,
        min_sharpe_ratio=args.min_sharpe,
        max_drawdown_pct=args.max_drawdown,
        min_trades=args.min_trades,
        min_maker_fill_ratio=args.min_maker_fill,
        max_spread_skip_ratio=args.max_spread_skip,
    )

    # Create validator
    validator = PaperTradingValidator(criteria=criteria)

    # Calculate metrics
    logger.info("Calculating paper trading metrics...")
    metrics = validator.calculate_metrics_from_trades(
        trades_df=trades_df,
        signals_df=signals_df,
        start_date=start_date,
        end_date=end_date,
    )

    # Generate report
    report = validator.generate_validation_report(metrics)

    # Print report
    print(report)
    print()

    # Save report
    output_path = project_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(report)

    logger.info(f"Validation report saved to {output_path}")

    # Exit code based on validation result
    if metrics.overall_pass and metrics.days_elapsed >= criteria.min_paper_days:
        logger.info("[OK] Paper trading validation PASSED - ready for LIVE")
        return 0
    else:
        logger.warning("[X] Paper trading validation FAILED - continue paper trading")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
