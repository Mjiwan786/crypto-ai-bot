"""
Unit tests for bar_reaction_5m configuration validation.

Tests cover:
1. Missing required fields → raises ValueError
2. Bad bounds (out of range) → raises ValueError
3. Happy path (valid config) → loads successfully

Test categories:
- Missing fields (timeframe, trigger_bps, ATR params, etc.)
- Invalid bounds (negative values, reversed ranges)
- Invalid types (wrong mode, trigger_mode)
- Edge cases (boundary conditions)
- Symbol normalization
- Happy path (complete valid config)

Environment:
- Conda env: crypto-bot
- Python: 3.10.18
- Redis: TLS cloud connection (not used in these tests)
"""

import pytest
import tempfile
import yaml
from pathlib import Path
from typing import Dict, Any

from config.enhanced_scalper_loader import EnhancedScalperConfigLoader


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def valid_bar_reaction_config() -> Dict[str, Any]:
    """Valid bar_reaction_5m configuration for happy path tests."""
    return {
        'bar_reaction_5m': {
            'enabled': True,
            'mode': 'trend',
            'pairs': ['BTC/USD', 'ETH/USD', 'SOL/USD'],
            'timeframe': '5m',
            'trigger_mode': 'open_to_close',
            'trigger_bps_up': 12,
            'trigger_bps_down': 12,
            'atr_window': 14,
            'min_atr_pct': 0.25,
            'max_atr_pct': 3.0,
            'risk_per_trade_pct': 0.6,
            'sl_atr': 0.6,
            'tp1_atr': 1.0,
            'tp2_atr': 1.8,
            'trail_atr': 0.8,
            'break_even_at_r': 0.8,
            'maker_only': True,
            'spread_bps_cap': 8,
            'min_rolling_notional_usd': 200000,
            'cooldown_bars': 1,
            'max_concurrent_per_pair': 1,
            'enable_mean_revert_extremes': True,
            'extreme_bps_threshold': 35,
            'mean_revert_size_factor': 0.5,
        }
    }


@pytest.fixture
def temp_config_file(valid_bar_reaction_config):
    """Create a temporary config file with valid configuration."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(valid_bar_reaction_config, f)
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


def create_invalid_config(base_config: Dict[str, Any], **overrides) -> str:
    """
    Create a temporary config file with invalid settings.

    Args:
        base_config: Base configuration dictionary
        **overrides: Fields to override in bar_reaction_5m section

    Returns:
        Path to temporary config file
    """
    config = base_config.copy()
    if 'bar_reaction_5m' in config:
        config['bar_reaction_5m'] = {**config['bar_reaction_5m'], **overrides}
    else:
        config['bar_reaction_5m'] = overrides

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config, f)
        return f.name


# =============================================================================
# MISSING FIELDS TESTS
# =============================================================================

class TestMissingFields:
    """Test that missing required fields raise appropriate errors."""

    def test_missing_timeframe(self, valid_bar_reaction_config):
        """Missing timeframe should pass validation (has default behavior)."""
        # Note: timeframe is checked if present, but not required to exist
        config = valid_bar_reaction_config.copy()
        del config['bar_reaction_5m']['timeframe']

        temp_path = create_invalid_config(config)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            # This should not raise since we check .get('timeframe')
            # which returns None, and we compare to '5m'
            with pytest.raises(ValueError, match="timeframe must be '5m'"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_missing_trigger_bps_up(self, valid_bar_reaction_config):
        """Missing trigger_bps_up should fail validation."""
        config = valid_bar_reaction_config.copy()
        del config['bar_reaction_5m']['trigger_bps_up']

        temp_path = create_invalid_config(config)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="trigger_bps_up must be > 0"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_missing_trigger_bps_down(self, valid_bar_reaction_config):
        """Missing trigger_bps_down should fail validation."""
        config = valid_bar_reaction_config.copy()
        del config['bar_reaction_5m']['trigger_bps_down']

        temp_path = create_invalid_config(config)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="trigger_bps_down must be > 0"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_missing_atr_window(self, valid_bar_reaction_config):
        """Missing atr_window should fail validation."""
        config = valid_bar_reaction_config.copy()
        del config['bar_reaction_5m']['atr_window']

        temp_path = create_invalid_config(config)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="atr_window must be >= 5"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_missing_min_atr_pct(self, valid_bar_reaction_config):
        """Missing min_atr_pct defaults to 0, which is valid (passes validation)."""
        config = valid_bar_reaction_config.copy()
        del config['bar_reaction_5m']['min_atr_pct']

        temp_path = create_invalid_config(config)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            # Missing min_atr_pct defaults to 0 via .get(), which is valid (>= 0)
            # So this should pass, not raise
            loaded_config = loader.load_config()
            # The value defaults to 0 from .get('min_atr_pct', 0)
            assert loaded_config['bar_reaction_5m'].get('min_atr_pct', 0) == 0
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_missing_mode(self, valid_bar_reaction_config):
        """Missing mode should fail validation."""
        config = valid_bar_reaction_config.copy()
        del config['bar_reaction_5m']['mode']

        temp_path = create_invalid_config(config)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="mode must be one of"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)


# =============================================================================
# BAD BOUNDS TESTS
# =============================================================================

class TestBadBounds:
    """Test that out-of-range values raise appropriate errors."""

    def test_invalid_timeframe_1m(self, valid_bar_reaction_config):
        """Timeframe '1m' should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, timeframe='1m')
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="timeframe must be '5m'"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_invalid_timeframe_15m(self, valid_bar_reaction_config):
        """Timeframe '15m' should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, timeframe='15m')
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="timeframe must be '5m'"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_trigger_bps_up_zero(self, valid_bar_reaction_config):
        """trigger_bps_up = 0 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, trigger_bps_up=0)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="trigger_bps_up must be > 0"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_trigger_bps_up_negative(self, valid_bar_reaction_config):
        """trigger_bps_up < 0 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, trigger_bps_up=-5)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="trigger_bps_up must be > 0"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_trigger_bps_down_zero(self, valid_bar_reaction_config):
        """trigger_bps_down = 0 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, trigger_bps_down=0)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="trigger_bps_down must be > 0"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_min_atr_pct_negative(self, valid_bar_reaction_config):
        """min_atr_pct < 0 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, min_atr_pct=-0.5)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="min_atr_pct must be >= 0"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_max_atr_pct_less_than_min(self, valid_bar_reaction_config):
        """max_atr_pct <= min_atr_pct should be rejected."""
        temp_path = create_invalid_config(
            valid_bar_reaction_config,
            min_atr_pct=3.0,
            max_atr_pct=2.0
        )
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="max_atr_pct.*must be > min_atr_pct"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_max_atr_pct_equal_to_min(self, valid_bar_reaction_config):
        """max_atr_pct == min_atr_pct should be rejected."""
        temp_path = create_invalid_config(
            valid_bar_reaction_config,
            min_atr_pct=3.0,
            max_atr_pct=3.0
        )
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="max_atr_pct.*must be > min_atr_pct"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_atr_window_too_small(self, valid_bar_reaction_config):
        """atr_window < 5 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, atr_window=3)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="atr_window must be >= 5"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_risk_per_trade_zero(self, valid_bar_reaction_config):
        """risk_per_trade_pct = 0 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, risk_per_trade_pct=0)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="risk_per_trade_pct must be in"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_risk_per_trade_too_high(self, valid_bar_reaction_config):
        """risk_per_trade_pct > 2.0 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, risk_per_trade_pct=3.0)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="risk_per_trade_pct must be in"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_sl_atr_zero(self, valid_bar_reaction_config):
        """sl_atr = 0 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, sl_atr=0)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="sl_atr must be > 0"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_tp1_atr_zero(self, valid_bar_reaction_config):
        """tp1_atr = 0 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, tp1_atr=0)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="tp1_atr must be > 0"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_tp2_atr_less_than_tp1(self, valid_bar_reaction_config):
        """tp2_atr <= tp1_atr should be rejected."""
        temp_path = create_invalid_config(
            valid_bar_reaction_config,
            tp1_atr=1.5,
            tp2_atr=1.0
        )
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="tp2_atr.*must be > tp1_atr"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_spread_bps_cap_zero(self, valid_bar_reaction_config):
        """spread_bps_cap = 0 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, spread_bps_cap=0)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="spread_bps_cap must be in"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_spread_bps_cap_too_high(self, valid_bar_reaction_config):
        """spread_bps_cap > 20 should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, spread_bps_cap=25)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="spread_bps_cap must be in"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_extreme_threshold_too_low(self, valid_bar_reaction_config):
        """extreme_bps_threshold <= trigger_bps_up should be rejected."""
        temp_path = create_invalid_config(
            valid_bar_reaction_config,
            trigger_bps_up=12,
            extreme_bps_threshold=10,
            enable_mean_revert_extremes=True
        )
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="extreme_bps_threshold.*must be > trigger_bps_up"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_mean_revert_size_factor_zero(self, valid_bar_reaction_config):
        """mean_revert_size_factor = 0 should be rejected."""
        temp_path = create_invalid_config(
            valid_bar_reaction_config,
            mean_revert_size_factor=0,
            enable_mean_revert_extremes=True
        )
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="mean_revert_size_factor must be in"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_mean_revert_size_factor_too_high(self, valid_bar_reaction_config):
        """mean_revert_size_factor > 1.0 should be rejected."""
        temp_path = create_invalid_config(
            valid_bar_reaction_config,
            mean_revert_size_factor=1.5,
            enable_mean_revert_extremes=True
        )
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="mean_revert_size_factor must be in"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)


# =============================================================================
# INVALID TYPES TESTS
# =============================================================================

class TestInvalidTypes:
    """Test that invalid enum values raise appropriate errors."""

    def test_invalid_mode(self, valid_bar_reaction_config):
        """Invalid mode should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, mode='scalp')
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="mode must be one of"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_invalid_trigger_mode(self, valid_bar_reaction_config):
        """Invalid trigger_mode should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, trigger_mode='invalid')
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="trigger_mode must be one of"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_maker_only_false(self, valid_bar_reaction_config):
        """maker_only = False should be rejected."""
        temp_path = create_invalid_config(valid_bar_reaction_config, maker_only=False)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            with pytest.raises(ValueError, match="maker_only must be true"):
                loader.load_config()
        finally:
            Path(temp_path).unlink(missing_ok=True)


# =============================================================================
# EDGE CASES TESTS
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_minimum_valid_trigger_bps(self, valid_bar_reaction_config):
        """Minimum valid trigger_bps_up (0.01) should pass."""
        temp_path = create_invalid_config(
            valid_bar_reaction_config,
            trigger_bps_up=0.01,
            trigger_bps_down=0.01
        )
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            config = loader.load_config()
            assert config['bar_reaction_5m']['trigger_bps_up'] == 0.01
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_minimum_valid_atr_window(self, valid_bar_reaction_config):
        """Minimum valid atr_window (5) should pass."""
        temp_path = create_invalid_config(valid_bar_reaction_config, atr_window=5)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            config = loader.load_config()
            assert config['bar_reaction_5m']['atr_window'] == 5
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_maximum_valid_spread_bps_cap(self, valid_bar_reaction_config):
        """Maximum valid spread_bps_cap (20) should pass."""
        temp_path = create_invalid_config(valid_bar_reaction_config, spread_bps_cap=20)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            config = loader.load_config()
            assert config['bar_reaction_5m']['spread_bps_cap'] == 20
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_min_atr_pct_zero(self, valid_bar_reaction_config):
        """min_atr_pct = 0 should pass (allows zero lower bound)."""
        temp_path = create_invalid_config(
            valid_bar_reaction_config,
            min_atr_pct=0.0,
            max_atr_pct=3.0
        )
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            config = loader.load_config()
            assert config['bar_reaction_5m']['min_atr_pct'] == 0.0
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_tp2_equal_to_tp1_plus_epsilon(self, valid_bar_reaction_config):
        """tp2_atr slightly greater than tp1_atr should pass."""
        temp_path = create_invalid_config(
            valid_bar_reaction_config,
            tp1_atr=1.0,
            tp2_atr=1.01
        )
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            config = loader.load_config()
            assert config['bar_reaction_5m']['tp2_atr'] == 1.01
        finally:
            Path(temp_path).unlink(missing_ok=True)


# =============================================================================
# SYMBOL NORMALIZATION TESTS
# =============================================================================

class TestSymbolNormalization:
    """Test symbol normalization functionality."""

    def test_normalize_btcusd(self):
        """BTCUSD should normalize to BTC/USD."""
        loader = EnhancedScalperConfigLoader()
        assert loader.normalize_symbol("BTCUSD") == "BTC/USD"

    def test_normalize_ethusdt(self):
        """ETHUSDT should normalize to ETH/USDT."""
        loader = EnhancedScalperConfigLoader()
        assert loader.normalize_symbol("ETHUSDT") == "ETH/USDT"

    def test_normalize_btc_dash_usd(self):
        """BTC-USD should normalize to BTC/USD."""
        loader = EnhancedScalperConfigLoader()
        assert loader.normalize_symbol("BTC-USD") == "BTC/USD"

    def test_normalize_already_normalized(self):
        """BTC/USD should remain BTC/USD."""
        loader = EnhancedScalperConfigLoader()
        assert loader.normalize_symbol("BTC/USD") == "BTC/USD"

    def test_normalize_pairs_list(self):
        """Mixed format pairs should all normalize correctly."""
        loader = EnhancedScalperConfigLoader()
        input_pairs = ["BTCUSD", "ETH-USDT", "SOL/USD"]
        expected = ["BTC/USD", "ETH/USDT", "SOL/USD"]
        assert loader.normalize_pairs(input_pairs) == expected

    def test_pairs_normalized_on_load(self, valid_bar_reaction_config):
        """Pairs should be auto-normalized during config load."""
        config = valid_bar_reaction_config.copy()
        config['bar_reaction_5m']['pairs'] = ['BTCUSD', 'ETH-USD', 'SOLUSDT']

        temp_path = create_invalid_config(config)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            loaded_config = loader.load_config()

            expected_pairs = ['BTC/USD', 'ETH/USD', 'SOL/USDT']
            assert loaded_config['bar_reaction_5m']['pairs'] == expected_pairs
        finally:
            Path(temp_path).unlink(missing_ok=True)


# =============================================================================
# HAPPY PATH TESTS
# =============================================================================

class TestHappyPath:
    """Test valid configurations that should load successfully."""

    def test_valid_config_loads(self, temp_config_file):
        """Valid configuration should load without errors."""
        loader = EnhancedScalperConfigLoader(temp_config_file)
        config = loader.load_config()

        assert 'bar_reaction_5m' in config
        assert config['bar_reaction_5m']['mode'] == 'trend'
        assert config['bar_reaction_5m']['timeframe'] == '5m'

    def test_all_required_fields_present(self, temp_config_file):
        """All required fields should be present in loaded config."""
        loader = EnhancedScalperConfigLoader(temp_config_file)
        config = loader.load_config()

        br_config = config['bar_reaction_5m']

        # Check all critical fields
        assert 'timeframe' in br_config
        assert 'trigger_bps_up' in br_config
        assert 'trigger_bps_down' in br_config
        assert 'min_atr_pct' in br_config
        assert 'max_atr_pct' in br_config
        assert 'atr_window' in br_config
        assert 'mode' in br_config
        assert 'maker_only' in br_config

    def test_values_match_expected(self, temp_config_file):
        """Loaded values should match what was written."""
        loader = EnhancedScalperConfigLoader(temp_config_file)
        config = loader.load_config()

        br_config = config['bar_reaction_5m']

        assert br_config['timeframe'] == '5m'
        assert br_config['trigger_bps_up'] == 12
        assert br_config['trigger_bps_down'] == 12
        assert br_config['min_atr_pct'] == 0.25
        assert br_config['max_atr_pct'] == 3.0
        assert br_config['atr_window'] == 14
        assert br_config['mode'] == 'trend'
        assert br_config['maker_only'] is True

    def test_trend_mode_valid(self, valid_bar_reaction_config):
        """Mode 'trend' should be valid."""
        temp_path = create_invalid_config(valid_bar_reaction_config, mode='trend')
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            config = loader.load_config()
            assert config['bar_reaction_5m']['mode'] == 'trend'
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_revert_mode_valid(self, valid_bar_reaction_config):
        """Mode 'revert' should be valid."""
        temp_path = create_invalid_config(valid_bar_reaction_config, mode='revert')
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            config = loader.load_config()
            assert config['bar_reaction_5m']['mode'] == 'revert'
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_open_to_close_trigger_mode_valid(self, valid_bar_reaction_config):
        """trigger_mode 'open_to_close' should be valid."""
        temp_path = create_invalid_config(valid_bar_reaction_config, trigger_mode='open_to_close')
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            config = loader.load_config()
            assert config['bar_reaction_5m']['trigger_mode'] == 'open_to_close'
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_prev_close_to_close_trigger_mode_valid(self, valid_bar_reaction_config):
        """trigger_mode 'prev_close_to_close' should be valid."""
        temp_path = create_invalid_config(valid_bar_reaction_config, trigger_mode='prev_close_to_close')
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            config = loader.load_config()
            assert config['bar_reaction_5m']['trigger_mode'] == 'prev_close_to_close'
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_extreme_mode_disabled(self, valid_bar_reaction_config):
        """Extreme mode disabled should not require threshold/factor fields."""
        config = valid_bar_reaction_config.copy()
        config['bar_reaction_5m']['enable_mean_revert_extremes'] = False
        del config['bar_reaction_5m']['extreme_bps_threshold']
        del config['bar_reaction_5m']['mean_revert_size_factor']

        temp_path = create_invalid_config(config)
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            loaded_config = loader.load_config()
            assert loaded_config['bar_reaction_5m']['enable_mean_revert_extremes'] is False
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_high_trigger_bps_valid(self, valid_bar_reaction_config):
        """High trigger_bps values should be valid (with matching extreme threshold)."""
        temp_path = create_invalid_config(
            valid_bar_reaction_config,
            trigger_bps_up=50,
            trigger_bps_down=50,
            extreme_bps_threshold=80,  # Must be > trigger_bps_up when extreme mode enabled
        )
        try:
            loader = EnhancedScalperConfigLoader(temp_path)
            config = loader.load_config()
            assert config['bar_reaction_5m']['trigger_bps_up'] == 50
            assert config['bar_reaction_5m']['extreme_bps_threshold'] == 80
        finally:
            Path(temp_path).unlink(missing_ok=True)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Test integration with actual config file."""

    def test_load_actual_config_file(self):
        """Should be able to load the actual enhanced_scalper_config.yaml."""
        config_path = Path("config/enhanced_scalper_config.yaml")

        if not config_path.exists():
            pytest.skip("Config file not found")

        loader = EnhancedScalperConfigLoader(str(config_path))
        config = loader.load_config()

        # Verify bar_reaction_5m exists and is valid
        assert 'bar_reaction_5m' in config
        br_config = config['bar_reaction_5m']

        # Check critical fields
        assert br_config['timeframe'] == '5m'
        assert br_config['trigger_bps_up'] > 0
        assert br_config['trigger_bps_down'] > 0
        assert br_config['min_atr_pct'] < br_config['max_atr_pct']
        assert br_config['maker_only'] is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
