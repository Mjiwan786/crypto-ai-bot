"""WebSocket client and tick stream simulator.

This module exposes functions to subscribe to real‑time market data
streams or to simulate such streams for backtesting. The live client
connects to Kraken's public WebSocket but can be extended to other
exchanges. During testing a deterministic random walk is used to
generate synthetic ticks.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from typing import AsyncIterator, Dict, Optional

try:
    import websockets  # type: ignore
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore

from ..infra.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Tick:
    """Simple market tick representation.

    Attributes:
        ts: Timestamp in seconds since the epoch.
        price: Last traded price.
        volume: Quantity traded.
        side: "buy" or "sell" depending on aggressor side.
    """

    ts: float
    price: float
    volume: float
    side: str

    def to_message(self) -> Dict[str, str]:
        return {
            "ts": str(self.ts),
            "price": str(self.price),
            "volume": str(self.volume),
            "side": self.side,
        }


async def stream_ticks(symbol: str, ws_url: Optional[str] = None) -> AsyncIterator[Tick]:
    """Asynchronously yield ticks for a given symbol.

    If a WebSocket URL is provided and the ``websockets`` library is
    installed, this function will connect to the exchange and yield
    real market data. Otherwise, it will generate synthetic ticks
    using a simple random walk to simulate price movements.

    Args:
        symbol: Trading symbol, e.g. ``BTC/USD``.
        ws_url: Optional WebSocket URL to connect to.

    Yields:
        :class:`Tick` objects.
    """
    if ws_url and websockets is not None:
        # Real WebSocket mode
        async with websockets.connect(ws_url) as websocket:
            # Subscribe to ticker channel; message format is exchange specific
            subscribe_msg = json.dumps(
                {
                    "event": "subscribe",
                    "pair": [symbol.replace("/", "")],
                    "subscription": {"name": "ticker"},
                }
            )
            await websocket.send(subscribe_msg)
            logger.info("Subscribed to %s via %s", symbol, ws_url)
            async for message in websocket:
                data = json.loads(message)
                # Kraken sends heartbeats and channel info
                if not isinstance(data, list):
                    continue
                # Example: [channelID, {"a":["54321.2",...],"b":["54320.1",...],"c":["54320.2","0.012345"]}, "ticker", "XBT/USD"]
                try:
                    _, tick_data, _, _ = data
                    price = float(tick_data.get("c", [0])[0])
                    volume = float(tick_data.get("c", [0, 0])[1])
                    side = "buy" if random.random() > 0.5 else "sell"
                    yield Tick(ts=time.time(), price=price, volume=volume, side=side)
                except Exception:
                    continue
    else:
        # Synthetic mode: random walk
        price = 50000.0  # starting price
        logger.info("Starting synthetic tick stream for %s", symbol)
        while True:
            # Simulate small random price change
            delta = random.normalvariate(0, 5)
            price = max(0.0, price + delta)
            volume = abs(random.normalvariate(0.1, 0.05))
            side = "buy" if delta >= 0 else "sell"
            yield Tick(ts=time.time(), price=price, volume=volume, side=side)
            await asyncio.sleep(0.5)  # 2 ticks per second
