"""
WebSocket adapter interface for real-time exchange data.

Extends the exchange adapter layer with streaming capabilities using
CCXT Pro. Publishes all data to Redis streams in the same format as
the existing Kraken production engine, so downstream consumers work
unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TickerUpdate:
    """Real-time ticker snapshot from a WebSocket feed."""
    exchange: str
    symbol: str
    bid: float
    ask: float
    last: float
    volume_24h: float
    timestamp: datetime


@dataclass(frozen=True)
class OHLCVUpdate:
    """Real-time OHLCV candle update from a WebSocket feed."""
    exchange: str
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class TradeUpdate:
    """Real-time trade from a WebSocket feed."""
    exchange: str
    symbol: str
    side: str       # 'buy' or 'sell'
    price: float
    amount: float
    timestamp: datetime


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class BaseWSAdapter(ABC):
    """Abstract WebSocket adapter for real-time exchange data.

    Implementations should handle reconnection internally with
    exponential backoff.
    """

    @property
    @abstractmethod
    def exchange_id(self) -> str:
        """Canonical lowercase exchange identifier."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the adapter currently has an active connection."""

    @abstractmethod
    async def connect(self) -> None:
        """Initialise the WebSocket connection (load markets, etc.)."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close all WebSocket connections."""

    @abstractmethod
    async def watch_ticker(self, symbol: str) -> AsyncIterator[TickerUpdate]:
        """Stream real-time ticker updates for *symbol*."""

    @abstractmethod
    async def watch_ohlcv(
        self, symbol: str, timeframe: str = "1m"
    ) -> AsyncIterator[OHLCVUpdate]:
        """Stream real-time OHLCV candle updates for *symbol*."""

    @abstractmethod
    async def watch_trades(self, symbol: str) -> AsyncIterator[TradeUpdate]:
        """Stream real-time trade feed for *symbol*."""

    @abstractmethod
    async def watch_order_book(
        self, symbol: str, limit: int = 20
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream real-time order book snapshots for *symbol*."""
