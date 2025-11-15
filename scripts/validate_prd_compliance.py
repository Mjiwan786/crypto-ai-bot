"""
Quick Validation Script for PRD-001 Signal Schema Compliance

This script validates that signals conform to PRD-001 specification.
Can be run to verify schema compliance before production deployment.

Usage:
    python scripts/validate_prd_compliance.py

Expected output:
    - ✅ All PRD-001 required fields present
    - ✅ Schema validation passes
    - ✅ Redis serialization works correctly
"""

import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.prd_signal_schema import PRDSignalSchema, validate_signal_for_publishing
from agents.core.signal_processor import ProcessedSignal, SignalAction, SignalQuality, ExecutionUrgency


def test_prd_compliant_signal():
    """Test creating a PRD-001 compliant signal directly"""
    print("=" * 70)
    print("Test 1: Direct PRD-001 Signal Creation")
    print("=" * 70)

    try:
        signal = PRDSignalSchema(
            timestamp=time.time(),
            signal_type="entry",
            trading_pair="BTC/USD",
            size=0.5,
            stop_loss=50000.0,
            take_profit=55000.0,
            confidence_score=0.85,
            agent_id="momentum_strategy"
        )

        print("✅ PRD-001 signal created successfully")
        print(f"\nSignal details:")
        print(f"  - timestamp: {signal.timestamp}")
        print(f"  - signal_type: {signal.signal_type}")
        print(f"  - trading_pair: {signal.trading_pair}")
        print(f"  - size: {signal.size}")
        print(f"  - stop_loss: {signal.stop_loss}")
        print(f"  - take_profit: {signal.take_profit}")
        print(f"  - confidence_score: {signal.confidence_score}")
        print(f"  - agent_id: {signal.agent_id}")

        # Test Redis serialization
        redis_data = signal.to_redis_dict()
        print(f"\n✅ Redis serialization successful")
        print(f"  - All {len(redis_data)} fields converted to strings")
        print(f"  - Ready for XADD to Redis stream")

        return True

    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_processed_signal_with_prd_schema():
    """Test ProcessedSignal with agent_id and PRD schema conversion"""
    print("\n" + "=" * 70)
    print("Test 2: ProcessedSignal with PRD-001 Compliance")
    print("=" * 70)

    try:
        # Create a ProcessedSignal (internal format)
        processed_signal = ProcessedSignal(
            signal_id="test_signal_001",
            timestamp=time.time(),
            pair="ETH/USD",
            action=SignalAction.BUY,
            quality=SignalQuality.EXCELLENT,
            urgency=ExecutionUrgency.HIGH,
            unified_signal=0.92,
            regime_state="trending",
            confidence=0.88,
            market_context={"regime": "trending", "volatility": "low"},
            ta_analysis={"rsi": 65, "macd": 0.05},
            sentiment_analysis={"score": 0.75, "trend": "bullish"},
            macro_analysis={"signal": 0.8, "notes": "strong"},
            price=3200.0,
            quantity=2.5,
            stop_loss=3000.0,
            take_profit=3500.0,
            target_strategy="momentum_v1",
            agent_id="signal_processor",  # PRD-001 required field
        )

        print("✅ ProcessedSignal created with agent_id")
        print(f"  - agent_id: {processed_signal.agent_id}")

        # Convert to PRD-001 schema
        prd_data = processed_signal.to_prd_schema()

        print(f"\n✅ Converted to PRD-001 schema")
        print(f"  - timestamp: {prd_data['timestamp']}")
        print(f"  - signal_type: {prd_data['signal_type']}")
        print(f"  - trading_pair: {prd_data['trading_pair']}")
        print(f"  - size: {prd_data['size']}")
        print(f"  - stop_loss: {prd_data['stop_loss']}")
        print(f"  - take_profit: {prd_data['take_profit']}")
        print(f"  - confidence_score: {prd_data['confidence_score']}")
        print(f"  - agent_id: {prd_data['agent_id']}")

        # Validate
        validated = validate_signal_for_publishing(prd_data)
        print(f"\n✅ PRD-001 schema validation PASSED")

        return True

    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_legacy_signal_conversion():
    """Test conversion from legacy signal format"""
    print("\n" + "=" * 70)
    print("Test 3: Legacy Signal Conversion to PRD-001")
    print("=" * 70)

    try:
        # Simulate legacy signal format (pre-PRD compliance)
        legacy_signal = {
            "timestamp": time.time(),
            "pair": "SOL/USD",  # Legacy: "pair"
            "action": "sell",  # Legacy: "action"
            "quantity": 10.0,  # Legacy: "quantity"
            "stop_loss": 155.0,
            "take_profit": 145.0,
            "ai_confidence": 0.79,  # Legacy: "ai_confidence"
            "strategy": "mean_reversion"  # Legacy: "strategy"
        }

        print("Legacy signal format:")
        for key, value in legacy_signal.items():
            print(f"  - {key}: {value}")

        # Convert to PRD-001
        prd_signal = PRDSignalSchema.from_legacy_signal(legacy_signal)

        print(f"\n✅ Converted to PRD-001 format")
        print(f"  - timestamp: {prd_signal.timestamp} (kept)")
        print(f"  - signal_type: {prd_signal.signal_type} (was 'action')")
        print(f"  - trading_pair: {prd_signal.trading_pair} (was 'pair')")
        print(f"  - size: {prd_signal.size} (was 'quantity')")
        print(f"  - confidence_score: {prd_signal.confidence_score} (was 'ai_confidence')")
        print(f"  - agent_id: {prd_signal.agent_id} (was 'strategy')")

        return True

    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_all_required_fields_present():
    """Verify all PRD-001 required fields are present"""
    print("\n" + "=" * 70)
    print("Test 4: All PRD-001 Required Fields Present")
    print("=" * 70)

    required_fields = [
        "timestamp",
        "signal_type",
        "trading_pair",
        "size",
        "confidence_score",
        "agent_id"
    ]

    try:
        signal = PRDSignalSchema(
            timestamp=time.time(),
            signal_type="entry",
            trading_pair="BTC/USD",
            size=0.5,
            confidence_score=0.85,
            agent_id="test_agent"
        )

        signal_dict = signal.model_dump()

        missing_fields = []
        for field in required_fields:
            if field not in signal_dict:
                missing_fields.append(field)
            else:
                print(f"  ✅ {field}: {signal_dict[field]}")

        if missing_fields:
            print(f"\n❌ FAILED: Missing required fields: {missing_fields}")
            return False

        print(f"\n✅ All {len(required_fields)} required PRD-001 fields present")
        return True

    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_agent_id_requirement():
    """Test that agent_id is required (cannot be omitted)"""
    print("\n" + "=" * 70)
    print("Test 5: Agent ID Requirement Validation")
    print("=" * 70)

    try:
        # Attempt to create signal without agent_id (should fail)
        signal = PRDSignalSchema(
            timestamp=time.time(),
            signal_type="entry",
            trading_pair="BTC/USD",
            size=0.5,
            confidence_score=0.85
            # Missing: agent_id
        )

        print(f"❌ FAILED: Should have raised validation error for missing agent_id")
        return False

    except Exception as e:
        if "agent_id" in str(e).lower():
            print(f"✅ Correctly rejected signal without agent_id")
            print(f"   Error message: {str(e)[:100]}...")
            return True
        else:
            print(f"❌ FAILED with unexpected error: {e}")
            return False


def main():
    """Run all validation tests"""
    print("\n" + "🔬" * 35)
    print("PRD-001 Signal Schema Compliance Validation")
    print("🔬" * 35 + "\n")

    tests = [
        ("Direct PRD-001 Signal Creation", test_prd_compliant_signal),
        ("ProcessedSignal with PRD-001", test_processed_signal_with_prd_schema),
        ("Legacy Signal Conversion", test_legacy_signal_conversion),
        ("All Required Fields Present", test_all_required_fields_present),
        ("Agent ID Requirement", test_agent_id_requirement),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ Test '{test_name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print("\n" + "-" * 70)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED - PRD-001 COMPLIANCE VERIFIED")
        print("\nNext steps:")
        print("  1. Run integration tests: pytest tests/agents/test_signal_schema_compliance.py")
        print("  2. Start signal_processor and verify live signals")
        print("  3. Monitor Redis streams for PRD-001 compliance")
        return 0
    else:
        print(f"\n⚠️  {total - passed} TEST(S) FAILED - FIX REQUIRED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
