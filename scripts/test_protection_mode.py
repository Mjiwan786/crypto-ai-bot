#!/usr/bin/env python3
"""
Protection Mode Test Suite

Tests protection mode activation, deactivation, and parameter adjustments.

Usage:
    python scripts/test_protection_mode.py --test all
    python scripts/test_protection_mode.py --test equity
    python scripts/test_protection_mode.py --test win-streak
    python scripts/test_protection_mode.py --test override
    python scripts/test_protection_mode.py --test api
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import argparse
import requests

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import redis.asyncio as aioredis
    from core.protection_mode import (
        ProtectionModeManager,
        ProtectionModeConfig,
        ProtectionModeStatus,
        ProtectionModeTrigger,
        create_protection_mode_from_config
    )
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're in the crypto_ai_bot directory and have installed dependencies")
    sys.exit(1)


class ProtectionModeTests:
    """Protection mode test suite"""

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or "rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
        self.redis_client: aioredis.Redis = None

        # Test results
        self.passed = 0
        self.failed = 0
        self.results = []

    async def setup(self):
        """Setup Redis connection"""
        print("🔧 Setting up test environment...")

        try:
            self.redis_client = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis_client.ping()
            print("✅ Connected to Redis")

            # Clear test keys
            await self.redis_client.delete("protection:mode:override")
            await self.redis_client.delete("protection:mode:state")
            print("✅ Cleared test keys")

        except Exception as e:
            print(f"❌ Setup failed: {e}")
            raise

    async def teardown(self):
        """Cleanup"""
        print("\n🧹 Cleaning up...")

        if self.redis_client:
            # Clear test keys
            await self.redis_client.delete("protection:mode:override")
            await self.redis_client.delete("protection:mode:state")
            await self.redis_client.close()
            print("✅ Cleaned up Redis keys")

    def assert_true(self, condition: bool, message: str):
        """Assert a condition is true"""
        if condition:
            self.passed += 1
            self.results.append(f"✅ PASS: {message}")
            print(f"  ✅ {message}")
        else:
            self.failed += 1
            self.results.append(f"❌ FAIL: {message}")
            print(f"  ❌ {message}")

    def assert_equals(self, actual, expected, message: str):
        """Assert two values are equal"""
        if actual == expected:
            self.passed += 1
            self.results.append(f"✅ PASS: {message}")
            print(f"  ✅ {message}")
        else:
            self.failed += 1
            self.results.append(f"❌ FAIL: {message} (expected: {expected}, actual: {actual})")
            print(f"  ❌ {message} (expected: {expected}, actual: {actual})")

    async def test_equity_threshold_activation(self):
        """Test: Protection mode activates when equity ≥ $18k"""
        print("\n📊 Test: Equity Threshold Activation")

        config = ProtectionModeConfig(
            enabled=True,
            equity_threshold_usd=18000.0,
            win_streak_threshold=5,
            risk_multiplier=0.5,
            sl_multiplier=0.7,
            rate_multiplier=0.5
        )

        manager = ProtectionModeManager(config, self.redis_client, starting_equity=10000.0)

        # Test 1: Below threshold - should NOT activate
        state = await manager.check_and_update(current_equity=17500.0)
        self.assert_equals(state.status, ProtectionModeStatus.DISABLED, "Status is DISABLED when equity < $18k")
        self.assert_equals(state.risk_multiplier, 1.0, "Risk multiplier is 1.0 (normal)")

        # Test 2: At threshold - should activate
        state = await manager.check_and_update(current_equity=18000.0)
        self.assert_equals(state.status, ProtectionModeStatus.ENABLED, "Status is ENABLED when equity = $18k")
        self.assert_equals(state.trigger, ProtectionModeTrigger.EQUITY_THRESHOLD, "Trigger is EQUITY_THRESHOLD")
        self.assert_equals(state.risk_multiplier, 0.5, "Risk multiplier is 0.5 (halved)")
        self.assert_equals(state.sl_multiplier, 0.7, "SL multiplier is 0.7 (tightened)")

        # Test 3: Above threshold - should remain active
        state = await manager.check_and_update(current_equity=19000.0)
        self.assert_equals(state.status, ProtectionModeStatus.ENABLED, "Status remains ENABLED when equity > $18k")

    async def test_win_streak_activation(self):
        """Test: Protection mode activates after 5 consecutive wins"""
        print("\n🎯 Test: Win Streak Activation")

        config = ProtectionModeConfig(
            enabled=True,
            equity_threshold_usd=18000.0,
            win_streak_threshold=5,
            risk_multiplier=0.5
        )

        manager = ProtectionModeManager(config, self.redis_client, starting_equity=10000.0)

        # Test 1: 4 wins - should NOT activate
        trades = [
            {'pnl_usd': 50.0, 'closed_at': '2025-11-08T01:00:00Z'},
            {'pnl_usd': 30.0, 'closed_at': '2025-11-08T02:00:00Z'},
            {'pnl_usd': 20.0, 'closed_at': '2025-11-08T03:00:00Z'},
            {'pnl_usd': 40.0, 'closed_at': '2025-11-08T04:00:00Z'},
        ]
        state = await manager.check_and_update(current_equity=15000.0, recent_trades=trades)
        self.assert_equals(state.status, ProtectionModeStatus.DISABLED, "Status is DISABLED with 4 wins")
        self.assert_equals(state.current_win_streak, 4, "Win streak is 4")

        # Test 2: 5 wins - should activate
        trades.append({'pnl_usd': 25.0, 'closed_at': '2025-11-08T05:00:00Z'})
        state = await manager.check_and_update(current_equity=15000.0, recent_trades=trades)
        self.assert_equals(state.status, ProtectionModeStatus.ENABLED, "Status is ENABLED with 5 wins")
        self.assert_equals(state.trigger, ProtectionModeTrigger.WIN_STREAK, "Trigger is WIN_STREAK")
        self.assert_equals(state.current_win_streak, 5, "Win streak is 5")

        # Test 3: Loss breaks streak
        trades.insert(0, {'pnl_usd': -10.0, 'closed_at': '2025-11-08T06:00:00Z'})
        manager.recent_trades = trades
        state = await manager.check_and_update(current_equity=15000.0, recent_trades=trades)
        self.assert_equals(state.current_win_streak, 0, "Win streak reset to 0 after loss")

    async def test_manual_override(self):
        """Test: Manual override via Redis"""
        print("\n🔧 Test: Manual Override")

        config = ProtectionModeConfig(
            enabled=True,
            equity_threshold_usd=18000.0,
            win_streak_threshold=5
        )

        manager = ProtectionModeManager(config, self.redis_client, starting_equity=10000.0)

        # Test 1: Force enable via Redis
        await self.redis_client.set("protection:mode:override", "force_enabled")
        state = await manager.check_and_update(current_equity=12000.0)
        self.assert_equals(state.status, ProtectionModeStatus.FORCE_ENABLED, "Status is FORCE_ENABLED via Redis override")

        # Test 2: Force disable via Redis
        await self.redis_client.set("protection:mode:override", "force_disabled")
        state = await manager.check_and_update(current_equity=20000.0)
        self.assert_equals(state.status, ProtectionModeStatus.FORCE_DISABLED, "Status is FORCE_DISABLED even with equity > $18k")

        # Test 3: Clear override
        await self.redis_client.delete("protection:mode:override")
        state = await manager.check_and_update(current_equity=20000.0)
        self.assert_equals(state.status, ProtectionModeStatus.ENABLED, "Status is ENABLED after override cleared")

    async def test_parameter_adjustments(self):
        """Test: Parameter adjustments are applied correctly"""
        print("\n⚙️  Test: Parameter Adjustments")

        config = ProtectionModeConfig(
            enabled=True,
            equity_threshold_usd=18000.0,
            risk_multiplier=0.5,
            sl_multiplier=0.7,
            tp_multiplier=0.8,
            rate_multiplier=0.5
        )

        manager = ProtectionModeManager(config, self.redis_client, starting_equity=10000.0)

        # Activate protection mode
        await manager.check_and_update(current_equity=18500.0)

        # Test adjustments
        base_params = {
            'risk_per_trade_pct': 1.2,
            'sl_atr': 1.5,
            'tp1_atr': 2.5,
            'max_trades_per_minute': 10
        }

        adjusted = manager.get_adjusted_params(base_params)

        self.assert_equals(adjusted['risk_per_trade_pct'], 0.6, "Risk reduced from 1.2% to 0.6%")
        self.assert_equals(adjusted['sl_atr'], 1.05, "SL tightened from 1.5 to 1.05 ATR")
        self.assert_equals(adjusted['tp1_atr'], 2.0, "TP1 tightened from 2.5 to 2.0 ATR")
        self.assert_equals(adjusted['max_trades_per_minute'], 5, "Trade rate reduced from 10 to 5/min")

    async def test_deactivation_logic(self):
        """Test: Deactivation when equity drops"""
        print("\n📉 Test: Deactivation Logic")

        config = ProtectionModeConfig(
            enabled=True,
            equity_threshold_usd=18000.0,
            deactivate_below_equity=17000.0,
            win_streak_threshold=5
        )

        manager = ProtectionModeManager(config, self.redis_client, starting_equity=10000.0)

        # Activate at $18k
        state = await manager.check_and_update(current_equity=18000.0)
        self.assert_equals(state.status, ProtectionModeStatus.ENABLED, "Status is ENABLED at $18k")

        # Drop to $17.5k - should remain active
        state = await manager.check_and_update(current_equity=17500.0)
        self.assert_equals(state.status, ProtectionModeStatus.ENABLED, "Status remains ENABLED at $17.5k")

        # Drop to $16.5k - should deactivate
        state = await manager.check_and_update(current_equity=16500.0)
        self.assert_equals(state.status, ProtectionModeStatus.DISABLED, "Status is DISABLED below $17k")
        self.assert_equals(state.risk_multiplier, 1.0, "Risk multiplier reset to 1.0")

    async def test_redis_state_publishing(self):
        """Test: State is published to Redis"""
        print("\n📡 Test: Redis State Publishing")

        config = ProtectionModeConfig(enabled=True, equity_threshold_usd=18000.0)
        manager = ProtectionModeManager(config, self.redis_client, starting_equity=10000.0)

        # Activate
        await manager.check_and_update(current_equity=18500.0)

        # Check Redis state
        state = await self.redis_client.hgetall("protection:mode:state")
        self.assert_true(state is not None, "State is published to Redis")
        self.assert_equals(state.get('status'), 'enabled', "Redis state shows 'enabled'")
        self.assert_equals(float(state.get('current_equity', 0)), 18500.0, "Redis state has correct equity")

        # Check events stream
        events = await self.redis_client.xrevrange("protection:mode:events", "+", "-", count=1)
        self.assert_true(len(events) > 0, "Event published to stream")

    def test_api_endpoints(self):
        """Test: API endpoints for runtime override"""
        print("\n🌐 Test: API Endpoints")

        api_url = "https://crypto-signals-api.fly.dev"

        # Test 1: Get status
        try:
            response = requests.get(f"{api_url}/protection-mode/status", timeout=5)
            self.assert_equals(response.status_code, 200, "GET /protection-mode/status returns 200")

            data = response.json()
            self.assert_true('status' in data, "Response contains 'status' field")
            self.assert_true('current_equity' in data, "Response contains 'current_equity' field")
        except Exception as e:
            print(f"  ⚠️  API test skipped (API not accessible): {e}")

        # Test 2: Set override (enable)
        try:
            response = requests.post(
                f"{api_url}/protection-mode/override",
                json={"action": "enable", "reason": "Test activation"},
                timeout=5
            )
            self.assert_equals(response.status_code, 200, "POST /protection-mode/override (enable) returns 200")

            data = response.json()
            self.assert_true(data.get('success'), "Override set successfully")
            self.assert_equals(data.get('override_set'), 'force_enabled', "Override set to 'force_enabled'")
        except Exception as e:
            print(f"  ⚠️  API test skipped (API not accessible): {e}")

        # Test 3: Clear override
        try:
            response = requests.delete(f"{api_url}/protection-mode/override", timeout=5)
            self.assert_equals(response.status_code, 200, "DELETE /protection-mode/override returns 200")

            data = response.json()
            self.assert_true(data.get('success'), "Override cleared successfully")
        except Exception as e:
            print(f"  ⚠️  API test skipped (API not accessible): {e}")

    async def run_all_tests(self):
        """Run all tests"""
        print("\n" + "="*80)
        print("PROTECTION MODE TEST SUITE")
        print("="*80)

        await self.setup()

        try:
            await self.test_equity_threshold_activation()
            await self.test_win_streak_activation()
            await self.test_manual_override()
            await self.test_parameter_adjustments()
            await self.test_deactivation_logic()
            await self.test_redis_state_publishing()
            self.test_api_endpoints()

        finally:
            await self.teardown()

        # Print summary
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        print(f"✅ Passed: {self.passed}")
        print(f"❌ Failed: {self.failed}")
        print(f"📊 Total:  {self.passed + self.failed}")
        print("="*80)

        if self.failed > 0:
            print("\n❌ SOME TESTS FAILED")
            sys.exit(1)
        else:
            print("\n✅ ALL TESTS PASSED")
            sys.exit(0)


async def main():
    parser = argparse.ArgumentParser(description='Test protection mode functionality')
    parser.add_argument(
        '--test',
        choices=['all', 'equity', 'win-streak', 'override', 'params', 'deactivation', 'redis', 'api'],
        default='all',
        help='Which test to run'
    )
    parser.add_argument(
        '--redis-url',
        default=None,
        help='Redis URL (default: Redis Cloud)'
    )

    args = parser.parse_args()

    tests = ProtectionModeTests(redis_url=args.redis_url)

    if args.test == 'all':
        await tests.run_all_tests()
    else:
        await tests.setup()
        try:
            if args.test == 'equity':
                await tests.test_equity_threshold_activation()
            elif args.test == 'win-streak':
                await tests.test_win_streak_activation()
            elif args.test == 'override':
                await tests.test_manual_override()
            elif args.test == 'params':
                await tests.test_parameter_adjustments()
            elif args.test == 'deactivation':
                await tests.test_deactivation_logic()
            elif args.test == 'redis':
                await tests.test_redis_state_publishing()
            elif args.test == 'api':
                tests.test_api_endpoints()
        finally:
            await tests.teardown()

        # Print summary for single test
        print("\n" + "="*80)
        print(f"✅ Passed: {tests.passed}")
        print(f"❌ Failed: {tests.failed}")
        print("="*80)


if __name__ == '__main__':
    asyncio.run(main())
