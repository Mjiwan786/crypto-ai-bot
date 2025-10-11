"""
Market Scanner - Scheduler with injected data source.

Pure scheduler that pulls market data via injected Protocol.
No hardcoded exchange dependencies.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from agents.core.types import MarketData

logger = logging.getLogger(__name__)


# ==============================================================================
# Data Source Protocol
# ==============================================================================


class DataSourceProtocol(Protocol):
    """Protocol for market data source."""

    async def fetch_market_data(self, symbol: str) -> MarketData:
        """Fetch market data for symbol.

        Args:
            symbol: Trading symbol

        Returns:
            MarketData snapshot
        """
        ...

    async def fetch_multiple(self, symbols: list[str]) -> list[MarketData]:
        """Fetch market data for multiple symbols.

        Args:
            symbols: List of trading symbols

        Returns:
            List of MarketData snapshots
        """
        ...


# ==============================================================================
# Scanner Functions
# ==============================================================================


async def scan(
    symbols: list[str],
    data_source: DataSourceProtocol,
) -> list[MarketData]:
    """Scan market data for symbols (pure function with injected source).

    Args:
        symbols: List of symbols to scan
        data_source: Data source protocol (injected)

    Returns:
        List of market data snapshots

    Examples:
        >>> fake_source = FakeDataSource()
        >>> data = await scan(["BTC/USD", "ETH/USD"], fake_source)
        >>> assert len(data) == 2
    """
    try:
        return await data_source.fetch_multiple(symbols)
    except Exception as e:
        logger.error(f"Scan failed: {e}")
        return []


# ==============================================================================
# Market Scanner Class
# ==============================================================================


class MarketScanner:
    """Market scanner with injected data source."""

    def __init__(
        self,
        symbols: list[str],
        data_source: DataSourceProtocol,
        interval_seconds: int = 60,
    ):
        """Initialize market scanner.

        Args:
            symbols: List of symbols to scan
            data_source: Data source protocol (injected)
            interval_seconds: Scan interval
        """
        self.symbols = symbols
        self.data_source = data_source
        self.interval_seconds = interval_seconds
        self.running = False
        logger.info(f"MarketScanner initialized for {len(symbols)} symbols (interval={interval_seconds}s)")

    async def scan_once(self) -> list[MarketData]:
        """Perform single scan."""
        return await scan(self.symbols, self.data_source)

    async def start(self) -> None:
        """Start continuous scanning."""
        self.running = True
        logger.info("MarketScanner started")

        while self.running:
            try:
                data = await self.scan_once()
                logger.info(f"Scanned {len(data)} symbols")

                # Yield control
                await asyncio.sleep(self.interval_seconds)

            except Exception as e:
                logger.error(f"Scanner error: {e}")
                await asyncio.sleep(self.interval_seconds)

    def stop(self) -> None:
        """Stop scanning."""
        self.running = False
        logger.info("MarketScanner stopped")


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "scan",
    "MarketScanner",
    "DataSourceProtocol",
]
