"""
PRD-001 Compliant Spread Filter (Section 4.1)

This module implements PRD-001 Section 4.1 spread filtering with:
- Fetch current spread from Kraken spread channel
- Calculate spread %: (ask - bid) / mid * 100
- Reject signal if spread > 0.5% (configurable)
- WARNING level logging for rejections
- Prometheus counter risk_filter_rejections_total{reason="wide_spread", pair}

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Tuple
from decimal import Decimal

# PRD-001 Section 4.1: Prometheus metrics
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


class PRDSpreadFilter:
    """
    PRD-001 Section 4.1 compliant spread filter.

    Features:
    - Fetch spread from Kraken spread channel
    - Calculate spread percentage
    - Configurable max spread threshold (default 0.5%)
    - WARNING level logging for rejections
    - Prometheus metrics

    Usage:
        filter = PRDSpreadFilter(max_spread_pct=0.5)

        # Check if signal should be rejected
        should_reject, spread_pct = filter.check_spread(
            bid=50000.0,
            ask=50250.0,
            pair="BTC/USD"
        )

        if should_reject:
            # Signal rejected due to wide spread
            pass
    """

    def __init__(
        self,
        max_spread_pct: float = 0.5,
        kraken_ws_client = None
    ):
        """
        Initialize PRD-compliant spread filter.

        Args:
            max_spread_pct: Maximum allowed spread percentage (default 0.5% per PRD)
            kraken_ws_client: Optional Kraken WebSocket client for live spread fetching
        """
        # PRD-001 Section 4.1: Configurable max spread threshold
        self.max_spread_pct = max_spread_pct
        self.kraken_ws_client = kraken_ws_client

        # Statistics
        self.total_checks = 0
        self.total_rejections = 0

        logger.info(
            f"PRDSpreadFilter initialized: max_spread_pct={max_spread_pct:.2f}%"
        )

    def fetch_current_spread(self, pair: str) -> Optional[Tuple[float, float]]:
        """
        PRD-001 Section 4.1: Fetch current spread from Kraken spread channel.

        Args:
            pair: Trading pair (e.g., "BTC/USD")

        Returns:
            (bid, ask) tuple or None if unavailable
        """
        if self.kraken_ws_client is None:
            logger.debug("No Kraken WS client available for spread fetch")
            return None

        try:
            # Fetch spread from Kraken spread channel
            # This would be implemented by the actual Kraken WS client
            spread_data = self.kraken_ws_client.get_spread(pair)

            if spread_data:
                bid = float(spread_data.get('bid', 0.0))
                ask = float(spread_data.get('ask', 0.0))
                return (bid, ask)

        except Exception as e:
            logger.warning(f"Failed to fetch spread for {pair}: {e}")

        return None

    def calculate_spread_pct(
        self,
        bid: float,
        ask: float
    ) -> float:
        """
        PRD-001 Section 4.1: Calculate spread percentage.

        Formula: (ask - bid) / mid * 100
        Where mid = (bid + ask) / 2

        Args:
            bid: Bid price
            ask: Ask price

        Returns:
            Spread percentage
        """
        if bid <= 0 or ask <= 0:
            logger.warning(f"Invalid bid/ask: bid={bid}, ask={ask}")
            return 999.0  # Return very high spread for invalid data

        # Calculate mid price
        mid = (bid + ask) / 2.0

        if mid <= 0:
            logger.warning(f"Invalid mid price: {mid}")
            return 999.0

        # PRD-001 Section 4.1: Calculate spread %
        spread_pct = ((ask - bid) / mid) * 100.0

        return spread_pct

    def check_spread(
        self,
        bid: float,
        ask: float,
        pair: str
    ) -> Tuple[bool, float]:
        """
        Check if spread exceeds threshold and should reject signal.

        PRD-001 Section 4.1:
        1. Calculate spread percentage
        2. Compare to max threshold
        3. Log rejection at WARNING level if exceeded
        4. Emit Prometheus counter

        Args:
            bid: Current bid price
            ask: Current ask price
            pair: Trading pair

        Returns:
            (should_reject, spread_pct) tuple
        """
        self.total_checks += 1

        # Calculate spread %
        spread_pct = self.calculate_spread_pct(bid, ask)

        # PRD-001 Section 4.1: Reject if spread > threshold
        should_reject = spread_pct > self.max_spread_pct

        if should_reject:
            self.total_rejections += 1

            # PRD-001 Section 4.1: Log at WARNING level
            logger.warning(
                f"[SPREAD REJECTION] {pair}: spread {spread_pct:.3f}% > "
                f"max {self.max_spread_pct:.2f}% (bid={bid:.2f}, ask={ask:.2f})"
            )

            # PRD-001 Section 4.1: Emit Prometheus counter
            if PROMETHEUS_AVAILABLE and RISK_FILTER_REJECTIONS:
                RISK_FILTER_REJECTIONS.labels(
                    reason="wide_spread",
                    pair=pair
                ).inc()

        else:
            logger.debug(
                f"[SPREAD CHECK] {pair}: spread {spread_pct:.3f}% ≤ "
                f"max {self.max_spread_pct:.2f}% - PASS"
            )

        return should_reject, spread_pct

    def check_signal(
        self,
        signal: Dict[str, Any],
        market_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Check if signal should be rejected based on spread.

        Convenience method that extracts bid/ask from market data
        and checks spread.

        Args:
            signal: Trading signal dict
            market_data: Market data dict with 'bid' and 'ask' fields

        Returns:
            True if signal should be REJECTED, False if should ACCEPT
        """
        pair = signal.get("trading_pair", "UNKNOWN")

        # Try to get bid/ask from market_data
        if market_data:
            bid = market_data.get("bid")
            ask = market_data.get("ask")
        else:
            # Try to fetch from Kraken WS
            spread_data = self.fetch_current_spread(pair)
            if spread_data:
                bid, ask = spread_data
            else:
                logger.warning(
                    f"No bid/ask data available for {pair}, "
                    f"allowing signal (cannot validate spread)"
                )
                return False  # Don't reject if we can't check

        if bid is None or ask is None:
            logger.warning(
                f"Missing bid/ask for {pair}, "
                f"allowing signal (cannot validate spread)"
            )
            return False

        # Check spread
        should_reject, spread_pct = self.check_spread(
            bid=float(bid),
            ask=float(ask),
            pair=pair
        )

        return should_reject

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get spread filter metrics.

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
            "max_spread_pct": self.max_spread_pct
        }

    def reset_stats(self):
        """Reset statistics counters."""
        self.total_checks = 0
        self.total_rejections = 0
        logger.info("Spread filter statistics reset")


# Export for convenience
__all__ = [
    "PRDSpreadFilter",
]
