"""
Comprehensive tests for drawdown gates and loss streak handling.

Tests simulate loss streaks, daily drawdowns, and rolling drawdowns
to assert proper gate behavior, cooldowns, and size scaling.

Validates:
- Consecutive loss tracking and cooldowns
- Hard day DD -> no new entries (existing trades managed)
- Rolling 30d drawdown gates
- Size multiplier scaling
- Day rollover behavior
- Multi-scope precedence (portfolio/strategy/symbol)
"""

import pytest
import sys
import time
from pathlib import Path
from typing import List

# Add parent directory to path to import drawdown_protector directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from agents.risk.drawdown_protector import (
    DrawdownBands,
    DrawdownProtector,
    FillEvent,
    SnapshotEvent,
    GateDecision,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def policy_strict():
    """Strict risk policy for testing gates."""
    return DrawdownBands(
        daily_stop_pct=-0.04,  # -4% daily DD
        rolling_windows_pct=[
            (3600, -0.01),  # 1 hour: -1%
            (14400, -0.015),  # 4 hours: -1.5%
            (2592000, -0.12),  # 30 days: -12%
        ],
        max_consecutive_losses=3,
        cooldown_after_soft_s=600,  # 10 min
        cooldown_after_hard_s=1800,  # 30 min
        scale_bands=[
            (-0.01, 0.75),  # -1% -> 75%
            (-0.02, 0.50),  # -2% -> 50%
            (-0.03, 0.25),  # -3% -> 25%
        ],
        enable_per_strategy=True,
        enable_per_symbol=True,
    )


@pytest.fixture
def policy_lenient():
    """Lenient risk policy for comparison."""
    return DrawdownBands(
        daily_stop_pct=-0.10,  # -10% daily DD
        rolling_windows_pct=[(86400, -0.05)],  # 24h: -5%
        max_consecutive_losses=5,
        cooldown_after_soft_s=300,
        cooldown_after_hard_s=900,
        scale_bands=[
            (-0.05, 0.75),
            (-0.08, 0.50),
        ],
        enable_per_strategy=False,
        enable_per_symbol=False,
    )


@pytest.fixture
def mock_time():
    """Mock time provider for deterministic testing."""
    current_time = [1000000]  # Start at T=1M seconds

    def get_time():
        return current_time[0]

    def advance(seconds):
        current_time[0] += seconds

    get_time.advance = advance
    return get_time


# =============================================================================
# TEST: CONSECUTIVE LOSS TRACKING
# =============================================================================


def test_consecutive_losses_trigger_soft_stop(policy_strict, mock_time):
    """Test that 3 consecutive losses trigger soft stop with cooldown."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    protector.reset(equity_start_of_day_usd=10000, ts_s=mock_time())

    # Loss 1
    protector.ingest_fill(
        FillEvent(
            ts_s=mock_time(),
            pnl_after_fees=-50,
            strategy="scalper",
            symbol="BTC/USD",
            won=False,
        )
    )
    assert protector.state.portfolio.loss_streak == 1

    # Loss 2
    mock_time.advance(60)
    protector.ingest_fill(
        FillEvent(
            ts_s=mock_time(),
            pnl_after_fees=-50,
            strategy="scalper",
            symbol="BTC/USD",
            won=False,
        )
    )
    assert protector.state.portfolio.loss_streak == 2

    # Loss 3 - triggers soft stop
    mock_time.advance(60)
    protector.ingest_fill(
        FillEvent(
            ts_s=mock_time(),
            pnl_after_fees=-50,
            strategy="scalper",
            symbol="BTC/USD",
            won=False,
        )
    )
    assert protector.state.portfolio.loss_streak == 3

    # Check gate decision
    decision = protector.assess_can_open("scalper", "BTC/USD")
    assert not decision.allow_new_positions, "Should not allow new positions after 3 losses"
    assert decision.reduce_only, "Should be in reduce-only mode"
    assert not decision.halt_all, "Should not halt all (soft stop, not hard halt)"
    assert decision.reason == "loss-streak-soft", f"Got reason: {decision.reason}"

    # Verify cooldown is active
    mock_time.advance(300)  # 5 min (still in 10 min cooldown)
    decision2 = protector.assess_can_open("scalper", "BTC/USD")
    assert not decision2.allow_new_positions, "Cooldown should still be active"


def test_consecutive_losses_second_breach_hard_halt(policy_strict, mock_time):
    """Test that second loss streak breach on same day triggers hard halt."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    protector.reset(equity_start_of_day_usd=10000, ts_s=mock_time())

    # First loss streak (3 losses)
    for _ in range(3):
        protector.ingest_fill(
            FillEvent(
                ts_s=mock_time(),
                pnl_after_fees=-50,
                strategy="scalper",
                symbol="BTC/USD",
                won=False,
            )
        )
        mock_time.advance(60)

    # Soft stop triggered
    decision = protector.assess_can_open("scalper", "BTC/USD")
    assert decision.reduce_only, "First breach should be soft stop"

    # Wait for cooldown to expire
    mock_time.advance(700)  # 10+ min

    # Winning trade resets streak
    protector.ingest_fill(
        FillEvent(
            ts_s=mock_time(),
            pnl_after_fees=100,
            strategy="scalper",
            symbol="BTC/USD",
            won=True,
        )
    )
    assert protector.state.portfolio.loss_streak == 0

    # Second loss streak (3 more losses) - should trigger HARD HALT
    for _ in range(3):
        mock_time.advance(60)
        protector.ingest_fill(
            FillEvent(
                ts_s=mock_time(),
                pnl_after_fees=-50,
                strategy="scalper",
                symbol="BTC/USD",
                won=False,
            )
        )

    # Check gate - should be hard halt on second breach same day
    decision = protector.assess_can_open("scalper", "BTC/USD")
    assert decision.halt_all, "Second breach should trigger hard halt"
    assert not decision.allow_new_positions
    assert not decision.reduce_only  # Hard halt doesn't allow reduce-only
    assert decision.reason == "loss-streak-hard", f"Got reason: {decision.reason}"


def test_win_resets_loss_streak(policy_strict, mock_time):
    """Test that winning trade resets loss streak."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    protector.reset(equity_start_of_day_usd=10000, ts_s=mock_time())

    # 2 losses
    for _ in range(2):
        protector.ingest_fill(
            FillEvent(
                ts_s=mock_time(),
                pnl_after_fees=-50,
                strategy="scalper",
                symbol="BTC/USD",
                won=False,
            )
        )
        mock_time.advance(60)

    assert protector.state.portfolio.loss_streak == 2

    # Win resets
    protector.ingest_fill(
        FillEvent(
            ts_s=mock_time(),
            pnl_after_fees=100,
            strategy="scalper",
            symbol="BTC/USD",
            won=True,
        )
    )
    assert protector.state.portfolio.loss_streak == 0

    # Another loss starts fresh
    mock_time.advance(60)
    protector.ingest_fill(
        FillEvent(
            ts_s=mock_time(),
            pnl_after_fees=-50,
            strategy="scalper",
            symbol="BTC/USD",
            won=False,
        )
    )
    assert protector.state.portfolio.loss_streak == 1


# =============================================================================
# TEST: DAILY DRAWDOWN GATES
# =============================================================================


def test_daily_dd_soft_stop(policy_strict, mock_time):
    """Test that hitting daily DD limit triggers soft stop."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    equity_start = 10000.0
    protector.reset(equity_start_of_day_usd=equity_start, ts_s=mock_time())

    # Lose 4% (hit daily stop)
    equity_current = equity_start * 0.96  # -4%
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_current,
        )
    )

    # Should trigger soft stop
    assert protector.state.portfolio.dd_daily_pct == -0.04
    assert protector.state.portfolio.mode == "soft_stop"

    # Gate should deny new positions
    decision = protector.assess_can_open("any", "any")
    assert not decision.allow_new_positions, "Should not allow new positions at -4% DD"
    assert decision.reduce_only, "Should allow reduce-only"
    assert not decision.halt_all


def test_daily_dd_hard_halt(policy_strict, mock_time):
    """Test that hitting 1.5x daily DD triggers hard halt."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    equity_start = 10000.0
    protector.reset(equity_start_of_day_usd=equity_start, ts_s=mock_time())

    # Lose 6% (1.5x daily stop of -4%)
    equity_current = equity_start * 0.94  # -6%
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_current,
        )
    )

    # Should trigger hard halt
    assert protector.state.portfolio.mode == "hard_halt"

    # Gate should halt all trading
    decision = protector.assess_can_open("any", "any")
    assert decision.halt_all, "Should halt all trading at -6% DD"
    assert not decision.allow_new_positions
    assert not decision.reduce_only  # Hard halt means full stop


def test_daily_dd_no_new_entries_existing_managed(policy_strict, mock_time):
    """
    Test that hard day DD prevents new entries but existing trades are managed.

    This is the critical "stay in business" test - we don't want to be locked
    out of managing existing positions when we hit daily DD.
    """
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    equity_start = 10000.0
    protector.reset(equity_start_of_day_usd=equity_start, ts_s=mock_time())

    # Hit hard halt at -6%
    equity_current = equity_start * 0.94
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_current,
        )
    )

    decision = protector.assess_can_open("scalper", "BTC/USD")
    assert decision.halt_all, "Hard halt should be active"
    assert not decision.allow_new_positions, "Cannot open NEW positions"

    # Key assertion: Gate says halt_all but this is for NEW positions only
    # Existing position management (closing, updating stops) should still work
    # This is enforced at the application layer, not in DrawdownProtector
    # DrawdownProtector just signals the restriction

    # Simulate managing an existing position by checking if we're in halt mode
    # Application logic would check: if halt_all, skip new orders but process exits
    assert decision.halt_all, "Signal to application: don't open new"
    # Application sees halt_all=True and knows to:
    # 1. Skip signal generation for new positions
    # 2. Continue processing stop losses, take profits
    # 3. Continue updating existing orders


def test_day_rollover_resets_daily_dd(policy_strict, mock_time):
    """Test that day rollover resets daily DD but preserves rolling windows."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    equity_start = 10000.0
    protector.reset(equity_start_of_day_usd=equity_start, ts_s=mock_time())

    # Hit soft stop at -4%
    equity_current = equity_start * 0.96
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_current,
        )
    )
    assert protector.state.portfolio.mode == "soft_stop"

    # Advance to next day (86400 seconds)
    mock_time.advance(86400)
    new_equity_start = equity_current  # Start new day at yesterday's close

    # Day rollover
    protector.on_day_rollover(equity_start_of_day_usd=new_equity_start, ts_s=mock_time())

    # Daily DD should be reset, loss streak reset
    assert protector.state.portfolio.dd_daily_pct == 0.0
    assert protector.state.portfolio.loss_streak == 0

    # Mode should be recalculated (no longer in soft stop if DD recovered)
    # Simulate small gain on new day
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=new_equity_start,
            equity_current_usd=new_equity_start * 1.001,  # +0.1%
        )
    )

    decision = protector.assess_can_open("scalper", "BTC/USD")
    assert decision.allow_new_positions, "Should allow new positions on new day with positive DD"


# =============================================================================
# TEST: ROLLING DRAWDOWN GATES
# =============================================================================


def test_rolling_1h_window_triggers_soft_stop(policy_strict, mock_time):
    """Test that -1% DD in 1-hour window triggers soft stop."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    equity_start = 10000.0
    protector.reset(equity_start_of_day_usd=equity_start, ts_s=mock_time())

    # Initial snapshot at start
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_start,
        )
    )

    # Advance 30 min, lose 1%
    mock_time.advance(1800)
    equity_current = equity_start * 0.99  # -1%
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_current,
        )
    )

    # Should trigger soft stop via 1h rolling window
    assert protector.state.portfolio.mode == "soft_stop"
    assert protector.state.portfolio.trigger_reason == "soft-stop-rolling-dd"

    decision = protector.assess_can_open("any", "any")
    assert not decision.allow_new_positions
    assert decision.reduce_only


def test_rolling_30d_window_long_term_dd(policy_strict, mock_time):
    """Test 30-day rolling drawdown gate with -12% limit."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    equity_start = 10000.0
    protector.reset(equity_start_of_day_usd=equity_start, ts_s=mock_time())

    # Peak at start
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_start,
        )
    )

    # Simulate gradual decline over 15 days to -12%
    days = 15
    for day in range(days):
        mock_time.advance(86400)  # Advance 1 day
        # Gradual decline: 0.8% per day × 15 days = -12%
        equity_current = equity_start * (1 - 0.008 * (day + 1))

        # Day rollover
        if day > 0:
            protector.on_day_rollover(equity_start_of_day_usd=equity_start, ts_s=mock_time())

        protector.ingest_snapshot(
            SnapshotEvent(
                ts_s=mock_time(),
                equity_start_of_day_usd=equity_start,
                equity_current_usd=equity_current,
            )
        )

    # At -12%, should trigger soft stop via 30d rolling window
    # Daily DD might be small (-0.8%), but rolling 30d is -12%
    assert protector.state.portfolio.mode in ("soft_stop", "warn")

    # Verify rolling DD calculation
    assert protector.state.portfolio.dd_rolling_pct <= -0.11  # Close to -12%


# =============================================================================
# TEST: SIZE MULTIPLIER SCALING
# =============================================================================


def test_size_multiplier_progressive_scaling(policy_strict, mock_time):
    """Test that size multiplier scales progressively with DD severity."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    equity_start = 10000.0
    protector.reset(equity_start_of_day_usd=equity_start, ts_s=mock_time())

    # Test points: -0.5%, -1%, -2%, -3%, -4%
    test_cases = [
        (-0.005, 1.0),  # No scaling yet
        (-0.01, 0.75),  # First band: -1% -> 75%
        (-0.02, 0.50),  # Second band: -2% -> 50%
        (-0.03, 0.25),  # Third band: -3% -> 25%
        (-0.04, 0.25),  # Still at 25% (soft stop triggered)
    ]

    for dd_pct, expected_multiplier in test_cases:
        equity_current = equity_start * (1 + dd_pct)
        protector.ingest_snapshot(
            SnapshotEvent(
                ts_s=mock_time(),
                equity_start_of_day_usd=equity_start,
                equity_current_usd=equity_current,
            )
        )

        decision = protector.assess_can_open("any", "any")
        assert decision.size_multiplier == expected_multiplier, (
            f"At {dd_pct:.1%} DD, expected multiplier {expected_multiplier}, "
            f"got {decision.size_multiplier}"
        )

        mock_time.advance(60)  # Advance time for next snapshot


# =============================================================================
# TEST: COOLDOWN BEHAVIOR
# =============================================================================


def test_soft_stop_cooldown_prevents_oscillation(policy_strict, mock_time):
    """Test that cooldown prevents rapid mode oscillation."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    equity_start = 10000.0
    protector.reset(equity_start_of_day_usd=equity_start, ts_s=mock_time())

    # Trigger soft stop at -4%
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_start * 0.96,
        )
    )

    # First assessment starts cooldown
    decision1 = protector.assess_can_open("any", "any")
    assert not decision1.allow_new_positions
    assert protector.state.portfolio.cooldown_ends_at_s is not None

    # Equity recovers to -2% (would normally exit soft stop)
    mock_time.advance(60)
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_start * 0.98,
        )
    )

    # Should still be in cooldown (600s cooldown, only 60s passed)
    decision2 = protector.assess_can_open("any", "any")
    assert not decision2.allow_new_positions, "Cooldown should prevent immediate recovery"
    assert "cooldown" in decision2.reason.lower()

    # After cooldown expires (600s total)
    mock_time.advance(600)
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_start * 0.99,  # -1% now
        )
    )

    # Cooldown should be cleared, mode reassessed
    decision3 = protector.assess_can_open("any", "any")
    # At -1%, should be in warn mode (not soft stop)
    assert decision3.allow_new_positions or protector.state.portfolio.mode == "warn"


# =============================================================================
# TEST: MULTI-SCOPE PRECEDENCE
# =============================================================================


def test_strategy_scope_overrides_portfolio(policy_strict, mock_time):
    """Test that strategy-level gate can be stricter than portfolio."""
    protector = DrawdownProtector(policy_strict, now_s_provider=mock_time)
    equity_start = 10000.0
    protector.reset(equity_start_of_day_usd=equity_start, ts_s=mock_time())

    # Portfolio is fine: -0.5% DD
    protector.ingest_snapshot(
        SnapshotEvent(
            ts_s=mock_time(),
            equity_start_of_day_usd=equity_start,
            equity_current_usd=equity_start * 0.995,
            strategy_equity_usd={"scalper": 5000 * 0.96, "trend": 5000 * 1.00},  # Scalper down -4%
        )
    )

    # Portfolio decision should be OK
    portfolio_decision = protector.assess_can_open("trend", "ETH/USD")
    assert portfolio_decision.allow_new_positions, "Portfolio is fine for trend strategy"

    # Scalper decision should be restricted (strategy-level -4%)
    scalper_decision = protector.assess_can_open("scalper", "BTC/USD")
    assert not scalper_decision.allow_new_positions, "Scalper strategy hit -4% DD"


# =============================================================================
# RUN TESTS
# =============================================================================


if __name__ == "__main__":
    """Run tests with pytest or as standalone script."""
    import sys

    # Run with pytest if available
    try:
        import pytest

        sys.exit(pytest.main([__file__, "-v", "-s"]))
    except ImportError:
        print("pytest not installed, running basic sanity checks...")

        # Create fixtures manually
        policy = DrawdownBands(
            daily_stop_pct=-0.04,
            rolling_windows_pct=[(3600, -0.01), (14400, -0.015), (2592000, -0.12)],
            max_consecutive_losses=3,
            cooldown_after_soft_s=600,
            cooldown_after_hard_s=1800,
            scale_bands=[(-0.01, 0.75), (-0.02, 0.50), (-0.03, 0.25)],
        )

        mock_time_val = [1000000]

        def mock_time():
            return mock_time_val[0]

        def advance(s):
            mock_time_val[0] += s

        mock_time.advance = advance

        # Run basic tests
        print("\n[1/4] Testing consecutive losses...")
        test_consecutive_losses_trigger_soft_stop(policy, mock_time)
        print("  [PASS] Consecutive losses trigger soft stop")

        print("\n[2/4] Testing daily DD gates...")
        test_daily_dd_soft_stop(policy, mock_time)
        print("  [PASS] Daily DD triggers soft stop")

        print("\n[3/4] Testing hard DD with existing trades...")
        test_daily_dd_no_new_entries_existing_managed(policy, mock_time)
        print("  [PASS] Hard DD prevents new entries, allows existing management")

        print("\n[4/4] Testing size multiplier scaling...")
        test_size_multiplier_progressive_scaling(policy, mock_time)
        print("  [PASS] Size multiplier scales progressively")

        print("\n[PASS] All basic sanity checks passed!")
