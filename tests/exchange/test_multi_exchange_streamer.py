"""
Tests for the MultiExchangeStreamer.

Uses mocked Redis and exchange adapters for fast, deterministic testing.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exchange.multi_exchange_streamer import (
    MultiExchangeStreamer,
    _NO_WATCH_OHLCV,
    _USDT_EXCHANGES,
)
from exchange.ws_adapter import OHLCVUpdate, TickerUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_redis() -> AsyncMock:
    """Create a mock Redis client with xadd and set."""
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value="1234567890-0")
    redis.set = AsyncMock(return_value=True)
    return redis


# ---------------------------------------------------------------------------
# Tests: Pair mapping
# ---------------------------------------------------------------------------

class TestPairMapping:
    """Tests for USD -> USDT pair conversion."""

    def test_usd_exchange_keeps_usd(self):
        streamer = MultiExchangeStreamer(
            redis_client=_make_mock_redis(),
            exchanges=["kraken"],
            pairs=["BTC/USD", "ETH/USD"],
        )
        assert streamer._map_pairs("kraken") == ["BTC/USD", "ETH/USD"]

    def test_usdt_exchange_converts(self):
        streamer = MultiExchangeStreamer(
            redis_client=_make_mock_redis(),
            exchanges=["binance"],
            pairs=["BTC/USD", "ETH/USD", "SOL/USD"],
        )
        mapped = streamer._map_pairs("binance")
        assert mapped == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    def test_coinbase_keeps_usd(self):
        streamer = MultiExchangeStreamer(
            redis_client=_make_mock_redis(),
            exchanges=["coinbase"],
            pairs=["BTC/USD"],
        )
        assert streamer._map_pairs("coinbase") == ["BTC/USD"]

    def test_bitfinex_keeps_usd(self):
        streamer = MultiExchangeStreamer(
            redis_client=_make_mock_redis(),
            exchanges=["bitfinex"],
            pairs=["BTC/USD", "ETH/USD"],
        )
        assert streamer._map_pairs("bitfinex") == ["BTC/USD", "ETH/USD"]

    @pytest.mark.parametrize("exchange_id", sorted(_USDT_EXCHANGES))
    def test_all_usdt_exchanges(self, exchange_id):
        streamer = MultiExchangeStreamer(
            redis_client=_make_mock_redis(),
            exchanges=[exchange_id],
            pairs=["BTC/USD"],
        )
        assert streamer._map_pairs(exchange_id) == ["BTC/USDT"]


# ---------------------------------------------------------------------------
# Tests: OHLCV streaming to Redis
# ---------------------------------------------------------------------------

class TestStreamOHLCV:
    """Tests for _stream_ohlcv publishing to Redis."""

    @pytest.mark.asyncio
    async def test_publishes_to_correct_stream_key(self):
        """WebSocket path: non-Coinbase exchanges use watch_ohlcv."""
        mock_redis = _make_mock_redis()
        streamer = MultiExchangeStreamer(
            redis_client=mock_redis,
            exchanges=["kraken"],
            pairs=["BTC/USD"],
        )

        mock_adapter = MagicMock()
        mock_adapter.exchange_id = "kraken"

        candle = OHLCVUpdate(
            exchange="kraken", symbol="BTC/USD", timeframe="1m",
            timestamp=datetime(2026, 3, 3, 12, 0, 0, tzinfo=timezone.utc),
            open=50000.0, high=50100.0, low=49900.0,
            close=50050.0, volume=100.0,
        )

        async def mock_ohlcv_gen(symbol, timeframe):
            yield candle

        mock_adapter.watch_ohlcv = mock_ohlcv_gen

        await streamer._stream_ohlcv(mock_adapter, "BTC/USD", "1m")

        mock_redis.xadd.assert_awaited_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "kraken:ohlc:1m:BTC-USD"

        data = call_args[0][1]
        assert data["exchange"] == "kraken"
        assert data["symbol"] == "BTC/USD"
        assert data["close"] == "50050.0"
        assert data["source"] == "websocket"

    @pytest.mark.asyncio
    async def test_coinbase_uses_rest_polling(self):
        """REST path: Coinbase falls back to fetch_ohlcv polling."""
        mock_redis = _make_mock_redis()
        streamer = MultiExchangeStreamer(
            redis_client=mock_redis,
            exchanges=["coinbase"],
            pairs=["BTC/USD"],
        )

        mock_adapter = MagicMock()
        mock_adapter.exchange_id = "coinbase"
        mock_adapter._exchange = AsyncMock()

        # fetch_ohlcv returns data, then triggers shutdown
        async def fetch_then_stop(*args, **kwargs):
            streamer._shutdown.set()
            return [[1709467200000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0]]

        mock_adapter._exchange.fetch_ohlcv = AsyncMock(side_effect=fetch_then_stop)

        await streamer._stream_ohlcv(mock_adapter, "BTC/USD", "1m")

        mock_redis.xadd.assert_awaited_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "coinbase:ohlc:1m:BTC-USD"
        data = call_args[0][1]
        assert data["exchange"] == "coinbase"
        assert data["close"] == "50050.0"
        assert data["source"] == "rest_poll"

    @pytest.mark.asyncio
    async def test_rest_poll_skips_duplicate_timestamps(self):
        """REST polling deduplicates by timestamp."""
        mock_redis = _make_mock_redis()
        streamer = MultiExchangeStreamer(
            redis_client=mock_redis,
            exchanges=["coinbase"],
            pairs=["BTC/USD"],
        )

        mock_adapter = MagicMock()
        mock_adapter.exchange_id = "coinbase"
        mock_adapter._exchange = AsyncMock()

        async def fetch_dupes(*args, **kwargs):
            streamer._shutdown.set()
            return [
                [1709467200000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0],
                [1709467200000, 50000.0, 50100.0, 49900.0, 50060.0, 110.0],
            ]

        mock_adapter._exchange.fetch_ohlcv = AsyncMock(side_effect=fetch_dupes)

        await streamer._stream_ohlcv(mock_adapter, "BTC/USD", "1m")

        # Only one candle published (second is duplicate)
        assert mock_redis.xadd.await_count == 1

    @pytest.mark.asyncio
    async def test_increments_message_count(self):
        mock_redis = _make_mock_redis()
        streamer = MultiExchangeStreamer(
            redis_client=mock_redis,
            exchanges=["binance"],
            pairs=["BTC/USDT"],
        )
        streamer.message_counts["binance"] = 0

        mock_adapter = MagicMock()
        mock_adapter.exchange_id = "binance"

        candle = OHLCVUpdate(
            exchange="binance", symbol="BTC/USDT", timeframe="5m",
            timestamp=datetime(2026, 3, 3, tzinfo=timezone.utc),
            open=50000.0, high=50100.0, low=49900.0,
            close=50050.0, volume=50.0,
        )

        async def mock_ohlcv_gen(symbol, timeframe):
            yield candle

        mock_adapter.watch_ohlcv = mock_ohlcv_gen

        await streamer._stream_ohlcv(mock_adapter, "BTC/USDT", "5m")

        assert streamer.message_counts["binance"] == 1

    @pytest.mark.asyncio
    async def test_handles_redis_publish_error(self):
        mock_redis = _make_mock_redis()
        mock_redis.xadd = AsyncMock(side_effect=Exception("Redis down"))
        streamer = MultiExchangeStreamer(
            redis_client=mock_redis,
            exchanges=["okx"],
            pairs=["BTC/USDT"],
        )
        streamer.error_counts["okx"] = 0

        mock_adapter = MagicMock()
        mock_adapter.exchange_id = "okx"

        candle = OHLCVUpdate(
            exchange="okx", symbol="BTC/USDT", timeframe="1m",
            timestamp=datetime(2026, 3, 3, tzinfo=timezone.utc),
            open=50000.0, high=50100.0, low=49900.0,
            close=50050.0, volume=10.0,
        )

        async def mock_ohlcv_gen(symbol, timeframe):
            yield candle

        mock_adapter.watch_ohlcv = mock_ohlcv_gen

        await streamer._stream_ohlcv(mock_adapter, "BTC/USDT", "1m")

        # Should have incremented error count, not crashed
        assert streamer.error_counts["okx"] == 1


# ---------------------------------------------------------------------------
# Tests: Ticker streaming to Redis
# ---------------------------------------------------------------------------

class TestStreamTicker:
    """Tests for _stream_ticker publishing to Redis."""

    @pytest.mark.asyncio
    async def test_publishes_ticker_data(self):
        mock_redis = _make_mock_redis()
        streamer = MultiExchangeStreamer(
            redis_client=mock_redis,
            exchanges=["bybit"],
            pairs=["ETH/USDT"],
        )

        mock_adapter = MagicMock()
        mock_adapter.exchange_id = "bybit"

        ticker = TickerUpdate(
            exchange="bybit", symbol="ETH/USDT",
            bid=3000.0, ask=3001.0, last=3000.5, volume_24h=50000.0,
            timestamp=datetime(2026, 3, 3, tzinfo=timezone.utc),
        )

        async def mock_ticker_gen(symbol):
            yield ticker

        mock_adapter.watch_ticker = mock_ticker_gen

        await streamer._stream_ticker(mock_adapter, "ETH/USDT")

        mock_redis.xadd.assert_awaited_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "bybit:ticker:ETH-USDT"
        assert call_args[0][1]["last"] == "3000.5"


# ---------------------------------------------------------------------------
# Tests: Heartbeat
# ---------------------------------------------------------------------------

class TestHeartbeat:
    """Tests for the per-exchange heartbeat publisher."""

    @pytest.mark.asyncio
    async def test_publishes_heartbeat(self):
        mock_redis = _make_mock_redis()
        streamer = MultiExchangeStreamer(
            redis_client=mock_redis,
            exchanges=["kucoin"],
            pairs=[],
            heartbeat_interval=0,  # Immediate
        )
        streamer.connected_exchanges.add("kucoin")
        streamer.message_counts["kucoin"] = 42
        streamer.error_counts["kucoin"] = 1

        # Run one heartbeat iteration then shutdown
        async def stop_after_one():
            await asyncio.sleep(0.05)
            streamer._shutdown.set()

        await asyncio.gather(
            streamer._heartbeat("kucoin"),
            stop_after_one(),
        )

        assert mock_redis.xadd.await_count >= 1
        call_args = mock_redis.xadd.call_args_list[0]
        assert call_args[0][0] == "kucoin:heartbeat"
        data = call_args[0][1]
        assert data["exchange"] == "kucoin"
        assert data["status"] == "connected"
        assert data["messages"] == "42"


# ---------------------------------------------------------------------------
# Tests: Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    """Tests for the aggregated metrics publisher."""

    @pytest.mark.asyncio
    async def test_publishes_aggregated_metrics(self):
        mock_redis = _make_mock_redis()
        streamer = MultiExchangeStreamer(
            redis_client=mock_redis,
            exchanges=["coinbase", "binance"],
            pairs=[],
            metrics_interval=0,
        )
        streamer.connected_exchanges = {"coinbase", "binance"}
        streamer.message_counts = {"coinbase": 10, "binance": 20}
        streamer.error_counts = {"coinbase": 0, "binance": 1}

        async def stop_after_one():
            await asyncio.sleep(0.05)
            streamer._shutdown.set()

        await asyncio.gather(
            streamer._publish_metrics(),
            stop_after_one(),
        )

        assert mock_redis.set.await_count >= 1
        call_args = mock_redis.set.call_args_list[0]
        assert call_args[0][0] == "multi_exchange:metrics"
        metrics = json.loads(call_args[0][1])
        assert int(metrics["total_messages"]) == 30
        assert int(metrics["total_errors"]) == 1


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------

class TestStreamerInit:
    """Tests for MultiExchangeStreamer initialization."""

    def test_default_timeframes(self):
        streamer = MultiExchangeStreamer(
            redis_client=_make_mock_redis(),
            exchanges=["kraken"],
            pairs=["BTC/USD"],
        )
        assert streamer.timeframes == ["1m", "5m", "15m", "1h"]

    def test_custom_timeframes(self):
        streamer = MultiExchangeStreamer(
            redis_client=_make_mock_redis(),
            exchanges=["kraken"],
            pairs=["BTC/USD"],
            timeframes=["1m", "15m"],
        )
        assert streamer.timeframes == ["1m", "15m"]

    def test_initial_state(self):
        streamer = MultiExchangeStreamer(
            redis_client=_make_mock_redis(),
            exchanges=["coinbase", "binance"],
            pairs=["BTC/USD", "ETH/USD"],
        )
        assert len(streamer.adapters) == 0
        assert len(streamer.connected_exchanges) == 0
        assert not streamer._shutdown.is_set()
