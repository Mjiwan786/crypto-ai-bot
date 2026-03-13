"""
Tests for on-chain Family D (consensus gate) and CoinglassClient.

Tests the cached Redis read path (not live HTTP).
"""
import json
import os
import time
import asyncio
import numpy as np
import pytest

from signals.consensus_gate import (
    _evaluate_onchain,
    evaluate_consensus,
    Family,
)
from market_data.onchain.coinglass_client import CoinglassClient


# ── Mock Redis for on-chain reads ────────────────────────────────────

class SyncMockRedis:
    """Sync mock Redis for _evaluate_onchain (which reads synchronously)."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def expire(self, key, ttl):
        pass


class SyncMockRedisClient:
    def __init__(self):
        self._inner = SyncMockRedis()

    @property
    def client(self):
        return self._inner


class AsyncMockRedis:
    """Async mock for CoinglassClient tests."""

    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value

    async def expire(self, key, ttl):
        pass


class AsyncMockRedisClient:
    def __init__(self):
        self._inner = AsyncMockRedis()

    @property
    def client(self):
        return self._inner


# ── _evaluate_onchain Tests ──────────────────────────────────────────

class TestOnchainVoting:
    def test_long_vote_low_ls_ratio(self):
        """OI increasing + low L/S ratio → LONG vote."""
        mock = SyncMockRedisClient()
        now = time.time()
        mock._inner.data["onchain:BTC:oi"] = json.dumps({
            "change_24h_pct": 5.0,   # >2% = OI increasing
            "timestamp": now,
        })
        mock._inner.data["onchain:BTC:ls_ratio"] = json.dumps({
            "ratio": 0.7,  # <0.85 = shorts overextended
            "timestamp": now,
        })

        vote = _evaluate_onchain("BTC/USD", mock)
        assert vote is not None
        assert vote.direction == "long"
        assert vote.family == Family.ONCHAIN
        assert vote.confidence == pytest.approx(0.55, abs=0.01)

    def test_short_vote_high_ls_ratio(self):
        """OI increasing + high L/S ratio → SHORT vote."""
        mock = SyncMockRedisClient()
        now = time.time()
        mock._inner.data["onchain:BTC:oi"] = json.dumps({
            "change_24h_pct": 3.5,
            "timestamp": now,
        })
        mock._inner.data["onchain:BTC:ls_ratio"] = json.dumps({
            "ratio": 1.5,  # >1.3 = longs overextended
            "timestamp": now,
        })

        vote = _evaluate_onchain("BTC/USD", mock)
        assert vote is not None
        assert vote.direction == "short"
        assert vote.confidence == pytest.approx(0.55, abs=0.01)

    def test_abstain_low_oi_change(self):
        """Low OI change (<2%) → abstain."""
        mock = SyncMockRedisClient()
        now = time.time()
        mock._inner.data["onchain:BTC:oi"] = json.dumps({
            "change_24h_pct": 1.0,  # <2%
            "timestamp": now,
        })
        mock._inner.data["onchain:BTC:ls_ratio"] = json.dumps({
            "ratio": 0.7,
            "timestamp": now,
        })

        vote = _evaluate_onchain("BTC/USD", mock)
        assert vote is None

    def test_abstain_neutral_ls_ratio(self):
        """Neutral L/S ratio (0.85-1.3) → abstain even with high OI."""
        mock = SyncMockRedisClient()
        now = time.time()
        mock._inner.data["onchain:BTC:oi"] = json.dumps({
            "change_24h_pct": 5.0,
            "timestamp": now,
        })
        mock._inner.data["onchain:BTC:ls_ratio"] = json.dumps({
            "ratio": 1.1,  # neutral zone
            "timestamp": now,
        })

        vote = _evaluate_onchain("BTC/USD", mock)
        assert vote is None

    def test_abstain_stale_data(self):
        """Data older than 10 minutes → abstain."""
        mock = SyncMockRedisClient()
        old_ts = time.time() - 700  # 11+ minutes old
        mock._inner.data["onchain:BTC:oi"] = json.dumps({
            "change_24h_pct": 5.0,
            "timestamp": old_ts,
        })
        mock._inner.data["onchain:BTC:ls_ratio"] = json.dumps({
            "ratio": 0.7,
            "timestamp": old_ts,
        })

        vote = _evaluate_onchain("BTC/USD", mock)
        assert vote is None

    def test_abstain_no_data(self):
        """No cached data → abstain."""
        mock = SyncMockRedisClient()
        vote = _evaluate_onchain("BTC/USD", mock)
        assert vote is None

    def test_abstain_no_redis(self):
        """No Redis client → abstain."""
        vote = _evaluate_onchain("BTC/USD", None)
        assert vote is None


# ── Feature flag test ────────────────────────────────────────────────

class TestOnchainFeatureFlag:
    def test_disabled_family_not_called(self, monkeypatch):
        """ONCHAIN_FAMILY_ENABLED=false → Family D never votes."""
        monkeypatch.setenv("ONCHAIN_FAMILY_ENABLED", "false")

        mock = SyncMockRedisClient()
        now = time.time()
        mock._inner.data["onchain:BTC:oi"] = json.dumps({
            "change_24h_pct": 5.0, "timestamp": now,
        })
        mock._inner.data["onchain:BTC:ls_ratio"] = json.dumps({
            "ratio": 0.7, "timestamp": now,
        })

        ohlcv = np.random.rand(50, 5) * 100 + 67000
        ohlcv[:, 1] = ohlcv[:, 3] + 50
        ohlcv[:, 2] = ohlcv[:, 3] - 50

        result = evaluate_consensus(ohlcv, pair="BTC/USD", redis_client=mock)
        # Family D should not appear in votes
        onchain_votes = [v for v in result.votes if v.family == Family.ONCHAIN]
        assert len(onchain_votes) == 0

    def test_enabled_family_can_vote(self, monkeypatch):
        """ONCHAIN_FAMILY_ENABLED=true → Family D can contribute."""
        monkeypatch.setenv("ONCHAIN_FAMILY_ENABLED", "true")

        mock = SyncMockRedisClient()
        now = time.time()
        mock._inner.data["onchain:BTC:oi"] = json.dumps({
            "change_24h_pct": 5.0, "timestamp": now,
        })
        mock._inner.data["onchain:BTC:ls_ratio"] = json.dumps({
            "ratio": 0.7, "timestamp": now,
        })

        # Use data that won't trigger other families, to isolate Family D
        ohlcv = np.full((50, 5), 68000.0)
        ohlcv[:, 0] = 67990.0  # open
        ohlcv[:, 1] = 68010.0  # high
        ohlcv[:, 2] = 67990.0  # low
        ohlcv[:, 4] = 50.0     # volume

        result = evaluate_consensus(
            ohlcv, pair="BTC/USD", redis_client=mock, min_families=1,
        )
        onchain_votes = [v for v in result.votes if v.family == Family.ONCHAIN]
        assert len(onchain_votes) == 1
        assert onchain_votes[0].direction == "long"


# ── CoinglassClient Tests ───────────────────────────────────────────

class TestCoinglassClient:
    def test_disabled_does_not_start(self):
        mock = AsyncMockRedisClient()
        client = CoinglassClient(mock, enabled=False)
        asyncio.run(client.start())
        assert client._task is None

    def test_start_stop_lifecycle(self):
        mock = AsyncMockRedisClient()
        client = CoinglassClient(mock, pairs=["BTC/USD"], enabled=True)

        async def run():
            await client.start()
            assert client._task is not None
            await asyncio.sleep(0.05)
            await client.stop()
            assert client._task is None

        asyncio.run(run())

    def test_rate_limiter(self):
        mock = AsyncMockRedisClient()
        client = CoinglassClient(mock)
        now = time.time()
        assert client._rate_limit_ok("oi", now) is True
        client._last_fetch["oi"] = now
        assert client._rate_limit_ok("oi", now + 10) is False
        assert client._rate_limit_ok("oi", now + 31) is True
