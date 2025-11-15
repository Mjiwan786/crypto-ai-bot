"""
Test script for dynamic sizing integration with PositionManager.

This script verifies that the dynamic sizing module is properly integrated
into the PositionManager and works correctly.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


async def test_basic_integration():
    """Test basic dynamic sizing integration."""
    print("=" * 60)
    print("Testing Dynamic Sizing Integration with PositionManager")
    print("=" * 60)

    # Import PositionManager
    try:
        from agents.scalper.execution.position_manager import PositionManager
        print("[OK] PositionManager import successful")
    except ImportError as e:
        print(f"[FAIL] PositionManager import failed: {e}")
        return False

    # Test 1: Initialize without dynamic sizing (backward compatibility)
    print("\nTest 1: Initialize without dynamic sizing...")
    try:
        pm1 = PositionManager(
            agent_id="test_agent_1",
            initial_capital=10000.0,
        )
        print(f"[OK] PositionManager initialized without dynamic sizing")
        print(f"     - dynamic_sizing attribute: {pm1.dynamic_sizing}")
        assert pm1.dynamic_sizing is None, "Expected None for dynamic_sizing"
    except Exception as e:
        print(f"[FAIL] Initialization without dynamic sizing failed: {e}")
        return False

    # Test 2: Initialize with dynamic sizing enabled
    print("\nTest 2: Initialize with dynamic sizing enabled...")
    try:
        dynamic_config = {
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
            "allow_runtime_overrides": False,  # Disable for testing
            "log_sizing_decisions": True,
            "publish_metrics_to_redis": False,  # Disable Redis for testing
        }

        pm2 = PositionManager(
            agent_id="test_agent_2",
            initial_capital=10000.0,
            dynamic_sizing_config=dynamic_config,
            redis_bus=None,  # No Redis for testing
            state_manager=None,  # No state manager for testing
        )
        print(f"[OK] PositionManager initialized with dynamic sizing")
        print(f"     - dynamic_sizing: {pm2.dynamic_sizing}")
        assert pm2.dynamic_sizing is not None, "Expected dynamic_sizing to be initialized"
    except Exception as e:
        print(f"[FAIL] Initialization with dynamic sizing failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test 3: Start/stop lifecycle
    print("\nTest 3: Testing lifecycle methods...")
    try:
        await pm2.start()
        print(f"[OK] PositionManager.start() completed")

        await pm2.stop()
        print(f"[OK] PositionManager.stop() completed")
    except Exception as e:
        print(f"[FAIL] Lifecycle methods failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test 4: Test get_size_multiplier integration
    print("\nTest 4: Testing size multiplier calculation...")
    try:
        await pm2.start()

        # Simulate getting a size multiplier
        multiplier, breakdown = await pm2.dynamic_sizing.get_size_multiplier(
            current_equity_usd=10000.0,
            portfolio_heat_pct=45.0,
            current_volatility_atr_pct=1.5,
        )

        print(f"[OK] Size multiplier calculated: {multiplier:.2f}x")
        print(f"     - Breakdown: base_risk={breakdown.get('base_risk_pct', 0):.2f}%, "
              f"streak_boost={breakdown.get('streak_boost_pct', 0):.2f}%, "
              f"final={breakdown.get('final_multiplier', 0):.2f}x")

        assert multiplier > 0, "Expected positive multiplier"
        assert multiplier <= 3.0, "Expected multiplier <= 3.0 (safety cap)"

        await pm2.stop()
    except Exception as e:
        print(f"[FAIL] Size multiplier calculation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test 5: Test record_trade_outcome
    print("\nTest 5: Testing trade outcome recording...")
    try:
        await pm2.start()

        # Record a winning trade
        await pm2.dynamic_sizing.record_trade_outcome(
            symbol="BTC/USD",
            pnl_usd=100.0,
            size_usd=1000.0,
        )
        print(f"[OK] Trade outcome recorded (win)")

        # Get state to verify
        state = await pm2.dynamic_sizing.get_state()
        print(f"     - Current streak: {state.get('current_streak', 0)}")
        print(f"     - Trade count: {state.get('trade_count', 0)}")

        assert state.get('current_streak', 0) == 1, "Expected streak = 1 after one win"

        # Record another winning trade
        await pm2.dynamic_sizing.record_trade_outcome(
            symbol="BTC/USD",
            pnl_usd=50.0,
            size_usd=1000.0,
        )

        state = await pm2.dynamic_sizing.get_state()
        print(f"[OK] Second trade recorded")
        print(f"     - Current streak: {state.get('current_streak', 0)}")
        assert state.get('current_streak', 0) == 2, "Expected streak = 2 after two wins"

        # Verify multiplier increases with streak
        multiplier_with_streak, breakdown = await pm2.dynamic_sizing.get_size_multiplier(
            current_equity_usd=10200.0,
            portfolio_heat_pct=45.0,
            current_volatility_atr_pct=1.5,
        )

        print(f"[OK] Size multiplier with 2-win streak: {multiplier_with_streak:.2f}x")
        print(f"     - Streak boost: {breakdown.get('streak_boost_pct', 0):.2f}%")

        assert breakdown.get('streak_boost_pct', 0) > 0, "Expected positive streak boost"

        await pm2.stop()
    except Exception as e:
        print(f"[FAIL] Trade outcome recording failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)
    print("\nDynamic sizing integration is working correctly.")
    print("Next steps:")
    print("  - Integrate into enhanced_scalper_agent or main trading agent")
    print("  - Pass dynamic_sizing_config from config file")
    print("  - Add Redis bus and state manager for full functionality")
    print("  - Run paper trading trial to validate in live conditions")

    return True


if __name__ == "__main__":
    success = asyncio.run(test_basic_integration())
    sys.exit(0 if success else 1)
