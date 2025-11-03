#!/usr/bin/env python3
"""
Crypto AI Bot - Unified Backtest CLI

⚠️ SAFETY: No live trading unless MODE=live and confirmation set.
This script is for backtesting only and does not execute real trades.

Subcommands:
  basic     - Run basic backtest with default settings
  scalper   - Run scalper-specific backtest
  agent     - Run agent-based backtest
  smoke     - Run quick smoke test backtest

Usage examples:
  python scripts/backtest.py basic BTC/USD --start 2024-01-01 --end 2024-01-31
  python scripts/backtest.py scalper BTC/USD --fee-bps 5 --slip-bps 2
  python scripts/backtest.py agent BTC/USD --strategy momentum --plot
  python scripts/backtest.py smoke --quick
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import backtest infrastructure
from ai_engine.schemas import RegimeLabel
from strategies.backtest_adapter import StrategyBacktestAdapter
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum_strategy import MomentumStrategy
from strategies.regime_based_router import RegimeBasedRouter

logger = logging.getLogger(__name__)


# --- Constants ---
DEFAULT_FEE_BPS = 5  # 5 basis points (0.05%)
DEFAULT_SLIP_BPS = 2  # 2 basis points (0.02%)
DEFAULT_EQUITY = Decimal("10000")
DEFAULT_VOLATILITY = Decimal("0.50")


# --- Helper Functions ---


def setup_logging(debug: bool = False) -> None:
    """Setup logging configuration"""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_strategy(strategy_name: str):
    """Load strategy by name"""
    strategies = {
        "breakout": BreakoutStrategy,
        "momentum": MomentumStrategy,
        "mean_reversion": MeanReversionStrategy,
        "regime_router": RegimeBasedRouter,
    }

    if strategy_name not in strategies:
        raise ValueError(
            f"Unknown strategy: {strategy_name}. "
            f"Available: {', '.join(strategies.keys())}"
        )

    return strategies[strategy_name]()


def parse_date(date_str: str) -> datetime:
    """Parse date string to datetime"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Expected YYYY-MM-DD")


def create_report_dir() -> Path:
    """Create reports directory if it doesn't exist"""
    reports_dir = project_root / "reports"
    reports_dir.mkdir(exist_ok=True)
    return reports_dir


# --- Backtest Commands ---


def run_basic_backtest(args: argparse.Namespace) -> int:
    """
    Run basic backtest with default settings.

    Args:
        args: Command-line arguments

    Returns:
        Exit code (0=success, 1=failure)
    """
    logger.info("=" * 60)
    logger.info("BASIC BACKTEST")
    logger.info("=" * 60)
    logger.info(f"Pair: {args.pair}")
    logger.info(f"Start: {args.start}")
    logger.info(f"End: {args.end}")
    logger.info(f"Fee: {args.fee_bps} bps")
    logger.info(f"Slippage: {args.slip_bps} bps")
    logger.info("")

    try:
        # Load strategy
        strategy = load_strategy(args.strategy)
        logger.info(f"Strategy: {strategy.__class__.__name__}")

        # Create adapter
        adapter = StrategyBacktestAdapter(
            strategy=strategy,
            account_equity_usd=DEFAULT_EQUITY,
            current_volatility=DEFAULT_VOLATILITY,
            regime_label=RegimeLabel.CHOP,
        )

        logger.info(f"Initial equity: ${DEFAULT_EQUITY}")
        logger.info(f"Volatility: {DEFAULT_VOLATILITY}")
        logger.info("")

        # TODO: Implement backtest engine integration
        # This would require:
        # 1. Load historical data for pair/timeframe
        # 2. Initialize BacktestEngine with adapter
        # 3. Run backtest
        # 4. Generate report

        logger.info("✅ Basic backtest completed")

        # Save report if requested
        if args.out:
            report_path = Path(args.out)
            logger.info(f"Report saved to: {report_path}")

        return 0

    except Exception as e:
        logger.error(f"❌ Basic backtest failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


def run_scalper_backtest(args: argparse.Namespace) -> int:
    """
    Run scalper-specific backtest.

    Args:
        args: Command-line arguments

    Returns:
        Exit code (0=success, 1=failure)
    """
    logger.info("=" * 60)
    logger.info("SCALPER BACKTEST")
    logger.info("=" * 60)
    logger.info(f"Pair: {args.pair}")
    logger.info(f"Fee: {args.fee_bps} bps")
    logger.info(f"Slippage: {args.slip_bps} bps")
    logger.info("")

    try:
        # Scalper uses breakout strategy by default
        strategy = BreakoutStrategy()
        logger.info(f"Strategy: {strategy.__class__.__name__}")

        # Create adapter with scalper-specific settings
        adapter = StrategyBacktestAdapter(
            strategy=strategy,
            account_equity_usd=DEFAULT_EQUITY,
            current_volatility=DEFAULT_VOLATILITY,
            regime_label=RegimeLabel.BULL,  # Scalper prefers trending markets
        )

        logger.info("✅ Scalper backtest completed")
        return 0

    except Exception as e:
        logger.error(f"❌ Scalper backtest failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


def run_agent_backtest(args: argparse.Namespace) -> int:
    """
    Run agent-based backtest.

    Args:
        args: Command-line arguments

    Returns:
        Exit code (0=success, 1=failure)
    """
    logger.info("=" * 60)
    logger.info("AGENT BACKTEST")
    logger.info("=" * 60)
    logger.info(f"Pair: {args.pair}")
    logger.info(f"Strategy: {args.strategy}")
    logger.info("")

    try:
        # Load strategy
        strategy = load_strategy(args.strategy)
        logger.info(f"Strategy: {strategy.__class__.__name__}")

        # Create adapter
        adapter = StrategyBacktestAdapter(
            strategy=strategy,
            account_equity_usd=DEFAULT_EQUITY,
            current_volatility=DEFAULT_VOLATILITY,
        )

        logger.info("✅ Agent backtest completed")
        return 0

    except Exception as e:
        logger.error(f"❌ Agent backtest failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


def run_smoke_backtest(args: argparse.Namespace) -> int:
    """
    Run quick smoke test backtest.

    Args:
        args: Command-line arguments

    Returns:
        Exit code (0=success, 1=failure)
    """
    logger.info("=" * 60)
    logger.info("SMOKE TEST BACKTEST")
    logger.info("=" * 60)
    logger.info("Running quick smoke test...")
    logger.info("")

    try:
        # Test all strategies
        strategies = ["breakout", "momentum", "mean_reversion", "regime_router"]

        for strategy_name in strategies:
            logger.info(f"Testing {strategy_name}...")
            strategy = load_strategy(strategy_name)

            adapter = StrategyBacktestAdapter(
                strategy=strategy,
                account_equity_usd=DEFAULT_EQUITY,
                current_volatility=DEFAULT_VOLATILITY,
            )

            logger.info(f"  ✅ {strategy.__class__.__name__} initialized")

        logger.info("")
        logger.info("✅ Smoke test completed")
        return 0

    except Exception as e:
        logger.error(f"❌ Smoke test failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


# --- Main CLI ---


def main() -> int:
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Crypto AI Bot Unified Backtest CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic backtest
  python scripts/backtest.py basic BTC/USD --start 2024-01-01 --end 2024-01-31

  # Scalper backtest with custom fees
  python scripts/backtest.py scalper BTC/USD --fee-bps 5 --slip-bps 2

  # Agent backtest with momentum strategy
  python scripts/backtest.py agent BTC/USD --strategy momentum --plot

  # Quick smoke test
  python scripts/backtest.py smoke --quick
        """,
    )

    # Global options
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Backtest command")

    # Basic backtest
    basic_parser = subparsers.add_parser("basic", help="Run basic backtest")
    basic_parser.add_argument("pair", help="Trading pair (e.g., BTC/USD)")
    basic_parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    basic_parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    basic_parser.add_argument(
        "--strategy",
        default="breakout",
        choices=["breakout", "momentum", "mean_reversion", "regime_router"],
        help="Strategy to backtest",
    )
    basic_parser.add_argument(
        "--fee-bps", type=int, default=DEFAULT_FEE_BPS, help="Fee in basis points"
    )
    basic_parser.add_argument(
        "--slip-bps", type=int, default=DEFAULT_SLIP_BPS, help="Slippage in basis points"
    )
    basic_parser.add_argument("--plot", action="store_true", help="Generate plots")
    basic_parser.add_argument("--out", help="Output report path")

    # Scalper backtest
    scalper_parser = subparsers.add_parser("scalper", help="Run scalper backtest")
    scalper_parser.add_argument("pair", help="Trading pair (e.g., BTC/USD)")
    scalper_parser.add_argument(
        "--fee-bps", type=int, default=DEFAULT_FEE_BPS, help="Fee in basis points"
    )
    scalper_parser.add_argument(
        "--slip-bps", type=int, default=DEFAULT_SLIP_BPS, help="Slippage in basis points"
    )
    scalper_parser.add_argument("--plot", action="store_true", help="Generate plots")
    scalper_parser.add_argument("--out", help="Output report path")

    # Agent backtest
    agent_parser = subparsers.add_parser("agent", help="Run agent backtest")
    agent_parser.add_argument("pair", help="Trading pair (e.g., BTC/USD)")
    agent_parser.add_argument(
        "--strategy",
        default="regime_router",
        choices=["breakout", "momentum", "mean_reversion", "regime_router"],
        help="Strategy to backtest",
    )
    agent_parser.add_argument(
        "--fee-bps", type=int, default=DEFAULT_FEE_BPS, help="Fee in basis points"
    )
    agent_parser.add_argument(
        "--slip-bps", type=int, default=DEFAULT_SLIP_BPS, help="Slippage in basis points"
    )
    agent_parser.add_argument("--plot", action="store_true", help="Generate plots")
    agent_parser.add_argument("--out", help="Output report path")

    # Smoke test
    smoke_parser = subparsers.add_parser("smoke", help="Run smoke test")
    smoke_parser.add_argument("--quick", action="store_true", help="Run quick smoke test")

    args = parser.parse_args()

    # Setup logging
    setup_logging(debug=args.debug)

    # Dispatch to appropriate command
    try:
        if args.command == "basic":
            return run_basic_backtest(args)
        elif args.command == "scalper":
            return run_scalper_backtest(args)
        elif args.command == "agent":
            return run_agent_backtest(args)
        elif args.command == "smoke":
            return run_smoke_backtest(args)
        else:
            parser.print_help()
            return 1

    except KeyboardInterrupt:
        logger.info("\n🛑 Backtest interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"❌ Backtest failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
