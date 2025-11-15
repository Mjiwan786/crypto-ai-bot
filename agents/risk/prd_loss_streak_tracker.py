"""
PRD-001 Compliant Loss Streak Tracker (Section 4.5)

This module implements PRD-001 Section 4.5 loss streak management with:
- Track consecutive losses per strategy
- Increment loss count on losing trade, reset to 0 on winning trade
- After 3 consecutive losses, reduce strategy allocation by 50%
- After 5 consecutive losses, pause strategy and require manual review
- WARNING level logging (3 losses) and CRITICAL level logging (5 losses)
- Prometheus gauge strategy_loss_streak{strategy} for current loss count
- Store loss streak state in Redis: state:loss_streak:{strategy} with 7-day TTL

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional
from datetime import timedelta

# PRD-001 Section 4.5: Prometheus metrics
try:
    from prometheus_client import Gauge
    STRATEGY_LOSS_STREAK = Gauge(
        'strategy_loss_streak',
        'Current consecutive loss streak by strategy',
        ['strategy']
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    STRATEGY_LOSS_STREAK = None

logger = logging.getLogger(__name__)


class LossStreakTracker:
    """
    PRD-001 Section 4.5 compliant loss streak tracker.

    Features:
    - Track consecutive losses per strategy
    - Allocation reduction at 3 losses (50%)
    - Strategy pause at 5 losses
    - WARNING and CRITICAL level logging
    - Prometheus gauge
    - Redis persistence with 7-day TTL

    Usage:
        tracker = LossStreakTracker(redis_client=redis_client)

        # Record trade result
        tracker.record_trade(strategy="scalper", is_win=False)

        # Check allocation
        allocation_multiplier = tracker.get_allocation_multiplier("scalper")
        # Returns: 1.0 (normal), 0.5 (3+ losses), or 0.0 (5+ losses, paused)

        # Check if strategy is paused
        is_paused = tracker.is_strategy_paused("scalper")
    """

    def __init__(
        self,
        redis_client=None,
        warning_threshold: int = 3,
        critical_threshold: int = 5,
        ttl_days: int = 7
    ):
        """
        Initialize PRD-compliant loss streak tracker.

        Args:
            redis_client: Redis client for state persistence (optional)
            warning_threshold: Loss count to trigger allocation reduction (default 3 per PRD)
            critical_threshold: Loss count to pause strategy (default 5 per PRD)
            ttl_days: Redis state TTL in days (default 7 per PRD)
        """
        self.redis_client = redis_client

        # PRD-001 Section 4.5: Thresholds
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.ttl_days = ttl_days
        self.ttl_seconds = ttl_days * 24 * 60 * 60

        # In-memory loss streaks (strategy -> loss_count)
        self.loss_streaks: Dict[str, int] = {}

        # Paused strategies (strategy -> True/False)
        self.paused_strategies: Dict[str, bool] = {}

        # Load state from Redis if available
        if self.redis_client:
            self._load_from_redis()

        logger.info(
            f"LossStreakTracker initialized: "
            f"warning_threshold={warning_threshold}, "
            f"critical_threshold={critical_threshold}, "
            f"ttl={ttl_days}d"
        )

    def _get_redis_key(self, strategy: str) -> str:
        """
        Get Redis key for strategy loss streak.

        PRD-001 Section 4.5: state:loss_streak:{strategy}

        Args:
            strategy: Strategy name

        Returns:
            Redis key string
        """
        return f"state:loss_streak:{strategy}"

    def _load_from_redis(self):
        """
        Load loss streak state from Redis.
        """
        if not self.redis_client:
            return

        try:
            # Get all loss streak keys
            keys = self.redis_client.keys("state:loss_streak:*")

            for key in keys:
                # Extract strategy name
                strategy = key.split(":")[-1]

                # Get loss count
                loss_count_str = self.redis_client.get(key)
                if loss_count_str:
                    loss_count = int(loss_count_str)
                    self.loss_streaks[strategy] = loss_count

                    # Update Prometheus
                    if PROMETHEUS_AVAILABLE and STRATEGY_LOSS_STREAK:
                        STRATEGY_LOSS_STREAK.labels(strategy=strategy).set(loss_count)

                    # Check if paused
                    if loss_count >= self.critical_threshold:
                        self.paused_strategies[strategy] = True

            logger.info(f"Loaded {len(self.loss_streaks)} loss streaks from Redis")

        except Exception as e:
            logger.error(f"Failed to load loss streaks from Redis: {e}")

    def _save_to_redis(self, strategy: str, loss_count: int):
        """
        PRD-001 Section 4.5: Save loss streak to Redis with 7-day TTL.

        Args:
            strategy: Strategy name
            loss_count: Current loss count
        """
        if not self.redis_client:
            return

        try:
            key = self._get_redis_key(strategy)

            if loss_count > 0:
                # Save with TTL
                self.redis_client.setex(key, self.ttl_seconds, str(loss_count))
            else:
                # Delete key if loss count is 0 (reset)
                self.redis_client.delete(key)

        except Exception as e:
            logger.error(f"Failed to save loss streak to Redis: {e}")

    def get_loss_count(self, strategy: str) -> int:
        """
        Get current loss streak count for a strategy.

        Args:
            strategy: Strategy name

        Returns:
            Current consecutive loss count
        """
        return self.loss_streaks.get(strategy, 0)

    def record_trade(self, strategy: str, is_win: bool):
        """
        PRD-001 Section 4.5: Record trade result and update loss streak.

        Steps:
        1. If win: reset loss count to 0
        2. If loss: increment loss count
        3. Check thresholds and log warnings
        4. Update Prometheus gauge
        5. Save to Redis

        Args:
            strategy: Strategy name
            is_win: True if trade was profitable, False if loss
        """
        current_loss_count = self.loss_streaks.get(strategy, 0)

        if is_win:
            # PRD-001 Section 4.5: Reset to 0 on winning trade
            if current_loss_count > 0:
                logger.info(
                    f"[LOSS STREAK RESET] {strategy}: Win after {current_loss_count} losses"
                )

            self.loss_streaks[strategy] = 0
            self.paused_strategies[strategy] = False

        else:
            # PRD-001 Section 4.5: Increment loss count on losing trade
            new_loss_count = current_loss_count + 1
            self.loss_streaks[strategy] = new_loss_count

            # PRD-001 Section 4.5: Log at WARNING level (3 losses)
            if new_loss_count == self.warning_threshold:
                logger.warning(
                    f"[LOSS STREAK WARNING] {strategy}: {new_loss_count} consecutive losses - "
                    f"REDUCING ALLOCATION BY 50%"
                )

            # PRD-001 Section 4.5: Log at CRITICAL level (5 losses)
            elif new_loss_count == self.critical_threshold:
                logger.critical(
                    f"[LOSS STREAK CRITICAL] {strategy}: {new_loss_count} consecutive losses - "
                    f"PAUSING STRATEGY - MANUAL REVIEW REQUIRED"
                )
                self.paused_strategies[strategy] = True

            # Log intermediate losses
            elif new_loss_count > self.critical_threshold:
                logger.critical(
                    f"[LOSS STREAK CRITICAL] {strategy}: {new_loss_count} consecutive losses - "
                    f"STRATEGY PAUSED"
                )

            elif new_loss_count > self.warning_threshold:
                logger.warning(
                    f"[LOSS STREAK WARNING] {strategy}: {new_loss_count} consecutive losses - "
                    f"ALLOCATION REDUCED"
                )

        # PRD-001 Section 4.5: Update Prometheus gauge
        if PROMETHEUS_AVAILABLE and STRATEGY_LOSS_STREAK:
            STRATEGY_LOSS_STREAK.labels(strategy=strategy).set(
                self.loss_streaks[strategy]
            )

        # PRD-001 Section 4.5: Save to Redis with TTL
        self._save_to_redis(strategy, self.loss_streaks[strategy])

    def get_allocation_multiplier(self, strategy: str) -> float:
        """
        PRD-001 Section 4.5: Get allocation multiplier based on loss streak.

        Logic:
        - 0-2 losses: 1.0 (normal allocation)
        - 3-4 losses: 0.5 (50% allocation reduction)
        - 5+ losses: 0.0 (paused, no allocation)

        Args:
            strategy: Strategy name

        Returns:
            Allocation multiplier (0.0, 0.5, or 1.0)
        """
        loss_count = self.loss_streaks.get(strategy, 0)

        if loss_count >= self.critical_threshold:
            # PRD-001 Section 4.5: Paused at 5+ losses
            return 0.0

        elif loss_count >= self.warning_threshold:
            # PRD-001 Section 4.5: 50% reduction at 3+ losses
            return 0.5

        else:
            # Normal allocation
            return 1.0

    def is_strategy_paused(self, strategy: str) -> bool:
        """
        Check if strategy is paused due to loss streak.

        Args:
            strategy: Strategy name

        Returns:
            True if strategy is paused, False otherwise
        """
        return self.paused_strategies.get(strategy, False)

    def manually_unpause_strategy(self, strategy: str):
        """
        Manually unpause a strategy (after review).

        This resets the loss streak and removes the pause flag.

        Args:
            strategy: Strategy name
        """
        old_loss_count = self.loss_streaks.get(strategy, 0)

        self.loss_streaks[strategy] = 0
        self.paused_strategies[strategy] = False

        # Update Prometheus
        if PROMETHEUS_AVAILABLE and STRATEGY_LOSS_STREAK:
            STRATEGY_LOSS_STREAK.labels(strategy=strategy).set(0)

        # Save to Redis
        self._save_to_redis(strategy, 0)

        logger.warning(
            f"[MANUAL UNPAUSE] {strategy}: Strategy manually unpaused "
            f"(was at {old_loss_count} losses)"
        )

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get loss streak tracker metrics.

        Returns:
            Dictionary with metrics
        """
        total_strategies = len(self.loss_streaks)
        paused_count = sum(1 for paused in self.paused_strategies.values() if paused)
        reduced_count = sum(
            1 for loss_count in self.loss_streaks.values()
            if self.warning_threshold <= loss_count < self.critical_threshold
        )

        return {
            "total_strategies_tracked": total_strategies,
            "strategies_paused": paused_count,
            "strategies_reduced_allocation": reduced_count,
            "loss_streaks": dict(self.loss_streaks),
            "paused_strategies": dict(self.paused_strategies),
            "warning_threshold": self.warning_threshold,
            "critical_threshold": self.critical_threshold
        }

    def reset_all_streaks(self):
        """Reset all loss streaks (for testing/recovery)."""
        for strategy in list(self.loss_streaks.keys()):
            self.loss_streaks[strategy] = 0
            self.paused_strategies[strategy] = False

            # Update Prometheus
            if PROMETHEUS_AVAILABLE and STRATEGY_LOSS_STREAK:
                STRATEGY_LOSS_STREAK.labels(strategy=strategy).set(0)

            # Save to Redis
            self._save_to_redis(strategy, 0)

        logger.warning("All loss streaks reset")


# Export for convenience
__all__ = [
    "LossStreakTracker",
]
