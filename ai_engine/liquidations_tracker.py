"""
Liquidations Tracker Module (ai_engine/liquidations_tracker.py)

Tracks liquidation events in perpetual futures markets:
- Long vs short liquidation imbalance
- Liquidation cascades (multiple liquidations in short time)
- Liquidation heatmap levels (where liquidations likely cluster)
- Funding rate spread analysis

For Prompt 2: ML Predictor Enhancement
Author: Crypto AI Bot Team
Version: 2.0.0
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Deque, Dict, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class LiquidationMetrics(BaseModel):
    """Liquidation analysis results."""

    long_liquidations: float = Field(description="Long liquidation volume (USD)")
    short_liquidations: float = Field(description="Short liquidation volume (USD)")
    imbalance: float = Field(description="Liquidation imbalance: (shorts-longs)/(shorts+longs) (-1 to 1)")
    cascade_detected: bool = Field(description="Liquidation cascade in progress")
    cascade_severity: float = Field(ge=0.0, le=1.0, description="Cascade severity (0=none, 1=extreme)")
    funding_spread: float = Field(description="Funding rate spread vs historical avg (bps)")
    liquidation_pressure: float = Field(description="Overall liquidation pressure (-1 to 1)")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in liquidation data")


class LiquidationsTracker:
    """
    Tracks liquidation events and detects patterns.

    Maintains rolling window of liquidation events to detect:
    - Imbalances (more longs or shorts liquidated)
    - Cascades (rapid succession of liquidations)
    - Funding divergence
    """

    def __init__(self, window_minutes: int = 60, cascade_threshold: int = 5):
        """
        Initialize liquidations tracker.

        Args:
            window_minutes: Rolling window for liquidation analysis
            cascade_threshold: Number of liquidations to trigger cascade alert
        """
        self.window_minutes = window_minutes
        self.cascade_threshold = cascade_threshold
        self.liquidation_history: Deque[Dict] = deque(maxlen=1000)
        self.funding_history: Deque[float] = deque(maxlen=100)

    def add_liquidation_event(
        self,
        timestamp: int,
        side: str,  # "long" or "short"
        amount_usd: float,
        price: float,
    ) -> None:
        """
        Record a liquidation event.

        Args:
            timestamp: Unix timestamp (ms)
            side: "long" or "short"
            amount_usd: Liquidation size in USD
            price: Liquidation price
        """
        event = {
            "timestamp": timestamp,
            "side": side.lower(),
            "amount_usd": amount_usd,
            "price": price,
        }
        self.liquidation_history.append(event)
        logger.debug(
            "Liquidation event: %s $%.0f @ $%.2f",
            side, amount_usd, price
        )

    def add_funding_rate(self, funding_rate: float) -> None:
        """
        Record current funding rate.

        Args:
            funding_rate: Funding rate (e.g., 0.0001 = 0.01%)
        """
        self.funding_history.append(funding_rate)

    def analyze_liquidations(
        self,
        current_timestamp: int,
        current_funding_rate: Optional[float] = None,
    ) -> LiquidationMetrics:
        """
        Analyze recent liquidation activity.

        Args:
            current_timestamp: Current time (unix ms)
            current_funding_rate: Current funding rate

        Returns:
            LiquidationMetrics with imbalance and cascade detection
        """
        try:
            # Add current funding rate
            if current_funding_rate is not None:
                self.add_funding_rate(current_funding_rate)

            # Filter liquidations within window
            cutoff_time = current_timestamp - (self.window_minutes * 60 * 1000)
            recent_liquidations = [
                liq for liq in self.liquidation_history
                if liq["timestamp"] >= cutoff_time
            ]

            if not recent_liquidations:
                return self._empty_metrics()

            # 1. Calculate long vs short liquidation volume
            long_liq_volume = sum(
                liq["amount_usd"] for liq in recent_liquidations
                if liq["side"] == "long"
            )
            short_liq_volume = sum(
                liq["amount_usd"] for liq in recent_liquidations
                if liq["side"] == "short"
            )

            total_volume = long_liq_volume + short_liq_volume

            # 2. Calculate imbalance (-1 to 1)
            # Positive = more shorts liquidated (bullish)
            # Negative = more longs liquidated (bearish)
            if total_volume > 0:
                imbalance = (short_liq_volume - long_liq_volume) / total_volume
            else:
                imbalance = 0.0

            imbalance = float(np.clip(imbalance, -1.0, 1.0))

            # 3. Detect liquidation cascades
            # Cascade = multiple liquidations in short time (last 5 minutes)
            cascade_window = 5 * 60 * 1000  # 5 minutes
            cascade_cutoff = current_timestamp - cascade_window
            cascade_events = [
                liq for liq in recent_liquidations
                if liq["timestamp"] >= cascade_cutoff
            ]

            cascade_detected = len(cascade_events) >= self.cascade_threshold
            cascade_severity = min(1.0, len(cascade_events) / (self.cascade_threshold * 3))

            # 4. Funding spread analysis
            funding_spread = 0.0
            if self.funding_history and current_funding_rate is not None:
                avg_funding = np.mean(list(self.funding_history))
                funding_spread = (current_funding_rate - avg_funding) * 10000  # in bps

            # 5. Overall liquidation pressure
            # Combine imbalance, cascade, and funding signals
            pressure = imbalance * 0.5  # Imbalance contributes 50%

            # Cascade adds urgency
            if cascade_detected:
                # Liquidation cascades amplify the trend
                # If longs liquidating (negative imbalance) + cascade = more bearish
                pressure += np.sign(imbalance) * cascade_severity * 0.3

            # Funding spread confirmation
            # High positive funding + shorts liquidating = potential reversal (bearish)
            # High negative funding + longs liquidating = potential reversal (bullish)
            if abs(funding_spread) > 5.0:  # Extreme funding (>0.05%)
                funding_direction = np.sign(funding_spread)
                # Contrarian signal if liquidations oppose funding
                if np.sign(imbalance) == -funding_direction:
                    pressure += imbalance * 0.2

            pressure = float(np.clip(pressure, -1.0, 1.0))

            # 6. Confidence
            # Higher confidence with:
            # - More liquidation events
            # - Higher total volume
            # - Funding rate data available
            event_quality = min(1.0, len(recent_liquidations) / 20.0)
            volume_quality = min(1.0, total_volume / 1_000_000)  # $1M = full confidence
            funding_quality = 1.0 if self.funding_history else 0.5

            confidence = float(np.mean([event_quality, volume_quality, funding_quality]))

            logger.debug(
                "Liquidations: long=$%.0f, short=$%.0f, imbalance=%.2f, cascade=%s (%.2f), "
                "funding_spread=%.1f bps, pressure=%.2f, conf=%.2f",
                long_liq_volume, short_liq_volume, imbalance, cascade_detected,
                cascade_severity, funding_spread, pressure, confidence
            )

            return LiquidationMetrics(
                long_liquidations=long_liq_volume,
                short_liquidations=short_liq_volume,
                imbalance=imbalance,
                cascade_detected=cascade_detected,
                cascade_severity=cascade_severity,
                funding_spread=funding_spread,
                liquidation_pressure=pressure,
                confidence=confidence,
            )

        except Exception as e:
            logger.exception("Error analyzing liquidations: %s", e)
            return self._empty_metrics()

    def _empty_metrics(self) -> LiquidationMetrics:
        """Return empty metrics when no data available."""
        return LiquidationMetrics(
            long_liquidations=0.0,
            short_liquidations=0.0,
            imbalance=0.0,
            cascade_detected=False,
            cascade_severity=0.0,
            funding_spread=0.0,
            liquidation_pressure=0.0,
            confidence=0.0,
        )

    def estimate_liquidation_levels(
        self,
        current_price: float,
        leverage_levels: list[int] = [10, 20, 50, 100],
    ) -> Dict[str, list[float]]:
        """
        Estimate price levels where liquidations likely cluster.

        Args:
            current_price: Current market price
            leverage_levels: Common leverage multipliers

        Returns:
            Dictionary with "long_liquidation_levels" and "short_liquidation_levels"
        """
        long_liq_levels = []
        short_liq_levels = []

        for leverage in leverage_levels:
            # Long liquidation level (price drops by liquidation threshold)
            # Example: 10x long liquidates if price drops ~10%
            liquidation_threshold = 1.0 / leverage
            long_liq_price = current_price * (1.0 - liquidation_threshold * 0.9)
            long_liq_levels.append(long_liq_price)

            # Short liquidation level (price rises by liquidation threshold)
            short_liq_price = current_price * (1.0 + liquidation_threshold * 0.9)
            short_liq_levels.append(short_liq_price)

        return {
            "long_liquidation_levels": sorted(long_liq_levels, reverse=True),
            "short_liquidation_levels": sorted(short_liq_levels),
        }


def interpret_liquidation_signal(metrics: LiquidationMetrics) -> str:
    """
    Generate human-readable interpretation of liquidation signal.

    Args:
        metrics: LiquidationMetrics from analyze_liquidations

    Returns:
        Interpretation string
    """
    if metrics.confidence < 0.2:
        return "Insufficient liquidation data"

    interpretations = []

    # Imbalance interpretation
    if abs(metrics.imbalance) > 0.5:
        side = "longs" if metrics.imbalance < 0 else "shorts"
        strength = "Heavy" if abs(metrics.imbalance) > 0.7 else "Moderate"
        interpretations.append(f"{strength} {side} liquidation")

    # Cascade interpretation
    if metrics.cascade_detected:
        severity = "extreme" if metrics.cascade_severity > 0.7 else "moderate"
        interpretations.append(f"{severity} liquidation cascade")

    # Funding spread interpretation
    if abs(metrics.funding_spread) > 10.0:
        direction = "premium" if metrics.funding_spread > 0 else "discount"
        interpretations.append(f"extreme funding {direction}")

    # Overall pressure
    if abs(metrics.liquidation_pressure) > 0.5:
        direction = "bullish" if metrics.liquidation_pressure > 0 else "bearish"
        interpretations.append(f"{direction} pressure")

    if not interpretations:
        return "Neutral liquidation environment"

    return " | ".join(interpretations)


# Self-check for development/testing
if __name__ == "__main__":
    import sys
    import time

    logging.basicConfig(level=logging.INFO)
    logger.info("Running liquidations tracker self-check...")

    try:
        tracker = LiquidationsTracker(window_minutes=60)

        # Simulate liquidation events
        current_time = int(time.time() * 1000)

        # Add normal liquidations
        for i in range(10):
            timestamp = current_time - (60 - i) * 60 * 1000
            side = "long" if i % 2 == 0 else "short"
            amount = 50000 + np.random.randint(-10000, 10000)
            price = 50000 + np.random.randint(-500, 500)
            tracker.add_liquidation_event(timestamp, side, amount, price)

        # Add cascade (multiple longs liquidated recently)
        for i in range(6):
            timestamp = current_time - i * 30 * 1000  # Last 3 minutes
            tracker.add_liquidation_event(timestamp, "long", 100000, 49500)

        # Add funding rates
        for rate in [0.0001, 0.00015, 0.0002, 0.00025]:
            tracker.add_funding_rate(rate)

        # Analyze
        metrics = tracker.analyze_liquidations(
            current_timestamp=current_time,
            current_funding_rate=0.0003,
        )

        # Validate
        assert metrics.long_liquidations >= 0
        assert metrics.short_liquidations >= 0
        assert -1.0 <= metrics.imbalance <= 1.0
        assert 0.0 <= metrics.cascade_severity <= 1.0
        assert -1.0 <= metrics.liquidation_pressure <= 1.0
        assert 0.0 <= metrics.confidence <= 1.0

        logger.info("Liquidation metrics: %s", metrics)

        # Test interpretation
        interpretation = interpret_liquidation_signal(metrics)
        assert len(interpretation) > 0
        logger.info("Interpretation: %s", interpretation)

        # Test liquidation level estimation
        levels = tracker.estimate_liquidation_levels(current_price=50000)
        assert len(levels["long_liquidation_levels"]) > 0
        assert len(levels["short_liquidation_levels"]) > 0
        logger.info("Liquidation levels: %s", levels)

        logger.info("Self-check passed!")
        sys.exit(0)

    except Exception as e:
        logger.error("Self-check failed: %s", e)
        sys.exit(1)
