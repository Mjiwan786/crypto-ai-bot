"""
Unit tests for PRDSpreadFilter (PRD-001 Section 4.1)

Tests coverage:
- Spread calculation formula accuracy
- Rejection logic when spread > threshold
- Acceptance when spread ≤ threshold
- WARNING level logging verification
- Prometheus counter emission
- Edge cases (zero prices, missing data, invalid inputs)
- Integration with signal checking

Author: Crypto AI Bot Team
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

from agents.risk.prd_spread_filter import PRDSpreadFilter


class TestPRDSpreadFilterInit:
    """Test PRDSpreadFilter initialization."""

    def test_init_default_params(self):
        """Test initialization with default parameters."""
        filter = PRDSpreadFilter()
        assert filter.max_spread_pct == 0.5
        assert filter.kraken_ws_client is None
        assert filter.total_checks == 0
        assert filter.total_rejections == 0

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        mock_client = Mock()
        filter = PRDSpreadFilter(max_spread_pct=1.0, kraken_ws_client=mock_client)
        assert filter.max_spread_pct == 1.0
        assert filter.kraken_ws_client is mock_client

    def test_init_logs_info(self, caplog):
        """Test that initialization logs at INFO level."""
        import logging
        with caplog.at_level(logging.INFO):
            filter = PRDSpreadFilter(max_spread_pct=0.75)

        assert "PRDSpreadFilter initialized" in caplog.text
        assert "max_spread_pct=0.75%" in caplog.text


class TestCalculateSpreadPct:
    """Test spread percentage calculation."""

    def test_calculate_spread_pct_normal(self):
        """Test spread calculation with normal bid/ask."""
        filter = PRDSpreadFilter()

        # bid=50000, ask=50250
        # mid = (50000 + 50250) / 2 = 50125
        # spread = (50250 - 50000) / 50125 * 100 = 0.498%
        spread_pct = filter.calculate_spread_pct(bid=50000.0, ask=50250.0)

        assert abs(spread_pct - 0.4987531) < 0.0001

    def test_calculate_spread_pct_tight(self):
        """Test spread calculation with tight bid/ask."""
        filter = PRDSpreadFilter()

        # bid=100.0, ask=100.1
        # mid = 100.05
        # spread = 0.1 / 100.05 * 100 = 0.0999%
        spread_pct = filter.calculate_spread_pct(bid=100.0, ask=100.1)

        assert abs(spread_pct - 0.09995) < 0.0001

    def test_calculate_spread_pct_wide(self):
        """Test spread calculation with wide bid/ask."""
        filter = PRDSpreadFilter()

        # bid=1000, ask=1100
        # mid = 1050
        # spread = 100 / 1050 * 100 = 9.52%
        spread_pct = filter.calculate_spread_pct(bid=1000.0, ask=1100.0)

        assert abs(spread_pct - 9.5238) < 0.01

    def test_calculate_spread_pct_zero_bid(self, caplog):
        """Test spread calculation with zero bid."""
        import logging
        filter = PRDSpreadFilter()

        with caplog.at_level(logging.WARNING):
            spread_pct = filter.calculate_spread_pct(bid=0.0, ask=100.0)

        assert spread_pct == 999.0  # Return very high spread
        assert "Invalid bid/ask" in caplog.text

    def test_calculate_spread_pct_zero_ask(self, caplog):
        """Test spread calculation with zero ask."""
        import logging
        filter = PRDSpreadFilter()

        with caplog.at_level(logging.WARNING):
            spread_pct = filter.calculate_spread_pct(bid=100.0, ask=0.0)

        assert spread_pct == 999.0
        assert "Invalid bid/ask" in caplog.text

    def test_calculate_spread_pct_negative_bid(self, caplog):
        """Test spread calculation with negative bid."""
        import logging
        filter = PRDSpreadFilter()

        with caplog.at_level(logging.WARNING):
            spread_pct = filter.calculate_spread_pct(bid=-100.0, ask=100.0)

        assert spread_pct == 999.0
        assert "Invalid bid/ask" in caplog.text


class TestCheckSpread:
    """Test spread checking logic."""

    def test_check_spread_accept_below_threshold(self, caplog):
        """Test that spreads below threshold are accepted."""
        import logging
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # Spread = 0.25%
        with caplog.at_level(logging.DEBUG):
            should_reject, spread_pct = filter.check_spread(
                bid=100.0,
                ask=100.25,
                pair="BTC/USD"
            )

        assert should_reject is False
        assert abs(spread_pct - 0.2493) < 0.01
        assert filter.total_checks == 1
        assert filter.total_rejections == 0
        assert "[SPREAD CHECK]" in caplog.text
        assert "PASS" in caplog.text

    def test_check_spread_accept_at_threshold(self, caplog):
        """Test that spreads exactly at threshold are accepted."""
        import logging
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # Create bid/ask that gives exactly 0.5% spread
        # mid = 100, spread = 0.5, so ask - bid = 0.5
        # bid + ask = 200, ask - bid = 0.5
        # bid = 99.75, ask = 100.25
        with caplog.at_level(logging.DEBUG):
            should_reject, spread_pct = filter.check_spread(
                bid=99.75,
                ask=100.25,
                pair="BTC/USD"
            )

        assert should_reject is False
        assert abs(spread_pct - 0.5) < 0.01
        assert filter.total_rejections == 0

    def test_check_spread_reject_above_threshold(self, caplog):
        """Test that spreads above threshold are rejected."""
        import logging
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # Spread = 1.0%
        with caplog.at_level(logging.WARNING):
            should_reject, spread_pct = filter.check_spread(
                bid=100.0,
                ask=101.0,
                pair="BTC/USD"
            )

        assert should_reject is True
        assert abs(spread_pct - 0.995) < 0.01
        assert filter.total_checks == 1
        assert filter.total_rejections == 1
        assert "[SPREAD REJECTION]" in caplog.text
        assert "BTC/USD" in caplog.text
        assert ">" in caplog.text

    def test_check_spread_reject_multiple(self):
        """Test multiple rejections increment counter."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # First rejection
        should_reject, _ = filter.check_spread(bid=100.0, ask=102.0, pair="BTC/USD")
        assert should_reject is True
        assert filter.total_rejections == 1

        # Second rejection
        should_reject, _ = filter.check_spread(bid=100.0, ask=103.0, pair="ETH/USD")
        assert should_reject is True
        assert filter.total_rejections == 2

        # Acceptance
        should_reject, _ = filter.check_spread(bid=100.0, ask=100.25, pair="BTC/USD")
        assert should_reject is False
        assert filter.total_rejections == 2  # Unchanged

        assert filter.total_checks == 3

    def test_check_spread_custom_threshold(self):
        """Test spread checking with custom threshold."""
        filter = PRDSpreadFilter(max_spread_pct=1.0)

        # Spread = 0.75% (would be rejected with default 0.5%)
        should_reject, spread_pct = filter.check_spread(
            bid=100.0,
            ask=100.75,
            pair="BTC/USD"
        )

        assert should_reject is False  # Accepted with 1.0% threshold
        assert abs(spread_pct - 0.746) < 0.01

    @patch('agents.risk.prd_spread_filter.PROMETHEUS_AVAILABLE', True)
    @patch('agents.risk.prd_spread_filter.RISK_FILTER_REJECTIONS')
    def test_check_spread_emits_prometheus_counter(self, mock_counter):
        """Test that Prometheus counter is emitted on rejection."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # Wide spread triggers rejection
        should_reject, _ = filter.check_spread(
            bid=100.0,
            ask=102.0,
            pair="BTC/USD"
        )

        assert should_reject is True
        mock_counter.labels.assert_called_once_with(
            reason="wide_spread",
            pair="BTC/USD"
        )
        mock_counter.labels.return_value.inc.assert_called_once()

    @patch('agents.risk.prd_spread_filter.PROMETHEUS_AVAILABLE', False)
    def test_check_spread_no_prometheus(self):
        """Test that missing Prometheus doesn't break functionality."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # Should still work without Prometheus
        should_reject, spread_pct = filter.check_spread(
            bid=100.0,
            ask=102.0,
            pair="BTC/USD"
        )

        assert should_reject is True


class TestFetchCurrentSpread:
    """Test spread fetching from Kraken."""

    def test_fetch_current_spread_no_client(self, caplog):
        """Test spread fetching without Kraken client."""
        import logging
        filter = PRDSpreadFilter()

        with caplog.at_level(logging.DEBUG):
            result = filter.fetch_current_spread("BTC/USD")

        assert result is None
        assert "No Kraken WS client available" in caplog.text

    def test_fetch_current_spread_success(self):
        """Test successful spread fetching."""
        mock_client = Mock()
        mock_client.get_spread.return_value = {
            "bid": "50000.0",
            "ask": "50250.0"
        }

        filter = PRDSpreadFilter(kraken_ws_client=mock_client)
        result = filter.fetch_current_spread("BTC/USD")

        assert result == (50000.0, 50250.0)
        mock_client.get_spread.assert_called_once_with("BTC/USD")

    def test_fetch_current_spread_missing_bid(self):
        """Test spread fetching with missing bid."""
        mock_client = Mock()
        mock_client.get_spread.return_value = {
            "ask": "50250.0"
        }

        filter = PRDSpreadFilter(kraken_ws_client=mock_client)
        result = filter.fetch_current_spread("BTC/USD")

        assert result == (0.0, 50250.0)

    def test_fetch_current_spread_no_data(self):
        """Test spread fetching with no data."""
        mock_client = Mock()
        mock_client.get_spread.return_value = None

        filter = PRDSpreadFilter(kraken_ws_client=mock_client)
        result = filter.fetch_current_spread("BTC/USD")

        assert result is None

    def test_fetch_current_spread_exception(self, caplog):
        """Test spread fetching with exception."""
        import logging
        mock_client = Mock()
        mock_client.get_spread.side_effect = Exception("Connection error")

        filter = PRDSpreadFilter(kraken_ws_client=mock_client)

        with caplog.at_level(logging.WARNING):
            result = filter.fetch_current_spread("BTC/USD")

        assert result is None
        assert "Failed to fetch spread" in caplog.text
        assert "Connection error" in caplog.text


class TestCheckSignal:
    """Test signal checking integration."""

    def test_check_signal_with_market_data_accept(self):
        """Test signal checking with market data - accepted."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        signal = {"trading_pair": "BTC/USD"}
        market_data = {"bid": 100.0, "ask": 100.25}

        should_reject = filter.check_signal(signal, market_data)

        assert should_reject is False

    def test_check_signal_with_market_data_reject(self):
        """Test signal checking with market data - rejected."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        signal = {"trading_pair": "BTC/USD"}
        market_data = {"bid": 100.0, "ask": 102.0}

        should_reject = filter.check_signal(signal, market_data)

        assert should_reject is True

    def test_check_signal_fetch_from_kraken(self):
        """Test signal checking fetches from Kraken if no market data."""
        mock_client = Mock()
        mock_client.get_spread.return_value = {
            "bid": "100.0",
            "ask": "100.25"
        }

        filter = PRDSpreadFilter(max_spread_pct=0.5, kraken_ws_client=mock_client)

        signal = {"trading_pair": "BTC/USD"}

        should_reject = filter.check_signal(signal, market_data=None)

        assert should_reject is False
        mock_client.get_spread.assert_called_once_with("BTC/USD")

    def test_check_signal_no_data_allows_signal(self, caplog):
        """Test that missing data allows signal (fail open)."""
        import logging
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        signal = {"trading_pair": "BTC/USD"}

        with caplog.at_level(logging.WARNING):
            should_reject = filter.check_signal(signal, market_data=None)

        assert should_reject is False  # Allow if can't check
        assert "No bid/ask data available" in caplog.text
        assert "allowing signal" in caplog.text

    def test_check_signal_missing_bid(self, caplog):
        """Test signal checking with missing bid."""
        import logging
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        signal = {"trading_pair": "BTC/USD"}
        market_data = {"ask": 100.25}  # Missing bid

        with caplog.at_level(logging.WARNING):
            should_reject = filter.check_signal(signal, market_data)

        assert should_reject is False  # Allow if can't check
        assert "Missing bid/ask" in caplog.text

    def test_check_signal_missing_ask(self, caplog):
        """Test signal checking with missing ask."""
        import logging
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        signal = {"trading_pair": "BTC/USD"}
        market_data = {"bid": 100.0}  # Missing ask

        with caplog.at_level(logging.WARNING):
            should_reject = filter.check_signal(signal, market_data)

        assert should_reject is False

    def test_check_signal_unknown_pair(self):
        """Test signal checking with unknown trading pair."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        signal = {}  # No trading_pair
        market_data = {"bid": 100.0, "ask": 100.25}

        should_reject = filter.check_signal(signal, market_data)

        assert should_reject is False  # Spread is acceptable


class TestGetMetrics:
    """Test metrics retrieval."""

    def test_get_metrics_initial(self):
        """Test metrics with no checks."""
        filter = PRDSpreadFilter(max_spread_pct=0.75)

        metrics = filter.get_metrics()

        assert metrics["total_checks"] == 0
        assert metrics["total_rejections"] == 0
        assert metrics["rejection_rate"] == 0.0
        assert metrics["max_spread_pct"] == 0.75

    def test_get_metrics_after_checks(self):
        """Test metrics after some checks."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # 2 rejections, 3 acceptances
        filter.check_spread(100.0, 102.0, "BTC/USD")  # Reject
        filter.check_spread(100.0, 103.0, "ETH/USD")  # Reject
        filter.check_spread(100.0, 100.25, "BTC/USD")  # Accept
        filter.check_spread(100.0, 100.3, "ETH/USD")  # Accept
        filter.check_spread(100.0, 100.2, "XRP/USD")  # Accept

        metrics = filter.get_metrics()

        assert metrics["total_checks"] == 5
        assert metrics["total_rejections"] == 2
        assert abs(metrics["rejection_rate"] - 0.4) < 0.01
        assert metrics["max_spread_pct"] == 0.5

    def test_get_metrics_all_rejections(self):
        """Test metrics with all rejections."""
        filter = PRDSpreadFilter(max_spread_pct=0.1)

        # All should be rejected
        filter.check_spread(100.0, 102.0, "BTC/USD")
        filter.check_spread(100.0, 101.0, "ETH/USD")

        metrics = filter.get_metrics()

        assert metrics["total_checks"] == 2
        assert metrics["total_rejections"] == 2
        assert metrics["rejection_rate"] == 1.0


class TestResetStats:
    """Test statistics reset."""

    def test_reset_stats(self, caplog):
        """Test statistics reset."""
        import logging
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # Make some checks
        filter.check_spread(100.0, 102.0, "BTC/USD")
        filter.check_spread(100.0, 100.25, "ETH/USD")

        assert filter.total_checks == 2
        assert filter.total_rejections == 1

        # Reset
        with caplog.at_level(logging.INFO):
            filter.reset_stats()

        assert filter.total_checks == 0
        assert filter.total_rejections == 0
        assert "Spread filter statistics reset" in caplog.text


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_small_prices(self):
        """Test with very small prices (altcoins)."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # bid=0.00001, ask=0.0000101
        # mid = 0.00001005
        # spread = 0.0000001 / 0.00001005 * 100 = 0.995%
        should_reject, spread_pct = filter.check_spread(
            bid=0.00001,
            ask=0.0000101,
            pair="SHIB/USD"
        )

        assert should_reject is True  # > 0.5%
        assert spread_pct > 0.5

    def test_very_large_prices(self):
        """Test with very large prices."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # bid=100000, ask=100250
        should_reject, spread_pct = filter.check_spread(
            bid=100000.0,
            ask=100250.0,
            pair="BTC/USD"
        )

        assert should_reject is False
        assert abs(spread_pct - 0.2493) < 0.01

    def test_inverted_bid_ask(self):
        """Test with inverted bid/ask (ask < bid)."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # ask < bid (unusual but should handle)
        should_reject, spread_pct = filter.check_spread(
            bid=100.0,
            ask=99.0,
            pair="BTC/USD"
        )

        # Spread will be negative, but absolute comparison should work
        # Actually the formula gives: (99 - 100) / 99.5 * 100 = -1.005%
        # This will be negative, so < 0.5%, so should_reject = False
        assert should_reject is False

    def test_equal_bid_ask(self):
        """Test with equal bid and ask (zero spread)."""
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        should_reject, spread_pct = filter.check_spread(
            bid=100.0,
            ask=100.0,
            pair="BTC/USD"
        )

        assert should_reject is False
        assert spread_pct == 0.0
