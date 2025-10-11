#!/usr/bin/env python3
"""
Test script to verify clean API surfaces with __all__ exports.

This demonstrates:
1. Clean __all__ definitions
2. Proper module exports
3. No missing exports
"""

import sys


def test_core_exports():
    """Test agents.core exports."""
    print("=" * 70)
    print("Testing agents.core exports")
    print("=" * 70)

    from agents import core

    # Check __all__ is defined
    assert hasattr(core, "__all__"), "agents.core missing __all__"
    print(f"\n[OK] __all__ defined with {len(core.__all__)} exports")
    print(f"  Exports: {', '.join(core.__all__)}")

    # Verify all exported modules can be imported
    print("\n[OK] Verifying module imports:")
    for module_name in core.__all__:
        try:
            __import__(f"agents.core.{module_name}")
            print(f"    [OK] {module_name}")
        except ImportError as e:
            print(f"    [FAIL] {module_name} - {e}")
            return False

    print("\n[OK] agents.core exports validated")
    return True


def test_infrastructure_exports():
    """Test agents.infrastructure exports."""
    print("\n" + "=" * 70)
    print("Testing agents.infrastructure exports")
    print("=" * 70)

    from agents import infrastructure

    assert hasattr(infrastructure, "__all__"), "agents.infrastructure missing __all__"
    print(f"\n[OK] __all__ defined with {len(infrastructure.__all__)} exports")
    print(f"  Exports: {', '.join(infrastructure.__all__)}")

    print("\n[OK] Verifying module imports:")
    for module_name in infrastructure.__all__:
        try:
            __import__(f"agents.infrastructure.{module_name}")
            print(f"    [OK] {module_name}")
        except ImportError as e:
            print(f"    [FAIL] {module_name} - {e}")
            return False

    print("\n[OK] agents.infrastructure exports validated")
    return True


def test_risk_exports():
    """Test agents.risk exports."""
    print("\n" + "=" * 70)
    print("Testing agents.risk exports")
    print("=" * 70)

    from agents import risk

    assert hasattr(risk, "__all__"), "agents.risk missing __all__"
    print(f"\n[OK] __all__ defined with {len(risk.__all__)} exports")
    print(f"  Exports: {', '.join(risk.__all__)}")

    print("\n[OK] Verifying module imports:")
    for module_name in risk.__all__:
        try:
            __import__(f"agents.risk.{module_name}")
            print(f"    [OK] {module_name}")
        except ImportError as e:
            print(f"    [FAIL] {module_name} - {e}")
            return False

    print("\n[OK] agents.risk exports validated")
    return True


def main():
    """Run all export tests."""
    print("\n" + "=" * 70)
    print("TESTING CLEAN API SURFACES WITH __all__ EXPORTS")
    print("=" * 70)

    try:
        # Run tests
        results = [
            test_core_exports(),
            test_infrastructure_exports(),
            test_risk_exports(),
        ]

        if not all(results):
            print("\n[FAIL] SOME TESTS FAILED")
            return 1

        # Summary
        print("\n" + "=" * 70)
        print("[OK] ALL TESTS PASSED")
        print("=" * 70)
        print("\nBenefits:")
        print("  [OK] Clean autocomplete in IDEs")
        print("  [OK] No star-import lint warnings")
        print("  [OK] Clear public API surface")
        print("  [OK] Explicit module exports")
        print("\nUsage examples:")
        print("  from agents.core import execution_agent")
        print("  from agents.infrastructure import redis_client")
        print("  from agents.risk import risk_router")
        print("=" * 70)

        return 0

    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
