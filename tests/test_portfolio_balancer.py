"""
tests/test_portfolio_balancer.py

Comprehensive tests for PortfolioBalancer pure-logic sizing & caps.

Covers:
- Happy path sizing within budgets/caps
- Strategy budget clamp and zero-remaining case
- Symbol/gross/net caps
- Per-trade risk sizing monotonicity & bps=0 edge
- Leverage off vs on; caps use leveraged exposure
- Liquidity guards (spread/depth) deterministic scaling
- Liquidity deny threshold (optional)
- Per-strategy risk overrides
- Per-symbol min/max overrides
- Drawdown reduce_only/halt_all with size_multiplier
- Compliance rejection
- Correlation bucket cap
- Invalid equity guard
- Determinism (same inputs => identical outputs)
"""

from __future__ import annotations

import pytest

from agents.risk.portfolio_balancer import (
    PortfolioBalancer,
    BalancePolicy,
    ExposureSnapshot,
)


def _mk_balancer(policy: BalancePolicy, equity: float = 10_000.0) -> PortfolioBalancer:
    b = PortfolioBalancer(policy)
    b.update_equity(equity)
    b.update_exposure_snapshot(ExposureSnapshot(equity_usd=equity))
    return b


# ---------- Core sizing ----------

def test_happy_path_allocation():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3, "trend": 0.4, "meanrev": 0.3},
        max_strategy_exposure_pct=0.5,
        max_symbol_exposure_pct=0.25,
        max_gross_exposure_pct=1.0,
        max_net_exposure_pct=0.5,
        per_trade_risk_pct=0.01,   # 1% per trade
        min_notional_usd=10.0,
        max_notional_usd=1000.0,   # cap
        leverage_allowed=False,
        max_leverage=1.0,
    )
    b = _mk_balancer(policy)
    d = b.propose_allocation(
        strategy="scalp",
        symbol="BTC/USD",
        price_usd=50_000.0,
        stop_distance_bps=100,  # raw 10_000 -> capped to 1_000
    )
    assert d.allowed is True
    assert d.reduce_only is False
    assert d.notional_usd == pytest.approx(1_000.0, rel=1e-9)
    assert d.base_size == pytest.approx(0.02, rel=1e-9)
    assert d.leverage == 1.0
    assert d.reasons == []
    # normalized keys present
    for k in (
        "strategy",
        "symbol",
        "strategy_budget_usd",
        "symbol_cap_usd",
        "gross_cap_usd",
        "net_cap_usd",
        "bucket_cap_usd",
        "final_scale",
        "final_notional_usd",
        "final_base_size",
        "final_leverage",
    ):
        assert k in d.normalized


def test_strategy_budget_cap_clamp_reason():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        max_notional_usd=1_000.0,
    )
    b = _mk_balancer(policy, equity=10_000.0)
    # 30% of 10k = 3,000 budget; existing strategy exposure 2,800 -> room 200
    snap = ExposureSnapshot(equity_usd=10_000.0, by_strategy_usd={"scalp": 2_800.0})
    b.update_exposure_snapshot(snap)
    d = b.propose_allocation(
        strategy="scalp", symbol="BTC/USD", price_usd=50_000.0, stop_distance_bps=100
    )
    assert d.allowed is True
    assert d.notional_usd == pytest.approx(200.0, rel=1e-9)
    assert "over-budget-strategy" in d.reasons


def test_strategy_budget_exceeded_to_zero():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        max_notional_usd=1_000.0,
    )
    b = _mk_balancer(policy, equity=10_000.0)
    # At budget already (3,000)
    snap = ExposureSnapshot(equity_usd=10_000.0, by_strategy_usd={"scalp": 3_000.0})
    b.update_exposure_snapshot(snap)
    d = b.propose_allocation(
        strategy="scalp", symbol="BTC/USD", price_usd=50_000.0, stop_distance_bps=100
    )
    assert d.allowed is False
    assert d.notional_usd == 0.0
    assert "over-budget-strategy" in d.reasons


def test_symbol_exposure_cap():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        max_notional_usd=1_000.0,
        max_symbol_exposure_pct=0.25,
    )
    b = _mk_balancer(policy, equity=10_000.0)
    # cap 25% of 10k = 2,500; current symbol 2,000 -> room 500
    snap = ExposureSnapshot(equity_usd=10_000.0, by_symbol_usd={"BTC/USD": 2_000.0})
    b.update_exposure_snapshot(snap)
    d = b.propose_allocation(
        strategy="scalp", symbol="BTC/USD", price_usd=50_000.0, stop_distance_bps=100
    )
    assert d.allowed is True
    assert d.notional_usd == pytest.approx(500.0, rel=1e-9)
    assert "over-cap-symbol" in d.reasons


def test_gross_exposure_cap():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        max_notional_usd=1_000.0,
        max_gross_exposure_pct=1.0,
    )
    b = _mk_balancer(policy, equity=10_000.0)
    # gross cap = 10,000; current 9,500 -> room 500
    snap = ExposureSnapshot(equity_usd=10_000.0, gross_exposure_usd=9_500.0)
    b.update_exposure_snapshot(snap)
    d = b.propose_allocation(
        strategy="scalp", symbol="BTC/USD", price_usd=50_000.0, stop_distance_bps=100
    )
    assert d.allowed is True
    assert d.notional_usd == pytest.approx(500.0, rel=1e-9)
    assert "over-cap-gross" in d.reasons


def test_net_exposure_cap():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        max_notional_usd=1_000.0,
        max_net_exposure_pct=0.5,
    )
    b = _mk_balancer(policy, equity=10_000.0)
    # net cap = 5,000; current 4,500 -> room 500
    snap = ExposureSnapshot(equity_usd=10_000.0, net_exposure_usd=4_500.0)
    b.update_exposure_snapshot(snap)
    d = b.propose_allocation(
        strategy="scalp", symbol="BTC/USD", price_usd=50_000.0, stop_distance_bps=100
    )
    assert d.allowed is True
    assert d.notional_usd == pytest.approx(500.0, rel=1e-9)
    assert "over-cap-net" in d.reasons


def test_per_trade_risk_monotonicity():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        max_notional_usd=1_000.0,
    )
    b = _mk_balancer(policy)
    # Larger stop => smaller notional (capped by max_notional_usd for first two)
    d1 = b.propose_allocation("scalp", "BTC/USD", 50_000.0, 50)
    d2 = b.propose_allocation("scalp", "BTC/USD", 50_000.0, 100)
    d3 = b.propose_allocation("scalp", "BTC/USD", 50_000.0, 200)
    assert d1.notional_usd == d2.notional_usd == 1_000.0
    assert d3.notional_usd == pytest.approx(500.0, rel=1e-9)


def test_zero_stop_distance_is_one():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3}, per_trade_risk_pct=0.01, max_notional_usd=1_000.0
    )
    b = _mk_balancer(policy)
    d = b.propose_allocation("scalp", "BTC/USD", 50_000.0, 0)
    assert d.notional_usd == 1_000.0  # capped by max_notional_usd


# ---------- Leverage & caps on leveraged exposure ----------

def test_leverage_disabled_default():
    policy = BalancePolicy(target_alloc_strategy={"scalp": 0.3})
    b = _mk_balancer(policy)
    d = b.propose_allocation("scalp", "BTC/USD", 50_000.0, 100)
    assert d.leverage == 1.0


def test_leverage_enabled_caps_apply_on_levered_exposure():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        leverage_allowed=True,
        max_leverage=2.0,     # exposure doubles for caps
        max_symbol_exposure_pct=0.25,
        max_net_exposure_pct=0.5,
        max_gross_exposure_pct=1.0,
        max_strategy_exposure_pct=0.5,
        max_notional_usd=1_000.0,
    )
    b = _mk_balancer(policy, 10_000.0)
    # Symbol already at 2,000 exposure; cap is 2,500; with 2x leverage new exposure = 2*notional
    snap = ExposureSnapshot(equity_usd=10_000.0, by_symbol_usd={"BTC/USD": 2_000.0})
    b.update_exposure_snapshot(snap)
    d = b.propose_allocation("scalp", "BTC/USD", 50_000.0, 100)
    # Available headroom in exposure = 500, so with 2x leverage, notional must clamp to 250
    assert d.notional_usd == pytest.approx(250.0, rel=1e-9)
    assert d.leverage == 2.0
    assert "over-cap-symbol" in d.reasons


# ---------- Liquidity guards ----------

def test_liquidity_spread_guard_scales_and_reasons():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        max_spread_bps=10,
        max_notional_usd=1_000.0,
    )
    b = _mk_balancer(policy)
    d = b.propose_allocation(
        "scalp", "BTC/USD", 50_000.0, 100, liquidity={"spread_bps": 20}
    )
    # raw 1_000 → × (10/20) = 500
    assert d.notional_usd == pytest.approx(500.0, rel=1e-9)
    assert "spread-too-wide" in d.reasons


def test_liquidity_depth_guard_scales_and_reasons():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        min_book_depth_usd=1_000.0,
        max_notional_usd=1_000.0,
    )
    b = _mk_balancer(policy)
    d = b.propose_allocation(
        "scalp", "BTC/USD", 50_000.0, 100, liquidity={"depth_usd": 500.0}
    )
    # raw 1_000 → × (500/1000) = 500
    assert d.notional_usd == pytest.approx(500.0, rel=1e-9)
    assert "depth-too-thin" in d.reasons


def test_min_liquidity_scale_floor_applied():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        max_spread_bps=10,
        min_liquidity_scale=0.5,   # floor
        max_notional_usd=1_000.0,
    )
    b = _mk_balancer(policy)
    # spread 40bps -> raw scale 10/40 = 0.25, but floor forces 0.5
    d = b.propose_allocation(
        "scalp", "BTC/USD", 50_000.0, 100, liquidity={"spread_bps": 40}
    )
    # base raw would be 1_000 * 0.25 = 250, but floor => 500
    assert d.notional_usd == pytest.approx(500.0, rel=1e-9)


def test_liquidity_deny_if_under_min_triggers():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,
        max_spread_bps=10,
        liquidity_deny_if_under_min=True,
        min_notional_usd=400.0,    # raise min
        max_notional_usd=1_000.0,
    )
    b = _mk_balancer(policy)
    # spread too wide -> scale 10/50 = 0.2; pre_constraints_notional = 1_000 * 0.2 = 200 < min(400)
    d = b.propose_allocation(
        "scalp", "BTC/USD", 50_000.0, 100, liquidity={"spread_bps": 50}
    )
    assert d.allowed is False
    assert d.notional_usd == 0.0
    assert "liquidity-deny" in d.reasons


# ---------- Per-strategy / per-symbol overrides ----------

def test_per_strategy_risk_override():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.01,  # default 1%
        per_trade_risk_pct_by_strategy={"scalp": 0.02},  # override to 2%
        max_notional_usd=2_000.0,
    )
    b = _mk_balancer(policy, 10_000.0)
    d = b.propose_allocation("scalp", "BTC/USD", 50_000.0, 100)
    # raw notional = 10k * 2% * 100 = 20_000 => capped 2,000
    assert d.notional_usd == pytest.approx(2_000.0, rel=1e-9)


def test_per_symbol_min_override_applies_before_liquidity():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.001,  # small baseline
        min_notional_usd=10.0,
        min_notional_by_symbol_usd={"ETH/USD": 150.0},  # force higher floor
        max_notional_usd=10_000.0,
    )
    b = _mk_balancer(policy)
    d = b.propose_allocation("scalp", "ETH/USD", 2_000.0, 100)
    assert d.notional_usd >= 150.0  # per-symbol floor respected


def test_per_symbol_max_override_caps():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3},
        per_trade_risk_pct=0.05,   # large
        max_notional_usd=5_000.0,
        max_notional_by_symbol_usd={"BTC/USD": 600.0},
    )
    b = _mk_balancer(policy)
    d = b.propose_allocation("scalp", "BTC/USD", 50_000.0, 100)
    assert d.notional_usd == pytest.approx(600.0, rel=1e-9)


# ---------- Drawdown & compliance ----------

def test_drawdown_halt_all():
    policy = BalancePolicy(target_alloc_strategy={"scalp": 0.3})
    b = _mk_balancer(policy)
    d = b.propose_allocation(
        "scalp",
        "BTC/USD",
        50_000.0,
        100,
        drawdown_gate={"halt_all": True},
    )
    assert d.allowed is False and d.reduce_only is True
    assert d.notional_usd == 0.0
    assert "drawdown-halt" in d.reasons


def test_drawdown_reduce_only_and_multiplier():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3}, per_trade_risk_pct=0.01, max_notional_usd=1_000.0
    )
    b = _mk_balancer(policy)
    d = b.propose_allocation(
        "scalp",
        "BTC/USD",
        50_000.0,
        100,
        drawdown_gate={"reduce_only": True, "size_multiplier": 0.4},
    )
    # raw 10,000 -> capped 1,000 -> ×0.4 = 400 (no other caps)
    assert d.allowed is True and d.reduce_only is True
    assert d.notional_usd == pytest.approx(400.0, rel=1e-9)
    assert "drawdown-reduce" in d.reasons


def test_compliance_rejection():
    policy = BalancePolicy(target_alloc_strategy={"scalp": 0.3})
    b = _mk_balancer(policy)
    d = b.propose_allocation(
        "scalp",
        "BTC/USD",
        50_000.0,
        100,
        compliance_gate={"allowed": False},
    )
    assert d.allowed is False and d.notional_usd == 0.0
    assert "compliance-reject" in d.reasons


# ---------- Correlation bucket cap ----------

def test_correlation_bucket_cap():
    policy = BalancePolicy(
        target_alloc_strategy={"trend": 0.4},
        per_trade_risk_pct=0.01,
        corr_cap_pct=0.3,         # 30% of equity per bucket
        max_notional_usd=1_000.0,
    )
    b = _mk_balancer(policy)
    b.set_correlation_buckets({"ETH/USD": "L1s"})
    # Snapshot stores bucket exposure as PERCENT of equity (e.g., 0.25 → 25%)
    # $2,500 used, cap $3,000
    snap = ExposureSnapshot(
        equity_usd=10_000.0, by_corr_bucket_pct={"L1s": 0.25}
    )
    b.update_exposure_snapshot(snap)
    d = b.propose_allocation("trend", "ETH/USD", 2_000.0, 100)
    # Room is 500 USD => notional must clamp to 500
    assert d.notional_usd == pytest.approx(500.0, rel=1e-9)
    assert "over-cap-correlation" in d.reasons


# ---------- Invalid equity & determinism ----------

def test_invalid_equity_rejected():
    policy = BalancePolicy(target_alloc_strategy={"scalp": 0.3})
    b = _mk_balancer(policy, equity=0.0)
    d = b.propose_allocation("scalp", "BTC/USD", 50_000.0, 100)
    assert d.allowed is False
    assert "invalid-equity" in d.reasons


def test_determinism_same_inputs_identical_outputs():
    policy = BalancePolicy(
        target_alloc_strategy={"scalp": 0.3}, per_trade_risk_pct=0.01, max_notional_usd=1_000.0
    )
    b = _mk_balancer(policy)
    kwargs = dict(strategy="scalp", symbol="BTC/USD", price_usd=50_000.0, stop_distance_bps=100)
    d1 = b.propose_allocation(**kwargs)
    d2 = b.propose_allocation(**kwargs)
    assert d1.model_dump() == d2.model_dump()
