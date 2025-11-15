"""
PRD-001 Compliant Daily Drawdown Circuit Breaker (Section 4.3)

This module implements PRD-001 Section 4.3 daily drawdown protection with:
- Track P&L from midnight UTC daily reset
- Calculate daily drawdown: (current_equity - start_of_day_equity) / start_of_day_equity
- If daily drawdown < -5%, halt new signals until next day (00:00 UTC)
- CRITICAL level logging for circuit breaker activation
- Prometheus counter circuit_breaker_triggered{reason="daily_drawdown"}
- Prometheus gauge current_drawdown_pct (updated real-time)

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# PRD-001 Section 4.3: Prometheus metrics
try:
    from prometheus_client import Counter, Gauge
    CIRCUIT_BREAKER_TRIGGERED = Counter(
        'circuit_breaker_triggered',
        'Total circuit breaker triggers by reason',
        ['reason']
    )
    CURRENT_DRAWDOWN_PCT = Gauge(
        'current_drawdown_pct',
        'Current daily drawdown percentage'
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    CIRCUIT_BREAKER_TRIGGERED = None
    CURRENT_DRAWDOWN_PCT = None

logger = logging.getLogger(__name__)


class PRDDrawdownCircuitBreaker:
    """
    PRD-001 Section 4.3 compliant daily drawdown circuit breaker.

    Features:
    - Track P&L from midnight UTC daily reset
    - Calculate daily drawdown percentage
    - Circuit breaker at -5% daily drawdown (configurable)
    - Auto-reset at midnight UTC
    - CRITICAL level logging
    - Prometheus metrics

    Usage:
        breaker = PRDDrawdownCircuitBreaker(
            start_of_day_equity=10000.0,
            max_drawdown_pct=-5.0
        )

        # Update current equity after trades
        breaker.update_equity(9600.0)

        # Check if circuit breaker is active
        is_halted, drawdown_pct = breaker.check()

        if is_halted:
            # Halt new signals due to daily drawdown
            pass
    """

    def __init__(
        self,
        start_of_day_equity: float = 10000.0,
        max_drawdown_pct: float = -5.0,
        auto_reset: bool = True
    ):
        """
        Initialize PRD-compliant daily drawdown circuit breaker.

        Args:
            start_of_day_equity: Starting equity at midnight UTC
            max_drawdown_pct: Maximum allowed daily drawdown % (default -5% per PRD)
            auto_reset: Auto-reset at midnight UTC (default True)
        """
        # PRD-001 Section 4.3: Track P&L from midnight UTC
        self.start_of_day_equity = Decimal(str(start_of_day_equity))
        self.current_equity = Decimal(str(start_of_day_equity))

        # PRD-001 Section 4.3: Drawdown threshold
        self.max_drawdown_pct = max_drawdown_pct

        # Auto-reset flag
        self.auto_reset = auto_reset

        # Track when day started (midnight UTC)
        self.day_start_time = self._get_current_day_start()

        # Circuit breaker state
        self.is_active = False
        self.activation_time: Optional[datetime] = None

        # Statistics
        self.total_checks = 0
        self.total_activations = 0

        logger.info(
            f"PRDDrawdownCircuitBreaker initialized: "
            f"start_equity={start_of_day_equity:.2f}, "
            f"max_drawdown={max_drawdown_pct:.1f}%"
        )

    def _get_current_day_start(self) -> datetime:
        """
        Get current day's midnight UTC time.

        Returns:
            Datetime of current day's 00:00 UTC
        """
        now_utc = datetime.now(timezone.utc)
        day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start

    def _should_reset(self) -> bool:
        """
        Check if we should reset for a new day.

        Returns:
            True if current time is past the stored day start time
        """
        now_utc = datetime.now(timezone.utc)
        current_day_start = self._get_current_day_start()

        # Reset if we've crossed into a new day
        return current_day_start > self.day_start_time

    def reset_for_new_day(self, new_start_equity: Optional[float] = None):
        """
        PRD-001 Section 4.3: Reset at midnight UTC for new trading day.

        Args:
            new_start_equity: Optional new starting equity (defaults to current_equity)
        """
        if new_start_equity is not None:
            self.start_of_day_equity = Decimal(str(new_start_equity))
            self.current_equity = Decimal(str(new_start_equity))
        else:
            # Carry forward current equity as new start
            self.start_of_day_equity = self.current_equity

        self.day_start_time = self._get_current_day_start()
        self.is_active = False
        self.activation_time = None

        logger.info(
            f"[DAILY RESET] New trading day started at {self.day_start_time} UTC | "
            f"Starting equity: ${self.start_of_day_equity:.2f}"
        )

    def update_equity(self, new_equity: float):
        """
        Update current equity and check for auto-reset.

        Args:
            new_equity: New current equity value
        """
        # Check if we should auto-reset for new day
        if self.auto_reset and self._should_reset():
            self.reset_for_new_day(new_equity)
        else:
            self.current_equity = Decimal(str(new_equity))

        # Update Prometheus gauge
        if PROMETHEUS_AVAILABLE and CURRENT_DRAWDOWN_PCT:
            drawdown_pct = self.calculate_drawdown_pct()
            CURRENT_DRAWDOWN_PCT.set(drawdown_pct)

    def calculate_drawdown_pct(self) -> float:
        """
        PRD-001 Section 4.3: Calculate daily drawdown percentage.

        Formula: (current_equity - start_of_day_equity) / start_of_day_equity * 100

        Returns:
            Drawdown percentage (negative value indicates loss)
        """
        if self.start_of_day_equity <= 0:
            logger.warning(f"Invalid start_of_day_equity: {self.start_of_day_equity}")
            return 0.0

        # Calculate drawdown
        drawdown = (self.current_equity - self.start_of_day_equity) / self.start_of_day_equity * 100

        return float(drawdown)

    def check(self) -> Tuple[bool, float]:
        """
        Check if circuit breaker should be active.

        PRD-001 Section 4.3:
        1. Auto-reset if new day
        2. Calculate current drawdown %
        3. If drawdown < -5%, activate circuit breaker
        4. Log at CRITICAL level if activated
        5. Emit Prometheus metrics

        Returns:
            (is_halted, drawdown_pct) tuple
            - is_halted: True if circuit breaker is active
            - drawdown_pct: Current daily drawdown percentage
        """
        self.total_checks += 1

        # Auto-reset if new day
        if self.auto_reset and self._should_reset():
            self.reset_for_new_day()

        # Calculate current drawdown
        drawdown_pct = self.calculate_drawdown_pct()

        # Update Prometheus gauge
        if PROMETHEUS_AVAILABLE and CURRENT_DRAWDOWN_PCT:
            CURRENT_DRAWDOWN_PCT.set(drawdown_pct)

        # PRD-001 Section 4.3: Check if drawdown exceeds threshold
        if drawdown_pct < self.max_drawdown_pct:
            if not self.is_active:
                # First activation
                self.is_active = True
                self.activation_time = datetime.now(timezone.utc)
                self.total_activations += 1

                # PRD-001 Section 4.3: Log at CRITICAL level
                logger.critical(
                    f"[CIRCUIT BREAKER ACTIVATED] Daily drawdown {drawdown_pct:.2f}% < "
                    f"threshold {self.max_drawdown_pct:.1f}% | "
                    f"Start equity: ${self.start_of_day_equity:.2f} | "
                    f"Current equity: ${self.current_equity:.2f} | "
                    f"HALTING NEW SIGNALS UNTIL NEXT DAY (00:00 UTC)"
                )

                # PRD-001 Section 4.3: Emit Prometheus counter
                if PROMETHEUS_AVAILABLE and CIRCUIT_BREAKER_TRIGGERED:
                    CIRCUIT_BREAKER_TRIGGERED.labels(
                        reason="daily_drawdown"
                    ).inc()

            return True, drawdown_pct

        else:
            # Within acceptable range
            if self.is_active:
                # Was active, now deactivated (reset happened)
                logger.info(
                    f"[CIRCUIT BREAKER DEACTIVATED] Drawdown {drawdown_pct:.2f}% back "
                    f"within threshold (reset occurred)"
                )
                self.is_active = False
                self.activation_time = None

            return False, drawdown_pct

    def check_signal(
        self,
        signal: Dict[str, Any]
    ) -> bool:
        """
        Check if signal should be rejected based on daily drawdown.

        Convenience method that checks circuit breaker status.

        Args:
            signal: Trading signal dict

        Returns:
            True if signal should be REJECTED, False if should ACCEPT
        """
        is_halted, drawdown_pct = self.check()

        if is_halted:
            logger.warning(
                f"Signal rejected due to daily drawdown circuit breaker: "
                f"current drawdown {drawdown_pct:.2f}% < threshold {self.max_drawdown_pct:.1f}%"
            )

        return is_halted

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get circuit breaker metrics.

        Returns:
            Dictionary with metrics
        """
        activation_rate = (
            self.total_activations / self.total_checks
            if self.total_checks > 0
            else 0.0
        )

        current_drawdown = self.calculate_drawdown_pct()

        return {
            "total_checks": self.total_checks,
            "total_activations": self.total_activations,
            "activation_rate": activation_rate,
            "is_active": self.is_active,
            "current_drawdown_pct": current_drawdown,
            "start_of_day_equity": float(self.start_of_day_equity),
            "current_equity": float(self.current_equity),
            "max_drawdown_pct": self.max_drawdown_pct,
            "day_start_time": self.day_start_time.isoformat(),
            "activation_time": self.activation_time.isoformat() if self.activation_time else None
        }

    def reset_stats(self):
        """Reset statistics counters."""
        self.total_checks = 0
        self.total_activations = 0
        logger.info("Circuit breaker statistics reset")

    def force_activate(self):
        """
        Manually activate circuit breaker (for testing/emergency).

        This bypasses the drawdown check and immediately activates the breaker.
        """
        self.is_active = True
        self.activation_time = datetime.now(timezone.utc)
        self.total_activations += 1

        logger.critical(
            f"[CIRCUIT BREAKER MANUALLY ACTIVATED] "
            f"Current drawdown: {self.calculate_drawdown_pct():.2f}%"
        )

    def force_deactivate(self):
        """
        Manually deactivate circuit breaker (for testing/recovery).

        This bypasses the drawdown check and immediately deactivates the breaker.
        """
        was_active = self.is_active
        self.is_active = False
        self.activation_time = None

        if was_active:
            logger.warning(
                f"[CIRCUIT BREAKER MANUALLY DEACTIVATED] "
                f"Current drawdown: {self.calculate_drawdown_pct():.2f}%"
            )


# Export for convenience
__all__ = [
    "PRDDrawdownCircuitBreaker",
]
