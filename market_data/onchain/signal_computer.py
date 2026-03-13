"""
On-Chain Signal Computer — Sprint 3

Background task that reads raw on-chain data from Redis, computes
Family D signals via the feature pipeline, and writes computed signals
back to Redis for the consensus gate to read.

Runs on a 30-second cycle.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, List, Optional

from market_data.onchain.feature_pipeline import evaluate_derivatives_signal

logger = logging.getLogger(__name__)


class OnChainSignalComputer:
    """Reads raw on-chain data from Redis, computes Family D signals, writes back."""

    def __init__(self, redis_client: Any, trading_pairs: List[str]) -> None:
        self._redis = redis_client
        self.assets = list(set(p.split("/")[0] for p in trading_pairs))
        self._running = False
        self.signals_computed = 0

    async def start(self) -> None:
        """Run signal computation loop."""
        self._running = True
        while self._running:
            for asset in self.assets:
                try:
                    await self._compute_signal(asset)
                except Exception as e:
                    logger.warning("[ONCHAIN_COMPUTE] Failed for %s: %s", asset, e)
            await asyncio.sleep(30)

    async def stop(self) -> None:
        self._running = False

    def _client(self) -> Any:
        return self._redis.client if hasattr(self._redis, "client") else self._redis

    async def _compute_signal(self, asset: str) -> None:
        """Read raw data, compute signal, write to Redis."""
        client = self._client()

        # Read cached data from Redis
        derivs_raw = await client.get(f"onchain:{asset}:derivatives")
        pos_raw = await client.get(f"onchain:{asset}:positioning")
        macro_raw = await client.get("onchain:macro")
        sent_raw = await client.get("onchain:sentiment")

        # Parse (handle None gracefully)
        derivatives = json.loads(derivs_raw) if derivs_raw else None
        positioning = json.loads(pos_raw) if pos_raw else None
        macro = json.loads(macro_raw) if macro_raw else None
        sentiment = json.loads(sent_raw) if sent_raw else None

        if derivatives is None:
            return  # Can't compute without derivatives data

        # Compute signal
        result = evaluate_derivatives_signal(derivatives, positioning, macro, sentiment)

        if result is None:
            # Write abstain marker
            await client.set(
                f"onchain:{asset}:signal",
                json.dumps({"direction": None, "confidence": 0.0, "reasons": ["abstain"]}),
                ex=120,
            )
            # Shadow log
            await self._shadow_log(client, asset, None, 0.0, ["abstain"])
            return

        direction, confidence, reasons = result
        self.signals_computed += 1

        # Write computed signal
        signal_data = {
            "direction": direction,
            "confidence": confidence,
            "reasons": reasons,
            "asset": asset,
            "computed_at": time.time(),
        }
        await client.set(
            f"onchain:{asset}:signal",
            json.dumps(signal_data),
            ex=120,
        )

        # Shadow log (always, regardless of mode)
        await self._shadow_log(client, asset, direction, confidence, reasons)

        logger.info(
            "[ONCHAIN_COMPUTE] %s: %s (conf=%.2f, reasons=%s)",
            asset, direction, confidence, reasons,
        )

    async def _shadow_log(self, client: Any, asset: str, direction: Optional[str],
                           confidence: float, reasons: list) -> None:
        """Append to shadow log stream."""
        try:
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
        except Exception:
            pass  # Non-critical
