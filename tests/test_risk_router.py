# tests/test_risk_router.py
# Deterministic, pure-logic tests for RiskRouter
import copy
from typing import Optional
import pytest
from unittest.mock import Mock

from mcp.schemas import Signal, OrderSide, OrderType
from agents.risk.risk_router import RiskRouter, RiskRouterConfig


# ---- Lightweight mock decision objects ----
class MockComplianceDecision:
    def __init__(self, allowed: bool):
        self.allowed = allowed


class MockGateDecision:
    def __init__(
        self, halt_all: bool = False, reduce_only: bool = False, 
        size_multiplier: float = 1.0
    ):
        self.halt_all = halt_all
        self.reduce_only = reduce_only
        self.size_multiplier = size_multiplier


class MockAllocationDecision:
    def __init__(
        self,
        allowed: bool,
        notional_usd: float = 100.0,
        base_size: Optional[float] = None,
        leverage: float = 1.0,
        reduce_only: bool = False,
        reason: Optional[str] = None,
    ):
        self.allowed = allowed
        self.notional_usd = notional_usd
        self.base_size = base_size
        self.leverage = leverage
        self.reduce_only = reduce_only
        self.reason = reason or ""


# ---- Fixtures ----
@pytest.fixture
def cfg():
    return RiskRouterConfig(
        default_order_type=OrderType.LIMIT, 
        default_time_in_force="GTC", 
        allow_reduce_only_on_soft_stop=True
    )


@pytest.fixture
def compliance():
    # Create mock that doesn't have assess_signal by default (use spec to limit methods)
    mock = Mock()
    # Delete assess_signal so hasattr returns False
    del mock.assess_signal
    return mock


@pytest.fixture
def drawdown():
    mock = Mock()
    # Delete assess methods so they raise AttributeError if called without setup
    return mock


@pytest.fixture
def balancer():
    mock = Mock()
    return mock


@pytest.fixture
def router(cfg, compliance, drawdown, balancer):
    return RiskRouter(config=cfg, compliance=compliance, drawdown=drawdown, balancer=balancer)


@pytest.fixture
def sig():
    return Signal(
        strategy="scalp",
        symbol="BTC/USD",
        timeframe="15s",
        side=OrderSide.BUY,
        confidence=0.9,
        risk={"sl_bps": 25, "tp_bps": [50]},
        # Note: Signal model doesn't support metadata field, risk_router handles None gracefully
    )


# ---- Tests: Input validation ----
def test_missing_price(router, sig, compliance):
    out = router.assess(sig, price_usd=None)
    assert not out.allowed
    assert out.reasons == ["missing-price"]
    assert out.intent is None
    assert out.normalized["router_stage"] == "final"
    assert not compliance.mock_calls  # short-circuits before gates


def test_malformed_signal(router):
    bad = Signal(strategy="", symbol="BTC/USD", timeframe="1m", side=OrderSide.SELL, confidence=0.1)
    out = router.assess(bad, price_usd=100.0)
    assert not out.allowed and out.reasons == ["malformed-signal"]


def test_malformed_symbol(router):
    # Note: Signal model validates symbol format, so invalid symbols raise ValidationError
    # Testing router's defensive check with model_construct (bypasses validation)
    from pydantic import ValidationError as PydanticValidationError
    bad = Signal.model_construct(strategy="x", symbol="BTCUSD", timeframe="1m", side="sell", confidence=0.1)
    out = router.assess(bad, price_usd=100.0)
    assert not out.allowed and out.reasons == ["malformed-symbol"]


# ---- Tests: Compliance gate ----
def test_compliance_hard_deny(router, compliance, sig):
    compliance.assess.return_value = MockComplianceDecision(False)
    out = router.assess(sig, price_usd=10.0)
    assert not out.allowed and out.reasons == ["compliance-reject"]
    compliance.assess.assert_called_once()


def test_compliance_assess_signal_method(router, compliance, drawdown, balancer, sig):
    # prefer assess_signal if present
    delattr(compliance, "assess")
    compliance.assess_signal = Mock(return_value=MockComplianceDecision(True))
    drawdown.assess_can_open.return_value = MockGateDecision()
    balancer.propose_allocation.return_value = MockAllocationDecision(True)
    out = router.assess(sig, price_usd=10.0)
    assert out.allowed
    compliance.assess_signal.assert_called_once()


def test_compliance_exception_maps_to_reject(router, compliance, sig):
    compliance.assess.side_effect = Exception("boom")
    out = router.assess(sig, price_usd=10.0)
    assert not out.allowed and out.reasons == ["compliance-reject"]


# ---- Tests: Drawdown gate ----
def test_drawdown_halt(router, compliance, drawdown, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision(halt_all=True)
    out = router.assess(sig, price_usd=10.0)
    assert not out.allowed and out.reasons == ["drawdown-halt"]


def test_drawdown_reduce_only_propagates(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision(reduce_only=True)
    balancer.propose_allocation.return_value = MockAllocationDecision(True, reduce_only=False)
    out = router.assess(sig, price_usd=10.0)
    assert out.allowed
    assert "drawdown-reduce-only" in out.reasons
    assert out.intent.reduce_only is True
    assert out.normalized["reduce_only"] is True


def test_drawdown_size_multiplier_clamped(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision(size_multiplier=0.5)
    balancer.propose_allocation.return_value = MockAllocationDecision(True)
    _ = router.assess(sig, price_usd=10.0)
    call = balancer.propose_allocation.call_args.kwargs
    assert call["drawdown_gate"]["size_multiplier"] == 0.5


def test_drawdown_exception_maps_to_halt(router, compliance, drawdown, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.side_effect = Exception("x")
    out = router.assess(sig, price_usd=10.0)
    assert not out.allowed and out.reasons == ["drawdown-halt"]


# ---- Tests: Balancer gate ----
def test_balancer_deny_over_cap_gross(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision()
    balancer.propose_allocation.return_value = MockAllocationDecision(
        False, reason="over gross capacity"
    )
    out = router.assess(sig, price_usd=10.0)
    assert not out.allowed and out.reasons == ["over-cap-gross"]


def test_balancer_deny_budget(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision()
    balancer.propose_allocation.return_value = MockAllocationDecision(
        False, reason="over strategy budget"
    )
    out = router.assess(sig, price_usd=10.0)
    assert not out.allowed and out.reasons == ["over-budget-strategy"]


def test_balancer_spread_depth_mapping(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision()
    balancer.propose_allocation.return_value = MockAllocationDecision(
        False, reason="spread too wide"
    )
    out = router.assess(sig, price_usd=10.0)
    assert not out.allowed and out.reasons == ["spread-too-wide"]
    # depth too thin
    balancer.propose_allocation.return_value = MockAllocationDecision(
        False, reason="depth too thin"
    )
    out2 = router.assess(sig, price_usd=10.0)
    assert not out2.allowed and out2.reasons == ["depth-too-thin"]


def test_balancer_parameters_forwarded(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision(reduce_only=True, size_multiplier=0.8)
    balancer.propose_allocation.return_value = MockAllocationDecision(True)
    _ = router.assess(sig, price_usd=45000.0)
    kw = balancer.propose_allocation.call_args.kwargs
    assert kw["strategy"] == sig.strategy
    assert kw["symbol"] == sig.symbol
    assert kw["price_usd"] == 45000.0
    assert kw["stop_distance_bps"] == 25  # from signal.risk.sl_bps
    # Note: liquidity is None because Signal model doesn't have metadata field
    assert kw["liquidity"] is None
    assert kw["drawdown_gate"]["reduce_only"] is True
    assert kw["drawdown_gate"]["size_multiplier"] == 0.8
    assert kw["compliance_gate"]["allowed"] is True


# ---- Tests: Size validation & happy path ----
def test_tiny_notional_rejected(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision()
    balancer.propose_allocation.return_value = MockAllocationDecision(True, notional_usd=0.5)
    out = router.assess(sig, price_usd=10.0)
    assert not out.allowed and out.reasons == ["size-too-small"]


def test_tiny_base_size_rejected(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision()
    balancer.propose_allocation.return_value = MockAllocationDecision(
        True, notional_usd=10.0, base_size=1e-12
    )
    out = router.assess(sig, price_usd=10.0)
    assert not out.allowed and out.reasons == ["size-too-small"]


def test_happy_path_builds_intent(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision(reduce_only=False)
    balancer.propose_allocation.return_value = MockAllocationDecision(
        True, notional_usd=250.0, base_size=0.01, leverage=3.0
    )
    out = router.assess(sig, price_usd=50000.0)
    assert out.allowed
    assert out.intent.symbol == "BTC/USD"
    assert out.intent.side == OrderSide.BUY
    assert out.intent.order_type == OrderType.LIMIT
    assert out.intent.tif == "GTC"
    assert out.intent.size_quote_usd == 250.0
    assert out.intent.reduce_only is False
    assert out.normalized["price_used"] == 50000.0
    assert out.normalized["final_notional_usd"] == 250.0
    assert out.normalized["final_base_size"] == 0.01
    assert out.normalized["router_stage"] == "final"


# ---- Tests: Reason ordering & determinism ----
def test_reason_ordering_multiple(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision(reduce_only=True)
    balancer.propose_allocation.return_value = MockAllocationDecision(
        False, reason="over strategy budget and spread too wide"
    )
    out = router.assess(sig, price_usd=10.0)
    assert out.reasons == ["drawdown-reduce-only", "over-budget-strategy", "spread-too-wide"]


def test_determinism(router, compliance, drawdown, balancer, sig):
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision(reduce_only=True, size_multiplier=0.75)
    balancer.propose_allocation.return_value = MockAllocationDecision(
        True, notional_usd=123.0, base_size=0.002, leverage=2.0, reduce_only=True
    )
    out1 = router.assess(sig, price_usd=111.0)
    out2 = router.assess(copy.deepcopy(sig), price_usd=111.0)
    assert out1.allowed == out2.allowed
    assert out1.reasons == out2.reasons
    assert out1.normalized == out2.normalized
    assert out1.intent.symbol == out2.intent.symbol
    assert out1.intent.side == out2.intent.side
    assert out1.intent.order_type == out2.intent.order_type
    assert out1.intent.size_quote_usd == out2.intent.size_quote_usd
    assert out1.intent.reduce_only == out2.intent.reduce_only
    assert out1.intent.tif == out2.intent.tif


# ============================================================================
# TABLE-DRIVEN TESTS: Allow/Deny Scenarios
# ============================================================================

@pytest.mark.parametrize(
    "test_name,compliance_allowed,drawdown_halt,drawdown_reduce,size_mult,balancer_allowed,balancer_reason,expected_allowed,expected_reasons",
    [
        # Happy path scenarios
        ("happy_all_pass", True, False, False, 1.0, True, None, True, []),
        ("happy_with_reduce_only", True, False, True, 1.0, True, None, True, ["drawdown-reduce-only"]),
        ("happy_with_size_mult_80pct", True, False, False, 0.8, True, None, True, []),
        ("happy_with_size_mult_50pct", True, False, False, 0.5, True, None, True, []),

        # Compliance denials
        ("deny_compliance_reject", False, False, False, 1.0, True, None, False, ["compliance-reject"]),

        # Drawdown denials
        ("deny_drawdown_halt", True, True, False, 1.0, True, None, False, ["drawdown-halt"]),
        ("deny_drawdown_halt_ignores_balancer", True, True, False, 1.0, False, "over gross", False, ["drawdown-halt"]),

        # Balancer denials
        ("deny_balancer_over_gross", True, False, False, 1.0, False, "over gross capacity", False, ["over-cap-gross"]),
        ("deny_balancer_over_net", True, False, False, 1.0, False, "over net capacity", False, ["over-cap-net"]),
        ("deny_balancer_over_symbol", True, False, False, 1.0, False, "over symbol capacity", False, ["over-cap-symbol"]),
        ("deny_balancer_over_budget", True, False, False, 1.0, False, "over strategy budget", False, ["over-budget-strategy"]),
        ("deny_balancer_spread_wide", True, False, False, 1.0, False, "spread too wide", False, ["spread-too-wide"]),
        ("deny_balancer_depth_thin", True, False, False, 1.0, False, "depth too thin", False, ["depth-too-thin"]),

        # Combined scenarios
        ("combined_drawdown_reduce_plus_balancer_deny", True, False, True, 1.0, False, "over gross", False, ["drawdown-reduce-only", "over-cap-gross"]),
        ("combined_all_warnings", True, False, True, 0.75, True, None, True, ["drawdown-reduce-only"]),
    ],
    ids=lambda x: x if isinstance(x, str) else ""
)
def test_router_allow_deny_table(
    cfg, compliance, drawdown, balancer, sig,
    test_name, compliance_allowed, drawdown_halt, drawdown_reduce, size_mult,
    balancer_allowed, balancer_reason, expected_allowed, expected_reasons
):
    """Table-driven tests for comprehensive allow/deny scenarios"""
    router = RiskRouter(config=cfg, compliance=compliance, drawdown=drawdown, balancer=balancer)

    # Setup mocks
    compliance.assess.return_value = MockComplianceDecision(compliance_allowed)
    drawdown.assess_can_open.return_value = MockGateDecision(
        halt_all=drawdown_halt,
        reduce_only=drawdown_reduce,
        size_multiplier=size_mult
    )
    balancer.propose_allocation.return_value = MockAllocationDecision(
        allowed=balancer_allowed,
        notional_usd=100.0,
        base_size=0.002,
        reason=balancer_reason
    )

    # Execute
    result = router.assess(sig, price_usd=50000.0)

    # Assert
    assert result.allowed == expected_allowed, f"Test '{test_name}' failed: allowed mismatch"
    assert result.reasons == expected_reasons, f"Test '{test_name}' failed: reasons mismatch"

    # Additional assertions for allowed cases
    if expected_allowed:
        assert result.intent is not None
        assert result.intent.symbol == sig.symbol
        assert result.intent.side == sig.side


# ============================================================================
# TABLE-DRIVEN TESTS: Size Multiplier Scenarios
# ============================================================================

@pytest.mark.parametrize(
    "size_multiplier,expected_clamped,should_forward_to_balancer",
    [
        (1.0, 1.0, True),
        (0.8, 0.8, True),
        (0.5, 0.5, True),
        (0.25, 0.25, True),
        (0.0, 0.0, True),
        (-0.5, 0.0, True),  # Negative clamped to 0
        (1.5, 1.0, True),   # >1 clamped to 1
        (2.0, 1.0, True),   # >1 clamped to 1
    ],
    ids=[
        "normal_100pct",
        "normal_80pct",
        "normal_50pct",
        "normal_25pct",
        "edge_0pct",
        "edge_negative_clamped",
        "edge_150pct_clamped",
        "edge_200pct_clamped",
    ]
)
def test_size_multiplier_clamping_table(
    cfg, compliance, drawdown, balancer, sig,
    size_multiplier, expected_clamped, should_forward_to_balancer
):
    """Table-driven tests for size multiplier clamping logic"""
    router = RiskRouter(config=cfg, compliance=compliance, drawdown=drawdown, balancer=balancer)

    # Setup
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision(
        halt_all=False,
        reduce_only=False,
        size_multiplier=size_multiplier
    )
    balancer.propose_allocation.return_value = MockAllocationDecision(
        allowed=True,
        notional_usd=100.0,
        base_size=0.002
    )

    # Execute
    result = router.assess(sig, price_usd=50000.0)

    # Verify size multiplier was clamped and forwarded
    if should_forward_to_balancer:
        call_kwargs = balancer.propose_allocation.call_args.kwargs
        assert call_kwargs["drawdown_gate"]["size_multiplier"] == expected_clamped

    # Result should be allowed regardless of clamping
    assert result.allowed


# ============================================================================
# TABLE-DRIVEN TESTS: Tiny Size Edge Cases
# ============================================================================

@pytest.mark.parametrize(
    "notional_usd,base_size,expected_allowed,expected_reason",
    [
        # Normal sizes
        (100.0, 0.002, True, None),
        (10.0, 0.0002, True, None),
        (1.0, 0.00002, True, None),

        # Edge: exactly at minimum
        (1.0, 1e-9, True, None),

        # Tiny notional
        (0.99, 0.002, False, "size-too-small"),
        (0.5, 0.001, False, "size-too-small"),
        (0.01, 0.0001, False, "size-too-small"),

        # Tiny base size
        (100.0, 1e-10, False, "size-too-small"),
        (50.0, 1e-15, False, "size-too-small"),

        # Both tiny
        (0.1, 1e-12, False, "size-too-small"),
    ],
    ids=[
        "normal_100usd",
        "normal_10usd",
        "normal_1usd_min",
        "edge_exactly_min",
        "tiny_notional_99cents",
        "tiny_notional_50cents",
        "tiny_notional_1cent",
        "tiny_base_1e-10",
        "tiny_base_1e-15",
        "both_tiny",
    ]
)
def test_tiny_size_rejection_table(
    cfg, compliance, drawdown, balancer, sig,
    notional_usd, base_size, expected_allowed, expected_reason
):
    """Table-driven tests for tiny size rejection logic"""
    router = RiskRouter(config=cfg, compliance=compliance, drawdown=drawdown, balancer=balancer)

    # Setup
    compliance.assess.return_value = MockComplianceDecision(True)
    drawdown.assess_can_open.return_value = MockGateDecision()
    balancer.propose_allocation.return_value = MockAllocationDecision(
        allowed=True,
        notional_usd=notional_usd,
        base_size=base_size
    )

    # Execute
    result = router.assess(sig, price_usd=50000.0)

    # Assert
    assert result.allowed == expected_allowed
    if not expected_allowed:
        assert expected_reason in result.reasons
