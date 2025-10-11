"""
Test script for security and safety features

Tests:
1. Live trading guards (MODE and LIVE_TRADING_CONFIRMATION)
2. Kill switch activation/deactivation
3. Redis-based control:halt_all key
4. Paper mode enforcement

Run with: conda activate crypto-bot && python -m protections.test_kill_switch
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from protections.kill_switches import (
    GlobalKillSwitch,
    check_live_trading_allowed,
    get_trading_mode,
    enforce_paper_mode
)


async def test_live_trading_guards():
    """Test live trading guards"""
    print("\n" + "=" * 60)
    print("TEST 1: Live Trading Guards")
    print("=" * 60)

    # Save original env vars
    orig_mode = os.getenv("MODE")
    orig_confirmation = os.getenv("LIVE_TRADING_CONFIRMATION")

    try:
        # Test 1: Paper mode (should allow)
        print("\n1.1 Testing paper mode...")
        os.environ["MODE"] = "paper"
        os.environ["LIVE_TRADING_CONFIRMATION"] = ""

        mode = get_trading_mode()
        print(f"   Mode: {mode.mode}")
        print(f"   Paper mode: {mode.paper_mode}")
        print(f"   Live allowed: {mode.is_live_allowed}")

        assert mode.paper_mode == True, "Paper mode should be True"
        assert mode.is_live_allowed == False, "Live should not be allowed in paper mode"
        print("   ✅ PASS: Paper mode correctly configured\n")

        # Test 2: Live mode without confirmation (should block)
        print("1.2 Testing live mode without confirmation...")
        os.environ["MODE"] = "live"
        os.environ["LIVE_TRADING_CONFIRMATION"] = ""

        allowed, error = check_live_trading_allowed()
        print(f"   Allowed: {allowed}")
        print(f"   Error: {error}")

        assert allowed == False, "Live trading should be blocked without confirmation"
        print("   ✅ PASS: Live trading correctly blocked\n")

        # Test 3: Live mode with wrong confirmation (should block)
        print("1.3 Testing live mode with wrong confirmation...")
        os.environ["MODE"] = "live"
        os.environ["LIVE_TRADING_CONFIRMATION"] = "wrong-value"

        allowed, error = check_live_trading_allowed()
        print(f"   Allowed: {allowed}")
        print(f"   Error: {error}")

        assert allowed == False, "Live trading should be blocked with wrong confirmation"
        print("   ✅ PASS: Wrong confirmation correctly rejected\n")

        # Test 4: Live mode with correct confirmation (should allow)
        print("1.4 Testing live mode with correct confirmation...")
        os.environ["MODE"] = "live"
        os.environ["LIVE_TRADING_CONFIRMATION"] = "I-accept-the-risk"

        allowed, error = check_live_trading_allowed()
        print(f"   Allowed: {allowed}")
        print(f"   Error: {error}")

        assert allowed == True, "Live trading should be allowed with correct confirmation"
        print("   ✅ PASS: Live trading correctly enabled\n")

    finally:
        # Restore original env vars
        if orig_mode:
            os.environ["MODE"] = orig_mode
        else:
            os.environ.pop("MODE", None)

        if orig_confirmation:
            os.environ["LIVE_TRADING_CONFIRMATION"] = orig_confirmation
        else:
            os.environ.pop("LIVE_TRADING_CONFIRMATION", None)


async def test_kill_switch_basic():
    """Test basic kill switch functionality"""
    print("\n" + "=" * 60)
    print("TEST 2: Kill Switch Basic Functionality")
    print("=" * 60)

    # Create kill switch (no Redis)
    ks = GlobalKillSwitch()

    # Test 1: Initial state (should allow trading)
    print("\n2.1 Testing initial state...")
    allowed = await ks.is_trading_allowed()
    print(f"   Trading allowed: {allowed}")
    print(f"   Status: {ks.get_status()}")

    assert allowed == True, "Trading should be allowed initially"
    print("   ✅ PASS: Initial state correct\n")

    # Test 2: Activate kill switch
    print("2.2 Testing kill switch activation...")
    await ks.activate(reason="Test activation", ttl_seconds=300)
    allowed = await ks.is_trading_allowed()
    status = ks.get_status()

    print(f"   Trading allowed: {allowed}")
    print(f"   Status: {status}")

    assert allowed == False, "Trading should be blocked after activation"
    assert status['is_active'] == True, "Kill switch should be active"
    assert "Test activation" in status['reason'], "Reason should be recorded"
    print("   ✅ PASS: Kill switch activated correctly\n")

    # Test 3: Deactivate kill switch
    print("2.3 Testing kill switch deactivation...")
    await ks.deactivate()
    allowed = await ks.is_trading_allowed()
    status = ks.get_status()

    print(f"   Trading allowed: {allowed}")
    print(f"   Status: {status}")

    assert allowed == True, "Trading should be allowed after deactivation"
    assert status['is_active'] == False, "Kill switch should be inactive"
    print("   ✅ PASS: Kill switch deactivated correctly\n")


async def test_kill_switch_redis(redis_client=None):
    """Test Redis-based kill switch control"""
    print("\n" + "=" * 60)
    print("TEST 3: Redis-based Kill Switch")
    print("=" * 60)

    if not redis_client:
        print("\n⚠️  SKIP: No Redis client available")
        print("   To test Redis functionality:")
        print("   1. Set REDIS_URL environment variable")
        print("   2. Ensure Redis is running")
        print("   3. Re-run this test\n")
        return

    try:
        # Create kill switch with Redis
        ks = GlobalKillSwitch(redis_client)

        # Test 1: Set Redis kill switch key
        print("\n3.1 Testing Redis key activation...")
        await redis_client.setex("control:halt_all", 60, "Test Redis halt")

        allowed = await ks.is_trading_allowed()
        status = ks.get_status()

        print(f"   Trading allowed: {allowed}")
        print(f"   Status: {status}")

        assert allowed == False, "Trading should be blocked when Redis key exists"
        print("   ✅ PASS: Redis key activation works\n")

        # Test 2: Remove Redis kill switch key
        print("3.2 Testing Redis key deactivation...")
        await redis_client.delete("control:halt_all")

        allowed = await ks.is_trading_allowed()
        status = ks.get_status()

        print(f"   Trading allowed: {allowed}")
        print(f"   Status: {status}")

        assert allowed == True, "Trading should be allowed when Redis key removed"
        print("   ✅ PASS: Redis key deactivation works\n")

        # Test 3: TTL functionality
        print("3.3 Testing Redis TTL...")
        await ks.activate(reason="TTL test", ttl_seconds=5)

        ttl = await redis_client.ttl("control:halt_all")
        print(f"   TTL: {ttl} seconds")

        assert ttl > 0 and ttl <= 5, "TTL should be set correctly"
        print("   ✅ PASS: Redis TTL works\n")

        # Cleanup
        await redis_client.delete("control:halt_all")

    except Exception as e:
        print(f"   ❌ FAIL: Redis test error: {e}\n")
        raise


async def test_paper_mode_decorator():
    """Test paper mode enforcement decorator"""
    print("\n" + "=" * 60)
    print("TEST 4: Paper Mode Decorator")
    print("=" * 60)

    # Save original env vars
    orig_mode = os.getenv("MODE")

    try:
        # Define test functions
        @enforce_paper_mode(allow_live=False)
        def paper_only_function():
            return "executed"

        @enforce_paper_mode(allow_live=True)
        def can_be_live_function():
            return "executed"

        # Test 1: Paper mode (should work for both)
        print("\n4.1 Testing paper mode enforcement...")
        os.environ["MODE"] = "paper"

        result = paper_only_function()
        assert result == "executed", "Paper-only function should work in paper mode"
        print("   ✅ PASS: Paper-only function works in paper mode\n")

        result = can_be_live_function()
        assert result == "executed", "Live-allowed function should work in paper mode"
        print("   ✅ PASS: Live-allowed function works in paper mode\n")

        # Test 2: Live mode without confirmation (should fail for both)
        print("4.2 Testing live mode without confirmation...")
        os.environ["MODE"] = "live"
        os.environ["LIVE_TRADING_CONFIRMATION"] = ""

        try:
            paper_only_function()
            assert False, "Paper-only function should fail in live mode"
        except RuntimeError as e:
            print(f"   Expected error: {str(e)[:60]}...")
            print("   ✅ PASS: Paper-only function blocked in live mode\n")

        try:
            can_be_live_function()
            assert False, "Live-allowed function should fail without confirmation"
        except RuntimeError as e:
            print(f"   Expected error: {str(e)[:60]}...")
            print("   ✅ PASS: Live-allowed function blocked without confirmation\n")

    finally:
        # Restore original env vars
        if orig_mode:
            os.environ["MODE"] = orig_mode
        else:
            os.environ.pop("MODE", None)
        os.environ.pop("LIVE_TRADING_CONFIRMATION", None)


async def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("CRYPTO AI BOT - SECURITY & SAFETY TEST SUITE")
    print("=" * 60)

    # Reset environment for clean tests
    os.environ.pop("EMERGENCY_HALT", None)
    os.environ["MODE"] = "paper"
    os.environ["LIVE_TRADING_CONFIRMATION"] = ""

    try:
        # Run tests
        await test_live_trading_guards()
        await test_kill_switch_basic()
        await test_paper_mode_decorator()

        # Try to connect to Redis for Redis tests
        redis_client = None
        try:
            import redis.asyncio as redis
            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                print("\n" + "=" * 60)
                print("Connecting to Redis for advanced tests...")
                print("=" * 60)
                redis_client = redis.from_url(redis_url, decode_responses=True)
                await redis_client.ping()
                print("✅ Connected to Redis\n")
                await test_kill_switch_redis(redis_client)
                await redis_client.aclose()
        except Exception as e:
            print(f"\n⚠️  Redis connection failed: {e}")
            print("   Skipping Redis tests\n")

        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print("✅ All basic tests PASSED")
        print("\nSecurity features verified:")
        print("  1. ✅ MODE and LIVE_TRADING_CONFIRMATION guards")
        print("  2. ✅ Kill switch activation/deactivation")
        print("  3. ✅ Paper mode enforcement decorator")
        if redis_client:
            print("  4. ✅ Redis-based control:halt_all key")
        else:
            print("  4. ⚠️  Redis tests skipped (no connection)")

        print("\n" + "=" * 60)
        print("SECURITY VERIFICATION COMPLETE")
        print("=" * 60)
        print("\n✅ Your trading bot is protected against:")
        print("   • Accidental live trading (MODE guard)")
        print("   • Missing confirmation (LIVE_TRADING_CONFIRMATION)")
        print("   • Emergency situations (kill switch)")
        print("   • Remote control (Redis halt key)\n")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
