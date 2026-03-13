"""
On-Chain Data Publisher — Sprint 3

Unified Redis publisher that caches all on-chain/derivatives snapshots.
Merges data from multiple sources and writes to standardized Redis keys.

Redis key schema:
  onchain:{ASSET}:derivatives  → DerivativesSnapshot JSON    TTL=120s
  onchain:{ASSET}:positioning  → PositioningSnapshot JSON    TTL=120s
  onchain:{ASSET}:signal       → Computed signal JSON        TTL=120s
  onchain:macro                → MacroSnapshot JSON          TTL=600s
  onchain:sentiment            → SentimentSnapshot JSON      TTL=3600s
  onchain:shadow_log           → Redis Stream (MAXLEN 5000)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)


class OnChainDataPublisher:
    """Writes on-chain/derivatives data to Redis with TTLs."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def _client(self) -> Any:
        return self._redis.client if hasattr(self._redis, "client") else self._redis

    async def publish_derivatives(
        self,
        asset: str,
        coinalyze_data: Optional[Any] = None,
        binance_data: Optional[dict] = None,
    ) -> None:
        """Merge Coinalyze + Binance derivatives data and cache in Redis."""
        merged: dict = {"asset": asset, "timestamp": time.time(), "source": "merged"}

        if coinalyze_data is not None and not isinstance(coinalyze_data, Exception):
            d = asdict(coinalyze_data) if hasattr(coinalyze_data, "__dataclass_fields__") else {}
            for k in ("open_interest_usd", "oi_change_1h_pct", "funding_rate",
                       "predicted_funding", "liquidated_longs_usd", "liquidated_shorts_usd"):
                if d.get(k) is not None:
                    merged[k] = d[k]

        if isinstance(binance_data, dict):
            # Binance funding as fallback if Coinalyze didn't have it
            if merged.get("funding_rate") is None and binance_data.get("funding_rate") is not None:
                merged["funding_rate"] = binance_data["funding_rate"]
            if binance_data.get("open_interest") is not None and merged.get("open_interest_usd") is None:
                merged["open_interest_usd"] = binance_data["open_interest"]

        key = f"onchain:{asset}:derivatives"
        try:
            client = self._client()
            await client.set(key, json.dumps(merged), ex=120)
            logger.debug("[ONCHAIN_PUB] Published derivatives for %s", asset)
        except Exception as e:
            logger.warning("[ONCHAIN_PUB] Failed to publish derivatives for %s: %s", asset, e)

    async def publish_positioning(self, asset: str, positioning: Any) -> None:
        """Cache positioning snapshot in Redis."""
        if positioning is None or isinstance(positioning, Exception):
            return
        key = f"onchain:{asset}:positioning"
        try:
            data = asdict(positioning) if hasattr(positioning, "__dataclass_fields__") else positioning
            client = self._client()
            await client.set(key, json.dumps(data), ex=120)
            logger.debug("[ONCHAIN_PUB] Published positioning for %s", asset)
        except Exception as e:
            logger.warning("[ONCHAIN_PUB] Failed to publish positioning for %s: %s", asset, e)

    async def publish_macro(self, macro: Any) -> None:
        """Cache macro snapshot in Redis."""
        if macro is None or isinstance(macro, Exception):
            return
        try:
            data = asdict(macro) if hasattr(macro, "__dataclass_fields__") else macro
            client = self._client()
            await client.set("onchain:macro", json.dumps(data), ex=600)
            logger.debug("[ONCHAIN_PUB] Published macro data")
        except Exception as e:
            logger.warning("[ONCHAIN_PUB] Failed to publish macro: %s", e)

    async def publish_sentiment(self, sentiment: Any) -> None:
        """Cache sentiment snapshot in Redis."""
        if sentiment is None or isinstance(sentiment, Exception):
            return
        try:
            data = asdict(sentiment) if hasattr(sentiment, "__dataclass_fields__") else sentiment
            client = self._client()
            await client.set("onchain:sentiment", json.dumps(data), ex=3600)
            logger.debug("[ONCHAIN_PUB] Published sentiment data")
        except Exception as e:
            logger.warning("[ONCHAIN_PUB] Failed to publish sentiment: %s", e)

    async def publish_shadow_log(self, asset: str, direction: Optional[str],
                                  confidence: float, reasons: list) -> None:
        """Append to shadow log stream for offline analysis."""
        try:
            client = self._client()
            await client.xadd(
                "onchain:shadow_log",
                {
                    "asset": asset,
                    "direction": direction or "abstain",
                    "confidence": str(confidence),
                    "reasons": json.dumps(reasons),
                    "ts": str(int(time.time() * 1000)),
                },
                maxlen=5000,
            )
        except Exception as e:
            logger.debug("[ONCHAIN_PUB] Shadow log write failed: %s", e)
