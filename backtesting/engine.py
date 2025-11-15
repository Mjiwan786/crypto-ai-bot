"""
Backtesting engine - simulates strategy execution against historical data.

Uses the same pure functions as live trading (graph.py) to ensure
consistency between backtest and production behavior.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from ai_engine import select_strategy, MarketSnapshot
from backtesting.metrics import Trade, calculate_metrics, BacktestResults

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for backtest run."""
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    timeframe: str

    # Risk parameters
    position_size_pct: float = 0.02  # 2% of capital per trade
    max_positions: int = 1  # Max concurrent positions
    stop_loss_pct: float = 0.02  # 2% stop loss
    take_profit_pct: float = 0.04  # 4% take profit

    # Transaction costs
    commission_pct: float = 0.001  # 0.1% per trade
    slippage_pct: float = 0.0005  # 0.05% slippage

    # Strategy parameters
    min_confidence_to_open: float = 0.55
    min_confidence_to_close: float = 0.35


class BacktestEngine:
    """
    Backtesting engine that simulates strategy execution.

    Uses pure graph logic from orchestration to ensure backtest matches
    live trading behavior.
    """

    def __init__(self, config: BacktestConfig):
        """
        Initialize backtest engine.

        Args:
            config: Backtest configuration
        """
        self.config = config
        self.equity = config.initial_capital
        self.cash = config.initial_capital
        self.positions: list[Trade] = []
        self.closed_trades: list[Trade] = []
        self.equity_curve: list[float] = [config.initial_capital]
        self.timestamps: list[pd.Timestamp] = []

    def get_position_size(self, price: float) -> float:
        """
        Calculate position size based on available capital.

        Args:
            price: Current price

        Returns:
            Position size in base currency
        """
        position_value = self.equity * self.config.position_size_pct
        quantity = position_value / price
        return quantity

    def can_open_position(self) -> bool:
        """Check if we can open a new position."""
        open_positions = [p for p in self.positions if p.status == "open"]
        return len(open_positions) < self.config.max_positions

    def execute_entry(
        self,
        timestamp: pd.Timestamp,
        symbol: str,
        side: str,
        price: float,
    ) -> Optional[Trade]:
        """
        Execute trade entry with transaction costs.

        Args:
            timestamp: Entry timestamp
            symbol: Trading symbol
            side: 'long' or 'short'
            price: Entry price

        Returns:
            Trade object if executed, None otherwise
        """
        if not self.can_open_position():
            logger.debug(f"Cannot open position: max positions reached")
            return None

        # Calculate position size
        quantity = self.get_position_size(price)
        position_value = quantity * price

        # Apply transaction costs
        commission = position_value * self.config.commission_pct
        slippage = position_value * self.config.slippage_pct
        total_cost = position_value + commission + slippage

        if total_cost > self.cash:
            logger.debug(f"Insufficient cash: need ${total_cost:.2f}, have ${self.cash:.2f}")
            return None

        # Deduct from cash
        self.cash -= total_cost

        # Create trade
        trade = Trade(
            entry_time=timestamp,
            exit_time=None,
            symbol=symbol,
            side=side,
            entry_price=price,
            exit_price=None,
            quantity=quantity,
            status="open",
        )

        self.positions.append(trade)

        logger.info(
            f"ENTRY: {side.upper()} {quantity:.4f} {symbol} @ ${price:.2f} "
            f"(cost: ${total_cost:.2f}, cash: ${self.cash:.2f})"
        )

        return trade

    def execute_exit(
        self,
        trade: Trade,
        timestamp: pd.Timestamp,
        price: float,
        reason: str = "signal",
    ) -> None:
        """
        Execute trade exit with transaction costs.

        Args:
            trade: Trade to close
            timestamp: Exit timestamp
            price: Exit price
            reason: Exit reason ('signal', 'stop', 'take_profit')
        """
        # Calculate proceeds
        position_value = trade.quantity * price
        commission = position_value * self.config.commission_pct
        slippage = position_value * self.config.slippage_pct
        proceeds = position_value - commission - slippage

        # Add proceeds to cash
        self.cash += proceeds

        # Close trade
        trade.close(timestamp, price, status=reason)

        # Move to closed trades
        self.positions.remove(trade)
        self.closed_trades.append(trade)

        logger.info(
            f"EXIT: {trade.side.upper()} {trade.quantity:.4f} {trade.symbol} @ ${price:.2f} "
            f"(P&L: ${trade.pnl:.2f}, {trade.pnl_pct:+.2f}%, "
            f"reason: {reason}, cash: ${self.cash:.2f})"
        )

    def check_stops(self, current_price: float, timestamp: pd.Timestamp) -> None:
        """
        Check if any positions hit stop loss or take profit.

        Args:
            current_price: Current market price
            timestamp: Current timestamp
        """
        for trade in self.positions[:]:  # Copy list since we'll modify it
            if trade.status != "open":
                continue

            if trade.side == "long":
                # Check stop loss
                stop_price = trade.entry_price * (1 - self.config.stop_loss_pct)
                if current_price <= stop_price:
                    self.execute_exit(trade, timestamp, current_price, reason="stop_loss")
                    continue

                # Check take profit
                tp_price = trade.entry_price * (1 + self.config.take_profit_pct)
                if current_price >= tp_price:
                    self.execute_exit(trade, timestamp, current_price, reason="take_profit")
                    continue

            else:  # short
                # Check stop loss
                stop_price = trade.entry_price * (1 + self.config.stop_loss_pct)
                if current_price >= stop_price:
                    self.execute_exit(trade, timestamp, current_price, reason="stop_loss")
                    continue

                # Check take profit
                tp_price = trade.entry_price * (1 - self.config.take_profit_pct)
                if current_price <= tp_price:
                    self.execute_exit(trade, timestamp, current_price, reason="take_profit")
                    continue

    def update_equity(self, current_price: float) -> None:
        """
        Update total equity based on open positions.

        Args:
            current_price: Current market price
        """
        # Calculate unrealized P&L
        unrealized_pnl = 0.0
        for trade in self.positions:
            if trade.side == "long":
                unrealized_pnl += (current_price - trade.entry_price) * trade.quantity
            else:  # short
                unrealized_pnl += (trade.entry_price - current_price) * trade.quantity

        self.equity = self.cash + unrealized_pnl

    def run(self, data: pd.DataFrame) -> BacktestResults:
        """
        Run backtest on historical data.

        Args:
            data: DataFrame with OHLCV columns

        Returns:
            BacktestResults with performance metrics
        """
        logger.info(f"Starting backtest: {self.config.symbol} from {self.config.start_date} to {self.config.end_date}")
        logger.info(f"Initial capital: ${self.config.initial_capital:,.2f}")

        lookback_periods = 300  # Periods needed for TA indicators

        if len(data) < lookback_periods:
            raise ValueError(
                f"Insufficient data: {len(data)} rows, need at least {lookback_periods}"
            )

        # Iterate through each bar
        for i in range(lookback_periods, len(data)):
            # Get current bar
            current_bar = data.iloc[i]
            timestamp = current_bar["timestamp"]
            current_price = current_bar["close"]

            # Get lookback window for strategy
            window = data.iloc[i - lookback_periods : i]

            # Check stops first
            self.check_stops(current_price, timestamp)

            # Create market snapshot
            snapshot = MarketSnapshot(
                symbol=self.config.symbol,
                timeframe=self.config.timeframe,
                timestamp_ms=int(timestamp.timestamp() * 1000),
                mid_price=float(current_price),
                spread_bps=5.0,  # Assume 5 bps spread
                volume_24h=float(window["volume"].sum()),
            )

            # Run strategy selector (pure function)
            try:
                advice = select_strategy(snapshot, window)

                # Execute based on advice
                if advice.action.value == "open" and advice.confidence >= self.config.min_confidence_to_open:
                    if advice.side.value == "long":
                        self.execute_entry(timestamp, self.config.symbol, "long", current_price)
                    elif advice.side.value == "short":
                        self.execute_entry(timestamp, self.config.symbol, "short", current_price)

                elif advice.action.value == "reduce" or advice.confidence < self.config.min_confidence_to_close:
                    # Close open positions
                    for trade in self.positions[:]:
                        if trade.status == "open":
                            self.execute_exit(trade, timestamp, current_price, reason="signal")

            except Exception as e:
                logger.warning(f"Strategy error at {timestamp}: {e}")

            # Update equity
            self.update_equity(current_price)
            self.equity_curve.append(self.equity)
            self.timestamps.append(timestamp)

        # Close any remaining positions
        final_timestamp = data.iloc[-1]["timestamp"]
        final_price = data.iloc[-1]["close"]
        for trade in self.positions[:]:
            self.execute_exit(trade, final_timestamp, final_price, reason="end_of_backtest")

        # Calculate metrics
        results = calculate_metrics(
            equity_curve=pd.Series(self.equity_curve),
            timestamps=pd.Series(self.timestamps),
            trades=self.closed_trades,
            initial_capital=self.config.initial_capital,
            symbol=self.config.symbol,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            timeframe=self.config.timeframe,
        )

        logger.info(f"Backtest complete: {results.total_trades} trades executed")
        logger.info(f"Final equity: ${self.equity:,.2f} ({results.total_return_pct:+.2f}%)")

        return results


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Run mini backtest with synthetic data"""
    import sys
    import numpy as np

    logging.basicConfig(level=logging.INFO)

    # Generate synthetic price data (uptrend with noise)
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=500, freq="1H")

    # Create price series
    trend = np.linspace(40000, 45000, 500)
    noise = np.random.normal(0, 200, 500)
    close = trend + noise

    # Generate OHLCV
    open_prices = close + np.random.normal(0, 50, 500)
    high = np.maximum(open_prices, close) + np.random.exponential(100, 500)
    low = np.minimum(open_prices, close) - np.random.exponential(100, 500)
    volume = np.random.lognormal(15, 1, 500)

    data = pd.DataFrame({
        "timestamp": dates,
        "open": open_prices,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })

    try:
        # Configure backtest
        config = BacktestConfig(
            symbol="BTC/USD",
            start_date="2023-01-01",
            end_date="2023-01-21",
            initial_capital=10000.0,
            timeframe="1h",
            position_size_pct=0.10,  # 10% per trade (aggressive for testing)
            max_positions=1,
        )

        # Run backtest
        engine = BacktestEngine(config)
        results = engine.run(data)

        # Print results
        print("\nPASS Backtest Engine Self-Check:")
        results.print_summary()

    except Exception as e:
        print(f"\nFAIL Backtest Engine Self-Check: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
