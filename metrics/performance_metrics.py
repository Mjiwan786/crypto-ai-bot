"""
Real-Time Performance Metrics Calculator

Calculates and publishes real-time trading performance metrics:
- Aggressive mode score (risk-adjusted performance)
- Velocity to target (progress tracking)
- Days remaining estimate (time projection)

Publishes to Redis streams and Prometheus.

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

try:
    from prometheus_client import Gauge, Counter, Histogram
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    Gauge = Counter = Histogram = None


@dataclass
class PerformanceMetrics:
    """Real-time performance metrics."""
    timestamp: float

    # Aggressive mode score
    aggressive_mode_score: float  # (win_rate*avg_win)/(loss_rate*avg_loss)
    win_rate: float
    loss_rate: float
    avg_win_usd: float
    avg_loss_usd: float

    # Velocity to target
    velocity_to_target: float  # (equity - 10k) / (20k - 10k)
    current_equity_usd: float
    target_equity_usd: float
    starting_equity_usd: float

    # Days remaining estimate
    days_remaining_estimate: float
    daily_rate_usd: float
    days_elapsed: float

    # Supporting metrics
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl_usd: float


class PerformanceMetricsCalculator:
    """
    Calculates real-time performance metrics from trading history.

    Publishes to Redis streams and Prometheus metrics.
    """

    def __init__(
        self,
        redis_manager=None,
        logger=None,
        starting_equity: float = 10000.0,
        target_equity: float = 20000.0,
        start_date: Optional[datetime] = None,
    ):
        """
        Initialize performance metrics calculator.

        Args:
            redis_manager: Redis manager for publishing
            logger: Logger instance
            starting_equity: Starting equity in USD (default: 10k)
            target_equity: Target equity in USD (default: 20k)
            start_date: Start date for tracking (default: now)
        """
        self.redis = redis_manager
        self.logger = logger or logging.getLogger(__name__)

        # Configuration
        self.starting_equity = starting_equity
        self.target_equity = target_equity
        self.start_date = start_date or datetime.now()

        # Feature flag
        self.enabled = os.getenv("ENABLE_PERFORMANCE_METRICS", "true").lower() == "true"

        # Cache
        self.last_metrics: Optional[PerformanceMetrics] = None
        self.cache_ttl = 10  # seconds
        self.last_update = 0

        # Prometheus metrics
        if PROMETHEUS_AVAILABLE and self.enabled:
            self.prometheus_metrics = self._init_prometheus()
        else:
            self.prometheus_metrics = None

        if self.enabled:
            self.logger.info(
                f"PerformanceMetricsCalculator initialized: "
                f"${starting_equity:,.0f} → ${target_equity:,.0f}"
            )

    def _init_prometheus(self) -> Dict:
        """Initialize Prometheus metrics."""
        try:
            return {
                "aggressive_mode_score": Gauge(
                    "aggressive_mode_score",
                    "Risk-adjusted performance score (win_rate*avg_win)/(loss_rate*avg_loss)"
                ),
                "velocity_to_target": Gauge(
                    "velocity_to_target",
                    "Progress towards target equity (0.0 to 1.0)"
                ),
                "days_remaining_estimate": Gauge(
                    "days_remaining_estimate",
                    "Estimated days to reach target at current rate"
                ),
                "current_equity_usd": Gauge(
                    "current_equity_usd",
                    "Current equity in USD"
                ),
                "daily_rate_usd": Gauge(
                    "daily_rate_usd",
                    "Current daily profit rate in USD"
                ),
                "win_rate_percent": Gauge(
                    "win_rate_percent",
                    "Percentage of winning trades"
                ),
            }
        except Exception as e:
            self.logger.error(f"Error initializing Prometheus metrics: {e}")
            return {}

    def calculate_metrics(
        self,
        trades: List[Dict],
        current_equity: float,
    ) -> PerformanceMetrics:
        """
        Calculate performance metrics from trade history.

        Args:
            trades: List of closed trades with PnL
            current_equity: Current account equity

        Returns:
            PerformanceMetrics object
        """
        if not self.enabled:
            return None

        # Check cache
        current_time = time.time()
        if (self.last_metrics and
            current_time - self.last_update < self.cache_ttl):
            return self.last_metrics

        # Filter completed trades with PnL
        completed_trades = [
            t for t in trades
            if t.get("status") == "closed" and "pnl_usd" in t
        ]

        if not completed_trades:
            # No trades yet - return baseline metrics
            return self._baseline_metrics(current_equity)

        # Calculate win/loss statistics
        winning_trades = [t for t in completed_trades if t["pnl_usd"] > 0]
        losing_trades = [t for t in completed_trades if t["pnl_usd"] < 0]

        total_trades = len(completed_trades)
        num_wins = len(winning_trades)
        num_losses = len(losing_trades)

        win_rate = num_wins / total_trades if total_trades > 0 else 0.0
        loss_rate = num_losses / total_trades if total_trades > 0 else 0.0

        # Average win/loss
        avg_win = (
            sum(t["pnl_usd"] for t in winning_trades) / num_wins
            if num_wins > 0 else 0.0
        )
        avg_loss = (
            abs(sum(t["pnl_usd"] for t in losing_trades)) / num_losses
            if num_losses > 0 else 1.0  # Avoid division by zero
        )

        # Total PnL
        total_pnl = sum(t["pnl_usd"] for t in completed_trades)

        # 1. Aggressive Mode Score
        # = (win_rate * avg_win) / (loss_rate * avg_loss)
        # Higher is better (winning more, larger wins, smaller losses)
        if loss_rate > 0 and avg_loss > 0:
            aggressive_score = (win_rate * avg_win) / (loss_rate * avg_loss)
        else:
            aggressive_score = win_rate * avg_win if win_rate > 0 else 0.0

        # 2. Velocity to Target
        # = (current_equity - starting) / (target - starting)
        # 0.0 = at start, 1.0 = at target
        equity_range = self.target_equity - self.starting_equity
        if equity_range > 0:
            velocity = (current_equity - self.starting_equity) / equity_range
        else:
            velocity = 0.0

        # Clamp to reasonable range
        velocity = max(0.0, min(2.0, velocity))  # Allow up to 200%

        # 3. Days Remaining Estimate
        days_elapsed = (datetime.now() - self.start_date).total_seconds() / 86400
        days_elapsed = max(0.1, days_elapsed)  # Avoid division by zero

        # Daily rate
        daily_rate = total_pnl / days_elapsed if days_elapsed > 0 else 0.0

        # Days remaining to target
        equity_remaining = self.target_equity - current_equity
        if daily_rate > 0:
            days_remaining = equity_remaining / daily_rate
            days_remaining = max(0.0, days_remaining)  # Can't be negative
        else:
            days_remaining = float('inf')  # Not making progress

        # Create metrics object
        metrics = PerformanceMetrics(
            timestamp=current_time,
            aggressive_mode_score=aggressive_score,
            win_rate=win_rate,
            loss_rate=loss_rate,
            avg_win_usd=avg_win,
            avg_loss_usd=avg_loss,
            velocity_to_target=velocity,
            current_equity_usd=current_equity,
            target_equity_usd=self.target_equity,
            starting_equity_usd=self.starting_equity,
            days_remaining_estimate=days_remaining,
            daily_rate_usd=daily_rate,
            days_elapsed=days_elapsed,
            total_trades=total_trades,
            winning_trades=num_wins,
            losing_trades=num_losses,
            total_pnl_usd=total_pnl,
        )

        # Update cache
        self.last_metrics = metrics
        self.last_update = current_time

        # Publish to Prometheus
        if self.prometheus_metrics:
            self._update_prometheus(metrics)

        # Publish to Redis
        if self.redis:
            self._publish_to_redis(metrics)

        # Log summary
        self.logger.info(
            f"Performance Metrics: "
            f"Aggressive={aggressive_score:.2f}, "
            f"Velocity={velocity:.1%}, "
            f"Days Remaining={days_remaining:.1f}, "
            f"Win Rate={win_rate:.1%}"
        )

        return metrics

    def _baseline_metrics(self, current_equity: float) -> PerformanceMetrics:
        """Return baseline metrics when no trades exist."""
        current_time = time.time()
        days_elapsed = (datetime.now() - self.start_date).total_seconds() / 86400

        return PerformanceMetrics(
            timestamp=current_time,
            aggressive_mode_score=0.0,
            win_rate=0.0,
            loss_rate=0.0,
            avg_win_usd=0.0,
            avg_loss_usd=0.0,
            velocity_to_target=0.0,
            current_equity_usd=current_equity,
            target_equity_usd=self.target_equity,
            starting_equity_usd=self.starting_equity,
            days_remaining_estimate=float('inf'),
            daily_rate_usd=0.0,
            days_elapsed=days_elapsed,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            total_pnl_usd=0.0,
        )

    def _update_prometheus(self, metrics: PerformanceMetrics):
        """Update Prometheus metrics."""
        try:
            self.prometheus_metrics["aggressive_mode_score"].set(
                metrics.aggressive_mode_score
            )
            self.prometheus_metrics["velocity_to_target"].set(
                metrics.velocity_to_target
            )

            # Cap days_remaining at reasonable value for Prometheus
            days_remaining = min(metrics.days_remaining_estimate, 9999.0)
            self.prometheus_metrics["days_remaining_estimate"].set(days_remaining)

            self.prometheus_metrics["current_equity_usd"].set(
                metrics.current_equity_usd
            )
            self.prometheus_metrics["daily_rate_usd"].set(metrics.daily_rate_usd)
            self.prometheus_metrics["win_rate_percent"].set(metrics.win_rate * 100)

        except Exception as e:
            self.logger.error(f"Error updating Prometheus metrics: {e}")

    def _publish_to_redis(self, metrics: PerformanceMetrics):
        """Publish metrics to Redis stream."""
        try:
            # Publish to metrics stream
            data = asdict(metrics)

            # Handle inf/nan values for JSON
            data["days_remaining_estimate"] = (
                None if not isinstance(data["days_remaining_estimate"], (int, float))
                or data["days_remaining_estimate"] == float('inf')
                else data["days_remaining_estimate"]
            )

            self.redis.publish_event("metrics:performance", data)

            # Also publish individual metrics for SSE
            self.redis.publish_event("metrics:aggressive_mode_score", {
                "timestamp": metrics.timestamp,
                "value": metrics.aggressive_mode_score,
            })

            self.redis.publish_event("metrics:velocity_to_target", {
                "timestamp": metrics.timestamp,
                "value": metrics.velocity_to_target,
            })

            self.redis.publish_event("metrics:days_remaining", {
                "timestamp": metrics.timestamp,
                "value": data["days_remaining_estimate"],
            })

        except Exception as e:
            self.logger.error(f"Error publishing to Redis: {e}")

    def get_latest_metrics(self) -> Optional[PerformanceMetrics]:
        """Get latest calculated metrics from cache."""
        return self.last_metrics

    def get_metrics_summary(self) -> Dict:
        """Get summary of latest metrics for display."""
        if not self.last_metrics:
            return {
                "available": False,
                "message": "No metrics calculated yet"
            }

        m = self.last_metrics

        return {
            "available": True,
            "timestamp": m.timestamp,
            "aggressive_mode_score": {
                "value": m.aggressive_mode_score,
                "description": "Risk-adjusted performance",
                "interpretation": self._interpret_aggressive_score(m.aggressive_mode_score),
            },
            "velocity_to_target": {
                "value": m.velocity_to_target,
                "percent": m.velocity_to_target * 100,
                "description": f"Progress: ${m.current_equity_usd:,.0f} / ${m.target_equity_usd:,.0f}",
            },
            "days_remaining_estimate": {
                "value": m.days_remaining_estimate if m.days_remaining_estimate != float('inf') else None,
                "daily_rate": m.daily_rate_usd,
                "description": self._interpret_days_remaining(m),
            },
            "trading_stats": {
                "total_trades": m.total_trades,
                "win_rate": m.win_rate,
                "avg_win": m.avg_win_usd,
                "avg_loss": m.avg_loss_usd,
                "total_pnl": m.total_pnl_usd,
            },
        }

    def _interpret_aggressive_score(self, score: float) -> str:
        """Interpret aggressive mode score."""
        if score >= 2.0:
            return "Excellent - Strong risk-adjusted returns"
        elif score >= 1.5:
            return "Very Good - Positive risk profile"
        elif score >= 1.0:
            return "Good - Balanced performance"
        elif score >= 0.5:
            return "Fair - Room for improvement"
        else:
            return "Poor - Review strategy"

    def _interpret_days_remaining(self, metrics: PerformanceMetrics) -> str:
        """Interpret days remaining estimate."""
        if metrics.daily_rate_usd <= 0:
            return "Not making progress - negative daily rate"
        elif metrics.days_remaining_estimate == float('inf'):
            return "Insufficient data"
        elif metrics.days_remaining_estimate < 7:
            return f"Target within {metrics.days_remaining_estimate:.0f} days!"
        elif metrics.days_remaining_estimate < 30:
            return f"On track - {metrics.days_remaining_estimate:.0f} days to target"
        elif metrics.days_remaining_estimate < 90:
            return f"Moderate pace - {metrics.days_remaining_estimate:.0f} days remaining"
        else:
            return f"Slow progress - {metrics.days_remaining_estimate:.0f} days at current rate"
