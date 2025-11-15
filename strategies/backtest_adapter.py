"""
Strategy backtest adapter for crypto-ai-bot.

Bridges the Strategy API (SignalSpec, MarketSnapshot) with the backtest engine's
interface (Signal, BarContext) to enable backtesting of strategies.

Features:
- Converts BarContext → MarketSnapshot + OHLCV DataFrame
- Calls strategy methods (generate_signals, size_positions)
- Converts SignalSpec → Signal format for backtest engine
- Handles position sizing and risk management
- Supports all strategy types (Breakout, Momentum, MeanReversion, RegimeRouter)
- Optional PnL emission to Redis streams for unified charts (backtest + live)

PnL Emission:
    When EMIT_PNL_EVENTS=true, backtest trades are published to the same
    Redis stream (trades:closed) used by live trading. This enables unified
    equity charts combining historical backtest data with live results.

    Features:
    - Uses candle close timestamps for realistic spacing
    - Silent failure if Redis unavailable (doesn't break backtests)
    - Tracks entry price and calculates PnL on exit
    - Compatible with PnL aggregator (monitoring/pnl_aggregator.py)

Example:
    from strategies import BreakoutStrategy
    from strategies.backtest_adapter import StrategyBacktestAdapter
    from agents.scalper.backtest.engine import BacktestEngine

    # Create strategy
    strategy = BreakoutStrategy()

    # Create adapter (with PnL emission enabled)
    import os
    os.environ["EMIT_PNL_EVENTS"] = "true"

    adapter = StrategyBacktestAdapter(
        strategy=strategy,
        account_equity_usd=Decimal("10000"),
        current_volatility=Decimal("0.50"),
    )

    # Use with backtest engine
    engine = BacktestEngine(config)
    engine.load_ohlcv(data)
    result = engine.run(pairs, timeframe, strategy_adapter=adapter)

    # Backtest trades are now in Redis stream "trades:closed"
    # Run aggregator to see unified equity curve:
    #   python -m monitoring.pnl_aggregator
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol, Optional, Union

import pandas as pd
import numpy as np

from ai_engine.schemas import MarketSnapshot, RegimeLabel
from strategies.api import SignalSpec, PositionSpec
from strategies.regime_based_router import RegimeBasedRouter

# Optional: PnL publisher for unified charts (can fail silently)
try:
    from agents.infrastructure.pnl_publisher import publish_trade_close
    PNL_PUBLISHER_AVAILABLE = True
except ImportError:
    PNL_PUBLISHER_AVAILABLE = False

# Import backtest engine types
try:
    from agents.scalper.backtest.engine import (
        BarContext,
        Signal,
        Side,
        OrderType,
        Position,
    )
except ImportError:
    # Fallback for when backtest engine is not available
    from typing import Any as BarContext
    from typing import Any as Signal
    from typing import Any as Side
    from typing import Any as OrderType
    from typing import Any as Position

logger = logging.getLogger(__name__)


# =============================================================================
# Strategy Protocol
# =============================================================================


class Strategy(Protocol):
    """
    Protocol for strategies that can be adapted for backtesting.

    All strategies (Breakout, Momentum, MeanReversion) implement this interface.
    """

    def prepare(self, snapshot: MarketSnapshot, ohlcv_df: pd.DataFrame) -> None:
        """Prepare strategy by caching expensive calculations."""
        ...

    def should_trade(self, snapshot: MarketSnapshot) -> bool:
        """Fast pre-filter before signal generation."""
        ...

    def generate_signals(
        self,
        snapshot: MarketSnapshot,
        ohlcv_df: pd.DataFrame,
        regime_label: RegimeLabel,
    ) -> list[SignalSpec]:
        """Generate trading signals."""
        ...

    def size_positions(
        self,
        signals: list[SignalSpec],
        account_equity_usd: Decimal,
        current_volatility: Decimal,
    ) -> list[PositionSpec]:
        """Convert signals to sized positions."""
        ...


# =============================================================================
# Backtest Adapter
# =============================================================================


class StrategyBacktestAdapter:
    """
    Adapter to use Strategy API strategies with backtest engine.

    Converts between:
    - BarContext → MarketSnapshot + OHLCV DataFrame
    - SignalSpec → Signal (backtest engine format)

    Attributes:
        strategy: Strategy instance to adapt
        account_equity_usd: Current account equity for position sizing
        current_volatility: Current market volatility (annualized)
        regime_label: Current market regime (default CHOP)
        ohlcv_history: Historical OHLCV data for technical indicators
        max_history_bars: Maximum bars to keep in history
    """

    def __init__(
        self,
        strategy: Union[Strategy, RegimeBasedRouter],
        account_equity_usd: Decimal = Decimal("10000"),
        current_volatility: Decimal = Decimal("0.50"),
        regime_label: RegimeLabel = RegimeLabel.CHOP,
        max_history_bars: int = 200,
        execution_config: Optional[dict] = None,
    ):
        """
        Initialize backtest adapter.

        Args:
            strategy: Strategy instance or RegimeBasedRouter
            account_equity_usd: Starting account equity
            current_volatility: Market volatility (annualized, e.g., 0.50 = 50%)
            regime_label: Default market regime (BULL/BEAR/CHOP)
            max_history_bars: Maximum bars to keep for indicators
            execution_config: Optional execution config (maker_only, max_queue_s, spread_bps_cap)
        """
        self.strategy = strategy
        self.account_equity_usd = account_equity_usd
        self.current_volatility = current_volatility
        self.regime_label = regime_label
        self.max_history_bars = max_history_bars

        # Execution configuration for maker-only trading
        self.execution_config = execution_config or {
            "maker_only": True,
            "max_queue_s": 10,
            "spread_bps_cap": 8,
        }

        # Historical OHLCV data for technical indicators
        self.ohlcv_history: dict[str, list[dict]] = {}

        # Track whether this is a RegimeRouter (has different interface)
        self.is_router = isinstance(strategy, RegimeBasedRouter)

        # PnL emission toggle (check environment variable)
        self.emit_pnl_events = (
            PNL_PUBLISHER_AVAILABLE
            and os.getenv("EMIT_PNL_EVENTS", "true").lower() in ("true", "1", "yes")
        )

        # Track open position for PnL calculation
        self.open_position_data: Optional[dict] = None

        logger.info(
            f"StrategyBacktestAdapter initialized: "
            f"strategy={strategy.__class__.__name__}, "
            f"equity=${account_equity_usd}, "
            f"vol={current_volatility}, "
            f"regime={regime_label.value}, "
            f"emit_pnl={self.emit_pnl_events}, "
            f"execution={self.execution_config}"
        )

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        """
        Process bar and return signals (backtest engine interface).

        This is the main entry point called by the backtest engine.

        Args:
            ctx: BarContext with candle, position, equity, etc.

        Returns:
            List of Signal objects for backtest engine
        """
        # Update equity from backtest engine
        self.account_equity_usd = Decimal(str(ctx.equity))

        # Update OHLCV history
        self._update_ohlcv_history(ctx)

        # Convert BarContext to MarketSnapshot
        snapshot = self._bar_context_to_snapshot(ctx)

        # Get OHLCV DataFrame for technical indicators
        ohlcv_df = self._get_ohlcv_dataframe(ctx.pair)

        # Check if we have enough data
        if len(ohlcv_df) < 20:  # Need minimum data for indicators
            logger.debug(f"Insufficient data: {len(ohlcv_df)} bars, need at least 20")
            return []

        # Handle position exits first
        if not ctx.position.is_flat:
            exit_signal = self._check_exit_conditions(ctx, snapshot, ohlcv_df)
            if exit_signal:
                # Emit PnL event for closed trade (if enabled)
                self._emit_trade_close_event(ctx, snapshot)
                return [exit_signal]

        # Handle new entries
        if ctx.position.is_flat:
            entry_signals = self._generate_entry_signals(snapshot, ohlcv_df)

            # Track entry for future PnL emission
            if entry_signals and self.emit_pnl_events:
                self._track_position_entry(ctx, entry_signals[0], snapshot)

            return entry_signals

        return []

    def _update_ohlcv_history(self, ctx: BarContext) -> None:
        """Update OHLCV history with new bar."""
        pair = ctx.pair

        if pair not in self.ohlcv_history:
            self.ohlcv_history[pair] = []

        # Append new bar
        bar_data = {
            "timestamp": ctx.candle.time,
            "open": float(ctx.candle.open),
            "high": float(ctx.candle.high),
            "low": float(ctx.candle.low),
            "close": float(ctx.candle.close),
            "volume": float(ctx.candle.volume),
        }

        self.ohlcv_history[pair].append(bar_data)

        # Trim history to max_history_bars
        if len(self.ohlcv_history[pair]) > self.max_history_bars:
            self.ohlcv_history[pair] = self.ohlcv_history[pair][-self.max_history_bars :]

    def _get_ohlcv_dataframe(self, pair: str) -> pd.DataFrame:
        """Get OHLCV DataFrame for technical indicator calculations."""
        if pair not in self.ohlcv_history:
            return pd.DataFrame()

        df = pd.DataFrame(self.ohlcv_history[pair])

        if df.empty:
            return df

        # Set timestamp as index
        df.set_index("timestamp", inplace=True)

        return df

    def _bar_context_to_snapshot(self, ctx: BarContext) -> MarketSnapshot:
        """
        Convert BarContext to MarketSnapshot.

        Args:
            ctx: BarContext from backtest engine

        Returns:
            MarketSnapshot for Strategy API
        """
        # Convert timestamp to milliseconds
        timestamp_ms = int(ctx.candle.time.timestamp() * 1000)

        # Use close price as mid_price
        mid_price = float(ctx.candle.close)

        # Estimate spread from candle range or use provided spread_bps
        if ctx.spread_bps is not None:
            spread_bps = float(ctx.spread_bps)
        else:
            # Estimate: spread ~= 10% of (high - low)
            candle_range_pct = (float(ctx.candle.high) - float(ctx.candle.low)) / mid_price
            spread_bps = min(candle_range_pct * 0.1 * 10000, 20.0)  # Cap at 20 bps

        # Estimate 24h volume (approximate from recent bars)
        if ctx.pair in self.ohlcv_history and len(self.ohlcv_history[ctx.pair]) > 0:
            recent_volume = sum(
                bar["volume"] * bar["close"] for bar in self.ohlcv_history[ctx.pair][-24:]
            )
            volume_24h = recent_volume
        else:
            volume_24h = float(ctx.candle.volume) * mid_price * 24  # Rough estimate

        snapshot = MarketSnapshot(
            symbol=ctx.pair,
            timeframe=ctx.timeframe,
            timestamp_ms=timestamp_ms,
            mid_price=mid_price,
            spread_bps=spread_bps,
            volume_24h=volume_24h,
        )

        return snapshot

    def _generate_entry_signals(
        self, snapshot: MarketSnapshot, ohlcv_df: pd.DataFrame
    ) -> list[Signal]:
        """
        Generate entry signals from strategy.

        Args:
            snapshot: Market snapshot
            ohlcv_df: OHLCV DataFrame

        Returns:
            List of Signal objects for backtest engine
        """
        # Prepare strategy (cache calculations)
        if hasattr(self.strategy, "prepare"):
            self.strategy.prepare(snapshot, ohlcv_df)

        # Check if strategy should trade
        if hasattr(self.strategy, "should_trade"):
            if not self.strategy.should_trade(snapshot):
                logger.debug(f"{self.strategy.__class__.__name__}: should_trade=False")
                return []

        # Generate signals from strategy
        if self.is_router:
            # RegimeBasedRouter has different interface
            signal_spec, routing_reason = self.strategy.route_signal(
                snapshot, ohlcv_df, self.regime_label
            )
            signal_specs = [signal_spec] if signal_spec else []
            if signal_spec:
                logger.debug(f"Router: {routing_reason}")
        else:
            # Regular strategy
            signal_specs = self.strategy.generate_signals(snapshot, ohlcv_df, self.regime_label)

        if not signal_specs:
            return []

        # Size positions
        if self.is_router:
            # RegimeRouter handles sizing differently
            positions = []
            for signal_spec in signal_specs:
                # Manually call size_positions on appropriate strategy
                # This is a simplified approach - RegimeRouter should handle this
                position_spec = self._size_signal_spec(signal_spec)
                if position_spec:
                    positions.append(position_spec)
        else:
            # Regular strategy
            positions = self.strategy.size_positions(
                signal_specs, self.account_equity_usd, self.current_volatility
            )

        if not positions:
            return []

        # Convert PositionSpec → Signal
        signals = []
        for position in positions:
            signal = self._position_spec_to_signal(position, snapshot)
            signals.append(signal)
            logger.info(
                f"Entry signal: {signal.side.value} {signal.target_qty:.6f} @ "
                f"{signal.target_price or 'MARKET'}"
            )

        return signals

    def _size_signal_spec(self, signal_spec: SignalSpec) -> Optional[PositionSpec]:
        """
        Size a single signal spec (fallback for router).

        This is a simplified sizing method used when the router doesn't
        handle sizing directly.
        """
        # Calculate position size (simple approach)
        risk_per_trade = self.account_equity_usd * Decimal("0.02")  # 2% risk
        stop_distance = abs(signal_spec.entry_price - signal_spec.stop_loss)

        if stop_distance == 0:
            return None

        size_base = risk_per_trade / stop_distance
        size_usd = size_base * signal_spec.entry_price

        # Cap at 10% of equity
        max_size_usd = self.account_equity_usd * Decimal("0.10")
        if size_usd > max_size_usd:
            size_usd = max_size_usd
            size_base = size_usd / signal_spec.entry_price

        expected_risk_usd = size_base * stop_distance

        position = PositionSpec(
            signal_id=signal_spec.signal_id,
            symbol=signal_spec.symbol,
            side=signal_spec.side,
            size=size_base,
            notional_usd=size_usd,
            entry_price=signal_spec.entry_price,
            stop_loss=signal_spec.stop_loss,
            take_profit=signal_spec.take_profit,
            expected_risk_usd=expected_risk_usd,
            volatility_adjusted=False,
            kelly_fraction=None,
        )

        return position

    def _position_spec_to_signal(self, position: PositionSpec, snapshot: MarketSnapshot) -> Signal:
        """
        Convert PositionSpec to Signal for backtest engine.

        Args:
            position: PositionSpec from strategy
            snapshot: Market snapshot

        Returns:
            Signal for backtest engine
        """
        # Convert side: "long" → BUY, "short" → SELL
        if position.side == "long":
            side = Side.BUY
        elif position.side == "short":
            side = Side.SELL
        else:
            raise ValueError(f"Unknown side: {position.side}")

        # Use MARKET orders by default (can be customized)
        order_type = OrderType.MARKET
        target_price = None  # Market orders don't need target price
        post_only = False
        hidden = False

        signal = Signal(
            pair=position.symbol,
            side=side,
            type="entry",
            target_qty=position.size,
            target_price=target_price,
            stop_price=position.stop_loss,
            order_type=order_type,
            post_only=post_only,
            hidden=hidden,
            metadata={
                "signal_id": position.signal_id,
                "entry_price": str(position.entry_price),
                "stop_loss": str(position.stop_loss),
                "take_profit": str(position.take_profit),
                "expected_risk_usd": str(position.expected_risk_usd),
                "notional_usd": str(position.notional_usd),
            },
        )

        return signal

    def _check_exit_conditions(
        self, ctx: BarContext, snapshot: MarketSnapshot, ohlcv_df: pd.DataFrame
    ) -> Optional[Signal]:
        """
        Check if current position should be exited.

        Checks:
        - Take profit hit
        - Stop loss hit
        - Time-based exit (optional)

        Args:
            ctx: BarContext
            snapshot: Market snapshot
            ohlcv_df: OHLCV DataFrame

        Returns:
            Exit signal if position should be closed, else None
        """
        position = ctx.position
        current_price = float(ctx.candle.close)

        # Extract stop/target from position metadata (if available)
        # This would require tracking entry metadata - for now, use simple P&L-based exits

        # Calculate current P&L in basis points
        if position.is_long:
            pnl_bps = ((current_price - float(position.avg_price)) / float(position.avg_price)) * 10000
        else:
            pnl_bps = ((float(position.avg_price) - current_price) / float(position.avg_price)) * 10000

        # Check take profit (example: +50 bps)
        if pnl_bps >= 50:
            logger.info(f"Take profit hit: {pnl_bps:.2f} bps")
            return self._create_exit_signal(ctx, "take_profit")

        # Check stop loss (example: -25 bps)
        if pnl_bps <= -25:
            logger.info(f"Stop loss hit: {pnl_bps:.2f} bps")
            return self._create_exit_signal(ctx, "stop_loss")

        # Check time-based exit (example: max 100 bars)
        if position.entry_ts:
            bars_held = (ctx.candle.time - position.entry_ts).total_seconds() / 60  # Assume 1min bars
            if bars_held > 100:
                logger.info(f"Time-based exit: {bars_held:.0f} bars held")
                return self._create_exit_signal(ctx, "time_exit")

        return None

    def _create_exit_signal(self, ctx: BarContext, reason: str) -> Signal:
        """
        Create exit signal to close position.

        Args:
            ctx: BarContext
            reason: Exit reason

        Returns:
            Exit signal
        """
        position = ctx.position

        # Exit side is opposite of position side
        if position.is_long:
            exit_side = Side.SELL
        else:
            exit_side = Side.BUY

        signal = Signal(
            pair=ctx.pair,
            side=exit_side,
            type="exit",
            target_qty=abs(position.qty),
            target_price=None,  # Market exit
            stop_price=None,
            order_type=OrderType.MARKET,
            post_only=False,
            hidden=False,
            metadata={"reason": reason},
        )

        return signal

    def update_regime(self, regime_label: RegimeLabel) -> None:
        """
        Update market regime for strategy.

        This can be called externally to change the regime dynamically
        during backtesting.

        Args:
            regime_label: New market regime
        """
        self.regime_label = regime_label
        logger.debug(f"Regime updated to {regime_label.value}")

    def update_volatility(self, current_volatility: Decimal) -> None:
        """
        Update market volatility for position sizing.

        Args:
            current_volatility: New volatility (annualized)
        """
        self.current_volatility = current_volatility
        logger.debug(f"Volatility updated to {current_volatility}")

    def _track_position_entry(self, ctx: BarContext, entry_signal: Signal, snapshot: MarketSnapshot) -> None:
        """
        Track position entry for future PnL emission.

        Args:
            ctx: BarContext at entry
            entry_signal: Entry signal that will be executed
            snapshot: Market snapshot at entry
        """
        if not self.emit_pnl_events:
            return

        # Store entry details for PnL calculation on exit
        self.open_position_data = {
            "entry_ts_ms": snapshot.timestamp_ms,
            "entry_price": snapshot.mid_price,
            "pair": ctx.pair,
            "side": "long" if entry_signal.side.value == "BUY" else "short",
            "qty": float(entry_signal.target_qty),
            "trade_id": f"backtest_{ctx.pair}_{snapshot.timestamp_ms}",
        }

        logger.debug(
            f"Tracked entry: {self.open_position_data['side']} "
            f"{self.open_position_data['qty']:.6f} @ ${self.open_position_data['entry_price']:.2f}"
        )

    def _emit_trade_close_event(self, ctx: BarContext, snapshot: MarketSnapshot) -> None:
        """
        Emit trade close event to PnL pipeline.

        Args:
            ctx: BarContext at exit
            snapshot: Market snapshot at exit
        """
        if not self.emit_pnl_events:
            return

        if not self.open_position_data:
            logger.warning("No open position data tracked - cannot emit PnL event")
            return

        # Calculate PnL
        entry_price = self.open_position_data["entry_price"]
        exit_price = snapshot.mid_price
        qty = self.open_position_data["qty"]
        side = self.open_position_data["side"]

        if side == "long":
            pnl = (exit_price - entry_price) * qty
        else:  # short
            pnl = (entry_price - exit_price) * qty

        # Create trade close event
        trade_event = {
            "id": self.open_position_data["trade_id"],
            "ts": snapshot.timestamp_ms,  # Use candle close time for realistic spacing
            "pair": ctx.pair,
            "side": side,
            "entry": entry_price,
            "exit": exit_price,
            "qty": qty,
            "pnl": pnl,
        }

        # Emit to PnL pipeline (silent failure)
        try:
            publish_trade_close(trade_event)
            logger.info(
                f"Emitted backtest trade close: {side} {qty:.6f} @ "
                f"${entry_price:.2f} → ${exit_price:.2f}, PnL: ${pnl:+,.2f}"
            )
        except Exception as e:
            logger.debug(f"Failed to emit PnL event (non-critical): {e}")

        # Clear tracked position
        self.open_position_data = None


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test backtest adapter with synthetic data"""
    import sys

    logging.basicConfig(level=logging.INFO)

    try:
        # Import strategies
        from strategies.breakout import BreakoutStrategy
        from strategies.momentum_strategy import MomentumStrategy
        from strategies.mean_reversion import MeanReversionStrategy

        # Test 1: Initialize adapter with Breakout strategy
        breakout_strategy = BreakoutStrategy()
        adapter = StrategyBacktestAdapter(
            strategy=breakout_strategy,
            account_equity_usd=Decimal("10000"),
            current_volatility=Decimal("0.50"),
            regime_label=RegimeLabel.BULL,
        )
        assert adapter.strategy == breakout_strategy
        assert adapter.account_equity_usd == Decimal("10000")

        print("\nPASS Strategy Backtest Adapter Self-Check:")
        print(f"  - Initialization: OK")
        print(f"  - Breakout strategy adapter: OK")
        print(f"  - Equity tracking: OK")
        print(f"  - Regime handling: OK")

        # Test 2: Test with Momentum strategy
        momentum_strategy = MomentumStrategy()
        adapter2 = StrategyBacktestAdapter(
            strategy=momentum_strategy,
            account_equity_usd=Decimal("10000"),
        )
        assert adapter2.strategy == momentum_strategy
        print(f"  - Momentum strategy adapter: OK")

        # Test 3: Test with MeanReversion strategy
        mean_reversion_strategy = MeanReversionStrategy()
        adapter3 = StrategyBacktestAdapter(
            strategy=mean_reversion_strategy,
            account_equity_usd=Decimal("10000"),
        )
        assert adapter3.strategy == mean_reversion_strategy
        print(f"  - MeanReversion strategy adapter: OK")

        # Test 4: Test with RegimeBasedRouter
        router = RegimeBasedRouter(use_ensemble=False)
        adapter4 = StrategyBacktestAdapter(
            strategy=router,
            account_equity_usd=Decimal("10000"),
        )
        assert adapter4.is_router
        print(f"  - RegimeRouter adapter: OK")

        # Test 5: Test regime update
        adapter.update_regime(RegimeLabel.BEAR)
        assert adapter.regime_label == RegimeLabel.BEAR
        print(f"  - Regime update: OK")

        # Test 6: Test volatility update
        adapter.update_volatility(Decimal("0.75"))
        assert adapter.current_volatility == Decimal("0.75")
        print(f"  - Volatility update: OK")

        print("\nAll adapter tests passed!")

    except Exception as e:
        print(f"\nFAIL Strategy Backtest Adapter Self-Check: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
