"""
CoinGlass On-Chain Data Client — Sprint 2 (P1-B)

Fetches open interest and long/short ratio from CoinGlass public API,
caches in Redis with TTL, runs as a background asyncio.Task.

The consensus gate's Family D reads from Redis cache — never inline HTTP.

Feature flag: ONCHAIN_FAMILY_ENABLED (default false)

Lifecycle (same pattern as RegimeWriter):
    client = CoinglassClient(redis_client, pairs=["BTC/USD"])
    await client.start()   # spawns background refresh task
    ...
    await client.stop()    # cancels task
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

# CoinGlass public API (no key needed for basic data)
COINGLASS_OI_URL = "https://open-api.coinglass.com/public/v2/open_interest"
COINGLASS_LS_URL = "https://open-api.coinglass.com/public/v2/long_short"

# CoinGecko fallback for derivatives
COINGECKO_DERIVATIVES_URL = "https://api.coingecko.com/api/v3/derivatives"

CACHE_TTL_S = 300       # 5 min cache
REFRESH_INTERVAL_S = 300 # Refresh every 5 min
RATE_LIMIT_S = 30        # Max 1 request per 30s per endpoint


@dataclass
class OnChainData:
    """On-chain data snapshot for a single asset."""
    open_interest_change_24h: float  # percentage change
    long_short_ratio: float          # >1 = more longs, <1 = more shorts
    data_source: str                 # "coinglass" or "coingecko" or "unavailable"
    is_stale: bool                   # True if data > 10 min old
    timestamp: float = 0.0


class CoinglassClient:
    """
    Background task that fetches on-chain data and caches in Redis.

    Redis keys written:
      onchain:{SYMBOL}:oi       → {"change_24h_pct": float, "timestamp": float}
      onchain:{SYMBOL}:ls_ratio → {"ratio": float, "timestamp": float}
    """

    def __init__(
        self,
        redis_client: Any,
        pairs: Optional[List[str]] = None,
        enabled: bool = True,
    ):
        self._redis = redis_client
        self._pairs = pairs or ["BTC/USD"]
        self._enabled = enabled
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._http: Optional[aiohttp.ClientSession] = None
        self._last_fetch: Dict[str, float] = {}  # endpoint → last fetch timestamp

    async def start(self) -> None:
        """Start background refresh loop."""
        if not self._enabled:
            logger.info("[ONCHAIN] CoinglassClient disabled via feature flag")
            return
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="coinglass_refresh")
        logger.info("[ONCHAIN] CoinglassClient started: pairs=%s", ",".join(self._pairs))

    async def stop(self) -> None:
        """Stop background refresh loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._http:
            await self._http.close()
            self._http = None
        logger.info("[ONCHAIN] CoinglassClient stopped")

    async def _loop(self) -> None:
        """Main loop: fetch data for each pair, cache in Redis."""
        while self._running:
            try:
                for pair in self._pairs:
                    symbol = pair.split("/")[0]  # BTC/USD → BTC
                    await self._refresh_pair(symbol)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[ONCHAIN] refresh loop error: %s", e, exc_info=True)
            await asyncio.sleep(REFRESH_INTERVAL_S)

    async def _refresh_pair(self, symbol: str) -> None:
        """Fetch OI and L/S ratio for a symbol, cache in Redis."""
        if not self._http:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
            )

        now = time.time()

        # ── Open Interest ──
        oi_change = None
        oi_key = f"onchain:{symbol}:oi"
        try:
            if self._rate_limit_ok("oi", now):
                data = await self._fetch_coinglass_oi(symbol)
                if data is not None:
                    oi_change = data
                    payload = json.dumps({"change_24h_pct": oi_change, "timestamp": now})
                    client = self._redis.client
                    await client.set(oi_key, payload)
                    await client.expire(oi_key, CACHE_TTL_S)
                    self._last_fetch["oi"] = now
        except Exception as e:
            logger.debug("[ONCHAIN] OI fetch failed for %s: %s", symbol, e)

        # ── Long/Short Ratio ──
        ls_ratio = None
        ls_key = f"onchain:{symbol}:ls_ratio"
        try:
            if self._rate_limit_ok("ls", now):
                data = await self._fetch_coinglass_ls(symbol)
                if data is not None:
                    ls_ratio = data
                    payload = json.dumps({"ratio": ls_ratio, "timestamp": now})
                    client = self._redis.client
                    await client.set(ls_key, payload)
                    await client.expire(ls_key, CACHE_TTL_S)
                    self._last_fetch["ls"] = now
        except Exception as e:
            logger.debug("[ONCHAIN] L/S fetch failed for %s: %s", symbol, e)

        if oi_change is not None or ls_ratio is not None:
            logger.info(
                "[ONCHAIN] %s: OI_change=%.1f%%, L/S_ratio=%.2f",
                symbol,
                oi_change if oi_change is not None else 0.0,
                ls_ratio if ls_ratio is not None else 0.0,
            )

    def _rate_limit_ok(self, endpoint: str, now: float) -> bool:
        """Check rate limit: max 1 request per RATE_LIMIT_S per endpoint."""
        last = self._last_fetch.get(endpoint, 0)
        return (now - last) >= RATE_LIMIT_S

    async def _fetch_coinglass_oi(self, symbol: str) -> Optional[float]:
        """Fetch 24h OI change from CoinGlass. Returns percentage change or None."""
        try:
            url = f"{COINGLASS_OI_URL}?symbol={symbol}"
            async with self._http.get(url) as resp:
                if resp.status != 200:
                    return await self._fallback_coingecko_oi(symbol)
                data = await resp.json()
                if data.get("code") != "0" or not data.get("data"):
                    return await self._fallback_coingecko_oi(symbol)
                # CoinGlass returns list of exchange OI data
                items = data["data"]
                if not items:
                    return None
                # Aggregate: sum current vs 24h ago
                total_current = sum(float(i.get("openInterest", 0)) for i in items)
                total_prev = sum(float(i.get("openInterest24hAgo", total_current)) for i in items)
                if total_prev > 0:
                    return ((total_current - total_prev) / total_prev) * 100
                return 0.0
        except Exception as e:
            logger.debug("[ONCHAIN] CoinGlass OI error: %s", e)
            return await self._fallback_coingecko_oi(symbol)

    async def _fetch_coinglass_ls(self, symbol: str) -> Optional[float]:
        """Fetch long/short ratio from CoinGlass. Returns ratio or None."""
        try:
            url = f"{COINGLASS_LS_URL}?symbol={symbol}"
            async with self._http.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("code") != "0" or not data.get("data"):
                    return None
                items = data["data"]
                if not items:
                    return None
                # Average ratio across exchanges
                ratios = [float(i.get("longRate", 50)) / max(float(i.get("shortRate", 50)), 0.01)
                          for i in items if i.get("longRate") and i.get("shortRate")]
                if ratios:
                    return sum(ratios) / len(ratios)
                return None
        except Exception as e:
            logger.debug("[ONCHAIN] CoinGlass L/S error: %s", e)
            return None

    async def _fallback_coingecko_oi(self, symbol: str) -> Optional[float]:
        """Fallback: CoinGecko derivatives endpoint for basic OI data."""
        try:
            async with self._http.get(COINGECKO_DERIVATIVES_URL) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                # Find matching symbol in derivatives data
                for item in data:
                    if symbol.upper() in str(item.get("symbol", "")).upper():
                        oi = item.get("open_interest")
                        if oi:
                            return 0.0  # CoinGecko doesn't provide 24h change
                return None
        except Exception:
            return None


# ── Self-test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    print("=" * 60)
    print("CoinGlass Client — Self-Test (mock Redis)")
    print("=" * 60)

    class MockRedisInner:
        def __init__(self):
            self.data: Dict[str, str] = {}

        async def set(self, key, value):
            self.data[key] = value

        async def get(self, key):
            return self.data.get(key)

        async def expire(self, key, ttl):
            pass

    class MockRedisClient:
        def __init__(self):
            self._inner = MockRedisInner()

        @property
        def client(self):
            return self._inner

    async def run_test():
        mock = MockRedisClient()
        client = CoinglassClient(mock, pairs=["BTC/USD"], enabled=True)

        # Test lifecycle
        await client.start()
        assert client._task is not None
        await asyncio.sleep(0.1)
        await client.stop()
        assert client._task is None
        print("\nLifecycle test: PASS")

        # Test disabled
        client_off = CoinglassClient(mock, enabled=False)
        await client_off.start()
        assert client_off._task is None
        print("Disabled test: PASS")

        # Test rate limiter
        now = time.time()
        assert client._rate_limit_ok("oi", now) is True
        client._last_fetch["oi"] = now
        assert client._rate_limit_ok("oi", now + 10) is False
        assert client._rate_limit_ok("oi", now + 31) is True
        print("Rate limit test: PASS")

        print("\n" + "=" * 60)
        print("ALL SELF-TESTS PASSED")
        print("=" * 60)

    asyncio.run(run_test())
