"""
On-Chain Data Agent -- reads from Sprint 3 on-chain pipeline.

Fetches cached on-chain metrics from Redis that were populated by the
background on-chain fetcher tasks (Coinalyze, Binance Futures, DefiLlama,
Fear & Greed). Does NOT make external API calls directly -- reads cached data.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class OnChainDataAgent:
    """Fetch on-chain metrics from Redis cache."""

    def __init__(self, redis_client: Optional[Any] = None) -> None:
        self._redis = redis_client

    async def fetch_metrics_async(self, asset: str = "BTC") -> Dict[str, float]:
        """
        Return on-chain metrics from Redis cache.

        Reads from keys populated by Sprint 3 on-chain pipeline:
        - onchain:{ASSET}:* -- on-chain metrics
        - derivs:{ASSET}:* -- derivatives metrics
        """
        metrics: Dict[str, float] = {}

        if self._redis is None:
            logger.debug("OnChainDataAgent: no Redis client, returning empty metrics")
            return metrics

        keys_to_read = {
            f"onchain:{asset}:exchange_netflow_usd_1h": "exchange_netflow",
            f"onchain:{asset}:funding_rate": "funding_rate",
            f"onchain:{asset}:open_interest": "open_interest",
            f"onchain:{asset}:ls_ratio": "long_short_ratio",
            f"onchain:{asset}:crowding_score": "crowding_score",
            "onchain:fear_greed": "fear_greed_index",
        }

        for redis_key, metric_name in keys_to_read.items():
            try:
                raw = await self._redis_get(redis_key)
                if raw:
                    data = json.loads(raw)
                    if isinstance(data, dict) and "value" in data:
                        metrics[metric_name] = float(data["value"])
                    elif isinstance(data, (int, float)):
                        metrics[metric_name] = float(data)
            except Exception as e:
                logger.debug("OnChainDataAgent: failed to read %s: %s", redis_key, e)

        logger.debug("OnChainDataAgent: fetched %d metrics for %s", len(metrics), asset)
        return metrics

    def fetch_metrics(self) -> Dict[str, float]:
        """Sync fallback -- returns empty metrics (backward compatible)."""
        return {}

    async def _redis_get(self, key: str) -> Optional[str]:
        """Safe async Redis GET."""
        try:
            if hasattr(self._redis, "client"):
                val = await self._redis.client.get(key)
            else:
                val = await self._redis.get(key)
            if isinstance(val, bytes):
                return val.decode()
            return val
        except Exception:
            return None
