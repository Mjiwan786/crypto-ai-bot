"""
Multi-Exchange Price Provider — two-price model.

- Execution price: venue where the position exists (Kraken for live, any for paper)
- Reference price: cross-exchange median for anomaly detection and analytics

Uses Redis ticker streams published by the multi-exchange streamer.
"""

import os
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Which exchanges to use for reference price (must have USD pairs)
REFERENCE_EXCHANGES = ["coinbase", "bitfinex", "kraken"]
# USDT exchanges (converted from USD for reference pricing)
USDT_REFERENCE_EXCHANGES = ["binance", "bybit"]

# Maximum age of a ticker before it's considered stale
STALE_THRESHOLD_S = float(os.getenv("PRICE_STALE_THRESHOLD_S", "30.0"))

# Anomaly threshold — if execution price deviates from reference by more than this, warn
ANOMALY_THRESHOLD_BPS = float(os.getenv("PRICE_ANOMALY_THRESHOLD_BPS", "50.0"))


class PriceProvider:
    """
    Provides execution prices and cross-exchange reference prices.

    In paper mode: uses reference price (best available from any exchange).
    In live mode: uses execution venue price as canonical, reference for anomaly checks.
    """

    def __init__(self, redis_client: Any, mode: str = "paper"):
        self._redis = redis_client
        self._mode = mode
        self._execution_venue = os.getenv("EXECUTION_VENUE", "kraken")
        self._cache: Dict[str, Tuple[float, float]] = {}  # {key: (price, timestamp)}
        self._cache_ttl = float(os.getenv("PRICE_CACHE_TTL_S", "5.0"))

    async def get_price(self, pair: str) -> Optional[float]:
        """
        Get the canonical price for a pair.

        Paper mode: returns reference price (best available exchange)
        Live mode: returns execution venue price
        """
        if self._mode == "live":
            price = await self._get_execution_price(pair)
            if price:
                # Also compute reference for anomaly check
                ref = await self._get_reference_price(pair)
                if ref and price > 0:
                    deviation_bps = abs(price - ref) / price * 10000
                    if deviation_bps > ANOMALY_THRESHOLD_BPS:
                        logger.warning(
                            "[PRICE] %s: Execution price $%.2f deviates %.1f bps from reference $%.2f",
                            pair, price, deviation_bps, ref,
                        )
                return price
            # Fallback to reference if execution venue unavailable
            logger.warning("[PRICE] %s: Execution venue %s unavailable, using reference", pair, self._execution_venue)
            return await self._get_reference_price(pair)
        else:
            # Paper mode: use reference price
            return await self._get_reference_price(pair)

    async def _get_execution_price(self, pair: str) -> Optional[float]:
        """Get price from the execution venue (e.g., Kraken for live trading)."""
        return await self._read_ticker(self._execution_venue, pair)

    async def _get_reference_price(self, pair: str) -> Optional[float]:
        """Get cross-exchange reference price (robust median of available tickers)."""
        prices: List[float] = []

        for exchange in REFERENCE_EXCHANGES:
            price = await self._read_ticker(exchange, pair)
            if price and price > 0:
                prices.append(price)

        for exchange in USDT_REFERENCE_EXCHANGES:
            # USDT exchanges — price is close enough for reference
            usdt_pair = pair.replace("/USD", "/USDT").replace("-USD", "-USDT")
            price = await self._read_ticker(exchange, usdt_pair)
            if price and price > 0:
                prices.append(price)

        if not prices:
            return None

        # Robust median — handles outliers from stale/wrong data
        return float(np.median(prices))

    async def _read_ticker(self, exchange: str, pair: str) -> Optional[float]:
        """Read latest ticker price from Redis ticker stream or OHLCV stream."""
        now = time.time()
        cache_key = f"{exchange}:{pair}"

        # Check cache
        if cache_key in self._cache:
            cached_price, cached_time = self._cache[cache_key]
            if now - cached_time < self._cache_ttl:
                return cached_price

        dash_pair = pair.replace("/", "-")
        # Try multiple key patterns — ticker streams and OHLCV streams
        keys_to_try = [
            f"{exchange}:ticker:{dash_pair}",
            f"{exchange}:ticker:{pair}",
            f"{exchange}:ohlc:1m:{dash_pair}",
            f"{exchange}:ohlc:1:{dash_pair}",
        ]
        # USDT variant for USDT exchanges
        if exchange in {"binance", "bybit", "okx", "kucoin", "gateio"}:
            usdt_pair = dash_pair.replace("-USD", "-USDT")
            keys_to_try.extend([
                f"{exchange}:ticker:{usdt_pair}",
                f"{exchange}:ohlc:1m:{usdt_pair}",
                f"{exchange}:ohlc:1:{usdt_pair}",
            ])

        for key in keys_to_try:
            try:
                client = self._redis.client if hasattr(self._redis, 'client') else self._redis
                entries = await client.xrevrange(key, count=1)
                if entries:
                    entry_id, fields = entries[0]
                    def _get(k: str) -> Optional[float]:
                        v = fields.get(k) or fields.get(k.encode() if isinstance(k, str) else k)
                        if v is None:
                            return None
                        return float(v.decode() if isinstance(v, bytes) else v)

                    price = _get("last") or _get("close") or _get("price")
                    if price and price > 0:
                        # Check staleness
                        eid = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                        ts_ms = int(eid.split("-")[0])
                        age_s = now - (ts_ms / 1000.0)
                        if age_s > STALE_THRESHOLD_S:
                            logger.debug("[PRICE] %s:%s stale (%.0fs old)", exchange, pair, age_s)
                            continue
                        self._cache[cache_key] = (price, now)
                        return price
            except Exception as e:
                logger.debug("[PRICE] Failed reading %s: %s", key, e)
                continue

        return None

    async def get_anomaly_report(self, pair: str) -> Optional[Dict]:
        """Get cross-exchange price comparison for a pair (for diagnostics)."""
        prices: Dict[str, float] = {}
        for exchange in REFERENCE_EXCHANGES + USDT_REFERENCE_EXCHANGES:
            p = await self._read_ticker(exchange, pair)
            if p:
                prices[exchange] = p
        if len(prices) < 2:
            return None
        values = list(prices.values())
        return {
            "pair": pair,
            "prices": prices,
            "median": float(np.median(values)),
            "spread_bps": (max(values) - min(values)) / np.median(values) * 10000,
            "exchanges_reporting": len(prices),
        }
