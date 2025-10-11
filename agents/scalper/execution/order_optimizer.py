"""
Intelligent order execution optimization for scalping strategies.

This module provides comprehensive order optimization capabilities for the scalping
system, optimizing order placement, timing, and execution tactics to maximize
execution quality and minimize market impact.

Features:
- Market condition analysis and adaptation
- Execution tactic selection (aggressive, passive, smart, iceberg, TWAP)
- Order sizing optimization
- Timing optimization and prediction
- Slippage prediction and modeling
- Performance tracking and learning
- Multi-tactic execution strategies

This module provides the core order optimization capabilities for the scalping
system, enabling intelligent execution decisions and improved trade outcomes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from ..config_loader import KrakenScalpingConfig
from .kraken_gateway import OrderRequest

logger = logging.getLogger(__name__)


class OrderTactic(Enum):
    """Order execution tactics"""

    AGGRESSIVE = "aggressive"  # Market orders, fast execution
    PASSIVE = "passive"  # Post-only limit orders
    SMART = "smart"  # Adaptive based on conditions
    ICEBERG = "iceberg"  # Break large orders into pieces
    TWAP = "twap"  # Time-weighted average price


@dataclass
class MarketConditions:
    """Current market conditions for optimization"""

    spread_bps: float = 0.0
    volatility: float = 0.0
    volume_ratio: float = 1.0  # Current vs average volume
    book_imbalance: float = 0.5  # 0 = all bids, 1 = all asks
    recent_price_movement: float = 0.0
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class OptimizedOrder:
    """Optimized order with execution plan"""

    original_request: OrderRequest
    optimized_requests: List[OrderRequest]
    tactic: OrderTactic
    expected_slippage_bps: float
    confidence_score: float
    estimated_fill_time_ms: float
    reasoning: str


class OrderOptimizer:
    """
    Intelligent order optimization for scalping operations.

    Features:
    - Market condition analysis
    - Execution tactic selection
    - Order sizing optimization
    - Timing optimization
    - Slippage prediction
    """

    def __init__(self, config: KrakenScalpingConfig, agent_id: str = "kraken_scalper"):
        self.config = config
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Optimization parameters (overridable from config if present)
        self.min_spread_for_passive = float(
            getattr(getattr(config, "scalp", object()), "min_spread_for_passive_bps", 2.0)
        )
        self.max_spread_for_aggressive = float(
            getattr(getattr(config, "scalp", object()), "max_spread_for_aggressive_bps", 10.0)
        )
        self.volatility_threshold = float(
            getattr(getattr(config, "scalp", object()), "volatility_threshold", 0.02)
        )
        self.volume_threshold = float(
            getattr(getattr(config, "scalp", object()), "volume_threshold", 0.5)
        )

        # Performance tracking
        self.execution_history: List[Dict] = []
        self.optimization_metrics = {
            "optimizations_performed": 0,
            "avg_slippage_improvement": 0.0,
            "avg_fill_time_improvement": 0.0,
            "success_rate": 0.0,
        }

        # Market microstructure models
        self.slippage_model = SlippageModel(config)
        self.timing_model = TimingModel(config)

        self.logger.info("OrderOptimizer initialized")

    async def optimize_order(
        self,
        order_request: OrderRequest,
        market_conditions: MarketConditions,
        current_positions: Optional[Dict] = None,
    ) -> OptimizedOrder:
        """
        Optimize an order based on current market conditions.

        Returns optimized order plan with execution strategy.
        """
        try:
            self._validate_request(order_request)

            # Analyze market conditions → pick tactic
            tactic = self._select_execution_tactic(order_request, market_conditions)

            # Optimize based on selected tactic
            if tactic == OrderTactic.AGGRESSIVE:
                optimized = await self._optimize_aggressive(order_request, market_conditions)
            elif tactic == OrderTactic.PASSIVE:
                optimized = await self._optimize_passive(order_request, market_conditions)
            elif tactic == OrderTactic.SMART:
                optimized = await self._optimize_smart(order_request, market_conditions)
            elif tactic == OrderTactic.ICEBERG:
                optimized = await self._optimize_iceberg(order_request, market_conditions)
            else:  # TWAP
                optimized = await self._optimize_twap(order_request, market_conditions)

            self.optimization_metrics["optimizations_performed"] += 1

            self.logger.debug(
                "Optimized order: %s %s %.8f using %s tactic",
                order_request.symbol,
                order_request.side,
                order_request.size,
                tactic.value,
            )
            return optimized

        except Exception as e:
            self.logger.error("Error optimizing order: %s", e, exc_info=True)
            # Return unoptimized order as fallback
            return OptimizedOrder(
                original_request=order_request,
                optimized_requests=[order_request],
                tactic=OrderTactic.SMART,
                expected_slippage_bps=5.0,  # Conservative estimate
                confidence_score=0.5,
                estimated_fill_time_ms=1000.0,
                reasoning=f"Optimization failed: {e}. Using original order",
            )

    async def predict_execution_quality(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> Dict[str, float]:
        """
        Predict execution quality metrics for an order.

        Returns predicted slippage, fill time, and probability.
        """
        try:
            self._validate_request(order_request)

            predicted_slippage = self.slippage_model.predict_slippage(
                order_request, market_conditions
            )
            predicted_fill_time = self.timing_model.predict_fill_time(
                order_request, market_conditions
            )
            fill_probability = self._calculate_fill_probability(order_request, market_conditions)

            return {
                "predicted_slippage_bps": float(predicted_slippage),
                "predicted_fill_time_ms": float(predicted_fill_time),
                "fill_probability": float(fill_probability),
                "market_impact_bps": float(predicted_slippage) * 0.6,  # heuristic
                "timing_risk": max(0.0, float(predicted_fill_time) - 500.0) / 1000.0,
            }

        except Exception as e:
            self.logger.error("Error predicting execution quality: %s", e, exc_info=True)
            return {
                "predicted_slippage_bps": 5.0,
                "predicted_fill_time_ms": 1000.0,
                "fill_probability": 0.8,
                "market_impact_bps": 3.0,
                "timing_risk": 0.5,
            }

    # ------------------------- Tactic Selection -------------------------

    def _select_execution_tactic(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> OrderTactic:
        """Select optimal execution tactic based on conditions."""

        # Prefer passive when spread is WIDE ENOUGH to earn maker edge and volatility is tame
        if (
            market_conditions.spread_bps >= self.min_spread_for_passive
            and market_conditions.volatility < self.volatility_threshold
        ):
            return OrderTactic.PASSIVE

        # Use aggressive when urgency is high (very wide spreads/very high vol)
        if (
            market_conditions.spread_bps > self.max_spread_for_aggressive
            or market_conditions.volatility > self.volatility_threshold * 2.0
        ):
            return OrderTactic.AGGRESSIVE

        # Use iceberg for larger notional
        notional_value = float(order_request.size) * float(order_request.price or 100.0)
        if notional_value > float(
            getattr(
                getattr(self.config, "scalp", object()), "iceberg_notional_threshold_usd", 1000.0
            )
        ):
            return OrderTactic.ICEBERG

        # Default to smart execution
        return OrderTactic.SMART

    # ------------------------- Tactic Optimizers -------------------------

    async def _optimize_aggressive(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> OptimizedOrder:
        """Optimize for aggressive (fast) execution: convert to market IOC."""
        optimized_request = OrderRequest(
            symbol=order_request.symbol,
            side=order_request.side,
            order_type="market",
            size=max(0.0, order_request.size),
            price=None,  # Market
            time_in_force="IOC",
            post_only=False,
            client_order_id=order_request.client_order_id,
        )

        # Predict execution quality
        expected_slippage = max(
            0.0, market_conditions.spread_bps * 0.8
        )  # crossing spread heuristic
        estimated_fill_time = 100.0  # fast

        return OptimizedOrder(
            original_request=order_request,
            optimized_requests=[optimized_request],
            tactic=OrderTactic.AGGRESSIVE,
            expected_slippage_bps=expected_slippage,
            confidence_score=0.9,
            estimated_fill_time_ms=estimated_fill_time,
            reasoning="Aggressive execution for speed priority",
        )

    async def _optimize_passive(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> OptimizedOrder:
        """Optimize for passive (maker fee) execution."""
        optimized_price = self._calculate_optimal_passive_price(order_request, market_conditions)

        optimized_request = OrderRequest(
            symbol=order_request.symbol,
            side=order_request.side,
            order_type="limit",
            size=max(0.0, order_request.size),
            price=optimized_price,
            time_in_force="GTC",
            post_only=True,  # maker only
            hidden=bool(getattr(getattr(self.config, "scalp", object()), "hidden_orders", False)),
            client_order_id=order_request.client_order_id,
        )

        expected_slippage = 0.0  # target maker execution
        estimated_fill_time = self._estimate_passive_fill_time(market_conditions)

        return OptimizedOrder(
            original_request=order_request,
            optimized_requests=[optimized_request],
            tactic=OrderTactic.PASSIVE,
            expected_slippage_bps=expected_slippage,
            confidence_score=0.8,
            estimated_fill_time_ms=estimated_fill_time,
            reasoning="Passive execution for maker fees and reduced slippage",
        )

    async def _optimize_smart(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> OptimizedOrder:
        """Smart adaptive execution based on conditions."""
        # Simple microstructure-aware bump
        if market_conditions.book_imbalance > 0.7:  # Strong buying pressure
            price_bps = 1.0 if order_request.side == "buy" else -2.0
        elif market_conditions.book_imbalance < 0.3:  # Strong selling pressure
            price_bps = -2.0 if order_request.side == "sell" else 1.0
        else:
            price_bps = 0.0

        base_price = float(order_request.price or 100.0)
        smart_price = base_price * (1.0 + price_bps / 10_000.0)
        smart_price = self._round_price(smart_price)

        optimized_request = OrderRequest(
            symbol=order_request.symbol,
            side=order_request.side,
            order_type="limit",
            size=max(0.0, order_request.size),
            price=smart_price,
            time_in_force="GTC",
            post_only=market_conditions.spread_bps < 5.0,  # opportunistic maker
            client_order_id=order_request.client_order_id,
        )

        expected_slippage = max(0.0, market_conditions.spread_bps * 0.3)
        estimated_fill_time = self.timing_model.predict_fill_time(
            optimized_request, market_conditions
        )

        return OptimizedOrder(
            original_request=order_request,
            optimized_requests=[optimized_request],
            tactic=OrderTactic.SMART,
            expected_slippage_bps=expected_slippage,
            confidence_score=0.85,
            estimated_fill_time_ms=estimated_fill_time,
            reasoning="Smart execution with adaptive pricing",
        )

    async def _optimize_iceberg(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> OptimizedOrder:
        """Break large order into smaller pieces (simple iceberg)."""
        total_size = max(0.0, float(order_request.size))
        slice_size = self._calculate_iceberg_slice_size(total_size, market_conditions)

        optimized_requests: List[OrderRequest] = []
        remaining = total_size
        idx = 0

        while remaining > 1e-12:
            current_slice = max(1e-6, min(slice_size, remaining))
            slice_req = OrderRequest(
                symbol=order_request.symbol,
                side=order_request.side,
                order_type="limit",
                size=current_slice,
                price=self._round_price(float(order_request.price or 100.0)),
                time_in_force="GTC",
                post_only=True,
                hidden=True,  # gateway can translate to iceberg mechanics if supported
                client_order_id=(
                    f"{order_request.client_order_id}_slice_{idx}"
                    if order_request.client_order_id
                    else None
                ),
            )
            optimized_requests.append(slice_req)
            remaining -= current_slice
            idx += 1

            # Safety cap to avoid pathological loops
            if idx > 10_000:
                break

        estimated_fill_time = len(optimized_requests) * 2000.0  # heuristic
        expected_slippage = max(0.0, market_conditions.spread_bps * 0.1)

        return OptimizedOrder(
            original_request=order_request,
            optimized_requests=optimized_requests,
            tactic=OrderTactic.ICEBERG,
            expected_slippage_bps=expected_slippage,
            confidence_score=0.75,
            estimated_fill_time_ms=estimated_fill_time,
            reasoning=f"Iceberg execution with {len(optimized_requests)} slices",
        )

    async def _optimize_twap(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> OptimizedOrder:
        """Time-weighted average price execution (basic)."""
        total_size = max(0.0, float(order_request.size))
        # Between 2 and 5 intervals; never zero
        num_intervals = min(5, max(2, int(max(1, total_size / 0.1))))
        interval_size = total_size / num_intervals

        optimized_requests: List[OrderRequest] = []
        accumulated = 0.0

        for i in range(num_intervals):
            # small deterministic variation (no random)
            variation = interval_size * 0.1 * (0.5 - (i % 3) / 3.0)  # ~±5%
            actual_size = max(1e-6, interval_size + variation)
            if i == num_intervals - 1:
                actual_size = max(1e-6, total_size - accumulated)
            accumulated += actual_size
            actual_size = min(
                actual_size, max(1e-6, total_size - sum(r.size for r in optimized_requests))
            )

            twap_request = OrderRequest(
                symbol=order_request.symbol,
                side=order_request.side,
                order_type="limit",
                size=actual_size,
                price=self._round_price(float(order_request.price or 100.0)),
                time_in_force="GTC",
                post_only=True,
                client_order_id=(
                    f"{order_request.client_order_id}_twap_{i}"
                    if order_request.client_order_id
                    else None
                ),
            )
            optimized_requests.append(twap_request)

        estimated_fill_time = num_intervals * 5000.0
        expected_slippage = max(0.0, market_conditions.spread_bps * 0.05)

        return OptimizedOrder(
            original_request=order_request,
            optimized_requests=optimized_requests,
            tactic=OrderTactic.TWAP,
            expected_slippage_bps=expected_slippage,
            confidence_score=0.7,
            estimated_fill_time_ms=estimated_fill_time,
            reasoning=f"TWAP execution across {num_intervals} intervals",
        )

    # --------------------------- Pricing & Models ---------------------------

    def _calculate_optimal_passive_price(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> float:
        """Calculate optimal price for passive orders (small price improvement)."""
        base_price = float(order_request.price or 100.0)
        spread_bps = float(market_conditions.spread_bps)

        # Slight improvement to increase queue position/fill probability
        improvement_bps = min(spread_bps * 0.2, 1.0)  # cap at 1 bps
        if order_request.side.lower() == "buy":
            optimal = base_price * (1.0 + improvement_bps / 10_000.0)
        else:
            optimal = base_price * (1.0 - improvement_bps / 10_000.0)

        return self._round_price(optimal)

    def _estimate_passive_fill_time(self, market_conditions: MarketConditions) -> float:
        """Estimate fill time for passive orders (ms)."""
        base_time = 2000.0  # 2s base
        volume_factor = 1.0 / max(0.5, float(market_conditions.volume_ratio))
        # Higher vol → more trades → faster chances to get hit
        volatility_factor = 1.0 / max(0.1, float(market_conditions.volatility))

        estimated_time = base_time * volume_factor * volatility_factor
        # Clamp to 0.1s .. 30s range
        return max(100.0, min(30_000.0, estimated_time))

    def _calculate_iceberg_slice_size(
        self, total_size: float, market_conditions: MarketConditions
    ) -> float:
        """Calculate optimal slice size for iceberg orders."""
        base_slice_pct = 0.2  # 20%

        # Adjust for liquidity
        if market_conditions.volume_ratio > 1.5:
            base_slice_pct = 0.3
        elif market_conditions.volume_ratio < 0.5:
            base_slice_pct = 0.1

        # Adjust for volatility (smaller slices if high vol)
        if market_conditions.volatility > 0.03:
            base_slice_pct *= 0.8

        slice_size = max(0.0, total_size) * base_slice_pct
        min_slice = 0.01  # Exchange min lot may override elsewhere
        max_slice = max(0.01, total_size * 0.5)

        return max(min_slice, min(max_slice, slice_size))

    def _calculate_fill_probability(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> float:
        """Calculate probability of order being filled (0..1)."""
        base_probability = 0.8

        if order_request.order_type.lower() == "market":
            return 0.95

        # Spread sensitivity
        if market_conditions.spread_bps > 10.0:
            base_probability *= 0.7
        elif market_conditions.spread_bps < 2.0:
            base_probability *= 1.1

        # Post-only impacts queue priority
        if order_request.post_only:
            base_probability *= 0.6

        # Liquidity impact
        if market_conditions.volume_ratio > 1.5:
            base_probability *= 1.2
        elif market_conditions.volume_ratio < 0.5:
            base_probability *= 0.8

        return min(0.99, max(0.1, base_probability))

    # ------------------------------- Models -------------------------------


class SlippageModel:
    """Model for predicting order slippage"""

    def __init__(self, config: KrakenScalpingConfig):
        self.config = config
        self.base_slippage_bps = float(
            getattr(getattr(config, "scalp", object()), "base_slippage_bps", 2.0)
        )
        self.slippage_history: List[Dict] = []  # historical learning buffer

    def predict_slippage(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> float:
        """Predict slippage for an order (bps)."""
        if order_request.order_type.lower() == "market":
            base_slippage = max(0.0, market_conditions.spread_bps * 0.8)  # cross most of spread
        else:
            base_slippage = self.base_slippage_bps

        notional_value = float(order_request.size) * float(order_request.price or 100.0)
        impact_factor = min(2.0, max(0.5, notional_value / 1000.0))  # mild upscaling by size
        volatility_factor = 1.0 + max(0.0, float(market_conditions.volatility)) * 10.0
        liquidity_factor = 1.0 / max(0.5, float(market_conditions.volume_ratio))

        predicted = base_slippage * impact_factor * volatility_factor * liquidity_factor
        return max(0.0, float(predicted))

    def update_actual_slippage(
        self,
        order_request: OrderRequest,
        actual_slippage_bps: float,
        market_conditions: MarketConditions,
    ) -> None:
        """Update model with actual slippage data."""
        record = {
            "timestamp": time.time(),
            "symbol": order_request.symbol,
            "order_type": order_request.order_type,
            "size": float(order_request.size),
            "spread_bps": float(market_conditions.spread_bps),
            "volatility": float(market_conditions.volatility),
            "volume_ratio": float(market_conditions.volume_ratio),
            "actual_slippage_bps": float(actual_slippage_bps),
        }
        self.slippage_history.append(record)
        if len(self.slippage_history) > 1000:
            self.slippage_history = self.slippage_history[-1000:]


class TimingModel:
    """Model for predicting order fill times"""

    def __init__(self, config: KrakenScalpingConfig):
        self.config = config
        self.base_fill_time_ms = float(
            getattr(getattr(config, "scalp", object()), "base_fill_time_ms", 1000.0)
        )
        self.timing_history: List[Dict] = []

    def predict_fill_time(
        self, order_request: OrderRequest, market_conditions: MarketConditions
    ) -> float:
        """Predict time to fill for an order (ms)."""
        if order_request.order_type.lower() == "market":
            return 100.0

        base_time = self.base_fill_time_ms

        if market_conditions.volume_ratio > 1.5:
            base_time *= 0.5
        elif market_conditions.volume_ratio < 0.5:
            base_time *= 2.0

        if market_conditions.spread_bps > 5.0:
            base_time *= 1.5

        if order_request.post_only:
            base_time *= 2.0

        return max(100.0, min(30_000.0, float(base_time)))

    def update_actual_timing(
        self,
        order_request: OrderRequest,
        actual_fill_time_ms: float,
        market_conditions: MarketConditions,
    ) -> None:
        """Update model with actual timing data."""
        record = {
            "timestamp": time.time(),
            "symbol": order_request.symbol,
            "order_type": order_request.order_type,
            "post_only": bool(order_request.post_only),
            "spread_bps": float(market_conditions.spread_bps),
            "volume_ratio": float(market_conditions.volume_ratio),
            "actual_fill_time_ms": float(actual_fill_time_ms),
        }
        self.timing_history.append(record)
        if len(self.timing_history) > 1000:
            self.timing_history = self.timing_history[-1000:]

    # ------------------------------ Utilities ------------------------------

    def _validate_request(self, order_request: OrderRequest) -> None:
        """Basic input validation to avoid nonsense optimization outputs."""
        if not isinstance(order_request.size, (int, float)) or order_request.size <= 0:
            raise ValueError("Order size must be positive")
        if order_request.order_type.lower() == "limit":
            if order_request.price is None or order_request.price <= 0:
                raise ValueError("Limit order requires positive price")

    @staticmethod
    def _round_price(price: float) -> float:
        """
        Round to a conservative 1e-5 tick if exchange tick size not provided.
        (Gateway can handle precise tick rounding if available.)
        """
        return round(float(price), 5)
