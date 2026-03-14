"""Tests for agents.special.onchain_data_agent (Sprint 4B replacement)."""
import pytest

from agents.special.onchain_data_agent import OnChainDataAgent


class TestOnChainDataAgent:
    def test_no_redis_returns_empty(self) -> None:
        agent = OnChainDataAgent(redis_client=None)
        metrics = agent.fetch_metrics()
        assert metrics == {}

    def test_sync_fetch_returns_dict(self) -> None:
        agent = OnChainDataAgent()
        metrics = agent.fetch_metrics()
        assert isinstance(metrics, dict)

    @pytest.mark.asyncio
    async def test_async_no_redis(self) -> None:
        agent = OnChainDataAgent(redis_client=None)
        metrics = await agent.fetch_metrics_async("BTC")
        assert metrics == {}
