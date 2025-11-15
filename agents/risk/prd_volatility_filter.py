"""
PRD-001 Compliant Volatility Filter (Section 4.2)

This module implements PRD-001 Section 4.2 volatility filtering with:
- Calculate ATR(14) on 5-minute candles for each pair
- Track 30-day rolling average ATR for each pair
- If current_ATR > 3.0 × avg_ATR, reduce position size by 50%
- If current_ATR > 5.0 × avg_ATR, halt new signals (circuit breaker)
- INFO level logging for volatility adjustments
- Prometheus counter risk_filter_rejections_total{reason="high_volatility", pair}

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Tuple
from collections import deque
from decimal import Decimal
import numpy as np

# PRD-001 Section 4.2: Prometheus metrics
try:
    from prometheus_client import Counter
    RISK_FILTER_REJECTIONS = Counter(
        'risk_filter_rejections_total',
        'Total risk filter rejections by reason and pair',
        ['reason', 'pair']
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    RISK_FILTER_REJECTIONS = None

logger = logging.getLogger(__name__)


class PRDVolatilityFilter:
    """
    PRD-001 Section 4.2 compliant volatility filter.

    Features:
    - ATR(14) calculation on 5-minute candles
    - 30-day rolling average ATR tracking
    - Position sizing adjustment based on ATR ratio
    - Circuit breaker for extreme volatility
    - INFO level logging
    - Prometheus metrics

    Usage:
        filter = PRDVolatilityFilter(
            position_reduction_threshold=3.0,
            circuit_breaker_threshold=5.0
        )

        # Check volatility and get position sizing adjustment
        should_halt, position_multiplier, atr_ratio = filter.check_volatility(
            pair="BTC/USD",
            current_atr=1500.0
        )

        if should_halt:
            # Halt new signals due to extreme volatility
            pass
        else:
            # Apply position multiplier (1.0 = normal, 0.5 = reduced)
            position_size = base_size * position_multiplier
    """

    def __init__(
        self,
        atr_period: int = 14,
        rolling_window_days: int = 30,
        position_reduction_threshold: float = 3.0,
        circuit_breaker_threshold: float = 5.0
    ):
        """
        Initialize PRD-compliant volatility filter.

        Args:
            atr_period: ATR calculation period (default 14 per PRD)
            rolling_window_days: Days to track for rolling average (default 30 per PRD)
            position_reduction_threshold: ATR ratio to trigger 50% position reduction (default 3.0)
            circuit_breaker_threshold: ATR ratio to halt signals (default 5.0)
        """
        # PRD-001 Section 4.2: ATR parameters
        self.atr_period = atr_period
        self.rolling_window_days = rolling_window_days

        # PRD-001 Section 4.2: Thresholds
        self.position_reduction_threshold = position_reduction_threshold
        self.circuit_breaker_threshold = circuit_breaker_threshold

        # Track ATR history per pair
        # Format: {pair: deque([atr1, atr2, ...], maxlen=30*288)}
        # 30 days * 288 5-min candles per day = 8640 candles
        candles_per_day = 24 * 60 // 5  # 288 5-min candles per day
        self.max_history_length = rolling_window_days * candles_per_day
        self.atr_history: Dict[str, deque] = {}

        # Statistics
        self.total_checks = 0
        self.total_reductions = 0
        self.total_halts = 0

        logger.info(
            f"PRDVolatilityFilter initialized: "
            f"atr_period={atr_period}, rolling_window={rolling_window_days}d, "
            f"reduction_threshold={position_reduction_threshold:.1f}x, "
            f"circuit_breaker_threshold={circuit_breaker_threshold:.1f}x"
        )

    def calculate_atr(
        self,
        high_prices: list,
        low_prices: list,
        close_prices: list,
        period: Optional[int] = None
    ) -> float:
        """
        PRD-001 Section 4.2: Calculate ATR(14) from price data.

        Args:
            high_prices: List of high prices
            low_prices: List of low prices
            close_prices: List of close prices
            period: ATR period (defaults to self.atr_period)

        Returns:
            ATR value
        """
        if period is None:
            period = self.atr_period

        if len(high_prices) < period or len(low_prices) < period or len(close_prices) < period:
            logger.warning(
                f"Insufficient data for ATR calculation: "
                f"need {period}, got {min(len(high_prices), len(low_prices), len(close_prices))}"
            )
            return 0.0

        # Calculate True Range for each period
        true_ranges = []
        for i in range(1, len(high_prices)):
            high = high_prices[i]
            low = low_prices[i]
            prev_close = close_prices[i - 1]

            # True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return 0.0

        # PRD-001 Section 4.2: ATR = average of true ranges over period
        atr = np.mean(true_ranges[-period:])
        return float(atr)

    def update_atr_history(self, pair: str, atr: float):
        """
        Update ATR history for a pair.

        Args:
            pair: Trading pair
            atr: Current ATR value
        """
        if pair not in self.atr_history:
            self.atr_history[pair] = deque(maxlen=self.max_history_length)

        self.atr_history[pair].append(atr)

        logger.debug(
            f"ATR history updated for {pair}: "
            f"current={atr:.2f}, history_length={len(self.atr_history[pair])}"
        )

    def get_rolling_average_atr(self, pair: str) -> Optional[float]:
        """
        PRD-001 Section 4.2: Get 30-day rolling average ATR for a pair.

        Args:
            pair: Trading pair

        Returns:
            Rolling average ATR or None if insufficient data
        """
        if pair not in self.atr_history or len(self.atr_history[pair]) == 0:
            logger.debug(f"No ATR history for {pair}")
            return None

        # Calculate average of all historical ATR values
        avg_atr = np.mean(self.atr_history[pair])
        return float(avg_atr)

    def calculate_atr_ratio(
        self,
        current_atr: float,
        avg_atr: float
    ) -> float:
        """
        Calculate ATR ratio: current_ATR / avg_ATR

        Args:
            current_atr: Current ATR value
            avg_atr: Rolling average ATR

        Returns:
            ATR ratio
        """
        if avg_atr <= 0:
            logger.warning(f"Invalid avg_atr: {avg_atr}, returning high ratio")
            return 999.0

        ratio = current_atr / avg_atr
        return ratio

    def check_volatility(
        self,
        pair: str,
        current_atr: float
    ) -> Tuple[bool, float, float]:
        """
        Check volatility and determine position sizing adjustment.

        PRD-001 Section 4.2:
        1. Get rolling average ATR for pair
        2. Calculate ATR ratio
        3. If ratio > 5.0x, halt signals (circuit breaker)
        4. If ratio > 3.0x, reduce position size by 50%
        5. Log at INFO level
        6. Emit Prometheus counter if halted

        Args:
            pair: Trading pair
            current_atr: Current ATR value

        Returns:
            (should_halt, position_multiplier, atr_ratio) tuple
            - should_halt: True if circuit breaker triggered
            - position_multiplier: 1.0 (normal), 0.5 (reduced), or 0.0 (halted)
            - atr_ratio: Current ATR / Average ATR
        """
        self.total_checks += 1

        # Update ATR history
        self.update_atr_history(pair, current_atr)

        # Get rolling average ATR
        avg_atr = self.get_rolling_average_atr(pair)

        if avg_atr is None or avg_atr <= 0:
            # Insufficient history - allow normal operation
            logger.debug(
                f"[VOLATILITY CHECK] {pair}: Insufficient ATR history, "
                f"allowing normal operation"
            )
            return False, 1.0, 1.0

        # Calculate ATR ratio
        atr_ratio = self.calculate_atr_ratio(current_atr, avg_atr)

        # PRD-001 Section 4.2: Check circuit breaker threshold
        if atr_ratio > self.circuit_breaker_threshold:
            self.total_halts += 1

            # PRD-001 Section 4.2: Log at INFO level
            logger.info(
                f"[VOLATILITY HALT] {pair}: ATR ratio {atr_ratio:.2f}x > "
                f"circuit breaker threshold {self.circuit_breaker_threshold:.1f}x "
                f"(current_ATR={current_atr:.2f}, avg_ATR={avg_atr:.2f}) - "
                f"HALTING NEW SIGNALS"
            )

            # PRD-001 Section 4.2: Emit Prometheus counter
            if PROMETHEUS_AVAILABLE and RISK_FILTER_REJECTIONS:
                RISK_FILTER_REJECTIONS.labels(
                    reason="high_volatility",
                    pair=pair
                ).inc()

            return True, 0.0, atr_ratio

        # PRD-001 Section 4.2: Check position reduction threshold
        elif atr_ratio > self.position_reduction_threshold:
            self.total_reductions += 1

            # PRD-001 Section 4.2: Log at INFO level
            logger.info(
                f"[VOLATILITY REDUCTION] {pair}: ATR ratio {atr_ratio:.2f}x > "
                f"reduction threshold {self.position_reduction_threshold:.1f}x "
                f"(current_ATR={current_atr:.2f}, avg_ATR={avg_atr:.2f}) - "
                f"REDUCING POSITION SIZE BY 50%"
            )

            return False, 0.5, atr_ratio

        else:
            # Normal volatility
            logger.debug(
                f"[VOLATILITY CHECK] {pair}: ATR ratio {atr_ratio:.2f}x ≤ "
                f"threshold {self.position_reduction_threshold:.1f}x - NORMAL"
            )

            return False, 1.0, atr_ratio

    def check_signal(
        self,
        signal: Dict[str, Any],
        market_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, float]:
        """
        Check if signal should be rejected based on volatility.

        Convenience method that extracts ATR from market data
        and checks volatility.

        Args:
            signal: Trading signal dict
            market_data: Market data dict with 'atr' or 'atr_14' field

        Returns:
            (should_halt, position_multiplier) tuple
            - should_halt: True if signal should be REJECTED
            - position_multiplier: Position size multiplier (0.0-1.0)
        """
        pair = signal.get("trading_pair", "UNKNOWN")

        # Try to get ATR from market_data
        current_atr = None
        if market_data:
            current_atr = market_data.get("atr") or market_data.get("atr_14")

        if current_atr is None:
            # Try to get from signal itself
            current_atr = signal.get("atr") or signal.get("atr_14")

        if current_atr is None:
            logger.warning(
                f"No ATR data available for {pair}, "
                f"allowing signal (cannot validate volatility)"
            )
            return False, 1.0  # Don't reject if we can't check

        # Check volatility
        should_halt, position_multiplier, atr_ratio = self.check_volatility(
            pair=pair,
            current_atr=float(current_atr)
        )

        return should_halt, position_multiplier

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get volatility filter metrics.

        Returns:
            Dictionary with metrics
        """
        reduction_rate = (
            self.total_reductions / self.total_checks
            if self.total_checks > 0
            else 0.0
        )

        halt_rate = (
            self.total_halts / self.total_checks
            if self.total_checks > 0
            else 0.0
        )

        return {
            "total_checks": self.total_checks,
            "total_reductions": self.total_reductions,
            "total_halts": self.total_halts,
            "reduction_rate": reduction_rate,
            "halt_rate": halt_rate,
            "position_reduction_threshold": self.position_reduction_threshold,
            "circuit_breaker_threshold": self.circuit_breaker_threshold,
            "pairs_tracked": len(self.atr_history)
        }

    def reset_stats(self):
        """Reset statistics counters."""
        self.total_checks = 0
        self.total_reductions = 0
        self.total_halts = 0
        logger.info("Volatility filter statistics reset")

    def clear_history(self, pair: Optional[str] = None):
        """
        Clear ATR history.

        Args:
            pair: Specific pair to clear, or None to clear all
        """
        if pair:
            if pair in self.atr_history:
                del self.atr_history[pair]
                logger.info(f"ATR history cleared for {pair}")
        else:
            self.atr_history.clear()
            logger.info("All ATR history cleared")


# Export for convenience
__all__ = [
    "PRDVolatilityFilter",
]
