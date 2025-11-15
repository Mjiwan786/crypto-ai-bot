"""
Unit tests for LossStreakTracker (PRD-001 Section 4.5)

Tests coverage:
- Tracking consecutive losses per strategy
- Increment on loss, reset on win
- Allocation reduction at 3 losses (50%)
- Strategy pause at 5 losses
- WARNING level logging (3 losses)
- CRITICAL level logging (5 losses)
- Prometheus gauge emission
- Redis storage with 7-day TTL
- Sequence of wins/losses (PRD requirement)

Author: Crypto AI Bot Team
"""

import pytest
from unittest.mock import Mock, patch
from agents.risk.prd_loss_streak_tracker import LossStreakTracker


class TestLossStreakTrackerInit:
    """Test LossStreakTracker initialization."""

    def test_init_default_params(self):
        """Test initialization with default parameters."""
        tracker = LossStreakTracker()
        assert tracker.warning_threshold == 3
        assert tracker.critical_threshold == 5
        assert tracker.ttl_days == 7
        assert tracker.ttl_seconds == 7 * 24 * 60 * 60
        assert len(tracker.loss_streaks) == 0
        assert len(tracker.paused_strategies) == 0

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        tracker = LossStreakTracker(
            warning_threshold=2,
            critical_threshold=4,
            ttl_days=14
        )
        assert tracker.warning_threshold == 2
        assert tracker.critical_threshold == 4
        assert tracker.ttl_days == 14

    def test_init_logs_info(self, caplog):
        """Test that initialization logs at INFO level."""
        import logging
        with caplog.at_level(logging.INFO):
            tracker = LossStreakTracker()

        assert "LossStreakTracker initialized" in caplog.text
        assert "warning_threshold=3" in caplog.text
        assert "critical_threshold=5" in caplog.text


class TestRecordTrade:
    """Test trade recording and loss streak tracking."""

    def test_record_first_loss(self):
        """Test recording first loss."""
        tracker = LossStreakTracker()

        tracker.record_trade(strategy="scalper", is_win=False)

        assert tracker.get_loss_count("scalper") == 1

    def test_record_consecutive_losses(self):
        """Test recording consecutive losses."""
        tracker = LossStreakTracker()

        tracker.record_trade("scalper", is_win=False)  # 1
        tracker.record_trade("scalper", is_win=False)  # 2

        assert tracker.get_loss_count("scalper") == 2

    def test_record_win_resets_streak(self, caplog):
        """Test that win resets loss streak to 0."""
        import logging
        tracker = LossStreakTracker()

        # Build up losses
        tracker.record_trade("scalper", is_win=False)  # 1
        tracker.record_trade("scalper", is_win=False)  # 2

        assert tracker.get_loss_count("scalper") == 2

        # Win should reset
        with caplog.at_level(logging.INFO):
            tracker.record_trade("scalper", is_win=True)

        assert tracker.get_loss_count("scalper") == 0
        assert "[LOSS STREAK RESET]" in caplog.text
        assert "Win after 2 losses" in caplog.text

    def test_record_warning_threshold(self, caplog):
        """Test WARNING level logging at 3 losses."""
        import logging
        tracker = LossStreakTracker()

        # 2 losses - no warning yet
        tracker.record_trade("scalper", is_win=False)
        tracker.record_trade("scalper", is_win=False)

        # 3rd loss - should trigger WARNING
        with caplog.at_level(logging.WARNING):
            tracker.record_trade("scalper", is_win=False)

        assert tracker.get_loss_count("scalper") == 3
        assert "[LOSS STREAK WARNING]" in caplog.text
        assert "3 consecutive losses" in caplog.text
        assert "REDUCING ALLOCATION BY 50%" in caplog.text

    def test_record_critical_threshold(self, caplog):
        """Test CRITICAL level logging at 5 losses."""
        import logging
        tracker = LossStreakTracker()

        # 4 losses
        for _ in range(4):
            tracker.record_trade("scalper", is_win=False)

        # 5th loss - should trigger CRITICAL
        with caplog.at_level(logging.CRITICAL):
            tracker.record_trade("scalper", is_win=False)

        assert tracker.get_loss_count("scalper") == 5
        assert "[LOSS STREAK CRITICAL]" in caplog.text
        assert "5 consecutive losses" in caplog.text
        assert "PAUSING STRATEGY" in caplog.text
        assert "MANUAL REVIEW REQUIRED" in caplog.text

    def test_record_beyond_critical(self, caplog):
        """Test logging continues beyond critical threshold."""
        import logging
        tracker = LossStreakTracker()

        # 6 losses
        for _ in range(6):
            tracker.record_trade("scalper", is_win=False)

        # 7th loss
        with caplog.at_level(logging.CRITICAL):
            tracker.record_trade("scalper", is_win=False)

        assert tracker.get_loss_count("scalper") == 7
        assert "[LOSS STREAK CRITICAL]" in caplog.text

    @patch('agents.risk.prd_loss_streak_tracker.PROMETHEUS_AVAILABLE', True)
    @patch('agents.risk.prd_loss_streak_tracker.STRATEGY_LOSS_STREAK')
    def test_record_updates_prometheus(self, mock_gauge):
        """Test that Prometheus gauge is updated."""
        tracker = LossStreakTracker()

        tracker.record_trade("scalper", is_win=False)

        mock_gauge.labels.assert_called_with(strategy="scalper")
        mock_gauge.labels.return_value.set.assert_called_with(1)


class TestGetAllocationMultiplier:
    """Test allocation multiplier calculation."""

    def test_allocation_multiplier_normal(self):
        """Test allocation multiplier with 0-2 losses (normal)."""
        tracker = LossStreakTracker()

        # 0 losses
        assert tracker.get_allocation_multiplier("scalper") == 1.0

        # 1 loss
        tracker.record_trade("scalper", is_win=False)
        assert tracker.get_allocation_multiplier("scalper") == 1.0

        # 2 losses
        tracker.record_trade("scalper", is_win=False)
        assert tracker.get_allocation_multiplier("scalper") == 1.0

    def test_allocation_multiplier_reduced(self):
        """Test allocation multiplier with 3-4 losses (50% reduction)."""
        tracker = LossStreakTracker()

        # 3 losses - should reduce to 0.5
        for _ in range(3):
            tracker.record_trade("scalper", is_win=False)

        assert tracker.get_allocation_multiplier("scalper") == 0.5

        # 4 losses - still 0.5
        tracker.record_trade("scalper", is_win=False)
        assert tracker.get_allocation_multiplier("scalper") == 0.5

    def test_allocation_multiplier_paused(self):
        """Test allocation multiplier with 5+ losses (paused)."""
        tracker = LossStreakTracker()

        # 5 losses - should pause (0.0)
        for _ in range(5):
            tracker.record_trade("scalper", is_win=False)

        assert tracker.get_allocation_multiplier("scalper") == 0.0

        # 6 losses - still 0.0
        tracker.record_trade("scalper", is_win=False)
        assert tracker.get_allocation_multiplier("scalper") == 0.0


class TestIsStrategyPaused:
    """Test strategy pause status."""

    def test_is_strategy_paused_no(self):
        """Test strategy not paused with <5 losses."""
        tracker = LossStreakTracker()

        assert tracker.is_strategy_paused("scalper") is False

        # 4 losses - not paused yet
        for _ in range(4):
            tracker.record_trade("scalper", is_win=False)

        assert tracker.is_strategy_paused("scalper") is False

    def test_is_strategy_paused_yes(self):
        """Test strategy paused with 5+ losses."""
        tracker = LossStreakTracker()

        # 5 losses - should be paused
        for _ in range(5):
            tracker.record_trade("scalper", is_win=False)

        assert tracker.is_strategy_paused("scalper") is True

    def test_is_strategy_paused_after_win(self):
        """Test strategy unpaused after win."""
        tracker = LossStreakTracker()

        # 5 losses - paused
        for _ in range(5):
            tracker.record_trade("scalper", is_win=False)

        assert tracker.is_strategy_paused("scalper") is True

        # Win - should unpause
        tracker.record_trade("scalper", is_win=True)

        assert tracker.is_strategy_paused("scalper") is False


class TestRedisIntegration:
    """Test Redis storage and persistence."""

    def test_save_to_redis_on_loss(self):
        """Test loss streak saved to Redis."""
        mock_redis = Mock()
        tracker = LossStreakTracker(redis_client=mock_redis)

        tracker.record_trade("scalper", is_win=False)

        # Should save to Redis with TTL
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "state:loss_streak:scalper"
        assert call_args[0][1] == 7 * 24 * 60 * 60  # 7 days in seconds
        assert call_args[0][2] == "1"

    def test_delete_from_redis_on_win(self):
        """Test loss streak deleted from Redis on win."""
        mock_redis = Mock()
        tracker = LossStreakTracker(redis_client=mock_redis)

        # Build up losses
        tracker.record_trade("scalper", is_win=False)
        tracker.record_trade("scalper", is_win=False)

        # Win - should delete key
        tracker.record_trade("scalper", is_win=True)

        mock_redis.delete.assert_called_with("state:loss_streak:scalper")

    def test_custom_ttl(self):
        """Test custom TTL in Redis."""
        mock_redis = Mock()
        tracker = LossStreakTracker(redis_client=mock_redis, ttl_days=14)

        tracker.record_trade("scalper", is_win=False)

        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 14 * 24 * 60 * 60  # 14 days


class TestSequenceOfWinsAndLosses:
    """
    PRD-001 Section 4.5 Requirement:
    Add loss streak unit test with sequence of wins/losses.
    """

    def test_sequence_losses_then_win(self, caplog):
        """
        Test sequence: L, L, L (warning), W (reset).
        """
        import logging
        tracker = LossStreakTracker()

        # 3 losses - should trigger warning
        tracker.record_trade("scalper", is_win=False)  # 1
        tracker.record_trade("scalper", is_win=False)  # 2

        with caplog.at_level(logging.WARNING):
            tracker.record_trade("scalper", is_win=False)  # 3

        assert tracker.get_loss_count("scalper") == 3
        assert tracker.get_allocation_multiplier("scalper") == 0.5
        assert "[LOSS STREAK WARNING]" in caplog.text

        # Win - should reset
        with caplog.at_level(logging.INFO):
            tracker.record_trade("scalper", is_win=True)

        assert tracker.get_loss_count("scalper") == 0
        assert tracker.get_allocation_multiplier("scalper") == 1.0
        assert "[LOSS STREAK RESET]" in caplog.text

    def test_sequence_to_pause_then_win(self, caplog):
        """
        Test sequence: L×5 (pause), W (unpause).
        """
        import logging
        tracker = LossStreakTracker()

        # 5 losses - should pause
        for i in range(4):
            tracker.record_trade("scalper", is_win=False)

        with caplog.at_level(logging.CRITICAL):
            tracker.record_trade("scalper", is_win=False)  # 5th

        assert tracker.get_loss_count("scalper") == 5
        assert tracker.is_strategy_paused("scalper") is True
        assert "[LOSS STREAK CRITICAL]" in caplog.text

        # Win - should unpause and reset
        tracker.record_trade("scalper", is_win=True)

        assert tracker.get_loss_count("scalper") == 0
        assert tracker.is_strategy_paused("scalper") is False

    def test_sequence_mixed_wins_losses(self):
        """
        Test sequence: L, L, W, L, L, L, W, L.
        """
        tracker = LossStreakTracker()

        tracker.record_trade("scalper", is_win=False)  # 1
        assert tracker.get_loss_count("scalper") == 1

        tracker.record_trade("scalper", is_win=False)  # 2
        assert tracker.get_loss_count("scalper") == 2

        tracker.record_trade("scalper", is_win=True)  # Reset
        assert tracker.get_loss_count("scalper") == 0

        tracker.record_trade("scalper", is_win=False)  # 1
        assert tracker.get_loss_count("scalper") == 1

        tracker.record_trade("scalper", is_win=False)  # 2
        assert tracker.get_loss_count("scalper") == 2

        tracker.record_trade("scalper", is_win=False)  # 3 - warning
        assert tracker.get_loss_count("scalper") == 3
        assert tracker.get_allocation_multiplier("scalper") == 0.5

        tracker.record_trade("scalper", is_win=True)  # Reset
        assert tracker.get_loss_count("scalper") == 0
        assert tracker.get_allocation_multiplier("scalper") == 1.0

        tracker.record_trade("scalper", is_win=False)  # 1
        assert tracker.get_loss_count("scalper") == 1

    def test_sequence_multiple_strategies(self):
        """
        Test loss tracking for multiple strategies independently.
        """
        tracker = LossStreakTracker()

        # Scalper: L, L, L
        tracker.record_trade("scalper", is_win=False)
        tracker.record_trade("scalper", is_win=False)
        tracker.record_trade("scalper", is_win=False)

        # Trend: L, L
        tracker.record_trade("trend", is_win=False)
        tracker.record_trade("trend", is_win=False)

        # Mean reversion: W
        tracker.record_trade("mean_reversion", is_win=True)

        # Check independent tracking
        assert tracker.get_loss_count("scalper") == 3
        assert tracker.get_loss_count("trend") == 2
        assert tracker.get_loss_count("mean_reversion") == 0

        assert tracker.get_allocation_multiplier("scalper") == 0.5
        assert tracker.get_allocation_multiplier("trend") == 1.0
        assert tracker.get_allocation_multiplier("mean_reversion") == 1.0

    def test_sequence_long_losing_streak(self, caplog):
        """
        Test long losing streak: L×10.
        """
        import logging
        tracker = LossStreakTracker()

        for i in range(10):
            with caplog.at_level(logging.WARNING):
                tracker.record_trade("scalper", is_win=False)

        assert tracker.get_loss_count("scalper") == 10
        assert tracker.is_strategy_paused("scalper") is True
        assert tracker.get_allocation_multiplier("scalper") == 0.0


class TestManualUnpause:
    """Test manual strategy unpause."""

    def test_manually_unpause_strategy(self, caplog):
        """Test manual unpause after review."""
        import logging
        tracker = LossStreakTracker()

        # Build up to pause
        for _ in range(5):
            tracker.record_trade("scalper", is_win=False)

        assert tracker.is_strategy_paused("scalper") is True

        # Manual unpause
        with caplog.at_level(logging.WARNING):
            tracker.manually_unpause_strategy("scalper")

        assert tracker.get_loss_count("scalper") == 0
        assert tracker.is_strategy_paused("scalper") is False
        assert tracker.get_allocation_multiplier("scalper") == 1.0
        assert "[MANUAL UNPAUSE]" in caplog.text
        assert "was at 5 losses" in caplog.text


class TestGetMetrics:
    """Test metrics retrieval."""

    def test_get_metrics_initial(self):
        """Test metrics with no trades."""
        tracker = LossStreakTracker()

        metrics = tracker.get_metrics()

        assert metrics["total_strategies_tracked"] == 0
        assert metrics["strategies_paused"] == 0
        assert metrics["strategies_reduced_allocation"] == 0
        assert metrics["warning_threshold"] == 3
        assert metrics["critical_threshold"] == 5

    def test_get_metrics_after_trades(self):
        """Test metrics after various trades."""
        tracker = LossStreakTracker()

        # Scalper: 5 losses (paused)
        for _ in range(5):
            tracker.record_trade("scalper", is_win=False)

        # Trend: 3 losses (reduced)
        for _ in range(3):
            tracker.record_trade("trend", is_win=False)

        # Mean reversion: 2 losses (normal)
        for _ in range(2):
            tracker.record_trade("mean_reversion", is_win=False)

        metrics = tracker.get_metrics()

        assert metrics["total_strategies_tracked"] == 3
        assert metrics["strategies_paused"] == 1
        assert metrics["strategies_reduced_allocation"] == 1
        assert metrics["loss_streaks"]["scalper"] == 5
        assert metrics["loss_streaks"]["trend"] == 3
        assert metrics["loss_streaks"]["mean_reversion"] == 2


class TestResetAllStreaks:
    """Test resetting all loss streaks."""

    def test_reset_all_streaks(self, caplog):
        """Test resetting all strategies."""
        import logging
        tracker = LossStreakTracker()

        # Build up multiple streaks
        for _ in range(5):
            tracker.record_trade("scalper", is_win=False)

        for _ in range(3):
            tracker.record_trade("trend", is_win=False)

        assert tracker.get_loss_count("scalper") == 5
        assert tracker.get_loss_count("trend") == 3

        # Reset all
        with caplog.at_level(logging.WARNING):
            tracker.reset_all_streaks()

        assert tracker.get_loss_count("scalper") == 0
        assert tracker.get_loss_count("trend") == 0
        assert tracker.is_strategy_paused("scalper") is False
        assert "All loss streaks reset" in caplog.text
