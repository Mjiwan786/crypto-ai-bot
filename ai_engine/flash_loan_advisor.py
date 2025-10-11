"""
ai_engine/flash_loan_advisor.py

Production-ready flash loan advisor module for crypto AI system.
Pure logic, deterministic, and OFF by default.

IMPORTANT: This module provides ADVISORY ONLY analysis of hypothetical
flash loan arbitrage opportunities. It does NOT:
- Execute transactions
- Connect to networks
- Sign transactions
- Interact with DeFi protocols

Usage:
    from ai_engine.flash_loan_advisor import advise_flash_loan, AdvisorConfig, SwapPath, SwapHop, Pool, PriceSnapshot
    advice = advise_flash_loan(paths, prices, pools, AdvisorConfig(enabled=True, mode="shadow"))
    print(advice.action, advice.expected_profit_usd, advice.reasons)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import statistics
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    field_serializer,
    ConfigDict,
    model_validator,
)

logger = logging.getLogger(__name__)

# =====================================
# Enums
# =====================================


class AMMModel(str, Enum):
    """Automated Market Maker models supported."""
    CONSTANT_PRODUCT = "constant_product"
    STABLE_SWAP = "stable_swap"
    RFQ_FIXED = "rfq_fixed"


class Action(str, Enum):
    """Advisory action recommendation."""
    PROPOSE = "propose"
    NOOP = "noop"


class Mode(str, Enum):
    """Operating mode for the advisor."""
    SHADOW = "shadow"  # Informational only
    ACTIVE = "active"  # Can influence system decisions


# =====================================
# Core Models
# =====================================


class PriceSnapshot(BaseModel):
    """Market price snapshot at a given timestamp."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0")
    ts_ms: int = Field(description="Timestamp in milliseconds")
    prices_usd: Dict[str, float] = Field(description="Token prices in USD")

    @field_validator("prices_usd")
    @classmethod
    def validate_prices(cls, v: Dict[str, float]) -> Dict[str, float]:
        for token, price in v.items():
            if not isinstance(price, (int, float)) or price <= 0 or not math.isfinite(price):
                raise ValueError(f"Invalid price for {token}: {price}")
        return v


class Pool(BaseModel):
    """Liquidity pool description."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Unique pool identifier")
    chain: str = Field(description="Blockchain name")
    model: AMMModel = Field(description="AMM model type")
    token0: str = Field(description="First token symbol")
    token1: str = Field(description="Second token symbol")
    r0: float = Field(ge=0, description="Reserve of token0")
    r1: float = Field(ge=0, description="Reserve of token1")
    fee_bps: int = Field(ge=0, le=10000, description="Fee in basis points")
    extra: Dict[str, float] = Field(default_factory=dict, description="Model-specific parameters")

    @field_validator("r0", "r1")
    @classmethod
    def validate_reserves(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"Invalid reserve: {v}")
        return v


class SwapHop(BaseModel):
    """Single swap operation in a path."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    pool_id: str = Field(description="Pool to use for this hop")
    in_token: str = Field(description="Input token symbol")
    out_token: str = Field(description="Output token symbol")


class SwapPath(BaseModel):
    """Complete arbitrage path with flash loan."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    hops: List[SwapHop] = Field(min_length=1, description="Sequence of swaps")
    borrow_token: str = Field(description="Token to flash borrow")
    repay_token: str = Field(description="Token to repay flash loan")

    @field_validator("hops")
    @classmethod
    def validate_path_continuity(cls, v: List[SwapHop]) -> List[SwapHop]:
        if len(v) < 1:
            raise ValueError("Path must have at least one hop")
        # Check hop continuity
        for i in range(len(v) - 1):
            if v[i].out_token != v[i + 1].in_token:
                raise ValueError(
                    f"Hop {i} output {v[i].out_token} != hop {i+1} input {v[i+1].in_token}"
                )
        return v

    @model_validator(mode="after")
    def _validate_start_end(self) -> "SwapPath":
        # Ensure path starts with borrow_token and ends with repay_token for early failure
        if not self.hops:
            return self
        if self.hops[0].in_token != self.borrow_token:
            raise ValueError(f"Path must start with borrow_token {self.borrow_token}")
        if self.hops[-1].out_token != self.repay_token:
            raise ValueError(f"Path must end with repay_token {self.repay_token}")
        return self


class AdvisorConfig(BaseModel):
    """Configuration for flash loan advisor."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = Field(default=False, description="Enable advisor (OFF by default)")
    mode: Mode = Field(default=Mode.SHADOW, description="Operating mode")
    max_hops: int = Field(default=4, ge=1, le=10, description="Maximum swap hops")
    max_borrow_usd: float = Field(default=5000.0, gt=0, le=1_000_000, description="Maximum borrow amount in USD")
    min_profit_usd: float = Field(default=15.0, gt=0, description="Minimum expected profit in USD")
    min_worst_case_profit_usd: float = Field(default=5.0, gt=0, description="Minimum worst-case profit in USD")
    max_liquidity_frac: float = Field(default=0.25, gt=0, le=1.0, description="Maximum pool liquidity usage")
    slippage_bps: int = Field(default=30, ge=0, le=500, description="Adversarial slippage in basis points")
    mev_risk_threshold: float = Field(default=0.6, ge=0, le=1.0, description="MEV risk threshold")
    gas_usd_per_tx: Dict[str, float] = Field(default_factory=dict, description="Gas cost per chain in USD")
    latency_budget_ms: int = Field(default=250, gt=0, le=5000, description="Latency budget in milliseconds")


class FlashLoanAdvice(BaseModel):
    """Advisory output for flash loan opportunity."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0")
    action: Action = Field(description="Recommended action")
    mode: Mode = Field(description="Advisor mode")
    borrow_token: Optional[str] = Field(default=None, description="Token to borrow")
    borrow_amount: Optional[float] = Field(default=None, description="Amount to borrow in token units")
    route: List[SwapHop] = Field(default_factory=list, description="Recommended swap route")
    expected_profit_usd: float = Field(description="Expected profit in USD")
    worst_case_profit_usd: float = Field(description="Worst-case profit in USD")
    mev_risk_score: float = Field(ge=0, le=1, description="MEV risk score")
    confidence: float = Field(ge=0, le=1, description="Confidence in recommendation")
    reasons: List[str] = Field(description="Top decision reasons")
    diagnostics: Dict[str, float] = Field(description="Detailed metrics")
    decision_hash: str = Field(description="SHA256 hash of decision inputs")
    latency_ms: int = Field(description="Processing latency")

    @field_serializer("diagnostics", when_used="always")
    def serialize_diagnostics(self, v: Dict[str, float]) -> Dict[str, float]:
        """Ensure deterministic serialization by sorting keys."""
        return {k: v[k] for k in sorted(v.keys())}


# =====================================
# Core Algorithm Functions
# =====================================


def _constant_product_out(r_in: float, r_out: float, amount_in: float, fee_bps: int) -> float:
    """
    Calculate output for constant product AMM (Uniswap v2 style).
    Formula: out = (Δx * (1 - fee)) * r1 / (r0 + Δx * (1 - fee))

    Note: We do not zero-out large trades; out approaches r_out asymptotically.
    We clamp to <100% of reserves to avoid numerical drain.
    """
    if r_in <= 0 or r_out <= 0 or amount_in <= 0:
        return 0.0

    fee_factor = 1.0 - (fee_bps / 10000.0)
    amount_in_after_fee = amount_in * fee_factor

    numerator = amount_in_after_fee * r_out
    denominator = r_in + amount_in_after_fee
    if denominator <= 0:
        return 0.0

    out = numerator / denominator
    # Clamp to below full reserve to avoid pathological drain
    return min(out, r_out * 0.9999)


def _stable_swap_out(r_in: float, r_out: float, amount_in: float, fee_bps: int, A: float) -> float:
    """
    Simplified stable-swap calculation with amplification parameter A.

    This is an approximation used for determinism and speed:
    - For small trades, behaves like constant product with reduced slippage.
    - A is applied linearly here for simplicity (not Curve's exact invariant).
    """
    if r_in <= 0 or r_out <= 0 or amount_in <= 0 or A <= 0:
        return 0.0

    fee_factor = 1.0 - (fee_bps / 10000.0)
    amount_in_after_fee = amount_in * fee_factor

    total_liquidity = r_in + r_out
    if total_liquidity <= 0:
        return 0.0

    # Apply amplification to reduce slippage for similar assets
    amplified_r_in = r_in * (1 + A / 100.0)

    numerator = amount_in_after_fee * r_out
    denominator = amplified_r_in + amount_in_after_fee
    if denominator <= 0:
        return 0.0

    out = numerator / denominator
    # Cap at 99% of reserves for safety
    return min(out, r_out * 0.99)


def _usd(value_token: float, token: str, prices_usd: Dict[str, float]) -> float:
    """Convert token amount to USD."""
    price = prices_usd.get(token, 0.0)
    return value_token * price


def _sigmoid(x: float) -> float:
    """Sigmoid function for risk scoring (deterministic and bounded)."""
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 1.0 if x > 0 else 0.0


def _sha256_sorted(obj: Any) -> str:
    """Create deterministic SHA256 hash of sorted object."""
    json_str = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(json_str.encode()).hexdigest()


def _sorted_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Return dictionary with sorted keys for deterministic serialization."""
    return {k: d[k] for k in sorted(d.keys())}


# =====================================
# Public API Functions
# =====================================


def simulate_swap(pool: Pool, amount_in: float, in_token: str) -> Tuple[float, float]:
    """
    Simulate a single swap through a pool.

    Args:
        pool: Pool to swap through
        amount_in: Amount of input token
        in_token: Symbol of input token

    Returns:
        Tuple of (amount_out, fee_paid_tokens)

    Raises:
        ValueError: On invalid swap direction or insufficient liquidity
    """
    if amount_in <= 0:
        raise ValueError(f"Invalid amount_in: {amount_in}")

    # Determine swap direction
    if in_token == pool.token0:
        r_in, r_out = pool.r0, pool.r1
        out_token = pool.token1
    elif in_token == pool.token1:
        r_in, r_out = pool.r1, pool.r0
        out_token = pool.token0
    else:
        raise ValueError(f"Token {in_token} not found in pool {pool.id}")

    if r_in <= 0 or r_out <= 0:
        raise ValueError(f"Pool {pool.id} has zero reserves")

    # Calculate output based on AMM model
    if pool.model == AMMModel.CONSTANT_PRODUCT:
        amount_out = _constant_product_out(r_in, r_out, amount_in, pool.fee_bps)
    elif pool.model == AMMModel.STABLE_SWAP:
        A = pool.extra.get("A", 100.0)  # Default amplification
        amount_out = _stable_swap_out(r_in, r_out, amount_in, pool.fee_bps, A)
    elif pool.model == AMMModel.RFQ_FIXED:
        # RFQ semantics: price is out_per_in; depth is in OUT-token units.
        # Prefer 'depth_out'; fall back to legacy 'depth' for compatibility.
        price = pool.extra.get("price", 1.0)
        depth_out = pool.extra.get("depth_out")
        if depth_out is None:
            depth_out = pool.extra.get("depth", float("inf"))
        fee_factor = 1.0 - (pool.fee_bps / 10000.0)
        out_nominal = amount_in * price
        if out_nominal <= depth_out:
            amount_out = out_nominal * fee_factor
        else:
            amount_out = 0.0
    else:
        raise ValueError(f"Unsupported AMM model: {pool.model}")

    if amount_out <= 0:
        raise ValueError(f"Insufficient liquidity in pool {pool.id}")

    # Calculate fee paid (in input token units)
    fee_paid = amount_in * (pool.fee_bps / 10000.0)

    return amount_out, fee_paid


def simulate_path(path: SwapPath, borrow_amount: float, pools: Dict[str, Pool]) -> Dict[str, Any]:
    """
    Simulate execution of complete swap path.

    Args:
        path: Swap path to simulate
        borrow_amount: Amount to borrow initially
        pools: Dictionary of pool_id -> Pool

    Returns:
        Dictionary with simulation results including:
        - amount_out (in final token units)
        - fees_token_sum (sum of input-token fees across hops; USD conversion done in evaluate_path)
        - liquidity_usage (max fraction of pool reserves used on any hop)
        - per_hop (list of hop details)
    """
    if borrow_amount <= 0:
        raise ValueError(f"Invalid borrow_amount: {borrow_amount}")

    current_amount = borrow_amount
    current_token = path.borrow_token
    total_fees = 0.0
    per_hop_details: List[Dict[str, Any]] = []
    max_liquidity_usage = 0.0

    # Model-level validator already checks start/end alignment; keep runtime checks defensive.
    if path.hops[0].in_token != path.borrow_token:
        raise ValueError(f"Path must start with borrow_token {path.borrow_token}")

    if path.hops[-1].out_token != path.repay_token:
        raise ValueError(f"Path must end with repay_token {path.repay_token}")

    try:
        for i, hop in enumerate(path.hops):
            if hop.in_token != current_token:
                raise ValueError(
                    f"Hop {i} token mismatch: expected {current_token}, got {hop.in_token}"
                )

            pool = pools.get(hop.pool_id)
            if not pool:
                raise ValueError(f"Pool {hop.pool_id} not found")

            # Calculate liquidity usage relative to source reserve for the hop
            if hop.in_token == pool.token0:
                liquidity_usage = current_amount / pool.r0 if pool.r0 > 0 else 1.0
            else:
                liquidity_usage = current_amount / pool.r1 if pool.r1 > 0 else 1.0

            max_liquidity_usage = max(max_liquidity_usage, liquidity_usage)

            amount_out, fee_paid = simulate_swap(pool, current_amount, current_token)

            hop_detail = {
                "hop_index": i,
                "pool_id": hop.pool_id,
                "in_token": hop.in_token,
                "out_token": hop.out_token,
                "amount_in": float(current_amount),
                "amount_out": float(amount_out),
                "fee_paid": float(fee_paid),
                "liquidity_usage": float(liquidity_usage),
            }
            per_hop_details.append(hop_detail)

            current_amount = amount_out
            current_token = hop.out_token
            total_fees += fee_paid

        return {
            "amount_out": float(current_amount),
            # NOTE: token-denominated fee sum (caller converts to USD in evaluate_path)
            "fees_token_sum": float(total_fees),
            # NOTE: adversarial slippage is applied in evaluate_path, not here
            "liquidity_usage": float(max_liquidity_usage),
            "per_hop": per_hop_details,
        }

    except Exception as e:
        logger.debug(f"Path simulation failed: {e}")
        return {
            "amount_out": 0.0,
            "liquidity_usage": 1.0,
            "per_hop": per_hop_details,
            "sim_error": 1.0,
            "error_code": "SIM_PATH_FAIL",
        }


def evaluate_path(
    path: SwapPath,
    borrow_amount: float,
    prices: PriceSnapshot,
    pools: Dict[str, Pool],
    cfg: AdvisorConfig,
) -> Tuple[float, float, float, Dict[str, float]]:
    """
    Evaluate a path for profitability and risk.

    Returns:
        Tuple of (expected_profit_usd, worst_case_profit_usd, mev_risk_score, diagnostics)
    """
    try:
        # Simulate ideal case
        ideal_result = simulate_path(path, borrow_amount, pools)

        if ideal_result["amount_out"] <= 0:
            return 0.0, -float("inf"), 1.0, {"error": 1.0}

        # Calculate gross arbitrage
        borrow_usd = _usd(borrow_amount, path.borrow_token, prices.prices_usd)
        repay_usd = _usd(ideal_result["amount_out"], path.repay_token, prices.prices_usd)
        gross_arbitrage_usd = repay_usd - borrow_usd

        # Calculate fees in USD from per-hop token fees
        fees_usd = 0.0
        for hop_detail in ideal_result.get("per_hop", []):
            in_token = hop_detail["in_token"]
            fee_paid_tokens = hop_detail["fee_paid"]
            in_price = prices.prices_usd.get(in_token, 0.0)
            if in_price > 0:
                fees_usd += fee_paid_tokens * in_price

        # Calculate gas costs (deterministic chain ordering)
        chains_used = sorted({pools[hop.pool_id].chain for hop in path.hops})
        gas_usd = sum(cfg.gas_usd_per_tx.get(chain, 5.0) for chain in chains_used)

        # Calculate adversarial slippage impact (compounded per hop)
        slippage_factor = cfg.slippage_bps / 10000.0
        hop_count = len(path.hops)
        compounded_slippage = 1.0 - (1.0 - slippage_factor) ** hop_count
        slippage_usd = repay_usd * compounded_slippage

        # Expected profit (ideal case minus costs)
        expected_profit_usd = gross_arbitrage_usd - fees_usd - gas_usd

        # Worst case profit (with adversarial slippage)
        worst_case_profit_usd = expected_profit_usd - slippage_usd

        # MEV risk score (deterministic proxy)
        liquidity_usage = ideal_result["liquidity_usage"]
        mev_base = _sigmoid(liquidity_usage * 10.0 - 2.0)  # Higher usage = more risk
        mev_complexity = _sigmoid(hop_count - 2.0)          # More hops = more risk
        mev_risk_score = min(0.5 * mev_base + 0.5 * mev_complexity, 1.0)

        diagnostics: Dict[str, float] = {
            "borrow_usd": float(borrow_usd),
            "gross_arbitrage_usd": float(gross_arbitrage_usd),
            "fees_usd": float(fees_usd),
            "gas_usd": float(gas_usd),
            "slippage_usd": float(slippage_usd),
            "liquidity_usage": float(liquidity_usage),
            "hop_count": float(hop_count),
            "mev_base_risk": float(mev_base),
            "mev_complexity_risk": float(mev_complexity),
        }

        return (
            float(expected_profit_usd),
            float(worst_case_profit_usd),
            float(mev_risk_score),
            diagnostics,
        )

    except Exception as e:
        logger.debug(f"Path evaluation failed: {e}")
        return 0.0, -float("inf"), 1.0, {"evaluation_error": 1.0}


def choose_borrow_amount(
    path: SwapPath, prices: PriceSnapshot, pools: Dict[str, Pool], cfg: AdvisorConfig
) -> float:
    """
    Deterministically choose optimal borrow amount based on liquidity and limits.
    """
    try:
        # Find minimum liquidity constraint across all hops
        min_available = float("inf")
        borrow_price = prices.prices_usd.get(path.borrow_token, 0.0)

        if borrow_price <= 0:
            return 0.0

        for hop in path.hops:
            pool = pools.get(hop.pool_id)
            if not pool:
                continue

            # Determine which reserve to check
            if hop.in_token == pool.token0:
                available = pool.r0 * cfg.max_liquidity_frac
            else:
                available = pool.r1 * cfg.max_liquidity_frac

            min_available = min(min_available, available)

        if min_available == float("inf"):
            return 0.0

        # Also respect max_borrow_usd limit
        max_borrow_tokens = cfg.max_borrow_usd / borrow_price

        # Choose conservative amount
        borrow_amount = min(min_available, max_borrow_tokens) * 0.8  # 80% safety margin

        return max(borrow_amount, 0.0)

    except Exception as e:
        logger.debug(f"Borrow amount selection failed: {e}")
        return 0.0


def advise_flash_loan(
    paths: List[SwapPath],
    prices: PriceSnapshot,
    pools: List[Pool],
    cfg: AdvisorConfig,
) -> FlashLoanAdvice:
    """
    Main advisory function for flash loan opportunities.

    Args:
        paths: List of potential arbitrage paths
        prices: Current market prices
        pools: Available liquidity pools
        cfg: Advisor configuration

    Returns:
        FlashLoanAdvice with recommendation and analysis
    """
    start_time = time.perf_counter()

    # Create pools dictionary for efficient lookup
    pools_dict = {pool.id: pool for pool in pools}

    # Default NOOP response
    def create_noop(
        reasons: List[str], confidence: float = 0.0, diagnostics: Optional[Dict[str, float]] = None
    ) -> FlashLoanAdvice:
        diag: Dict[str, float] = diagnostics or {}
        decision_input = {
            "action": "noop",
            "paths_count": len(paths),
            "prices_snapshot": prices.ts_ms,
            # Use JSON mode for stable enum/typing serialization
            "config_hash": _sha256_sorted(cfg.model_dump(mode="json")),
            "reasons": sorted(reasons),
        }

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        return FlashLoanAdvice(
            action=Action.NOOP,
            mode=cfg.mode,
            expected_profit_usd=0.0,
            worst_case_profit_usd=0.0,
            mev_risk_score=1.0,
            confidence=confidence,
            reasons=sorted(set(reasons))[:3],  # Top 3 stabilized
            diagnostics=_sorted_dict(diag),
            decision_hash=_sha256_sorted(decision_input),
            latency_ms=latency_ms,
        )

    try:
        # Guardrail 1: Check if enabled
        if not cfg.enabled:
            return create_noop(["disabled"], 0.0, {"enabled": 0.0})

        # Guardrail 2: Check if any paths provided
        if not paths:
            return create_noop(["no_paths"], 0.0, {"paths_count": 0.0})

        # Guardrail 3: Check if pools available
        if not pools:
            return create_noop(["no_pools"], 0.0, {"pools_count": 0.0})

        best_path: Optional[SwapPath] = None
        best_profit = -float("inf")
        best_worst_case = -float("inf")
        best_mev_risk = 1.0
        best_borrow_amount = 0.0
        best_diagnostics: Dict[str, float] = {}
        evaluation_results: List[Dict[str, Any]] = []

        # Evaluate each path
        for path_idx, path in enumerate(paths):
            try:
                # Guardrail: Check hop count
                if len(path.hops) > cfg.max_hops:
                    continue

                # Choose borrow amount
                borrow_amount = choose_borrow_amount(path, prices, pools_dict, cfg)
                if borrow_amount <= 0:
                    continue

                # Check borrow amount in USD
                borrow_price = prices.prices_usd.get(path.borrow_token, 0.0)
                if borrow_price <= 0:
                    continue

                borrow_usd = borrow_amount * borrow_price
                if borrow_usd > cfg.max_borrow_usd:
                    continue

                # Evaluate path
                expected_profit, worst_case_profit, mev_risk, diagnostics = evaluate_path(
                    path, borrow_amount, prices, pools_dict, cfg
                )

                evaluation_results.append(
                    {
                        "path_idx": path_idx,
                        "expected_profit": expected_profit,
                        "worst_case_profit": worst_case_profit,
                        "mev_risk": mev_risk,
                        "borrow_amount": borrow_amount,
                        "diagnostics": diagnostics,
                    }
                )

                # Check if this is the best path (deterministic tie-breaking)
                route_sig = ",".join(h.pool_id for h in path.hops)
                best_route_sig = ",".join(h.pool_id for h in best_path.hops) if best_path else None

                if (
                    worst_case_profit > best_worst_case
                    or (worst_case_profit == best_worst_case and expected_profit > best_profit)
                    or (
                        worst_case_profit == best_worst_case
                        and expected_profit == best_profit
                        and (best_route_sig is None or route_sig < best_route_sig)
                    )
                ):
                    best_path = path
                    best_profit = expected_profit
                    best_worst_case = worst_case_profit
                    best_mev_risk = mev_risk
                    best_borrow_amount = borrow_amount
                    best_diagnostics = diagnostics

            except Exception as e:
                logger.debug(f"Path {path_idx} evaluation failed: {e}")
                continue

        # If no valid paths found
        if best_path is None:
            reasons = ["no_viable_paths"]
            if evaluation_results:
                reasons.append(f"evaluated_{len(evaluation_results)}_paths")
            return create_noop(reasons, 0.0, {"evaluated_paths": float(len(evaluation_results))})

        # Apply final guardrails
        guardrail_reasons: List[str] = []

        # Check minimum profit thresholds
        if best_profit < cfg.min_profit_usd:
            guardrail_reasons.append(f"expected_profit_low_{best_profit:.1f}")

        if best_worst_case < cfg.min_worst_case_profit_usd:
            guardrail_reasons.append(f"worst_case_profit_low_{best_worst_case:.1f}")

        # Check MEV risk
        if best_mev_risk > cfg.mev_risk_threshold:
            guardrail_reasons.append(f"mev_risk_high_{best_mev_risk:.2f}")

        # Check liquidity usage
        max_liquidity_usage = best_diagnostics.get("liquidity_usage", 0.0)
        if max_liquidity_usage > cfg.max_liquidity_frac:
            guardrail_reasons.append(f"liquidity_usage_high_{max_liquidity_usage:.2f}")

        # If any guardrails triggered
        if guardrail_reasons:
            return create_noop(guardrail_reasons, 0.1, best_diagnostics)

        # Calculate confidence (monotone with profit and inverse risk)
        profit_margin = best_worst_case / max(cfg.min_worst_case_profit_usd, 1.0)
        mev_confidence = 1.0 - best_mev_risk
        liquidity_headroom = 1.0 - max_liquidity_usage / cfg.max_liquidity_frac

        confidence = statistics.mean(
            [
                min(profit_margin, 1.0),
                mev_confidence,
                liquidity_headroom,
            ]
        )
        confidence = max(0.0, min(confidence, 1.0))

        # Create proposal with explicitly sorted reasons (max 3)
        reasons = sorted(
            {
                f"profitable_{best_profit:.1f}usd",
                f"worst_case_{best_worst_case:.1f}usd",
                f"confidence_{confidence:.2f}",
            }
        )

        # Create decision hash (exclude latency; stable ordering)
        decision_input = {
            "action": "propose",
            "borrow_token": best_path.borrow_token,
            "borrow_amount": best_borrow_amount,
            "route": [
                {"pool_id": h.pool_id, "in_token": h.in_token, "out_token": h.out_token}
                for h in best_path.hops
            ],
            "expected_profit": best_profit,
            "worst_case_profit": best_worst_case,
            "prices_snapshot": prices.ts_ms,
            # Use JSON mode for stable enum/typing serialization
            "config_hash": _sha256_sorted(cfg.model_dump(mode="json")),
        }

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        advice = FlashLoanAdvice(
            action=Action.PROPOSE,
            mode=cfg.mode,
            borrow_token=best_path.borrow_token,
            borrow_amount=best_borrow_amount,
            route=list(best_path.hops),
            expected_profit_usd=best_profit,
            worst_case_profit_usd=best_worst_case,
            mev_risk_score=best_mev_risk,
            confidence=confidence,
            reasons=reasons,
            diagnostics=_sorted_dict(best_diagnostics),
            decision_hash=_sha256_sorted(decision_input),
            latency_ms=latency_ms,
        )

        # Log final decision (observability; does not affect outputs)
        logger.info(
            "Flash loan advice: action=%s, mode=%s, profit=%.2f/%.2f USD, confidence=%.2f, reasons=%s, latency=%dms",
            advice.action.value,
            advice.mode.value,
            advice.expected_profit_usd,
            advice.worst_case_profit_usd,
            advice.confidence,
            advice.reasons,
            advice.latency_ms,
        )

        return advice

    except Exception as e:
        logger.exception(f"Flash loan advisor failed: {e}")
        return create_noop(["internal_error"], 0.0, {"error": 1.0})


# =====================================
# Self-Check and Example (runs only if executed directly)
# =====================================

if __name__ == "__main__":
    # Set up logging (no import-time side effects)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    # Create synthetic test data
    prices = PriceSnapshot(
        ts_ms=1640995200000,  # 2022-01-01 00:00:00 UTC
        prices_usd={
            "USDC": 1.0,
            "WETH": 3500.0,
            "WBTC": 47000.0,
        },
    )

    pools = [
        # USDC/WETH constant product pool
        Pool(
            id="uniswap_usdc_weth",
            chain="ethereum",
            model=AMMModel.CONSTANT_PRODUCT,
            token0="USDC",
            token1="WETH",
            r0=1_000_000.0,  # 1M USDC
            r1=285.71,  # ~285.71 WETH (1M / 3500)
            fee_bps=30,  # 0.3%
            extra={},
        ),
        # WETH/WBTC constant product pool
        Pool(
            id="uniswap_weth_wbtc",
            chain="ethereum",
            model=AMMModel.CONSTANT_PRODUCT,
            token0="WETH",
            token1="WBTC",
            r0=100.0,  # 100 WETH
            r1=7.45,  # ~7.45 WBTC (100 * 3500 / 47000)
            fee_bps=30,  # 0.3%
            extra={},
        ),
        # WBTC/USDC RFQ fixed quote (slightly better rate for arbitrage)
        Pool(
            id="rfq_wbtc_usdc",
            chain="ethereum",
            model=AMMModel.RFQ_FIXED,
            token0="WBTC",
            token1="USDC",
            r0=1.0,  # Not used for RFQ
            r1=1.0,  # Not used for RFQ
            fee_bps=10,  # 0.1% (better than AMM)
            extra={
                "price": 47100.0,  # Slightly higher than market (47000)
                "depth_out": 50_000.0,  # $50k depth in out token (USDC)
            },
        ),
    ]

    # Create 3-hop arbitrage path: USDC -> WETH -> WBTC -> USDC
    path = SwapPath(
        hops=[
            SwapHop(pool_id="uniswap_usdc_weth", in_token="USDC", out_token="WETH"),
            SwapHop(pool_id="uniswap_weth_wbtc", in_token="WETH", out_token="WBTC"),
            SwapHop(pool_id="rfq_wbtc_usdc", in_token="WBTC", out_token="USDC"),
        ],
        borrow_token="USDC",
        repay_token="USDC",
    )

    # Test with enabled shadow mode
    config = AdvisorConfig(
        enabled=True,
        mode=Mode.SHADOW,
        max_borrow_usd=1000.0,
        min_profit_usd=5.0,
        min_worst_case_profit_usd=1.0,
        gas_usd_per_tx={"ethereum": 8.0},
    )

    # Run advisor
    advice = advise_flash_loan([path], prices, pools, config)

    print("\nFlash Loan Advisor Self-Check:")
    print(f"Action: {advice.action.value}")
    print(f"Expected Profit: ${advice.expected_profit_usd:.2f}")
    print(f"Worst Case Profit: ${advice.worst_case_profit_usd:.2f}")
    print(f"Confidence: {advice.confidence:.2f}")
    print(f"Reasons: {advice.reasons}")
    print(f"Latency: {advice.latency_ms}ms")
    print(f"Decision Hash: {advice.decision_hash[:16]}...")

    # Test disabled mode
    disabled_config = AdvisorConfig(enabled=False)
    disabled_advice = advise_flash_loan([path], prices, pools, disabled_config)
    print("\nDisabled Mode Test:")
    print(f"Action: {disabled_advice.action.value}")
    print(f"Reasons: {disabled_advice.reasons}")

    print("\n✅ Self-check completed successfully!")
