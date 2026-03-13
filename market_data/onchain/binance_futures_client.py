"""
Binance Futures Public API Client — Sprint 3

Fetches derivatives data (funding rates, open interest, long-short ratios,
taker buy/sell volume) from Binance Futures public API. No API key required.

Rate limit: 1200 req/min (very generous)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://fapi.binance.com"
HEADERS = {"User-Agent": "crypto-ai-bot/1.0"}


@dataclass
class PositioningSnapshot:
    """Long/short positioning data from Binance Futures."""
    asset: str
    long_short_ratio: float = 1.0
    top_trader_long_ratio: float = 0.5
    top_trader_short_ratio: float = 0.5
    taker_buy_volume: float = 0.0
    taker_sell_volume: float = 0.0
    taker_buy_sell_ratio: float = 1.0
    timestamp: float = 0.0
    source: str = "binance_futures"


class BinanceFuturesClient:
    """Async client for Binance Futures public derivatives data."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers=HEADERS,
            )
        return self._session

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """Make a GET request with error handling."""
        try:
            session = await self._get_session()
            url = f"{BASE_URL}{path}"
            t0 = time.time()
            async with session.get(url, params=params) as resp:
                latency = (time.time() - t0) * 1000
                if resp.status == 429:
                    logger.warning("[BINANCE_FUTURES] Rate limited (429)")
                    return None
                if resp.status != 200:
                    logger.debug("[BINANCE_FUTURES] HTTP %d for %s", resp.status, path)
                    return None
                data = await resp.json()
                logger.debug("[BINANCE_FUTURES] %s → %dms", path, int(latency))
                return data
        except aiohttp.ClientError as e:
            logger.debug("[BINANCE_FUTURES] Request error for %s: %s", path, e)
            return None
        except Exception as e:
            logger.debug("[BINANCE_FUTURES] Unexpected error for %s: %s", path, e)
            return None

    async def fetch_funding_rate(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch current funding rate for a symbol (e.g. 'BTCUSDT')."""
        data = await self._get("/fapi/v1/fundingRate", params={
            "symbol": symbol,
            "limit": 1,
        })
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        try:
            entry = data[-1]
            return {
                "funding_rate": float(entry.get("fundingRate", 0)),
                "timestamp": float(entry.get("fundingTime", time.time() * 1000)) / 1000,
            }
        except (KeyError, ValueError, TypeError):
            return None

    async def fetch_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch current open interest."""
        data = await self._get("/fapi/v1/openInterest", params={"symbol": symbol})
        if not data or not isinstance(data, dict):
            return None
        try:
            return {
                "open_interest": float(data.get("openInterest", 0)),
                "timestamp": float(data.get("time", time.time() * 1000)) / 1000,
            }
        except (KeyError, ValueError, TypeError):
            return None

    async def fetch_long_short_ratio(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch global long/short account ratio."""
        data = await self._get("/futures/data/globalLongShortAccountRatio", params={
            "symbol": symbol,
            "period": "1h",
            "limit": 1,
        })
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        try:
            entry = data[-1]
            return {
                "long_short_ratio": float(entry.get("longShortRatio", 1.0)),
                "long_account": float(entry.get("longAccount", 0.5)),
                "short_account": float(entry.get("shortAccount", 0.5)),
                "timestamp": float(entry.get("timestamp", time.time() * 1000)) / 1000,
            }
        except (KeyError, ValueError, TypeError):
            return None

    async def fetch_top_trader_ratio(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch top trader long/short position ratio."""
        data = await self._get("/futures/data/topLongShortPositionRatio", params={
            "symbol": symbol,
            "period": "1h",
            "limit": 1,
        })
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        try:
            entry = data[-1]
            return {
                "long_ratio": float(entry.get("longAccount", 0.5)),
                "short_ratio": float(entry.get("shortAccount", 0.5)),
                "timestamp": float(entry.get("timestamp", time.time() * 1000)) / 1000,
            }
        except (KeyError, ValueError, TypeError):
            return None

    async def fetch_taker_volume(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch taker buy/sell volume."""
        data = await self._get("/futures/data/takerlongshortRatio", params={
            "symbol": symbol,
            "period": "1h",
            "limit": 1,
        })
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        try:
            entry = data[-1]
            buy_vol = float(entry.get("buyVol", 0))
            sell_vol = float(entry.get("sellVol", 0))
            ratio = buy_vol / sell_vol if sell_vol > 0 else 1.0
            return {
                "taker_buy_volume": buy_vol,
                "taker_sell_volume": sell_vol,
                "taker_buy_sell_ratio": ratio,
                "timestamp": float(entry.get("timestamp", time.time() * 1000)) / 1000,
            }
        except (KeyError, ValueError, TypeError):
            return None

    async def fetch_derivatives(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch combined derivatives snapshot (funding + OI)."""
        import asyncio
        funding, oi = await asyncio.gather(
            self.fetch_funding_rate(symbol),
            self.fetch_open_interest(symbol),
            return_exceptions=True,
        )
        if isinstance(funding, Exception):
            funding = None
        if isinstance(oi, Exception):
            oi = None
        if funding is None and oi is None:
            return None
        result: Dict[str, Any] = {"source": "binance_futures"}
        if funding:
            result["funding_rate"] = funding.get("funding_rate")
        if oi:
            result["open_interest"] = oi.get("open_interest")
        return result

    async def fetch_positioning(self, symbol: str) -> Optional[PositioningSnapshot]:
        """Fetch combined positioning snapshot (L/S ratio + top traders + taker volume)."""
        import asyncio
        ls, top, taker = await asyncio.gather(
            self.fetch_long_short_ratio(symbol),
            self.fetch_top_trader_ratio(symbol),
            self.fetch_taker_volume(symbol),
            return_exceptions=True,
        )

        if all(isinstance(r, (Exception, type(None))) for r in [ls, top, taker]):
            return None

        asset = symbol.replace("USDT", "")
        snap = PositioningSnapshot(asset=asset, timestamp=time.time())

        if isinstance(ls, dict):
            snap.long_short_ratio = ls.get("long_short_ratio", 1.0)
        if isinstance(top, dict):
            snap.top_trader_long_ratio = top.get("long_ratio", 0.5)
            snap.top_trader_short_ratio = top.get("short_ratio", 0.5)
        if isinstance(taker, dict):
            snap.taker_buy_volume = taker.get("taker_buy_volume", 0.0)
            snap.taker_sell_volume = taker.get("taker_sell_volume", 0.0)
            snap.taker_buy_sell_ratio = taker.get("taker_buy_sell_ratio", 1.0)

        return snap

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
