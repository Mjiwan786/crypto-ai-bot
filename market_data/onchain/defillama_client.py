"""
DefiLlama Free API Client — Sprint 3

Fetches macro DeFi data (TVL, stablecoin market cap, DEX volume).
100% free, no API key required.

API: https://api.llama.fi
Rate limit: ~300/min (undocumented but generous)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "crypto-ai-bot/1.0"}


@dataclass
class MacroSnapshot:
    """Macro DeFi data snapshot."""
    total_tvl_usd: float = 0.0
    tvl_change_24h_pct: float = 0.0
    stablecoin_mcap_usd: float = 0.0
    dex_volume_24h_usd: float = 0.0
    timestamp: float = 0.0
    source: str = "defillama"


class DefiLlamaClient:
    """Async client for DefiLlama macro data."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20),
                headers=HEADERS,
            )
        return self._session

    async def _get(self, url: str) -> Optional[dict]:
        try:
            session = await self._get_session()
            t0 = time.time()
            async with session.get(url) as resp:
                latency = (time.time() - t0) * 1000
                if resp.status != 200:
                    logger.debug("[DEFILLAMA] HTTP %d for %s", resp.status, url)
                    return None
                data = await resp.json()
                logger.debug("[DEFILLAMA] %s → %dms", url.split("/")[-1], int(latency))
                return data
        except Exception as e:
            logger.debug("[DEFILLAMA] Error fetching %s: %s", url, e)
            return None

    async def fetch_total_tvl(self) -> Optional[dict]:
        """Fetch total DeFi TVL across all chains."""
        data = await self._get("https://api.llama.fi/v2/historicalChainTvl")
        if not data or not isinstance(data, list) or len(data) < 2:
            return None
        try:
            latest = data[-1]
            prev = data[-2]
            tvl = float(latest.get("tvl", 0))
            prev_tvl = float(prev.get("tvl", 1))
            change = ((tvl - prev_tvl) / prev_tvl * 100) if prev_tvl > 0 else 0.0
            return {"total_tvl_usd": tvl, "tvl_change_24h_pct": change}
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    async def fetch_stablecoin_mcap(self) -> Optional[float]:
        """Fetch total stablecoin market cap."""
        data = await self._get("https://stablecoins.llama.fi/stablecoins?includePrices=false")
        if not data or not isinstance(data, dict):
            return None
        try:
            pegged = data.get("peggedAssets", [])
            total = sum(
                float(s.get("circulating", {}).get("peggedUSD", 0))
                for s in pegged
                if isinstance(s, dict)
            )
            return total if total > 0 else None
        except (TypeError, ValueError):
            return None

    async def fetch_dex_volume(self) -> Optional[float]:
        """Fetch 24h total DEX volume."""
        data = await self._get("https://api.llama.fi/overview/dexs?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true")
        if not data or not isinstance(data, dict):
            return None
        try:
            return float(data.get("total24h", 0))
        except (TypeError, ValueError):
            return None

    async def fetch_macro(self) -> Optional[MacroSnapshot]:
        """Fetch combined macro snapshot."""
        import asyncio
        tvl_data, stable_mcap, dex_vol = await asyncio.gather(
            self.fetch_total_tvl(),
            self.fetch_stablecoin_mcap(),
            self.fetch_dex_volume(),
            return_exceptions=True,
        )

        snap = MacroSnapshot(timestamp=time.time())

        if isinstance(tvl_data, dict):
            snap.total_tvl_usd = tvl_data.get("total_tvl_usd", 0.0)
            snap.tvl_change_24h_pct = tvl_data.get("tvl_change_24h_pct", 0.0)
        if isinstance(stable_mcap, (int, float)):
            snap.stablecoin_mcap_usd = float(stable_mcap)
        if isinstance(dex_vol, (int, float)):
            snap.dex_volume_24h_usd = float(dex_vol)

        # Return None only if we got absolutely nothing
        if snap.total_tvl_usd == 0.0 and snap.stablecoin_mcap_usd == 0.0 and snap.dex_volume_24h_usd == 0.0:
            return None

        return snap

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
