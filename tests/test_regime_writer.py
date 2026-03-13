"""Tests for ai_engine/regime_detector/regime_writer.py"""
import asyncio
import json
import numpy as np
import pytest

from ai_engine.regime_detector.regime_writer import RegimeWriter, REGIME_KEY


# ── Mock Redis ───────────────────────────────────────────────────────

class MockRedisInner:
    def __init__(self):
        self.data = {}
        self.streams = {}

    async def set(self, key, value):
        self.data[key] = value

    async def xrevrange(self, key, count=50):
        return self.streams.get(key, [])


class MockRedisClient:
    def __init__(self):
        self._inner = MockRedisInner()

    @property
    def client(self):
        return self._inner


def _populate_stream(mock: MockRedisClient, key: str, n: int = 50, trend: float = 0.0):
    """Add synthetic OHLCV entries to a mock stream."""
    np.random.seed(42)
    entries = []
    base = 68000.0
    for i in range(n):
        c = base + (trend / n) * i + np.random.randn() * 30
        o = c - np.random.rand() * 20
        h = max(o, c) + np.random.rand() * 10
        l = min(o, c) - np.random.rand() * 10
        v = np.random.rand() * 80 + 20
        fields = {
            "open": str(round(o, 2)),
            "high": str(round(h, 2)),
            "low": str(round(l, 2)),
            "close": str(round(c, 2)),
            "volume": str(round(v, 2)),
        }
        entries.append((f"1709000000000-{i}", fields))
    mock._inner.streams[key] = entries


# ── Tests ────────────────────────────────────────────────────────────

class TestRegimeWriter:
    def test_tick_writes_to_redis(self):
        mock = MockRedisClient()
        _populate_stream(mock, "kraken:ohlc:1m:BTC-USD", 50)

        writer = RegimeWriter(mock, pairs=["BTC/USD"], interval_s=5)
        asyncio.run(writer._tick())

        raw = mock._inner.data.get(REGIME_KEY)
        assert raw is not None, "mcp:market_context not written"
        payload = json.loads(raw)
        assert "primary_regime" in payload
        assert "pairs" in payload
        assert "BTC/USD" in payload["pairs"]
        assert payload["pairs"]["BTC/USD"]["regime"] in ("bull", "bear", "sideways", "neutral")

    def test_tick_multi_pair(self):
        mock = MockRedisClient()
        _populate_stream(mock, "kraken:ohlc:1m:BTC-USD", 50)
        _populate_stream(mock, "kraken:ohlc:1m:ETH-USD", 50, trend=500)

        writer = RegimeWriter(mock, pairs=["BTC/USD", "ETH/USD"])
        asyncio.run(writer._tick())

        payload = json.loads(mock._inner.data[REGIME_KEY])
        assert "BTC/USD" in payload["pairs"]
        assert "ETH/USD" in payload["pairs"]

    def test_tick_missing_data_defaults_neutral(self):
        mock = MockRedisClient()
        # No stream data at all
        writer = RegimeWriter(mock, pairs=["BTC/USD"])
        asyncio.run(writer._tick())

        payload = json.loads(mock._inner.data[REGIME_KEY])
        assert payload["pairs"]["BTC/USD"]["regime"] == "neutral"

    def test_disabled_does_not_start(self):
        mock = MockRedisClient()
        writer = RegimeWriter(mock, enabled=False)
        asyncio.run(writer.start())
        assert writer._task is None

    def test_start_stop_lifecycle(self):
        mock = MockRedisClient()
        _populate_stream(mock, "kraken:ohlc:1m:BTC-USD", 50)

        async def run():
            writer = RegimeWriter(mock, pairs=["BTC/USD"], interval_s=1)
            await writer.start()
            assert writer._task is not None
            await asyncio.sleep(0.1)
            await writer.stop()
            assert writer._task is None

        asyncio.run(run())

    def test_payload_has_timestamp(self):
        mock = MockRedisClient()
        _populate_stream(mock, "kraken:ohlc:1m:BTC-USD", 50)

        writer = RegimeWriter(mock, pairs=["BTC/USD"])
        asyncio.run(writer._tick())

        payload = json.loads(mock._inner.data[REGIME_KEY])
        assert "timestamp" in payload
        assert isinstance(payload["timestamp"], float)

    def test_regime_transition_logged(self, caplog):
        """Verify regime transitions are logged."""
        mock = MockRedisClient()
        _populate_stream(mock, "kraken:ohlc:1m:BTC-USD", 50)

        writer = RegimeWriter(mock, pairs=["BTC/USD"])
        import logging
        with caplog.at_level(logging.INFO):
            asyncio.run(writer._tick())

        # First tick should log a transition from "unknown" to something
        assert any("[REGIME]" in r.message for r in caplog.records)
