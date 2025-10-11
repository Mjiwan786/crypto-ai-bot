"""
Advanced slippage modeling and prediction for scalping operations.

This module provides comprehensive slippage modeling capabilities for the scalping
system, implementing multiple models for accurate execution cost estimation and
market impact prediction to optimize order execution strategies.

Features:
- Multiple prediction methodologies (linear, sqrt, spread-based, volume-weighted)
- Market microstructure analysis and modeling
- Historical calibration and real-time adaptation
- Order size impact modeling and prediction
- Ensemble prediction with weighted averaging
- Performance tracking and model recalibration
- Component-based slippage decomposition

This module provides the core slippage modeling capabilities for the scalping
system, enabling intelligent execution cost prediction and optimization.
"""

from __future__ import annotations

import logging
import math
import statistics
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Tuple

from ..config_loader import KrakenScalpingConfig
from .kraken_gateway import OrderRequest, OrderResponse

logger = logging.getLogger(__name__)


class SlippageType(Enum):
    """Types of slippage"""

    SPREAD_CROSSING = "spread_crossing"  # Crossing bid-ask spread
    MARKET_IMPACT = "market_impact"  # Moving the market
    TIMING_DECAY = "timing_decay"  # Price movement while waiting
    EXECUTION_DELAY = "execution_delay"  # Latency-based slippage
    LIQUIDITY_SHORTAGE = "liquidity_shortage"  # Insufficient liquidity


@dataclass
class SlippageComponents:
    """Breakdown of slippage components"""

    spread_crossing_bps: float = 0.0
    market_impact_bps: float = 0.0
    timing_decay_bps: float = 0.0
    execution_delay_bps: float = 0.0
    liquidity_shortage_bps: float = 0.0

    @property
    def total_bps(self) -> float:
        """Total slippage in basis points"""
        return (
            self.spread_crossing_bps
            + self.market_impact_bps
            + self.timing_decay_bps
            + self.execution_delay_bps
            + self.liquidity_shortage_bps
        )


@dataclass
class MarketMicrostructure:
    """Market microstructure data for slippage modeling"""

    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    spread_bps: float
    book_depth: List[Tuple[float, float]]  # [(price, size), ...]
    recent_trades: List[Dict] = field(default_factory=list)
    volatility: float = 0.0
    volume_ratio: float = 1.0  # Current vs average volume
    timestamp: float = field(default_factory=time.time)


@dataclass
class SlippageEstimate:
    """Slippage estimate for an order"""

    order_request: OrderRequest
    predicted_slippage_bps: float
    confidence: float
    components: SlippageComponents
    methodology: str
    timestamp: float = field(default_factory=time.time)


class SlippageModel:
    """
    Advanced slippage prediction model for scalping operations.

    Features:
    - Multiple prediction methodologies
    - Market microstructure analysis
    - Historical calibration
    - Real-time adaptation
    - Order size impact modeling
    """

    def __init__(self, config: KrakenScalpingConfig, agent_id: str = "kraken_scalper"):
        self.config = config
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Base models (ensemble)
        self.base_models: Dict[str, BaseSlippageModel] = {
            "linear_impact": LinearImpactModel(config),
            "sqrt_impact": SqrtImpactModel(config),
            "spread_model": SpreadBasedModel(config),
            "volume_weighted": VolumeWeightedModel(config),
        }

        # Historical data for calibration
        self.execution_history: List[Dict] = []
        self.market_data_history: Dict[str, List[MarketMicrostructure]] = {}

        # Model weights (learned from performance)
        self.model_weights: Dict[str, float] = {
            "linear_impact": 0.25,
            "sqrt_impact": 0.25,
            "spread_model": 0.25,
            "volume_weighted": 0.25,
        }

        # Performance tracking
        self.prediction_errors: List[float] = []
        self.model_performance = {
            model_name: {"mae": 0.0, "rmse": 0.0, "accuracy": 0.0}
            for model_name in self.base_models.keys()
        }

        # Calibration parameters
        self.calibration_window = 500  # number of executions to use for calibration
        self.min_calibration_samples = 50

        self.logger.info("SlippageModel initialized")

    async def predict_slippage(
        self,
        order_request: OrderRequest,
        market_data: MarketMicrostructure,
        execution_urgency: float = 0.5,
    ) -> SlippageEstimate:
        """
        Predict slippage for an order given market conditions.
        """
        try:
            # Get predictions from all models
            model_predictions: Dict[str, float] = {}
            for model_name, model in self.base_models.items():
                prediction = await model.predict(order_request, market_data, execution_urgency)
                model_predictions[model_name] = max(0.0, float(prediction))

            # Ensemble prediction using weighted average
            ensemble_prediction = self._combine_predictions(model_predictions)

            # Confidence based on model agreement
            confidence = self._calculate_confidence(model_predictions)

            # Market-regime adjustment (vol/liquidity/spread)
            regime_adjustment = await self._apply_regime_adjustment(
                ensemble_prediction, market_data
            )
            final_prediction = max(0.0, ensemble_prediction + regime_adjustment)

            # Build component breakdown
            components = await self._decompose_slippage(
                order_request, market_data, final_prediction
            )

            estimate = SlippageEstimate(
                order_request=order_request,
                predicted_slippage_bps=final_prediction,
                confidence=confidence,
                components=components,
                methodology="ensemble_weighted",
            )

            self.logger.debug(
                "Slippage prediction: %s %s %.6f -> %.2f bps (conf=%.2f) models=%s",
                order_request.symbol,
                order_request.side,
                order_request.size,
                final_prediction,
                confidence,
                {k: round(v, 2) for k, v in model_predictions.items()},
            )

            return estimate

        except Exception as e:
            self.logger.error(f"Error predicting slippage: {e}")
            # Conservative fallback: at least 5 bps or 80% of spread for market
            fallback = max(market_data.spread_bps * 0.8, 5.0)
            return SlippageEstimate(
                order_request=order_request,
                predicted_slippage_bps=fallback,
                confidence=0.3,
                components=SlippageComponents(spread_crossing_bps=fallback),
                methodology="fallback",
            )

    async def update_with_execution(
        self,
        order_request: OrderRequest,
        order_response: OrderResponse,
        market_data: MarketMicrostructure,
        actual_slippage_bps: float,
    ) -> None:
        """Update model with actual execution results and track error metrics."""
        try:
            # Record execution data (minimal fields required for back-replay)
            execution_record = {
                "timestamp": time.time(),
                "symbol": order_request.symbol,
                "side": order_request.side,
                "order_type": order_request.order_type,
                "size": float(order_request.size),
                "requested_price": float(order_request.price) if order_request.price else None,
                "executed_price": (
                    float(order_response.avg_fill_price) if order_response.avg_fill_price else None
                ),
                "actual_slippage_bps": float(actual_slippage_bps),
                "spread_bps": float(market_data.spread_bps),
                "volatility": float(market_data.volatility),
                "volume_ratio": float(market_data.volume_ratio),
                "latency_ms": float(getattr(order_response, "latency_ms", 0.0)),
            }

            self.execution_history.append(execution_record)
            # Trim to 2x calibration window to bound memory
            if len(self.execution_history) > self.calibration_window * 2:
                self.execution_history = self.execution_history[-self.calibration_window :]

            # Update individual models
            for model in self.base_models.values():
                await model.update_with_execution(execution_record)

            # Compute ensemble prediction at the time of update for error tracking
            try:
                reconstruct_market = MarketMicrostructure(
                    symbol=execution_record["symbol"],
                    bid=market_data.bid,
                    ask=market_data.ask,
                    bid_size=market_data.bid_size,
                    ask_size=market_data.ask_size,
                    spread_bps=execution_record["spread_bps"],
                    book_depth=market_data.book_depth,
                    volatility=execution_record["volatility"],
                    volume_ratio=execution_record["volume_ratio"],
                )
                reconstructed_order = OrderRequest(
                    symbol=execution_record["symbol"],
                    side=execution_record["side"],
                    order_type=execution_record["order_type"],
                    size=execution_record["size"],
                    price=execution_record["requested_price"],
                )
                model_predictions = {
                    name: max(
                        0.0,
                        float(await model.predict(reconstructed_order, reconstruct_market, 0.5)),
                    )
                    for name, model in self.base_models.items()
                }
                predicted_bps = self._combine_predictions(model_predictions)
                error = abs(predicted_bps - execution_record["actual_slippage_bps"])
                self.prediction_errors.append(error)
                if len(self.prediction_errors) > self.calibration_window * 2:
                    self.prediction_errors = self.prediction_errors[-self.calibration_window :]
            except Exception as ex_calc:
                self.logger.debug(f"Error computing prediction error: {ex_calc}")

            # Recalibrate ensemble weights if we have enough samples
            if len(self.execution_history) >= self.min_calibration_samples:
                await self._recalibrate_models()

            self.logger.debug(
                "Updated slippage model with execution: %.2f bps", actual_slippage_bps
            )

        except Exception as e:
            self.logger.error(f"Error updating slippage model: {e}")

    async def get_model_performance(self) -> Dict[str, Any]:
        """Get current model performance metrics"""
        return {
            "model_weights": self.model_weights.copy(),
            "model_performance": self.model_performance.copy(),
            "total_executions": len(self.execution_history),
            "avg_prediction_error": (
                statistics.mean(self.prediction_errors) if self.prediction_errors else 0.0
            ),
            "prediction_std": (
                statistics.stdev(self.prediction_errors) if len(self.prediction_errors) > 1 else 0.0
            ),
        }

    # ---------- Private helpers ----------

    def _combine_predictions(self, model_predictions: Dict[str, float]) -> float:
        """Combine predictions from multiple models using weighted average."""
        weighted_sum = 0.0
        total_weight = 0.0
        for model_name, prediction in model_predictions.items():
            weight = float(self.model_weights.get(model_name, 0.0))
            weighted_sum += float(prediction) * weight
            total_weight += weight

        if total_weight > 1e-12:
            return max(0.0, weighted_sum / total_weight)
        # Fallback to simple mean if weights degenerate
        return max(0.0, statistics.mean(model_predictions.values())) if model_predictions else 0.0

    def _calculate_confidence(self, model_predictions: Dict[str, float]) -> float:
        """Confidence based on cross-model agreement (1 - CoV)."""
        if not model_predictions:
            return 0.5
        preds = list(model_predictions.values())
        mean_pred = statistics.mean(preds)
        if mean_pred <= 0:
            return 0.5
        std_pred = statistics.pstdev(preds) if len(preds) > 1 else 0.0
        cv = std_pred / mean_pred
        return max(0.1, min(0.95, 1.0 - cv))

    async def _apply_regime_adjustment(
        self, base_prediction: float, market_data: MarketMicrostructure
    ) -> float:
        """Apply market regime adjustments to prediction."""
        adjustment = 0.0

        # High volatility increases slippage
        if market_data.volatility > 0.03:  # 3% daily vol
            adjustment += base_prediction * 0.20

        # Low liquidity (low volume ratio) increases slippage
        if market_data.volume_ratio < 0.5:
            adjustment += base_prediction * 0.30

        # Wide spreads increase slippage
        if market_data.spread_bps > 8.0:
            adjustment += base_prediction * 0.15

        # Clamp to sensible bounds
        return max(-base_prediction * 0.5, min(adjustment, base_prediction * 1.5))

    async def _decompose_slippage(
        self, order_request: OrderRequest, market_data: MarketMicrostructure, total_slippage: float
    ) -> SlippageComponents:
        """Heuristic decomposition of total slippage into components."""
        # Spread crossing (for market orders only)
        spread_component = (
            market_data.spread_bps * 0.8 if order_request.order_type == "market" else 0.0
        )

        # Market impact (proportional to notional)
        notional = float(order_request.size) * float(order_request.price or market_data.ask)
        if notional > 1000.0:
            impact_component = min(total_slippage * 0.4, 3.0)  # cap at 3 bps
        else:
            impact_component = 0.0

        # Timing decay (volatility proxy)
        timing_component = max(0.0, market_data.volatility * 100.0 * 0.5)  # 50% of vol in bps

        # Execution delay (latency-based) — very small for this stack
        delay_component = 0.1

        # Whatever remains is attributed to liquidity shortage
        liquidity_component = max(
            0.0,
            total_slippage
            - spread_component
            - impact_component
            - timing_component
            - delay_component,
        )

        return SlippageComponents(
            spread_crossing_bps=spread_component,
            market_impact_bps=impact_component,
            timing_decay_bps=timing_component,
            execution_delay_bps=delay_component,
            liquidity_shortage_bps=liquidity_component,
        )

    async def _recalibrate_models(self) -> None:
        """Recalibrate ensemble weights using recent execution errors."""
        try:
            if len(self.execution_history) < self.min_calibration_samples:
                return

            recent = self.execution_history[-self.calibration_window :]
            model_errors: Dict[str, List[float]] = {name: [] for name in self.base_models.keys()}

            # Build a light reconstruction context per execution
            for ex in recent:
                market = MarketMicrostructure(
                    symbol=ex["symbol"],
                    bid=0.0,
                    ask=0.0,
                    bid_size=0.0,
                    ask_size=0.0,
                    spread_bps=ex["spread_bps"],
                    book_depth=[],
                    volatility=ex["volatility"],
                    volume_ratio=ex["volume_ratio"],
                )
                order = OrderRequest(
                    symbol=ex["symbol"],
                    side=ex["side"],
                    order_type=ex["order_type"],
                    size=ex["size"],
                    price=ex["requested_price"],
                )

                actual = float(ex["actual_slippage_bps"])
                for name, model in self.base_models.items():
                    try:
                        pred = float(await model.predict(order, market, 0.5))
                        model_errors[name].append(abs(pred - actual))
                    except Exception as model_err:
                        self.logger.debug("Calibration error for model %s: %s", name, model_err)

            # Compute inverse-error weights
            inverse: Dict[str, float] = {}
            total_inv = 0.0
            for name, errs in model_errors.items():
                if errs:
                    mae = statistics.mean(errs)
                    rmse = math.sqrt(statistics.mean([e * e for e in errs]))
                    inv = 1.0 / (1.0 + mae)  # smooth inverse
                    inverse[name] = inv
                    total_inv += inv
                    # update performance
                    self.model_performance[name]["mae"] = mae
                    self.model_performance[name]["rmse"] = rmse

            if total_inv > 0:
                for name in self.model_weights.keys():
                    self.model_weights[name] = (
                        (inverse.get(name, 0.0) / total_inv) if total_inv else 0.0
                    )

                self.logger.info(
                    "Recalibrated model weights: %s",
                    {k: round(v, 3) for k, v in self.model_weights.items()},
                )

        except Exception as e:
            self.logger.error(f"Error recalibrating models: {e}")


# ----------------- Base and concrete models -----------------


class BaseSlippageModel:
    """Base class for individual slippage models"""

    def __init__(self, config: KrakenScalpingConfig):
        self.config = config
        self.parameters: Dict[str, float] = {}
        self.calibration_data: List[Dict[str, Any]] = []

    async def predict(
        self, order_request: OrderRequest, market_data: MarketMicrostructure, urgency: float
    ) -> float:
        """Predict slippage in basis points"""
        raise NotImplementedError

    async def update_with_execution(self, execution_record: Dict[str, Any]) -> None:
        """Update model with execution data"""
        self.calibration_data.append(execution_record)
        if len(self.calibration_data) > 1000:
            self.calibration_data = self.calibration_data[-1000:]


class LinearImpactModel(BaseSlippageModel):
    """Linear market impact model"""

    def __init__(self, config: KrakenScalpingConfig):
        super().__init__(config)
        self.impact_coefficient = 0.5  # bps per $1000 notional

    async def predict(
        self, order_request: OrderRequest, market_data: MarketMicrostructure, urgency: float
    ) -> float:
        """Linear impact: slippage = base + coefficient * notional"""
        base_slippage = market_data.spread_bps * max(0.0, min(1.0, urgency))
        notional = float(order_request.size) * float(order_request.price or market_data.ask)
        impact_slippage = (notional / 1000.0) * self.impact_coefficient
        return max(0.0, base_slippage + impact_slippage)


class SqrtImpactModel(BaseSlippageModel):
    """Square root market impact model (more realistic for large orders)"""

    def __init__(self, config: KrakenScalpingConfig):
        super().__init__(config)
        self.impact_coefficient = 1.0

    async def predict(
        self, order_request: OrderRequest, market_data: MarketMicrostructure, urgency: float
    ) -> float:
        """Square root impact: slippage = base + coefficient * sqrt(notional/1000)"""
        base_slippage = market_data.spread_bps * max(0.0, min(1.0, urgency))
        notional = float(order_request.size) * float(order_request.price or market_data.ask)
        impact_slippage = self.impact_coefficient * math.sqrt(max(0.0, notional / 1000.0))
        return max(0.0, base_slippage + impact_slippage)


class SpreadBasedModel(BaseSlippageModel):
    """Spread-based slippage model"""

    async def predict(
        self, order_request: OrderRequest, market_data: MarketMicrostructure, urgency: float
    ) -> float:
        """Slippage based on spread and urgency"""
        if order_request.order_type == "market":
            base_slippage = market_data.spread_bps * 0.8
        else:
            base_slippage = market_data.spread_bps * 0.2
        urgency_adjustment = base_slippage * max(0.0, min(1.0, urgency)) * 0.5
        volatility_adjustment = max(0.0, market_data.volatility) * 50.0  # 50 bps per 1% vol
        return max(0.0, base_slippage + urgency_adjustment + volatility_adjustment)


class VolumeWeightedModel(BaseSlippageModel):
    """Volume-weighted slippage model"""

    async def predict(
        self, order_request: OrderRequest, market_data: MarketMicrostructure, urgency: float
    ) -> float:
        """Slippage based on volume and liquidity"""
        base_slippage = market_data.spread_bps * 0.5

        # Volume/liquidity adjustment
        if market_data.volume_ratio > 1.5:
            volume_adjustment = -base_slippage * 0.3
        elif market_data.volume_ratio < 0.5:
            volume_adjustment = base_slippage * 0.5
        else:
            volume_adjustment = 0.0

        notional = float(order_request.size) * float(order_request.price or market_data.ask)
        size_adjustment = min(notional / 5000.0, 1.0) * base_slippage  # cap at 1x base

        # Urgency adds a small constant slope
        return max(
            0.0,
            base_slippage
            + volume_adjustment
            + size_adjustment
            + (max(0.0, min(1.0, urgency)) * 2.0),
        )
