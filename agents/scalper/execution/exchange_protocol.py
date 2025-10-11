"""
Protocol interface for exchange gateways.

This module defines the protocol (interface) that all exchange gateway implementations
must follow. Using Python's typing.Protocol enables structural subtyping without
inheritance, making it easy to swap implementations and test with fakes.

Key principles:
- Protocol-based interface: structural typing, no inheritance required
- Async-first: all methods are async for non-blocking I/O
- Type safety: comprehensive type hints for all methods
- Immutable DTOs: request/response objects are dataclasses
- Error classification: all errors are ExchangeError subclasses

Usage:
    from agents.scalper.execution.exchange_protocol import (
        ExchangeGatewayProtocol,
        OrderRequest,
        OrderResponse,
    )

    # Implement protocol
    class KrakenGateway:
        async def place_order(self, request: OrderRequest) -> OrderResponse:
            ...

    # Use protocol for type hints
    async def execute_trade(gateway: ExchangeGatewayProtocol, request: OrderRequest):
        response = await gateway.place_order(request)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Protocol

from .exchange_errors import ExchangeError


# ======================== Enums ========================


class OrderSide(Enum):
    """Order side"""

    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type"""

    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    STOP_LOSS_LIMIT = "stop_loss_limit"
    TAKE_PROFIT_LIMIT = "take_profit_limit"


class OrderStatus(Enum):
    """Order status"""

    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"


class TimeInForce(Enum):
    """Time in force"""

    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill


# ======================== DTOs (Data Transfer Objects) ========================


@dataclass(frozen=True)
class OrderRequest:
    """
    Immutable order request DTO.

    All fields are immutable to prevent accidental modification during routing.
    """

    symbol: str
    side: OrderSide
    order_type: OrderType
    size: float  # Quantity in base currency
    price: Optional[float] = None  # Required for limit orders
    stop_price: Optional[float] = None  # Required for stop orders
    time_in_force: TimeInForce = TimeInForce.GTC
    client_order_id: Optional[str] = None
    reduce_only: bool = False
    post_only: bool = False
    leverage: Optional[int] = None
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate order request"""
        if self.size <= 0:
            raise ValueError(f"Order size must be positive, got {self.size}")

        if self.order_type in {OrderType.LIMIT, OrderType.STOP_LOSS_LIMIT, OrderType.TAKE_PROFIT_LIMIT}:
            if self.price is None or self.price <= 0:
                raise ValueError(f"Limit orders require positive price, got {self.price}")

        if self.order_type in {OrderType.STOP_LOSS, OrderType.TAKE_PROFIT, OrderType.STOP_LOSS_LIMIT, OrderType.TAKE_PROFIT_LIMIT}:
            if self.stop_price is None or self.stop_price <= 0:
                raise ValueError(f"Stop orders require positive stop_price, got {self.stop_price}")


@dataclass
class OrderResponse:
    """
    Mutable order response DTO.

    Contains exchange-returned order details and status.
    """

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    size: float
    filled_size: float
    price: Optional[float]
    average_fill_price: Optional[float]
    timestamp: float
    client_order_id: Optional[str] = None
    fee: Optional[float] = None
    fee_currency: Optional[str] = None
    stop_price: Optional[float] = None
    time_in_force: Optional[TimeInForce] = None
    metadata: Dict[str, str] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        """Check if order is open (pending or partially filled)"""
        return self.status in {OrderStatus.PENDING, OrderStatus.OPEN}

    @property
    def is_closed(self) -> bool:
        """Check if order is closed (fully filled)"""
        return self.status == OrderStatus.CLOSED

    @property
    def is_canceled(self) -> bool:
        """Check if order was canceled"""
        return self.status == OrderStatus.CANCELED

    @property
    def is_rejected(self) -> bool:
        """Check if order was rejected"""
        return self.status == OrderStatus.REJECTED

    @property
    def remaining_size(self) -> float:
        """Calculate remaining unfilled size"""
        return max(0.0, self.size - self.filled_size)


@dataclass
class Balance:
    """Account balance for a currency"""

    currency: str
    available: float
    total: float
    reserved: float = 0.0

    @property
    def free(self) -> float:
        """Alias for available"""
        return self.available


@dataclass
class Position:
    """Open position"""

    symbol: str
    side: OrderSide
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    leverage: Optional[int] = None
    liquidation_price: Optional[float] = None


# ======================== Protocol Definition ========================


class ExchangeGatewayProtocol(Protocol):
    """
    Protocol for exchange gateway implementations.

    All exchange gateways must implement these methods to be compatible with
    the trading system. Uses structural subtyping (Protocol) rather than
    inheritance for flexibility.

    Example implementation:
        class KrakenGateway:
            async def place_order(self, request: OrderRequest) -> OrderResponse:
                # Kraken-specific implementation
                ...

            async def cancel_order(self, order_id: str, symbol: str) -> bool:
                # Kraken-specific implementation
                ...
    """

    async def place_order(self, request: OrderRequest) -> OrderResponse:
        """
        Place a new order on the exchange.

        Args:
            request: Immutable order request with all required parameters

        Returns:
            OrderResponse with exchange-assigned order ID and status

        Raises:
            RateLimitError: If rate limit exceeded (retryable)
            NetworkError: If network issue occurs (retryable)
            InvalidOrderError: If order parameters invalid (fatal)
            InsufficientFundsError: If insufficient balance (fatal)
            AuthenticationError: If authentication fails (fatal)
        """
        ...

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: Exchange-assigned order ID
            symbol: Trading pair symbol

        Returns:
            True if order was canceled, False if already filled/canceled

        Raises:
            RateLimitError: If rate limit exceeded (retryable)
            NetworkError: If network issue occurs (retryable)
            OrderNotFoundError: If order doesn't exist (fatal)
            AuthenticationError: If authentication fails (fatal)
        """
        ...

    async def get_order_status(self, order_id: str, symbol: str) -> Optional[OrderResponse]:
        """
        Get current status of an order.

        Args:
            order_id: Exchange-assigned order ID
            symbol: Trading pair symbol

        Returns:
            OrderResponse with current status, or None if order not found

        Raises:
            RateLimitError: If rate limit exceeded (retryable)
            NetworkError: If network issue occurs (retryable)
            AuthenticationError: If authentication fails (fatal)
        """
        ...

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderResponse]:
        """
        Get all open orders.

        Args:
            symbol: Optional symbol filter (None for all symbols)

        Returns:
            List of OrderResponse objects for open orders

        Raises:
            RateLimitError: If rate limit exceeded (retryable)
            NetworkError: If network issue occurs (retryable)
            AuthenticationError: If authentication fails (fatal)
        """
        ...

    async def get_balance(self, currency: Optional[str] = None) -> Dict[str, Balance]:
        """
        Get account balances.

        Args:
            currency: Optional currency filter (None for all currencies)

        Returns:
            Dictionary mapping currency code to Balance object

        Raises:
            RateLimitError: If rate limit exceeded (retryable)
            NetworkError: If network issue occurs (retryable)
            AuthenticationError: If authentication fails (fatal)
        """
        ...

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """
        Get open positions (for margin/futures trading).

        Args:
            symbol: Optional symbol filter (None for all positions)

        Returns:
            List of Position objects

        Raises:
            RateLimitError: If rate limit exceeded (retryable)
            NetworkError: If network issue occurs (retryable)
            AuthenticationError: If authentication fails (fatal)
        """
        ...


# ======================== Rate Limiting ========================


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""

    max_requests_per_second: float = 1.0
    max_burst: int = 5
    cooldown_on_429: float = 60.0  # Seconds to wait after rate limit error


@dataclass
class RateLimitState:
    """Mutable state for rate limiting (token bucket algorithm)"""

    tokens: float
    last_refill: float
    total_requests: int = 0
    rate_limit_hits: int = 0
    last_rate_limit_time: Optional[float] = None


# ======================== Helper Types ========================


@dataclass
class ExchangeInfo:
    """Exchange information and limits"""

    name: str
    symbols: List[str]
    min_order_size: Dict[str, float]
    max_order_size: Dict[str, float]
    price_precision: Dict[str, int]
    size_precision: Dict[str, int]
    rate_limits: RateLimitConfig
