"""
Pure functions for liquidity analysis.

This module contains stateless, deterministic functions for analyzing order book
liquidity. All functions are pure - same inputs produce same outputs with no side
effects or external dependencies (no Redis, no HTTP, no logging).

Key principles:
- Pure functions: deterministic, no side effects
- Explicit parameters: all inputs passed as arguments
- Immutable data: inputs not modified
- Type safety: comprehensive type hints
- Testability: 100% unit testable without I/O

Usage:
    from agents.scalper.analysis.liquidity_pure import (
        calculate_liquidity_metrics,
        estimate_market_impact,
        calculate_optimal_order_size
    )

    # Pure function - deterministic output
    metrics = calculate_liquidity_metrics(orderbook, depth_levels=10)
    impact = estimate_market_impact(orderbook, "buy", 0.5, impact_params)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .liquidity import (
    LiquidityMetrics,
    LiquidityRegime,
    OrderBookLevel,
    OrderBookSnapshot,
)


# ======================== Parameter Models ========================


@dataclass(frozen=True)
class ImpactModelParams:
    """Immutable parameters for market impact estimation"""

    linear_coefficient: float = 0.1  # bps per BTC
    sqrt_coefficient: float = 0.5  # sqrt impact
    temp_impact_decay: float = 0.95  # temporary impact decay (reserved)


@dataclass(frozen=True)
class RegimeThresholds:
    """Immutable thresholds for regime classification"""

    abundant_spread_bps: float = 2.0
    abundant_depth_btc: float = 10.0
    normal_spread_bps: float = 5.0
    normal_depth_btc: float = 5.0
    constrained_spread_bps: float = 10.0
    constrained_depth_btc: float = 2.0
    scarce_spread_bps: float = 20.0
    scarce_depth_btc: float = 1.0
    stressed_spread_bps: float = 50.0
    stressed_depth_btc: float = 0.5


@dataclass(frozen=True)
class MarketImpactEstimate:
    """Result of market impact estimation"""

    temporary_impact_bps: float
    permanent_impact_bps: float
    effective_spread_bps: float
    total_impact_bps: float


@dataclass(frozen=True)
class OptimalSizeResult:
    """Result of optimal order size calculation"""

    optimal_size_btc: float
    max_safe_size_btc: float
    impact_at_optimal_bps: float


# ======================== Core Pure Functions ========================


def calculate_liquidity_metrics(
    orderbook: OrderBookSnapshot,
    depth_levels: int = 10,
    impact_params: ImpactModelParams = ImpactModelParams(),
    regime_thresholds: RegimeThresholds = RegimeThresholds(),
) -> LiquidityMetrics:
    """
    Calculate comprehensive liquidity metrics from an order book snapshot.

    Pure function - deterministic output with no side effects.

    Args:
        orderbook: Order book snapshot to analyze
        depth_levels: Number of price levels to analyze (default 10)
        impact_params: Parameters for market impact model
        regime_thresholds: Thresholds for regime classification

    Returns:
        LiquidityMetrics with all calculated metrics

    Example:
        >>> orderbook = OrderBookSnapshot(...)
        >>> metrics = calculate_liquidity_metrics(orderbook, depth_levels=10)
        >>> print(f"Spread: {metrics.spread_bps:.2f} bps")
    """
    # Normalize orderbook (ensure sorted, non-negative)
    normalized_ob = _normalize_orderbook(orderbook)

    # Calculate layered metrics
    basic_metrics = _calculate_basic_metrics(normalized_ob, depth_levels)
    advanced_metrics = _calculate_advanced_metrics(normalized_ob, depth_levels, impact_params)
    imbalance_metrics = _calculate_imbalance_metrics(normalized_ob, depth_levels)

    # Regime classification
    regime, confidence = _classify_regime(
        basic_metrics["spread_bps"],
        basic_metrics["total_depth_btc"],
        regime_thresholds,
    )

    return LiquidityMetrics(
        symbol=normalized_ob.symbol,
        timestamp=normalized_ob.timestamp,
        spread_bps=basic_metrics["spread_bps"],
        bid_depth_btc=basic_metrics["bid_depth_btc"],
        ask_depth_btc=basic_metrics["ask_depth_btc"],
        total_depth_btc=basic_metrics["total_depth_btc"],
        effective_spread_bps=advanced_metrics["effective_spread_bps"],
        price_impact_bps=advanced_metrics["price_impact_bps"],
        market_depth_score=advanced_metrics["market_depth_score"],
        liquidity_score=advanced_metrics["liquidity_score"],
        book_imbalance=imbalance_metrics["book_imbalance"],
        depth_imbalance=imbalance_metrics["depth_imbalance"],
        spread_volatility=0.0,  # Requires historical data (computed externally)
        depth_volatility=0.0,  # Requires historical data (computed externally)
        liquidity_regime=regime,
        regime_confidence=confidence,
    )


def estimate_market_impact(
    orderbook: OrderBookSnapshot,
    side: str,
    size_btc: float,
    impact_params: ImpactModelParams = ImpactModelParams(),
) -> MarketImpactEstimate:
    """
    Estimate market impact for a given order size.

    Pure function - deterministic calculation with no side effects.

    Args:
        orderbook: Order book snapshot
        side: Order side ('buy' or 'sell')
        size_btc: Order size in BTC
        impact_params: Parameters for impact model

    Returns:
        MarketImpactEstimate with breakdown of impact components

    Example:
        >>> impact = estimate_market_impact(orderbook, "buy", 0.5)
        >>> print(f"Total impact: {impact.total_impact_bps:.2f} bps")
    """
    normalized_ob = _normalize_orderbook(orderbook)

    # Select side of book to walk
    levels = normalized_ob.asks if side == "buy" else normalized_ob.bids

    if not levels:
        # Empty book - return high impact estimates
        return MarketImpactEstimate(
            temporary_impact_bps=10.0,
            permanent_impact_bps=5.0,
            effective_spread_bps=10.0,
            total_impact_bps=15.0,
        )

    # Calculate impact components
    temporary_impact = _calculate_temporary_impact(levels, size_btc)
    permanent_impact = _calculate_permanent_impact(size_btc, normalized_ob.spread_bps, impact_params)
    effective_spread = _calculate_effective_spread(levels, size_btc)

    return MarketImpactEstimate(
        temporary_impact_bps=temporary_impact,
        permanent_impact_bps=permanent_impact,
        effective_spread_bps=effective_spread,
        total_impact_bps=temporary_impact + permanent_impact,
    )


def calculate_optimal_order_size(
    orderbook: OrderBookSnapshot,
    side: str,
    max_impact_bps: float = 5.0,
    impact_params: ImpactModelParams = ImpactModelParams(),
) -> OptimalSizeResult:
    """
    Calculate optimal order size under a total impact constraint using binary search.

    Pure function - deterministic output with no side effects.

    Args:
        orderbook: Order book snapshot
        side: Order side ('buy' or 'sell')
        max_impact_bps: Maximum acceptable total impact in bps (default 5.0)
        impact_params: Parameters for impact model

    Returns:
        OptimalSizeResult with optimal size and impact metrics

    Example:
        >>> result = calculate_optimal_order_size(orderbook, "buy", max_impact_bps=5.0)
        >>> print(f"Optimal size: {result.optimal_size_btc:.4f} BTC")
    """
    normalized_ob = _normalize_orderbook(orderbook)

    # Binary search for optimal size
    low, high = 0.01, 5.0
    optimal = low

    for _ in range(22):  # ~2^22 precision
        mid = (low + high) / 2.0
        impact = estimate_market_impact(normalized_ob, side, mid, impact_params)

        if impact.total_impact_bps <= max_impact_bps:
            optimal = mid
            low = mid
        else:
            high = mid

        if (high - low) < 1e-3:
            break

    # Find max safe size (up to 2x constraint)
    max_safe = optimal
    probe = optimal
    while probe <= 10.0:
        impact = estimate_market_impact(normalized_ob, side, probe, impact_params)
        if impact.total_impact_bps > max_impact_bps * 2.0:
            break
        max_safe = probe
        probe += 0.1

    # Calculate impact at optimal
    impact_at_optimal = estimate_market_impact(normalized_ob, side, optimal, impact_params)

    return OptimalSizeResult(
        optimal_size_btc=round(optimal, 6),
        max_safe_size_btc=round(max_safe, 6),
        impact_at_optimal_bps=impact_at_optimal.total_impact_bps,
    )


def calculate_stability_metrics(
    metrics_history: List[LiquidityMetrics],
) -> Dict[str, float]:
    """
    Calculate liquidity stability metrics from historical metrics.

    Pure function - requires historical data passed as input.

    Args:
        metrics_history: List of historical LiquidityMetrics (chronological order)

    Returns:
        Dictionary with spread_volatility and depth_volatility

    Example:
        >>> history = [metrics1, metrics2, metrics3, ...]
        >>> stability = calculate_stability_metrics(history[-20:])
        >>> print(f"Spread vol: {stability['spread_volatility']:.2f}")
    """
    if len(metrics_history) < 10:
        return {"spread_volatility": 0.0, "depth_volatility": 0.0}

    spreads = [m.spread_bps for m in metrics_history]
    depths = [m.total_depth_btc for m in metrics_history]

    spread_volatility = 0.0
    if len(spreads) > 1:
        spread_volatility = statistics.stdev(spreads)

    depth_volatility = 0.0
    mean_depth = statistics.mean(depths) if depths else 0.0
    if len(depths) > 1 and mean_depth > 0:
        depth_volatility = statistics.stdev(depths) / mean_depth

    return {
        "spread_volatility": spread_volatility,
        "depth_volatility": depth_volatility,
    }


# ======================== Internal Helpers ========================


def _normalize_orderbook(orderbook: OrderBookSnapshot) -> OrderBookSnapshot:
    """
    Normalize orderbook: sort levels and ensure non-negative values.

    Bids sorted descending by price, asks sorted ascending by price.
    """
    bids = sorted(
        [
            OrderBookLevel(
                price=max(0.0, level.price),
                size=max(0.0, level.size),
                timestamp=level.timestamp,
            )
            for level in orderbook.bids
        ],
        key=lambda x: x.price,
        reverse=True,
    )
    asks = sorted(
        [
            OrderBookLevel(
                price=max(0.0, level.price),
                size=max(0.0, level.size),
                timestamp=level.timestamp,
            )
            for level in orderbook.asks
        ],
        key=lambda x: x.price,
    )
    return OrderBookSnapshot(
        symbol=orderbook.symbol,
        bids=bids,
        asks=asks,
        timestamp=orderbook.timestamp,
    )


def _calculate_basic_metrics(
    orderbook: OrderBookSnapshot,
    depth_levels: int,
) -> Dict[str, float]:
    """Calculate basic liquidity metrics (spread, depth)"""
    bid_depth = sum(level.size for level in orderbook.bids[:depth_levels])
    ask_depth = sum(level.size for level in orderbook.asks[:depth_levels])

    return {
        "spread_bps": orderbook.spread_bps,
        "bid_depth_btc": bid_depth,
        "ask_depth_btc": ask_depth,
        "total_depth_btc": bid_depth + ask_depth,
    }


def _calculate_advanced_metrics(
    orderbook: OrderBookSnapshot,
    depth_levels: int,
    impact_params: ImpactModelParams,
) -> Dict[str, float]:
    """Calculate advanced liquidity metrics (impact, scores)"""
    # Estimate impact at typical size (0.1 BTC)
    typical_size = 0.1
    impact = estimate_market_impact(orderbook, "buy", typical_size, impact_params)

    # Calculate depth score
    total_depth = sum(level.size for level in orderbook.bids[:depth_levels]) + sum(
        level.size for level in orderbook.asks[:depth_levels]
    )

    if total_depth > 10:
        depth_score = 100.0
    elif total_depth > 5:
        depth_score = 80.0
    elif total_depth > 2:
        depth_score = 60.0
    elif total_depth > 1:
        depth_score = 40.0
    else:
        depth_score = 20.0

    # Calculate spread score (penalize wide spreads)
    spread_score = max(0.0, 100.0 - orderbook.spread_bps * 5.0)

    # Combined liquidity score
    liquidity_score = (depth_score + spread_score) / 2.0

    return {
        "effective_spread_bps": impact.effective_spread_bps,
        "price_impact_bps": impact.total_impact_bps,
        "market_depth_score": depth_score,
        "liquidity_score": liquidity_score,
    }


def _calculate_imbalance_metrics(
    orderbook: OrderBookSnapshot,
    depth_levels: int,
) -> Dict[str, float]:
    """Calculate order book imbalance metrics"""
    bid_depth = sum(level.size for level in orderbook.bids[:depth_levels])
    ask_depth = sum(level.size for level in orderbook.asks[:depth_levels])
    total_depth = bid_depth + ask_depth

    # Book imbalance: 0 = all bids, 1 = all asks
    book_imbalance = (ask_depth / total_depth) if total_depth > 0 else 0.5

    # Depth imbalance: weighted by distance from mid
    depth_imbalance = 0.0
    mid = orderbook.mid_price
    if mid > 0:
        weighted_bid = sum(
            level.size / (1 + abs(level.price - mid) / mid)
            for level in orderbook.bids[:5]
        )
        weighted_ask = sum(
            level.size / (1 + abs(level.price - mid) / mid)
            for level in orderbook.asks[:5]
        )
        total_weighted = weighted_bid + weighted_ask
        if total_weighted > 0:
            depth_imbalance = (weighted_ask - weighted_bid) / total_weighted  # [-1, 1]

    return {
        "book_imbalance": book_imbalance,
        "depth_imbalance": depth_imbalance,
    }


def _classify_regime(
    spread_bps: float,
    total_depth_btc: float,
    thresholds: RegimeThresholds,
) -> Tuple[LiquidityRegime, float]:
    """
    Classify liquidity regime using threshold heuristics.

    Returns tuple of (regime, confidence_score)
    """
    regime_scores: Dict[LiquidityRegime, float] = {}

    # Abundant: tight spreads AND deep book
    if spread_bps <= thresholds.abundant_spread_bps and total_depth_btc >= thresholds.abundant_depth_btc:
        regime_scores[LiquidityRegime.ABUNDANT] = 1.0
    else:
        regime_scores[LiquidityRegime.ABUNDANT] = 0.0

    # Normal: moderate spreads AND adequate depth
    if spread_bps <= thresholds.normal_spread_bps and total_depth_btc >= thresholds.normal_depth_btc:
        regime_scores[LiquidityRegime.NORMAL] = 1.0
    else:
        regime_scores[LiquidityRegime.NORMAL] = 0.3

    # Constrained: wider spreads OR lower depth
    if spread_bps >= thresholds.constrained_spread_bps or total_depth_btc <= thresholds.constrained_depth_btc:
        regime_scores[LiquidityRegime.CONSTRAINED] = 1.0
    else:
        regime_scores[LiquidityRegime.CONSTRAINED] = 0.2

    # Scarce: wide spreads OR thin depth
    if spread_bps >= thresholds.scarce_spread_bps or total_depth_btc <= thresholds.scarce_depth_btc:
        regime_scores[LiquidityRegime.SCARCE] = 1.0
    else:
        regime_scores[LiquidityRegime.SCARCE] = 0.1

    # Stressed: extreme spreads OR very thin depth
    if spread_bps >= thresholds.stressed_spread_bps or total_depth_btc <= thresholds.stressed_depth_btc:
        regime_scores[LiquidityRegime.STRESSED] = 1.0
    else:
        regime_scores[LiquidityRegime.STRESSED] = 0.0

    best_regime = max(regime_scores.keys(), key=lambda r: regime_scores[r])
    confidence = float(regime_scores[best_regime])

    return best_regime, confidence


def _calculate_temporary_impact(
    levels: List[OrderBookLevel],
    size_btc: float,
) -> float:
    """
    Calculate temporary market impact by walking the order book.

    Returns impact in basis points relative to top of book.
    """
    if not levels or size_btc <= 0:
        return 0.0

    remaining = size_btc
    total_cost = 0.0
    reference = levels[0].price

    for level in levels:
        if remaining <= 0:
            break
        take = min(remaining, level.size)
        total_cost += take * level.price
        remaining -= take

    if remaining > 1e-9:
        # Could not fill entire order within visible depth
        return 50.0

    vwap = total_cost / size_btc if size_btc > 0 else reference
    return abs(vwap - reference) / (reference if reference > 0 else 1.0) * 10000.0


def _calculate_permanent_impact(
    size_btc: float,
    spread_bps: float,
    impact_params: ImpactModelParams,
) -> float:
    """
    Calculate permanent market impact using linear + sqrt model.

    Returns impact in basis points.
    """
    linear = size_btc * impact_params.linear_coefficient
    sqrt = (size_btc ** 0.5) * impact_params.sqrt_coefficient
    impact = linear + sqrt

    # Scale up impact in illiquid conditions
    if spread_bps > 10.0:
        impact *= 1.5

    return impact


def _calculate_effective_spread(
    levels: List[OrderBookLevel],
    size_btc: float,
) -> float:
    """
    Calculate effective spread (VWAP vs top of book) for a given size.

    Returns spread in basis points.
    """
    if not levels or size_btc <= 0:
        return 0.0

    remaining = size_btc
    total_cost = 0.0

    for level in levels:
        if remaining <= 0:
            break
        take = min(remaining, level.size)
        total_cost += take * level.price
        remaining -= take

    filled = size_btc - remaining
    if filled <= 0:
        return 10.0

    vwap = total_cost / filled
    reference = levels[0].price
    return abs(vwap - reference) / (reference if reference > 0 else 1.0) * 10000.0
