"""
Signal Processor - Pure signal enrichment and routing (NO I/O).

Provides pure functions for:
1. enrich(signals) -> signals with added metadata
2. route(signals) -> dict mapping strategy -> signals

No Redis, no network calls in core functions.
Use separate adapter for I/O.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Protocol

from agents.core.types import Signal, SignalType

logger = logging.getLogger(__name__)


# ==============================================================================
# Configuration Protocol
# ==============================================================================


class ProcessorConfig(Protocol):
    """Protocol for signal processor configuration."""

    @property
    def min_confidence(self) -> float:
        """Minimum confidence for signal pass-through."""
        ...

    @property
    def quality_boost_threshold(self) -> float:
        """Confidence threshold for quality boost."""
        ...

    def get_strategy_for_signal_type(self, signal_type: SignalType) -> str:
        """Map signal type to strategy name."""
        ...


# ==============================================================================
# Pure Enrichment Functions
# ==============================================================================


def enrich(signals: list[Signal], config: ProcessorConfig) -> list[Signal]:
    """Enrich signals with metadata and quality scores (pure function).

    Args:
        signals: Input signals to enrich
        config: Configuration protocol

    Returns:
        Enriched signals with updated metadata
    """
    enriched: list[Signal] = []

    for sig in signals:
        # Filter low confidence
        if sig.confidence < config.min_confidence:
            logger.debug(f"Filtered signal {sig.symbol} (confidence {sig.confidence:.2f} < {config.min_confidence})")
            continue

        # Apply quality boost
        boosted_confidence = sig.confidence
        if sig.confidence >= config.quality_boost_threshold:
            boosted_confidence = min(1.0, sig.confidence * 1.1)
            logger.debug(f"Quality boost: {sig.confidence:.2f} -> {boosted_confidence:.2f}")

        # Create enriched signal
        enriched_sig = replace(
            sig,
            confidence=boosted_confidence,
            features={
                **sig.features,
                "enriched": True,
                "original_confidence": sig.confidence,
            },
        )

        enriched.append(enriched_sig)

    return enriched


def route(signals: list[Signal], config: ProcessorConfig) -> dict[str, list[Signal]]:
    """Route signals to strategies (pure function).

    Args:
        signals: Signals to route
        config: Configuration protocol

    Returns:
        Dictionary mapping strategy name -> list of signals
    """
    routes: dict[str, list[Signal]] = {}

    for sig in signals:
        # Determine target strategy
        if sig.signal_type == SignalType.SCALP:
            strategy = "scalp"
        elif sig.signal_type == SignalType.TREND:
            strategy = "trend_following"
        elif sig.signal_type == SignalType.BREAKOUT:
            strategy = "breakout"
        elif sig.signal_type == SignalType.MEAN_REVERSION:
            strategy = "sideways"
        else:
            strategy = config.get_strategy_for_signal_type(sig.signal_type)

        # Add to route
        if strategy not in routes:
            routes[strategy] = []
        routes[strategy].append(sig)

    return routes


# ==============================================================================
# Combined Processing
# ==============================================================================


def process(signals: list[Signal], config: ProcessorConfig) -> dict[str, list[Signal]]:
    """Enrich and route signals in one step (pure function).

    Args:
        signals: Input signals
        config: Configuration protocol

    Returns:
        Dictionary mapping strategy -> enriched signals
    """
    enriched = enrich(signals, config)
    return route(enriched, config)


# ==============================================================================
# Example Config Implementation
# ==============================================================================


@dataclass
class SimpleConfig:
    """Simple configuration for testing."""

    min_confidence: float = 0.6
    quality_boost_threshold: float = 0.8

    def get_strategy_for_signal_type(self, signal_type: SignalType) -> str:
        """Map signal type to strategy."""
        mapping = {
            SignalType.ENTRY: "default",
            SignalType.EXIT: "default",
            SignalType.SCALP: "scalp",
            SignalType.TREND: "trend_following",
            SignalType.BREAKOUT: "breakout",
            SignalType.MEAN_REVERSION: "sideways",
        }
        return mapping.get(signal_type, "default")


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "enrich",
    "route",
    "process",
    "ProcessorConfig",
    "SimpleConfig",
]
