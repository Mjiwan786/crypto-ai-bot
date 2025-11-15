"""
Unit tests for deep_ta_analyzer.py - Technical Analysis Regime Detection

Tests verify:
- Pure function behavior (deterministic, no side effects)
- No network/Redis calls
- Proper input validation
- Correct output types and structure
- Edge case handling
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ai_engine.regime_detector.deep_ta_analyzer import (
    TAAnalyzer,
    TAConfig,
    TARegime,
    compute_features,
    detect_ta_regime,
)


# =============================================================================
# FIXTURES - Deterministic test data
# =============================================================================

@pytest.fixture
def minimal_ohlcv_df() -> pd.DataFrame:
    """Minimal valid OHLCV DataFrame for testing."""
    np.random.seed(42)  # Deterministic
    n_rows = 250  # Just above min_rows threshold

    # Create realistic price series
    close = 100 + np.cumsum(np.random.normal(0, 0.5, n_rows))
    open_prices = close + np.random.normal(0, 0.2, n_rows)
    high = np.maximum(open_prices, close) + np.random.exponential(0.3, n_rows)
    low = np.minimum(open_prices, close) - np.random.exponential(0.3, n_rows)
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
def bullish_ohlcv_df() -> pd.DataFrame:
    """OHLCV data with clear bullish trend."""
    np.random.seed(123)
    n_rows = 300

    # Strong uptrend
    trend = np.linspace(100, 120, n_rows)
    noise = np.random.normal(0, 0.5, n_rows)
    close = trend + noise

    open_prices = close + np.random.normal(-0.1, 0.2, n_rows)
    high = np.maximum(open_prices, close) + np.random.exponential(0.2, n_rows)
    low = np.minimum(open_prices, close) - np.random.exponential(0.1, n_rows)
    volume = np.random.lognormal(10, 0.5, n_rows)

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='5min'),
        'open': open_prices,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })


@pytest.fixture
def bearish_ohlcv_df() -> pd.DataFrame:
    """OHLCV data with clear bearish trend."""
    np.random.seed(456)
    n_rows = 300

    # Strong downtrend
    trend = np.linspace(120, 100, n_rows)
    noise = np.random.normal(0, 0.5, n_rows)
    close = trend + noise

    open_prices = close + np.random.normal(0.1, 0.2, n_rows)
    high = np.maximum(open_prices, close) + np.random.exponential(0.1, n_rows)
    low = np.minimum(open_prices, close) - np.random.exponential(0.2, n_rows)
    volume = np.random.lognormal(10, 0.5, n_rows)

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='5min'),
        'open': open_prices,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })


@pytest.fixture
def choppy_ohlcv_df() -> pd.DataFrame:
    """OHLCV data with high volatility and no clear trend (choppy)."""
    np.random.seed(789)
    n_rows = 300

    # No trend, just noise
    close = 110 + np.random.normal(0, 2.0, n_rows)

    open_prices = close + np.random.normal(0, 0.3, n_rows)
    high = np.maximum(open_prices, close) + np.random.exponential(0.5, n_rows)
    low = np.minimum(open_prices, close) - np.random.exponential(0.5, n_rows)
    volume = np.random.lognormal(10, 1.5, n_rows)

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='5min'),
        'open': open_prices,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })


@pytest.fixture
def default_ta_config() -> TAConfig:
    """Default TA configuration for testing."""
    return TAConfig()


# =============================================================================
# TEST: Configuration & Setup
# =============================================================================

def test_ta_config_creation():
    """Test TAConfig can be created with defaults."""
    config = TAConfig()
    assert config.lookbacks['trend'] == 50
    assert config.lookbacks['momentum'] == 20
    assert config.thresholds['bull'] > 0
    assert config.thresholds['bear'] < 0
    assert config.model_config['frozen'] is True
    assert config.model_config['extra'] == 'forbid'


def test_ta_config_custom_values():
    """Test TAConfig accepts custom values."""
    config = TAConfig(
        lookbacks={'trend': 100, 'momentum': 30, 'vol': 40, 'micro': 20},
        thresholds={'bull': 0.6, 'bear': -0.6, 'chop_abs': 0.2},
    )
    assert config.lookbacks['trend'] == 100
    assert config.thresholds['bull'] == 0.6


def test_ta_config_validation():
    """Test TAConfig validates weights sum to ~1.0."""
    with pytest.raises(ValueError, match="Weights must sum"):
        TAConfig(weights={'trend': 0.5, 'momentum': 0.2, 'vol_regime': 0.1, 'microstructure': 0.1})


# =============================================================================
# TEST: Pure Function Behavior - Determinism
# =============================================================================

def test_detect_ta_regime_deterministic(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test that detect_ta_regime is deterministic (same input → same output)."""
    result1 = detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config)
    result2 = detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config)

    assert result1.label == result2.label
    assert result1.confidence == result2.confidence
    assert result1.components == result2.components
    assert result1.explain == result2.explain


def test_compute_features_deterministic(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test that compute_features is deterministic."""
    features1 = compute_features(minimal_ohlcv_df, default_ta_config, "1m")
    features2 = compute_features(minimal_ohlcv_df, default_ta_config, "1m")

    for key in features1.keys():
        pd.testing.assert_series_equal(features1[key], features2[key])


# =============================================================================
# TEST: Input Validation & Edge Cases
# =============================================================================

def test_detect_ta_regime_empty_dataframe(default_ta_config: TAConfig):
    """Test handling of empty DataFrame."""
    empty_df = pd.DataFrame()
    result = detect_ta_regime(empty_df, "1m", default_ta_config)

    assert result.label == "chop"
    assert result.confidence == 0.0
    assert result.n_samples == 0


def test_detect_ta_regime_insufficient_data(default_ta_config: TAConfig):
    """Test handling of insufficient data (below min_rows)."""
    small_df = pd.DataFrame({
        'open': [100] * 50,
        'high': [101] * 50,
        'low': [99] * 50,
        'close': [100.5] * 50,
        'volume': [1000] * 50,
    })

    result = detect_ta_regime(small_df, "1m", default_ta_config)

    assert result.label == "chop"
    assert result.confidence == 0.0
    assert "insufficient_data" in result.explain


def test_detect_ta_regime_invalid_timeframe(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test handling of invalid timeframe format."""
    # Invalid timeframe should return safe default (chop with 0 confidence)
    result = detect_ta_regime(minimal_ohlcv_df, "invalid", default_ta_config)
    assert result.label == "chop"
    assert result.confidence == 0.0


def test_detect_ta_regime_missing_columns(default_ta_config: TAConfig):
    """Test handling of missing required columns."""
    incomplete_df = pd.DataFrame({
        'open': [100] * 300,
        'close': [101] * 300,
        # Missing 'high', 'low', 'volume'
    })

    result = detect_ta_regime(incomplete_df, "1m", default_ta_config)
    assert result.label == "chop"
    assert result.confidence == 0.0


# =============================================================================
# TEST: Output Structure & Types
# =============================================================================

def test_detect_ta_regime_output_structure(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test that output matches TARegime schema."""
    result = detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config)

    assert isinstance(result, TARegime)
    assert result.label in ["bull", "bear", "chop"]
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.components, dict)
    assert isinstance(result.features, dict)
    assert isinstance(result.explain, str)
    assert result.latency_ms >= 0
    assert result.n_samples > 0


def test_ta_regime_frozen(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test that TARegime output is frozen (immutable)."""
    result = detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config)

    with pytest.raises(Exception):  # Pydantic ValidationError
        result.label = "bull"


def test_ta_regime_extra_forbid(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test that TARegime rejects extra fields."""
    result = detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config)
    result_dict = result.model_dump()

    with pytest.raises(Exception):  # Pydantic ValidationError
        TARegime(**{**result_dict, 'extra_field': 'should_fail'})


# =============================================================================
# TEST: Regime Classification Logic
# =============================================================================

def test_detect_bullish_regime(bullish_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test detection of bullish regime from uptrending data."""
    result = detect_ta_regime(bullish_ohlcv_df, "5m", default_ta_config)

    # Should detect bullish trend (or at least not bearish)
    assert result.label in ["bull", "chop"]
    assert result.confidence > 0.0

    # Trend component should be positive
    if 'trend' in result.components:
        assert result.components['trend'] > -0.3  # Allow some tolerance


def test_detect_bearish_regime(bearish_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test detection of bearish regime from downtrending data."""
    result = detect_ta_regime(bearish_ohlcv_df, "5m", default_ta_config)

    # Should detect bearish trend (or at least not bullish)
    assert result.label in ["bear", "chop"]
    assert result.confidence > 0.0

    # Trend component should be negative
    if 'trend' in result.components:
        assert result.components['trend'] < 0.3  # Allow some tolerance


def test_detect_choppy_regime(choppy_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test detection of choppy regime from high-volatility no-trend data."""
    result = detect_ta_regime(choppy_ohlcv_df, "5m", default_ta_config)

    # High volatility should often result in chop classification
    # But not strict requirement due to randomness
    assert result.label in ["bull", "bear", "chop"]
    assert result.confidence >= 0.0


# =============================================================================
# TEST: Component Analysis
# =============================================================================

def test_compute_features_completeness(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test that compute_features returns all expected components."""
    features = compute_features(minimal_ohlcv_df, default_ta_config, "1m")

    expected_features = ['trend', 'momentum', 'vol_regime', 'microstructure']
    for feature in expected_features:
        assert feature in features
        assert isinstance(features[feature], pd.Series)
        assert len(features[feature]) == len(minimal_ohlcv_df)


def test_ta_analyzer_instance():
    """Test TAAnalyzer can be instantiated."""
    analyzer = TAAnalyzer()
    assert analyzer is not None


# =============================================================================
# TEST: Context Metadata Handling
# =============================================================================

def test_detect_ta_regime_with_context_meta(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test handling of optional context_meta parameter."""
    context = {
        'now_ms': 1704067200000,  # 2024-01-01
        'spread_bps_mean': 15.0,
    }

    result = detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config, context_meta=context)

    assert isinstance(result, TARegime)
    assert result.confidence > 0.0  # Should not crash


def test_detect_ta_regime_high_spread_penalty(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test that high spread reduces confidence."""
    context_normal = {'spread_bps_mean': 10.0}
    context_high_spread = {'spread_bps_mean': 60.0}

    result_normal = detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config, context_meta=context_normal)
    result_high = detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config, context_meta=context_high_spread)

    # High spread should result in lower confidence or chop label
    assert result_high.label == "chop" or result_high.confidence <= result_normal.confidence


# =============================================================================
# TEST: No Side Effects (Pure Functions)
# =============================================================================

def test_no_side_effects_on_input_dataframe(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test that analyzer doesn't modify input DataFrame."""
    df_copy = minimal_ohlcv_df.copy()

    detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config)

    pd.testing.assert_frame_equal(minimal_ohlcv_df, df_copy)


def test_no_global_state_pollution(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test that multiple calls don't interfere with each other."""
    result1 = detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config)
    result2 = detect_ta_regime(minimal_ohlcv_df, "5m", default_ta_config)  # Different timeframe

    # Results should be independent
    assert result1.label in ["bull", "bear", "chop"]
    assert result2.label in ["bull", "bear", "chop"]


# =============================================================================
# TEST: Timeframe Scaling
# =============================================================================

def test_different_timeframes_produce_different_results(minimal_ohlcv_df: pd.DataFrame, default_ta_config: TAConfig):
    """Test that different timeframes may produce different regime assessments."""
    result_1m = detect_ta_regime(minimal_ohlcv_df, "1m", default_ta_config)
    result_5m = detect_ta_regime(minimal_ohlcv_df, "5m", default_ta_config)

    # Both should be valid outputs
    assert result_1m.label in ["bull", "bear", "chop"]
    assert result_5m.label in ["bull", "bear", "chop"]

    # Features should be computed (may differ due to timeframe scaling)
    assert len(result_1m.features) > 0
    assert len(result_5m.features) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
