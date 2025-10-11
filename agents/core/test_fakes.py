"""
Test Fakes for Dependency Injection Testing.

Provides fake implementations of:
- FakeKrakenGateway (ExchangeClientProtocol)
- FakeRedisClient (RedisClientProtocol)
- FakeDataSource (DataSourceProtocol)

These fakes enable testing without network I/O.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Optional

from agents.core.types import MarketData


# ==============================================================================
# Fake Kraken Gateway
# ==============================================================================


class FakeKrakenGateway:
    """Fake Kraken gateway for testing (implements ExchangeClientProtocol)."""

    def __init__(self):
        """Initialize fake gateway."""
        self.orders: list[dict[str, Any]] = []
        self.order_count = 0
        self.fail_next = False  # Set to True to simulate failure

    async def fetch_ticker(self, symbol: str) -> dict[str, float]:
        """Fake ticker fetch."""
        return {
            "symbol": symbol,
            "bid": 50000.0,
            "ask": 50010.0,
            "last": 50005.0,
            "volume": 1000.0,
        }

    async def fetch_order_book(
        self, symbol: str, limit: int = 20
    ) -> dict[str, list[list[float]]]:
        """Fake order book fetch."""
        return {
            "bids": [[50000.0, 1.0], [49990.0, 2.0]],
            "asks": [[50010.0, 1.0], [50020.0, 2.0]],
        }

    async def create_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
    ) -> dict[str, Any]:
        """Fake order creation."""
        if self.fail_next:
            self.fail_next = False
            raise Exception("Simulated order failure")

        self.order_count += 1
        order_id = f"fake_order_{self.order_count}"

        order = {
            "id": order_id,
            "symbol": symbol,
            "type": order_type,
            "side": side,
            "amount": amount,
            "price": price or 50000.0,
            "filled": amount,  # Assume fully filled
            "average": price or 50000.0,
            "fee": {"cost": amount * (price or 50000.0) * 0.0015, "currency": "USD"},
            "timestamp": int(time.time() * 1000),
        }

        self.orders.append(order)
        return order


# ==============================================================================
# Fake Redis Client
# ==============================================================================


class FakeRedisClient:
    """Fake Redis client for testing (implements RedisClientProtocol)."""

    def __init__(self):
        """Initialize fake Redis."""
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.message_id_counter = 0

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        """Fake stream add."""
        self.message_id_counter += 1
        message_id = f"{int(time.time() * 1000)}-{self.message_id_counter}"

        if stream not in self.streams:
            self.streams[stream] = []

        self.streams[stream].append((message_id, fields))
        return message_id

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: Optional[int] = None,
        block: Optional[int] = None,
    ) -> list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]]:
        """Fake stream read."""
        # Simplified - return empty for now
        return []

    async def ping(self) -> bool:
        """Fake ping."""
        return True

    async def aclose(self) -> None:
        """Fake close."""
        pass

    def get_stream_length(self, stream: str) -> int:
        """Helper to check stream length."""
        return len(self.streams.get(stream, []))


# ==============================================================================
# Fake Data Source
# ==============================================================================


class FakeDataSource:
    """Fake data source for testing (implements DataSourceProtocol)."""

    def __init__(self, static_price: Decimal = Decimal("50000.0")):
        """Initialize fake data source.

        Args:
            static_price: Static price to return for all symbols
        """
        self.static_price = static_price
        self.fetch_count = 0

    async def fetch_market_data(self, symbol: str) -> MarketData:
        """Fake market data fetch."""
        self.fetch_count += 1

        return MarketData(
            symbol=symbol,
            timestamp=time.time(),
            bid=self.static_price - Decimal("10"),
            ask=self.static_price + Decimal("10"),
            last_price=self.static_price,
            volume=Decimal("1000"),
            spread_bps=20.0,
            mid_price=self.static_price,
        )

    async def fetch_multiple(self, symbols: list[str]) -> list[MarketData]:
        """Fake multiple fetch."""
        return [await self.fetch_market_data(sym) for sym in symbols]


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "FakeKrakenGateway",
    "FakeRedisClient",
    "FakeDataSource",
]
