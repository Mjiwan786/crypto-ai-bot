"""
Pure functions for order flow analysis.

This module contains stateless, deterministic functions for analyzing trade flow
and market microstructure. All functions are pure - same inputs produce same outputs
with no side effects or external dependencies (no Redis, no HTTP, no logging).

Key principles:
- Pure functions: deterministic, no side effects
- Explicit parameters: all inputs passed as arguments
- Immutable data: inputs not modified
- Type safety: comprehensive type hints
- Testability: 100% unit testable without I/O

Usage:
    from agents.scalper.analysis.order_flow_pure import (
        calculate_flow_metrics,
        classify_trade_direction,
        generate_flow_signal
    )

    # Pure function - deterministic output
    metrics = calculate_flow_metrics(trades, window_seconds, config)
    direction = classify_trade_direction(price, last_price, side)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .order_flow import (
    FlowMetrics,
    FlowSignal,
    OrderFlowConfig,
    TradeDirection,
    TradeEvent,
)


# ======================== Parameter Models ========================


@dataclass(frozen=True)
class WindowMetricsParams:
    """Immutable parameters for window metrics calculation"""

    large_trade_btc: float = 0.5
    price_improvement_threshold_bps: float = 0.5
    strong_imbalance_threshold: float = 0.7
    weak_imbalance_threshold: float = 0.3


@dataclass(frozen=True)
class FlowSignalWeights:
    """Immutable weights for flow signal generation"""

    volume_weight: float = 0.4
    trade_weight: float = 0.3
    price_weight: float = 0.2
    size_weight: float = 0.1


# ======================== Core Pure Functions ========================


def classify_trade_direction(
    price: float,
    last_price: Optional[float],
    side: Optional[str],
) -> TradeDirection:
    """
    Classify trade direction using tick rule and side indication.

    Pure function - deterministic classification with no side effects.

    Args:
        price: Current trade price
        last_price: Previous trade price (None if no history)
        side: Trade side from exchange ('b'/'buy', 's'/'sell', or None)

    Returns:
        TradeDirection enum (BUY, SELL, or UNKNOWN)

    Example:
        >>> direction = classify_trade_direction(50000.0, 49990.0, None)
        >>> print(direction)  # TradeDirection.BUY (price increased)
    """
    # Method 1: Direct side indication (most reliable if available)
    if side:
        side_lower = side.lower()
        if side_lower in {"b", "buy"}:
            return TradeDirection.BUY
        if side_lower in {"s", "sell"}:
            return TradeDirection.SELL

    # Method 2: Tick rule (compare to last price)
    if last_price is not None:
        if price > last_price:
            return TradeDirection.BUY
        if price < last_price:
            return TradeDirection.SELL

    # Unable to determine direction
    return TradeDirection.UNKNOWN


def calculate_flow_metrics(
    trades: List[TradeEvent],
    window_seconds: int,
    pair: str,
    params: WindowMetricsParams = WindowMetricsParams(),
    signal_weights: FlowSignalWeights = FlowSignalWeights(),
) -> Optional[FlowMetrics]:
    """
    Calculate comprehensive order flow metrics for a time window.

    Pure function - deterministic calculation with no side effects.

    Args:
        trades: List of TradeEvent objects (chronologically ordered)
        window_seconds: Time window in seconds
        pair: Trading pair symbol
        params: Parameters for metrics calculation
        signal_weights: Weights for flow signal generation

    Returns:
        FlowMetrics object or None if insufficient data

    Example:
        >>> trades = [trade1, trade2, trade3]
        >>> metrics = calculate_flow_metrics(trades, 60, "BTC/USD")
        >>> print(f"Volume imbalance: {metrics.volume_imbalance:.2f}")
    """
    if not trades:
        return None

    total_trades = len(trades)

    # Basic counts
    buy_trades = sum(1 for t in trades if t.direction == TradeDirection.BUY)
    sell_trades = sum(1 for t in trades if t.direction == TradeDirection.SELL)

    # Volume analysis
    total_volume = float(sum(t.volume for t in trades))
    buy_volume = float(sum(t.volume for t in trades if t.direction == TradeDirection.BUY))
    sell_volume = float(sum(t.volume for t in trades if t.direction == TradeDirection.SELL))

    # Imbalances
    denom_vol = (buy_volume + sell_volume) or 1e-8
    volume_imbalance = (buy_volume - sell_volume) / denom_vol

    denom_trd = total_trades or 1e-8
    trade_imbalance = (buy_trades - sell_trades) / denom_trd

    # VWAP calculation
    total_notional = float(sum(t.price * t.volume for t in trades))
    vwap = total_notional / total_volume if total_volume > 0.0 else 0.0

    # Price change (first to last trade)
    if total_trades >= 2:
        price_change = trades[-1].price - trades[0].price
        price_change_bps = (
            (price_change / trades[0].price) * 10000.0 if trades[0].price else 0.0
        )
    else:
        price_change = 0.0
        price_change_bps = 0.0

    # Size analysis
    avg_trade_size = total_volume / total_trades if total_trades > 0 else 0.0
    large_trades = [t for t in trades if t.volume >= params.large_trade_btc]
    large_trade_count = len(large_trades)
    large_trade_volume = float(sum(t.volume for t in large_trades))

    # Microstructure metrics
    microstructure = _calculate_microstructure_metrics(trades, params)

    # Flow signal generation
    large_trade_ratio = (large_trade_volume / total_volume) if total_volume > 0 else 0.0
    flow_signal, flow_strength = generate_flow_signal(
        volume_imbalance,
        trade_imbalance,
        price_change_bps,
        large_trade_ratio,
        params,
        signal_weights,
    )

    return FlowMetrics(
        timestamp=trades[-1].timestamp,  # Use last trade timestamp
        pair=pair,
        window_seconds=window_seconds,
        total_volume=total_volume,
        buy_volume=buy_volume,
        sell_volume=sell_volume,
        volume_imbalance=volume_imbalance,
        total_trades=total_trades,
        buy_trades=buy_trades,
        sell_trades=sell_trades,
        trade_imbalance=trade_imbalance,
        vwap=vwap,
        price_change=float(price_change),
        price_change_bps=float(price_change_bps),
        avg_trade_size=float(avg_trade_size),
        large_trade_count=large_trade_count,
        large_trade_volume=large_trade_volume,
        flow_signal=flow_signal,
        flow_strength=float(flow_strength),
        tick_direction_sum=microstructure["tick_direction_sum"],
        price_improvement_events=microstructure["price_improvement_events"],
        aggressive_trade_ratio=microstructure["aggressive_trade_ratio"],
    )


def generate_flow_signal(
    volume_imbalance: float,
    trade_imbalance: float,
    price_change_bps: float,
    large_trade_ratio: float,
    params: WindowMetricsParams = WindowMetricsParams(),
    weights: FlowSignalWeights = FlowSignalWeights(),
) -> Tuple[FlowSignal, float]:
    """
    Generate order flow signal from multiple factors.

    Pure function - deterministic signal generation with no side effects.

    Args:
        volume_imbalance: Volume imbalance ratio [-1, 1]
        trade_imbalance: Trade count imbalance ratio [-1, 1]
        price_change_bps: Price change in basis points
        large_trade_ratio: Ratio of large trade volume to total [0, 1]
        params: Parameters with imbalance thresholds
        weights: Weights for signal components

    Returns:
        Tuple of (FlowSignal, strength) where strength is in [0, 1]

    Example:
        >>> signal, strength = generate_flow_signal(0.8, 0.6, 5.0, 0.3)
        >>> print(signal)  # FlowSignal.STRONG_BUY
    """
    # Calculate weighted components (all scaled to [-1, 1])
    volume_score = float(volume_imbalance)
    trade_score = float(trade_imbalance)
    price_score = float(np.tanh(price_change_bps / 10.0))  # Smooth clamp
    size_score = float(large_trade_ratio * 2.0 - 1.0)  # Map [0,1] -> [-1,1]

    # Weighted flow score
    flow_score = (
        weights.volume_weight * volume_score
        + weights.trade_weight * trade_score
        + weights.price_weight * price_score
        + weights.size_weight * size_score
    )

    # Flow strength (absolute value, clamped to [0, 1])
    flow_strength = min(1.0, max(0.0, abs(flow_score)))

    # Signal classification
    if flow_score >= params.strong_imbalance_threshold:
        return FlowSignal.STRONG_BUY, flow_strength
    if flow_score >= params.weak_imbalance_threshold:
        return FlowSignal.WEAK_BUY, flow_strength
    if flow_score <= -params.strong_imbalance_threshold:
        return FlowSignal.STRONG_SELL, flow_strength
    if flow_score <= -params.weak_imbalance_threshold:
        return FlowSignal.WEAK_SELL, flow_strength

    return FlowSignal.NEUTRAL, flow_strength


def detect_block_trades(
    trades: List[TradeEvent],
    block_threshold_btc: float = 2.0,
) -> List[TradeEvent]:
    """
    Detect block trades (large institutional trades) from trade list.

    Pure function - deterministic filtering with no side effects.

    Args:
        trades: List of TradeEvent objects
        block_threshold_btc: Minimum size to classify as block trade (default 2.0 BTC)

    Returns:
        List of TradeEvent objects that are block trades (sorted by timestamp desc)

    Example:
        >>> blocks = detect_block_trades(trades, block_threshold_btc=2.0)
        >>> print(f"Found {len(blocks)} block trades")
    """
    block_trades = [t for t in trades if t.volume >= block_threshold_btc]
    return sorted(block_trades, key=lambda x: x.timestamp, reverse=True)


def calculate_whale_metrics(
    trades: List[TradeEvent],
    whale_threshold_btc: float = 10.0,
) -> Dict[str, float]:
    """
    Calculate whale trading activity metrics.

    Pure function - deterministic calculation with no side effects.

    Args:
        trades: List of TradeEvent objects
        whale_threshold_btc: Minimum size to classify as whale trade (default 10.0 BTC)

    Returns:
        Dictionary with whale metrics (empty dict if no whale trades)

    Example:
        >>> whale_stats = calculate_whale_metrics(trades, whale_threshold_btc=10.0)
        >>> print(f"Whale imbalance: {whale_stats.get('whale_imbalance', 0):.2f}")
    """
    whale_trades = [t for t in trades if t.volume >= whale_threshold_btc]

    if not whale_trades:
        return {}

    total_whale_volume = float(sum(t.volume for t in whale_trades))
    whale_buy_volume = float(
        sum(t.volume for t in whale_trades if t.direction == TradeDirection.BUY)
    )
    whale_sell_volume = float(
        sum(t.volume for t in whale_trades if t.direction == TradeDirection.SELL)
    )

    denom = (whale_buy_volume + whale_sell_volume) or 1e-8
    whale_imbalance = (whale_buy_volume - whale_sell_volume) / denom

    return {
        "total_whale_volume": total_whale_volume,
        "whale_buy_volume": whale_buy_volume,
        "whale_sell_volume": whale_sell_volume,
        "whale_imbalance": whale_imbalance,
        "whale_trade_count": float(len(whale_trades)),
    }


def calculate_volume_profile(
    trades: List[TradeEvent],
    price_buckets: int = 20,
) -> Dict[float, float]:
    """
    Calculate volume profile (volume at price levels).

    Pure function - deterministic bucketing with no side effects.

    Args:
        trades: List of TradeEvent objects
        price_buckets: Number of price buckets (default 20)

    Returns:
        Dictionary mapping bucket price to volume

    Example:
        >>> profile = calculate_volume_profile(trades, price_buckets=20)
        >>> for price, volume in sorted(profile.items()):
        ...     print(f"{price:.2f}: {volume:.4f} BTC")
    """
    if not trades:
        return {}

    prices = [t.price for t in trades]
    min_price, max_price = min(prices), max(prices)

    # Single-price edge case
    if min_price == max_price:
        return {float(min_price): float(sum(t.volume for t in trades))}

    # Guard bucket sizing
    price_buckets = max(1, int(price_buckets))
    bucket_size = (max_price - min_price) / float(price_buckets)

    if bucket_size <= 0:
        return {float(min_price): float(sum(t.volume for t in trades))}

    volume_profile: Dict[float, float] = {}
    for trade in trades:
        idx = int((trade.price - min_price) / bucket_size)
        if idx >= price_buckets:
            idx = price_buckets - 1
        bucket_price = min_price + idx * bucket_size

        if bucket_price not in volume_profile:
            volume_profile[bucket_price] = 0.0
        volume_profile[bucket_price] += float(trade.volume)

    return volume_profile


def is_flow_favorable_for_scalping(
    short_flow: Optional[FlowMetrics],
    medium_flow: Optional[FlowMetrics],
    flow_strength_threshold: float = 0.6,
) -> Tuple[bool, str]:
    """
    Determine if current order flow is favorable for scalping.

    Pure function - deterministic evaluation with no side effects.

    Args:
        short_flow: Short-term flow metrics (e.g., 30s window)
        medium_flow: Medium-term flow metrics (e.g., 60s window)
        flow_strength_threshold: Minimum flow strength for favorable conditions

    Returns:
        Tuple of (is_favorable, reason)

    Example:
        >>> is_favorable, reason = is_flow_favorable_for_scalping(short, medium)
        >>> print(f"Favorable: {is_favorable}, Reason: {reason}")
    """
    if not short_flow or not medium_flow:
        return False, "Insufficient flow data"

    # Strong momentum across timeframes
    if short_flow.flow_signal in {FlowSignal.STRONG_BUY, FlowSignal.STRONG_SELL}:
        if medium_flow.flow_signal in {FlowSignal.STRONG_BUY, FlowSignal.STRONG_SELL}:
            return True, f"Strong directional flow: {short_flow.flow_signal.value}"
        # Short-term spike without medium support
        return False, "Conflicting flow signals across timeframes"

    # Excessive short-term volatility
    if abs(short_flow.price_change_bps) > 50.0:
        return False, f"Excessive short-term volatility: {short_flow.price_change_bps:.1f} bps"

    # Trade activity sufficiency
    if short_flow.total_trades < 5:
        return False, "Insufficient trade activity"

    # Balanced flow for mean reversion
    if abs(short_flow.volume_imbalance) < 0.3 and abs(medium_flow.volume_imbalance) < 0.3:
        return True, "Balanced flow suitable for mean reversion"

    # Consistent direction with adequate strength
    if (
        short_flow.flow_signal == medium_flow.flow_signal
        and short_flow.flow_strength > flow_strength_threshold
    ):
        return True, f"Consistent {short_flow.flow_signal.value} flow"

    return False, "No clear scalping opportunity in flow"


# ======================== Internal Helpers ========================


def _calculate_microstructure_metrics(
    trades: List[TradeEvent],
    params: WindowMetricsParams,
) -> Dict[str, int | float]:
    """
    Calculate market microstructure metrics from trade sequence.

    Pure function - internal helper for microstructure analysis.
    """
    tick_direction_sum = 0
    price_improvement_events = 0
    aggressive_trades = 0

    for i, trade in enumerate(trades):
        if i > 0:
            prev_price = trades[i - 1].price

            # Tick direction
            if trade.price > prev_price:
                tick_direction_sum += 1
            elif trade.price < prev_price:
                tick_direction_sum -= 1

            # Price improvement detection
            if prev_price > 0:
                price_diff_bps = abs(trade.price - prev_price) / prev_price * 10000.0
                if price_diff_bps > params.price_improvement_threshold_bps:
                    price_improvement_events += 1

        # Aggressive trade detection
        if trade.order_type == "market":
            aggressive_trades += 1

    total_trades = len(trades)
    aggressive_trade_ratio = aggressive_trades / total_trades if total_trades > 0 else 0.0

    return {
        "tick_direction_sum": int(tick_direction_sum),
        "price_improvement_events": int(price_improvement_events),
        "aggressive_trade_ratio": float(aggressive_trade_ratio),
    }
