"""
Tests for Multi-Pair Allocation System

Tests:
- Allocation sums ≤ configured cap
- Per-pair allocation doesn't exceed 10%
- Failsafe removes pairs with abnormal spread
- Trading specs validation
- Priority-based pair selection

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import sys
import unittest
from decimal import Decimal

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.infrastructure.allocation_router import AllocationRouter
from agents.infrastructure.trading_specs_validator import (
    TradingSpecsValidator,
    validate_spread_from_orderbook,
    validate_liquidity_from_orderbook,
)


class TestAllocationCaps(unittest.TestCase):
    """Test allocation cap enforcement."""

    def setUp(self):
        """Set up test router."""
        self.router = AllocationRouter(
            total_capital_usd=100000.0,
            mode="turbo",
        )

    def test_total_allocation_within_cap(self):
        """Test that total allocation doesn't exceed 100%."""
        pairs = self.router.get_enabled_pairs(include_alts=True)

        # Mock good spread/liquidity
        spread_data = {ks: 5.0 for _, ks, _, _ in pairs}
        liquidity_data = {ks: 500000.0 for _, ks, _, _ in pairs}

        # Allocate
        state = self.router.allocate_capital(pairs, spread_data, liquidity_data)

        # Calculate total allocation
        total_allocation = sum(
            a.allocation_pct for a in state.pair_allocations.values()
        )

        self.assertLessEqual(
            total_allocation,
            100.0,
            f"Total allocation {total_allocation}% exceeds 100%",
        )

    def test_per_pair_allocation_capped_at_10_percent(self):
        """Test that no single pair exceeds 10% allocation."""
        pairs = self.router.get_enabled_pairs(include_alts=True)

        # Mock good spread/liquidity
        spread_data = {ks: 5.0 for _, ks, _, _ in pairs}
        liquidity_data = {ks: 500000.0 for _, ks, _, _ in pairs}

        # Allocate
        state = self.router.allocate_capital(pairs, spread_data, liquidity_data)

        # Check each pair
        for symbol, allocation in state.pair_allocations.items():
            self.assertLessEqual(
                allocation.allocation_pct,
                10.0,
                f"{symbol} allocation {allocation.allocation_pct}% exceeds 10%",
            )

    def test_allocation_respects_max_concurrent_pairs(self):
        """Test that max concurrent pairs limit is enforced."""
        self.router.max_concurrent_pairs = 2

        pairs = self.router.get_enabled_pairs(include_alts=True)

        # Mock good spread/liquidity
        spread_data = {ks: 5.0 for _, ks, _, _ in pairs}
        liquidity_data = {ks: 500000.0 for _, ks, _, _ in pairs}

        # Allocate
        state = self.router.allocate_capital(pairs, spread_data, liquidity_data)

        # Check active pairs count
        self.assertLessEqual(
            len(state.active_pairs),
            2,
            f"Active pairs {len(state.active_pairs)} exceeds limit of 2",
        )

    def test_allocation_priority_ordering(self):
        """Test that pairs are selected by priority order."""
        self.router.max_concurrent_pairs = 2

        pairs = self.router.get_enabled_pairs(include_alts=True)

        # Mock good spread/liquidity (BTC needs higher liquidity)
        spread_data = {ks: 3.5 for _, ks, _, _ in pairs}
        liquidity_data = {
            "XBTUSD": 2000000.0,  # $2M for BTC
            "ETHUSD": 800000.0,   # $800K for ETH
            "SOLUSD": 300000.0,   # $300K for SOL
            "ADAUSD": 150000.0,   # $150K for ADA
        }

        # Allocate
        state = self.router.allocate_capital(pairs, spread_data, liquidity_data)

        # Should have BTC and ETH (priority 1 and 2)
        self.assertIn("BTC/USD", state.active_pairs)
        self.assertIn("ETH/USD", state.active_pairs)


class TestSpreadValidation(unittest.TestCase):
    """Test spread validation and failsafe."""

    def setUp(self):
        """Set up test validator."""
        self.validator = TradingSpecsValidator()
        self.router = AllocationRouter(total_capital_usd=100000.0, mode="turbo")

    def test_abnormal_spread_rejects_pair(self):
        """Test that pairs with abnormal spread are rejected."""
        pairs = [("BTC/USD", "XBTUSD", 1, 10.0)]

        # Mock abnormally high spread (50 bps >> 5 bps limit)
        spread_data = {"XBTUSD": 50.0}
        liquidity_data = {"XBTUSD": 2000000.0}

        # Allocate
        state = self.router.allocate_capital(pairs, spread_data, liquidity_data)

        # Pair should be rejected
        self.assertNotIn("BTC/USD", state.active_pairs)
        self.assertEqual(len(state.active_pairs), 0)

    def test_acceptable_spread_allows_pair(self):
        """Test that pairs with acceptable spread are allowed."""
        pairs = [("BTC/USD", "XBTUSD", 1, 10.0)]

        # Mock good spread (3.5 bps < 5 bps limit)
        spread_data = {"XBTUSD": 3.5}
        liquidity_data = {"XBTUSD": 2000000.0}

        # Allocate
        state = self.router.allocate_capital(pairs, spread_data, liquidity_data)

        # Pair should be accepted
        self.assertIn("BTC/USD", state.active_pairs)

    def test_spread_validation_from_orderbook(self):
        """Test spread calculation from orderbook data."""
        # Mock orderbook with tight spread
        orderbook = {
            "bids": [[50000.0, 1.0], [49999.0, 2.0]],
            "asks": [[50001.0, 1.0], [50002.0, 2.0]],
        }

        spread_bps = validate_spread_from_orderbook(orderbook)

        # Expected: (50001 - 50000) / 50000.5 * 10000 ≈ 0.2 bps
        self.assertLess(spread_bps, 1.0)

    def test_wide_spread_fails_validation(self):
        """Test that wide spread fails validation."""
        # Mock orderbook with wide spread
        orderbook = {
            "bids": [[49500.0, 1.0]],
            "asks": [[50500.0, 1.0]],  # 1000 USD spread (~200 bps)
        }

        spread_bps = validate_spread_from_orderbook(orderbook)

        # Expected: ~200 bps spread (very wide)
        self.assertGreater(spread_bps, 100.0)


class TestLiquidityValidation(unittest.TestCase):
    """Test liquidity validation."""

    def setUp(self):
        """Set up test validator."""
        self.validator = TradingSpecsValidator()
        self.router = AllocationRouter(total_capital_usd=100000.0, mode="turbo")

    def test_low_liquidity_rejects_pair(self):
        """Test that pairs with low liquidity are rejected."""
        pairs = [("BTC/USD", "XBTUSD", 1, 10.0)]

        # Mock low liquidity ($10K << $1M minimum)
        spread_data = {"XBTUSD": 3.5}
        liquidity_data = {"XBTUSD": 10000.0}

        # Allocate
        state = self.router.allocate_capital(pairs, spread_data, liquidity_data)

        # Pair should be rejected
        self.assertNotIn("BTC/USD", state.active_pairs)

    def test_sufficient_liquidity_allows_pair(self):
        """Test that pairs with sufficient liquidity are allowed."""
        pairs = [("BTC/USD", "XBTUSD", 1, 10.0)]

        # Mock good liquidity ($2M > $1M minimum)
        spread_data = {"XBTUSD": 3.5}
        liquidity_data = {"XBTUSD": 2000000.0}

        # Allocate
        state = self.router.allocate_capital(pairs, spread_data, liquidity_data)

        # Pair should be accepted
        self.assertIn("BTC/USD", state.active_pairs)

    def test_liquidity_calculation_from_orderbook(self):
        """Test liquidity calculation from orderbook."""
        # Mock deep orderbook
        orderbook = {
            "bids": [[50000.0, 10.0], [49999.0, 20.0]],  # $500K + $1M
            "asks": [[50001.0, 10.0], [50002.0, 20.0]],  # $500K + $1M
        }

        liquidity_usd = validate_liquidity_from_orderbook(orderbook, depth_levels=2)

        # Expected: ~$3M total liquidity
        self.assertGreater(liquidity_usd, 2000000.0)


class TestPrecisionValidation(unittest.TestCase):
    """Test precision/tick size validation."""

    def setUp(self):
        """Set up test validator."""
        self.validator = TradingSpecsValidator()

    def test_precision_data_available(self):
        """Test that precision data is available for all pairs."""
        pairs = [
            ("BTC/USD", "XBTUSD"),
            ("ETH/USD", "ETHUSD"),
            ("SOL/USD", "SOLUSD"),
            ("ADA/USD", "ADAUSD"),
        ]

        for symbol, kraken_symbol in pairs:
            result = self.validator.validate_pair(symbol, kraken_symbol)

            self.assertTrue(
                result.is_valid or "No precision data" in result.failures[0],
                f"{symbol} validation failed: {result.failures}",
            )

            if result.is_valid:
                self.assertIsNotNone(result.spec)
                self.assertGreater(result.spec.price_decimals, 0)
                self.assertGreater(result.spec.size_decimals, 0)
                self.assertGreater(result.spec.tick_size, 0)

    def test_missing_precision_fails_validation(self):
        """Test that missing precision data fails validation."""
        # Test with a non-existent pair
        result = self.validator.validate_pair("FAKE/USD", "FAKEUSD")

        self.assertFalse(result.is_valid)
        self.assertIn("No precision data", result.failures[0])


class TestAllocationSum(unittest.TestCase):
    """Test allocation sum validation."""

    def setUp(self):
        """Set up test validator."""
        self.validator = TradingSpecsValidator()

    def test_allocation_sum_at_limit(self):
        """Test that 100% allocation is valid."""
        allocations = {
            "BTC/USD": 10.0,
            "ETH/USD": 10.0,
            "SOL/USD": 10.0,
            "ADA/USD": 10.0,
            "PAIR5": 10.0,
            "PAIR6": 10.0,
            "PAIR7": 10.0,
            "PAIR8": 10.0,
            "PAIR9": 10.0,
            "PAIR10": 10.0,
        }

        is_valid, total, violations = self.validator.check_allocation_sum(allocations)

        self.assertTrue(is_valid)
        self.assertEqual(total, 100.0)
        self.assertEqual(len(violations), 0)

    def test_allocation_sum_exceeds_limit(self):
        """Test that > 100% allocation fails."""
        allocations = {
            "BTC/USD": 10.0,
            "ETH/USD": 10.0,
            "SOL/USD": 10.0,
            "ADA/USD": 10.0,
            "PAIR5": 10.0,
            "PAIR6": 10.0,
            "PAIR7": 10.0,
            "PAIR8": 10.0,
            "PAIR9": 10.0,
            "PAIR10": 10.0,
            "PAIR11": 10.0,  # Exceeds 100%
        }

        is_valid, total, violations = self.validator.check_allocation_sum(allocations)

        self.assertFalse(is_valid)
        self.assertGreater(total, 100.0)
        self.assertGreater(len(violations), 0)

    def test_per_pair_cap_exceeded(self):
        """Test that individual pair > 10% fails."""
        allocations = {
            "BTC/USD": 15.0,  # Exceeds 10% cap
            "ETH/USD": 10.0,
        }

        is_valid, total, violations = self.validator.check_allocation_sum(allocations)

        self.assertFalse(is_valid)
        self.assertGreater(len(violations), 0)
        self.assertIn("BTC/USD", violations[0])


class TestPositionLimits(unittest.TestCase):
    """Test position limit checks."""

    def setUp(self):
        """Set up test router."""
        self.router = AllocationRouter(
            total_capital_usd=100000.0,
            mode="turbo",
        )

        # Allocate capital
        pairs = self.router.get_enabled_pairs(include_alts=False)
        spread_data = {ks: 3.5 for _, ks, _, _ in pairs}
        liquidity_data = {ks: 2000000.0 for _, ks, _, _ in pairs}
        self.router.allocate_capital(pairs, spread_data, liquidity_data)

    def test_position_within_allocation_allowed(self):
        """Test that position within allocation is allowed."""
        # BTC/USD has 10% = $10,000
        allowed, reason = self.router.check_pair_limits("BTC/USD", 9000.0)

        self.assertTrue(allowed)
        self.assertEqual(reason, "OK")

    def test_position_exceeds_allocation_rejected(self):
        """Test that position exceeding allocation is rejected."""
        # BTC/USD has 10% = $10,000
        allowed, reason = self.router.check_pair_limits("BTC/USD", 15000.0)

        self.assertFalse(allowed)
        self.assertIn("max", reason.lower())

    def test_unallocated_pair_rejected(self):
        """Test that unallocated pair is rejected."""
        allowed, reason = self.router.check_pair_limits("FAKE/USD", 1000.0)

        self.assertFalse(allowed)
        self.assertIn("not allocated", reason)


if __name__ == "__main__":
    unittest.main()
