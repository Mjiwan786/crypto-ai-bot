"""
Market Data Layer

Platform-grade multi-exchange data feeds and internal synthetic price engine.

This module provides:
- MarketDataFeed: Abstract interface for exchange data feeds
- KrakenFeed: Kraken exchange implementation
- BinanceFeed: Binance exchange implementation
- MarketDataOrchestrator: Coordinates multiple exchange feeds
- PriceEngine: Computes synthetic prices from multi-exchange data

Redis Stream Namespaces (new, separate from signals:*):
- market:raw:{exchange}:{pair}  - Raw ticker data from exchanges
- market:price:{pair}           - Synthetic weighted prices
- market:spread:{pair}          - Spread estimates
- exchange:health:{exchange}    - Exchange health status

Example:
    from market_data import MarketDataOrchestrator, PriceEngine

    # Start market data collection
    orchestrator = await MarketDataOrchestrator.from_config("config/market_data.yaml")
    await orchestrator.start()

    # Get synthetic prices
    engine = PriceEngine(orchestrator)
    await engine.start()
"""

from market_data.base import (
    MarketDataFeed,
    TickerData,
    FeedHealth,
    FeedStatus,
)
from market_data.kraken_feed import KrakenFeed
from market_data.binance_feed import BinanceFeed
from market_data.orchestrator import MarketDataOrchestrator
from market_data.price_engine import PriceEngine
from market_data.config import MarketDataConfig, load_market_data_config

__all__ = [
    # Base types
    "MarketDataFeed",
    "TickerData",
    "FeedHealth",
    "FeedStatus",
    # Implementations
    "KrakenFeed",
    "BinanceFeed",
    # Orchestration
    "MarketDataOrchestrator",
    "PriceEngine",
    # Config
    "MarketDataConfig",
    "load_market_data_config",
]
