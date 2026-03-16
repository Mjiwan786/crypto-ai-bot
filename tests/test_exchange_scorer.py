"""Tests for signals/exchange_scorer.py — Exchange Quality Scorer."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from signals.exchange_scorer import (
    ExchangeScore,
    ExchangeScorer,
    SUPPORTED_EXCHANGES,
    USDT_EXCHANGES,
    TIMEFRAME_FORMATS,
)


# ── Helpers ──

def _make_ohlcv_entries(n: int, base_price: float = 100.0, spread_pct: float = 0.001, base_ts_ms: int = None):
    """Create fake Redis stream entries for testing."""
    if base_ts_ms is None:
        base_ts_ms = int(time.time() * 1000) - (n * 60000)
    entries = []
    for i in range(n):
        ts_ms = base_ts_ms + i * 60000
        entry_id = f"{ts_ms}-0".encode()
        c = base_price + np.random.normal(0, base_price * 0.001)
        h = c * (1 + spread_pct)
        low = c * (1 - spread_pct)
        fields = {
            b"open": str(c).encode(),
            b"high": str(h).encode(),
            b"low": str(low).encode(),
            b"close": str(c).encode(),
            b"volume": b"1000.0",
        }
        entries.append((entry_id, fields))
    return entries


def _make_mock_redis(entries_by_key: dict = None):
    """Create mock Redis client that returns entries for specific keys.
    Keys can be str or bytes — both are checked."""
    mock = MagicMock()
    raw_client = AsyncMock()
    entries_by_key = entries_by_key or {}

    # Normalize to both str and bytes variants
    normalized = {}
    for k, v in entries_by_key.items():
        k_str = k.decode() if isinstance(k, bytes) else k
        k_bytes = k.encode() if isinstance(k, str) else k
        normalized[k_str] = v
        normalized[k_bytes] = v

    async def fake_xrevrange(key, count=100):
        key_lookup = key.decode() if isinstance(key, bytes) else key
        if key_lookup in normalized:
            return list(reversed(normalized[key_lookup]))[:count]
        return []

    raw_client.xrevrange = fake_xrevrange
    mock.client = raw_client
    return mock


# ── Tests ──

class TestExchangeScore:
    def test_total_score_unavailable(self):
        s = ExchangeScore(exchange="test", pair="BTC/USD", timeframe="1m", available=False)
        assert s.total_score == 0.0

    def test_total_score_weighted(self):
        s = ExchangeScore(
            exchange="test", pair="BTC/USD", timeframe="1m",
            available=True,
            freshness_score=1.0,
            continuity_score=1.0,
            spread_score=1.0,
            reliability_score=1.0,
        )
        assert abs(s.total_score - 1.0) < 0.001

    def test_total_score_weights(self):
        s = ExchangeScore(
            exchange="test", pair="BTC/USD", timeframe="1m",
            available=True,
            freshness_score=1.0,
            continuity_score=0.0,
            spread_score=0.0,
            reliability_score=0.0,
        )
        assert abs(s.total_score - 0.35) < 0.001


class TestExchangeScorer:
    @pytest.mark.asyncio
    async def test_score_exchange_with_fresh_data(self):
        entries = _make_ohlcv_entries(50, base_price=68000.0)
        redis = _make_mock_redis({b"coinbase:ohlc:1m:BTC-USD": entries})
        scorer = ExchangeScorer()
        score = await scorer._score_exchange(redis, "coinbase", "BTC/USD", "BTC-USD", "1m", 100)
        assert score.available is True
        assert score.candle_count == 50
        assert score.freshness_score > 0.5
        assert score.continuity_score > 0.8

    @pytest.mark.asyncio
    async def test_score_exchange_missing_data(self):
        redis = _make_mock_redis({})
        scorer = ExchangeScorer()
        score = await scorer._score_exchange(redis, "coinbase", "BTC/USD", "BTC-USD", "1m", 100)
        assert score.available is False
        assert score.total_score == 0.0

    @pytest.mark.asyncio
    async def test_score_exchange_stale_data(self):
        # Data ending 30+ minutes ago (base 80min ago, 50 entries at 1min = ends 30min ago)
        old_ts = int((time.time() - 4800) * 1000)
        entries = _make_ohlcv_entries(50, base_price=68000.0, base_ts_ms=old_ts)
        redis = _make_mock_redis({b"coinbase:ohlc:1m:BTC-USD": entries})
        scorer = ExchangeScorer()
        score = await scorer._score_exchange(redis, "coinbase", "BTC/USD", "BTC-USD", "1m", 100)
        assert score.available is True
        assert score.freshness_score < 0.05  # Very stale

    @pytest.mark.asyncio
    async def test_usdt_exchange_builds_correct_key(self):
        scorer = ExchangeScorer()
        keys = scorer._build_key_candidates("binance", "BTC/USD", "BTC-USD", "1m")
        assert any("BTC-USDT" in k for k in keys), f"Expected USDT key, got: {keys}"
        assert not any(k.endswith("BTC-USD") and k.startswith("binance") for k in keys)

    @pytest.mark.asyncio
    async def test_usd_exchange_keeps_usd_key(self):
        scorer = ExchangeScorer()
        keys = scorer._build_key_candidates("coinbase", "BTC/USD", "BTC-USD", "1m")
        assert any("BTC-USD" in k for k in keys)
        assert not any("BTC-USDT" in k for k in keys)

    @pytest.mark.asyncio
    async def test_ranking_sorted_by_score(self):
        # Coinbase fresh, Bitfinex stale
        fresh_entries = _make_ohlcv_entries(50, base_price=68000.0)
        old_ts = int((time.time() - 3600) * 1000)
        stale_entries = _make_ohlcv_entries(50, base_price=68000.0, base_ts_ms=old_ts)

        redis = _make_mock_redis({
            b"coinbase:ohlc:1m:BTC-USD": fresh_entries,
            b"bitfinex:ohlc:1m:BTC-USD": stale_entries,
        })
        scorer = ExchangeScorer()
        ranked = await scorer.score_all(redis, "BTC/USD", "1m")

        available = [(ex, s) for ex, s in ranked if s.available]
        assert len(available) >= 2
        assert available[0][0] == "coinbase"  # Fresh data should rank first
        assert available[0][1].total_score > available[1][1].total_score

    @pytest.mark.asyncio
    async def test_cache_returns_within_ttl(self):
        entries = _make_ohlcv_entries(50)
        redis = _make_mock_redis({b"coinbase:ohlc:1m:BTC-USD": entries})

        scorer = ExchangeScorer(cache_ttl_s=300)
        result1 = await scorer.score_all(redis, "BTC/USD", "1m")
        result2 = await scorer.score_all(redis, "BTC/USD", "1m")
        # Same object from cache
        assert result1 is result2

    @pytest.mark.asyncio
    async def test_cache_invalidates_after_ttl(self):
        entries = _make_ohlcv_entries(50)
        redis = _make_mock_redis({b"coinbase:ohlc:1m:BTC-USD": entries})

        scorer = ExchangeScorer(cache_ttl_s=0)  # Immediate expiry
        result1 = await scorer.score_all(redis, "BTC/USD", "1m")
        result2 = await scorer.score_all(redis, "BTC/USD", "1m")
        # Different objects since cache expired
        assert result1 is not result2

    @pytest.mark.asyncio
    async def test_continuity_detects_gaps(self):
        # Create entries with a big gap in the middle
        base_ts = int(time.time() * 1000) - 100 * 60000
        entries = []
        for i in range(50):
            # Gap from candle 20 to 30 (10 missing candles)
            ts_offset = i if i < 20 else i + 10
            ts_ms = base_ts + ts_offset * 60000
            entry_id = f"{ts_ms}-0".encode()
            fields = {
                b"open": b"100.0", b"high": b"100.1",
                b"low": b"99.9", b"close": b"100.0", b"volume": b"1000",
            }
            entries.append((entry_id, fields))

        redis = _make_mock_redis({b"coinbase:ohlc:1m:BTC-USD": entries})
        scorer = ExchangeScorer()
        score = await scorer._score_exchange(redis, "coinbase", "BTC/USD", "BTC-USD", "1m", 100)
        assert score.available is True
        # Continuity should be penalized (50 actual over 60 expected time span)
        assert score.continuity_score < 0.95

    @pytest.mark.asyncio
    async def test_spread_score_penalizes_wide_spread(self):
        # Tight spread
        tight = _make_ohlcv_entries(50, spread_pct=0.0001)
        redis_tight = _make_mock_redis({b"coinbase:ohlc:1m:BTC-USD": tight})

        # Wide spread
        wide = _make_ohlcv_entries(50, spread_pct=0.01)
        redis_wide = _make_mock_redis({b"coinbase:ohlc:1m:BTC-USD": wide})

        scorer = ExchangeScorer()
        score_tight = await scorer._score_exchange(redis_tight, "coinbase", "BTC/USD", "BTC-USD", "1m", 100)
        scorer2 = ExchangeScorer()
        score_wide = await scorer2._score_exchange(redis_wide, "coinbase", "BTC/USD", "BTC-USD", "1m", 100)
        assert score_tight.spread_score > score_wide.spread_score

    @pytest.mark.asyncio
    async def test_get_best_returns_highest(self):
        entries = _make_ohlcv_entries(50)
        redis = _make_mock_redis({b"coinbase:ohlc:1m:BTC-USD": entries})
        scorer = ExchangeScorer()
        await scorer.score_all(redis, "BTC/USD", "1m")
        best = scorer.get_best("BTC/USD", "1m")
        assert best is not None
        assert best[0] == "coinbase"
        assert best[1].available is True

    @pytest.mark.asyncio
    async def test_get_ranked_returns_available_only(self):
        entries = _make_ohlcv_entries(50)
        redis = _make_mock_redis({b"coinbase:ohlc:1m:BTC-USD": entries})
        scorer = ExchangeScorer()
        await scorer.score_all(redis, "BTC/USD", "1m")
        ranked = scorer.get_ranked("BTC/USD", "1m")
        assert len(ranked) >= 1
        assert all(score > 0 for _, score in ranked)

    @pytest.mark.asyncio
    async def test_multiple_timeframe_formats(self):
        scorer = ExchangeScorer()
        keys = scorer._build_key_candidates("coinbase", "BTC/USD", "BTC-USD", "1m")
        # Should try "1m", "1", "60" format variants
        tf_variants = [k.split(":")[2] for k in keys if k.startswith("coinbase:")]
        assert "1m" in tf_variants or "1" in tf_variants or "60" in tf_variants

    @pytest.mark.asyncio
    async def test_invalidate_cache(self):
        entries = _make_ohlcv_entries(50)
        redis = _make_mock_redis({b"coinbase:ohlc:1m:BTC-USD": entries})
        scorer = ExchangeScorer(cache_ttl_s=300)
        await scorer.score_all(redis, "BTC/USD", "1m")
        assert scorer.get_best("BTC/USD", "1m") is not None
        scorer.invalidate_cache("BTC/USD", "1m")
        assert scorer.get_best("BTC/USD", "1m") is None
