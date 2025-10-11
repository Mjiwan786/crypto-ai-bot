"""
Advanced liquidity analysis for scalping operations.

Analyzes order book depth, liquidity patterns, and market impact to provide
comprehensive liquidity metrics for high-frequency trading strategies.

Features:
- Real-time liquidity metrics calculation
- Regime classification and detection
- Market impact estimation
- Liquidity forecasting
- Optimal execution sizing
- Order book imbalance analysis
- Spread and depth volatility tracking

This module provides the core liquidity analysis capabilities for the scalping
system, enabling intelligent order sizing and execution timing decisions.
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

from ..config_loader import KrakenScalpingConfig


class LiquidityRegime(Enum):
    """Market liquidity regimes"""

    ABUNDANT = "abundant"  # High liquidity, tight spreads
    NORMAL = "normal"  # Typical liquidity conditions
    CONSTRAINED = "constrained"  # Reduced liquidity, wider spreads
    SCARCE = "scarce"  # Very low liquidity, large spreads
    STRESSED = "stressed"  # Extreme illiquidity


@dataclass
class OrderBookLevel:
    """Individual order book level"""

    price: float
    size: float
    timestamp: float = field(default_factory=time.time)

    @property
    def notional(self) -> float:
        """Notional value of this level"""
        return max(0.0, self.price) * max(0.0, self.size)


@dataclass
class OrderBookSnapshot:
    """Complete order book snapshot"""

    symbol: str
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    timestamp: float = field(default_factory=time.time)

    @property
    def best_bid(self) -> Optional[OrderBookLevel]:
        """Best bid price/size; assumes bids are sorted desc by price"""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[OrderBookLevel]:
        """Best ask price/size; assumes asks are sorted asc by price"""
        return self.asks[0] if self.asks else None

    @property
    def mid_price(self) -> float:
        """Mid price (0.0 if unavailable)"""
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2.0
        return 0.0

    @property
    def spread_bps(self) -> float:
        """Bid-ask spread in basis points relative to mid"""
        mid = self.mid_price
        if mid > 0 and self.best_bid and self.best_ask:
            return ((self.best_ask.price - self.best_bid.price) / mid) * 10000.0
        return 0.0


@dataclass
class LiquidityMetrics:
    """Comprehensive liquidity metrics"""

    symbol: str
    timestamp: float = field(default_factory=time.time)

    # Basic metrics
    spread_bps: float = 0.0
    bid_depth_btc: float = 0.0
    ask_depth_btc: float = 0.0
    total_depth_btc: float = 0.0

    # Advanced metrics
    effective_spread_bps: float = 0.0
    price_impact_bps: float = 0.0
    market_depth_score: float = 0.0  # 0..100
    liquidity_score: float = 0.0  # 0..100

    # Imbalance metrics
    book_imbalance: float = 0.5  # 0 = all bids, 1 = all asks
    depth_imbalance: float = 0.0  # [-1, 1], ask-heavy positive

    # Stability metrics
    spread_volatility: float = 0.0
    depth_volatility: float = 0.0

    # Regime classification
    liquidity_regime: LiquidityRegime = LiquidityRegime.NORMAL
    regime_confidence: float = 0.5


class LiquidityAnalyzer:
    """
    Advanced liquidity analysis for order book data.

    Features:
    - Real-time liquidity metrics calculation
    - Regime classification and detection
    - Market impact estimation
    - Liquidity forecasting
    - Optimal execution sizing
    """

    def __init__(self, config: KrakenScalpingConfig, agent_id: str = "kraken_scalper"):
        self.config = config
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Analysis parameters
        self.depth_levels: int = 10  # Number of book levels to analyze
        self.analysis_window: int = 100  # Number of snapshots for analysis

        # Historical data storage
        self.orderbook_history: Dict[str, Deque[OrderBookSnapshot]] = {}
        self.metrics_history: Dict[str, Deque[LiquidityMetrics]] = {}

        # Regime detection thresholds
        self.regime_thresholds: Dict[LiquidityRegime, Dict[str, float]] = {
            LiquidityRegime.ABUNDANT: {"spread_bps": 2.0, "depth_btc": 10.0},
            LiquidityRegime.NORMAL: {"spread_bps": 5.0, "depth_btc": 5.0},
            LiquidityRegime.CONSTRAINED: {"spread_bps": 10.0, "depth_btc": 2.0},
            LiquidityRegime.SCARCE: {"spread_bps": 20.0, "depth_btc": 1.0},
            LiquidityRegime.STRESSED: {"spread_bps": 50.0, "depth_btc": 0.5},
        }

        # Market impact model parameters
        self.impact_model = {
            "linear_coefficient": 0.1,  # bps per BTC
            "sqrt_coefficient": 0.5,  # sqrt impact
            "temp_impact_decay": 0.95,  # (reserved)
        }

        self.logger.info("LiquidityAnalyzer initialized")

    # ---------------------------
    # Public API
    # ---------------------------

    async def analyze_orderbook(self, orderbook: OrderBookSnapshot) -> LiquidityMetrics:
        """
        Perform comprehensive liquidity analysis on an order book snapshot.

        Returns:
            LiquidityMetrics
        """
        try:
            ob = self._normalize_orderbook(orderbook)

            # Store snapshot for historical analysis
            await self._store_snapshot(ob)

            # Calculate layered metrics
            basic_metrics = self._calculate_basic_metrics(ob)
            advanced_metrics = await self._calculate_advanced_metrics(ob)
            imbalance_metrics = self._calculate_imbalance_metrics(ob)
            stability_metrics = await self._calculate_stability_metrics(ob)

            # Regime classification
            regime, confidence = await self._classify_regime(basic_metrics, advanced_metrics)

            metrics = LiquidityMetrics(
                symbol=ob.symbol,
                **basic_metrics,
                **advanced_metrics,
                **imbalance_metrics,
                **stability_metrics,
                liquidity_regime=regime,
                regime_confidence=confidence,
            )

            await self._store_metrics(metrics)
            return metrics

        except Exception as e:
            self.logger.error(f"Error analyzing orderbook for {orderbook.symbol}: {e}")
            return LiquidityMetrics(symbol=orderbook.symbol)

    async def estimate_market_impact(
        self,
        symbol: str,
        side: str,
        size_btc: float,
        orderbook: Optional[OrderBookSnapshot] = None,
    ) -> Dict[str, float]:
        """
        Estimate market impact for a given order size (in BTC).

        Returns:
            dict with keys: temporary_impact_bps, permanent_impact_bps, effective_spread_bps, total_impact_bps
        """
        try:
            ob = self._normalize_orderbook(
                orderbook or (self.orderbook_history.get(symbol, deque()) or deque())[-1]
                if self.orderbook_history.get(symbol)
                else None
            )
            if not ob:
                return {
                    "temporary_impact_bps": 5.0,
                    "permanent_impact_bps": 2.0,
                    "effective_spread_bps": 5.0,
                    "total_impact_bps": 7.0,
                }

            levels = ob.asks if side == "buy" else ob.bids
            if not levels:
                return {
                    "temporary_impact_bps": 10.0,
                    "permanent_impact_bps": 5.0,
                    "effective_spread_bps": 10.0,
                    "total_impact_bps": 15.0,
                }

            temporary_impact = await self._calculate_temporary_impact(levels, size_btc)
            permanent_impact = await self._calculate_permanent_impact(size_btc, ob)
            effective_spread = await self._calculate_effective_spread(levels, size_btc)

            return {
                "temporary_impact_bps": temporary_impact,
                "permanent_impact_bps": permanent_impact,
                "effective_spread_bps": effective_spread,
                "total_impact_bps": temporary_impact + permanent_impact,
            }

        except Exception as e:
            self.logger.error(f"Error estimating market impact: {e}")
            return {
                "temporary_impact_bps": 10.0,
                "permanent_impact_bps": 5.0,
                "effective_spread_bps": 10.0,
                "total_impact_bps": 15.0,
            }

    async def get_optimal_order_size(
        self,
        symbol: str,
        side: str,
        max_impact_bps: float = 5.0,
        orderbook: Optional[OrderBookSnapshot] = None,
    ) -> Dict[str, float]:
        """
        Binary-search an optimal order size under a total impact constraint.

        Returns:
            dict with keys: optimal_size_btc, max_safe_size_btc, impact_at_optimal_bps
        """
        try:
            ob = self._normalize_orderbook(
                orderbook or (self.orderbook_history.get(symbol, deque()) or deque())[-1]
                if self.orderbook_history.get(symbol)
                else None
            )
            if not ob:
                return {
                    "optimal_size_btc": 0.1,
                    "max_safe_size_btc": 0.2,
                    "impact_at_optimal_bps": max_impact_bps,
                }

            # Binary search bounds
            low, high = 0.01, 5.0
            optimal = low

            for _ in range(22):  # ~2^22 precision is plenty; we stop earlier via epsilon
                mid = (low + high) / 2.0
                impact = await self.estimate_market_impact(symbol, side, mid, ob)
                total = impact.get("total_impact_bps", 10.0)

                if total <= max_impact_bps:
                    optimal = mid
                    low = mid
                else:
                    high = mid

                if (high - low) < 1e-3:
                    break

            # Scan up from optimal to find ~2x-constraint boundary
            max_safe = optimal
            probe = optimal
            while probe <= 10.0:
                impact = await self.estimate_market_impact(symbol, side, probe, ob)
                if impact.get("total_impact_bps", 0.0) > max_impact_bps * 2.0:
                    break
                max_safe = probe
                probe += 0.1

            impact_at_optimal = (await self.estimate_market_impact(symbol, side, optimal, ob)).get(
                "total_impact_bps", 0.0
            )

            return {
                "optimal_size_btc": round(optimal, 6),
                "max_safe_size_btc": round(max_safe, 6),
                "impact_at_optimal_bps": impact_at_optimal,
            }

        except Exception as e:
            self.logger.error(f"Error calculating optimal order size: {e}")
            return {
                "optimal_size_btc": 0.1,
                "max_safe_size_btc": 0.2,
                "impact_at_optimal_bps": max_impact_bps,
            }

    async def detect_liquidity_events(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Detect significant liquidity events (drying up, restocking, spread widening, regime change).
        """
        try:
            metrics_history = self.metrics_history.get(symbol, deque())
            if len(metrics_history) < 10:
                return []

            events: List[Dict[str, Any]] = []
            recent: List[LiquidityMetrics] = list(metrics_history)[-20:]

            # Drying up (depth collapses)
            if len(recent) >= 10:
                recent_depths = [m.total_depth_btc for m in recent[-5:]]
                earlier_depths = [m.total_depth_btc for m in recent[-10:-5]]
                if earlier_depths and statistics.mean(earlier_depths) > 0:
                    if (
                        statistics.mean(recent_depths) < statistics.mean(earlier_depths) * 0.5
                        and statistics.mean(recent_depths) < 2.0
                    ):
                        events.append(
                            {
                                "type": "liquidity_drying",
                                "severity": (
                                    "high" if statistics.mean(recent_depths) < 1.0 else "medium"
                                ),
                                "current_depth": statistics.mean(recent_depths),
                                "previous_depth": statistics.mean(earlier_depths),
                                "timestamp": time.time(),
                            }
                        )

            # Spread widening
            if len(recent) >= 10:
                recent_spreads = [m.spread_bps for m in recent[-5:]]
                earlier_spreads = [m.spread_bps for m in recent[-10:-5]]
                if earlier_spreads and statistics.mean(earlier_spreads) > 0:
                    if (
                        statistics.mean(recent_spreads) > statistics.mean(earlier_spreads) * 2.0
                        and statistics.mean(recent_spreads) > 10.0
                    ):
                        events.append(
                            {
                                "type": "spread_widening",
                                "severity": (
                                    "high" if statistics.mean(recent_spreads) > 20.0 else "medium"
                                ),
                                "current_spread": statistics.mean(recent_spreads),
                                "previous_spread": statistics.mean(earlier_spreads),
                                "timestamp": time.time(),
                            }
                        )

            # Regime change
            if len(recent) >= 2:
                cur, prev = recent[-1], recent[-2]
                if cur.liquidity_regime != prev.liquidity_regime:
                    events.append(
                        {
                            "type": "regime_change",
                            "severity": "medium",
                            "from_regime": prev.liquidity_regime.value,
                            "to_regime": cur.liquidity_regime.value,
                            "confidence": cur.regime_confidence,
                            "timestamp": time.time(),
                        }
                    )

            return events

        except Exception as e:
            self.logger.error(f"Error detecting liquidity events: {e}")
            return []

    # ---------------------------
    # Internal helpers
    # ---------------------------

    def _normalize_orderbook(
        self, orderbook: Optional[OrderBookSnapshot]
    ) -> Optional[OrderBookSnapshot]:
        """Ensure levels are sorted (bids desc, asks asc) and sizes/prices are non-negative."""
        if not orderbook:
            return None

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
            symbol=orderbook.symbol, bids=bids, asks=asks, timestamp=orderbook.timestamp
        )

    async def _store_snapshot(self, orderbook: OrderBookSnapshot) -> None:
        """Store orderbook snapshot for historical analysis"""
        dq = self.orderbook_history.setdefault(orderbook.symbol, deque(maxlen=self.analysis_window))
        dq.append(orderbook)

    async def _store_metrics(self, metrics: LiquidityMetrics) -> None:
        """Store metrics for historical analysis"""
        dq = self.metrics_history.setdefault(metrics.symbol, deque(maxlen=self.analysis_window))
        dq.append(metrics)

    def _calculate_basic_metrics(self, orderbook: OrderBookSnapshot) -> Dict[str, float]:
        """Calculate basic liquidity metrics"""
        bid_depth = sum(level.size for level in orderbook.bids[: self.depth_levels])
        ask_depth = sum(level.size for level in orderbook.asks[: self.depth_levels])

        return {
            "spread_bps": orderbook.spread_bps,
            "bid_depth_btc": bid_depth,
            "ask_depth_btc": ask_depth,
            "total_depth_btc": bid_depth + ask_depth,
        }

    async def _calculate_advanced_metrics(self, orderbook: OrderBookSnapshot) -> Dict[str, float]:
        """Calculate advanced liquidity metrics"""
        metrics: Dict[str, float] = {
            "effective_spread_bps": 0.0,
            "price_impact_bps": 0.0,
            "market_depth_score": 0.0,
            "liquidity_score": 0.0,
        }

        # Effective spread & impact at a typical size
        typical_size = 0.1  # BTC
        impact = await self.estimate_market_impact(orderbook.symbol, "buy", typical_size, orderbook)
        metrics["effective_spread_bps"] = impact.get("effective_spread_bps", orderbook.spread_bps)
        metrics["price_impact_bps"] = impact.get("total_impact_bps", 5.0)

        # Depth score (very simple piecewise normalization)
        total_depth = sum(level.size for level in orderbook.bids[: self.depth_levels]) + sum(
            level.size for level in orderbook.asks[: self.depth_levels]
        )

        if total_depth > 10:
            depth_score = 100
        elif total_depth > 5:
            depth_score = 80
        elif total_depth > 2:
            depth_score = 60
        elif total_depth > 1:
            depth_score = 40
        else:
            depth_score = 20

        # Combined liquidity score
        spread_score = max(0.0, 100.0 - orderbook.spread_bps * 5.0)  # penalize wide spreads
        metrics["market_depth_score"] = depth_score
        metrics["liquidity_score"] = (depth_score + spread_score) / 2.0

        return metrics

    def _calculate_imbalance_metrics(self, orderbook: OrderBookSnapshot) -> Dict[str, float]:
        """Calculate order book imbalance metrics"""
        bid_depth = sum(level.size for level in orderbook.bids[: self.depth_levels])
        ask_depth = sum(level.size for level in orderbook.asks[: self.depth_levels])
        total_depth = bid_depth + ask_depth

        book_imbalance = (ask_depth / total_depth) if total_depth > 0 else 0.5

        depth_imbalance = 0.0
        mid = orderbook.mid_price
        if mid > 0:
            weighted_bid = sum(
                level.size / (1 + abs(level.price - mid) / mid) for level in orderbook.bids[:5]
            )
            weighted_ask = sum(
                level.size / (1 + abs(level.price - mid) / mid) for level in orderbook.asks[:5]
            )
            total_weighted = weighted_bid + weighted_ask
            if total_weighted > 0:
                depth_imbalance = (weighted_ask - weighted_bid) / total_weighted  # [-1,1]

        return {"book_imbalance": book_imbalance, "depth_imbalance": depth_imbalance}

    async def _calculate_stability_metrics(self, orderbook: OrderBookSnapshot) -> Dict[str, float]:
        """Calculate liquidity stability metrics from recent history"""
        metrics = {"spread_volatility": 0.0, "depth_volatility": 0.0}
        recent = list(self.metrics_history.get(orderbook.symbol, deque()))[-20:]

        if len(recent) >= 10:
            spreads = [m.spread_bps for m in recent]
            if len(spreads) > 1:
                metrics["spread_volatility"] = statistics.stdev(spreads)

            depths = [m.total_depth_btc for m in recent]
            mean_depth = statistics.mean(depths) if depths else 0.0
            if len(depths) > 1 and mean_depth > 0:
                metrics["depth_volatility"] = statistics.stdev(depths) / mean_depth

        return metrics

    async def _classify_regime(
        self,
        basic_metrics: Dict[str, float],
        advanced_metrics: Dict[str, float],
    ) -> Tuple[LiquidityRegime, float]:
        """
        Classify current liquidity regime using threshold heuristics.

        Note: Fixed inverted logic for CONSTRAINED/SCARCE/STRESSED.
        """
        spread = basic_metrics.get("spread_bps", 10.0)
        depth = basic_metrics.get("total_depth_btc", 1.0)

        regime_scores: Dict[LiquidityRegime, float] = {}

        for regime, thresholds in self.regime_thresholds.items():
            spread_thr = thresholds["spread_bps"]
            depth_thr = thresholds["depth_btc"]

            if regime == LiquidityRegime.ABUNDANT:
                score = 1.0 if (spread <= spread_thr and depth >= depth_thr) else 0.0
            elif regime == LiquidityRegime.NORMAL:
                score = 1.0 if (spread <= spread_thr and depth >= depth_thr) else 0.3
            elif regime == LiquidityRegime.CONSTRAINED:
                # Reduced liquidity -> wider spreads OR lower depth
                score = 1.0 if (spread >= spread_thr or depth <= depth_thr) else 0.2
            elif regime == LiquidityRegime.SCARCE:
                score = 1.0 if (spread >= spread_thr or depth <= depth_thr) else 0.1
            else:  # STRESSED (extreme)
                score = 1.0 if (spread >= spread_thr or depth <= depth_thr) else 0.0

            regime_scores[regime] = score

        best_regime = max(regime_scores.keys(), key=lambda r: regime_scores[r])
        confidence = float(regime_scores[best_regime])

        return best_regime, confidence

    async def _calculate_temporary_impact(
        self, levels: List[OrderBookLevel], size_btc: float
    ) -> float:
        """Calculate temporary market impact by walking the book"""
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
            # Could not fill whole order within visible depth
            return 50.0

        vwap = total_cost / size_btc if size_btc > 0 else reference
        return abs(vwap - reference) / (reference if reference > 0 else 1.0) * 10000.0

    async def _calculate_permanent_impact(
        self, size_btc: float, orderbook: OrderBookSnapshot
    ) -> float:
        """Calculate permanent market impact via linear + sqrt model"""
        linear = size_btc * self.impact_model["linear_coefficient"]
        sqrt = (size_btc**0.5) * self.impact_model["sqrt_coefficient"]
        impact = linear + sqrt

        if orderbook.spread_bps > 10.0:
            impact *= 1.5

        return impact

    async def _calculate_effective_spread(
        self, levels: List[OrderBookLevel], size_btc: float
    ) -> float:
        """Calculate effective spread (VWAP vs top of book) for a given size"""
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


@dataclass
class LiquiditySignal:
    """Liquidity-based trading signal"""

    symbol: str
    timestamp: float
    signal_type: str  # 'buy', 'sell', 'hold'
    confidence: float
    reason: str
    metrics: LiquidityMetrics

    def __post_init__(self):
        """Validate signal data"""
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        if self.signal_type not in ["buy", "sell", "hold"]:
            raise ValueError("Signal type must be 'buy', 'sell', or 'hold'")


def liquidity_signal(
    symbol: str, signal_type: str, confidence: float, reason: str, metrics: LiquidityMetrics
) -> LiquiditySignal:
    """Create a liquidity signal"""
    return LiquiditySignal(
        symbol=symbol,
        timestamp=time.time(),
        signal_type=signal_type,
        confidence=confidence,
        reason=reason,
        metrics=metrics,
    )
