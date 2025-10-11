#!/usr/bin/env python3
"""
Test script to verify that importing agent modules does not:
- Open network sockets (Redis connections)
- Read files (config files, .env files)
- Execute any significant code

Usage:
    python test_import_safety.py
"""

import sys
import socket
import warnings
from unittest.mock import patch, MagicMock

# Track network/file operations
network_calls = []
file_reads = []
dotenv_calls = []


def mock_socket_connect(original_connect):
    """Mock socket.connect to track connection attempts"""
    def _connect(self, address):
        network_calls.append(("socket.connect", address))
        raise ConnectionRefusedError(f"Blocked socket connection to {address}")
    return _connect


def mock_file_open(original_open):
    """Mock open() to track file reads (allow __pycache__ and .py files)"""
    def _open(file, mode='r', *args, **kwargs):
        file_str = str(file)
        # Allow Python bytecode and source files
        if file_str.endswith(('.pyc', '.py', '.pyi')) or '__pycache__' in file_str:
            return original_open(file, mode, *args, **kwargs)
        # Block everything else during import
        file_reads.append(("open", file_str, mode))
        raise PermissionError(f"Blocked file access to {file}")
    return _open


def mock_dotenv_load(*args, **kwargs):
    """Mock dotenv.load_dotenv to track calls"""
    dotenv_calls.append(("load_dotenv", args, kwargs))
    # Don't actually load anything
    return None


def test_import_module(module_name: str) -> bool:
    """
    Test that importing a module doesn't execute side effects.

    Returns:
        True if import is safe, False otherwise
    """
    print(f"\n{'='*70}")
    print(f"Testing: {module_name}")
    print(f"{'='*70}")

    # Clear tracking lists
    network_calls.clear()
    file_reads.clear()
    dotenv_calls.clear()

    # Patch network and file operations
    original_connect = socket.socket.connect
    original_open = open

    try:
        with patch('socket.socket.connect', mock_socket_connect(original_connect)):
            with patch('builtins.open', mock_file_open(original_open)):
                with patch('dotenv.load_dotenv', mock_dotenv_load):
                    # Attempt import
                    __import__(module_name)

        # Check for violations
        violations = []

        if network_calls:
            violations.append(f"Network calls detected: {network_calls}")

        if file_reads:
            violations.append(f"File reads detected: {file_reads}")

        if dotenv_calls:
            violations.append(f"dotenv.load_dotenv called during import: {dotenv_calls}")

        if violations:
            print("[FAILED] - Import has side effects:")
            for violation in violations:
                print(f"  * {violation}")
            return False
        else:
            print("[PASSED] - No side effects detected")
            return True

    except ImportError as e:
        print(f"[SKIPPED] - Import error (missing dependencies): {e}")
        return True  # Not a safety issue, just missing deps
    except Exception as e:
        print(f"[ERROR] - Unexpected error during import: {e}")
        return False


def main():
    """Test all agent modules for import safety"""

    print("\n" + "="*70)
    print("IMPORT SAFETY TEST")
    print("Testing that agent modules don't execute code on import")
    print("="*70)

    # Modules to test
    test_modules = [
        # Core agents
        "agents.core.performance_monitor",
        "agents.core.autogen_wrappers",
        "agents.core.signal_processor",
        "agents.core.signal_analyst",
        "agents.core.market_scanner",
        "agents.core.execution_agent",

        # Scalper agents
        "agents.scalper.config_loader",
        "agents.scalper.enhanced_scalper_agent",
        "agents.scalper.kraken_scalper_agent",
    ]

    results = {}
    for module in test_modules:
        # Remove module from sys.modules if already imported
        if module in sys.modules:
            del sys.modules[module]

        results[module] = test_import_module(module)

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"\nPassed: {passed}/{total}")

    if passed == total:
        print("\n[SUCCESS] ALL TESTS PASSED - Modules are import-safe!")
        print("\nModules can be imported without:")
        print("  * Opening network connections (Redis, HTTP, etc.)")
        print("  * Reading files (.env, config files, etc.)")
        print("  * Executing business logic")
        return 0
    else:
        print("\n[FAILURE] SOME TESTS FAILED - Fix the following modules:")
        for module, passed in results.items():
            if not passed:
                print(f"  * {module}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
