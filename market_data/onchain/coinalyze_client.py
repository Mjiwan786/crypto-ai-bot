"""
Coinalyze Free API Client — Sprint 3

Fetches aggregated derivatives data (open interest, funding rates, liquidations)
from Coinalyze's free public API. No API key required.

Rate limit: 40 req/min
Docs: https://api.coinalyze.net/v1
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://api.coinalyze.net/v1"
HEADERS = {"User-Agent": "crypto-ai-bot/1.0"}


@dataclass
class DerivativesSnapshot:
    """Aggregated derivatives data for a single asset."""
    asset: str
    timestamp: float
    source: str = "coinalyze"
    open_interest_usd: Optional[float] = None
    oi_change_1h_pct: Optional[float] = None
    funding_rate: Optional[float] = None
    predicted_funding: Optional[float] = None
    liquidated_longs_usd: Optional[float] = None
    liquidated_shorts_usd: Optional[float] = None
    fetched_at: float = 0.0


class CoinalyzeClient:
    """Async client for Coinalyze free derivatives data."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_request_at: float = 0.0
        # Min interval between requests: 60s / 40 = 1.5s
        self._min_interval: float = 1.5

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers=HEADERS,
            )
        return self._session

    async def _rate_wait(self) -> None:
        """Enforce rate limit."""
        now = time.time()
        wait = self._min_interval - (now - self._last_request_at)
        if wait > 0:
            import asyncio
            await asyncio.sleep(wait)
        self._last_request_at = time.time()

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
        """Make a GET request with error handling."""
        try:
            await self._rate_wait()
            session = await self._get_session()
            url = f"{BASE_URL}{path}"
            t0 = time.time()
            async with session.get(url, params=params) as resp:
                latency = (time.time() - t0) * 1000
                if resp.status == 429:
                    logger.warning("[COINALYZE] Rate limited (429), backing off")
                    return None
                if resp.status != 200:
                    logger.debug("[COINALYZE] HTTP %d for %s", resp.status, path)
                    return None
                data = await resp.json()
                logger.debug("[COINALYZE] %s → %dms", path, int(latency))
                return data
        except aiohttp.ClientError as e:
            logger.debug("[COINALYZE] Request error for %s: %s", path, e)
            return None
        except Exception as e:
            logger.debug("[COINALYZE] Unexpected error for %s: %s", path, e)
            return None

    async def fetch_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch aggregated open interest for a symbol.
        Symbol format: 'BTCUSD.6' (aggregate across exchanges).
        """
        data = await self._get("/open-interest-history", params={
            "symbols": symbol,
            "interval": "1h",
            "limit": 2,
        })
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        try:
            entries = data[0].get("history", data) if isinstance(data[0], dict) else data
            if isinstance(entries, list) and len(entries) >= 1:
                latest = entries[-1] if isinstance(entries[-1], dict) else {}
                return {
                    "open_interest_usd": latest.get("o", latest.get("val")),
                    "timestamp": latest.get("t", time.time()),
                }
        except (KeyError, IndexError, TypeError):
            pass
        return None

    async def fetch_funding_rate(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch current and predicted funding rate."""
        data = await self._get("/funding-rate-history", params={
            "symbols": symbol,
            "interval": "1h",
            "limit": 1,
        })
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        try:
            entries = data[0].get("history", data) if isinstance(data[0], dict) else data
            if isinstance(entries, list) and len(entries) >= 1:
                latest = entries[-1] if isinstance(entries[-1], dict) else {}
                return {
                    "funding_rate": latest.get("o", latest.get("val")),
                    "predicted_funding": latest.get("p"),
                    "timestamp": latest.get("t", time.time()),
                }
        except (KeyError, IndexError, TypeError):
            pass
        return None

    async def fetch_liquidations(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch long/short liquidation data."""
        data = await self._get("/liquidation-history", params={
            "symbols": symbol,
            "interval": "1h",
            "limit": 1,
        })
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        try:
            entries = data[0].get("history", data) if isinstance(data[0], dict) else data
            if isinstance(entries, list) and len(entries) >= 1:
                latest = entries[-1] if isinstance(entries[-1], dict) else {}
                return {
                    "liquidated_longs_usd": latest.get("l", 0.0),
                    "liquidated_shorts_usd": latest.get("s", 0.0),
                    "timestamp": latest.get("t", time.time()),
                }
        except (KeyError, IndexError, TypeError):
            pass
        return None

    async def fetch_all(self, symbol: str) -> Optional[DerivativesSnapshot]:
        """Fetch all derivatives data for a symbol and merge into snapshot."""
        import asyncio
        oi, funding, liqs = await asyncio.gather(
            self.fetch_open_interest(symbol),
            self.fetch_funding_rate(symbol),
            self.fetch_liquidations(symbol),
            return_exceptions=True,
        )

        # If all failed, return None
        if all(isinstance(r, (Exception, type(None))) for r in [oi, funding, liqs]):
            return None

        asset = symbol.split("USD")[0] if "USD" in symbol else symbol.rstrip(".6")
        now = time.time()
        snap = DerivativesSnapshot(asset=asset, timestamp=now, fetched_at=now)

        if isinstance(oi, dict):
            snap.open_interest_usd = oi.get("open_interest_usd")
        if isinstance(funding, dict):
            snap.funding_rate = funding.get("funding_rate")
            snap.predicted_funding = funding.get("predicted_funding")
        if isinstance(liqs, dict):
            snap.liquidated_longs_usd = liqs.get("liquidated_longs_usd")
            snap.liquidated_shorts_usd = liqs.get("liquidated_shorts_usd")

        return snap

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
