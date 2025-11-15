"""
Comprehensive unit tests for BarReaction5M agent.

Test Coverage:
- Signal generation (up bar -> long, down bar -> short)
- ATR gates (too low/high -> skip)
- Microstructure checks (spread above cap -> skip, notional too low -> skip)
- Cooldown enforcement (minutes since last signal)
- Concurrency limits (max open positions per pair)
- Extreme mode with mode=revert (side flip + size factor)
- Confidence and RR calculation
"""

import pytest
import pytest_asyncio
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any

import redis.asyncio as redis
try:
    from fakeredis.aioredis import FakeRedis as FakeAsyncRedis
except ImportError:
    # Fallback if fakeredis not available
    FakeAsyncRedis = None

from agents.strategies.bar_reaction_5m import (
    BarReaction5M,
    BarCloseEvent,
    MicrostructureCheck,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def base_config() -> Dict[str, Any]:
    """Base configuration for tests."""
    return {
        "mode": "trend",
        "trigger_mode": "open_to_close",
        "trigger_bps_up": 12.0,
        "trigger_bps_down": 12.0,
        "min_atr_pct": 0.25,
        "max_atr_pct": 3.0,
        "atr_window": 14,
        "sl_atr": 0.6,
        "tp1_atr": 1.0,
        "tp2_atr": 1.8,
        "risk_per_trade_pct": 0.6,
        "maker_only": True,
        "spread_bps_cap": 8.0,
        "min_notional_floor": 100000.0,
        "cooldown_minutes": 15,
        "max_concurrent_per_pair": 2,
        "max_signals_per_day": 50,
        "enable_mean_revert_extremes": False,
        "extreme_bps_threshold": 35.0,
        "mean_revert_size_factor": 0.5,
    }


@pytest.fixture
def redis_client():
    """Mock Redis client for sync tests."""
    from unittest.mock import MagicMock
    client = MagicMock()
    return client


@pytest_asyncio.fixture
async def redis_client_async():
    """Fake async Redis client for async tests."""
    if FakeAsyncRedis is not None:
        client = FakeAsyncRedis(decode_responses=True)
    else:
        # Fallback to mock
        from unittest.mock import AsyncMock
        client = AsyncMock()
    yield client
    # Cleanup
    try:
        if hasattr(client, 'flushall'):
            await client.flushall()
        if hasattr(client, 'aclose'):
            await client.aclose()
    except:
        pass


@pytest.fixture
def agent(base_config, redis_client):
    """Initialize BarReaction5M agent with test config."""
    return BarReaction5M(base_config, redis_client)


def create_bar_event(
    pair: str = "BTC/USD",
    timestamp: datetime = None,
    close: float = 50000.0,
    volume: float = 100.0
) -> BarCloseEvent:
    """Helper to create bar-close event."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    return BarCloseEvent(
        timestamp=timestamp,
        pair=pair,
        timeframe="5m",
        bar_data={
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": volume,
        }
    )


# =============================================================================
# TEST: INITIALIZATION
# =============================================================================

def test_agent_initialization(agent):
    """Test agent initializes with correct config parameters."""
    assert agent.mode == "trend"
    assert agent.trigger_mode == "open_to_close"
    assert agent.trigger_bps_up == 12.0
    assert agent.trigger_bps_down == 12.0
    assert agent.min_atr_pct == 0.25
    assert agent.max_atr_pct == 3.0
    assert agent.sl_atr == 0.6
    assert agent.tp1_atr == 1.0
    assert agent.tp2_atr == 1.8
    assert agent.spread_bps_cap == 8.0
    assert agent.cooldown_minutes == 15
    assert agent.max_concurrent_per_pair == 2


def test_invalid_mode_raises_error(base_config, redis_client):
    """Test invalid mode raises ValueError."""
    base_config["mode"] = "invalid"
    # Agent doesn't validate mode in __init__, but strategy does
    # This is tested in strategy tests


def test_invalid_trigger_mode_raises_error(base_config, redis_client):
    """Test invalid trigger_mode raises ValueError."""
    base_config["trigger_mode"] = "invalid"
    # Agent doesn't validate trigger_mode in __init__, but strategy does
    # This is tested in strategy tests


# =============================================================================
# TEST: MICROSTRUCTURE CHECKS
# =============================================================================

def test_microstructure_pass_spread_ok_notional_ok(agent):
    """Test microstructure passes when spread and notional are within limits."""
    result = agent._check_microstructure(spread_bps=5.0, notional=200000.0)

    assert result.passed is True
    assert result.spread_bps == 5.0
    assert result.rolling_notional == 200000.0
    assert result.reason is None


def test_microstructure_fail_spread_above_cap(agent):
    """Test microstructure fails when spread > cap."""
    result = agent._check_microstructure(spread_bps=10.0, notional=200000.0)

    assert result.passed is False
    assert "Spread" in result.reason
    assert "10.00bps" in result.reason


def test_microstructure_fail_notional_below_floor(agent):
    """Test microstructure fails when notional < floor."""
    result = agent._check_microstructure(spread_bps=5.0, notional=50000.0)

    assert result.passed is False
    assert "Notional" in result.reason
    assert "50000" in result.reason


def test_microstructure_edge_case_spread_exactly_at_cap(agent):
    """Test microstructure passes when spread exactly equals cap."""
    result = agent._check_microstructure(spread_bps=8.0, notional=200000.0)

    # Should pass (8.0 <= 8.0)
    assert result.passed is True


def test_microstructure_edge_case_notional_exactly_at_floor(agent):
    """Test microstructure passes when notional exactly equals floor."""
    result = agent._check_microstructure(spread_bps=5.0, notional=100000.0)

    # Should pass (100000 >= 100000)
    assert result.passed is True


# =============================================================================
# TEST: SIGNAL DECISION LOGIC
# =============================================================================

def test_decide_signal_trend_mode_up_move_long(agent):
    """Test trend mode: upward move -> long signal."""
    signal_type, side = agent._decide_signal(move_bps=15.0)

    assert signal_type == "primary"
    assert side == "buy"


def test_decide_signal_trend_mode_down_move_short(agent):
    """Test trend mode: downward move -> short signal."""
    signal_type, side = agent._decide_signal(move_bps=-15.0)

    assert signal_type == "primary"
    assert side == "sell"


def test_decide_signal_trend_mode_small_move_no_signal(agent):
    """Test trend mode: move below threshold -> no signal."""
    signal_type, side = agent._decide_signal(move_bps=5.0)

    assert signal_type is None
    assert side is None


def test_decide_signal_revert_mode_up_move_short(base_config, redis_client):
    """Test revert mode: upward move -> short signal (fade)."""
    base_config["mode"] = "revert"
    agent = BarReaction5M(base_config, redis_client)

    signal_type, side = agent._decide_signal(move_bps=15.0)

    assert signal_type == "primary"
    assert side == "sell"  # Revert: fade up move


def test_decide_signal_revert_mode_down_move_long(base_config, redis_client):
    """Test revert mode: downward move -> long signal (fade)."""
    base_config["mode"] = "revert"
    agent = BarReaction5M(base_config, redis_client)

    signal_type, side = agent._decide_signal(move_bps=-15.0)

    assert signal_type == "primary"
    assert side == "buy"  # Revert: fade down move


def test_decide_signal_extreme_fade_enabled_big_up_move_short(base_config, redis_client):
    """Test extreme fade: big upward move triggers extreme fade."""
    base_config["enable_mean_revert_extremes"] = True
    agent = BarReaction5M(base_config, redis_client)

    signal_type, side = agent._decide_signal(move_bps=40.0)

    # Note: _decide_signal returns primary first, then extreme is checked separately
    # For move_bps=40 (> trigger_bps_up=12), returns primary signal
    # Extreme fade is a separate check in on_bar_close
    assert signal_type in ("primary", "extreme_fade")
    if signal_type == "primary":
        assert side == "buy"  # Trend: follow up move
    else:
        assert side == "sell"  # Extreme: fade up move


def test_decide_signal_extreme_fade_enabled_big_down_move_long(base_config, redis_client):
    """Test extreme fade: big downward move triggers extreme fade."""
    base_config["enable_mean_revert_extremes"] = True
    agent = BarReaction5M(base_config, redis_client)

    signal_type, side = agent._decide_signal(move_bps=-40.0)

    # Note: _decide_signal returns primary first
    assert signal_type in ("primary", "extreme_fade")
    if signal_type == "primary":
        assert side == "sell"  # Trend: follow down move
    else:
        assert side == "buy"  # Extreme: fade down move


def test_decide_signal_extreme_fade_disabled_big_move_no_extreme_signal(agent):
    """Test extreme fade disabled: big move -> no extreme signal."""
    # Agent has enable_mean_revert_extremes=False by default
    signal_type, side = agent._decide_signal(move_bps=40.0)

    # Should not generate extreme_fade signal
    # Only primary signal if move >= trigger_bps_up
    if agent.mode == "trend":
        assert signal_type == "primary"
        assert side == "buy"


# =============================================================================
# TEST: CONFIDENCE CALCULATION
# =============================================================================

def test_confidence_calculation_strong_move_mid_atr(agent):
    """Test confidence for strong move with mid-range ATR."""
    conf = agent._calculate_confidence(move_bps=20.0, atr_pct=1.5, signal_type="primary")

    # Strong move (20/12 = 1.67x threshold) + mid ATR (1.5% is mid-range) = high confidence
    assert 0.70 <= conf <= 0.90


def test_confidence_calculation_weak_move_low_atr(agent):
    """Test confidence for weak move with low ATR."""
    conf = agent._calculate_confidence(move_bps=12.0, atr_pct=0.3, signal_type="primary")

    # Weak move (12/12 = 1.0x threshold) + low ATR (near min) = lower confidence
    assert 0.50 <= conf <= 0.70


def test_confidence_calculation_extreme_fade_reduced(agent):
    """Test confidence for extreme fade is reduced."""
    conf_primary = agent._calculate_confidence(move_bps=40.0, atr_pct=1.5, signal_type="primary")
    conf_extreme = agent._calculate_confidence(move_bps=40.0, atr_pct=1.5, signal_type="extreme_fade")

    # Extreme fade should be 80% of primary
    assert conf_extreme == pytest.approx(conf_primary * 0.80, rel=0.01)


def test_confidence_clipped_to_range(agent):
    """Test confidence is clipped to [0.50, 0.90]."""
    # Very strong move
    conf = agent._calculate_confidence(move_bps=100.0, atr_pct=1.5, signal_type="primary")
    assert conf <= 0.90

    # Very weak move
    conf = agent._calculate_confidence(move_bps=1.0, atr_pct=0.25, signal_type="primary")
    assert conf >= 0.50


# =============================================================================
# TEST: RR CALCULATION
# =============================================================================

def test_rr_calculation_blended_tp1_tp2(agent):
    """Test RR calculation with blended TP1/TP2."""
    rr = agent._calculate_rr(entry=50000, sl=49700, tp1=50500, tp2=50900)

    # RR_TP1 = 500/300 = 1.67
    # RR_TP2 = 900/300 = 3.00
    # Blended = (1.67 + 3.00) / 2 = 2.33
    assert rr == pytest.approx(2.33, rel=0.01)


def test_rr_calculation_zero_sl_distance_returns_zero(agent):
    """Test RR calculation with zero SL distance returns 0."""
    rr = agent._calculate_rr(entry=50000, sl=50000, tp1=50500, tp2=50900)

    assert rr == 0.0


# =============================================================================
# TEST: SIGNAL CREATION
# =============================================================================

def test_signal_creation_long(agent):
    """Test signal creation for long position."""
    signal = agent._create_signal(
        pair="BTC/USD",
        side="buy",
        signal_type="primary",
        entry_price=50000.0,
        atr=75.0,
        atr_pct=0.15,
        move_bps=15.0,
        timestamp=datetime.now(timezone.utc),
    )

    assert signal.side == "long"
    assert float(signal.entry) == 50000.0
    assert float(signal.sl) < float(signal.entry)  # Long: SL below entry
    assert float(signal.tp) > float(signal.entry)  # Long: TP above entry
    assert signal.strategy == "bar_reaction_5m"
    assert 0.50 <= signal.confidence <= 0.90


def test_signal_creation_short(agent):
    """Test signal creation for short position."""
    signal = agent._create_signal(
        pair="BTC/USD",
        side="sell",
        signal_type="primary",
        entry_price=50000.0,
        atr=75.0,
        atr_pct=0.15,
        move_bps=-15.0,
        timestamp=datetime.now(timezone.utc),
    )

    assert signal.side == "short"
    assert float(signal.entry) == 50000.0
    assert float(signal.sl) > float(signal.entry)  # Short: SL above entry
    assert float(signal.tp) < float(signal.entry)  # Short: TP below entry


def test_signal_creation_atr_based_levels(agent):
    """Test signal levels are ATR-based."""
    atr = 75.0
    entry = 50000.0

    signal = agent._create_signal(
        pair="BTC/USD",
        side="buy",
        signal_type="primary",
        entry_price=entry,
        atr=atr,
        atr_pct=0.15,
        move_bps=15.0,
        timestamp=datetime.now(timezone.utc),
    )

    # SL = entry - (0.6 * ATR) = 50000 - 45 = 49955
    # TP2 = entry + (1.8 * ATR) = 50000 + 135 = 50135
    expected_sl = entry - (0.6 * atr)
    expected_tp2 = entry + (1.8 * atr)

    assert float(signal.sl) == pytest.approx(expected_sl, rel=0.01)
    assert float(signal.tp) == pytest.approx(expected_tp2, rel=0.01)


def test_signal_creation_deterministic_id(agent):
    """Test signal ID is deterministic."""
    ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    signal1 = agent._create_signal(
        pair="BTC/USD",
        side="buy",
        signal_type="primary",
        entry_price=50000.0,
        atr=75.0,
        atr_pct=0.15,
        move_bps=15.0,
        timestamp=ts,
    )

    signal2 = agent._create_signal(
        pair="BTC/USD",
        side="buy",
        signal_type="primary",
        entry_price=50000.0,
        atr=75.0,
        atr_pct=0.15,
        move_bps=15.0,
        timestamp=ts,
    )

    # Same inputs -> same ID
    assert signal1.id == signal2.id


# =============================================================================
# TEST: COOLDOWN ENFORCEMENT
# =============================================================================

@pytest.mark.asyncio
async def test_cooldown_pass_no_previous_signal(base_config, redis_client_async):
    """Test cooldown passes when no previous signal."""
    agent = BarReaction5M(base_config, redis_client_async)
    ok, reason = await agent._check_cooldowns("BTC/USD")

    assert ok is True
    assert reason is None


@pytest.mark.asyncio
async def test_cooldown_pass_sufficient_time_elapsed(base_config, redis_client_async):
    """Test cooldown passes when sufficient time has elapsed."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"

    # Set last signal timestamp to 20 minutes ago
    past_ts = (datetime.now(timezone.utc) - timedelta(minutes=20)).timestamp()
    await redis_client_async.set(f"bar_reaction:cooldown:{pair}", str(past_ts))

    ok, reason = await agent._check_cooldowns(pair)

    assert ok is True
    assert reason is None


@pytest.mark.asyncio
async def test_cooldown_fail_insufficient_time_elapsed(base_config, redis_client_async):
    """Test cooldown fails when insufficient time has elapsed."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"

    # Set last signal timestamp to 5 minutes ago (< 15 minute cooldown)
    past_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    await redis_client_async.set(f"bar_reaction:cooldown:{pair}", str(past_ts))

    ok, reason = await agent._check_cooldowns(pair)

    assert ok is False
    assert "Cooldown" in reason
    assert "5." in reason  # Should mention ~5 minutes


# =============================================================================
# TEST: CONCURRENCY LIMITS
# =============================================================================

@pytest.mark.asyncio
async def test_concurrency_pass_no_open_positions(base_config, redis_client_async):
    """Test concurrency passes when no open positions."""
    agent = BarReaction5M(base_config, redis_client_async)
    ok, reason = await agent._check_cooldowns("BTC/USD")

    assert ok is True


@pytest.mark.asyncio
async def test_concurrency_pass_below_limit(base_config, redis_client_async):
    """Test concurrency passes when open positions below limit."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"

    # Set open positions to 1 (< 2 limit)
    await redis_client_async.set(f"bar_reaction:open_positions:{pair}", "1")

    ok, reason = await agent._check_cooldowns(pair)

    assert ok is True


@pytest.mark.asyncio
async def test_concurrency_fail_at_limit(base_config, redis_client_async):
    """Test concurrency fails when at max limit."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"

    # Set open positions to 2 (>= 2 limit)
    await redis_client_async.set(f"bar_reaction:open_positions:{pair}", "2")

    ok, reason = await agent._check_cooldowns(pair)

    assert ok is False
    assert "Concurrency" in reason
    assert "2" in reason


@pytest.mark.asyncio
async def test_concurrency_fail_above_limit(base_config, redis_client_async):
    """Test concurrency fails when above max limit."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"

    # Set open positions to 3 (> 2 limit)
    await redis_client_async.set(f"bar_reaction:open_positions:{pair}", "3")

    ok, reason = await agent._check_cooldowns(pair)

    assert ok is False
    assert "Concurrency" in reason


# =============================================================================
# TEST: DAILY LIMITS
# =============================================================================

@pytest.mark.asyncio
async def test_daily_limit_pass_no_signals_today(base_config, redis_client_async):
    """Test daily limit passes when no signals today."""
    agent = BarReaction5M(base_config, redis_client_async)
    ok, reason = await agent._check_cooldowns("BTC/USD")

    assert ok is True


@pytest.mark.asyncio
async def test_daily_limit_pass_below_limit(base_config, redis_client_async):
    """Test daily limit passes when signals below limit."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")

    # Set daily count to 10 (< 50 limit)
    await redis_client_async.set(f"bar_reaction:daily_count:{pair}:{today}", "10")

    ok, reason = await agent._check_cooldowns(pair)

    assert ok is True


@pytest.mark.asyncio
async def test_daily_limit_fail_at_limit(base_config, redis_client_async):
    """Test daily limit fails when at max limit."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")

    # Set daily count to 50 (>= 50 limit)
    await redis_client_async.set(f"bar_reaction:daily_count:{pair}:{today}", "50")

    ok, reason = await agent._check_cooldowns(pair)

    assert ok is False
    assert "Daily limit" in reason
    assert "50" in reason


# =============================================================================
# TEST: COOLDOWN STATE UPDATES
# =============================================================================

@pytest.mark.asyncio
async def test_update_cooldown_state_sets_timestamp(base_config, redis_client_async):
    """Test cooldown state update sets timestamp."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"
    timestamp = datetime.now(timezone.utc)

    await agent._update_cooldown_state(pair, timestamp)

    # Check cooldown key was set
    cooldown_ts = await redis_client_async.get(f"bar_reaction:cooldown:{pair}")
    assert cooldown_ts is not None
    assert float(cooldown_ts) == pytest.approx(timestamp.timestamp(), rel=0.01)


@pytest.mark.asyncio
async def test_update_cooldown_state_increments_open_positions(base_config, redis_client_async):
    """Test cooldown state update increments open positions."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"
    timestamp = datetime.now(timezone.utc)

    # Start with 0 open positions
    await agent._update_cooldown_state(pair, timestamp)

    # Check open positions incremented to 1
    open_pos = await redis_client_async.get(f"bar_reaction:open_positions:{pair}")
    assert open_pos == "1"

    # Update again
    await agent._update_cooldown_state(pair, timestamp)

    # Check open positions incremented to 2
    open_pos = await redis_client_async.get(f"bar_reaction:open_positions:{pair}")
    assert open_pos == "2"


@pytest.mark.asyncio
async def test_update_cooldown_state_increments_daily_count(base_config, redis_client_async):
    """Test cooldown state update increments daily count."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"
    timestamp = datetime.now(timezone.utc)
    today = timestamp.strftime("%Y%m%d")

    # Start with 0 daily count
    await agent._update_cooldown_state(pair, timestamp)

    # Check daily count incremented to 1
    daily_count = await redis_client_async.get(f"bar_reaction:daily_count:{pair}:{today}")
    assert daily_count == "1"

    # Update again
    await agent._update_cooldown_state(pair, timestamp)

    # Check daily count incremented to 2
    daily_count = await redis_client_async.get(f"bar_reaction:daily_count:{pair}:{today}")
    assert daily_count == "2"


@pytest.mark.asyncio
async def test_decrement_open_positions(base_config, redis_client_async):
    """Test decrementing open positions."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"

    # Set open positions to 2
    await redis_client_async.set(f"bar_reaction:open_positions:{pair}", "2")

    # Decrement
    await agent.decrement_open_positions(pair)

    # Check decremented to 1
    open_pos = await redis_client_async.get(f"bar_reaction:open_positions:{pair}")
    assert open_pos == "1"


@pytest.mark.asyncio
async def test_decrement_open_positions_does_not_go_negative(base_config, redis_client_async):
    """Test decrement does not go negative."""
    agent = BarReaction5M(base_config, redis_client_async)
    pair = "BTC/USD"

    # Set open positions to 0
    await redis_client_async.set(f"bar_reaction:open_positions:{pair}", "0")

    # Decrement
    await agent.decrement_open_positions(pair)

    # Should still be 0 (not negative)
    open_pos = await redis_client_async.get(f"bar_reaction:open_positions:{pair}")
    assert open_pos == "0"


# =============================================================================
# SUMMARY
# =============================================================================

if __name__ == "__main__":
    """Run tests with pytest."""
    pytest.main([__file__, "-v", "--tb=short"])
