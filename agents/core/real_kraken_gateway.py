"""
Real Kraken Gateway - Production implementation.

Implements ExchangeClientProtocol for real Kraken API calls.
Can be swapped with FakeKrakenGateway for testing.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import ccxt

from agents.core.types import ExchangeClientProtocol

logger = logging.getLogger(__name__)


class RealKrakenGateway:
    """Real Kraken gateway implementing ExchangeClientProtocol.

    This is a production-ready implementation that makes actual API calls
    to Kraken. It can be swapped with FakeKrakenGateway for testing.

    Example:
        # Production
        gateway = RealKrakenGateway(api_key="...", api_secret="...")

        # Testing
        gateway = FakeKrakenGateway()

        # Both implement same Protocol - no code changes needed!
        agent = ExecutionAgent(gateway=gateway)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        testnet: bool = False,
    ):
        """Initialize real Kraken gateway.

        Args:
            api_key: Kraken API key (optional for public endpoints)
            api_secret: Kraken API secret (optional for public endpoints)
            testnet: Use testnet instead of production
        """
        self.exchange = ccxt.kraken(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "timeout": 30000,
            }
        )

        if testnet:
            self.exchange.set_sandbox_mode(True)
            logger.info("Kraken gateway initialized (TESTNET)")
        else:
            logger.info("Kraken gateway initialized (PRODUCTION)")

    async def fetch_ticker(self, symbol: str) -> dict[str, float]:
        """Fetch real ticker data from Kraken.

        Args:
            symbol: Trading symbol (e.g., "BTC/USD")

        Returns:
            Ticker data dictionary

        Raises:
            Exception: If API call fails
        """
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "bid": float(ticker.get("bid", 0)),
                "ask": float(ticker.get("ask", 0)),
                "last": float(ticker.get("last", 0)),
                "volume": float(ticker.get("quoteVolume", 0)),
            }
        except Exception as e:
            logger.error(f"Failed to fetch ticker for {symbol}: {e}")
            raise

    async def fetch_order_book(
        self, symbol: str, limit: int = 20
    ) -> dict[str, list[list[float]]]:
        """Fetch real order book from Kraken.

        Args:
            symbol: Trading symbol
            limit: Number of levels to fetch

        Returns:
            Order book with bids and asks

        Raises:
            Exception: If API call fails
        """
        try:
            book = await self.exchange.fetch_order_book(symbol, limit=limit)
            return {
                "bids": book["bids"],
                "asks": book["asks"],
            }
        except Exception as e:
            logger.error(f"Failed to fetch order book for {symbol}: {e}")
            raise

    async def create_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
    ) -> dict[str, Any]:
        """Create real order on Kraken.

        Args:
            symbol: Trading symbol
            order_type: Order type (market, limit, etc.)
            side: Order side (buy, sell)
            amount: Order amount
            price: Order price (for limit orders)

        Returns:
            Order result dictionary

        Raises:
            Exception: If order placement fails
        """
        try:
            logger.info(
                f"Creating {side} {order_type} order: {amount} {symbol} @ {price or 'market'}"
            )

            order = await self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
            )

            logger.info(f"Order created: {order.get('id')}")
            return order

        except Exception as e:
            logger.error(f"Failed to create order: {e}")
            raise

    async def fetch_balance(self) -> dict[str, Any]:
        """Fetch account balance from Kraken.

        Returns:
            Balance dictionary

        Raises:
            Exception: If API call fails
        """
        try:
            balance = await self.exchange.fetch_balance()
            return balance
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            raise

    async def cancel_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        """Cancel order on Kraken.

        Args:
            order_id: Order ID to cancel
            symbol: Trading symbol

        Returns:
            Cancellation result

        Raises:
            Exception: If cancellation fails
        """
        try:
            result = await self.exchange.cancel_order(order_id, symbol)
            logger.info(f"Order cancelled: {order_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise

    async def close(self) -> None:
        """Close exchange connection."""
        if hasattr(self.exchange, "close"):
            await self.exchange.close()
        logger.info("Kraken gateway closed")


# ==============================================================================
# Factory Function
# ==============================================================================


def create_kraken_gateway(
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    testnet: bool = False,
    use_fake: bool = False,
) -> ExchangeClientProtocol:
    """Factory function to create appropriate gateway.

    Args:
        api_key: Kraken API key
        api_secret: Kraken API secret
        testnet: Use testnet
        use_fake: Return fake gateway for testing

    Returns:
        Gateway implementing ExchangeClientProtocol

    Example:
        # For production
        gateway = create_kraken_gateway(api_key="...", api_secret="...")

        # For testing
        gateway = create_kraken_gateway(use_fake=True)

        # Both return same Protocol interface!
    """
    if use_fake:
        from agents.core.test_fakes import FakeKrakenGateway

        logger.info("Creating FAKE Kraken gateway for testing")
        return FakeKrakenGateway()
    else:
        logger.info("Creating REAL Kraken gateway")
        return RealKrakenGateway(api_key=api_key, api_secret=api_secret, testnet=testnet)


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "RealKrakenGateway",
    "create_kraken_gateway",
]
