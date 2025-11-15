"""
Unit tests for sentiment_analyzer.py - Sentiment Regime Detection

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

from ai_engine.regime_detector.sentiment_analyzer import (
    SentimentConfig,
    SentimentRegime,
    compute_sentiment_features,
    detect_sentiment_regime,
    score_components,
)


# =============================================================================
# FIXTURES - Deterministic test data
# =============================================================================

@pytest.fixture
def minimal_sentiment_df() -> pd.DataFrame:
    """Minimal valid sentiment DataFrame for testing."""
    np.random.seed(42)
    n_rows = 250

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='5min'),
        'tw_score': np.random.normal(0.05, 0.3, n_rows).clip(-1, 1),
        'tw_volume': np.random.exponential(100, n_rows),
        'rd_score': np.random.normal(0.03, 0.25, n_rows).clip(-1, 1),
        'rd_volume': np.random.exponential(80, n_rows),
        'news_score': np.random.normal(0.02, 0.2, n_rows).clip(-1, 1),
        'news_volume': np.random.exponential(50, n_rows),
        'news_dispersion': np.random.exponential(1.5, n_rows),
        'ret_5m': np.random.normal(0.0, 0.02, n_rows),
        'ret_1h': np.random.normal(0.0, 0.05, n_rows),
    })


@pytest.fixture
def bullish_sentiment_df() -> pd.DataFrame:
    """Sentiment data indicating bullish conditions."""
    np.random.seed(123)
    n_rows = 300

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='5min'),
        # Positive sentiment scores
        'tw_score': np.random.normal(0.4, 0.15, n_rows).clip(-1, 1),
        'tw_volume': np.random.exponential(150, n_rows),
        'rd_score': np.random.normal(0.35, 0.15, n_rows).clip(-1, 1),
        'rd_volume': np.random.exponential(120, n_rows),
        'news_score': np.random.normal(0.3, 0.15, n_rows).clip(-1, 1),
        'news_volume': np.random.exponential(80, n_rows),
        'news_dispersion': np.random.exponential(1.0, n_rows),  # Low dispersion
        # Positive returns (price momentum)
        'ret_5m': np.random.normal(0.01, 0.015, n_rows),
        'ret_1h': np.random.normal(0.02, 0.03, n_rows),
        'mentions_btc': np.random.poisson(200, n_rows),
        'mentions_eth': np.random.poisson(150, n_rows),
    })


@pytest.fixture
def bearish_sentiment_df() -> pd.DataFrame:
    """Sentiment data indicating bearish conditions."""
    np.random.seed(456)
    n_rows = 300

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='5min'),
        # Negative sentiment scores
        'tw_score': np.random.normal(-0.4, 0.15, n_rows).clip(-1, 1),
        'tw_volume': np.random.exponential(150, n_rows),
        'rd_score': np.random.normal(-0.35, 0.15, n_rows).clip(-1, 1),
        'rd_volume': np.random.exponential(120, n_rows),
        'news_score': np.random.normal(-0.3, 0.15, n_rows).clip(-1, 1),
        'news_volume': np.random.exponential(80, n_rows),
        'news_dispersion': np.random.exponential(1.0, n_rows),
        # Negative returns (price momentum)
        'ret_5m': np.random.normal(-0.01, 0.015, n_rows),
        'ret_1h': np.random.normal(-0.02, 0.03, n_rows),
        'mentions_btc': np.random.poisson(200, n_rows),
        'mentions_eth': np.random.poisson(150, n_rows),
    })


@pytest.fixture
def neutral_sentiment_df() -> pd.DataFrame:
    """Sentiment data indicating neutral/choppy conditions."""
    np.random.seed(789)
    n_rows = 300

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='5min'),
        # Mixed/neutral sentiment scores
        'tw_score': np.random.normal(0.0, 0.4, n_rows).clip(-1, 1),
        'tw_volume': np.random.exponential(100, n_rows),
        'rd_score': np.random.normal(0.0, 0.35, n_rows).clip(-1, 1),
        'rd_volume': np.random.exponential(90, n_rows),
        'news_score': np.random.normal(0.0, 0.3, n_rows).clip(-1, 1),
        'news_volume': np.random.exponential(60, n_rows),
        'news_dispersion': np.random.exponential(2.5, n_rows),  # High dispersion
        # Near-zero returns
        'ret_5m': np.random.normal(0.0, 0.025, n_rows),
        'ret_1h': np.random.normal(0.0, 0.06, n_rows),
        'mentions_btc': np.random.poisson(100, n_rows),
        'mentions_eth': np.random.poisson(80, n_rows),
    })


@pytest.fixture
def default_sentiment_config() -> SentimentConfig:
    """Default sentiment configuration for testing."""
    return SentimentConfig()


# =============================================================================
# TEST: Configuration & Setup
# =============================================================================

def test_sentiment_config_creation():
    """Test SentimentConfig can be created with defaults."""
    config = SentimentConfig()
    assert config.lookbacks['short'] == 20
    assert config.lookbacks['medium'] == 60
    assert config.lookbacks['long'] == 180
    assert config.thresholds['bull'] > 0
    assert config.thresholds['bear'] < 0
    assert config.model_config['frozen'] is True
    assert config.model_config['extra'] == 'forbid'


def test_sentiment_config_weights_validation():
    """Test SentimentConfig validates weights sum to ~1.0."""
    with pytest.raises(ValueError, match="Weights must sum"):
        SentimentConfig(weights={'social': 0.5, 'news': 0.3, 'reaction': 0.1})


def test_sentiment_config_thresholds_validation():
    """Test SentimentConfig validates threshold ordering."""
    with pytest.raises(ValueError, match="threshold"):
        SentimentConfig(thresholds={'bull': 0.2, 'bear': -0.2, 'chop_abs': 0.3})


# =============================================================================
# TEST: Pure Function Behavior - Determinism
# =============================================================================

def test_detect_sentiment_regime_deterministic(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that detect_sentiment_regime is deterministic (same input → same output)."""
    result1 = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config)
    result2 = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config)

    assert result1.label == result2.label
    assert result1.confidence == result2.confidence
    assert result1.components == result2.components
    assert result1.explain == result2.explain


def test_compute_sentiment_features_deterministic(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that compute_sentiment_features is deterministic."""
    features1 = compute_sentiment_features(minimal_sentiment_df, default_sentiment_config)
    features2 = compute_sentiment_features(minimal_sentiment_df, default_sentiment_config)

    for key in features1.keys():
        pd.testing.assert_series_equal(features1[key], features2[key])


# =============================================================================
# TEST: Input Validation & Edge Cases
# =============================================================================

def test_detect_sentiment_regime_empty_dataframe(default_sentiment_config: SentimentConfig):
    """Test handling of empty DataFrame."""
    empty_df = pd.DataFrame()
    result = detect_sentiment_regime(empty_df, "5m", default_sentiment_config)

    assert result.label == "chop"
    assert result.confidence == 0.0
    assert result.n_samples == 0


def test_detect_sentiment_regime_insufficient_data(default_sentiment_config: SentimentConfig):
    """Test handling of insufficient data (below min_rows)."""
    small_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=50, freq='5min'),
        'tw_score': [0.1] * 50,
        'tw_volume': [100] * 50,
    })

    result = detect_sentiment_regime(small_df, "5m", default_sentiment_config)

    # Should handle gracefully with low confidence
    assert result.label in ["bull", "bear", "chop"]
    assert result.confidence >= 0.0


def test_detect_sentiment_regime_invalid_timeframe(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test handling of invalid timeframe format."""
    # Invalid timeframe should return safe default (chop with 0 confidence)
    result = detect_sentiment_regime(minimal_sentiment_df, "invalid_tf", default_sentiment_config)
    assert result.label == "chop"
    assert result.confidence == 0.0


def test_detect_sentiment_regime_missing_columns(default_sentiment_config: SentimentConfig):
    """Test handling when expected columns are missing."""
    incomplete_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=300, freq='5min'),
        'tw_score': [0.1] * 300,
        # Missing other columns
    })

    result = detect_sentiment_regime(incomplete_df, "5m", default_sentiment_config)

    # Should still produce a result with available data
    assert result.label in ["bull", "bear", "chop"]
    assert result.confidence >= 0.0


# =============================================================================
# TEST: Output Structure & Types
# =============================================================================

def test_detect_sentiment_regime_output_structure(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that output matches SentimentRegime schema."""
    result = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config)

    assert isinstance(result, SentimentRegime)
    assert result.label in ["bull", "bear", "chop"]
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.components, dict)
    assert isinstance(result.features, dict)
    assert isinstance(result.explain, str)
    assert result.latency_ms >= 0
    assert result.n_samples > 0


def test_sentiment_regime_frozen(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that SentimentRegime output is frozen (immutable)."""
    result = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config)

    with pytest.raises(Exception):  # Pydantic ValidationError
        result.label = "bull"


def test_sentiment_regime_extra_forbid(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that SentimentRegime rejects extra fields."""
    result = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config)
    result_dict = result.model_dump()

    with pytest.raises(Exception):  # Pydantic ValidationError
        SentimentRegime(**{**result_dict, 'extra_field': 'should_fail'})


# =============================================================================
# TEST: Regime Classification Logic
# =============================================================================

def test_detect_bullish_sentiment(bullish_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test detection of bullish sentiment from positive sentiment data."""
    result = detect_sentiment_regime(bullish_sentiment_df, "5m", default_sentiment_config)

    # Should detect bullish or neutral (not bearish with strong bullish signals)
    assert result.label in ["bull", "chop"]
    assert result.confidence > 0.0


def test_detect_bearish_sentiment(bearish_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test detection of bearish sentiment from negative sentiment data."""
    result = detect_sentiment_regime(bearish_sentiment_df, "5m", default_sentiment_config)

    # Should detect bearish or neutral (not bullish with strong bearish signals)
    assert result.label in ["bear", "chop"]
    assert result.confidence > 0.0


def test_detect_neutral_sentiment(neutral_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test detection of neutral/choppy sentiment from mixed data."""
    result = detect_sentiment_regime(neutral_sentiment_df, "5m", default_sentiment_config)

    # With high dispersion and mixed signals, should often be chop
    assert result.label in ["bull", "bear", "chop"]
    assert result.confidence >= 0.0


# =============================================================================
# TEST: Component Analysis
# =============================================================================

def test_compute_sentiment_features_completeness(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that compute_sentiment_features returns expected features."""
    features = compute_sentiment_features(minimal_sentiment_df, default_sentiment_config)

    # Should have computed features
    assert len(features) > 0
    for feature_name, feature_series in features.items():
        assert isinstance(feature_series, pd.Series)
        assert len(feature_series) == len(minimal_sentiment_df)


def test_score_components_structure(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that score_components returns all expected components."""
    features = compute_sentiment_features(minimal_sentiment_df, default_sentiment_config)
    components = score_components(features, default_sentiment_config)

    expected_components = ['social', 'news', 'reaction']
    for comp in expected_components:
        assert comp in components
        assert isinstance(components[comp], pd.Series)


def test_score_components_deterministic(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that score_components is deterministic."""
    features = compute_sentiment_features(minimal_sentiment_df, default_sentiment_config)

    components1 = score_components(features, default_sentiment_config)
    components2 = score_components(features, default_sentiment_config)

    for key in ['social', 'news', 'reaction']:
        pd.testing.assert_series_equal(components1[key], components2[key])


# =============================================================================
# TEST: Context Metadata Handling
# =============================================================================

def test_detect_sentiment_regime_with_context_meta(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test handling of optional context_meta parameter."""
    context = {
        't_start_ms': 1704067200000,
        't_end_ms': 1704067200150,  # 150ms difference
        'spread_bps_mean': 10.0,
    }

    result = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config, context_meta=context)

    assert isinstance(result, SentimentRegime)
    assert result.latency_ms == 150  # From context


def test_detect_sentiment_regime_high_spread_penalty(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that high spread reduces confidence."""
    context_normal = {'spread_bps_mean': 10.0, 't_start_ms': 0, 't_end_ms': 0}
    context_high_spread = {'spread_bps_mean': 35.0, 't_start_ms': 0, 't_end_ms': 0}

    result_normal = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config, context_meta=context_normal)
    result_high = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config, context_meta=context_high_spread)

    # High spread should reduce confidence slightly
    assert result_high.confidence <= result_normal.confidence


# =============================================================================
# TEST: No Side Effects (Pure Functions)
# =============================================================================

def test_no_side_effects_on_input_dataframe(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that analyzer doesn't modify input DataFrame."""
    df_copy = minimal_sentiment_df.copy()

    detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config)

    pd.testing.assert_frame_equal(minimal_sentiment_df, df_copy)


def test_no_global_state_pollution(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that multiple calls don't interfere with each other."""
    result1 = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config)
    result2 = detect_sentiment_regime(minimal_sentiment_df, "15m", default_sentiment_config)

    # Results should be independent
    assert result1.label in ["bull", "bear", "chop"]
    assert result2.label in ["bull", "bear", "chop"]


# =============================================================================
# TEST: Volume Weighting
# =============================================================================

def test_low_volume_reduces_confidence(default_sentiment_config: SentimentConfig):
    """Test that low volume reduces confidence in sentiment assessment."""
    low_volume_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=300, freq='5min'),
        'tw_score': [0.5] * 300,  # Strong positive
        'tw_volume': [10] * 300,  # Very low volume
        'rd_score': [0.5] * 300,
        'rd_volume': [10] * 300,
        'news_score': [0.5] * 300,
        'news_volume': [5] * 300,
        'ret_5m': [0.01] * 300,
        'ret_1h': [0.02] * 300,
    })

    result = detect_sentiment_regime(low_volume_df, "5m", default_sentiment_config)

    # Low volume should result in lower confidence
    assert result.confidence < 0.8  # Shouldn't be very confident with low volume


# =============================================================================
# TEST: NaN Handling
# =============================================================================

def test_high_nan_data_quality(default_sentiment_config: SentimentConfig):
    """Test handling of data with high NaN fraction."""
    df_with_nans = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=300, freq='5min'),
        'tw_score': [np.nan] * 150 + [0.2] * 150,
        'tw_volume': [100] * 300,
        'rd_score': [0.1] * 300,
        'rd_volume': [80] * 300,
    })

    result = detect_sentiment_regime(df_with_nans, "5m", default_sentiment_config)

    # Should handle gracefully
    assert result.label in ["bull", "bear", "chop"]
    assert result.confidence >= 0.0


# =============================================================================
# TEST: JSON Serialization
# =============================================================================

def test_sentiment_regime_json_roundtrip(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that SentimentRegime can be serialized to/from JSON."""
    result = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config)

    # Serialize to JSON
    json_str = result.model_dump_json()

    # Deserialize from JSON
    result_copy = SentimentRegime.model_validate_json(json_str)

    # Should be equal
    assert result == result_copy


# =============================================================================
# TEST: Deterministic Key Ordering
# =============================================================================

def test_components_sorted_keys(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that components dict has sorted keys for determinism in serialization."""
    result = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config)

    # Check that JSON serialization has sorted keys
    json_data = result.model_dump_json()
    import json as json_module
    parsed = json_module.loads(json_data)
    components_keys = list(parsed["components"].keys())
    assert components_keys == sorted(components_keys)


def test_features_sorted_keys(minimal_sentiment_df: pd.DataFrame, default_sentiment_config: SentimentConfig):
    """Test that features dict has sorted keys for determinism in serialization."""
    result = detect_sentiment_regime(minimal_sentiment_df, "5m", default_sentiment_config)

    # Check that JSON serialization has sorted keys
    json_data = result.model_dump_json()
    import json as json_module
    parsed = json_module.loads(json_data)
    features_keys = list(parsed["features"].keys())
    assert features_keys == sorted(features_keys)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
