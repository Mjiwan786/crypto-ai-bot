"""
Abstract base class defining the unified exchange adapter interface.

All exchange adapters must implement this interface so that the rest of
the system can interact with any supported exchange through the same API.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OrderSide(str, enum.Enum):
    """Side of a trade order."""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, enum.Enum):
    """Supported order types."""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class OrderStatus(str, enum.Enum):
    """Lifecycle status of an order."""
    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    PENDING = "pending"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ticker:
    """Snapshot of the latest ticker data for a trading pair.

    Attributes:
        symbol: Normalised pair (e.g. "BTC/USD").
        bid: Best bid price.
        ask: Best ask price.
        last: Last traded price.
        volume_24h: 24-hour volume in base currency.
        timestamp: Exchange timestamp (UTC).
        raw: Raw response from the exchange for debugging.
    """
    symbol: str
    bid: float
    ask: float
    last: float
    volume_24h: float
    timestamp: datetime
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class OHLCV:
    """Single OHLCV candle.

    Attributes:
        timestamp: Candle open time (UTC).
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Volume in base currency.
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class OrderResult:
    """Result of a create / cancel / fetch order operation.

    Attributes:
        order_id: Exchange-assigned order ID.
        symbol: Normalised pair.
        side: Buy or sell.
        order_type: Market, limit, etc.
        status: Current order status.
        price: Execution / limit price.
        amount: Order quantity in base currency.
        filled: Filled quantity.
        remaining: Unfilled quantity.
        cost: Total cost in quote currency.
        fee: Fee amount.
        fee_currency: Currency the fee was charged in.
        timestamp: Order creation timestamp (UTC).
        raw: Raw exchange response.
    """
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    price: float
    amount: float
    filled: float
    remaining: float
    cost: float
    fee: float = 0.0
    fee_currency: str = ""
    timestamp: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Balance:
    """Account balance snapshot.

    Attributes:
        currency: Currency code (e.g. "USD", "BTC").
        free: Available for trading.
        used: Currently locked in open orders.
        total: free + used.
    """
    currency: str
    free: float
    used: float
    total: float


@dataclass(frozen=True)
class ExchangeLimits:
    """Exchange trading limits for a specific pair.

    Attributes:
        min_order_amount: Minimum order size in base currency.
        max_order_amount: Maximum order size in base currency (0 = unlimited).
        min_order_cost: Minimum order value in quote currency.
        price_precision: Number of decimal places for price.
        amount_precision: Number of decimal places for amount.
        maker_fee: Maker fee as a decimal (e.g. 0.0016 = 0.16%).
        taker_fee: Taker fee as a decimal (e.g. 0.0026 = 0.26%).
    """
    min_order_amount: float
    max_order_amount: float
    min_order_cost: float
    price_precision: int
    amount_precision: int
    maker_fee: float
    taker_fee: float


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class BaseExchangeAdapter(ABC):
    """Abstract interface for exchange adapters.

    Implementations must support both public (no auth) and private
    (authenticated) operations.  Public-only adapters may raise
    ``ExchangeAuthError`` for private methods.
    """

    # -- Properties ----------------------------------------------------------

    @property
    @abstractmethod
    def exchange_id(self) -> str:
        """Canonical lowercase exchange identifier (e.g. ``"kraken"``)."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-friendly exchange name (e.g. ``"Kraken"``)."""

    # -- Connection ----------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Initialise the exchange connection (load markets, etc.)."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the exchange connection and release resources."""

    # -- Market data (public, no auth) ---------------------------------------

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Fetch the latest ticker for *symbol*.

        Args:
            symbol: Normalised pair (e.g. ``"BTC/USD"``).

        Returns:
            A ``Ticker`` snapshot.
        """

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
    ) -> list[OHLCV]:
        """Fetch OHLCV candles.

        Args:
            symbol: Normalised pair.
            timeframe: Candle interval (``"1m"``, ``"5m"``, ``"1h"``, etc.).
            limit: Maximum number of candles to return.

        Returns:
            A list of ``OHLCV`` candles ordered oldest-first.
        """

    @abstractmethod
    async def fetch_orderbook(
        self,
        symbol: str,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Fetch the order book for *symbol*.

        Args:
            symbol: Normalised pair.
            limit: Number of levels per side.

        Returns:
            A dict with ``"bids"`` and ``"asks"`` lists of ``[price, amount]``.
        """

    # -- Trading (auth required) ---------------------------------------------

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: float,
        price: float | None = None,
    ) -> OrderResult:
        """Place an order on the exchange.

        Args:
            symbol: Normalised pair.
            side: ``OrderSide.BUY`` or ``OrderSide.SELL``.
            order_type: ``OrderType.MARKET``, ``OrderType.LIMIT``, etc.
            amount: Order size in base currency.
            price: Limit price (required for limit orders).

        Returns:
            An ``OrderResult`` with the exchange-assigned order ID.
        """

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> OrderResult:
        """Cancel an open order.

        Args:
            order_id: Exchange-assigned order ID.
            symbol: Normalised pair.

        Returns:
            An ``OrderResult`` reflecting the cancellation.
        """

    @abstractmethod
    async def fetch_order(self, order_id: str, symbol: str) -> OrderResult:
        """Retrieve the current state of an order.

        Args:
            order_id: Exchange-assigned order ID.
            symbol: Normalised pair.

        Returns:
            An ``OrderResult`` with the latest status.
        """

    # -- Account (auth required) ---------------------------------------------

    @abstractmethod
    async def fetch_balance(self) -> list[Balance]:
        """Fetch all non-zero account balances.

        Returns:
            A list of ``Balance`` entries for each currency with a non-zero
            total.
        """

    # -- Exchange info -------------------------------------------------------

    @abstractmethod
    async def get_supported_pairs(self) -> list[str]:
        """Return all tradable pairs in normalised format."""

    @abstractmethod
    async def get_limits(self, symbol: str) -> ExchangeLimits:
        """Return trading limits / precision for *symbol*."""

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Test whether the configured API credentials are valid.

        Returns:
            ``True`` if the credentials authenticate successfully.
        """
