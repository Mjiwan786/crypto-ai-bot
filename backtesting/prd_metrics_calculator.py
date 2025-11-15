"""
PRD-001 Section 6.2 Backtest Metrics Calculator

This module implements PRD-001 Section 6.2 backtest metrics with:
- Calculate total return % for backtest period
- Calculate Sharpe ratio: (mean_return - risk_free_rate) / std_deviation
- Calculate max drawdown: max peak-to-trough decline
- Calculate win rate: winning_trades / total_trades
- Calculate profit factor: gross_profit / gross_loss
- Calculate average trade duration in hours
- Count total trades in backtest period
- Log all metrics to out/backtests/{strategy}_{date}.json

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)

# PRD-001 Section 6.2: Output directory
OUTPUT_DIR = Path("out/backtests")

# Risk-free rate assumption (annual)
RISK_FREE_RATE_ANNUAL = 0.02  # 2% annual risk-free rate


class BacktestMetrics:
    """
    PRD-001 Section 6.2 compliant backtest metrics.

    Contains all calculated metrics for a backtest run.
    """

    def __init__(
        self,
        total_return_pct: float,
        sharpe_ratio: float,
        max_drawdown_pct: float,
        win_rate: float,
        profit_factor: float,
        avg_trade_duration_hours: float,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        gross_profit: float,
        gross_loss: float,
        final_equity: float,
        initial_capital: float
    ):
        """Initialize backtest metrics."""
        # PRD-001 Section 6.2: Required metrics
        self.total_return_pct = total_return_pct
        self.sharpe_ratio = sharpe_ratio
        self.max_drawdown_pct = max_drawdown_pct
        self.win_rate = win_rate
        self.profit_factor = profit_factor
        self.avg_trade_duration_hours = avg_trade_duration_hours
        self.total_trades = total_trades

        # Additional useful metrics
        self.winning_trades = winning_trades
        self.losing_trades = losing_trades
        self.gross_profit = gross_profit
        self.gross_loss = gross_loss
        self.final_equity = final_equity
        self.initial_capital = initial_capital

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "total_return_pct": round(self.total_return_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "win_rate": round(self.win_rate, 2),
            "profit_factor": round(self.profit_factor, 2),
            "avg_trade_duration_hours": round(self.avg_trade_duration_hours, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "gross_profit": round(self.gross_profit, 2),
            "gross_loss": round(self.gross_loss, 2),
            "final_equity": round(self.final_equity, 2),
            "initial_capital": round(self.initial_capital, 2)
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"BacktestMetrics("
            f"return={self.total_return_pct:.2f}%, "
            f"sharpe={self.sharpe_ratio:.2f}, "
            f"drawdown={self.max_drawdown_pct:.2f}%, "
            f"win_rate={self.win_rate:.2f}%, "
            f"trades={self.total_trades})"
        )


class PRDMetricsCalculator:
    """
    PRD-001 Section 6.2 compliant backtest metrics calculator.

    Features:
    - Calculate all PRD-required metrics
    - Save metrics to JSON files
    - Provide detailed trade analysis

    Usage:
        calculator = PRDMetricsCalculator()

        metrics = calculator.calculate_metrics(
            trades=trades_list,
            equity_curve=equity_curve,
            initial_capital=10000.0
        )

        # Save to file
        calculator.save_metrics(
            metrics=metrics,
            strategy="scalper",
            output_dir=Path("out/backtests")
        )
    """

    def __init__(self, risk_free_rate: float = RISK_FREE_RATE_ANNUAL):
        """
        Initialize PRD-compliant metrics calculator.

        Args:
            risk_free_rate: Annual risk-free rate (default 2%)
        """
        self.risk_free_rate = risk_free_rate

        logger.info(
            f"PRDMetricsCalculator initialized: risk_free_rate={risk_free_rate:.2%}"
        )

    def calculate_metrics(
        self,
        trades: List[Dict[str, Any]],
        equity_curve: List[float],
        initial_capital: float
    ) -> BacktestMetrics:
        """
        PRD-001 Section 6.2: Calculate all backtest metrics.

        Args:
            trades: List of trade dictionaries with 'pnl', 'duration_hours', etc.
            equity_curve: List of equity values over time
            initial_capital: Starting capital

        Returns:
            BacktestMetrics with all calculated metrics
        """
        # PRD-001 Section 6.2 Item 7: Count total trades
        total_trades = len(trades)

        if total_trades == 0:
            logger.warning("No trades to analyze")
            return self._create_zero_metrics(initial_capital)

        # PRD-001 Section 6.2 Item 1: Calculate total return %
        final_equity = equity_curve[-1] if equity_curve else initial_capital
        total_return_pct = ((final_equity - initial_capital) / initial_capital) * 100.0

        # PRD-001 Section 6.2 Item 2: Calculate Sharpe ratio
        sharpe_ratio = self._calculate_sharpe_ratio(equity_curve, initial_capital)

        # PRD-001 Section 6.2 Item 3: Calculate max drawdown
        max_drawdown_pct = self._calculate_max_drawdown(equity_curve)

        # PRD-001 Section 6.2 Item 4: Calculate win rate
        winning_trades = sum(1 for t in trades if t.get("pnl", 0) > 0)
        losing_trades = sum(1 for t in trades if t.get("pnl", 0) < 0)
        win_rate = (winning_trades / total_trades) * 100.0 if total_trades > 0 else 0.0

        # PRD-001 Section 6.2 Item 5: Calculate profit factor
        gross_profit = sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) > 0)
        gross_loss = abs(sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

        # PRD-001 Section 6.2 Item 6: Calculate average trade duration
        durations = [t.get("duration_hours", 0) for t in trades if "duration_hours" in t]
        avg_trade_duration_hours = np.mean(durations) if durations else 0.0

        metrics = BacktestMetrics(
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_drawdown_pct,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_trade_duration_hours=avg_trade_duration_hours,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            final_equity=final_equity,
            initial_capital=initial_capital
        )

        logger.info(f"Calculated metrics: {metrics}")

        return metrics

    def _calculate_sharpe_ratio(
        self,
        equity_curve: List[float],
        initial_capital: float
    ) -> float:
        """
        PRD-001 Section 6.2: Calculate Sharpe ratio.

        Formula: (mean_return - risk_free_rate) / std_deviation

        Args:
            equity_curve: List of equity values
            initial_capital: Starting capital

        Returns:
            Sharpe ratio (annualized)
        """
        if len(equity_curve) < 2:
            return 0.0

        # Calculate returns
        returns = np.diff(equity_curve) / equity_curve[:-1]

        if len(returns) == 0:
            return 0.0

        # Annualize returns (assume daily data)
        mean_return = np.mean(returns) * 252  # 252 trading days per year
        std_return = np.std(returns) * np.sqrt(252)

        if std_return == 0:
            return 0.0

        # Sharpe ratio: (mean_return - risk_free_rate) / std_deviation
        sharpe = (mean_return - self.risk_free_rate) / std_return

        return float(sharpe)

    def _calculate_max_drawdown(self, equity_curve: List[float]) -> float:
        """
        PRD-001 Section 6.2: Calculate max drawdown.

        Max peak-to-trough decline in percentage.

        Args:
            equity_curve: List of equity values

        Returns:
            Max drawdown in percentage (negative value)
        """
        if len(equity_curve) < 2:
            return 0.0

        equity_array = np.array(equity_curve)

        # Calculate running maximum
        running_max = np.maximum.accumulate(equity_array)

        # Calculate drawdown at each point
        drawdown = (equity_array - running_max) / running_max * 100.0

        # Max drawdown is the most negative value
        max_drawdown = float(np.min(drawdown))

        return max_drawdown

    def _create_zero_metrics(self, initial_capital: float) -> BacktestMetrics:
        """Create metrics object for zero trades case."""
        return BacktestMetrics(
            total_return_pct=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            avg_trade_duration_hours=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            gross_profit=0.0,
            gross_loss=0.0,
            final_equity=initial_capital,
            initial_capital=initial_capital
        )

    def save_metrics(
        self,
        metrics: BacktestMetrics,
        strategy: str,
        output_dir: Optional[Path] = None
    ) -> Path:
        """
        PRD-001 Section 6.2 Item 8: Log all metrics to JSON file.

        Saves to out/backtests/{strategy}_{date}.json

        Args:
            metrics: BacktestMetrics to save
            strategy: Strategy name (e.g., "scalper")
            output_dir: Output directory (default: out/backtests/)

        Returns:
            Path to saved file
        """
        output_dir = output_dir or OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        # PRD-001 Section 6.2: Filename format {strategy}_{date}.json
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{strategy}_{timestamp}.json"
        filepath = output_dir / filename

        # Convert metrics to dict and add metadata
        data = {
            "strategy": strategy,
            "timestamp": datetime.now().isoformat(),
            "metrics": metrics.to_dict()
        }

        # Save to JSON
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved backtest metrics to {filepath}")

        return filepath

    def load_metrics(self, filepath: Path) -> Dict[str, Any]:
        """
        Load metrics from JSON file.

        Args:
            filepath: Path to metrics JSON file

        Returns:
            Dictionary with metrics data
        """
        with open(filepath, 'r') as f:
            data = json.load(f)

        logger.info(f"Loaded backtest metrics from {filepath}")

        return data


# Singleton instance
_calculator_instance: Optional[PRDMetricsCalculator] = None


def get_metrics_calculator() -> PRDMetricsCalculator:
    """
    Get singleton PRDMetricsCalculator instance.

    Returns:
        PRDMetricsCalculator instance
    """
    global _calculator_instance

    if _calculator_instance is None:
        _calculator_instance = PRDMetricsCalculator()

    return _calculator_instance


# Export for convenience
__all__ = [
    "BacktestMetrics",
    "PRDMetricsCalculator",
    "get_metrics_calculator",
    "OUTPUT_DIR",
    "RISK_FREE_RATE_ANNUAL",
]
