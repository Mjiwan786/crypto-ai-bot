#!/usr/bin/env python3
"""Test script for agents.core.types module."""

from decimal import Decimal
import time

from agents.core.types import (
    Side,
    Timeframe,
    OrderType,
    OrderStatus,
    SignalType,
    Signal,
    OrderIntent,
    Order,
    ExecutionResult,
    MarketData,
)


def test_enums() -> None:
    """Test enum conversions and validation."""
    print("\n=== Testing Enums ===")

    # Test Side
    assert Side.from_str("buy") == Side.BUY
    assert Side.from_str("SELL") == Side.SELL
    assert Side.from_str("  long  ") == Side.BUY
    print("[OK] Side enum works")

    # Test Timeframe
    assert Timeframe.from_str("15s") == Timeframe.T15S
    assert Timeframe.from_str("1h") == Timeframe.H1
    print("[OK] Timeframe enum works")

    # Test OrderType
    assert OrderType.from_str("limit") == OrderType.LIMIT
    assert OrderType.from_str("IOC") == OrderType.IOC
    print("[OK] OrderType enum works")

    # Test invalid values
    try:
        Side.from_str("invalid")
        assert False, "Should have raised ValueError"
    except ValueError:
        print("[OK] Side validation works")


def test_signal() -> None:
    """Test Signal dataclass."""
    print("\n=== Testing Signal ===")

    signal = Signal(
        symbol="BTC/USD",
        side=Side.BUY,
        confidence=0.85,
        price=Decimal("50000.00"),
        timestamp=time.time(),
        strategy="scalp",
        signal_type=SignalType.SCALP,
        timeframe=Timeframe.T15S,
        stop_loss_bps=6,
        take_profit_bps=[12, 20],
        ttl_seconds=300,
        features={"spread_bps": 2.5, "volume_ratio": 1.8},
        notes="High confidence scalp signal",
    )

    print(f"  Symbol: {signal.symbol}")
    print(f"  Side: {signal.side.value}")
    print(f"  Confidence: {signal.confidence}")
    print(f"  Price: {signal.price}")

    # Test to_dict
    signal_dict = signal.to_dict()
    assert signal_dict["symbol"] == "BTC/USD"
    assert signal_dict["side"] == "buy"
    print("[OK] Signal.to_dict() works")

    # Test from_dict
    signal2 = Signal.from_dict(signal_dict)
    assert signal2.symbol == signal.symbol
    assert signal2.side == signal.side
    print("[OK] Signal.from_dict() works")

    # Test validation
    try:
        Signal(
            symbol="BTC/USD",
            side=Side.BUY,
            confidence=1.5,  # Invalid: > 1.0
            price=Decimal("50000"),
            timestamp=time.time(),
            strategy="test",
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"[OK] Signal validation works: {e}")


def test_order_intent() -> None:
    """Test OrderIntent dataclass."""
    print("\n=== Testing OrderIntent ===")

    intent = OrderIntent(
        symbol="ETH/USD",
        side=Side.SELL,
        quantity=Decimal("1.5"),
        order_type=OrderType.POST_ONLY,
        price=Decimal("3000.00"),
        strategy="scalp",
    )

    print(f"  Symbol: {intent.symbol}")
    print(f"  Quantity: {intent.quantity}")
    print(f"  Order Type: {intent.order_type.value}")

    # Test validation - limit order requires price
    try:
        OrderIntent(
            symbol="BTC/USD",
            side=Side.BUY,
            quantity=Decimal("0.1"),
            order_type=OrderType.LIMIT,
            price=None,  # Invalid: limit orders need price
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"[OK] OrderIntent validation works: {e}")


def test_order() -> None:
    """Test Order dataclass."""
    print("\n=== Testing Order ===")

    order = Order(
        order_id="ORDER-123456",
        symbol="BTC/USD",
        side=Side.BUY,
        quantity=Decimal("0.5"),
        order_type=OrderType.LIMIT,
        status=OrderStatus.PARTIALLY_FILLED,
        price=Decimal("50000"),
        filled_quantity=Decimal("0.3"),
        average_fill_price=Decimal("49950"),
        fee=Decimal("15.00"),
        timestamp=time.time(),
        strategy="scalp",
    )

    print(f"  Order ID: {order.order_id}")
    print(f"  Status: {order.status.value}")
    print(f"  Filled: {order.filled_quantity}/{order.quantity}")
    print(f"  Remaining: {order.remaining_quantity}")
    print(f"  Is Filled: {order.is_filled}")

    assert order.remaining_quantity == Decimal("0.2")
    assert not order.is_filled
    print("[OK] Order properties work")


def test_execution_result() -> None:
    """Test ExecutionResult dataclass."""
    print("\n=== Testing ExecutionResult ===")

    result = ExecutionResult(
        success=True,
        order_id="ORDER-789",
        filled_quantity=Decimal("1.0"),
        average_price=Decimal("50000"),
        fee=Decimal("25.00"),
        execution_time_ms=45.3,
        slippage_bps=1.2,
        timestamp=time.time(),
    )

    print(f"  Success: {result.success}")
    print(f"  Execution Time: {result.execution_time_ms}ms")
    print(f"  Slippage: {result.slippage_bps}bps")

    result_dict = result.to_dict()
    assert result_dict["success"] is True
    print("[OK] ExecutionResult works")


def test_market_data() -> None:
    """Test MarketData dataclass."""
    print("\n=== Testing MarketData ===")

    data = MarketData(
        symbol="BTC/USD",
        timestamp=time.time(),
        bid=Decimal("49990"),
        ask=Decimal("50010"),
        last_price=Decimal("50000"),
        volume=Decimal("125.5"),
    )

    print(f"  Symbol: {data.symbol}")
    print(f"  Bid: {data.bid}")
    print(f"  Ask: {data.ask}")
    print(f"  Mid Price: {data.calculated_mid_price}")
    print(f"  Spread: {data.calculated_spread_bps}bps")

    assert data.calculated_mid_price == Decimal("50000")
    assert data.calculated_spread_bps is not None
    assert abs(data.calculated_spread_bps - 4.0) < 0.1  # ~4 bps spread
    print("[OK] MarketData calculations work")


def main() -> None:
    """Run all tests."""
    print("="*70)
    print("TESTING agents.core.types")
    print("="*70)

    test_enums()
    test_signal()
    test_order_intent()
    test_order()
    test_execution_result()
    test_market_data()

    print("\n" + "="*70)
    print("[SUCCESS] ALL TESTS PASSED")
    print("="*70)


if __name__ == "__main__":
    main()
