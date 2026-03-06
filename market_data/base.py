"""
Market Data Feed Interface

Abstract base class and data types for exchange market data feeds.
All feed implementations (Kraken, Binance, etc.) must implement this interface.

Example:
    class KrakenFeed(MarketDataFeed):
        async def fetch_ticker(self, pair: str) -> TickerData:
            # Implementation
            pass
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


# ==============================================================================
# Enums
# ==============================================================================


class FeedStatus(str, Enum):
    """Feed connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"


class DataSource(str, Enum):
    """Source of market data."""

    REST = "rest"
    WEBSOCKET = "websocket"
    CACHED = "cached"


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class TickerData:
    """Raw ticker data from an exchange.

    Contains price, bid/ask, volume, and metadata about the data fetch.

    Attributes:
        ts_ms: Timestamp in milliseconds (Unix epoch)
        exchange: Exchange name (e.g., "kraken")
        pair: Trading pair in internal format (e.g., "BTC/USD")
        price: Last trade price
        bid: Best bid price (optional)
        ask: Best ask price (optional)
        volume: 24h volume (optional)
        latency_ms: Time taken to fetch data in ms
        source: Data source (REST, WebSocket, etc.)
    """

    ts_ms: int
    exchange: str
    pair: str
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[float] = None
    latency_ms: int = 0
    source: str = "rest"

    @property
    def ts_seconds(self) -> float:
        """Timestamp in seconds."""
        return self.ts_ms / 1000.0

    @property
    def spread(self) -> Optional[float]:
        """Bid-ask spread if available."""
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    @property
    def spread_pct(self) -> Optional[float]:
        """Spread as percentage of mid price."""
        if self.bid is not None and self.ask is not None and self.bid > 0:
            mid = (self.bid + self.ask) / 2
            return ((self.ask - self.bid) / mid) * 100
        return None

    def to_dict(self) -> Dict[str, str]:
        """Convert to string dict for Redis publishing."""
        return {
            "ts_ms": str(self.ts_ms),
            "exchange": self.exchange,
            "pair": self.pair,
            "price": str(self.price),
            "bid": str(self.bid) if self.bid is not None else "",
            "ask": str(self.ask) if self.ask is not None else "",
            "volume": str(self.volume) if self.volume is not None else "",
            "latency_ms": str(self.latency_ms),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> TickerData:
        """Create from Redis dict format."""
        return cls(
            ts_ms=int(data["ts_ms"]),
            exchange=data["exchange"],
            pair=data["pair"],
            price=float(data["price"]),
            bid=float(data["bid"]) if data.get("bid") else None,
            ask=float(data["ask"]) if data.get("ask") else None,
            volume=float(data["volume"]) if data.get("volume") else None,
            latency_ms=int(data.get("latency_ms", "0")),
            source=data.get("source", "rest"),
        )

    def to_json_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict (non-string values)."""
        return {
            "ts_ms": self.ts_ms,
            "exchange": self.exchange,
            "pair": self.pair,
            "price": self.price,
            "bid": self.bid,
            "ask": self.ask,
            "volume": self.volume,
            "latency_ms": self.latency_ms,
            "source": self.source,
        }


@dataclass
class FeedHealth:
    """Health status of a market data feed.

    Used for monitoring and alerting on feed status.

    Attributes:
        exchange: Exchange name
        status: Current feed status
        last_ok_ts_ms: Last successful data fetch timestamp (ms)
        last_error: Last error message (if any)
        errors_5m: Error count in last 5 minutes
        avg_latency_ms: Average latency in ms
        timestamp: When this health check was created
    """

    exchange: str
    status: FeedStatus
    last_ok_ts_ms: Optional[int] = None
    last_error: Optional[str] = None
    errors_5m: int = 0
    avg_latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    @property
    def is_healthy(self) -> bool:
        """Check if feed is in a healthy state."""
        return self.status == FeedStatus.CONNECTED and self.errors_5m < 5

    @property
    def seconds_since_ok(self) -> Optional[float]:
        """Seconds since last successful data fetch."""
        if self.last_ok_ts_ms is None:
            return None
        return (time.time() * 1000 - self.last_ok_ts_ms) / 1000.0

    def to_dict(self) -> Dict[str, str]:
        """Convert to string dict for Redis publishing."""
        return {
            "exchange": self.exchange,
            "status": self.status.value,
            "last_ok_ts_ms": str(self.last_ok_ts_ms) if self.last_ok_ts_ms else "",
            "last_error": self.last_error or "",
            "errors_5m": str(self.errors_5m),
            "avg_latency_ms": str(int(self.avg_latency_ms)),
            "timestamp": str(int(self.timestamp * 1000)),
            "is_healthy": str(self.is_healthy).lower(),
        }


# ==============================================================================
# Protocol / Interface
# ==============================================================================


class MarketDataFeed(ABC):
    """Abstract base class for market data feeds.

    All exchange feed implementations must inherit from this class
    and implement the abstract methods.

    Example:
        class KrakenFeed(MarketDataFeed):
            def __init__(self, config: Dict[str, Any]):
                super().__init__("kraken", config)

            async def fetch_ticker(self, pair: str) -> TickerData:
                # Fetch from Kraken API
                pass
    """

    def __init__(self, exchange: str, config: Optional[Dict[str, Any]] = None):
        """Initialize market data feed.

        Args:
            exchange: Exchange name (e.g., "kraken", "binance")
            config: Optional configuration dictionary
        """
        self.exchange = exchange.lower()
        self._config = config or {}
        self._status = FeedStatus.DISCONNECTED
        self._last_ok_ts_ms: Optional[int] = None
        self._last_error: Optional[str] = None
        self._error_timestamps: List[float] = []
        self._latency_samples: List[float] = []
        self._max_latency_samples = 100

    @property
    def status(self) -> FeedStatus:
        """Current feed status."""
        return self._status

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the exchange.

        Should initialize any API clients, load markets, etc.
        Sets status to CONNECTED on success.

        Raises:
            Exception: If connection fails
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the exchange.

        Should clean up resources and set status to DISCONNECTED.
        """
        pass

    @abstractmethod
    async def fetch_ticker(self, pair: str) -> TickerData:
        """Fetch current ticker data for a trading pair.

        Args:
            pair: Trading pair in internal format (e.g., "BTC/USD")

        Returns:
            TickerData with current price, bid/ask, volume

        Raises:
            Exception: If fetch fails
        """
        pass

    async def fetch_orderbook(
        self, pair: str, limit: int = 20
    ) -> Optional[Dict[str, Any]]:
        """Fetch order book data (optional implementation).

        Args:
            pair: Trading pair in internal format
            limit: Number of levels to fetch

        Returns:
            Order book dict with 'bids' and 'asks', or None if not supported
        """
        return None

    def get_health(self) -> FeedHealth:
        """Get current health status of the feed.

        Returns:
            FeedHealth with status, errors, latency info
        """
        # Clean old errors (older than 5 minutes)
        cutoff = time.time() - 300
        self._error_timestamps = [ts for ts in self._error_timestamps if ts > cutoff]

        # Calculate average latency
        avg_latency = 0.0
        if self._latency_samples:
            avg_latency = sum(self._latency_samples) / len(self._latency_samples)

        return FeedHealth(
            exchange=self.exchange,
            status=self._status,
            last_ok_ts_ms=self._last_ok_ts_ms,
            last_error=self._last_error,
            errors_5m=len(self._error_timestamps),
            avg_latency_ms=avg_latency,
        )

    def record_success(self, latency_ms: float) -> None:
        """Record a successful data fetch.

        Args:
            latency_ms: Time taken to fetch data in milliseconds
        """
        self._last_ok_ts_ms = int(time.time() * 1000)
        self._last_error = None

        # Track latency
        self._latency_samples.append(latency_ms)
        if len(self._latency_samples) > self._max_latency_samples:
            self._latency_samples.pop(0)

        # Ensure status is connected
        if self._status != FeedStatus.CONNECTED:
            self._status = FeedStatus.CONNECTED

    def record_error(self, error: str) -> None:
        """Record a data fetch error.

        Args:
            error: Error message
        """
        self._last_error = error
        self._error_timestamps.append(time.time())

        # If too many errors, mark as errored
        if len(self._error_timestamps) >= 5:
            self._status = FeedStatus.ERROR

    def normalize_pair(self, pair: str) -> str:
        """Convert internal pair format to exchange-specific format.

        Default implementation returns pair unchanged.
        Override in subclasses for exchange-specific normalization.

        Args:
            pair: Internal format (e.g., "BTC/USD")

        Returns:
            Exchange-specific format
        """
        return pair


# ==============================================================================
# Utility Functions
# ==============================================================================


def internal_to_stream(pair: str) -> str:
    """Convert internal pair format to stream format.

    Args:
        pair: Internal format (e.g., "BTC/USD")

    Returns:
        Stream format (e.g., "BTC-USD")
    """
    return pair.replace("/", "-")


def stream_to_internal(pair: str) -> str:
    """Convert stream pair format to internal format.

    Args:
        pair: Stream format (e.g., "BTC-USD")

    Returns:
        Internal format (e.g., "BTC/USD")
    """
    return pair.replace("-", "/")


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    # Enums
    "FeedStatus",
    "DataSource",
    # Data classes
    "TickerData",
    "FeedHealth",
    # Interface
    "MarketDataFeed",
    # Utilities
    "internal_to_stream",
    "stream_to_internal",
]
