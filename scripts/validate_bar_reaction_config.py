#!/usr/bin/env python3
"""
Validation script for bar_reaction_5m configuration.

Tests that the enhanced_scalper_config.yaml contains valid bar_reaction_5m settings
with zero ambiguity and correct parameter ranges.

Usage:
    python scripts/validate_bar_reaction_config.py
    python scripts/validate_bar_reaction_config.py --verbose

Exit codes:
    0 = All validations passed
    1 = Validation failed
"""

import sys
from pathlib import Path
from typing import Any, Dict

import yaml


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load YAML configuration file."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        sys.exit(1)


def validate_bar_reaction_config(config: Dict[str, Any], verbose: bool = False) -> bool:
    """
    Validate bar_reaction_5m configuration block.

    Returns:
        True if all validations pass, False otherwise
    """
    errors = []
    warnings = []

    # Check if bar_reaction_5m exists
    if 'bar_reaction_5m' not in config:
        errors.append("Missing 'bar_reaction_5m' configuration block")
        return False

    br_config = config['bar_reaction_5m']

    # =========================================================================
    # Core Settings Validation
    # =========================================================================
    if br_config.get('enabled') is not True:
        warnings.append("bar_reaction_5m is disabled (enabled=false)")

    valid_modes = ['trend', 'revert']
    if br_config.get('mode') not in valid_modes:
        errors.append(f"Invalid mode: {br_config.get('mode')}. Must be one of {valid_modes}")

    if br_config.get('timeframe') != '5m':
        errors.append(f"Invalid timeframe: {br_config.get('timeframe')}. Must be '5m'")

    if not isinstance(br_config.get('pairs'), list) or len(br_config.get('pairs', [])) == 0:
        errors.append("'pairs' must be a non-empty list")

    # =========================================================================
    # Trigger Settings Validation
    # =========================================================================
    valid_trigger_modes = ['open_to_close', 'prev_close_to_close']
    if br_config.get('trigger_mode') not in valid_trigger_modes:
        errors.append(f"Invalid trigger_mode: {br_config.get('trigger_mode')}. Must be one of {valid_trigger_modes}")

    # Validate trigger thresholds
    trigger_bps_up = br_config.get('trigger_bps_up')
    trigger_bps_down = br_config.get('trigger_bps_down')

    if not isinstance(trigger_bps_up, (int, float)) or trigger_bps_up <= 0:
        errors.append(f"trigger_bps_up must be positive number, got: {trigger_bps_up}")

    if not isinstance(trigger_bps_down, (int, float)) or trigger_bps_down <= 0:
        errors.append(f"trigger_bps_down must be positive number, got: {trigger_bps_down}")

    if trigger_bps_up != trigger_bps_down:
        warnings.append(f"Asymmetric triggers: up={trigger_bps_up}, down={trigger_bps_down}")

    # =========================================================================
    # ATR Validation
    # =========================================================================
    atr_window = br_config.get('atr_window')
    if not isinstance(atr_window, int) or atr_window < 5:
        errors.append(f"atr_window must be int >= 5, got: {atr_window}")

    min_atr_pct = br_config.get('min_atr_pct')
    max_atr_pct = br_config.get('max_atr_pct')

    if not isinstance(min_atr_pct, (int, float)) or min_atr_pct < 0:
        errors.append(f"min_atr_pct must be >= 0, got: {min_atr_pct}")

    if not isinstance(max_atr_pct, (int, float)) or max_atr_pct <= min_atr_pct:
        errors.append(f"max_atr_pct ({max_atr_pct}) must be > min_atr_pct ({min_atr_pct})")

    if max_atr_pct > 5.0:
        warnings.append(f"max_atr_pct={max_atr_pct} is very high (>5%), may allow chaotic conditions")

    # =========================================================================
    # Risk Management Validation
    # =========================================================================
    risk_per_trade = br_config.get('risk_per_trade_pct')
    if not isinstance(risk_per_trade, (int, float)) or risk_per_trade <= 0 or risk_per_trade > 2.0:
        errors.append(f"risk_per_trade_pct must be in (0, 2.0], got: {risk_per_trade}")

    sl_atr = br_config.get('sl_atr')
    tp1_atr = br_config.get('tp1_atr')
    tp2_atr = br_config.get('tp2_atr')

    if not isinstance(sl_atr, (int, float)) or sl_atr <= 0:
        errors.append(f"sl_atr must be positive, got: {sl_atr}")

    if not isinstance(tp1_atr, (int, float)) or tp1_atr <= 0:
        errors.append(f"tp1_atr must be positive, got: {tp1_atr}")

    if not isinstance(tp2_atr, (int, float)) or tp2_atr <= 0:
        errors.append(f"tp2_atr must be positive, got: {tp2_atr}")

    # Validate RR ratios
    if sl_atr > 0:
        rr1 = tp1_atr / sl_atr
        rr2 = tp2_atr / sl_atr
        blended_rr = (rr1 + rr2) / 2

        if verbose:
            print(f"  RR1: {rr1:.2f}:1")
            print(f"  RR2: {rr2:.2f}:1")
            print(f"  Blended RR: {blended_rr:.2f}:1")

        if rr1 < 1.0:
            warnings.append(f"RR1 ({rr1:.2f}:1) is less than 1:1 (risky)")

        if tp1_atr >= tp2_atr:
            errors.append(f"tp1_atr ({tp1_atr}) must be < tp2_atr ({tp2_atr})")

    # =========================================================================
    # Dynamic Risk Validation
    # =========================================================================
    trail_atr = br_config.get('trail_atr')
    break_even_at_r = br_config.get('break_even_at_r')

    if not isinstance(trail_atr, (int, float)) or trail_atr <= 0:
        errors.append(f"trail_atr must be positive, got: {trail_atr}")

    if not isinstance(break_even_at_r, (int, float)) or break_even_at_r <= 0 or break_even_at_r > 1.0:
        errors.append(f"break_even_at_r must be in (0, 1.0], got: {break_even_at_r}")

    # =========================================================================
    # Execution Settings Validation
    # =========================================================================
    if br_config.get('maker_only') is not True:
        errors.append("maker_only must be true for bar_reaction_5m strategy")

    spread_bps_cap = br_config.get('spread_bps_cap')
    if not isinstance(spread_bps_cap, (int, float)) or spread_bps_cap <= 0 or spread_bps_cap > 20:
        errors.append(f"spread_bps_cap must be in (0, 20], got: {spread_bps_cap}")

    # =========================================================================
    # Liquidity Validation
    # =========================================================================
    min_rolling_notional = br_config.get('min_rolling_notional_usd')
    if not isinstance(min_rolling_notional, (int, float)) or min_rolling_notional < 0:
        errors.append(f"min_rolling_notional_usd must be >= 0, got: {min_rolling_notional}")

    if min_rolling_notional < 100000:
        warnings.append(f"min_rolling_notional_usd={min_rolling_notional} is low (<$100k), may have liquidity issues")

    # =========================================================================
    # Concurrency Validation
    # =========================================================================
    cooldown_bars = br_config.get('cooldown_bars')
    if not isinstance(cooldown_bars, int) or cooldown_bars < 0:
        errors.append(f"cooldown_bars must be int >= 0, got: {cooldown_bars}")

    max_concurrent = br_config.get('max_concurrent_per_pair')
    if not isinstance(max_concurrent, int) or max_concurrent < 1:
        errors.append(f"max_concurrent_per_pair must be int >= 1, got: {max_concurrent}")

    # =========================================================================
    # Extreme Mode Validation
    # =========================================================================
    enable_extremes = br_config.get('enable_mean_revert_extremes')
    if enable_extremes:
        extreme_threshold = br_config.get('extreme_bps_threshold')
        mean_revert_factor = br_config.get('mean_revert_size_factor')

        if not isinstance(extreme_threshold, (int, float)) or extreme_threshold <= trigger_bps_up:
            errors.append(
                f"extreme_bps_threshold ({extreme_threshold}) must be > trigger_bps_up ({trigger_bps_up})"
            )

        if not isinstance(mean_revert_factor, (int, float)) or mean_revert_factor <= 0 or mean_revert_factor > 1.0:
            errors.append(f"mean_revert_size_factor must be in (0, 1.0], got: {mean_revert_factor}")

    # =========================================================================
    # Strategy Router Validation
    # =========================================================================
    if 'strategy_router' in config:
        router = config['strategy_router']
        allocations = router.get('allocations', {})

        if 'bar_reaction_5m' not in allocations:
            warnings.append("bar_reaction_5m not in strategy_router allocations (won't be used by router)")
        else:
            alloc = allocations['bar_reaction_5m']
            if not isinstance(alloc, (int, float)) or alloc < 0 or alloc > 1.0:
                errors.append(f"Invalid allocation for bar_reaction_5m: {alloc}. Must be in [0, 1.0]")

        # Check that allocations sum to <= 1.0
        total_alloc = sum(allocations.values())
        if total_alloc > 1.0 + 1e-9:
            errors.append(f"Total strategy allocations ({total_alloc:.2f}) exceed 1.0")

        # Validate router limits
        max_trades_day = router.get('max_trades_per_day', {})
        max_trades_hour = router.get('max_trades_per_hour', {})

        if 'bar_reaction_5m' not in max_trades_day:
            warnings.append("bar_reaction_5m missing from max_trades_per_day")

        if 'bar_reaction_5m' not in max_trades_hour:
            warnings.append("bar_reaction_5m missing from max_trades_per_hour")

    # =========================================================================
    # Print Results
    # =========================================================================
    if errors:
        print("\n[FAIL] VALIDATION FAILED\n")
        print(f"Found {len(errors)} error(s):\n")
        for i, err in enumerate(errors, 1):
            print(f"  {i}. {err}")

        if warnings:
            print(f"\nFound {len(warnings)} warning(s):\n")
            for i, warn in enumerate(warnings, 1):
                print(f"  {i}. {warn}")

        return False
    else:
        print("\n[PASS] VALIDATION PASSED\n")

        if warnings:
            print(f"Found {len(warnings)} warning(s):\n")
            for i, warn in enumerate(warnings, 1):
                print(f"  {i}. {warn}")
            print()

        # Print summary
        print("Configuration Summary:")
        print(f"  Mode: {br_config.get('mode')}")
        print(f"  Pairs: {', '.join(br_config.get('pairs', []))}")
        print(f"  Timeframe: {br_config.get('timeframe')}")
        print(f"  Trigger: {br_config.get('trigger_mode')} @ {trigger_bps_up}bps")
        print(f"  ATR Window: {atr_window} bars")
        print(f"  ATR Range: {min_atr_pct}% - {max_atr_pct}%")
        print(f"  Risk per Trade: {risk_per_trade}%")
        print(f"  Stop Loss: {sl_atr}x ATR")
        print(f"  Take Profit: {tp1_atr}x ATR (TP1), {tp2_atr}x ATR (TP2)")
        print(f"  Spread Cap: {spread_bps_cap}bps")
        print(f"  Min Liquidity: ${min_rolling_notional:,.0f}")
        print(f"  Extreme Mode: {'Enabled' if enable_extremes else 'Disabled'}")
        if enable_extremes:
            print(f"    Threshold: {br_config.get('extreme_bps_threshold')}bps")
            print(f"    Size Factor: {br_config.get('mean_revert_size_factor')}")

        return True


def main():
    """Main validation entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate bar_reaction_5m configuration")
    parser.add_argument('--verbose', '-v', action='store_true', help="Verbose output")
    parser.add_argument(
        '--config',
        '-c',
        type=Path,
        default=Path('config/enhanced_scalper_config.yaml'),
        help="Path to config file"
    )
    args = parser.parse_args()

    print("=" * 80)
    print("Bar Reaction 5m Configuration Validation")
    print("=" * 80)
    print(f"\nConfig file: {args.config}\n")

    # Check if file exists
    if not args.config.exists():
        print(f"[ERROR] Config file not found: {args.config}")
        sys.exit(1)

    # Load config
    config = load_config(args.config)

    # Validate
    success = validate_bar_reaction_config(config, verbose=args.verbose)

    # Exit
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
