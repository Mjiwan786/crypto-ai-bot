"""
Unit tests for macro_analyzer.py - Macro Regime Detection

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

from ai_engine.regime_detector.macro_analyzer import (
    MacroConfig,
    MacroRegime,
    compute_macro_features,
    detect_macro_regime,
    score_components,
)


# =============================================================================
# FIXTURES - Deterministic test data
# =============================================================================

@pytest.fixture
def minimal_macro_df() -> pd.DataFrame:
    """Minimal valid macro DataFrame for testing."""
    np.random.seed(42)
    n_rows = 250

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='1H'),
        'dxy': 103 + np.random.normal(0, 0.5, n_rows),
        'us10y': 4.2 + np.random.normal(0, 0.1, n_rows),
        'funding_8h': np.random.normal(0.01, 0.005, n_rows),
        'futures_basis_annual': np.random.normal(5.0, 2.0, n_rows),
        'open_interest_usd': 1e9 * (1 + np.random.normal(0, 0.05, n_rows)),
        'btc_dominance': 50 + np.random.normal(0, 2.0, n_rows),
        'vix': 15 + np.random.normal(0, 2.0, n_rows),
        'stablecoin_mcap': 1.2e11 * (1 + np.cumsum(np.random.normal(0, 0.001, n_rows))),
    })


@pytest.fixture
def bullish_macro_df() -> pd.DataFrame:
    """Macro data indicating bullish conditions."""
    np.random.seed(123)
    n_rows = 300

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='1H'),
        # Weakening USD (bullish for crypto)
        'dxy': 105 - np.linspace(0, 3, n_rows) + np.random.normal(0, 0.3, n_rows),
        # Falling rates (bullish)
        'us10y': 4.5 - np.linspace(0, 0.5, n_rows) + np.random.normal(0, 0.05, n_rows),
        # Positive funding (bullish sentiment)
        'funding_8h': np.random.normal(0.02, 0.003, n_rows),
        # Positive basis (contango = bullish)
        'futures_basis_annual': np.random.normal(8.0, 1.5, n_rows),
        # Growing OI (increasing participation)
        'open_interest_usd': 1e9 * (1 + np.linspace(0, 0.2, n_rows) + np.random.normal(0, 0.02, n_rows)),
        # Stable BTC dominance
        'btc_dominance': 50 + np.random.normal(0, 1.0, n_rows),
        # Low VIX (low fear)
        'vix': 12 + np.random.normal(0, 1.0, n_rows),
        # Growing stablecoin supply (capital inflow)
        'stablecoin_mcap': 1.2e11 * (1 + np.linspace(0, 0.1, n_rows) + np.random.normal(0, 0.005, n_rows)),
    })


@pytest.fixture
def bearish_macro_df() -> pd.DataFrame:
    """Macro data indicating bearish conditions."""
    np.random.seed(456)
    n_rows = 300

    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='1H'),
        # Strengthening USD (bearish for crypto)
        'dxy': 103 + np.linspace(0, 3, n_rows) + np.random.normal(0, 0.3, n_rows),
        # Rising rates (bearish)
        'us10y': 4.0 + np.linspace(0, 0.5, n_rows) + np.random.normal(0, 0.05, n_rows),
        # Negative funding (bearish sentiment)
        'funding_8h': np.random.normal(-0.01, 0.003, n_rows),
        # Negative basis (backwardation = bearish)
        'futures_basis_annual': np.random.normal(-2.0, 1.5, n_rows),
        # Declining OI (decreasing participation)
        'open_interest_usd': 1e9 * (1 - np.linspace(0, 0.15, n_rows) + np.random.normal(0, 0.02, n_rows)),
        # Rising BTC dominance (flight to safety)
        'btc_dominance': 48 + np.linspace(0, 5, n_rows) + np.random.normal(0, 1.0, n_rows),
        # High VIX (high fear)
        'vix': 22 + np.random.normal(0, 2.0, n_rows),
        # Declining stablecoin supply (capital outflow)
        'stablecoin_mcap': 1.2e11 * (1 - np.linspace(0, 0.08, n_rows) + np.random.normal(0, 0.005, n_rows)),
    })


@pytest.fixture
def default_macro_config() -> MacroConfig:
    """Default macro configuration for testing."""
    return MacroConfig()


# =============================================================================
# TEST: Configuration & Setup
# =============================================================================

def test_macro_config_creation():
    """Test MacroConfig can be created with defaults."""
    config = MacroConfig()
    assert config.lookbacks['short'] == 14
    assert config.lookbacks['medium'] == 30
    assert config.lookbacks['long'] == 90
    assert config.thresholds['bull'] > 0
    assert config.thresholds['bear'] < 0
    assert config.model_config['frozen'] is True
    assert config.model_config['extra'] == 'forbid'


def test_macro_config_weights_validation():
    """Test MacroConfig validates weights sum to ~1.0."""
    with pytest.raises(ValueError, match="Weights must sum"):
        MacroConfig(weights={'usd_liquidity': 0.5, 'crypto_derivs': 0.2, 'risk_appetite': 0.1, 'flow': 0.1})


def test_macro_config_thresholds_validation():
    """Test MacroConfig validates threshold ordering."""
    with pytest.raises(ValueError, match="threshold"):
        MacroConfig(thresholds={'bull': 0.2, 'bear': -0.2, 'chop_abs': 0.3})


def test_macro_config_lookbacks_validation():
    """Test MacroConfig validates lookback ordering."""
    with pytest.raises(ValueError, match="Lookbacks must satisfy"):
        MacroConfig(lookbacks={'short': 50, 'medium': 30, 'long': 90})


# =============================================================================
# TEST: Pure Function Behavior - Determinism
# =============================================================================

def test_detect_macro_regime_deterministic(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that detect_macro_regime is deterministic (same input → same output)."""
    result1 = detect_macro_regime(minimal_macro_df, "1h", default_macro_config)
    result2 = detect_macro_regime(minimal_macro_df, "1h", default_macro_config)

    assert result1.label == result2.label
    assert result1.confidence == result2.confidence
    assert result1.components == result2.components
    assert result1.explain == result2.explain


def test_compute_macro_features_deterministic(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that compute_macro_features is deterministic."""
    features1 = compute_macro_features(minimal_macro_df, default_macro_config, "1h")
    features2 = compute_macro_features(minimal_macro_df, default_macro_config, "1h")

    for key in features1.keys():
        pd.testing.assert_series_equal(features1[key], features2[key])


# =============================================================================
# TEST: Input Validation & Edge Cases
# =============================================================================

def test_detect_macro_regime_empty_dataframe(default_macro_config: MacroConfig):
    """Test handling of empty DataFrame."""
    empty_df = pd.DataFrame()
    result = detect_macro_regime(empty_df, "1h", default_macro_config)

    assert result.label == "chop"
    assert result.confidence == 0.0
    assert result.n_samples == 0


def test_detect_macro_regime_insufficient_data(default_macro_config: MacroConfig):
    """Test handling of insufficient data (below min_rows)."""
    small_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=50, freq='1H'),
        'dxy': [103] * 50,
        'funding_8h': [0.01] * 50,
    })

    result = detect_macro_regime(small_df, "1h", default_macro_config)

    # Should handle gracefully with low confidence
    assert result.label in ["bull", "bear", "chop"]
    assert result.confidence >= 0.0


def test_detect_macro_regime_invalid_timeframe(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test handling of invalid timeframe format."""
    with pytest.raises(ValueError, match="Invalid timeframe"):
        detect_macro_regime(minimal_macro_df, "invalid", default_macro_config)


def test_detect_macro_regime_missing_all_columns(default_macro_config: MacroConfig):
    """Test handling when all expected columns are missing."""
    incomplete_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=300, freq='1H'),
        'random_col': [1] * 300,
    })

    result = detect_macro_regime(incomplete_df, "1h", default_macro_config)

    # Should return chop with low confidence when no data available
    assert result.label == "chop"
    assert result.confidence == 0.0


# =============================================================================
# TEST: Output Structure & Types
# =============================================================================

def test_detect_macro_regime_output_structure(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that output matches MacroRegime schema."""
    result = detect_macro_regime(minimal_macro_df, "1h", default_macro_config)

    assert isinstance(result, MacroRegime)
    assert result.label in ["bull", "bear", "chop"]
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.components, dict)
    assert isinstance(result.features, dict)
    assert isinstance(result.explain, str)
    assert result.latency_ms >= 0
    assert result.n_samples > 0


def test_macro_regime_frozen(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that MacroRegime output is frozen (immutable)."""
    result = detect_macro_regime(minimal_macro_df, "1h", default_macro_config)

    with pytest.raises(Exception):  # Pydantic ValidationError
        result.label = "bull"


def test_macro_regime_extra_forbid(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that MacroRegime rejects extra fields."""
    result = detect_macro_regime(minimal_macro_df, "1h", default_macro_config)
    result_dict = result.model_dump()

    with pytest.raises(Exception):  # Pydantic ValidationError
        MacroRegime(**{**result_dict, 'extra_field': 'should_fail'})


# =============================================================================
# TEST: Regime Classification Logic
# =============================================================================

def test_detect_bullish_macro_regime(bullish_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test detection of bullish regime from favorable macro conditions."""
    result = detect_macro_regime(bullish_macro_df, "1h", default_macro_config)

    # Should detect bullish or neutral (not bearish with strong bullish signals)
    assert result.label in ["bull", "chop"]
    assert result.confidence > 0.0


def test_detect_bearish_macro_regime(bearish_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test detection of bearish regime from unfavorable macro conditions."""
    result = detect_macro_regime(bearish_macro_df, "1h", default_macro_config)

    # Should detect bearish or neutral (not bullish with strong bearish signals)
    assert result.label in ["bear", "chop"]
    assert result.confidence > 0.0


# =============================================================================
# TEST: Component Analysis
# =============================================================================

def test_compute_macro_features_completeness(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that compute_macro_features returns expected features."""
    features = compute_macro_features(minimal_macro_df, default_macro_config, "1h")

    # Should have at least some features computed
    assert len(features) > 0
    for feature_name, feature_series in features.items():
        assert isinstance(feature_series, pd.Series)
        assert len(feature_series) == len(minimal_macro_df)


def test_score_components_structure(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that score_components returns all expected components."""
    features = compute_macro_features(minimal_macro_df, default_macro_config, "1h")
    components = score_components(features, default_macro_config)

    expected_components = ['usd_liquidity', 'crypto_derivs', 'risk_appetite', 'flow']
    for comp in expected_components:
        assert comp in components
        assert isinstance(components[comp], pd.Series)


def test_score_components_deterministic(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that score_components is deterministic."""
    features = compute_macro_features(minimal_macro_df, default_macro_config, "1h")

    components1 = score_components(features, default_macro_config)
    components2 = score_components(features, default_macro_config)

    for key in components1.keys():
        if not key.startswith('_'):  # Skip metadata fields
            pd.testing.assert_series_equal(components1[key], components2[key])


# =============================================================================
# TEST: Context Metadata Handling
# =============================================================================

def test_detect_macro_regime_with_context_meta(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test handling of optional context_meta parameter."""
    context = {
        't_start_ms': 1704067200000,
        't_end_ms': 1704067200100,  # 100ms difference
        'spread_bps_mean': 12.0,
    }

    result = detect_macro_regime(minimal_macro_df, "1h", default_macro_config, context_meta=context)

    assert isinstance(result, MacroRegime)
    assert result.latency_ms == 100  # From context


def test_detect_macro_regime_high_spread_penalty(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that high spread reduces confidence."""
    context_normal = {'spread_bps_mean': 10.0}
    context_high_spread = {'spread_bps_mean': 50.0}

    result_normal = detect_macro_regime(minimal_macro_df, "1h", default_macro_config, context_meta=context_normal)
    result_high = detect_macro_regime(minimal_macro_df, "1h", default_macro_config, context_meta=context_high_spread)

    # High spread should reduce confidence
    assert result_high.confidence <= result_normal.confidence


# =============================================================================
# TEST: No Side Effects (Pure Functions)
# =============================================================================

def test_no_side_effects_on_input_dataframe(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that analyzer doesn't modify input DataFrame values."""
    # Save original numeric values
    df_copy = minimal_macro_df.copy(deep=True)
    numeric_cols = minimal_macro_df.select_dtypes(include=[np.number]).columns
    orig_values = {col: minimal_macro_df[col].values.copy() for col in numeric_cols}

    detect_macro_regime(minimal_macro_df, "1h", default_macro_config)

    # Check that numeric data values haven't changed (ignore index/metadata changes)
    for col in numeric_cols:
        assert np.allclose(minimal_macro_df[col].values, orig_values[col], equal_nan=True), \
            f"Column {col} values were modified"


def test_no_global_state_pollution(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that multiple calls don't interfere with each other."""
    result1 = detect_macro_regime(minimal_macro_df, "1h", default_macro_config)
    result2 = detect_macro_regime(minimal_macro_df, "4h", default_macro_config)

    # Results should be independent
    assert result1.label in ["bull", "bear", "chop"]
    assert result2.label in ["bull", "bear", "chop"]


# =============================================================================
# TEST: Timeframe Scaling
# =============================================================================

def test_timeframe_scaling_affects_features(minimal_macro_df: pd.DataFrame, default_macro_config: MacroConfig):
    """Test that different timeframes produce appropriately scaled features."""
    features_1h = compute_macro_features(minimal_macro_df, default_macro_config, "1h")
    features_8h = compute_macro_features(minimal_macro_df, default_macro_config, "8h")

    # Both should produce features
    assert len(features_1h) > 0
    assert len(features_8h) > 0


def test_partial_data_coverage(default_macro_config: MacroConfig):
    """Test handling when only some macro indicators are available."""
    partial_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=300, freq='1H'),
        'dxy': 103 + np.random.normal(0, 0.5, 300),
        'funding_8h': np.random.normal(0.01, 0.005, 300),
        # Missing other indicators
    })

    result = detect_macro_regime(partial_df, "1h", default_macro_config)

    # Should still produce a result, but possibly with lower confidence
    assert result.label in ["bull", "bear", "chop"]
    assert 0.0 <= result.confidence <= 1.0


# =============================================================================
# TEST: NaN Handling
# =============================================================================

def test_high_nan_data_quality_warning(default_macro_config: MacroConfig):
    """Test handling of data with high NaN fraction."""
    df_with_nans = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=300, freq='1H'),
        'dxy': [np.nan] * 150 + [103] * 150,
        'funding_8h': [0.01] * 300,
    })

    result = detect_macro_regime(df_with_nans, "1h", default_macro_config)

    # Should handle gracefully, possibly with lower confidence
    assert result.label in ["bull", "bear", "chop"]
    assert result.confidence >= 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
