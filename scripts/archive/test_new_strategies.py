"""
Test new strategies with backtesting.

Runs backtests for:
- Breakout strategy (ATR stops)
- Momentum strategy (twin-momentum)
- Mean reversion strategy (RSI bands)
- Regime-based router (ensemble)

Compares performance metrics and generates summary report.

⚠️ SAFETY: No live trading unless MODE=live and confirmation set.
This script is for backtesting only and does not execute real trades.

Usage:
    python scripts/test_new_strategies.py
"""
from __future__ import annotations

import logging
import sys
from decimal import Decimal
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# Import backtest engine
from agents.scalper.backtest.engine import (
    BacktestEngine,
    load_sample_data,
    validate_backtest_data,
)
from ai_engine.schemas import RegimeLabel
from strategies.backtest_adapter import StrategyBacktestAdapter
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum_strategy import MomentumStrategy
from strategies.regime_based_router import RegimeBasedRouter

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_config():
    """Load or create minimal configuration for testing."""
    try:
        from config.loader import get_config

        config = get_config()
        logger.info("Loaded actual configuration")

        # Disable walk-forward for initial testing
        if hasattr(config, "backtest"):
            backtest_dict = config.backtest if isinstance(config.backtest, dict) else {}
            if isinstance(backtest_dict, dict):
                backtest_dict["walk_forward"] = backtest_dict.get("walk_forward", {})
                backtest_dict["walk_forward"]["enabled"] = False

        return config

    except Exception as e:
        logger.warning(f"Could not load full configuration: {e}")
        logger.info("Using minimal test configuration instead")

        # Use minimal config approach from engine.py example
        class MinimalConfig:
            def __init__(self):
                self.backtest = {
                    "slippage": 0.0005,
                    "partial_fill_probability": 0.3,
                    "partial_fill_min_pct": 0.65,
                    "random_seed": 42,
                    "walk_forward": {
                        "enabled": False,
                        "warmup_days": 3,
                        "test_days": 2,
                        "roll_bars": 24,
                    },
                }

                self.risk = type(
                    "Risk",
                    (),
                    {
                        "global_max_drawdown": -0.15,
                        "daily_stop_loss": -0.03,
                        "max_concurrent_positions": 3,
                        "per_symbol_max_exposure": 0.25,
                        "circuit_breakers": {"spread_bps_max": 12},
                    },
                )()

                self.trading = type("Trading", (), {"position_sizing": {"base_position_size": 0.03}})()

                self.data = type("Data", (), {"warmup_bars": 50})()

                self.strategies = type(
                    "Strategies",
                    (),
                    {
                        "scalp": type(
                            "Scalp",
                            (),
                            {
                                "timeframe": "1m",
                                "target_bps": 10,
                                "stop_loss_bps": 5,
                                "max_hold_seconds": 300,
                                "max_spread_bps": 5,
                                "post_only": True,
                                "hidden_orders": False,
                            },
                        )()
                    },
                )()

                self.exchanges = {"kraken": type("Kraken", (), {"fee_taker": 0.0026})()}

        # Set type to bypass isinstance check
        config = MinimalConfig()
        config.__class__.__name__ = "CryptoAIBotConfig"

        return config


def run_strategy_backtest(
    strategy_name: str,
    strategy,
    data: dict,
    pairs: list[str],
    timeframe: str,
    config,
    regime_label: RegimeLabel = RegimeLabel.CHOP,
) -> dict:
    """
    Run backtest for a single strategy.

    Args:
        strategy_name: Strategy name for logging
        strategy: Strategy instance
        data: OHLCV data dictionary
        pairs: Trading pairs
        timeframe: Timeframe
        config: Backtest configuration
        regime_label: Market regime

    Returns:
        Dict with backtest results and metrics
    """
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Testing {strategy_name}")
    logger.info(f"{'=' * 60}")

    # Create adapter
    adapter = StrategyBacktestAdapter(
        strategy=strategy,
        account_equity_usd=Decimal("10000"),
        current_volatility=Decimal("0.50"),
        regime_label=regime_label,
    )

    # Create backtest engine
    engine = BacktestEngine(config, seed=42)
    engine.load_ohlcv(data)

    # Run backtest
    result = engine.run(pairs, timeframe, strategy_adapter=adapter)

    # Extract metrics
    summary = result.summary
    metrics = {
        "strategy": strategy_name,
        "total_trades": summary.get("total_trades", 0),
        "win_rate": summary.get("win_rate", 0.0) * 100,
        "total_return": summary.get("total_return", 0.0) * 100,
        "profit_factor": summary.get("profit_factor", 0.0),
        "sharpe_ratio": summary.get("sharpe_ratio", 0.0),
        "max_drawdown": summary.get("max_drawdown", 0.0) * 100,
        "avg_trade_duration": summary.get("avg_trade_duration", 0.0),
        "total_fees": summary.get("total_fees", 0.0),
        "final_equity": summary.get("final_equity", 10000.0),
    }

    # Log results
    logger.info(f"\n{strategy_name} Results:")
    logger.info(f"  Total Trades: {metrics['total_trades']}")
    logger.info(f"  Win Rate: {metrics['win_rate']:.1f}%")
    logger.info(f"  Total Return: {metrics['total_return']:.2f}%")
    logger.info(f"  Profit Factor: {metrics['profit_factor']:.2f}")
    logger.info(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    logger.info(f"  Max Drawdown: {metrics['max_drawdown']:.2f}%")
    logger.info(f"  Avg Trade Duration: {metrics['avg_trade_duration']:.1f} bars")
    logger.info(f"  Total Fees: ${metrics['total_fees']:.2f}")
    logger.info(f"  Final Equity: ${metrics['final_equity']:.2f}")

    return {"metrics": metrics, "result": result}


def print_comparison_table(all_results: list[dict]) -> None:
    """
    Print comparison table of all strategies.

    Args:
        all_results: List of result dicts from each strategy
    """
    logger.info(f"\n{'=' * 80}")
    logger.info("STRATEGY COMPARISON")
    logger.info(f"{'=' * 80}")

    # Extract metrics
    strategies = [r["metrics"]["strategy"] for r in all_results]
    total_trades = [r["metrics"]["total_trades"] for r in all_results]
    win_rates = [r["metrics"]["win_rate"] for r in all_results]
    returns = [r["metrics"]["total_return"] for r in all_results]
    profit_factors = [r["metrics"]["profit_factor"] for r in all_results]
    sharpes = [r["metrics"]["sharpe_ratio"] for r in all_results]
    drawdowns = [r["metrics"]["max_drawdown"] for r in all_results]

    # Log table
    logger.info(f"\n{'Strategy':<20} {'Trades':>8} {'Win%':>8} {'Return%':>10} {'PF':>6} {'Sharpe':>8} {'DD%':>8}")
    logger.info("-" * 80)

    for i in range(len(strategies)):
        logger.info(
            f"{strategies[i]:<20} {total_trades[i]:>8} {win_rates[i]:>7.1f}% "
            f"{returns[i]:>9.2f}% {profit_factors[i]:>6.2f} {sharpes[i]:>8.2f} "
            f"{drawdowns[i]:>7.2f}%"
        )

    logger.info("-" * 80)

    # Find best strategy
    if returns:
        best_idx = returns.index(max(returns))
        logger.info(f"\nBest performing strategy: {strategies[best_idx]}")
        logger.info(f"  Return: {returns[best_idx]:.2f}%")
        logger.info(f"  Win Rate: {win_rates[best_idx]:.1f}%")
        logger.info(f"  Sharpe: {sharpes[best_idx]:.2f}")


def main():
    """Main entry point for strategy backtesting."""
    logger.info("Starting strategy backtesting...")

    # Load configuration
    config = load_config()

    # Generate sample data (7 days of 1-minute data)
    logger.info("\nGenerating sample data...")
    pairs = ["BTC/USD"]
    timeframe = "1m"
    data = load_sample_data(pairs, timeframe, days=7)

    # Validate data
    validation = validate_backtest_data(data, min_bars=100)
    if not validation["valid"]:
        logger.error(f"Data validation failed: {validation['errors']}")
        return 1

    logger.info(f"Data validation passed: {len(data)} datasets loaded")

    # Initialize strategies
    strategies = [
        ("Breakout (ATR)", BreakoutStrategy(), RegimeLabel.BULL),
        ("Momentum (Twin)", MomentumStrategy(), RegimeLabel.BULL),
        ("MeanReversion (RSI)", MeanReversionStrategy(), RegimeLabel.CHOP),
        ("RegimeRouter", RegimeBasedRouter(use_ensemble=False), RegimeLabel.CHOP),
    ]

    # Run backtests
    all_results = []

    for strategy_name, strategy, regime in strategies:
        try:
            result = run_strategy_backtest(
                strategy_name=strategy_name,
                strategy=strategy,
                data=data,
                pairs=pairs,
                timeframe=timeframe,
                config=config,
                regime_label=regime,
            )
            all_results.append(result)

        except Exception as e:
            logger.error(f"Error testing {strategy_name}: {e}")
            import traceback

            traceback.print_exc()

    # Print comparison
    if all_results:
        print_comparison_table(all_results)

        logger.info("\n✓ Strategy backtesting completed successfully!")
        return 0
    else:
        logger.error("\n✗ No strategies completed successfully")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
