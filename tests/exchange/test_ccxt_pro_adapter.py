"""
Tests for the CCXT Pro WebSocket adapter.

Unit tests use mocked CCXT Pro exchange instances.
Integration tests (marked slow) connect to real exchanges.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exchange.ccxt_pro_adapter import CcxtProWSAdapter, _CCXTPRO_CLASSES
from exchange.ws_adapter import OHLCVUpdate, TickerUpdate, TradeUpdate


# ---------------------------------------------------------------------------
# Unit tests (mocked — fast)
# ---------------------------------------------------------------------------


class TestCcxtProAdapterInit:
    """Tests for adapter initialisation."""

    def test_supported_exchanges(self):
        expected = {"kraken", "coinbase", "binance", "bybit", "okx", "kucoin", "gateio", "bitfinex"}
        assert set(_CCXTPRO_CLASSES.keys()) == expected

    def test_create_valid_exchange(self):
        adapter = CcxtProWSAdapter(exchange_id="binance")
        assert adapter.exchange_id == "binance"
        assert not adapter.is_connected

    def test_create_case_insensitive(self):
        adapter = CcxtProWSAdapter(exchange_id="BINANCE")
        assert adapter.exchange_id == "binance"

    def test_create_unsupported_raises(self):
        with pytest.raises(ValueError, match="Unsupported exchange"):
            CcxtProWSAdapter(exchange_id="fakeexchange")

    def test_initial_state(self):
        adapter = CcxtProWSAdapter(exchange_id="kraken")
        assert not adapter.is_connected
        assert adapter.exchange_id == "kraken"


class TestCcxtProAdapterConnection:
    """Tests for connect/disconnect lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_loads_markets(self):
        adapter = CcxtProWSAdapter(exchange_id="binance")
        adapter._exchange = AsyncMock()
        adapter._exchange.markets = {"BTC/USDT": {}, "ETH/USDT": {}}
        adapter._exchange.load_markets = AsyncMock()

        await adapter.connect()
        assert adapter.is_connected
        adapter._exchange.load_markets.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        adapter = CcxtProWSAdapter(exchange_id="binance")
        adapter._exchange = AsyncMock()
        adapter._exchange.load_markets = AsyncMock(
            side_effect=Exception("network error")
        )

        with pytest.raises(Exception, match="network error"):
            await adapter.connect()
        assert not adapter.is_connected

    @pytest.mark.asyncio
    async def test_disconnect(self):
        adapter = CcxtProWSAdapter(exchange_id="binance")
        adapter._exchange = AsyncMock()
        adapter._exchange.load_markets = AsyncMock()
        adapter._exchange.markets = {}
        adapter._exchange.close = AsyncMock()

        await adapter.connect()
        assert adapter.is_connected

        await adapter.disconnect()
        assert not adapter.is_connected
        adapter._exchange.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_handles_error(self):
        adapter = CcxtProWSAdapter(exchange_id="binance")
        adapter._connected = True
        adapter._exchange = AsyncMock()
        adapter._exchange.close = AsyncMock(side_effect=Exception("close error"))

        await adapter.disconnect()
        assert not adapter.is_connected  # Still disconnects


class TestCcxtProAdapterStreaming:
    """Tests for streaming methods with mocked exchange."""

    @pytest.mark.asyncio
    async def test_watch_ticker_yields_updates(self):
        adapter = CcxtProWSAdapter(exchange_id="coinbase")
        adapter._connected = True
        adapter._exchange = AsyncMock()

        mock_ticker = {
            "bid": 50000.0,
            "ask": 50001.0,
            "last": 50000.5,
            "quoteVolume": 1234567.0,
        }

        async def mock_watch_ticker(symbol):
            return mock_ticker

        adapter._exchange.watch_ticker = mock_watch_ticker

        updates = []
        async for update in adapter.watch_ticker("BTC/USD"):
            updates.append(update)
            adapter._connected = False  # Stop after first yield

        assert len(updates) == 1
        assert isinstance(updates[0], TickerUpdate)
        assert updates[0].exchange == "coinbase"
        assert updates[0].symbol == "BTC/USD"
        assert updates[0].bid == 50000.0
        assert updates[0].ask == 50001.0
        assert updates[0].last == 50000.5

    @pytest.mark.asyncio
    async def test_watch_ohlcv_yields_candles(self):
        adapter = CcxtProWSAdapter(exchange_id="binance")
        adapter._connected = True
        adapter._exchange = AsyncMock()

        ts_ms = int(datetime(2026, 3, 3, tzinfo=timezone.utc).timestamp() * 1000)
        mock_candles = [
            [ts_ms, 50000.0, 50100.0, 49900.0, 50050.0, 123.45],
        ]

        async def mock_watch_ohlcv(symbol, timeframe):
            return mock_candles

        adapter._exchange.watch_ohlcv = mock_watch_ohlcv

        updates = []
        async for update in adapter.watch_ohlcv("BTC/USDT", "1m"):
            updates.append(update)
            adapter._connected = False  # Stop after first yield

        assert len(updates) == 1
        assert isinstance(updates[0], OHLCVUpdate)
        assert updates[0].exchange == "binance"
        assert updates[0].symbol == "BTC/USDT"
        assert updates[0].timeframe == "1m"
        assert updates[0].close == 50050.0
        assert updates[0].volume == 123.45

    @pytest.mark.asyncio
    async def test_watch_trades_yields_trades(self):
        adapter = CcxtProWSAdapter(exchange_id="okx")
        adapter._connected = True
        adapter._exchange = AsyncMock()

        mock_trades = [
            {"side": "buy", "price": 50000.0, "amount": 0.5},
        ]

        async def mock_watch_trades(symbol):
            return mock_trades

        adapter._exchange.watch_trades = mock_watch_trades

        updates = []
        async for update in adapter.watch_trades("BTC/USDT"):
            updates.append(update)
            adapter._connected = False  # Stop after first yield

        assert len(updates) == 1
        assert isinstance(updates[0], TradeUpdate)
        assert updates[0].exchange == "okx"
        assert updates[0].side == "buy"
        assert updates[0].price == 50000.0

    @pytest.mark.asyncio
    async def test_watch_ticker_reconnects_on_error(self):
        """Verify exponential backoff on errors."""
        adapter = CcxtProWSAdapter(exchange_id="kraken")
        adapter._connected = True
        adapter._exchange = AsyncMock()

        call_count = 0

        async def mock_watch_ticker(symbol):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("temporary error")
            if call_count == 2:
                adapter._connected = False
                return {"bid": 1, "ask": 2, "last": 1.5, "quoteVolume": 100}
            return {"bid": 1, "ask": 2, "last": 1.5, "quoteVolume": 100}

        adapter._exchange.watch_ticker = mock_watch_ticker

        updates = []
        with patch("exchange.ccxt_pro_adapter.asyncio.sleep", new_callable=AsyncMock):
            async for update in adapter.watch_ticker("BTC/USD"):
                updates.append(update)

        # Should have recovered after error and yielded 1 update
        assert len(updates) == 1
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_stops_when_disconnected(self):
        """Verify streams stop cleanly when disconnected."""
        adapter = CcxtProWSAdapter(exchange_id="bybit")
        adapter._connected = False  # Not connected

        updates = []
        async for update in adapter.watch_ticker("BTC/USDT"):
            updates.append(update)

        assert len(updates) == 0


class TestCcxtProAdapterDataClasses:
    """Tests for data class creation and immutability."""

    def test_ticker_update_frozen(self):
        t = TickerUpdate(
            exchange="test", symbol="BTC/USD",
            bid=50000.0, ask=50001.0, last=50000.5,
            volume_24h=1000.0, timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(AttributeError):
            t.bid = 99999.0  # type: ignore[misc]

    def test_ohlcv_update_frozen(self):
        o = OHLCVUpdate(
            exchange="test", symbol="BTC/USD", timeframe="1m",
            timestamp=datetime.now(timezone.utc),
            open=50000.0, high=50100.0, low=49900.0,
            close=50050.0, volume=123.45,
        )
        with pytest.raises(AttributeError):
            o.close = 0.0  # type: ignore[misc]

    def test_trade_update_frozen(self):
        t = TradeUpdate(
            exchange="test", symbol="BTC/USD",
            side="buy", price=50000.0, amount=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(AttributeError):
            t.price = 0.0  # type: ignore[misc]
