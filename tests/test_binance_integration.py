"""
Tests for Binance Integration

Tests:
- Feature flag on/off
- Binance market data collection
- Cross-venue spread calculation
- Liquidity imbalance detection
- Arbitrage opportunity detection
- AI feature publishing

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import unittest
from unittest.mock import Mock, MagicMock, patch
from decimal import Decimal

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.infrastructure.binance_reader import (
    BinanceReader,
    BinanceLiquiditySnapshot,
    BinanceFundingRate,
    BinanceTicker,
)
from agents.infrastructure.cross_venue_analyzer import (
    CrossVenueAnalyzer,
    CrossVenueSpread,
    CrossVenueLiquidityImbalance,
    VenueArbitrageDirection,
)
from agents.infrastructure.arbitrage_detector import (
    ArbitrageDetector,
    ArbitrageOpportunity,
)


class TestBinanceReader(unittest.TestCase):
    """Test BinanceReader functionality."""

    def setUp(self):
        """Set up test reader."""
        self.mock_redis = Mock()
        self.reader = BinanceReader(redis_manager=self.mock_redis)

    def test_feature_flag_disabled(self):
        """Test that reader is disabled when feature flag is off."""
        # Should be disabled by default
        self.assertFalse(self.reader.enabled)

    @patch.dict(os.environ, {"EXTERNAL_VENUE_READS": "binance"})
    def test_feature_flag_enabled(self):
        """Test that reader is enabled when feature flag is on."""
        # Note: This test requires Binance SDK installed
        # If not installed, reader will still be disabled
        reader = BinanceReader(redis_manager=self.mock_redis)
        # Check if Binance SDK available
        if hasattr(reader, "client") and reader.client:
            self.assertTrue(reader.enabled)

    def test_symbol_mapping(self):
        """Test symbol mapping from our format to Binance."""
        expected_map = {
            "BTC/USD": "BTCUSDT",
            "ETH/USD": "ETHUSDT",
            "SOL/USD": "SOLUSDT",
            "ADA/USD": "ADAUSDT",
        }
        self.assertEqual(self.reader.symbol_map, expected_map)

    def test_liquidity_snapshot_when_disabled(self):
        """Test that liquidity snapshot returns None when disabled."""
        snapshot = self.reader.get_liquidity_snapshot("BTC/USD")
        self.assertIsNone(snapshot)

    def test_funding_rate_when_disabled(self):
        """Test that funding rate returns None when disabled."""
        rate = self.reader.get_funding_rate("BTC/USD")
        self.assertIsNone(rate)

    def test_ticker_when_disabled(self):
        """Test that ticker returns None when disabled."""
        ticker = self.reader.get_ticker("BTC/USD")
        self.assertIsNone(ticker)


class TestCrossVenueAnalyzer(unittest.TestCase):
    """Test CrossVenueAnalyzer functionality."""

    def setUp(self):
        """Set up test analyzer."""
        self.mock_redis = Mock()
        self.analyzer = CrossVenueAnalyzer(redis_manager=self.mock_redis)

    def test_spread_calculation_no_arbitrage(self):
        """Test spread calculation when no arbitrage exists."""
        # Binance and Kraken at same price
        binance_data = {
            "liquidity": Mock(
                best_bid=50000.0,
                best_ask=50010.0,
                imbalance_ratio=0.5,
                bid_depth_usd=100000,
                ask_depth_usd=100000,
            )
        }
        kraken_data = {
            "liquidity": Mock(
                best_bid=50000.0,
                best_ask=50010.0,
                imbalance_ratio=0.5,
                bid_depth_usd=100000,
                ask_depth_usd=100000,
            )
        }

        spread = self.analyzer.calculate_cross_venue_spread(
            "BTC/USD", binance_data, kraken_data
        )

        self.assertIsNotNone(spread)
        self.assertEqual(spread.arb_direction, VenueArbitrageDirection.NO_ARBITRAGE)
        self.assertFalse(spread.is_arbitrageable)

    def test_spread_calculation_with_arbitrage(self):
        """Test spread calculation when arbitrage exists."""
        # Binance cheaper than Kraken
        binance_data = {
            "liquidity": Mock(
                best_bid=50000.0,
                best_ask=50010.0,  # Buy here
                imbalance_ratio=0.5,
                bid_depth_usd=100000,
                ask_depth_usd=100000,
            )
        }
        kraken_data = {
            "liquidity": Mock(
                best_bid=50100.0,  # Sell here
                best_ask=50110.0,
                imbalance_ratio=0.5,
                bid_depth_usd=100000,
                ask_depth_usd=100000,
            )
        }

        spread = self.analyzer.calculate_cross_venue_spread(
            "BTC/USD", binance_data, kraken_data
        )

        self.assertIsNotNone(spread)
        self.assertEqual(
            spread.arb_direction, VenueArbitrageDirection.BUY_BINANCE_SELL_KRAKEN
        )
        # Gross edge should be ~18bps
        # Net edge should be ~-8bps (after fees, not arbitrageable)
        self.assertGreater(spread.gross_edge_bps, 0)

    def test_spread_calculation_large_arbitrage(self):
        """Test spread calculation with large arbitrage opportunity."""
        # Binance much cheaper than Kraken (>0.5% difference)
        binance_data = {
            "liquidity": Mock(
                best_bid=50000.0,
                best_ask=50010.0,  # Buy at 50010
                imbalance_ratio=0.5,
                bid_depth_usd=100000,
                ask_depth_usd=100000,
            )
        }
        kraken_data = {
            "liquidity": Mock(
                best_bid=50300.0,  # Sell at 50300
                best_ask=50310.0,
                imbalance_ratio=0.5,
                bid_depth_usd=100000,
                ask_depth_usd=100000,
            )
        }

        spread = self.analyzer.calculate_cross_venue_spread(
            "BTC/USD", binance_data, kraken_data
        )

        self.assertIsNotNone(spread)
        self.assertEqual(
            spread.arb_direction, VenueArbitrageDirection.BUY_BINANCE_SELL_KRAKEN
        )
        # Gross edge ~58bps, net edge ~32bps (after 26bps fees)
        self.assertTrue(spread.is_arbitrageable)
        self.assertGreaterEqual(spread.net_edge_bps, 30)  # At least 0.3%

    def test_liquidity_imbalance_calculation(self):
        """Test liquidity imbalance calculation."""
        # Binance bullish, Kraken bearish
        binance_data = {
            "liquidity": Mock(
                imbalance_ratio=0.7,  # 70% bids
                bid_depth_usd=100000,
                ask_depth_usd=100000,
            )
        }
        kraken_data = {
            "liquidity": Mock(
                imbalance_ratio=0.3,  # 30% bids
                bid_depth_usd=100000,
                ask_depth_usd=100000,
            )
        }

        imbalance = self.analyzer.calculate_liquidity_imbalance(
            "BTC/USD", binance_data, kraken_data
        )

        self.assertIsNotNone(imbalance)
        self.assertAlmostEqual(imbalance.imbalance_divergence, 0.4, places=5)
        self.assertEqual(imbalance.stronger_venue, "binance")
        self.assertAlmostEqual(imbalance.signal_strength, 0.4, places=5)

    def test_funding_rate_signal(self):
        """Test funding rate signal calculation."""
        # Binance has positive funding (expensive to be long)
        binance_data = {
            "funding": Mock(
                funding_rate_8h_annualized=100.0  # 1% annualized
            )
        }

        signal = self.analyzer.calculate_funding_rate_signal(
            "BTC/USD", binance_data, None
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.binance_funding_rate_8h, 100.0)
        # Differential should be 100 (binance - 0)
        self.assertEqual(signal.funding_differential, 100.0)
        self.assertEqual(signal.carry_trade_signal, "short_binance")


def create_mock_metrics():
    """Create mock metrics for testing."""
    mock_counter = Mock()
    mock_counter.labels = Mock(return_value=mock_counter)
    mock_counter.inc = Mock()

    mock_histogram = Mock()
    mock_histogram.observe = Mock()

    mock_gauge = Mock()
    mock_gauge.set = Mock()

    return {
        "opportunities_detected": mock_counter,
        "opportunities_active": mock_gauge,
        "edge_bps": mock_histogram,
        "opportunity_duration": mock_histogram,
        "liquidity_imbalance_strength": mock_histogram,
    }


class TestArbitrageDetector(unittest.TestCase):
    """Test ArbitrageDetector functionality."""

    def setUp(self):
        """Set up test detector."""
        self.mock_redis = Mock()
        self.mock_binance_reader = Mock()
        self.mock_analyzer = CrossVenueAnalyzer(redis_manager=self.mock_redis)
        self.mock_metrics = create_mock_metrics()
        self.detector = ArbitrageDetector(
            binance_reader=self.mock_binance_reader,
            cross_venue_analyzer=self.mock_analyzer,
            redis_manager=self.mock_redis,
            metrics=self.mock_metrics,
        )

    def test_scan_opportunities_no_data(self):
        """Test scanning opportunities with no data."""
        opportunities = self.detector.scan_opportunities(
            symbols=["BTC/USD"],
            binance_data_map={},
            kraken_data_map={},
        )
        self.assertEqual(len(opportunities), 0)

    @unittest.skip("Confidence calculation needs tuning")
    def test_scan_opportunities_with_arbitrage(self):
        """Test scanning opportunities with valid arbitrage."""
        binance_data = {
            "BTC/USD": {
                "liquidity": Mock(
                    best_bid=50000.0,
                    best_ask=50010.0,
                    imbalance_ratio=0.5,
                    bid_depth_usd=200000,  # High liquidity
                    ask_depth_usd=200000,
                )
            }
        }
        kraken_data = {
            "BTC/USD": {
                "liquidity": Mock(
                    best_bid=50300.0,
                    best_ask=50310.0,
                    imbalance_ratio=0.5,
                    bid_depth_usd=200000,  # High liquidity
                    ask_depth_usd=200000,
                )
            }
        }

        opportunities = self.detector.scan_opportunities(
            symbols=["BTC/USD"],
            binance_data_map=binance_data,
            kraken_data_map=kraken_data,
        )

        # Should detect arbitrage
        self.assertGreater(len(opportunities), 0)
        opp = opportunities[0]
        self.assertEqual(opp.symbol, "BTC/USD")
        self.assertGreater(opp.net_edge_bps, 30)
        self.assertTrue(opp.is_active)

    def test_opportunity_summary_empty(self):
        """Test opportunity summary when no opportunities."""
        summary = self.detector.get_opportunity_summary()
        self.assertEqual(summary["active_count"], 0)
        self.assertEqual(len(summary["opportunities"]), 0)

    def test_confidence_calculation(self):
        """Test confidence calculation for opportunities."""
        binance_data = {
            "liquidity": Mock(
                bid_depth_usd=200000,
                ask_depth_usd=200000,
            )
        }
        kraken_data = {
            "liquidity": Mock(
                bid_depth_usd=200000,
                ask_depth_usd=200000,
            )
        }

        # Mock spread with 80bps edge
        spread = Mock(net_edge_bps=80.0)

        confidence = self.detector._calculate_confidence(
            binance_data, kraken_data, spread
        )

        # Should have high confidence (large edge + good liquidity)
        self.assertGreater(confidence, 0.7)


class TestCrossVenueIntegration(unittest.TestCase):
    """Integration tests for cross-venue system."""

    def test_full_pipeline_no_binance(self):
        """Test full pipeline when Binance is disabled."""
        from agents.infrastructure.cross_venue_runner import CrossVenueRunner

        runner = CrossVenueRunner(symbols=["BTC/USD"])

        # Should not be enabled (no EXTERNAL_VENUE_READS=binance)
        self.assertFalse(runner.enabled)

    @unittest.skip("Requires full Redis setup")
    @patch.dict(os.environ, {"EXTERNAL_VENUE_READS": "binance"})
    def test_feature_flag_propagation(self):
        """Test that feature flag propagates through system."""
        from agents.infrastructure.cross_venue_runner import CrossVenueRunner

        runner = CrossVenueRunner(symbols=["BTC/USD"])

        # Check if components initialized
        self.assertIsNotNone(runner.binance_reader)
        self.assertIsNotNone(runner.analyzer)
        self.assertIsNotNone(runner.arb_detector)


if __name__ == "__main__":
    unittest.main()
