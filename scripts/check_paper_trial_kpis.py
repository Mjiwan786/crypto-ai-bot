"""
Check Paper Trial KPIs - Step 7 Validation

Daily health check script for paper trading trial.
Verifies ML confidence gate is working and performance meets criteria.

Usage:
    python scripts/check_paper_trial_kpis.py

Outputs:
    - Daily KPI summary
    - PASS/WARN/FAIL status
    - Recommendations if off-track

Pass Criteria (from Step 7):
    - Trade count: 60-80% of baseline (expect ~40-65 trades/week)
    - Profit Factor: >= 1.5
    - Monthly ROI: >= 0.83% (10% annualized)
    - Max Drawdown: <= -20%
    - P95 latency: < 500ms
    - ML confidence: present in all signals
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Expected baseline from Step 7C validation (synthetic)
BASELINE_TRADES_PER_WEEK = 78 / 52  # 78 trades in 360d = ~1.5 trades/week
BASELINE_WEEKLY_MIN = int(BASELINE_TRADES_PER_WEEK * 0.6)  # 60% retention
BASELINE_WEEKLY_MAX = int(BASELINE_TRADES_PER_WEEK * 0.8)  # 80% retention

# Pass criteria
MIN_PROFIT_FACTOR = 1.5
MIN_MONTHLY_ROI_PCT = 0.83  # 10% annualized
MAX_DRAWDOWN_PCT = -20.0
MAX_P95_LATENCY_MS = 500.0


def load_paper_trial_metrics():
    """Load metrics from paper trial logs/redis"""
    # Placeholder - implement based on actual storage
    # This would typically read from:
    # 1. Redis streams (signals:paper)
    # 2. Prometheus metrics (http://localhost:9108/metrics)
    # 3. Log files (logs/paper_trial_*.log)

    # For now, return mock structure
    return {
        "start_date": datetime.now() - timedelta(days=3),
        "end_date": datetime.now(),
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "total_pnl_usd": 0.0,
        "max_drawdown_pct": 0.0,
        "profit_factor": 0.0,
        "latency_p95_ms": 0.0,
        "signals_with_confidence": 0,
        "signals_total": 0,
    }


def calculate_kpis(metrics):
    """Calculate KPIs from raw metrics"""
    duration_days = (metrics["end_date"] - metrics["start_date"]).days

    if duration_days == 0:
        duration_days = 1  # Prevent division by zero

    # Annualize ROI
    total_pnl_pct = (metrics["total_pnl_usd"] / 10000.0) * 100  # Assume $10k initial
    monthly_roi_pct = (total_pnl_pct / duration_days) * 30  # Scale to monthly

    # Win rate
    if metrics["total_trades"] > 0:
        win_rate_pct = (metrics["winning_trades"] / metrics["total_trades"]) * 100
    else:
        win_rate_pct = 0.0

    # ML confidence coverage
    if metrics["signals_total"] > 0:
        ml_coverage_pct = (metrics["signals_with_confidence"] / metrics["signals_total"]) * 100
    else:
        ml_coverage_pct = 0.0

    return {
        "duration_days": duration_days,
        "total_trades": metrics["total_trades"],
        "trades_per_week": (metrics["total_trades"] / duration_days) * 7 if duration_days > 0 else 0,
        "win_rate_pct": win_rate_pct,
        "profit_factor": metrics["profit_factor"],
        "monthly_roi_pct": monthly_roi_pct,
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "latency_p95_ms": metrics["latency_p95_ms"],
        "ml_coverage_pct": ml_coverage_pct,
    }


def evaluate_kpis(kpis):
    """Evaluate KPIs against pass criteria"""
    issues = []
    warnings = []

    # 1. Trade count (starvation check)
    if kpis["trades_per_week"] < BASELINE_WEEKLY_MIN:
        issues.append(
            f"Trade starvation: {kpis['trades_per_week']:.1f} trades/week < {BASELINE_WEEKLY_MIN} minimum"
        )
    elif kpis["trades_per_week"] > BASELINE_WEEKLY_MAX * 1.5:
        warnings.append(
            f"Excessive trading: {kpis['trades_per_week']:.1f} trades/week > expected range"
        )

    # 2. Profit factor
    if kpis["profit_factor"] < MIN_PROFIT_FACTOR:
        issues.append(
            f"Profit factor too low: {kpis['profit_factor']:.2f} < {MIN_PROFIT_FACTOR} minimum"
        )

    # 3. Monthly ROI
    if kpis["monthly_roi_pct"] < MIN_MONTHLY_ROI_PCT:
        issues.append(
            f"Monthly ROI too low: {kpis['monthly_roi_pct']:.2f}% < {MIN_MONTHLY_ROI_PCT}% minimum"
        )

    # 4. Drawdown
    if kpis["max_drawdown_pct"] < MAX_DRAWDOWN_PCT:
        issues.append(
            f"Drawdown exceeded: {kpis['max_drawdown_pct']:.1f}% < {MAX_DRAWDOWN_PCT}% maximum"
        )

    # 5. Latency
    if kpis["latency_p95_ms"] > MAX_P95_LATENCY_MS:
        issues.append(
            f"Latency too high: {kpis['latency_p95_ms']:.0f}ms > {MAX_P95_LATENCY_MS}ms maximum"
        )

    # 6. ML coverage
    if kpis["ml_coverage_pct"] < 95.0:
        warnings.append(
            f"ML confidence coverage low: {kpis['ml_coverage_pct']:.1f}% (expect >95%)"
        )

    # Overall verdict
    if len(issues) == 0:
        if len(warnings) == 0:
            status = "PASS"
        else:
            status = "PASS_WITH_WARNINGS"
    else:
        status = "FAIL"

    return status, issues, warnings


def print_kpi_report(kpis, status, issues, warnings):
    """Print formatted KPI report"""
    print()
    print("=" * 80)
    print("PAPER TRIAL KPI REPORT - Step 7 Validation")
    print("=" * 80)
    print()
    print(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Trial Duration: {kpis['duration_days']} days")
    print()

    print("=" * 80)
    print("KEY PERFORMANCE INDICATORS")
    print("=" * 80)
    print()

    # Trade activity
    print(f"Trade Count:")
    print(f"  Total: {kpis['total_trades']}")
    print(f"  Per Week: {kpis['trades_per_week']:.1f} (expect {BASELINE_WEEKLY_MIN}-{BASELINE_WEEKLY_MAX})")
    status_icon = "✅" if BASELINE_WEEKLY_MIN <= kpis['trades_per_week'] <= BASELINE_WEEKLY_MAX * 1.5 else "❌"
    print(f"  Status: {status_icon}")
    print()

    # Performance metrics
    print(f"Performance:")
    print(f"  Win Rate: {kpis['win_rate_pct']:.1f}%")
    pf_icon = "✅" if kpis['profit_factor'] >= MIN_PROFIT_FACTOR else "❌"
    print(f"  Profit Factor: {kpis['profit_factor']:.2f} (min {MIN_PROFIT_FACTOR}) {pf_icon}")
    roi_icon = "✅" if kpis['monthly_roi_pct'] >= MIN_MONTHLY_ROI_PCT else "❌"
    print(f"  Monthly ROI: {kpis['monthly_roi_pct']:.2f}% (min {MIN_MONTHLY_ROI_PCT}%) {roi_icon}")
    dd_icon = "✅" if kpis['max_drawdown_pct'] >= MAX_DRAWDOWN_PCT else "❌"
    print(f"  Max Drawdown: {kpis['max_drawdown_pct']:.1f}% (max {MAX_DRAWDOWN_PCT}%) {dd_icon}")
    print()

    # Technical metrics
    print(f"Technical:")
    lat_icon = "✅" if kpis['latency_p95_ms'] < MAX_P95_LATENCY_MS else "❌"
    print(f"  P95 Latency: {kpis['latency_p95_ms']:.0f}ms (max {MAX_P95_LATENCY_MS}ms) {lat_icon}")
    ml_icon = "✅" if kpis['ml_coverage_pct'] >= 95.0 else "⚠️"
    print(f"  ML Coverage: {kpis['ml_coverage_pct']:.1f}% (expect >95%) {ml_icon}")
    print()

    # Issues
    if issues:
        print("=" * 80)
        print("ISSUES DETECTED")
        print("=" * 80)
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        print()

    # Warnings
    if warnings:
        print("=" * 80)
        print("WARNINGS")
        print("=" * 80)
        for i, warning in enumerate(warnings, 1):
            print(f"  {i}. {warning}")
        print()

    # Final verdict
    print("=" * 80)
    print("VERDICT")
    print("=" * 80)
    print()

    if status == "PASS":
        print("✅ PAPER TRIAL: PASS")
        print()
        print("All KPIs meet criteria. Paper trial on track for successful completion.")
        print()
        print("Next Steps:")
        print("  1. Continue monitoring for remaining trial duration")
        print("  2. After 7 days, evaluate for live trading approval")
        print("  3. If approved, enable live with 50% capital allocation")

    elif status == "PASS_WITH_WARNINGS":
        print("⚠️ PAPER TRIAL: PASS (with warnings)")
        print()
        print("Core KPIs meet criteria, but some warnings detected.")
        print("Review warnings and monitor closely.")

    else:
        print("❌ PAPER TRIAL: FAIL")
        print()
        print("One or more KPIs below criteria. Action required.")
        print()
        print("Recommended Actions:")

        # Specific recommendations based on issues
        for issue in issues:
            if "Trade starvation" in issue:
                print("  - Lower ML threshold (0.60 → 0.55)")
                print("    Command: sed -i 's/min_alignment_confidence: 0.60/min_alignment_confidence: 0.55/' config/params/ml.yaml")

            elif "Profit factor" in issue or "Monthly ROI" in issue:
                print("  - Consider raising ML threshold for better quality (0.60 → 0.65)")
                print("  - OR disable ML gate and rely on regime/router fixes only")
                print("    Command: sed -i 's/enabled: true/enabled: false/' config/params/ml.yaml")

            elif "Drawdown" in issue:
                print("  - Check risk manager breaker settings")
                print("  - Verify position sizing is within limits")

            elif "Latency" in issue:
                print("  - Check system resources (CPU/memory)")
                print("  - Review strategy complexity")

    print()
    print("=" * 80)


def main():
    """Run daily KPI check"""
    print()
    print("Loading paper trial metrics...")

    try:
        metrics = load_paper_trial_metrics()
        kpis = calculate_kpis(metrics)
        status, issues, warnings = evaluate_kpis(kpis)
        print_kpi_report(kpis, status, issues, warnings)

        # Exit code based on status
        if status == "FAIL":
            return 1
        else:
            return 0

    except Exception as e:
        print(f"\n❌ ERROR: Failed to load/calculate KPIs: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
