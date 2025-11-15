"""
D1 — Unit tests for graph.py (B1)

Tests:
- Graph nodes are pure functions (deterministic, no side effects)
- Typed payloads (Pydantic v2)
- State transitions work correctly
"""

from __future__ import annotations

import pytest

from orchestration.graph import (
    IngestPayload,
    AnalyzePayload,
    SelectPayload,
    EmitPayload,
    ingest_node,
    analyze_node,
    select_node,
    emit_node,
    build_graph,
    create_test_ingest_payload,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_ingest_payload() -> IngestPayload:
    """Create sample IngestPayload for testing."""
    return create_test_ingest_payload(
        symbol="BTCUSDT",
        timeframe="1m",
        mid_price=50000.0,
        spread_bps=5.0,
        n_candles=100,
    )


# =============================================================================
# TESTS: Node Purity (Deterministic)
# =============================================================================


def test_ingest_node_deterministic(sample_ingest_payload: IngestPayload):
    """Test that ingest_node is deterministic."""
    result1 = ingest_node(sample_ingest_payload)
    result2 = ingest_node(sample_ingest_payload)

    # Results should be identical
    assert result1.snapshot == result2.snapshot
    assert result1.ohlcv == result2.ohlcv
    assert result1.run_id == result2.run_id


def test_analyze_node_deterministic(sample_ingest_payload: IngestPayload):
    """Test that analyze_node is deterministic."""
    analyze_payload = ingest_node(sample_ingest_payload)

    result1 = analyze_node(analyze_payload)
    result2 = analyze_node(analyze_payload)

    # Results should be identical
    assert result1.regime_state.ta.label == result2.regime_state.ta.label
    assert result1.regime_state.ta.confidence == result2.regime_state.ta.confidence


def test_select_node_deterministic(sample_ingest_payload: IngestPayload):
    """Test that select_node is deterministic."""
    analyze_payload = ingest_node(sample_ingest_payload)
    select_payload = analyze_node(analyze_payload)

    result1 = select_node(select_payload)
    result2 = select_node(select_payload)

    # Results should be identical
    assert result1.strategy_advice.action == result2.strategy_advice.action
    assert result1.strategy_advice.side == result2.strategy_advice.side
    assert result1.strategy_advice.allocation == result2.strategy_advice.allocation


def test_emit_node_deterministic(sample_ingest_payload: IngestPayload):
    """Test that emit_node is deterministic (and pure)."""
    analyze_payload = ingest_node(sample_ingest_payload)
    select_payload = analyze_node(analyze_payload)
    emit_payload = select_node(select_payload)

    result1 = emit_node(emit_payload)
    result2 = emit_node(emit_payload)

    # Results should be identical
    assert result1.signals == result2.signals
    assert result1.publish_required == result2.publish_required


# =============================================================================
# TESTS: No Side Effects
# =============================================================================


def test_ingest_node_no_side_effects(sample_ingest_payload: IngestPayload):
    """Test that ingest_node doesn't modify input."""
    payload_copy = IngestPayload(**sample_ingest_payload.model_dump())

    ingest_node(sample_ingest_payload)

    # Input should be unchanged (frozen=True ensures this)
    assert sample_ingest_payload == payload_copy


def test_analyze_node_no_side_effects(sample_ingest_payload: IngestPayload):
    """Test that analyze_node doesn't modify input."""
    analyze_payload = ingest_node(sample_ingest_payload)
    payload_copy = AnalyzePayload(**analyze_payload.model_dump())

    analyze_node(analyze_payload)

    # Input should be unchanged
    assert analyze_payload == payload_copy


def test_select_node_no_side_effects(sample_ingest_payload: IngestPayload):
    """Test that select_node doesn't modify input."""
    analyze_payload = ingest_node(sample_ingest_payload)
    select_payload = analyze_node(analyze_payload)
    payload_copy = SelectPayload(**select_payload.model_dump())

    select_node(select_payload)

    # Input should be unchanged
    assert select_payload == payload_copy


# =============================================================================
# TESTS: Typed Payloads (Pydantic v2)
# =============================================================================


def test_ingest_payload_typed():
    """Test that IngestPayload is properly typed."""
    payload = create_test_ingest_payload()

    # Check types
    assert isinstance(payload, IngestPayload)
    assert isinstance(payload.symbol, str)
    assert isinstance(payload.mid_price, float)
    assert isinstance(payload.ohlcv, list)


def test_analyze_payload_typed(sample_ingest_payload: IngestPayload):
    """Test that AnalyzePayload is properly typed."""
    result = ingest_node(sample_ingest_payload)

    # Check types
    assert isinstance(result, AnalyzePayload)
    assert hasattr(result, 'snapshot')
    assert hasattr(result, 'ohlcv')


def test_select_payload_typed(sample_ingest_payload: IngestPayload):
    """Test that SelectPayload is properly typed."""
    analyze_payload = ingest_node(sample_ingest_payload)
    result = analyze_node(analyze_payload)

    # Check types
    assert isinstance(result, SelectPayload)
    assert hasattr(result, 'snapshot')
    assert hasattr(result, 'regime_state')


def test_emit_payload_typed(sample_ingest_payload: IngestPayload):
    """Test that EmitPayload is properly typed."""
    analyze_payload = ingest_node(sample_ingest_payload)
    select_payload = analyze_node(analyze_payload)
    result = select_node(select_payload)

    # Check types
    assert isinstance(result, EmitPayload)
    assert hasattr(result, 'strategy_advice')
    assert hasattr(result, 'signals')
    assert hasattr(result, 'publish_required')


# =============================================================================
# TESTS: Payload Validation (Pydantic v2 Strict)
# =============================================================================


def test_ingest_payload_frozen():
    """Test that IngestPayload is frozen (immutable)."""
    payload = create_test_ingest_payload()

    # Attempt to modify should raise error
    with pytest.raises(Exception):  # Pydantic ValidationError
        payload.symbol = "ETHUSDT"


def test_ingest_payload_extra_forbid():
    """Test that IngestPayload rejects extra fields."""
    with pytest.raises(Exception):  # Pydantic ValidationError
        IngestPayload(
            symbol="BTCUSDT",
            timeframe="1m",
            timestamp_ms=123,
            ohlcv=[],
            mid_price=50000.0,
            spread_bps=5.0,
            run_id="test",
            extra_field="should_fail"  # Extra field
        )


def test_invalid_ingest_payload():
    """Test that invalid IngestPayload raises ValidationError."""
    # IngestPayload doesn't have validation on mid_price (no constraints)
    # Instead, test with missing required field
    with pytest.raises(Exception):  # Pydantic ValidationError
        IngestPayload(
            symbol="BTCUSDT",
            timeframe="1m",
            # Missing timestamp_ms (required)
            ohlcv=[],
            mid_price=50000.0,
            spread_bps=5.0,
            run_id="test",
        )


# =============================================================================
# TESTS: State Transitions (INGEST → ANALYZE → SELECT → EMIT)
# =============================================================================


def test_full_graph_flow(sample_ingest_payload: IngestPayload):
    """Test complete graph flow through all states."""
    # INGEST → ANALYZE
    analyze_payload = ingest_node(sample_ingest_payload)
    assert isinstance(analyze_payload, AnalyzePayload)

    # ANALYZE → SELECT
    select_payload = analyze_node(analyze_payload)
    assert isinstance(select_payload, SelectPayload)

    # SELECT → EMIT
    emit_payload = select_node(select_payload)
    assert isinstance(emit_payload, EmitPayload)

    # EMIT (terminal)
    final_payload = emit_node(emit_payload)
    assert isinstance(final_payload, EmitPayload)


def test_graph_execute_complete(sample_ingest_payload: IngestPayload):
    """Test graph execution via build_graph()."""
    graph = build_graph()

    result = graph.invoke(sample_ingest_payload)

    # Should return EmitPayload
    assert isinstance(result, EmitPayload)
    assert result.run_id == sample_ingest_payload.run_id
    assert result.snapshot.symbol == sample_ingest_payload.symbol


# =============================================================================
# TESTS: Graph Properties
# =============================================================================


def test_graph_nodes_registered():
    """Test that graph has all expected nodes."""
    graph = build_graph()

    expected_nodes = ["INGEST", "ANALYZE", "SELECT", "EMIT"]
    assert list(graph.nodes.keys()) == expected_nodes


def test_graph_invoke_deterministic(sample_ingest_payload: IngestPayload):
    """Test that graph.invoke() is deterministic."""
    graph = build_graph()

    result1 = graph.invoke(sample_ingest_payload)
    result2 = graph.invoke(sample_ingest_payload)

    # Results should be identical
    assert result1.strategy_advice.action == result2.strategy_advice.action
    assert result1.strategy_advice.side == result2.strategy_advice.side


def test_graph_multiple_invocations_independent(sample_ingest_payload: IngestPayload):
    """Test that multiple graph invocations are independent."""
    graph = build_graph()

    results = []
    for _ in range(3):
        result = graph.invoke(sample_ingest_payload)
        results.append(result)

    # All results should be identical (deterministic, no shared state)
    for i in range(1, len(results)):
        assert results[i].strategy_advice.action == results[0].strategy_advice.action


# =============================================================================
# TESTS: No Redis/Network in Graph
# =============================================================================


def test_graph_no_network_calls(sample_ingest_payload: IngestPayload):
    """Test that graph execution doesn't make network calls."""
    import socket

    # Mock socket to detect network calls
    original_socket = socket.socket

    network_calls = []

    def mock_socket(*args, **kwargs):
        network_calls.append(("socket", args, kwargs))
        return original_socket(*args, **kwargs)

    socket.socket = mock_socket

    try:
        graph = build_graph()
        graph.invoke(sample_ingest_payload)

        # Should not have made any network calls
        assert len(network_calls) == 0, "Graph made network calls (should be pure)"

    finally:
        socket.socket = original_socket


def test_emit_payload_indicates_publish_requirement():
    """Test that EmitPayload has publish_required flag (for external adapters)."""
    payload = create_test_ingest_payload()
    graph = build_graph()

    result = graph.invoke(payload)

    # Should have publish_required flag
    assert hasattr(result, 'publish_required')
    assert isinstance(result.publish_required, bool)

    # If signals present, publish_required should be True
    if result.signals:
        assert result.publish_required is True


# =============================================================================
# TESTS: Performance
# =============================================================================


def test_graph_execution_fast(sample_ingest_payload: IngestPayload):
    """Test that graph execution is reasonably fast."""
    import time

    graph = build_graph()

    start = time.perf_counter()
    graph.invoke(sample_ingest_payload)
    end = time.perf_counter()

    latency_s = end - start

    # Should complete in under 0.5 seconds (generous for pure logic)
    assert latency_s < 0.5


def test_node_functions_fast():
    """Test that individual node functions are fast."""
    import time

    payload = create_test_ingest_payload()

    # Test INGEST node
    start = time.perf_counter()
    analyze_payload = ingest_node(payload)
    ingest_latency = time.perf_counter() - start

    # Test ANALYZE node
    start = time.perf_counter()
    select_payload = analyze_node(analyze_payload)
    analyze_latency = time.perf_counter() - start

    # Test SELECT node
    start = time.perf_counter()
    emit_payload = select_node(select_payload)
    select_latency = time.perf_counter() - start

    # All should be fast (<100ms each)
    assert ingest_latency < 0.1
    assert analyze_latency < 0.1
    assert select_latency < 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
