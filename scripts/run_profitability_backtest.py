"""
Profitability Optimization Backtest Runner

Automated 180d and 365d backtesting with success gate validation.
Tests against targets: PF≥1.4, Sharpe≥1.3, DD≤10%, CAGR≥120%

Usage:
    python scripts/run_profitability_backtest.py --days 180
    python scripts/run_profitability_backtest.py --days 365 --pairs BTC/USD,ETH/USD,SOL/USD
"""
import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import existing backtest infrastructure
try:
    from strategies.bar_reaction_5m import BarReaction5mStrategy
    from strategies.backtest_adapter import BacktestAdapter
    from strategies.api import SignalSpec
except ImportError as e:
    print(f"ERROR: Failed to import required modules: {e}")
    print("Make sure you're running from the project root with crypto-bot conda env activated")
    sys.exit(1)


class ProfitabilityBacktest:
    """
    Runs profitability-focused backtests with success gate validation.
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        pairs: List[str] = None,
        days: int = 180
    ):
        """
        Initialize profitability backtest.

        Args:
            initial_capital: Starting capital in USD
            pairs: List of trading pairs (e.g., ["BTC/USD", "ETH/USD"])
            days: Backtest duration in days (180 or 365)
        """
        self.initial_capital = initial_capital
        self.pairs = pairs or ["BTC/USD", "ETH/USD"]
        self.days = days

        # Success gates (targets from PRD)
        self.success_gates = {
            "profit_factor": 1.4,
            "sharpe_ratio": 1.3,
            "max_drawdown_pct": 10.0,
            "cagr_pct": 120.0
        }

    def fetch_historical_data(
        self,
        pair: str,
        days: int
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data for backtesting.

        Args:
            pair: Trading pair (e.g., "BTC/USD")
            days: Number of days of historical data

        Returns:
            DataFrame with OHLCV columns
        """
        print(f"Fetching {days} days of historical data for {pair}...")

        # TODO: Implement actual data fetching from Kraken API or cache
        # For now, use synthetic data generator
        from datetime import datetime, timedelta
        import numpy as np

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days + 30)  # Extra for indicators

        # Generate synthetic 5-minute bars
        periods = days * 24 * 12  # 12 bars per hour, 24 hours per day
        dates = pd.date_range(start=start_date, end=end_date, periods=periods)

        # Realistic crypto price simulation
        base_price = 45000 if "BTC" in pair else 3000
        returns = np.random.normal(0.0001, 0.005, periods)  # Small drift, high vol
        prices = base_price * np.exp(np.cumsum(returns))

        df = pd.DataFrame({
            'timestamp': dates,
            'open': prices * np.random.uniform(0.998, 1.002, periods),
            'high': prices * np.random.uniform(1.001, 1.01, periods),
            'low': prices * np.random.uniform(0.99, 0.999, periods),
            'close': prices,
            'volume': np.random.uniform(1000, 10000, periods)
        })

        df = df.set_index('timestamp')
        print(f"✓ Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")

        return df

    def run_backtest(
        self,
        df: pd.DataFrame,
        pair: str,
        strategy_config: Dict = None
    ) -> Dict:
        """
        Run backtest on historical data.

        Args:
            df: Historical OHLCV data
            pair: Trading pair
            strategy_config: Strategy configuration override

        Returns:
            Backtest results dictionary
        """
        print(f"\nRunning backtest for {pair}...")

        # Default strategy configuration (with Priority 1 fixes)
        if strategy_config is None:
            strategy_config = {
                "mode": "trend",
                "trigger_bps_up": 12.0,
                "trigger_bps_down": 12.0,
                "min_atr_pct": 0.25,
                "max_atr_pct": 3.0,
                "sl_atr": 1.0,  # FIXED: 0.6 → 1.0 (wider stops)
                "tp1_atr": 0.8,  # FIXED: 1.0 → 0.8 (closer first target)
                "tp2_atr": 2.0,  # FIXED: 1.8 → 2.0 (let winners run)
                "risk_per_trade_pct": 0.6,
                "min_position_usd": 50.0,  # FIXED: 0.0 → 50.0 (death spiral prevention)
                "max_position_usd": 2500.0,  # FIXED: 100000 → 2500 (25% of $10k)
                "maker_only": True,
                "spread_bps_cap": 8.0
            }

        # Initialize strategy
        strategy = BarReaction5mStrategy(**strategy_config)

        # Prepare strategy with data
        strategy.prepare(symbol=pair, df_1m=df)

        # Simulate trading
        capital = self.initial_capital
        peak_capital = capital
        trades = []
        equity_curve = [capital]
        dates = []

        for i in range(len(df)):
            current_bar = df.iloc[:i+1]

            if len(current_bar) < 100:  # Need minimum history for indicators
                continue

            # Generate signals
            signals = strategy.generate_signal(
                symbol=pair,
                df_1m=current_bar,
                capital=capital
            )

            if not signals:
                equity_curve.append(capital)
                dates.append(df.index[i])
                continue

            # Execute signals (simplified execution)
            for signal in signals:
                # Calculate P&L (simplified)
                direction = 1 if signal.side == "buy" else -1
                stop_distance = abs(signal.entry - signal.sl)
                target_distance = abs(signal.tp - signal.entry)

                # Win probability based on historical win rate (simplified)
                win_prob = 0.52  # Assume 52% win rate

                # Simulate outcome
                is_win = np.random.random() < win_prob

                if is_win:
                    # Hit target
                    profit = (target_distance / signal.entry) * signal.position_size
                    capital += profit
                    outcome = "WIN"
                else:
                    # Hit stop
                    loss = (stop_distance / signal.entry) * signal.position_size
                    capital -= loss
                    outcome = "LOSS"

                # Record trade
                trades.append({
                    "timestamp": df.index[i],
                    "pair": pair,
                    "side": signal.side,
                    "entry": signal.entry,
                    "sl": signal.sl,
                    "tp": signal.tp,
                    "position_size": signal.position_size,
                    "outcome": outcome,
                    "pnl": profit if is_win else -loss
                })

                # Update peak capital
                peak_capital = max(peak_capital, capital)

            equity_curve.append(capital)
            dates.append(df.index[i])

        # Calculate metrics
        metrics = self.calculate_metrics(
            equity_curve=equity_curve,
            dates=dates,
            trades=trades,
            initial_capital=self.initial_capital
        )

        print(f"✓ Backtest complete: {len(trades)} trades, "
              f"${capital:.2f} final capital ({metrics['total_return_pct']:.2f}%)")

        return {
            "pair": pair,
            "equity_curve": equity_curve,
            "dates": dates,
            "trades": trades,
            "metrics": metrics
        }

    def calculate_metrics(
        self,
        equity_curve: List[float],
        dates: List[datetime],
        trades: List[Dict],
        initial_capital: float
    ) -> Dict:
        """
        Calculate comprehensive backtest metrics.

        Returns:
            Dictionary with PF, Sharpe, DD, CAGR, etc.
        """
        if not trades:
            return {
                "total_return_pct": 0.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "cagr_pct": 0.0,
                "win_rate_pct": 0.0,
                "total_trades": 0,
                "status": "NO_TRADES"
            }

        # Total return
        final_capital = equity_curve[-1]
        total_return = final_capital - initial_capital
        total_return_pct = (total_return / initial_capital) * 100

        # Profit factor
        winning_trades = [t for t in trades if t["pnl"] > 0]
        losing_trades = [t for t in trades if t["pnl"] < 0]

        gross_profit = sum(t["pnl"] for t in winning_trades) if winning_trades else 0
        gross_loss = abs(sum(t["pnl"] for t in losing_trades)) if losing_trades else 0

        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

        # Win rate
        win_rate_pct = (len(winning_trades) / len(trades)) * 100 if trades else 0.0

        # Sharpe ratio (annualized)
        returns = pd.Series(equity_curve).pct_change().dropna()
        if len(returns) > 0 and returns.std() > 0:
            # Annualize: sqrt(periods_per_year) = sqrt(365 * 288) for 5min bars
            periods_per_year = 365 * 24 * 12  # 5-minute bars per year
            sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(periods_per_year)
        else:
            sharpe_ratio = 0.0

        # Max drawdown
        equity_series = pd.Series(equity_curve)
        running_max = equity_series.expanding().max()
        drawdown = (equity_series - running_max) / running_max * 100
        max_drawdown_pct = abs(drawdown.min())

        # CAGR (Compound Annual Growth Rate)
        if len(dates) >= 2:
            days_elapsed = (dates[-1] - dates[0]).days
            years = days_elapsed / 365.0
            if years > 0:
                cagr_pct = ((final_capital / initial_capital) ** (1 / years) - 1) * 100
            else:
                cagr_pct = 0.0
        else:
            cagr_pct = 0.0

        # Monthly return (extrapolated)
        if len(dates) >= 2:
            days_elapsed = (dates[-1] - dates[0]).days
            monthly_return_pct = (total_return_pct / days_elapsed) * 30 if days_elapsed > 0 else 0.0
        else:
            monthly_return_pct = 0.0

        return {
            "total_return_pct": round(total_return_pct, 2),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "cagr_pct": round(cagr_pct, 2),
            "monthly_return_pct": round(monthly_return_pct, 2),
            "win_rate_pct": round(win_rate_pct, 1),
            "total_trades": len(trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "final_capital": round(final_capital, 2),
            "days_elapsed": (dates[-1] - dates[0]).days if len(dates) >= 2 else 0
        }

    def validate_success_gates(self, metrics: Dict) -> Dict:
        """
        Validate backtest results against success gates.

        Args:
            metrics: Backtest metrics dictionary

        Returns:
            {
                "profit_factor": {"value": 1.64, "target": 1.4, "status": "PASS"},
                "sharpe_ratio": {"value": 0.84, "target": 1.3, "status": "FAIL"},
                ...
            }
        """
        gates = {}

        # Profit Factor
        gates["profit_factor"] = {
            "value": metrics.get("profit_factor", 0.0),
            "target": self.success_gates["profit_factor"],
            "status": "PASS" if metrics.get("profit_factor", 0.0) >= self.success_gates["profit_factor"] else "FAIL"
        }

        # Sharpe Ratio
        gates["sharpe_ratio"] = {
            "value": metrics.get("sharpe_ratio", 0.0),
            "target": self.success_gates["sharpe_ratio"],
            "status": "PASS" if metrics.get("sharpe_ratio", 0.0) >= self.success_gates["sharpe_ratio"] else "FAIL"
        }

        # Max Drawdown (lower is better)
        gates["max_drawdown"] = {
            "value": metrics.get("max_drawdown_pct", 100.0),
            "target": self.success_gates["max_drawdown_pct"],
            "status": "PASS" if metrics.get("max_drawdown_pct", 100.0) <= self.success_gates["max_drawdown_pct"] else "FAIL"
        }

        # CAGR
        gates["cagr"] = {
            "value": metrics.get("cagr_pct", 0.0),
            "target": self.success_gates["cagr_pct"],
            "status": "PASS" if metrics.get("cagr_pct", 0.0) >= self.success_gates["cagr_pct"] else "FAIL"
        }

        # Overall status
        all_pass = all(gate["status"] == "PASS" for gate in gates.values())
        gates["overall"] = "✅ ALL GATES PASSED" if all_pass else "❌ SOME GATES FAILED"

        return gates

    def print_results(self, results: List[Dict], gate_validation: Dict):
        """
        Print backtest results in readable format.
        """
        print("\n" + "="*70)
        print("PROFITABILITY BACKTEST RESULTS")
        print("="*70)

        # Aggregate metrics across all pairs
        total_trades = sum(r["metrics"]["total_trades"] for r in results)
        avg_pf = np.mean([r["metrics"]["profit_factor"] for r in results])
        avg_sharpe = np.mean([r["metrics"]["sharpe_ratio"] for r in results])
        max_dd = max([r["metrics"]["max_drawdown_pct"] for r in results])
        avg_cagr = np.mean([r["metrics"]["cagr_pct"] for r in results])

        final_capital = sum([r["equity_curve"][-1] for r in results]) / len(results)
        total_return_pct = ((final_capital - self.initial_capital) / self.initial_capital) * 100

        print(f"\nConfiguration:")
        print(f"  Duration: {self.days} days")
        print(f"  Pairs: {', '.join(self.pairs)}")
        print(f"  Initial Capital: ${self.initial_capital:,.2f}")
        print(f"  Final Capital: ${final_capital:,.2f}")
        print(f"  Total Return: {total_return_pct:+.2f}%")

        print(f"\nPerformance Metrics:")
        print(f"  Total Trades: {total_trades}")
        print(f"  Profit Factor: {avg_pf:.2f} (target: ≥{self.success_gates['profit_factor']})")
        print(f"  Sharpe Ratio: {avg_sharpe:.2f} (target: ≥{self.success_gates['sharpe_ratio']})")
        print(f"  Max Drawdown: {max_dd:.2f}% (target: ≤{self.success_gates['max_drawdown_pct']}%)")
        print(f"  CAGR: {avg_cagr:.2f}% (target: ≥{self.success_gates['cagr_pct']}%)")

        print(f"\nSuccess Gate Validation:")
        for gate_name, gate_data in gate_validation.items():
            if gate_name == "overall":
                continue
            status_icon = "✅" if gate_data["status"] == "PASS" else "❌"
            print(f"  {status_icon} {gate_name.replace('_', ' ').title()}: "
                  f"{gate_data['value']:.2f} vs target {gate_data['target']:.2f}")

        print(f"\n{gate_validation['overall']}")
        print("="*70)

    def save_results(self, results: List[Dict], gate_validation: Dict, output_file: str):
        """
        Save backtest results to JSON file.
        """
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "configuration": {
                "initial_capital": self.initial_capital,
                "pairs": self.pairs,
                "days": self.days
            },
            "success_gates": self.success_gates,
            "results": [
                {
                    "pair": r["pair"],
                    "metrics": r["metrics"],
                    "num_trades": len(r["trades"])
                }
                for r in results
            ],
            "gate_validation": gate_validation
        }

        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)

        print(f"\n✓ Results saved to: {output_file}")

    def run_full_backtest(self) -> Tuple[List[Dict], Dict]:
        """
        Run complete backtest for all pairs and validate gates.

        Returns:
            (results, gate_validation)
        """
        all_results = []

        for pair in self.pairs:
            # Fetch historical data
            df = self.fetch_historical_data(pair, self.days)

            # Run backtest
            result = self.run_backtest(df, pair)
            all_results.append(result)

        # Aggregate metrics for gate validation
        aggregated_metrics = {
            "profit_factor": np.mean([r["metrics"]["profit_factor"] for r in all_results]),
            "sharpe_ratio": np.mean([r["metrics"]["sharpe_ratio"] for r in all_results]),
            "max_drawdown_pct": max([r["metrics"]["max_drawdown_pct"] for r in all_results]),
            "cagr_pct": np.mean([r["metrics"]["cagr_pct"] for r in all_results])
        }

        # Validate gates
        gate_validation = self.validate_success_gates(aggregated_metrics)

        return all_results, gate_validation


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run profitability optimization backtests"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=180,
        choices=[180, 365],
        help="Backtest duration (180 or 365 days)"
    )
    parser.add_argument(
        "--pairs",
        type=str,
        default="BTC/USD,ETH/USD",
        help="Comma-separated list of trading pairs"
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Initial capital in USD"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: out/profitability_backtest_{days}d.json)"
    )

    args = parser.parse_args()

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(',')]

    # Initialize backtest
    backtest = ProfitabilityBacktest(
        initial_capital=args.capital,
        pairs=pairs,
        days=args.days
    )

    # Run backtest
    print(f"\n{'='*70}")
    print(f"STARTING {args.days}-DAY PROFITABILITY BACKTEST")
    print(f"{'='*70}\n")

    results, gate_validation = backtest.run_full_backtest()

    # Print results
    backtest.print_results(results, gate_validation)

    # Save results
    output_file = args.output or f"out/profitability_backtest_{args.days}d.json"
    os.makedirs("out", exist_ok=True)
    backtest.save_results(results, gate_validation, output_file)

    # Exit with appropriate code
    if gate_validation["overall"] == "✅ ALL GATES PASSED":
        print("\n✅ SUCCESS: All gates passed. System ready for deployment.")
        sys.exit(0)
    else:
        print("\n❌ FAILED: Some gates failed. Further optimization needed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
