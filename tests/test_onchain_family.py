"""
Tests for on-chain Family D (consensus gate) and CoinglassClient.

Sprint 3 update: Family D now reads pre-computed signals from Redis
(written by signal_computer.py), not raw OI/LS data directly.
"""
import json
import os
import time
import asyncio
import numpy as np
import pytest

from signals.consensus_gate import (
    _evaluate_onchain_family,
    evaluate_consensus as _evaluate_consensus_async,
    Family,
)
from market_data.onchain.coinglass_client import CoinglassClient


def evaluate_consensus(*args, **kwargs):
    """Sync wrapper for tests."""
    return asyncio.run(_evaluate_consensus_async(*args, **kwargs))


# ── Mock Redis for on-chain reads (async, Sprint 3) ───────────────

class AsyncMockRedis:
    """Async mock Redis for Family D tests."""

    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def expire(self, key, ttl):
        pass


class AsyncMockRedisClient:
    def __init__(self):
        self._inner = AsyncMockRedis()

    @property
    def client(self):
        return self._inner


# ── _evaluate_onchain_family Tests ────────────────────────────────

class TestOnchainVoting:
    def test_long_signal_from_redis(self):
        """Pre-computed long signal in Redis → LONG vote."""
        mock = AsyncMockRedisClient()
        mock._inner.data["onchain:BTC:signal"] = json.dumps({
            "direction": "long",
            "confidence": 0.65,
            "reasons": ["funding_bullish"],
        })

        vote = asyncio.run(
            _evaluate_onchain_family("BTC/USD", mock)
        )
        assert vote is not None
        assert vote.direction == "long"
        assert vote.family == Family.ONCHAIN
        assert vote.confidence == pytest.approx(0.65, abs=0.01)
        assert vote.name == "onchain_derivatives"

    def test_short_signal_from_redis(self):
        """Pre-computed short signal in Redis → SHORT vote."""
        mock = AsyncMockRedisClient()
        mock._inner.data["onchain:BTC:signal"] = json.dumps({
            "direction": "short",
            "confidence": 0.70,
            "reasons": ["ls_crowded_longs"],
        })

        vote = asyncio.run(
            _evaluate_onchain_family("BTC/USD", mock)
        )
        assert vote is not None
        assert vote.direction == "short"
        assert vote.confidence == pytest.approx(0.70, abs=0.01)

    def test_abstain_low_confidence(self):
        """Signal with confidence < 0.40 → abstain."""
        mock = AsyncMockRedisClient()
        mock._inner.data["onchain:BTC:signal"] = json.dumps({
            "direction": "long",
            "confidence": 0.30,
            "reasons": ["weak"],
        })

        vote = asyncio.run(
            _evaluate_onchain_family("BTC/USD", mock)
        )
        assert vote is None

    def test_abstain_direction_none(self):
        """Signal with direction=None → abstain."""
        mock = AsyncMockRedisClient()
        mock._inner.data["onchain:BTC:signal"] = json.dumps({
            "direction": None,
            "confidence": 0.0,
            "reasons": ["abstain"],
        })

        vote = asyncio.run(
            _evaluate_onchain_family("BTC/USD", mock)
        )
        assert vote is None

    def test_abstain_no_data(self):
        """No cached data → abstain."""
        mock = AsyncMockRedisClient()
        vote = asyncio.run(
            _evaluate_onchain_family("BTC/USD", mock)
        )
        assert vote is None

    def test_abstain_no_redis(self):
        """No Redis client → abstain."""
        vote = asyncio.run(
            _evaluate_onchain_family("BTC/USD", None)
        )
        assert vote is None

    def test_confidence_capped_at_080(self):
        """Confidence capped at 0.80 even if signal says higher."""
        mock = AsyncMockRedisClient()
        mock._inner.data["onchain:BTC:signal"] = json.dumps({
            "direction": "short",
            "confidence": 0.95,
            "reasons": ["extreme"],
        })

        vote = asyncio.run(
            _evaluate_onchain_family("BTC/USD", mock)
        )
        assert vote is not None
        assert vote.confidence <= 0.80


# ── Feature flag test ────────────────────────────────────────────

class TestOnchainFeatureFlag:
    def test_disabled_family_not_called(self, monkeypatch):
        """ONCHAIN_FAMILY_ENABLED=false → Family D never votes."""
        monkeypatch.setenv("ONCHAIN_FAMILY_ENABLED", "false")

        mock = AsyncMockRedisClient()
        mock._inner.data["onchain:BTC:signal"] = json.dumps({
            "direction": "long",
            "confidence": 0.65,
            "reasons": ["funding_bullish"],
        })

        ohlcv = np.random.rand(50, 5) * 100 + 67000
        ohlcv[:, 1] = ohlcv[:, 3] + 50
        ohlcv[:, 2] = ohlcv[:, 3] - 50

        result = evaluate_consensus(ohlcv, pair="BTC/USD", redis_client=mock)
        onchain_votes = [v for v in result.votes if v.family == Family.ONCHAIN]
        assert len(onchain_votes) == 0

    def test_enabled_family_can_vote(self, monkeypatch):
        """ONCHAIN_FAMILY_ENABLED=true → Family D can contribute."""
        monkeypatch.setenv("ONCHAIN_FAMILY_ENABLED", "true")

        mock = AsyncMockRedisClient()
        mock._inner.data["onchain:BTC:signal"] = json.dumps({
            "direction": "long",
            "confidence": 0.65,
            "reasons": ["funding_bullish"],
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


# ── CoinglassClient Tests ───────────────────────────────────────

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
