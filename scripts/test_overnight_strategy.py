"""
Test Overnight Momentum Strategy

Tests all components:
- Asian session detection
- Volume filtering
- Momentum detection
- Position management
- Trailing stops
- Backtest framework
- Promotion gates

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import sys
import logging
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pandas as pd
import numpy as np

# Fix Windows encoding for emoji/unicode
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from strategies.overnight_momentum import (
    OvernightMomentumStrategy,
    SessionType,
    create_overnight_momentum_strategy,
)
from strategies.overnight_position_manager import (
    OvernightPositionManager,
    create_overnight_position_manager,
)
from strategies.overnight_backtest import (
    OvernightBacktester,
    BacktestConfig,
    create_backtest_report,
    print_trade_log,
)


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_session_detection():
    """Test Asian session detection."""
    print("\n" + "="*80)
    print("TEST 1: Session Detection")
    print("="*80)

    strategy = create_overnight_momentum_strategy(
        enabled=True,
        backtest_only=True,
    )

    # Test times (UTC)
    test_cases = [
        ("2025-01-01 02:00:00", SessionType.ASIAN),      # 02:00 UTC = Asian
        ("2025-01-01 07:30:00", SessionType.ASIAN),      # 07:30 UTC = Asian
        ("2025-01-01 10:00:00", SessionType.EUROPEAN),   # 10:00 UTC = European
        ("2025-01-01 18:00:00", SessionType.US),         # 18:00 UTC = US
    ]

    all_passed = True
    for time_str, expected_session in test_cases:
        dt = datetime.fromisoformat(time_str).replace(tzinfo=timezone.utc)
        timestamp = dt.timestamp()

        detected_session = strategy.detect_session(timestamp)

        passed = detected_session == expected_session
        all_passed &= passed

        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {time_str} UTC -> {detected_session.value} (expected: {expected_session.value})")

    print(f"\nSession Detection: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    return all_passed


def test_volume_filter():
    """Test volume filtering."""
    print("\n" + "="*80)
    print("TEST 2: Volume Filter")
    print("="*80)

    strategy = create_overnight_momentum_strategy(
        enabled=True,
        backtest_only=True,
    )

    # Test cases
    test_cases = [
        (100.0, 1000.0, True),   # 10th percentile -> PASS
        (500.0, 1000.0, True),   # 50th percentile -> PASS (at threshold)
        (600.0, 1000.0, False),  # 60th percentile -> FAIL
        (1000.0, 1000.0, False), # 100th percentile -> FAIL
    ]

    all_passed = True
    for current_vol, avg_vol, expected_pass in test_cases:
        passes, percentile = strategy.check_volume_filter(current_vol, avg_vol)

        passed = passes == expected_pass
        all_passed &= passed

        status = "✅ PASS" if passed else "❌ FAIL"
        result = "PASS" if passes else "FAIL"
        print(f"{status} Volume {current_vol}/{avg_vol} = {percentile:.1f}th percentile -> {result}")

    print(f"\nVolume Filter: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    return all_passed


def test_momentum_detection():
    """Test momentum detection."""
    print("\n" + "="*80)
    print("TEST 3: Momentum Detection")
    print("="*80)

    # Use lower momentum threshold for testing
    import os
    os.environ["OVERNIGHT_MOMENTUM_THRESHOLD"] = "0.2"

    strategy = create_overnight_momentum_strategy(
        enabled=True,
        backtest_only=True,
    )

    # Create stronger uptrend with volatility expansion
    uptrend_prices = []
    base = 100.0
    for i in range(20):
        # Exponential trend with increasing volatility
        uptrend_prices.append(Decimal(str(base + i * 2)))
        base += 0.5

    volumes = [1000.0] * 20
    current_price = Decimal("140")

    has_momentum, strength, direction = strategy.detect_momentum(
        uptrend_prices, volumes, current_price
    )

    print(f"Uptrend test:")
    print(f"  Momentum detected: {has_momentum}")
    print(f"  Strength: {strength:.3f}")
    print(f"  Direction: {direction}")

    uptrend_passed = has_momentum and direction == "long"

    # Create stronger downtrend with volatility expansion
    downtrend_prices = []
    base = 140.0
    for i in range(20):
        downtrend_prices.append(Decimal(str(base - i * 2)))
        base -= 0.5

    has_momentum, strength, direction = strategy.detect_momentum(
        downtrend_prices, volumes, current_price
    )

    print(f"\nDowntrend test:")
    print(f"  Momentum detected: {has_momentum}")
    print(f"  Strength: {strength:.3f}")
    print(f"  Direction: {direction}")

    downtrend_passed = has_momentum and direction == "short"

    # Create flat prices (no momentum)
    flat_prices = [Decimal("100")] * 20

    has_momentum, strength, direction = strategy.detect_momentum(
        flat_prices, volumes, current_price
    )

    print(f"\nFlat (no momentum) test:")
    print(f"  Momentum detected: {has_momentum}")
    print(f"  Strength: {strength:.3f}")
    print(f"  Direction: {direction}")

    flat_passed = not has_momentum or strength < 0.3

    all_passed = uptrend_passed and downtrend_passed and flat_passed

    print(f"\nMomentum Detection: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    return all_passed


def test_position_manager():
    """Test position manager with leverage proxy."""
    print("\n" + "="*80)
    print("TEST 4: Position Manager (Leverage Proxy)")
    print("="*80)

    position_manager = create_overnight_position_manager(
        spot_notional_multiplier=2.0,  # 2x leverage proxy
    )

    # Mock signal
    from strategies.overnight_momentum import OvernightSignal
    signal = OvernightSignal(
        signal_id="test_001",
        symbol="BTC/USD",
        side="long",
        entry_price=Decimal("50000"),
        target_price=Decimal("50750"),  # 1.5% target
        trailing_stop_pct=Decimal("0.7"),
        confidence=Decimal("0.8"),
        session=SessionType.ASIAN,
        volume_percentile=30.0,
        momentum_strength=0.75,
        timestamp=time.time(),
        metadata={},
    )

    # Calculate position size
    equity_usd = Decimal("10000")
    risk_pct = Decimal("1.0")

    position_size = position_manager.calculate_position_size(
        signal=signal,
        equity_usd=equity_usd,
        risk_per_trade_pct=risk_pct,
    )

    print(f"Equity: ${equity_usd}")
    print(f"Risk per trade: {risk_pct}%")
    print(f"Risk amount: ${equity_usd * risk_pct / 100}")
    print(f"Trailing stop: {signal.trailing_stop_pct}%")
    print(f"Base position size: ${equity_usd * risk_pct / 100 / (signal.trailing_stop_pct / 100):.2f}")
    print(f"Position size with 2x leverage proxy: ${position_size:.2f}")

    # Expected: $10k * 1% / 0.7% = $1,428 base -> $2,857 with 2x
    expected_base = equity_usd * risk_pct / Decimal("100") / (signal.trailing_stop_pct / Decimal("100"))
    expected_with_proxy = expected_base * Decimal("2.0")

    leverage_proxy_passed = abs(position_size - expected_with_proxy) < Decimal("1")

    print(f"\n{'✅ PASS' if leverage_proxy_passed else '❌ FAIL'}: Leverage proxy calculation")

    # Test position opening
    position = position_manager.open_position(
        signal=signal,
        position_size_usd=position_size,
    )

    print(f"\nPosition opened:")
    print(f"  Symbol: {position.symbol}")
    print(f"  Side: {position.side}")
    print(f"  Entry: ${position.entry_price}")
    print(f"  Target: ${position.target_price}")
    print(f"  Stop: ${position.stop_loss}")
    print(f"  Quantity: {position.quantity:.6f}")
    print(f"  Notional: ${position.notional_usd:.2f}")

    position_opened = position_manager.get_position_count() == 1

    # Test trailing stop update
    new_price = Decimal("50500")  # Price moved up
    stop_updated = position_manager.update_trailing_stop("BTC/USD", new_price)

    updated_position = position_manager.get_position("BTC/USD")
    print(f"\nTrailing stop update (price moved to ${new_price}):")
    print(f"  Stop updated: {stop_updated}")
    print(f"  New stop: ${updated_position.stop_loss:.2f}")

    # Test exit check
    exit_price = Decimal("50750")  # Hit target
    should_exit, reason = position_manager.check_exit("BTC/USD", exit_price)

    print(f"\nExit check at ${exit_price}:")
    print(f"  Should exit: {should_exit}")
    print(f"  Reason: {reason}")

    exit_logic_passed = should_exit and reason == "target_reached"

    all_passed = leverage_proxy_passed and position_opened and exit_logic_passed

    print(f"\nPosition Manager: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    return all_passed


def test_backtest_framework():
    """Test backtest framework with synthetic data."""
    print("\n" + "="*80)
    print("TEST 5: Backtest Framework")
    print("="*80)

    # Use lower momentum threshold for testing
    import os
    os.environ["OVERNIGHT_MOMENTUM_THRESHOLD"] = "0.2"

    # Create strategy and position manager
    strategy = create_overnight_momentum_strategy(
        enabled=True,
        backtest_only=True,
    )

    position_manager = create_overnight_position_manager(
        spot_notional_multiplier=2.0,
    )

    # Create backtester
    backtester = OvernightBacktester(
        strategy=strategy,
        position_manager=position_manager,
        config=BacktestConfig(
            initial_equity_usd=Decimal("10000"),
            risk_per_trade_pct=Decimal("1.0"),
        ),
    )

    # Generate synthetic data (30 days, 1-hour bars)
    print("\nGenerating synthetic data...")

    num_bars = 30 * 24  # 30 days
    base_price = 50000.0
    base_volume = 1000.0

    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    # Start time: Asian session
    current_time = datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp()

    for i in range(num_bars):
        dt = datetime.fromtimestamp(current_time, tz=timezone.utc)
        hour = dt.hour

        # Asian session (00:00-08:00 UTC): add stronger trends with momentum
        if 0 <= hour < 8:
            # Create alternating strong trends every 2 days
            if i % 48 < 24:
                # Strong uptrend
                trend = 200.0 + (i % 24) * 20.0
            else:
                # Strong downtrend
                trend = -200.0 - (i % 24) * 20.0
            volatility = 0.02  # Higher volatility for momentum detection
            low_volume = True
        else:
            trend = 0.0
            volatility = 0.005
            low_volume = False

        # Generate OHLC with stronger movements
        open_price = base_price + np.random.normal(trend * 0.3, base_price * volatility)
        close_price = open_price + np.random.normal(trend * 0.5, base_price * volatility)
        high_price = max(open_price, close_price) + abs(np.random.normal(trend * 0.1, base_price * volatility))
        low_price = min(open_price, close_price) - abs(np.random.normal(trend * 0.1, base_price * volatility))

        volume = base_volume * (0.3 if low_volume else 1.0) * (0.8 + 0.4 * np.random.random())

        timestamps.append(current_time)
        opens.append(open_price)
        highs.append(high_price)
        lows.append(low_price)
        closes.append(close_price)
        volumes.append(volume)

        base_price = close_price  # Update base for next bar
        current_time += 3600  # 1 hour

    # Create DataFrame
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
    })

    print(f"Generated {len(df)} bars of synthetic data")
    print(f"Date range: {datetime.fromtimestamp(df.iloc[0]['timestamp'], tz=timezone.utc)} to "
          f"{datetime.fromtimestamp(df.iloc[-1]['timestamp'], tz=timezone.utc)}")

    # Run backtest
    print("\nRunning backtest...")
    results = backtester.run(df, symbol="BTC/USD")

    # Print report
    report = create_backtest_report(results)
    print(report)

    # Print trade log
    print_trade_log(results, max_trades=10)

    # Check if backtest ran successfully
    backtest_passed = results.total_trades > 0

    print(f"\nBacktest Framework: {'✅ TEST PASSED' if backtest_passed else '❌ TEST FAILED'}")
    return backtest_passed


def test_promotion_gates():
    """Test promotion gate validation."""
    print("\n" + "="*80)
    print("TEST 6: Promotion Gates")
    print("="*80)

    strategy = create_overnight_momentum_strategy(
        enabled=True,
        backtest_only=True,
    )

    # Test passing gates
    passing_results = {
        "total_trades": 60,
        "win_rate": 0.60,
        "sharpe_ratio": 1.8,
        "max_drawdown": 0.08,
    }

    passes, failed_gates = strategy.check_promotion_gates(passing_results)

    print("Test 1: Passing results")
    print(f"  Total trades: {passing_results['total_trades']}")
    print(f"  Win rate: {passing_results['win_rate']:.1%}")
    print(f"  Sharpe: {passing_results['sharpe_ratio']:.2f}")
    print(f"  Max DD: {passing_results['max_drawdown']:.1%}")
    print(f"  Result: {'✅ PASS' if passes else '❌ FAIL'}")

    if failed_gates:
        for gate in failed_gates:
            print(f"    - {gate}")

    passing_test = passes

    # Test failing gates
    failing_results = {
        "total_trades": 30,  # Too few
        "win_rate": 0.45,    # Too low
        "sharpe_ratio": 1.0, # Too low
        "max_drawdown": 0.15,# Too high
    }

    passes, failed_gates = strategy.check_promotion_gates(failing_results)

    print("\nTest 2: Failing results")
    print(f"  Total trades: {failing_results['total_trades']}")
    print(f"  Win rate: {failing_results['win_rate']:.1%}")
    print(f"  Sharpe: {failing_results['sharpe_ratio']:.2f}")
    print(f"  Max DD: {failing_results['max_drawdown']:.1%}")
    print(f"  Result: {'❌ FAIL' if not passes else '✅ PASS (unexpected!)'}")

    if failed_gates:
        print("  Failed gates:")
        for gate in failed_gates:
            print(f"    - {gate}")

    failing_test = not passes and len(failed_gates) > 0

    all_passed = passing_test and failing_test

    print(f"\nPromotion Gates: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    return all_passed


def main():
    """Run all tests."""
    print("="*80)
    print("OVERNIGHT MOMENTUM STRATEGY - COMPREHENSIVE TEST SUITE")
    print("="*80)

    results = {}

    # Run all tests
    results['session_detection'] = test_session_detection()
    results['volume_filter'] = test_volume_filter()
    results['momentum_detection'] = test_momentum_detection()
    results['position_manager'] = test_position_manager()
    results['backtest_framework'] = test_backtest_framework()
    results['promotion_gates'] = test_promotion_gates()

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {test_name}")

    total_tests = len(results)
    passed_tests = sum(results.values())

    print(f"\nTotal: {passed_tests}/{total_tests} tests passed")

    if all(results.values()):
        print("\n🎉 ALL TESTS PASSED - Strategy ready for backtesting!")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED - Review implementation")
        return 1


if __name__ == "__main__":
    exit(main())
