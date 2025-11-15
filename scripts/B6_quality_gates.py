#!/usr/bin/env python3
"""
B6 - Quality Gates Checker

Evaluates backtest results against profitability criteria:
- total_return_pct > 0
- profit_factor >= 1.2
- max_dd_pct <= 25
- sharpe >= 0.8

Usage:
    python scripts/B6_quality_gates.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Quality gate thresholds (Production Rollout Criteria)
# Based on PRD_AGENTIC.md rollout plan:
# - PF ≥ 1.3 (profit factor)
# - Sharpe ≥ 1.0
# - MaxDD ≤ 6%
# - ≥ 40 trades minimum sample size
QUALITY_GATES = {
    "total_return_pct": (">", 0),
    "profit_factor": (">=", 1.3),  # Stricter: was 1.2
    "max_dd_pct": ("<=", 6),        # Stricter: was 25
    "sharpe": (">=", 1.0),          # Stricter: was 0.8
    "num_trades": (">=", 40),       # New: minimum sample size
}


class QualityGateResult(NamedTuple):
    """Quality gate evaluation result"""

    pair: str
    total_return_pass: bool
    profit_factor_pass: bool
    max_dd_pass: bool
    sharpe_pass: bool
    num_trades_pass: bool
    overall_pass: bool


def evaluate_pair(row: pd.Series) -> QualityGateResult:
    """
    Evaluate a single pair against quality gates.

    Args:
        row: DataFrame row with backtest metrics

    Returns:
        QualityGateResult with pass/fail status for each criterion
    """
    total_return_pass = row["total_return_pct"] > 0
    profit_factor_pass = row["profit_factor"] >= 1.3  # Production threshold
    max_dd_pass = row["max_dd_pct"] <= 6              # Production threshold
    sharpe_pass = row["sharpe"] >= 1.0                # Production threshold
    num_trades_pass = row.get("num_trades", 0) >= 40  # Minimum sample size

    overall_pass = all([
        total_return_pass,
        profit_factor_pass,
        max_dd_pass,
        sharpe_pass,
        num_trades_pass
    ])

    return QualityGateResult(
        pair=row["pair"],
        total_return_pass=total_return_pass,
        profit_factor_pass=profit_factor_pass,
        max_dd_pass=max_dd_pass,
        sharpe_pass=sharpe_pass,
        num_trades_pass=num_trades_pass,
        overall_pass=overall_pass,
    )


def format_result(result: QualityGateResult) -> str:
    """Format quality gate result as a string"""
    status = "PASS [OK]" if result.overall_pass else "FAIL [X]"
    return f"{result.pair}: {status}"


def format_detailed_result(result: QualityGateResult, row: pd.Series) -> str:
    """Format detailed quality gate result"""
    num_trades = row.get("num_trades", 0)
    lines = [
        f"\n{result.pair}:",
        f"  Overall: {'PASS [OK]' if result.overall_pass else 'FAIL [X]'}",
        f"  - Total Return: {'PASS' if result.total_return_pass else 'FAIL'} ({row['total_return_pct']:.2f}% vs >0%)",
        f"  - Profit Factor: {'PASS' if result.profit_factor_pass else 'FAIL'} ({row['profit_factor']:.2f} vs >=1.3)",
        f"  - Max Drawdown: {'PASS' if result.max_dd_pass else 'FAIL'} ({row['max_dd_pct']:.2f}% vs <=6%)",
        f"  - Sharpe Ratio: {'PASS' if result.sharpe_pass else 'FAIL'} ({row['sharpe']:.2f} vs >=1.0)",
        f"  - Num Trades: {'PASS' if result.num_trades_pass else 'FAIL'} ({num_trades} vs >=40)",
    ]
    return "\n".join(lines)


def main() -> int:
    """Main entry point"""
    # Load backtest summary
    summary_path = project_root / "reports" / "backtest_summary.csv"

    if not summary_path.exists():
        print(f"ERROR: {summary_path} not found. Run backtest first.")
        return 1

    print("=" * 60)
    print("B6 - QUALITY GATES CHECKER")
    print("=" * 60)
    print(f"Loading: {summary_path}")
    print()

    df = pd.read_csv(summary_path)

    # Evaluate each pair
    results = []
    detailed_output = []

    for _, row in df.iterrows():
        result = evaluate_pair(row)
        results.append(result)
        detailed_output.append(format_detailed_result(result, row))

    # Print summary
    print("Quality Gate Thresholds (Production Rollout Criteria):")
    print(f"  - Total Return: > 0%")
    print(f"  - Profit Factor: >= 1.3")
    print(f"  - Max Drawdown: <= 6%")
    print(f"  - Sharpe Ratio: >= 1.0")
    print(f"  - Num Trades: >= 40")
    print()

    print("=" * 60)
    print("RESULTS")
    print("=" * 60)

    for output in detailed_output:
        print(output)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    # Overall basket verdict
    all_passed = all(r.overall_pass for r in results)
    passed_count = sum(r.overall_pass for r in results)
    total_count = len(results)

    for result in results:
        print(format_result(result))

    print()
    print(f"Basket Verdict: {passed_count}/{total_count} pairs passed")
    if all_passed:
        print("OVERALL: PASS [OK] - All pairs meet quality gates")
    else:
        print("OVERALL: FAIL [X] - Some pairs do not meet quality gates")

    # Save to file
    output_path = project_root / "reports" / "quality_gates.txt"
    with open(output_path, "w") as f:
        f.write("=" * 60 + "\n")
        f.write("B6 - QUALITY GATES REPORT\n")
        f.write("=" * 60 + "\n")
        f.write(f"Generated: {pd.Timestamp.now()}\n")
        f.write("\n")

        f.write("Quality Gate Thresholds (Production Rollout Criteria):\n")
        f.write("  - Total Return: > 0%\n")
        f.write("  - Profit Factor: >= 1.3\n")
        f.write("  - Max Drawdown: <= 6%\n")
        f.write("  - Sharpe Ratio: >= 1.0\n")
        f.write("  - Num Trades: >= 40\n")
        f.write("\n")

        f.write("=" * 60 + "\n")
        f.write("RESULTS\n")
        f.write("=" * 60 + "\n")

        for output in detailed_output:
            f.write(output + "\n")

        f.write("\n")
        f.write("=" * 60 + "\n")
        f.write("SUMMARY\n")
        f.write("=" * 60 + "\n")

        for result in results:
            f.write(format_result(result) + "\n")

        f.write("\n")
        f.write(f"Basket Verdict: {passed_count}/{total_count} pairs passed\n")
        if all_passed:
            f.write("OVERALL: PASS [OK] - All pairs meet quality gates\n")
        else:
            f.write("OVERALL: FAIL [X] - Some pairs do not meet quality gates\n")

    print()
    print(f"[OK] Quality gates report saved to: {output_path}")

    # Return exit code based on overall result
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
