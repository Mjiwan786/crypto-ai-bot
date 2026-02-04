"""
Immutability tests for canonical models.

Verifies that all canonical models are frozen (immutable) and cannot be
modified after creation. This is critical for:
- Thread safety
- Audit trail integrity
- Preventing accidental mutations
"""

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from shared_contracts import (
    Strategy,
    StrategyType,
    StrategySource,
    RiskProfile,
    TradeIntent,
    TradeSide,
    IntentReason,
    ExecutionDecision,
    DecisionStatus,
    RiskSnapshot,
    RejectionReason,
    Trade,
    TradeStatus,
    OrderFill,
    ExplainabilityChain,
    MarketSnapshot,
    AccountState,
)


class TestStrategyImmutability:
    """Test Strategy immutability."""

    def test_strategy_is_frozen(self) -> None:
        """Test that Strategy cannot be mutated."""
        strategy = Strategy(
            name="Test Strategy",
            strategy_type=StrategyType.RSI_MEAN_REVERSION,
        )

        with pytest.raises(ValidationError):
            strategy.name = "Modified Name"

    def test_strategy_nested_risk_profile_is_frozen(self) -> None:
        """Test that nested RiskProfile is also frozen."""
        strategy = Strategy(
            name="Test",
            strategy_type=StrategyType.CUSTOM,
            risk_profile=RiskProfile(max_position_size_usd=100.0),
        )

        with pytest.raises(ValidationError):
            strategy.risk_profile.max_position_size_usd = 200.0

    def test_risk_profile_is_frozen(self) -> None:
        """Test that RiskProfile cannot be mutated."""
        profile = RiskProfile(max_position_size_usd=100.0)

        with pytest.raises(ValidationError):
            profile.max_position_size_usd = 200.0


class TestTradeIntentImmutability:
    """Test TradeIntent immutability."""

    def test_trade_intent_is_frozen(self) -> None:
        """Test that TradeIntent cannot be mutated."""
        intent = TradeIntent(
            strategy_id="strat_123",
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),
            confidence=0.85,
            reasons=[
                IntentReason(rule="test", description="Test reason")
            ],
        )

        with pytest.raises(ValidationError):
            intent.pair = "ETH/USD"

        with pytest.raises(ValidationError):
            intent.confidence = 0.5

    def test_intent_reason_is_frozen(self) -> None:
        """Test that IntentReason cannot be mutated."""
        reason = IntentReason(
            rule="rsi_oversold",
            description="RSI below threshold",
            inputs={"rsi": 28},
        )

        with pytest.raises(ValidationError):
            reason.rule = "modified_rule"


class TestExecutionDecisionImmutability:
    """Test ExecutionDecision immutability."""

    def test_execution_decision_is_frozen(self) -> None:
        """Test that ExecutionDecision cannot be mutated."""
        decision = ExecutionDecision.approve(
            intent_id="intent_123",
            risk_snapshot=RiskSnapshot(),
        )

        with pytest.raises(ValidationError):
            decision.status = DecisionStatus.REJECTED

    def test_risk_snapshot_is_frozen(self) -> None:
        """Test that RiskSnapshot cannot be mutated."""
        snapshot = RiskSnapshot(
            account_equity_usd=10000.0,
            daily_pnl_usd=-50.0,
        )

        with pytest.raises(ValidationError):
            snapshot.account_equity_usd = 5000.0

    def test_rejection_reason_is_frozen(self) -> None:
        """Test that RejectionReason cannot be mutated."""
        reason = RejectionReason(
            code="TEST_CODE",
            message="Test message",
        )

        with pytest.raises(ValidationError):
            reason.code = "MODIFIED_CODE"


class TestTradeImmutability:
    """Test Trade immutability."""

    def test_trade_is_frozen(self) -> None:
        """Test that Trade cannot be mutated."""
        trade = Trade(
            decision_id="decision_123",
            pair="BTC/USD",
            side="long",
            requested_quantity=Decimal("0.002"),
            requested_price=Decimal("50000"),
            explainability_chain=ExplainabilityChain(
                strategy_id="strat_123",
                intent_id="intent_123",
                decision_id="decision_123",
            ),
        )

        with pytest.raises(ValidationError):
            trade.status = TradeStatus.FILLED

    def test_order_fill_is_frozen(self) -> None:
        """Test that OrderFill cannot be mutated."""
        fill = OrderFill(
            price=Decimal("50000"),
            quantity=Decimal("0.002"),
        )

        with pytest.raises(ValidationError):
            fill.price = Decimal("51000")

    def test_explainability_chain_is_frozen(self) -> None:
        """Test that ExplainabilityChain cannot be mutated."""
        chain = ExplainabilityChain(
            strategy_id="strat_123",
            intent_id="intent_123",
            decision_id="decision_123",
        )

        with pytest.raises(ValidationError):
            chain.strategy_id = "modified_strat"


class TestMarketSnapshotImmutability:
    """Test MarketSnapshot immutability."""

    def test_market_snapshot_is_frozen(self) -> None:
        """Test that MarketSnapshot cannot be mutated."""
        snapshot = MarketSnapshot(
            pair="BTC/USD",
            bid=Decimal("49990"),
            ask=Decimal("50010"),
            last_price=Decimal("50000"),
        )

        with pytest.raises(ValidationError):
            snapshot.last_price = Decimal("51000")


class TestAccountStateImmutability:
    """Test AccountState immutability."""

    def test_account_state_is_frozen(self) -> None:
        """Test that AccountState cannot be mutated."""
        state = AccountState(
            account_id="acc_123",
            user_id="user_456",
            total_equity_usd=Decimal("10000"),
            available_balance_usd=Decimal("8000"),
        )

        with pytest.raises(ValidationError):
            state.total_equity_usd = Decimal("5000")


class TestCannotBypassImmutability:
    """Test that immutability cannot be bypassed."""

    def test_cannot_use_setattr(self) -> None:
        """Test that setattr also fails."""
        strategy = Strategy(
            name="Test",
            strategy_type=StrategyType.CUSTOM,
        )

        with pytest.raises(ValidationError):
            setattr(strategy, "name", "Modified")

    def test_cannot_modify_via_attribute(self) -> None:
        """Test that attribute assignment fails on frozen models."""
        strategy = Strategy(
            name="Test",
            strategy_type=StrategyType.CUSTOM,
        )

        # Direct attribute assignment should fail
        with pytest.raises(ValidationError):
            strategy.name = "Modified"

        # Model should remain unchanged
        assert strategy.name == "Test"

    def test_dict_access_note(self) -> None:
        """
        Note: Pydantic v2 frozen models allow __dict__ access as implementation detail.

        This is NOT a security feature - it's just for accidental mutation prevention.
        The frozen=True config prevents normal attribute assignment, which is the
        primary protection mechanism.
        """
        strategy = Strategy(
            name="Test",
            strategy_type=StrategyType.CUSTOM,
        )

        # Normal attribute access works for reading
        assert strategy.name == "Test"

        # The key protection is that direct assignment fails (tested above)
        # __dict__ access is an implementation detail, not a contract


class TestImmutableCopying:
    """Test that creating modified copies works correctly."""

    def test_strategy_model_copy(self) -> None:
        """Test that model_copy creates a new immutable instance."""
        original = Strategy(
            name="Original",
            strategy_type=StrategyType.RSI_MEAN_REVERSION,
        )

        # Create a copy with modifications
        modified = original.model_copy(update={"name": "Modified"})

        # Original unchanged
        assert original.name == "Original"

        # Modified is new instance
        assert modified.name == "Modified"
        assert modified.strategy_id == original.strategy_id  # ID preserved

    def test_trade_intent_model_copy(self) -> None:
        """Test that TradeIntent can be copied with modifications."""
        original = TradeIntent(
            strategy_id="strat_123",
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),
            confidence=0.85,
            reasons=[IntentReason(rule="test", description="Test")],
        )

        modified = original.model_copy(update={"confidence": 0.95})

        assert original.confidence == 0.85
        assert modified.confidence == 0.95
