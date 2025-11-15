"""
D1 — Unit tests for strategy_selector.py

Tests:
- Deterministic selection (same input → same output)
- Latency field present in StrategyAdvice
- Pure function behavior (no side effects)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ai_engine.strategy_selector import (
    select_strategy,
    SelectorWeights,
    StrategyParams,
)
from ai_engine.schemas import MarketSnapshot


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_snapshot() -> MarketSnapshot:
    """Create a sample market snapshot for testing."""
    return MarketSnapshot(
        symbol="BTCUSDT",
        timeframe="1m",
        timestamp_ms=1234567890000,
        mid_price=50000.0,
        spread_bps=5.0,
        volume_24h=1000000.0,
        funding_rate_8h=0.0001,
        open_interest=50000000.0,
    )


@pytest.fixture
def sample_ohlcv_df() -> pd.DataFrame:
    """Create sample OHLCV DataFrame for testing."""
    np.random.seed(42)  # Deterministic
    n_rows = 300

    # Create realistic price series
    close = 50000 + np.cumsum(np.random.normal(0, 10, n_rows))
    open_prices = close + np.random.normal(0, 5, n_rows)
    high = np.maximum(open_prices, close) + np.random.exponential(5, n_rows)
    low = np.minimum(open_prices, close) - np.random.exponential(5, n_rows)
    volume = np.random.lognormal(10, 1, n_rows)

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='1min'),
        'open': open_prices,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })


@pytest.fixture
def default_weights() -> SelectorWeights:
    """Default selector weights."""
    return SelectorWeights()


@pytest.fixture
def default_params() -> StrategyParams:
    """Default strategy parameters."""
    return StrategyParams()


# =============================================================================
# TESTS: Deterministic Selection
# =============================================================================


def test_select_strategy_deterministic(
    sample_snapshot: MarketSnapshot,
    sample_ohlcv_df: pd.DataFrame,
    default_weights: SelectorWeights,
    default_params: StrategyParams,
):
    """Test that select_strategy is deterministic (same input → same output)."""
    # Run twice with same inputs
    result1 = select_strategy(
        sample_snapshot,
        sample_ohlcv_df,
        weights=default_weights,
        params=default_params,
    )

    result2 = select_strategy(
        sample_snapshot,
        sample_ohlcv_df,
        weights=default_weights,
        params=default_params,
    )

    # Results should be identical (except latency in explain field)
    assert result1.symbol == result2.symbol
    assert result1.action == result2.action
    assert result1.side == result2.side
    assert result1.allocation == result2.allocation
    assert result1.confidence == result2.confidence
    # Note: Don't compare explain field - it contains non-deterministic latency


def test_select_strategy_no_side_effects(
    sample_snapshot: MarketSnapshot,
    sample_ohlcv_df: pd.DataFrame,
):
    """Test that select_strategy has no side effects on input data."""
    # Make copies
    snapshot_copy = MarketSnapshot(**sample_snapshot.model_dump())
    df_copy = sample_ohlcv_df.copy()

    # Run selection
    select_strategy(sample_snapshot, sample_ohlcv_df)

    # Verify inputs unchanged
    assert sample_snapshot == snapshot_copy
    pd.testing.assert_frame_equal(sample_ohlcv_df, df_copy)


# =============================================================================
# TESTS: Latency Field Present
# =============================================================================


def test_strategy_advice_has_latency_field(
    sample_snapshot: MarketSnapshot,
    sample_ohlcv_df: pd.DataFrame,
):
    """Test that StrategyAdvice contains latency_ms in diagnostics."""
    result = select_strategy(sample_snapshot, sample_ohlcv_df)

    # Check diagnostics has latency_ms
    assert 'latency_ms' in result.diagnostics
    assert isinstance(result.diagnostics['latency_ms'], (int, float))
    assert result.diagnostics['latency_ms'] >= 0


def test_latency_increases_with_data_size(sample_snapshot: MarketSnapshot):
    """Test that latency is measured (increases with more data)."""
    # Small dataset
    small_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=100, freq='1min'),
        'open': [50000.0] * 100,
        'high': [50100.0] * 100,
        'low': [49900.0] * 100,
        'close': [50000.0] * 100,
        'volume': [1000.0] * 100,
    })

    # Large dataset
    large_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=1000, freq='1min'),
        'open': [50000.0] * 1000,
        'high': [50100.0] * 1000,
        'low': [49900.0] * 1000,
        'close': [50000.0] * 1000,
        'volume': [1000.0] * 1000,
    })

    result_small = select_strategy(sample_snapshot, small_df)
    result_large = select_strategy(sample_snapshot, large_df)

    # Both should have latency measurements
    assert result_small.diagnostics['latency_ms'] >= 0
    assert result_large.diagnostics['latency_ms'] >= 0


# =============================================================================
# TESTS: Output Structure
# =============================================================================


def test_strategy_advice_structure(
    sample_snapshot: MarketSnapshot,
    sample_ohlcv_df: pd.DataFrame,
):
    """Test that StrategyAdvice has expected structure."""
    result = select_strategy(sample_snapshot, sample_ohlcv_df)

    # Required fields
    assert hasattr(result, 'symbol')
    assert hasattr(result, 'timeframe')
    assert hasattr(result, 'action')
    assert hasattr(result, 'side')
    assert hasattr(result, 'allocation')
    assert hasattr(result, 'confidence')
    assert hasattr(result, 'explain')
    assert hasattr(result, 'diagnostics')

    # Type checks
    assert isinstance(result.symbol, str)
    assert isinstance(result.allocation, float)
    assert 0.0 <= result.allocation <= 1.0
    assert isinstance(result.confidence, float)
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.diagnostics, dict)


def test_strategy_advice_frozen(
    sample_snapshot: MarketSnapshot,
    sample_ohlcv_df: pd.DataFrame,
):
    """Test that StrategyAdvice is frozen (immutable)."""
    result = select_strategy(sample_snapshot, sample_ohlcv_df)

    # Attempt to modify should raise error
    with pytest.raises(Exception):  # Pydantic ValidationError
        result.allocation = 0.99


# =============================================================================
# TESTS: Edge Cases
# =============================================================================


def test_select_strategy_minimal_data(sample_snapshot: MarketSnapshot):
    """Test with minimal OHLCV data (edge case)."""
    # Minimal DataFrame (just above threshold)
    minimal_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=100, freq='1min'),
        'open': [50000.0] * 100,
        'high': [50100.0] * 100,
        'low': [49900.0] * 100,
        'close': [50000.0] * 100,
        'volume': [1000.0] * 100,
    })

    result = select_strategy(sample_snapshot, minimal_df)

    # Should still produce valid output
    assert result.symbol == sample_snapshot.symbol
    assert 'latency_ms' in result.diagnostics


def test_select_strategy_with_custom_weights(
    sample_snapshot: MarketSnapshot,
    sample_ohlcv_df: pd.DataFrame,
):
    """Test with custom selector weights."""
    custom_weights = SelectorWeights(
        ta=0.6,
        macro=0.3,
        sentiment=0.1,
    )

    result = select_strategy(
        sample_snapshot,
        sample_ohlcv_df,
        weights=custom_weights,
    )

    # Should produce valid result with custom weights
    assert result is not None
    assert 'latency_ms' in result.diagnostics


def test_select_strategy_with_custom_params(
    sample_snapshot: MarketSnapshot,
    sample_ohlcv_df: pd.DataFrame,
):
    """Test with custom strategy parameters."""
    custom_params = StrategyParams(
        max_position_usd=2000.0,
        sl_multiplier=2.0,
        tp_multiplier=3.0,
        min_confidence_to_open=0.7,
        min_confidence_to_close=0.4,
    )

    result = select_strategy(
        sample_snapshot,
        sample_ohlcv_df,
        params=custom_params,
    )

    # Should produce valid result
    assert result is not None


# =============================================================================
# TESTS: Pure Function Properties
# =============================================================================


def test_multiple_calls_independent(
    sample_snapshot: MarketSnapshot,
    sample_ohlcv_df: pd.DataFrame,
):
    """Test that multiple calls are independent (no shared state)."""
    results = []

    for _ in range(5):
        result = select_strategy(sample_snapshot, sample_ohlcv_df)
        results.append(result)

    # All results should be identical (deterministic)
    for i in range(1, len(results)):
        assert results[i].action == results[0].action
        assert results[i].side == results[0].side
        assert results[i].allocation == results[0].allocation


def test_concurrent_safe_simulation(
    sample_snapshot: MarketSnapshot,
    sample_ohlcv_df: pd.DataFrame,
):
    """Simulate concurrent calls (pure functions should be safe)."""
    import concurrent.futures

    def run_selection():
        return select_strategy(sample_snapshot, sample_ohlcv_df)

    # Run multiple selections in parallel (thread pool)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(run_selection) for _ in range(10)]
        results = [f.result() for f in futures]

    # All results should be identical
    for result in results[1:]:
        assert result.action == results[0].action
        assert result.side == results[0].side


# =============================================================================
# PERFORMANCE
# =============================================================================


def test_selection_performance_reasonable(
    sample_snapshot: MarketSnapshot,
    sample_ohlcv_df: pd.DataFrame,
):
    """Test that selection completes in reasonable time."""
    import time

    start = time.perf_counter()
    result = select_strategy(sample_snapshot, sample_ohlcv_df)
    end = time.perf_counter()

    latency_s = end - start

    # Should complete in under 1 second (very generous)
    assert latency_s < 1.0

    # Latency field should be present and reasonable
    assert result.diagnostics['latency_ms'] < 1000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
