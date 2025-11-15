"""
Comprehensive tests for agents/risk_manager.py

Tests cover:
- Position sizing math (1-2% risk via SL distance)
- Portfolio risk caps (≤4% total)
- Leverage limits (per-symbol caps, default 2-3x, max 5x)
- Drawdown breakers (daily/rolling thresholds, risk reduction, cooldown)
- Edge cases (zero equity, extreme volatility, etc.)

Per PRD §6 & §8 requirements.
"""

import pytest
from decimal import Decimal
from typing import List

from agents.risk_manager import (
    RiskConfig,
    RiskManager,
    PositionSize,
    RiskCheckResult,
    DrawdownState,
    SignalInput,
    create_risk_manager,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def default_config():
    """Default risk configuration"""
    return RiskConfig()


@pytest.fixture
def risk_manager(default_config):
    """Default risk manager instance"""
    return RiskManager(config=default_config)


@pytest.fixture
def sample_signal():
    """Sample signal with 2% SL distance"""
    return SignalInput(
        signal_id="test_001",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("49000.00"),  # 2% SL
        take_profit=Decimal("52000.00"),
        confidence=Decimal("0.75"),
    )


@pytest.fixture
def sample_signal_tight_sl():
    """Signal with tight 1% SL"""
    return SignalInput(
        signal_id="test_002",
        symbol="ETH/USD",
        side="long",
        entry_price=Decimal("3000.00"),
        stop_loss=Decimal("2970.00"),  # 1% SL
        take_profit=Decimal("3100.00"),
        confidence=Decimal("0.80"),
    )


@pytest.fixture
def sample_signal_short():
    """Short signal with 3% SL"""
    return SignalInput(
        signal_id="test_003",
        symbol="BTC/USD",
        side="short",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("51500.00"),  # 3% SL
        take_profit=Decimal("48000.00"),
        confidence=Decimal("0.70"),
    )


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================


def test_risk_manager_initialization_default():
    """Test risk manager initializes with defaults"""
    rm = RiskManager()
    assert rm.config.per_trade_risk_pct_max == 0.02
    assert rm.config.max_portfolio_risk_pct == 0.04
    assert rm.config.default_leverage == 2.0
    assert rm.config.max_leverage_default == 5.0


def test_risk_manager_initialization_custom():
    """Test risk manager with custom config"""
    config = RiskConfig(
        per_trade_risk_pct_max=0.01,
        max_portfolio_risk_pct=0.03,
        default_leverage=3.0,
    )
    rm = RiskManager(config=config)
    assert rm.config.per_trade_risk_pct_max == 0.01
    assert rm.config.max_portfolio_risk_pct == 0.03
    assert rm.config.default_leverage == 3.0


def test_create_risk_manager_convenience():
    """Test convenience factory function"""
    rm = create_risk_manager(
        per_trade_risk_pct=0.015,
        max_portfolio_risk_pct=0.035,
        max_leverage=4.0,
    )
    assert rm.config.per_trade_risk_pct_max == 0.015
    assert rm.config.max_portfolio_risk_pct == 0.035
    assert rm.config.max_leverage_default == 4.0


# =============================================================================
# POSITION SIZING TESTS
# =============================================================================


def test_size_position_basic(risk_manager, sample_signal):
    """Test basic position sizing with 2% risk and 2% SL"""
    equity = Decimal("10000.00")
    position = risk_manager.size_position(sample_signal, equity)

    # Expected: 2% risk = $200, SL distance = 2%, so notional = $200/0.02 = $10000
    assert position.allowed
    assert float(position.expected_risk_usd) == pytest.approx(200.0, rel=0.01)
    assert float(position.risk_pct) == pytest.approx(0.02, rel=0.01)
    assert float(position.notional_usd) == pytest.approx(10000.0, rel=0.01)
    assert position.leverage == Decimal("2.0")


def test_size_position_tight_sl(risk_manager, sample_signal_tight_sl):
    """Test position sizing with tighter 1% SL"""
    equity = Decimal("10000.00")
    position = risk_manager.size_position(sample_signal_tight_sl, equity)

    # Expected: 2% risk = $200, SL distance = 1%, so notional = $200/0.01 = $20000
    assert position.allowed
    assert float(position.expected_risk_usd) == pytest.approx(200.0, rel=0.01)
    assert float(position.risk_pct) == pytest.approx(0.02, rel=0.01)
    assert float(position.notional_usd) == pytest.approx(20000.0, rel=0.01)


def test_size_position_short(risk_manager, sample_signal_short):
    """Test position sizing for short signal"""
    equity = Decimal("10000.00")
    position = risk_manager.size_position(sample_signal_short, equity)

    # Expected: 2% risk = $200, SL distance = 3%, so notional = $200/0.03 = $6666.67
    assert position.allowed
    assert position.side == "short"
    assert float(position.expected_risk_usd) == pytest.approx(200.0, rel=0.01)
    assert float(position.notional_usd) == pytest.approx(6666.67, rel=0.01)


def test_size_position_min_size_rejection(risk_manager):
    """Test rejection when position below minimum USD"""
    # Create signal with very wide SL (50%)
    signal = SignalInput(
        signal_id="test_tiny",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("25000.00"),  # 50% SL
        take_profit=Decimal("60000.00"),
        confidence=Decimal("0.50"),
    )

    equity = Decimal("100.00")  # Small equity
    position = risk_manager.size_position(signal, equity)

    # Expected: 2% risk = $2, SL = 50%, notional = $2/0.5 = $4 < min_position_usd (10)
    assert not position.allowed
    assert "below_min_position_usd" in position.rejection_reasons


def test_size_position_leverage_caps(sample_signal):
    """Test per-symbol leverage caps"""
    config = RiskConfig(leverage_caps={"BTC/USD": 3.0, "ETH/USD": 2.0})
    rm = RiskManager(config=config)
    equity = Decimal("10000.00")

    position = rm.size_position(sample_signal, equity)

    # BTC/USD capped at 3x, default is 2x, so should use 2x
    assert position.leverage == Decimal("2.0")


def test_size_position_drawdown_multiplier(risk_manager):
    """Test position sizing with drawdown risk reduction"""
    # Trigger soft stop (0.5x risk multiplier)
    equity_curve = [Decimal("10000"), Decimal("9750")]  # -2.5% daily DD
    risk_manager.update_drawdown_state(equity_curve, current_bar=1)

    signal = SignalInput(
        signal_id="test_dd",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("49000.00"),  # 2% SL
        take_profit=Decimal("52000.00"),
        confidence=Decimal("0.75"),
    )

    equity = Decimal("9750.00")
    position = risk_manager.size_position(signal, equity)

    # Expected: base risk 2% * 0.5 multiplier = 1% = $97.50
    assert position.allowed
    assert float(position.expected_risk_usd) == pytest.approx(97.50, rel=0.05)


def test_size_position_hard_halt(risk_manager):
    """Test position rejected during hard halt"""
    # Trigger hard halt (0.0x risk multiplier)
    equity_curve = [Decimal(f"{10000 - i*300}") for i in range(25)]  # -5%+ rolling DD
    risk_manager.update_drawdown_state(equity_curve, current_bar=24)

    signal = SignalInput(
        signal_id="test_halt",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("49000.00"),
        take_profit=Decimal("52000.00"),
        confidence=Decimal("0.75"),
    )

    position = risk_manager.size_position(signal, Decimal("8500.00"))

    assert not position.allowed
    assert "drawdown_hard_halt" in position.rejection_reasons
    assert float(position.expected_risk_usd) == 0.0


# =============================================================================
# PORTFOLIO RISK TESTS
# =============================================================================


def test_check_portfolio_risk_single_position(risk_manager, sample_signal):
    """Test portfolio risk check with single position"""
    equity = Decimal("10000.00")
    position = risk_manager.size_position(sample_signal, equity)

    result = risk_manager.check_portfolio_risk([position], equity)

    assert result.passed
    assert result.position_count == 1
    assert float(result.total_risk_pct) == pytest.approx(0.02, rel=0.01)
    assert len(result.violations) == 0


def test_check_portfolio_risk_multiple_positions(risk_manager):
    """Test portfolio risk with multiple positions under limit"""
    equity = Decimal("10000.00")

    # Create 2 positions with 2% risk each (total 4% = at limit)
    signals = [
        SignalInput(
            signal_id=f"test_{i}",
            symbol=f"SYM{i}/USD",
            side="long",
            entry_price=Decimal("1000.00"),
            stop_loss=Decimal("980.00"),  # 2% SL
            take_profit=Decimal("1040.00"),
            confidence=Decimal("0.75"),
        )
        for i in range(2)
    ]

    positions = [risk_manager.size_position(sig, equity) for sig in signals]
    result = risk_manager.check_portfolio_risk(positions, equity)

    assert result.passed
    assert result.position_count == 2
    assert float(result.total_risk_pct) <= 0.04


def test_check_portfolio_risk_exceeded(risk_manager):
    """Test portfolio risk rejection when exceeding 4% limit"""
    equity = Decimal("10000.00")

    # Create 3 positions with 2% risk each (total 6% > 4% limit)
    signals = [
        SignalInput(
            signal_id=f"test_{i}",
            symbol=f"SYM{i}/USD",
            side="long",
            entry_price=Decimal("1000.00"),
            stop_loss=Decimal("980.00"),  # 2% SL
            take_profit=Decimal("1040.00"),
            confidence=Decimal("0.75"),
        )
        for i in range(3)
    ]

    positions = [risk_manager.size_position(sig, equity) for sig in signals]
    result = risk_manager.check_portfolio_risk(positions, equity)

    assert not result.passed
    assert result.position_count == 3
    assert float(result.total_risk_pct) > 0.04
    assert any("portfolio_risk_exceeded" in v for v in result.violations)


def test_check_portfolio_risk_max_positions(risk_manager):
    """Test max concurrent positions limit"""
    equity = Decimal("100000.00")  # Large equity to avoid risk limit

    # Create 4 positions (> max 3)
    signals = [
        SignalInput(
            signal_id=f"test_{i}",
            symbol=f"SYM{i}/USD",
            side="long",
            entry_price=Decimal("1000.00"),
            stop_loss=Decimal("990.00"),  # 1% SL (low risk)
            take_profit=Decimal("1020.00"),
            confidence=Decimal("0.75"),
        )
        for i in range(4)
    ]

    positions = [risk_manager.size_position(sig, equity) for sig in signals]
    result = risk_manager.check_portfolio_risk(positions, equity)

    assert not result.passed
    assert result.position_count == 4
    assert any("max_positions_exceeded" in v for v in result.violations)


# =============================================================================
# DRAWDOWN BREAKER TESTS
# =============================================================================


def test_drawdown_state_normal(risk_manager):
    """Test drawdown state in normal conditions"""
    equity_curve = [Decimal("10000"), Decimal("10100"), Decimal("10200")]
    state = risk_manager.update_drawdown_state(equity_curve, current_bar=2)

    assert state.mode == "normal"
    assert state.risk_multiplier == 1.0
    assert state.pause_remaining == 0
    assert state.daily_dd_pct > 0  # Positive return


def test_drawdown_state_soft_stop(risk_manager):
    """Test soft stop trigger on daily DD threshold"""
    equity_curve = [Decimal("10000"), Decimal("9750")]  # -2.5% daily DD
    state = risk_manager.update_drawdown_state(equity_curve, current_bar=1)

    assert state.mode == "soft_stop"
    assert state.risk_multiplier == 0.5
    assert state.daily_dd_pct == pytest.approx(-0.025, rel=0.01)


def test_drawdown_state_hard_halt(risk_manager):
    """Test hard halt trigger on rolling DD threshold"""
    # Create declining equity curve (-5% rolling DD)
    equity_curve = [Decimal(f"{10000 - i*30}") for i in range(25)]
    state = risk_manager.update_drawdown_state(equity_curve, current_bar=24)

    assert state.mode == "hard_halt"
    assert state.risk_multiplier == 0.0
    assert state.pause_remaining == 10  # Default cooldown


def test_drawdown_state_cooldown_expiration(risk_manager):
    """Test cooldown expiration after hard halt"""
    # Trigger hard halt
    equity_curve_down = [Decimal(f"{10000 - i*30}") for i in range(25)]
    state1 = risk_manager.update_drawdown_state(equity_curve_down, current_bar=24)
    assert state1.mode == "hard_halt"
    assert state1.pause_remaining == 10

    # Recover equity but still in cooldown
    equity_curve_recover = equity_curve_down + [Decimal("9500")]
    state2 = risk_manager.update_drawdown_state(equity_curve_recover, current_bar=25)
    assert state2.mode == "hard_halt"
    assert state2.pause_remaining == 9  # Decremented

    # Continue cooldown expiration (9 more bars)
    for i in range(9):
        equity_curve_recover.append(Decimal("9500"))
        state = risk_manager.update_drawdown_state(equity_curve_recover, current_bar=26 + i)

    # After 10 bars, should return to normal
    assert state.mode == "normal"
    assert state.pause_remaining == 0


def test_drawdown_state_get_state(risk_manager):
    """Test getting current drawdown state"""
    initial_state = risk_manager.get_drawdown_state()
    assert initial_state.mode == "normal"

    # Trigger soft stop
    equity_curve = [Decimal("10000"), Decimal("9750")]
    risk_manager.update_drawdown_state(equity_curve, current_bar=1)

    current_state = risk_manager.get_drawdown_state()
    assert current_state.mode == "soft_stop"


# =============================================================================
# LEVERAGE TESTS
# =============================================================================


def test_get_max_leverage_default(risk_manager):
    """Test default max leverage for unknown symbol"""
    max_lev = risk_manager.get_max_leverage("UNKNOWN/USD")
    assert max_lev == 5.0


def test_get_max_leverage_symbol_specific():
    """Test per-symbol leverage caps"""
    rm = create_risk_manager(leverage_caps={"BTC/USD": 3.0, "ETH/USD": 2.0})

    btc_lev = rm.get_max_leverage("BTC/USD")
    eth_lev = rm.get_max_leverage("ETH/USD")
    default_lev = rm.get_max_leverage("SOL/USD")

    assert btc_lev == 3.0
    assert eth_lev == 2.0
    assert default_lev == 5.0


# =============================================================================
# METRICS TESTS
# =============================================================================


def test_metrics_tracking(risk_manager, sample_signal):
    """Test metrics tracking"""
    equity = Decimal("10000.00")

    # Size one position
    risk_manager.size_position(sample_signal, equity)

    metrics = risk_manager.get_metrics()
    assert metrics["total_sized"] == 1
    assert metrics["total_rejected"] == 0


def test_metrics_rejection_tracking():
    """Test rejection metrics"""
    # Create fresh instance to avoid cross-test contamination
    rm = RiskManager()

    # Create tiny signal (below min size)
    signal = SignalInput(
        signal_id="test_tiny",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("25000.00"),  # 50% SL
        take_profit=Decimal("60000.00"),
        confidence=Decimal("0.50"),
    )

    equity = Decimal("100.00")
    rm.size_position(signal, equity)

    metrics = rm.get_metrics()
    assert metrics["total_sized"] == 1
    assert metrics["total_rejected"] == 1
    assert metrics["rejected_min_size"] == 1


def test_metrics_reset(risk_manager, sample_signal):
    """Test metrics reset"""
    equity = Decimal("10000.00")
    risk_manager.size_position(sample_signal, equity)

    metrics_before = risk_manager.get_metrics()
    assert metrics_before["total_sized"] == 1

    risk_manager.reset_metrics()

    metrics_after = risk_manager.get_metrics()
    assert metrics_after["total_sized"] == 0


# =============================================================================
# EDGE CASES
# =============================================================================


def test_zero_equity():
    """Test handling of zero equity"""
    rm = RiskManager()
    signal = SignalInput(
        signal_id="test_zero",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("49000.00"),
        take_profit=Decimal("52000.00"),
        confidence=Decimal("0.75"),
    )

    position = rm.size_position(signal, Decimal("0.00"))

    # Should handle gracefully (0 size, 0 risk)
    assert float(position.notional_usd) == 0.0
    assert float(position.expected_risk_usd) == 0.0


def test_insufficient_equity_curve():
    """Test drawdown with insufficient data"""
    rm = RiskManager()
    equity_curve = [Decimal("10000")]  # Only 1 bar

    state = rm.update_drawdown_state(equity_curve, current_bar=0)

    # Should return initial state (not enough data)
    assert state.mode == "normal"
    assert state.daily_dd_pct == 0.0


def test_config_validation_invalid_risk_pct():
    """Test config validation rejects invalid risk percentages"""
    with pytest.raises(Exception):  # Pydantic ValidationError
        RiskConfig(per_trade_risk_pct_max=0.01, per_trade_risk_pct_min=0.02)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


def test_full_workflow_normal_conditions(risk_manager):
    """Test complete workflow in normal conditions"""
    equity = Decimal("10000.00")

    # 1. Create signals
    signals = [
        SignalInput(
            signal_id=f"test_{i}",
            symbol=f"SYM{i}/USD",
            side="long",
            entry_price=Decimal("1000.00"),
            stop_loss=Decimal("980.00"),  # 2% SL
            take_profit=Decimal("1040.00"),
            confidence=Decimal("0.75"),
        )
        for i in range(2)
    ]

    # 2. Size positions
    positions = [risk_manager.size_position(sig, equity) for sig in signals]
    assert all(p.allowed for p in positions)

    # 3. Check portfolio risk
    risk_check = risk_manager.check_portfolio_risk(positions, equity)
    assert risk_check.passed

    # 4. Update drawdown (normal equity curve)
    equity_curve = [Decimal("10000"), Decimal("10100"), Decimal("10200")]
    dd_state = risk_manager.update_drawdown_state(equity_curve, current_bar=2)
    assert dd_state.mode == "normal"


def test_full_workflow_stress_conditions(risk_manager):
    """Test complete workflow under stress (drawdown)"""
    initial_equity = Decimal("10000.00")

    # 1. Trigger drawdown soft stop
    equity_curve = [Decimal("10000"), Decimal("9750")]  # -2.5% daily DD
    dd_state = risk_manager.update_drawdown_state(equity_curve, current_bar=1)
    assert dd_state.mode == "soft_stop"

    # 2. Size position (should be reduced to 0.5x)
    signal = SignalInput(
        signal_id="test_stress",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000.00"),
        stop_loss=Decimal("49000.00"),  # 2% SL
        take_profit=Decimal("52000.00"),
        confidence=Decimal("0.75"),
    )

    current_equity = Decimal("9750.00")
    position = risk_manager.size_position(signal, current_equity)

    assert position.allowed
    # Risk should be ~1% (2% * 0.5)
    assert float(position.risk_pct) == pytest.approx(0.01, rel=0.05)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
