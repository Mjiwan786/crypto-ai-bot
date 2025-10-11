"""
ai_engine/strategy_selector.py

Production-ready deterministic meta-strategy selector for crypto-ai-bot.
Given per-symbol Signals, current positions/limits, and selector config,
decides open/close/reduce/hold actions with bounded allocations.

Pure logic only - no I/O, no env reads, no wall-clock dependencies.
Deterministic: same inputs → same outputs.
"""

import logging
import math
import re
from decimal import Decimal, ROUND_HALF_EVEN
from enum import Enum
from typing import Any, Dict, Optional, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

logger = logging.getLogger(__name__)

# Validation patterns
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}([:/-][A-Z0-9]{2,20})?$", re.ASCII)
_TIMEFRAME_RE = re.compile(r"^\d+[mhdw]$", re.ASCII)


class Action(str, Enum):
    """Trading action to take"""
    OPEN = "open"
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"


class Side(str, Enum):
    """Position side"""
    LONG = "long"
    SHORT = "short"
    NONE = "none"


class SignalLike(Protocol):
    """Duck-type protocol for signal inputs"""
    side: str
    score: float
    confidence: float


def _is_finite(value: float) -> bool:
    """Check if value is finite (not NaN or Inf)"""
    return math.isfinite(value)


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value to range [min_val, max_val]"""
    return max(min_val, min(max_val, value))


def _round_to_step(value: float, step: float) -> float:
    """Round value to nearest multiple of step using banker's rounding (ROUND_HALF_EVEN)"""
    if step <= 0:
        return value
    # Use Decimal for precise banker's rounding
    decimal_value = Decimal(str(value))
    decimal_step = Decimal(str(step))
    # Round to nearest step
    rounded = (decimal_value / decimal_step).quantize(
        Decimal("1"), rounding=ROUND_HALF_EVEN
    ) * decimal_step
    return float(rounded)


class PositionSnapshot(BaseModel):
    """Current position state for a symbol"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(description="Trading symbol")
    timeframe: str = Field(description="Strategy timeframe")
    side: Side = Field(description="Current position side")
    allocation: float = Field(ge=0.0, le=1.0, description="Current allocation [0..1]")
    avg_entry_px: Optional[float] = Field(default=None, description="Average entry price")

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        v = v.upper()
        if not _SYMBOL_RE.match(v):
            raise ValueError(f"Invalid symbol format: {v}")
        return v

    @field_validator("timeframe")
    @classmethod
    def _validate_timeframe(cls, v: str) -> str:
        if not _TIMEFRAME_RE.match(v):
            raise ValueError(f"Invalid timeframe format: {v}")
        return v

    @field_validator("avg_entry_px")
    @classmethod
    def _validate_avg_entry_px(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not _is_finite(v):
            raise ValueError("avg_entry_px must be finite")
        return v


class LimitsConfig(BaseModel):
    """Position and allocation limits"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_allocation: float = Field(default=1.0, gt=0.0, le=1.0, description="Cap per symbol")
    max_gross_allocation: float = Field(default=2.0, gt=0.0, description="Cap across all symbols")
    step_allocation: float = Field(default=0.25, gt=0.0, le=1.0, description="Min increment/decrement")
    min_conf_to_open: float = Field(default=0.55, ge=0.0, le=1.0, description="Confidence to open/raise")
    min_conf_to_flip: float = Field(default=0.65, ge=0.0, le=1.0, description="Confidence to reverse side")
    min_conf_to_close: float = Field(default=0.35, ge=0.0, le=1.0, description="Allow close threshold")
    reduce_on_dip_conf: float = Field(default=0.45, ge=0.0, le=1.0, description="Reduce on confidence dip")

    @model_validator(mode="after")
    def _validate_ordering(self) -> "LimitsConfig":
        """Validate confidence threshold ordering"""
        if not (self.min_conf_to_close <= self.reduce_on_dip_conf <=
                self.min_conf_to_open <= self.min_conf_to_flip):
            raise ValueError(
                "Confidence thresholds must be ordered: "
                "min_conf_to_close ≤ reduce_on_dip_conf ≤ min_conf_to_open ≤ min_conf_to_flip"
            )
        if self.max_gross_allocation < self.max_allocation:
            raise ValueError("max_gross_allocation must be ≥ max_allocation")
        return self


class RiskConfig(BaseModel):
    """Risk management parameters"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    daily_stop_usd: float = Field(default=0.0, ge=0.0, description="Daily loss limit")
    spread_bps_cap: float = Field(default=50.0, gt=0.0, description="Max spread in bps")
    latency_budget_ms: int = Field(default=100, gt=0, description="Latency budget in ms")


class SelectorConfig(BaseModel):
    """Complete selector configuration"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0", description="Schema version")
    limits: LimitsConfig = Field(description="Position limits")
    risk: RiskConfig = Field(description="Risk parameters")


class SelectorDecision(BaseModel):
    """Decision for a single symbol"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0", description="Schema version")
    symbol: str = Field(description="Trading symbol")
    timeframe: str = Field(description="Strategy timeframe")
    action: Action = Field(description="Action to take")
    side: Side = Field(description="Target side")
    target_allocation: float = Field(ge=0.0, le=1.0, description="Desired allocation")
    order_allocation_delta: float = Field(description="Allocation change (+ add, - remove)")
    confidence: float = Field(ge=0.0, le=1.0, description="Decision confidence")
    explain: str = Field(description="Decision explanation")
    diagnostics: Dict[str, float] = Field(description="Diagnostic metrics")

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, v: str) -> str:
        v = v.upper()
        if not _SYMBOL_RE.match(v):
            raise ValueError(f"Invalid symbol format: {v}")
        return v

    @field_validator("timeframe")
    @classmethod
    def _validate_timeframe(cls, v: str) -> str:
        if not _TIMEFRAME_RE.match(v):
            raise ValueError(f"Invalid timeframe format: {v}")
        return v

    @field_validator("diagnostics")
    @classmethod
    def _validate_diagnostics(cls, v: Dict[str, float]) -> Dict[str, float]:
        for key, val in v.items():
            if not isinstance(val, (int, float)) or not _is_finite(val):
                raise ValueError(f"Diagnostic {key} must be finite: {val}")
        return v

    @field_serializer("diagnostics", mode="plain")
    def _serialize_diagnostics(self, v: Dict[str, float]) -> Dict[str, float]:
        """Serialize diagnostics with sorted keys for determinism"""
        return {k: v[k] for k in sorted(v.keys())}


class SelectorPlan(BaseModel):
    """Batch plan for multiple symbols"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    decisions: Dict[str, SelectorDecision] = Field(description="Decisions by symbol")

    @field_serializer("decisions", mode="plain")
    def _serialize_decisions(self, v: Dict[str, SelectorDecision]) -> Dict[str, SelectorDecision]:
        """Serialize decisions with sorted keys for determinism"""
        return {k: v[k] for k in sorted(v.keys())}


def select_for_symbol(
    symbol: str,
    timeframe: str,
    signal: SignalLike,
    position: PositionSnapshot,
    cfg: SelectorConfig,
    *,
    daily_pnl_usd: float = 0.0,
    spread_bps: Optional[float] = None,
    latency_ms: Optional[int] = None,
) -> SelectorDecision:
    """
    Pure and deterministic strategy selection for a single symbol.

    Args:
        symbol: Trading symbol
        timeframe: Strategy timeframe
        signal: Signal with side, score, confidence
        position: Current position state
        cfg: Selector configuration
        daily_pnl_usd: Daily P&L (negative = loss)
        spread_bps: Current spread in basis points
        latency_ms: Current latency in milliseconds

    Returns:
        SelectorDecision with action, allocations, and diagnostics
    """
    # Validate inputs
    symbol = symbol.upper()
    if not _SYMBOL_RE.match(symbol):
        raise ValueError(f"Invalid symbol: {symbol}")
    if not _TIMEFRAME_RE.match(timeframe):
        raise ValueError(f"Invalid timeframe: {timeframe}")

    # Extract signal data with validation
    sig_side = getattr(signal, "side", "none").lower()
    sig_score = float(getattr(signal, "score", 0.0))
    sig_conf = float(getattr(signal, "confidence", 0.0))

    if not _is_finite(sig_score) or not _is_finite(sig_conf):
        raise ValueError("Signal score and confidence must be finite")

    sig_score = _clamp(sig_score, -1.0, 1.0)
    sig_conf = _clamp(sig_conf, 0.0, 1.0)

    # Current state
    cur_side = position.side
    cur_alloc = position.allocation

    # Initialize decision variables
    action = Action.HOLD
    target_side = Side.NONE
    target_alloc = cur_alloc
    confidence = sig_conf
    reasons = []
    diagnostics = {
        "sig_score": sig_score,
        "sig_conf": sig_conf,
        "cur_alloc": cur_alloc,
        "daily_pnl_usd": daily_pnl_usd,
        "step": cfg.limits.step_allocation,
        "max_alloc": cfg.limits.max_allocation,
    }

    if spread_bps is not None and _is_finite(float(spread_bps)):
        diagnostics["spread_bps"] = float(spread_bps)
    if latency_ms is not None and _is_finite(float(latency_ms)):
        diagnostics["latency_ms"] = float(latency_ms)

    # Determine desired side and magnitude
    if sig_side == "none" or abs(sig_score) < 1e-6:
        target_side = Side.NONE
        desired_magnitude = 0.0
    else:
        target_side = Side.LONG if sig_side in ("long", "buy") else Side.SHORT
        desired_magnitude = min(abs(sig_score), cfg.limits.max_allocation)

    # Risk gating (with finite checks)
    daily_stop_breached = (
        cfg.risk.daily_stop_usd > 0 and daily_pnl_usd <= -cfg.risk.daily_stop_usd
    )
    spread_too_wide = (
        spread_bps is not None
        and _is_finite(float(spread_bps))
        and float(spread_bps) > cfg.risk.spread_bps_cap
    )
    latency_high = (
        latency_ms is not None
        and _is_finite(float(latency_ms))
        and float(latency_ms) > float(cfg.risk.latency_budget_ms)
    )

    if daily_stop_breached:
        reasons.append("daily_stop")
        diagnostics["daily_stop"] = 1.0
    if spread_too_wide:
        reasons.append("spread_cap_exceeded")
        diagnostics["spread_cap_exceeded"] = 1.0
    if latency_high:
        reasons.append("latency_over_budget")
        diagnostics["latency_over_budget"] = 1.0

    # Decision logic
    if cur_side == Side.NONE:
        # Currently flat
        if target_side == Side.NONE:
            action = Action.HOLD
            target_alloc = 0.0
            reasons.append("signal_none")
        elif (
            sig_conf >= cfg.limits.min_conf_to_open
            and not daily_stop_breached
            and not spread_too_wide
        ):
            action = Action.OPEN
            target_alloc = _round_to_step(desired_magnitude, cfg.limits.step_allocation)
            target_alloc = _clamp(target_alloc, 0.0, cfg.limits.max_allocation)
            reasons.append("open_new")
        else:
            action = Action.HOLD
            target_alloc = 0.0
            if sig_conf < cfg.limits.min_conf_to_open:
                reasons.append("conf_too_low")
            if daily_stop_breached:
                reasons.append("risk_block")
            if spread_too_wide:
                reasons.append("spread_block")

    elif cur_side == target_side:
        # Same side, consider scaling
        if target_side == Side.NONE:
            # Signal went to none, close position if allowed by min_conf_to_close
            if sig_conf >= cfg.limits.min_conf_to_close:
                action = Action.CLOSE
                target_alloc = 0.0
                reasons.append("close_signal_none")
            elif cur_alloc > cfg.limits.step_allocation:
                action = Action.REDUCE
                target_alloc = _round_to_step(
                    max(0.0, cur_alloc - cfg.limits.step_allocation),
                    cfg.limits.step_allocation,
                )
                reasons.append("reduce_toward_none")
            else:
                action = Action.CLOSE
                target_alloc = 0.0
                reasons.append("close_final_step")
        else:
            # Same side, check if we should adjust
            desired_alloc = _round_to_step(desired_magnitude, cfg.limits.step_allocation)
            desired_alloc = _clamp(desired_alloc, 0.0, cfg.limits.max_allocation)

            if desired_alloc > cur_alloc:
                # Want to increase
                if (
                    sig_conf >= cfg.limits.min_conf_to_open
                    and not daily_stop_breached
                    and not spread_too_wide
                ):
                    action = Action.OPEN
                    target_alloc = desired_alloc
                    reasons.append("raise_exposure")
                else:
                    action = Action.HOLD
                    target_alloc = cur_alloc
                    reasons.append("hold_cant_raise")
            elif desired_alloc < cur_alloc:
                # Want to decrease
                if sig_conf < cfg.limits.min_conf_to_close:
                    action = Action.CLOSE if desired_alloc == 0 else Action.REDUCE
                    target_alloc = desired_alloc
                    reasons.append("reduce_low_conf")
                elif cfg.limits.reduce_on_dip_conf <= sig_conf < cfg.limits.min_conf_to_open:
                    action = Action.REDUCE
                    target_alloc = _round_to_step(
                        max(0.0, cur_alloc - cfg.limits.step_allocation),
                        cfg.limits.step_allocation,
                    )
                    reasons.append("reduce_on_dip")
                else:
                    action = Action.HOLD
                    target_alloc = cur_alloc
                    reasons.append("hold_same_side")
            else:
                # Desired equals current
                action = Action.HOLD
                target_alloc = cur_alloc
                reasons.append("hold_optimal")

    else:
        # Opposite side, need to flip or close
        if target_side == Side.NONE:
            # Signal is none, close position
            if cur_alloc > cfg.limits.step_allocation:
                action = Action.REDUCE
                target_alloc = _round_to_step(
                    max(0.0, cur_alloc - cfg.limits.step_allocation),
                    cfg.limits.step_allocation,
                )
                reasons.append("reduce_to_none")
            else:
                action = Action.CLOSE
                target_alloc = 0.0
                reasons.append("close_to_none")
        elif (
            sig_conf >= cfg.limits.min_conf_to_flip
            and not daily_stop_breached
            and not spread_too_wide
        ):
            # High confidence flip
            action = Action.OPEN  # Will close current and open new
            desired_alloc = _round_to_step(desired_magnitude, cfg.limits.step_allocation)
            target_alloc = _clamp(desired_alloc, 0.0, cfg.limits.max_allocation)
            reasons.append("flip_side")
        else:
            # Not confident enough to flip, reduce toward neutral
            if cur_alloc > cfg.limits.step_allocation:
                action = Action.REDUCE
                target_alloc = _round_to_step(
                    max(0.0, cur_alloc - cfg.limits.step_allocation),
                    cfg.limits.step_allocation,
                )
                reasons.append("reduce_toward_flip")
            else:
                action = Action.CLOSE
                target_alloc = 0.0
                reasons.append("close_cant_flip")

    # Normalize target allocation to grid and cap, then set final target side
    target_alloc = _clamp(
        _round_to_step(target_alloc, cfg.limits.step_allocation),
        0.0,
        cfg.limits.max_allocation,
    )

    # Set final target side based on target allocation
    if target_alloc == 0.0:
        final_side = Side.NONE
    else:
        final_side = target_side

    # Apply constraints and compute confidence adjustment (reporting only)
    confidence_penalty = 0.0
    if daily_stop_breached or spread_too_wide:
        confidence_penalty = 0.05
    final_confidence = max(0.0, confidence - confidence_penalty)

    # Compute allocation delta
    order_delta = target_alloc - cur_alloc

    # Final diagnostics
    diagnostics.update({
        "target_pre_cap": target_alloc,
        "target_post_cap": target_alloc,
        "order_delta": order_delta,
        "confidence_penalty": confidence_penalty,
        "risk_constraints": float(
            int(bool(diagnostics.get("daily_stop", 0.0))) +
            int(bool(diagnostics.get("spread_cap_exceeded", 0.0))) +
            int(bool(diagnostics.get("latency_over_budget", 0.0)))
        ),
    })

    # Build explanation (deterministic wording & ordering)
    explain_parts = [
        f"{action.value}",
        f"side={final_side.value}",
        f"alloc={cur_alloc:.3f}→{target_alloc:.3f}",
        f"conf={final_confidence:.3f}",
    ]
    if reasons:
        explain_parts.append(f"reasons={','.join(sorted(reasons))}")
    explain = " ".join(explain_parts)

    logger.info(
        f"Symbol {symbol}: {action.value} {final_side.value} "
        f"{cur_alloc:.3f}→{target_alloc:.3f} conf={final_confidence:.3f} "
        f"reasons={','.join(sorted(reasons)) if reasons else 'none'}"
    )
    logger.debug(f"Symbol {symbol} diagnostics: {diagnostics}")

    return SelectorDecision(
        symbol=symbol,
        timeframe=timeframe,
        action=action,
        side=final_side,
        target_allocation=target_alloc,
        order_allocation_delta=order_delta,
        confidence=final_confidence,
        explain=explain,
        diagnostics=diagnostics,
    )


def plan_for_universe(
    signals: Dict[str, SignalLike],
    positions: Dict[str, PositionSnapshot],
    cfg: SelectorConfig,
    *,
    timeframe: str,
    daily_pnl_usd: float = 0.0,
    spread_bps_by_symbol: Optional[Dict[str, float]] = None,
    latency_ms_by_symbol: Optional[Dict[str, int]] = None,
) -> SelectorPlan:
    """
    Build a deterministic plan for multiple symbols with gross allocation limits.

    Args:
        signals: Signal by symbol
        positions: Position snapshot by symbol
        cfg: Selector configuration
        timeframe: Strategy timeframe
        daily_pnl_usd: Daily P&L
        spread_bps_by_symbol: Spread by symbol
        latency_ms_by_symbol: Latency by symbol

    Returns:
        SelectorPlan with decisions for all symbols
    """
    if not _TIMEFRAME_RE.match(timeframe):
        raise ValueError(f"Invalid timeframe: {timeframe}")

    decisions: Dict[str, SelectorDecision] = {}
    spread_map = spread_bps_by_symbol or {}
    latency_map = latency_ms_by_symbol or {}

    # Process each symbol individually first
    for symbol in sorted(set(signals.keys()) | set(positions.keys())):
        signal = signals.get(symbol)
        position = positions.get(symbol)

        if signal is None or position is None:
            continue

        spread_bps = spread_map.get(symbol)
        latency_ms = latency_map.get(symbol)

        try:
            decision = select_for_symbol(
                symbol=symbol,
                timeframe=timeframe,
                signal=signal,
                position=position,
                cfg=cfg,
                daily_pnl_usd=daily_pnl_usd,
                spread_bps=spread_bps,
                latency_ms=latency_ms,
            )
            decisions[symbol] = decision
        except Exception as e:  # pragma: no cover - defensive
            logger.exception(f"Error processing symbol {symbol}: {e}")
            # Create safe HOLD decision (deterministic fallback)
            safe_alloc = position.allocation if position else 0.0
            decisions[symbol] = SelectorDecision(
                symbol=symbol,
                timeframe=timeframe,
                action=Action.HOLD,
                side=position.side if position else Side.NONE,
                target_allocation=safe_alloc,
                order_allocation_delta=0.0,
                confidence=0.0,
                explain=f"hold error={type(e).__name__}",
                diagnostics={
                    "error": 1.0,
                    "target_pre_cap": safe_alloc,
                    "target_post_cap": safe_alloc,
                    "order_delta": 0.0,
                    "gross_cap_limit": cfg.limits.max_gross_allocation,
                },
            )

    # Check gross allocation constraint (deterministic order)
    total_target = sum(decisions[k].target_allocation for k in sorted(decisions.keys()))

    if total_target > cfg.limits.max_gross_allocation:
        # Scale down proportionally (deterministic by symbol order)
        scale_factor = cfg.limits.max_gross_allocation / total_target
        logger.info(
            f"Scaling allocations by {scale_factor:.3f} "
            f"(total {total_target:.3f} > limit {cfg.limits.max_gross_allocation})"
        )

        scaled_decisions: Dict[str, SelectorDecision] = {}
        for symbol in sorted(decisions.keys()):
            decision = decisions[symbol]
            original_target = decision.target_allocation
            scaled_target = original_target * scale_factor

            # Round to step and recompute delta
            scaled_target = _round_to_step(scaled_target, cfg.limits.step_allocation)
            scaled_target = _clamp(scaled_target, 0.0, cfg.limits.max_allocation)

            position = positions[symbol]
            new_delta = scaled_target - position.allocation

            # Update diagnostics and explanation
            new_diagnostics = dict(decision.diagnostics)
            new_diagnostics.update({
                "scale_factor": float(scale_factor),
                "gross_cap_limit": cfg.limits.max_gross_allocation,
                "target_pre_cap": original_target,
                "target_post_cap": scaled_target,
                "order_delta": new_delta,
            })

            new_explain = decision.explain + " scaled_to_gross_cap"

            scaled_decisions[symbol] = SelectorDecision(
                schema_version=decision.schema_version,
                symbol=symbol,
                timeframe=timeframe,
                action=decision.action,
                side=decision.side,
                target_allocation=scaled_target,
                order_allocation_delta=new_delta,
                confidence=decision.confidence,
                explain=new_explain,
                diagnostics=new_diagnostics,
            )

        # Assign scaled decisions
        decisions = scaled_decisions

        # Deterministic residual trim after rounding to ensure gross cap compliance
        step = cfg.limits.step_allocation
        max_gross = cfg.limits.max_gross_allocation
        total_after_round = sum(decisions[k].target_allocation for k in sorted(decisions.keys()))

        if total_after_round > max_gross and step > 0:
            while total_after_round > max_gross:
                for symbol in sorted(decisions.keys()):
                    if total_after_round <= max_gross:
                        break
                    d = decisions[symbol]
                    new_target = max(0.0, d.target_allocation - step)
                    if new_target < d.target_allocation:
                        pos_alloc = positions[symbol].allocation
                        new_delta = new_target - pos_alloc
                        new_diag = dict(d.diagnostics)
                        new_diag.update({
                            "gross_cap_limit": max_gross,
                            "target_post_cap": new_target,
                            "order_delta": new_delta,
                        })
                        decisions[symbol] = SelectorDecision(
                            schema_version=d.schema_version,
                            symbol=symbol,
                            timeframe=timeframe,
                            action=d.action,
                            side=d.side,
                            target_allocation=new_target,
                            order_allocation_delta=new_delta,
                            confidence=d.confidence,
                            explain=d.explain + " gross_cap_trim",
                            diagnostics=new_diag,
                        )
                        total_after_round -= (d.target_allocation - new_target)

    return SelectorPlan(decisions=decisions)


# Optional adapters (implement if modules are available)
try:
    from ai_engine.schemas import StrategyDecision

    def to_internal_strategy_decision(
        sd: SelectorDecision,
        *,
        max_position_usd: float,
        sl_multiplier: float,
        tp_multiplier: float,
    ) -> StrategyDecision:
        """Convert SelectorDecision to internal StrategyDecision (pure adapter)"""
        return StrategyDecision(
            type="strategy.decision",
            strategy="meta_selector",
            symbol=sd.symbol,
            timeframe=sd.timeframe,
            side=sd.side,
            action=sd.action,
            confidence=sd.confidence,
            target_allocation=sd.target_allocation,
            order_allocation_delta=sd.order_allocation_delta,
            max_position_usd=max_position_usd,
            sl_multiplier=sl_multiplier,
            tp_multiplier=tp_multiplier,
            metadata={
                "explain": sd.explain,
                "diagnostics": sd.diagnostics,
            },
        )

except ImportError:
    def to_internal_strategy_decision(*args, **kwargs):
        raise ImportError("ai_engine.schemas.StrategyDecision not available")


try:
    from ai_engine.events import StrategyDecisionEvent

    def to_strategy_decision_event(
        sd: SelectorDecision,
        *,
        base_event_kwargs: Dict[str, Any],
        max_position_usd: float,
        sl_multiplier: float,
        tp_multiplier: float,
    ) -> "StrategyDecisionEvent":
        """Convert SelectorDecision to wire event (pure adapter)"""
        return StrategyDecisionEvent(
            **base_event_kwargs,
            strategy="meta_selector",
            symbol=sd.symbol,
            timeframe=sd.timeframe,
            side=sd.side,
            action=sd.action,
            confidence=sd.confidence,
            target_allocation=sd.target_allocation,
            order_allocation_delta=sd.order_allocation_delta,
            max_position_usd=max_position_usd,
            sl_multiplier=sl_multiplier,
            tp_multiplier=tp_multiplier,
            explain=sd.explain,
            diagnostics=sd.diagnostics,
        )

except ImportError:
    def to_strategy_decision_event(*args, **kwargs):
        raise ImportError("ai_engine.events.StrategyDecisionEvent not available")


if __name__ == "__main__":
    """Self-check with synthetic signals and positions (no side effects on import)"""

    # Configure logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Create synthetic signal-like objects
    class MockSignal:
        def __init__(self, side: str, score: float, confidence: float):
            self.side = side
            self.score = score
            self.confidence = confidence

    # Test signals
    btc_signal = MockSignal("long", 0.6, 0.7)
    eth_signal = MockSignal("short", -0.55, 0.62)

    # Test positions
    btc_position = PositionSnapshot(
        symbol="BTCUSDT",
        timeframe="1m",
        side=Side.NONE,
        allocation=0.0,
        avg_entry_px=None,
    )

    eth_position = PositionSnapshot(
        symbol="ETHUSDT",
        timeframe="1m",
        side=Side.LONG,
        allocation=0.5,
        avg_entry_px=2000.0,
    )

    # Test configuration
    cfg = SelectorConfig(
        limits=LimitsConfig(
            max_allocation=0.75,
            step_allocation=0.25,
            max_gross_allocation=1.0,
        ),
        risk=RiskConfig(),
    )

    # Build plan
    signals = {"BTCUSDT": btc_signal, "ETHUSDT": eth_signal}
    positions = {"BTCUSDT": btc_position, "ETHUSDT": eth_position}

    plan = plan_for_universe(
        signals=signals,
        positions=positions,
        cfg=cfg,
        timeframe="1m",
    )

    logger.info("=== Strategy Selection Self-Check Complete ===")
    logger.info(f"Generated {len(plan.decisions)} decisions:")
    for sym, decision in plan.decisions.items():
        logger.info(f"  {sym}: {decision.explain}")

    print("Self-check completed successfully - see log output above")
