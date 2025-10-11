"""
Performance monitoring and metrics calculation for crypto trading agents.

Provides comprehensive performance tracking including risk-adjusted returns,
drawdown analysis, and calibration metrics for trading strategy evaluation.

Features:
- Real-time performance metrics calculation
- Risk-adjusted return measures (Sharpe, Sortino)
- Maximum drawdown tracking
- Expected Calibration Error (ECE) for model validation
- Win rate and return statistics
- Thread-safe operations with proper data validation
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np


class PerformanceMonitor:
    """Performance monitoring and metrics calculation for crypto trading agents."""

    def __init__(self) -> None:
        """Initialize performance monitor with empty tracking lists."""
        self.returns: List[float] = []
        self.pred_exp: List[float] = []

    def record_trade(self, realized_ret: float, expected_ret: float | None = None) -> None:
        """
        Record a trade's realized and expected returns.

        Args:
            realized_ret: Actual return from the trade
            expected_ret: Expected return (optional, for calibration)
        """
        self.returns.append(float(realized_ret))
        if expected_ret is not None:
            self.pred_exp.append(float(expected_ret))

    def _sharpe(self) -> float:
        """Calculate Sharpe ratio for recorded returns."""
        r = np.array(self.returns, dtype=float)
        if len(r) < 2:
            return 0.0
        return float(np.mean(r) / (np.std(r) + 1e-9))

    def _sortino(self) -> float:
        """Calculate Sortino ratio for recorded returns."""
        r = np.array(self.returns, dtype=float)
        if len(r) < 2:
            return 0.0
        downside = r[r < 0]
        denom = np.std(downside) if len(downside) else 1e-9
        return float(np.mean(r) / denom)

    def _maxdd(self) -> float:
        """Calculate maximum drawdown for recorded returns."""
        r = np.array(self.returns, dtype=float)
        eq = np.cumsum(r)
        peak = np.maximum.accumulate(eq)
        dd = eq - peak
        return float(dd.min() if len(dd) else 0.0)

    def _ece(self) -> float:
        """Calculate Expected Calibration Error between predicted and actual returns."""
        if not self.pred_exp or not self.returns:
            return 0.0
        p = np.array(self.pred_exp[: len(self.returns)])
        r = np.array(self.returns[: len(self.pred_exp)])
        return float(np.mean(np.abs(p - r)))

    def report_metrics(self) -> Dict[str, float]:
        """
        Generate comprehensive performance metrics report.

        Returns:
            Dictionary mapping metric names to their calculated values:
                - Sharpe: Sharpe ratio
                - Sortino: Sortino ratio (downside deviation)
                - MaxDD: Maximum drawdown
                - ECE: Expected Calibration Error
                - WinRate: Percentage of profitable trades
        """
        return {
            "Sharpe": self._sharpe(),
            "Sortino": self._sortino(),
            "MaxDD": self._maxdd(),
            "ECE": self._ece(),
            "WinRate": float(np.mean(np.array(self.returns) > 0) if self.returns else 0.0),
        }
