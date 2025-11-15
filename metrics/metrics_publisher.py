"""
Metrics Publisher

Integrates with existing trading system to calculate and publish
real-time performance metrics at regular intervals.

Publishes to:
- Redis streams (for signals-api SSE)
- Prometheus /metrics endpoint

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import logging
import threading
from typing import Dict, List, Optional

from metrics.performance_metrics import PerformanceMetricsCalculator


class MetricsPublisher:
    """
    Publishes real-time performance metrics at regular intervals.

    Integrates with trading system to fetch trades and equity data.
    """

    def __init__(
        self,
        redis_manager=None,
        trade_manager=None,
        equity_tracker=None,
        logger=None,
        update_interval: int = 30,
    ):
        """
        Initialize metrics publisher.

        Args:
            redis_manager: Redis manager for publishing
            trade_manager: Trade manager to fetch closed trades
            equity_tracker: Equity tracker to get current equity
            logger: Logger instance
            update_interval: Update interval in seconds (default: 30)
        """
        self.redis = redis_manager
        self.trade_manager = trade_manager
        self.equity_tracker = equity_tracker
        self.logger = logger or logging.getLogger(__name__)
        self.update_interval = update_interval

        # Feature flag
        self.enabled = os.getenv("ENABLE_PERFORMANCE_METRICS", "true").lower() == "true"

        # Configuration from environment
        starting_equity = float(os.getenv("STARTING_EQUITY_USD", "10000"))
        target_equity = float(os.getenv("TARGET_EQUITY_USD", "20000"))

        # Create calculator
        self.calculator = PerformanceMetricsCalculator(
            redis_manager=redis_manager,
            logger=logger,
            starting_equity=starting_equity,
            target_equity=target_equity,
        )

        # Background thread
        self.running = False
        self.thread: Optional[threading.Thread] = None

        if self.enabled:
            self.logger.info(
                f"MetricsPublisher initialized: "
                f"update_interval={update_interval}s"
            )
        else:
            self.logger.info("MetricsPublisher disabled (ENABLE_PERFORMANCE_METRICS=false)")

    def start(self):
        """Start background metrics publishing."""
        if not self.enabled:
            self.logger.info("Metrics publisher not enabled")
            return

        if self.running:
            self.logger.warning("Metrics publisher already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.logger.info("Metrics publisher started")

    def stop(self):
        """Stop background metrics publishing."""
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.logger.info("Metrics publisher stopped")

    def _run_loop(self):
        """Background loop to publish metrics."""
        while self.running:
            try:
                self.update_and_publish()
            except Exception as e:
                self.logger.error(f"Error in metrics publishing loop: {e}", exc_info=True)

            # Sleep in small intervals to allow quick shutdown
            for _ in range(self.update_interval):
                if not self.running:
                    break
                time.sleep(1)

    def update_and_publish(self) -> Optional[Dict]:
        """
        Fetch latest data and publish metrics.

        Returns:
            Metrics summary dict or None
        """
        if not self.enabled:
            return None

        try:
            # Fetch closed trades
            trades = self._get_closed_trades()

            # Get current equity
            current_equity = self._get_current_equity()

            # Calculate metrics
            metrics = self.calculator.calculate_metrics(trades, current_equity)

            if metrics:
                return self.calculator.get_metrics_summary()

            return None

        except Exception as e:
            self.logger.error(f"Error updating metrics: {e}", exc_info=True)
            return None

    def _get_closed_trades(self) -> List[Dict]:
        """
        Get closed trades from trade manager.

        Returns:
            List of closed trades with PnL
        """
        if not self.trade_manager:
            # Fallback: try to load from Redis
            return self._get_trades_from_redis()

        try:
            # Get closed trades from trade manager
            closed_trades = self.trade_manager.get_closed_trades()

            # Convert to dict format
            trades = []
            for trade in closed_trades:
                if hasattr(trade, "to_dict"):
                    trade_dict = trade.to_dict()
                elif isinstance(trade, dict):
                    trade_dict = trade
                else:
                    continue

                # Ensure has required fields
                if "pnl_usd" in trade_dict:
                    trades.append(trade_dict)

            return trades

        except Exception as e:
            self.logger.error(f"Error getting trades from manager: {e}")
            return []

    def _get_trades_from_redis(self) -> List[Dict]:
        """Fallback: Get closed trades from Redis."""
        if not self.redis:
            return []

        try:
            # Try to read from trades stream
            events = self.redis.read_stream("trades:closed", count=1000)

            trades = []
            for event in events:
                if "pnl_usd" in event:
                    trades.append(event)

            return trades

        except Exception as e:
            self.logger.error(f"Error reading trades from Redis: {e}")
            return []

    def _get_current_equity(self) -> float:
        """
        Get current equity from equity tracker.

        Returns:
            Current equity in USD
        """
        if self.equity_tracker:
            try:
                return self.equity_tracker.get_current_equity()
            except Exception as e:
                self.logger.error(f"Error getting equity from tracker: {e}")

        # Fallback: calculate from trades
        trades = self._get_closed_trades()
        if trades:
            starting_equity = float(os.getenv("STARTING_EQUITY_USD", "10000"))
            total_pnl = sum(t.get("pnl_usd", 0) for t in trades)
            return starting_equity + total_pnl

        # Default to starting equity
        return float(os.getenv("STARTING_EQUITY_USD", "10000"))

    def get_latest_summary(self) -> Optional[Dict]:
        """Get latest metrics summary."""
        return self.calculator.get_metrics_summary()


# Standalone function for easy integration
def create_metrics_publisher(
    redis_manager=None,
    trade_manager=None,
    equity_tracker=None,
    logger=None,
    update_interval: int = 30,
    auto_start: bool = True,
) -> MetricsPublisher:
    """
    Create and optionally start a metrics publisher.

    Args:
        redis_manager: Redis manager
        trade_manager: Trade manager
        equity_tracker: Equity tracker
        logger: Logger instance
        update_interval: Update interval in seconds
        auto_start: Auto-start publishing (default: True)

    Returns:
        MetricsPublisher instance
    """
    publisher = MetricsPublisher(
        redis_manager=redis_manager,
        trade_manager=trade_manager,
        equity_tracker=equity_tracker,
        logger=logger,
        update_interval=update_interval,
    )

    if auto_start:
        publisher.start()

    return publisher
