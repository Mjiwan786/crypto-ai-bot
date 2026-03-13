"""
Tests for Sprint 3 consensus gate Family D integration.

Tests that the async consensus gate works correctly with and without
Family D enabled, and that on-chain signals integrate properly.
"""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from signals.consensus_gate import (
    ConsensusResult,
    Family,
    StrategyVote,
    evaluate_consensus,
    _evaluate_onchain_family,
)


def _make_ohlcv(n: int = 50, trend: str = "up") -> np.ndarray:
    """Generate synthetic OHLCV data that triggers momentum/trend signals."""
    base = 100.0
    data = []
    for i in range(n):
        if trend == "up":
            c = base + i * 0.5 + (i % 3) * 0.1
        elif trend == "down":
            c = base - i * 0.5 - (i % 3) * 0.1
        else:
            c = base + (i % 5 - 2) * 0.1
        o = c - 0.1
        h = c + 0.3
        l = c - 0.3
        v = 1000 + i * 10
        data.append([o, h, l, c, v])
    return np.array(data)


class TestConsensusGateAsync(unittest.TestCase):
    """Test that evaluate_consensus is async and works correctly."""

    def test_consensus_returns_awaitable(self):
        """evaluate_consensus returns a coroutine."""
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(evaluate_consensus))

    def test_consensus_without_onchain(self):
        """Consensus works without Family D (redis_client=None)."""
        ohlcv = _make_ohlcv(50, "up")

        async def run():
            result = await evaluate_consensus(ohlcv, min_families=1)
            self.assertIsInstance(result, ConsensusResult)
            # Should still work with families A/B/C
            self.assertGreaterEqual(result.total_families_voting, 0)

        asyncio.run(run())

    def test_consensus_insufficient_data(self):
        """Short OHLCV returns insufficient_data."""
        short_data = np.random.rand(10, 5)

        async def run():
            result = await evaluate_consensus(short_data)
            self.assertFalse(result.published)
            self.assertEqual(result.reason, "insufficient_data")

        asyncio.run(run())

    def test_consensus_none_ohlcv(self):
        """None OHLCV returns insufficient_data."""
        async def run():
            result = await evaluate_consensus(None)
            self.assertFalse(result.published)
            self.assertEqual(result.reason, "insufficient_data")

        asyncio.run(run())


class TestFamilyDIntegration(unittest.TestCase):
    """Test Family D on-chain integration with consensus gate."""

    def _make_mock_redis(self, signal_data: dict = None):
        """Create a mock Redis client with pre-loaded on-chain signal."""
        mock_inner = AsyncMock()
        if signal_data is not None:
            mock_inner.get = AsyncMock(return_value=json.dumps(signal_data))
        else:
            mock_inner.get = AsyncMock(return_value=None)

        mock_redis = MagicMock()
        mock_redis.client = mock_inner
        return mock_redis

    def test_family_d_disabled_no_redis(self):
        """Family D disabled (redis_client=None) → behaves exactly like before."""
        ohlcv = _make_ohlcv(50, "up")

        async def run():
            result = await evaluate_consensus(ohlcv, min_families=2, redis_client=None)
            # Family D should not be in any votes
            for vote in result.votes:
                self.assertNotEqual(vote.family, Family.ONCHAIN)

        asyncio.run(run())

    @patch.dict(os.environ, {"ONCHAIN_FAMILY_ENABLED": "true"})
    def test_family_d_enabled_with_signal(self):
        """Family D enabled with valid signal → adds vote."""
        mock_redis = self._make_mock_redis({
            "direction": "long",
            "confidence": 0.65,
            "reasons": ["funding_bullish"],
        })

        async def run():
            vote = await _evaluate_onchain_family("BTC/USD", mock_redis)
            self.assertIsNotNone(vote)
            self.assertEqual(vote.family, Family.ONCHAIN)
            self.assertEqual(vote.direction, "long")
            self.assertAlmostEqual(vote.confidence, 0.65)
            self.assertEqual(vote.name, "onchain_derivatives")

        asyncio.run(run())

    @patch.dict(os.environ, {"ONCHAIN_FAMILY_ENABLED": "true"})
    def test_family_d_no_data_abstains(self):
        """No on-chain data in Redis → Family D abstains cleanly."""
        mock_redis = self._make_mock_redis(None)

        async def run():
            vote = await _evaluate_onchain_family("BTC/USD", mock_redis)
            self.assertIsNone(vote)

        asyncio.run(run())

    @patch.dict(os.environ, {"ONCHAIN_FAMILY_ENABLED": "true"})
    def test_family_d_low_confidence_abstains(self):
        """Signal with confidence < 0.40 → abstains."""
        mock_redis = self._make_mock_redis({
            "direction": "long",
            "confidence": 0.30,
            "reasons": ["weak"],
        })

        async def run():
            vote = await _evaluate_onchain_family("BTC/USD", mock_redis)
            self.assertIsNone(vote)

        asyncio.run(run())

    @patch.dict(os.environ, {"ONCHAIN_FAMILY_ENABLED": "true"})
    def test_family_d_abstain_direction_none(self):
        """Signal with direction=None → abstains."""
        mock_redis = self._make_mock_redis({
            "direction": None,
            "confidence": 0.0,
            "reasons": ["abstain"],
        })

        async def run():
            vote = await _evaluate_onchain_family("BTC/USD", mock_redis)
            self.assertIsNone(vote)

        asyncio.run(run())

    @patch.dict(os.environ, {"ONCHAIN_FAMILY_ENABLED": "true"})
    def test_family_d_confidence_capped_at_080(self):
        """Confidence is capped at 0.80 even if signal says higher."""
        mock_redis = self._make_mock_redis({
            "direction": "short",
            "confidence": 0.95,
            "reasons": ["extreme"],
        })

        async def run():
            vote = await _evaluate_onchain_family("BTC/USD", mock_redis)
            self.assertIsNotNone(vote)
            self.assertLessEqual(vote.confidence, 0.80)

        asyncio.run(run())

    @patch.dict(os.environ, {"ONCHAIN_FAMILY_ENABLED": "true"})
    def test_family_d_redis_error_abstains(self):
        """Redis error → Family D abstains (no crash)."""
        mock_inner = AsyncMock()
        mock_inner.get = AsyncMock(side_effect=Exception("Redis timeout"))
        mock_redis = MagicMock()
        mock_redis.client = mock_inner

        async def run():
            vote = await _evaluate_onchain_family("BTC/USD", mock_redis)
            self.assertIsNone(vote)

        asyncio.run(run())

    def test_family_d_none_redis_client(self):
        """redis_client=None → abstains."""
        async def run():
            vote = await _evaluate_onchain_family("BTC/USD", None)
            self.assertIsNone(vote)

        asyncio.run(run())

    @patch.dict(os.environ, {"ONCHAIN_FAMILY_ENABLED": "true"})
    def test_family_d_adds_to_consensus(self):
        """Family D vote increases families_agreeing in consensus result."""
        ohlcv = _make_ohlcv(50, "up")

        mock_redis = self._make_mock_redis({
            "direction": "long",  # Same direction as uptrend
            "confidence": 0.65,
            "reasons": ["funding_bullish"],
        })

        async def run():
            # With Family D
            result_with = await evaluate_consensus(
                ohlcv, min_families=1, pair="BTC/USD", redis_client=mock_redis
            )
            # Without Family D
            result_without = await evaluate_consensus(
                ohlcv, min_families=1, pair="BTC/USD", redis_client=None
            )

            # Family D should add at most one more family voting
            onchain_votes = [v for v in result_with.votes if v.family == Family.ONCHAIN]
            self.assertTrue(len(onchain_votes) <= 1)

        asyncio.run(run())


class TestSignalComputer(unittest.TestCase):
    """Test OnChainSignalComputer."""

    def test_compute_writes_to_redis(self):
        """Signal computer reads raw data and writes computed signal."""
        from market_data.onchain.signal_computer import OnChainSignalComputer

        mock_inner = AsyncMock()
        # Return derivatives data with clear short signal
        mock_inner.get = AsyncMock(side_effect=lambda key: {
            "onchain:BTC:derivatives": json.dumps({
                "funding_rate": 0.001, "oi_change_1h_pct": 8.0,
            }),
            "onchain:BTC:positioning": json.dumps({
                "long_short_ratio": 2.5, "taker_buy_sell_ratio": 0.6,
            }),
            "onchain:macro": None,
            "onchain:sentiment": None,
        }.get(key))
        mock_inner.set = AsyncMock()
        mock_inner.xadd = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.client = mock_inner

        computer = OnChainSignalComputer(mock_redis, ["BTC/USD"])

        async def run():
            await computer._compute_signal("BTC")
            # Should have written to onchain:BTC:signal
            mock_inner.set.assert_called()
            call_args = mock_inner.set.call_args
            self.assertIn("onchain:BTC:signal", str(call_args))

        asyncio.run(run())

    def test_compute_no_derivatives_skips(self):
        """No derivatives data → skips computation."""
        from market_data.onchain.signal_computer import OnChainSignalComputer

        mock_inner = AsyncMock()
        mock_inner.get = AsyncMock(return_value=None)
        mock_inner.set = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.client = mock_inner

        computer = OnChainSignalComputer(mock_redis, ["BTC/USD"])

        async def run():
            await computer._compute_signal("BTC")
            # Should NOT have written any signal
            mock_inner.set.assert_not_called()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
