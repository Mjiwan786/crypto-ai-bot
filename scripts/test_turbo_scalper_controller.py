"""
Test script for Turbo Scalper Controller

Validates:
- Conditional 5s bar enablement based on latency
- News override control
- Configuration loading from YAML
- Redis integration
- Change callbacks

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import sys
import asyncio
import logging

# Add parent to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.turbo_scalper_controller import TurboScalperController, get_turbo_controller

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


def test_yaml_loading():
    """Test 1: Load configuration from YAML."""
    print("\n" + "="*80)
    print("TEST 1: Load Configuration from YAML")
    print("="*80)

    controller = TurboScalperController()
    success = controller.load_from_yaml()

    if success:
        print("[PASS] Configuration loaded successfully")
        print(controller.get_status_summary())
        return True
    else:
        print("[FAIL] Failed to load configuration")
        return False


def test_latency_monitoring():
    """Test 2: Latency monitoring and conditional 5s enablement."""
    print("\n" + "="*80)
    print("TEST 2: Latency Monitoring and Conditional 5s Enablement")
    print("="*80)

    controller = TurboScalperController()
    controller.load_from_yaml()

    print("\nPhase 1: Low latency (should enable 5s)...")
    for i in range(15):
        controller.update_latency(40.0 + i * 0.3)

    if controller.config.timeframe_5s_enabled:
        print("[PASS] 5s bars enabled with low latency")
        print(f"  Avg Latency: {controller.latency_monitor.avg_latency_ms:.1f}ms")
    else:
        print("[FAIL] 5s bars not enabled with low latency")
        return False

    print("\nPhase 2: High latency (should disable 5s)...")
    for i in range(15):
        controller.update_latency(55.0 + i * 0.5)

    if not controller.config.timeframe_5s_enabled:
        print("[PASS] 5s bars disabled with high latency")
        print(f"  Avg Latency: {controller.latency_monitor.avg_latency_ms:.1f}ms")
        return True
    else:
        print("[FAIL] 5s bars still enabled with high latency")
        return False


def test_news_override():
    """Test 3: News override control."""
    print("\n" + "="*80)
    print("TEST 3: News Override Control")
    print("="*80)

    controller = TurboScalperController()
    controller.load_from_yaml()

    print("\nEnabling news override...")
    controller.enable_news_override()

    if controller.config.news_override_enabled:
        print("[PASS] News override enabled")
        print(f"  Position Multiplier: {controller.config.news_override_position_multiplier}x")
        print(f"  Stops Disabled: {controller.config.news_override_disable_stops}")
    else:
        print("[FAIL] News override not enabled")
        return False

    print("\nDisabling news override...")
    controller.disable_news_override()

    if not controller.config.news_override_enabled:
        print("[PASS] News override disabled")
        return True
    else:
        print("[FAIL] News override still enabled")
        return False


def test_change_callbacks():
    """Test 4: Change callbacks."""
    print("\n" + "="*80)
    print("TEST 4: Change Callbacks")
    print("="*80)

    controller = TurboScalperController()
    controller.load_from_yaml()

    callback_triggered = {'count': 0, 'params': []}

    def test_callback(param_name, new_value):
        callback_triggered['count'] += 1
        callback_triggered['params'].append((param_name, new_value))
        print(f"  Callback triggered: {param_name} = {new_value}")

    controller.register_callback(test_callback)

    print("\nEnabling news override (should trigger callback)...")
    controller.enable_news_override()

    print("\nEnabling 5s bars (should trigger callback)...")
    for i in range(15):
        controller.update_latency(40.0)

    if callback_triggered['count'] >= 2:
        print(f"[PASS] Callbacks triggered {callback_triggered['count']} times")
        print(f"  Params changed: {callback_triggered['params']}")
        return True
    else:
        print(f"[FAIL] Callbacks not triggered (count: {callback_triggered['count']})")
        return False


def test_config_export():
    """Test 5: Configuration export."""
    print("\n" + "="*80)
    print("TEST 5: Configuration Export")
    print("="*80)

    controller = TurboScalperController()
    controller.load_from_yaml()

    # Update some settings
    for i in range(15):
        controller.update_latency(45.0)
    controller.enable_news_override()

    config_dict = controller.get_current_config()

    print("\nExported configuration:")
    for key, value in config_dict.items():
        print(f"  {key}: {value}")

    if 'timeframe_5s_enabled' in config_dict and 'news_override_enabled' in config_dict:
        print("[PASS] Configuration exported successfully")
        return True
    else:
        print("[FAIL] Configuration export incomplete")
        return False


def test_5s_time_tracking():
    """Test 6: Track time with 5s bars enabled."""
    print("\n" + "="*80)
    print("TEST 6: Track 5s Bar Enablement Time")
    print("="*80)

    controller = TurboScalperController()
    controller.load_from_yaml()

    print("\nEnabling 5s bars...")
    for i in range(15):
        controller.update_latency(40.0)

    import time
    time.sleep(2)  # 5s enabled for 2 seconds

    print("\nDisabling 5s bars...")
    for i in range(15):
        controller.update_latency(55.0)

    config = controller.get_current_config()
    total_hours = config['total_5s_enabled_hours']

    print(f"Total 5s enabled time: {total_hours:.4f} hours ({total_hours * 3600:.1f} seconds)")

    if total_hours > 0:
        print("[PASS] 5s enablement time tracked")
        return True
    else:
        print("[FAIL] 5s enablement time not tracked")
        return False


def test_singleton_pattern():
    """Test 7: Singleton pattern."""
    print("\n" + "="*80)
    print("TEST 7: Singleton Pattern")
    print("="*80)

    controller1 = get_turbo_controller()
    controller2 = get_turbo_controller()

    if controller1 is controller2:
        print("[PASS] Singleton pattern working (same instance)")
        return True
    else:
        print("[FAIL] Different instances returned")
        return False


async def test_redis_integration():
    """Test 8: Redis integration."""
    print("\n" + "="*80)
    print("TEST 8: Redis Integration")
    print("="*80)

    controller = TurboScalperController()
    controller.load_from_yaml()

    print("\nConnecting to Redis...")
    connected = await controller.connect_redis()

    if connected:
        print("[PASS] Connected to Redis")

        print("\nPublishing configuration update...")
        published = await controller.publish_config_update()

        if published:
            print("[PASS] Configuration published to Redis")

            # Close connection
            if controller.redis:
                await controller.redis.aclose()

            return True
        else:
            print("[FAIL] Failed to publish configuration")
            return False
    else:
        print("[WARN] Redis not available - skipping test")
        return True  # Don't fail if Redis unavailable


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*80)
    print("TURBO SCALPER CONTROLLER - TEST SUITE")
    print("="*80)

    results = {}

    # Synchronous tests
    results['yaml_loading'] = test_yaml_loading()
    results['latency_monitoring'] = test_latency_monitoring()
    results['news_override'] = test_news_override()
    results['change_callbacks'] = test_change_callbacks()
    results['config_export'] = test_config_export()
    results['5s_time_tracking'] = test_5s_time_tracking()
    results['singleton_pattern'] = test_singleton_pattern()

    # Async test
    results['redis_integration'] = asyncio.run(test_redis_integration())

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_flag in results.items():
        status = "[PASS]" if passed_flag else "[FAIL]"
        print(f"{status} {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*80)

    return passed == total


if __name__ == '__main__':
    success = run_all_tests()
    exit(0 if success else 1)
