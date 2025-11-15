"""
Unit Tests for Dynamic Position Sizing Module

Tests:
- Base risk scaling based on equity
- Win streak boost with safety caps
- Volatility adjustment
- Portfolio heat limiter
- Runtime overrides
- Safety limits enforcement

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import time
from decimal import Decimal

import pytest

from agents.scalper.risk.dynamic_sizing import (
    DynamicPositionSizer,
    DynamicSizingConfig,
    TradeOutcome,
    create_default_sizer,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def default_config():
    """Default production-safe config."""
    return DynamicSizingConfig()


@pytest.fixture
def default_sizer(default_config):
    """Default sizer with production config."""
    return DynamicPositionSizer(default_config)


@pytest.fixture
def custom_config():
    """Custom config for testing edge cases."""
    return DynamicSizingConfig(
        base_risk_pct_small=2.0,
        base_risk_pct_large=1.5,
        equity_threshold_usd=10000.0,
        streak_boost_pct=0.3,
        max_streak_boost_pct=1.5,
        max_streak_count=5,
        high_vol_multiplier=0.6,
        normal_vol_multiplier=1.0,
        high_vol_threshold_atr_pct=3.0,
        portfolio_heat_threshold_pct=70.0,
        portfolio_heat_cut_multiplier=0.4,
    )


# =============================================================================
# TEST: BASE RISK SCALING
# =============================================================================


def test_base_risk_small_equity(default_sizer):
    """Test base risk is 1.5% when equity < $15k."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=10000.0,  # < 15k
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.0,
    )

    assert breakdown["base_risk_pct"] == 1.5
    assert multiplier == pytest.approx(1.5, rel=0.01)  # 1.5% / 1.0% = 1.5x


def test_base_risk_large_equity(default_sizer):
    """Test base risk is 1.0% when equity >= $15k."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,  # >= 15k
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.0,
    )

    assert breakdown["base_risk_pct"] == 1.0
    assert multiplier == pytest.approx(1.0, rel=0.01)  # 1.0% / 1.0% = 1.0x


def test_base_risk_at_threshold(default_sizer):
    """Test base risk exactly at threshold."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=15000.0,  # Exactly at threshold
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.0,
    )

    # At threshold should use large equity rate
    assert breakdown["base_risk_pct"] == 1.0


# =============================================================================
# TEST: WIN STREAK BOOST
# =============================================================================


def test_no_boost_with_no_streak(default_sizer):
    """Test no boost when no winning streak."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.0,
    )

    assert breakdown["streak_boost_pct"] == 0.0
    assert default_sizer.current_streak == 0


def test_boost_increases_with_wins(default_sizer):
    """Test boost increases with consecutive wins."""
    # Record 2 consecutive wins
    default_sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)
    default_sizer.record_trade("BTC/USD", pnl_usd=50.0, size_usd=1000.0)

    assert default_sizer.current_streak == 2

    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.0,
    )

    # Boost should be 2 * 0.2% = 0.4%
    assert breakdown["streak_boost_pct"] == pytest.approx(0.4, rel=0.01)


def test_boost_capped_at_max(default_sizer):
    """Test boost is capped at max_streak_boost_pct (1.0%)."""
    # Record 10 wins (way more than cap)
    for _ in range(10):
        default_sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)

    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.0,
    )

    # Boost should be capped at 1.0%
    assert breakdown["streak_boost_pct"] == pytest.approx(1.0, rel=0.01)
    assert breakdown["streak_boost_pct"] <= 1.0  # Ensure it never exceeds


def test_boost_resets_on_loss(default_sizer):
    """Test boost resets to 0 after a loss."""
    # Build streak
    default_sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)
    default_sizer.record_trade("BTC/USD", pnl_usd=50.0, size_usd=1000.0)
    assert default_sizer.current_streak == 2

    # Record loss
    default_sizer.record_trade("BTC/USD", pnl_usd=-100.0, size_usd=1000.0)
    assert default_sizer.current_streak == -1  # Negative streak

    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.0,
    )

    # No boost for negative streak
    assert breakdown["streak_boost_pct"] == 0.0


def test_streak_boost_safety_never_exceeds_2_5_pct(default_sizer):
    """CRITICAL SAFETY TEST: Boost never exceeds 1.0% (not 2.5%)."""
    # Record massive winning streak (100 wins)
    for _ in range(100):
        default_sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)

    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.0,
    )

    # Ensure boost is NEVER more than 1.0%
    assert breakdown["streak_boost_pct"] <= 1.0
    assert breakdown["streak_boost_pct"] == pytest.approx(1.0, rel=0.01)


# =============================================================================
# TEST: VOLATILITY ADJUSTMENT
# =============================================================================


def test_normal_vol_no_adjustment(default_sizer):
    """Test normal volatility (< 2.0% ATR) → 1.0x multiplier."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.5,  # Normal vol
    )

    assert breakdown["vol_multiplier"] == 1.0


def test_high_vol_reduces_size(default_sizer):
    """Test high volatility (>= 2.0% ATR) → 0.8x multiplier."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=2.5,  # High vol
    )

    assert breakdown["vol_multiplier"] == 0.8


def test_vol_at_threshold(default_sizer):
    """Test volatility exactly at threshold."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=2.0,  # Exactly at threshold
    )

    # At threshold should trigger high vol
    assert breakdown["vol_multiplier"] == 0.8


def test_vol_none_defaults_to_normal(default_sizer):
    """Test None volatility defaults to normal (1.0x)."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=None,  # No data
    )

    assert breakdown["vol_multiplier"] == 1.0


# =============================================================================
# TEST: PORTFOLIO HEAT LIMITER
# =============================================================================


def test_normal_heat_no_limit(default_sizer):
    """Test normal heat (< 80%) → 1.0x multiplier."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=50.0,  # Normal heat
        current_volatility_atr_pct=1.0,
    )

    assert breakdown["heat_multiplier"] == 1.0


def test_high_heat_forces_half_size(default_sizer):
    """Test high heat (>= 80%) → 0.5x multiplier (emergency brake)."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=85.0,  # High heat
        current_volatility_atr_pct=1.0,
    )

    assert breakdown["heat_multiplier"] == 0.5
    assert multiplier <= 0.5  # Ensure size is cut


def test_heat_at_threshold(default_sizer):
    """Test heat exactly at threshold (80%)."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=80.0,  # Exactly at threshold
        current_volatility_atr_pct=1.0,
    )

    # At threshold should trigger limiter
    assert breakdown["heat_multiplier"] == 0.5


def test_heat_limiter_works_with_high_multiplier(default_sizer):
    """Test heat limiter overrides high multipliers."""
    # Build big streak
    for _ in range(5):
        default_sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)

    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=5000.0,  # Small equity → 1.5% base
        portfolio_heat_pct=90.0,  # Very high heat
        current_volatility_atr_pct=1.0,
    )

    # Even with high base + streak, heat should clamp it down
    assert breakdown["heat_multiplier"] == 0.5
    # Final multiplier should be significantly reduced
    assert multiplier < 1.0


# =============================================================================
# TEST: COMBINED FACTORS
# =============================================================================


def test_all_factors_combine_correctly(default_sizer):
    """Test all factors combine as expected."""
    # Build streak
    default_sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)
    default_sizer.record_trade("BTC/USD", pnl_usd=50.0, size_usd=1000.0)

    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=10000.0,  # < 15k → 1.5% base
        portfolio_heat_pct=50.0,  # Normal heat → 1.0x
        current_volatility_atr_pct=2.5,  # High vol → 0.8x
    )

    # Expected: (1.5% + 0.4%) * 0.8 * 1.0 / 1.0% = 1.52x
    expected = (1.5 + 0.4) * 0.8 * 1.0 / 1.0
    assert multiplier == pytest.approx(expected, rel=0.01)


def test_worst_case_all_de_risk_factors(default_sizer):
    """Test worst case: all factors reduce size."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=20000.0,  # Large equity → 1.0% base
        portfolio_heat_pct=90.0,  # Very high heat → 0.5x
        current_volatility_atr_pct=3.0,  # High vol → 0.8x
    )

    # Expected: 1.0% * 0.8 * 0.5 / 1.0% = 0.4x
    expected = 1.0 * 0.8 * 0.5 / 1.0
    assert multiplier == pytest.approx(expected, rel=0.01)


def test_best_case_all_boost_factors(default_sizer):
    """Test best case: all factors increase size (but capped)."""
    # Build max streak
    for _ in range(10):
        default_sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)

    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=10000.0,  # Small equity → 1.5% base
        portfolio_heat_pct=30.0,  # Low heat → 1.0x
        current_volatility_atr_pct=1.0,  # Normal vol → 1.0x
    )

    # Expected: (1.5% + 1.0%) * 1.0 * 1.0 / 1.0% = 2.5x
    # But should be capped at max_position_size_multiplier (3.0)
    expected_raw = (1.5 + 1.0) * 1.0 * 1.0 / 1.0
    expected_capped = min(expected_raw, 3.0)  # Cap at 3.0
    assert multiplier == pytest.approx(expected_capped, rel=0.01)
    assert multiplier <= 3.0  # Ensure cap is enforced


# =============================================================================
# TEST: SAFETY LIMITS
# =============================================================================


def test_min_multiplier_cap(default_sizer):
    """Test minimum multiplier is enforced (0.1)."""
    # Force all factors to minimum
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=50000.0,  # Very large equity
        portfolio_heat_pct=95.0,  # Very high heat
        current_volatility_atr_pct=5.0,  # Very high vol
    )

    # Should be capped at minimum
    assert multiplier >= 0.1
    assert breakdown["capped"] is True


def test_max_multiplier_cap(default_sizer):
    """Test maximum multiplier is enforced (3.0)."""
    # Build max streak
    for _ in range(20):
        default_sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)

    # Custom config with high caps to test max limit
    config = DynamicSizingConfig(
        base_risk_pct_small=5.0,  # Very high base
        streak_boost_pct=1.0,  # High boost
        max_streak_boost_pct=5.0,  # High max boost
    )
    sizer = DynamicPositionSizer(config)

    # Build streak
    for _ in range(20):
        sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)

    multiplier, breakdown = sizer.calculate_size_multiplier(
        current_equity_usd=5000.0,
        portfolio_heat_pct=20.0,
        current_volatility_atr_pct=0.5,
    )

    # Should be capped at maximum (3.0)
    assert multiplier <= 3.0
    assert multiplier == 3.0


# =============================================================================
# TEST: RUNTIME OVERRIDES
# =============================================================================


def test_runtime_override_bypasses_calculation(default_sizer):
    """Test runtime override completely bypasses normal calculation."""
    # Set override
    default_sizer.set_runtime_override("size_multiplier", 2.5, expiry_seconds=60)

    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=10000.0,
        portfolio_heat_pct=50.0,
        current_volatility_atr_pct=1.0,
    )

    # Should return override value
    assert multiplier == 2.5
    assert "override" in breakdown


def test_runtime_override_expires(default_sizer):
    """Test runtime override expires after specified time."""
    # Set override with 1 second expiry
    default_sizer.set_runtime_override("size_multiplier", 2.5, expiry_seconds=1)

    # Should work immediately
    multiplier1, _ = default_sizer.calculate_size_multiplier(10000.0, 50.0, 1.0)
    assert multiplier1 == 2.5

    # Wait for expiry
    time.sleep(1.1)

    # Should revert to normal calculation
    multiplier2, breakdown = default_sizer.calculate_size_multiplier(10000.0, 50.0, 1.0)
    assert multiplier2 != 2.5
    assert "override" not in breakdown


def test_clear_runtime_override(default_sizer):
    """Test clearing runtime override."""
    # Set override
    default_sizer.set_runtime_override("size_multiplier", 2.5)

    # Clear it
    default_sizer.clear_runtime_override("size_multiplier")

    # Should revert to normal calculation
    multiplier, breakdown = default_sizer.calculate_size_multiplier(10000.0, 50.0, 1.0)
    assert multiplier != 2.5
    assert "override" not in breakdown


def test_override_disabled_in_config():
    """Test overrides are ignored when disabled in config."""
    config = DynamicSizingConfig(allow_runtime_overrides=False)
    sizer = DynamicPositionSizer(config)

    # Try to set override (should be ignored)
    sizer.set_runtime_override("size_multiplier", 2.5)

    multiplier, breakdown = sizer.calculate_size_multiplier(10000.0, 50.0, 1.0)

    # Should use normal calculation (not override)
    assert multiplier != 2.5


# =============================================================================
# TEST: STATE MANAGEMENT
# =============================================================================


def test_get_state(default_sizer):
    """Test getting sizer state for monitoring."""
    # Record some trades
    default_sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)
    default_sizer.record_trade("ETH/USD", pnl_usd=-50.0, size_usd=500.0)

    state = default_sizer.get_state()

    assert "current_streak" in state
    assert "trade_count" in state
    assert "recent_trades" in state
    assert state["trade_count"] == 2


def test_reset_streak(default_sizer):
    """Test resetting streak manually."""
    # Build streak
    default_sizer.record_trade("BTC/USD", pnl_usd=100.0, size_usd=1000.0)
    default_sizer.record_trade("BTC/USD", pnl_usd=50.0, size_usd=1000.0)
    assert default_sizer.current_streak == 2

    # Reset
    default_sizer.reset_streak()
    assert default_sizer.current_streak == 0


# =============================================================================
# TEST: ERROR HANDLING
# =============================================================================


def test_failsafe_on_exception(default_sizer, monkeypatch):
    """Test failsafe returns 1.0x on any exception."""

    def mock_error(*args, **kwargs):
        raise ValueError("Test error")

    monkeypatch.setattr(default_sizer, "_calculate_base_risk", mock_error)

    multiplier, breakdown = default_sizer.calculate_size_multiplier(10000.0, 50.0, 1.0)

    # Should return failsafe value
    assert multiplier == 1.0
    assert "failsafe" in breakdown


# =============================================================================
# TEST: EDGE CASES
# =============================================================================


def test_zero_equity(default_sizer):
    """Test handling of zero equity."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=0.0,
        portfolio_heat_pct=0.0,
        current_volatility_atr_pct=1.0,
    )

    # Should handle gracefully (use small equity base)
    assert multiplier > 0


def test_negative_equity(default_sizer):
    """Test handling of negative equity (blown account)."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=-1000.0,  # Negative equity
        portfolio_heat_pct=100.0,
        current_volatility_atr_pct=1.0,
    )

    # Should still return valid multiplier
    assert multiplier > 0


def test_extreme_heat(default_sizer):
    """Test handling of extreme heat (>100%)."""
    multiplier, breakdown = default_sizer.calculate_size_multiplier(
        current_equity_usd=10000.0,
        portfolio_heat_pct=150.0,  # Over 100%
        current_volatility_atr_pct=1.0,
    )

    # Should trigger heat limiter
    assert breakdown["heat_multiplier"] == 0.5


# =============================================================================
# TEST: FACTORY FUNCTIONS
# =============================================================================


def test_create_default_sizer():
    """Test factory function creates sizer with default config."""
    sizer = create_default_sizer()
    assert isinstance(sizer, DynamicPositionSizer)
    assert sizer.config.base_risk_pct_small == 1.5
    assert sizer.config.base_risk_pct_large == 1.0


def test_create_sizer_from_dict():
    """Test factory function creates sizer from dict."""
    from agents.scalper.risk.dynamic_sizing import create_sizer_from_dict

    config_dict = {
        "base_risk_pct_small": 2.0,
        "base_risk_pct_large": 1.5,
        "equity_threshold_usd": 10000.0,
    }

    sizer = create_sizer_from_dict(config_dict)
    assert sizer.config.base_risk_pct_small == 2.0
    assert sizer.config.base_risk_pct_large == 1.5
    assert sizer.config.equity_threshold_usd == 10000.0
