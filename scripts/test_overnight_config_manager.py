"""
Test Overnight Config Manager

Tests:
- Environment variable overrides (env-first)
- Configuration validation with bounds
- Fail-fast on invalid configurations
- Live updates via Redis streams
- Change callbacks

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import sys
import time
import json
from decimal import Decimal

# Fix Windows encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.overnight_config_manager import (
    create_overnight_config_manager,
    OvernightMomentumConfig,
    ValidationBounds,
)


def test_config_load():
    """Test configuration loading."""
    print("\n" + "="*80)
    print("TEST 1: Configuration Loading")
    print("="*80)

    # Create config manager using standalone config
    config_manager = create_overnight_config_manager(
        config_path="config/overnight_momentum_config.yaml"
    )

    # Get config
    config = config_manager.get_config()

    print(f"✓ Configuration loaded successfully")
    print(f"  - Enabled: {config.enabled}")
    print(f"  - Backtest only: {config.backtest_only}")
    print(f"  - Target range: {config.target_min_pct}-{config.target_max_pct}%")
    print(f"  - Trailing stop: {config.trailing_stop_pct}%")
    print(f"  - Risk per trade: {config.risk_per_trade_pct}%")
    print(f"  - Spot notional multiplier: {config.spot_notional_multiplier}x")
    print(f"  - Max portfolio heat: {config.max_portfolio_heat_pct}%")

    return True


def test_env_overrides():
    """Test environment variable overrides."""
    print("\n" + "="*80)
    print("TEST 2: Environment Variable Overrides (env-first)")
    print("="*80)

    # Set environment variables
    os.environ["OVERNIGHT_MOMENTUM_ENABLED"] = "true"
    os.environ["OVERNIGHT_RISK_PER_TRADE"] = "2.5"
    os.environ["OVERNIGHT_TRAILING_STOP"] = "0.9"
    os.environ["OVERNIGHT_TARGET_MIN"] = "1.5"

    # Create config manager (will use env vars)
    config_manager = create_overnight_config_manager(
        config_path="config/overnight_momentum_config.yaml"
    )
    config = config_manager.get_config()

    print(f"Environment variables set:")
    print(f"  OVERNIGHT_MOMENTUM_ENABLED=true")
    print(f"  OVERNIGHT_RISK_PER_TRADE=2.5")
    print(f"  OVERNIGHT_TRAILING_STOP=0.9")
    print(f"  OVERNIGHT_TARGET_MIN=1.5")

    print(f"\nConfiguration values:")
    print(f"  Enabled: {config.enabled}")
    print(f"  Risk per trade: {config.risk_per_trade_pct}%")
    print(f"  Trailing stop: {config.trailing_stop_pct}%")
    print(f"  Target min: {config.target_min_pct}%")

    # Verify env overrides worked
    passed = (
        config.enabled == True and
        config.risk_per_trade_pct == 2.5 and
        config.trailing_stop_pct == 0.9 and
        config.target_min_pct == 1.5
    )

    # Clean up env vars
    del os.environ["OVERNIGHT_MOMENTUM_ENABLED"]
    del os.environ["OVERNIGHT_RISK_PER_TRADE"]
    del os.environ["OVERNIGHT_TRAILING_STOP"]
    del os.environ["OVERNIGHT_TARGET_MIN"]

    print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Environment overrides")
    return passed


def test_validation_pass():
    """Test validation with valid parameters."""
    print("\n" + "="*80)
    print("TEST 3: Validation - Valid Parameters")
    print("="*80)

    try:
        config = OvernightMomentumConfig(
            risk_per_trade_pct=2.0,  # Valid: within [0.1, 5.0]
            trailing_stop_pct=0.7,   # Valid: within [0.3, 2.0]
            target_min_pct=1.5,      # Valid: within [0.5, 5.0]
            target_max_pct=3.0,      # Valid: within [0.5, 5.0]
            spot_notional_multiplier=2.5,  # Valid: within [1.0, 3.0]
            max_portfolio_heat_pct=12.0,   # Valid: within [1.0, 20.0]
        )

        config.validate()  # Should not raise

        print(f"✓ Valid configuration accepted:")
        print(f"  risk_per_trade_pct: {config.risk_per_trade_pct}")
        print(f"  trailing_stop_pct: {config.trailing_stop_pct}")
        print(f"  target_min_pct: {config.target_min_pct}")
        print(f"  target_max_pct: {config.target_max_pct}")
        print(f"  spot_notional_multiplier: {config.spot_notional_multiplier}")
        print(f"  max_portfolio_heat_pct: {config.max_portfolio_heat_pct}")

        print(f"\n✅ PASS: Validation accepts valid parameters")
        return True

    except Exception as e:
        print(f"\n❌ FAIL: Validation rejected valid parameters: {e}")
        return False


def test_validation_fail():
    """Test validation with invalid parameters (fail-fast)."""
    print("\n" + "="*80)
    print("TEST 4: Validation - Invalid Parameters (Fail-Fast)")
    print("="*80)

    test_cases = [
        {
            "name": "risk_per_trade_pct too high",
            "params": {"risk_per_trade_pct": 6.0},  # Max: 5.0
            "expected_error": "risk_per_trade_pct"
        },
        {
            "name": "trailing_stop_pct too low",
            "params": {"trailing_stop_pct": 0.2},  # Min: 0.3
            "expected_error": "trailing_stop_pct"
        },
        {
            "name": "spot_notional_multiplier too high",
            "params": {"spot_notional_multiplier": 4.0},  # Max: 3.0
            "expected_error": "spot_notional_multiplier"
        },
        {
            "name": "max_portfolio_heat_pct too high",
            "params": {"max_portfolio_heat_pct": 25.0},  # Max: 20.0
            "expected_error": "max_portfolio_heat_pct"
        },
        {
            "name": "volume_percentile_max out of bounds",
            "params": {"volume_percentile_max": 95.0},  # Max: 90.0
            "expected_error": "volume_percentile_max"
        },
        {
            "name": "target_min > target_max",
            "params": {"target_min_pct": 3.0, "target_max_pct": 2.0},
            "expected_error": "target_min_pct must be <= target_max_pct"
        },
    ]

    all_passed = True

    for test in test_cases:
        try:
            config = OvernightMomentumConfig(**test["params"])
            config.validate()

            # Should have raised ValueError
            print(f"❌ FAIL: {test['name']} - validation did not fail")
            all_passed = False

        except ValueError as e:
            if test["expected_error"] in str(e):
                print(f"✓ {test['name']} - correctly rejected: {e}")
            else:
                print(f"❌ FAIL: {test['name']} - wrong error: {e}")
                all_passed = False

    print(f"\n{'✅ PASS' if all_passed else '❌ FAIL'}: Fail-fast validation")
    return all_passed


def test_config_update():
    """Test configuration updates with validation."""
    print("\n" + "="*80)
    print("TEST 5: Configuration Updates")
    print("="*80)

    config_manager = create_overnight_config_manager(
        config_path="config/overnight_momentum_config.yaml"
    )

    # Test valid update
    try:
        updates = {
            "risk_per_trade_pct": 1.5,
            "trailing_stop_pct": 0.8,
            "target_min_pct": 1.2,
        }

        config_manager.update_config(updates)

        new_config = config_manager.get_config()

        print(f"✓ Valid update accepted:")
        print(f"  risk_per_trade_pct: {new_config.risk_per_trade_pct}")
        print(f"  trailing_stop_pct: {new_config.trailing_stop_pct}")
        print(f"  target_min_pct: {new_config.target_min_pct}")

        valid_update_passed = True

    except Exception as e:
        print(f"❌ Valid update rejected: {e}")
        valid_update_passed = False

    # Test invalid update (should fail-fast)
    try:
        invalid_updates = {
            "risk_per_trade_pct": 10.0,  # Out of bounds
        }

        config_manager.update_config(invalid_updates)

        print(f"❌ Invalid update accepted (should have failed)")
        invalid_update_passed = False

    except ValueError as e:
        print(f"\n✓ Invalid update correctly rejected: {e}")
        invalid_update_passed = True

    passed = valid_update_passed and invalid_update_passed

    print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Configuration updates")
    return passed


def test_change_callbacks():
    """Test configuration change callbacks."""
    print("\n" + "="*80)
    print("TEST 6: Change Callbacks")
    print("="*80)

    config_manager = create_overnight_config_manager(
        config_path="config/overnight_momentum_config.yaml"
    )

    # Track callback invocations
    callback_count = [0]
    received_config = [None]

    def on_config_change(config: OvernightMomentumConfig):
        callback_count[0] += 1
        received_config[0] = config
        print(f"  ✓ Callback invoked (count: {callback_count[0]})")

    # Register callback
    config_manager.register_change_callback(on_config_change)

    print(f"Callback registered")

    # Trigger update
    updates = {"risk_per_trade_pct": 1.8}
    config_manager.update_config(updates)

    time.sleep(0.1)  # Give callback time to execute

    passed = (
        callback_count[0] == 1 and
        received_config[0] is not None and
        received_config[0].risk_per_trade_pct == 1.8
    )

    print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Change callbacks")
    return passed


def test_status():
    """Test status reporting."""
    print("\n" + "="*80)
    print("TEST 7: Status Reporting")
    print("="*80)

    config_manager = create_overnight_config_manager(
        config_path="config/overnight_momentum_config.yaml"
    )

    status = config_manager.get_status()

    print(f"Configuration manager status:")
    for key, value in status.items():
        print(f"  {key}: {value}")

    passed = (
        status['config_loaded'] == True and
        'config_path' in status
    )

    print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Status reporting")
    return passed


def main():
    """Run all tests."""
    print("="*80)
    print("OVERNIGHT CONFIG MANAGER - TEST SUITE")
    print("="*80)

    results = {}

    # Run all tests
    results['config_load'] = test_config_load()
    results['env_overrides'] = test_env_overrides()
    results['validation_pass'] = test_validation_pass()
    results['validation_fail'] = test_validation_fail()
    results['config_update'] = test_config_update()
    results['change_callbacks'] = test_change_callbacks()
    results['status'] = test_status()

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {test_name}")

    total_tests = len(results)
    passed_tests = sum(results.values())

    print(f"\nTotal: {passed_tests}/{total_tests} tests passed")

    if all(results.values()):
        print("\n🎉 ALL TESTS PASSED!")
        print("\n✅ Features validated:")
        print("  - Environment variable overrides (env-first)")
        print("  - Configuration validation with bounds")
        print("  - Fail-fast on invalid configurations")
        print("  - Live configuration updates")
        print("  - Change callbacks")
        print("\n📝 Ready for:")
        print("  - Redis stream integration (requires Redis connection)")
        print("  - Live hot-reload without restarts")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED - Review implementation")
        return 1


if __name__ == "__main__":
    exit(main())
