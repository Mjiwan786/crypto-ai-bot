"""
PRD-001 Section 6.4 Automated Backtest Runner

This module implements PRD-001 Section 6.4 automation requirements with:
- Automated backtest execution for all strategies
- PRD-compliant data fetching, metrics calculation, and acceptance criteria
- Timestamped results storage in out/backtests/ directory
- HTML report generation with equity curve charts
- CI/CD integration with acceptance criteria enforcement

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np

from backtesting.prd_data_provider import PRDBacktestDataProvider
from backtesting.prd_metrics_calculator import PRDMetricsCalculator, BacktestMetrics
from backtesting.prd_acceptance_criteria import (
    PRDAcceptanceCriteria,
    AcceptanceCriteriaError
)

logger = logging.getLogger(__name__)

# PRD-001 Section 6.4: Output directory
OUTPUT_DIR = Path("out/backtests")
REPORTS_DIR = Path("docs")


class PRDBacktestRunner:
    """
    PRD-001 Section 6.4 compliant backtest automation.

    Features:
    - Run backtests for multiple strategies and pairs
    - Use PRD-compliant data provider, metrics calculator, acceptance criteria
    - Store results in out/backtests/ with timestamp
    - Generate HTML reports with equity curves
    - Enforce acceptance criteria (fail if not met)

    Usage:
        runner = PRDBacktestRunner()

        results = runner.run_backtest(
            strategy="scalper",
            pair="BTC/USD",
            period_days=365
        )

        # Generate HTML report
        runner.generate_html_report(results, "scalper", "BTC/USD")

        # Check acceptance criteria
        runner.check_acceptance_criteria(results.metrics)
    """

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        reports_dir: Optional[Path] = None
    ):
        """
        Initialize PRD-compliant backtest runner.

        Args:
            output_dir: Directory for backtest results (default: out/backtests/)
            reports_dir: Directory for HTML reports (default: docs/)
        """
        self.output_dir = output_dir or OUTPUT_DIR
        self.reports_dir = reports_dir or REPORTS_DIR

        # Initialize PRD components
        self.data_provider = PRDBacktestDataProvider()
        self.metrics_calculator = PRDMetricsCalculator()
        self.acceptance_criteria = PRDAcceptanceCriteria()

        # Create output directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"PRDBacktestRunner initialized: "
            f"output_dir={self.output_dir}, reports_dir={self.reports_dir}"
        )

    def run_backtest(
        self,
        strategy: str,
        pair: str,
        period_days: int = 365,
        timeframe: str = "1h",
        initial_capital: float = 10000.0,
        use_latest_data: bool = True
    ) -> "BacktestResults":
        """
        Run PRD-compliant backtest for a strategy.

        Args:
            strategy: Strategy name (e.g., "scalper", "momentum")
            pair: Trading pair (e.g., "BTC/USD")
            period_days: Backtest period in days (default: 365)
            timeframe: Candle timeframe (default: "1h")
            initial_capital: Initial capital (default: 10000.0)
            use_latest_data: Use latest market data (default: True)

        Returns:
            BacktestResults object
        """
        logger.info("=" * 80)
        logger.info(f"RUNNING BACKTEST: {strategy} | {pair} | {period_days}d")
        logger.info("=" * 80)

        # Step 1: Fetch OHLCV data
        logger.info(f"\n[STEP 1] Fetching {pair} data...")
        if use_latest_data:
            ohlcv_data = self.data_provider.fetch_latest_ohlcv(
                pair=pair,
                days=period_days,
                timeframe=timeframe
            )
        else:
            ohlcv_data = self.data_provider.fetch_ohlcv(
                pair=pair,
                days=period_days,
                timeframe=timeframe
            )

        logger.info(f"✓ Loaded {len(ohlcv_data)} candles")
        logger.info(
            f"  Period: {ohlcv_data['timestamp'].min()} to "
            f"{ohlcv_data['timestamp'].max()}"
        )

        # Step 2: Run strategy backtest
        logger.info(f"\n[STEP 2] Running {strategy} strategy...")
        trades, equity_curve = self._run_strategy(
            strategy=strategy,
            ohlcv_data=ohlcv_data,
            initial_capital=initial_capital
        )

        logger.info(f"✓ Strategy executed: {len(trades)} trade(s)")

        # Step 3: Calculate metrics
        logger.info(f"\n[STEP 3] Calculating PRD metrics...")
        metrics = self.metrics_calculator.calculate_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_capital=initial_capital
        )

        logger.info(f"✓ Metrics calculated:")
        logger.info(f"  Total Return:     {metrics.total_return_pct:>7.2f}%")
        logger.info(f"  Sharpe Ratio:     {metrics.sharpe_ratio:>7.2f}")
        logger.info(f"  Max Drawdown:     {metrics.max_drawdown_pct:>7.2f}%")
        logger.info(f"  Win Rate:         {metrics.win_rate:>7.2f}%")
        logger.info(f"  Profit Factor:    {metrics.profit_factor:>7.2f}")
        logger.info(f"  Total Trades:     {metrics.total_trades:>7}")

        # Step 4: Check acceptance criteria
        logger.info(f"\n[STEP 4] Checking acceptance criteria...")
        acceptance_result = self.acceptance_criteria.check_acceptance(metrics)

        if acceptance_result.passed:
            logger.info("✓ ACCEPTANCE PASSED - Ready for production")
        else:
            logger.warning("✗ ACCEPTANCE FAILED - Not ready for production")
            for failure in acceptance_result.failures:
                logger.warning(f"  - {failure}")

        # Step 5: Save results
        logger.info(f"\n[STEP 5] Saving results...")
        timestamp = datetime.now()

        results = BacktestResults(
            strategy=strategy,
            pair=pair,
            period_days=period_days,
            timeframe=timeframe,
            initial_capital=initial_capital,
            trades=trades,
            equity_curve=equity_curve,
            timestamps=ohlcv_data['timestamp'].tolist(),
            metrics=metrics,
            acceptance_result=acceptance_result,
            timestamp=timestamp
        )

        # Save JSON results
        output_file = self._save_results_json(results)
        logger.info(f"✓ Results saved to: {output_file}")

        logger.info("\n" + "=" * 80)
        logger.info("BACKTEST COMPLETE")
        logger.info("=" * 80)

        return results

    def _run_strategy(
        self,
        strategy: str,
        ohlcv_data: pd.DataFrame,
        initial_capital: float
    ) -> Tuple[List[Dict[str, Any]], List[float]]:
        """
        Run strategy logic on OHLCV data.

        This is a simple placeholder implementation. In production, this would
        call the actual strategy implementation.

        Args:
            strategy: Strategy name
            ohlcv_data: OHLCV DataFrame
            initial_capital: Initial capital

        Returns:
            Tuple of (trades list, equity curve)
        """
        # Simple buy-and-hold strategy for demonstration
        entry_price = ohlcv_data['close'].iloc[0]
        exit_price = ohlcv_data['close'].iloc[-1]

        position_size_usd = initial_capital

        # Calculate fill with costs
        entry_fill_price, entry_fee, entry_cost = self.data_provider.simulate_order_fill(
            price=entry_price,
            size_usd=position_size_usd,
            side="buy",
            order_type="market"
        )

        exit_fill_price, exit_fee, exit_proceeds = self.data_provider.simulate_order_fill(
            price=exit_price,
            size_usd=position_size_usd,
            side="sell",
            order_type="market"
        )

        # Calculate PnL
        pnl = exit_proceeds - entry_cost
        final_equity = initial_capital + pnl

        # Calculate trade duration
        trade_duration_hours = (
            ohlcv_data['timestamp'].iloc[-1] - ohlcv_data['timestamp'].iloc[0]
        ).total_seconds() / 3600

        # Create trades list
        trades = [{
            'pnl': pnl,
            'duration_hours': trade_duration_hours,
            'entry_price': entry_fill_price,
            'exit_price': exit_fill_price,
            'entry_fee': entry_fee,
            'exit_fee': exit_fee,
            'entry_time': ohlcv_data['timestamp'].iloc[0],
            'exit_time': ohlcv_data['timestamp'].iloc[-1]
        }]

        # Create simple equity curve
        equity_curve = [initial_capital, final_equity]

        return trades, equity_curve

    def _save_results_json(self, results: "BacktestResults") -> Path:
        """
        Save backtest results to JSON file.

        PRD-001 Section 6.4: Store backtest results in out/backtests/ with timestamp

        Args:
            results: BacktestResults object

        Returns:
            Path to saved file
        """
        timestamp_str = results.timestamp.strftime("%Y%m%d_%H%M%S")
        pair_safe = results.pair.replace("/", "_")
        filename = f"{results.strategy}_{pair_safe}_{timestamp_str}.json"
        filepath = self.output_dir / filename

        data = {
            "strategy": results.strategy,
            "pair": results.pair,
            "period_days": results.period_days,
            "timeframe": results.timeframe,
            "initial_capital": results.initial_capital,
            "timestamp": results.timestamp.isoformat(),
            "metrics": results.metrics.to_dict(),
            "acceptance_result": {
                "passed": results.acceptance_result.passed,
                "failures": results.acceptance_result.failures
            },
            "trades_count": len(results.trades)
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        return filepath

    def generate_html_report(
        self,
        results: "BacktestResults",
        strategy: str,
        pair: str
    ) -> Path:
        """
        Generate HTML backtest report with equity curve chart.

        PRD-001 Section 6.4: Generate backtest report with equity curve chart

        Args:
            results: BacktestResults object
            strategy: Strategy name
            pair: Trading pair

        Returns:
            Path to HTML report
        """
        timestamp_str = results.timestamp.strftime("%Y%m%d")
        filename = f"backtest_report_{timestamp_str}.html"
        filepath = self.reports_dir / filename

        # Generate HTML content
        html_content = self._generate_html_content(results, strategy, pair)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"✓ HTML report generated: {filepath}")

        return filepath

    def _generate_html_content(
        self,
        results: "BacktestResults",
        strategy: str,
        pair: str
    ) -> str:
        """
        Generate HTML content for backtest report.

        Args:
            results: BacktestResults object
            strategy: Strategy name
            pair: Trading pair

        Returns:
            HTML content string
        """
        metrics = results.metrics
        acceptance = results.acceptance_result

        # Generate equity curve chart data
        chart_data = self._generate_chart_data(results)

        # Status badge
        status_badge = "✅ PASSED" if acceptance.passed else "❌ FAILED"
        status_color = "#28a745" if acceptance.passed else "#dc3545"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Backtest Report - {strategy} | {pair}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
        }}
        .status-badge {{
            display: inline-block;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: bold;
            background-color: {status_color};
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}
        .metric-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .metric-label {{
            color: #666;
            font-size: 14px;
            margin-bottom: 5px;
        }}
        .metric-value {{
            font-size: 32px;
            font-weight: bold;
            color: #333;
        }}
        .chart-container {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .failures {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
        }}
        .failure-item {{
            color: #856404;
            margin: 5px 0;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{strategy.upper()} | {pair}</h1>
        <p>Generated: {results.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p>Period: {results.period_days} days | Timeframe: {results.timeframe}</p>
        <div class="status-badge">{status_badge}</div>
    </div>

    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-label">Total Return</div>
            <div class="metric-value">{metrics.total_return_pct:+.2f}%</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Sharpe Ratio</div>
            <div class="metric-value">{metrics.sharpe_ratio:.2f}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Max Drawdown</div>
            <div class="metric-value">{metrics.max_drawdown_pct:.2f}%</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Win Rate</div>
            <div class="metric-value">{metrics.win_rate:.1f}%</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Profit Factor</div>
            <div class="metric-value">{metrics.profit_factor:.2f}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Total Trades</div>
            <div class="metric-value">{metrics.total_trades}</div>
        </div>
    </div>

    {self._generate_failures_html(acceptance) if not acceptance.passed else ""}

    <div class="chart-container">
        <h2>Equity Curve</h2>
        <canvas id="equityChart"></canvas>
    </div>

    <script>
        const ctx = document.getElementById('equityChart').getContext('2d');
        const chart = new Chart(ctx, {{
            type: 'line',
            data: {chart_data},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{
                        display: false
                    }},
                    title: {{
                        display: true,
                        text: 'Equity Curve Over Time'
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: false,
                        title: {{
                            display: true,
                            text: 'Equity ($)'
                        }}
                    }},
                    x: {{
                        title: {{
                            display: true,
                            text: 'Time'
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""

        return html

    def _generate_failures_html(self, acceptance) -> str:
        """Generate HTML for acceptance failures."""
        if not acceptance.failures:
            return ""

        failures_html = '<div class="failures"><h3>❌ Acceptance Criteria Failures:</h3>'
        for failure in acceptance.failures:
            failures_html += f'<div class="failure-item">• {failure}</div>'
        failures_html += '</div>'

        return failures_html

    def _generate_chart_data(self, results: "BacktestResults") -> str:
        """Generate Chart.js data for equity curve."""
        # Create labels (simplified timestamps)
        labels = [
            ts.strftime("%Y-%m-%d") if isinstance(ts, pd.Timestamp) else str(ts)
            for ts in results.timestamps[:100]  # Limit to 100 points for performance
        ]

        # Get equity values (limit to same number of points)
        equity_values = results.equity_curve[:100]

        chart_data = {
            "labels": labels,
            "datasets": [{
                "label": "Equity",
                "data": equity_values,
                "borderColor": "rgb(75, 192, 192)",
                "backgroundColor": "rgba(75, 192, 192, 0.1)",
                "tension": 0.1,
                "fill": True
            }]
        }

        return json.dumps(chart_data)

    def check_acceptance_criteria_and_exit(self, metrics: BacktestMetrics) -> None:
        """
        Check acceptance criteria and exit with error code if failed.

        PRD-001 Section 6.4: Fail CI build if backtest doesn't meet acceptance criteria

        Args:
            metrics: BacktestMetrics to check

        Raises:
            SystemExit: Exits with code 1 if acceptance criteria failed
        """
        result = self.acceptance_criteria.check_acceptance(metrics)

        if not result.passed:
            logger.error("ACCEPTANCE CRITERIA FAILED - BLOCKING DEPLOYMENT")
            sys.exit(1)


class BacktestResults:
    """Container for backtest results."""

    def __init__(
        self,
        strategy: str,
        pair: str,
        period_days: int,
        timeframe: str,
        initial_capital: float,
        trades: List[Dict[str, Any]],
        equity_curve: List[float],
        timestamps: List[Any],
        metrics: BacktestMetrics,
        acceptance_result: Any,
        timestamp: datetime
    ):
        """Initialize backtest results."""
        self.strategy = strategy
        self.pair = pair
        self.period_days = period_days
        self.timeframe = timeframe
        self.initial_capital = initial_capital
        self.trades = trades
        self.equity_curve = equity_curve
        self.timestamps = timestamps
        self.metrics = metrics
        self.acceptance_result = acceptance_result
        self.timestamp = timestamp


# Singleton instance
_runner_instance: Optional[PRDBacktestRunner] = None


def get_backtest_runner() -> PRDBacktestRunner:
    """
    Get singleton PRDBacktestRunner instance.

    Returns:
        PRDBacktestRunner instance
    """
    global _runner_instance

    if _runner_instance is None:
        _runner_instance = PRDBacktestRunner()

    return _runner_instance


# Export for convenience
__all__ = [
    "PRDBacktestRunner",
    "BacktestResults",
    "get_backtest_runner",
]
