"""
CCXT Pro WebSocket adapter implementation.

Connects to any exchange supported by CCXT Pro and streams real-time
market data.  Handles reconnection with exponential backoff, rate
limits, and exchange-specific quirks transparently.

Public market data only — no API keys required for streaming.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import ccxt.pro as ccxtpro

from exchange.ws_adapter import (
    BaseWSAdapter,
    OHLCVUpdate,
    TickerUpdate,
    TradeUpdate,
)

logger = logging.getLogger(__name__)

# Exchange class lookup — all 8 supported exchanges.
_CCXTPRO_CLASSES: dict[str, type] = {
    "kraken": ccxtpro.kraken,
    "coinbase": ccxtpro.coinbase,
    "binance": ccxtpro.binance,
    "bybit": ccxtpro.bybit,
    "okx": ccxtpro.okx,
    "kucoin": ccxtpro.kucoin,
    "gateio": ccxtpro.gateio,
    "bitfinex": ccxtpro.bitfinex,
}

# Maximum reconnect delay (seconds) for exponential backoff.
_MAX_BACKOFF = 30


class CcxtProWSAdapter(BaseWSAdapter):
    """CCXT Pro WebSocket adapter for real-time public market data."""

    def __init__(
        self,
        exchange_id: str,
        api_key: str = "",
        secret: str = "",
        passphrase: str = "",
    ) -> None:
        exchange_id = exchange_id.lower()
        if exchange_id not in _CCXTPRO_CLASSES:
            raise ValueError(
                f"Unsupported exchange: {exchange_id}. "
                f"Supported: {sorted(_CCXTPRO_CLASSES)}"
            )

        config: dict[str, Any] = {
            "enableRateLimit": True,
            "timeout": 30000,
            "newUpdates": True,
        }
        if api_key:
            config["apiKey"] = api_key
            config["secret"] = secret
        if passphrase:
            config["password"] = passphrase

        ExchangeClass = _CCXTPRO_CLASSES[exchange_id]
        self._exchange = ExchangeClass(config)
        self._exchange_id = exchange_id
        self._connected = False
        self._backoff = 1

    # -- Properties ----------------------------------------------------------

    @property
    def exchange_id(self) -> str:
        return self._exchange_id

    @property
    def is_connected(self) -> bool:
        return self._connected

    # -- Connection ----------------------------------------------------------

    async def connect(self) -> None:
        try:
            await self._exchange.load_markets()
            self._connected = True
            self._backoff = 1
            logger.info(
                "[%s] WebSocket connected — %d markets loaded",
                self._exchange_id,
                len(self._exchange.markets),
            )
        except Exception as exc:
            logger.error("[%s] Connect failed: %s", self._exchange_id, exc)
            raise

    async def disconnect(self) -> None:
        try:
            await self._exchange.close()
        except Exception as exc:
            logger.warning("[%s] Disconnect error: %s", self._exchange_id, exc)
        finally:
            self._connected = False
            logger.info("[%s] WebSocket disconnected", self._exchange_id)

    # -- Streaming -----------------------------------------------------------

    async def watch_ticker(self, symbol: str) -> AsyncIterator[TickerUpdate]:
        while self._connected:
            try:
                ticker = await self._exchange.watch_ticker(symbol)
                self._backoff = 1
                yield TickerUpdate(
                    exchange=self._exchange_id,
                    symbol=symbol,
                    bid=float(ticker.get("bid") or 0),
                    ask=float(ticker.get("ask") or 0),
                    last=float(ticker.get("last") or 0),
                    volume_24h=float(ticker.get("quoteVolume") or 0),
                    timestamp=datetime.now(timezone.utc),
                )
            except Exception as exc:
                if not self._connected:
                    break
                logger.warning(
                    "[%s] Ticker error %s: %s — reconnecting in %ds",
                    self._exchange_id, symbol, exc, self._backoff,
                )
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, _MAX_BACKOFF)

    async def watch_ohlcv(
        self, symbol: str, timeframe: str = "1m"
    ) -> AsyncIterator[OHLCVUpdate]:
        while self._connected:
            try:
                candles = await self._exchange.watch_ohlcv(symbol, timeframe)
                self._backoff = 1
                for candle in candles:
                    yield OHLCVUpdate(
                        exchange=self._exchange_id,
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=datetime.fromtimestamp(
                            candle[0] / 1000, tz=timezone.utc
                        ),
                        open=float(candle[1]),
                        high=float(candle[2]),
                        low=float(candle[3]),
                        close=float(candle[4]),
                        volume=float(candle[5]),
                    )
            except Exception as exc:
                if not self._connected:
                    break
                logger.warning(
                    "[%s] OHLCV error %s/%s: %s — reconnecting in %ds",
                    self._exchange_id, symbol, timeframe, exc, self._backoff,
                )
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, _MAX_BACKOFF)

    async def watch_trades(self, symbol: str) -> AsyncIterator[TradeUpdate]:
        while self._connected:
            try:
                trades = await self._exchange.watch_trades(symbol)
                self._backoff = 1
                for trade in trades:
                    yield TradeUpdate(
                        exchange=self._exchange_id,
                        symbol=symbol,
                        side=trade.get("side", "unknown"),
                        price=float(trade.get("price") or 0),
                        amount=float(trade.get("amount") or 0),
                        timestamp=datetime.now(timezone.utc),
                    )
            except Exception as exc:
                if not self._connected:
                    break
                logger.warning(
                    "[%s] Trades error %s: %s — reconnecting in %ds",
                    self._exchange_id, symbol, exc, self._backoff,
                )
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, _MAX_BACKOFF)

    async def watch_order_book(
        self, symbol: str, limit: int = 20
    ) -> AsyncIterator[dict[str, Any]]:
        while self._connected:
            try:
                ob = await self._exchange.watch_order_book(symbol, limit)
                self._backoff = 1
                yield {
                    "exchange": self._exchange_id,
                    "symbol": symbol,
                    "bids": ob.get("bids", [])[:limit],
                    "asks": ob.get("asks", [])[:limit],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            except Exception as exc:
                if not self._connected:
                    break
                logger.warning(
                    "[%s] OrderBook error %s: %s",
                    self._exchange_id, symbol, exc,
                )
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, _MAX_BACKOFF)
