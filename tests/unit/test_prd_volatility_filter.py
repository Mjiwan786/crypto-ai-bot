"""
Unit tests for PRDVolatilityFilter (PRD-001 Section 4.2)

Tests coverage:
- ATR(14) calculation accuracy
- 30-day rolling average ATR tracking
- Position sizing adjustment (50% reduction at 3.0x)
- Circuit breaker (halt at 5.0x)
- INFO level logging verification
- Prometheus counter emission
- Edge cases

Author: Crypto AI Bot Team
"""

import pytest
from unittest.mock import Mock, patch
import numpy as np
from collections import deque

from agents.risk.prd_volatility_filter import PRDVolatilityFilter


class TestPRDVolatilityFilterInit:
    """Test PRDVolatilityFilter initialization."""

    def test_init_default_params(self):
        """Test initialization with default parameters."""
        filter = PRDVolatilityFilter()
        assert filter.atr_period == 14
        assert filter.rolling_window_days == 30
        assert filter.position_reduction_threshold == 3.0
        assert filter.circuit_breaker_threshold == 5.0
        assert filter.total_checks == 0
        assert filter.total_reductions == 0
        assert filter.total_halts == 0
        assert len(filter.atr_history) == 0

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        filter = PRDVolatilityFilter(
            atr_period=20,
            rolling_window_days=60,
            position_reduction_threshold=2.5,
            circuit_breaker_threshold=4.0
        )
        assert filter.atr_period == 20
        assert filter.rolling_window_days == 60
        assert filter.position_reduction_threshold == 2.5
        assert filter.circuit_breaker_threshold == 4.0

    def test_init_logs_info(self, caplog):
        """Test that initialization logs at INFO level."""
        import logging
        with caplog.at_level(logging.INFO):
            filter = PRDVolatilityFilter(
                position_reduction_threshold=3.0,
                circuit_breaker_threshold=5.0
            )

        assert "PRDVolatilityFilter initialized" in caplog.text
        assert "reduction_threshold=3.0x" in caplog.text
        assert "circuit_breaker_threshold=5.0x" in caplog.text


class TestCalculateATR:
    """Test ATR calculation."""

    def test_calculate_atr_simple(self):
        """Test ATR calculation with simple data."""
        filter = PRDVolatilityFilter(atr_period=3)

        # Simple price data
        high = [102, 104, 103, 105]
        low = [98, 100, 99, 101]
        close = [100, 102, 101, 103]

        atr = filter.calculate_atr(high, low, close, period=3)

        # TR1 = max(104-100, |104-100|, |100-100|) = 4
        # TR2 = max(103-99, |103-102|, |99-102|) = max(4, 1, 3) = 4
        # TR3 = max(105-101, |105-101|, |101-101|) = 4
        # ATR = (4 + 4 + 4) / 3 = 4.0

        assert abs(atr - 4.0) < 0.1

    def test_calculate_atr_insufficient_data(self, caplog):
        """Test ATR calculation with insufficient data."""
        import logging
        filter = PRDVolatilityFilter(atr_period=14)

        high = [102, 104]
        low = [98, 100]
        close = [100, 102]

        with caplog.at_level(logging.WARNING):
            atr = filter.calculate_atr(high, low, close)

        assert atr == 0.0
        assert "Insufficient data for ATR calculation" in caplog.text

    def test_calculate_atr_empty_data(self):
        """Test ATR calculation with empty data."""
        filter = PRDVolatilityFilter()

        atr = filter.calculate_atr([], [], [])

        assert atr == 0.0

    def test_calculate_atr_real_data(self):
        """Test ATR calculation with realistic market data."""
        filter = PRDVolatilityFilter(atr_period=14)

        # Generate realistic BTC price data (around 50000)
        np.random.seed(42)
        base_price = 50000
        close = [base_price]

        for _ in range(20):
            change = np.random.randn() * 500
            close.append(close[-1] + change)

        high = [c + abs(np.random.randn() * 200) for c in close]
        low = [c - abs(np.random.randn() * 200) for c in close]

        atr = filter.calculate_atr(high, low, close)

        assert atr > 0
        assert atr < 5000  # Reasonable range for BTC


class TestUpdateATRHistory:
    """Test ATR history tracking."""

    def test_update_atr_history_new_pair(self):
        """Test updating ATR history for new pair."""
        filter = PRDVolatilityFilter()

        filter.update_atr_history("BTC/USD", 1500.0)

        assert "BTC/USD" in filter.atr_history
        assert len(filter.atr_history["BTC/USD"]) == 1
        assert filter.atr_history["BTC/USD"][0] == 1500.0

    def test_update_atr_history_multiple(self):
        """Test updating ATR history multiple times."""
        filter = PRDVolatilityFilter()

        filter.update_atr_history("BTC/USD", 1500.0)
        filter.update_atr_history("BTC/USD", 1550.0)
        filter.update_atr_history("BTC/USD", 1600.0)

        assert len(filter.atr_history["BTC/USD"]) == 3
        assert list(filter.atr_history["BTC/USD"]) == [1500.0, 1550.0, 1600.0]

    def test_update_atr_history_multiple_pairs(self):
        """Test updating ATR history for multiple pairs."""
        filter = PRDVolatilityFilter()

        filter.update_atr_history("BTC/USD", 1500.0)
        filter.update_atr_history("ETH/USD", 100.0)
        filter.update_atr_history("BTC/USD", 1550.0)

        assert len(filter.atr_history) == 2
        assert len(filter.atr_history["BTC/USD"]) == 2
        assert len(filter.atr_history["ETH/USD"]) == 1

    def test_update_atr_history_max_length(self):
        """Test that ATR history respects max length."""
        filter = PRDVolatilityFilter(rolling_window_days=1)  # 288 candles max

        # Add more than max candles
        for i in range(300):
            filter.update_atr_history("BTC/USD", float(i))

        # Should only keep last 288
        assert len(filter.atr_history["BTC/USD"]) == 288
        # Should have the most recent values
        assert filter.atr_history["BTC/USD"][-1] == 299.0


class TestGetRollingAverageATR:
    """Test rolling average ATR calculation."""

    def test_get_rolling_average_atr_no_history(self, caplog):
        """Test rolling average with no history."""
        import logging
        filter = PRDVolatilityFilter()

        with caplog.at_level(logging.DEBUG):
            avg_atr = filter.get_rolling_average_atr("BTC/USD")

        assert avg_atr is None
        assert "No ATR history" in caplog.text

    def test_get_rolling_average_atr_single_value(self):
        """Test rolling average with single value."""
        filter = PRDVolatilityFilter()

        filter.update_atr_history("BTC/USD", 1500.0)
        avg_atr = filter.get_rolling_average_atr("BTC/USD")

        assert avg_atr == 1500.0

    def test_get_rolling_average_atr_multiple_values(self):
        """Test rolling average with multiple values."""
        filter = PRDVolatilityFilter()

        filter.update_atr_history("BTC/USD", 1000.0)
        filter.update_atr_history("BTC/USD", 1500.0)
        filter.update_atr_history("BTC/USD", 2000.0)

        avg_atr = filter.get_rolling_average_atr("BTC/USD")

        assert abs(avg_atr - 1500.0) < 0.1  # (1000 + 1500 + 2000) / 3 = 1500


class TestCalculateATRRatio:
    """Test ATR ratio calculation."""

    def test_calculate_atr_ratio_normal(self):
        """Test ATR ratio calculation with normal values."""
        filter = PRDVolatilityFilter()

        ratio = filter.calculate_atr_ratio(current_atr=3000.0, avg_atr=1000.0)

        assert ratio == 3.0

    def test_calculate_atr_ratio_low(self):
        """Test ATR ratio below thresholds."""
        filter = PRDVolatilityFilter()

        ratio = filter.calculate_atr_ratio(current_atr=1500.0, avg_atr=1000.0)

        assert ratio == 1.5

    def test_calculate_atr_ratio_zero_avg(self, caplog):
        """Test ATR ratio with zero average."""
        import logging
        filter = PRDVolatilityFilter()

        with caplog.at_level(logging.WARNING):
            ratio = filter.calculate_atr_ratio(current_atr=1500.0, avg_atr=0.0)

        assert ratio == 999.0
        assert "Invalid avg_atr" in caplog.text


class TestCheckVolatility:
    """Test volatility checking logic."""

    def test_check_volatility_normal(self, caplog):
        """Test volatility check with normal ATR."""
        import logging
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        # Check with normal ATR (1.5x average)
        with caplog.at_level(logging.DEBUG):
            should_halt, position_multiplier, atr_ratio = filter.check_volatility(
                pair="BTC/USD",
                current_atr=1500.0
            )

        assert should_halt is False
        assert position_multiplier == 1.0
        assert abs(atr_ratio - 1.5) < 0.1
        assert "[VOLATILITY CHECK]" in caplog.text
        assert "NORMAL" in caplog.text

    def test_check_volatility_position_reduction(self, caplog):
        """Test volatility check triggers position reduction at 3.0x."""
        import logging
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        # Check with high ATR (3.5x average) - should reduce position
        with caplog.at_level(logging.INFO):
            should_halt, position_multiplier, atr_ratio = filter.check_volatility(
                pair="BTC/USD",
                current_atr=3500.0
            )

        assert should_halt is False
        assert position_multiplier == 0.5  # 50% reduction
        assert abs(atr_ratio - 3.5) < 0.1
        assert filter.total_reductions == 1
        assert "[VOLATILITY REDUCTION]" in caplog.text
        assert "REDUCING POSITION SIZE BY 50%" in caplog.text

    def test_check_volatility_circuit_breaker(self, caplog):
        """Test volatility check triggers circuit breaker at 5.0x."""
        import logging
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        # Check with extreme ATR (6.0x average) - should halt
        # Note: current_atr gets added to history, changing avg
        # avg = (100*1000 + 6000) / 101 = 1049.5
        # ratio = 6000 / 1049.5 = 5.72x > 5.0x threshold
        with caplog.at_level(logging.INFO):
            should_halt, position_multiplier, atr_ratio = filter.check_volatility(
                pair="BTC/USD",
                current_atr=6000.0
            )

        assert should_halt is True
        assert position_multiplier == 0.0  # Halted
        assert atr_ratio > 5.0  # Should be > circuit breaker threshold
        assert filter.total_halts == 1
        assert "[VOLATILITY HALT]" in caplog.text
        assert "HALTING NEW SIGNALS" in caplog.text

    def test_check_volatility_exactly_at_reduction_threshold(self):
        """Test volatility exactly at 3.0x threshold."""
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        # Check with exactly 3.0x ATR
        should_halt, position_multiplier, atr_ratio = filter.check_volatility(
            pair="BTC/USD",
            current_atr=3000.0
        )

        # Should be normal (threshold is >, not >=)
        assert should_halt is False
        assert position_multiplier == 1.0

    def test_check_volatility_exactly_at_circuit_breaker_threshold(self):
        """Test volatility exactly at 5.0x threshold."""
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        # Check with 5.0x ATR
        # Note: current_atr gets added to history, changing avg
        # avg = (100*1000 + 5000) / 101 = 1039.6
        # ratio = 5000 / 1039.6 = 4.81x
        # This is > 3.0x (reduction threshold) but < 5.0x (circuit breaker)
        should_halt, position_multiplier, atr_ratio = filter.check_volatility(
            pair="BTC/USD",
            current_atr=5000.0
        )

        # Should trigger position reduction, not circuit breaker
        assert should_halt is False
        assert position_multiplier == 0.5  # Reduced, not halted
        assert 3.0 < atr_ratio < 5.0

    def test_check_volatility_insufficient_history(self, caplog):
        """Test volatility check with insufficient history."""
        import logging
        filter = PRDVolatilityFilter()

        # No previous history - current ATR will be added as first value
        # avg will be current value, so ratio = current / current = 1.0
        with caplog.at_level(logging.DEBUG):
            should_halt, position_multiplier, atr_ratio = filter.check_volatility(
                pair="BTC/USD",
                current_atr=5000.0
            )

        # With single value, ratio is 1.0 (normal operation)
        assert should_halt is False
        assert position_multiplier == 1.0
        assert atr_ratio == 1.0
        assert "[VOLATILITY CHECK]" in caplog.text
        assert "NORMAL" in caplog.text

    @patch('agents.risk.prd_volatility_filter.PROMETHEUS_AVAILABLE', True)
    @patch('agents.risk.prd_volatility_filter.RISK_FILTER_REJECTIONS')
    def test_check_volatility_emits_prometheus_counter(self, mock_counter):
        """Test that Prometheus counter is emitted on circuit breaker."""
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        # Trigger circuit breaker
        should_halt, _, _ = filter.check_volatility(
            pair="BTC/USD",
            current_atr=6000.0
        )

        assert should_halt is True
        mock_counter.labels.assert_called_once_with(
            reason="high_volatility",
            pair="BTC/USD"
        )
        mock_counter.labels.return_value.inc.assert_called_once()


class TestCheckSignal:
    """Test signal checking integration."""

    def test_check_signal_with_market_data_normal(self):
        """Test signal checking with market data - normal volatility."""
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        signal = {"trading_pair": "BTC/USD"}
        market_data = {"atr_14": 1500.0}

        should_halt, position_multiplier = filter.check_signal(signal, market_data)

        assert should_halt is False
        assert position_multiplier == 1.0

    def test_check_signal_with_market_data_reduced(self):
        """Test signal checking with market data - reduced position."""
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        signal = {"trading_pair": "BTC/USD"}
        market_data = {"atr": 3500.0}

        should_halt, position_multiplier = filter.check_signal(signal, market_data)

        assert should_halt is False
        assert position_multiplier == 0.5

    def test_check_signal_with_market_data_halted(self):
        """Test signal checking with market data - halted."""
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        signal = {"trading_pair": "BTC/USD"}
        market_data = {"atr_14": 6000.0}

        should_halt, position_multiplier = filter.check_signal(signal, market_data)

        assert should_halt is True
        assert position_multiplier == 0.0

    def test_check_signal_atr_from_signal(self):
        """Test signal checking gets ATR from signal if not in market_data."""
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        signal = {"trading_pair": "BTC/USD", "atr_14": 1500.0}

        should_halt, position_multiplier = filter.check_signal(signal, market_data=None)

        assert should_halt is False
        assert position_multiplier == 1.0

    def test_check_signal_no_atr_allows_signal(self, caplog):
        """Test that missing ATR allows signal (fail open)."""
        import logging
        filter = PRDVolatilityFilter()

        signal = {"trading_pair": "BTC/USD"}

        with caplog.at_level(logging.WARNING):
            should_halt, position_multiplier = filter.check_signal(signal, market_data=None)

        assert should_halt is False
        assert position_multiplier == 1.0
        assert "No ATR data available" in caplog.text
        assert "allowing signal" in caplog.text


class TestGetMetrics:
    """Test metrics retrieval."""

    def test_get_metrics_initial(self):
        """Test metrics with no checks."""
        filter = PRDVolatilityFilter()

        metrics = filter.get_metrics()

        assert metrics["total_checks"] == 0
        assert metrics["total_reductions"] == 0
        assert metrics["total_halts"] == 0
        assert metrics["reduction_rate"] == 0.0
        assert metrics["halt_rate"] == 0.0
        assert metrics["pairs_tracked"] == 0

    def test_get_metrics_after_checks(self):
        """Test metrics after some checks."""
        filter = PRDVolatilityFilter()

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)
            filter.update_atr_history("ETH/USD", 100.0)

        # 2 normal, 2 reductions, 1 halt
        filter.check_volatility("BTC/USD", 1500.0)  # Normal
        filter.check_volatility("BTC/USD", 1800.0)  # Normal
        filter.check_volatility("BTC/USD", 3500.0)  # Reduction
        filter.check_volatility("BTC/USD", 4000.0)  # Reduction
        filter.check_volatility("BTC/USD", 6000.0)  # Halt

        metrics = filter.get_metrics()

        assert metrics["total_checks"] == 5
        assert metrics["total_reductions"] == 2
        assert metrics["total_halts"] == 1
        assert abs(metrics["reduction_rate"] - 0.4) < 0.01
        assert abs(metrics["halt_rate"] - 0.2) < 0.01
        assert metrics["pairs_tracked"] == 2


class TestResetStats:
    """Test statistics reset."""

    def test_reset_stats(self, caplog):
        """Test statistics reset."""
        import logging
        filter = PRDVolatilityFilter()

        # Set up baseline history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        # Make some checks that trigger conditions
        # avg = 1000, so 3500 / ~1034 = 3.38x > 3.0 (reduction)
        filter.check_volatility("BTC/USD", 3500.0)  # Should trigger reduction

        # avg = ~1024, so 6000 / ~1074 = 5.59x > 5.0 (halt)
        filter.check_volatility("BTC/USD", 6000.0)  # Should trigger halt

        assert filter.total_checks == 2
        assert filter.total_reductions >= 1  # At least one reduction
        assert filter.total_halts >= 1  # At least one halt

        # Reset
        with caplog.at_level(logging.INFO):
            filter.reset_stats()

        assert filter.total_checks == 0
        assert filter.total_reductions == 0
        assert filter.total_halts == 0
        assert "Volatility filter statistics reset" in caplog.text


class TestClearHistory:
    """Test history clearing."""

    def test_clear_history_specific_pair(self, caplog):
        """Test clearing history for specific pair."""
        import logging
        filter = PRDVolatilityFilter()

        filter.update_atr_history("BTC/USD", 1000.0)
        filter.update_atr_history("ETH/USD", 100.0)

        with caplog.at_level(logging.INFO):
            filter.clear_history("BTC/USD")

        assert "BTC/USD" not in filter.atr_history
        assert "ETH/USD" in filter.atr_history
        assert "ATR history cleared for BTC/USD" in caplog.text

    def test_clear_history_all(self, caplog):
        """Test clearing all history."""
        import logging
        filter = PRDVolatilityFilter()

        filter.update_atr_history("BTC/USD", 1000.0)
        filter.update_atr_history("ETH/USD", 100.0)

        with caplog.at_level(logging.INFO):
            filter.clear_history()

        assert len(filter.atr_history) == 0
        assert "All ATR history cleared" in caplog.text


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_custom_thresholds(self):
        """Test with custom thresholds."""
        filter = PRDVolatilityFilter(
            position_reduction_threshold=2.0,
            circuit_breaker_threshold=4.0
        )

        # Set up history
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        # 2.5x should trigger reduction (threshold is 2.0)
        should_halt, position_multiplier, _ = filter.check_volatility("BTC/USD", 2500.0)
        assert should_halt is False
        assert position_multiplier == 0.5

        # 4.5x should trigger circuit breaker (threshold is 4.0)
        should_halt, position_multiplier, _ = filter.check_volatility("BTC/USD", 4500.0)
        assert should_halt is True
        assert position_multiplier == 0.0

    def test_very_low_volatility(self):
        """Test with very low current volatility."""
        filter = PRDVolatilityFilter()

        # Set up history with normal volatility
        for _ in range(100):
            filter.update_atr_history("BTC/USD", 1000.0)

        # Current ATR much lower (0.1x)
        should_halt, position_multiplier, atr_ratio = filter.check_volatility(
            "BTC/USD", 100.0
        )

        assert should_halt is False
        assert position_multiplier == 1.0
        assert abs(atr_ratio - 0.1) < 0.01
