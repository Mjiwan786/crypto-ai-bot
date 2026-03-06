"""
Binance Market Data Feed

Implements MarketDataFeed interface for Binance exchange using CCXT.
Publishes raw ticker data to market:raw:binance:{pair} Redis streams.

Note: Binance primarily uses USDT pairs, so BTC/USD is mapped to BTC/USDT.
The price is treated as USD-equivalent for synthetic price calculation.

Example:
    feed = BinanceFeed(config)
    await feed.connect()

    ticker = await feed.fetch_ticker("BTC/USD")
    print(ticker.price)  # 50000.0 (from BTC/USDT)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import ccxt.async_support as ccxt

from market_data.base import (
    DataSource,
    FeedStatus,
    MarketDataFeed,
    TickerData,
)

logger = logging.getLogger(__name__)


# Binance symbol mapping: internal -> Binance API format
# Binance uses USDT pairs primarily
BINANCE_SYMBOL_MAP = {
    "BTC/USD": "BTC/USDT",
    "ETH/USD": "ETH/USDT",
    "SOL/USD": "SOL/USDT",
    "LINK/USD": "LINK/USDT",
}

# Reverse mapping
BINANCE_SYMBOL_REVERSE = {v: k for k, v in BINANCE_SYMBOL_MAP.items()}


class BinanceFeed(MarketDataFeed):
    """Binance exchange market data feed.

    Uses CCXT for REST API access. Fetches ticker data including
    price, bid/ask, and volume.

    Note: Binance primarily uses USDT pairs. This feed maps USD pairs
    to their USDT equivalents (e.g., BTC/USD -> BTC/USDT) and treats
    USDT as USD-equivalent for price calculations.

    Attributes:
        exchange: "binance"
        _ccxt: CCXT Binance client instance
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Binance feed.

        Args:
            config: Optional configuration dictionary with keys:
                - symbol_map: Override symbol mappings
                - rate_limit_ms: Minimum ms between requests
                - use_us: Use Binance.US instead of global (default: False)
        """
        super().__init__("binance", config)

        self._ccxt: Optional[ccxt.binance] = None
        self._symbol_map = BINANCE_SYMBOL_MAP.copy()
        self._symbol_reverse = BINANCE_SYMBOL_REVERSE.copy()

        # Apply config overrides
        if config:
            if "symbol_map" in config:
                self._symbol_map.update(config["symbol_map"])
                self._symbol_reverse = {v: k for k, v in self._symbol_map.items()}

        self._rate_limit_ms = self._config.get("rate_limit_ms", 100)
        self._use_us = self._config.get("use_us", False)
        self._last_request_time: float = 0

    async def connect(self) -> None:
        """Establish connection to Binance API.

        Initializes CCXT client and loads market info.
        """
        self._status = FeedStatus.CONNECTING
        logger.info("Binance feed: Connecting...")

        try:
            # Get API credentials from environment (optional for public data)
            api_key = os.getenv("BINANCE_API_KEY")
            api_secret = os.getenv("BINANCE_API_SECRET")

            # Choose exchange class
            exchange_class = ccxt.binanceus if self._use_us else ccxt.binance

            # Initialize CCXT client
            self._ccxt = exchange_class({
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "timeout": 30000,
                "options": {
                    "defaultType": "spot",
                    "adjustForTimeDifference": True,
                },
            })

            # Test connection by loading markets
            await self._ccxt.load_markets()

            self._status = FeedStatus.CONNECTED
            exchange_name = "Binance.US" if self._use_us else "Binance"
            logger.info(
                f"{exchange_name} feed: Connected. {len(self._ccxt.markets)} markets loaded."
            )

        except Exception as e:
            self._status = FeedStatus.ERROR
            self._last_error = str(e)
            logger.error(f"Binance feed: Connection failed: {e}")
            raise

    async def disconnect(self) -> None:
        """Close connection to Binance."""
        logger.info("Binance feed: Disconnecting...")

        if self._ccxt:
            try:
                await self._ccxt.close()
            except Exception as e:
                logger.warning(f"Binance feed: Error during disconnect: {e}")

        self._ccxt = None
        self._status = FeedStatus.DISCONNECTED
        logger.info("Binance feed: Disconnected")

    async def fetch_ticker(self, pair: str) -> TickerData:
        """Fetch ticker data from Binance.

        Args:
            pair: Trading pair in internal format (e.g., "BTC/USD")

        Returns:
            TickerData with price, bid/ask, volume

        Raises:
            RuntimeError: If not connected
            Exception: If API call fails
        """
        if self._ccxt is None:
            raise RuntimeError("Binance feed not connected")

        # Rate limiting
        await self._enforce_rate_limit()

        start_time = time.time()
        exchange_pair = self.normalize_pair(pair)

        try:
            # Fetch ticker via CCXT
            ticker = await self._ccxt.fetch_ticker(exchange_pair)

            latency_ms = int((time.time() - start_time) * 1000)

            # Build TickerData
            # Note: We return the original internal pair format, not the exchange format
            ticker_data = TickerData(
                ts_ms=int(time.time() * 1000),
                exchange="binance",
                pair=pair,  # Return in internal format (BTC/USD, not BTC/USDT)
                price=float(ticker.get("last", 0) or ticker.get("close", 0)),
                bid=float(ticker["bid"]) if ticker.get("bid") else None,
                ask=float(ticker["ask"]) if ticker.get("ask") else None,
                volume=float(ticker.get("quoteVolume") or ticker.get("baseVolume", 0)),
                latency_ms=latency_ms,
                source=DataSource.REST.value,
            )

            self.record_success(latency_ms)
            logger.debug(
                f"Binance ticker {pair}: ${ticker_data.price:.2f} "
                f"(latency: {latency_ms}ms)"
            )

            return ticker_data

        except Exception as e:
            error_msg = f"Binance fetch_ticker failed for {pair}: {e}"
            self.record_error(error_msg)
            logger.error(error_msg)
            raise

    async def fetch_orderbook(
        self, pair: str, limit: int = 20
    ) -> Optional[Dict[str, Any]]:
        """Fetch order book from Binance.

        Args:
            pair: Trading pair in internal format
            limit: Number of levels to fetch

        Returns:
            Order book dict with 'bids' and 'asks'
        """
        if self._ccxt is None:
            raise RuntimeError("Binance feed not connected")

        await self._enforce_rate_limit()

        start_time = time.time()
        exchange_pair = self.normalize_pair(pair)

        try:
            book = await self._ccxt.fetch_order_book(exchange_pair, limit=limit)

            latency_ms = int((time.time() - start_time) * 1000)
            self.record_success(latency_ms)

            return {
                "bids": book["bids"],
                "asks": book["asks"],
                "timestamp": book.get("timestamp"),
            }

        except Exception as e:
            error_msg = f"Binance fetch_orderbook failed for {pair}: {e}"
            self.record_error(error_msg)
            logger.error(error_msg)
            raise

    def normalize_pair(self, pair: str) -> str:
        """Convert internal pair format to Binance format.

        Args:
            pair: Internal format (e.g., "BTC/USD")

        Returns:
            Binance format (e.g., "BTC/USDT")
        """
        return self._symbol_map.get(pair, pair)

    def denormalize_pair(self, exchange_pair: str) -> str:
        """Convert Binance format to internal pair format.

        Args:
            exchange_pair: Binance format (e.g., "BTC/USDT")

        Returns:
            Internal format (e.g., "BTC/USD")
        """
        return self._symbol_reverse.get(exchange_pair, exchange_pair)

    async def _enforce_rate_limit(self) -> None:
        """Enforce minimum delay between requests."""
        import asyncio

        now = time.time()
        elapsed_ms = (now - self._last_request_time) * 1000

        if elapsed_ms < self._rate_limit_ms:
            delay_ms = self._rate_limit_ms - elapsed_ms
            await asyncio.sleep(delay_ms / 1000)

        self._last_request_time = time.time()


# ==============================================================================
# Factory function
# ==============================================================================


def create_binance_feed(config: Optional[Dict[str, Any]] = None) -> BinanceFeed:
    """Create a Binance feed instance.

    Args:
        config: Optional configuration dictionary

    Returns:
        BinanceFeed instance
    """
    return BinanceFeed(config)


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "BinanceFeed",
    "create_binance_feed",
    "BINANCE_SYMBOL_MAP",
]
