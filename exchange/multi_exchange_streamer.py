"""
Multi-Exchange WebSocket Streamer
==================================

Connects to multiple exchanges via CCXT Pro and publishes real-time
market data to Redis streams.  Runs alongside the existing Kraken
production engine — they share the same Redis stream format.

REDIS STREAMS PUBLISHED:
    {exchange}:ohlc:{timeframe}:{symbol}   OHLCV candle data
    {exchange}:ticker:{symbol}             Real-time ticker
    {exchange}:heartbeat                   Heartbeat per exchange
    multi_exchange:metrics                 Aggregated metrics (STRING key)

The stream format matches production_engine.py so downstream consumers
(signals-api SSE, bot engine, signal generation) work unchanged.

USAGE:
    python -m exchange.multi_exchange_streamer \\
        --exchanges coinbase,binance,bybit,okx,kucoin,gateio,bitfinex \\
        --pairs BTC/USD,ETH/USD,SOL/USD,LINK/USD \\
        --timeframes 1m,5m,15m,1h
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from exchange.ccxt_pro_adapter import CcxtProWSAdapter

logger = logging.getLogger(__name__)

# USDT exchanges — pairs are converted from BTC/USD -> BTC/USDT, etc.
_USDT_EXCHANGES = frozenset({"binance", "bybit", "okx", "kucoin", "gateio"})

# Redis stream size caps
_OHLCV_MAXLEN = 5000
_TICKER_MAXLEN = 1000
_HEARTBEAT_MAXLEN = 100


class MultiExchangeStreamer:
    """
    Manages WebSocket connections to multiple exchanges and publishes
    all market data to Redis streams.
    """

    def __init__(
        self,
        redis_client: Any,
        exchanges: list[str],
        pairs: list[str],
        timeframes: list[str] | None = None,
        heartbeat_interval: int = 30,
        metrics_interval: int = 60,
    ) -> None:
        self.redis = redis_client
        self.exchange_ids = exchanges
        self.pairs = pairs
        self.timeframes = timeframes or ["1m", "5m", "15m", "1h"]
        self.heartbeat_interval = heartbeat_interval
        self.metrics_interval = metrics_interval

        # Adapter instances
        self.adapters: dict[str, CcxtProWSAdapter] = {}

        # Metrics tracking
        self.message_counts: dict[str, int] = {}
        self.error_counts: dict[str, int] = {}
        self.last_message_time: dict[str, float] = {}
        self.connected_exchanges: set[str] = set()

        # Shutdown event
        self._shutdown = asyncio.Event()

    # -- Public API ----------------------------------------------------------

    async def start(self) -> None:
        """Start streaming from all exchanges."""
        logger.info(
            "Starting multi-exchange streamer: "
            "exchanges=%s, pairs=%s, timeframes=%s",
            self.exchange_ids, self.pairs, self.timeframes,
        )

        # Connect to each exchange (failures are isolated)
        for ex_id in self.exchange_ids:
            try:
                adapter = CcxtProWSAdapter(exchange_id=ex_id)
                await adapter.connect()
                self.adapters[ex_id] = adapter
                self.connected_exchanges.add(ex_id)
                self.message_counts[ex_id] = 0
                self.error_counts[ex_id] = 0
                logger.info("[%s] Connected successfully", ex_id)
            except Exception as exc:
                logger.error("[%s] Failed to connect: %s", ex_id, exc)
                self.error_counts[ex_id] = 1

        if not self.connected_exchanges:
            logger.error("No exchanges connected. Exiting.")
            return

        # Launch concurrent streaming tasks
        tasks: list[asyncio.Task] = []

        for ex_id, adapter in self.adapters.items():
            ex_pairs = self._map_pairs(ex_id)

            # OHLCV streams — primary data for signal generation
            for pair in ex_pairs:
                for tf in self.timeframes:
                    tasks.append(
                        asyncio.create_task(
                            self._stream_ohlcv(adapter, pair, tf),
                            name=f"{ex_id}:ohlcv:{pair}:{tf}",
                        )
                    )

            # Ticker streams — for real-time pricing
            for pair in ex_pairs:
                tasks.append(
                    asyncio.create_task(
                        self._stream_ticker(adapter, pair),
                        name=f"{ex_id}:ticker:{pair}",
                    )
                )

            # Heartbeat per exchange
            tasks.append(
                asyncio.create_task(
                    self._heartbeat(ex_id),
                    name=f"{ex_id}:heartbeat",
                )
            )

        # Global metrics publisher
        tasks.append(
            asyncio.create_task(
                self._publish_metrics(),
                name="global:metrics",
            )
        )

        logger.info(
            "Launched %d streaming tasks across %d exchanges",
            len(tasks), len(self.connected_exchanges),
        )

        # Wait for shutdown signal
        try:
            await self._shutdown.wait()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received")
        finally:
            # Cancel all tasks
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.stop()

    async def stop(self) -> None:
        """Gracefully disconnect all exchanges."""
        self._shutdown.set()
        for ex_id, adapter in self.adapters.items():
            try:
                await adapter.disconnect()
            except Exception as exc:
                logger.warning("[%s] Disconnect error: %s", ex_id, exc)

    # -- Pair mapping --------------------------------------------------------

    def _map_pairs(self, exchange_id: str) -> list[str]:
        """Map standard USD pairs to exchange-specific format."""
        if exchange_id in _USDT_EXCHANGES:
            return [p.replace("/USD", "/USDT") for p in self.pairs]
        return list(self.pairs)

    # -- Stream publishers ---------------------------------------------------

    async def _stream_ohlcv(
        self, adapter: CcxtProWSAdapter, symbol: str, timeframe: str
    ) -> None:
        """Stream OHLCV data and publish to Redis."""
        safe_symbol = symbol.replace("/", "-")
        stream_key = f"{adapter.exchange_id}:ohlc:{timeframe}:{safe_symbol}"
        logger.info(
            "[%s] Streaming OHLCV %s %s -> %s",
            adapter.exchange_id, symbol, timeframe, stream_key,
        )

        async for candle in adapter.watch_ohlcv(symbol, timeframe):
            try:
                data = {
                    "exchange": adapter.exchange_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp": candle.timestamp.isoformat(),
                    "open": str(candle.open),
                    "high": str(candle.high),
                    "low": str(candle.low),
                    "close": str(candle.close),
                    "volume": str(candle.volume),
                    "published_at": datetime.now(timezone.utc).isoformat(),
                }
                await self.redis.xadd(
                    stream_key, data,
                    maxlen=_OHLCV_MAXLEN, approximate=True,
                )
                self.message_counts[adapter.exchange_id] = (
                    self.message_counts.get(adapter.exchange_id, 0) + 1
                )
                self.last_message_time[adapter.exchange_id] = time.time()
            except Exception as exc:
                logger.error(
                    "[%s] Redis publish error for %s: %s",
                    adapter.exchange_id, symbol, exc,
                )
                self.error_counts[adapter.exchange_id] = (
                    self.error_counts.get(adapter.exchange_id, 0) + 1
                )

    async def _stream_ticker(
        self, adapter: CcxtProWSAdapter, symbol: str
    ) -> None:
        """Stream ticker data and publish to Redis."""
        safe_symbol = symbol.replace("/", "-")
        stream_key = f"{adapter.exchange_id}:ticker:{safe_symbol}"

        async for ticker in adapter.watch_ticker(symbol):
            try:
                data = {
                    "exchange": adapter.exchange_id,
                    "symbol": symbol,
                    "bid": str(ticker.bid),
                    "ask": str(ticker.ask),
                    "last": str(ticker.last),
                    "volume_24h": str(ticker.volume_24h),
                    "timestamp": ticker.timestamp.isoformat(),
                }
                await self.redis.xadd(
                    stream_key, data,
                    maxlen=_TICKER_MAXLEN, approximate=True,
                )
                self.message_counts[adapter.exchange_id] = (
                    self.message_counts.get(adapter.exchange_id, 0) + 1
                )
                self.last_message_time[adapter.exchange_id] = time.time()
            except Exception:
                self.error_counts[adapter.exchange_id] = (
                    self.error_counts.get(adapter.exchange_id, 0) + 1
                )

    async def _heartbeat(self, exchange_id: str) -> None:
        """Publish heartbeat for exchange health monitoring."""
        while not self._shutdown.is_set():
            try:
                await self.redis.xadd(
                    f"{exchange_id}:heartbeat",
                    {
                        "exchange": exchange_id,
                        "status": (
                            "connected"
                            if exchange_id in self.connected_exchanges
                            else "disconnected"
                        ),
                        "messages": str(self.message_counts.get(exchange_id, 0)),
                        "errors": str(self.error_counts.get(exchange_id, 0)),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    maxlen=_HEARTBEAT_MAXLEN, approximate=True,
                )
            except Exception:
                pass
            await asyncio.sleep(self.heartbeat_interval)

    async def _publish_metrics(self) -> None:
        """Publish aggregated metrics across all exchanges."""
        while not self._shutdown.is_set():
            try:
                metrics: dict[str, str] = {
                    "connected_exchanges": ",".join(
                        sorted(self.connected_exchanges)
                    ),
                    "total_messages": str(sum(self.message_counts.values())),
                    "total_errors": str(sum(self.error_counts.values())),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                for ex_id in self.exchange_ids:
                    metrics[f"{ex_id}_msgs"] = str(
                        self.message_counts.get(ex_id, 0)
                    )
                    metrics[f"{ex_id}_errs"] = str(
                        self.error_counts.get(ex_id, 0)
                    )
                    last_ts = self.last_message_time.get(ex_id, 0)
                    metrics[f"{ex_id}_lag_sec"] = str(
                        round(time.time() - last_ts, 1) if last_ts else -1
                    )

                await self.redis.set(
                    "multi_exchange:metrics", json.dumps(metrics),
                )
            except Exception:
                pass
            await asyncio.sleep(self.metrics_interval)
