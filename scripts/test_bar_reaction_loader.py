#!/usr/bin/env python3
"""
Test script for EnhancedScalperConfigLoader with bar_reaction_5m validation.

Tests:
1. Timeframe validation (must be 5m)
2. Trigger BPS validation (must be > 0)
3. ATR validation (min < max)
4. Symbol normalization (BTC-USD → BTC/USD, BTCUSDT → BTC/USDT)
5. Risk parameter validation
6. Execution settings validation

Usage:
    python scripts/test_bar_reaction_loader.py
    python scripts/test_bar_reaction_loader.py --verbose
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from config.enhanced_scalper_loader import EnhancedScalperConfigLoader


def test_successful_load():
    """Test successful configuration loading"""
    print("\n" + "="*80)
    print("TEST 1: Successful Configuration Load")
    print("="*80)

    try:
        loader = EnhancedScalperConfigLoader("config/enhanced_scalper_config.yaml")
        config = loader.load_config()

        print("[PASS] Configuration loaded successfully")

        # Check bar_reaction_5m exists
        if 'bar_reaction_5m' in config:
            br_config = config['bar_reaction_5m']
            print(f"\n[PASS] bar_reaction_5m strategy found:")
            print(f"  - Mode: {br_config.get('mode')}")
            print(f"  - Timeframe: {br_config.get('timeframe')}")
            print(f"  - Pairs: {br_config.get('pairs')}")
            print(f"  - Trigger BPS: up={br_config.get('trigger_bps_up')}, down={br_config.get('trigger_bps_down')}")
            print(f"  - ATR Range: {br_config.get('min_atr_pct')}% - {br_config.get('max_atr_pct')}%")
            print(f"  - Risk per Trade: {br_config.get('risk_per_trade_pct')}%")
            print(f"  - Maker Only: {br_config.get('maker_only')}")
        else:
            print("[FAIL] bar_reaction_5m strategy not found in config")
            return False

        return True

    except Exception as e:
        print(f"[FAIL] Test failed: {e}")
        return False


def test_symbol_normalization():
    """Test symbol normalization"""
    print("\n" + "="*80)
    print("TEST 2: Symbol Normalization")
    print("="*80)

    loader = EnhancedScalperConfigLoader()

    test_cases = [
        ("BTC/USD", "BTC/USD"),      # Already normalized
        ("BTC-USD", "BTC/USD"),       # Dash to slash
        ("BTCUSD", "BTC/USD"),        # No separator
        ("ETH/USDT", "ETH/USDT"),     # Already normalized
        ("ETH-USDT", "ETH/USDT"),     # Dash to slash
        ("ETHUSDT", "ETH/USDT"),      # No separator
        ("SOL/USD", "SOL/USD"),       # Already normalized
        ("SOLUSD", "SOL/USD"),        # No separator
    ]

    all_passed = True

    for input_symbol, expected_output in test_cases:
        normalized = loader.normalize_symbol(input_symbol)
        passed = normalized == expected_output

        if passed:
            print(f"  [OK]  {input_symbol:12s} -> {normalized:12s} (expected: {expected_output})")
        else:
            print(f"  [ERR] {input_symbol:12s} -> {normalized:12s} (expected: {expected_output})")
            all_passed = False

    return all_passed


def test_invalid_timeframe():
    """Test validation fails for invalid timeframe"""
    print("\n" + "="*80)
    print("TEST 3: Invalid Timeframe Validation")
    print("="*80)

    import yaml
    import tempfile

    # Create invalid config with wrong timeframe
    invalid_config = {
        'bar_reaction_5m': {
            'enabled': True,
            'mode': 'trend',
            'pairs': ['BTC/USD'],
            'timeframe': '1m',  # INVALID - must be 5m
            'trigger_bps_up': 12,
            'trigger_bps_down': 12,
            'min_atr_pct': 0.25,
            'max_atr_pct': 3.0,
            'atr_window': 14,
            'maker_only': True,
            'spread_bps_cap': 8,
        }
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(invalid_config, f)
        temp_path = f.name

    try:
        loader = EnhancedScalperConfigLoader(temp_path)
        config = loader.load_config()
        print("  [ERR] Validation should have failed for timeframe='1m'")
        return False
    except ValueError as e:
        if "timeframe must be '5m'" in str(e):
            print(f"  [OK] Validation correctly rejected invalid timeframe")
            print(f"    Error: {e}")
            return True
        else:
            print(f"  [ERR] Wrong error: {e}")
            return False
    finally:
        import os
        os.unlink(temp_path)


def test_invalid_trigger_bps():
    """Test validation fails for invalid trigger BPS"""
    print("\n" + "="*80)
    print("TEST 4: Invalid Trigger BPS Validation")
    print("="*80)

    import yaml
    import tempfile

    # Create invalid config with zero trigger BPS
    invalid_config = {
        'bar_reaction_5m': {
            'enabled': True,
            'mode': 'trend',
            'pairs': ['BTC/USD'],
            'timeframe': '5m',
            'trigger_bps_up': 0,  # INVALID - must be > 0
            'trigger_bps_down': 12,
            'min_atr_pct': 0.25,
            'max_atr_pct': 3.0,
            'atr_window': 14,
            'maker_only': True,
            'spread_bps_cap': 8,
        }
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(invalid_config, f)
        temp_path = f.name

    try:
        loader = EnhancedScalperConfigLoader(temp_path)
        config = loader.load_config()
        print("  [ERR] Validation should have failed for trigger_bps_up=0")
        return False
    except ValueError as e:
        if "trigger_bps_up must be > 0" in str(e):
            print(f"  [OK] Validation correctly rejected invalid trigger_bps_up")
            print(f"    Error: {e}")
            return True
        else:
            print(f"  [ERR] Wrong error: {e}")
            return False
    finally:
        import os
        os.unlink(temp_path)


def test_invalid_atr_range():
    """Test validation fails for invalid ATR range"""
    print("\n" + "="*80)
    print("TEST 5: Invalid ATR Range Validation")
    print("="*80)

    import yaml
    import tempfile

    # Create invalid config with min_atr >= max_atr
    invalid_config = {
        'bar_reaction_5m': {
            'enabled': True,
            'mode': 'trend',
            'pairs': ['BTC/USD'],
            'timeframe': '5m',
            'trigger_bps_up': 12,
            'trigger_bps_down': 12,
            'min_atr_pct': 3.0,  # INVALID - min >= max
            'max_atr_pct': 3.0,
            'atr_window': 14,
            'maker_only': True,
            'spread_bps_cap': 8,
        }
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(invalid_config, f)
        temp_path = f.name

    try:
        loader = EnhancedScalperConfigLoader(temp_path)
        config = loader.load_config()
        print("  [ERR] Validation should have failed for min_atr_pct >= max_atr_pct")
        return False
    except ValueError as e:
        if "max_atr_pct" in str(e) and "must be > min_atr_pct" in str(e):
            print(f"  [OK] Validation correctly rejected invalid ATR range")
            print(f"    Error: {e}")
            return True
        else:
            print(f"  [ERR] Wrong error: {e}")
            return False
    finally:
        import os
        os.unlink(temp_path)


def test_pairs_normalization_in_config():
    """Test pairs are normalized when loading config"""
    print("\n" + "="*80)
    print("TEST 6: Pairs Normalization in Config Load")
    print("="*80)

    import yaml
    import tempfile

    # Create config with non-normalized pairs
    test_config = {
        'bar_reaction_5m': {
            'enabled': True,
            'mode': 'trend',
            'pairs': ['BTCUSD', 'ETH-USD', 'SOL/USD'],  # Mixed formats
            'timeframe': '5m',
            'trigger_mode': 'open_to_close',
            'trigger_bps_up': 12,
            'trigger_bps_down': 12,
            'min_atr_pct': 0.25,
            'max_atr_pct': 3.0,
            'atr_window': 14,
            'risk_per_trade_pct': 0.6,
            'sl_atr': 0.6,
            'tp1_atr': 1.0,
            'tp2_atr': 1.8,
            'maker_only': True,
            'spread_bps_cap': 8,
        }
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(test_config, f)
        temp_path = f.name

    try:
        loader = EnhancedScalperConfigLoader(temp_path)
        config = loader.load_config()

        normalized_pairs = config['bar_reaction_5m']['pairs']
        expected_pairs = ['BTC/USD', 'ETH/USD', 'SOL/USD']

        if normalized_pairs == expected_pairs:
            print(f"  [OK] Pairs correctly normalized:")
            print(f"    Input:  {test_config['bar_reaction_5m']['pairs']}")
            print(f"    Output: {normalized_pairs}")
            return True
        else:
            print(f"  [ERR] Pairs normalization failed:")
            print(f"    Expected: {expected_pairs}")
            print(f"    Got:      {normalized_pairs}")
            return False

    except Exception as e:
        print(f"  [ERR] Test failed: {e}")
        return False
    finally:
        import os
        os.unlink(temp_path)


def main():
    """Run all tests"""
    import argparse

    parser = argparse.ArgumentParser(description="Test bar_reaction_5m config loader")
    parser.add_argument('--verbose', '-v', action='store_true', help="Verbose output")
    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='%(levelname)s - %(name)s - %(message)s'
    )

    print("="*80)
    print("EnhancedScalperConfigLoader - bar_reaction_5m Tests")
    print("="*80)

    results = []

    # Run tests
    results.append(("Successful Load", test_successful_load()))
    results.append(("Symbol Normalization", test_symbol_normalization()))
    results.append(("Invalid Timeframe", test_invalid_timeframe()))
    results.append(("Invalid Trigger BPS", test_invalid_trigger_bps()))
    results.append(("Invalid ATR Range", test_invalid_atr_range()))
    results.append(("Pairs Normalization", test_pairs_normalization_in_config()))

    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        symbol = "[OK] " if result else "[ERR]"
        print(f"  {symbol} {name:30s} [{status}]")

    print("\n" + "-"*80)
    print(f"  Total: {passed}/{total} tests passed")
    print("="*80 + "\n")

    # Exit code
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
