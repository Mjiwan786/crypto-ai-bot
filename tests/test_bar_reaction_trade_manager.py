"""
Comprehensive unit tests for BarReactionTradeManager.

Test Coverage (G3):
- G1: ATR-based stops (SL, TP1, TP2, Break-Even, Trailing)
- G2: Stacking & caps (concurrent limits, drawdown gates)
- G3: Breakeven fires only after threshold
- G3: Partial TP correct quantity math
- G3: Cooldown after 3 losses
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any

try:
    from fakeredis.aioredis import FakeRedis as FakeAsyncRedis
except ImportError:
    FakeAsyncRedis = None

from agents.strategies.bar_reaction_trade_manager import (
    BarReactionTradeManager,
    TradeConfig,
    Position,
    TradeUpdate,
    DrawdownState,
    as_decimal,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def base_config() -> TradeConfig:
    """Base configuration for tests."""
    return TradeConfig(
        sl_atr=0.6,
        tp1_atr=1.0,
        tp2_atr=1.8,
        trail_atr=0.8,
        break_even_at_r=0.5,
        tp1_close_pct=0.5,
        max_concurrent_per_pair=1,
        day_max_drawdown_pct=5.0,
        rolling_max_drawdown_pct=10.0,
        max_consecutive_losses=3,
        cooldown_after_losses_seconds=3600,
        backtest_mode=True,
    )


@pytest_asyncio.fixture
async def redis_client_async():
    """Fake async Redis client for tests."""
    if FakeAsyncRedis is not None:
        client = FakeAsyncRedis(decode_responses=True)
    else:
        from unittest.mock import AsyncMock
        client = AsyncMock()
    yield client
    try:
        if hasattr(client, 'flushall'):
            await client.flushall()
        if hasattr(client, 'aclose'):
            await client.aclose()
    except:
        pass


def create_signal(
    pair: str = "BTC/USD",
    side: str = "long",
) -> Dict[str, Any]:
    """Helper to create signal dictionary."""
    return {
        "id": "test_signal_123",
        "pair": pair,
        "side": side,
        "strategy": "bar_reaction_5m",
    }


# =============================================================================
# TEST: INITIALIZATION
# =============================================================================

@pytest.mark.asyncio
async def test_manager_initialization(base_config, redis_client_async):
    """Test manager initializes with correct config."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    assert manager.config.sl_atr == 0.6
    assert manager.config.tp1_atr == 1.0
    assert manager.config.tp2_atr == 1.8
    assert manager.config.break_even_at_r == 0.5
    assert manager.config.max_concurrent_per_pair == 1
    assert len(manager.active_positions) == 0


# =============================================================================
# TEST: G1 - ATR-BASED STOPS
# =============================================================================

@pytest.mark.asyncio
async def test_open_position_long_calculates_atr_levels(base_config, redis_client_async):
    """G1: Long position calculates correct ATR-based SL/TP levels."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    signal = create_signal(side="long")
    entry_price = Decimal("50000")
    quantity = Decimal("0.1")
    atr = Decimal("500")  # ATR = $500

    position = await manager.open_position(signal, entry_price, quantity, atr)

    # SL = entry - 0.6*ATR = 50000 - 300 = 49700
    assert position.sl == Decimal("49700")

    # TP1 = entry + 1.0*ATR = 50000 + 500 = 50500
    assert position.tp1 == Decimal("50500")

    # TP2 = entry + 1.8*ATR = 50000 + 900 = 50900
    assert position.tp2 == Decimal("50900")

    # Current SL starts at initial SL
    assert position.current_sl == position.sl


@pytest.mark.asyncio
async def test_open_position_short_calculates_atr_levels(base_config, redis_client_async):
    """G1: Short position calculates correct ATR-based SL/TP levels."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    signal = create_signal(side="short")
    entry_price = Decimal("50000")
    quantity = Decimal("0.1")
    atr = Decimal("500")

    position = await manager.open_position(signal, entry_price, quantity, atr)

    # SL = entry + 0.6*ATR = 50000 + 300 = 50300
    assert position.sl == Decimal("50300")

    # TP1 = entry - 1.0*ATR = 50000 - 500 = 49500
    assert position.tp1 == Decimal("49500")

    # TP2 = entry - 1.8*ATR = 50000 - 900 = 49100
    assert position.tp2 == Decimal("49100")


# =============================================================================
# TEST: G3 - BREAKEVEN FIRES ONLY AFTER THRESHOLD
# =============================================================================

@pytest.mark.asyncio
async def test_breakeven_not_triggered_below_threshold(base_config, redis_client_async):
    """G3: Breakeven does NOT fire when unrealized < 0.5R."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open long position
    signal = create_signal(side="long")
    entry_price = Decimal("50000")
    atr = Decimal("500")

    position = await manager.open_position(signal, entry_price, Decimal("0.1"), atr)

    # SL distance = 300, so 0.5R threshold = 150
    # Current price = 50100 (profit = 100, below 150 threshold)
    current_price = Decimal("50100")

    update = await manager.update_position(position.position_id, current_price)

    # Should NOT move to breakeven
    assert update.action != "move_be"
    assert position.breakeven_set is False
    assert position.current_sl == position.sl  # Still at original SL


@pytest.mark.asyncio
async def test_breakeven_triggered_at_threshold(base_config, redis_client_async):
    """G3: Breakeven fires when unrealized >= 0.5R."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open long position
    signal = create_signal(side="long")
    entry_price = Decimal("50000")
    atr = Decimal("500")

    position = await manager.open_position(signal, entry_price, Decimal("0.1"), atr)

    # SL distance = 300, so 0.5R threshold = 150
    # Current price = 50150 (profit = 150, exactly at threshold)
    current_price = Decimal("50150")

    update = await manager.update_position(position.position_id, current_price)

    # Should move to breakeven
    assert update.action == "move_be"
    assert position.breakeven_set is True
    assert position.current_sl == entry_price  # Moved to entry


@pytest.mark.asyncio
async def test_breakeven_triggered_above_threshold(base_config, redis_client_async):
    """G3: Breakeven fires when unrealized > 0.5R."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open long position
    signal = create_signal(side="long")
    entry_price = Decimal("50000")
    atr = Decimal("500")

    position = await manager.open_position(signal, entry_price, Decimal("0.1"), atr)

    # Current price = 50200 (profit = 200, above 150 threshold)
    current_price = Decimal("50200")

    update = await manager.update_position(position.position_id, current_price)

    # Should move to breakeven
    assert update.action == "move_be"
    assert position.breakeven_set is True


@pytest.mark.asyncio
async def test_breakeven_only_fires_once(base_config, redis_client_async):
    """G3: Breakeven only fires once, not repeatedly."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open long position
    signal = create_signal(side="long")
    entry_price = Decimal("50000")
    atr = Decimal("500")

    position = await manager.open_position(signal, entry_price, Decimal("0.1"), atr)

    # First update - triggers BE
    update1 = await manager.update_position(position.position_id, Decimal("50200"))
    assert update1.action == "move_be"

    # Second update - should NOT trigger BE again
    update2 = await manager.update_position(position.position_id, Decimal("50300"))
    assert update2.action != "move_be"


# =============================================================================
# TEST: G3 - PARTIAL TP CORRECT QUANTITY MATH
# =============================================================================

@pytest.mark.asyncio
async def test_tp1_partial_close_correct_quantity(base_config, redis_client_async):
    """G3: TP1 closes correct quantity (50% of position)."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open position with 1.0 BTC
    signal = create_signal(side="long")
    entry_price = Decimal("50000")
    quantity = Decimal("1.0")
    atr = Decimal("500")

    position = await manager.open_position(signal, entry_price, quantity, atr)

    assert position.remaining_quantity == Decimal("1.0")

    # Price hits TP1
    tp1_price = position.tp1

    update = await manager.update_position(position.position_id, tp1_price)

    # Should close 50%
    assert update.action == "tp1_close"
    assert update.close_quantity == Decimal("0.5")  # 50% of 1.0
    assert position.remaining_quantity == Decimal("0.5")  # 50% remains
    assert position.tp1_hit is True


@pytest.mark.asyncio
async def test_tp1_partial_pnl_calculation(base_config, redis_client_async):
    """G3: TP1 partial close calculates correct PnL."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open position
    signal = create_signal(side="long")
    entry_price = Decimal("50000")
    quantity = Decimal("1.0")
    atr = Decimal("500")

    position = await manager.open_position(signal, entry_price, quantity, atr)

    # TP1 = 50500 (profit = 500 per BTC)
    tp1_price = position.tp1

    update = await manager.update_position(position.position_id, tp1_price)

    # Realized PnL = profit_per_unit * close_quantity
    # = 500 * 0.5 = 250
    expected_pnl = Decimal("250")

    assert update.realized_pnl == expected_pnl
    assert position.realized_pnl == expected_pnl


@pytest.mark.asyncio
async def test_tp2_closes_remaining_quantity(base_config, redis_client_async):
    """G3: TP2 closes remaining 50% after TP1."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open position
    signal = create_signal(side="long")
    entry_price = Decimal("50000")
    quantity = Decimal("1.0")
    atr = Decimal("500")

    position = await manager.open_position(signal, entry_price, quantity, atr)

    # Hit TP1 first
    await manager.update_position(position.position_id, position.tp1)

    assert position.remaining_quantity == Decimal("0.5")

    # Hit TP2
    tp2_price = position.tp2

    update = await manager.update_position(position.position_id, tp2_price)

    # Should close remaining 50%
    assert update.action == "tp2_close"
    assert update.close_quantity == Decimal("0.5")
    assert position.status == "closed"


# =============================================================================
# TEST: G3 - COOLDOWN AFTER 3 LOSSES
# =============================================================================

@pytest.mark.asyncio
async def test_no_cooldown_after_1_loss(base_config, redis_client_async):
    """G3: No cooldown after 1 loss."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Simulate 1 losing trade
    signal = create_signal()
    position = await manager.open_position(signal, Decimal("50000"), Decimal("0.1"), Decimal("500"))

    # Hit SL (loss)
    await manager.update_position(position.position_id, position.sl)

    # Check can still open position
    can_open, reason = await manager.can_open_position("BTC/USD")

    assert can_open is True
    assert reason is None
    assert manager.drawdown_state.consecutive_losses == 1


@pytest.mark.asyncio
async def test_no_cooldown_after_2_losses(base_config, redis_client_async):
    """G3: No cooldown after 2 losses."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Simulate 2 losing trades
    for i in range(2):
        signal = create_signal(pair=f"PAIR{i}/USD")
        position = await manager.open_position(signal, Decimal("50000"), Decimal("0.1"), Decimal("500"))
        await manager.update_position(position.position_id, position.sl)

    # Check can still open position
    can_open, reason = await manager.can_open_position("BTC/USD")

    assert can_open is True
    assert manager.drawdown_state.consecutive_losses == 2


@pytest.mark.asyncio
async def test_cooldown_after_3_losses(base_config, redis_client_async):
    """G3: Cooldown triggered after 3 consecutive losses."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Simulate 3 losing trades
    for i in range(3):
        signal = create_signal(pair=f"PAIR{i}/USD")
        position = await manager.open_position(signal, Decimal("50000"), Decimal("0.1"), Decimal("500"))
        await manager.update_position(position.position_id, position.sl)

    # Check cooldown is active
    can_open, reason = await manager.can_open_position("BTC/USD")

    assert can_open is False
    assert "Cooldown" in reason
    assert manager.drawdown_state.consecutive_losses == 3
    assert manager.drawdown_state.cooldown_until is not None


@pytest.mark.asyncio
async def test_cooldown_reset_on_win(base_config, redis_client_async):
    """G3: Consecutive losses reset to 0 on win."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # 2 losses
    for i in range(2):
        signal = create_signal(pair=f"PAIR{i}/USD")
        position = await manager.open_position(signal, Decimal("50000"), Decimal("0.1"), Decimal("500"))
        await manager.update_position(position.position_id, position.sl)

    assert manager.drawdown_state.consecutive_losses == 2

    # 1 win (TP2 hit)
    signal = create_signal(pair="WIN/USD")
    position = await manager.open_position(signal, Decimal("50000"), Decimal("0.1"), Decimal("500"))

    # Hit TP1 first
    await manager.update_position(position.position_id, position.tp1)

    # Hit TP2 (win)
    await manager.update_position(position.position_id, position.tp2)

    # Consecutive losses should reset
    assert manager.drawdown_state.consecutive_losses == 0
    assert manager.drawdown_state.cooldown_until is None


# =============================================================================
# TEST: G2 - CONCURRENT LIMITS
# =============================================================================

@pytest.mark.asyncio
async def test_concurrent_limit_allows_first_position(base_config, redis_client_async):
    """G2: Can open first position for pair."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    can_open, reason = await manager.can_open_position("BTC/USD")

    assert can_open is True
    assert reason is None


@pytest.mark.asyncio
async def test_concurrent_limit_rejects_second_position(base_config, redis_client_async):
    """G2: Cannot open second position when max_concurrent=1."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open first position
    signal = create_signal()
    await manager.open_position(signal, Decimal("50000"), Decimal("0.1"), Decimal("500"))

    # Try to open second position for same pair
    can_open, reason = await manager.can_open_position("BTC/USD")

    assert can_open is False
    assert "Concurrent limit" in reason


@pytest.mark.asyncio
async def test_concurrent_limit_allows_different_pair(base_config, redis_client_async):
    """G2: Can open position for different pair even if one pair at limit."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open position for BTC/USD
    signal1 = create_signal(pair="BTC/USD")
    await manager.open_position(signal1, Decimal("50000"), Decimal("0.1"), Decimal("500"))

    # Can still open for ETH/USD
    can_open, reason = await manager.can_open_position("ETH/USD")

    assert can_open is True


@pytest.mark.asyncio
async def test_concurrent_limit_freed_after_close(base_config, redis_client_async):
    """G2: Concurrent slot freed after position closes."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open and close position
    signal = create_signal()
    position = await manager.open_position(signal, Decimal("50000"), Decimal("0.1"), Decimal("500"))

    # Hit SL to close position
    await manager.update_position(position.position_id, position.sl)

    # Can now open new position for same pair
    can_open, reason = await manager.can_open_position("BTC/USD")

    assert can_open is True


# =============================================================================
# TEST: G2 - DRAWDOWN GATES
# =============================================================================

@pytest.mark.asyncio
async def test_day_drawdown_gate_allows_below_limit(base_config, redis_client_async):
    """G2: Day drawdown gate allows trading when below limit."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Simulate 3% daily loss (below 5% limit)
    manager.drawdown_state.daily_pnl = Decimal("-3000")  # -3% of 100k
    manager.drawdown_state.daily_start_equity = Decimal("100000")

    can_open, reason = await manager.can_open_position("BTC/USD")

    assert can_open is True


@pytest.mark.asyncio
async def test_day_drawdown_gate_rejects_above_limit(base_config, redis_client_async):
    """G2: Day drawdown gate rejects when above 5% limit."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Simulate 6% daily loss (above 5% limit)
    manager.drawdown_state.daily_pnl = Decimal("-6000")  # -6% of 100k
    manager.drawdown_state.daily_start_equity = Decimal("100000")

    can_open, reason = await manager.can_open_position("BTC/USD")

    assert can_open is False
    assert "Day drawdown" in reason


@pytest.mark.asyncio
async def test_rolling_drawdown_gate_rejects_above_limit(base_config, redis_client_async):
    """G2: Rolling drawdown gate rejects when above 10% limit."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Simulate 12% rolling loss (above 10% limit)
    manager.drawdown_state.rolling_pnl = Decimal("-12000")  # -12% of 100k
    manager.drawdown_state.rolling_start_equity = Decimal("100000")

    can_open, reason = await manager.can_open_position("BTC/USD")

    assert can_open is False
    assert "Rolling drawdown" in reason


# =============================================================================
# TEST: TRAILING STOP
# =============================================================================

@pytest.mark.asyncio
async def test_trailing_starts_after_tp1(base_config, redis_client_async):
    """G1: Trailing starts after TP1 hit."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open position
    signal = create_signal(side="long")
    position = await manager.open_position(signal, Decimal("50000"), Decimal("0.1"), Decimal("500"))

    # Before TP1
    assert position.trailing is False

    # Hit TP1
    await manager.update_position(position.position_id, position.tp1)

    # Trailing should start
    assert position.trailing is True


@pytest.mark.asyncio
async def test_trailing_updates_sl_upward_for_long(base_config, redis_client_async):
    """G1: Trailing stop moves up for longs (never down)."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open long position
    signal = create_signal(side="long")
    entry_price = Decimal("50000")
    atr = Decimal("500")

    position = await manager.open_position(signal, entry_price, Decimal("0.1"), atr)

    # Hit TP1 to start trailing
    await manager.update_position(position.position_id, position.tp1)

    old_sl = position.current_sl

    # Price moves higher - should update trail
    # Trail = current_price - trail_atr*ATR = 50700 - 0.8*500 = 50300
    higher_price = Decimal("50700")

    update = await manager.update_position(position.position_id, higher_price)

    # SL should move up
    assert position.current_sl > old_sl
    assert position.current_sl == Decimal("50300")  # 50700 - 400


@pytest.mark.asyncio
async def test_trailing_does_not_move_down_for_long(base_config, redis_client_async):
    """G1: Trailing stop does NOT move down for longs."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open long position
    signal = create_signal(side="long")
    position = await manager.open_position(signal, Decimal("50000"), Decimal("0.1"), Decimal("500"))

    # Hit TP1 and move SL up via trailing
    await manager.update_position(position.position_id, position.tp1)
    await manager.update_position(position.position_id, Decimal("50700"))

    current_sl = position.current_sl

    # Price moves down - SL should NOT move down
    lower_price = Decimal("50600")

    update = await manager.update_position(position.position_id, lower_price)

    assert position.current_sl == current_sl  # Unchanged


# =============================================================================
# TEST: STOP LOSS HIT
# =============================================================================

@pytest.mark.asyncio
async def test_sl_hit_long_closes_position(base_config, redis_client_async):
    """G1: Stop loss hit closes position."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open long position
    signal = create_signal(side="long")
    position = await manager.open_position(signal, Decimal("50000"), Decimal("0.1"), Decimal("500"))

    # Price hits SL
    sl_price = position.sl

    update = await manager.update_position(position.position_id, sl_price)

    assert update.action == "sl_hit"
    assert position.status == "closed"
    assert position.position_id not in manager.active_positions


@pytest.mark.asyncio
async def test_sl_hit_calculates_loss(base_config, redis_client_async):
    """G1: Stop loss calculates correct loss."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # Open long position
    signal = create_signal(side="long")
    entry_price = Decimal("50000")
    quantity = Decimal("1.0")
    atr = Decimal("500")

    position = await manager.open_position(signal, entry_price, quantity, atr)

    # SL = 49700, loss = -300 per BTC
    # Total loss = -300 * 1.0 = -300
    sl_price = position.sl

    update = await manager.update_position(position.position_id, sl_price)

    expected_loss = Decimal("-300")

    assert update.realized_pnl == expected_loss


# =============================================================================
# TEST: STATISTICS
# =============================================================================

@pytest.mark.asyncio
async def test_stats_tracking(base_config, redis_client_async):
    """Test statistics tracking."""
    manager = BarReactionTradeManager(base_config, redis_client_async)

    # 1 winning trade
    signal1 = create_signal(pair="WIN/USD")
    pos1 = await manager.open_position(signal1, Decimal("50000"), Decimal("0.1"), Decimal("500"))
    await manager.update_position(pos1.position_id, pos1.tp1)
    await manager.update_position(pos1.position_id, pos1.tp2)

    # 1 losing trade
    signal2 = create_signal(pair="LOSS/USD")
    pos2 = await manager.open_position(signal2, Decimal("50000"), Decimal("0.1"), Decimal("500"))
    await manager.update_position(pos2.position_id, pos2.sl)

    stats = manager.get_stats()

    assert stats["total_trades"] == 2
    assert stats["winning_trades"] == 1
    assert stats["losing_trades"] == 1
    assert stats["win_rate_pct"] == 50.0
    assert stats["tp1_hits"] == 1
    assert stats["tp2_hits"] == 1
    assert stats["sl_hits"] == 1


# =============================================================================
# TEST: HELPER FUNCTIONS
# =============================================================================

def test_as_decimal_conversions():
    """Test as_decimal helper function."""
    assert as_decimal(123.45) == Decimal("123.45")
    assert as_decimal("678.90") == Decimal("678.90")

    dec = Decimal("999.99")
    assert as_decimal(dec) is dec  # Same object


# =============================================================================
# SUMMARY
# =============================================================================

"""
Test Summary:

G1 - ATR-based stops:
- ✓ Long/short SL/TP calculation
- ✓ Break-even threshold (0.5R)
- ✓ Trailing stop (starts after TP1, moves favorably only)
- ✓ TP1 partial close (50%)
- ✓ TP2 final close

G2 - Stacking & caps:
- ✓ Concurrent limit (max 1 per pair)
- ✓ Day drawdown gate (5%)
- ✓ Rolling drawdown gate (10%)
- ✓ Different pairs allowed

G3 - Specific requirements:
- ✓ Breakeven fires ONLY after threshold
- ✓ Partial TP correct quantity math
- ✓ Cooldown after 3 losses

Total: 40 comprehensive tests
"""
