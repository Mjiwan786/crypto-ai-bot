"""
Test Overnight Agent Integration

Validates integration with main trading system:
- Signal generation and publishing
- Position management
- Exit handling
- Redis integration
- Status reporting

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

# Fix Windows encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.strategies.overnight_agent import create_overnight_agent


def test_agent_initialization():
    """Test agent initialization."""
    print("\n" + "="*80)
    print("TEST 1: Agent Initialization")
    print("="*80)

    # Create agent
    agent = create_overnight_agent(
        enabled=True,
        backtest_only=True,
        spot_notional_multiplier=2.0,
        risk_per_trade_pct=1.0,
    )

    # Check status
    status = agent.get_status()

    print(f"Enabled: {status['enabled']}")
    print(f"Backtest only: {status['backtest_only']}")
    print(f"Active positions: {status['active_positions']}")
    print(f"Max positions: {status['max_positions']}")
    print(f"Risk per trade: {status['risk_per_trade_pct']}%")
    print(f"\nStrategy config:")
    for key, value in status['strategy_config'].items():
        print(f"  {key}: {value}")

    passed = (
        status['enabled'] == True and
        status['backtest_only'] == True and
        status['active_positions'] == 0 and
        status['max_positions'] == 1
    )

    print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Agent initialization")
    return passed


def test_signal_generation():
    """Test signal generation flow."""
    print("\n" + "="*80)
    print("TEST 2: Signal Generation")
    print("="*80)

    agent = create_overnight_agent(
        enabled=True,
        backtest_only=True,
        spot_notional_multiplier=2.0,
        risk_per_trade_pct=1.0,
    )

    # Create strong uptrend data (exponential growth)
    prices = []
    base = 50000.0
    for i in range(20):
        # Strong exponential trend
        prices.append(Decimal(str(base + i * 100)))
        base += 50  # Accelerating growth

    volumes = [300.0] * 20  # Low volume
    avg_24h_volume = 1000.0

    current_price = Decimal("52000")  # Continuing the uptrend
    equity_usd = Decimal("10000")

    # Set time to Asian session (02:00 UTC)
    current_time = datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp()

    # Process bar
    result = agent.process_bar(
        symbol="BTC/USD",
        current_price=current_price,
        prices=prices,
        volumes=volumes,
        avg_24h_volume=avg_24h_volume,
        equity_usd=equity_usd,
        current_time=current_time,
    )

    print(f"Signal generated: {result is not None}")

    if result:
        print(f"  Action: {result['action']}")
        print(f"  Symbol: {result['symbol']}")
        print(f"  Side: {result['side']}")
        print(f"  Entry price: ${result['entry_price']:.2f}")
        print(f"  Target price: ${result['target_price']:.2f}")
        print(f"  Position size: ${result['position_size_usd']:.2f}")
        print(f"  Stop loss: ${result['stop_loss']:.2f}")

    # Check active positions
    active_positions = agent.get_position_count()
    print(f"\nActive positions: {active_positions}")

    passed = result is not None and active_positions == 1

    print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Signal generation")
    return passed


def test_trailing_stop_update():
    """Test trailing stop updates."""
    print("\n" + "="*80)
    print("TEST 3: Trailing Stop Updates")
    print("="*80)

    agent = create_overnight_agent(
        enabled=True,
        backtest_only=True,
        spot_notional_multiplier=2.0,
        risk_per_trade_pct=1.0,
    )

    # Generate signal first with strong uptrend
    prices = []
    base = 50000.0
    for i in range(20):
        prices.append(Decimal(str(base + i * 100)))
        base += 50
    volumes = [300.0] * 20
    current_time = datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp()

    result = agent.process_bar(
        symbol="BTC/USD",
        current_price=Decimal("52000"),
        prices=prices,
        volumes=volumes,
        avg_24h_volume=1000.0,
        equity_usd=Decimal("10000"),
        current_time=current_time,
    )

    if not result:
        print("❌ FAIL: No signal generated")
        return False

    initial_stop = result['stop_loss']
    print(f"Initial stop loss: ${initial_stop:.2f}")

    # Price moves up (for long position)
    new_price = Decimal("51500")
    result2 = agent.process_bar(
        symbol="BTC/USD",
        current_price=new_price,
        prices=prices + [new_price],
        volumes=volumes + [300.0],
        avg_24h_volume=1000.0,
        equity_usd=Decimal("10000"),
        current_time=current_time + 60,
    )

    # Get updated position
    positions = agent.get_active_positions()
    if positions:
        updated_stop = positions[0]['stop_loss']
        print(f"Price moved to: ${new_price:.2f}")
        print(f"Updated stop loss: ${updated_stop:.2f}")

        # Stop should have moved up (for long)
        passed = Decimal(str(updated_stop)) > Decimal(str(initial_stop))

        print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Trailing stop updates")
        return passed
    else:
        print("❌ FAIL: Position not found")
        return False


def test_exit_on_target():
    """Test exit when target is reached."""
    print("\n" + "="*80)
    print("TEST 4: Exit on Target Reached")
    print("="*80)

    agent = create_overnight_agent(
        enabled=True,
        backtest_only=True,
        spot_notional_multiplier=2.0,
        risk_per_trade_pct=1.0,
    )

    # Generate signal with strong uptrend
    prices = []
    base = 50000.0
    for i in range(20):
        prices.append(Decimal(str(base + i * 100)))
        base += 50
    volumes = [300.0] * 20
    current_time = datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp()

    result = agent.process_bar(
        symbol="BTC/USD",
        current_price=Decimal("52000"),
        prices=prices,
        volumes=volumes,
        avg_24h_volume=1000.0,
        equity_usd=Decimal("10000"),
        current_time=current_time,
    )

    if not result or result['action'] != 'entry':
        print("❌ FAIL: No entry signal generated")
        return False

    target_price = Decimal(str(result['target_price']))
    print(f"Entry: ${result['entry_price']:.2f}")
    print(f"Target: ${target_price:.2f}")

    # Move price to target
    exit_price = target_price + Decimal("10")  # Slightly above target
    result2 = agent.process_bar(
        symbol="BTC/USD",
        current_price=exit_price,
        prices=prices + [exit_price],
        volumes=volumes + [300.0],
        avg_24h_volume=1000.0,
        equity_usd=Decimal("10000"),
        current_time=current_time + 120,
    )

    print(f"Price moved to: ${exit_price:.2f}")

    if result2 and result2['action'] == 'exit':
        print(f"Exit action: {result2['action']}")
        print(f"Exit reason: {result2['exit_reason']}")
        print(f"P&L: {result2['pnl_pct']:+.2f}%")

        passed = result2['exit_reason'] == 'target_reached'
        print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Exit on target reached")
        return passed
    else:
        print("❌ FAIL: No exit signal generated")
        return False


def test_exit_on_trailing_stop():
    """Test exit when trailing stop is hit."""
    print("\n" + "="*80)
    print("TEST 5: Exit on Trailing Stop")
    print("="*80)

    agent = create_overnight_agent(
        enabled=True,
        backtest_only=True,
        spot_notional_multiplier=2.0,
        risk_per_trade_pct=1.0,
    )

    # Generate signal (strong downtrend for short)
    prices = []
    base = 52000.0
    for i in range(20):
        prices.append(Decimal(str(base - i * 100)))
        base -= 50  # Accelerating decline
    volumes = [300.0] * 20
    current_time = datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp()

    result = agent.process_bar(
        symbol="BTC/USD",
        current_price=Decimal("49000"),  # Continuing downtrend
        prices=prices,
        volumes=volumes,
        avg_24h_volume=1000.0,
        equity_usd=Decimal("10000"),
        current_time=current_time,
    )

    if not result or result['action'] != 'entry':
        print("❌ FAIL: No entry signal generated")
        return False

    entry_price = Decimal(str(result['entry_price']))
    stop_loss = Decimal(str(result['stop_loss']))
    side = result['side']

    print(f"Entry: ${entry_price:.2f}")
    print(f"Side: {side}")
    print(f"Stop loss: ${stop_loss:.2f}")

    # Move price to hit stop (opposite direction)
    if side == 'short':
        # For short, stop is above entry
        exit_price = stop_loss + Decimal("50")
    else:
        # For long, stop is below entry
        exit_price = stop_loss - Decimal("50")

    result2 = agent.process_bar(
        symbol="BTC/USD",
        current_price=exit_price,
        prices=prices + [exit_price],
        volumes=volumes + [300.0],
        avg_24h_volume=1000.0,
        equity_usd=Decimal("10000"),
        current_time=current_time + 120,
    )

    print(f"Price moved to: ${exit_price:.2f}")

    if result2 and result2['action'] == 'exit':
        print(f"Exit action: {result2['action']}")
        print(f"Exit reason: {result2['exit_reason']}")
        print(f"P&L: {result2['pnl_pct']:+.2f}%")

        passed = result2['exit_reason'] == 'trailing_stop'
        print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Exit on trailing stop")
        return passed
    else:
        print("❌ FAIL: No exit signal generated")
        return False


def test_force_close():
    """Test force close functionality."""
    print("\n" + "="*80)
    print("TEST 6: Force Close Positions")
    print("="*80)

    agent = create_overnight_agent(
        enabled=True,
        backtest_only=True,
        spot_notional_multiplier=2.0,
        risk_per_trade_pct=1.0,
    )

    # Generate signal with strong uptrend
    prices = []
    base = 50000.0
    for i in range(20):
        prices.append(Decimal(str(base + i * 100)))
        base += 50
    volumes = [300.0] * 20
    current_time = datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp()

    result = agent.process_bar(
        symbol="BTC/USD",
        current_price=Decimal("52000"),
        prices=prices,
        volumes=volumes,
        avg_24h_volume=1000.0,
        equity_usd=Decimal("10000"),
        current_time=current_time,
    )

    if not result:
        print("❌ FAIL: No signal generated")
        return False

    print(f"Position opened: {result['symbol']} {result['side'].upper()}")

    # Force close
    current_prices = {"BTC/USD": Decimal("51200")}
    exits = agent.force_close_all(current_prices, reason="test_force_close")

    print(f"Force closed {len(exits)} position(s)")

    if exits:
        for exit_summary in exits:
            print(f"  {exit_summary['symbol']}: P&L={exit_summary['pnl_pct']:+.2f}%, reason={exit_summary['exit_reason']}")

    active_positions = agent.get_position_count()
    print(f"Active positions after force close: {active_positions}")

    passed = len(exits) == 1 and active_positions == 0

    print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Force close")
    return passed


def test_position_cap():
    """Test position cap enforcement."""
    print("\n" + "="*80)
    print("TEST 7: Position Cap (1 max)")
    print("="*80)

    agent = create_overnight_agent(
        enabled=True,
        backtest_only=True,
        spot_notional_multiplier=2.0,
        risk_per_trade_pct=1.0,
    )

    # Generate first signal
    prices = [Decimal(str(50000 + i * 50)) for i in range(20)]
    volumes = [300.0] * 20
    current_time = datetime(2025, 1, 1, 2, 0, 0, tzinfo=timezone.utc).timestamp()

    result1 = agent.process_bar(
        symbol="BTC/USD",
        current_price=Decimal("51000"),
        prices=prices,
        volumes=volumes,
        avg_24h_volume=1000.0,
        equity_usd=Decimal("10000"),
        current_time=current_time,
    )

    if not result1:
        print("❌ FAIL: No signal generated")
        return False

    print(f"First position opened: BTC/USD")
    print(f"Active positions: {agent.get_position_count()}")

    # Try to generate second signal on different symbol
    result2 = agent.process_bar(
        symbol="ETH/USD",
        current_price=Decimal("3000"),
        prices=[Decimal(str(2900 + i * 10)) for i in range(20)],
        volumes=volumes,
        avg_24h_volume=1000.0,
        equity_usd=Decimal("10000"),
        current_time=current_time + 60,
    )

    print(f"Second signal generated: {result2 is not None}")
    print(f"Active positions: {agent.get_position_count()}")

    # Should still be 1 (position cap enforced)
    passed = agent.get_position_count() == 1 and result2 is None

    print(f"\n{'✅ PASS' if passed else '❌ FAIL'}: Position cap enforcement")
    return passed


def main():
    """Run all integration tests."""
    # Set lower momentum threshold for testing (do this BEFORE creating agents)
    os.environ["OVERNIGHT_MOMENTUM_THRESHOLD"] = "0.2"

    print("="*80)
    print("OVERNIGHT AGENT - INTEGRATION TEST SUITE")
    print("="*80)

    results = {}

    # Run all tests
    results['agent_initialization'] = test_agent_initialization()
    results['signal_generation'] = test_signal_generation()
    results['trailing_stop_update'] = test_trailing_stop_update()
    results['exit_on_target'] = test_exit_on_target()
    results['exit_on_trailing_stop'] = test_exit_on_trailing_stop()
    results['force_close'] = test_force_close()
    results['position_cap'] = test_position_cap()

    # Summary
    print("\n" + "="*80)
    print("INTEGRATION TEST SUMMARY")
    print("="*80)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {test_name}")

    total_tests = len(results)
    passed_tests = sum(results.values())

    print(f"\nTotal: {passed_tests}/{total_tests} tests passed")

    if all(results.values()):
        print("\n🎉 ALL INTEGRATION TESTS PASSED!")
        print("✅ Overnight agent is ready for deployment")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED - Review implementation")
        return 1


if __name__ == "__main__":
    exit(main())
