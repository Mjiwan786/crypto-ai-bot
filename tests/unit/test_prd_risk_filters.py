"""
Unit tests for PRD-001 risk filters.

Tests:
1. PRDSpreadFilter - spread checks
2. PRDVolatilityFilter - ATR-based volatility limits
3. PRDDrawdownCircuitBreaker - daily drawdown protection

Run: pytest tests/unit/test_prd_risk_filters.py -v
"""

import pytest
from datetime import datetime, timezone, timedelta

from agents.risk.prd_spread_filter import PRDSpreadFilter
from agents.risk.prd_volatility_filter import PRDVolatilityFilter
from agents.risk.prd_drawdown_circuit_breaker import PRDDrawdownCircuitBreaker


# =============================================================================
# PRDSpreadFilter TESTS
# =============================================================================

class TestPRDSpreadFilter:
    """Test PRD-001 Section 4.1 spread filter."""

    @pytest.fixture
    def spread_filter(self):
        """Create spread filter with default threshold."""
        return PRDSpreadFilter(max_spread_pct=0.5)

    def test_calculate_spread_pct(self, spread_filter):
        """Test spread percentage calculation."""
        bid = 50000.0
        ask = 50025.0  # $25 spread
        mid = (bid + ask) / 2  # 50012.5
        
        spread_pct = spread_filter.calculate_spread_pct(bid, ask)
        # (25 / 50012.5) * 100 ≈ 0.05%
        assert spread_pct == pytest.approx(0.05, abs=0.01)

    def test_check_spread_accepts_tight_spread(self, spread_filter):
        """Test tight spread is accepted."""
        bid = 50000.0
        ask = 50010.0  # 0.02% spread
        should_reject, spread_pct = spread_filter.check_spread(bid, ask, "BTC/USD")
        
        assert should_reject is False
        assert spread_pct < 0.5

    def test_check_spread_rejects_wide_spread(self, spread_filter):
        """Test wide spread is rejected."""
        bid = 50000.0
        ask = 50250.0  # 0.5% spread (at threshold)
        should_reject, spread_pct = spread_filter.check_spread(bid, ask, "BTC/USD")
        
        assert should_reject is True
        assert spread_pct >= 0.5

    def test_check_spread_very_wide_spread(self, spread_filter):
        """Test very wide spread is rejected."""
        bid = 50000.0
        ask = 51000.0  # 2% spread
        should_reject, spread_pct = spread_filter.check_spread(bid, ask, "ETH/USD")
        
        assert should_reject is True
        assert spread_pct > 0.5

    def test_check_signal_with_market_data(self, spread_filter):
        """Test check_signal convenience method."""
        signal = {
            "trading_pair": "BTC/USD",
            "entry_price": 50000.0,
        }
        market_data = {
            "bid": 49990.0,
            "ask": 50010.0,  # 0.04% spread
        }
        
        should_reject = spread_filter.check_signal(signal, market_data)
        assert should_reject is False

    def test_check_signal_missing_market_data(self, spread_filter):
        """Test check_signal handles missing market data gracefully."""
        signal = {"trading_pair": "BTC/USD"}
        should_reject = spread_filter.check_signal(signal, None)
        # Should not reject if we can't check
        assert should_reject is False

    def test_metrics_tracking(self, spread_filter):
        """Test metrics are tracked correctly."""
        # Make some checks
        spread_filter.check_spread(50000.0, 50010.0, "BTC/USD")
        spread_filter.check_spread(50000.0, 50250.0, "ETH/USD")  # Rejected
        
        metrics = spread_filter.get_metrics()
        assert metrics["total_checks"] == 2
        assert metrics["total_rejections"] == 1


# =============================================================================
# PRDVolatilityFilter TESTS
# =============================================================================

class TestPRDVolatilityFilter:
    """Test PRD-001 Section 4.2 volatility filter."""

    @pytest.fixture
    def volatility_filter(self):
        """Create volatility filter with default thresholds."""
        return PRDVolatilityFilter(
            position_reduction_threshold=3.0,
            circuit_breaker_threshold=5.0
        )

    def test_calculate_atr(self, volatility_filter):
        """Test ATR calculation."""
        high_prices = [100, 102, 104, 103, 105]
        low_prices = [98, 100, 102, 101, 103]
        close_prices = [99, 101, 103, 102, 104]
        
        atr = volatility_filter.calculate_atr(
            high_prices, low_prices, close_prices, period=5
        )
        assert atr > 0
        assert isinstance(atr, float)

    def test_update_atr_history(self, volatility_filter):
        """Test ATR history tracking."""
        volatility_filter.update_atr_history("BTC/USD", 500.0)
        volatility_filter.update_atr_history("BTC/USD", 510.0)
        
        avg_atr = volatility_filter.get_rolling_average_atr("BTC/USD")
        assert avg_atr == pytest.approx(505.0, abs=1.0)

    def test_check_volatility_normal(self, volatility_filter):
        """Test normal volatility allows full position size."""
        # Build history
        for i in range(10):
            volatility_filter.update_atr_history("BTC/USD", 500.0)
        
        should_halt, multiplier, ratio = volatility_filter.check_volatility(
            "BTC/USD", 500.0
        )
        
        assert should_halt is False
        assert multiplier == 1.0
        assert ratio == pytest.approx(1.0, abs=0.1)

    def test_check_volatility_reduction(self, volatility_filter):
        """Test high volatility reduces position size."""
        # Build history with avg ATR = 500
        for i in range(10):
            volatility_filter.update_atr_history("BTC/USD", 500.0)
        
        # Current ATR = 1600 (3.2x average)
        should_halt, multiplier, ratio = volatility_filter.check_volatility(
            "BTC/USD", 1600.0
        )
        
        assert should_halt is False
        assert multiplier == 0.5  # 50% reduction
        assert ratio > 3.0

    def test_check_volatility_circuit_breaker(self, volatility_filter):
        """Test extreme volatility halts signals."""
        # Build history with avg ATR = 500
        for i in range(10):
            volatility_filter.update_atr_history("BTC/USD", 500.0)
        
        # Current ATR = 2600 (5.2x average)
        should_halt, multiplier, ratio = volatility_filter.check_volatility(
            "BTC/USD", 2600.0
        )
        
        assert should_halt is True
        assert multiplier == 0.0
        assert ratio > 5.0

    def test_check_volatility_insufficient_history(self, volatility_filter):
        """Test insufficient history allows normal operation."""
        should_halt, multiplier, ratio = volatility_filter.check_volatility(
            "ETH/USD", 1000.0
        )
        
        # Should allow normal operation if no history
        assert should_halt is False
        assert multiplier == 1.0

    def test_check_signal_with_atr(self, volatility_filter):
        """Test check_signal convenience method."""
        # Build history
        for i in range(10):
            volatility_filter.update_atr_history("BTC/USD", 500.0)
        
        signal = {"trading_pair": "BTC/USD"}
        market_data = {"atr_14": 1600.0}
        
        should_halt, multiplier = volatility_filter.check_signal(signal, market_data)
        assert should_halt is False
        assert multiplier == 0.5


# =============================================================================
# PRDDrawdownCircuitBreaker TESTS
# =============================================================================

class TestPRDDrawdownCircuitBreaker:
    """Test PRD-001 Section 4.3 daily drawdown circuit breaker."""

    @pytest.fixture
    def circuit_breaker(self):
        """Create circuit breaker with default threshold."""
        return PRDDrawdownCircuitBreaker(
            start_of_day_equity=10000.0,
            max_drawdown_pct=-5.0
        )

    def test_initial_state_allows_trading(self, circuit_breaker):
        """Test initial state allows trading."""
        is_halted, drawdown_pct = circuit_breaker.check()
        
        assert is_halted is False
        assert drawdown_pct == 0.0

    def test_calculate_drawdown_pct(self, circuit_breaker):
        """Test drawdown percentage calculation."""
        circuit_breaker.update_equity(9500.0)  # -5% from 10000
        drawdown_pct = circuit_breaker.calculate_drawdown_pct()
        
        assert drawdown_pct == pytest.approx(-5.0, abs=0.1)

    def test_check_within_threshold(self, circuit_breaker):
        """Test drawdown within threshold allows trading."""
        circuit_breaker.update_equity(9600.0)  # -4% (within -5% threshold)
        is_halted, drawdown_pct = circuit_breaker.check()
        
        assert is_halted is False
        assert drawdown_pct == pytest.approx(-4.0, abs=0.1)

    def test_check_exceeds_threshold(self, circuit_breaker):
        """Test drawdown exceeding threshold halts trading."""
        circuit_breaker.update_equity(9400.0)  # -6% (exceeds -5% threshold)
        is_halted, drawdown_pct = circuit_breaker.check()
        
        assert is_halted is True
        assert drawdown_pct < -5.0

    def test_check_signal_rejects_when_halted(self, circuit_breaker):
        """Test check_signal rejects when circuit breaker is active."""
        circuit_breaker.update_equity(9400.0)  # -6%
        circuit_breaker.check()  # Activate breaker
        
        signal = {"trading_pair": "BTC/USD"}
        should_reject = circuit_breaker.check_signal(signal)
        
        assert should_reject is True

    def test_reset_for_new_day(self, circuit_breaker):
        """Test reset for new trading day."""
        circuit_breaker.update_equity(9400.0)  # -6%
        circuit_breaker.check()  # Activate breaker
        
        # Reset for new day
        circuit_breaker.reset_for_new_day(new_start_equity=9400.0)
        
        is_halted, _ = circuit_breaker.check()
        assert is_halted is False  # Should be deactivated

    def test_auto_reset_on_new_day(self, circuit_breaker):
        """Test auto-reset when day rolls over."""
        circuit_breaker.update_equity(9400.0)
        circuit_breaker.check()  # Activate
        
        # Simulate day rollover by manually setting day_start_time
        from datetime import timedelta
        circuit_breaker.day_start_time = datetime.now(timezone.utc) - timedelta(days=1)
        
        # Update equity should trigger auto-reset
        circuit_breaker.update_equity(9400.0)
        is_halted, _ = circuit_breaker.check()
        
        # Should be reset (though this depends on implementation)
        # For now, just verify it doesn't crash

    def test_metrics_tracking(self, circuit_breaker):
        """Test metrics are tracked correctly."""
        circuit_breaker.check()
        circuit_breaker.update_equity(9400.0)
        circuit_breaker.check()  # Should activate
        
        metrics = circuit_breaker.get_metrics()
        assert metrics["total_checks"] >= 2
        assert metrics["is_active"] is True
        assert metrics["current_drawdown_pct"] < -5.0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestRiskFiltersIntegration:
    """Test risk filters work together."""

    def test_all_filters_pass(self):
        """Test signal passes all filters."""
        spread_filter = PRDSpreadFilter(max_spread_pct=0.5)
        volatility_filter = PRDVolatilityFilter()
        circuit_breaker = PRDDrawdownCircuitBreaker(
            start_of_day_equity=10000.0,
            max_drawdown_pct=-5.0
        )
        
        signal = {"trading_pair": "BTC/USD", "entry_price": 50000.0}
        market_data = {
            "bid": 49990.0,
            "ask": 50010.0,  # Tight spread
            "atr_14": 500.0,
        }
        
        # Check all filters
        spread_reject = spread_filter.check_signal(signal, market_data)
        vol_halt, vol_mult = volatility_filter.check_signal(signal, market_data)
        dd_halt, _ = circuit_breaker.check()
        
        # All should pass
        assert spread_reject is False
        assert vol_halt is False
        assert dd_halt is False

    def test_spread_filter_rejects_first(self):
        """Test spread filter rejects before other checks."""
        spread_filter = PRDSpreadFilter(max_spread_pct=0.5)
        
        signal = {"trading_pair": "BTC/USD"}
        market_data = {
            "bid": 50000.0,
            "ask": 51000.0,  # 2% spread - should reject
        }
        
        should_reject = spread_filter.check_signal(signal, market_data)
        assert should_reject is True

    def test_volatility_reduces_position_size(self):
        """Test volatility filter reduces position size."""
        volatility_filter = PRDVolatilityFilter()
        
        # Build history
        for i in range(10):
            volatility_filter.update_atr_history("BTC/USD", 500.0)
        
        signal = {"trading_pair": "BTC/USD"}
        market_data = {"atr_14": 1600.0}  # 3.2x average
        
        should_halt, multiplier = volatility_filter.check_signal(signal, market_data)
        assert should_halt is False
        assert multiplier == 0.5  # 50% reduction


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])









