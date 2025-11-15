"""
backtests/metrics.py - Backtest Metrics Module

Comprehensive metrics calculation for backtesting including:
- Monthly ROI aggregation
- Profit Factor (PF)
- Sharpe Ratio
- Maximum Drawdown (DD)
- Win rate and trade statistics
- Deterministic calculations

Per PRD §12:
- Report monthly ROI, PF, DD, Sharpe
- Fail fast if DD > 20%
- Deterministic under fixed seed

Author: Crypto AI Bot Team
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# =============================================================================
# TRADE DATA CLASSES
# =============================================================================

@dataclass
class Trade:
    """
    Single trade record.

    Attributes:
        entry_time: Entry timestamp
        exit_time: Exit timestamp
        pair: Trading pair
        side: Trade direction (long/short)
        entry_price: Entry price
        exit_price: Exit price
        size: Position size
        pnl: Realized P&L
        pnl_pct: P&L percentage
        fees: Total fees paid
        strategy: Strategy name
    """
    entry_time: datetime
    exit_time: datetime
    pair: str
    side: str
    entry_price: Decimal
    exit_price: Decimal
    size: Decimal
    pnl: Decimal
    pnl_pct: Decimal
    fees: Decimal
    strategy: str


@dataclass
class EquityPoint:
    """
    Single equity curve point.

    Attributes:
        timestamp: Timestamp
        equity: Total equity
        cash: Available cash
        position_value: Current position value
        pnl: Cumulative P&L
    """
    timestamp: datetime
    equity: Decimal
    cash: Decimal
    position_value: Decimal
    pnl: Decimal


# =============================================================================
# METRICS RESULT
# =============================================================================

@dataclass
class BacktestMetrics:
    """
    Complete backtest metrics result.

    Attributes:
        # Period
        start_date: Backtest start date
        end_date: Backtest end date
        duration_days: Duration in days

        # Capital
        initial_capital: Starting capital
        final_capital: Ending capital
        total_return: Total return (%)
        total_return_pct: Total return percentage

        # Monthly metrics
        monthly_returns: Dict of monthly returns
        monthly_roi_mean: Mean monthly ROI
        monthly_roi_median: Median monthly ROI
        monthly_roi_std: Standard deviation of monthly ROI

        # Trade statistics
        total_trades: Number of trades
        winning_trades: Number of winning trades
        losing_trades: Number of losing trades
        win_rate: Win rate (%)

        # Profit metrics
        gross_profit: Total gross profit
        gross_loss: Total gross loss
        profit_factor: Profit factor (PF)
        avg_win: Average winning trade
        avg_loss: Average losing trade
        expectancy: Expected value per trade

        # Risk metrics
        max_drawdown: Maximum drawdown (%)
        max_drawdown_duration: Max DD duration (days)
        sharpe_ratio: Sharpe ratio
        sortino_ratio: Sortino ratio
        calmar_ratio: Calmar ratio

        # Fees
        total_fees: Total fees paid
        fees_pct: Fees as % of capital
    """
    # Period
    start_date: datetime
    end_date: datetime
    duration_days: int

    # Capital
    initial_capital: Decimal
    final_capital: Decimal
    total_return: Decimal
    total_return_pct: Decimal

    # Monthly metrics
    monthly_returns: Dict[str, Decimal] = field(default_factory=dict)
    monthly_roi_mean: Decimal = Decimal("0")
    monthly_roi_median: Decimal = Decimal("0")
    monthly_roi_std: Decimal = Decimal("0")

    # Trade statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = Decimal("0")

    # Profit metrics
    gross_profit: Decimal = Decimal("0")
    gross_loss: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    avg_win: Decimal = Decimal("0")
    avg_loss: Decimal = Decimal("0")
    expectancy: Decimal = Decimal("0")

    # Risk metrics
    max_drawdown: Decimal = Decimal("0")
    max_drawdown_duration: int = 0
    sharpe_ratio: Decimal = Decimal("0")
    sortino_ratio: Decimal = Decimal("0")
    calmar_ratio: Decimal = Decimal("0")

    # Fees
    total_fees: Decimal = Decimal("0")
    fees_pct: Decimal = Decimal("0")


# =============================================================================
# METRICS CALCULATOR
# =============================================================================

class MetricsCalculator:
    """
    Calculates comprehensive backtest metrics from trades and equity curve.

    All calculations are deterministic and pure (no I/O).
    """

    @staticmethod
    def calculate(
        trades: List[Trade],
        equity_curve: List[EquityPoint],
        initial_capital: Decimal,
    ) -> BacktestMetrics:
        """
        Calculate all metrics from trades and equity curve.

        Args:
            trades: List of closed trades
            equity_curve: Equity curve points
            initial_capital: Starting capital

        Returns:
            Complete BacktestMetrics
        """
        if not equity_curve:
            raise ValueError("Equity curve is empty")

        # Extract dates
        start_date = equity_curve[0].timestamp
        end_date = equity_curve[-1].timestamp
        duration_days = (end_date - start_date).days

        # Capital metrics
        final_capital = equity_curve[-1].equity
        total_return = final_capital - initial_capital
        total_return_pct = (total_return / initial_capital * Decimal("100")) if initial_capital > 0 else Decimal("0")

        # Monthly returns
        monthly_returns = MetricsCalculator._calculate_monthly_returns(equity_curve)
        monthly_roi_mean = MetricsCalculator._mean_decimal(list(monthly_returns.values()))
        monthly_roi_median = MetricsCalculator._median_decimal(list(monthly_returns.values()))
        monthly_roi_std = MetricsCalculator._std_decimal(list(monthly_returns.values()))

        # Trade statistics
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t.pnl > 0])
        losing_trades = len([t for t in trades if t.pnl < 0])
        win_rate = Decimal(winning_trades) / Decimal(total_trades) * Decimal("100") if total_trades > 0 else Decimal("0")

        # Profit metrics
        gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else Decimal("0")

        avg_win = gross_profit / Decimal(winning_trades) if winning_trades > 0 else Decimal("0")
        avg_loss = gross_loss / Decimal(losing_trades) if losing_trades > 0 else Decimal("0")

        expectancy = sum(t.pnl for t in trades) / Decimal(total_trades) if total_trades > 0 else Decimal("0")

        # Risk metrics
        max_drawdown, max_dd_duration = MetricsCalculator._calculate_max_drawdown(equity_curve)
        sharpe_ratio = MetricsCalculator._calculate_sharpe_ratio(equity_curve, initial_capital)
        sortino_ratio = MetricsCalculator._calculate_sortino_ratio(equity_curve, initial_capital)
        calmar_ratio = (total_return_pct / abs(max_drawdown)) if max_drawdown != 0 else Decimal("0")

        # Fees
        total_fees = sum(t.fees for t in trades)
        fees_pct = total_fees / initial_capital * Decimal("100") if initial_capital > 0 else Decimal("0")

        return BacktestMetrics(
            # Period
            start_date=start_date,
            end_date=end_date,
            duration_days=duration_days,
            # Capital
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            # Monthly metrics
            monthly_returns=monthly_returns,
            monthly_roi_mean=monthly_roi_mean,
            monthly_roi_median=monthly_roi_median,
            monthly_roi_std=monthly_roi_std,
            # Trade statistics
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            # Profit metrics
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            expectancy=expectancy,
            # Risk metrics
            max_drawdown=max_drawdown,
            max_drawdown_duration=max_dd_duration,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            # Fees
            total_fees=total_fees,
            fees_pct=fees_pct,
        )

    @staticmethod
    def _calculate_monthly_returns(equity_curve: List[EquityPoint]) -> Dict[str, Decimal]:
        """
        Calculate monthly returns.

        Args:
            equity_curve: Equity curve points

        Returns:
            Dict mapping "YYYY-MM" to return percentage
        """
        # Convert to DataFrame for resampling
        df = pd.DataFrame([
            {"timestamp": point.timestamp, "equity": float(point.equity)}
            for point in equity_curve
        ])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)

        # Resample to month end
        monthly_equity = df["equity"].resample("M").last()

        # Calculate returns
        monthly_returns = {}
        for i in range(1, len(monthly_equity)):
            prev_equity = monthly_equity.iloc[i-1]
            curr_equity = monthly_equity.iloc[i]

            if prev_equity > 0:
                ret_pct = (curr_equity - prev_equity) / prev_equity * 100
                month_key = monthly_equity.index[i].strftime("%Y-%m")
                monthly_returns[month_key] = Decimal(str(ret_pct))

        return monthly_returns

    @staticmethod
    def _calculate_max_drawdown(equity_curve: List[EquityPoint]) -> Tuple[Decimal, int]:
        """
        Calculate maximum drawdown and its duration.

        Args:
            equity_curve: Equity curve points

        Returns:
            Tuple of (max_drawdown_pct, duration_days)
        """
        if not equity_curve:
            return Decimal("0"), 0

        equity_values = [float(point.equity) for point in equity_curve]
        timestamps = [point.timestamp for point in equity_curve]

        # Calculate running maximum
        running_max = np.maximum.accumulate(equity_values)

        # Calculate drawdown
        drawdown = (equity_values - running_max) / running_max * 100

        # Find maximum drawdown
        max_dd = abs(float(np.min(drawdown)))

        # Find duration
        max_dd_duration = 0
        current_dd_duration = 0

        for i in range(len(drawdown)):
            if drawdown[i] < 0:
                current_dd_duration += 1
                max_dd_duration = max(max_dd_duration, current_dd_duration)
            else:
                current_dd_duration = 0

        return Decimal(str(max_dd)), max_dd_duration

    @staticmethod
    def _calculate_sharpe_ratio(
        equity_curve: List[EquityPoint],
        initial_capital: Decimal,
        risk_free_rate: Decimal = Decimal("0.02"),  # 2% annual
    ) -> Decimal:
        """
        Calculate Sharpe ratio.

        Args:
            equity_curve: Equity curve points
            initial_capital: Starting capital
            risk_free_rate: Annual risk-free rate (default: 2%)

        Returns:
            Sharpe ratio
        """
        if len(equity_curve) < 2:
            return Decimal("0")

        # Calculate daily returns
        equity_values = [float(point.equity) for point in equity_curve]
        returns = np.diff(equity_values) / equity_values[:-1]

        if len(returns) == 0:
            return Decimal("0")

        # Mean and std of returns
        mean_return = np.mean(returns)
        std_return = np.std(returns, ddof=1)

        if std_return == 0:
            return Decimal("0")

        # Annualize (assuming daily data)
        annual_mean = mean_return * 365
        annual_std = std_return * np.sqrt(365)

        # Calculate Sharpe
        sharpe = (annual_mean - float(risk_free_rate)) / annual_std

        return Decimal(str(sharpe))

    @staticmethod
    def _calculate_sortino_ratio(
        equity_curve: List[EquityPoint],
        initial_capital: Decimal,
        risk_free_rate: Decimal = Decimal("0.02"),  # 2% annual
    ) -> Decimal:
        """
        Calculate Sortino ratio (like Sharpe but only penalizes downside volatility).

        Args:
            equity_curve: Equity curve points
            initial_capital: Starting capital
            risk_free_rate: Annual risk-free rate (default: 2%)

        Returns:
            Sortino ratio
        """
        if len(equity_curve) < 2:
            return Decimal("0")

        # Calculate daily returns
        equity_values = [float(point.equity) for point in equity_curve]
        returns = np.diff(equity_values) / equity_values[:-1]

        if len(returns) == 0:
            return Decimal("0")

        # Mean of returns
        mean_return = np.mean(returns)

        # Downside deviation (only negative returns)
        downside_returns = returns[returns < 0]

        if len(downside_returns) == 0:
            return Decimal("0")

        downside_std = np.std(downside_returns, ddof=1)

        if downside_std == 0:
            return Decimal("0")

        # Annualize
        annual_mean = mean_return * 365
        annual_downside_std = downside_std * np.sqrt(365)

        # Calculate Sortino
        sortino = (annual_mean - float(risk_free_rate)) / annual_downside_std

        return Decimal(str(sortino))

    @staticmethod
    def _mean_decimal(values: List[Decimal]) -> Decimal:
        """Calculate mean of Decimal values"""
        if not values:
            return Decimal("0")
        return sum(values) / Decimal(len(values))

    @staticmethod
    def _median_decimal(values: List[Decimal]) -> Decimal:
        """Calculate median of Decimal values"""
        if not values:
            return Decimal("0")
        sorted_values = sorted(values)
        n = len(sorted_values)
        if n % 2 == 0:
            return (sorted_values[n//2 - 1] + sorted_values[n//2]) / Decimal("2")
        else:
            return sorted_values[n//2]

    @staticmethod
    def _std_decimal(values: List[Decimal]) -> Decimal:
        """Calculate standard deviation of Decimal values"""
        if len(values) < 2:
            return Decimal("0")

        mean = MetricsCalculator._mean_decimal(values)
        variance = sum((v - mean) ** 2 for v in values) / Decimal(len(values) - 1)

        # Convert to float for sqrt, then back to Decimal
        return Decimal(str(float(variance) ** 0.5))


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "Trade",
    "EquityPoint",
    "BacktestMetrics",
    "MetricsCalculator",
]