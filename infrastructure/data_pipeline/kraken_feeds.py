"""
Real‑time market data feeds for Kraken.

This module provides a stub implementation of a WebSocket client that
connects to Kraken's public market data API and yields price updates.
For production use you should consider using the official Kraken WebSocket
API via the `websocket-client` package or `ccxt` with websockets support.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Iterable, List

try:
    import websockets  # type: ignore
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore


logger = logging.getLogger(__name__)


class KrakenFeed:
    """A simplistic asynchronous WebSocket client for Kraken trades."""

    def __init__(self, pairs: Iterable[str]) -> None:
        self.pairs = list(pairs)
        self.url = "wss://ws.kraken.com"
        self._task: Optional[asyncio.Task] = None

    async def _subscribe(self, websocket) -> None:
        subscribe_msg = {
            "event": "subscribe",
            "pair": self.pairs,
            "subscription": {"name": "trade"},
        }
        await websocket.send(json.dumps(subscribe_msg))
        logger.info("Subscribed to Kraken trade feed for %s", ",".join(self.pairs))

    async def stream_trades(self) -> AsyncIterator[dict]:
        """Asynchronously yield trade messages as dictionaries."""
        if websockets is None:
            raise RuntimeError("websockets package is required for KrakenFeed")
        async with websockets.connect(self.url) as websocket:
            await self._subscribe(websocket)
            async for message in websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue
                # Kraken returns heartbeat and system status events as dicts
                if isinstance(data, dict):
                    continue
                # Trade messages come as [channelID, trades, pair]
                if len(data) >= 3 and isinstance(data[1], list):
                    for trade in data[1]:
                        yield {
                            "price": float(trade[0]),
                            "volume": float(trade[1]),
                            "time": float(trade[2]),
                            "side": trade[3],
                            "order_type": trade[4],
                            "misc": trade[5],
                        }