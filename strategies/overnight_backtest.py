"""
Overnight Momentum Strategy Backtest Framework

Simulates overnight momentum trading with:
- Asian session detection
- Low volume filtering
- Momentum entries
- Trailing stops
- Performance metrics
- Promotion gate validation

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import logging
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from dataclasses import dataclass, asdict
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from strategies.overnight_momentum import OvernightMomentumStrategy, OvernightSignal
from strategies.overnight_position_manager import OvernightPositionManager


@dataclass
class BacktestConfig:
    """Backtest configuration."""
    initial_equity_usd: Decimal = Decimal("10000")
    risk_per_trade_pct: Decimal = Decimal("1.0")
    commission_bps: int = 26  # 0.26% total fees
    slippage_bps: int = 10  # 10 bps
    lookback_bars: int = 20


@dataclass
class Trade:
    """Completed trade record."""
    symbol: str
    side: str
    entry_time: float
    entry_price: Decimal
    exit_time: float
    exit_price: Decimal
    quantity: Decimal
    notional_usd: Decimal
    pnl_usd: Decimal
    pnl_pct: float
    exit_reason: str
    hold_hours: float
    commission_usd: Decimal
    slippage_usd: Decimal
    net_pnl_usd: Decimal


@dataclass
class BacktestResults:
    """Backtest performance results."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float

    total_pnl_usd: Decimal
    total_pnl_pct: float

    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float

    max_drawdown: float
    max_drawdown_usd: Decimal

    sharpe_ratio: float
    sortino_ratio: float

    avg_hold_hours: float
    max_hold_hours: float

    final_equity_usd: Decimal
    total_return_pct: float

    trades: List[Trade]
    equity_curve: List[Tuple[float, Decimal]]

    # Promotion gate checks
    passes_promotion_gates: bool
    failed_gates: List[str]


class OvernightBacktester:
    """
    Backtest engine for overnight momentum strategy.

    Simulates trading on historical data and calculates metrics.
    """

    def __init__(
        self,
        strategy: OvernightMomentumStrategy,
        position_manager: OvernightPositionManager,
        config: Optional[BacktestConfig] = None,
        logger=None,
    ):
        """
        Initialize backtester.

        Args:
            strategy: Overnight momentum strategy
            position_manager: Position manager
            config: Backtest configuration
            logger: Logger instance
        """
        self.strategy = strategy
        self.position_manager = position_manager
        self.config = config or BacktestConfig()
        self.logger = logger or logging.getLogger(__name__)

        # State
        self.equity = self.config.initial_equity_usd
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[float, Decimal]] = []
        self.peak_equity = self.config.initial_equity_usd
        self.max_drawdown = Decimal("0")

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> BacktestResults:
        """
        Run backtest on historical data.

        Args:
            df: DataFrame with columns: timestamp, open, high, low, close, volume
            symbol: Trading symbol

        Returns:
            BacktestResults
        """
        self.logger.info(f"Starting backtest for {symbol} with {len(df)} bars")

        # Reset state
        self.equity = self.config.initial_equity_usd
        self.trades = []
        self.equity_curve = [(df.iloc[0]['timestamp'], self.equity)]
        self.peak_equity = self.equity
        self.max_drawdown = Decimal("0")

        # Track active position
        active_position = None

        # Iterate through bars
        for i in range(self.config.lookback_bars, len(df)):
            bar = df.iloc[i]
            current_time = bar['timestamp']
            current_price = Decimal(str(bar['close']))

            # Get lookback data
            lookback_data = df.iloc[i - self.config.lookback_bars:i]
            prices = [Decimal(str(p)) for p in lookback_data['close'].values]
            volumes = lookback_data['volume'].values.tolist()
            avg_24h_volume = float(lookback_data['volume'].mean())

            # Update trailing stops if position active
            if active_position:
                self.position_manager.update_trailing_stop(
                    symbol=symbol,
                    current_price=current_price,
                )

                # Check for exit
                should_exit, exit_reason = self.position_manager.check_exit(
                    symbol=symbol,
                    current_price=current_price,
                )

                if should_exit:
                    # Close position
                    exit_summary = self.position_manager.close_position(
                        symbol=symbol,
                        exit_price=current_price,
                        reason=exit_reason,
                    )

                    if exit_summary:
                        # Calculate costs
                        commission = self._calculate_commission(
                            Decimal(str(exit_summary['notional_usd']))
                        )
                        slippage = self._calculate_slippage(
                            Decimal(str(exit_summary['notional_usd']))
                        )

                        net_pnl = Decimal(str(exit_summary['pnl_usd'])) - commission - slippage

                        # Record trade
                        trade = Trade(
                            symbol=symbol,
                            side=exit_summary['side'],
                            entry_time=exit_summary['entry_time'],
                            entry_price=Decimal(str(exit_summary['entry_price'])),
                            exit_time=exit_summary['exit_time'],
                            exit_price=Decimal(str(exit_summary['exit_price'])),
                            quantity=Decimal(str(exit_summary['quantity'])),
                            notional_usd=Decimal(str(exit_summary['notional_usd'])),
                            pnl_usd=Decimal(str(exit_summary['pnl_usd'])),
                            pnl_pct=exit_summary['pnl_pct'],
                            exit_reason=exit_reason,
                            hold_hours=exit_summary['hold_time_hours'],
                            commission_usd=commission,
                            slippage_usd=slippage,
                            net_pnl_usd=net_pnl,
                        )

                        self.trades.append(trade)

                        # Update equity
                        self.equity += net_pnl
                        self.equity_curve.append((current_time, self.equity))

                        # Track drawdown
                        if self.equity > self.peak_equity:
                            self.peak_equity = self.equity
                        else:
                            drawdown = (self.peak_equity - self.equity) / self.peak_equity
                            if drawdown > self.max_drawdown:
                                self.max_drawdown = drawdown

                        self.logger.info(
                            f"Trade closed: {symbol} {trade.side.upper()} "
                            f"P&L={trade.pnl_pct:+.2f}% (${trade.net_pnl_usd:+.2f}), "
                            f"reason={exit_reason}, equity=${self.equity:.2f}"
                        )

                        active_position = None

            # Check for new signal (only if no active position)
            if active_position is None:
                signal = self.strategy.generate_signal(
                    symbol=symbol,
                    current_price=current_price,
                    prices=prices,
                    volumes=volumes,
                    avg_24h_volume=avg_24h_volume,
                    current_time=current_time,
                )

                if signal:
                    # Calculate position size
                    position_size_usd = self.position_manager.calculate_position_size(
                        signal=signal,
                        equity_usd=self.equity,
                        risk_per_trade_pct=self.config.risk_per_trade_pct,
                    )

                    # Open position
                    position = self.position_manager.open_position(
                        signal=signal,
                        position_size_usd=position_size_usd,
                    )

                    active_position = position

                    self.logger.info(
                        f"Position opened: {symbol} {signal.side.upper()} @ ${current_price:.2f}, "
                        f"size=${position_size_usd:.2f}, target=${signal.target_price:.2f}"
                    )

        # Close any remaining position at end
        if active_position:
            final_bar = df.iloc[-1]
            final_price = Decimal(str(final_bar['close']))
            final_time = final_bar['timestamp']

            exit_summary = self.position_manager.close_position(
                symbol=symbol,
                exit_price=final_price,
                reason="backtest_end",
            )

            if exit_summary:
                commission = self._calculate_commission(Decimal(str(exit_summary['notional_usd'])))
                slippage = self._calculate_slippage(Decimal(str(exit_summary['notional_usd'])))
                net_pnl = Decimal(str(exit_summary['pnl_usd'])) - commission - slippage

                trade = Trade(
                    symbol=symbol,
                    side=exit_summary['side'],
                    entry_time=exit_summary['entry_time'],
                    entry_price=Decimal(str(exit_summary['entry_price'])),
                    exit_time=final_time,
                    exit_price=final_price,
                    quantity=Decimal(str(exit_summary['quantity'])),
                    notional_usd=Decimal(str(exit_summary['notional_usd'])),
                    pnl_usd=Decimal(str(exit_summary['pnl_usd'])),
                    pnl_pct=exit_summary['pnl_pct'],
                    exit_reason="backtest_end",
                    hold_hours=exit_summary['hold_time_hours'],
                    commission_usd=commission,
                    slippage_usd=slippage,
                    net_pnl_usd=net_pnl,
                )

                self.trades.append(trade)
                self.equity += net_pnl
                self.equity_curve.append((final_time, self.equity))

        # Calculate results
        results = self._calculate_results()

        self.logger.info(
            f"Backtest complete: {results.total_trades} trades, "
            f"win_rate={results.win_rate:.1%}, "
            f"total_return={results.total_return_pct:.2f}%, "
            f"sharpe={results.sharpe_ratio:.2f}, "
            f"max_dd={results.max_drawdown:.2%}"
        )

        return results

    def _calculate_commission(self, notional_usd: Decimal) -> Decimal:
        """Calculate commission cost."""
        return notional_usd * Decimal(str(self.config.commission_bps / 10000))

    def _calculate_slippage(self, notional_usd: Decimal) -> Decimal:
        """Calculate slippage cost."""
        return notional_usd * Decimal(str(self.config.slippage_bps / 10000))

    def _calculate_results(self) -> BacktestResults:
        """Calculate backtest performance metrics."""
        if not self.trades:
            return BacktestResults(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl_usd=Decimal("0"),
                total_pnl_pct=0.0,
                avg_win_pct=0.0,
                avg_loss_pct=0.0,
                profit_factor=0.0,
                max_drawdown=0.0,
                max_drawdown_usd=Decimal("0"),
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                avg_hold_hours=0.0,
                max_hold_hours=0.0,
                final_equity_usd=self.equity,
                total_return_pct=0.0,
                trades=[],
                equity_curve=self.equity_curve,
                passes_promotion_gates=False,
                failed_gates=["No trades executed"],
            )

        # Basic stats
        total_trades = len(self.trades)
        winning_trades = sum(1 for t in self.trades if t.net_pnl_usd > 0)
        losing_trades = sum(1 for t in self.trades if t.net_pnl_usd <= 0)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        # P&L
        total_pnl_usd = sum(t.net_pnl_usd for t in self.trades)
        total_return_pct = float((self.equity - self.config.initial_equity_usd) / self.config.initial_equity_usd) * 100

        # Win/Loss averages
        wins = [t.pnl_pct for t in self.trades if t.net_pnl_usd > 0]
        losses = [t.pnl_pct for t in self.trades if t.net_pnl_usd <= 0]

        avg_win_pct = sum(wins) / len(wins) if wins else 0.0
        avg_loss_pct = sum(losses) / len(losses) if losses else 0.0

        # Profit factor
        gross_profit = sum(t.net_pnl_usd for t in self.trades if t.net_pnl_usd > 0)
        gross_loss = abs(sum(t.net_pnl_usd for t in self.trades if t.net_pnl_usd <= 0))
        profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 0.0

        # Hold times
        hold_hours = [t.hold_hours for t in self.trades]
        avg_hold_hours = sum(hold_hours) / len(hold_hours) if hold_hours else 0.0
        max_hold_hours = max(hold_hours) if hold_hours else 0.0

        # Risk metrics
        returns = [float(t.net_pnl_usd / self.config.initial_equity_usd) for t in self.trades]

        if len(returns) > 1:
            returns_array = np.array(returns)
            sharpe_ratio = float(np.mean(returns_array) / np.std(returns_array) * np.sqrt(252)) if np.std(returns_array) > 0 else 0.0

            # Sortino (downside deviation)
            downside_returns = returns_array[returns_array < 0]
            downside_std = float(np.std(downside_returns)) if len(downside_returns) > 0 else 0.0
            sortino_ratio = float(np.mean(returns_array) / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0
        else:
            sharpe_ratio = 0.0
            sortino_ratio = 0.0

        # Max drawdown (already tracked)
        max_drawdown_pct = float(self.max_drawdown)
        max_drawdown_usd = self.peak_equity * self.max_drawdown

        # Promotion gates check
        passes_gates, failed_gates = self.strategy.check_promotion_gates({
            "total_trades": total_trades,
            "win_rate": win_rate,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown_pct,
        })

        results = BacktestResults(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl_usd=total_pnl_usd,
            total_pnl_pct=total_return_pct,
            avg_win_pct=avg_win_pct,
            avg_loss_pct=avg_loss_pct,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown_pct,
            max_drawdown_usd=max_drawdown_usd,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            avg_hold_hours=avg_hold_hours,
            max_hold_hours=max_hold_hours,
            final_equity_usd=self.equity,
            total_return_pct=total_return_pct,
            trades=self.trades,
            equity_curve=self.equity_curve,
            passes_promotion_gates=passes_gates,
            failed_gates=failed_gates,
        )

        return results


def create_backtest_report(results: BacktestResults) -> str:
    """
    Create formatted backtest report.

    Args:
        results: Backtest results

    Returns:
        Formatted report string
    """
    report = f"""
{'='*80}
OVERNIGHT MOMENTUM STRATEGY - BACKTEST RESULTS
{'='*80}

PERFORMANCE SUMMARY
{'-'*80}
Total Trades:        {results.total_trades}
Winning Trades:      {results.winning_trades}
Losing Trades:       {results.losing_trades}
Win Rate:            {results.win_rate:.2%}

Total P&L:           ${results.total_pnl_usd:,.2f}
Total Return:        {results.total_return_pct:+.2f}%
Final Equity:        ${results.final_equity_usd:,.2f}

Average Win:         {results.avg_win_pct:+.2f}%
Average Loss:        {results.avg_loss_pct:+.2f}%
Profit Factor:       {results.profit_factor:.2f}

RISK METRICS
{'-'*80}
Max Drawdown:        {results.max_drawdown:.2%} (${results.max_drawdown_usd:,.2f})
Sharpe Ratio:        {results.sharpe_ratio:.2f}
Sortino Ratio:       {results.sortino_ratio:.2f}

HOLDING TIMES
{'-'*80}
Average Hold:        {results.avg_hold_hours:.1f} hours
Max Hold:            {results.max_hold_hours:.1f} hours

PROMOTION GATES
{'-'*80}
Status:              {'✅ PASS' if results.passes_promotion_gates else '❌ FAIL'}
"""

    if results.failed_gates:
        report += "\nFailed Gates:\n"
        for gate in results.failed_gates:
            report += f"  - {gate}\n"

    report += f"\n{'='*80}\n"

    return report


def print_trade_log(results: BacktestResults, max_trades: int = 10):
    """
    Print recent trades.

    Args:
        results: Backtest results
        max_trades: Maximum trades to display
    """
    print(f"\nRECENT TRADES (last {max_trades}):")
    print("-" * 120)
    print(f"{'Time':<20} {'Symbol':<10} {'Side':<6} {'Entry':<10} {'Exit':<10} {'P&L %':<10} {'Net P&L':<12} {'Reason':<15}")
    print("-" * 120)

    for trade in results.trades[-max_trades:]:
        entry_time_str = datetime.fromtimestamp(trade.entry_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(
            f"{entry_time_str:<20} {trade.symbol:<10} {trade.side.upper():<6} "
            f"${trade.entry_price:<9.2f} ${trade.exit_price:<9.2f} "
            f"{trade.pnl_pct:>+9.2f}% ${trade.net_pnl_usd:>+10.2f} {trade.exit_reason:<15}"
        )
    print("-" * 120)
