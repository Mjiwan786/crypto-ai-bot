"""
flash_loan_system/profitability_simulator.py

Production-grade profitability simulator for flash-loan arbitrage opportunities.
Performs Monte Carlo simulation with risk modeling and position-sizing optimization.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import statistics

# Project imports
from .opportunity_scorer import (
    ScoredOpportunity,
    RawOpportunity,          # for the example usage
    OpportunityType,         # for the example usage
)

from utils.logger import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Domain models
# ──────────────────────────────────────────────────────────────────────────────

class DecisionType(str, Enum):
    EXECUTE = "EXECUTE"
    SKIP = "SKIP"
    DEFER = "DEFER"


class RouteType(str, Enum):
    CEX_ARBITRAGE = "cex_arbitrage"
    DEX_ARBITRAGE = "dex_arbitrage"
    CROSS_CHAIN = "cross_chain"
    TRIANGULAR = "triangular"


@dataclass
class MarketConditions:
    """Current market conditions for simulation."""
    eth_usd_price: float
    gas_price_gwei: float
    network_congestion: float = 1.0   # multiplier for gas costs
    mev_risk_level: float = 0.5       # 0-1 scale
    volatility_regime: str = "normal" # normal, high, extreme
    liquidity_conditions: Dict[str, float] = field(default_factory=dict)


@dataclass
class RouteHop:
    """Single hop in an arbitrage route."""
    venue: str                   # "kraken", "uniswap_v3", "1inch", etc.
    venue_type: str              # "cex", "dex", "aggregator"
    from_token: str
    to_token: str
    pool_address: Optional[str] = None
    fee_tier: Optional[float] = None
    liquidity_depth: Optional[float] = None  # USD depth available around mid
    expected_slippage_bps: float = 0.0       # optional per-hop prior


@dataclass
class RouteConfig:
    """Complete route configuration."""
    route_id: str
    route_type: RouteType
    hops: List[RouteHop]
    estimated_gas_limit: int
    flash_loan_provider: str = "aave"  # aave, dydx, euler
    expected_latency_ms: int = 500


@dataclass
class SimulationConfig:
    """Configuration for profitability simulation."""
    # Position sizing
    min_size_usd: float = 1_000.0
    max_size_usd: float = 100_000.0
    size_steps: int = 15

    # Risk constraints
    min_p95_usd: float = 0.0                # P95 must be ≥ 0
    max_p5_loss_usd: float = -500.0         # P5 ≥ this (e.g., no worse than -$500)
    max_fail_prob: float = 0.08             # 8% maximum failure probability
    min_sharpe_ratio: float = 0.5

    # Fees & buffers
    flash_loan_fee_bps: float = 9.0         # e.g., 0.09% Aave
    gas_buffer_multiplier: float = 1.30     # +30%

    # MEV & latency
    max_mev_risk_bps: float = 25.0          # max allowed MEV risk (for constraints)
    latency_drift_bps_per_ms: float = 0.01  # expected adverse drift per ms (bps)

    # Simulation parameters
    monte_carlo_runs: int = 1_000
    confidence_intervals: List[float] = field(default_factory=lambda: [0.05, 0.25, 0.50, 0.75, 0.95])

    # Market impact modeling
    impact_model: str = "sqrt"              # "linear", "sqrt", "power"
    impact_coefficient: float = 0.1         # tuned coefficient

    # Execution modeling
    partial_fill_prob: float = 0.15
    revert_prob_per_hop: float = 0.02
    base_execution_cost_usd: float = 50.0   # fixed costs (signing, RPC, etc.)


@dataclass
class RiskMetrics:
    """Risk metrics from simulation."""
    var_95: float
    cvar_95: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    hit_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    worst_case: float
    best_case: float


@dataclass
class SimulationResult:
    """Complete simulation result."""
    decision: DecisionType
    rationale: Optional[str] = None

    optimal_size_usd: float = 0.0
    optimal_route: Optional[RouteConfig] = None

    ev_usd: float = 0.0
    p95_usd: float = 0.0
    p75_usd: float = 0.0
    p50_usd: float = 0.0
    p25_usd: float = 0.0
    p5_usd: float = 0.0

    # Performance components (bps)
    gross_bps: float = 0.0
    net_bps: float = 0.0
    slippage_bps: float = 0.0
    fees_bps: float = 0.0
    gas_cost_bps: float = 0.0
    flash_loan_cost_bps: float = 0.0

    # Risks
    risk_metrics: Optional[RiskMetrics] = None
    fail_prob: float = 0.0
    mev_risk_bps: float = 0.0

    # Execution plan
    gas_estimate: int = 0
    gas_cost_usd: float = 0.0
    estimated_settlement_time_ms: int = 0

    # Meta
    simulation_time_ms: float = 0.0
    monte_carlo_runs: int = 0
    route_alternatives: int = 0

    # Raw for diagnostics
    pnl_distribution: Optional[List[float]] = None
    size_curve: Optional[Dict[float, float]] = None  # size -> EV


# ──────────────────────────────────────────────────────────────────────────────
# Simulator
# ──────────────────────────────────────────────────────────────────────────────

class ProfitabilitySimulator:
    """
    Profitability simulator for flash-loan arbitrage opportunities.

    - Monte Carlo with latency/MEV/fail/partial-fill modeling
    - Size sweep to maximize EV subject to constraints
    - Per-route comparison; returns optimal plan & rationale
    """

    def __init__(self, config: Optional[SimulationConfig] = None):
        self.config = config or SimulationConfig()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.logger.info("Initialized ProfitabilitySimulator with config: %s", self.config)

    # ── public API ────────────────────────────────────────────────────────────

    async def simulate(
        self,
        opportunity: ScoredOpportunity,
        market_conditions: MarketConditions,
        route_configs: List[RouteConfig],
    ) -> SimulationResult:
        """
        Run full profitability simulation for a scored opportunity across routes.
        """
        start = time.perf_counter()

        try:
            opp_id = getattr(opportunity.raw_opportunity, "id", "unknown")
            self.logger.info("Starting simulation for opportunity %s", opp_id)

            size_grid = self._generate_size_grid()
            best: Optional[SimulationResult] = None
            best_ev = float("-inf")
            route_results: List[SimulationResult] = []

            for route in route_configs:
                route_result = await self._evaluate_route(
                    opportunity, market_conditions, route, size_grid
                )
                route_results.append(route_result)

                if route_result.ev_usd > best_ev and self._passes_constraints(route_result):
                    best = route_result
                    best_ev = route_result.ev_usd

            # fallback: pick best EV even if constraints fail (will SKIP)
            if best is None:
                if not route_results:
                    return SimulationResult(
                        decision=DecisionType.SKIP,
                        rationale="No routes provided",
                        simulation_time_ms=(time.perf_counter() - start) * 1000.0,
                        route_alternatives=0,
                    )
                best = max(route_results, key=lambda r: r.ev_usd)

            decision, rationale = self._make_decision(best, opportunity)
            best.decision = decision
            best.rationale = rationale
            best.simulation_time_ms = (time.perf_counter() - start) * 1000.0
            best.route_alternatives = len(route_configs)
            return best

        except Exception as e:
            self.logger.error("Simulation failed: %s", e, exc_info=True)
            return SimulationResult(
                decision=DecisionType.SKIP,
                rationale=f"Simulation error: {e}",
                simulation_time_ms=(time.perf_counter() - start) * 1000.0,
                route_alternatives=len(route_configs),
            )

    # ── internals ────────────────────────────────────────────────────────────

    def _generate_size_grid(self) -> List[float]:
        """Log-spaced grid (min..max, inclusive)."""
        min_size, max_size, steps = self.config.min_size_usd, self.config.max_size_usd, self.config.size_steps
        log_min, log_max = np.log10(min_size), np.log10(max_size)
        log_sizes = np.linspace(log_min, log_max, steps)
        return [float(10 ** x) for x in log_sizes]

    async def _evaluate_route(
        self,
        opportunity: ScoredOpportunity,
        market: MarketConditions,
        route: RouteConfig,
        size_grid: List[float],
    ) -> SimulationResult:
        """Evaluate a route over size sweep; return best size result."""

        best_ev = float("-inf")
        best_size = 0.0
        size_results: Dict[float, Dict[str, Any]] = {}

        for size_usd in size_grid:
            pnl_distribution = await self._run_monte_carlo(opportunity, market, route, size_usd)
            if not pnl_distribution:
                continue

            ev = statistics.mean(pnl_distribution)
            p5, p25, p50, p75, p95 = np.percentile(pnl_distribution, [5, 25, 50, 75, 95])

            size_results[size_usd] = {
                "ev": float(ev),
                "percentiles": (float(p5), float(p25), float(p50), float(p75), float(p95)),
                "dist": pnl_distribution,
            }

            if ev > best_ev:
                best_ev = float(ev)
                best_size = float(size_usd)

        if not size_results:
            return SimulationResult(
                decision=DecisionType.SKIP,
                rationale="No valid size found for route",
                optimal_route=route,
            )

        # Build optimal result
        data = size_results[best_size]
        p5, p25, p50, p75, p95 = data["percentiles"]
        risk_metrics = self._risk_metrics(data["dist"])

        # Deterministic component costs (for reporting/constraints)
        gas_cost_usd = self._gas_cost(route, market)
        flash_loan_cost_usd = best_size * (self.config.flash_loan_fee_bps / 10_000.0)
        fees_bps = (flash_loan_cost_usd / max(1.0, best_size)) * 10_000.0
        gas_bps = (gas_cost_usd / max(1.0, best_size)) * 10_000.0

        # Deterministic slippage estimate (median, no randomness)
        slip_usd = self._market_impact_expected(route, best_size)
        slippage_bps = (slip_usd / max(1.0, best_size)) * 10_000.0

        # Deterministic MEV risk estimate in bps (expected value)
        mev_bps = self._estimate_mev_risk_bps(best_size, market)

        # For reporting: gross vs net bps
        gross_bps = ((best_size * self._base_profit_bps(opportunity)) / max(1.0, best_size))
        net_bps = (best_ev / max(1.0, best_size)) * 10_000.0

        # Failure probability from distribution: count executions that lost more than fixed costs
        fail_prob = float(sum(1 for pnl in data["dist"] if pnl < -self.config.base_execution_cost_usd) / len(data["dist"]))

        return SimulationResult(
            decision=DecisionType.DEFER,  # finalized later by _make_decision
            optimal_size_usd=best_size,
            optimal_route=route,
            ev_usd=float(best_ev),
            p95_usd=float(p95),
            p75_usd=float(p75),
            p50_usd=float(p50),
            p25_usd=float(p25),
            p5_usd=float(p5),
            gross_bps=float(gross_bps),
            net_bps=float(net_bps),
            slippage_bps=float(slippage_bps),
            fees_bps=float(fees_bps),
            gas_cost_bps=float(gas_bps),
            flash_loan_cost_bps=float(self.config.flash_loan_fee_bps),
            risk_metrics=risk_metrics,
            fail_prob=fail_prob,
            mev_risk_bps=float(mev_bps),
            gas_estimate=route.estimated_gas_limit,
            gas_cost_usd=float(gas_cost_usd),
            estimated_settlement_time_ms=route.expected_latency_ms,
            monte_carlo_runs=self.config.monte_carlo_runs,
            pnl_distribution=[float(x) for x in data["dist"]],
            size_curve={float(sz): float(info["ev"]) for sz, info in size_results.items()},
        )

    async def _run_monte_carlo(
        self,
        opportunity: ScoredOpportunity,
        market: MarketConditions,
        route: RouteConfig,
        size_usd: float,
    ) -> List[float]:
        """Run Monte Carlo trials and return a list of PnL (USD) outcomes."""
        trials = self.config.monte_carlo_runs
        results: List[float] = []
        for _ in range(trials):
            pnl = self._simulate_once(opportunity, market, route, size_usd)
            results.append(float(pnl))
        return results

    # ── per-trial simulation ─────────────────────────────────────────────────

    def _simulate_once(
        self,
        opportunity: ScoredOpportunity,
        market: MarketConditions,
        route: RouteConfig,
        size_usd: float,
    ) -> float:
        """
        One simulated execution including:
        - base profit from spread
        - market impact/slippage
        - gas, flash-loan fees
        - MEV & latency adverse move
        - partial fill and revert risks
        """
        # Base profit (bps) with mild noise (to reflect microstructure variance)
        base_bps = self._base_profit_bps(opportunity) * np.random.normal(1.0, 0.10)  # ±10%
        base_profit_usd = (size_usd * base_bps) / 10_000.0

        # Slippage/impact (randomized)
        slippage_usd = self._market_impact_random(route, size_usd)

        # Gas (lognormal variance)
        gas_cost_usd = self._gas_cost(market=market, route=route) * np.random.lognormal(mean=0.0, sigma=0.30)

        # Flash-loan fee (proportional to notional)
        flash_fee_usd = size_usd * (self.config.flash_loan_fee_bps / 10_000.0)

        # MEV risk (random draw around expected)
        mev_usd = (self._estimate_mev_risk_bps(size_usd, market) * np.random.random()) * size_usd / 10_000.0

        # Latency drift (adverse move) in USD
        latency_usd = self._latency_risk_usd(route, market, size_usd)

        # Revert / failure risk (pay gas, no fill)
        if not self._exec_success(route):
            return -gas_cost_usd

        # Partial fill
        fill = self._fill_ratio()
        notional = size_usd * fill

        # Scale the proportional costs/profits by fill
        profit = base_profit_usd * fill
        slip = slippage_usd * fill
        mev = mev_usd * fill
        latency = latency_usd * fill
        flash_fee = flash_fee_usd * fill

        # Net P&L
        pnl = profit - slip - gas_cost_usd - flash_fee - mev - latency - self.config.base_execution_cost_usd
        return float(pnl)

    # ── components (math) ────────────────────────────────────────────────────

    def _base_profit_bps(self, opportunity: ScoredOpportunity) -> float:
        """Use the raw spread in bps; clamp to non-negative."""
        try:
            bps = float(getattr(opportunity.raw_opportunity, "spread_bps", 0.0))
        except Exception:
            bps = 0.0
        return max(0.0, bps)

    def _market_impact_expected(self, route: RouteConfig, size_usd: float) -> float:
        """Deterministic slippage (median)."""
        total = 0.0
        for hop in route.hops:
            depth = float(hop.liquidity_depth or 50_000.0)
            if self.config.impact_model == "sqrt":
                impact_bps = self.config.impact_coefficient * np.sqrt(max(1e-9, size_usd / depth)) * 100.0
            elif self.config.impact_model == "linear":
                impact_bps = self.config.impact_coefficient * (size_usd / depth) * 100.0
            else:  # power ~0.7
                impact_bps = self.config.impact_coefficient * ((max(1e-9, size_usd / depth)) ** 0.7) * 100.0
            total += (size_usd * impact_bps) / 10_000.0
        return float(total)

    def _market_impact_random(self, route: RouteConfig, size_usd: float) -> float:
        """Slippage with randomness (lognormal noise around expected)."""
        expected = self._market_impact_expected(route, size_usd)
        noise = np.random.lognormal(mean=0.0, sigma=0.20)  # median 1.0
        return float(expected * noise)

    def _gas_cost(self, route: RouteConfig, market: MarketConditions) -> float:
        """Gas cost (USD) with congestion + buffer (deterministic path)."""
        base = route.estimated_gas_limit * market.gas_price_gwei * 1e-9 * market.eth_usd_price
        return float(base * market.network_congestion * self.config.gas_buffer_multiplier)

    def _estimate_mev_risk_bps(self, size_usd: float, market: MarketConditions) -> float:
        """Expected MEV risk in bps (size-scaled)."""
        base = self.config.max_mev_risk_bps * float(market.mev_risk_level)
        size_mult = min(2.0, np.sqrt(max(1.0, size_usd) / 10_000.0))  # grows with size
        # Expected value: assume mean of U[0,1] = 0.5 for random multiplier in trials
        return float(base * size_mult * 0.5)

    def _latency_risk_usd(self, route: RouteConfig, market: MarketConditions, size_usd: float) -> float:
        """Adverse price drift during settlement (USD)."""
        exec_time_ms = route.expected_latency_ms * np.random.lognormal(mean=0.0, sigma=0.30)
        drift_bps = self.config.latency_drift_bps_per_ms * exec_time_ms
        vol_mult = {"normal": 1.0, "high": 2.0, "extreme": 3.5}.get(market.volatility_regime, 1.0)
        drift_bps *= vol_mult
        # Adverse move magnitude (absolute normal around 0)
        adverse_bps = abs(np.random.normal(0.0, drift_bps))
        return float(size_usd * adverse_bps / 10_000.0)

    def _exec_success(self, route: RouteConfig) -> bool:
        """Chained success probability after per-hop revert probabilities."""
        success = 1.0
        for _ in route.hops:
            success *= (1.0 - self.config.revert_prob_per_hop)
        return bool(np.random.random() < success)

    def _fill_ratio(self) -> float:
        """Partial fill modeling."""
        return float(np.random.uniform(0.5, 1.0)) if (np.random.random() < self.config.partial_fill_prob) else 1.0

    # ── analytics ────────────────────────────────────────────────────────────

    def _risk_metrics(self, pnl: List[float]) -> RiskMetrics:
        arr = np.array(pnl, dtype=float)
        mean, std = float(np.mean(arr)), float(np.std(arr))
        var95 = float(np.percentile(arr, 5))
        cvar95 = float(np.mean(arr[arr <= var95])) if arr.size else 0.0

        # Sharpe & Sortino (rf = 0)
        sharpe = float(mean / std) if std > 0 else 0.0
        downside = arr[arr < 0.0]
        dstd = float(np.std(downside)) if downside.size else 0.0
        sortino = float(mean / dstd) if dstd > 0 else 0.0

        winners, losers = arr[arr > 0.0], arr[arr < 0.0]
        hit_rate = float(winners.size / arr.size) if arr.size else 0.0
        avg_win = float(np.mean(winners)) if winners.size else 0.0
        avg_loss = float(np.mean(losers)) if losers.size else 0.0
        profit_factor = float(abs(avg_win / avg_loss)) if avg_loss != 0.0 else float("inf")

        return RiskMetrics(
            var_95=var95,
            cvar_95=cvar95,
            max_drawdown=float(np.min(arr)) if arr.size else 0.0,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            hit_rate=hit_rate,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            worst_case=float(np.min(arr)) if arr.size else 0.0,
            best_case=float(np.max(arr)) if arr.size else 0.0,
        )

    # ── policy ───────────────────────────────────────────────────────────────

    def _passes_constraints(self, r: SimulationResult) -> bool:
        """Check risk policy constraints on a candidate result."""
        ok = True
        reasons: List[str] = []

        if r.p95_usd < self.config.min_p95_usd:
            ok = False
            reasons.append(f"P95 ${r.p95_usd:.2f} < ${self.config.min_p95_usd:.2f}")

        if r.p5_usd < self.config.max_p5_loss_usd:
            ok = False
            reasons.append(f"P5 ${r.p5_usd:.2f} < ${self.config.max_p5_loss_usd:.2f}")

        if r.fail_prob > self.config.max_fail_prob:
            ok = False
            reasons.append(f"Fail prob {r.fail_prob:.1%} > {self.config.max_fail_prob:.1%}")

        if r.risk_metrics and r.risk_metrics.sharpe_ratio < self.config.min_sharpe_ratio:
            ok = False
            reasons.append(f"Sharpe {r.risk_metrics.sharpe_ratio:.2f} < {self.config.min_sharpe_ratio:.2f}")

        if r.mev_risk_bps > self.config.max_mev_risk_bps:
            ok = False
            reasons.append(f"MEV risk {r.mev_risk_bps:.1f} bps > {self.config.max_mev_risk_bps:.1f} bps")

        if not ok:
            self.logger.debug("Constraint violations: %s", "; ".join(reasons))
        return ok

    def _make_decision(self, r: SimulationResult, opp: ScoredOpportunity) -> Tuple[DecisionType, str]:
        """Final decision based on EV, constraints, and scorer confidence."""
        if r.ev_usd <= 0.0:
            return DecisionType.SKIP, f"Negative EV: ${r.ev_usd:.2f}"

        if not self._passes_constraints(r):
            return DecisionType.SKIP, "Failed risk constraints"

        conf = float(getattr(opp, "confidence_score", 0.0))
        if conf < 0.70:
            return DecisionType.SKIP, f"Low confidence from scorer: {conf:.2f}"

        # marginal EV vs fixed execution cost
        if r.ev_usd < self.config.base_execution_cost_usd:
            return DecisionType.DEFER, f"Marginal EV (${r.ev_usd:.2f}) < base cost (${self.config.base_execution_cost_usd:.2f})"

        if r.fail_prob > (self.config.max_fail_prob * 0.5):
            return DecisionType.DEFER, f"Elevated fail probability: {r.fail_prob:.1%}"

        return DecisionType.EXECUTE, f"Profitable: EV ${r.ev_usd:.2f}, P95 ${r.p95_usd:.2f}"

    # ── UX helper ────────────────────────────────────────────────────────────

    def get_simulation_summary(self, r: SimulationResult) -> str:
        lines = [
            f"Decision: {r.decision.value}",
            f"Rationale: {r.rationale}",
            f"Optimal Size: ${r.optimal_size_usd:,.2f}",
            f"Expected Value: ${r.ev_usd:.2f}",
            f"P95 / P50 / P5: ${r.p95_usd:.2f} / ${r.p50_usd:.2f} / ${r.p5_usd:.2f}",
            f"Net Return: {r.net_bps:.1f} bps",
            f"Failure Prob: {r.fail_prob:.1%}",
            f"Simulation Time: {r.simulation_time_ms:.0f} ms",
        ]
        if r.risk_metrics:
            lines += [
                f"Sharpe: {r.risk_metrics.sharpe_ratio:.2f}",
                f"Hit Rate: {r.risk_metrics.hit_rate:.1%}",
                f"Profit Factor: {r.risk_metrics.profit_factor:.2f}",
            ]
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Example usage (smoke test)
# ──────────────────────────────────────────────────────────────────────────────

async def example_usage() -> SimulationResult:
    """
    Minimal runnable example: builds a dummy ScoredOpportunity and one route.
    """

    # Build a dummy ScoredOpportunity
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    raw = RawOpportunity(
        id="opp_demo_001",
        timestamp=now,
        opportunity_type=OpportunityType.CROSS_EXCHANGE,
        pair="ETH/USD",
        buy_exchange="kraken",
        sell_exchange="coinbase",
        buy_price=2500.0,
        sell_price=2501.5,
        spread_bps=60.0,               # 60 bps gross spread
        buy_liquidity=150_000.0,
        sell_liquidity=180_000.0,
        min_liquidity=150_000.0,
        gas_price=30.0,
    )

    opp = ScoredOpportunity(
        raw_opportunity=raw,
        profitability_score=0.8,
        risk_score=0.7,
        confidence_score=0.85,
        liquidity_score=0.75,
        execution_score=0.7,
        overall_score=0.77,
        accepted=True,
        rejection_reason=None,
        estimated_profit_bps=55.0,
        estimated_profit_usd=0.0,
        estimated_slippage_bps=5.0,
        estimated_gas_cost_usd=20.0,
        net_profit_bps=40.0,
        priority_rank=1,
        processing_time_ms=10.0,
        expires_at=now,
        features={"demo": 1.0},
    )

    market = MarketConditions(
        eth_usd_price=2500.0,
        gas_price_gwei=30.0,
        network_congestion=1.2,
        mev_risk_level=0.6,
        volatility_regime="normal",
    )

    route = RouteConfig(
        route_id="kraken_coinbase_univ3",
        route_type=RouteType.CEX_ARBITRAGE,
        hops=[
            RouteHop("kraken", "cex", "USD", "ETH", liquidity_depth=120_000.0),
            RouteHop("uniswap_v3", "dex", "ETH", "USD", liquidity_depth=100_000.0),
        ],
        estimated_gas_limit=180_000,
        expected_latency_ms=800,
    )

    sim = ProfitabilitySimulator(SimulationConfig(max_size_usd=50_000.0, monte_carlo_runs=500))
    result = await sim.simulate(opp, market, [route])

    print(sim.get_simulation_summary(result))
    return result


if __name__ == "__main__":
    asyncio.run(example_usage())
