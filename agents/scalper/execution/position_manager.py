"""
Production-grade position management for trading agents.

This module provides comprehensive position management capabilities for the scalping
system, handling position sizing, P&L tracking, exposure monitoring, and order
lifecycle management with advanced risk controls and performance analytics.

Features:
- Dynamic position sizing with risk management
- Real-time P&L calculation and tracking
- Order lifecycle management and fill processing
- Portfolio exposure monitoring and limits
- Performance metrics and analytics
- Kelly criterion sizing (optional)
- Volatility-based position adjustment
- Multi-position portfolio management

This module provides the core position management capabilities for the scalping
system, enabling sophisticated risk management and portfolio optimization.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from utils.logger import get_logger

# Dynamic position sizing integration
try:
    from agents.scalper.risk.dynamic_sizing import DynamicPositionSizer, create_sizer_from_dict
    from agents.scalper.risk.sizing_integration import DynamicSizingIntegration
    DYNAMIC_SIZING_AVAILABLE = True
except ImportError:
    DYNAMIC_SIZING_AVAILABLE = False
    DynamicPositionSizer = None
    DynamicSizingIntegration = None

logger = logging.getLogger(__name__)


def as_decimal(x: float | str | Decimal) -> Decimal:
    """
    Convert float, string, or Decimal to Decimal for precise calculations.

    Args:
        x: Value to convert (float, str, or Decimal)

    Returns:
        Decimal representation of the input value
    """
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


# ----------------------------- Enums & Data Models -----------------------------


class PositionSide(str, Enum):
    """Position side enumeration."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class OrderStatus(str, Enum):
    """Order status enumeration."""

    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PositionStatus(str, Enum):
    """Position status enumeration."""

    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class Fill:
    """Represents an order fill."""

    id: str
    order_id: str
    symbol: str
    side: str
    size: Decimal
    price: Decimal
    fee: Decimal
    timestamp: float
    fee_currency: str = "USD"


@dataclass
class Order:
    """Order tracking information."""

    id: str
    symbol: str
    side: str  # "buy" or "sell"
    type: str  # "limit", "market", etc.
    size: Decimal
    price: Optional[Decimal]
    status: OrderStatus
    created_time: float
    updated_time: float
    filled_size: Decimal = Decimal("0")
    avg_fill_price: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    fills: List[Fill] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def remaining_size(self) -> Decimal:
        """Remaining unfilled size (non-negative)."""
        return max(Decimal("0"), self.size - self.filled_size)

    @property
    def fill_percentage(self) -> float:
        """Fraction of order filled in [0,1]."""
        return float(self.filled_size / self.size) if self.size > Decimal("0") else 0.0

    @property
    def is_complete(self) -> bool:
        """True if order fully filled or remaining_size == 0."""
        return self.status == OrderStatus.FILLED or self.remaining_size <= Decimal("0")


@dataclass
class Position:
    """Position tracking information (one net position per symbol)."""

    symbol: str
    side: PositionSide
    size: Decimal  # signed: LONG>0, SHORT<0
    avg_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    total_fees: Decimal
    status: PositionStatus
    opened_time: float
    updated_time: float
    orders: List[str] = field(default_factory=list)  # list of Order IDs
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def market_value(self) -> Decimal:
        """Absolute notional value at current price."""
        return abs(self.size) * self.current_price

    @property
    def total_pnl(self) -> Decimal:
        """Realized + unrealized P&L."""
        return self.realized_pnl + self.unrealized_pnl

    @property
    def return_percentage(self) -> float:
        """Return % vs. average entry price, signed by side."""
        if self.avg_price <= Decimal("0"):
            return 0.0
        signed = Decimal("1") if self.side == PositionSide.LONG else Decimal("-1")
        return float(signed * (self.current_price - self.avg_price) / self.avg_price)


class PositionSizingConfig(BaseModel):
    """Position sizing configuration (USD-based)."""

    base_size_usd: float = Field(default=100.0, gt=0)
    max_size_usd: float = Field(default=1000.0, gt=0)
    min_size_usd: float = Field(default=10.0, gt=0)
    risk_percentage: float = Field(default=0.01, gt=0, le=0.1)  # risk per trade
    volatility_adjustment: bool = True
    volatility_lookback_periods: int = 20
    max_position_percentage: float = Field(default=0.10, gt=0, le=1.0)  # of equity

    # Kelly criterion settings
    use_kelly_sizing: bool = False
    kelly_fraction: float = Field(default=0.25, gt=0, le=1.0)  # fractional Kelly
    min_edge_requirement: float = Field(
        default=0.10, gt=0
    )  # min expected edge (not used here but kept for API)


@dataclass
class PositionMetrics:
    """Position management performance metrics."""

    total_positions: int = 0
    active_positions: int = 0
    winning_positions: int = 0
    losing_positions: int = 0
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_fees_paid: float = 0.0
    avg_position_duration_seconds: float = (
        0.0  # placeholder: compute if you track durations explicitly
    )
    max_position_size: float = 0.0
    current_exposure: float = 0.0
    sharpe_ratio: Optional[float] = None
    win_rate: float = 0.0
    profit_factor: Optional[float] = None
    # New: separate buckets for profit factor correctness
    _gross_winning_pnl: float = 0.0
    _gross_losing_pnl: float = 0.0


# --------------------------------- Manager ------------------------------------


class PositionManager:
    """
    Advanced position manager for trading agents.

    Features:
    - Dynamic position sizing with risk management
    - Real-time P&L calculation
    - Order lifecycle tracking
    - Portfolio exposure monitoring
    - Performance metrics and analytics
    - Kelly criterion sizing (optional)
    """

    def __init__(
        self,
        agent_id: str,
        initial_capital: float = 10000.0,
        sizing_config: Optional[PositionSizingConfig] = None,
        max_positions: int = 5,
        dynamic_sizing_config: Optional[Dict[str, Any]] = None,
        redis_bus: Optional[Any] = None,
        state_manager: Optional[Any] = None,
    ):
        self.agent_id = agent_id
        self.initial_capital = float(initial_capital)
        self.current_capital = float(initial_capital)
        self.sizing_config = sizing_config or PositionSizingConfig()
        self.max_positions = int(max_positions)

        # Position & order tracking
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []
        self.position_history: List[Position] = []

        # Price tracking for P&L calculations
        self.current_prices: Dict[str, float] = {}
        self.price_history: Dict[str, List[Tuple[float, float]]] = {}  # (timestamp, price)

        # Metrics & analytics
        self.metrics = PositionMetrics()
        self.daily_pnl_history: List[Tuple[float, float]] = []  # (timestamp, daily_pnl)
        self.returns_history: List[float] = []  # per-trade returns recorded on close

        # Concurrency
        self.position_lock = asyncio.Lock()

        # Logging
        self.logger = get_logger(f"position_manager.{agent_id}")
        self.logger.info(f"Position manager initialized with ${initial_capital:,.2f} capital")

        # Dynamic position sizing (optional)
        self.dynamic_sizing: Optional[DynamicSizingIntegration] = None
        if DYNAMIC_SIZING_AVAILABLE and dynamic_sizing_config and dynamic_sizing_config.get("enabled", False):
            try:
                self.dynamic_sizing = DynamicSizingIntegration(
                    config_dict=dynamic_sizing_config,
                    redis_bus=redis_bus,
                    state_manager=state_manager,
                    agent_id=agent_id,
                )
                self.logger.info("Dynamic position sizing enabled")
            except Exception as e:
                self.logger.error(f"Failed to initialize dynamic sizing: {e}", exc_info=True)
                self.dynamic_sizing = None

    # ------------------------------- Lifecycle --------------------------------

    async def start(self) -> None:
        """Start the position manager (initializes dynamic sizing if enabled)."""
        if self.dynamic_sizing:
            try:
                await self.dynamic_sizing.start()
                self.logger.info("Dynamic sizing started")
            except Exception as e:
                self.logger.error(f"Failed to start dynamic sizing: {e}", exc_info=True)

    async def stop(self) -> None:
        """Stop the position manager (shuts down dynamic sizing if enabled)."""
        if self.dynamic_sizing:
            try:
                await self.dynamic_sizing.stop()
                self.logger.info("Dynamic sizing stopped")
            except Exception as e:
                self.logger.error(f"Failed to stop dynamic sizing: {e}", exc_info=True)

    async def register_order(self, order: Order) -> None:
        """Register a new order so fills can be attached later."""
        async with self.position_lock:
            self.orders[order.id] = order
            self.logger.debug(
                f"Registered order {order.id} {order.side} {order.size} {order.symbol}"
            )

    async def calculate_position_size(
        self,
        symbol: str,
        signal_confidence: float,
        risk_score: float,
        target_profit_bps: int,
        stop_loss_bps: int,
        current_price: Optional[float] = None,
    ) -> float:
        """
        Calculate optimal position size based on risk and portfolio state.

        Returns: position size in USD (clamped to [min_size, max_size] and portfolio constraints)
        """
        async with self.position_lock:
            try:
                with log_context(agent_id=self.agent_id, symbol=symbol):
                    price = current_price or self.current_prices.get(symbol, 0.0)
                    if price <= 0:
                        self.logger.warning(f"No price available for {symbol}")
                        return 0.0

                    # Base sizing
                    base_size = self.sizing_config.base_size_usd

                    # Risk / confidence multipliers
                    risk_multiplier = max(0.10, 1.0 - max(0.0, min(1.0, risk_score)))
                    confidence_multiplier = max(0.50, max(0.0, min(1.0, signal_confidence)))

                    # Volatility multiplier
                    vol_multiplier = 1.0
                    if self.sizing_config.volatility_adjustment:
                        vol_multiplier = await self._calculate_volatility_multiplier(symbol)

                    # Portfolio heat multiplier
                    exposure_multiplier = await self._calculate_exposure_multiplier()

                    # Risk-per-trade sizing (risk % of equity / stop loss fraction)
                    # If stop_loss_bps is tiny, fall back to base sizing.
                    stop_loss_fraction = max(1e-6, abs(stop_loss_bps) / 10_000.0)
                    equity = await self.get_portfolio_value()
                    risk_budget_usd = equity * self.sizing_config.risk_percentage
                    risk_based_size = risk_budget_usd / stop_loss_fraction

                    # Combine signals
                    position_size = (
                        base_size
                        * risk_multiplier
                        * confidence_multiplier
                        * vol_multiplier
                        * exposure_multiplier
                    )
                    # Take the safer of the two: risk-based vs signal-based
                    position_size = min(position_size, risk_based_size)

                    # Kelly (optional): cap by Kelly sizing
                    if self.sizing_config.use_kelly_sizing:
                        kelly_size = await self._calculate_kelly_size(
                            target_profit_bps, stop_loss_bps, signal_confidence
                        )
                        position_size = min(position_size, kelly_size)

                    # Dynamic position sizing (NEW): apply adaptive multiplier
                    if self.dynamic_sizing:
                        try:
                            # Calculate portfolio heat
                            total_exposure = sum(
                                abs(p.get("notional_value", 0.0))
                                for p in (await self._get_all_positions()).values()
                            )
                            portfolio_heat_pct = (total_exposure / equity * 100.0) if equity > 0 else 0.0

                            # Get current volatility (ATR%)
                            volatility_atr_pct = await self._get_current_atr_pct(symbol)

                            # Get dynamic size multiplier
                            size_multiplier, breakdown = await self.dynamic_sizing.get_size_multiplier(
                                current_equity_usd=equity,
                                portfolio_heat_pct=portfolio_heat_pct,
                                current_volatility_atr_pct=volatility_atr_pct,
                            )

                            # Apply multiplier
                            position_size *= size_multiplier

                            self.logger.debug(
                                "Dynamic sizing applied: %.2fx multiplier (breakdown: %s)",
                                size_multiplier,
                                breakdown,
                            )
                        except Exception as e:
                            self.logger.error("Error applying dynamic sizing: %s", e, exc_info=True)

                    # Limits
                    position_size = max(self.sizing_config.min_size_usd, position_size)
                    position_size = min(self.sizing_config.max_size_usd, position_size)

                    # Portfolio limits
                    max_portfolio_size = equity * self.sizing_config.max_position_percentage
                    position_size = min(position_size, max_portfolio_size)

                    # Liquidity: available capital
                    available_capital = await self._get_available_capital()
                    position_size = max(0.0, min(position_size, available_capital))

                    self.logger.debug(
                        "Size %s: $%.2f [risk=%.2f conf=%.2f vol=%.2f exp=%.2f riskUSD=%.2f equity=%.2f]",
                        symbol,
                        position_size,
                        risk_multiplier,
                        confidence_multiplier,
                        vol_multiplier,
                        exposure_multiplier,
                        risk_budget_usd,
                        equity,
                    )
                    return position_size
            except Exception as e:
                self.logger.error(f"Error calculating position size: {e}")
                return 0.0

    async def open_position(
        self,
        order_id: str,
        symbol: str,
        side: str,
        size: float,
        price: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Open a new position or add to an existing one.
        For SHORT, internal signed size is negative.
        """
        async with self.position_lock:
            try:
                with log_context(agent_id=self.agent_id, symbol=symbol, order_id=order_id):
                    now = time.time()
                    position_side = (
                        PositionSide.LONG if side.lower() == "buy" else PositionSide.SHORT
                    )

                    if symbol in self.positions:
                        existing = self.positions[symbol]
                        if existing.side != position_side:
                            # Reduce the opposite position first
                            await self._reduce_position(symbol, size, price, order_id)
                        else:
                            # Add to same-direction position
                            await self._add_to_position(symbol, size, price, order_id)
                    else:
                        if len(self.positions) >= self.max_positions:
                            self.logger.warning(f"Maximum positions ({self.max_positions}) reached")
                            return False

                        pos = Position(
                            symbol=symbol,
                            side=position_side,
                            size=size if position_side == PositionSide.LONG else -abs(size),
                            avg_price=price,
                            current_price=price,
                            unrealized_pnl=0.0,
                            realized_pnl=0.0,
                            total_fees=0.0,
                            status=PositionStatus.OPEN,
                            opened_time=now,
                            updated_time=now,
                            orders=[order_id],
                            metadata=metadata or {},
                        )
                        self.positions[symbol] = pos
                        self.metrics.active_positions += 1
                        self.metrics.total_positions += 1

                    self.current_prices[symbol] = price

                    log_trade(
                        self.logger,
                        symbol,
                        side,
                        size,
                        price,
                        order_id=order_id,
                        position_type="open",
                    )

                    await self._update_metrics()
                    return True
            except Exception as e:
                self.logger.error(f"Error opening position: {e}")
                return False

    async def close_position(
        self,
        symbol: str,
        order_id: str,
        size: Optional[float] = None,
        price: Optional[float] = None,
    ) -> bool:
        """
        Close a position fully or partially. Realizes P&L.
        """
        async with self.position_lock:
            try:
                with log_context(agent_id=self.agent_id, symbol=symbol, order_id=order_id):
                    if symbol not in self.positions:
                        self.logger.warning(f"No position found for {symbol}")
                        return False

                    pos = self.positions[symbol]
                    exec_price = price or self.current_prices.get(symbol, pos.current_price)
                    close_size = float(size or abs(pos.size))
                    close_size = min(abs(pos.size), close_size)

                    # Realized P&L (fees are tracked separately)
                    if pos.side == PositionSide.LONG:
                        realized_pnl = (exec_price - pos.avg_price) * close_size
                        trade_side = "sell"
                    else:
                        realized_pnl = (pos.avg_price - exec_price) * close_size
                        trade_side = "buy"

                    # Update realized buckets for Profit Factor
                    if realized_pnl >= 0:
                        self.metrics.winning_positions += 1
                        self.metrics._gross_winning_pnl += realized_pnl
                    else:
                        self.metrics.losing_positions += 1
                        self.metrics._gross_losing_pnl += realized_pnl  # negative

                    # Record per-trade return for Sharpe (normalized to equity at decision time)
                    equity_before = max(1e-9, await self.get_portfolio_value())
                    self.returns_history.append(realized_pnl / equity_before)

                    # Update position
                    pos.realized_pnl += realized_pnl
                    pos.updated_time = time.time()
                    pos.orders.append(order_id)

                    # Adjust size
                    if close_size >= abs(pos.size) - 1e-12:
                        # Full close
                        pos.status = PositionStatus.CLOSED
                        pos.size = 0.0
                        pos.unrealized_pnl = 0.0

                        # Move to history and drop from active
                        self.position_history.append(pos)
                        del self.positions[symbol]
                        self.metrics.active_positions = max(0, self.metrics.active_positions - 1)
                    else:
                        # Partial close: keep sign consistent
                        remaining_ratio = (abs(pos.size) - close_size) / abs(pos.size)
                        pos.size = math.copysign(
                            abs(pos.size) * remaining_ratio,
                            1.0 if pos.side == PositionSide.LONG else -1.0,
                        )

                    # Update capital and cumulative metrics
                    self.metrics.total_realized_pnl += realized_pnl
                    self.current_capital += realized_pnl

                    log_trade(
                        self.logger,
                        symbol,
                        trade_side,
                        close_size,
                        exec_price,
                        order_id=order_id,
                        position_type="close",
                        pnl=realized_pnl,
                    )

                    # Record trade outcome for dynamic sizing (NEW)
                    if self.dynamic_sizing:
                        try:
                            await self.dynamic_sizing.record_trade_outcome(
                                symbol=symbol,
                                pnl_usd=realized_pnl,
                                size_usd=close_size * exec_price,
                            )
                        except Exception as e:
                            self.logger.error(f"Error recording trade for dynamic sizing: {e}", exc_info=True)

                    await self._update_metrics()
                    return True
            except Exception as e:
                self.logger.error(f"Error closing position: {e}")
                return False

    # ------------------------------- Updates ----------------------------------

    async def update_market_price(self, symbol: str, price: float) -> None:
        """Update market price and recompute unrealized P&L."""
        async with self.position_lock:
            try:
                self.current_prices[symbol] = price
                now = time.time()

                # Price history
                bucket = self.price_history.setdefault(symbol, [])
                bucket.append((now, price))
                if len(bucket) > 100:
                    self.price_history[symbol] = bucket[-100:]

                if symbol in self.positions:
                    pos = self.positions[symbol]
                    pos.current_price = price
                    if pos.side == PositionSide.LONG:
                        pos.unrealized_pnl = (price - pos.avg_price) * abs(pos.size)
                    else:
                        pos.unrealized_pnl = (pos.avg_price - price) * abs(pos.size)
                    pos.updated_time = now
            except Exception as e:
                self.logger.error(f"Error updating market price: {e}")

    async def add_order_fill(self, order_id: str, fill: Fill) -> None:
        """Attach a fill to an existing order and update aggregates."""
        async with self.position_lock:
            try:
                if order_id not in self.orders:
                    # If the order wasn't registered, create a minimal shell to avoid losing fills.
                    self.logger.warning(
                        f"Order {order_id} not found; creating a placeholder to store fills."
                    )
                    placeholder = Order(
                        id=order_id,
                        symbol=fill.symbol,
                        side=fill.side,
                        type="unknown",
                        size=fill.size,
                        price=fill.price,
                        status=OrderStatus.PENDING,
                        created_time=fill.timestamp,
                        updated_time=fill.timestamp,
                    )
                    self.orders[order_id] = placeholder

                order = self.orders[order_id]
                order.fills.append(fill)
                order.filled_size += fill.size
                order.total_fees += fill.fee
                order.updated_time = time.time()

                # Average fill price
                if order.filled_size > 0:
                    total_value = sum(f.size * f.price for f in order.fills)
                    order.avg_fill_price = total_value / order.filled_size

                # Status machine
                if order.filled_size >= order.size - 1e-12:
                    order.status = OrderStatus.FILLED
                elif order.filled_size > 0:
                    order.status = OrderStatus.PARTIALLY_FILLED

                # Propagate fees to position metrics if position exists
                if order.symbol in self.positions:
                    self.positions[order.symbol].total_fees += fill.fee
                self.metrics.total_fees_paid += fill.fee

                self.logger.debug(f"Added fill to order {order_id}: {fill.size} @ {fill.price}")
            except Exception as e:
                self.logger.error(f"Error adding order fill: {e}")

    # --------------------------------- Views ----------------------------------

    async def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a symbol (shallow copy semantics)."""
        return self.positions.get(symbol)

    async def get_all_positions(self) -> Dict[str, Position]:
        """Get all current positions (shallow copy semantics)."""
        return dict(self.positions)

    async def get_portfolio_value(self) -> float:
        """
        Mark-to-market equity:
        equity = current_capital (cash + realized) + sum(unrealized P&L)
        """
        async with self.position_lock:
            equity = self.current_capital
            equity += sum(p.unrealized_pnl for p in self.positions.values())
            return equity

    async def get_total_exposure(self) -> float:
        """Sum of absolute position notionals at current price."""
        return sum(p.market_value for p in self.positions.values())

    async def get_metrics(self) -> PositionMetrics:
        """Return a snapshot of current metrics."""
        async with self.position_lock:
            await self._update_metrics()
            # Return a shallow copy so callers can serialize safely
            return PositionMetrics(**self.metrics.__dict__)

    async def get_position_summary(self) -> Dict[str, Any]:
        """Human-friendly summary of capital, positions, and performance."""
        portfolio_value = await self.get_portfolio_value()
        total_exposure = await self.get_total_exposure()

        return {
            "capital": {
                "initial": self.initial_capital,
                "current": self.current_capital,
                "portfolio_value": portfolio_value,
                "total_return": (portfolio_value - self.initial_capital)
                / max(1e-9, self.initial_capital),
            },
            "positions": {
                "active_count": len(self.positions),
                "total_exposure": total_exposure,
                "exposure_ratio": total_exposure / max(1e-9, portfolio_value),
                "positions": {
                    symbol: {
                        "side": pos.side.value,
                        "size": pos.size,
                        "avg_price": pos.avg_price,
                        "current_price": pos.current_price,
                        "unrealized_pnl": pos.unrealized_pnl,
                        "return_pct": pos.return_percentage * 100.0,
                    }
                    for symbol, pos in self.positions.items()
                },
            },
            "performance": {
                "total_realized_pnl": self.metrics.total_realized_pnl,
                "total_unrealized_pnl": self.metrics.total_unrealized_pnl,
                "total_fees": self.metrics.total_fees_paid,
                "win_rate": self.metrics.win_rate * 100.0,
                "profit_factor": self.metrics.profit_factor,
                "sharpe_ratio": self.metrics.sharpe_ratio,
            },
        }

    # ---------------------------- Internal helpers ----------------------------

    async def _calculate_volatility_multiplier(self, symbol: str) -> float:
        """Inverse-volatility sizing multiplier computed from simple returns."""
        try:
            hist = self.price_history.get(symbol, [])
            n = self.sizing_config.volatility_lookback_periods
            if len(hist) < n:
                return 1.0

            recent = hist[-n:]
            rets: List[float] = []
            for i in range(1, len(recent)):
                p1 = recent[i - 1][1]
                p2 = recent[i][1]
                if p1 <= 0:
                    continue
                rets.append((p2 / p1) - 1.0)

            if not rets:
                return 1.0

            mean_r = sum(rets) / len(rets)
            var = sum((r - mean_r) ** 2 for r in rets) / len(rets)
            vol = math.sqrt(var)
            ann_vol = vol * math.sqrt(365.0)

            base_vol = 0.20  # target base annualized vol
            multiplier = base_vol / max(0.01, ann_vol)  # inverse vol
            return min(2.0, max(0.25, multiplier))
        except Exception as e:
            self.logger.error(f"Error calculating volatility multiplier: {e}")
            return 1.0

    async def _calculate_exposure_multiplier(self) -> float:
        """Reduce size as portfolio exposure approaches 100% of equity."""
        try:
            total_exposure = await self.get_total_exposure()
            equity = await self.get_portfolio_value()
            if equity <= 0:
                return 0.10
            ratio = total_exposure / equity
            max_exposure = 1.0
            if ratio >= max_exposure:
                return 0.10
            return max(0.10, 1.0 - (ratio / max_exposure))
        except Exception as e:
            self.logger.error(f"Error calculating exposure multiplier: {e}")
            return 1.0

    async def _calculate_kelly_size(
        self,
        target_profit_bps: int,
        stop_loss_bps: int,
        win_probability: float,
    ) -> float:
        """Fractional Kelly sizing (capped)."""
        try:
            win_amount = max(1e-6, target_profit_bps / 10_000.0)
            loss_amount = max(1e-6, abs(stop_loss_bps) / 10_000.0)

            b = win_amount / loss_amount  # payoff ratio
            p = max(0.0, min(1.0, win_probability))
            q = 1.0 - p

            kelly_fraction = (b * p - q) / max(1e-9, b)
            kelly_fraction = max(0.0, kelly_fraction) * self.sizing_config.kelly_fraction
            kelly_fraction = min(kelly_fraction, 0.50)  # extra safety cap

            equity = await self.get_portfolio_value()
            return equity * kelly_fraction
        except Exception as e:
            self.logger.error(f"Error calculating Kelly size: {e}")
            return self.sizing_config.base_size_usd

    async def _get_available_capital(self) -> float:
        """
        Available capital for new exposure:
        equity - (current exposure + equity * reserve_ratio)
        """
        equity = await self.get_portfolio_value()
        exposure = await self.get_total_exposure()
        reserve_ratio = 0.20
        available = equity - (exposure + equity * reserve_ratio)
        return max(0.0, available)

    async def _get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """Get all positions formatted for risk calculations."""
        return {
            symbol: {
                "size": float(pos.size),
                "notional_value": float(pos.market_value),
                "side": pos.side.value,
            }
            for symbol, pos in self.positions.items()
        }

    async def _get_current_atr_pct(self, symbol: str) -> Optional[float]:
        """
        Calculate current ATR% for volatility adjustment.

        Returns None if insufficient data, otherwise ATR as % of price.
        """
        try:
            price_data = self.price_history.get(symbol, [])
            if len(price_data) < 14:
                return None  # Not enough data for ATR

            # Simple ATR calculation using last 14 periods
            recent_prices = [p[1] for p in price_data[-14:]]
            true_ranges = []
            for i in range(1, len(recent_prices)):
                high_low = abs(recent_prices[i] - recent_prices[i - 1])
                true_ranges.append(high_low)

            if not true_ranges:
                return None

            atr = sum(true_ranges) / len(true_ranges)
            current_price = self.current_prices.get(symbol, recent_prices[-1])

            if current_price <= 0:
                return None

            atr_pct = (atr / current_price) * 100.0
            return atr_pct

        except Exception as e:
            self.logger.error(f"Error calculating ATR% for {symbol}: {e}")
            return None

    async def _add_to_position(self, symbol: str, size: float, price: float, order_id: str) -> None:
        """Add to an existing same-direction position (recompute VWAP avg_price)."""
        pos = self.positions[symbol]
        current_value = abs(pos.size) * pos.avg_price
        new_value = abs(size) * price
        new_size = abs(pos.size) + abs(size)
        if new_size > 0:
            pos.avg_price = (current_value + new_value) / new_size

        if pos.side == PositionSide.LONG:
            pos.size += abs(size)
        else:
            pos.size -= abs(size)

        pos.updated_time = time.time()
        pos.orders.append(order_id)

    async def _reduce_position(self, symbol: str, size: float, price: float, order_id: str) -> None:
        """Reduce or close an existing position (opposite-side trade)."""
        pos = self.positions[symbol]
        reduce_qty = min(abs(pos.size), abs(size))

        if pos.side == PositionSide.LONG:
            realized_pnl = (price - pos.avg_price) * reduce_qty
        else:
            realized_pnl = (pos.avg_price - price) * reduce_qty

        # Update PF buckets and counts
        if realized_pnl >= 0:
            self.metrics.winning_positions += 1
            self.metrics._gross_winning_pnl += realized_pnl
        else:
            self.metrics.losing_positions += 1
            self.metrics._gross_losing_pnl += realized_pnl

        equity_before = max(1e-9, await self.get_portfolio_value())
        self.returns_history.append(realized_pnl / equity_before)

        pos.realized_pnl += realized_pnl
        self.current_capital += realized_pnl
        self.metrics.total_realized_pnl += realized_pnl

        # Adjust size
        if reduce_qty >= abs(pos.size) - 1e-12:
            pos.status = PositionStatus.CLOSED
            pos.size = 0.0
            pos.unrealized_pnl = 0.0
        else:
            if pos.side == PositionSide.LONG:
                pos.size -= reduce_qty
            else:
                pos.size += reduce_qty

        pos.updated_time = time.time()
        pos.orders.append(order_id)

    async def _update_metrics(self) -> None:
        """Recompute derived metrics (win rate, PF, exposure, unrealized, Sharpe)."""
        try:
            # Win rate
            closed = self.metrics.winning_positions + self.metrics.losing_positions
            self.metrics.win_rate = (self.metrics.winning_positions / closed) if closed > 0 else 0.0

            # Profit Factor = sum(wins) / abs(sum(losses))
            gross_wins = self.metrics._gross_winning_pnl
            gross_losses = abs(self.metrics._gross_losing_pnl)  # remember negative
            self.metrics.profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else None

            # Exposure
            self.metrics.current_exposure = await self.get_total_exposure()

            # Unrealized
            total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())
            self.metrics.total_unrealized_pnl = total_unrealized

            # (Optional) Sharpe on per-trade returns (simple, non-annualized)
            if len(self.returns_history) >= 10:
                avg_r = sum(self.returns_history) / len(self.returns_history)
                var_r = sum((r - avg_r) ** 2 for r in self.returns_history) / len(
                    self.returns_history
                )
                std_r = math.sqrt(var_r)
                self.metrics.sharpe_ratio = (avg_r / std_r) if std_r > 0 else None

            # Track max position size (by notional)
            if self.positions:
                self.metrics.max_position_size = max(
                    p.market_value for p in self.positions.values()
                )
            else:
                self.metrics.max_position_size = 0.0

        except Exception as e:
            self.logger.error(f"Error updating metrics: {e}")


# ------------------------------- Public Exports -------------------------------

__all__ = [
    "PositionManager",
    "Position",
    "Order",
    "Fill",
    "PositionSide",
    "OrderStatus",
    "PositionStatus",
    "PositionSizingConfig",
    "PositionMetrics",
]
