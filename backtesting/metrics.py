"""
Performance metrics calculator for backtesting results.

Calculates standard trading metrics: returns, Sharpe ratio, drawdown,
win rate, profit factor, etc.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Individual trade record."""
    entry_time: pd.Timestamp
    exit_time: Optional[pd.Timestamp]
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    status: str = "open"  # 'open', 'closed', 'stopped'

    # ATR risk management fields
    atr_value: Optional[float] = None
    sl_atr_multiple: Optional[float] = None
    tp1_atr_multiple: Optional[float] = None
    tp2_atr_multiple: Optional[float] = None
    trail_atr_multiple: Optional[float] = None
    breakeven_r: Optional[float] = None
    tp1_size_pct: Optional[float] = None
    initial_stop_loss: Optional[float] = None
    current_stop_loss: Optional[float] = None
    tp1_price: Optional[float] = None
    tp2_price: Optional[float] = None
    breakeven_price: Optional[float] = None
    stop_moved_to_be: bool = False
    tp1_hit: bool = False
    highest_price: Optional[float] = None  # For longs
    lowest_price: Optional[float] = None  # For shorts
    remaining_size_pct: float = 1.0

    def close(self, exit_time: pd.Timestamp, exit_price: float, status: str = "closed"):
        """Close the trade and calculate P&L."""
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.status = status

        if self.side == "long":
            self.pnl = (exit_price - self.entry_price) * self.quantity
            self.pnl_pct = ((exit_price / self.entry_price) - 1) * 100
        else:  # short
            self.pnl = (self.entry_price - exit_price) * self.quantity
            self.pnl_pct = ((self.entry_price / exit_price) - 1) * 100

    def to_csv_dict(self) -> dict:
        """Convert trade to dictionary for CSV export."""
        return {
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "status": self.status,
            "atr_value": self.atr_value,
            "sl_atr_multiple": self.sl_atr_multiple,
            "tp1_atr_multiple": self.tp1_atr_multiple,
            "tp2_atr_multiple": self.tp2_atr_multiple,
            "trail_atr_multiple": self.trail_atr_multiple,
            "breakeven_r": self.breakeven_r,
            "tp1_size_pct": self.tp1_size_pct,
            "initial_stop_loss": self.initial_stop_loss,
            "current_stop_loss": self.current_stop_loss,
            "tp1_price": self.tp1_price,
            "tp2_price": self.tp2_price,
            "breakeven_price": self.breakeven_price,
            "stop_moved_to_be": self.stop_moved_to_be,
            "tp1_hit": self.tp1_hit,
            "highest_price": self.highest_price,
            "lowest_price": self.lowest_price,
            "remaining_size_pct": self.remaining_size_pct,
        }


@dataclass
class BacktestResults:
    """Complete backtest results with performance metrics."""

    # Configuration
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    timeframe: str

    # Equity curve
    equity_curve: pd.Series
    timestamps: pd.Series

    # Trades
    trades: List[Trade]
    total_trades: int
    winning_trades: int
    losing_trades: int

    # Returns
    total_return: float
    total_return_pct: float
    annualized_return_pct: float

    # Risk metrics
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int

    # Performance metrics
    win_rate_pct: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float

    # Additional metrics
    calmar_ratio: float
    recovery_factor: float
    volatility_annualized_pct: float

    def export_trades_to_csv(self, filepath: str) -> None:
        """
        Export trades to CSV file with all ATR risk fields.

        Args:
            filepath: Path to output CSV file
        """
        if not self.trades:
            logger.warning("No trades to export")
            return

        # Convert trades to dictionaries
        trade_dicts = [trade.to_csv_dict() for trade in self.trades]

        # Create DataFrame and export
        df = pd.DataFrame(trade_dicts)
        df.to_csv(filepath, index=False)
        logger.info(f"Exported {len(self.trades)} trades to {filepath}")

    def print_summary(self):
        """Print human-readable summary."""
        print("\n" + "=" * 70)
        print("BACKTEST RESULTS SUMMARY")
        print("=" * 70)
        print(f"\nConfiguration:")
        print(f"  Symbol: {self.symbol}")
        print(f"  Period: {self.start_date} to {self.end_date}")
        print(f"  Initial Capital: ${self.initial_capital:,.2f}")
        print(f"  Final Equity: ${self.equity_curve.iloc[-1]:,.2f}")
        print(f"  Timeframe: {self.timeframe}")

        print(f"\nReturns:")
        print(f"  Total Return: ${self.total_return:,.2f} ({self.total_return_pct:+.2f}%)")
        print(f"  Annualized Return: {self.annualized_return_pct:+.2f}%")

        print(f"\nRisk Metrics:")
        print(f"  Sharpe Ratio: {self.sharpe_ratio:.2f}")
        print(f"  Sortino Ratio: {self.sortino_ratio:.2f}")
        print(f"  Max Drawdown: ${self.max_drawdown:,.2f} ({self.max_drawdown_pct:.2f}%)")
        print(f"  Max DD Duration: {self.max_drawdown_duration_days} days")
        print(f"  Volatility (Annual): {self.volatility_annualized_pct:.2f}%")

        print(f"\nTrade Statistics:")
        print(f"  Total Trades: {self.total_trades}")
        print(f"  Winning Trades: {self.winning_trades} ({self.win_rate_pct:.1f}%)")
        print(f"  Losing Trades: {self.losing_trades}")
        print(f"  Avg Win: ${self.avg_win:,.2f}")
        print(f"  Avg Loss: ${self.avg_loss:,.2f}")
        print(f"  Profit Factor: {self.profit_factor:.2f}")
        print(f"  Expectancy: ${self.expectancy:,.2f}")

        print(f"\nRisk-Adjusted Metrics:")
        print(f"  Calmar Ratio: {self.calmar_ratio:.2f}")
        print(f"  Recovery Factor: {self.recovery_factor:.2f}")

        print("\n" + "=" * 70 + "\n")


def calculate_metrics(
    equity_curve: pd.Series,
    timestamps: pd.Series,
    trades: List[Trade],
    initial_capital: float,
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str,
    risk_free_rate: float = 0.02,  # 2% annual risk-free rate
) -> BacktestResults:
    """
    Calculate comprehensive performance metrics.

    Args:
        equity_curve: Time series of portfolio value
        timestamps: Corresponding timestamps
        trades: List of all trades
        initial_capital: Starting capital
        symbol: Trading symbol
        start_date: Backtest start date
        end_date: Backtest end date
        timeframe: Candle timeframe
        risk_free_rate: Annual risk-free rate (default 2%)

    Returns:
        BacktestResults with all calculated metrics
    """
    # Filter closed trades
    closed_trades = [t for t in trades if t.status == "closed" or t.status == "stopped"]

    # Trade statistics
    total_trades = len(closed_trades)
    winning_trades = len([t for t in closed_trades if t.pnl and t.pnl > 0])
    losing_trades = len([t for t in closed_trades if t.pnl and t.pnl <= 0])

    # Returns
    final_equity = equity_curve.iloc[-1]
    total_return = final_equity - initial_capital
    total_return_pct = (total_return / initial_capital) * 100

    # Annualized return
    days = (timestamps.iloc[-1] - timestamps.iloc[0]).days
    years = days / 365.25
    annualized_return_pct = (((final_equity / initial_capital) ** (1 / years)) - 1) * 100 if years > 0 else 0

    # Daily returns
    returns = equity_curve.pct_change().dropna()

    # Sharpe ratio (annualized)
    if len(returns) > 0 and returns.std() > 0:
        daily_rf = risk_free_rate / 252  # Convert annual to daily
        excess_returns = returns - daily_rf
        sharpe_ratio = (excess_returns.mean() / returns.std()) * np.sqrt(252)
    else:
        sharpe_ratio = 0.0

    # Sortino ratio (uses downside deviation)
    downside_returns = returns[returns < 0]
    if len(downside_returns) > 0 and downside_returns.std() > 0:
        daily_rf = risk_free_rate / 252
        sortino_ratio = ((returns.mean() - daily_rf) / downside_returns.std()) * np.sqrt(252)
    else:
        sortino_ratio = 0.0

    # Maximum drawdown
    rolling_max = equity_curve.expanding().max()
    drawdown = equity_curve - rolling_max
    max_drawdown = drawdown.min()
    max_drawdown_pct = (max_drawdown / rolling_max[drawdown.idxmin()]) * 100 if max_drawdown < 0 else 0.0

    # Max drawdown duration
    is_drawdown = drawdown < 0
    drawdown_periods = []
    current_dd_start = None

    for i, in_dd in enumerate(is_drawdown):
        if in_dd and current_dd_start is None:
            current_dd_start = timestamps.iloc[i]
        elif not in_dd and current_dd_start is not None:
            duration = (timestamps.iloc[i] - current_dd_start).days
            drawdown_periods.append(duration)
            current_dd_start = None

    max_drawdown_duration_days = max(drawdown_periods) if drawdown_periods else 0

    # Win/loss statistics
    if total_trades > 0:
        win_rate_pct = (winning_trades / total_trades) * 100

        wins = [t.pnl for t in closed_trades if t.pnl and t.pnl > 0]
        losses = [t.pnl for t in closed_trades if t.pnl and t.pnl <= 0]

        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = np.mean(losses) if losses else 0.0

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        expectancy = (win_rate_pct / 100 * avg_win) + ((100 - win_rate_pct) / 100 * avg_loss)
    else:
        win_rate_pct = 0.0
        avg_win = 0.0
        avg_loss = 0.0
        profit_factor = 0.0
        expectancy = 0.0

    # Calmar ratio (return / max drawdown)
    calmar_ratio = annualized_return_pct / abs(max_drawdown_pct) if max_drawdown_pct != 0 else 0.0

    # Recovery factor (net profit / max drawdown)
    recovery_factor = total_return / abs(max_drawdown) if max_drawdown < 0 else float('inf')

    # Volatility (annualized)
    volatility_annualized_pct = returns.std() * np.sqrt(252) * 100 if len(returns) > 0 else 0.0

    return BacktestResults(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        timeframe=timeframe,
        equity_curve=equity_curve,
        timestamps=timestamps,
        trades=trades,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        total_return=total_return,
        total_return_pct=total_return_pct,
        annualized_return_pct=annualized_return_pct,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        max_drawdown_duration_days=max_drawdown_duration_days,
        win_rate_pct=win_rate_pct,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        calmar_ratio=calmar_ratio,
        recovery_factor=recovery_factor,
        volatility_annualized_pct=volatility_annualized_pct,
    )


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test metrics calculation"""
    import sys

    # Generate synthetic equity curve (upward trend with drawdowns)
    dates = pd.date_range("2023-01-01", periods=252, freq="D")
    np.random.seed(42)

    # Simulate daily returns with drift
    returns = np.random.normal(0.001, 0.02, 252)  # 0.1% daily return, 2% volatility
    equity = 10000 * (1 + returns).cumprod()

    equity_curve = pd.Series(equity, index=dates)

    # Generate some sample trades
    trades = [
        Trade(
            entry_time=dates[10],
            exit_time=dates[20],
            symbol="BTC/USD",
            side="long",
            entry_price=40000,
            exit_price=42000,
            quantity=0.1,
        ),
        Trade(
            entry_time=dates[30],
            exit_time=dates[40],
            symbol="BTC/USD",
            side="long",
            entry_price=41000,
            exit_price=40000,
            quantity=0.1,
        ),
    ]

    # Calculate P&L for trades
    for trade in trades:
        if trade.exit_price:
            trade.close(trade.exit_time, trade.exit_price)

    try:
        results = calculate_metrics(
            equity_curve=equity_curve,
            timestamps=pd.Series(dates),
            trades=trades,
            initial_capital=10000.0,
            symbol="BTC/USD",
            start_date="2023-01-01",
            end_date="2023-12-31",
            timeframe="1d",
        )

        print("\nPASS Metrics Calculator Self-Check:")
        results.print_summary()

    except Exception as e:
        print(f"\nFAIL Metrics Calculator Self-Check: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
