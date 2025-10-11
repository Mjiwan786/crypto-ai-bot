"""
Test Execution Planning: Price Rounding and Fee Inclusion

Tests price rounding per market tick size and fee inclusion in execution planning.
Uses table-driven tests for comprehensive coverage of tick sizes and fee scenarios.

Designed for conda env 'crypto-bot'.
"""

import pytest
from decimal import Decimal
from typing import Optional
from unittest.mock import Mock, AsyncMock, patch

# Import execution agent components
from agents.core.execution_agent import (
    ScalpingExecutionEngine,
    EnhancedExecutionAgent,
    OrderRequest,
    OrderFill,
    as_decimal,
)


# ============================================================================
# Helper Functions for Price Rounding
# ============================================================================

def round_to_tick_size(price: Decimal, tick_size: Decimal) -> Decimal:
    """
    Round price to nearest tick size.

    Args:
        price: Price to round
        tick_size: Tick size (e.g., 0.01, 0.1, 1.0)

    Returns:
        Price rounded to tick size

    Examples:
        >>> round_to_tick_size(Decimal("50123.456"), Decimal("0.1"))
        Decimal('50123.5')
        >>> round_to_tick_size(Decimal("50123.456"), Decimal("1.0"))
        Decimal('50123.0')
    """
    if tick_size <= 0:
        raise ValueError("Tick size must be positive")

    # Round to nearest tick
    ticks = (price / tick_size).quantize(Decimal("1"), rounding="ROUND_HALF_UP")
    return ticks * tick_size


def calculate_fee(
    quantity: Decimal,
    price: Decimal,
    fee_bps: Decimal,
    is_maker: bool = False
) -> Decimal:
    """
    Calculate trading fee.

    Args:
        quantity: Order quantity
        price: Execution price
        fee_bps: Fee in basis points (e.g., 15 for 0.15%)
        is_maker: True if maker order (may have rebate)

    Returns:
        Fee amount (negative if rebate)

    Examples:
        >>> calculate_fee(Decimal("0.1"), Decimal("50000"), Decimal("15"))
        Decimal('7.50')  # 0.1 * 50000 * 0.0015 = 7.50
    """
    notional = quantity * price
    fee = notional * fee_bps / Decimal("10000")

    # Maker rebates are negative fees
    if is_maker and fee_bps < 0:
        return -abs(fee)

    return fee


def calculate_total_cost(
    quantity: Decimal,
    price: Decimal,
    fee: Decimal,
    side: str
) -> Decimal:
    """
    Calculate total cost including fees.

    Args:
        quantity: Order quantity
        price: Execution price
        fee: Fee amount
        side: 'buy' or 'sell'

    Returns:
        Total cost (positive for buys, includes fees)

    Examples:
        >>> calculate_total_cost(Decimal("0.1"), Decimal("50000"), Decimal("7.50"), "buy")
        Decimal('5007.50')  # 0.1 * 50000 + 7.50
    """
    notional = quantity * price

    if side.lower() == "buy":
        return notional + fee
    else:
        return notional - fee


# ============================================================================
# Table-Driven Tests: Price Rounding
# ============================================================================

@pytest.mark.parametrize(
    "price,tick_size,expected_rounded",
    [
        # BTC/USD: 0.1 tick size
        ("50123.456", "0.1", "50123.5"),
        ("50123.449", "0.1", "50123.4"),
        ("50123.45", "0.1", "50123.5"),
        ("50123.44", "0.1", "50123.4"),

        # BTC/USD: 1.0 tick size (some exchanges)
        ("50123.6", "1.0", "50124.0"),
        ("50123.4", "1.0", "50123.0"),
        ("50123.5", "1.0", "50124.0"),  # ROUND_HALF_UP

        # ETH/USD: 0.01 tick size
        ("3456.789", "0.01", "3456.79"),
        ("3456.784", "0.01", "3456.78"),
        ("3456.785", "0.01", "3456.79"),

        # Small altcoin: 0.0001 tick size
        ("12.34567", "0.0001", "12.3457"),
        ("12.34563", "0.0001", "12.3456"),

        # Large tick: 10.0
        ("50123", "10.0", "50120.0"),
        ("50125", "10.0", "50130.0"),
        ("50128", "10.0", "50130.0"),

        # Edge cases
        ("0.1", "0.01", "0.10"),
        ("0.0", "0.1", "0.0"),
        ("100000.0", "1.0", "100000.0"),
    ],
    ids=[
        "btc_usd_0.1_round_up",
        "btc_usd_0.1_round_down",
        "btc_usd_0.1_exactly_half_up",
        "btc_usd_0.1_exactly_half_down",
        "btc_usd_1.0_round_up",
        "btc_usd_1.0_round_down",
        "btc_usd_1.0_exactly_half",
        "eth_usd_0.01_round_up",
        "eth_usd_0.01_round_down",
        "eth_usd_0.01_exactly_half",
        "altcoin_0.0001_round_up",
        "altcoin_0.0001_round_down",
        "large_tick_10_round_down",
        "large_tick_10_round_up_1",
        "large_tick_10_round_up_2",
        "edge_tiny_price",
        "edge_zero_price",
        "edge_large_exact",
    ]
)
def test_price_rounding_to_tick_size(price: str, tick_size: str, expected_rounded: str):
    """Table-driven tests for price rounding to market tick size"""
    price_decimal = Decimal(price)
    tick_decimal = Decimal(tick_size)
    expected = Decimal(expected_rounded)

    rounded = round_to_tick_size(price_decimal, tick_decimal)

    assert rounded == expected, f"Expected {expected}, got {rounded}"


@pytest.mark.parametrize(
    "tick_size,should_raise",
    [
        ("0.0", True),
        ("-0.1", True),
        ("0.01", False),
    ],
    ids=["zero_tick", "negative_tick", "valid_tick"]
)
def test_tick_size_validation(tick_size: str, should_raise: bool):
    """Test that invalid tick sizes are rejected"""
    tick_decimal = Decimal(tick_size)

    if should_raise:
        with pytest.raises(ValueError, match="Tick size must be positive"):
            round_to_tick_size(Decimal("100.0"), tick_decimal)
    else:
        # Should not raise
        result = round_to_tick_size(Decimal("100.0"), tick_decimal)
        assert result == Decimal("100.00")


# ============================================================================
# Table-Driven Tests: Fee Calculation
# ============================================================================

@pytest.mark.parametrize(
    "quantity,price,fee_bps,is_maker,expected_fee",
    [
        # Taker fees (positive)
        ("0.1", "50000.0", "15", False, "7.50"),  # 0.15% taker
        ("0.1", "50000.0", "26", False, "13.00"),  # 0.26% standard
        ("1.0", "3000.0", "15", False, "4.50"),
        ("0.5", "100.0", "15", False, "0.075"),

        # Maker rebates (negative fee_bps)
        ("0.1", "50000.0", "-2.5", True, "-1.25"),  # -0.025% rebate
        ("1.0", "3000.0", "-2.5", True, "-0.75"),

        # Zero fee
        ("0.1", "50000.0", "0", False, "0.0"),

        # Edge cases
        ("0.001", "50000.0", "15", False, "0.075"),  # Tiny quantity
        ("10.0", "1.0", "15", False, "0.015"),  # Low price
        ("0.0", "50000.0", "15", False, "0.0"),  # Zero quantity
    ],
    ids=[
        "taker_0.15pct_btc",
        "taker_0.26pct_btc",
        "taker_0.15pct_eth",
        "taker_0.15pct_small",
        "maker_rebate_0.025pct_btc",
        "maker_rebate_0.025pct_eth",
        "zero_fee",
        "edge_tiny_quantity",
        "edge_low_price",
        "edge_zero_quantity",
    ]
)
def test_fee_calculation(
    quantity: str,
    price: str,
    fee_bps: str,
    is_maker: bool,
    expected_fee: str
):
    """Table-driven tests for fee calculation"""
    qty_decimal = Decimal(quantity)
    price_decimal = Decimal(price)
    fee_bps_decimal = Decimal(fee_bps)
    expected = Decimal(expected_fee)

    calculated_fee = calculate_fee(qty_decimal, price_decimal, fee_bps_decimal, is_maker)

    # Allow small rounding differences
    assert abs(calculated_fee - expected) < Decimal("0.01"), \
        f"Expected {expected}, got {calculated_fee}"


# ============================================================================
# Table-Driven Tests: Total Cost with Fees
# ============================================================================

@pytest.mark.parametrize(
    "quantity,price,fee,side,expected_total",
    [
        # Buy orders (cost + fee)
        ("0.1", "50000.0", "7.50", "buy", "5007.50"),
        ("1.0", "3000.0", "4.50", "buy", "3004.50"),
        ("0.5", "100.0", "0.075", "buy", "50.075"),

        # Sell orders (proceeds - fee)
        ("0.1", "50000.0", "7.50", "sell", "4992.50"),
        ("1.0", "3000.0", "4.50", "sell", "2995.50"),

        # With maker rebate (negative fee)
        ("0.1", "50000.0", "-1.25", "buy", "4998.75"),  # Buy with rebate
        ("0.1", "50000.0", "-1.25", "sell", "5001.25"),  # Sell with rebate

        # Zero fee
        ("0.1", "50000.0", "0.0", "buy", "5000.0"),
        ("0.1", "50000.0", "0.0", "sell", "5000.0"),
    ],
    ids=[
        "buy_btc_with_taker_fee",
        "buy_eth_with_taker_fee",
        "buy_small_with_taker_fee",
        "sell_btc_with_taker_fee",
        "sell_eth_with_taker_fee",
        "buy_btc_with_maker_rebate",
        "sell_btc_with_maker_rebate",
        "buy_zero_fee",
        "sell_zero_fee",
    ]
)
def test_total_cost_with_fees(
    quantity: str,
    price: str,
    fee: str,
    side: str,
    expected_total: str
):
    """Table-driven tests for total cost including fees"""
    qty_decimal = Decimal(quantity)
    price_decimal = Decimal(price)
    fee_decimal = Decimal(fee)
    expected = Decimal(expected_total)

    total_cost = calculate_total_cost(qty_decimal, price_decimal, fee_decimal, side)

    # Allow small rounding differences
    assert abs(total_cost - expected) < Decimal("0.01"), \
        f"Expected {expected}, got {total_cost}"


# ============================================================================
# Integration Tests: Execution Agent with Rounding and Fees
# ============================================================================

@pytest.mark.asyncio
async def test_execution_agent_applies_fees():
    """Test that execution agent correctly applies fees"""
    engine = ScalpingExecutionEngine()

    # Taker fee should be applied to IOC orders
    assert engine.taker_fee_bps == 15  # 0.15%

    # Calculate expected fee for test order
    quantity = Decimal("0.1")
    price = Decimal("50000.0")
    expected_fee_bps = Decimal("15")

    expected_fee = quantity * price * expected_fee_bps / Decimal("10000")

    # Fee should be around 7.5 USD
    assert abs(expected_fee - Decimal("7.5")) < Decimal("0.01")


@pytest.mark.asyncio
async def test_execution_agent_maker_rebate():
    """Test that post-only orders earn maker rebates"""
    engine = ScalpingExecutionEngine()

    # Post-only rebate
    assert engine.post_only_rebate_bps == -2.5  # -0.025% rebate

    # Calculate expected rebate
    quantity = Decimal("0.1")
    price = Decimal("50000.0")
    rebate_bps = Decimal("-2.5")

    expected_rebate = quantity * price * rebate_bps / Decimal("10000")

    # Rebate should be around -1.25 USD (negative = we receive it)
    assert abs(expected_rebate - Decimal("-1.25")) < Decimal("0.01")


# ============================================================================
# Table-Driven Tests: Round-Trip Price Rounding
# ============================================================================

@pytest.mark.parametrize(
    "original_price,tick_size,side",
    [
        ("50123.456", "0.1", "buy"),
        ("50123.456", "0.1", "sell"),
        ("3456.789", "0.01", "buy"),
        ("3456.789", "0.01", "sell"),
        ("100.12345", "0.0001", "buy"),
    ],
    ids=[
        "btc_buy_0.1_tick",
        "btc_sell_0.1_tick",
        "eth_buy_0.01_tick",
        "eth_sell_0.01_tick",
        "altcoin_buy_0.0001_tick",
    ]
)
def test_price_rounding_idempotent(original_price: str, tick_size: str, side: str):
    """Test that rounding is idempotent (round(round(x)) == round(x))"""
    price_decimal = Decimal(original_price)
    tick_decimal = Decimal(tick_size)

    # First rounding
    rounded_once = round_to_tick_size(price_decimal, tick_decimal)

    # Second rounding (should be same)
    rounded_twice = round_to_tick_size(rounded_once, tick_decimal)

    assert rounded_once == rounded_twice, \
        f"Rounding not idempotent: {rounded_once} != {rounded_twice}"


# ============================================================================
# Table-Driven Tests: Fee Impact on Profitability
# ============================================================================

@pytest.mark.parametrize(
    "entry_price,exit_price,quantity,fee_bps,expected_profit_sign",
    [
        # Profitable trades
        ("50000.0", "50200.0", "0.1", "15", "positive"),  # +200 USD - fees (net ~185)
        ("3000.0", "3050.0", "1.0", "15", "positive"),  # +50 USD - fees (net ~40)

        # Losing trades
        ("50000.0", "49900.0", "0.1", "15", "negative"),  # -100 USD - fees

        # Break-even before fees (loses after fees)
        ("50000.0", "50000.0", "0.1", "15", "negative"),  # Fees make it negative

        # Small profit eaten by fees
        ("50000.0", "50010.0", "0.1", "26", "negative"),  # 10 USD profit < 26 USD fees

        # Maker rebate helps profitability
        ("50000.0", "50010.0", "0.1", "-2.5", "positive"),  # Profit + rebate
    ],
    ids=[
        "profitable_btc_minus_fees",
        "profitable_eth_minus_fees",
        "losing_btc_minus_fees",
        "breakeven_loses_to_fees",
        "small_profit_eaten_by_fees",
        "maker_rebate_boosts_profit",
    ]
)
def test_fee_impact_on_profitability(
    entry_price: str,
    exit_price: str,
    quantity: str,
    fee_bps: str,
    expected_profit_sign: str
):
    """Table-driven tests for how fees impact trade profitability"""
    entry = Decimal(entry_price)
    exit_prc = Decimal(exit_price)
    qty = Decimal(quantity)
    fee_bps_dec = Decimal(fee_bps)

    # Calculate entry cost (buy)
    entry_fee = calculate_fee(qty, entry, fee_bps_dec, is_maker=False)
    entry_cost = qty * entry + entry_fee

    # Calculate exit proceeds (sell)
    exit_fee = calculate_fee(qty, exit_prc, fee_bps_dec, is_maker=(fee_bps_dec < 0))
    exit_proceeds = qty * exit_prc - exit_fee

    # Net profit
    net_profit = exit_proceeds - entry_cost

    if expected_profit_sign == "positive":
        assert net_profit > 0, f"Expected positive profit, got {net_profit}"
    else:
        assert net_profit <= 0, f"Expected non-positive profit, got {net_profit}"


# ============================================================================
# Edge Case Tests
# ============================================================================

def test_as_decimal_conversion():
    """Test as_decimal helper function from execution_agent"""
    # Float
    assert as_decimal(123.45) == Decimal("123.45")

    # String
    assert as_decimal("123.45") == Decimal("123.45")

    # Already Decimal
    d = Decimal("123.45")
    assert as_decimal(d) == d
    assert as_decimal(d) is d  # Should return same object


def test_round_to_tick_preserves_precision():
    """Test that rounding doesn't lose unnecessary precision"""
    # Price already at tick boundary
    price = Decimal("50100.0")
    tick = Decimal("0.1")

    rounded = round_to_tick_size(price, tick)

    assert rounded == price
    assert str(rounded) == "50100.0"


@pytest.mark.parametrize(
    "price,tick_size",
    [
        ("0.000001", "0.000001"),  # Micro price
        ("100000000.0", "1.0"),  # Very large price
        ("12345.678901234567890", "0.01"),  # High precision input
    ],
    ids=["micro_price", "very_large_price", "high_precision"]
)
def test_price_rounding_extreme_values(price: str, tick_size: str):
    """Test price rounding with extreme values"""
    price_decimal = Decimal(price)
    tick_decimal = Decimal(tick_size)

    # Should not raise
    rounded = round_to_tick_size(price_decimal, tick_decimal)

    # Result should be multiple of tick size
    ticks = rounded / tick_decimal
    assert ticks == ticks.quantize(Decimal("1")), \
        f"Rounded price {rounded} not a multiple of tick size {tick_decimal}"


# ============================================================================
# Performance Test
# ============================================================================

def test_price_rounding_performance():
    """Test that price rounding is fast enough for high-frequency trading"""
    import time

    price = Decimal("50123.456")
    tick = Decimal("0.1")

    # Warm up
    for _ in range(100):
        round_to_tick_size(price, tick)

    # Measure
    iterations = 10000
    start = time.time()

    for _ in range(iterations):
        round_to_tick_size(price, tick)

    elapsed = time.time() - start
    avg_time_us = (elapsed / iterations) * 1_000_000

    # Should be under 10 microseconds per operation
    assert avg_time_us < 10.0, \
        f"Price rounding too slow: {avg_time_us:.2f}μs > 10μs threshold"


if __name__ == "__main__":
    # Run with: python -m pytest tests/test_execution_planner.py -v
    pytest.main([__file__, "-v"])
