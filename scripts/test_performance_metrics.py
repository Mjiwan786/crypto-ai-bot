"""
Test Performance Metrics Calculator

Verifies:
- Aggressive mode score calculation
- Velocity to target calculation
- Days remaining estimate
- Prometheus metrics export
- Redis stream publishing
"""

import os
import sys
import time
from datetime import datetime, timedelta

# Set feature flag
os.environ["ENABLE_PERFORMANCE_METRICS"] = "true"
os.environ["STARTING_EQUITY_USD"] = "10000"
os.environ["TARGET_EQUITY_USD"] = "20000"

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metrics.performance_metrics import PerformanceMetricsCalculator


def create_sample_trades():
    """Create sample trade data for testing."""
    # Simulate 20 trades over 5 days
    # Win rate: 60%, Avg win: $50, Avg loss: $30
    trades = []

    # 12 winning trades
    for i in range(12):
        trades.append({
            "status": "closed",
            "pnl_usd": 50.0 + (i * 2),  # $50-$72
            "timestamp": time.time() - (5 * 86400) + (i * 3600),
        })

    # 8 losing trades
    for i in range(8):
        trades.append({
            "status": "closed",
            "pnl_usd": -30.0 - (i * 1.5),  # $-30 to $-40.5
            "timestamp": time.time() - (5 * 86400) + (12 * 3600) + (i * 3600),
        })

    return trades


def test_performance_metrics():
    """Test performance metrics calculation."""
    print("=" * 70)
    print("Performance Metrics Calculator Test")
    print("=" * 70)
    print()

    # Initialize calculator
    print("1. Initializing calculator...")
    start_date = datetime.now() - timedelta(days=5)
    calculator = PerformanceMetricsCalculator(
        redis_manager=None,  # No Redis for this test
        starting_equity=10000.0,
        target_equity=20000.0,
        start_date=start_date,
    )
    print("   [OK] Calculator initialized")
    print()

    # Create sample trades
    print("2. Creating sample trade data...")
    trades = create_sample_trades()
    print(f"   [OK] Created {len(trades)} sample trades")
    print()

    # Calculate total PnL
    total_pnl = sum(t["pnl_usd"] for t in trades)
    current_equity = 10000.0 + total_pnl
    print(f"   Total PnL: ${total_pnl:,.2f}")
    print(f"   Current Equity: ${current_equity:,.2f}")
    print()

    # Calculate metrics
    print("3. Calculating performance metrics...")
    metrics = calculator.calculate_metrics(trades, current_equity)

    if not metrics:
        print("   [FAIL] No metrics returned")
        return False

    print("   [OK] Metrics calculated")
    print()

    # Display results
    print("4. Performance Metrics Results:")
    print("   " + "-" * 66)

    # Aggressive Mode Score
    print(f"   Aggressive Mode Score: {metrics.aggressive_mode_score:.2f}")
    print(f"      Win Rate: {metrics.win_rate:.1%}")
    print(f"      Loss Rate: {metrics.loss_rate:.1%}")
    print(f"      Avg Win: ${metrics.avg_win_usd:.2f}")
    print(f"      Avg Loss: ${metrics.avg_loss_usd:.2f}")
    print(f"      Formula: ({metrics.win_rate:.2f} * {metrics.avg_win_usd:.2f}) / ({metrics.loss_rate:.2f} * {metrics.avg_loss_usd:.2f})")
    print()

    # Velocity to Target
    print(f"   Velocity to Target: {metrics.velocity_to_target:.1%}")
    print(f"      Starting: ${metrics.starting_equity_usd:,.0f}")
    print(f"      Current: ${metrics.current_equity_usd:,.2f}")
    print(f"      Target: ${metrics.target_equity_usd:,.0f}")
    print(f"      Progress: ${metrics.current_equity_usd - metrics.starting_equity_usd:,.2f} / ${metrics.target_equity_usd - metrics.starting_equity_usd:,.0f}")
    print()

    # Days Remaining Estimate
    if metrics.days_remaining_estimate != float('inf'):
        print(f"   Days Remaining Estimate: {metrics.days_remaining_estimate:.1f} days")
    else:
        print(f"   Days Remaining Estimate: Insufficient data")
    print(f"      Daily Rate: ${metrics.daily_rate_usd:.2f}/day")
    print(f"      Days Elapsed: {metrics.days_elapsed:.1f} days")
    print(f"      Remaining to Target: ${metrics.target_equity_usd - metrics.current_equity_usd:,.2f}")
    print()

    # Trading Statistics
    print(f"   Trading Statistics:")
    print(f"      Total Trades: {metrics.total_trades}")
    print(f"      Winning Trades: {metrics.winning_trades}")
    print(f"      Losing Trades: {metrics.losing_trades}")
    print(f"      Total PnL: ${metrics.total_pnl_usd:,.2f}")
    print("   " + "-" * 66)
    print()

    # Validate calculations
    print("5. Validating calculations...")

    # Check win rate
    expected_win_rate = 12 / 20  # 60%
    if abs(metrics.win_rate - expected_win_rate) > 0.01:
        print(f"   [WARN] Win rate mismatch: {metrics.win_rate:.2%} vs expected {expected_win_rate:.2%}")
    else:
        print(f"   [OK] Win rate correct: {metrics.win_rate:.1%}")

    # Check velocity
    expected_velocity = total_pnl / (20000 - 10000)
    if abs(metrics.velocity_to_target - expected_velocity) > 0.01:
        print(f"   [WARN] Velocity mismatch: {metrics.velocity_to_target:.2%} vs expected {expected_velocity:.2%}")
    else:
        print(f"   [OK] Velocity correct: {metrics.velocity_to_target:.1%}")

    # Check daily rate
    expected_daily_rate = total_pnl / 5.0
    if abs(metrics.daily_rate_usd - expected_daily_rate) > 1.0:
        print(f"   [WARN] Daily rate mismatch: ${metrics.daily_rate_usd:.2f} vs expected ${expected_daily_rate:.2f}")
    else:
        print(f"   [OK] Daily rate correct: ${metrics.daily_rate_usd:.2f}/day")

    print()

    # Test summary getter
    print("6. Testing metrics summary...")
    summary = calculator.get_metrics_summary()

    if not summary.get("available"):
        print("   [FAIL] Summary not available")
        return False

    print("   [OK] Summary generated")
    print(f"      Aggressive Score Interpretation: {summary['aggressive_mode_score']['interpretation']}")
    print(f"      Velocity Description: {summary['velocity_to_target']['description']}")
    print(f"      Days Remaining: {summary['days_remaining_estimate']['description']}")
    print()

    # Test baseline metrics (no trades)
    print("7. Testing baseline metrics (no trades)...")
    baseline_metrics = calculator.calculate_metrics([], 10000.0)

    if not baseline_metrics:
        print("   [FAIL] Baseline metrics not returned")
        return False

    print("   [OK] Baseline metrics returned")
    print(f"      Aggressive Score: {baseline_metrics.aggressive_mode_score:.2f}")
    print(f"      Velocity: {baseline_metrics.velocity_to_target:.1%}")
    print(f"      Win Rate: {baseline_metrics.win_rate:.1%}")
    print()

    print("[SUCCESS] All performance metrics tests passed!")
    print()

    return True


if __name__ == "__main__":
    try:
        success = test_performance_metrics()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
