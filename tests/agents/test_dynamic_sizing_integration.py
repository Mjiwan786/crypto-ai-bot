"""
Integration Tests for Dynamic Sizing with Redis/MCP Runtime Overrides

Tests:
- Redis-based runtime overrides
- Hot config reloading
- State persistence
- Metric publishing
- Full integration with RiskManager

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.scalper.risk.dynamic_sizing import DynamicSizingConfig
from agents.scalper.risk.sizing_integration import DynamicSizingIntegration


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_redis_bus():
    """Mock Redis bus for testing."""
    bus = AsyncMock()
    bus.publish = AsyncMock()
    bus.subscribe = AsyncMock()
    return bus


@pytest.fixture
def mock_state_manager():
    """Mock state manager for testing."""
    manager = AsyncMock()
    manager.load_sizing_state = AsyncMock(return_value=None)
    manager.save_sizing_state = AsyncMock()
    return manager


@pytest.fixture
def config_dict():
    """Standard config dict for testing."""
    return {
        "enabled": True,
        "base_risk_pct_small": 1.5,
        "base_risk_pct_large": 1.0,
        "equity_threshold_usd": 15000.0,
        "streak_boost_pct": 0.2,
        "max_streak_boost_pct": 1.0,
        "max_streak_count": 5,
        "high_vol_multiplier": 0.8,
        "normal_vol_multiplier": 1.0,
        "high_vol_threshold_atr_pct": 2.0,
        "portfolio_heat_threshold_pct": 80.0,
        "portfolio_heat_cut_multiplier": 0.5,
        "allow_runtime_overrides": True,
        "override_expiry_seconds": 3600,
        "log_sizing_decisions": True,
        "publish_metrics_to_redis": True,
        "metrics_publish_interval_seconds": 1,  # Fast for testing
    }


@pytest.fixture
async def integration(config_dict, mock_redis_bus, mock_state_manager):
    """Create integration instance."""
    integration = DynamicSizingIntegration(
        config_dict=config_dict,
        redis_bus=mock_redis_bus,
        state_manager=mock_state_manager,
        agent_id="test_agent",
    )
    await integration.start()
    yield integration
    await integration.stop()


# =============================================================================
# TEST: INITIALIZATION & LIFECYCLE
# =============================================================================


@pytest.mark.asyncio
async def test_integration_initialization(config_dict, mock_redis_bus):
    """Test integration initializes correctly."""
    integration = DynamicSizingIntegration(
        config_dict=config_dict,
        redis_bus=mock_redis_bus,
        agent_id="test_agent",
    )

    assert integration.agent_id == "test_agent"
    assert integration.sizer is not None
    assert integration.log_sizing_decisions is True
    assert integration.publish_metrics is True


@pytest.mark.asyncio
async def test_integration_start_stop(integration):
    """Test integration lifecycle."""
    assert integration.is_running is True

    await integration.stop()
    assert integration.is_running is False


# =============================================================================
# TEST: SIZE CALCULATION API
# =============================================================================


@pytest.mark.asyncio
async def test_get_size_multiplier_basic(integration):
    """Test basic size multiplier calculation via integration."""
    multiplier, breakdown = await integration.get_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=50.0,
        current_volatility_atr_pct=1.0,
    )

    assert multiplier > 0
    assert "base_risk_pct" in breakdown
    assert "final_multiplier" in breakdown


@pytest.mark.asyncio
async def test_get_size_multiplier_with_streak(integration):
    """Test size multiplier with win streak."""
    # Record wins
    await integration.record_trade_outcome("BTC/USD", pnl_usd=100.0, size_usd=1000.0)
    await integration.record_trade_outcome("BTC/USD", pnl_usd=50.0, size_usd=1000.0)

    multiplier, breakdown = await integration.get_size_multiplier(
        current_equity_usd=20000.0,
        portfolio_heat_pct=50.0,
        current_volatility_atr_pct=1.0,
    )

    # Should have streak boost
    assert breakdown["streak_boost_pct"] > 0


# =============================================================================
# TEST: REDIS RUNTIME OVERRIDES
# =============================================================================


@pytest.mark.asyncio
async def test_redis_override_subscription(integration, mock_redis_bus):
    """Test Redis override subscription is setup."""
    # Check subscribe was called
    assert mock_redis_bus.subscribe.called
    calls = mock_redis_bus.subscribe.call_args_list

    # Should subscribe to override channel
    channel_names = [call[0][0] for call in calls]
    assert any("sizing:override:" in name for name in channel_names)


@pytest.mark.asyncio
async def test_handle_override_update(integration):
    """Test handling runtime override from Redis."""
    # Simulate override message
    override_data = {
        "key": "size_multiplier",
        "value": 2.0,
        "expiry_seconds": 3600,
        "reason": "test override",
    }

    await integration._handle_override_update(override_data)

    # Calculate size - should use override
    multiplier, breakdown = await integration.get_size_multiplier(
        current_equity_usd=10000.0,
        portfolio_heat_pct=50.0,
        current_volatility_atr_pct=1.0,
    )

    assert multiplier == 2.0
    assert "override" in breakdown


@pytest.mark.asyncio
async def test_handle_control_command_reset_streak(integration):
    """Test reset streak control command."""
    # Build streak
    await integration.record_trade_outcome("BTC/USD", pnl_usd=100.0, size_usd=1000.0)
    assert integration.sizer.current_streak == 1

    # Send reset command
    await integration._handle_control_command({"command": "reset_streak"})

    # Streak should be reset
    assert integration.sizer.current_streak == 0


@pytest.mark.asyncio
async def test_handle_control_command_clear_overrides(integration):
    """Test clear overrides control command."""
    # Set override
    integration.sizer.set_runtime_override("size_multiplier", 2.0)

    # Send clear command
    await integration._handle_control_command({"command": "clear_overrides"})

    # Override should be cleared
    multiplier, breakdown = await integration.get_size_multiplier(
        current_equity_usd=10000.0,
        portfolio_heat_pct=50.0,
    )

    assert "override" not in breakdown


# =============================================================================
# TEST: METRICS PUBLISHING
# =============================================================================


@pytest.mark.asyncio
async def test_metrics_publishing(config_dict, mock_redis_bus, mock_state_manager):
    """Test metrics are published to Redis periodically."""
    integration = DynamicSizingIntegration(
        config_dict=config_dict,
        redis_bus=mock_redis_bus,
        state_manager=mock_state_manager,
        agent_id="test_agent",
    )

    await integration.start()

    # Wait for at least one publish cycle
    await asyncio.sleep(1.5)

    # Check publish was called
    assert mock_redis_bus.publish.called
    calls = mock_redis_bus.publish.call_args_list

    # Should publish to metrics channel
    channel_names = [call[0][0] for call in calls]
    assert any("sizing:metrics:" in name for name in channel_names)

    await integration.stop()


@pytest.mark.asyncio
async def test_trade_recorded_publishes_update(integration, mock_redis_bus):
    """Test trade recording publishes update to Redis."""
    await integration.record_trade_outcome("BTC/USD", pnl_usd=100.0, size_usd=1000.0)

    # Should publish trade recorded event
    assert mock_redis_bus.publish.called
    calls = mock_redis_bus.publish.call_args_list

    # Find the trade_recorded publish
    trade_publishes = [
        call for call in calls if "sizing:trade_recorded:" in call[0][0]
    ]
    assert len(trade_publishes) > 0

    # Check message content
    message = trade_publishes[0][0][1]
    assert message["symbol"] == "BTC/USD"
    assert message["pnl"] == 100.0
    assert message["streak"] == 1


# =============================================================================
# TEST: STATE PERSISTENCE
# =============================================================================


@pytest.mark.asyncio
async def test_state_loading_on_start(config_dict, mock_redis_bus, mock_state_manager):
    """Test state is loaded on start."""
    # Setup mock state
    mock_state = {
        "current_streak": 3,
        "trade_history": [
            {
                "timestamp": time.time(),
                "symbol": "BTC/USD",
                "outcome": "win",
                "pnl": 100.0,
                "size": 1000.0,
            }
        ],
    }
    mock_state_manager.load_sizing_state = AsyncMock(return_value=mock_state)

    integration = DynamicSizingIntegration(
        config_dict=config_dict,
        redis_bus=mock_redis_bus,
        state_manager=mock_state_manager,
        agent_id="test_agent",
    )

    await integration.start()

    # Check state was loaded
    assert integration.sizer.current_streak == 3
    assert len(integration.sizer.trade_history) == 1

    await integration.stop()


@pytest.mark.asyncio
async def test_state_saving_on_stop(integration, mock_state_manager):
    """Test state is saved on stop."""
    # Record some trades
    await integration.record_trade_outcome("BTC/USD", pnl_usd=100.0, size_usd=1000.0)

    await integration.stop()

    # Check save was called
    assert mock_state_manager.save_sizing_state.called


# =============================================================================
# TEST: ERROR HANDLING
# =============================================================================


@pytest.mark.asyncio
async def test_override_update_handles_invalid_message(integration):
    """Test graceful handling of invalid override message."""
    # Send invalid message (missing key)
    await integration._handle_override_update({"value": 2.0})

    # Should not crash - override not applied
    multiplier, breakdown = await integration.get_size_multiplier(
        current_equity_usd=10000.0,
        portfolio_heat_pct=50.0,
    )

    assert "override" not in breakdown


@pytest.mark.asyncio
async def test_control_command_handles_unknown_command(integration):
    """Test graceful handling of unknown control command."""
    # Send unknown command
    await integration._handle_control_command({"command": "unknown_command"})

    # Should not crash - no effect


# =============================================================================
# TEST: INTEGRATION WITH REAL WORKFLOW
# =============================================================================


@pytest.mark.asyncio
async def test_full_trading_cycle_workflow(integration, mock_redis_bus):
    """Test full trading cycle: calculate size → execute → record → update."""
    # 1. Get initial size
    multiplier1, _ = await integration.get_size_multiplier(
        current_equity_usd=10000.0,
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.5,
    )

    # 2. "Execute trade" (simulated)

    # 3. Record trade outcome (win)
    await integration.record_trade_outcome("BTC/USD", pnl_usd=100.0, size_usd=1000.0)

    # 4. Get new size (should have streak boost)
    multiplier2, breakdown = await integration.get_size_multiplier(
        current_equity_usd=10100.0,  # After profit
        portfolio_heat_pct=40.0,
        current_volatility_atr_pct=1.5,
    )

    # Second multiplier should be higher (streak boost)
    assert multiplier2 > multiplier1
    assert breakdown["streak_boost_pct"] > 0


@pytest.mark.asyncio
async def test_heat_emergency_brake_workflow(integration):
    """Test emergency brake kicks in during high heat."""
    # Normal size
    multiplier1, _ = await integration.get_size_multiplier(
        current_equity_usd=10000.0,
        portfolio_heat_pct=50.0,  # Normal
    )

    # High heat emergency
    multiplier2, breakdown = await integration.get_size_multiplier(
        current_equity_usd=10000.0,
        portfolio_heat_pct=85.0,  # Emergency!
    )

    # Second multiplier should be half of first
    assert breakdown["heat_multiplier"] == 0.5
    assert multiplier2 < multiplier1


# =============================================================================
# TEST: MCP COMPATIBILITY
# =============================================================================


@pytest.mark.asyncio
async def test_mcp_override_format_compatibility(integration):
    """Test MCP-style override message format is supported."""
    # MCP-style override (simplified)
    mcp_override = {
        "key": "size_multiplier",
        "value": 1.5,
        "expiry_seconds": 600,
        "source": "mcp",
        "reason": "Manual adjustment",
    }

    await integration._handle_override_update(mcp_override)

    multiplier, breakdown = await integration.get_size_multiplier(
        current_equity_usd=10000.0,
        portfolio_heat_pct=50.0,
    )

    assert multiplier == 1.5


# =============================================================================
# TEST: CONFIGURATION VARIATIONS
# =============================================================================


@pytest.mark.asyncio
async def test_integration_with_disabled_overrides(mock_redis_bus):
    """Test integration with runtime overrides disabled."""
    config = {
        "enabled": True,
        "base_risk_pct_small": 1.5,
        "base_risk_pct_large": 1.0,
        "equity_threshold_usd": 15000.0,
        "allow_runtime_overrides": False,  # Disabled
    }

    integration = DynamicSizingIntegration(
        config_dict=config,
        redis_bus=mock_redis_bus,
        agent_id="test_agent",
    )

    await integration.start()

    # Try to set override
    await integration._handle_override_update({"key": "size_multiplier", "value": 2.0})

    # Should be ignored
    multiplier, breakdown = await integration.get_size_multiplier(10000.0, 50.0)
    assert multiplier != 2.0

    await integration.stop()


@pytest.mark.asyncio
async def test_integration_without_redis(config_dict):
    """Test integration works without Redis bus."""
    integration = DynamicSizingIntegration(
        config_dict=config_dict,
        redis_bus=None,  # No Redis
        state_manager=None,
        agent_id="test_agent",
    )

    await integration.start()

    # Should still work
    multiplier, breakdown = await integration.get_size_multiplier(10000.0, 50.0)
    assert multiplier > 0

    await integration.stop()


# =============================================================================
# BENCHMARK TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_sizing_calculation_performance(integration):
    """Benchmark: sizing calculation should be fast (<1ms)."""
    import time

    iterations = 1000
    start = time.perf_counter()

    for _ in range(iterations):
        await integration.get_size_multiplier(10000.0, 50.0, 1.5)

    end = time.perf_counter()
    avg_time_ms = ((end - start) / iterations) * 1000

    # Should be very fast (<1ms per calculation)
    assert avg_time_ms < 1.0, f"Sizing calculation too slow: {avg_time_ms:.3f}ms"
