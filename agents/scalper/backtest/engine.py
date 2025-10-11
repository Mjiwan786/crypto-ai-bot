"""
Production-grade backtesting engine for crypto-ai-bot scalping strategies.

This module provides a fast, deterministic backtest engine with comprehensive
walk-forward analysis, risk management, and performance metrics.

Example
-------
from config.loader import get_config
from agents.scalper.backtest.engine import BacktestEngine, ScalperAdapter

cfg = get_config()
engine = BacktestEngine(cfg, seed=cfg.backtest.get('random_seed', 42))
engine.load_ohlcv({'BTC/USD@1m': btc_df})  # user-provided DataFrame
result = engine.run(['BTC/USD'], '1m', strategy_adapter=ScalperAdapter(cfg))
print(result.summary['win_rate'])
"""

from __future__ import annotations

import logging
import random
import statistics
import warnings
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Optional, Protocol

import numpy as np
import pandas as pd

# Suppress pandas warnings for cleaner output
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

logger = logging.getLogger(__name__)

# Type aliases
Timestamp = pd.Timestamp
DataFrame = pd.DataFrame

# =============================================================================
# Enums and Constants
# =============================================================================


class Side(Enum):
    """Order side enumeration."""

    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type enumeration."""

    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(Enum):
    """Time in force enumeration."""

    IOC = "ioc"  # Immediate or Cancel
    GTC = "gtc"  # Good Till Cancelled


# =============================================================================
# Data Entities
# =============================================================================


@dataclass(slots=True, frozen=True)
class Candle:
    """OHLCV candle data point."""

    time: Timestamp
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self):
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError(
                f"Invalid OHLC data at {self.time}: H={self.high}, L={self.low}, O={self.open}, C={self.close}"
            )


@dataclass(slots=True)
class Order:
    """Order representation."""

    id: str
    ts: Timestamp
    pair: str
    side: Side
    type: OrderType
    qty: Decimal
    limit_price: Optional[Decimal] = None
    time_in_force: TimeInForce = TimeInForce.GTC
    post_only: bool = False
    hidden: bool = False
    filled_qty: Decimal = Decimal("0.0")
    status: str = "pending"  # pending, filled, partial, cancelled


@dataclass(slots=True, frozen=True)
class Fill:
    """Order fill representation."""

    order_id: str
    ts: Timestamp
    price: Decimal
    qty: Decimal
    is_maker: bool
    fees: Decimal = Decimal("0.0")


@dataclass(slots=True)
class Position:
    """Position tracking."""

    pair: str
    qty: Decimal = Decimal("0.0")
    avg_price: Decimal = Decimal("0.0")
    unrealized_pnl: Decimal = Decimal("0.0")
    realized_pnl: Decimal = Decimal("0.0")
    entry_ts: Optional[Timestamp] = None
    exit_ts: Optional[Timestamp] = None

    @property
    def is_long(self) -> bool:
        return self.qty > 0

    @property
    def is_short(self) -> bool:
        return self.qty < 0

    @property
    def is_flat(self) -> bool:
        return abs(self.qty) < 1e-8


@dataclass(slots=True, frozen=True)
class Trade:
    """Completed trade record."""

    pair: str
    side: Side
    entry_ts: Timestamp
    entry_price: Decimal
    exit_ts: Timestamp
    exit_price: Decimal
    qty: Decimal
    pnl: Decimal
    pnl_pct: Decimal
    fees: Decimal
    slippage: Decimal
    max_adverse_excursion: Decimal  # MAE
    max_favorable_excursion: Decimal  # MFE
    bars_held: int
    window_id: Optional[int] = None


@dataclass(slots=True, frozen=True)
class EquityPoint:
    """Equity curve data point."""

    ts: Timestamp
    equity: Decimal
    cash: Decimal
    drawdown: Decimal


@dataclass(slots=True, frozen=True)
class Signal:
    """Strategy signal."""

    pair: str
    side: Side
    type: str  # "entry", "exit", "adjust"
    target_qty: Decimal
    target_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    order_type: OrderType = OrderType.MARKET
    post_only: bool = False
    hidden: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class BarContext:
    """Context passed to strategy adapters."""

    candle: Candle
    pair: str
    timeframe: str
    position: Position
    equity: Decimal
    cash: Decimal
    spread_bps: Optional[Decimal] = None
    book_imbalance: Optional[Decimal] = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class BacktestResult:
    """Complete backtest results."""

    equity_curve: list[EquityPoint]
    trades: list[Trade]
    orders: list[Order]
    fills: list[Fill]
    summary: dict[str, Any]
    per_pair: dict[str, dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Protocol Interfaces
# =============================================================================


class StrategyAdapter(Protocol):
    """Strategy adapter interface."""

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        """Process bar and return signals."""
        ...


class SlippageModel(Protocol):
    """Slippage calculation interface."""

    def apply(self, side: Side, price: float, spread_bps: Optional[float]) -> float:
        """Apply slippage to execution price."""
        ...


class FeeModel(Protocol):
    """Fee calculation interface."""

    def cost(self, notional: float, is_maker: bool) -> float:
        """Calculate trading fees."""
        ...


# =============================================================================
# Default Models
# =============================================================================


class SpreadBoundSlippageModel:
    """Default spread-bound slippage model."""

    def __init__(self, base_slippage_bps: float = 2.0, max_slippage_bps: float = 10.0):
        self.base_slippage_bps = base_slippage_bps
        self.max_slippage_bps = max_slippage_bps

    def apply(self, side: Side, price: float, spread_bps: Optional[float]) -> float:
        """Apply slippage based on spread and base slippage."""
        slippage_bps = self.base_slippage_bps

        if spread_bps is not None:
            # Use half spread plus base slippage
            slippage_bps = min(spread_bps / 2 + self.base_slippage_bps, self.max_slippage_bps)

        slippage_factor = slippage_bps / 10000

        if side == Side.BUY:
            return price * (1 + slippage_factor)
        else:
            return price * (1 - slippage_factor)


class KrakenFeeModel:
    """Kraken fee structure."""

    def __init__(self, maker_fee: float = 0.0016, taker_fee: float = 0.0026):
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee

    def cost(self, notional: float, is_maker: bool) -> float:
        """Calculate fees based on maker/taker status."""
        fee_rate = self.maker_fee if is_maker else self.taker_fee
        return notional * fee_rate


# =============================================================================
# Utility Functions
# =============================================================================


def bps_to_price(base_price: float, bps: float) -> float:
    """
    Convert basis points to price offset.

    Args:
        base_price: Base price to apply offset to
        bps: Basis points offset (e.g., 100 = 1%)

    Returns:
        Price with basis points offset applied
    """
    return base_price * (bps / 10000)


def price_to_bps(base_price: float, target_price: float) -> float:
    """
    Convert price difference to basis points.

    Args:
        base_price: Base price for comparison
        target_price: Target price to compare against

    Returns:
        Price difference in basis points
    """
    return ((target_price - base_price) / base_price) * 10000


def timeframe_to_seconds(timeframe: str) -> int:
    """
    Convert timeframe string to seconds.

    Args:
        timeframe: Timeframe string (e.g., '1m', '5h', '1d')

    Returns:
        Timeframe in seconds

    Raises:
        ValueError: If timeframe format is not recognized
    """
    if timeframe.endswith("s"):
        return int(timeframe[:-1])
    elif timeframe.endswith("m"):
        return int(timeframe[:-1]) * 60
    elif timeframe.endswith("h"):
        return int(timeframe[:-1]) * 3600
    elif timeframe.endswith("d"):
        return int(timeframe[:-1]) * 86400
    else:
        raise ValueError(f"Unknown timeframe format: {timeframe}")


def intrabar_fillable(order: Order, candle: Candle) -> tuple[bool, float]:
    """Check if order can be filled within the bar and at what price."""
    if order.type == OrderType.MARKET:
        # Market orders execute at close price (simplified)
        return True, candle.close

    elif order.type == OrderType.LIMIT:
        if order.side == Side.BUY:
            # Buy limit fills if price touched the limit or below
            if candle.low <= order.limit_price:
                # If post-only, check if we would have crossed the spread
                if order.post_only and candle.open < order.limit_price:
                    return False, 0.0  # Would have been a taker order
                return True, min(order.limit_price, candle.high)
        else:  # SELL
            # Sell limit fills if price touched the limit or above
            if candle.high >= order.limit_price:
                # If post-only, check if we would have crossed the spread
                if order.post_only and candle.open > order.limit_price:
                    return False, 0.0  # Would have been a taker order
                return True, max(order.limit_price, candle.low)

    return False, 0.0


def calculate_sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0) -> float:
    """Calculate Sharpe ratio from returns."""
    if not returns or len(returns) < 2:
        return 0.0

    excess_returns = [r - risk_free_rate for r in returns]
    mean_return = statistics.mean(excess_returns)

    if len(excess_returns) < 2:
        return 0.0

    std_return = statistics.stdev(excess_returns)

    if std_return == 0:
        return 0.0

    return mean_return / std_return


# =============================================================================
# Built-in Strategy Adapter
# =============================================================================


class ScalperAdapter:
    """Built-in scalper strategy adapter."""

    def __init__(self, config):
        """Initialize with scalper configuration."""
        self.config = config
        self.scalp_config = getattr(config.strategies, "scalp", None)

        if not self.scalp_config:
            raise ValueError("Scalp strategy configuration not found")

        # Extract scalper parameters
        self.timeframe = getattr(self.scalp_config, "timeframe", "15s")
        self.target_bps = getattr(self.scalp_config, "target_bps", 10)
        self.stop_loss_bps = getattr(self.scalp_config, "stop_loss_bps", 5)
        self.max_hold_seconds = getattr(self.scalp_config, "max_hold_seconds", 120)
        self.max_spread_bps = getattr(self.scalp_config, "max_spread_bps", 3)
        self.post_only = getattr(self.scalp_config, "post_only", True)
        self.hidden_orders = getattr(self.scalp_config, "hidden_orders", True)

        # Convert max hold time to bars
        timeframe_seconds = timeframe_to_seconds(self.timeframe)
        self.max_hold_bars = max(1, self.max_hold_seconds // timeframe_seconds)

        # Position sizing
        self.base_position_size = config.trading.position_sizing.get("base_position_size", 0.03)

        # Track entry timestamps
        self.entry_timestamps: dict[str, Timestamp] = {}

        logger.info(
            f"ScalperAdapter initialized: target={self.target_bps}bps, "
            f"stop={self.stop_loss_bps}bps, max_hold={self.max_hold_bars}bars"
        )

    def on_bar(self, ctx: BarContext) -> list[Signal]:
        """Generate scalping signals."""
        signals = []

        # Check for exit conditions first
        if not ctx.position.is_flat:
            exit_signal = self._check_exit_conditions(ctx)
            if exit_signal:
                signals.append(exit_signal)
                return signals

        # Check for entry conditions
        if ctx.position.is_flat:
            entry_signal = self._check_entry_conditions(ctx)
            if entry_signal:
                signals.append(entry_signal)

        return signals

    def _check_exit_conditions(self, ctx: BarContext) -> Optional[Signal]:
        """Check if position should be exited."""
        if ctx.position.is_flat:
            return None

        current_price = ctx.candle.close
        entry_price = ctx.position.avg_price

        # Calculate P&L in basis points
        if ctx.position.is_long:
            pnl_bps = price_to_bps(entry_price, current_price)
        else:
            pnl_bps = price_to_bps(entry_price, current_price) * -1

        # Check profit target
        if pnl_bps >= self.target_bps:
            return Signal(
                pair=ctx.pair,
                side=Side.SELL if ctx.position.is_long else Side.BUY,
                type="exit",
                target_qty=abs(ctx.position.qty),
                order_type=OrderType.MARKET,
                metadata={"reason": "profit_target", "pnl_bps": pnl_bps},
            )

        # Check stop loss
        if pnl_bps <= -self.stop_loss_bps:
            return Signal(
                pair=ctx.pair,
                side=Side.SELL if ctx.position.is_long else Side.BUY,
                type="exit",
                target_qty=abs(ctx.position.qty),
                order_type=OrderType.MARKET,
                metadata={"reason": "stop_loss", "pnl_bps": pnl_bps},
            )

        # Check max hold time
        if ctx.position.entry_ts:
            bars_held = self._calculate_bars_held(ctx.position.entry_ts, ctx.candle.time)
            if bars_held >= self.max_hold_bars:
                return Signal(
                    pair=ctx.pair,
                    side=Side.SELL if ctx.position.is_long else Side.BUY,
                    type="exit",
                    target_qty=abs(ctx.position.qty),
                    order_type=OrderType.MARKET,
                    metadata={"reason": "max_hold", "bars_held": bars_held},
                )

        return None

    def _check_entry_conditions(self, ctx: BarContext) -> Optional[Signal]:
        """Check for entry opportunities."""
        # Check spread constraint
        if ctx.spread_bps and ctx.spread_bps > self.max_spread_bps:
            return None

        # Simple momentum-based entry logic
        # This is a simplified example - real implementation would be more sophisticated
        candle = ctx.candle

        # Check for strong intrabar momentum
        range_pct = (candle.high - candle.low) / candle.close
        close_position = (
            (candle.close - candle.low) / (candle.high - candle.low)
            if candle.high > candle.low
            else 0.5
        )

        # Minimum volatility filter
        if range_pct < 0.0005:  # 5 bps minimum range
            return None

        # Calculate position size
        position_value = ctx.equity * self.base_position_size
        target_qty = position_value / candle.close

        # Long signal: close near high with decent volume
        if close_position > 0.7 and candle.volume > 0:
            return Signal(
                pair=ctx.pair,
                side=Side.BUY,
                type="entry",
                target_qty=target_qty,
                order_type=OrderType.LIMIT if self.post_only else OrderType.MARKET,
                target_price=(
                    candle.close * 0.9999 if self.post_only else None
                ),  # Slightly below market
                post_only=self.post_only,
                hidden=self.hidden_orders,
                metadata={"close_position": close_position, "range_pct": range_pct},
            )

        # Short signal: close near low with decent volume
        elif close_position < 0.3 and candle.volume > 0:
            return Signal(
                pair=ctx.pair,
                side=Side.SELL,
                type="entry",
                target_qty=target_qty,
                order_type=OrderType.LIMIT if self.post_only else OrderType.MARKET,
                target_price=(
                    candle.close * 1.0001 if self.post_only else None
                ),  # Slightly above market
                post_only=self.post_only,
                hidden=self.hidden_orders,
                metadata={"close_position": close_position, "range_pct": range_pct},
            )

        return None

    def _calculate_bars_held(self, entry_ts: Timestamp, current_ts: Timestamp) -> int:
        """Calculate number of bars held."""
        time_diff = (current_ts - entry_ts).total_seconds()
        timeframe_seconds = timeframe_to_seconds(self.timeframe)
        return int(time_diff // timeframe_seconds)


# =============================================================================
# Main Backtest Engine
# =============================================================================


class BacktestEngine:
    """Production-grade backtesting engine."""

    def __init__(self, config, seed: Optional[int] = None):
        """Initialize backtest engine with configuration."""
        # Import here to avoid circular dependency
        try:
            from config.loader import CryptoAIBotConfig

            if not isinstance(config, CryptoAIBotConfig):
                raise TypeError("config must be CryptoAIBotConfig instance")
        except ImportError:
            # Fallback for testing
            logger.warning("Could not import CryptoAIBotConfig, assuming valid config")

        self.config = config

        # Set random seed for determinism
        self.seed = seed or getattr(config.backtest, "random_seed", 42)
        random.seed(self.seed)
        np.random.seed(self.seed)

        # Extract configuration
        self._load_config()

        # Models
        self.slippage_model: SlippageModel = SpreadBoundSlippageModel(
            base_slippage_bps=self.slippage_bps, max_slippage_bps=self.slippage_bps * 2
        )
        self.fee_model: FeeModel = KrakenFeeModel(
            maker_fee=self.maker_fee, taker_fee=self.taker_fee
        )

        # Data storage
        self.ohlcv_data: dict[str, DataFrame] = {}

        # State tracking
        self._reset_state()

        logger.info(f"BacktestEngine initialized with seed={self.seed}")

    def _load_config(self):
        """Load and validate configuration parameters."""
        # Backtest config
        backtest_config = getattr(self.config, "backtest", {})

        self.slippage_bps = float(backtest_config.get("slippage", 0.0005)) * 10000  # Convert to bps
        self.partial_fill_prob = float(backtest_config.get("partial_fill_probability", 0.3))
        self.partial_fill_min_pct = float(backtest_config.get("partial_fill_min_pct", 0.65))

        # Walk-forward config
        wf_config = backtest_config.get("walk_forward", {})
        self.wf_enabled = wf_config.get("enabled", True)
        self.wf_warmup_days = int(wf_config.get("warmup_days", 14))
        self.wf_test_days = int(wf_config.get("test_days", 7))
        self.wf_roll_bars = int(wf_config.get("roll_bars", 24))

        # Fee structure
        fee_config = backtest_config.get("fee_structure", {})
        self.maker_fee = float(fee_config.get("kraken", 0.0016))  # Fallback to Kraken maker
        self.taker_fee = float(
            getattr(self.config.exchanges.get("kraken", {}), "fee_taker", 0.0026)
        )

        # Risk config
        risk_config = self.config.risk
        self.global_max_drawdown = float(risk_config.global_max_drawdown)
        self.daily_stop_loss = float(risk_config.daily_stop_loss)
        self.max_concurrent_positions = int(risk_config.max_concurrent_positions)
        self.per_symbol_max_exposure = float(risk_config.per_symbol_max_exposure)

        # Circuit breakers
        cb_config = risk_config.circuit_breakers
        self.max_spread_bps = float(cb_config.get("spread_bps_max", 12))

        # Trading config
        trading_config = self.config.trading
        self.base_position_size = float(trading_config.position_sizing["base_position_size"])

        # Data config
        data_config = self.config.data
        self.warmup_bars = int(data_config.warmup_bars)

    def _reset_state(self):
        """Reset internal state for new backtest."""
        self.starting_cash = 100000.0  # Default starting capital
        self.cash = self.starting_cash
        self.equity = self.starting_cash
        self.peak_equity = self.starting_cash

        # Position tracking
        self.positions: dict[str, Position] = {}
        self.orders: list[Order] = []
        self.fills: list[Fill] = []
        self.trades: list[Trade] = []
        self.equity_curve: list[EquityPoint] = []

        # Order management
        self.next_order_id = 1
        self.pending_orders: list[Order] = []

        # Daily tracking
        self.daily_pnl = 0.0
        self.current_date = None
        self.session_start_equity = self.starting_cash

        # Risk tracking
        self.max_drawdown = 0.0
        self.consecutive_losses = 0

        # Walk-forward tracking
        self.current_window = 0

        logger.debug("Engine state reset")

    def load_ohlcv(
        self,
        data: Optional[dict[str, DataFrame]] = None,
        *,
        loader: Optional[Callable] = None,
    ) -> None:
        """Load OHLCV data for backtesting."""
        if data is not None:
            self.ohlcv_data = data.copy()
        elif loader is not None:
            self.ohlcv_data = loader()
        else:
            raise ValueError("Either data or loader must be provided")

        # Validate data
        for key, df in self.ohlcv_data.items():
            if not isinstance(df.index, pd.DatetimeIndex):
                raise ValueError(f"Data {key} must have DatetimeIndex")

            required_cols = ["open", "high", "low", "close", "volume"]
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                raise ValueError(f"Data {key} missing columns: {missing_cols}")

            # Check for timezone awareness
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
                logger.warning(f"Data {key} was timezone-naive, assuming UTC")

            # Validate no NaN values in critical columns
            for col in required_cols:
                if df[col].isna().any():
                    raise ValueError(f"Data {key} contains NaN values in column {col}")

            # Check minimum data length
            if len(df) < self.warmup_bars:
                raise ValueError(
                    f"Data {key} has only {len(df)} bars, need at least {self.warmup_bars}"
                )

            logger.info(f"Loaded {len(df)} bars for {key} from {df.index[0]} to {df.index[-1]}")

    def set_slippage_model(self, model: SlippageModel) -> None:
        """Set custom slippage model."""
        self.slippage_model = model
        logger.info(f"Slippage model set to {type(model).__name__}")

    def set_fee_model(self, model: FeeModel) -> None:
        """Set custom fee model."""
        self.fee_model = model
        logger.info(f"Fee model set to {type(model).__name__}")

    def run(
        self,
        pairs: list[str],
        timeframe: str,
        strategy_adapter: StrategyAdapter,
        *,
        walk_forward: Optional[bool] = None,
    ) -> BacktestResult:
        """Run backtest simulation."""
        if walk_forward is None:
            walk_forward = self.wf_enabled

        if walk_forward:
            return self._run_walk_forward(pairs, timeframe, strategy_adapter)
        else:
            return self._run_single(pairs, timeframe, strategy_adapter)

    def _run_single(
        self,
        pairs: list[str],
        timeframe: str,
        strategy_adapter: StrategyAdapter,
    ) -> BacktestResult:
        """Run single backtest period."""
        logger.info(f"Starting single backtest for {pairs} on {timeframe}")

        self._reset_state()

        # Get combined data
        combined_data = self._prepare_combined_data(pairs, timeframe)

        if combined_data.empty:
            raise ValueError("No data available for specified pairs and timeframe")

        # Skip warmup period
        start_idx = self.warmup_bars
        trading_data = combined_data.iloc[start_idx:]

        logger.info(
            f"Trading from {trading_data.index[0]} to {trading_data.index[-1]} "
            f"({len(trading_data)} bars)"
        )

        # Process each bar
        for idx, (timestamp, row) in enumerate(trading_data.iterrows()):
            self._process_bar(timestamp, row, pairs, timeframe, strategy_adapter)

            # Update equity curve
            self._update_equity_curve(timestamp)

            # Check circuit breakers
            if self._check_circuit_breakers():
                logger.warning(f"Circuit breaker triggered at {timestamp}")
                break

        # Close all positions at end
        self._close_all_positions(trading_data.index[-1])

        return self._build_result()

    def _run_walk_forward(
        self,
        pairs: list[str],
        timeframe: str,
        strategy_adapter: StrategyAdapter,
    ) -> BacktestResult:
        """Run walk-forward analysis."""
        logger.info(f"Starting walk-forward analysis for {pairs} on {timeframe}")

        # Get combined data
        combined_data = self._prepare_combined_data(pairs, timeframe)

        if combined_data.empty:
            raise ValueError("No data available for specified pairs and timeframe")

        # Calculate window parameters
        warmup_bars = self.wf_warmup_days * (86400 // timeframe_to_seconds(timeframe))
        test_bars = self.wf_test_days * (86400 // timeframe_to_seconds(timeframe))
        total_window_bars = warmup_bars + test_bars

        all_results = []
        window_id = 0

        start_idx = 0
        while start_idx + total_window_bars <= len(combined_data):
            end_idx = start_idx + total_window_bars
            window_data = combined_data.iloc[start_idx:end_idx]

            logger.info(f"Window {window_id}: {window_data.index[0]} to {window_data.index[-1]}")

            # Reset state for this window
            self._reset_state()
            self.current_window = window_id

            # Skip warmup, trade on test period
            trading_data = window_data.iloc[warmup_bars:]

            # Process each bar in this window
            for timestamp, row in trading_data.iterrows():
                self._process_bar(timestamp, row, pairs, timeframe, strategy_adapter)
                self._update_equity_curve(timestamp)

                if self._check_circuit_breakers():
                    break

            # Close positions at end of window
            self._close_all_positions(trading_data.index[-1])

            # Store window results
            window_result = self._build_result()
            window_result.metadata["window_id"] = window_id
            all_results.append(window_result)

            # Advance window
            start_idx += self.wf_roll_bars
            window_id += 1

        # Combine all window results
        return self._combine_walk_forward_results(all_results)

    def _prepare_combined_data(self, pairs: list[str], timeframe: str) -> DataFrame:
        """Prepare combined OHLCV data for all pairs."""
        data_frames = []

        for pair in pairs:
            key = f"{pair}@{timeframe}"
            if key not in self.ohlcv_data:
                raise ValueError(f"No data found for {key}")

            df = self.ohlcv_data[key].copy()

            # Add pair column for identification
            for col in ["open", "high", "low", "close", "volume"]:
                df[f"{pair}_{col}"] = df[col]

            # Keep only the pair-specific columns
            pair_cols = [f"{pair}_{col}" for col in ["open", "high", "low", "close", "volume"]]
            df = df[pair_cols]

            data_frames.append(df)

        if not data_frames:
            return DataFrame()

        # Combine all pairs on common time index
        combined = pd.concat(data_frames, axis=1, join="inner")
        combined = combined.sort_index()

        # Forward fill small gaps (max 2 periods)
        combined = combined.fillna(method="ffill", limit=2)

        # Drop any remaining NaN rows
        combined = combined.dropna()

        logger.info(f"Combined data: {len(combined)} bars across {len(pairs)} pairs")
        return combined

    def _process_bar(
        self,
        timestamp: Timestamp,
        row: pd.Series,
        pairs: list[str],
        timeframe: str,
        strategy_adapter: StrategyAdapter,
    ) -> None:
        """Process a single bar across all pairs."""
        # Check for new trading day
        self._check_new_trading_day(timestamp)

        # Process each pair
        for pair in pairs:
            candle = self._extract_candle(timestamp, row, pair)

            if candle is None:
                continue

            # Get or create position
            position = self.positions.get(pair, Position(pair=pair))
            self.positions[pair] = position

            # Update position mark-to-market
            self._update_position_mtm(position, candle.close)

            # Create bar context
            ctx = BarContext(
                candle=candle,
                pair=pair,
                timeframe=timeframe,
                position=position,
                equity=self.equity,
                cash=self.cash,
                spread_bps=self._estimate_spread_bps(candle),
                metadata={"timestamp": timestamp},
            )

            # Get signals from strategy
            signals = strategy_adapter.on_bar(ctx)

            # Process signals
            for signal in signals:
                self._process_signal(signal, candle, timestamp)

        # Process pending orders
        self._process_pending_orders(timestamp, row, pairs)

        # Update equity
        self._update_equity()

    def _extract_candle(self, timestamp: Timestamp, row: pd.Series, pair: str) -> Optional[Candle]:
        """Extract candle data for a specific pair."""
        try:
            return Candle(
                time=timestamp,
                open=row[f"{pair}_open"],
                high=row[f"{pair}_high"],
                low=row[f"{pair}_low"],
                close=row[f"{pair}_close"],
                volume=row[f"{pair}_volume"],
            )
        except KeyError:
            logger.warning(f"Missing data for {pair} at {timestamp}")
            return None
        except Exception as e:
            logger.error(f"Error extracting candle for {pair} at {timestamp}: {e}")
            return None

    def _estimate_spread_bps(self, candle: Candle) -> Optional[float]:
        """Estimate spread in basis points from candle data."""
        # Simple heuristic: spread ~= 0.1% of the range
        if candle.high > candle.low:
            range_pct = (candle.high - candle.low) / candle.close
            estimated_spread_pct = min(range_pct * 0.1, 0.001)  # Cap at 10 bps
            return estimated_spread_pct * 10000  # Convert to bps
        return None

    def _process_signal(self, signal: Signal, candle: Candle, timestamp: Timestamp) -> None:
        """Process a strategy signal."""
        if signal.type == "entry":
            self._handle_entry_signal(signal, candle, timestamp)
        elif signal.type == "exit":
            self._handle_exit_signal(signal, candle, timestamp)
        elif signal.type == "adjust":
            self._handle_adjust_signal(signal, candle, timestamp)

    def _handle_entry_signal(self, signal: Signal, candle: Candle, timestamp: Timestamp) -> None:
        """Handle entry signal."""
        # Check risk limits
        if not self._check_entry_risk_limits(signal):
            logger.debug(f"Entry signal blocked by risk limits: {signal.pair} {signal.side}")
            return

        # Create order
        order = Order(
            id=f"order_{self.next_order_id}",
            ts=timestamp,
            pair=signal.pair,
            side=signal.side,
            type=signal.order_type,
            qty=signal.target_qty,
            limit_price=signal.target_price,
            post_only=signal.post_only,
            hidden=signal.hidden,
            time_in_force=(
                TimeInForce.GTC if signal.order_type == OrderType.LIMIT else TimeInForce.IOC
            ),
        )

        self.next_order_id += 1
        self.orders.append(order)
        self.pending_orders.append(order)

        logger.debug(
            f"Created entry order: {order.id} {order.side.value} {order.qty:.6f} {order.pair}"
        )

    def _handle_exit_signal(self, signal: Signal, candle: Candle, timestamp: Timestamp) -> None:
        """Handle exit signal."""
        position = self.positions.get(signal.pair)
        if not position or position.is_flat:
            logger.debug(f"Exit signal ignored - no position in {signal.pair}")
            return

        # Determine exit quantity
        exit_qty = min(signal.target_qty, abs(position.qty))

        # Create exit order
        order = Order(
            id=f"order_{self.next_order_id}",
            ts=timestamp,
            pair=signal.pair,
            side=signal.side,
            type=signal.order_type,
            qty=exit_qty,
            limit_price=signal.target_price,
            post_only=signal.post_only,
            hidden=signal.hidden,
            time_in_force=TimeInForce.IOC,  # Exit orders should be immediate
        )

        self.next_order_id += 1
        self.orders.append(order)
        self.pending_orders.append(order)

        logger.debug(
            f"Created exit order: {order.id} {order.side.value} {order.qty:.6f} {order.pair}"
        )

    def _handle_adjust_signal(self, signal: Signal, candle: Candle, timestamp: Timestamp) -> None:
        """Handle position adjustment signal."""
        # Implementation for position adjustments
        logger.debug(f"Position adjustment not implemented: {signal.pair}")

    def _check_entry_risk_limits(self, signal: Signal) -> bool:
        """Check if entry signal passes risk limits."""
        # Check max concurrent positions
        active_positions = sum(1 for pos in self.positions.values() if not pos.is_flat)
        if active_positions >= self.max_concurrent_positions:
            return False

        # Check per-symbol exposure
        signal_notional = signal.target_qty * signal.target_price if signal.target_price else 0
        if signal_notional > self.equity * self.per_symbol_max_exposure:
            return False

        # Check daily stop loss
        if self.daily_pnl <= self.daily_stop_loss * self.session_start_equity:
            return False

        # Check global drawdown
        current_drawdown = (self.equity - self.peak_equity) / self.peak_equity
        if current_drawdown <= self.global_max_drawdown:
            return False

        return True

    def _process_pending_orders(
        self, timestamp: Timestamp, row: pd.Series, pairs: list[str]
    ) -> None:
        """Process all pending orders."""
        filled_orders = []

        for order in self.pending_orders[:]:  # Copy list to avoid modification during iteration
            candle = self._extract_candle(timestamp, row, order.pair)
            if candle is None:
                continue

            # Check if order can be filled
            can_fill, fill_price = intrabar_fillable(order, candle)

            if can_fill:
                # Apply partial fill probability
                if random.random() < self.partial_fill_prob:
                    # Partial fill
                    fill_ratio = self.partial_fill_min_pct + random.random() * (
                        1 - self.partial_fill_min_pct
                    )
                    fill_qty = order.qty * fill_ratio
                    order.filled_qty += fill_qty

                    if order.filled_qty >= order.qty * 0.99:  # Consider fully filled if > 99%
                        order.status = "filled"
                        filled_orders.append(order)
                    else:
                        order.status = "partial"
                else:
                    # Full fill
                    fill_qty = order.qty - order.filled_qty
                    order.filled_qty = order.qty
                    order.status = "filled"
                    filled_orders.append(order)

                # Apply slippage
                final_price = self.slippage_model.apply(
                    order.side, fill_price, self._estimate_spread_bps(candle)
                )

                # Determine if maker or taker
                is_maker = order.post_only or (
                    order.type == OrderType.LIMIT and order.limit_price != candle.close
                )

                # Calculate fees
                notional = fill_qty * final_price
                fees = self.fee_model.cost(notional, is_maker)

                # Create fill
                fill = Fill(
                    order_id=order.id,
                    ts=timestamp,
                    price=final_price,
                    qty=fill_qty,
                    is_maker=is_maker,
                    fees=fees,
                )

                self.fills.append(fill)

                # Update position
                self._update_position_from_fill(fill)

                logger.debug(
                    f"Filled order {order.id}: {fill_qty:.6f} @ {final_price:.2f} "
                    f"(fees: {fees:.2f})"
                )

        # Remove filled orders from pending
        for order in filled_orders:
            if order in self.pending_orders:
                self.pending_orders.remove(order)

    def _update_position_from_fill(self, fill: Fill) -> None:
        """Update position from order fill."""
        order = next(o for o in self.orders if o.id == fill.order_id)
        position = self.positions.get(order.pair, Position(pair=order.pair))

        # Calculate position change
        if order.side == Side.BUY:
            qty_change = fill.qty
        else:
            qty_change = -fill.qty

        # Update position
        if position.is_flat:
            # New position
            position.qty = qty_change
            position.avg_price = fill.price
            position.entry_ts = fill.ts
            position.exit_ts = None
        else:
            # Existing position
            if (position.qty > 0 and qty_change > 0) or (position.qty < 0 and qty_change < 0):
                # Adding to position
                total_value = position.qty * position.avg_price + qty_change * fill.price
                position.qty += qty_change
                position.avg_price = total_value / position.qty if position.qty != 0 else 0
            else:
                # Reducing or closing position
                if abs(qty_change) >= abs(position.qty):
                    # Closing position completely
                    realized_pnl = self._calculate_realized_pnl(
                        position, fill.price, abs(position.qty)
                    )
                    position.realized_pnl += realized_pnl

                    # Create trade record
                    self._create_trade_record(position, fill)

                    # Reset position or flip
                    remaining_qty = qty_change + position.qty
                    if abs(remaining_qty) < 1e-8:
                        position.qty = 0
                        position.avg_price = 0
                        position.exit_ts = fill.ts
                    else:
                        # Position flipped
                        position.qty = remaining_qty
                        position.avg_price = fill.price
                        position.entry_ts = fill.ts
                        position.exit_ts = None
                else:
                    # Partial close
                    close_qty = abs(qty_change)
                    realized_pnl = self._calculate_realized_pnl(position, fill.price, close_qty)
                    position.realized_pnl += realized_pnl
                    position.qty += qty_change

        # Update cash
        cash_change = -qty_change * fill.price - fill.fees
        self.cash += cash_change

        self.positions[order.pair] = position

    def _calculate_realized_pnl(self, position: Position, exit_price: float, qty: float) -> float:
        """Calculate realized P&L for position close."""
        if position.is_long:
            return (exit_price - position.avg_price) * qty
        else:
            return (position.avg_price - exit_price) * qty

    def _create_trade_record(self, position: Position, exit_fill: Fill) -> None:
        """Create a trade record for completed position."""
        if position.entry_ts is None:
            return

        # Calculate trade metrics
        if position.is_long:
            pnl = (exit_fill.price - position.avg_price) * abs(position.qty)
            side = Side.BUY
        else:
            pnl = (position.avg_price - exit_fill.price) * abs(position.qty)
            side = Side.SELL

        pnl_pct = pnl / (position.avg_price * abs(position.qty)) if position.avg_price > 0 else 0

        # Calculate fees (simplified - would need to track entry fees too)
        total_fees = exit_fill.fees  # + entry_fees

        # Calculate bars held
        time_held = (exit_fill.ts - position.entry_ts).total_seconds()
        bars_held = max(1, int(time_held / 60))  # Assume 1-minute bars

        # Placeholder for MAE/MFE (would need tick-by-tick data)
        mae = 0.0
        mfe = pnl

        trade = Trade(
            pair=position.pair,
            side=side,
            entry_ts=position.entry_ts,
            entry_price=position.avg_price,
            exit_ts=exit_fill.ts,
            exit_price=exit_fill.price,
            qty=abs(position.qty),
            pnl=pnl,
            pnl_pct=pnl_pct,
            fees=total_fees,
            slippage=0.0,  # Would need more detailed tracking
            max_adverse_excursion=mae,
            max_favorable_excursion=mfe,
            bars_held=bars_held,
            window_id=self.current_window,
        )

        self.trades.append(trade)

        # Update consecutive losses tracking
        if pnl > 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1

    def _update_position_mtm(self, position: Position, current_price: float) -> None:
        """Update position mark-to-market."""
        if position.is_flat:
            position.unrealized_pnl = 0.0
            return

        if position.is_long:
            position.unrealized_pnl = (current_price - position.avg_price) * position.qty
        else:
            position.unrealized_pnl = (position.avg_price - current_price) * abs(position.qty)

    def _update_equity(self) -> None:
        """Update total equity including unrealized P&L."""
        unrealized_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())
        self.equity = self.cash + unrealized_pnl

        # Update peak equity
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

        # Update max drawdown
        current_drawdown = (self.equity - self.peak_equity) / self.peak_equity
        if current_drawdown < self.max_drawdown:
            self.max_drawdown = current_drawdown

    def _update_equity_curve(self, timestamp: Timestamp) -> None:
        """Add point to equity curve."""
        current_drawdown = (self.equity - self.peak_equity) / self.peak_equity

        point = EquityPoint(
            ts=timestamp, equity=self.equity, cash=self.cash, drawdown=current_drawdown
        )

        self.equity_curve.append(point)

    def _check_new_trading_day(self, timestamp: Timestamp) -> None:
        """Check if we're starting a new trading day."""
        current_date = timestamp.date()

        if self.current_date is None:
            self.current_date = current_date
            self.session_start_equity = self.equity
            self.daily_pnl = 0.0
        elif current_date != self.current_date:
            # New day
            self.current_date = current_date
            self.session_start_equity = self.equity
            self.daily_pnl = 0.0
        else:
            # Same day - update daily P&L
            self.daily_pnl = self.equity - self.session_start_equity

    def _check_circuit_breakers(self) -> bool:
        """Check if any circuit breakers should trigger."""
        # Check global drawdown
        current_drawdown = (self.equity - self.peak_equity) / self.peak_equity
        if current_drawdown <= self.global_max_drawdown:
            logger.warning(f"Global drawdown circuit breaker triggered: {current_drawdown:.2%}")
            return True

        # Check daily stop loss
        if self.daily_pnl <= self.daily_stop_loss * self.session_start_equity:
            logger.warning(f"Daily stop loss triggered: {self.daily_pnl:.2f}")
            return True

        return False

    def _close_all_positions(self, timestamp: Timestamp) -> None:
        """Close all open positions at the end of backtest."""
        for pair, position in self.positions.items():
            if not position.is_flat:
                # Create market exit order

                # Simulate immediate fill at last known price
                # This is simplified - in reality would need the last candle
                if self.equity_curve:
                    last_price = position.avg_price  # Fallback

                    # Calculate final P&L
                    if position.is_long:
                        final_pnl = (last_price - position.avg_price) * position.qty
                    else:
                        final_pnl = (position.avg_price - last_price) * abs(position.qty)

                    position.realized_pnl += final_pnl
                    position.exit_ts = timestamp

                    # Create final trade record
                    if position.entry_ts:
                        self._create_final_trade_record(position, last_price, timestamp)

                    # Update cash
                    self.cash += position.qty * last_price
                    position.qty = 0

    def _create_final_trade_record(
        self, position: Position, exit_price: float, exit_ts: Timestamp
    ) -> None:
        """Create trade record for forced position close."""
        if position.is_long:
            pnl = (exit_price - position.avg_price) * abs(position.qty)
            side = Side.BUY
        else:
            pnl = (position.avg_price - exit_price) * abs(position.qty)
            side = Side.SELL

        pnl_pct = pnl / (position.avg_price * abs(position.qty)) if position.avg_price > 0 else 0

        time_held = (exit_ts - position.entry_ts).total_seconds() if position.entry_ts else 0
        bars_held = max(1, int(time_held / 60))

        trade = Trade(
            pair=position.pair,
            side=side,
            entry_ts=position.entry_ts or exit_ts,
            entry_price=position.avg_price,
            exit_ts=exit_ts,
            exit_price=exit_price,
            qty=abs(position.qty),
            pnl=pnl,
            pnl_pct=pnl_pct,
            fees=0.0,  # Simplified
            slippage=0.0,
            max_adverse_excursion=0.0,
            max_favorable_excursion=pnl if pnl > 0 else 0.0,
            bars_held=bars_held,
            window_id=self.current_window,
        )

        self.trades.append(trade)

    def _build_result(self) -> BacktestResult:
        """Build final backtest result."""
        # Calculate summary statistics
        summary = self._calculate_summary_stats()

        # Calculate per-pair statistics
        per_pair = self._calculate_per_pair_stats()

        return BacktestResult(
            equity_curve=self.equity_curve,
            trades=self.trades,
            orders=self.orders,
            fills=self.fills,
            summary=summary,
            per_pair=per_pair,
            metadata={
                "seed": self.seed,
                "starting_cash": self.starting_cash,
                "final_equity": self.equity,
                "total_bars": len(self.equity_curve),
            },
        )

    def _calculate_summary_stats(self) -> dict[str, Any]:
        """Calculate comprehensive summary statistics."""
        if not self.trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_pnl": 0.0,
                "total_return": 0.0,
                "cagr": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": self.max_drawdown,
                "avg_trade_duration": 0.0,
                "total_fees": 0.0,
            }

        # Basic trade statistics
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]

        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0

        # P&L statistics
        total_pnl = sum(t.pnl for t in self.trades)
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = sum(abs(t.pnl) for t in losing_trades)

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Return calculations
        total_return = (self.equity - self.starting_cash) / self.starting_cash

        # Calculate CAGR
        if self.equity_curve and len(self.equity_curve) > 1:
            start_ts = self.equity_curve[0].ts
            end_ts = self.equity_curve[-1].ts
            years = (end_ts - start_ts).total_seconds() / (365.25 * 24 * 3600)
            if years > 0:
                cagr = (self.equity / self.starting_cash) ** (1 / years) - 1
            else:
                cagr = 0.0
        else:
            cagr = 0.0

        # Calculate Sharpe ratio from daily returns
        daily_returns = self._calculate_daily_returns()
        sharpe_ratio = calculate_sharpe_ratio(daily_returns)

        # Average trade duration
        avg_duration = statistics.mean(t.bars_held for t in self.trades) if self.trades else 0

        # Total fees
        total_fees = sum(f.fees for f in self.fills)

        # MAE/MFE statistics
        avg_mae = (
            statistics.mean(t.max_adverse_excursion for t in self.trades) if self.trades else 0
        )
        avg_mfe = (
            statistics.mean(t.max_favorable_excursion for t in self.trades) if self.trades else 0
        )

        return {
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "avg_win": statistics.mean([t.pnl for t in winning_trades]) if winning_trades else 0,
            "avg_loss": statistics.mean([t.pnl for t in losing_trades]) if losing_trades else 0,
            "total_return": total_return,
            "cagr": cagr,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "avg_trade_duration": avg_duration,
            "avg_mae": avg_mae,
            "avg_mfe": avg_mfe,
            "total_fees": total_fees,
            "total_slippage": sum(t.slippage for t in self.trades),
            "consecutive_losses": self.consecutive_losses,
            "final_equity": self.equity,
            "starting_cash": self.starting_cash,
        }

    def _calculate_per_pair_stats(self) -> dict[str, dict[str, Any]]:
        """Calculate per-pair performance statistics."""
        per_pair = {}

        # Group trades by pair
        pairs = set(t.pair for t in self.trades)

        for pair in pairs:
            pair_trades = [t for t in self.trades if t.pair == pair]

            if pair_trades:
                winning_trades = [t for t in pair_trades if t.pnl > 0]

                per_pair[pair] = {
                    "total_trades": len(pair_trades),
                    "winning_trades": len(winning_trades),
                    "win_rate": len(winning_trades) / len(pair_trades),
                    "total_pnl": sum(t.pnl for t in pair_trades),
                    "avg_pnl": statistics.mean(t.pnl for t in pair_trades),
                    "avg_duration": statistics.mean(t.bars_held for t in pair_trades),
                }

        return per_pair

    def _calculate_daily_returns(self) -> list[float]:
        """Calculate daily returns from equity curve."""
        if len(self.equity_curve) < 2:
            return []

        daily_equities = {}

        # Group equity points by date
        for point in self.equity_curve:
            date = point.ts.date()
            daily_equities[date] = point.equity

        # Calculate daily returns
        dates = sorted(daily_equities.keys())
        returns = []

        for i in range(1, len(dates)):
            prev_equity = daily_equities[dates[i - 1]]
            curr_equity = daily_equities[dates[i]]
            daily_return = (curr_equity - prev_equity) / prev_equity
            returns.append(daily_return)

        return returns

    def _combine_walk_forward_results(self, results: list[BacktestResult]) -> BacktestResult:
        """Combine multiple walk-forward results into single result."""
        if not results:
            return BacktestResult([], [], [], [], {}, {})

        # Combine all data
        all_trades = []
        all_orders = []
        all_fills = []
        all_equity_points = []

        for result in results:
            all_trades.extend(result.trades)
            all_orders.extend(result.orders)
            all_fills.extend(result.fills)
            all_equity_points.extend(result.equity_curve)

        # Sort by timestamp
        all_trades.sort(key=lambda t: t.entry_ts)
        all_orders.sort(key=lambda o: o.ts)
        all_fills.sort(key=lambda f: f.ts)
        all_equity_points.sort(key=lambda e: e.ts)

        # Calculate combined statistics
        if all_trades:
            total_pnl = sum(t.pnl for t in all_trades)
            win_rate = len([t for t in all_trades if t.pnl > 0]) / len(all_trades)
            avg_duration = statistics.mean(t.bars_held for t in all_trades)
        else:
            total_pnl = 0.0
            win_rate = 0.0
            avg_duration = 0.0

        # Build combined summary
        combined_summary = {
            "walk_forward_windows": len(results),
            "total_trades": len(all_trades),
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "avg_trade_duration": avg_duration,
            "window_summaries": [r.summary for r in results],
        }

        # Calculate per-pair stats for combined data
        per_pair = {}
        pairs = set(t.pair for t in all_trades)

        for pair in pairs:
            pair_trades = [t for t in all_trades if t.pair == pair]
            if pair_trades:
                winning_trades = [t for t in pair_trades if t.pnl > 0]
                per_pair[pair] = {
                    "total_trades": len(pair_trades),
                    "win_rate": len(winning_trades) / len(pair_trades),
                    "total_pnl": sum(t.pnl for t in pair_trades),
                    "avg_pnl": statistics.mean(t.pnl for t in pair_trades),
                }

        return BacktestResult(
            equity_curve=all_equity_points,
            trades=all_trades,
            orders=all_orders,
            fills=all_fills,
            summary=combined_summary,
            per_pair=per_pair,
            metadata={"walk_forward": True, "windows": len(results), "combined_result": True},
        )


# =============================================================================
# Convenience Functions
# =============================================================================


def run_simple_backtest(
    ohlcv_data: dict[str, DataFrame],
    pairs: list[str],
    timeframe: str,
    config=None,
    strategy_config: Optional[dict] = None,
    seed: Optional[int] = None,
) -> BacktestResult:
    """
    Convenience function for simple backtests.

    Parameters
    ----------
    ohlcv_data : dict
        Dictionary of DataFrames with OHLCV data
    pairs : list
        List of trading pairs
    timeframe : str
        Trading timeframe
    config : optional
        Bot configuration (will load default if None)
    strategy_config : dict, optional
        Override strategy configuration
    seed : int, optional
        Random seed for determinism

    Returns
    -------
    BacktestResult
        Complete backtest results
    """
    if config is None:
        try:
            from config.loader import get_config

            config = get_config()
        except ImportError:
            raise ValueError("Config must be provided when config.loader is not available")

    # Override strategy config if provided
    if strategy_config and hasattr(config.strategies, "scalp"):
        for key, value in strategy_config.items():
            setattr(config.strategies.scalp, key, value)

    # Create and run backtest
    engine = BacktestEngine(config, seed=seed)
    engine.load_ohlcv(ohlcv_data)

    strategy_adapter = ScalperAdapter(config)
    result = engine.run(pairs, timeframe, strategy_adapter)

    return result


def load_sample_data(
    pairs: list[str] = None, timeframe: str = "1m", days: int = 30
) -> dict[str, DataFrame]:
    """
    Generate sample OHLCV data for testing.

    Parameters
    ----------
    pairs : list, optional
        Trading pairs (default: ['BTC/USD', 'ETH/USD'])
    timeframe : str
        Timeframe for data generation
    days : int
        Number of days of data to generate

    Returns
    -------
    dict
        Dictionary of sample DataFrames
    """
    if pairs is None:
        pairs = ["BTC/USD", "ETH/USD"]

    # Calculate number of bars
    timeframe_seconds = timeframe_to_seconds(timeframe)
    total_bars = int(days * 86400 / timeframe_seconds)

    # Generate timestamps
    start_time = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    timestamps = pd.date_range(
        start=start_time, periods=total_bars, freq=f"{timeframe_seconds}S", tz="UTC"
    )

    data = {}

    for pair in pairs:
        # Base price depends on pair
        if "BTC" in pair:
            base_price = 50000.0
        elif "ETH" in pair:
            base_price = 3000.0
        else:
            base_price = 100.0

        # Generate realistic price data with random walk
        np.random.seed(42)  # For reproducible sample data

        # Generate returns
        returns = np.random.normal(0, 0.002, total_bars)  # 0.2% volatility

        # Calculate prices
        log_returns = np.cumsum(returns)
        prices = base_price * np.exp(log_returns)

        # Generate OHLCV data
        df_data = []
        for i, (ts, price) in enumerate(zip(timestamps, prices)):
            # Add some intrabar variation
            high_offset = np.random.exponential(0.001) * price
            low_offset = np.random.exponential(0.001) * price

            open_price = prices[i - 1] if i > 0 else price
            close_price = price
            high_price = max(open_price, close_price) + high_offset
            low_price = min(open_price, close_price) - low_offset

            # Volume (random but realistic)
            volume = np.random.lognormal(5, 1)  # Log-normal distribution

            df_data.append(
                {
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "volume": volume,
                }
            )

        df = pd.DataFrame(df_data, index=timestamps)
        data[f"{pair}@{timeframe}"] = df

    return data


def validate_backtest_data(data: dict[str, DataFrame], min_bars: int = 100) -> dict[str, Any]:
    """
    Validate backtest data quality and completeness.

    Parameters
    ----------
    data : dict
        Dictionary of OHLCV DataFrames
    min_bars : int
        Minimum number of bars required

    Returns
    -------
    dict
        Validation report
    """
    report = {"valid": True, "errors": [], "warnings": [], "data_summary": {}}

    for key, df in data.items():
        data_info = {
            "bars": len(df),
            "start": df.index[0] if len(df) > 0 else None,
            "end": df.index[-1] if len(df) > 0 else None,
            "gaps": 0,
            "zero_volume_bars": 0,
        }

        # Check minimum bars
        if len(df) < min_bars:
            report["errors"].append(f"{key}: Only {len(df)} bars, need at least {min_bars}")
            report["valid"] = False

        # Check for required columns
        required_cols = ["open", "high", "low", "close", "volume"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            report["errors"].append(f"{key}: Missing columns {missing_cols}")
            report["valid"] = False

        # Check for NaN values
        for col in required_cols:
            if col in df.columns and df[col].isna().any():
                nan_count = df[col].isna().sum()
                report["errors"].append(f"{key}: {nan_count} NaN values in {col}")
                report["valid"] = False

        # Check for zero/negative prices
        price_cols = ["open", "high", "low", "close"]
        for col in price_cols:
            if col in df.columns and (df[col] <= 0).any():
                report["errors"].append(f"{key}: Zero or negative prices in {col}")
                report["valid"] = False

        # Check OHLC logic
        if all(col in df.columns for col in price_cols):
            invalid_ohlc = (
                (df["high"] < df[["open", "close"]].max(axis=1))
                | (df["low"] > df[["open", "close"]].min(axis=1))
            ).any()

            if invalid_ohlc:
                report["errors"].append(f"{key}: Invalid OHLC relationships")
                report["valid"] = False

        # Check for time gaps
        if len(df) > 1:
            time_diffs = df.index[1:] - df.index[:-1]
            median_diff = time_diffs.median()
            large_gaps = (time_diffs > median_diff * 2).sum()
            data_info["gaps"] = large_gaps

            if large_gaps > len(df) * 0.05:  # More than 5% gaps
                report["warnings"].append(f"{key}: {large_gaps} large time gaps detected")

        # Check zero volume
        if "volume" in df.columns:
            zero_volume = (df["volume"] == 0).sum()
            data_info["zero_volume_bars"] = zero_volume

            if zero_volume > len(df) * 0.1:  # More than 10% zero volume
                report["warnings"].append(f"{key}: {zero_volume} bars with zero volume")

        report["data_summary"][key] = data_info

    return report


# =============================================================================
# Example Usage and Testing
# =============================================================================

if __name__ == "__main__":
    # Example usage
    import logging

    logging.basicConfig(level=logging.INFO)

    # Generate sample data
    sample_data = load_sample_data(["BTC/USD"], "1m", days=7)

    # Validate data
    validation = validate_backtest_data(sample_data)
    logger = logging.getLogger(__name__)
    logger.info("Data validation: %s", "PASSED" if validation["valid"] else "FAILED")

    if validation["errors"]:
        logger.error("Errors: %s", validation["errors"])

    # Create a minimal config for testing
    class MinimalConfig:
        def __init__(self):
            self.backtest = {
                "slippage": 0.0005,
                "partial_fill_probability": 0.3,
                "partial_fill_min_pct": 0.65,
                "random_seed": 42,
                "walk_forward": {
                    "enabled": False,
                    "warmup_days": 3,
                    "test_days": 2,
                    "roll_bars": 24,
                },
            }

            self.risk = type(
                "Risk",
                (),
                {
                    "global_max_drawdown": -0.15,
                    "daily_stop_loss": -0.03,
                    "max_concurrent_positions": 3,
                    "per_symbol_max_exposure": 0.25,
                    "circuit_breakers": {"spread_bps_max": 12},
                },
            )()

            self.trading = type("Trading", (), {"position_sizing": {"base_position_size": 0.03}})()

            self.data = type("Data", (), {"warmup_bars": 50})()

            self.strategies = type(
                "Strategies",
                (),
                {
                    "scalp": type(
                        "Scalp",
                        (),
                        {
                            "timeframe": "1m",
                            "target_bps": 10,
                            "stop_loss_bps": 5,
                            "max_hold_seconds": 300,
                            "max_spread_bps": 5,
                            "post_only": True,
                            "hidden_orders": False,
                        },
                    )()
                },
            )()

            self.exchanges = {"kraken": type("Kraken", (), {"fee_taker": 0.0026})()}

    try:
        # Run simple backtest
        config = MinimalConfig()
        result = run_simple_backtest(
            ohlcv_data=sample_data, pairs=["BTC/USD"], timeframe="1m", config=config, seed=42
        )

        logger.info("\nBacktest completed:")
        logger.info("Total trades: %d", result.summary["total_trades"])
        logger.info("Win rate: %.1f%%", result.summary["win_rate"] * 100)
        logger.info("Total return: %.1f%%", result.summary["total_return"] * 100)
        logger.info("Max drawdown: %.1f%%", result.summary["max_drawdown"] * 100)
        logger.info("Final equity: $%.2f", result.summary["final_equity"])

        if result.trades:
            logger.info(
                "First trade: %s %s PnL: $%.2f",
                result.trades[0].pair,
                result.trades[0].side.value,
                result.trades[0].pnl,
            )

    except Exception as e:
        logger.error("Example failed: %s", e)
        import traceback

        traceback.print_exc()
