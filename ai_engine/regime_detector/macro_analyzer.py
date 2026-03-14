"""
Macro analyzer for market regime detection.

Reads on-chain and derivatives data from Redis (if available from Sprint 3
on-chain pipeline) and computes macro regime indicators. Falls back to
neutral values when data is unavailable.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MacroAnalyzer:
    """Analyse macroeconomic and on-chain data."""

    def __init__(self, redis_client: Optional[Any] = None) -> None:
        self._redis = redis_client

    async def compute_market_regime_async(self, asset: str = "BTC") -> Dict[str, float]:
        """
        Async version -- reads from Redis on-chain streams.

        Returns dict of normalized macro features:
        - btc_dominance: 0.0-1.0 (0.5 = neutral)
        - exchange_netflow_zscore: z-score of exchange netflow
        - funding_rate_zscore: z-score of funding rate
        - fear_greed_normalized: 0.0-1.0 (0.5 = neutral)
        - macro_regime: "risk_on", "risk_off", or "neutral"
        """
        result = self._default_regime()

        if self._redis is None:
            return result

        try:
            for key_suffix, field_name in [
                ("exchange_netflow_usd_1h", "exchange_netflow_zscore"),
                ("funding_rate", "funding_rate_zscore"),
            ]:
                raw = await self._redis_get(f"onchain:{asset}:{key_suffix}")
                if raw:
                    data = json.loads(raw)
                    if isinstance(data, dict) and "value" in data:
                        result[field_name] = float(data["value"])

            fg_raw = await self._redis_get("onchain:fear_greed")
            if fg_raw:
                data = json.loads(fg_raw)
                if isinstance(data, dict) and "value" in data:
                    result["fear_greed_normalized"] = float(data["value"]) / 100.0

            result["macro_regime"] = self._classify_regime(result)

        except Exception as e:
            logger.warning("MacroAnalyzer: error reading Redis: %s, using defaults", e)

        return result

    def compute_market_regime(self) -> Dict[str, float]:
        """Sync version -- returns defaults (backward compatibility)."""
        return self._default_regime()

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

    @staticmethod
    def _default_regime() -> Dict[str, float]:
        return {
            "btc_dominance": 0.5,
            "exchange_netflow_zscore": 0.0,
            "funding_rate_zscore": 0.0,
            "fear_greed_normalized": 0.5,
            "macro_regime": "neutral",
        }

    @staticmethod
    def _classify_regime(indicators: Dict[str, float]) -> str:
        netflow_z = indicators.get("exchange_netflow_zscore", 0.0)
        fg = indicators.get("fear_greed_normalized", 0.5)
        if netflow_z < -1.5 and fg > 0.6:
            return "risk_on"
        elif netflow_z > 1.5 and fg < 0.3:
            return "risk_off"
        return "neutral"


# Legacy function interface (backward compatibility with regime_detector imports)
def analyse_macro(data: dict) -> dict:
    """Legacy sync interface for macro analysis."""
    analyzer = MacroAnalyzer()
    regime = analyzer.compute_market_regime()
    growth = "stable"
    if regime.get("macro_regime") == "risk_on":
        growth = "expanding"
    elif regime.get("macro_regime") == "risk_off":
        growth = "contracting"
    return {"growth": growth, "inflation": "moderate", **regime}
