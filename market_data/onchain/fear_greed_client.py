"""
Fear & Greed Index Client — Sprint 3

Fetches the Crypto Fear & Greed Index from Alternative.me.
100% free, no API key required.

API: https://api.alternative.me/fng/
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

FNG_URL = "https://api.alternative.me/fng/"
HEADERS = {"User-Agent": "crypto-ai-bot/1.0"}


@dataclass
class SentimentSnapshot:
    """Fear & Greed Index snapshot."""
    fear_greed_index: int = 50
    fear_greed_label: str = "Neutral"
    timestamp: float = 0.0
    source: str = "alternative_me"


class FearGreedClient:
    """Async client for the Crypto Fear & Greed Index."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                headers=HEADERS,
            )
        return self._session

    async def fetch_fear_greed(self) -> Optional[SentimentSnapshot]:
        """Fetch current Fear & Greed Index."""
        try:
            session = await self._get_session()
            t0 = time.time()
            async with session.get(FNG_URL, params={"limit": "1", "format": "json"}) as resp:
                latency = (time.time() - t0) * 1000
                if resp.status != 200:
                    logger.debug("[FEAR_GREED] HTTP %d", resp.status)
                    return None
                data = await resp.json()
                logger.debug("[FEAR_GREED] Fetched in %dms", int(latency))
        except Exception as e:
            logger.debug("[FEAR_GREED] Request error: %s", e)
            return None

        try:
            entries = data.get("data", [])
            if not entries:
                return None
            entry = entries[0]
            index = int(entry.get("value", 50))
            label = entry.get("value_classification", "Neutral")
            ts = float(entry.get("timestamp", time.time()))
            return SentimentSnapshot(
                fear_greed_index=index,
                fear_greed_label=label,
                timestamp=ts,
            )
        except (KeyError, ValueError, TypeError, IndexError):
            return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
