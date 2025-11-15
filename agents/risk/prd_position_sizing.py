"""
PRD-001 Compliant Position Sizing (Section 4.4)

This module implements PRD-001 Section 4.4 position sizing with:
- Formula: size = base_size * confidence * (avg_ATR / ATR)
- base_size = $100 per signal (configurable)
- Volatility adjustment: divide by (ATR / avg_ATR) to reduce size in high vol
- Confidence scaling: multiply by signal.confidence (0.6 - 1.0)
- Cap position size at $2,000 max per signal
- Enforce max total exposure: sum of all open positions ≤ $10,000
- DEBUG level logging with all factors

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, List
from decimal import Decimal

logger = logging.getLogger(__name__)


class PRDPositionSizer:
    """
    PRD-001 Section 4.4 compliant position sizing.

    Features:
    - Volatility-adjusted position sizing
    - Confidence-based scaling
    - Per-signal and total exposure caps
    - DEBUG level logging

    Usage:
        sizer = PRDPositionSizer(
            base_size_usd=100.0,
            max_position_usd=2000.0,
            max_total_exposure_usd=10000.0
        )

        # Calculate position size
        size_usd = sizer.calculate_position_size(
            confidence=0.75,
            current_atr=1500.0,
            avg_atr=1000.0,
            open_positions_usd=3000.0
        )
    """

    def __init__(
        self,
        base_size_usd: float = 100.0,
        max_position_usd: float = 2000.0,
        max_total_exposure_usd: float = 10000.0
    ):
        """
        Initialize PRD-compliant position sizer.

        Args:
            base_size_usd: Base position size in USD (default $100 per PRD)
            max_position_usd: Max position size in USD (default $2,000 per PRD)
            max_total_exposure_usd: Max total exposure in USD (default $10,000 per PRD)
        """
        # PRD-001 Section 4.4: Position sizing parameters
        self.base_size_usd = base_size_usd
        self.max_position_usd = max_position_usd
        self.max_total_exposure_usd = max_total_exposure_usd

        # Statistics
        self.total_calculations = 0
        self.total_capped = 0
        self.total_rejected_exposure = 0

        logger.info(
            f"PRDPositionSizer initialized: "
            f"base_size=${base_size_usd:.2f}, "
            f"max_position=${max_position_usd:.2f}, "
            f"max_total_exposure=${max_total_exposure_usd:.2f}"
        )

    def calculate_volatility_adjustment(
        self,
        current_atr: float,
        avg_atr: float
    ) -> float:
        """
        PRD-001 Section 4.4: Calculate volatility adjustment factor.

        Formula: avg_ATR / ATR
        Higher ATR (more volatile) → lower multiplier → smaller position

        Args:
            current_atr: Current ATR value
            avg_atr: Average ATR value

        Returns:
            Volatility adjustment factor
        """
        if current_atr <= 0:
            logger.warning(f"Invalid current_atr: {current_atr}, using 1.0")
            return 1.0

        if avg_atr <= 0:
            logger.warning(f"Invalid avg_atr: {avg_atr}, using 1.0")
            return 1.0

        # PRD-001 Section 4.4: avg_ATR / ATR
        # If ATR is high (volatile), this ratio is < 1.0, reducing position size
        # If ATR is low (calm), this ratio is > 1.0, increasing position size
        volatility_adjustment = avg_atr / current_atr

        return volatility_adjustment

    def calculate_position_size(
        self,
        confidence: float,
        current_atr: Optional[float] = None,
        avg_atr: Optional[float] = None,
        open_positions_usd: float = 0.0
    ) -> float:
        """
        PRD-001 Section 4.4: Calculate position size with all factors.

        Formula: size = base_size * confidence * (avg_ATR / ATR)

        Steps:
        1. Start with base_size
        2. Multiply by confidence (0.6 - 1.0)
        3. Apply volatility adjustment: multiply by (avg_ATR / ATR)
        4. Cap at max_position_usd
        5. Check total exposure limit

        Args:
            confidence: Signal confidence (0.6 - 1.0)
            current_atr: Current ATR (optional, if None no vol adjustment)
            avg_atr: Average ATR (optional, if None no vol adjustment)
            open_positions_usd: Current total open positions in USD

        Returns:
            Position size in USD (can be 0 if exposure limit reached)
        """
        self.total_calculations += 1

        # Start with base size
        size = self.base_size_usd

        # PRD-001 Section 4.4: Apply confidence scaling
        confidence_clamped = max(0.6, min(1.0, confidence))
        size *= confidence_clamped

        # PRD-001 Section 4.4: Apply volatility adjustment
        volatility_adjustment = 1.0
        if current_atr is not None and avg_atr is not None:
            volatility_adjustment = self.calculate_volatility_adjustment(
                current_atr, avg_atr
            )
            size *= volatility_adjustment

        # PRD-001 Section 4.4: Cap at max_position_usd
        was_capped = False
        if size > self.max_position_usd:
            size = self.max_position_usd
            was_capped = True
            self.total_capped += 1

        # PRD-001 Section 4.4: Enforce max total exposure
        remaining_exposure = self.max_total_exposure_usd - open_positions_usd
        if remaining_exposure <= 0:
            # No room for new position
            self.total_rejected_exposure += 1
            logger.warning(
                f"[POSITION SIZING] REJECTED - Max total exposure reached: "
                f"open_positions=${open_positions_usd:.2f} >= "
                f"max_total_exposure=${self.max_total_exposure_usd:.2f}"
            )
            return 0.0

        if size > remaining_exposure:
            # Reduce size to fit within exposure limit
            size = remaining_exposure
            was_capped = True

        # PRD-001 Section 4.4: Log at DEBUG level with all factors
        logger.debug(
            f"[POSITION SIZING] "
            f"base_size=${self.base_size_usd:.2f} | "
            f"confidence={confidence_clamped:.3f} | "
            f"vol_adjustment={volatility_adjustment:.3f} | "
            f"size=${size:.2f} | "
            f"capped={was_capped} | "
            f"open_positions=${open_positions_usd:.2f}"
        )

        return size

    def calculate_position_size_for_signal(
        self,
        signal: Dict[str, Any],
        open_positions: Optional[List[Dict[str, Any]]] = None
    ) -> float:
        """
        Calculate position size for a signal.

        Convenience method that extracts parameters from signal dict.

        Args:
            signal: Trading signal dict with confidence, atr, etc.
            open_positions: List of open positions (for exposure calculation)

        Returns:
            Position size in USD
        """
        # Extract confidence
        confidence = signal.get("confidence", 0.6)

        # Extract ATR values
        current_atr = signal.get("atr") or signal.get("atr_14")
        avg_atr = signal.get("avg_atr")

        # Calculate total open positions
        open_positions_usd = 0.0
        if open_positions:
            for pos in open_positions:
                open_positions_usd += pos.get("size_usd", 0.0)

        # Calculate position size
        size = self.calculate_position_size(
            confidence=confidence,
            current_atr=current_atr,
            avg_atr=avg_atr,
            open_positions_usd=open_positions_usd
        )

        return size

    def can_open_new_position(
        self,
        open_positions_usd: float,
        min_position_size: float = 10.0
    ) -> bool:
        """
        Check if we can open a new position based on exposure limits.

        Args:
            open_positions_usd: Current total open positions in USD
            min_position_size: Minimum viable position size

        Returns:
            True if we can open a new position
        """
        remaining_exposure = self.max_total_exposure_usd - open_positions_usd

        return remaining_exposure >= min_position_size

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get position sizer metrics.

        Returns:
            Dictionary with metrics
        """
        capped_rate = (
            self.total_capped / self.total_calculations
            if self.total_calculations > 0
            else 0.0
        )

        rejection_rate = (
            self.total_rejected_exposure / self.total_calculations
            if self.total_calculations > 0
            else 0.0
        )

        return {
            "total_calculations": self.total_calculations,
            "total_capped": self.total_capped,
            "total_rejected_exposure": self.total_rejected_exposure,
            "capped_rate": capped_rate,
            "rejection_rate": rejection_rate,
            "base_size_usd": self.base_size_usd,
            "max_position_usd": self.max_position_usd,
            "max_total_exposure_usd": self.max_total_exposure_usd
        }

    def reset_stats(self):
        """Reset statistics counters."""
        self.total_calculations = 0
        self.total_capped = 0
        self.total_rejected_exposure = 0
        logger.info("Position sizer statistics reset")


# Export for convenience
__all__ = [
    "PRDPositionSizer",
]
