"""
Unit tests for PRDPositionSizer (PRD-001 Section 4.4)

Tests coverage:
- Position sizing formula: size = base_size * confidence * (avg_ATR / ATR)
- Confidence scaling (0.6 - 1.0)
- Volatility adjustment
- Max position size cap ($2,000)
- Max total exposure enforcement ($10,000)
- DEBUG level logging verification
- Various confidence and ATR scenarios (PRD requirement)

Author: Crypto AI Bot Team
"""

import pytest
from unittest.mock import Mock
from agents.risk.prd_position_sizing import PRDPositionSizer


class TestPRDPositionSizerInit:
    """Test PRDPositionSizer initialization."""

    def test_init_default_params(self):
        """Test initialization with default parameters."""
        sizer = PRDPositionSizer()
        assert sizer.base_size_usd == 100.0
        assert sizer.max_position_usd == 2000.0
        assert sizer.max_total_exposure_usd == 10000.0
        assert sizer.total_calculations == 0
        assert sizer.total_capped == 0
        assert sizer.total_rejected_exposure == 0

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        sizer = PRDPositionSizer(
            base_size_usd=200.0,
            max_position_usd=5000.0,
            max_total_exposure_usd=25000.0
        )
        assert sizer.base_size_usd == 200.0
        assert sizer.max_position_usd == 5000.0
        assert sizer.max_total_exposure_usd == 25000.0

    def test_init_logs_info(self, caplog):
        """Test that initialization logs at INFO level."""
        import logging
        with caplog.at_level(logging.INFO):
            sizer = PRDPositionSizer(
                base_size_usd=100.0,
                max_position_usd=2000.0,
                max_total_exposure_usd=10000.0
            )

        assert "PRDPositionSizer initialized" in caplog.text
        assert "base_size=$100.00" in caplog.text
        assert "max_position=$2000.00" in caplog.text
        assert "max_total_exposure=$10000.00" in caplog.text


class TestCalculateVolatilityAdjustment:
    """Test volatility adjustment calculation."""

    def test_volatility_adjustment_normal(self):
        """Test volatility adjustment with normal ATR."""
        sizer = PRDPositionSizer()

        # avg_ATR = 1000, ATR = 1000 → adjustment = 1.0 (normal)
        adjustment = sizer.calculate_volatility_adjustment(
            current_atr=1000.0,
            avg_atr=1000.0
        )

        assert abs(adjustment - 1.0) < 0.01

    def test_volatility_adjustment_high_vol(self):
        """Test volatility adjustment with high volatility."""
        sizer = PRDPositionSizer()

        # avg_ATR = 1000, ATR = 2000 (high vol) → adjustment = 0.5 (reduce size)
        adjustment = sizer.calculate_volatility_adjustment(
            current_atr=2000.0,
            avg_atr=1000.0
        )

        assert abs(adjustment - 0.5) < 0.01

    def test_volatility_adjustment_low_vol(self):
        """Test volatility adjustment with low volatility."""
        sizer = PRDPositionSizer()

        # avg_ATR = 1000, ATR = 500 (low vol) → adjustment = 2.0 (increase size)
        adjustment = sizer.calculate_volatility_adjustment(
            current_atr=500.0,
            avg_atr=1000.0
        )

        assert abs(adjustment - 2.0) < 0.01

    def test_volatility_adjustment_zero_current_atr(self, caplog):
        """Test volatility adjustment with zero current ATR."""
        import logging
        sizer = PRDPositionSizer()

        with caplog.at_level(logging.WARNING):
            adjustment = sizer.calculate_volatility_adjustment(
                current_atr=0.0,
                avg_atr=1000.0
            )

        assert adjustment == 1.0
        assert "Invalid current_atr" in caplog.text

    def test_volatility_adjustment_zero_avg_atr(self, caplog):
        """Test volatility adjustment with zero average ATR."""
        import logging
        sizer = PRDPositionSizer()

        with caplog.at_level(logging.WARNING):
            adjustment = sizer.calculate_volatility_adjustment(
                current_atr=1000.0,
                avg_atr=0.0
            )

        assert adjustment == 1.0
        assert "Invalid avg_atr" in caplog.text


class TestCalculatePositionSize:
    """Test position size calculation."""

    def test_calculate_position_size_base_only(self, caplog):
        """Test position size with base parameters only (no ATR)."""
        import logging
        sizer = PRDPositionSizer(base_size_usd=100.0)

        with caplog.at_level(logging.DEBUG):
            size = sizer.calculate_position_size(confidence=1.0)

        # base_size * confidence * vol_adjustment
        # 100 * 1.0 * 1.0 = 100
        assert abs(size - 100.0) < 0.01
        assert "[POSITION SIZING]" in caplog.text

    def test_calculate_position_size_with_confidence(self):
        """Test position size with confidence scaling."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        # Confidence = 0.75
        size = sizer.calculate_position_size(confidence=0.75)

        # 100 * 0.75 * 1.0 = 75
        assert abs(size - 75.0) < 0.01

    def test_calculate_position_size_with_high_vol(self):
        """Test position size with high volatility (reduces size)."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        # Confidence = 1.0, ATR = 2000, avg_ATR = 1000
        # vol_adjustment = 1000 / 2000 = 0.5
        size = sizer.calculate_position_size(
            confidence=1.0,
            current_atr=2000.0,
            avg_atr=1000.0
        )

        # 100 * 1.0 * 0.5 = 50
        assert abs(size - 50.0) < 0.01

    def test_calculate_position_size_with_low_vol(self):
        """Test position size with low volatility (increases size)."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        # Confidence = 1.0, ATR = 500, avg_ATR = 1000
        # vol_adjustment = 1000 / 500 = 2.0
        size = sizer.calculate_position_size(
            confidence=1.0,
            current_atr=500.0,
            avg_atr=1000.0
        )

        # 100 * 1.0 * 2.0 = 200
        assert abs(size - 200.0) < 0.01

    def test_calculate_position_size_all_factors(self):
        """Test position size with all factors combined."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        # Confidence = 0.8, ATR = 1500, avg_ATR = 1000
        # vol_adjustment = 1000 / 1500 = 0.667
        size = sizer.calculate_position_size(
            confidence=0.8,
            current_atr=1500.0,
            avg_atr=1000.0
        )

        # 100 * 0.8 * 0.667 = 53.33
        assert abs(size - 53.33) < 1.0

    def test_calculate_position_size_capped_at_max(self):
        """Test position size capped at max_position_usd."""
        sizer = PRDPositionSizer(base_size_usd=100.0, max_position_usd=2000.0)

        # Confidence = 1.0, ATR = 100, avg_ATR = 1000
        # vol_adjustment = 1000 / 100 = 10.0
        # 100 * 1.0 * 10.0 = 1000 → should be capped at 2000
        # Actually this gives 1000, let's use lower ATR
        size = sizer.calculate_position_size(
            confidence=1.0,
            current_atr=10.0,  # Very low ATR → high multiplier
            avg_atr=1000.0
        )

        # 100 * 1.0 * 100.0 = 10000 → capped at 2000
        assert size == 2000.0
        assert sizer.total_capped == 1

    def test_calculate_position_size_low_confidence_clamped(self):
        """Test that confidence below 0.6 is clamped to 0.6."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        size = sizer.calculate_position_size(confidence=0.3)

        # Confidence clamped to 0.6
        # 100 * 0.6 * 1.0 = 60
        assert abs(size - 60.0) < 0.01

    def test_calculate_position_size_high_confidence_clamped(self):
        """Test that confidence above 1.0 is clamped to 1.0."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        size = sizer.calculate_position_size(confidence=1.5)

        # Confidence clamped to 1.0
        # 100 * 1.0 * 1.0 = 100
        assert abs(size - 100.0) < 0.01

    def test_calculate_position_size_max_exposure_reached(self, caplog):
        """Test position sizing when max total exposure is reached."""
        import logging
        sizer = PRDPositionSizer(
            base_size_usd=100.0,
            max_total_exposure_usd=10000.0
        )

        with caplog.at_level(logging.WARNING):
            size = sizer.calculate_position_size(
                confidence=1.0,
                open_positions_usd=10000.0  # Already at max
            )

        assert size == 0.0
        assert sizer.total_rejected_exposure == 1
        assert "REJECTED - Max total exposure reached" in caplog.text

    def test_calculate_position_size_reduced_for_exposure(self):
        """Test position sizing reduced to fit within exposure limit."""
        sizer = PRDPositionSizer(
            base_size_usd=100.0,
            max_total_exposure_usd=10000.0
        )

        # Open positions = 9950, remaining = 50
        # Calculated size would be 100, but should be reduced to 50
        size = sizer.calculate_position_size(
            confidence=1.0,
            open_positions_usd=9950.0
        )

        assert size == 50.0


class TestVariousConfidenceAndATRScenarios:
    """
    PRD-001 Section 4.4 Requirement:
    Add position sizing unit tests with various confidence and ATR scenarios.
    """

    def test_scenario_high_confidence_low_vol(self):
        """Scenario: High confidence (0.9) + Low volatility (ATR 500, avg 1000)."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        size = sizer.calculate_position_size(
            confidence=0.9,
            current_atr=500.0,
            avg_atr=1000.0
        )

        # 100 * 0.9 * 2.0 = 180
        assert abs(size - 180.0) < 1.0

    def test_scenario_low_confidence_high_vol(self):
        """Scenario: Low confidence (0.6) + High volatility (ATR 2000, avg 1000)."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        size = sizer.calculate_position_size(
            confidence=0.6,
            current_atr=2000.0,
            avg_atr=1000.0
        )

        # 100 * 0.6 * 0.5 = 30
        assert abs(size - 30.0) < 1.0

    def test_scenario_medium_confidence_normal_vol(self):
        """Scenario: Medium confidence (0.75) + Normal volatility (ATR = avg)."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        size = sizer.calculate_position_size(
            confidence=0.75,
            current_atr=1000.0,
            avg_atr=1000.0
        )

        # 100 * 0.75 * 1.0 = 75
        assert abs(size - 75.0) < 1.0

    def test_scenario_max_confidence_extreme_low_vol(self):
        """Scenario: Max confidence (1.0) + Extreme low vol (ATR 100, avg 1000)."""
        sizer = PRDPositionSizer(base_size_usd=100.0, max_position_usd=2000.0)

        size = sizer.calculate_position_size(
            confidence=1.0,
            current_atr=100.0,
            avg_atr=1000.0
        )

        # 100 * 1.0 * 10.0 = 1000
        assert abs(size - 1000.0) < 1.0

    def test_scenario_min_confidence_extreme_high_vol(self):
        """Scenario: Min confidence (0.6) + Extreme high vol (ATR 5000, avg 1000)."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        size = sizer.calculate_position_size(
            confidence=0.6,
            current_atr=5000.0,
            avg_atr=1000.0
        )

        # 100 * 0.6 * 0.2 = 12
        assert abs(size - 12.0) < 1.0

    def test_scenario_gradient_confidence_values(self):
        """Test position sizing with gradient of confidence values."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        # Confidence 0.6, 0.7, 0.8, 0.9, 1.0
        confidences = [0.6, 0.7, 0.8, 0.9, 1.0]
        sizes = []

        for conf in confidences:
            size = sizer.calculate_position_size(confidence=conf)
            sizes.append(size)

        # Sizes should increase with confidence
        assert sizes == sorted(sizes)
        # Expected: [60, 70, 80, 90, 100]
        assert abs(sizes[0] - 60.0) < 0.1
        assert abs(sizes[4] - 100.0) < 0.1

    def test_scenario_gradient_atr_values(self):
        """Test position sizing with gradient of ATR values (increasing volatility)."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        avg_atr = 1000.0
        current_atrs = [500, 1000, 1500, 2000, 3000]  # Increasing volatility
        sizes = []

        for atr in current_atrs:
            size = sizer.calculate_position_size(
                confidence=1.0,
                current_atr=float(atr),
                avg_atr=avg_atr
            )
            sizes.append(size)

        # Sizes should decrease as volatility increases
        assert sizes == sorted(sizes, reverse=True)

    def test_scenario_multiple_positions_approaching_limit(self):
        """Scenario: Opening multiple positions approaching exposure limit."""
        sizer = PRDPositionSizer(
            base_size_usd=100.0,
            max_total_exposure_usd=1000.0
        )

        # Position 1: 0 open
        size1 = sizer.calculate_position_size(confidence=1.0, open_positions_usd=0.0)
        assert size1 == 100.0

        # Position 2: 100 open
        size2 = sizer.calculate_position_size(confidence=1.0, open_positions_usd=100.0)
        assert size2 == 100.0

        # Position 3: 900 open (only 100 remaining)
        size3 = sizer.calculate_position_size(confidence=1.0, open_positions_usd=900.0)
        assert size3 == 100.0

        # Position 4: 950 open (only 50 remaining)
        size4 = sizer.calculate_position_size(confidence=1.0, open_positions_usd=950.0)
        assert size4 == 50.0

        # Position 5: 1000 open (no room)
        size5 = sizer.calculate_position_size(confidence=1.0, open_positions_usd=1000.0)
        assert size5 == 0.0


class TestCalculatePositionSizeForSignal:
    """Test signal-based position sizing."""

    def test_calculate_for_signal_basic(self):
        """Test position sizing from signal dict."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        signal = {
            "confidence": 0.8,
            "atr_14": 1500.0,
            "avg_atr": 1000.0
        }

        size = sizer.calculate_position_size_for_signal(signal)

        # 100 * 0.8 * 0.667 ≈ 53
        assert abs(size - 53.33) < 2.0

    def test_calculate_for_signal_with_open_positions(self):
        """Test position sizing with open positions."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        signal = {"confidence": 1.0}
        open_positions = [
            {"size_usd": 100.0},
            {"size_usd": 200.0}
        ]

        size = sizer.calculate_position_size_for_signal(
            signal,
            open_positions=open_positions
        )

        # Should account for 300 total open
        assert size == 100.0

    def test_calculate_for_signal_no_confidence(self):
        """Test position sizing when signal missing confidence."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        signal = {}  # No confidence field

        size = sizer.calculate_position_size_for_signal(signal)

        # Should default to 0.6
        # 100 * 0.6 = 60
        assert abs(size - 60.0) < 0.1


class TestCanOpenNewPosition:
    """Test exposure limit checking."""

    def test_can_open_new_position_yes(self):
        """Test can open when sufficient exposure available."""
        sizer = PRDPositionSizer(max_total_exposure_usd=10000.0)

        can_open = sizer.can_open_new_position(open_positions_usd=5000.0)

        assert can_open is True

    def test_can_open_new_position_no(self):
        """Test cannot open when at exposure limit."""
        sizer = PRDPositionSizer(max_total_exposure_usd=10000.0)

        can_open = sizer.can_open_new_position(open_positions_usd=10000.0)

        assert can_open is False

    def test_can_open_new_position_barely_yes(self):
        """Test can open when barely enough room."""
        sizer = PRDPositionSizer(max_total_exposure_usd=10000.0)

        # 10 remaining, min_position_size = 10 → can open
        can_open = sizer.can_open_new_position(
            open_positions_usd=9990.0,
            min_position_size=10.0
        )

        assert can_open is True

    def test_can_open_new_position_barely_no(self):
        """Test cannot open when not quite enough room."""
        sizer = PRDPositionSizer(max_total_exposure_usd=10000.0)

        # 9 remaining, min_position_size = 10 → cannot open
        can_open = sizer.can_open_new_position(
            open_positions_usd=9991.0,
            min_position_size=10.0
        )

        assert can_open is False


class TestGetMetrics:
    """Test metrics retrieval."""

    def test_get_metrics_initial(self):
        """Test metrics with no calculations."""
        sizer = PRDPositionSizer(base_size_usd=100.0)

        metrics = sizer.get_metrics()

        assert metrics["total_calculations"] == 0
        assert metrics["total_capped"] == 0
        assert metrics["total_rejected_exposure"] == 0
        assert metrics["capped_rate"] == 0.0
        assert metrics["rejection_rate"] == 0.0
        assert metrics["base_size_usd"] == 100.0

    def test_get_metrics_after_calculations(self):
        """Test metrics after some calculations."""
        sizer = PRDPositionSizer(base_size_usd=100.0, max_position_usd=150.0)

        # 3 calculations, 1 capped, 1 rejected
        sizer.calculate_position_size(confidence=1.0)  # Normal
        sizer.calculate_position_size(confidence=1.0, current_atr=10.0, avg_atr=1000.0)  # Capped
        sizer.calculate_position_size(confidence=1.0, open_positions_usd=10000.0)  # Rejected

        metrics = sizer.get_metrics()

        assert metrics["total_calculations"] == 3
        assert metrics["total_capped"] == 1
        assert metrics["total_rejected_exposure"] == 1
        assert abs(metrics["capped_rate"] - 0.333) < 0.01
        assert abs(metrics["rejection_rate"] - 0.333) < 0.01


class TestResetStats:
    """Test statistics reset."""

    def test_reset_stats(self, caplog):
        """Test statistics reset."""
        import logging
        sizer = PRDPositionSizer(base_size_usd=100.0)

        # Make some calculations
        sizer.calculate_position_size(confidence=1.0)
        sizer.calculate_position_size(confidence=0.8)

        assert sizer.total_calculations == 2

        # Reset
        with caplog.at_level(logging.INFO):
            sizer.reset_stats()

        assert sizer.total_calculations == 0
        assert sizer.total_capped == 0
        assert sizer.total_rejected_exposure == 0
        assert "Position sizer statistics reset" in caplog.text
