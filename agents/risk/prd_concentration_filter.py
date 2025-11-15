"""
PRD-001 Compliant Position Concentration Filter (Section 4.6)

This module implements PRD-001 Section 4.6 position concentration filtering with:
- Calculate position concentration per symbol: position_size / total_portfolio_value
- Reject signal if position concentration > 40% for any single symbol
- WARNING level logging for concentration rejections
- Prometheus counter risk_filter_rejections_total{reason="concentration", pair}

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, List

# PRD-001 Section 4.6: Prometheus metrics
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


class PRDConcentrationFilter:
    """
    PRD-001 Section 4.6 compliant position concentration filter.

    Features:
    - Calculate concentration per symbol
    - Reject if concentration > 40% (configurable)
    - WARNING level logging for rejections
    - Prometheus metrics

    Usage:
        filter = PRDConcentrationFilter(
            max_concentration_pct=40.0,
            total_portfolio_value=10000.0
        )

        # Check concentration
        should_reject, concentration_pct = filter.check_concentration(
            symbol="BTC/USD",
            position_size_usd=5000.0,
            existing_positions=existing_positions
        )

        if should_reject:
            # Signal rejected due to high concentration
            pass
    """

    def __init__(
        self,
        max_concentration_pct: float = 40.0,
        total_portfolio_value: float = 10000.0
    ):
        """
        Initialize PRD-compliant concentration filter.

        Args:
            max_concentration_pct: Maximum allowed concentration % (default 40% per PRD)
            total_portfolio_value: Total portfolio value in USD
        """
        # PRD-001 Section 4.6: Concentration threshold
        self.max_concentration_pct = max_concentration_pct
        self.total_portfolio_value = total_portfolio_value

        # Statistics
        self.total_checks = 0
        self.total_rejections = 0

        logger.info(
            f"PRDConcentrationFilter initialized: "
            f"max_concentration={max_concentration_pct:.1f}%, "
            f"portfolio_value=${total_portfolio_value:.2f}"
        )

    def calculate_concentration_pct(
        self,
        symbol: str,
        position_size_usd: float,
        existing_positions: Optional[List[Dict[str, Any]]] = None
    ) -> float:
        """
        PRD-001 Section 4.6: Calculate position concentration per symbol.

        Formula: (total_symbol_exposure / total_portfolio_value) * 100

        Args:
            symbol: Trading symbol (e.g., "BTC/USD")
            position_size_usd: New position size in USD
            existing_positions: List of existing positions

        Returns:
            Concentration percentage
        """
        # Start with new position size
        total_symbol_exposure = position_size_usd

        # Add existing positions for same symbol
        if existing_positions:
            for pos in existing_positions:
                pos_symbol = pos.get("symbol") or pos.get("trading_pair") or pos.get("pair")
                if pos_symbol == symbol:
                    total_symbol_exposure += pos.get("size_usd", 0.0)

        if self.total_portfolio_value <= 0:
            logger.warning(f"Invalid total_portfolio_value: {self.total_portfolio_value}")
            return 999.0  # Return very high concentration for invalid data

        # PRD-001 Section 4.6: position_size / total_portfolio_value
        concentration_pct = (total_symbol_exposure / self.total_portfolio_value) * 100.0

        return concentration_pct

    def check_concentration(
        self,
        symbol: str,
        position_size_usd: float,
        existing_positions: Optional[List[Dict[str, Any]]] = None
    ) -> tuple[bool, float]:
        """
        Check if position concentration exceeds threshold.

        PRD-001 Section 4.6:
        1. Calculate concentration percentage
        2. Compare to max threshold
        3. Log rejection at WARNING level if exceeded
        4. Emit Prometheus counter

        Args:
            symbol: Trading symbol
            position_size_usd: New position size in USD
            existing_positions: List of existing positions

        Returns:
            (should_reject, concentration_pct) tuple
        """
        self.total_checks += 1

        # Calculate concentration
        concentration_pct = self.calculate_concentration_pct(
            symbol, position_size_usd, existing_positions
        )

        # PRD-001 Section 4.6: Reject if concentration > threshold
        should_reject = concentration_pct > self.max_concentration_pct

        if should_reject:
            self.total_rejections += 1

            # PRD-001 Section 4.6: Log at WARNING level
            logger.warning(
                f"[CONCENTRATION REJECTION] {symbol}: concentration {concentration_pct:.2f}% > "
                f"max {self.max_concentration_pct:.1f}% "
                f"(position=${position_size_usd:.2f}, portfolio=${self.total_portfolio_value:.2f})"
            )

            # PRD-001 Section 4.6: Emit Prometheus counter
            if PROMETHEUS_AVAILABLE and RISK_FILTER_REJECTIONS:
                RISK_FILTER_REJECTIONS.labels(
                    reason="concentration",
                    pair=symbol
                ).inc()

        else:
            logger.debug(
                f"[CONCENTRATION CHECK] {symbol}: concentration {concentration_pct:.2f}% ≤ "
                f"max {self.max_concentration_pct:.1f}% - PASS"
            )

        return should_reject, concentration_pct

    def check_signal(
        self,
        signal: Dict[str, Any],
        position_size_usd: float,
        existing_positions: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        Check if signal should be rejected based on concentration.

        Convenience method that extracts symbol from signal dict.

        Args:
            signal: Trading signal dict
            position_size_usd: Position size in USD
            existing_positions: List of existing positions

        Returns:
            True if signal should be REJECTED, False if should ACCEPT
        """
        symbol = signal.get("trading_pair") or signal.get("pair") or signal.get("symbol", "UNKNOWN")

        should_reject, concentration_pct = self.check_concentration(
            symbol=symbol,
            position_size_usd=position_size_usd,
            existing_positions=existing_positions
        )

        return should_reject

    def update_portfolio_value(self, new_portfolio_value: float):
        """
        Update total portfolio value.

        Args:
            new_portfolio_value: New portfolio value in USD
        """
        old_value = self.total_portfolio_value
        self.total_portfolio_value = new_portfolio_value

        logger.info(
            f"Portfolio value updated: ${old_value:.2f} → ${new_portfolio_value:.2f}"
        )

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get concentration filter metrics.

        Returns:
            Dictionary with metrics
        """
        rejection_rate = (
            self.total_rejections / self.total_checks
            if self.total_checks > 0
            else 0.0
        )

        return {
            "total_checks": self.total_checks,
            "total_rejections": self.total_rejections,
            "rejection_rate": rejection_rate,
            "max_concentration_pct": self.max_concentration_pct,
            "total_portfolio_value": self.total_portfolio_value
        }

    def reset_stats(self):
        """Reset statistics counters."""
        self.total_checks = 0
        self.total_rejections = 0
        logger.info("Concentration filter statistics reset")


# Export for convenience
__all__ = [
    "PRDConcentrationFilter",
]
