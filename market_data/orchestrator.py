"""
Market Data Orchestrator

Coordinates multiple exchange feeds and publishes data to Redis streams.
Manages feed lifecycle, health monitoring, and data collection.

Redis Stream Namespaces:
- market:raw:{exchange}:{pair}  - Raw ticker data (e.g., market:raw:kraken:BTC-USD)
- exchange:health:{exchange}    - Exchange health status

Example:
    from market_data.orchestrator import MarketDataOrchestrator

    orchestrator = await MarketDataOrchestrator.from_config("config/market_data.yaml")
    await orchestrator.start()

    # Run for a while...

    await orchestrator.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Type

from market_data.base import (
    FeedHealth,
    FeedStatus,
    MarketDataFeed,
    TickerData,
    internal_to_stream,
)
from market_data.config import MarketDataConfig, load_market_data_config
from market_data.kraken_feed import KrakenFeed
from market_data.binance_feed import BinanceFeed

logger = logging.getLogger(__name__)


# Registry of available feed implementations
FEED_REGISTRY: Dict[str, Type[MarketDataFeed]] = {
    "kraken": KrakenFeed,
    "binance": BinanceFeed,
}


class MarketDataOrchestrator:
    """Orchestrates multiple exchange data feeds.

    Manages the lifecycle of exchange feeds, coordinates data collection,
    publishes to Redis streams, and monitors health.

    Attributes:
        config: Market data configuration
        feeds: Dictionary of active feed instances
        latest_tickers: Latest ticker data per (exchange, pair)
    """

    def __init__(
        self,
        config: MarketDataConfig,
        redis_client: Optional[Any] = None,
    ):
        """Initialize orchestrator.

        Args:
            config: Market data configuration
            redis_client: Optional Redis client for publishing
        """
        self.config = config
        self._redis = redis_client
        self._feeds: Dict[str, MarketDataFeed] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []

        # Latest data storage (in-memory cache)
        self._latest_tickers: Dict[str, Dict[str, TickerData]] = {}
        self._latest_health: Dict[str, FeedHealth] = {}

        # Statistics
        self._tick_count = 0
        self._error_count = 0
        self._start_time: Optional[float] = None

    @classmethod
    async def from_config(
        cls,
        config_path: Optional[str] = None,
        redis_client: Optional[Any] = None,
    ) -> MarketDataOrchestrator:
        """Create orchestrator from config file.

        Args:
            config_path: Path to market_data.yaml
            redis_client: Optional Redis client

        Returns:
            Configured MarketDataOrchestrator instance
        """
        config = load_market_data_config(config_path)
        return cls(config, redis_client)

    async def start(self) -> None:
        """Start the orchestrator and all feeds.

        Connects to all configured exchanges and begins data collection.
        """
        if self._running:
            logger.warning("Orchestrator already running")
            return

        if not self.config.feature_flags.market_data_enabled:
            logger.warning("Market data feature flag is disabled. Not starting.")
            return

        logger.info(
            f"Starting Market Data Orchestrator: "
            f"{len(self.config.enabled_exchanges)} exchanges, "
            f"{len(self.config.pairs)} pairs"
        )

        self._running = True
        self._start_time = time.time()

        # Initialize and connect feeds
        await self._initialize_feeds()

        # Start polling loops
        self._start_polling_tasks()

        # Start health monitoring
        if self.config.feature_flags.health_monitoring:
            self._tasks.append(
                asyncio.create_task(self._health_monitor_loop())
            )

        logger.info("Market Data Orchestrator started")

    async def stop(self) -> None:
        """Stop the orchestrator and all feeds.

        Gracefully shuts down polling, disconnects feeds, and cleans up.
        """
        if not self._running:
            return

        logger.info("Stopping Market Data Orchestrator...")
        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._tasks.clear()

        # Disconnect all feeds
        for exchange, feed in self._feeds.items():
            try:
                await feed.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting {exchange}: {e}")

        self._feeds.clear()

        # Log final stats
        if self._start_time:
            runtime = time.time() - self._start_time
            logger.info(
                f"Orchestrator stopped. Runtime: {runtime:.1f}s, "
                f"Ticks: {self._tick_count}, Errors: {self._error_count}"
            )

    async def _initialize_feeds(self) -> None:
        """Initialize and connect all configured feeds."""
        for exchange in self.config.enabled_exchanges:
            if exchange not in FEED_REGISTRY:
                logger.warning(f"Unknown exchange: {exchange}. Skipping.")
                continue

            try:
                # Get exchange-specific config
                override = self.config.exchange_overrides.get(exchange)
                feed_config = {}
                if override:
                    feed_config = {
                        "symbol_map": override.symbol_map,
                        "rate_limit_ms": override.rate_limit_ms,
                    }

                # Create feed instance
                feed_class = FEED_REGISTRY[exchange]
                feed = feed_class(feed_config)

                # Connect
                await feed.connect()

                self._feeds[exchange] = feed
                self._latest_tickers[exchange] = {}

                logger.info(f"Feed initialized: {exchange}")

            except Exception as e:
                logger.error(f"Failed to initialize {exchange} feed: {e}")

    def _start_polling_tasks(self) -> None:
        """Start polling tasks for each exchange/pair combination."""
        for exchange in self._feeds:
            for pair in self.config.pairs:
                task = asyncio.create_task(
                    self._poll_ticker(exchange, pair)
                )
                self._tasks.append(task)

    async def _poll_ticker(self, exchange: str, pair: str) -> None:
        """Polling loop for a single exchange/pair.

        Args:
            exchange: Exchange name
            pair: Trading pair in internal format
        """
        feed = self._feeds.get(exchange)
        if not feed:
            return

        interval = self.config.polling.interval_sec
        logger.debug(f"Starting poll loop: {exchange}:{pair} (interval: {interval}s)")

        while self._running:
            try:
                # Fetch ticker
                ticker = await feed.fetch_ticker(pair)

                # Store in memory
                self._latest_tickers[exchange][pair] = ticker

                # Publish to Redis
                await self._publish_raw_ticker(ticker)

                self._tick_count += 1

                # Log periodically
                if self._tick_count % self.config.logging.log_every_n_ticks == 0:
                    logger.info(
                        f"Tick #{self._tick_count}: {exchange}:{pair} = ${ticker.price:.2f}"
                    )

            except Exception as e:
                self._error_count += 1
                logger.error(f"Poll error {exchange}:{pair}: {e}")

            # Wait for next poll
            await asyncio.sleep(interval)

    async def _publish_raw_ticker(self, ticker: TickerData) -> None:
        """Publish raw ticker data to Redis stream.

        Stream: market:raw:{exchange}:{pair}
        Example: market:raw:kraken:BTC-USD

        Args:
            ticker: Ticker data to publish
        """
        if self._redis is None:
            return

        try:
            # Build stream name
            stream_pair = internal_to_stream(ticker.pair)
            stream_name = self.config.redis.streams.raw_ticker.format(
                exchange=ticker.exchange,
                pair=stream_pair,
            )

            # Convert to Redis format (all strings)
            fields = ticker.to_dict()

            # Publish via XADD
            maxlen = self.config.redis.maxlen.raw_ticker
            await self._redis.xadd(
                stream_name,
                fields,
                maxlen=maxlen,
            )

            if self.config.logging.log_price_updates:
                logger.debug(f"Published to {stream_name}: ${ticker.price:.2f}")

        except Exception as e:
            logger.error(f"Failed to publish ticker to Redis: {e}")

    async def _health_monitor_loop(self) -> None:
        """Periodically check and publish feed health."""
        interval = self.config.health.heartbeat_interval_sec

        while self._running:
            for exchange, feed in self._feeds.items():
                try:
                    health = feed.get_health()
                    self._latest_health[exchange] = health

                    await self._publish_health(health)

                except Exception as e:
                    logger.error(f"Health check error for {exchange}: {e}")

            await asyncio.sleep(interval)

    async def _publish_health(self, health: FeedHealth) -> None:
        """Publish exchange health to Redis stream.

        Stream: exchange:health:{exchange}
        Example: exchange:health:kraken

        Args:
            health: Feed health status
        """
        if self._redis is None:
            return

        try:
            stream_name = self.config.redis.streams.exchange_health.format(
                exchange=health.exchange,
            )

            fields = health.to_dict()
            maxlen = self.config.redis.maxlen.exchange_health

            await self._redis.xadd(
                stream_name,
                fields,
                maxlen=maxlen,
            )

        except Exception as e:
            logger.error(f"Failed to publish health to Redis: {e}")

    # ==========================================================================
    # Public API
    # ==========================================================================

    def get_latest_ticker(
        self, exchange: str, pair: str
    ) -> Optional[TickerData]:
        """Get latest cached ticker for an exchange/pair.

        Args:
            exchange: Exchange name
            pair: Trading pair in internal format

        Returns:
            Latest TickerData or None if not available
        """
        return self._latest_tickers.get(exchange, {}).get(pair)

    def get_all_latest_tickers(self, pair: str) -> Dict[str, TickerData]:
        """Get latest tickers from all exchanges for a pair.

        Args:
            pair: Trading pair in internal format

        Returns:
            Dict of exchange -> TickerData
        """
        result = {}
        for exchange, tickers in self._latest_tickers.items():
            if pair in tickers:
                result[exchange] = tickers[pair]
        return result

    def get_health(self, exchange: str) -> Optional[FeedHealth]:
        """Get latest health status for an exchange.

        Args:
            exchange: Exchange name

        Returns:
            FeedHealth or None if not available
        """
        return self._latest_health.get(exchange)

    def get_all_health(self) -> Dict[str, FeedHealth]:
        """Get health status for all exchanges.

        Returns:
            Dict of exchange -> FeedHealth
        """
        return self._latest_health.copy()

    @property
    def is_running(self) -> bool:
        """Check if orchestrator is running."""
        return self._running

    @property
    def stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        runtime = 0.0
        if self._start_time:
            runtime = time.time() - self._start_time

        return {
            "running": self._running,
            "runtime_seconds": runtime,
            "tick_count": self._tick_count,
            "error_count": self._error_count,
            "exchanges": list(self._feeds.keys()),
            "pairs": self.config.pairs,
            "ticks_per_second": self._tick_count / runtime if runtime > 0 else 0,
        }


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "MarketDataOrchestrator",
    "FEED_REGISTRY",
]
