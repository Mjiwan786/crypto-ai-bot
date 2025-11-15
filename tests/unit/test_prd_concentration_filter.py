"""
Unit tests for PRDConcentrationFilter (PRD-001 Section 4.6)

Tests coverage:
- Position concentration calculation: position_size / total_portfolio_value
- Rejection at > 40% concentration
- WARNING level logging verification
- Prometheus counter emission
- Edge cases and various scenarios

Author: Crypto AI Bot Team
"""

import pytest
from unittest.mock import Mock, patch
from agents.risk.prd_concentration_filter import PRDConcentrationFilter


class TestPRDConcentrationFilterInit:
    """Test PRDConcentrationFilter initialization."""

    def test_init_default_params(self):
        """Test initialization with default parameters."""
        filter = PRDConcentrationFilter()
        assert filter.max_concentration_pct == 40.0
        assert filter.total_portfolio_value == 10000.0
        assert filter.total_checks == 0
        assert filter.total_rejections == 0

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=30.0,
            total_portfolio_value=50000.0
        )
        assert filter.max_concentration_pct == 30.0
        assert filter.total_portfolio_value == 50000.0

    def test_init_logs_info(self, caplog):
        """Test that initialization logs at INFO level."""
        import logging
        with caplog.at_level(logging.INFO):
            filter = PRDConcentrationFilter(
                max_concentration_pct=40.0,
                total_portfolio_value=10000.0
            )

        assert "PRDConcentrationFilter initialized" in caplog.text
        assert "max_concentration=40.0%" in caplog.text
        assert "portfolio_value=$10000.00" in caplog.text


class TestCalculateConcentrationPct:
    """Test concentration percentage calculation."""

    def test_calculate_concentration_new_position_only(self):
        """Test concentration with new position only (no existing)."""
        filter = PRDConcentrationFilter(total_portfolio_value=10000.0)

        # $2000 position / $10000 portfolio = 20%
        concentration = filter.calculate_concentration_pct(
            symbol="BTC/USD",
            position_size_usd=2000.0,
            existing_positions=None
        )

        assert abs(concentration - 20.0) < 0.01

    def test_calculate_concentration_with_existing_same_symbol(self):
        """Test concentration with existing positions in same symbol."""
        filter = PRDConcentrationFilter(total_portfolio_value=10000.0)

        existing = [
            {"symbol": "BTC/USD", "size_usd": 2000.0},
            {"symbol": "ETH/USD", "size_usd": 1000.0}
        ]

        # New $1000 + existing $2000 = $3000 total for BTC/USD
        # $3000 / $10000 = 30%
        concentration = filter.calculate_concentration_pct(
            symbol="BTC/USD",
            position_size_usd=1000.0,
            existing_positions=existing
        )

        assert abs(concentration - 30.0) < 0.01

    def test_calculate_concentration_with_existing_different_symbol(self):
        """Test concentration with existing positions in different symbols."""
        filter = PRDConcentrationFilter(total_portfolio_value=10000.0)

        existing = [
            {"symbol": "ETH/USD", "size_usd": 2000.0},
            {"symbol": "XRP/USD", "size_usd": 1000.0}
        ]

        # New $2000 for BTC/USD, no existing BTC/USD positions
        # $2000 / $10000 = 20%
        concentration = filter.calculate_concentration_pct(
            symbol="BTC/USD",
            position_size_usd=2000.0,
            existing_positions=existing
        )

        assert abs(concentration - 20.0) < 0.01

    def test_calculate_concentration_zero_portfolio(self, caplog):
        """Test concentration with zero portfolio value."""
        import logging
        filter = PRDConcentrationFilter(total_portfolio_value=0.0)

        with caplog.at_level(logging.WARNING):
            concentration = filter.calculate_concentration_pct(
                symbol="BTC/USD",
                position_size_usd=1000.0
            )

        assert concentration == 999.0  # High value for invalid data
        assert "Invalid total_portfolio_value" in caplog.text

    def test_calculate_concentration_multiple_existing_same_symbol(self):
        """Test concentration with multiple existing positions in same symbol."""
        filter = PRDConcentrationFilter(total_portfolio_value=10000.0)

        existing = [
            {"symbol": "BTC/USD", "size_usd": 1000.0},
            {"symbol": "BTC/USD", "size_usd": 500.0},
            {"symbol": "ETH/USD", "size_usd": 2000.0}
        ]

        # New $1000 + existing $1500 (1000+500) = $2500 total
        # $2500 / $10000 = 25%
        concentration = filter.calculate_concentration_pct(
            symbol="BTC/USD",
            position_size_usd=1000.0,
            existing_positions=existing
        )

        assert abs(concentration - 25.0) < 0.01

    def test_calculate_concentration_trading_pair_field(self):
        """Test concentration with 'trading_pair' field instead of 'symbol'."""
        filter = PRDConcentrationFilter(total_portfolio_value=10000.0)

        existing = [
            {"trading_pair": "BTC/USD", "size_usd": 2000.0}
        ]

        concentration = filter.calculate_concentration_pct(
            symbol="BTC/USD",
            position_size_usd=1000.0,
            existing_positions=existing
        )

        assert abs(concentration - 30.0) < 0.01


class TestCheckConcentration:
    """Test concentration checking logic."""

    def test_check_concentration_accept_below_threshold(self, caplog):
        """Test concentration check accepts when below threshold."""
        import logging
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # 20% concentration (below 40%)
        with caplog.at_level(logging.DEBUG):
            should_reject, concentration = filter.check_concentration(
                symbol="BTC/USD",
                position_size_usd=2000.0
            )

        assert should_reject is False
        assert abs(concentration - 20.0) < 0.01
        assert filter.total_checks == 1
        assert filter.total_rejections == 0
        assert "[CONCENTRATION CHECK]" in caplog.text
        assert "PASS" in caplog.text

    def test_check_concentration_accept_at_threshold(self):
        """Test concentration check accepts when exactly at threshold."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # Exactly 40% concentration
        should_reject, concentration = filter.check_concentration(
            symbol="BTC/USD",
            position_size_usd=4000.0
        )

        # Threshold is >, so exactly 40% should NOT reject
        assert should_reject is False
        assert abs(concentration - 40.0) < 0.01

    def test_check_concentration_reject_above_threshold(self, caplog):
        """Test concentration check rejects when above threshold."""
        import logging
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # 50% concentration (above 40%)
        with caplog.at_level(logging.WARNING):
            should_reject, concentration = filter.check_concentration(
                symbol="BTC/USD",
                position_size_usd=5000.0
            )

        assert should_reject is True
        assert abs(concentration - 50.0) < 0.01
        assert filter.total_checks == 1
        assert filter.total_rejections == 1
        assert "[CONCENTRATION REJECTION]" in caplog.text
        assert "BTC/USD" in caplog.text
        assert "50.00%" in caplog.text

    def test_check_concentration_reject_with_existing(self, caplog):
        """Test concentration rejection with existing positions."""
        import logging
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        existing = [
            {"symbol": "BTC/USD", "size_usd": 3000.0}
        ]

        # New $2000 + existing $3000 = $5000 total (50%)
        with caplog.at_level(logging.WARNING):
            should_reject, concentration = filter.check_concentration(
                symbol="BTC/USD",
                position_size_usd=2000.0,
                existing_positions=existing
            )

        assert should_reject is True
        assert abs(concentration - 50.0) < 0.01
        assert "[CONCENTRATION REJECTION]" in caplog.text

    def test_check_concentration_multiple_rejections(self):
        """Test multiple rejections increment counter."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # First rejection
        should_reject, _ = filter.check_concentration("BTC/USD", 5000.0)
        assert should_reject is True
        assert filter.total_rejections == 1

        # Second rejection
        should_reject, _ = filter.check_concentration("ETH/USD", 6000.0)
        assert should_reject is True
        assert filter.total_rejections == 2

        # Acceptance
        should_reject, _ = filter.check_concentration("XRP/USD", 2000.0)
        assert should_reject is False
        assert filter.total_rejections == 2  # Unchanged

        assert filter.total_checks == 3

    @patch('agents.risk.prd_concentration_filter.PROMETHEUS_AVAILABLE', True)
    @patch('agents.risk.prd_concentration_filter.RISK_FILTER_REJECTIONS')
    def test_check_concentration_emits_prometheus_counter(self, mock_counter):
        """Test that Prometheus counter is emitted on rejection."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # High concentration triggers rejection
        should_reject, _ = filter.check_concentration("BTC/USD", 5000.0)

        assert should_reject is True
        mock_counter.labels.assert_called_once_with(
            reason="concentration",
            pair="BTC/USD"
        )
        mock_counter.labels.return_value.inc.assert_called_once()


class TestCheckSignal:
    """Test signal checking integration."""

    def test_check_signal_accept(self):
        """Test signal checking accepts signal with low concentration."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        signal = {"trading_pair": "BTC/USD"}

        should_reject = filter.check_signal(
            signal=signal,
            position_size_usd=2000.0
        )

        assert should_reject is False

    def test_check_signal_reject(self):
        """Test signal checking rejects signal with high concentration."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        signal = {"trading_pair": "BTC/USD"}

        should_reject = filter.check_signal(
            signal=signal,
            position_size_usd=5000.0
        )

        assert should_reject is True

    def test_check_signal_with_existing_positions(self):
        """Test signal checking with existing positions."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        signal = {"pair": "BTC/USD"}  # Using 'pair' field
        existing = [
            {"symbol": "BTC/USD", "size_usd": 3000.0}
        ]

        # New $2000 + existing $3000 = 50% (reject)
        should_reject = filter.check_signal(
            signal=signal,
            position_size_usd=2000.0,
            existing_positions=existing
        )

        assert should_reject is True


class TestUpdatePortfolioValue:
    """Test portfolio value updates."""

    def test_update_portfolio_value(self, caplog):
        """Test updating portfolio value."""
        import logging
        filter = PRDConcentrationFilter(total_portfolio_value=10000.0)

        with caplog.at_level(logging.INFO):
            filter.update_portfolio_value(15000.0)

        assert filter.total_portfolio_value == 15000.0
        assert "Portfolio value updated" in caplog.text
        assert "$10000.00 → $15000.00" in caplog.text

    def test_update_portfolio_value_affects_concentration(self):
        """Test that updating portfolio value affects concentration calculations."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # $5000 / $10000 = 50% (reject)
        should_reject1, conc1 = filter.check_concentration("BTC/USD", 5000.0)
        assert should_reject1 is True
        assert abs(conc1 - 50.0) < 0.01

        # Update portfolio to $20000
        filter.update_portfolio_value(20000.0)

        # $5000 / $20000 = 25% (accept)
        should_reject2, conc2 = filter.check_concentration("BTC/USD", 5000.0)
        assert should_reject2 is False
        assert abs(conc2 - 25.0) < 0.01


class TestGetMetrics:
    """Test metrics retrieval."""

    def test_get_metrics_initial(self):
        """Test metrics with no checks."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        metrics = filter.get_metrics()

        assert metrics["total_checks"] == 0
        assert metrics["total_rejections"] == 0
        assert metrics["rejection_rate"] == 0.0
        assert metrics["max_concentration_pct"] == 40.0
        assert metrics["total_portfolio_value"] == 10000.0

    def test_get_metrics_after_checks(self):
        """Test metrics after some checks."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # 2 rejections, 3 acceptances
        filter.check_concentration("BTC/USD", 5000.0)  # Reject (50%)
        filter.check_concentration("ETH/USD", 6000.0)  # Reject (60%)
        filter.check_concentration("XRP/USD", 2000.0)  # Accept (20%)
        filter.check_concentration("LTC/USD", 3000.0)  # Accept (30%)
        filter.check_concentration("ADA/USD", 1000.0)  # Accept (10%)

        metrics = filter.get_metrics()

        assert metrics["total_checks"] == 5
        assert metrics["total_rejections"] == 2
        assert abs(metrics["rejection_rate"] - 0.4) < 0.01


class TestResetStats:
    """Test statistics reset."""

    def test_reset_stats(self, caplog):
        """Test statistics reset."""
        import logging
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # Make some checks
        filter.check_concentration("BTC/USD", 5000.0)  # Reject
        filter.check_concentration("ETH/USD", 2000.0)  # Accept

        assert filter.total_checks == 2
        assert filter.total_rejections == 1

        # Reset
        with caplog.at_level(logging.INFO):
            filter.reset_stats()

        assert filter.total_checks == 0
        assert filter.total_rejections == 0
        assert "Concentration filter statistics reset" in caplog.text


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_concentration_100_percent(self, caplog):
        """Test 100% concentration (entire portfolio in one symbol)."""
        import logging
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        with caplog.at_level(logging.WARNING):
            should_reject, concentration = filter.check_concentration(
                "BTC/USD", 10000.0
            )

        assert should_reject is True
        assert abs(concentration - 100.0) < 0.01

    def test_concentration_over_100_percent(self):
        """Test concentration over 100% (leveraged position)."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # $15000 position / $10000 portfolio = 150%
        should_reject, concentration = filter.check_concentration(
            "BTC/USD", 15000.0
        )

        assert should_reject is True
        assert abs(concentration - 150.0) < 0.01

    def test_very_small_position(self):
        """Test very small position (< 1%)."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # $50 / $10000 = 0.5%
        should_reject, concentration = filter.check_concentration(
            "BTC/USD", 50.0
        )

        assert should_reject is False
        assert abs(concentration - 0.5) < 0.01

    def test_custom_threshold(self):
        """Test with custom concentration threshold."""
        filter = PRDConcentrationFilter(
            max_concentration_pct=25.0,  # More conservative
            total_portfolio_value=10000.0
        )

        # $3000 / $10000 = 30% (would pass default 40%, but fails 25%)
        should_reject, concentration = filter.check_concentration(
            "BTC/USD", 3000.0
        )

        assert should_reject is True
        assert abs(concentration - 30.0) < 0.01
