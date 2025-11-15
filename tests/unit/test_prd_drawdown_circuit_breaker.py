"""
Unit tests for PRDDrawdownCircuitBreaker (PRD-001 Section 4.3)

Tests coverage:
- P&L tracking from midnight UTC daily reset
- Daily drawdown calculation accuracy
- Circuit breaker activation at -5% threshold
- CRITICAL level logging verification
- Prometheus counter and gauge emission
- Auto-reset at midnight UTC
- Simulated losing trades (PRD requirement)

Author: Crypto AI Bot Team
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from agents.risk.prd_drawdown_circuit_breaker import PRDDrawdownCircuitBreaker


class TestPRDDrawdownCircuitBreakerInit:
    """Test PRDDrawdownCircuitBreaker initialization."""

    def test_init_default_params(self):
        """Test initialization with default parameters."""
        breaker = PRDDrawdownCircuitBreaker()
        assert breaker.start_of_day_equity == Decimal("10000.0")
        assert breaker.current_equity == Decimal("10000.0")
        assert breaker.max_drawdown_pct == -5.0
        assert breaker.auto_reset is True
        assert breaker.is_active is False
        assert breaker.activation_time is None
        assert breaker.total_checks == 0
        assert breaker.total_activations == 0

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        breaker = PRDDrawdownCircuitBreaker(
            start_of_day_equity=50000.0,
            max_drawdown_pct=-3.0,
            auto_reset=False
        )
        assert breaker.start_of_day_equity == Decimal("50000.0")
        assert breaker.current_equity == Decimal("50000.0")
        assert breaker.max_drawdown_pct == -3.0
        assert breaker.auto_reset is False

    def test_init_logs_info(self, caplog):
        """Test that initialization logs at INFO level."""
        import logging
        with caplog.at_level(logging.INFO):
            breaker = PRDDrawdownCircuitBreaker(
                start_of_day_equity=10000.0,
                max_drawdown_pct=-5.0
            )

        assert "PRDDrawdownCircuitBreaker initialized" in caplog.text
        assert "start_equity=10000.00" in caplog.text
        assert "max_drawdown=-5.0%" in caplog.text


class TestCalculateDrawdownPct:
    """Test drawdown percentage calculation."""

    def test_calculate_drawdown_no_change(self):
        """Test drawdown with no equity change."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(10000.0)

        drawdown_pct = breaker.calculate_drawdown_pct()

        assert drawdown_pct == 0.0

    def test_calculate_drawdown_profit(self):
        """Test drawdown with profit (positive)."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(10500.0)

        drawdown_pct = breaker.calculate_drawdown_pct()

        # (10500 - 10000) / 10000 * 100 = 5.0%
        assert abs(drawdown_pct - 5.0) < 0.01

    def test_calculate_drawdown_loss_small(self):
        """Test drawdown with small loss."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9800.0)

        drawdown_pct = breaker.calculate_drawdown_pct()

        # (9800 - 10000) / 10000 * 100 = -2.0%
        assert abs(drawdown_pct - (-2.0)) < 0.01

    def test_calculate_drawdown_loss_at_threshold(self):
        """Test drawdown exactly at -5% threshold."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9500.0)

        drawdown_pct = breaker.calculate_drawdown_pct()

        # (9500 - 10000) / 10000 * 100 = -5.0%
        assert abs(drawdown_pct - (-5.0)) < 0.01

    def test_calculate_drawdown_loss_beyond_threshold(self):
        """Test drawdown beyond -5% threshold."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9000.0)

        drawdown_pct = breaker.calculate_drawdown_pct()

        # (9000 - 10000) / 10000 * 100 = -10.0%
        assert abs(drawdown_pct - (-10.0)) < 0.01

    def test_calculate_drawdown_zero_start_equity(self, caplog):
        """Test drawdown with zero start equity."""
        import logging
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=0.0)

        with caplog.at_level(logging.WARNING):
            drawdown_pct = breaker.calculate_drawdown_pct()

        assert drawdown_pct == 0.0
        assert "Invalid start_of_day_equity" in caplog.text


class TestCheck:
    """Test circuit breaker checking logic."""

    def test_check_normal_operation(self):
        """Test circuit breaker with normal equity."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(10000.0)

        is_halted, drawdown_pct = breaker.check()

        assert is_halted is False
        assert drawdown_pct == 0.0
        assert breaker.is_active is False
        assert breaker.total_checks == 1

    def test_check_small_loss(self):
        """Test circuit breaker with small loss (within threshold)."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9700.0)  # -3% drawdown

        is_halted, drawdown_pct = breaker.check()

        assert is_halted is False
        assert abs(drawdown_pct - (-3.0)) < 0.01
        assert breaker.is_active is False

    def test_check_exactly_at_threshold(self):
        """Test circuit breaker exactly at -5% threshold."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9500.0)  # -5.0% drawdown

        is_halted, drawdown_pct = breaker.check()

        # Threshold is <, so exactly -5.0% should NOT trigger
        assert is_halted is False
        assert abs(drawdown_pct - (-5.0)) < 0.01
        assert breaker.is_active is False

    def test_check_circuit_breaker_activation(self, caplog):
        """Test circuit breaker activation at -5.1% (beyond threshold)."""
        import logging
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9490.0)  # -5.1% drawdown

        with caplog.at_level(logging.CRITICAL):
            is_halted, drawdown_pct = breaker.check()

        assert is_halted is True
        assert drawdown_pct < -5.0
        assert breaker.is_active is True
        assert breaker.activation_time is not None
        assert breaker.total_activations == 1
        assert "[CIRCUIT BREAKER ACTIVATED]" in caplog.text
        assert "HALTING NEW SIGNALS" in caplog.text

    def test_check_stays_active_once_triggered(self):
        """Test circuit breaker stays active after triggered."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9400.0)  # -6% drawdown

        # First check - should activate
        is_halted1, _ = breaker.check()
        assert is_halted1 is True
        assert breaker.total_activations == 1

        # Second check - should stay active (no new activation)
        is_halted2, _ = breaker.check()
        assert is_halted2 is True
        assert breaker.total_activations == 1  # Same count

    @patch('agents.risk.prd_drawdown_circuit_breaker.PROMETHEUS_AVAILABLE', True)
    @patch('agents.risk.prd_drawdown_circuit_breaker.CIRCUIT_BREAKER_TRIGGERED')
    @patch('agents.risk.prd_drawdown_circuit_breaker.CURRENT_DRAWDOWN_PCT')
    def test_check_emits_prometheus_metrics(self, mock_gauge, mock_counter):
        """Test that Prometheus metrics are emitted."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9400.0)  # -6% drawdown

        breaker.check()

        # Counter should be incremented
        mock_counter.labels.assert_called_once_with(reason="daily_drawdown")
        mock_counter.labels.return_value.inc.assert_called_once()

        # Gauge should be set (called during update_equity and check)
        assert mock_gauge.set.called


class TestResetForNewDay:
    """Test daily reset functionality."""

    def test_reset_for_new_day_default(self, caplog):
        """Test reset for new day with default (carry forward equity)."""
        import logging
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9500.0)  # Lost $500

        with caplog.at_level(logging.INFO):
            breaker.reset_for_new_day()

        # Should carry forward 9500 as new start
        assert breaker.start_of_day_equity == Decimal("9500.0")
        assert breaker.current_equity == Decimal("9500.0")
        assert breaker.is_active is False
        assert breaker.activation_time is None
        assert "[DAILY RESET]" in caplog.text

    def test_reset_for_new_day_with_new_equity(self, caplog):
        """Test reset for new day with specified new equity."""
        import logging
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9500.0)

        with caplog.at_level(logging.INFO):
            breaker.reset_for_new_day(new_start_equity=12000.0)

        # Should use specified 12000 as new start
        assert breaker.start_of_day_equity == Decimal("12000.0")
        assert breaker.current_equity == Decimal("12000.0")
        assert "[DAILY RESET]" in caplog.text
        assert "12000.00" in caplog.text

    def test_reset_clears_circuit_breaker(self):
        """Test reset clears active circuit breaker."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9400.0)  # Trigger circuit breaker
        breaker.check()

        assert breaker.is_active is True

        # Reset should clear circuit breaker
        breaker.reset_for_new_day()

        assert breaker.is_active is False
        assert breaker.activation_time is None


class TestAutoReset:
    """Test automatic daily reset."""

    @patch('agents.risk.prd_drawdown_circuit_breaker.PRDDrawdownCircuitBreaker._get_current_day_start')
    @patch('agents.risk.prd_drawdown_circuit_breaker.PRDDrawdownCircuitBreaker._should_reset')
    def test_auto_reset_on_check(self, mock_should_reset, mock_get_day_start, caplog):
        """Test that check() triggers auto-reset when new day."""
        import logging

        # Mock: new day has started
        mock_should_reset.return_value = True

        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0, auto_reset=True)
        breaker.update_equity(9500.0)

        with caplog.at_level(logging.INFO):
            is_halted, drawdown_pct = breaker.check()

        # Should have auto-reset
        assert "[DAILY RESET]" in caplog.text

    def test_no_auto_reset_when_disabled(self):
        """Test that auto-reset doesn't happen when disabled."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0, auto_reset=False)
        initial_start = breaker.start_of_day_equity

        # Even if we manually change day_start_time, shouldn't auto-reset
        breaker.day_start_time = breaker.day_start_time - timedelta(days=1)

        breaker.check()

        # Start equity should be unchanged
        assert breaker.start_of_day_equity == initial_start


class TestCheckSignal:
    """Test signal checking integration."""

    def test_check_signal_accept_normal(self):
        """Test signal checking accepts signal with normal equity."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(10000.0)

        signal = {"trading_pair": "BTC/USD"}

        should_reject = breaker.check_signal(signal)

        assert should_reject is False

    def test_check_signal_reject_circuit_breaker(self, caplog):
        """Test signal checking rejects signal with circuit breaker active."""
        import logging
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9400.0)  # -6% drawdown

        signal = {"trading_pair": "BTC/USD"}

        with caplog.at_level(logging.WARNING):
            should_reject = breaker.check_signal(signal)

        assert should_reject is True
        assert "Signal rejected due to daily drawdown circuit breaker" in caplog.text


class TestGetMetrics:
    """Test metrics retrieval."""

    def test_get_metrics_initial(self):
        """Test metrics with no checks."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)

        metrics = breaker.get_metrics()

        assert metrics["total_checks"] == 0
        assert metrics["total_activations"] == 0
        assert metrics["activation_rate"] == 0.0
        assert metrics["is_active"] is False
        assert metrics["current_drawdown_pct"] == 0.0
        assert metrics["start_of_day_equity"] == 10000.0
        assert metrics["current_equity"] == 10000.0
        assert metrics["max_drawdown_pct"] == -5.0
        assert metrics["activation_time"] is None

    def test_get_metrics_after_activation(self):
        """Test metrics after circuit breaker activation."""
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.update_equity(9400.0)
        breaker.check()
        breaker.check()  # Second check

        metrics = breaker.get_metrics()

        assert metrics["total_checks"] == 2
        assert metrics["total_activations"] == 1
        assert abs(metrics["activation_rate"] - 0.5) < 0.01
        assert metrics["is_active"] is True
        assert metrics["current_drawdown_pct"] < -5.0
        assert metrics["current_equity"] == 9400.0
        assert metrics["activation_time"] is not None


class TestResetStats:
    """Test statistics reset."""

    def test_reset_stats(self, caplog):
        """Test statistics reset."""
        import logging
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)

        # Make some checks
        breaker.update_equity(9400.0)
        breaker.check()
        breaker.check()

        assert breaker.total_checks == 2
        assert breaker.total_activations == 1

        # Reset
        with caplog.at_level(logging.INFO):
            breaker.reset_stats()

        assert breaker.total_checks == 0
        assert breaker.total_activations == 0
        assert "Circuit breaker statistics reset" in caplog.text


class TestManualControl:
    """Test manual activation/deactivation."""

    def test_force_activate(self, caplog):
        """Test manual activation."""
        import logging
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)

        with caplog.at_level(logging.CRITICAL):
            breaker.force_activate()

        assert breaker.is_active is True
        assert breaker.activation_time is not None
        assert breaker.total_activations == 1
        assert "[CIRCUIT BREAKER MANUALLY ACTIVATED]" in caplog.text

    def test_force_deactivate(self, caplog):
        """Test manual deactivation."""
        import logging
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)
        breaker.force_activate()

        with caplog.at_level(logging.WARNING):
            breaker.force_deactivate()

        assert breaker.is_active is False
        assert breaker.activation_time is None
        assert "[CIRCUIT BREAKER MANUALLY DEACTIVATED]" in caplog.text


class TestSimulatedLosingTrades:
    """
    PRD-001 Section 4.3 Requirement:
    Add daily drawdown unit test with simulated losing trades.
    """

    def test_simulated_losing_trades_sequence(self, caplog):
        """
        Test circuit breaker with simulated sequence of losing trades.

        Scenario:
        - Start with $10,000
        - Lose $200 on trade 1 (equity = $9,800, drawdown = -2%)
        - Lose $150 on trade 2 (equity = $9,650, drawdown = -3.5%)
        - Lose $100 on trade 3 (equity = $9,550, drawdown = -4.5%)
        - Lose $100 on trade 4 (equity = $9,450, drawdown = -5.5%)  <- TRIGGER
        """
        import logging

        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)

        # Trade 1: Lose $200
        breaker.update_equity(9800.0)
        is_halted, drawdown = breaker.check()
        assert is_halted is False  # -2% < -5% threshold
        assert abs(drawdown - (-2.0)) < 0.1

        # Trade 2: Lose $150
        breaker.update_equity(9650.0)
        is_halted, drawdown = breaker.check()
        assert is_halted is False  # -3.5% < -5% threshold
        assert abs(drawdown - (-3.5)) < 0.1

        # Trade 3: Lose $100
        breaker.update_equity(9550.0)
        is_halted, drawdown = breaker.check()
        assert is_halted is False  # -4.5% < -5% threshold
        assert abs(drawdown - (-4.5)) < 0.1

        # Trade 4: Lose $100 (SHOULD TRIGGER)
        breaker.update_equity(9450.0)
        with caplog.at_level(logging.CRITICAL):
            is_halted, drawdown = breaker.check()

        assert is_halted is True  # -5.5% triggers circuit breaker
        assert drawdown < -5.0
        assert breaker.is_active is True
        assert "[CIRCUIT BREAKER ACTIVATED]" in caplog.text

        # Trade 5: Try to trade (should still be halted)
        breaker.update_equity(9350.0)  # Another loss
        is_halted, drawdown = breaker.check()
        assert is_halted is True  # Still halted

    def test_simulated_losing_trades_with_recovery(self, caplog):
        """
        Test circuit breaker with losses followed by recovery.

        Scenario:
        - Start with $10,000
        - Lose $600 (equity = $9,400, drawdown = -6%)  <- TRIGGER
        - After reset, start new day with $9,400
        - Gain $300 (equity = $9,700, drawdown = +3.2% from new start)
        """
        import logging

        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0)

        # Big loss triggers circuit breaker
        breaker.update_equity(9400.0)
        with caplog.at_level(logging.CRITICAL):
            is_halted, drawdown = breaker.check()

        assert is_halted is True
        assert drawdown == -6.0

        # Reset for new day (carry forward $9,400)
        with caplog.at_level(logging.INFO):
            breaker.reset_for_new_day()

        assert breaker.start_of_day_equity == Decimal("9400.0")
        assert breaker.is_active is False

        # Gain $300
        breaker.update_equity(9700.0)
        is_halted, drawdown = breaker.check()

        assert is_halted is False  # No longer halted, new day
        assert abs(drawdown - 3.191) < 0.1  # (9700-9400)/9400 * 100 = 3.19%

    def test_simulated_losing_trades_multiple_days(self):
        """
        Test circuit breaker over multiple simulated trading days.

        Day 1: Start $10,000 → Lose $600 → End $9,400 (circuit breaker)
        Day 2: Start $9,400 → Lose $500 → End $8,900 (circuit breaker)
        Day 3: Start $8,900 → Gain $200 → End $9,100 (no circuit breaker)
        """
        breaker = PRDDrawdownCircuitBreaker(start_of_day_equity=10000.0, auto_reset=False)

        # === Day 1 ===
        breaker.update_equity(9400.0)  # -6% loss
        is_halted, _ = breaker.check()
        assert is_halted is True

        # Reset for Day 2
        breaker.reset_for_new_day()

        # === Day 2 ===
        assert breaker.start_of_day_equity == Decimal("9400.0")
        breaker.update_equity(8900.0)  # -5.32% loss
        is_halted, _ = breaker.check()
        assert is_halted is True

        # Reset for Day 3
        breaker.reset_for_new_day()

        # === Day 3 ===
        assert breaker.start_of_day_equity == Decimal("8900.0")
        breaker.update_equity(9100.0)  # +2.25% gain
        is_halted, drawdown = breaker.check()
        assert is_halted is False  # No circuit breaker, profitable day
        assert drawdown > 0  # Positive drawdown (profit)
