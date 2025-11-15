"""
Compare Predictor Performance (scripts/compare_predictor_performance.py)

Compares baseline predictor (v1) vs enhanced predictor (v2):
- Backtest both models on same historical data
- Measure predictive accuracy, precision, recall
- Calculate trading performance metrics (PF, Sharpe, Win Rate)
- Generate comparison report

Usage:
    python scripts/compare_predictor_performance.py --days 180
    python scripts/compare_predictor_performance.py --model-v2 models/predictor_v2.pkl --days 365

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

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.predictors import LogitPredictor, TreePredictor, EnsemblePredictor
from ml.predictor_v2 import EnhancedPredictorV2
from scripts.train_predictor_v2 import load_historical_data, create_training_samples

logger = logging.getLogger(__name__)


class PredictorBacktest:
    """Backtest framework for comparing predictors."""

    def __init__(
        self,
        initial_capital: float = 10000.0,
        position_size_pct: float = 0.25,
        confidence_threshold: float = 0.55,
    ):
        """
        Initialize backtest.

        Args:
            initial_capital: Starting capital
            position_size_pct: % of capital per trade
            confidence_threshold: Min probability to enter trade
        """
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct
        self.confidence_threshold = confidence_threshold

    def run_backtest(
        self,
        df: pd.DataFrame,
        predictor,
        predictor_name: str,
    ) -> Dict:
        """
        Run backtest using predictor signals.

        Args:
            df: Historical OHLCV data
            predictor: Predictor instance (v1 or v2)
            predictor_name: Name for logging

        Returns:
            Dict with backtest results
        """
        logger.info("Running backtest: %s (n_bars=%d)", predictor_name, len(df))

        capital = self.initial_capital
        equity_curve = [capital]
        trades = []
        positions = []

        # Generate synthetic sentiment data for v2 predictor
        np.random.seed(42)
        sentiment_df = pd.DataFrame({
            "tw_score": np.random.normal(0.05, 0.2, len(df)),
            "tw_volume": np.random.exponential(100, len(df)),
            "rd_score": np.random.normal(0.03, 0.15, len(df)),
            "rd_volume": np.random.exponential(80, len(df)),
            "news_score": np.random.normal(0.02, 0.1, len(df)),
            "news_volume": np.random.exponential(50, len(df)),
            "news_dispersion": np.random.exponential(1.5, len(df)),
            "ret_5m": df["close"].pct_change(),
            "ret_1h": df["close"].pct_change(12),
            "mentions_btc": np.random.poisson(150, len(df)),
            "mentions_eth": np.random.poisson(100, len(df)),
        })

        window_size = 100

        for i in range(window_size, len(df) - 12):  # Leave room for exit
            # Check if we have an open position
            if positions:
                # Check exit conditions
                entry_price = positions[0]["entry_price"]
                entry_bar = positions[0]["entry_bar"]
                current_price = df["close"].iloc[i]

                # Simple exit: 1% TP or 0.5% SL or 24 bars (2 hours)
                pnl_pct = (current_price - entry_price) / entry_price
                bars_held = i - entry_bar

                if pnl_pct >= 0.01 or pnl_pct <= -0.005 or bars_held >= 24:
                    # Close position
                    position = positions.pop(0)
                    pnl = position["size_usd"] * pnl_pct

                    capital += pnl

                    trades.append({
                        "entry_bar": entry_bar,
                        "exit_bar": i,
                        "entry_price": entry_price,
                        "exit_price": current_price,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "bars_held": bars_held,
                    })

                    logger.debug(
                        "Trade closed: PnL=%.2f (%.2f%%), bars=%d",
                        pnl, pnl_pct * 100, bars_held
                    )

            # Try to enter new position if no position
            if not positions:
                # Create context
                ohlcv_window = df.iloc[:i+1].copy()
                sentiment_window = sentiment_df.iloc[:i+1].copy()

                ctx = {
                    "ohlcv_df": ohlcv_window,
                    "current_price": float(df["close"].iloc[i]),
                    "timeframe": "5m",
                }

                # Add v2-specific context
                if isinstance(predictor, EnhancedPredictorV2):
                    ctx["sentiment_df"] = sentiment_window
                    ctx["funding_rate"] = np.random.normal(0.0001, 0.00005)

                try:
                    # Get prediction
                    prob = predictor.predict_proba(ctx)

                    # Enter if probability above threshold
                    if prob >= self.confidence_threshold:
                        position_size = capital * self.position_size_pct
                        positions.append({
                            "entry_bar": i,
                            "entry_price": df["close"].iloc[i],
                            "size_usd": position_size,
                            "probability": prob,
                        })

                        logger.debug(
                            "Position opened: prob=%.3f, size=$%.2f @ $%.2f",
                            prob, position_size, df["close"].iloc[i]
                        )

                except Exception as e:
                    logger.warning("Prediction failed at bar %d: %s", i, e)

            # Record equity
            equity_curve.append(capital)

        # Close any open positions at end
        if positions:
            position = positions.pop(0)
            entry_price = position["entry_price"]
            exit_price = df["close"].iloc[-1]
            pnl_pct = (exit_price - entry_price) / entry_price
            pnl = position["size_usd"] * pnl_pct
            capital += pnl

            trades.append({
                "entry_bar": position["entry_bar"],
                "exit_bar": len(df) - 1,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "bars_held": len(df) - 1 - position["entry_bar"],
            })

        # Calculate metrics
        metrics = self._calculate_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_capital=self.initial_capital,
        )

        metrics["predictor_name"] = predictor_name
        metrics["n_bars"] = len(df)

        logger.info(
            "%s: Total Return=%.2f%%, PF=%.2f, Sharpe=%.2f, Trades=%d, Win Rate=%.1f%%",
            predictor_name,
            metrics["total_return_pct"],
            metrics["profit_factor"],
            metrics["sharpe_ratio"],
            metrics["total_trades"],
            metrics["win_rate_pct"],
        )

        return metrics

    def _calculate_metrics(
        self,
        trades: List[Dict],
        equity_curve: List[float],
        initial_capital: float,
    ) -> Dict:
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
        final_capital = equity_curve[-1]
        total_return_pct = (final_capital - initial_capital) / initial_capital * 100

        # Profit factor
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        # Sharpe ratio (annualized)
        equity_series = pd.Series(equity_curve)
        returns = equity_series.pct_change().dropna()
        sharpe_ratio = (
            np.sqrt(252 * 288) * returns.mean() / returns.std()  # 288 5-min bars per day
            if len(returns) > 1 and returns.std() > 0
            else 0.0
        )

        # Max drawdown
        peak = np.maximum.accumulate(equity_series)
        drawdown = (equity_series - peak) / peak
        max_drawdown_pct = abs(drawdown.min() * 100)

        # Win rate
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] < 0]
        win_rate_pct = len(wins) / len(trades) * 100 if trades else 0.0

        # Average win/loss
        avg_win_pct = np.mean([t["pnl_pct"] for t in wins]) * 100 if wins else 0.0
        avg_loss_pct = np.mean([t["pnl_pct"] for t in losses]) * 100 if losses else 0.0

        return {
            "total_return_pct": total_return_pct,
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown_pct": max_drawdown_pct,
            "total_trades": len(trades),
            "win_rate_pct": win_rate_pct,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
        }


def compare_predictors(
    pairs: List[str],
    days: int = 180,
    model_v2_path: Path = Path("models/predictor_v2.pkl"),
    output_path: Path = Path("out/predictor_comparison.json"),
) -> Dict:
    """
    Compare baseline (v1) vs enhanced (v2) predictors.

    Args:
        pairs: List of trading pairs
        days: Days of historical data
        model_v2_path: Path to trained v2 model
        output_path: Path to save comparison results

    Returns:
        Comparison results dictionary
    """
    logger.info("Comparing predictors: v1 (baseline) vs v2 (enhanced)")

    # Initialize predictors
    # V1: Baseline ensemble (logit + tree)
    predictor_v1 = EnsemblePredictor([LogitPredictor(), TreePredictor()])

    # V2: Enhanced predictor with sentiment + whale flow + liquidations
    if model_v2_path.exists():
        logger.info("Loading trained v2 model from %s", model_v2_path)
        predictor_v2 = EnhancedPredictorV2(model_path=model_v2_path)
    else:
        logger.warning("V2 model not found, using untrained v2 predictor")
        predictor_v2 = EnhancedPredictorV2(use_lightgbm=False)

    # Run backtests
    backtest = PredictorBacktest(
        initial_capital=10000.0,
        position_size_pct=0.25,
        confidence_threshold=0.55,
    )

    results = {
        "v1_baseline": [],
        "v2_enhanced": [],
    }

    for pair in pairs:
        logger.info("Testing on %s...", pair)

        # Load data
        df = load_historical_data(pair, days=days)

        # Backtest v1
        v1_results = backtest.run_backtest(df, predictor_v1, f"V1-{pair}")
        results["v1_baseline"].append(v1_results)

        # Backtest v2
        v2_results = backtest.run_backtest(df, predictor_v2, f"V2-{pair}")
        results["v2_enhanced"].append(v2_results)

    # Calculate aggregate metrics
    def aggregate_metrics(pair_results: List[Dict]) -> Dict:
        if not pair_results:
            return {}

        return {
            "avg_return_pct": np.mean([r["total_return_pct"] for r in pair_results]),
            "avg_profit_factor": np.mean([r["profit_factor"] for r in pair_results]),
            "avg_sharpe": np.mean([r["sharpe_ratio"] for r in pair_results]),
            "avg_max_dd_pct": np.mean([r["max_drawdown_pct"] for r in pair_results]),
            "avg_win_rate": np.mean([r["win_rate_pct"] for r in pair_results]),
            "total_trades": sum([r["total_trades"] for r in pair_results]),
        }

    results["v1_aggregate"] = aggregate_metrics(results["v1_baseline"])
    results["v2_aggregate"] = aggregate_metrics(results["v2_enhanced"])

    # Calculate uplift
    v1_agg = results["v1_aggregate"]
    v2_agg = results["v2_aggregate"]

    results["uplift"] = {
        "return_improvement_pct": v2_agg["avg_return_pct"] - v1_agg["avg_return_pct"],
        "profit_factor_improvement": v2_agg["avg_profit_factor"] - v1_agg["avg_profit_factor"],
        "sharpe_improvement": v2_agg["avg_sharpe"] - v1_agg["avg_sharpe"],
        "win_rate_improvement_pct": v2_agg["avg_win_rate"] - v1_agg["avg_win_rate"],
    }

    # Save results
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    logger.info("Comparison results saved to %s", output_path)

    # Print summary
    print("\n" + "=" * 80)
    print("PREDICTOR COMPARISON SUMMARY")
    print("=" * 80)
    print(f"\nV1 Baseline:")
    print(f"  Avg Return: {v1_agg['avg_return_pct']:.2f}%")
    print(f"  Avg Profit Factor: {v1_agg['avg_profit_factor']:.2f}")
    print(f"  Avg Sharpe: {v1_agg['avg_sharpe']:.2f}")
    print(f"  Avg Win Rate: {v1_agg['avg_win_rate']:.1f}%")
    print(f"  Total Trades: {v1_agg['total_trades']}")

    print(f"\nV2 Enhanced:")
    print(f"  Avg Return: {v2_agg['avg_return_pct']:.2f}%")
    print(f"  Avg Profit Factor: {v2_agg['avg_profit_factor']:.2f}")
    print(f"  Avg Sharpe: {v2_agg['avg_sharpe']:.2f}")
    print(f"  Avg Win Rate: {v2_agg['avg_win_rate']:.1f}%")
    print(f"  Total Trades: {v2_agg['total_trades']}")

    print(f"\nUplift (V2 - V1):")
    print(f"  Return: {results['uplift']['return_improvement_pct']:+.2f}%")
    print(f"  Profit Factor: {results['uplift']['profit_factor_improvement']:+.2f}")
    print(f"  Sharpe: {results['uplift']['sharpe_improvement']:+.2f}")
    print(f"  Win Rate: {results['uplift']['win_rate_improvement_pct']:+.1f}%")
    print("=" * 80 + "\n")

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Compare Predictor Performance")
    parser.add_argument(
        "--pairs",
        type=str,
        default="BTC/USD,ETH/USD",
        help="Comma-separated list of trading pairs",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=180,
        help="Days of historical data to backtest",
    )
    parser.add_argument(
        "--model-v2",
        type=str,
        default="models/predictor_v2.pkl",
        help="Path to trained v2 model",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="out/predictor_comparison.json",
        help="Output path for comparison results",
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

    # Run comparison
    try:
        results = compare_predictors(
            pairs=pairs,
            days=args.days,
            model_v2_path=Path(args.model_v2),
            output_path=Path(args.output),
        )

        logger.info("Comparison complete!")
        return 0

    except Exception as e:
        logger.exception("Comparison failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
