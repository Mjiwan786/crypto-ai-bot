"""
On-Chain Data Fetcher — Sprint 3

Background async task that orchestrates data collection from all free
on-chain/derivatives data sources and publishes to Redis.

Sources:
  - Coinalyze: OI, funding rates, liquidations (60s cycle)
  - Binance Futures: L/S ratios, taker volume, funding (60s cycle)
  - DefiLlama: TVL, stablecoin mcap, DEX volume (300s cycle)
  - Alternative.me: Fear & Greed Index (3600s cycle)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from market_data.onchain.coinalyze_client import CoinalyzeClient
from market_data.onchain.binance_futures_client import BinanceFuturesClient
from market_data.onchain.defillama_client import DefiLlamaClient
from market_data.onchain.fear_greed_client import FearGreedClient
from market_data.onchain.data_publisher import OnChainDataPublisher

logger = logging.getLogger(__name__)

# Internal pair → derivatives symbol mapping
ASSET_SYMBOL_MAP: Dict[str, Dict[str, str]] = {
    "BTC":   {"coinalyze": "BTCUSD.6",   "binance": "BTCUSDT"},
    "ETH":   {"coinalyze": "ETHUSD.6",   "binance": "ETHUSDT"},
    "SOL":   {"coinalyze": "SOLUSD.6",   "binance": "SOLUSDT"},
    "ADA":   {"coinalyze": "ADAUSD.6",   "binance": "ADAUSDT"},
    "DOGE":  {"coinalyze": "DOGEUSD.6",  "binance": "DOGEUSDT"},
    "DOT":   {"coinalyze": "DOTUSD.6",   "binance": "DOTUSDT"},
    "LINK":  {"coinalyze": "LINKUSD.6",  "binance": "LINKUSDT"},
    "LTC":   {"coinalyze": "LTCUSD.6",   "binance": "LTCUSDT"},
    "XRP":   {"coinalyze": "XRPUSD.6",   "binance": "XRPUSDT"},
    "AVAX":  {"coinalyze": "AVAXUSD.6",  "binance": "AVAXUSDT"},
    "MATIC": {"coinalyze": "MATICUSD.6", "binance": "MATICUSDT"},
    "UNI":   {"coinalyze": "UNIUSD.6",   "binance": "UNIUSDT"},
    "ATOM":  {"coinalyze": "ATOMUSD.6",  "binance": "ATOMUSDT"},
    "NEAR":  {"coinalyze": "NEARUSD.6",  "binance": "NEARUSDT"},
    "ARB":   {"coinalyze": "ARBUSD.6",   "binance": "ARBUSDT"},
    "ALGO":  {"coinalyze": "ALGOUSD.6",  "binance": "ALGOUSDT"},
}


class OnChainDataFetcher:
    """Background task that fetches on-chain/derivatives data and publishes to Redis."""

    def __init__(self, redis_client: Any, trading_pairs: List[str]) -> None:
        self.coinalyze = CoinalyzeClient()
        self.binance_futures = BinanceFuturesClient()
        self.defillama = DefiLlamaClient()
        self.fear_greed = FearGreedClient()
        self.publisher = OnChainDataPublisher(redis_client)
        self._running = False
        self._asset_map = self._build_asset_map(trading_pairs)

        # Counters for observability
        self.fetches = 0
        self.fetch_errors = 0

    def _build_asset_map(self, trading_pairs: List[str]) -> Dict[str, Dict[str, str]]:
        """Map internal pairs to derivatives symbols."""
        result = {}
        for pair in trading_pairs:
            asset = pair.split("/")[0]
            if asset in ASSET_SYMBOL_MAP:
                result[asset] = ASSET_SYMBOL_MAP[asset]
        return result

    async def start(self) -> None:
        """Start background fetch loops."""
        self._running = True
        await asyncio.gather(
            self._derivatives_loop(),
            self._macro_loop(),
            self._sentiment_loop(),
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        await asyncio.gather(
            self.coinalyze.close(),
            self.binance_futures.close(),
            self.defillama.close(),
            self.fear_greed.close(),
            return_exceptions=True,
        )

    async def _derivatives_loop(self) -> None:
        """Fetch derivatives data for all assets every 60s."""
        while self._running:
            for asset, symbols in self._asset_map.items():
                try:
                    cz_data, bn_derivs, bn_positioning = await asyncio.gather(
                        self.coinalyze.fetch_all(symbols["coinalyze"]),
                        self.binance_futures.fetch_derivatives(symbols["binance"]),
                        self.binance_futures.fetch_positioning(symbols["binance"]),
                        return_exceptions=True,
                    )

                    self.fetches += 1

                    # Publish merged derivatives
                    await self.publisher.publish_derivatives(
                        asset,
                        cz_data if not isinstance(cz_data, Exception) else None,
                        bn_derivs if not isinstance(bn_derivs, Exception) else None,
                    )

                    # Publish positioning
                    if not isinstance(bn_positioning, Exception) and bn_positioning is not None:
                        await self.publisher.publish_positioning(asset, bn_positioning)

                except Exception as e:
                    self.fetch_errors += 1
                    logger.warning("[ONCHAIN_FETCH] Derivatives failed for %s: %s", asset, e)

            await asyncio.sleep(60)

    async def _macro_loop(self) -> None:
        """Fetch macro data every 5 minutes."""
        while self._running:
            try:
                macro = await self.defillama.fetch_macro()
                await self.publisher.publish_macro(macro)
                self.fetches += 1
            except Exception as e:
                self.fetch_errors += 1
                logger.warning("[ONCHAIN_FETCH] Macro failed: %s", e)
            await asyncio.sleep(300)

    async def _sentiment_loop(self) -> None:
        """Fetch sentiment data every hour."""
        while self._running:
            try:
                sentiment = await self.fear_greed.fetch_fear_greed()
                await self.publisher.publish_sentiment(sentiment)
                self.fetches += 1
            except Exception as e:
                self.fetch_errors += 1
                logger.warning("[ONCHAIN_FETCH] Sentiment failed: %s", e)
            await asyncio.sleep(3600)
