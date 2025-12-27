"""
test_orchestrator_smoke.py

Lean, dependency-free smoke tests for crypto-ai-bot orchestrators.
- No real Redis/CCXT/OpenAI/network calls.
- Validates config loads, graph builds, one-pass run works, and mocks wire up.
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --------------------------------------------------------------------------------------
# Test helpers
# --------------------------------------------------------------------------------------

def _force_env(**pairs: str):
    return patch.dict(os.environ, {**pairs}, clear=False)

def _fake_module(name: str):
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod

# --------------------------------------------------------------------------------------
# Optional third-party placeholders so imports inside your code never fail during tests
# (we DO NOT use them directly; we only ensure import paths exist)
# --------------------------------------------------------------------------------------
# If some submodule is imported by your code, add a stub below as needed.

# Stub for 'ccxt' if missing
if "ccxt" not in sys.modules:
    ccxt = _fake_module("ccxt")
    # Provide a stub kraken() ctor if anything tries to call it
    def _kraken():
        ex = MagicMock()
        ex.fetch_balance.return_value = {"free": {"USD": 1000.0}}
        ex.fetch_ticker.return_value = {"last": 45000.0, "bid": 44990.0, "ask": 45010.0}
        return ex
    ccxt.kraken = _kraken  # type: ignore

# Stub for 'openai' if missing
if "openai" not in sys.modules:
    openai = _fake_module("openai")
    class _OpenAI:
        def __init__(self, *a, **k): ...
    openai.OpenAI = _OpenAI  # type: ignore

# Stub for 'redis.asyncio' if missing
if "redis" not in sys.modules:
    redis = _fake_module("redis")
    redis.asyncio = _fake_module("redis.asyncio")
    class _Redis:
        def __init__(self, *a, **k): ...
        @classmethod
        def from_url(cls, *a, **k): return cls()
        async def ping(self): return True
        async def xadd(self, *a, **k): return b"0-1"
        async def xread(self, *a, **k): return []
        async def close(self): ...
    redis.asyncio.Redis = _Redis  # type: ignore

# --------------------------------------------------------------------------------------
# Imports from your project
# --------------------------------------------------------------------------------------

from config.config_loader import get_config

# Trading Graph (matches your file: trading_graph.TradingGraph/build_graph/run_once)
from orchestrator_package.orchestrators.trading_graph import (
    TradingGraph,
    build_graph,
    run_once as graph_run_once,
)

# --------------------------------------------------------------------------------------
# Global, fast fixtures
# --------------------------------------------------------------------------------------

@pytest.fixture(scope="session")
def cfg():
    with _force_env(
        ORCHESTRATOR_DRY_RUN="true",
        PAPER_TRADING_ENABLED="true",
        MCP_ENABLED="true",
        REDIS_URL="redis://localhost:6379/0",
    ):
        return get_config()

@pytest.fixture
def fake_redis_manager():
    """
    Patches mcp.redis_manager.RedisManager.get_or_create to return an object
    that has a .client with xadd/close methods (async) used by the orchestrator.
    """
    fake_client = AsyncMock()
    fake_client.xadd.return_value = b"0-1"
    fake_client.close.return_value = None

    fake_mgr = MagicMock()
    fake_mgr.client = fake_client

    async def _get_or_create(*_a, **_k):
        return fake_mgr

    with patch(
        "orchestrator_package.mcp.redis_manager.RedisManager.get_or_create",
        side_effect=_get_or_create,
    ), patch(
        "orchestrator_package.orchestrators.trading_graph.RedisManager.get_or_create",
        side_effect=_get_or_create,
    ):
        yield fake_mgr

@pytest.fixture
def patched_tools_allows_everything():
    """
    Make the pipeline pass quickly:
      - signals get accepted,
      - pretrade risk approves,
      - order sending returns an ack immediately.
    """
    # process_and_publish(plan, ff, filters, ...) -> {'allowed': True, ...}
    allow_outcome = {"allowed": True, "raw_id": "ok", "filtered_id": "ok"}

    async def _proc_signal(*_a, **_k):
        return allow_outcome

    class _Ack(dict):  # simple dict-like ack
        pass

    async def _send_intent(*_a, **_k):
        return _Ack(status="ack", id="order-123", dry_run=_k.get("dry_run", True))

    # pretrade_check(...) -> RiskDecision(allowed=True)
    class _RiskDecision:
        def __init__(self): self.allowed = True; self.reasons = []
    async def _pretrade(*_a, **_k): return _RiskDecision()

    with patch(
        "orchestrator_package.orchestrators.tools.signal_tools.process_and_publish",
        side_effect=_proc_signal,
    ), patch(
        "orchestrator_package.orchestrators.tools.exec_tools.send_intent",
        side_effect=_send_intent,
    ), patch(
        "orchestrator_package.orchestrators.tools.risk_tools.pretrade_check",
        side_effect=_pretrade,
    ):
        yield

# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------

def test_config_loads_has_core_sections(cfg):
    assert hasattr(cfg, "redis"), "Missing redis section"
    assert hasattr(cfg, "risk"), "Missing risk section"
    assert hasattr(cfg, "exchanges"), "Missing exchanges section"
    assert getattr(cfg, "mcp", None) is not None, "Missing mcp section"
    # quick sanity of redis url
    assert str(cfg.redis.url).startswith(("redis://", "rediss://"))

@pytest.mark.asyncio
async def test_trading_graph_build_and_run_once(cfg, fake_redis_manager, patched_tools_allows_everything):
    """
    Build TradingGraph and execute a single pass with everything mocked.
    """
    # Build via class
    tg = TradingGraph(cfg)
    graph = tg.build()
    assert graph is not None

    # Run one full iteration
    state = await tg.run_once()
    assert state is not None
    # should not crash; allowed to have zero/one signals depending on upstream mocks
    assert isinstance(state.errors, list)

@pytest.mark.asyncio
async def test_build_graph_helper_and_invoke(cfg, fake_redis_manager, patched_tools_allows_everything):
    """
    Use the build_graph() helper (matches your trading_graph API).
    """
    compiled, initial_state = build_graph(cfg)
    assert compiled is not None
    assert initial_state is not None

    # The compiled graph exposes .ainvoke(state)
    result_state = await compiled.ainvoke(initial_state)
    assert result_state is not None
    assert hasattr(result_state, "metrics")

@pytest.mark.asyncio
async def test_run_once_helper(cfg, fake_redis_manager, patched_tools_allows_everything):
    """
    Use the run_once() convenience function.
    """
    result_state = await graph_run_once(cfg)
    assert result_state is not None
    assert isinstance(result_state.errors, list)

@pytest.mark.asyncio
async def test_performance_smoke(cfg, fake_redis_manager, patched_tools_allows_everything):
    """
    Ensure the mocked iteration is fast (< 2s).
    """
    import time
    start = time.time()
    _ = await graph_run_once(cfg)
    elapsed = time.time() - start
    assert elapsed < 2.0, f"Orchestrator too slow: {elapsed:.2f}s"

def test_environment_overrides_monkeypatch(cfg):
    """
    Ensure we can override env vars without breaking config.
    """
    with _force_env(REDIS_URL="redis://127.0.0.1:6380/1"):
        cfg2 = get_config()
        assert str(cfg2.redis.url).startswith("redis://127.0.0.1:6380")
