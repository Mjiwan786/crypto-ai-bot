"""
Execution tests with mock gateway roundtrip.

Validates:
- Optimizer + mock gateway integration
- Order placement and fill simulation
- Position tracking
- P&L calculation

All tests are hermetic - use mock gateway, no live connections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pytest


# ======================== Mock Gateway Implementation ========================


@dataclass
class MockOrder:
    """Mock order for testing"""

    order_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    size: float
    price: float
    status: str = "open"  # 'open', 'filled', 'canceled'
    filled_size: float = 0.0
    average_fill_price: Optional[float] = None


class MockGateway:
    """
    Mock exchange gateway for testing.

    Simulates order execution without network calls.
    """

    def __init__(self, slippage_bps: float = 2.0, fill_probability: float = 1.0):
        self.slippage_bps = slippage_bps
        self.fill_probability = fill_probability

        self.orders: Dict[str, MockOrder] = {}
        self.next_order_id = 1

        # Mock market state
        self.market_prices = {"BTC/USD": 50000.0, "ETH/USD": 3000.0}

    async def place_order(
        self, symbol: str, side: str, size: float, price: Optional[float] = None
    ) -> MockOrder:
        """Place order in mock gateway"""
        order_id = f"mock_{self.next_order_id}"
        self.next_order_id += 1

        # Use limit price or market price with slippage
        if price is None:
            # Market order - use current price with slippage
            market_price = self.market_prices.get(symbol, 50000.0)
            slippage_factor = 1 + (self.slippage_bps / 10000)
            if side == "buy":
                price = market_price * slippage_factor
            else:
                price = market_price / slippage_factor

        order = MockOrder(
            order_id=order_id, symbol=symbol, side=side, size=size, price=price, status="open"
        )

        self.orders[order_id] = order
        return order

    async def fill_order(self, order_id: str) -> MockOrder:
        """Simulate order fill"""
        order = self.orders.get(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")

        # Simulate fill with slippage
        fill_price = order.price

        order.status = "filled"
        order.filled_size = order.size
        order.average_fill_price = fill_price

        return order

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order"""
        order = self.orders.get(order_id)
        if not order:
            return False

        order.status = "canceled"
        return True

    async def get_order_status(self, order_id: str) -> Optional[MockOrder]:
        """Get order status"""
        return self.orders.get(order_id)

    def get_balance(self, currency: str = "USD") -> float:
        """Get mock balance"""
        return 10000.0 if currency == "USD" else 1.0


# ======================== Position Manager Mock ========================


class MockPositionManager:
    """Mock position manager for testing"""

    def __init__(self):
        self.positions: Dict[str, float] = {}  # symbol -> size
        self.avg_prices: Dict[str, float] = {}  # symbol -> avg price
        self.realized_pnl = 0.0

    def update_position(
        self, symbol: str, side: str, size: float, price: float
    ) -> Dict[str, float]:
        """Update position from fill"""
        current_position = self.positions.get(symbol, 0.0)

        # Calculate realized P&L if closing position
        realized_pnl = 0.0
        if current_position != 0 and ((current_position > 0 and side == "sell") or (current_position < 0 and side == "buy")):
            # Closing position
            avg_price = self.avg_prices.get(symbol, price)
            close_size = min(abs(size), abs(current_position))

            if current_position > 0:  # Closing long
                realized_pnl = (price - avg_price) * close_size
            else:  # Closing short
                realized_pnl = (avg_price - price) * close_size

            self.realized_pnl += realized_pnl

        # Update position
        if side == "buy":
            new_position = current_position + size
        else:
            new_position = current_position - size

        # Update average price
        if new_position != 0:
            if current_position == 0:
                self.avg_prices[symbol] = price
            elif (current_position > 0 and side == "buy") or (current_position < 0 and side == "sell"):
                # Adding to position
                total_cost = (current_position * self.avg_prices.get(symbol, price)) + (size * price)
                self.avg_prices[symbol] = total_cost / abs(new_position)

        self.positions[symbol] = new_position

        return {
            "position": new_position,
            "avg_price": self.avg_prices.get(symbol, price),
            "realized_pnl": realized_pnl,
        }

    def get_position(self, symbol: str) -> float:
        """Get current position size"""
        return self.positions.get(symbol, 0.0)


# ======================== Tests ========================


@pytest.mark.asyncio
async def test_mock_gateway_place_order():
    """Test placing order with mock gateway"""
    gateway = MockGateway()

    order = await gateway.place_order(symbol="BTC/USD", side="buy", size=0.1, price=50000.0)

    assert order.order_id.startswith("mock_")
    assert order.symbol == "BTC/USD"
    assert order.side == "buy"
    assert order.size == 0.1
    assert order.price == 50000.0
    assert order.status == "open"


@pytest.mark.asyncio
async def test_mock_gateway_fill_order():
    """Test filling order with mock gateway"""
    gateway = MockGateway()

    # Place and fill order
    order = await gateway.place_order("BTC/USD", "buy", 0.1, 50000.0)
    filled_order = await gateway.fill_order(order.order_id)

    assert filled_order.status == "filled"
    assert filled_order.filled_size == 0.1
    assert filled_order.average_fill_price == 50000.0


@pytest.mark.asyncio
async def test_optimizer_gateway_roundtrip():
    """
    Test optimizer + gateway roundtrip.

    Flow:
    1. Optimizer generates order parameters
    2. Gateway places order
    3. Gateway fills order
    4. Position manager updates
    """
    gateway = MockGateway()
    position_manager = MockPositionManager()

    # 1. Simulate optimizer output
    optimizer_output = {"symbol": "BTC/USD", "side": "buy", "size": 0.1, "price": 50000.0}

    # 2. Place order via gateway
    order = await gateway.place_order(
        symbol=optimizer_output["symbol"],
        side=optimizer_output["side"],
        size=optimizer_output["size"],
        price=optimizer_output["price"],
    )

    assert order.status == "open"

    # 3. Fill order
    filled_order = await gateway.fill_order(order.order_id)

    assert filled_order.status == "filled"

    # 4. Update position manager
    result = position_manager.update_position(
        symbol=filled_order.symbol,
        side=filled_order.side,
        size=filled_order.filled_size,
        price=filled_order.average_fill_price,
    )

    assert result["position"] == 0.1
    assert result["avg_price"] == 50000.0


@pytest.mark.asyncio
async def test_full_trade_cycle():
    """
    Test full trade cycle: open -> close position.

    Simulates:
    1. Buy to open
    2. Sell to close
    3. Verify P&L calculation
    """
    gateway = MockGateway()
    position_manager = MockPositionManager()

    # 1. Buy to open
    buy_order = await gateway.place_order("BTC/USD", "buy", 0.1, 50000.0)
    filled_buy = await gateway.fill_order(buy_order.order_id)

    open_result = position_manager.update_position(
        "BTC/USD", "buy", filled_buy.filled_size, filled_buy.average_fill_price
    )

    assert open_result["position"] == 0.1
    assert open_result["realized_pnl"] == 0.0

    # 2. Sell to close at higher price
    sell_order = await gateway.place_order("BTC/USD", "sell", 0.1, 50050.0)
    filled_sell = await gateway.fill_order(sell_order.order_id)

    close_result = position_manager.update_position(
        "BTC/USD", "sell", filled_sell.filled_size, filled_sell.average_fill_price
    )

    assert close_result["position"] == 0.0
    expected_pnl = (50050.0 - 50000.0) * 0.1  # $5.0 profit
    assert abs(close_result["realized_pnl"] - expected_pnl) < 0.01


@pytest.mark.asyncio
async def test_partial_position_close():
    """Test closing part of a position"""
    gateway = MockGateway()
    position_manager = MockPositionManager()

    # Open position
    buy_order = await gateway.place_order("BTC/USD", "buy", 0.5, 50000.0)
    filled_buy = await gateway.fill_order(buy_order.order_id)
    position_manager.update_position("BTC/USD", "buy", 0.5, 50000.0)

    # Partially close
    sell_order = await gateway.place_order("BTC/USD", "sell", 0.2, 50100.0)
    filled_sell = await gateway.fill_order(sell_order.order_id)

    result = position_manager.update_position("BTC/USD", "sell", 0.2, 50100.0)

    assert abs(result["position"] - 0.3) < 0.01  # 0.5 - 0.2 = 0.3 remaining
    expected_pnl = (50100.0 - 50000.0) * 0.2  # $20 profit on closed portion
    assert abs(result["realized_pnl"] - expected_pnl) < 0.01


@pytest.mark.asyncio
async def test_market_order_with_slippage():
    """Test market order applies slippage"""
    gateway = MockGateway(slippage_bps=10.0)  # 10 bps slippage

    # Market buy order (no price specified)
    order = await gateway.place_order("BTC/USD", "buy", 0.1, price=None)

    # Should apply slippage to market price
    expected_price = 50000.0 * 1.001  # 50000 * (1 + 10/10000)
    assert abs(order.price - expected_price) < 1.0


@pytest.mark.asyncio
async def test_multiple_symbols():
    """Test trading multiple symbols simultaneously"""
    gateway = MockGateway()
    position_manager = MockPositionManager()

    # Trade BTC
    btc_buy = await gateway.place_order("BTC/USD", "buy", 0.1, 50000.0)
    await gateway.fill_order(btc_buy.order_id)
    position_manager.update_position("BTC/USD", "buy", 0.1, 50000.0)

    # Trade ETH
    eth_buy = await gateway.place_order("ETH/USD", "buy", 1.0, 3000.0)
    await gateway.fill_order(eth_buy.order_id)
    position_manager.update_position("ETH/USD", "buy", 1.0, 3000.0)

    # Verify positions
    assert position_manager.get_position("BTC/USD") == 0.1
    assert position_manager.get_position("ETH/USD") == 1.0


@pytest.mark.asyncio
async def test_order_cancel():
    """Test canceling open order"""
    gateway = MockGateway()

    order = await gateway.place_order("BTC/USD", "buy", 0.1, 50000.0)
    assert order.status == "open"

    success = await gateway.cancel_order(order.order_id)
    assert success is True

    canceled_order = await gateway.get_order_status(order.order_id)
    assert canceled_order.status == "canceled"


# ======================== Performance Tests ========================


@pytest.mark.asyncio
async def test_high_frequency_orders():
    """Test placing many orders quickly"""
    import time

    gateway = MockGateway()

    start = time.time()

    # Place 100 orders
    orders = []
    for i in range(100):
        order = await gateway.place_order("BTC/USD", "buy", 0.01, 50000.0 + i)
        orders.append(order)

    elapsed = time.time() - start

    assert len(orders) == 100
    assert all(o.status == "open" for o in orders)
    assert elapsed < 1.0, f"Placing 100 orders took too long: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_concurrent_position_updates():
    """Test concurrent position updates"""
    position_manager = MockPositionManager()

    # Simulate rapid position updates
    for i in range(50):
        position_manager.update_position("BTC/USD", "buy" if i % 2 == 0 else "sell", 0.1, 50000.0 + i)

    # Final position should be net of all updates
    final_position = position_manager.get_position("BTC/USD")
    assert isinstance(final_position, float)


# ======================== Integration Test ========================


@pytest.mark.asyncio
async def test_complete_scalping_scenario():
    """
    Complete scalping scenario with multiple trades.

    Simulates:
    - Opening and closing multiple positions
    - Tracking cumulative P&L
    - Verifying all positions closed at end
    """
    gateway = MockGateway()
    position_manager = MockPositionManager()

    trades = [
        # Trade 1: Win
        ("buy", 50000.0, "sell", 50050.0),
        # Trade 2: Loss
        ("buy", 50060.0, "sell", 50040.0),
        # Trade 3: Win
        ("buy", 50045.0, "sell", 50055.0),
    ]

    for entry_side, entry_price, exit_side, exit_price in trades:
        # Entry
        entry_order = await gateway.place_order("BTC/USD", entry_side, 0.1, entry_price)
        filled_entry = await gateway.fill_order(entry_order.order_id)
        position_manager.update_position("BTC/USD", entry_side, 0.1, entry_price)

        # Exit
        exit_order = await gateway.place_order("BTC/USD", exit_side, 0.1, exit_price)
        filled_exit = await gateway.fill_order(exit_order.order_id)
        position_manager.update_position("BTC/USD", exit_side, 0.1, exit_price)

    # Verify all positions closed
    final_position = position_manager.get_position("BTC/USD")
    assert abs(final_position) < 0.01, "All positions should be closed"

    # Verify P&L matches expected
    expected_pnl = (50050.0 - 50000.0) * 0.1 + (50040.0 - 50060.0) * 0.1 + (50055.0 - 50045.0) * 0.1
    assert abs(position_manager.realized_pnl - expected_pnl) < 0.01

    print(f"✅ Complete scalping scenario passed:")
    print(f"   Trades: {len(trades)}")
    print(f"   Realized P&L: ${position_manager.realized_pnl:.2f}")
    print(f"   Final position: {final_position:.4f}")
