"""
Unit Tests for analysis.metrics_summary module.

Tests metrics calculations against known inputs to ensure correctness.

Usage:
    pytest tests/unit/test_metrics_summary.py -v
    python -m pytest tests/unit/test_metrics_summary.py -v

Author: Crypto AI Bot Team
Date: 2025-12-03
"""

import pytest
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Import the module under test
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from analysis.metrics_summary import (
    MetricsSummaryCalculator,
    SignalFrequencyMetrics,
    PerformanceMetrics,
    SummaryMetrics,
    TradingAssumptions,
    CANONICAL_PAIRS,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def trading_assumptions():
    """Default trading assumptions for tests."""
    return TradingAssumptions()


@pytest.fixture
def sample_equity_curve():
    """Generate a sample equity curve for testing."""
    base_ts = datetime.now(timezone.utc).timestamp()
    curve = []
    equity = 10000.0

    # Simulate 30 days of trading
    for i in range(30):
        # Random-ish daily returns
        if i % 3 == 0:
            equity *= 1.02  # Win
        elif i % 5 == 0:
            equity *= 0.98  # Loss
        else:
            equity *= 1.005  # Small gain

        curve.append({
            "timestamp": base_ts - (30 - i) * 86400,
            "equity": equity,
            "realized_pnl": equity - 10000.0,
            "unrealized_pnl": 0.0,
        })

    return curve


@pytest.fixture
def sample_pnl_summary():
    """Sample PnL summary for testing."""
    return {
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        "initial_balance": 10000.0,
        "realized_pnl": 2500.0,
        "unrealized_pnl": 100.0,
        "total_pnl": 2600.0,
        "equity": 12600.0,
        "positions": {},
        "num_trades": 50,
        "num_wins": 30,
        "num_losses": 20,
        "win_rate": 0.60,
        "mode": "paper",
    }


# =============================================================================
# TEST: TradingAssumptions
# =============================================================================

class TestTradingAssumptions:
    """Tests for TradingAssumptions dataclass."""

    def test_default_values(self, trading_assumptions):
        """Test default trading assumptions match PRD-001."""
        assert trading_assumptions.slippage_pct == 0.1
        assert trading_assumptions.maker_fee_pct == 0.075
        assert trading_assumptions.taker_fee_pct == 0.15
        assert trading_assumptions.initial_capital == 10000.0
        assert trading_assumptions.risk_free_rate == 0.05
        assert trading_assumptions.trading_days_per_year == 365

    def test_frozen(self, trading_assumptions):
        """Test that assumptions are immutable."""
        with pytest.raises(Exception):  # FrozenInstanceError
            trading_assumptions.slippage_pct = 0.2


# =============================================================================
# TEST: SignalFrequencyMetrics
# =============================================================================

class TestSignalFrequencyMetrics:
    """Tests for SignalFrequencyMetrics dataclass."""

    def test_default_values(self):
        """Test default signal frequency values."""
        metrics = SignalFrequencyMetrics(pair="BTC/USD")
        assert metrics.pair == "BTC/USD"
        assert metrics.signals_today == 0
        assert metrics.signals_7d == 0
        assert metrics.signals_30d == 0
        assert metrics.avg_signals_per_day == 0.0

    def test_to_dict(self):
        """Test serialization to dictionary."""
        metrics = SignalFrequencyMetrics(
            pair="BTC/USD",
            signals_today=10,
            signals_7d=70,
            signals_30d=300,
            avg_signals_per_day=10.0,
        )
        result = metrics.to_dict()

        assert isinstance(result, dict)
        assert result["pair"] == "BTC/USD"
        assert result["signals_today"] == 10
        assert result["avg_signals_per_day"] == 10.0


# =============================================================================
# TEST: PerformanceMetrics
# =============================================================================

class TestPerformanceMetrics:
    """Tests for PerformanceMetrics dataclass."""

    def test_default_values(self):
        """Test default performance metrics."""
        metrics = PerformanceMetrics(period_days=30, period_label="30d")
        assert metrics.period_days == 30
        assert metrics.total_return_pct == 0.0
        assert metrics.win_rate_pct == 0.0
        assert metrics.sharpe_ratio == 0.0

    def test_to_dict(self):
        """Test serialization to dictionary."""
        metrics = PerformanceMetrics(
            period_days=30,
            period_label="30d",
            total_return_pct=15.5,
            win_rate_pct=60.0,
            profit_factor=1.52,
        )
        result = metrics.to_dict()

        assert isinstance(result, dict)
        assert result["period_label"] == "30d"
        assert result["total_return_pct"] == 15.5
        assert result["profit_factor"] == 1.52


# =============================================================================
# TEST: MetricsSummaryCalculator - Calculations
# =============================================================================

class TestMetricsSummaryCalculatorCalculations:
    """Tests for metric calculation methods."""

    @pytest.fixture
    def calculator(self):
        """Create a calculator instance for testing."""
        return MetricsSummaryCalculator(
            redis_url="redis://localhost:6379",
            mode="paper",
        )

    def test_calculate_max_drawdown_empty(self, calculator):
        """Test max drawdown with empty equity curve."""
        result = calculator.calculate_max_drawdown([])
        assert result == 0.0

    def test_calculate_max_drawdown_no_drawdown(self, calculator):
        """Test max drawdown with only gains."""
        curve = [
            {"equity": 10000.0},
            {"equity": 10500.0},
            {"equity": 11000.0},
            {"equity": 11500.0},
        ]
        result = calculator.calculate_max_drawdown(curve)
        assert result == 0.0

    def test_calculate_max_drawdown_simple(self, calculator):
        """Test max drawdown with known values."""
        curve = [
            {"equity": 10000.0},
            {"equity": 11000.0},  # Peak
            {"equity": 9900.0},   # Trough: (11000-9900)/11000 = 10%
            {"equity": 10500.0},
        ]
        result = calculator.calculate_max_drawdown(curve)
        assert result == 10.0

    def test_calculate_max_drawdown_multiple_drawdowns(self, calculator):
        """Test max drawdown selects the largest."""
        curve = [
            {"equity": 10000.0},
            {"equity": 11000.0},  # Peak 1
            {"equity": 10450.0},  # 5% dd
            {"equity": 12000.0},  # Peak 2
            {"equity": 10800.0},  # 10% dd (largest)
            {"equity": 11500.0},
        ]
        result = calculator.calculate_max_drawdown(curve)
        assert result == 10.0

    def test_calculate_sharpe_ratio_empty(self, calculator):
        """Test Sharpe ratio with empty curve."""
        result = calculator.calculate_sharpe_ratio([])
        assert result == 0.0

    def test_calculate_sharpe_ratio_single_point(self, calculator):
        """Test Sharpe ratio with single point."""
        curve = [{"equity": 10000.0}]
        result = calculator.calculate_sharpe_ratio(curve)
        assert result == 0.0

    def test_calculate_sharpe_ratio_positive_returns(self, calculator):
        """Test Sharpe ratio with positive returns."""
        # 10 days of 1% daily returns
        base_equity = 10000.0
        curve = []
        for i in range(10):
            equity = base_equity * (1.01 ** i)
            curve.append({"equity": equity})

        result = calculator.calculate_sharpe_ratio(curve)
        # With 1% daily return, annualized is ~365%
        # Should be positive and significant
        assert result > 0

    def test_calculate_cagr_zero_days(self, calculator):
        """Test CAGR with zero days."""
        result = calculator.calculate_cagr(10000.0, 12000.0, 0)
        assert result == 0.0

    def test_calculate_cagr_zero_starting(self, calculator):
        """Test CAGR with zero starting equity."""
        result = calculator.calculate_cagr(0.0, 12000.0, 365)
        assert result == 0.0

    def test_calculate_cagr_one_year_20_percent(self, calculator):
        """Test CAGR for 20% return over 1 year."""
        result = calculator.calculate_cagr(10000.0, 12000.0, 365)
        assert result == 20.0

    def test_calculate_cagr_one_year_100_percent(self, calculator):
        """Test CAGR for 100% return over 1 year."""
        result = calculator.calculate_cagr(10000.0, 20000.0, 365)
        assert result == 100.0

    def test_calculate_cagr_half_year(self, calculator):
        """Test CAGR for 50% return over 6 months."""
        # If we gain 50% in 6 months, CAGR = (1.5^2 - 1) * 100 = 125%
        result = calculator.calculate_cagr(10000.0, 15000.0, 182)
        # 182 days = ~0.5 years
        # CAGR = (15000/10000)^(1/0.5) - 1 = 2.25 - 1 = 1.25 = 125%
        assert 120 < result < 130  # Allow some rounding


# =============================================================================
# TEST: SummaryMetrics
# =============================================================================

class TestSummaryMetrics:
    """Tests for SummaryMetrics dataclass."""

    def test_default_values(self):
        """Test default summary metrics."""
        summary = SummaryMetrics(mode="paper", timestamp="2025-12-03T12:00:00Z")
        assert summary.mode == "paper"
        assert summary.signals_per_day == 0.0
        assert summary.roi_30d == 0.0
        assert summary.trading_pairs == []

    def test_to_json(self):
        """Test JSON serialization."""
        summary = SummaryMetrics(
            mode="paper",
            timestamp="2025-12-03T12:00:00Z",
            signals_per_day=100.5,
            roi_30d=25.0,
            trading_pairs=["BTC/USD", "ETH/USD"],
        )
        json_str = summary.to_json()

        assert isinstance(json_str, str)
        assert "paper" in json_str
        assert "100.5" in json_str
        assert "BTC/USD" in json_str


# =============================================================================
# TEST: Constants
# =============================================================================

class TestConstants:
    """Tests for module constants."""

    def test_canonical_pairs(self):
        """Test canonical pairs match PRD-001."""
        expected = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
        assert CANONICAL_PAIRS == expected

    def test_canonical_pairs_count(self):
        """Test exactly 5 canonical pairs."""
        assert len(CANONICAL_PAIRS) == 5


# =============================================================================
# TEST: Integration with Mock Redis
# =============================================================================

class TestMetricsSummaryCalculatorIntegration:
    """Integration tests with mocked Redis."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = AsyncMock()
        mock.ping = AsyncMock(return_value=True)
        mock.xrange = AsyncMock(return_value=[])
        mock.xrevrange = AsyncMock(return_value=[])
        mock.get = AsyncMock(return_value=None)
        mock.hset = AsyncMock(return_value=True)
        mock.expire = AsyncMock(return_value=True)
        mock.aclose = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_connect_success(self, mock_redis):
        """Test successful Redis connection."""
        calculator = MetricsSummaryCalculator(
            redis_url="redis://localhost:6379",
            mode="paper",
        )

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            result = await calculator.connect()
            assert result is True
            assert calculator.redis_client is not None

    @pytest.mark.asyncio
    async def test_count_signals_no_connection(self):
        """Test signal counting without connection."""
        calculator = MetricsSummaryCalculator(
            redis_url="redis://localhost:6379",
            mode="paper",
        )
        result = await calculator.count_signals_in_range("BTC/USD", 0, 1000)
        assert result == 0

    @pytest.mark.asyncio
    async def test_count_signals_with_mock(self, mock_redis):
        """Test signal counting with mock data."""
        # Mock 5 signals
        mock_redis.xrange = AsyncMock(return_value=[
            (b"1-0", {}), (b"2-0", {}), (b"3-0", {}),
            (b"4-0", {}), (b"5-0", {}),
        ])

        calculator = MetricsSummaryCalculator(
            redis_url="redis://localhost:6379",
            mode="paper",
        )
        calculator.redis_client = mock_redis

        result = await calculator.count_signals_in_range("BTC/USD", 0, 1000)
        assert result == 5

    @pytest.mark.asyncio
    async def test_calculate_signal_frequency(self, mock_redis):
        """Test signal frequency calculation."""
        mock_redis.xrange = AsyncMock(return_value=[
            (b"1-0", {}), (b"2-0", {}), (b"3-0", {}),
        ])
        mock_redis.xrevrange = AsyncMock(return_value=[
            (b"1733234567890-0", {b"ts": b"1733234567890"}),
        ])

        calculator = MetricsSummaryCalculator(
            redis_url="redis://localhost:6379",
            mode="paper",
        )
        calculator.redis_client = mock_redis

        result = await calculator.calculate_signal_frequency_for_pair("BTC/USD")

        assert result.pair == "BTC/USD"
        assert result.signals_today == 3
        assert result.signals_7d == 3
        assert result.last_signal_ts is not None

    @pytest.mark.asyncio
    async def test_publish_to_redis(self, mock_redis):
        """Test publishing summary to Redis."""
        calculator = MetricsSummaryCalculator(
            redis_url="redis://localhost:6379",
            mode="paper",
        )
        calculator.redis_client = mock_redis

        summary = SummaryMetrics(
            mode="paper",
            timestamp="2025-12-03T12:00:00Z",
            signals_per_day=100.0,
            roi_30d=25.0,
        )

        result = await calculator.publish_to_redis(summary)

        assert result is True
        mock_redis.hset.assert_called_once()
        mock_redis.expire.assert_called_once()


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def calculator(self):
        return MetricsSummaryCalculator(
            redis_url="redis://localhost:6379",
            mode="paper",
        )

    def test_max_drawdown_with_zero_equity(self, calculator):
        """Test max drawdown with zero equity values."""
        curve = [
            {"equity": 0.0},
            {"equity": 10000.0},
            {"equity": 9000.0},
        ]
        result = calculator.calculate_max_drawdown(curve)
        # Should handle division by zero gracefully
        assert result == 10.0

    def test_sharpe_ratio_zero_volatility(self, calculator):
        """Test Sharpe ratio with zero volatility (constant returns)."""
        curve = [
            {"equity": 10000.0},
            {"equity": 10000.0},
            {"equity": 10000.0},
        ]
        result = calculator.calculate_sharpe_ratio(curve)
        # With zero volatility, should return 0 or handle gracefully
        assert isinstance(result, float)

    def test_cagr_negative_return(self, calculator):
        """Test CAGR with negative return."""
        result = calculator.calculate_cagr(10000.0, 8000.0, 365)
        assert result == -20.0

    def test_win_rate_calculation(self):
        """Test win rate calculation from PnL summary."""
        # 30 wins out of 50 trades = 60%
        pnl_summary = {
            "num_trades": 50,
            "num_wins": 30,
            "num_losses": 20,
            "win_rate": 0.60,
        }
        win_rate_pct = pnl_summary["win_rate"] * 100
        assert win_rate_pct == 60.0


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
