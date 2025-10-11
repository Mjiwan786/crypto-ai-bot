# agents/risk/risk_router.py
"""
Production-ready risk router that converts signals into risk-constrained order intents.
Orchestrates Compliance -> Drawdown -> Balancer checks with strict precedence.
PURE LOGIC: no I/O, no env reads; deterministic outputs.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

# External modules (imported; not redefined)
from agents.risk.compliance_checker import ComplianceChecker
from agents.risk.drawdown_protector import DrawdownProtector
from agents.risk.portfolio_balancer import PortfolioBalancer
from mcp.schemas import OrderIntent, OrderType, Signal

# Deterministic constants
EPS = 1e-9
MIN_SIZE_USD = 1.0

# Canonical, deterministic reason order
REASON_ORDER: List[str] = [
    "compliance-reject",
    "drawdown-halt",
    "drawdown-reduce-only",
    "over-cap-gross",
    "over-cap-net",
    "over-cap-symbol",
    "over-budget-strategy",
    "spread-too-wide",
    "depth-too-thin",
    "size-too-small",
    "missing-price",
    "malformed-symbol",
    "malformed-signal",
]


def _order_reasons(reasons: List[str]) -> List[str]:
    """Order reasons deterministically per REASON_ORDER; drop duplicates; append unknowns alphabetically."""
    seen: set[str] = set()
    known = [r for r in REASON_ORDER if r in reasons and not (r in seen or seen.add(r))]
    unknown = sorted(
        [r for r in reasons if r not in REASON_ORDER and not (r in seen or seen.add(r))]
    )
    return known + unknown


class RiskRouterConfig(BaseModel):
    """Configuration for the risk router with deterministic defaults."""

    model_config = ConfigDict(frozen=True)

    # Order construction defaults
    default_order_type: OrderType = OrderType.LIMIT
    default_time_in_force: str = "GTC"
    allow_reduce_only_on_soft_stop: bool = True  # reserved for future policy tuning


class RouteResult(BaseModel):
    """Result of risk routing with deterministic structure."""

    allowed: bool
    reasons: List[str] = Field(default_factory=list)
    intent: Optional[OrderIntent] = None
    normalized: Dict[str, float | str | bool] = Field(default_factory=dict)


class RiskRouter:
    """
    Production risk router that converts signals to validated order intents.

    Flow: Signal -> Compliance -> Drawdown -> Balancer -> OrderIntent
    Strict precedence; short-circuit on denial. Pure logic, deterministic.
    """

    def __init__(
        self,
        *,
        config: RiskRouterConfig,
        compliance: ComplianceChecker,
        drawdown: DrawdownProtector,
        balancer: PortfolioBalancer,
    ) -> None:
        self.config = config
        self.compliance = compliance
        self.drawdown = drawdown
        self.balancer = balancer

    def assess(self, signal: Signal, *, price_usd: Optional[float]) -> RouteResult:
        """
        Assess signal and convert to order intent with risk constraints.

        Args:
            signal: Trading signal to evaluate.
            price_usd: Current market price in USD (required for routing).

        Returns:
            RouteResult with allow/deny decision and optional order intent.
        """
        reasons: List[str] = []

        ok, reason = self._validate_inputs(signal, price_usd)
        if not ok:
            return RouteResult(
                allowed=False,
                reasons=_order_reasons([reason]),
                intent=None,
                normalized=self._build_base_normalized(signal, price_usd),
            )

        # 1) Compliance gate
        comp_ok, comp_reasons = self._check_compliance(signal, price_usd)  # reasons only canonical
        if not comp_ok:
            reasons.extend(comp_reasons)
            return RouteResult(
                allowed=False,
                reasons=_order_reasons(reasons),
                intent=None,
                normalized=self._build_base_normalized(signal, price_usd),
            )

        # 2) Drawdown gate
        dd_ok, dd_reasons, reduce_only_override, size_multiplier = self._check_drawdown(signal)
        if not dd_ok:
            reasons.extend(dd_reasons)
            return RouteResult(
                allowed=False,
                reasons=_order_reasons(reasons),
                intent=None,
                normalized=self._build_base_normalized(signal, price_usd),
            )
        reasons.extend(dd_reasons)

        # 3) Balancer (sizing & final constraints)
        bal_ok, bal_reasons, notional_usd, base_size, leverage, final_reduce_only = (
            self._check_balancer(signal, float(price_usd), reduce_only_override, size_multiplier)
        )
        if not bal_ok:
            reasons.extend(bal_reasons)
            return RouteResult(
                allowed=False,
                reasons=_order_reasons(reasons),
                intent=None,
                normalized=self._build_base_normalized(signal, price_usd),
            )
        reasons.extend(bal_reasons)

        # Defensive tiny-size guard (belt & suspenders)
        if (notional_usd < MIN_SIZE_USD) or (base_size is not None and base_size < EPS):
            reasons.append("size-too-small")
            return RouteResult(
                allowed=False,
                reasons=_order_reasons(reasons),
                intent=None,
                normalized=self._build_base_normalized(signal, price_usd),
            )

        # 4) Build OrderIntent
        intent = self._build_intent(
            signal=signal,
            price_usd=float(price_usd),
            notional_usd=notional_usd,
            base_size=base_size,
            reduce_only=final_reduce_only,
            leverage=leverage,
        )

        normalized = self._build_final_normalized(
            signal=signal,
            price_usd=float(price_usd),
            notional_usd=notional_usd,
            base_size=base_size,
            leverage=leverage,
            reduce_only=final_reduce_only,
        )

        return RouteResult(
            allowed=True,
            reasons=_order_reasons(reasons),
            intent=intent,
            normalized=normalized,
        )

    # ---------------- Internal helpers ----------------

    def _validate_inputs(self, signal: Signal, price_usd: Optional[float]) -> Tuple[bool, str]:
        """Validate required inputs for routing."""
        if price_usd is None:
            return False, "missing-price"
        if (
            not getattr(signal, "strategy", None)
            or not getattr(signal, "symbol", None)
            or not getattr(signal, "side", None)
        ):
            return False, "malformed-signal"
        if "/" not in signal.symbol:
            return False, "malformed-symbol"
        return True, ""

    def _check_compliance(self, signal: Signal, price_usd: float) -> Tuple[bool, List[str]]:
        """Run compliance check; only canonical reasons are exposed."""
        try:
            decision = (
                self.compliance.assess_signal(signal, price_usd)
                if hasattr(self.compliance, "assess_signal")
                else self.compliance.assess(signal, price_usd)
            )
            if not decision.allowed:
                return False, ["compliance-reject"]
            return True, []
        except Exception:
            return False, ["compliance-reject"]

    def _check_drawdown(self, signal: Signal) -> Tuple[bool, List[str], bool, float]:
        """
        Check drawdown protection.
        Returns: (allowed, reasons, reduce_only_override, size_multiplier)
        """
        try:
            gate = self.drawdown.assess_can_open(strategy=signal.strategy, symbol=signal.symbol)
            if gate.halt_all:
                return False, ["drawdown-halt"], False, 1.0

            reasons: List[str] = []
            reduce_only = bool(getattr(gate, "reduce_only", False))
            if reduce_only:
                reasons.append("drawdown-reduce-only")

            size_multiplier = float(getattr(gate, "size_multiplier", 1.0))
            # clamp to [0,1]
            if size_multiplier < 0.0:
                size_multiplier = 0.0
            elif size_multiplier > 1.0:
                size_multiplier = 1.0

            return True, reasons, reduce_only, size_multiplier
        except Exception:
            return False, ["drawdown-halt"], False, 1.0

    def _check_balancer(
        self,
        signal: Signal,
        price_usd: float,
        reduce_only_override: bool,
        size_multiplier: float,
    ) -> Tuple[bool, List[str], float, Optional[float], float, bool]:
        """
        Check portfolio balancer for final sizing and allocation.
        Returns: (allowed, reasons, notional_usd, base_size, leverage, final_reduce_only)
        """
        try:
            # stop distance bps
            stop_distance_bps = 100
            if getattr(signal, "metadata", None) and "stop_distance_bps" in signal.metadata:
                stop_distance_bps = signal.metadata["stop_distance_bps"]
            elif getattr(signal, "risk", None) and "sl_bps" in signal.risk:
                stop_distance_bps = signal.risk["sl_bps"]

            # liquidity
            liquidity: Optional[Dict[str, float | int]] = None
            if getattr(signal, "metadata", None):
                has_spread = "spread_bps" in signal.metadata
                has_depth = "depth_usd" in signal.metadata
                if has_spread or has_depth:
                    liquidity = {}
                    if has_spread:
                        liquidity["spread_bps"] = signal.metadata["spread_bps"]
                    if has_depth:
                        liquidity["depth_usd"] = signal.metadata["depth_usd"]

            drawdown_gate = {
                "halt_all": False,
                "reduce_only": reduce_only_override,
                "size_multiplier": size_multiplier,
            }
            compliance_gate = {"allowed": True}

            alloc = self.balancer.propose_allocation(
                strategy=signal.strategy,
                symbol=signal.symbol,
                price_usd=price_usd,
                stop_distance_bps=stop_distance_bps,
                liquidity=liquidity,
                drawdown_gate=drawdown_gate,
                compliance_gate=compliance_gate,
            )

            # Deny: map reason text into canonical codes (can extract multiple)
            if not alloc.allowed:
                mapped: List[str] = []
                reason_text = (getattr(alloc, "reason", "") or "").lower()
                if "gross" in reason_text:
                    mapped.append("over-cap-gross")
                if "net" in reason_text:
                    mapped.append("over-cap-net")
                if "symbol" in reason_text:
                    mapped.append("over-cap-symbol")
                if "budget" in reason_text or "strategy" in reason_text:
                    mapped.append("over-budget-strategy")
                if "spread" in reason_text:
                    mapped.append("spread-too-wide")
                if "depth" in reason_text:
                    mapped.append("depth-too-thin")
                # Default if no keywords matched
                if not mapped:
                    mapped.append("over-cap-gross")
                return False, mapped, 0.0, None, 1.0, False

            # Allowed: extract sizing
            notional_usd: float = float(alloc.notional_usd)
            base_size: Optional[float] = (
                float(getattr(alloc, "base_size", 0.0))
                if getattr(alloc, "base_size", None) is not None
                else None
            )
            leverage: float = float(getattr(alloc, "leverage", 1.0))

            # Tiny-size checks (primary)
            if notional_usd < MIN_SIZE_USD:
                return False, ["size-too-small"], 0.0, None, 1.0, False
            if base_size is not None and base_size < EPS:
                return False, ["size-too-small"], 0.0, None, 1.0, False

            final_reduce_only = reduce_only_override or bool(getattr(alloc, "reduce_only", False))
            return True, [], notional_usd, base_size, leverage, final_reduce_only

        except Exception:
            # Conservatively deny on balancer errors
            return False, ["over-cap-gross"], 0.0, None, 1.0, False

    # -------- public, stable helper (signature required by spec) --------
    def _build_intent(
        self,
        signal: Signal,
        *,
        price_usd: float,
        notional_usd: float,
        base_size: Optional[float],
        reduce_only: bool,
        leverage: float,
    ) -> OrderIntent:
        """Build the final order intent from validated parameters. Pure logic."""
        notional_usd = max(0.0, float(notional_usd))
        if base_size is not None:
            base_size = max(0.0, float(base_size))
        leverage = max(0.0, float(leverage))

        # metadata: do not override router-provided keys
        metadata: Dict[str, float | str | bool] = {
            "strategy": signal.strategy,
            "signal_id": getattr(signal, "id", "") or "",
            "confidence": signal.confidence,
            "source": "risk_router",
            "leverage": leverage,
        }
        if getattr(signal, "metadata", None):
            for k, v in signal.metadata.items():
                if k not in metadata:
                    metadata[k] = v

        # Determine price for OrderIntent (required for LIMIT orders)
        intent_price = float(price_usd) if self.config.default_order_type == OrderType.LIMIT else None

        return OrderIntent(
            symbol=signal.symbol,
            side=signal.side,
            order_type=self.config.default_order_type,
            price=intent_price,
            size_quote_usd=notional_usd,
            reduce_only=reduce_only,
            post_only=False,  # execution layer policy
            tif=self.config.default_time_in_force,
            metadata=metadata,
        )

    # ---------------- normalized payload builders ----------------

    def _build_base_normalized(
        self, signal: Signal, price_usd: Optional[float]
    ) -> Dict[str, float | str | bool]:
        """Normalized snapshot for denied routes (deterministic keys)."""
        return {
            "strategy": getattr(signal, "strategy", "") or "",
            "symbol": getattr(signal, "symbol", "") or "",
            "side": str(getattr(signal, "side", "")),  # Signal.side is already a string due to use_enum_values=True
            "price_used": float(price_usd) if price_usd is not None else 0.0,
            "reduce_only": False,
            "leverage": 1.0,
            "final_notional_usd": 0.0,
            "final_base_size": 0.0,
            "router_stage": "final",  # required by spec
        }

    def _build_final_normalized(
        self,
        signal: Signal,
        price_usd: float,
        notional_usd: float,
        base_size: Optional[float],
        leverage: float,
        reduce_only: bool,
    ) -> Dict[str, float | str | bool]:
        """Normalized snapshot for allowed routes (deterministic keys)."""
        return {
            "strategy": signal.strategy,
            "symbol": signal.symbol,
            "side": str(signal.side),  # Signal.side is already a string due to use_enum_values=True
            "price_used": float(price_usd),
            "reduce_only": bool(reduce_only),
            "leverage": float(leverage),
            "final_notional_usd": float(notional_usd),
            "final_base_size": float(base_size) if base_size is not None else 0.0,
            "router_stage": "final",
        }
