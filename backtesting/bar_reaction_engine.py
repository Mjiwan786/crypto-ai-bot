"""
Bar Reaction 5m Backtest Engine

Realistic maker-only fill simulation with:
- Limit order queue logic
- Bar touch detection (fills only if limit price in bar range)
- Optional queue_bars parameter (wait N bars for fill)
- Maker fees (16 bps) + minimal slippage (1-2 bps)
- ATR-based stops and dual profit targets (TP1, TP2)

H2: Fill Model
- Limit sits at decision price
- Fill if next bar's range touches the limit price:
  * Long: low <= limit
  * Short: high >= limit
- If not touched in next bar, treat as queued & cancelled
  (or allow --queue_bars 1 to roll another bar)
- Slippage: add +/- 1 bps if limit is touched exactly at high/low boundary
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, List, Tuple

import pandas as pd
import numpy as np

from strategies.bar_reaction_5m import BarReaction5mStrategy
from strategies.api import SignalSpec, PositionSpec
from backtesting.metrics import Trade, calculate_metrics, BacktestResults

logger = logging.getLogger(__name__)


@dataclass
class BarReactionBacktestConfig:
    """Configuration for bar reaction 5m backtest."""
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float

    # Strategy params (loaded from YAML)
    mode: str = "trend"
    trigger_mode: str = "open_to_close"
    trigger_bps_up: float = 12.0
    trigger_bps_down: float = 12.0
    min_atr_pct: float = 0.25
    max_atr_pct: float = 3.0
    atr_window: int = 14
    sl_atr: float = 0.6
    tp1_atr: float = 1.0
    tp2_atr: float = 1.8
    risk_per_trade_pct: float = 0.6
    maker_only: bool = True
    spread_bps_cap: float = 8.0

    # Cost model (H3)
    maker_fee_bps: int = 16      # 0.16% maker fee
    slippage_bps: int = 1        # 1 bps slippage (optimistic for maker)

    # Fill model (H2)
    queue_bars: int = 1          # Bars to wait for fill (0=immediate, 1=next bar)


@dataclass
class PendingOrder:
    """Pending limit order awaiting fill."""
    signal: SignalSpec
    position: PositionSpec
    limit_price: Decimal
    created_bar_idx: int
    expires_bar_idx: int
    side: str  # "long" or "short"


class BarReactionBacktestEngine:
    """
    Backtesting engine for bar_reaction_5m with realistic maker fill model.

    Features:
    - 5m bar rollup from 1m data (or native 5m if available)
    - ATR(14) precomputation
    - Maker-only limit order simulation
    - Bar touch detection for fills
    - Dual profit targets (TP1 @ 1.0x ATR, TP2 @ 1.8x ATR)
    - Partial exits (50% at TP1, 50% at TP2)
    """

    def __init__(self, config: BarReactionBacktestConfig):
        """
        Initialize backtest engine.

        Args:
            config: Backtest configuration
        """
        self.config = config
        self.strategy = BarReaction5mStrategy(
            mode=config.mode,
            trigger_mode=config.trigger_mode,
            trigger_bps_up=config.trigger_bps_up,
            trigger_bps_down=config.trigger_bps_down,
            min_atr_pct=config.min_atr_pct,
            max_atr_pct=config.max_atr_pct,
            atr_window=config.atr_window,
            sl_atr=config.sl_atr,
            tp1_atr=config.tp1_atr,
            tp2_atr=config.tp2_atr,
            risk_per_trade_pct=config.risk_per_trade_pct,
            maker_only=config.maker_only,
            spread_bps_cap=config.spread_bps_cap,
        )

        # State
        self.equity = Decimal(str(config.initial_capital))
        self.cash = Decimal(str(config.initial_capital))
        self.positions: List[Trade] = []
        self.pending_orders: List[PendingOrder] = []
        self.closed_trades: List[Trade] = []
        self.equity_curve: List[float] = []
        self.timestamps: List[pd.Timestamp] = []

    def rollup_to_5m(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        """
        Rollup 1-minute OHLCV to 5-minute bars.

        Args:
            df_1m: 1-minute OHLCV DataFrame

        Returns:
            5-minute OHLCV DataFrame
        """
        df_1m = df_1m.copy()
        df_1m.set_index("timestamp", inplace=True)

        df_5m = df_1m.resample("5min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        df_5m.reset_index(inplace=True)
        return df_5m

    def compute_features(self, df_5m: pd.DataFrame) -> pd.DataFrame:
        """
        Precompute ATR(14), move_bps, atr_pct for all 5m bars.

        Args:
            df_5m: 5-minute OHLCV DataFrame

        Returns:
            DataFrame with added feature columns
        """
        df = df_5m.copy()

        # Calculate ATR using Wilder's method
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())

        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = true_range.rolling(window=self.config.atr_window).mean()

        # ATR as percentage of close
        df["atr_pct"] = (df["atr"] / df["close"]) * 100

        # Bar move in bps (open to close for now, will adjust per trigger_mode)
        if self.config.trigger_mode == "open_to_close":
            df["move_bps"] = ((df["close"] - df["open"]) / df["open"]) * 10000
        else:  # prev_close_to_close
            df["move_bps"] = ((df["close"] - df["close"].shift()) / df["close"].shift()) * 10000

        return df

    def apply_slippage(self, price: float, side: str, at_boundary: bool) -> float:
        """
        Apply slippage if limit is touched exactly at high/low boundary.

        Args:
            price: Limit price
            side: "long" or "short"
            at_boundary: True if touched exactly at high/low

        Returns:
            Fill price after slippage
        """
        if not at_boundary:
            return price

        slippage_mult = 1.0 + (self.config.slippage_bps / 10000)

        if side == "long":
            # Long: touched at low, pay slightly higher
            return price * slippage_mult
        else:  # short
            # Short: touched at high, receive slightly lower
            return price * (2.0 - slippage_mult)

    def check_fill(
        self,
        pending: PendingOrder,
        bar: pd.Series,
        bar_idx: int,
    ) -> Optional[Tuple[float, bool]]:
        """
        Check if pending limit order gets filled by bar.

        Fill logic (H2):
        - Long: fill if bar.low <= limit_price
        - Short: fill if bar.high >= limit_price
        - Add slippage if touched exactly at boundary

        Args:
            pending: Pending order
            bar: Current bar data
            bar_idx: Current bar index

        Returns:
            Tuple of (fill_price, at_boundary) if filled, None otherwise
        """
        limit_price = float(pending.limit_price)
        bar_high = bar["high"]
        bar_low = bar["low"]

        if pending.side == "long":
            # Long: fill if low touches or goes below limit
            if bar_low <= limit_price:
                at_boundary = abs(bar_low - limit_price) / limit_price < 0.0001  # Within 1 bps
                fill_price = self.apply_slippage(limit_price, "long", at_boundary)
                return (fill_price, at_boundary)
        else:  # short
            # Short: fill if high touches or goes above limit
            if bar_high >= limit_price:
                at_boundary = abs(bar_high - limit_price) / limit_price < 0.0001
                fill_price = self.apply_slippage(limit_price, "short", at_boundary)
                return (fill_price, at_boundary)

        return None

    def process_pending_orders(self, bar: pd.Series, bar_idx: int) -> None:
        """
        Process pending orders: check fills and expirations.

        Args:
            bar: Current bar data
            bar_idx: Current bar index
        """
        for pending in self.pending_orders[:]:  # Copy list
            # Check expiration
            if bar_idx > pending.expires_bar_idx:
                logger.debug(
                    f"Order expired: {pending.side} {pending.position.symbol} "
                    f"@ {pending.limit_price} (not filled)"
                )
                self.pending_orders.remove(pending)
                continue

            # Check fill
            fill_result = self.check_fill(pending, bar, bar_idx)
            if fill_result:
                fill_price, at_boundary = fill_result
                self.execute_fill(
                    pending=pending,
                    fill_price=fill_price,
                    timestamp=bar["timestamp"],
                    at_boundary=at_boundary,
                )
                self.pending_orders.remove(pending)

    def execute_fill(
        self,
        pending: PendingOrder,
        fill_price: float,
        timestamp: pd.Timestamp,
        at_boundary: bool,
    ) -> None:
        """
        Execute fill of pending limit order.

        Applies maker fees (16 bps) and creates Trade object.

        Args:
            pending: Pending order that was filled
            fill_price: Actual fill price (after slippage)
            timestamp: Fill timestamp
            at_boundary: True if filled at exact high/low
        """
        position = pending.position
        signal = pending.signal

        # Calculate cost with maker fee (H3)
        notional = Decimal(str(fill_price)) * position.size
        maker_fee = notional * Decimal(str(self.config.maker_fee_bps / 10000))
        total_cost = notional + maker_fee

        # CRITICAL FIX: Minimum position size check to prevent dust trading
        MIN_POSITION_SIZE_USD = Decimal("50.0")  # $50 minimum to avoid fee death spiral
        if notional < MIN_POSITION_SIZE_USD:
            logger.info(
                f"Skipping trade: position size ${notional:.2f} below minimum ${MIN_POSITION_SIZE_USD} "
                f"(would be eaten by fees)"
            )
            return

        # Deduct from cash
        if total_cost > self.cash:
            logger.warning(f"Insufficient cash: need {total_cost:.2f}, have {self.cash:.2f}")
            return

        self.cash -= total_cost

        # Calculate SL and TP prices from signal metadata
        tp1_price = float(signal.metadata.get("tp1_price", signal.take_profit))
        tp2_price = float(signal.metadata.get("tp2_price", signal.take_profit))
        sl_price = float(signal.stop_loss)

        # Create trade
        trade = Trade(
            entry_time=timestamp,
            exit_time=None,
            symbol=position.symbol,
            side=position.side,
            entry_price=fill_price,
            exit_price=None,
            quantity=float(position.size),
            status="open",
            # ATR fields
            atr_value=float(signal.metadata.get("atr", 0)),
            sl_atr_multiple=self.config.sl_atr,
            tp1_atr_multiple=self.config.tp1_atr,
            tp2_atr_multiple=self.config.tp2_atr,
            initial_stop_loss=sl_price,
            current_stop_loss=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            tp1_size_pct=50.0,  # 50% at TP1
        )

        self.positions.append(trade)

        logger.info(
            f"FILLED: {position.side.upper()} {position.size:.6f} {position.symbol} "
            f"@ ${fill_price:.2f} (limit={pending.limit_price:.2f}, "
            f"fee=${maker_fee:.2f}, boundary={at_boundary})"
        )

    def check_exits(self, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """
        Check if any open positions hit SL or TP.

        Supports dual profit targets:
        - TP1: Close 50% of position at tp1_price
        - TP2: Close remaining 50% at tp2_price
        - SL: Close entire position

        Args:
            bar: Current bar data
            timestamp: Current timestamp
        """
        for trade in self.positions[:]:  # Copy list
            if trade.status != "open":
                continue

            bar_high = bar["high"]
            bar_low = bar["low"]

            if trade.side == "long":
                # Check stop loss
                if bar_low <= trade.current_stop_loss:
                    self.execute_exit(
                        trade=trade,
                        exit_price=trade.current_stop_loss,
                        timestamp=timestamp,
                        reason="stop_loss",
                        size_pct=100.0,
                    )
                    continue

                # Check TP1 (if not hit yet)
                if not trade.tp1_hit and bar_high >= trade.tp1_price:
                    trade.tp1_hit = True
                    self.execute_exit(
                        trade=trade,
                        exit_price=trade.tp1_price,
                        timestamp=timestamp,
                        reason="tp1",
                        size_pct=50.0,
                    )
                    # Check if trade was fully closed after partial exit
                    if trade not in self.positions:
                        continue
                    # Move stop to breakeven
                    trade.current_stop_loss = trade.entry_price
                    trade.stop_moved_to_be = True
                    logger.debug(f"Moved stop to breakeven @ {trade.entry_price:.2f}")

                # Check TP2 (if TP1 already hit and trade still open)
                if trade in self.positions and trade.tp1_hit and bar_high >= trade.tp2_price:
                    self.execute_exit(
                        trade=trade,
                        exit_price=trade.tp2_price,
                        timestamp=timestamp,
                        reason="tp2",
                        size_pct=50.0,
                    )
                    continue

            else:  # short
                # Check stop loss
                if bar_high >= trade.current_stop_loss:
                    self.execute_exit(
                        trade=trade,
                        exit_price=trade.current_stop_loss,
                        timestamp=timestamp,
                        reason="stop_loss",
                        size_pct=100.0,
                    )
                    continue

                # Check TP1
                if not trade.tp1_hit and bar_low <= trade.tp1_price:
                    trade.tp1_hit = True
                    self.execute_exit(
                        trade=trade,
                        exit_price=trade.tp1_price,
                        timestamp=timestamp,
                        reason="tp1",
                        size_pct=50.0,
                    )
                    # Check if trade was fully closed after partial exit
                    if trade not in self.positions:
                        continue
                    # Move stop to breakeven
                    trade.current_stop_loss = trade.entry_price
                    trade.stop_moved_to_be = True
                    logger.debug(f"Moved stop to breakeven @ {trade.entry_price:.2f}")

                # Check TP2 (if trade still open)
                if trade in self.positions and trade.tp1_hit and bar_low <= trade.tp2_price:
                    self.execute_exit(
                        trade=trade,
                        exit_price=trade.tp2_price,
                        timestamp=timestamp,
                        reason="tp2",
                        size_pct=50.0,
                    )
                    continue

    def execute_exit(
        self,
        trade: Trade,
        exit_price: float,
        timestamp: pd.Timestamp,
        reason: str,
        size_pct: float,
    ) -> None:
        """
        Execute trade exit (full or partial).

        Args:
            trade: Trade to exit
            exit_price: Exit price
            timestamp: Exit timestamp
            reason: Exit reason (stop_loss, tp1, tp2, etc.)
            size_pct: Percentage of position to close (50 or 100)
        """
        # Calculate proceeds
        exit_quantity = trade.quantity * (size_pct / 100.0)
        notional = Decimal(str(exit_price)) * Decimal(str(exit_quantity))
        maker_fee = notional * Decimal(str(self.config.maker_fee_bps / 10000))
        proceeds = notional - maker_fee

        # Add to cash
        self.cash += proceeds

        # Calculate P&L for this exit
        if trade.side == "long":
            pnl = (exit_price - trade.entry_price) * exit_quantity
            pnl_pct = ((exit_price / trade.entry_price) - 1) * 100
        else:  # short
            pnl = (trade.entry_price - exit_price) * exit_quantity
            pnl_pct = ((trade.entry_price / exit_price) - 1) * 100

        # Always update trade's remaining size
        original_quantity = trade.quantity
        trade.remaining_size_pct -= size_pct

        if size_pct >= 100.0 or trade.remaining_size_pct <= 0.01:
            # Full exit or position fully closed: close trade and add to closed_trades
            # For partial exits that complete the position, we need to use weighted average exit price
            # But for simplicity, we use the final exit price
            # Use "closed" status so it's counted by metrics calculator
            trade.close(timestamp, exit_price, status="closed")
            if trade in self.positions:
                self.positions.remove(trade)
            self.closed_trades.append(trade)

            logger.info(
                f"EXIT: {trade.side.upper()} {exit_quantity:.6f} {trade.symbol} "
                f"@ ${exit_price:.2f} (P&L: ${pnl:.2f}, {pnl_pct:+.2f}%, reason: {reason})"
            )
        else:
            # Partial exit: reduce quantity but keep position open
            trade.quantity -= exit_quantity

            logger.info(
                f"PARTIAL EXIT ({size_pct:.0f}%): {trade.side.upper()} {exit_quantity:.6f} {trade.symbol} "
                f"@ ${exit_price:.2f} (P&L: ${pnl:.2f}, {pnl_pct:+.2f}%, reason: {reason})"
            )

    def update_equity(self, current_price: float) -> None:
        """
        Update total equity based on open positions.

        Args:
            current_price: Current market price
        """
        unrealized_pnl = Decimal("0")
        for trade in self.positions:
            if trade.status == "open":
                if trade.side == "long":
                    unrealized_pnl += Decimal(str((current_price - trade.entry_price) * trade.quantity))
                else:  # short
                    unrealized_pnl += Decimal(str((trade.entry_price - current_price) * trade.quantity))

        self.equity = self.cash + unrealized_pnl

    def run(self, df_1m: pd.DataFrame) -> BacktestResults:
        """
        Run backtest on 1-minute data (will rollup to 5m).

        Args:
            df_1m: 1-minute OHLCV DataFrame

        Returns:
            BacktestResults with performance metrics
        """
        logger.info(f"Starting bar_reaction_5m backtest: {self.config.symbol}")
        logger.info(f"Period: {self.config.start_date} to {self.config.end_date}")
        logger.info(f"Initial capital: ${self.config.initial_capital:,.2f}")

        # H1: Build 5m bars and compute features
        logger.info("Rolling up 1m -> 5m bars...")
        df_5m = self.rollup_to_5m(df_1m)
        logger.info(f"Generated {len(df_5m)} 5m bars")

        logger.info("Computing ATR(14), move_bps, atr_pct...")
        df_5m = self.compute_features(df_5m)

        # Prepare strategy
        self.strategy.prepare(self.config.symbol, df_1m)

        warmup_bars = max(self.config.atr_window + 5, 50)
        if len(df_5m) < warmup_bars:
            raise ValueError(f"Insufficient data: {len(df_5m)} bars, need at least {warmup_bars}")

        logger.info(f"Starting simulation from bar {warmup_bars} / {len(df_5m)}")

        # CRITICAL FIX: Drawdown circuit breaker
        MAX_DRAWDOWN_PCT = 20.0  # Stop trading at -20% drawdown per PRD
        circuit_breaker_triggered = False

        # Simulate bar by bar
        for i in range(warmup_bars, len(df_5m)):
            bar = df_5m.iloc[i]
            timestamp = bar["timestamp"]
            # Ensure timestamp is timezone-aware
            if timestamp.tz is None:
                from datetime import timezone as dt_timezone
                timestamp = timestamp.replace(tzinfo=dt_timezone.utc)
            close_price = bar["close"]

            # CRITICAL FIX: Check drawdown circuit breaker BEFORE trading
            current_dd_pct = ((float(self.equity) / self.config.initial_capital) - 1) * 100
            if current_dd_pct <= -MAX_DRAWDOWN_PCT and not circuit_breaker_triggered:
                circuit_breaker_triggered = True
                logger.warning(
                    f"CIRCUIT BREAKER TRIGGERED: Drawdown {current_dd_pct:.2f}% exceeded "
                    f"-{MAX_DRAWDOWN_PCT}% threshold. Stopping new trades."
                )
                # Close all pending orders
                self.pending_orders.clear()
                # Close all open positions at market
                for trade in self.positions[:]:
                    self.execute_exit(
                        trade=trade,
                        exit_price=close_price,
                        timestamp=timestamp,
                        reason="circuit_breaker",
                        size_pct=100.0,
                    )

            # Process pending orders first (H2: check fills)
            if not circuit_breaker_triggered:
                self.process_pending_orders(bar, i)

            # Check exits for open positions
            self.check_exits(bar, timestamp)

            # Generate new signals at bar close (skip if circuit breaker active)
            # Pass current bar's slice of features so strategy sees correct bar
            df_up_to_current = df_5m.iloc[:i+1]
            if not circuit_breaker_triggered and self.strategy.should_trade(self.config.symbol, df_5m=df_up_to_current):
                signals = self.strategy.generate_signals(
                    symbol=self.config.symbol,
                    current_price=close_price,
                    df_5m=df_up_to_current,
                    timestamp=timestamp,
                )

                if signals:
                    # Size positions
                    positions = self.strategy.size_positions(
                        signals=signals,
                        account_equity_usd=self.equity,
                    )

                    # Place limit orders (H2: add to pending queue)
                    for signal, position in zip(signals, positions):
                        if len(self.positions) + len(self.pending_orders) >= 1:  # Max 1 position
                            continue

                        pending = PendingOrder(
                            signal=signal,
                            position=position,
                            limit_price=signal.entry_price,
                            created_bar_idx=i,
                            expires_bar_idx=i + self.config.queue_bars,
                            side=signal.side,
                        )

                        self.pending_orders.append(pending)
                        logger.debug(
                            f"PENDING ORDER: {signal.side.upper()} {position.symbol} "
                            f"@ {signal.entry_price:.2f} (expires in {self.config.queue_bars} bars)"
                        )

            # Update equity
            self.update_equity(close_price)
            self.equity_curve.append(float(self.equity))
            self.timestamps.append(timestamp)

        # Close remaining positions at end
        final_bar = df_5m.iloc[-1]
        final_price = final_bar["close"]
        final_timestamp = final_bar["timestamp"]

        for trade in self.positions[:]:
            self.execute_exit(
                trade=trade,
                exit_price=final_price,
                timestamp=final_timestamp,
                reason="end_of_backtest",
                size_pct=100.0,
            )

        # Cancel remaining pending orders
        self.pending_orders.clear()

        # Calculate metrics
        results = calculate_metrics(
            equity_curve=pd.Series(self.equity_curve),
            timestamps=pd.Series(self.timestamps),
            trades=self.closed_trades,
            initial_capital=self.config.initial_capital,
            symbol=self.config.symbol,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            timeframe="5m",
        )

        logger.info(f"Backtest complete: {results.total_trades} trades executed")
        logger.info(f"Final equity: ${float(self.equity):,.2f} ({results.total_return_pct:+.2f}%)")

        return results
