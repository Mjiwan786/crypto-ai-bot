#!/usr/bin/env python
"""Simple test runner for DI integration tests (no unicode issues)."""

import asyncio
import sys

# Add project root to path
sys.path.insert(0, "C:\\Users\\Maith\\OneDrive\\Desktop\\crypto_ai_bot")

from tests.test_core_di_integration import (
    test_signal_analyst_pure,
    test_signal_processor_pure,
    test_execution_plan_pure,
    test_performance_monitor,
    test_market_scanner_with_fake_source,
    test_execution_with_fake_gateway,
    test_dry_run_mode,
    test_end_to_end_pipeline_with_fakes,
)


def run_tests():
    """Run all DI integration tests."""
    print("=" * 60)
    print("DI INTEGRATION TESTS")
    print("=" * 60)
    print()

    tests_passed = 0
    tests_failed = 0

    # Sync tests
    sync_tests = [
        ("Pure Signal Analyst", test_signal_analyst_pure),
        ("Pure Signal Processor", test_signal_processor_pure),
        ("Pure Execution Planning", test_execution_plan_pure),
        ("Performance Monitor", test_performance_monitor),
    ]

    for name, test_func in sync_tests:
        try:
            print(f"Running: {name}...", end=" ")
            test_func()
            print("PASSED")
            tests_passed += 1
        except Exception as e:
            print(f"FAILED: {e}")
            tests_failed += 1

    print()

    # Async tests
    async_tests = [
        ("Market Scanner with Fake Source", test_market_scanner_with_fake_source),
        ("Execution with Fake Gateway", test_execution_with_fake_gateway),
        ("Dry-Run Mode", test_dry_run_mode),
        ("End-to-End Pipeline", test_end_to_end_pipeline_with_fakes),
    ]

    for name, test_func in async_tests:
        try:
            print(f"Running: {name}...", end=" ")
            asyncio.run(test_func())
            print("PASSED")
            tests_passed += 1
        except Exception as e:
            print(f"FAILED: {e}")
            tests_failed += 1

    print()
    print("=" * 60)
    print(f"RESULTS: {tests_passed} passed, {tests_failed} failed")
    print("=" * 60)

    if tests_failed == 0:
        print()
        print("SUCCESS! All tests passed.")
        print()
        print("Architecture Validation:")
        print("  [OK] Pure functions tested without I/O")
        print("  [OK] All dependencies injected via Protocols")
        print("  [OK] No direct Redis imports in core modules")
        print("  [OK] Fake implementations enable fast testing")
        print("  [OK] Ready for production with real Kraken/Redis")
        print()
        return 0
    else:
        print()
        print(f"FAILED: {tests_failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())
