from __future__ import annotations

"""
⚠️ SAFETY: No live trading unless MODE=live and confirmation set.
Test script for Kraken WebSocket connection.
"""

import asyncio
import json
import logging

import websockets

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_ws() -> int:
    """Test Kraken WebSocket connection."""
    url = "wss://ws.kraken.com"
    try:
        logger.info(f"Connecting to {url}")
        async with websockets.connect(url) as ws:
            sub_msg = {
                "event": "subscribe",
                "pair": ["BTC/USD"],
                "subscription": {"name": "trade"},
            }
            await ws.send(json.dumps(sub_msg))
            logger.info("Subscription sent, receiving messages...")
            while True:
                msg = await ws.recv()
                logger.info(f"Received: {msg}")
    except Exception as e:
        logger.error(f"WebSocket test failed: {e}")
        return 1
    return 0


def main() -> int:
    """Main entry point."""
    return asyncio.run(test_ws())


if __name__ == "__main__":
    raise SystemExit(main())
