"""
Kraken Market Data Feed

Implements MarketDataFeed interface for Kraken exchange using CCXT.
Publishes raw ticker data to market:raw:kraken:{pair} Redis streams.

Example:
    feed = KrakenFeed(config)
    await feed.connect()

    ticker = await feed.fetch_ticker("BTC/USD")
    print(ticker.price)  # 50000.0
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


# Kraken symbol mapping: internal -> CCXT unified format
# NOTE: CCXT handles XBT<->BTC conversion internally, so we use BTC/USD
# Do NOT map to XBT/USD - CCXT expects unified format
KRAKEN_SYMBOL_MAP = {
    "BTC/USD": "BTC/USD",  # CCXT handles XBT conversion
    "ETH/USD": "ETH/USD",
    "SOL/USD": "SOL/USD",
    "LINK/USD": "LINK/USD",
}

# Reverse mapping
KRAKEN_SYMBOL_REVERSE = {v: k for k, v in KRAKEN_SYMBOL_MAP.items()}


class KrakenFeed(MarketDataFeed):
    """Kraken exchange market data feed.

    Uses CCXT for REST API access. Fetches ticker data including
    price, bid/ask, and volume.

    Attributes:
        exchange: "kraken"
        _ccxt: CCXT Kraken client instance
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Kraken feed.

        Args:
            config: Optional configuration dictionary with keys:
                - symbol_map: Override symbol mappings
                - rate_limit_ms: Minimum ms between requests
                - sandbox: Use sandbox mode (default: False)
        """
        super().__init__("kraken", config)

        self._ccxt: Optional[ccxt.kraken] = None
        self._symbol_map = KRAKEN_SYMBOL_MAP.copy()
        self._symbol_reverse = KRAKEN_SYMBOL_REVERSE.copy()

        # Apply config overrides
        if config:
            if "symbol_map" in config:
                self._symbol_map.update(config["symbol_map"])
                self._symbol_reverse = {v: k for k, v in self._symbol_map.items()}

        self._rate_limit_ms = self._config.get("rate_limit_ms", 1000)
        self._last_request_time: float = 0

    async def connect(self) -> None:
        """Establish connection to Kraken API.

        Initializes CCXT client and loads market info.
        """
        self._status = FeedStatus.CONNECTING
        logger.info("Kraken feed: Connecting...")

        try:
            # Get API credentials from environment (optional for public data)
            api_key = os.getenv("KRAKEN_API_KEY")
            api_secret = os.getenv("KRAKEN_API_SECRET")

            # Initialize CCXT client
            self._ccxt = ccxt.kraken({
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "timeout": 30000,
                "options": {
                    "defaultType": "spot",
                },
            })

            # Test connection by loading markets
            await self._ccxt.load_markets()

            self._status = FeedStatus.CONNECTED
            logger.info(
                f"Kraken feed: Connected. {len(self._ccxt.markets)} markets loaded."
            )

        except Exception as e:
            self._status = FeedStatus.ERROR
            self._last_error = str(e)
            logger.error(f"Kraken feed: Connection failed: {e}")
            raise

    async def disconnect(self) -> None:
        """Close connection to Kraken."""
        logger.info("Kraken feed: Disconnecting...")

        if self._ccxt:
            try:
                await self._ccxt.close()
            except Exception as e:
                logger.warning(f"Kraken feed: Error during disconnect: {e}")

        self._ccxt = None
        self._status = FeedStatus.DISCONNECTED
        logger.info("Kraken feed: Disconnected")

    async def fetch_ticker(self, pair: str) -> TickerData:
        """Fetch ticker data from Kraken.

        Args:
            pair: Trading pair in internal format (e.g., "BTC/USD")

        Returns:
            TickerData with price, bid/ask, volume

        Raises:
            RuntimeError: If not connected
            Exception: If API call fails
        """
        if self._ccxt is None:
            raise RuntimeError("Kraken feed not connected")

        # Rate limiting
        await self._enforce_rate_limit()

        start_time = time.time()
        exchange_pair = self.normalize_pair(pair)

        try:
            # Fetch ticker via CCXT
            ticker = await self._ccxt.fetch_ticker(exchange_pair)

            latency_ms = int((time.time() - start_time) * 1000)

            # Build TickerData
            ticker_data = TickerData(
                ts_ms=int(time.time() * 1000),
                exchange="kraken",
                pair=pair,  # Return in internal format
                price=float(ticker.get("last", 0) or ticker.get("close", 0)),
                bid=float(ticker["bid"]) if ticker.get("bid") else None,
                ask=float(ticker["ask"]) if ticker.get("ask") else None,
                volume=float(ticker.get("quoteVolume") or ticker.get("baseVolume", 0)),
                latency_ms=latency_ms,
                source=DataSource.REST.value,
            )

            self.record_success(latency_ms)
            logger.debug(
                f"Kraken ticker {pair}: ${ticker_data.price:.2f} "
                f"(latency: {latency_ms}ms)"
            )

            return ticker_data

        except Exception as e:
            error_msg = f"Kraken fetch_ticker failed for {pair}: {e}"
            self.record_error(error_msg)
            logger.error(error_msg)
            raise

    async def fetch_orderbook(
        self, pair: str, limit: int = 20
    ) -> Optional[Dict[str, Any]]:
        """Fetch order book from Kraken.

        Args:
            pair: Trading pair in internal format
            limit: Number of levels to fetch

        Returns:
            Order book dict with 'bids' and 'asks'
        """
        if self._ccxt is None:
            raise RuntimeError("Kraken feed not connected")

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
            error_msg = f"Kraken fetch_orderbook failed for {pair}: {e}"
            self.record_error(error_msg)
            logger.error(error_msg)
            raise

    def normalize_pair(self, pair: str) -> str:
        """Convert internal pair format to Kraken format.

        Args:
            pair: Internal format (e.g., "BTC/USD")

        Returns:
            Kraken format (e.g., "XBT/USD")
        """
        return self._symbol_map.get(pair, pair)

    def denormalize_pair(self, exchange_pair: str) -> str:
        """Convert Kraken format to internal pair format.

        Args:
            exchange_pair: Kraken format (e.g., "XBT/USD")

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


def create_kraken_feed(config: Optional[Dict[str, Any]] = None) -> KrakenFeed:
    """Create a Kraken feed instance.

    Args:
        config: Optional configuration dictionary

    Returns:
        KrakenFeed instance
    """
    return KrakenFeed(config)


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "KrakenFeed",
    "create_kraken_feed",
    "KRAKEN_SYMBOL_MAP",
]
