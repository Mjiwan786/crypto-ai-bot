"""
Exit Grid Optimization Script (scripts/optimize_exit_grid.py)

Backtests different TP/SL parameter combinations across multiple pairs
to find optimal exit grid configuration.

Usage:
    python scripts/optimize_exit_grid.py --pairs BTC/USD,ETH/USD,SOL/USD,ADA/USD --days 180
    python scripts/optimize_exit_grid.py --save-to-redis

Author: Crypto AI Bot Team
Version: 2.0.0
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import redis

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.risk.volatility_aware_exits import (
    ExitGridConfig,
    VolatilityAwareExits,
    save_exit_config_to_redis,
)
from scripts.train_predictor_v2 import load_historical_data

logger = logging.getLogger(__name__)


class ExitGridBacktest:
    """Backtest framework for exit grid optimization."""

    def __init__(
        self,
        initial_capital: float = 10000.0,
    ):
        """Initialize backtest."""
        self.initial_capital = initial_capital

    def run_backtest(
        self,
        df: pd.DataFrame,
        exit_config: ExitGridConfig,
        pair: str,
    ) -> Dict:
        """
        Run backtest with specific exit configuration.

        Args:
            df: Historical OHLCV data
            exit_config: Exit grid config to test
            pair: Trading pair name

        Returns:
            Dict with performance metrics
        """
        logger.info("Backtesting %s with config: %s", pair, exit_config.model_dump())

        exits_manager = VolatilityAwareExits(config=exit_config)
        capital = self.initial_capital
        trades = []

        # Add ATR if not present
        if "atr" not in df.columns:
            df["atr"] = self._calculate_atr(df, period=14)

        # Simple entry signal: every 50 bars (just for testing exits)
        position = None
        position_id = 0

        for i in range(100, len(df), 50):  # Sample every 50 bars
            if position is None:
                # Enter new position
                entry_price = df["close"].iloc[i]
                atr = df["atr"].iloc[i]
                direction = "long"  # Always long for simplicity

                # Calculate exit levels
                exit_levels = exits_manager.calculate_exit_levels(
                    entry_price=entry_price,
                    direction=direction,
                    atr=atr,
                    current_price=entry_price,
                )

                # Check if we should enter
                should_enter, reason = exits_manager.should_enter_trade(exit_levels)
                if not should_enter:
                    continue

                # Enter position
                position = {
                    "id": f"pos_{position_id}",
                    "entry_bar": i,
                    "entry_price": entry_price,
                    "direction": direction,
                    "size": capital * 0.25,  # 25% of capital
                    "exit_levels": exit_levels,
                }
                position_id += 1

                exits_manager.add_position(
                    position_id=position["id"],
                    entry_price=entry_price,
                    direction=direction,
                    size=position["size"],
                )

                logger.debug("Position opened: %s @ %.2f", position["id"], entry_price)

            else:
                # Check for exit signals
                current_price = df["close"].iloc[i]
                current_atr = df["atr"].iloc[i]

                # Recalculate exit levels with current ATR
                exit_levels = exits_manager.calculate_exit_levels(
                    entry_price=position["entry_price"],
                    direction=position["direction"],
                    atr=current_atr,
                    current_price=current_price,
                )

                # Update position
                signal = exits_manager.update_position(
                    position_id=position["id"],
                    current_price=current_price,
                    exit_levels=exit_levels,
                )

                # Check for exits
                if signal.get("should_exit_full") or signal.get("should_exit_partial"):
                    exit_price = signal["exit_price"]
                    exit_size = signal["exit_size"]
                    exit_reason = signal["exit_reason"]

                    # Calculate P&L
                    pnl = (exit_price - position["entry_price"]) * (exit_size / position["entry_price"])
                    capital += pnl

                    trades.append({
                        "entry_bar": position["entry_bar"],
                        "exit_bar": i,
                        "entry_price": position["entry_price"],
                        "exit_price": exit_price,
                        "pnl": pnl,
                        "pnl_pct": (pnl / position["size"]) * 100,
                        "bars_held": i - position["entry_bar"],
                        "exit_reason": exit_reason,
                        "partial": signal.get("should_exit_partial", False),
                    })

                    logger.debug(
                        "Position closed: %s @ %.2f | PnL: %.2f | Reason: %s",
                        position["id"], exit_price, pnl, exit_reason
                    )

                    # Close full position or update size
                    if signal.get("should_exit_full"):
                        exits_manager.remove_position(position["id"])
                        position = None

        # Calculate metrics
        metrics = self._calculate_metrics(trades, capital)
        metrics["pair"] = pair
        metrics["config"] = exit_config.model_dump()

        logger.info(
            "%s Results: Return=%.2f%%, PF=%.2f, Sharpe=%.2f, Trades=%d, Win Rate=%.1f%%",
            pair,
            metrics["total_return_pct"],
            metrics["profit_factor"],
            metrics["sharpe_ratio"],
            metrics["total_trades"],
            metrics["win_rate_pct"],
        )

        return metrics

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ATR."""
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())

        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(period).mean()

        return atr

    def _calculate_metrics(self, trades: List[Dict], final_capital: float) -> Dict:
        """Calculate performance metrics."""
        if not trades:
            return {
                "total_return_pct": 0.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "avg_win_pct": 0.0,
                "avg_loss_pct": 0.0,
            }

        # Total return
        total_return_pct = ((final_capital - self.initial_capital) / self.initial_capital) * 100

        # Profit factor
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        # Sharpe ratio (simplified)
        returns = [t["pnl_pct"] for t in trades]
        sharpe_ratio = (
            np.sqrt(252 * 288) * (np.mean(returns) / np.std(returns))
            if len(returns) > 1 and np.std(returns) > 0
            else 0.0
        )

        # Win rate
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] < 0]
        win_rate_pct = (len(wins) / len(trades)) * 100 if trades else 0.0

        # Average win/loss
        avg_win_pct = np.mean([t["pnl_pct"] for t in wins]) if wins else 0.0
        avg_loss_pct = np.mean([t["pnl_pct"] for t in losses]) if losses else 0.0

        return {
            "total_return_pct": total_return_pct,
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown_pct": 0.0,  # Not calculated in simple version
            "total_trades": len(trades),
            "win_rate_pct": win_rate_pct,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
        }


def optimize_exit_grid(
    pairs: List[str],
    days: int = 180,
    save_to_redis: bool = False,
    redis_url: Optional[str] = None,
    output_path: Path = Path("out/exit_grid_optimization.json"),
) -> Dict:
    """
    Optimize exit grid parameters across multiple pairs.

    Args:
        pairs: List of trading pairs
        days: Days of historical data
        save_to_redis: Save best config to Redis
        redis_url: Redis connection URL
        output_path: Path to save results

    Returns:
        Optimization results
    """
    logger.info("Optimizing exit grid across %d pairs (%d days)", len(pairs), days)

    # Define parameter grid
    param_grid = {
        "low_vol_sl_atr": [0.6, 0.8, 1.0],
        "low_vol_tp1_atr": [0.8, 1.0, 1.2],
        "low_vol_tp2_atr": [1.5, 1.8, 2.0],
        "normal_vol_sl_atr": [0.8, 1.0, 1.2],
        "normal_vol_tp1_atr": [1.2, 1.5, 1.8],
        "normal_vol_tp2_atr": [2.0, 2.5, 3.0],
        "high_vol_sl_atr": [1.2, 1.5, 1.8],
        "high_vol_tp1_atr": [1.8, 2.0, 2.5],
        "high_vol_tp2_atr": [3.0, 3.5, 4.0],
    }

    # Generate configurations (sample 20 random combinations for speed)
    np.random.seed(42)
    configs = []

    for _ in range(20):
        config_dict = {
            param: np.random.choice(values)
            for param, values in param_grid.items()
        }
        configs.append(ExitGridConfig(**config_dict))

    # Add baseline config
    configs.append(ExitGridConfig())

    logger.info("Testing %d configurations", len(configs))

    # Backtest each configuration on each pair
    backtest = ExitGridBacktest(initial_capital=10000.0)
    results = []

    for pair in pairs:
        logger.info("Loading data for %s...", pair)
        df = load_historical_data(pair, days=days)

        for i, config in enumerate(configs):
            logger.info("Testing config %d/%d on %s", i + 1, len(configs), pair)

            try:
                metrics = backtest.run_backtest(df, config, pair)
                results.append(metrics)
            except Exception as e:
                logger.exception("Backtest failed for config %d on %s: %s", i, pair, e)

    # Aggregate results by configuration
    config_performance = {}

    for result in results:
        config_json = json.dumps(result["config"], sort_keys=True)

        if config_json not in config_performance:
            config_performance[config_json] = {
                "config": result["config"],
                "results": [],
            }

        config_performance[config_json]["results"].append(result)

    # Calculate average performance for each config
    config_scores = []

    for config_json, data in config_performance.items():
        results_list = data["results"]

        avg_metrics = {
            "config": data["config"],
            "avg_return_pct": np.mean([r["total_return_pct"] for r in results_list]),
            "avg_profit_factor": np.mean([r["profit_factor"] for r in results_list]),
            "avg_sharpe": np.mean([r["sharpe_ratio"] for r in results_list]),
            "avg_win_rate": np.mean([r["win_rate_pct"] for r in results_list]),
            "total_trades": sum([r["total_trades"] for r in results_list]),
            "n_pairs": len(results_list),
        }

        # Calculate composite score (Sharpe + PF + Return)
        avg_metrics["composite_score"] = (
            avg_metrics["avg_sharpe"] * 0.4 +
            avg_metrics["avg_profit_factor"] * 0.3 +
            avg_metrics["avg_return_pct"] / 100.0 * 0.3
        )

        config_scores.append(avg_metrics)

    # Sort by composite score
    config_scores.sort(key=lambda x: -x["composite_score"])

    # Get best configuration
    best_config = config_scores[0]

    logger.info("\n" + "=" * 80)
    logger.info("BEST EXIT GRID CONFIGURATION")
    logger.info("=" * 80)
    logger.info("Composite Score: %.3f", best_config["composite_score"])
    logger.info("Avg Return: %.2f%%", best_config["avg_return_pct"])
    logger.info("Avg Profit Factor: %.2f", best_config["avg_profit_factor"])
    logger.info("Avg Sharpe: %.2f", best_config["avg_sharpe"])
    logger.info("Avg Win Rate: %.1f%%", best_config["avg_win_rate"])
    logger.info("Total Trades: %d", best_config["total_trades"])
    logger.info("\nParameters:")
    for key, value in best_config["config"].items():
        logger.info("  %s: %.2f", key, value)
    logger.info("=" * 80 + "\n")

    # Save to file
    output_data = {
        "best_config": best_config,
        "top_10_configs": config_scores[:10],
        "all_results": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    logger.info("Results saved to %s", output_path)

    # Save best config to Redis if requested
    if save_to_redis and redis_url:
        try:
            logger.info("Saving best config to Redis...")
            r = redis.from_url(redis_url, decode_responses=True)

            best_exit_config = ExitGridConfig(**best_config["config"])

            # Save for each pair
            for pair in pairs:
                save_exit_config_to_redis(best_exit_config, pair, r)

            logger.info("Best config saved to Redis for all pairs")

        except Exception as e:
            logger.exception("Failed to save to Redis: %s", e)

    return output_data


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Optimize Exit Grid Parameters")
    parser.add_argument(
        "--pairs",
        type=str,
        default="BTC/USD,ETH/USD,SOL/USD,ADA/USD",
        help="Comma-separated list of trading pairs",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=180,
        help="Days of historical data",
    )
    parser.add_argument(
        "--save-to-redis",
        action="store_true",
        help="Save best config to Redis",
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default="rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818",
        help="Redis connection URL",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="out/exit_grid_optimization.json",
        help="Output path for results",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(",")]

    # Run optimization
    try:
        results = optimize_exit_grid(
            pairs=pairs,
            days=args.days,
            save_to_redis=args.save_to_redis,
            redis_url=args.redis_url if args.save_to_redis else None,
            output_path=Path(args.output),
        )

        logger.info("Optimization complete!")
        logger.info("Best config saved to: %s", args.output)

        return 0

    except Exception as e:
        logger.exception("Optimization failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
