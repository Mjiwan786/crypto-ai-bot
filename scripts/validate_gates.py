#!/usr/bin/env python3
"""
Validate Success Gates for P&L Optimization

Checks backtest results against defined success criteria:
- Profit Factor ≥ 1.35
- Sharpe Ratio ≥ 1.2
- Max Drawdown ≤ 12%
- Net Return ≥ 25% annually
- Win Rate ≥ 45% (optional quality check)

Usage:
    python scripts/validate_gates.py out/backtest_results.json
    python scripts/validate_gates.py out/backtest_results.json --strict
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, Tuple


class SuccessGates:
    """Success gate thresholds"""
    MIN_PROFIT_FACTOR = 1.35
    MIN_SHARPE = 1.2
    MAX_DRAWDOWN_PCT = 12.0
    MIN_ANNUAL_RETURN_PCT = 25.0
    MIN_WIN_RATE_PCT = 45.0  # Optional quality metric


def load_backtest_results(file_path: Path) -> Dict[str, Any]:
    """Load backtest results from JSON file"""
    if not file_path.exists():
        print(f"❌ Error: File not found: {file_path}")
        sys.exit(1)

    with open(file_path, 'r') as f:
        return json.load(f)


def extract_metrics(results: Dict[str, Any]) -> Dict[str, float]:
    """Extract key metrics from backtest results"""
    # Handle different result formats
    if 'metrics' in results:
        metrics_data = results['metrics']
    else:
        metrics_data = results

    # Extract with fallbacks
    profit_factor = metrics_data.get('profit_factor', metrics_data.get('pf', 0.0))
    sharpe = metrics_data.get('sharpe_ratio', metrics_data.get('sharpe', 0.0))
    max_dd = abs(metrics_data.get('max_drawdown_pct', metrics_data.get('max_dd_pct', 0.0)))
    total_return_pct = metrics_data.get('total_return_pct', metrics_data.get('roi_pct', 0.0))
    win_rate_pct = metrics_data.get('win_rate_pct', metrics_data.get('win_rate', 0.0))
    period_days = metrics_data.get('duration_days', metrics_data.get('period_days', 365))

    # Annualize return if needed
    if period_days and period_days != 365:
        annual_return_pct = (total_return_pct / period_days) * 365
    else:
        annual_return_pct = total_return_pct

    return {
        'profit_factor': float(profit_factor),
        'sharpe_ratio': float(sharpe),
        'max_dd_pct': float(max_dd),
        'total_return_pct': float(total_return_pct),
        'annual_return_pct': float(annual_return_pct),
        'win_rate_pct': float(win_rate_pct),
        'period_days': int(period_days),
    }


def validate_gate(name: str, actual: float, target: float, comparison: str = ">=") -> Tuple[bool, str]:
    """
    Validate a single gate

    Args:
        name: Gate name
        actual: Actual value
        target: Target value
        comparison: Comparison operator (">=" or "<=")

    Returns:
        (passed, message)
    """
    if comparison == ">=":
        passed = actual >= target
        symbol = "✅" if passed else "❌"
        status = "PASS" if passed else "FAIL"
        return passed, f"{symbol} {name}: {actual:.2f} {comparison} {target:.2f} ({status})"
    elif comparison == "<=":
        passed = actual <= target
        symbol = "✅" if passed else "❌"
        status = "PASS" if passed else "FAIL"
        return passed, f"{symbol} {name}: {actual:.2f} {comparison} {target:.2f} ({status})"
    else:
        raise ValueError(f"Unknown comparison: {comparison}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate backtest results against success gates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic validation
  python scripts/validate_gates.py out/iter1.json

  # Strict mode (all gates must pass)
  python scripts/validate_gates.py out/iter1.json --strict

  # Custom thresholds
  python scripts/validate_gates.py out/iter1.json \\
      --pf-min 1.4 \\
      --sharpe-min 1.5 \\
      --dd-max 10.0 \\
      --return-min 30.0
        """
    )

    parser.add_argument(
        "results_file",
        type=Path,
        help="Path to backtest results JSON file"
    )

    parser.add_argument(
        "--pf-min",
        type=float,
        default=SuccessGates.MIN_PROFIT_FACTOR,
        help=f"Minimum profit factor (default: {SuccessGates.MIN_PROFIT_FACTOR})"
    )

    parser.add_argument(
        "--sharpe-min",
        type=float,
        default=SuccessGates.MIN_SHARPE,
        help=f"Minimum Sharpe ratio (default: {SuccessGates.MIN_SHARPE})"
    )

    parser.add_argument(
        "--dd-max",
        type=float,
        default=SuccessGates.MAX_DRAWDOWN_PCT,
        help=f"Maximum drawdown %% (default: {SuccessGates.MAX_DRAWDOWN_PCT})"
    )

    parser.add_argument(
        "--return-min",
        type=float,
        default=SuccessGates.MIN_ANNUAL_RETURN_PCT,
        help=f"Minimum annual return %% (default: {SuccessGates.MIN_ANNUAL_RETURN_PCT})"
    )

    parser.add_argument(
        "--win-rate-min",
        type=float,
        default=SuccessGates.MIN_WIN_RATE_PCT,
        help=f"Minimum win rate %% (default: {SuccessGates.MIN_WIN_RATE_PCT})"
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error code if any gate fails"
    )

    parser.add_argument(
        "--check-win-rate",
        action="store_true",
        help="Include win rate in mandatory checks"
    )

    args = parser.parse_args()

    # Load results
    print(f"\n{'='*80}")
    print(f"SUCCESS GATES VALIDATION")
    print(f"{'='*80}\n")
    print(f"Results File: {args.results_file}")

    results = load_backtest_results(args.results_file)
    metrics = extract_metrics(results)

    print(f"\nExtracted Metrics:")
    print(f"  Period: {metrics['period_days']} days")
    print(f"  Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {metrics['max_dd_pct']:.2f}%")
    print(f"  Total Return: {metrics['total_return_pct']:.2f}%")
    print(f"  Annual Return: {metrics['annual_return_pct']:.2f}%")
    print(f"  Win Rate: {metrics['win_rate_pct']:.2f}%")

    # Validate gates
    print(f"\n{'='*80}")
    print(f"GATE VALIDATION")
    print(f"{'='*80}\n")

    gates = []

    # Mandatory gates
    passed, msg = validate_gate("Profit Factor", metrics['profit_factor'], args.pf_min, ">=")
    print(msg)
    gates.append(passed)

    passed, msg = validate_gate("Sharpe Ratio", metrics['sharpe_ratio'], args.sharpe_min, ">=")
    print(msg)
    gates.append(passed)

    passed, msg = validate_gate("Max Drawdown", metrics['max_dd_pct'], args.dd_max, "<=")
    print(msg)
    gates.append(passed)

    passed, msg = validate_gate("Annual Return", metrics['annual_return_pct'], args.return_min, ">=")
    print(msg)
    gates.append(passed)

    # Optional win rate check
    if args.check_win_rate:
        passed, msg = validate_gate("Win Rate", metrics['win_rate_pct'], args.win_rate_min, ">=")
        print(msg)
        gates.append(passed)
    else:
        print(f"ℹ️  Win Rate: {metrics['win_rate_pct']:.2f}% (informational, not required)")

    # Summary
    print(f"\n{'='*80}")
    passed_count = sum(gates)
    total_count = len(gates)

    if all(gates):
        print(f"✅ ALL GATES PASSED ({passed_count}/{total_count})")
        print(f"{'='*80}\n")
        print("🎉 Strategy meets success criteria!")
        print("✅ Ready for paper trading dry-run (48h)")
        sys.exit(0)
    else:
        print(f"❌ GATES FAILED ({passed_count}/{total_count} passed)")
        print(f"{'='*80}\n")
        print("⚠️  Strategy does not meet success criteria")
        print("🔧 Recommendations:")

        if metrics['profit_factor'] < args.pf_min:
            print(f"   - Improve profit factor: widen stops (sl_atr), stretch targets (tp_atr)")
        if metrics['sharpe_ratio'] < args.sharpe_min:
            print(f"   - Improve Sharpe: reduce trade frequency (higher trigger_bps)")
        if metrics['max_dd_pct'] > args.dd_max:
            print(f"   - Reduce drawdown: lower risk_pct, add regime filter, tighter spread_cap")
        if metrics['annual_return_pct'] < args.return_min:
            if metrics['profit_factor'] >= args.pf_min:
                print(f"   - Increase returns: higher risk_pct, more concurrent positions")
            else:
                print(f"   - Increase returns: first fix profit factor, then scale position size")

        print()

        if args.strict:
            sys.exit(1)
        else:
            sys.exit(0)


if __name__ == "__main__":
    main()
