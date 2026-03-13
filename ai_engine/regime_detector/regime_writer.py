"""
Regime Writer — Sprint 2 (P0-A)

Computes market regime from OHLCV Redis streams and writes JSON to
the ``mcp:market_context`` Redis key every 60 seconds.

Runs as a background ``asyncio.Task`` inside ProductionEngine — NOT a
separate Fly process.

Lifecycle:
    writer = RegimeWriter(redis_client, pairs=["BTC/USD", "ETH/USD"])
    await writer.start()   # spawns background task
    ...
    await writer.stop()    # cancels background task

Feature flag: REGIME_WRITER_ENABLED (default true)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import sys
from pathlib import Path

import numpy as np

# Ensure project root is on sys.path (needed when run directly as __main__)
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger(__name__)

# Reuse the same EMA + regime logic from strategy_orchestrator
from signals.strategy_orchestrator import detect_regime, _ema

REGIME_KEY = "mcp:market_context"
DEFAULT_INTERVAL_S = 60


class RegimeWriter:
    """
    Background task that reads OHLCV from Redis, detects per-pair regime,
    and writes a JSON snapshot to ``mcp:market_context``.
    """

    def __init__(
        self,
        redis_client: Any,
        pairs: Optional[List[str]] = None,
        interval_s: int = DEFAULT_INTERVAL_S,
        enabled: bool = True,
    ):
        self._redis = redis_client
        self._pairs = pairs or ["BTC/USD"]
        self._interval_s = interval_s
        self._enabled = enabled
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_regimes: Dict[str, str] = {}

    async def start(self) -> None:
        """Start the background regime writer loop."""
        if not self._enabled:
            logger.info("[REGIME] RegimeWriter disabled via feature flag")
            return
        if self._task is not None:
            logger.warning("[REGIME] RegimeWriter already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="regime_writer")
        logger.info(
            "[REGIME] RegimeWriter started: pairs=%s interval=%ds",
            ",".join(self._pairs), self._interval_s,
        )

    async def stop(self) -> None:
        """Stop the background regime writer loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[REGIME] RegimeWriter stopped")

    async def _loop(self) -> None:
        """Main loop: compute regime → write to Redis → sleep."""
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[REGIME] tick error: %s", e, exc_info=True)
            await asyncio.sleep(self._interval_s)

    async def _tick(self) -> None:
        """Single iteration: read OHLCV for each pair, detect regime, publish."""
        from signals.ohlcv_reader import read_ohlcv_candles

        regimes: Dict[str, Dict[str, Any]] = {}
        primary_regime = "neutral"

        for pair in self._pairs:
            try:
                ohlcv = await read_ohlcv_candles(
                    redis_client=self._redis,
                    exchange="kraken",
                    pair=pair,
                    timeframe_s=60,
                    lookback=50,
                )
                if ohlcv is None or len(ohlcv) < 26:
                    regime = "neutral"
                    details: Dict[str, Any] = {"reason": "insufficient_ohlcv"}
                else:
                    regime = detect_regime(ohlcv)
                    closes = ohlcv[:, 3]
                    ema9 = _ema(closes, 9)
                    ema21 = _ema(closes, 21)
                    spread_pct = (ema9 - ema21) / ema21 * 100
                    vol = float(np.std(closes[-20:]) / np.mean(closes[-20:])) if len(closes) >= 20 else 0.0
                    roc = float((closes[-1] - closes[-11]) / closes[-11] * 100) if len(closes) >= 11 else 0.0
                    details = {
                        "ema_spread_pct": round(spread_pct, 4),
                        "volatility": round(vol, 5),
                        "roc_10": round(roc, 3),
                    }

                # Log transitions
                prev = self._last_regimes.get(pair, "unknown")
                if regime != prev:
                    logger.info(
                        "[REGIME] %s: %s -> %s (EMA spread=%.2f%%, ROC=%.1f%%)",
                        pair, prev, regime,
                        details.get("ema_spread_pct", 0),
                        details.get("roc_10", 0),
                    )
                self._last_regimes[pair] = regime

                regimes[pair] = {"regime": regime, **details}

                # First pair = primary
                if pair == self._pairs[0]:
                    primary_regime = regime

            except Exception as e:
                logger.warning("[REGIME] Error processing %s: %s", pair, e)
                regimes[pair] = {"regime": "neutral", "error": str(e)}

        # Build JSON payload
        payload = {
            "timestamp": time.time(),
            "primary_regime": primary_regime,
            "pairs": regimes,
        }

        # Write to Redis STRING key (SET, not XADD)
        try:
            client = self._redis.client
            await client.set(REGIME_KEY, json.dumps(payload))
            logger.debug("[REGIME] Published to %s: primary=%s", REGIME_KEY, primary_regime)
        except Exception as e:
            logger.error("[REGIME] Failed to write %s: %s", REGIME_KEY, e)


# ── Self-test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    print("=" * 60)
    print("Regime Writer — Self-Test (mock Redis)")
    print("=" * 60)

    class MockRedisInner:
        """Mock async Redis client."""
        def __init__(self):
            self.data: Dict[str, str] = {}
            self.streams: Dict[str, list] = {}

        async def set(self, key: str, value: str) -> None:
            self.data[key] = value

        async def xrevrange(self, key: str, count: int = 50) -> list:
            return self.streams.get(key, [])

    class MockRedisClient:
        """Mock RedisCloudClient wrapper."""
        def __init__(self):
            self._inner = MockRedisInner()

        @property
        def client(self):
            return self._inner

    async def run_test():
        mock = MockRedisClient()

        # Populate mock OHLCV stream (uptrend)
        np.random.seed(42)
        n = 50
        entries = []
        base = 68000.0
        for i in range(n):
            c = base + i * 15 + np.random.randn() * 30
            o = c - np.random.rand() * 20
            h = max(o, c) + np.random.rand() * 10
            l = min(o, c) - np.random.rand() * 10
            v = np.random.rand() * 80 + 20
            entry_id = f"1709000000000-{i}"
            fields = {
                "open": str(round(o, 2)),
                "high": str(round(h, 2)),
                "low": str(round(l, 2)),
                "close": str(round(c, 2)),
                "volume": str(round(v, 2)),
            }
            entries.append((entry_id, fields))

        # Set up stream keys the ohlcv_reader will try
        mock._inner.streams["kraken:ohlc:1m:BTC-USD"] = entries

        writer = RegimeWriter(mock, pairs=["BTC/USD"], interval_s=5, enabled=True)

        # Run one tick
        await writer._tick()

        # Check Redis was written
        raw = mock._inner.data.get(REGIME_KEY)
        assert raw is not None, "mcp:market_context not written!"
        payload = json.loads(raw)
        print(f"\nPayload written to {REGIME_KEY}:")
        print(f"  primary_regime: {payload['primary_regime']}")
        print(f"  BTC/USD regime: {payload['pairs']['BTC/USD']['regime']}")
        print(f"  EMA spread: {payload['pairs']['BTC/USD'].get('ema_spread_pct', 'N/A')}%")

        # Test start/stop lifecycle
        await writer.start()
        assert writer._task is not None
        await asyncio.sleep(0.1)
        await writer.stop()
        assert writer._task is None
        print("\nStart/stop lifecycle: PASS")

        # Test disabled
        writer_off = RegimeWriter(mock, enabled=False)
        await writer_off.start()
        assert writer_off._task is None
        print("Disabled test: PASS")

        print("\n" + "=" * 60)
        print("ALL SELF-TESTS PASSED")
        print("=" * 60)

    asyncio.run(run_test())
