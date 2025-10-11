"""
Type definitions, enums, and data structures for agents.core modules.

Provides strongly-typed models with validation for trading operations,
enabling strict mypy type checking across the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Protocol

# ==============================================================================
# Enums
# ==============================================================================


class Side(str, Enum):
    """Trading side (buy/sell)."""

    BUY = "buy"
    SELL = "sell"

    @classmethod
    def from_str(cls, value: str) -> Side:
        """Convert string to Side enum.

        Args:
            value: String value ("buy" or "sell")

        Returns:
            Side enum value

        Raises:
            ValueError: If value is not valid
        """
        normalized = value.lower().strip()
        if normalized in ("buy", "b", "long"):
            return cls.BUY
        elif normalized in ("sell", "s", "short"):
            return cls.SELL
        else:
            raise ValueError(f"Invalid side: {value}. Must be 'buy' or 'sell'")


class Timeframe(str, Enum):
    """Trading timeframes."""

    T15S = "15s"  # 15 seconds (scalping)
    T30S = "30s"  # 30 seconds
    M1 = "1m"  # 1 minute
    M5 = "5m"  # 5 minutes
    M15 = "15m"  # 15 minutes
    M30 = "30m"  # 30 minutes
    H1 = "1h"  # 1 hour
    H4 = "4h"  # 4 hours
    D1 = "1d"  # 1 day

    @classmethod
    def from_str(cls, value: str) -> Timeframe:
        """Convert string to Timeframe enum.

        Args:
            value: String value (e.g., "15s", "1m", "1h")

        Returns:
            Timeframe enum value

        Raises:
            ValueError: If value is not valid
        """
        normalized = value.lower().strip()
        for tf in cls:
            if tf.value == normalized:
                return tf
        raise ValueError(
            f"Invalid timeframe: {value}. "
            f"Valid values: {', '.join(tf.value for tf in cls)}"
        )


class OrderType(str, Enum):
    """Order types."""

    MARKET = "market"
    LIMIT = "limit"
    POST_ONLY = "post_only"
    IOC = "ioc"  # Immediate or Cancel
    FOK = "fok"  # Fill or Kill

    @classmethod
    def from_str(cls, value: str) -> OrderType:
        """Convert string to OrderType enum.

        Args:
            value: String value

        Returns:
            OrderType enum value

        Raises:
            ValueError: If value is not valid
        """
        normalized = value.lower().strip()
        for ot in cls:
            if ot.value == normalized:
                return ot
        raise ValueError(f"Invalid order type: {value}")


class OrderStatus(str, Enum):
    """Order status."""

    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SignalType(str, Enum):
    """Signal types."""

    ENTRY = "entry"
    EXIT = "exit"
    SCALP = "scalp"
    TREND = "trend"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"


# ==============================================================================
# Dataclasses
# ==============================================================================


@dataclass(frozen=True)
class Signal:
    """Trading signal with validation.

    Immutable signal object representing a trading opportunity.
    """

    symbol: str
    side: Side
    confidence: float
    price: Decimal
    timestamp: float
    strategy: str
    signal_type: SignalType = SignalType.ENTRY
    timeframe: Timeframe = Timeframe.M15
    stop_loss_bps: Optional[int] = None
    take_profit_bps: Optional[list[int]] = None
    ttl_seconds: Optional[int] = None
    features: dict[str, float] = field(default_factory=dict)
    notes: str = ""
    exchange: str = "kraken"
    source: str = "unknown"

    def __post_init__(self) -> None:
        """Validate signal fields after initialization.

        Raises:
            ValueError: If validation fails
        """
        # Validate confidence
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0, 1], got {self.confidence}")

        # Validate price
        if self.price <= 0:
            raise ValueError(f"Price must be positive, got {self.price}")

        # Validate timestamp
        if self.timestamp <= 0:
            raise ValueError(f"Timestamp must be positive, got {self.timestamp}")

        # Validate stop loss
        if self.stop_loss_bps is not None and self.stop_loss_bps <= 0:
            raise ValueError(f"Stop loss must be positive, got {self.stop_loss_bps}")

        # Validate take profit
        if self.take_profit_bps is not None:
            for tp in self.take_profit_bps:
                if tp <= 0:
                    raise ValueError(f"Take profit must be positive, got {tp}")

    def to_dict(self) -> dict[str, Any]:
        """Convert signal to dictionary.

        Returns:
            Dictionary representation of signal
        """
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "confidence": self.confidence,
            "price": str(self.price),
            "timestamp": self.timestamp,
            "strategy": self.strategy,
            "signal_type": self.signal_type.value,
            "timeframe": self.timeframe.value,
            "stop_loss_bps": self.stop_loss_bps,
            "take_profit_bps": self.take_profit_bps,
            "ttl_seconds": self.ttl_seconds,
            "features": self.features,
            "notes": self.notes,
            "exchange": self.exchange,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        """Create Signal from dictionary.

        Args:
            data: Dictionary with signal data

        Returns:
            Signal instance

        Raises:
            ValueError: If data is invalid
        """
        return cls(
            symbol=data["symbol"],
            side=Side.from_str(data["side"]),
            confidence=float(data["confidence"]),
            price=Decimal(str(data["price"])),
            timestamp=float(data["timestamp"]),
            strategy=data["strategy"],
            signal_type=SignalType(data.get("signal_type", "entry")),
            timeframe=Timeframe.from_str(data.get("timeframe", "15m")),
            stop_loss_bps=data.get("stop_loss_bps"),
            take_profit_bps=data.get("take_profit_bps"),
            ttl_seconds=data.get("ttl_seconds"),
            features=data.get("features", {}),
            notes=data.get("notes", ""),
            exchange=data.get("exchange", "kraken"),
            source=data.get("source", "unknown"),
        )


@dataclass
class OrderIntent:
    """Intent to place an order (mutable, pre-execution).

    Represents the intention to execute a trade, before actual order placement.
    """

    symbol: str
    side: Side
    quantity: Decimal
    order_type: OrderType = OrderType.LIMIT
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    time_in_force: str = "GTC"
    strategy: str = "unknown"
    signal_id: Optional[str] = None
    ttl_ms: Optional[int] = None
    priority: str = "normal"

    def __post_init__(self) -> None:
        """Validate order intent.

        Raises:
            ValueError: If validation fails
        """
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {self.quantity}")

        if self.price is not None and self.price <= 0:
            raise ValueError(f"Price must be positive, got {self.price}")

        if self.order_type in (OrderType.LIMIT, OrderType.POST_ONLY) and self.price is None:
            raise ValueError(f"{self.order_type.value} orders require a price")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "order_type": self.order_type.value,
            "price": str(self.price) if self.price else None,
            "stop_price": str(self.stop_price) if self.stop_price else None,
            "time_in_force": self.time_in_force,
            "strategy": self.strategy,
            "signal_id": self.signal_id,
            "ttl_ms": self.ttl_ms,
            "priority": self.priority,
        }


@dataclass
class Order:
    """Placed order (tracking state).

    Represents an order that has been submitted to the exchange.
    """

    order_id: str
    symbol: str
    side: Side
    quantity: Decimal
    order_type: OrderType
    status: OrderStatus
    price: Optional[Decimal] = None
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Optional[Decimal] = None
    fee: Decimal = Decimal("0")
    timestamp: float = 0.0
    updated_at: float = 0.0
    strategy: str = "unknown"
    signal_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate order.

        Raises:
            ValueError: If validation fails
        """
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {self.quantity}")

        if self.filled_quantity < 0:
            raise ValueError(f"Filled quantity cannot be negative, got {self.filled_quantity}")

        if self.filled_quantity > self.quantity:
            raise ValueError(
                f"Filled quantity ({self.filled_quantity}) "
                f"cannot exceed order quantity ({self.quantity})"
            )

    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled.

        Returns:
            True if order is fully filled
        """
        return self.status == OrderStatus.FILLED or self.filled_quantity >= self.quantity

    @property
    def remaining_quantity(self) -> Decimal:
        """Get remaining unfilled quantity.

        Returns:
            Remaining quantity to be filled
        """
        return self.quantity - self.filled_quantity

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "order_type": self.order_type.value,
            "status": self.status.value,
            "price": str(self.price) if self.price else None,
            "filled_quantity": str(self.filled_quantity),
            "average_fill_price": str(self.average_fill_price) if self.average_fill_price else None,
            "fee": str(self.fee),
            "timestamp": self.timestamp,
            "updated_at": self.updated_at,
            "strategy": self.strategy,
            "signal_id": self.signal_id,
        }


@dataclass(frozen=True)
class ExecutionResult:
    """Result of order execution (immutable).

    Contains the outcome of an order execution attempt.
    """

    success: bool
    order_id: Optional[str] = None
    filled_quantity: Decimal = Decimal("0")
    average_price: Optional[Decimal] = None
    fee: Decimal = Decimal("0")
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    slippage_bps: Optional[float] = None
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "success": self.success,
            "order_id": self.order_id,
            "filled_quantity": str(self.filled_quantity),
            "average_price": str(self.average_price) if self.average_price else None,
            "fee": str(self.fee),
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
            "slippage_bps": self.slippage_bps,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class MarketData:
    """Market data snapshot (immutable).

    Contains market data for a symbol at a point in time.
    """

    symbol: str
    timestamp: float
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    last_price: Optional[Decimal] = None
    volume: Optional[Decimal] = None
    spread_bps: Optional[float] = None
    mid_price: Optional[Decimal] = None

    def __post_init__(self) -> None:
        """Validate market data.

        Raises:
            ValueError: If validation fails
        """
        if self.timestamp <= 0:
            raise ValueError(f"Timestamp must be positive, got {self.timestamp}")

        # Validate prices are positive
        for field_name in ("bid", "ask", "last_price", "volume", "mid_price"):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise ValueError(f"{field_name} must be positive, got {value}")

    @property
    def calculated_mid_price(self) -> Optional[Decimal]:
        """Calculate mid price from bid/ask.

        Returns:
            Mid price if bid and ask available, otherwise None
        """
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / Decimal("2")
        return self.mid_price

    @property
    def calculated_spread_bps(self) -> Optional[float]:
        """Calculate spread in basis points.

        Returns:
            Spread in bps if bid and ask available, otherwise None
        """
        if self.bid is not None and self.ask is not None and self.bid > 0:
            spread_decimal = (self.ask - self.bid) / self.bid
            return float(spread_decimal * Decimal("10000"))
        return self.spread_bps

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "bid": str(self.bid) if self.bid else None,
            "ask": str(self.ask) if self.ask else None,
            "last_price": str(self.last_price) if self.last_price else None,
            "volume": str(self.volume) if self.volume else None,
            "spread_bps": self.spread_bps,
            "mid_price": str(self.mid_price) if self.mid_price else None,
        }


# ==============================================================================
# Protocols for Duck Typing
# ==============================================================================


class RedisClientProtocol(Protocol):
    """Protocol for Redis client interface."""

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        """Add entry to Redis stream.

        Args:
            stream: Stream name
            fields: Field-value pairs

        Returns:
            Message ID
        """
        ...

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: Optional[int] = None,
        block: Optional[int] = None,
    ) -> list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]]:
        """Read from stream using consumer group.

        Args:
            groupname: Consumer group name
            consumername: Consumer name
            streams: Stream names and IDs
            count: Maximum number of messages
            block: Block time in milliseconds

        Returns:
            List of stream messages
        """
        ...

    async def ping(self) -> bool:
        """Ping Redis server.

        Returns:
            True if successful
        """
        ...

    async def aclose(self) -> None:
        """Close Redis connection."""
        ...


class ExchangeClientProtocol(Protocol):
    """Protocol for exchange client interface."""

    async def fetch_ticker(self, symbol: str) -> dict[str, float]:
        """Fetch ticker data.

        Args:
            symbol: Trading symbol

        Returns:
            Ticker data
        """
        ...

    async def fetch_order_book(
        self, symbol: str, limit: int = 20
    ) -> dict[str, list[list[float]]]:
        """Fetch order book.

        Args:
            symbol: Trading symbol
            limit: Number of levels

        Returns:
            Order book with bids and asks
        """
        ...

    async def create_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
    ) -> dict[str, Any]:
        """Create order.

        Args:
            symbol: Trading symbol
            order_type: Order type (market, limit)
            side: Order side (buy, sell)
            amount: Order amount
            price: Order price (for limit orders)

        Returns:
            Order result
        """
        ...


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    # Enums
    "Side",
    "Timeframe",
    "OrderType",
    "OrderStatus",
    "SignalType",
    # Dataclasses
    "Signal",
    "OrderIntent",
    "Order",
    "ExecutionResult",
    "MarketData",
    # Protocols
    "RedisClientProtocol",
    "ExchangeClientProtocol",
]
