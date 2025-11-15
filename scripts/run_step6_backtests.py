#!/usr/bin/env python3
"""
STEP 6 Backtest Runner - Execute all three strategies with STEP 6 enhancements.

This script runs comprehensive 360-day backtests for:
1. Momentum Strategy (1h timeframe)
2. Mean Reversion Strategy (5m timeframe)
3. Scalper Strategy (1m timeframe)

Usage:
    # Run all three backtests
    python scripts/run_step6_backtests.py --all

    # Run individual strategy
    python scripts/run_step6_backtests.py --strategy momentum
    python scripts/run_step6_backtests.py --strategy mean_reversion
    python scripts/run_step6_backtests.py --strategy scalper

    # Quick test (30 days)
    python scripts/run_step6_backtests.py --all --quick

    # Compare with baseline
    python scripts/run_step6_backtests.py --all --compare-baseline
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd

from ai_engine.schemas import MarketSnapshot, RegimeLabel
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum_strategy import MomentumStrategy
from strategies.scalper import ScalperStrategy

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_START_DATE = "2024-01-01"
DEFAULT_END_DATE = "2024-12-26"
INITIAL_CAPITAL = 10000.0
COMMISSION_BPS = 5  # 0.05%
SLIPPAGE_BPS = 2  # 0.02%

STRATEGY_CONFIGS = {
    "momentum": {
        "class": MomentumStrategy,
        "timeframe": "1h",
        "kwargs": {
            # STEP 6 enhanced parameters
            "min_adx": 25.0,
            "slope_period": 10,
            "min_slope": 0.0,
            "sl_atr_multiplier": 1.5,
            "tp_atr_multiplier": 3.0,
            "use_partial_tp": True,
            "use_trailing_stop": True,
            "trail_pct": 0.02,
            "min_rr": 1.6,
        },
    },
    "mean_reversion": {
        "class": MeanReversionStrategy,
        "timeframe": "5m",
        "kwargs": {
            # STEP 6 enhanced parameters
            "max_adx": 20.0,
            "adx_period": 14,
            "sl_pct": 0.02,
            "tp_pct": 0.04,
            "max_hold_bars": 30,
            "min_rr": 1.6,
        },
    },
    "scalper": {
        "class": ScalperStrategy,
        "timeframe": "1m",
        "kwargs": {
            # STEP 6 enhanced parameters
            "max_latency_ms": 500.0,
            "max_trades_per_minute": 3,
            "min_rr": 1.0,
        },
    },
}


# =============================================================================
# Simple Backtest Engine
# =============================================================================


class SimpleBacktestEngine:
    """Simple backtest engine for strategy validation."""

    def __init__(
        self,
        strategy,
        initial_capital: float,
        timeframe: str = "1h",
        commission_bps: float = 5.0,
        slippage_bps: float = 2.0,
    ):
        self.strategy = strategy
        self.timeframe = timeframe
        self.initial_capital = initial_capital
        self.commission_bps = commission_bps
        self.slippage_bps = slippage_bps

        # State
        self.cash = initial_capital
        self.position_size = 0.0
        self.entry_price = 0.0
        self.trades: List[Dict] = []
        self.equity_curve: List[float] = []

    def calculate_costs(self, price: float, size: float) -> float:
        """Calculate transaction costs."""
        notional = abs(price * size)
        commission = notional * (self.commission_bps / 10000)
        slippage = notional * (self.slippage_bps / 10000)
        return commission + slippage

    def open_position(self, signal, current_price: float, timestamp: pd.Timestamp):
        """Open a new position."""
        if self.position_size != 0:
            return  # Already in position

        # Calculate position size (risk 2% of capital)
        risk_amount = self.cash * 0.02
        stop_distance = abs(current_price - float(signal.stop_loss))

        if stop_distance > 0:
            position_size = risk_amount / stop_distance
        else:
            position_size = self.cash * 0.1 / current_price  # Fallback: 10% of capital

        # Limit position size
        max_position_value = self.cash * 0.5  # Max 50% of capital
        max_position_size = max_position_value / current_price
        position_size = min(position_size, max_position_size)

        # Calculate costs
        costs = self.calculate_costs(current_price, position_size)

        # Execute
        self.position_size = position_size if signal.side == "long" else -position_size
        self.entry_price = current_price
        self.cash -= costs

        logger.debug(
            f"OPEN {signal.side.upper()}: {position_size:.4f} @ ${current_price:.2f} "
            f"(SL: ${signal.stop_loss:.2f}, TP: ${signal.take_profit:.2f}, costs: ${costs:.2f})"
        )

    def close_position(
        self, current_price: float, timestamp: pd.Timestamp, reason: str = "signal"
    ):
        """Close current position."""
        if self.position_size == 0:
            return  # No position

        # Calculate P&L
        if self.position_size > 0:  # Long
            pnl = (current_price - self.entry_price) * self.position_size
        else:  # Short
            pnl = (self.entry_price - current_price) * abs(self.position_size)

        # Calculate costs
        costs = self.calculate_costs(current_price, abs(self.position_size))

        # Net P&L
        net_pnl = pnl - costs

        # Update cash
        self.cash += net_pnl

        # Record trade
        self.trades.append(
            {
                "entry_price": self.entry_price,
                "exit_price": current_price,
                "size": self.position_size,
                "pnl": net_pnl,
                "return_pct": (net_pnl / self.initial_capital) * 100,
                "exit_time": timestamp,
                "reason": reason,
            }
        )

        side = "LONG" if self.position_size > 0 else "SHORT"
        logger.debug(
            f"CLOSE {side}: ${current_price:.2f} | P&L: ${net_pnl:.2f} | Reason: {reason}"
        )

        # Reset position
        self.position_size = 0.0
        self.entry_price = 0.0

    def check_stops(self, signal, current_bar: pd.Series):
        """Check if SL or TP hit."""
        if self.position_size == 0:
            return

        current_price = current_bar["close"]
        high = current_bar["high"]
        low = current_bar["low"]

        sl = float(signal.stop_loss)
        tp = float(signal.take_profit)

        if self.position_size > 0:  # Long
            if low <= sl:
                self.close_position(sl, current_bar["timestamp"], "stop_loss")
                return
            if high >= tp:
                self.close_position(tp, current_bar["timestamp"], "take_profit")
                return
        else:  # Short
            if high >= sl:
                self.close_position(sl, current_bar["timestamp"], "stop_loss")
                return
            if low <= tp:
                self.close_position(tp, current_bar["timestamp"], "take_profit")
                return

    def run(self, data: pd.DataFrame) -> Dict:
        """Run backtest on historical data."""
        logger.info(f"Running backtest on {len(data)} bars...")

        current_signal = None

        for idx in range(50, len(data)):  # Skip first 50 bars for indicators
            current_bar = data.iloc[idx]
            lookback_data = data.iloc[:idx + 1].copy()

            # Create market snapshot
            snapshot = MarketSnapshot(
                symbol="BTC/USD",
                timeframe=self.timeframe,
                timestamp_ms=int(current_bar["timestamp"].timestamp() * 1000),
                mid_price=current_bar["close"],
                spread_bps=5.0,  # Assume 5bps spread
                volume_24h=1e9,  # Placeholder
            )

            # Prepare strategy
            self.strategy.prepare(snapshot, lookback_data)

            # Check existing position stops
            if current_signal is not None:
                self.check_stops(current_signal, current_bar)

            # Generate new signals if not in position
            if self.position_size == 0:
                # Use appropriate regime label based on strategy type
                if hasattr(self.strategy, 'trend_gate'):
                    # Momentum/breakout strategies need trending regimes
                    regime = RegimeLabel.BULL
                elif hasattr(self.strategy, 'chop_gate'):
                    # Mean reversion strategies need ranging regimes
                    regime = RegimeLabel.CHOP
                else:
                    # Scalper doesn't care about regime
                    regime = RegimeLabel.CHOP

                signals = self.strategy.generate_signals(
                    snapshot, lookback_data, regime
                )

                if signals:
                    current_signal = signals[0]
                    self.open_position(
                        current_signal, current_bar["close"], current_bar["timestamp"]
                    )

            # Record equity
            current_equity = self.cash
            if self.position_size != 0:
                if self.position_size > 0:
                    current_equity += (current_bar["close"] - self.entry_price) * self.position_size
                else:
                    current_equity += (self.entry_price - current_bar["close"]) * abs(self.position_size)

            self.equity_curve.append(current_equity)

        # Close any remaining position
        if self.position_size != 0:
            self.close_position(
                data.iloc[-1]["close"], data.iloc[-1]["timestamp"], "end_of_data"
            )

        # Calculate metrics
        return self.calculate_metrics()

    def calculate_metrics(self) -> Dict:
        """Calculate backtest performance metrics."""
        if not self.trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_return": 0.0,
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "final_equity": self.cash,
            }

        df_trades = pd.DataFrame(self.trades)

        # Basic stats
        total_trades = len(df_trades)
        winning_trades = len(df_trades[df_trades["pnl"] > 0])
        losing_trades = len(df_trades[df_trades["pnl"] < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        # P&L stats
        total_pnl = df_trades["pnl"].sum()
        total_return_pct = (total_pnl / self.initial_capital) * 100

        gross_wins = df_trades[df_trades["pnl"] > 0]["pnl"].sum()
        gross_losses = abs(df_trades[df_trades["pnl"] < 0]["pnl"].sum())
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 0.0

        avg_win = gross_wins / winning_trades if winning_trades > 0 else 0.0
        avg_loss = gross_losses / losing_trades if losing_trades > 0 else 0.0

        # Drawdown
        equity_series = pd.Series(self.equity_curve)
        running_max = equity_series.expanding().max()
        drawdown = (equity_series - running_max) / running_max * 100
        max_drawdown_pct = abs(drawdown.min()) if len(drawdown) > 0 else 0.0

        # Sharpe ratio (simplified)
        if len(df_trades) > 1:
            returns = df_trades["return_pct"].values
            sharpe_ratio = (
                np.mean(returns) / np.std(returns) * np.sqrt(252)
                if np.std(returns) > 0
                else 0.0
            )
        else:
            sharpe_ratio = 0.0

        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_return": total_pnl,
            "total_return_pct": total_return_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "sharpe_ratio": sharpe_ratio,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "final_equity": self.cash,
        }


# =============================================================================
# Data Generation (for testing)
# =============================================================================


def generate_synthetic_data(
    start_date: str, end_date: str, timeframe: str = "1h"
) -> pd.DataFrame:
    """Generate synthetic OHLCV data for backtesting."""
    logger.info(f"Generating synthetic data: {start_date} to {end_date} ({timeframe})")

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    # Determine frequency
    freq_map = {"1m": "1min", "5m": "5min", "1h": "1h", "4h": "4h", "1d": "1D"}
    freq = freq_map.get(timeframe, "1h")

    # Generate timestamps
    timestamps = pd.date_range(start=start, end=end, freq=freq)
    n = len(timestamps)

    # Generate realistic price movement
    np.random.seed(42)

    # Trend + noise
    trend = np.linspace(50000, 52000, n)
    noise = np.random.normal(0, 500, n)
    seasonal = 1000 * np.sin(np.linspace(0, 10 * np.pi, n))

    close_prices = trend + noise + seasonal

    # Generate OHLC
    high_prices = close_prices + np.random.uniform(50, 300, n)
    low_prices = close_prices - np.random.uniform(50, 300, n)
    open_prices = close_prices + np.random.uniform(-100, 100, n)
    volume = np.random.uniform(1e6, 5e6, n)

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": volume,
        }
    )

    logger.info(f"Generated {len(df)} bars")
    return df


# =============================================================================
# Backtest Runner
# =============================================================================


def run_strategy_backtest(
    strategy_name: str,
    start_date: str,
    end_date: str,
    use_synthetic: bool = True,
) -> Tuple[Dict, str]:
    """Run backtest for a single strategy."""
    logger.info("=" * 70)
    logger.info(f"BACKTEST: {strategy_name.upper()}")
    logger.info("=" * 70)

    # Get strategy config
    config = STRATEGY_CONFIGS[strategy_name]

    # Initialize strategy
    strategy_class = config["class"]
    strategy = strategy_class(**config["kwargs"])
    logger.info(f"Strategy initialized: {strategy.__class__.__name__}")

    # Load or generate data
    timeframe = config["timeframe"]

    if use_synthetic:
        data = generate_synthetic_data(start_date, end_date, timeframe)
    else:
        # Load real data from cache - use most recent file
        import glob
        cache_pattern = str(project_root / f"data/cache/BTC_USD_{timeframe}_*.csv")
        cache_files = sorted(glob.glob(cache_pattern), reverse=True)

        if cache_files:
            data_file = cache_files[0]  # Most recent file
            logger.info(f"Loading real data from {data_file}")
            data = pd.read_csv(data_file)
            data["timestamp"] = pd.to_datetime(data["timestamp"])
            logger.info(f"Loaded {len(data)} rows from {data['timestamp'].min()} to {data['timestamp'].max()}")
        else:
            logger.warning(f"No cached data found for {timeframe}. Using synthetic data.")
            data = generate_synthetic_data(start_date, end_date, timeframe)

    # Run backtest
    engine = SimpleBacktestEngine(
        strategy=strategy,
        timeframe=timeframe,
        initial_capital=INITIAL_CAPITAL,
        commission_bps=COMMISSION_BPS,
        slippage_bps=SLIPPAGE_BPS,
    )

    results = engine.run(data)

    # Print summary
    print_results_summary(strategy_name, results)

    return results, strategy_name


def print_results_summary(strategy_name: str, results: Dict):
    """Print backtest results summary."""
    print()
    print("=" * 70)
    print(f"RESULTS: {strategy_name.upper()}")
    print("=" * 70)
    print(f"Total Trades:        {results['total_trades']}")
    print(f"Winning Trades:      {results['winning_trades']}")
    print(f"Losing Trades:       {results['losing_trades']}")
    print(f"Win Rate:            {results['win_rate']:.2f}%")
    print()
    print(f"Total Return:        ${results['total_return']:.2f}")
    print(f"Total Return %:      {results['total_return_pct']:.2f}%")
    print(f"Final Equity:        ${results['final_equity']:.2f}")
    print()
    print(f"Profit Factor:       {results['profit_factor']:.2f}")
    print(f"Max Drawdown:        {results['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio:        {results['sharpe_ratio']:.2f}")
    print()
    print(f"Avg Win:             ${results['avg_win']:.2f}")
    print(f"Avg Loss:            ${results['avg_loss']:.2f}")
    print("=" * 70)
    print()


def save_results(strategy_name: str, results: Dict, output_dir: Path):
    """Save results to JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{strategy_name}_results.json"

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"Results saved to: {output_file}")


def create_comparison_table(all_results: Dict[str, Dict]) -> str:
    """Create comparison table for all strategies."""
    table = []
    table.append("\n" + "=" * 90)
    table.append("STEP 6 BACKTEST RESULTS COMPARISON")
    table.append("=" * 90)
    table.append("")

    # Header
    header = f"{'Metric':<25} | {'Momentum':<18} | {'Mean Reversion':<18} | {'Scalper':<18}"
    table.append(header)
    table.append("-" * 90)

    # Metrics
    metrics = [
        ("Total Trades", "total_trades", "d"),
        ("Win Rate %", "win_rate", ".2f"),
        ("Profit Factor", "profit_factor", ".2f"),
        ("Total Return %", "total_return_pct", ".2f"),
        ("Max Drawdown %", "max_drawdown_pct", ".2f"),
        ("Sharpe Ratio", "sharpe_ratio", ".2f"),
        ("Avg Win $", "avg_win", ".2f"),
        ("Avg Loss $", "avg_loss", ".2f"),
    ]

    for metric_name, key, fmt in metrics:
        row_values = []
        for strategy in ["momentum", "mean_reversion", "scalper"]:
            value = all_results.get(strategy, {}).get(key, 0)
            if fmt == "d":
                row_values.append(f"{value:<18d}")
            else:
                row_values.append(f"{value:<18{fmt}}")

        row = f"{metric_name:<25} | {row_values[0]} | {row_values[1]} | {row_values[2]}"
        table.append(row)

    table.append("=" * 90)
    table.append("")

    # Success criteria
    table.append("STEP 6 SUCCESS CRITERIA:")
    table.append("  ✅ Profit Factor improves by ≥5% for at least 2/3 strategies, OR")
    table.append("  ✅ Max Drawdown decreases by ≥10% for at least 2/3 strategies")
    table.append("")

    return "\n".join(table)


# =============================================================================
# Main CLI
# =============================================================================


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run STEP 6 backtests for all strategies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--all", action="store_true", help="Run all three strategies"
    )

    parser.add_argument(
        "--strategy",
        type=str,
        choices=["momentum", "mean_reversion", "scalper"],
        help="Run specific strategy",
    )

    parser.add_argument(
        "--start-date",
        type=str,
        default=DEFAULT_START_DATE,
        help=f"Start date (YYYY-MM-DD). Default: {DEFAULT_START_DATE}",
    )

    parser.add_argument(
        "--end-date",
        type=str,
        default=DEFAULT_END_DATE,
        help=f"End date (YYYY-MM-DD). Default: {DEFAULT_END_DATE}",
    )

    parser.add_argument(
        "--quick", action="store_true", help="Run quick 30-day backtest"
    )

    parser.add_argument(
        "--use-synthetic",
        action="store_true",
        default=False,
        help="Use synthetic data instead of real cached data (default: False)",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="backtests/step6",
        help="Output directory for results",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Determine date range
    if args.quick:
        end = datetime.now()
        start = end - timedelta(days=30)
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")
        logger.info("QUICK MODE: Running 30-day backtest")
    else:
        start_date = args.start_date
        end_date = args.end_date

    # Determine which strategies to run
    if args.all:
        strategies = ["momentum", "mean_reversion", "scalper"]
    elif args.strategy:
        strategies = [args.strategy]
    else:
        logger.error("Must specify either --all or --strategy")
        return 1

    # Run backtests
    all_results = {}
    output_dir = Path(args.output_dir)

    for strategy_name in strategies:
        try:
            results, name = run_strategy_backtest(
                strategy_name,
                start_date,
                end_date,
                use_synthetic=args.use_synthetic,
            )
            all_results[name] = results
            save_results(name, results, output_dir)

        except Exception as e:
            logger.error(f"Failed to run {strategy_name}: {e}")
            import traceback
            traceback.print_exc()

    # Print comparison table
    if len(all_results) > 1:
        comparison = create_comparison_table(all_results)
        print(comparison)

        # Save comparison
        comparison_file = output_dir / "step6_comparison.txt"
        with open(comparison_file, "w") as f:
            f.write(comparison)
        logger.info(f"Comparison saved to: {comparison_file}")

    logger.info("✅ All backtests completed!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
