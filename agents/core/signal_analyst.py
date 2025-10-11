"""
Signal Analyst - Pure signal generation logic with no I/O dependencies.

This module provides pure functions for analyzing market data and generating
trading signals. All external dependencies (Redis, exchange APIs) are injected
via protocols, enabling easy testing with fakes.

Key principles:
- Pure functions: analyze() takes MarketData, returns list[Signal]
- No side effects: no direct Redis/network calls
- Protocol-based: dependencies injected via Protocol interfaces
- Testable: can run with fake data sources
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Protocol

from agents.core.types import MarketData, Signal, Side, SignalType, Timeframe

logger = logging.getLogger(__name__)


# ==============================================================================
# Configuration Protocol
# ==============================================================================


class AnalystConfig(Protocol):
    """Protocol for signal analyst configuration."""

    @property
    def min_confidence(self) -> float:
        """Minimum confidence threshold for signals."""
        ...

    @property
    def rsi_oversold(self) -> float:
        """RSI oversold threshold."""
        ...

    @property
    def rsi_overbought(self) -> float:
        """RSI overbought threshold."""
        ...

    @property
    def volatility_threshold(self) -> float:
        """Minimum volatility for signal generation."""
        ...


# ==============================================================================
# Data Transfer Objects
# ==============================================================================


@dataclass(frozen=True)
class AnalysisContext:
    """Context data for signal analysis."""

    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    bb_upper: Optional[Decimal] = None
    bb_lower: Optional[Decimal] = None
    bb_width: Optional[float] = None
    trend_strength: Optional[float] = None
    volume_ratio: Optional[float] = None
    sentiment_score: Optional[float] = None
    regime: str = "unknown"


# ==============================================================================
# Pure Analysis Functions
# ==============================================================================


def analyze(
    md: MarketData,
    context: AnalysisContext,
    config: AnalystConfig,
    strategy: str = "adaptive",
) -> list[Signal]:
    """Analyze market data and generate trading signals (pure function).

    This is the core signal generation logic with NO I/O operations.
    All dependencies are passed as parameters.

    Args:
        md: Market data snapshot (immutable)
        context: Analysis context with indicators (immutable)
        config: Configuration protocol
        strategy: Strategy name for signal routing

    Returns:
        List of generated signals (empty list if no signals)

    Examples:
        >>> md = MarketData(...)
        >>> ctx = AnalysisContext(rsi=30.0, ...)
        >>> signals = analyze(md, ctx, config)
        >>> if signals:
        ...     print(f"Generated {len(signals)} signals")
    """
    signals: list[Signal] = []

    # Skip if insufficient data
    if not md.bid or not md.ask or not md.last_price:
        logger.debug(f"Insufficient market data for {md.symbol}")
        return signals

    # Calculate mid price
    mid_price = (md.bid + md.ask) / Decimal("2")

    # RSI-based signals
    if context.rsi is not None:
        if context.rsi <= config.rsi_oversold:
            signal = _create_rsi_signal(
                symbol=md.symbol,
                side=Side.BUY,
                price=mid_price,
                confidence=_calculate_rsi_confidence(context.rsi, config.rsi_oversold, is_oversold=True),
                timestamp=md.timestamp,
                strategy=strategy,
                context=context,
            )
            if signal and signal.confidence >= config.min_confidence:
                signals.append(signal)

        elif context.rsi >= config.rsi_overbought:
            signal = _create_rsi_signal(
                symbol=md.symbol,
                side=Side.SELL,
                price=mid_price,
                confidence=_calculate_rsi_confidence(context.rsi, config.rsi_overbought, is_oversold=False),
                timestamp=md.timestamp,
                strategy=strategy,
                context=context,
            )
            if signal and signal.confidence >= config.min_confidence:
                signals.append(signal)

    # MACD crossover signals
    if context.macd is not None and context.macd_signal is not None:
        macd_diff = context.macd - context.macd_signal

        if abs(macd_diff) > 0.0001:  # Significant MACD divergence
            side = Side.BUY if macd_diff > 0 else Side.SELL
            confidence = min(0.95, 0.6 + abs(macd_diff) * 10)

            if confidence >= config.min_confidence:
                signal = _create_macd_signal(
                    symbol=md.symbol,
                    side=side,
                    price=mid_price,
                    confidence=confidence,
                    timestamp=md.timestamp,
                    strategy=strategy,
                    context=context,
                )
                signals.append(signal)

    # Bollinger Bands signals
    if context.bb_upper and context.bb_lower and md.last_price:
        if md.last_price <= context.bb_lower:
            # Price at lower band - potential bounce
            signal = _create_bb_signal(
                symbol=md.symbol,
                side=Side.BUY,
                price=mid_price,
                confidence=0.7,
                timestamp=md.timestamp,
                strategy=strategy,
                context=context,
                notes="Price at lower Bollinger Band",
            )
            if signal.confidence >= config.min_confidence:
                signals.append(signal)

        elif md.last_price >= context.bb_upper:
            # Price at upper band - potential reversal
            signal = _create_bb_signal(
                symbol=md.symbol,
                side=Side.SELL,
                price=mid_price,
                confidence=0.7,
                timestamp=md.timestamp,
                strategy=strategy,
                context=context,
                notes="Price at upper Bollinger Band",
            )
            if signal.confidence >= config.min_confidence:
                signals.append(signal)

    # Trend-following signals (regime-based)
    if context.trend_strength and context.trend_strength > 0.7:
        trend_signal = _create_trend_signal(
            symbol=md.symbol,
            price=mid_price,
            timestamp=md.timestamp,
            strategy=strategy,
            context=context,
        )
        if trend_signal and trend_signal.confidence >= config.min_confidence:
            signals.append(trend_signal)

    return signals


def _create_rsi_signal(
    symbol: str,
    side: Side,
    price: Decimal,
    confidence: float,
    timestamp: float,
    strategy: str,
    context: AnalysisContext,
) -> Signal:
    """Create RSI-based signal with risk parameters."""
    return Signal(
        symbol=symbol,
        side=side,
        confidence=confidence,
        price=price,
        timestamp=timestamp,
        strategy=strategy,
        signal_type=SignalType.MEAN_REVERSION,
        stop_loss_bps=150,  # 1.5% stop loss
        take_profit_bps=[100, 200],  # 1%, 2% targets
        ttl_seconds=300,  # 5 minutes
        features={
            "rsi": context.rsi or 0.0,
            "macd": context.macd or 0.0,
            "bb_width": context.bb_width or 0.0,
        },
        notes=f"RSI {side.value} signal (RSI={context.rsi:.1f})" if context.rsi else f"RSI {side.value} signal",
        source="signal_analyst",
    )


def _create_macd_signal(
    symbol: str,
    side: Side,
    price: Decimal,
    confidence: float,
    timestamp: float,
    strategy: str,
    context: AnalysisContext,
) -> Signal:
    """Create MACD-based signal with risk parameters."""
    return Signal(
        symbol=symbol,
        side=side,
        confidence=confidence,
        price=price,
        timestamp=timestamp,
        strategy=strategy,
        signal_type=SignalType.TREND,
        stop_loss_bps=200,  # 2% stop loss
        take_profit_bps=[150, 300, 450],  # 1.5%, 3%, 4.5% targets
        ttl_seconds=600,  # 10 minutes
        features={
            "macd": context.macd or 0.0,
            "macd_signal": context.macd_signal or 0.0,
            "macd_diff": (context.macd or 0.0) - (context.macd_signal or 0.0),
        },
        notes=f"MACD {side.value} crossover",
        source="signal_analyst",
    )


def _create_bb_signal(
    symbol: str,
    side: Side,
    price: Decimal,
    confidence: float,
    timestamp: float,
    strategy: str,
    context: AnalysisContext,
    notes: str,
) -> Signal:
    """Create Bollinger Band signal with risk parameters."""
    return Signal(
        symbol=symbol,
        side=side,
        confidence=confidence,
        price=price,
        timestamp=timestamp,
        strategy=strategy,
        signal_type=SignalType.MEAN_REVERSION,
        stop_loss_bps=100,  # 1% stop loss (tight for BB bounce)
        take_profit_bps=[75, 150],  # 0.75%, 1.5% targets
        ttl_seconds=180,  # 3 minutes (quick reversal play)
        features={
            "bb_width": context.bb_width or 0.0,
            "bb_upper": float(context.bb_upper) if context.bb_upper else 0.0,
            "bb_lower": float(context.bb_lower) if context.bb_lower else 0.0,
        },
        notes=notes,
        source="signal_analyst",
    )


def _create_trend_signal(
    symbol: str,
    price: Decimal,
    timestamp: float,
    strategy: str,
    context: AnalysisContext,
) -> Optional[Signal]:
    """Create trend-following signal based on regime."""
    if not context.trend_strength:
        return None

    # Determine side from regime
    if context.regime in ("strong_uptrend", "uptrend"):
        side = Side.BUY
        confidence = 0.75
    elif context.regime in ("strong_downtrend", "downtrend"):
        side = Side.SELL
        confidence = 0.75
    else:
        return None  # No clear trend

    return Signal(
        symbol=symbol,
        side=side,
        confidence=confidence,
        price=price,
        timestamp=timestamp,
        strategy=strategy,
        signal_type=SignalType.TREND,
        stop_loss_bps=250,  # 2.5% stop loss (wider for trend)
        take_profit_bps=[200, 400, 600],  # 2%, 4%, 6% targets
        ttl_seconds=900,  # 15 minutes
        features={
            "trend_strength": context.trend_strength,
            "regime": context.regime,
        },
        notes=f"Trend {side.value} ({context.regime})",
        source="signal_analyst",
    )


def _calculate_rsi_confidence(rsi: float, threshold: float, is_oversold: bool) -> float:
    """Calculate confidence based on RSI distance from threshold.

    Args:
        rsi: Current RSI value
        threshold: RSI threshold (oversold or overbought)
        is_oversold: True if checking oversold, False for overbought

    Returns:
        Confidence value [0.5, 1.0]
    """
    if is_oversold:
        # Lower RSI = higher confidence for buy
        distance = threshold - rsi
        confidence = 0.6 + min(0.35, distance / 30.0)  # Max 0.95
    else:
        # Higher RSI = higher confidence for sell
        distance = rsi - threshold
        confidence = 0.6 + min(0.35, distance / 30.0)  # Max 0.95

    return max(0.5, min(0.95, confidence))


# ==============================================================================
# Batch Analysis
# ==============================================================================


def analyze_batch(
    market_data_batch: list[MarketData],
    context_provider: Any,  # Protocol for getting analysis context
    config: AnalystConfig,
    strategy: str = "adaptive",
) -> dict[str, list[Signal]]:
    """Analyze multiple symbols in batch (pure function).

    Args:
        market_data_batch: List of market data snapshots
        context_provider: Provider for analysis context (Protocol)
        config: Configuration protocol
        strategy: Strategy name

    Returns:
        Dictionary mapping symbol to list of signals
    """
    results: dict[str, list[Signal]] = {}

    for md in market_data_batch:
        try:
            # Get context from provider
            context = context_provider.get_context(md.symbol)

            # Analyze and generate signals
            signals = analyze(md, context, config, strategy)

            if signals:
                results[md.symbol] = signals

        except Exception as e:
            logger.error(f"Error analyzing {md.symbol}: {e}")
            continue

    return results


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "analyze",
    "analyze_batch",
    "AnalysisContext",
    "AnalystConfig",
]
