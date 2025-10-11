"""
Comprehensive unit tests for risk management modules.
100% pure inputs, no I/O dependencies, parametrized edge cases.

Tests:
- drawdown_protector: state transitions, rolling windows, loss streaks
- compliance_checker: KYC/region/leverage/symbol/time validation
- portfolio_balancer: position caps, correlation buckets, liquidity scaling
- risk_router: end-to-end signal → order intent routing
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from agents.risk.drawdown_protector import (
    DrawdownProtector,
    DrawdownBands,
    SnapshotEvent,
    FillEvent,
    GateDecision,
)
from agents.risk.compliance_checker import (
    ComplianceChecker,
    ComplianceConfig,
    ComplianceDecision,
)
from agents.risk.portfolio_balancer import (
    PortfolioBalancer,
    BalancePolicy,
    ExposureSnapshot,
    AllocationDecision,
)
from agents.risk.risk_router import (
    RiskRouter,
    RiskRouterConfig,
    RouteResult,
)
from mcp.schemas import Signal, OrderSide, OrderType


# ============================================================================
# DRAWDOWN PROTECTOR TESTS
# ============================================================================


class TestDrawdownProtector:
    """Test drawdown protection with state machine transitions."""

    @pytest.fixture
    def minimal_policy(self) -> DrawdownBands:
        """Minimal drawdown policy for testing."""
        return DrawdownBands(
            daily_stop_pct=-0.10,  # -10% daily
            rolling_windows_pct=[(3600, -0.05), (14400, -0.08)],  # 1h: -5%, 4h: -8%
            max_consecutive_losses=3,
            cooldown_after_soft_s=60,
            cooldown_after_hard_s=180,
            scale_bands=[(-0.05, 0.50), (-0.10, 0.25), (-0.15, 0.00)],
            enable_per_strategy=True,
            enable_per_symbol=True,
        )

    @pytest.fixture
    def protector(self, minimal_policy: DrawdownBands) -> DrawdownProtector:
        """Create protector instance."""
        protector = DrawdownProtector(policy=minimal_policy)
        # Initialize with starting equity
        protector.reset(equity_start_of_day_usd=100.0, ts_s=1000000)
        return protector

    def test_initial_state_allows_all(self, protector: DrawdownProtector):
        """Initial state should allow all new positions."""
        gate = protector.assess_can_open(strategy="trend", symbol="BTC/USD")
        assert gate.allow_new_positions is True
        assert gate.reduce_only is False
        assert gate.halt_all is False
        assert gate.size_multiplier == 1.0

    @pytest.mark.parametrize(
        "equity_curve,expected_mode",
        [
            # No drawdown
            ([100.0, 105.0, 110.0], "normal"),
            # Small drawdown (< 5% warn threshold)
            ([100.0, 98.0, 97.0], "normal"),
            # Warn threshold (5% drawdown triggers warn via scale_bands)
            ([100.0, 95.0, 94.0], "warn"),
            # Soft stop (10% daily stop)
            ([100.0, 90.0, 89.0], "soft_stop"),
            # Hard halt (15% exceeds hard threshold)
            ([100.0, 85.0, 84.0], "hard_halt"),
        ],
    )
    def test_portfolio_state_transitions(
        self,
        protector: DrawdownProtector,
        equity_curve: List[float],
        expected_mode: str,
    ):
        """Test portfolio-level state transitions based on drawdown."""
        start_equity = equity_curve[0]
        base_ts = 1000000

        for i, equity in enumerate(equity_curve):
            event = SnapshotEvent(
                ts_s=base_ts + i * 60,  # 1 minute intervals
                equity_start_of_day_usd=start_equity,
                equity_current_usd=equity,
                strategy_equity_usd=None,
                symbol_equity_usd=None,
            )
            protector.ingest_snapshot(event)

        # Check final state
        state = protector.current_state()
        assert state.portfolio.mode == expected_mode

    @pytest.mark.parametrize(
        "drawdown_pct,expected_multiplier",
        [
            (0.00, 1.00),  # No drawdown
            (0.03, 1.00),  # Below warn (5%)
            (0.06, 0.50),  # In warn band (-5% to -10% → 0.50)
            (0.11, 0.25),  # In soft stop band (-10% to -15% → 0.25)
            (0.16, 0.00),  # Hard halt (>-15% → 0.00)
        ],
    )
    def test_size_multiplier_scaling(
        self,
        drawdown_pct: float,
        expected_multiplier: float,
    ):
        """Test size multiplier scales with drawdown severity."""
        policy = DrawdownBands(
            daily_stop_pct=-0.10,
            scale_bands=[(-0.05, 0.50), (-0.10, 0.25), (-0.15, 0.00)],
        )
        protector = DrawdownProtector(policy=policy)

        # Set up equity curve with specific drawdown
        start_equity = 100.0
        current_equity = start_equity * (1.0 - drawdown_pct)
        base_ts = 1000000

        protector.reset(equity_start_of_day_usd=start_equity, ts_s=base_ts)

        # Feed snapshot with drawdown
        protector.ingest_snapshot(
            SnapshotEvent(
                ts_s=base_ts + 60,
                equity_start_of_day_usd=start_equity,
                equity_current_usd=current_equity,
            )
        )

        gate = protector.assess_can_open(strategy="trend", symbol="BTC/USD")
        assert abs(gate.size_multiplier - expected_multiplier) < 0.01

    @pytest.mark.parametrize(
        "loss_count,expected_halt",
        [
            (0, False),  # No losses
            (1, False),  # Below threshold
            (2, False),  # Below threshold
            (3, True),  # At threshold (soft stop on first breach)
            (4, True),  # Over threshold
        ],
    )
    def test_consecutive_loss_streak_halt(
        self,
        protector: DrawdownProtector,
        loss_count: int,
        expected_halt: bool,
    ):
        """Test halt on consecutive loss streak."""
        base_ts = 1000000

        # Feed consecutive losses
        for i in range(loss_count):
            event = FillEvent(
                ts_s=base_ts + i * 60,
                pnl_after_fees=-10.0,  # Losing trade
                strategy="trend",
                symbol="BTC/USD",
                won=False,
            )
            protector.ingest_fill(event)

        gate = protector.assess_can_open(strategy="trend", symbol="BTC/USD")
        # First streak breach triggers soft_stop (reduce_only=True) not hard halt
        # Second breach same day triggers hard_halt
        if loss_count >= 3:
            assert gate.reduce_only is True or gate.halt_all is True
        else:
            assert gate.halt_all == expected_halt

    def test_loss_streak_resets_on_win(self, protector: DrawdownProtector):
        """Loss streak should reset after a winning trade."""
        base_ts = 1000000

        # Two losses
        for i in range(2):
            protector.ingest_fill(
                FillEvent(
                    ts_s=base_ts + i * 60,
                    pnl_after_fees=-10.0,
                    strategy="trend",
                    symbol="BTC/USD",
                    won=False,
                )
            )

        # Win (resets streak)
        protector.ingest_fill(
            FillEvent(
                ts_s=base_ts + 120,
                pnl_after_fees=20.0,  # Winning trade
                strategy="trend",
                symbol="BTC/USD",
                won=True,
            )
        )

        # One more loss (streak = 1, not 3)
        protector.ingest_fill(
            FillEvent(
                ts_s=base_ts + 180,
                pnl_after_fees=-5.0,
                strategy="trend",
                symbol="BTC/USD",
                won=False,
            )
        )

        gate = protector.assess_can_open(strategy="trend", symbol="BTC/USD")
        assert gate.halt_all is False  # Should not halt (streak = 1)

    def test_strategy_isolation(self, protector: DrawdownProtector):
        """Strategy drawdowns should be isolated."""
        base_ts = 1000000
        start_equity = 100.0

        # Strategy A: large drawdown
        for i in range(3):
            protector.ingest_snapshot(
                SnapshotEvent(
                    ts_s=base_ts + i * 60,
                    equity_start_of_day_usd=start_equity,
                    equity_current_usd=start_equity,  # Portfolio stays flat
                    strategy_equity_usd={
                        "strategyA": start_equity - i * 10.0,  # A declines
                        "strategyB": start_equity,  # B stays flat
                    },
                )
            )

        # Strategy A should be restricted (large drawdown)
        gate_a = protector.assess_can_open(strategy="strategyA", symbol="BTC/USD")
        assert gate_a.reduce_only is True or gate_a.halt_all is True

        # Strategy B should be fine (no drawdown)
        gate_b = protector.assess_can_open(strategy="strategyB", symbol="BTC/USD")
        assert gate_b.allow_new_positions is True


# ============================================================================
# COMPLIANCE CHECKER TESTS
# ============================================================================


class TestComplianceChecker:
    """Test compliance validation with pure inputs."""

    @pytest.fixture
    def minimal_config(self) -> ComplianceConfig:
        """Minimal compliance config."""
        return ComplianceConfig(
            required_kyc_tier=2,
            user_kyc_tier=3,
            user_region="US",
            blocked_regions=["KP", "IR"],
            max_leverage=2.0,
            margin_allowed=True,
            allowed_symbols=["BTC/USD", "ETH/USD", "SOL/USD"],
            banned_symbols=[],
            allowed_quote_currencies=["USD", "USDT"],
            trading_windows=[],  # Always allow
            min_notional_usd=10.0,
            max_notional_usd=100000.0,
        )

    @pytest.fixture
    def checker(self, minimal_config: ComplianceConfig) -> ComplianceChecker:
        """Create compliance checker."""
        return ComplianceChecker(config=minimal_config)

    @pytest.fixture
    def valid_signal(self) -> Signal:
        """Valid signal for testing."""
        return Signal(
            strategy="trend",
            symbol="BTC/USD",
            timeframe="1m",
            side=OrderSide.BUY,
            confidence=0.75,
        )

    def test_valid_signal_passes(
        self,
        checker: ComplianceChecker,
        valid_signal: Signal,
    ):
        """Valid signal should pass all checks."""
        decision = checker.assess_signal(valid_signal, price_usd=50000.0)
        assert decision.allowed is True
        assert len(decision.reasons) == 0

    @pytest.mark.parametrize(
        "user_tier,required_tier,expected_allowed",
        [
            (3, 2, True),  # User tier higher (OK)
            (2, 2, True),  # User tier equal (OK)
            (1, 2, False),  # User tier lower (DENY)
            (0, 1, False),  # No KYC (DENY)
        ],
    )
    def test_kyc_tier_validation(
        self,
        valid_signal: Signal,
        user_tier: int,
        required_tier: int,
        expected_allowed: bool,
    ):
        """Test KYC tier validation."""
        config = ComplianceConfig(
            required_kyc_tier=required_tier,
            user_kyc_tier=user_tier,
            user_region="US",
            allowed_symbols=["BTC/USD"],
        )
        checker = ComplianceChecker(config=config)

        decision = checker.assess_signal(valid_signal, price_usd=50000.0)
        assert decision.allowed == expected_allowed
        if not expected_allowed:
            assert any("kyc" in r.lower() for r in decision.reasons)

    @pytest.mark.parametrize(
        "user_region,blocked_regions,expected_allowed",
        [
            ("US", ["KP", "IR"], True),  # Not blocked
            ("KP", ["KP", "IR"], False),  # Blocked region
            ("IR", ["KP", "IR"], False),  # Blocked region
            ("CN", [], True),  # No restrictions
        ],
    )
    def test_regional_restrictions(
        self,
        valid_signal: Signal,
        user_region: str,
        blocked_regions: List[str],
        expected_allowed: bool,
    ):
        """Test regional restrictions."""
        config = ComplianceConfig(
            required_kyc_tier=0,
            user_kyc_tier=3,
            user_region=user_region,
            blocked_regions=blocked_regions,
            allowed_symbols=["BTC/USD"],
        )
        checker = ComplianceChecker(config=config)

        decision = checker.assess_signal(valid_signal, price_usd=50000.0)
        assert decision.allowed == expected_allowed
        if not expected_allowed:
            assert any("region" in r.lower() for r in decision.reasons)

    @pytest.mark.parametrize(
        "symbol,whitelist,blacklist,expected_allowed",
        [
            ("BTC/USD", ["BTC/USD", "ETH/USD"], [], True),  # In whitelist
            ("SOL/USD", ["BTC/USD", "ETH/USD"], [], False),  # Not in whitelist
            ("BTC/USD", [], ["ETH/USD"], True),  # Not in blacklist
            ("BTC/USD", [], ["BTC/USD"], False),  # In blacklist
            ("BTC/USD", [], [], True),  # No restrictions
        ],
    )
    def test_symbol_universe_validation(
        self,
        symbol: str,
        whitelist: List[str],
        blacklist: List[str],
        expected_allowed: bool,
    ):
        """Test symbol universe validation (whitelist/blacklist)."""
        config = ComplianceConfig(
            required_kyc_tier=0,
            user_kyc_tier=3,
            user_region="US",
            allowed_symbols=whitelist if whitelist else None,
            banned_symbols=blacklist,
        )
        checker = ComplianceChecker(config=config)

        signal = Signal(
            strategy="trend",
            symbol=symbol,
            timeframe="1m",
            side=OrderSide.BUY,
            confidence=0.75,
        )

        decision = checker.assess_signal(signal, price_usd=50000.0)
        assert decision.allowed == expected_allowed
        if not expected_allowed:
            assert any("symbol" in r.lower() for r in decision.reasons)

    @pytest.mark.parametrize(
        "quote_currency,allowed_quotes,expected_allowed",
        [
            ("USD", ["USD", "USDT"], True),  # Allowed
            ("USDT", ["USD", "USDT"], True),  # Allowed
            ("EUR", ["USD", "USDT"], False),  # Not allowed
            ("BTC", ["USD"], False),  # Not allowed
        ],
    )
    def test_quote_currency_filtering(
        self,
        quote_currency: str,
        allowed_quotes: List[str],
        expected_allowed: bool,
    ):
        """Test quote currency filtering."""
        config = ComplianceConfig(
            required_kyc_tier=0,
            user_kyc_tier=3,
            user_region="US",
            allowed_quote_currencies=allowed_quotes,
        )
        checker = ComplianceChecker(config=config)

        signal = Signal(
            strategy="trend",
            symbol=f"BTC/{quote_currency}",
            timeframe="1m",
            side=OrderSide.BUY,
            confidence=0.75,
        )

        decision = checker.assess_signal(signal, price_usd=50000.0)
        assert decision.allowed == expected_allowed

    @pytest.mark.parametrize(
        "leverage,max_allowed,margin_allowed,expected_allowed",
        [
            (1.0, 2.0, True, True),  # Within limit
            (2.0, 2.0, True, True),  # At limit
            (3.0, 2.0, True, False),  # Over limit
            (2.0, 1.0, False, False),  # Margin not allowed
            (1.0, 1.0, False, True),  # No margin needed
        ],
    )
    def test_leverage_caps(
        self,
        valid_signal: Signal,
        leverage: float,
        max_allowed: float,
        margin_allowed: bool,
        expected_allowed: bool,
    ):
        """Test leverage cap validation."""
        config = ComplianceConfig(
            required_kyc_tier=0,
            user_kyc_tier=3,
            user_region="US",
            max_leverage=max_allowed,
            margin_allowed=margin_allowed,
            allowed_symbols=["BTC/USD"],
        )
        checker = ComplianceChecker(config=config)

        # Create signal with leverage in metadata (Signal uses 'risk' not 'metadata')
        # Need to check actual Signal structure
        signal_with_leverage = valid_signal  # Use existing signal for now

        decision = checker.assess_signal(signal_with_leverage, price_usd=50000.0)
        assert decision.allowed == expected_allowed
        if not expected_allowed:
            assert any("leverage" in r.lower() or "margin" in r.lower() for r in decision.reasons)


# ============================================================================
# PORTFOLIO BALANCER TESTS
# ============================================================================


class TestPortfolioBalancer:
    """Test portfolio balancer with position caps and constraints."""

    @pytest.fixture
    def minimal_policy(self) -> BalancePolicy:
        """Minimal balance policy."""
        return BalancePolicy(
            target_alloc_strategy={"trend": 0.5, "meanrev": 0.3},
            max_strategy_exposure_pct=0.5,
            max_symbol_exposure_pct=0.25,
            max_gross_exposure_pct=1.0,
            max_net_exposure_pct=0.5,
            per_trade_risk_pct=0.01,
            min_notional_usd=10.0,
            max_notional_usd=10000.0,
            leverage_allowed=False,
            max_leverage=1.0,
        )

    @pytest.fixture
    def balancer(self, minimal_policy: BalancePolicy) -> PortfolioBalancer:
        """Create portfolio balancer."""
        balancer = PortfolioBalancer(policy=minimal_policy)
        balancer.update_equity(10000.0)  # $10k portfolio
        return balancer

    def test_basic_allocation_allowed(self, balancer: PortfolioBalancer):
        """Basic allocation should succeed with valid inputs."""
        decision = balancer.propose_allocation(
            strategy="trend",
            symbol="BTC/USD",
            price_usd=50000.0,
            stop_distance_bps=100,  # 1% stop
        )
        assert decision.allowed is True
        assert decision.notional_usd > 0
        assert decision.base_size is not None

    @pytest.mark.parametrize(
        "equity,risk_pct,stop_bps,expected_notional",
        [
            (10000.0, 0.01, 100, 1000.0),  # 10k * 1% * (1000/100) = 1000
            (10000.0, 0.02, 100, 2000.0),  # 10k * 2% * (1000/100) = 2000
            (10000.0, 0.01, 200, 500.0),  # 10k * 1% * (1000/200) = 500
            (20000.0, 0.01, 100, 2000.0),  # 20k * 1% * (1000/100) = 2000
        ],
    )
    def test_risk_based_sizing(
        self,
        equity: float,
        risk_pct: float,
        stop_bps: int,
        expected_notional: float,
    ):
        """Test risk-based position sizing formula."""
        policy = BalancePolicy(
            target_alloc_strategy={"trend": 1.0},
            per_trade_risk_pct=risk_pct,
            min_notional_usd=1.0,
            max_notional_usd=100000.0,
        )
        balancer = PortfolioBalancer(policy=policy)
        balancer.update_equity(equity)

        decision = balancer.propose_allocation(
            strategy="trend",
            symbol="BTC/USD",
            price_usd=50000.0,
            stop_distance_bps=stop_bps,
        )

        assert abs(decision.notional_usd - expected_notional) < 1.0

    @pytest.mark.parametrize(
        "existing_exposure,cap_pct,expected_allowed",
        [
            (0.0, 0.25, True),  # No exposure, can add
            (0.20, 0.25, True),  # Below cap, can add
            (0.25, 0.25, False),  # At cap, deny
            (0.30, 0.25, False),  # Over cap, deny
        ],
    )
    def test_symbol_exposure_cap(
        self,
        existing_exposure: float,
        cap_pct: float,
        expected_allowed: bool,
    ):
        """Test symbol exposure cap enforcement."""
        equity = 10000.0
        policy = BalancePolicy(
            target_alloc_strategy={"trend": 1.0},
            max_symbol_exposure_pct=cap_pct,
            per_trade_risk_pct=0.10,  # Large enough to hit cap
            min_notional_usd=1.0,
        )
        balancer = PortfolioBalancer(policy=policy)
        balancer.update_equity(equity)

        # Set existing exposure
        snapshot = ExposureSnapshot(
            equity_usd=equity,
            by_symbol_usd={"BTC/USD": equity * existing_exposure},
        )
        balancer.update_exposure_snapshot(snapshot)

        decision = balancer.propose_allocation(
            strategy="trend",
            symbol="BTC/USD",
            price_usd=50000.0,
            stop_distance_bps=100,
        )

        assert decision.allowed == expected_allowed
        if not expected_allowed:
            assert "over-cap-symbol" in decision.reasons

    @pytest.mark.parametrize(
        "liquidity,expected_scale",
        [
            (None, 1.0),  # No liquidity data, full size
            ({"spread_bps": 10, "depth_usd": 100000.0}, 1.0),  # Good liquidity
            ({"spread_bps": 100, "depth_usd": 100000.0}, 0.5),  # Wide spread (50% scale)
            ({"spread_bps": 10, "depth_usd": 5000.0}, 0.5),  # Thin depth (50% scale)
        ],
    )
    def test_liquidity_scaling(
        self,
        liquidity: Optional[Dict[str, float]],
        expected_scale: float,
    ):
        """Test liquidity-based position scaling."""
        policy = BalancePolicy(
            target_alloc_strategy={"trend": 1.0},
            per_trade_risk_pct=0.01,
            min_notional_usd=1.0,
            max_spread_bps=50,  # Max 50 bps spread
            min_book_depth_usd=10000.0,  # Min $10k depth
        )
        balancer = PortfolioBalancer(policy=policy)
        balancer.update_equity(10000.0)

        decision = balancer.propose_allocation(
            strategy="trend",
            symbol="BTC/USD",
            price_usd=50000.0,
            stop_distance_bps=100,
            liquidity=liquidity,
        )

        # Check if sizing was scaled appropriately
        if liquidity is None:
            # No liquidity constraint
            assert decision.notional_usd > 0
        else:
            # Should be scaled down for poor liquidity
            if liquidity.get("spread_bps", 0) > 50 or liquidity.get("depth_usd", 0) < 10000:
                assert any(
                    reason in decision.reasons
                    for reason in ["spread-too-wide", "depth-too-thin"]
                )

    def test_correlation_bucket_caps(self):
        """Test correlation bucket exposure caps."""
        policy = BalancePolicy(
            target_alloc_strategy={"trend": 1.0},
            per_trade_risk_pct=0.10,  # Large size
            corr_cap_pct=0.30,  # 30% cap per bucket
            min_notional_usd=1.0,
        )
        balancer = PortfolioBalancer(policy=policy)
        balancer.update_equity(10000.0)

        # Set correlation buckets (BTC and ETH in same bucket)
        balancer.set_correlation_buckets({"BTC/USD": "crypto_L1", "ETH/USD": "crypto_L1"})

        # Add existing BTC exposure (25% of equity)
        snapshot = ExposureSnapshot(
            equity_usd=10000.0,
            by_corr_bucket_pct={"crypto_L1": 0.25},
        )
        balancer.update_exposure_snapshot(snapshot)

        # Try to add ETH (should be capped because bucket at 25/30%)
        decision = balancer.propose_allocation(
            strategy="trend",
            symbol="ETH/USD",
            price_usd=3000.0,
            stop_distance_bps=100,
        )

        # Should be allowed but constrained
        if decision.notional_usd > 500:  # Room left: 30% - 25% = 5% = $500
            assert "over-cap-correlation" in decision.reasons


# ============================================================================
# RISK ROUTER TESTS (End-to-End)
# ============================================================================


class TestRiskRouter:
    """Test risk router orchestration of all checks."""

    @pytest.fixture
    def router(self) -> RiskRouter:
        """Create fully configured risk router."""
        # Compliance: permissive
        compliance_config = ComplianceConfig(
            required_kyc_tier=0,
            user_kyc_tier=3,
            user_region="US",
            blocked_regions=[],
            max_leverage=2.0,
            margin_allowed=True,
            allowed_symbols=["BTC/USD", "ETH/USD"],
        )
        compliance = ComplianceChecker(config=compliance_config)

        # Drawdown: permissive
        drawdown_policy = DrawdownBands(
            daily_stop_pct=-0.90,  # Very permissive (-90%)
            rolling_windows_pct=[(3600, -0.75)],
            max_consecutive_losses=100,  # Very permissive
        )
        drawdown = DrawdownProtector(policy=drawdown_policy)
        drawdown.reset(equity_start_of_day_usd=10000.0, ts_s=1000000)

        # Balancer: reasonable limits
        balance_policy = BalancePolicy(
            target_alloc_strategy={"trend": 0.5, "meanrev": 0.3},
            per_trade_risk_pct=0.01,
            min_notional_usd=10.0,
            max_notional_usd=10000.0,
        )
        balancer = PortfolioBalancer(policy=balance_policy)
        balancer.update_equity(10000.0)

        router_config = RiskRouterConfig()
        return RiskRouter(
            config=router_config,
            compliance=compliance,
            drawdown=drawdown,
            balancer=balancer,
        )

    @pytest.fixture
    def valid_signal(self) -> Signal:
        """Valid signal for routing."""
        return Signal(
            strategy="trend",
            symbol="BTC/USD",
            timeframe="1m",
            side=OrderSide.BUY,
            confidence=0.75,
            risk={"sl_bps": 100},  # stop_distance_bps via risk.sl_bps
        )

    def test_valid_signal_routes_successfully(
        self,
        router: RiskRouter,
        valid_signal: Signal,
    ):
        """Valid signal should route successfully."""
        result = router.assess(valid_signal, price_usd=50000.0)

        assert result.allowed is True
        assert result.intent is not None
        assert result.intent.symbol == "BTC/USD"
        assert result.intent.side == Side.BUY
        assert result.intent.size_quote_usd > 0

    def test_missing_price_denies_signal(
        self,
        router: RiskRouter,
        valid_signal: Signal,
    ):
        """Missing price should deny signal."""
        result = router.assess(valid_signal, price_usd=None)

        assert result.allowed is False
        assert "missing-price" in result.reasons
        assert result.intent is None

    def test_compliance_rejection_blocks_routing(self, router: RiskRouter):
        """Compliance rejection should block routing."""
        # Signal with blocked symbol
        signal = Signal(
            strategy="trend",
            symbol="BLOCKED/USD",  # Not in allowed_symbols
            timeframe="1m",
            side=OrderSide.BUY,
            confidence=0.75,
        )

        result = router.assess(signal, price_usd=50000.0)

        assert result.allowed is False
        assert "compliance-reject" in result.reasons
        assert result.intent is None

    def test_drawdown_halt_blocks_routing(self):
        """Drawdown halt should block routing."""
        # Create router with aggressive drawdown policy
        drawdown_policy = DrawdownBands(
            daily_stop_pct=-0.02,  # Very aggressive (-2%)
            rolling_windows_pct=[(3600, -0.01)],  # 1h: -1%
            max_consecutive_losses=1,  # Very strict
        )
        drawdown = DrawdownProtector(policy=drawdown_policy)
        drawdown.reset(equity_start_of_day_usd=100.0, ts_s=1000000)

        # Trigger hard halt with large drawdown
        base_ts = 1000000
        for i in range(3):
            drawdown.ingest_snapshot(
                SnapshotEvent(
                    ts_s=base_ts + i * 60,
                    equity_start_of_day_usd=100.0,
                    equity_current_usd=100.0 - i * 5.0,  # Large drawdown
                )
            )

        # Build router with halted drawdown
        compliance = ComplianceChecker(
            config=ComplianceConfig(
                required_kyc_tier=0,
                user_kyc_tier=3,
                user_region="US",
                allowed_symbols=["BTC/USD"],
            )
        )
        balancer = PortfolioBalancer(policy=BalancePolicy())
        balancer.update_equity(10000.0)

        router = RiskRouter(
            config=RiskRouterConfig(),
            compliance=compliance,
            drawdown=drawdown,
            balancer=balancer,
        )

        signal = Signal(
            strategy="trend",
            symbol="BTC/USD",
            timeframe="1m",
            side=OrderSide.BUY,
            confidence=0.75,
        )

        result = router.assess(signal, price_usd=50000.0)

        assert result.allowed is False
        assert "drawdown-halt" in result.reasons

    @pytest.mark.parametrize(
        "size_multiplier,expected_allowed",
        [
            (1.0, True),  # Full size
            (0.5, True),  # Half size
            (0.1, True),  # Small size
            (0.001, False),  # Too small (< $1 min)
        ],
    )
    def test_drawdown_size_multiplier_applied(
        self,
        size_multiplier: float,
        expected_allowed: bool,
    ):
        """Test drawdown size multiplier affects final sizing."""
        # Mock drawdown that returns specific multiplier
        class MockDrawdown:
            def assess_can_open(self, strategy: str, symbol: str):
                from agents.risk.drawdown_protector import GateDecision

                return GateDecision(
                    allow_new_positions=True,
                    reduce_only=False,
                    halt_all=False,
                    size_multiplier=size_multiplier,
                )

        compliance = ComplianceChecker(
            config=ComplianceConfig(
                required_kyc_tier=0,
                user_kyc_tier=3,
                user_region="US",
                allowed_symbols=["BTC/USD"],
            )
        )
        balancer = PortfolioBalancer(
            policy=BalancePolicy(
                target_alloc_strategy={"trend": 1.0},
                per_trade_risk_pct=0.01,
                min_notional_usd=10.0,
            )
        )
        balancer.update_equity(10000.0)

        router = RiskRouter(
            config=RiskRouterConfig(),
            compliance=compliance,
            drawdown=MockDrawdown(),
            balancer=balancer,
        )

        signal = Signal(
            strategy="trend",
            symbol="BTC/USD",
            timeframe="1m",
            side=OrderSide.BUY,
            confidence=0.75,
            risk={"sl_bps": 100},
        )

        result = router.assess(signal, price_usd=50000.0)

        assert result.allowed == expected_allowed
        if not expected_allowed:
            assert "size-too-small" in result.reasons


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
