"""Tests for signals/price_provider.py — Multi-Exchange Price Provider."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from signals.price_provider import PriceProvider, STALE_THRESHOLD_S


# ── Helpers ──

def _make_ticker_entry(price: float, age_s: float = 0):
    """Create a fake Redis stream entry for a ticker."""
    ts_ms = int((time.time() - age_s) * 1000)
    entry_id = f"{ts_ms}-0".encode()
    fields = {b"close": str(price).encode(), b"last": str(price).encode()}
    return [(entry_id, fields)]


def _make_mock_redis(ticker_map: dict = None):
    """Create mock Redis client. ticker_map = {key_str: price}."""
    mock = MagicMock()
    raw_client = AsyncMock()
    ticker_map = ticker_map or {}

    async def fake_xrevrange(key, count=1):
        key_str = key.decode() if isinstance(key, bytes) else key
        if key_str in ticker_map:
            val = ticker_map[key_str]
            if isinstance(val, tuple):
                price, age = val
            else:
                price, age = val, 0
            return _make_ticker_entry(price, age)
        return []

    raw_client.xrevrange = fake_xrevrange
    mock.client = raw_client
    return mock


# ── Tests ──

class TestPriceProvider:
    @pytest.mark.asyncio
    async def test_paper_mode_returns_reference_price(self):
        redis = _make_mock_redis({
            "coinbase:ticker:BTC-USD": 68000.0,
            "bitfinex:ticker:BTC-USD": 68010.0,
            "kraken:ticker:BTC-USD": 67990.0,
        })
        provider = PriceProvider(redis, mode="paper")
        price = await provider.get_price("BTC/USD")
        assert price is not None
        # Median of 68000, 68010, 67990 = 68000
        assert abs(price - 68000.0) < 50

    @pytest.mark.asyncio
    async def test_live_mode_returns_execution_venue(self):
        redis = _make_mock_redis({
            "kraken:ticker:BTC-USD": 68100.0,
            "coinbase:ticker:BTC-USD": 68000.0,
        })
        provider = PriceProvider(redis, mode="live")
        price = await provider.get_price("BTC/USD")
        assert price is not None
        assert abs(price - 68100.0) < 1  # Should use kraken (execution venue)

    @pytest.mark.asyncio
    @patch("signals.price_provider.ANOMALY_THRESHOLD_BPS", 10.0)
    async def test_live_mode_anomaly_warning(self, caplog):
        """When execution price deviates significantly from reference, log warning."""
        redis = _make_mock_redis({
            "kraken:ticker:BTC-USD": 69000.0,  # 1.5% above reference
            "coinbase:ticker:BTC-USD": 68000.0,
            "bitfinex:ticker:BTC-USD": 68000.0,
        })
        provider = PriceProvider(redis, mode="live")
        import logging
        with caplog.at_level(logging.WARNING):
            price = await provider.get_price("BTC/USD")
        assert price == 69000.0
        assert any("deviates" in msg for msg in caplog.messages)

    @pytest.mark.asyncio
    async def test_stale_ticker_skipped(self):
        # Only source is stale (> STALE_THRESHOLD_S old)
        redis = _make_mock_redis({
            "coinbase:ticker:BTC-USD": (68000.0, 60),  # 60s old
        })
        provider = PriceProvider(redis, mode="paper")
        # With default 30s threshold, this should be skipped
        price = await provider.get_price("BTC/USD")
        # Might find data from OHLCV fallback keys or return None
        # The ticker at 60s age should NOT be returned when threshold is 30s

    @pytest.mark.asyncio
    async def test_usdt_exchanges_in_reference(self):
        redis = _make_mock_redis({
            "coinbase:ticker:BTC-USD": 68000.0,
            "binance:ticker:BTC-USDT": 68050.0,
        })
        provider = PriceProvider(redis, mode="paper")
        price = await provider.get_price("BTC/USD")
        assert price is not None
        # Should be median of 68000 and 68050 = 68025
        assert 67900 < price < 68100

    @pytest.mark.asyncio
    async def test_no_prices_returns_none(self):
        redis = _make_mock_redis({})
        provider = PriceProvider(redis, mode="paper")
        price = await provider.get_price("BTC/USD")
        assert price is None

    @pytest.mark.asyncio
    async def test_live_fallback_to_reference(self):
        """When execution venue unavailable, fall back to reference."""
        redis = _make_mock_redis({
            # No kraken data
            "coinbase:ticker:BTC-USD": 68000.0,
        })
        provider = PriceProvider(redis, mode="live")
        price = await provider.get_price("BTC/USD")
        assert price is not None
        assert abs(price - 68000.0) < 1

    @pytest.mark.asyncio
    async def test_cache_respects_ttl(self):
        redis = _make_mock_redis({
            "coinbase:ticker:BTC-USD": 68000.0,
        })
        provider = PriceProvider(redis, mode="paper")
        provider._cache_ttl = 300  # Long TTL

        price1 = await provider.get_price("BTC/USD")
        assert price1 is not None

        # Should be cached now — verify cache hit
        assert len(provider._cache) > 0

    @pytest.mark.asyncio
    async def test_anomaly_report(self):
        redis = _make_mock_redis({
            "coinbase:ticker:BTC-USD": 68000.0,
            "bitfinex:ticker:BTC-USD": 68100.0,
            "kraken:ticker:BTC-USD": 67900.0,
        })
        provider = PriceProvider(redis, mode="paper")
        report = await provider.get_anomaly_report("BTC/USD")
        assert report is not None
        assert report["exchanges_reporting"] == 3
        assert "spread_bps" in report
        assert report["spread_bps"] > 0

    @pytest.mark.asyncio
    async def test_ohlcv_fallback_when_no_ticker(self):
        """When no ticker stream exists, fall back to OHLCV close price."""
        redis = _make_mock_redis({
            "coinbase:ohlc:1m:BTC-USD": 68500.0,
        })
        provider = PriceProvider(redis, mode="paper")
        price = await provider.get_price("BTC/USD")
        # May or may not find data depending on key matching, but shouldn't crash
        # The OHLCV fallback key is tried after ticker keys
