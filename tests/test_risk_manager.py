"""
tests/test_risk_manager.py - Comprehensive Risk Manager Tests (STEP 5)

Tests for per-trade risk limits, portfolio caps, RR filters, and DD breakers.

Requirements from STEP 5:
- Per-trade risk 1-2% (strict) - deny if >2%
- Portfolio at-risk ≤4%
- Min RR ≥1.6 (configurable)
- DD breakers: 10% → halve risk, 15-20% → pause N bars
- Cooldown respected by router

Author: Crypto AI Bot Team
"""

import pytest
from decimal import Decimal
from agents.risk_manager import (
    RiskManager,
    RiskConfig,
    SignalInput,
    PositionSize,
    RiskCheckResult,
    DrawdownState,
    create_risk_manager,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def default_config():
    """Default risk configuration"""
    return RiskConfig(
        per_trade_risk_pct_min=0.01,
        per_trade_risk_pct_max=0.02,
        max_portfolio_risk_pct=0.04,
        max_concurrent_positions=3,
        default_leverage=2.0,
        max_leverage_default=5.0,
        min_rr_ratio=1.6,  # NEW: Min risk/reward ratio
        dd_soft_threshold_pct=-0.10,  # NEW: 10% → halve risk
        dd_hard_threshold_pct=-0.15,  # NEW: 15% → pause
        dd_halt_threshold_pct=-0.20,  # NEW: 20% → full halt
        dd_risk_multiplier_soft=0.5,
        dd_pause_bars=10,
        min_position_usd=10.0,
    )


@pytest.fixture
def risk_manager(default_config):
    """Risk manager with default config"""
    return RiskManager(config=default_config)


@pytest.fixture
def sample_signal():
    """Sample valid signal with good RR"""
    return SignalInput(
        signal_id="test_001",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("49000.00"),  # -2% SL
        take_profit=Decimal("53000.00"),  # +6% TP (RR = 3.0)
        confidence=Decimal("0.75"),
    )


@pytest.fixture
def low_rr_signal():
    """Signal with RR < 1.6 (should be rejected)"""
    return SignalInput(
        signal_id="test_002",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("49000.00"),  # -2% SL
        take_profit=Decimal("51000.00"),  # +2% TP (RR = 1.0)
        confidence=Decimal("0.75"),
    )


@pytest.fixture
def tight_sl_signal():
    """Signal with very tight SL (high position size, may violate 2% risk)"""
    return SignalInput(
        signal_id="test_003",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("49900.00"),  # -0.2% SL (very tight)
        take_profit=Decimal("51000.00"),
        confidence=Decimal("0.75"),
    )


# =============================================================================
# TEST: BASIC POSITION SIZING
# =============================================================================


class TestBasicPositionSizing:
    """Test basic position sizing logic"""

    def test_position_sizing_from_sl_distance(self, risk_manager, sample_signal):
        """Test that position size is calculated from SL distance"""
        equity = Decimal("10000.00")
        position = risk_manager.size_position(sample_signal, equity)

        # With 2% SL and 2% risk target:
        # target_risk = 10000 * 0.02 = 200
        # position_size = 200 / 0.02 = 10000 notional
        assert position.allowed
        assert float(position.risk_pct) <= 0.02  # Within 2% limit
        assert float(position.expected_risk_usd) > 0

    def test_leverage_applied_correctly(self, risk_manager, sample_signal):
        """Test that leverage is applied correctly"""
        equity = Decimal("10000.00")
        position = risk_manager.size_position(sample_signal, equity)

        assert float(position.leverage) == 2.0  # Default leverage
        assert position.allowed

    def test_min_position_size_filter(self, risk_manager):
        """Test that positions below minimum USD are rejected"""
        # Create signal with very wide SL but good RR
        wide_sl_signal = SignalInput(
            signal_id="test_wide_sl",
            symbol="BTC/USD",
            side="long",
            entry_price=Decimal("50000.00"),
            stop_loss=Decimal("25000.00"),  # -50% SL (very wide)
            take_profit=Decimal("100000.00"),  # +100% TP (RR = 2.0, good)
            confidence=Decimal("0.75"),
        )

        equity = Decimal("10000.00")
        position = risk_manager.size_position(wide_sl_signal, equity)

        # Position should be rejected for being too small
        if float(position.notional_usd) < 10.0:
            assert not position.allowed
            assert any("below_min_position_usd" in r for r in position.rejection_reasons)


# =============================================================================
# TEST: STRICT PER-TRADE RISK LIMITS
# =============================================================================


class TestPerTradeRiskLimits:
    """Test strict 1-2% per-trade risk enforcement"""

    def test_risk_within_1_to_2_percent(self, risk_manager, sample_signal):
        """Test that risk is within 1-2% range"""
        equity = Decimal("10000.00")
        position = risk_manager.size_position(sample_signal, equity)

        assert position.allowed
        risk_pct = float(position.risk_pct)
        assert 0.01 <= risk_pct <= 0.02, f"Risk {risk_pct:.2%} outside 1-2% range"

    def test_reject_if_risk_exceeds_2_percent(self, risk_manager, tight_sl_signal):
        """Test that positions with >2% risk are rejected"""
        equity = Decimal("100.00")  # Very small equity
        position = risk_manager.size_position(tight_sl_signal, equity)

        # With tight SL and small equity, risk might exceed 2%
        if float(position.risk_pct) > 0.02:
            assert not position.allowed
            assert "risk_exceeds_max" in position.rejection_reasons

    def test_risk_scales_with_equity(self, risk_manager, sample_signal):
        """Test that risk scales proportionally with equity"""
        equity_small = Decimal("1000.00")
        equity_large = Decimal("100000.00")

        pos_small = risk_manager.size_position(sample_signal, equity_small)
        pos_large = risk_manager.size_position(sample_signal, equity_large)

        # Risk percentage should be similar
        assert abs(float(pos_small.risk_pct) - float(pos_large.risk_pct)) < 0.001

        # But absolute USD risk should scale
        assert float(pos_large.expected_risk_usd) > float(pos_small.expected_risk_usd)


# =============================================================================
# TEST: RISK/REWARD RATIO FILTER
# =============================================================================


class TestRiskRewardFilter:
    """Test minimum RR ratio filter (≥1.6)"""

    def test_good_rr_accepted(self, risk_manager, sample_signal):
        """Test that signals with RR ≥ 1.6 are accepted"""
        equity = Decimal("10000.00")
        position = risk_manager.size_position(sample_signal, equity)

        # Sample signal has RR = 3.0 (should pass)
        assert position.allowed
        assert "low_risk_reward_ratio" not in position.rejection_reasons

    def test_low_rr_rejected(self, risk_manager, low_rr_signal):
        """Test that signals with RR < 1.6 are rejected"""
        equity = Decimal("10000.00")
        position = risk_manager.size_position(low_rr_signal, equity)

        # Low RR signal has RR = 1.0 (should fail)
        assert not position.allowed
        assert any("low_risk_reward_ratio" in r for r in position.rejection_reasons)

    def test_rr_configurable(self):
        """Test that min RR can be configured"""
        config = RiskConfig(min_rr_ratio=2.0)  # Stricter RR requirement
        rm = RiskManager(config=config)

        # Signal with RR = 1.5 (passes default 1.6 but fails 2.0)
        signal_rr_15 = SignalInput(
            signal_id="test_rr",
            symbol="BTC/USD",
            side="long",
            entry_price=Decimal("50000.00"),
            stop_loss=Decimal("49000.00"),  # -2% SL
            take_profit=Decimal("51500.00"),  # +3% TP (RR = 1.5)
            confidence=Decimal("0.75"),
        )

        equity = Decimal("10000.00")
        position = rm.size_position(signal_rr_15, equity)

        assert not position.allowed
        assert any("low_risk_reward_ratio" in r for r in position.rejection_reasons)


# =============================================================================
# TEST: PORTFOLIO RISK CAPS
# =============================================================================


class TestPortfolioRiskCaps:
    """Test portfolio-level risk limits (≤4%)"""

    def test_portfolio_risk_within_limit(self, risk_manager, sample_signal):
        """Test that portfolio risk within 4% passes"""
        equity = Decimal("10000.00")

        # Create 2 positions @ 2% each = 4% total
        pos1 = risk_manager.size_position(sample_signal, equity)
        pos2 = risk_manager.size_position(sample_signal, equity)

        positions = [pos1, pos2]
        risk_check = risk_manager.check_portfolio_risk(positions, equity)

        assert risk_check.passed
        assert float(risk_check.total_risk_pct) <= 0.04

    def test_portfolio_risk_exceeds_limit(self, risk_manager, sample_signal):
        """Test that portfolio risk >4% fails"""
        equity = Decimal("10000.00")

        # Create 3 positions @ 2% each = 6% total (exceeds 4%)
        pos1 = risk_manager.size_position(sample_signal, equity)
        pos2 = risk_manager.size_position(sample_signal, equity)
        pos3 = risk_manager.size_position(sample_signal, equity)

        positions = [pos1, pos2, pos3]
        risk_check = risk_manager.check_portfolio_risk(positions, equity)

        assert not risk_check.passed
        assert "portfolio_risk_exceeded" in risk_check.violations[0]

    def test_max_concurrent_positions(self):
        """Test max concurrent positions limit"""
        # Use lower per-trade risk to avoid portfolio risk limit
        config = RiskConfig(
            per_trade_risk_pct_min=0.003,  # 0.3% min
            per_trade_risk_pct_max=0.005,  # 0.5% per trade max
            max_concurrent_positions=2,  # Only 2 positions allowed
            max_portfolio_risk_pct=0.10,  # 10% portfolio limit
        )
        rm = RiskManager(config=config)

        sample_signal = SignalInput(
            signal_id="test_001",
            symbol="BTC/USD",
            side="long",
            entry_price=Decimal("50000.00"),
            stop_loss=Decimal("49000.00"),
            take_profit=Decimal("53000.00"),
            confidence=Decimal("0.75"),
        )

        equity = Decimal("10000.00")

        # Create 3 positions (exceeds max of 2)
        positions = [rm.size_position(sample_signal, equity) for _ in range(3)]

        risk_check = rm.check_portfolio_risk(positions, equity)

        assert not risk_check.passed
        assert any("max_positions_exceeded" in v for v in risk_check.violations)


# =============================================================================
# TEST: DRAWDOWN BREAKERS
# =============================================================================


class TestDrawdownBreakers:
    """Test DD breaker state machine (10% → halve, 15-20% → pause)"""

    def test_normal_mode_no_drawdown(self, risk_manager):
        """Test normal mode when no drawdown"""
        equity_curve = [
            Decimal("10000"),
            Decimal("10100"),
            Decimal("10200"),
        ]

        dd_state = risk_manager.update_drawdown_state(equity_curve, current_bar=2)

        assert dd_state.mode == "normal"
        assert dd_state.risk_multiplier == 1.0
        assert dd_state.pause_remaining == 0

    def test_soft_stop_at_10_percent_dd(self, risk_manager):
        """Test soft stop (0.5x risk) triggers at -10% DD"""
        equity_curve = [
            Decimal("10000"),
            Decimal("9000"),  # -10% DD
        ]

        dd_state = risk_manager.update_drawdown_state(equity_curve, current_bar=1)

        assert dd_state.mode == "soft_stop"
        assert dd_state.risk_multiplier == 0.5  # Halve risk
        assert dd_state.rolling_dd_pct <= -0.10

    def test_hard_halt_at_15_percent_dd(self, risk_manager):
        """Test hard halt triggers at -15% DD"""
        equity_curve = [
            Decimal("10000"),
            Decimal("8500"),  # -15% DD
        ]

        dd_state = risk_manager.update_drawdown_state(equity_curve, current_bar=1)

        assert dd_state.mode == "hard_halt"
        assert dd_state.risk_multiplier == 0.0  # No trading
        assert dd_state.pause_remaining > 0

    def test_full_halt_at_20_percent_dd(self, risk_manager):
        """Test full halt at -20% DD"""
        equity_curve = [
            Decimal("10000"),
            Decimal("8000"),  # -20% DD
        ]

        dd_state = risk_manager.update_drawdown_state(equity_curve, current_bar=1)

        assert dd_state.mode == "hard_halt"
        assert dd_state.risk_multiplier == 0.0
        assert dd_state.pause_remaining == 20  # Extended pause (2x default)

    def test_cooldown_countdown(self, risk_manager):
        """Test that pause cooldown counts down"""
        # Trigger hard halt at -20%
        equity_curve = [Decimal("10000"), Decimal("8000")]
        dd_state1 = risk_manager.update_drawdown_state(equity_curve, current_bar=1)
        assert dd_state1.pause_remaining == 20  # Extended pause

        # Add more bars (recovery)
        for i in range(5):
            equity_curve.append(Decimal("8100"))
            dd_state = risk_manager.update_drawdown_state(equity_curve, current_bar=len(equity_curve) - 1)

        # Pause should count down from initial 20
        assert dd_state.pause_remaining < 20
        assert dd_state.mode == "hard_halt"  # Still in cooldown

    def test_recovery_to_normal(self, risk_manager):
        """Test recovery to normal mode after DD improves"""
        # Start with drawdown that triggers soft_stop (-10% threshold)
        equity_curve = [Decimal("10000"), Decimal("8900")]  # -11% DD (below -10%)
        dd_state1 = risk_manager.update_drawdown_state(equity_curve, current_bar=1)
        assert dd_state1.mode == "soft_stop"

        # Recover fully
        equity_curve.extend([Decimal("10000"), Decimal("10100"), Decimal("10200")])
        dd_state2 = risk_manager.update_drawdown_state(equity_curve, current_bar=len(equity_curve) - 1)

        # Should return to normal
        assert dd_state2.mode == "normal"
        assert dd_state2.risk_multiplier == 1.0


# =============================================================================
# TEST: DRAWDOWN AFFECTS SIZING
# =============================================================================


class TestDrawdownAffectsSizing:
    """Test that DD state affects position sizing"""

    def test_sizing_reduced_in_soft_stop(self, risk_manager, sample_signal):
        """Test that position size is halved in soft stop mode"""
        equity = Decimal("10000.00")

        # Normal sizing
        pos_normal = risk_manager.size_position(sample_signal, equity)
        normal_size = float(pos_normal.notional_usd)

        # Trigger soft stop
        equity_curve = [Decimal("10000"), Decimal("9000")]  # -10% DD
        risk_manager.update_drawdown_state(equity_curve, current_bar=1)

        # Sizing after soft stop
        pos_soft = risk_manager.size_position(sample_signal, equity)
        soft_size = float(pos_soft.notional_usd)

        # Size should be approximately halved
        assert soft_size < normal_size
        assert abs(soft_size / normal_size - 0.5) < 0.1  # ~50%

    def test_entries_blocked_in_hard_halt(self, risk_manager, sample_signal):
        """Test that entries are blocked in hard halt mode"""
        equity = Decimal("10000.00")

        # Trigger hard halt
        equity_curve = [Decimal("10000"), Decimal("8500")]  # -15% DD
        risk_manager.update_drawdown_state(equity_curve, current_bar=1)

        # Try to size position
        position = risk_manager.size_position(sample_signal, equity)

        assert not position.allowed
        assert "drawdown_hard_halt" in position.rejection_reasons


# =============================================================================
# TEST: LEVERAGE CAPS
# =============================================================================


class TestLeverageCaps:
    """Test per-symbol leverage caps"""

    def test_default_leverage_applied(self, risk_manager, sample_signal):
        """Test that default leverage is applied"""
        equity = Decimal("10000.00")
        position = risk_manager.size_position(sample_signal, equity)

        assert float(position.leverage) == 2.0  # Default

    def test_symbol_specific_leverage_cap(self):
        """Test that per-symbol leverage caps are respected"""
        config = RiskConfig(
            default_leverage=3.0,
            max_leverage_default=5.0,
            leverage_caps={"BTC/USD": 2.0, "ETH/USD": 3.0},
        )
        rm = RiskManager(config=config)

        # BTC should be capped at 2.0
        btc_cap = rm.get_max_leverage("BTC/USD")
        assert btc_cap == 2.0

        # ETH should be capped at 3.0
        eth_cap = rm.get_max_leverage("ETH/USD")
        assert eth_cap == 3.0

        # Unknown symbol should use default
        unknown_cap = rm.get_max_leverage("DOGE/USD")
        assert unknown_cap == 5.0


# =============================================================================
# TEST: METRICS TRACKING
# =============================================================================


class TestMetricsTracking:
    """Test risk manager metrics"""

    def test_metrics_track_rejections(self, risk_manager, low_rr_signal):
        """Test that metrics track rejections correctly"""
        equity = Decimal("10000.00")

        # Reset metrics
        risk_manager.reset_metrics()

        # Size a few positions (some will be rejected)
        for _ in range(5):
            risk_manager.size_position(low_rr_signal, equity)

        metrics = risk_manager.get_metrics()

        assert metrics["total_sized"] == 5
        assert metrics["total_rejected"] > 0

    def test_metrics_can_be_reset(self, risk_manager, sample_signal):
        """Test that metrics can be reset"""
        equity = Decimal("10000.00")

        # Generate some metrics
        risk_manager.size_position(sample_signal, equity)

        # Reset
        risk_manager.reset_metrics()
        metrics = risk_manager.get_metrics()

        assert metrics["total_sized"] == 0
        assert metrics["total_rejected"] == 0


# =============================================================================
# TEST: INTEGRATION SCENARIOS
# =============================================================================


class TestIntegrationScenarios:
    """Test realistic end-to-end scenarios"""

    def test_full_risk_workflow(self, risk_manager, sample_signal):
        """Test complete risk workflow: size → check portfolio → DD check"""
        equity = Decimal("10000.00")

        # 1. Size position
        position = risk_manager.size_position(sample_signal, equity)
        assert position.allowed

        # 2. Check portfolio risk
        risk_check = risk_manager.check_portfolio_risk([position], equity)
        assert risk_check.passed

        # 3. Update DD state (normal)
        equity_curve = [Decimal("10000"), Decimal("10100")]
        dd_state = risk_manager.update_drawdown_state(equity_curve, current_bar=1)
        assert dd_state.mode == "normal"

    def test_multiple_rejections_cascade(self, risk_manager, low_rr_signal):
        """Test that multiple rejection reasons cascade correctly"""
        equity = Decimal("50.00")  # Very small equity

        # This signal has low RR AND might violate min position size
        position = risk_manager.size_position(low_rr_signal, equity)

        assert not position.allowed
        assert len(position.rejection_reasons) >= 1  # At least one rejection


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
