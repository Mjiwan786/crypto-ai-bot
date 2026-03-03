"""
Multi-Exchange Signal Generator
================================

Reads OHLCV data from per-exchange Redis streams published by the
MultiExchangeStreamer and generates trading signals for each exchange
independently.

Publishes to:
    signals:{mode}:{exchange}:{pair}
    Example: signals:paper:coinbase:BTC-USD

This runs alongside the existing production_engine.py which handles
Kraken signals via its own pipeline.

Usage:
    python -m agents.multi_exchange_signal_generator \\
        --exchanges coinbase,binance,bybit \\
        --pairs BTC/USD,ETH/USD \\
        --mode paper
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig

logger = logging.getLogger(__name__)

# USDT exchanges — pairs are converted from BTC/USD -> BTC/USDT
_USDT_EXCHANGES = frozenset({"binance", "bybit", "okx", "kucoin", "gateio"})

# Minimum candles needed for signal generation
_MIN_CANDLES = 20

# Signal cooldown seconds (don't spam signals faster than this)
_SIGNAL_COOLDOWN_SEC = 60


class MultiExchangeSignalGenerator:
    """Generates trading signals from per-exchange OHLCV Redis streams.

    Reads from: {exchange}:ohlc:1m:{pair}
    Writes to:  signals:{mode}:{exchange}:{pair}
    """

    def __init__(
        self,
        redis_client: Any,
        exchanges: list[str],
        pairs: list[str],
        mode: str = "paper",
        poll_interval: int = 30,
    ) -> None:
        self.redis = redis_client
        self.exchanges = exchanges
        self.pairs = pairs
        self.mode = mode
        self.poll_interval = poll_interval
        self._shutdown = asyncio.Event()
        self._last_signal_time: dict[str, float] = {}

    async def run(self) -> None:
        """Run signal generation loop for all exchanges."""
        logger.info(
            "Starting multi-exchange signal generator: "
            "exchanges=%s, pairs=%s, mode=%s",
            self.exchanges, self.pairs, self.mode,
        )
        tasks = []
        for exchange_id in self.exchanges:
            for pair in self.pairs:
                mapped_pair = self._map_pair(pair, exchange_id)
                tasks.append(
                    asyncio.create_task(
                        self._generate_signals_loop(exchange_id, mapped_pair, pair),
                        name=f"signal:{exchange_id}:{pair}",
                    )
                )

        logger.info("Launched %d signal generation tasks", len(tasks))

        try:
            await self._shutdown.wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        self._shutdown.set()

    def _map_pair(self, pair: str, exchange_id: str) -> str:
        """Map USD pairs to USDT for exchanges that use USDT."""
        if exchange_id in _USDT_EXCHANGES:
            return pair.replace("/USD", "/USDT")
        return pair

    async def _generate_signals_loop(
        self, exchange_id: str, mapped_pair: str, original_pair: str
    ) -> None:
        """Continuous signal generation loop for one exchange/pair."""
        safe_pair = mapped_pair.replace("/", "-")
        stream_key = f"{exchange_id}:ohlc:1m:{safe_pair}"
        signal_key_id = f"{exchange_id}:{safe_pair}"

        while not self._shutdown.is_set():
            try:
                closes = await self._read_closes(stream_key)
                if len(closes) < _MIN_CANDLES:
                    await asyncio.sleep(self.poll_interval)
                    continue

                signal = self._compute_signal(closes, exchange_id, mapped_pair)
                if signal and self._check_cooldown(signal_key_id):
                    await self._publish_signal(
                        exchange_id, safe_pair, signal
                    )
                    self._last_signal_time[signal_key_id] = (
                        datetime.now(timezone.utc).timestamp()
                    )

            except Exception as exc:
                logger.warning(
                    "[%s] Signal gen error for %s: %s",
                    exchange_id, mapped_pair, exc,
                )

            await asyncio.sleep(self.poll_interval)

    async def _read_closes(self, stream_key: str, count: int = 50) -> list[float]:
        """Read recent close prices from an OHLCV Redis stream."""
        try:
            entries = await self.redis.xrevrange(stream_key, count=count)
            if not entries:
                return []

            closes = []
            for _, fields in entries:
                close_val = fields.get("close") or fields.get(b"close")
                if close_val:
                    if isinstance(close_val, bytes):
                        close_val = close_val.decode()
                    closes.append(float(close_val))

            closes.reverse()  # Chronological order
            return closes
        except Exception as exc:
            logger.debug("Failed to read %s: %s", stream_key, exc)
            return []

    def _compute_signal(
        self, closes: list[float], exchange_id: str, pair: str
    ) -> dict[str, Any] | None:
        """Compute a trading signal from close prices.

        Uses a simple momentum + mean-reversion strategy:
        - Short-term momentum (5-candle ROC)
        - Medium-term trend (20-candle EMA direction)
        - Volatility filter (ATR-based)
        """
        arr = np.array(closes)

        # Price change over last 5 candles
        roc_5 = (arr[-1] / arr[-6] - 1) * 100 if len(arr) >= 6 else 0.0

        # 20-candle EMA
        if len(arr) >= 20:
            weights = np.exp(np.linspace(-1, 0, 20))
            weights /= weights.sum()
            ema_20 = np.convolve(arr[-20:], weights, mode="valid")[0]
            trend = "bullish" if arr[-1] > ema_20 else "bearish"
        else:
            ema_20 = arr[-1]
            trend = "neutral"

        # ATR proxy (average absolute candle range)
        if len(arr) >= 15:
            ranges = np.abs(np.diff(arr[-15:]))
            atr_pct = (ranges.mean() / arr[-1]) * 100
        else:
            atr_pct = 0.0

        # Confidence scoring
        confidence = 0.5
        if abs(roc_5) > 0.5:
            confidence += 0.1
        if abs(roc_5) > 1.0:
            confidence += 0.1
        if trend == "bullish" and roc_5 > 0:
            confidence += 0.15
        elif trend == "bearish" and roc_5 < 0:
            confidence += 0.15
        if atr_pct < 2.0:
            confidence += 0.05  # Low volatility bonus
        confidence = min(confidence, 0.95)

        # Direction
        if roc_5 > 0.3 and trend == "bullish":
            direction = "long"
        elif roc_5 < -0.3 and trend == "bearish":
            direction = "short"
        else:
            return None  # No clear signal

        return {
            "exchange": exchange_id,
            "pair": pair,
            "direction": direction,
            "confidence": round(confidence, 3),
            "price": round(float(arr[-1]), 2),
            "roc_5": round(roc_5, 4),
            "trend": trend,
            "atr_pct": round(atr_pct, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _check_cooldown(self, key: str) -> bool:
        """Check if enough time has passed since last signal."""
        last = self._last_signal_time.get(key, 0)
        now = datetime.now(timezone.utc).timestamp()
        return (now - last) >= _SIGNAL_COOLDOWN_SEC

    async def _publish_signal(
        self, exchange_id: str, safe_pair: str, signal: dict[str, Any]
    ) -> None:
        """Publish signal to Redis stream."""
        stream_key = f"signals:{self.mode}:{exchange_id}:{safe_pair}"
        try:
            await self.redis.xadd(
                stream_key,
                {k: str(v) for k, v in signal.items()},
                maxlen=10000,
                approximate=True,
            )
            logger.info(
                "[%s] Signal: %s %s confidence=%.2f price=%s",
                exchange_id,
                signal["direction"],
                signal["pair"],
                signal["confidence"],
                signal["price"],
            )
        except Exception as exc:
            logger.error(
                "[%s] Failed to publish signal for %s: %s",
                exchange_id, safe_pair, exc,
            )


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Multi-Exchange Signal Generator"
    )
    parser.add_argument(
        "--exchanges",
        default=os.getenv(
            "SIGNAL_EXCHANGES", "coinbase,binance,bybit,okx,kucoin,gateio,bitfinex"
        ),
    )
    parser.add_argument(
        "--pairs",
        default=os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD,SOL/USD,LINK/USD"),
    )
    parser.add_argument("--mode", default="paper")
    parser.add_argument("--poll-interval", type=int, default=30)
    args = parser.parse_args()

    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        logger.error("REDIS_URL required")
        sys.exit(1)

    config = RedisCloudConfig(
        url=redis_url,
        ca_cert_path=os.getenv("REDIS_CA_CERT") or None,
    )
    client = RedisCloudClient(config)
    await client.connect()

    exchanges = [e.strip() for e in args.exchanges.split(",") if e.strip()]
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]

    gen = MultiExchangeSignalGenerator(
        redis_client=client.client,
        exchanges=exchanges,
        pairs=pairs,
        mode=args.mode,
        poll_interval=args.poll_interval,
    )

    try:
        await gen.run()
    finally:
        await gen.stop()
        await client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(main())
