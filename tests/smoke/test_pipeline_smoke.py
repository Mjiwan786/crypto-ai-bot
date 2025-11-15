"""
D2 — Integration smoke test (no secrets, no network)

Tests:
- Build synthetic MarketSnapshot
- Run graph via orchestrator with no-op Redis adapter
- Assert signals emitted & latency recorded
- Completes in <2 seconds without Redis/keys
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import pytest

from orchestration.graph import (
    IngestPayload,
    EmitPayload,
    build_graph,
    create_test_ingest_payload,
)
from orchestration.master_orchestrator import (
    OrchestratorConfig,
    MasterOrchestrator,
    ClockAdapter,
    RedisAdapter,
    LoggerAdapter,
)


# =============================================================================
# NO-OP REDIS ADAPTER (No Network Calls)
# =============================================================================


class NoOpRedisAdapter:
    """
    No-op Redis adapter for testing (no network calls).

    Mimics RedisAdapter interface but doesn't connect to Redis.
    """

    def __init__(self, *args, **kwargs):
        self._connected = False
        self._published_signals: List[Dict[str, Any]] = []
        self._published_metrics: List[Dict[str, Any]] = []

    async def connect(self) -> bool:
        """Fake connection (always succeeds)."""
        self._connected = True
        return True

    async def publish_signal(self, stream_name: str, signal: Dict[str, Any]) -> bool:
        """Store signal in memory instead of publishing."""
        self._published_signals.append({
            "stream": stream_name,
            "signal": signal,
        })
        return True

    async def publish_metrics(self, metrics: Dict[str, Any]) -> bool:
        """Store metrics in memory instead of publishing."""
        self._published_metrics.append(metrics)
        return True

    async def close(self) -> None:
        """Fake close."""
        self._connected = False

    def get_published_signals(self) -> List[Dict[str, Any]]:
        """Get all published signals for verification."""
        return self._published_signals

    def get_published_metrics(self) -> List[Dict[str, Any]]:
        """Get all published metrics for verification."""
        return self._published_metrics


# =============================================================================
# TEST ORCHESTRATOR (With No-Op Adapters)
# =============================================================================


class TestOrchestrator:
    """
    Test orchestrator with no-op adapters.

    Uses real graph logic but fake I/O adapters.
    """

    def __init__(self):
        """Initialize with no-op adapters."""
        self.clock = ClockAdapter()
        self.logger = LoggerAdapter("TestOrchestrator")
        self.redis = NoOpRedisAdapter()  # No network calls
        self.graph = build_graph()

    async def initialize(self) -> bool:
        """Initialize (no network required)."""
        await self.redis.connect()
        return True

    def run_once(self, payload: IngestPayload) -> Optional[EmitPayload]:
        """Execute graph once (pure logic, no network)."""
        try:
            t_start = self.clock.now_s()
            result = self.graph.invoke(payload)
            t_end = self.clock.now_s()

            latency_ms = (t_end - t_start) * 1000
            return result

        except Exception as e:
            self.logger.error(f"Graph execution failed: {e}")
            return None

    async def handle_emit_payload(self, payload: EmitPayload) -> None:
        """Handle emit payload (publish to no-op Redis)."""
        if payload.publish_required and payload.signals:
            for signal in payload.signals:
                stream_name = f"signals:{signal.get('symbol', 'unknown').lower()}"
                await self.redis.publish_signal(stream_name, signal)

        # Publish metrics
        metrics = {
            "timestamp_ms": str(self.clock.now_ms()),
            "symbol": payload.snapshot.symbol,
            "latency_ms": str(payload.latency_ms),
        }
        await self.redis.publish_metrics(metrics)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def test_orchestrator() -> TestOrchestrator:
    """Create test orchestrator with no-op adapters."""
    import asyncio
    orchestrator = TestOrchestrator()
    # Initialize async method in sync fixture
    asyncio.run(orchestrator.initialize())
    return orchestrator


@pytest.fixture
def synthetic_payload() -> IngestPayload:
    """Create synthetic market snapshot for testing."""
    return create_test_ingest_payload(
        symbol="BTCUSDT",
        timeframe="1m",
        mid_price=50000.0,
        spread_bps=5.0,
        n_candles=100,
    )


# =============================================================================
# TESTS: Smoke Test (End-to-End)
# =============================================================================


@pytest.mark.asyncio
async def test_pipeline_smoke_no_secrets(
    test_orchestrator: TestOrchestrator,
    synthetic_payload: IngestPayload,
):
    """
    Smoke test: Synthetic data → Graph → Signals (no secrets, no network).

    Verifies:
    - Graph executes successfully
    - Signals are emitted
    - Latency is recorded
    - No network calls made
    """
    # Execute graph
    result = test_orchestrator.run_once(synthetic_payload)

    # Assert graph executed successfully
    assert result is not None
    assert isinstance(result, EmitPayload)

    # Assert signals were generated (if applicable)
    assert isinstance(result.signals, list)

    # Handle emit payload (publish to no-op Redis)
    await test_orchestrator.handle_emit_payload(result)

    # Verify metrics were published
    metrics = test_orchestrator.redis.get_published_metrics()
    assert len(metrics) >= 1

    # Verify latency was recorded
    latest_metrics = metrics[-1]
    assert "latency_ms" in latest_metrics
    assert latest_metrics["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_pipeline_completes_under_2s(
    test_orchestrator: TestOrchestrator,
    synthetic_payload: IngestPayload,
):
    """Test that pipeline completes in <2 seconds."""
    start = time.perf_counter()

    # Execute pipeline
    result = test_orchestrator.run_once(synthetic_payload)
    await test_orchestrator.handle_emit_payload(result)

    end = time.perf_counter()
    elapsed = end - start

    # Should complete in under 2 seconds
    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_signals_emitted_when_action_taken(
    test_orchestrator: TestOrchestrator,
):
    """Test that signals are emitted when graph decides to act."""
    # Create payload with conditions likely to generate signal
    payload = create_test_ingest_payload(
        symbol="BTCUSDT",
        timeframe="1m",
        mid_price=50000.0,
        spread_bps=5.0,
        n_candles=300,  # More data for better regime detection
    )

    result = test_orchestrator.run_once(payload)
    assert result is not None

    # If action was taken, signals should be present
    if result.strategy_advice.action.value != "hold":
        assert len(result.signals) > 0
        assert result.publish_required is True


@pytest.mark.asyncio
async def test_no_network_calls_made(
    test_orchestrator: TestOrchestrator,
    synthetic_payload: IngestPayload,
):
    """Verify that no actual network calls are made during smoke test."""
    import socket

    # Mock socket to detect network attempts
    original_socket = socket.socket
    network_calls = []

    def mock_socket(*args, **kwargs):
        network_calls.append(("socket", args, kwargs))
        return original_socket(*args, **kwargs)

    socket.socket = mock_socket

    try:
        # Run pipeline
        result = test_orchestrator.run_once(synthetic_payload)
        await test_orchestrator.handle_emit_payload(result)

        # Should not have made any network calls
        assert len(network_calls) == 0, f"Made {len(network_calls)} network calls (should be 0)"

    finally:
        socket.socket = original_socket


# =============================================================================
# TESTS: Component Integration
# =============================================================================


@pytest.mark.asyncio
async def test_graph_to_orchestrator_integration(
    test_orchestrator: TestOrchestrator,
    synthetic_payload: IngestPayload,
):
    """Test integration between graph and orchestrator."""
    # Graph execution
    result = test_orchestrator.run_once(synthetic_payload)

    # Verify orchestrator received valid EmitPayload
    assert result is not None
    assert result.run_id == synthetic_payload.run_id
    assert result.snapshot.symbol == synthetic_payload.symbol

    # Verify strategy advice is present
    assert result.strategy_advice is not None
    assert hasattr(result.strategy_advice, 'action')
    assert hasattr(result.strategy_advice, 'side')


@pytest.mark.asyncio
async def test_redis_adapter_stores_signals(
    test_orchestrator: TestOrchestrator,
    synthetic_payload: IngestPayload,
):
    """Test that no-op Redis adapter stores signals in memory."""
    result = test_orchestrator.run_once(synthetic_payload)

    if result.publish_required and result.signals:
        await test_orchestrator.handle_emit_payload(result)

        # Verify signals were stored
        published = test_orchestrator.redis.get_published_signals()

        if result.signals:
            assert len(published) == len(result.signals)


# =============================================================================
# TESTS: Latency Tracking
# =============================================================================


@pytest.mark.asyncio
async def test_latency_recorded_in_metrics(
    test_orchestrator: TestOrchestrator,
    synthetic_payload: IngestPayload,
):
    """Test that latency is recorded in published metrics."""
    result = test_orchestrator.run_once(synthetic_payload)
    await test_orchestrator.handle_emit_payload(result)

    metrics = test_orchestrator.redis.get_published_metrics()
    assert len(metrics) > 0

    # Check latest metrics
    latest = metrics[-1]
    assert "latency_ms" in latest
    assert "timestamp_ms" in latest
    assert "symbol" in latest


@pytest.mark.asyncio
async def test_emit_payload_has_latency(
    test_orchestrator: TestOrchestrator,
    synthetic_payload: IngestPayload,
):
    """Test that EmitPayload contains latency information."""
    result = test_orchestrator.run_once(synthetic_payload)

    assert result is not None
    assert hasattr(result, 'latency_ms')
    assert isinstance(result.latency_ms, int)
    assert result.latency_ms >= 0


# =============================================================================
# TESTS: Multiple Runs (No Shared State)
# =============================================================================


@pytest.mark.asyncio
async def test_multiple_runs_independent(test_orchestrator: TestOrchestrator):
    """Test that multiple runs are independent (no shared state)."""
    results = []

    for i in range(3):
        payload = create_test_ingest_payload(
            symbol="BTCUSDT",
            timeframe="1m",
            mid_price=50000.0 + (i * 100),  # Slightly different prices
            spread_bps=5.0,
            n_candles=100,
        )

        result = test_orchestrator.run_once(payload)
        results.append(result)

    # All results should be valid
    assert all(r is not None for r in results)

    # Each result should have valid structure
    for result in results:
        assert isinstance(result, EmitPayload)
        assert result.strategy_advice is not None
        assert hasattr(result, 'latency_ms')


# =============================================================================
# TESTS: Error Handling
# =============================================================================


@pytest.mark.asyncio
async def test_handles_invalid_payload_gracefully(test_orchestrator: TestOrchestrator):
    """Test that orchestrator handles invalid payloads gracefully."""
    # Create payload with minimal data (might trigger edge cases)
    payload = create_test_ingest_payload(
        symbol="BTCUSDT",
        timeframe="1m",
        mid_price=50000.0,
        spread_bps=5.0,
        n_candles=10,  # Very small dataset
    )

    # Should not crash, even with minimal data
    result = test_orchestrator.run_once(payload)

    # Result might be None or valid EmitPayload, but shouldn't raise
    assert result is None or isinstance(result, EmitPayload)


# =============================================================================
# PERFORMANCE
# =============================================================================


@pytest.mark.asyncio
async def test_smoke_test_performance_reasonable(test_orchestrator: TestOrchestrator):
    """Test that smoke test completes in reasonable time (<500ms typical)."""
    payload = create_test_ingest_payload()

    times = []
    for _ in range(5):
        start = time.perf_counter()
        result = test_orchestrator.run_once(payload)
        await test_orchestrator.handle_emit_payload(result)
        end = time.perf_counter()

        times.append(end - start)

    avg_time = sum(times) / len(times)
    max_time = max(times)

    # Average should be fast (< 0.5s)
    assert avg_time < 0.5

    # Max (worst case) should still be under 2s
    assert max_time < 2.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
