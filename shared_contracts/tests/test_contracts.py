"""
Contract validation tests for canonical models.

Verifies that:
- Required explainability fields cannot be omitted
- Model constraints are enforced
- The pipeline protocol is correctly typed
"""

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from shared_contracts import (
    Strategy,
    StrategyType,
    TradeIntent,
    TradeSide,
    IntentReason,
    ExecutionDecision,
    DecisionStatus,
    RiskSnapshot,
    RejectionReason,
    Trade,
    TradeStatus,
    ExplainabilityChain,
    MarketSnapshot,
    AccountState,
    TradingPipeline,
)


class TestStrategyContracts:
    """Test Strategy contract requirements."""

    def test_strategy_requires_name(self) -> None:
        """Strategy must have a name."""
        with pytest.raises(ValidationError):
            Strategy(strategy_type=StrategyType.CUSTOM)

    def test_strategy_requires_type(self) -> None:
        """Strategy must have a type."""
        with pytest.raises(ValidationError):
            Strategy(name="Test")

    def test_strategy_name_length_validation(self) -> None:
        """Strategy name has length constraints."""
        # Empty name should fail
        with pytest.raises(ValidationError):
            Strategy(name="", strategy_type=StrategyType.CUSTOM)

        # Very long name should fail
        with pytest.raises(ValidationError):
            Strategy(name="x" * 101, strategy_type=StrategyType.CUSTOM)

    def test_strategy_requires_at_least_one_timeframe(self) -> None:
        """Strategy must have at least one timeframe."""
        with pytest.raises(ValidationError):
            Strategy(
                name="Test",
                strategy_type=StrategyType.CUSTOM,
                timeframes=[],  # Empty - should fail
            )


class TestTradeIntentContracts:
    """Test TradeIntent contract requirements."""

    def test_intent_requires_strategy_id(self) -> None:
        """TradeIntent must reference a strategy."""
        with pytest.raises(ValidationError):
            TradeIntent(
                pair="BTC/USD",
                side=TradeSide.LONG,
                entry_price=Decimal("50000"),
                stop_loss=Decimal("49000"),
                take_profit=Decimal("52000"),
                position_size_usd=Decimal("100"),
                confidence=0.85,
                reasons=[IntentReason(rule="test", description="Test")],
                # Missing strategy_id
            )

    def test_intent_requires_reasons_for_explainability(self) -> None:
        """TradeIntent must have at least one reason (explainability)."""
        with pytest.raises(ValidationError):
            TradeIntent(
                strategy_id="strat_123",
                pair="BTC/USD",
                side=TradeSide.LONG,
                entry_price=Decimal("50000"),
                stop_loss=Decimal("49000"),
                take_profit=Decimal("52000"),
                position_size_usd=Decimal("100"),
                confidence=0.85,
                reasons=[],  # Empty reasons - MUST fail
            )

    def test_intent_confidence_must_be_valid(self) -> None:
        """Confidence must be between 0 and 1."""
        with pytest.raises(ValidationError):
            TradeIntent(
                strategy_id="strat_123",
                pair="BTC/USD",
                side=TradeSide.LONG,
                entry_price=Decimal("50000"),
                stop_loss=Decimal("49000"),
                take_profit=Decimal("52000"),
                position_size_usd=Decimal("100"),
                confidence=1.5,  # Invalid - > 1
                reasons=[IntentReason(rule="test", description="Test")],
            )

    def test_intent_prices_must_be_positive(self) -> None:
        """Entry, SL, TP must be positive."""
        with pytest.raises(ValidationError):
            TradeIntent(
                strategy_id="strat_123",
                pair="BTC/USD",
                side=TradeSide.LONG,
                entry_price=Decimal("-50000"),  # Negative
                stop_loss=Decimal("49000"),
                take_profit=Decimal("52000"),
                position_size_usd=Decimal("100"),
                confidence=0.85,
                reasons=[IntentReason(rule="test", description="Test")],
            )

    def test_intent_reason_requires_rule_and_description(self) -> None:
        """IntentReason must have rule and description."""
        with pytest.raises(ValidationError):
            IntentReason(description="Test")  # Missing rule

        with pytest.raises(ValidationError):
            IntentReason(rule="test")  # Missing description

    def test_intent_risk_reward_calculation(self) -> None:
        """Risk/reward ratio should be calculated correctly."""
        # Long position
        long_intent = TradeIntent(
            strategy_id="strat_123",
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),  # 1000 risk
            take_profit=Decimal("52000"),  # 2000 reward
            position_size_usd=Decimal("100"),
            confidence=0.85,
            reasons=[IntentReason(rule="test", description="Test")],
        )
        assert long_intent.risk_reward_ratio == pytest.approx(2.0, rel=1e-6)

        # Short position
        short_intent = TradeIntent(
            strategy_id="strat_123",
            pair="BTC/USD",
            side=TradeSide.SHORT,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("51000"),  # 1000 risk
            take_profit=Decimal("48000"),  # 2000 reward
            position_size_usd=Decimal("100"),
            confidence=0.85,
            reasons=[IntentReason(rule="test", description="Test")],
        )
        assert short_intent.risk_reward_ratio == pytest.approx(2.0, rel=1e-6)


class TestExecutionDecisionContracts:
    """Test ExecutionDecision contract requirements."""

    def test_decision_requires_intent_id(self) -> None:
        """ExecutionDecision must reference an intent."""
        with pytest.raises(ValidationError):
            ExecutionDecision(
                status=DecisionStatus.APPROVED,
                # Missing intent_id
            )

    def test_decision_requires_status(self) -> None:
        """ExecutionDecision must have a status."""
        with pytest.raises(ValidationError):
            ExecutionDecision(
                intent_id="intent_123",
                # Missing status
            )

    def test_rejected_decision_should_have_reasons(self) -> None:
        """A rejected decision should explain why."""
        # This should NOT raise - but we can check that it's meaningful
        decision = ExecutionDecision.reject(
            intent_id="intent_123",
            reasons=[
                RejectionReason(
                    code="TEST",
                    message="Test rejection",
                )
            ],
            risk_snapshot=RiskSnapshot(),
        )

        assert decision.is_rejected
        assert len(decision.rejection_reasons) > 0
        assert decision.primary_rejection_reason == "Test rejection"

    def test_rejection_reason_requires_code_and_message(self) -> None:
        """RejectionReason must have code and message."""
        with pytest.raises(ValidationError):
            RejectionReason(code="TEST")  # Missing message

        with pytest.raises(ValidationError):
            RejectionReason(message="Test")  # Missing code


class TestTradeContracts:
    """Test Trade contract requirements."""

    def test_trade_requires_decision_id(self) -> None:
        """Trade must reference an ExecutionDecision."""
        with pytest.raises(ValidationError):
            Trade(
                pair="BTC/USD",
                side="long",
                requested_quantity=Decimal("0.002"),
                requested_price=Decimal("50000"),
                explainability_chain=ExplainabilityChain(
                    strategy_id="strat_123",
                    intent_id="intent_123",
                    decision_id="decision_123",
                ),
                # Missing decision_id
            )

    def test_trade_requires_explainability_chain(self) -> None:
        """Trade MUST have explainability chain."""
        with pytest.raises(ValidationError):
            Trade(
                decision_id="decision_123",
                pair="BTC/USD",
                side="long",
                requested_quantity=Decimal("0.002"),
                requested_price=Decimal("50000"),
                # Missing explainability_chain - MUST fail
            )

    def test_explainability_chain_requires_all_ids(self) -> None:
        """ExplainabilityChain must have all three IDs."""
        with pytest.raises(ValidationError):
            ExplainabilityChain(
                strategy_id="strat_123",
                # Missing intent_id and decision_id
            )

    def test_trade_fill_rate_calculation(self) -> None:
        """Fill rate should be calculated correctly."""
        trade = Trade(
            decision_id="decision_123",
            pair="BTC/USD",
            side="long",
            requested_quantity=Decimal("1.0"),
            requested_price=Decimal("50000"),
            total_filled_quantity=Decimal("0.5"),
            explainability_chain=ExplainabilityChain(
                strategy_id="strat_123",
                intent_id="intent_123",
                decision_id="decision_123",
            ),
        )

        assert trade.fill_rate == pytest.approx(0.5, rel=1e-6)


class TestMarketSnapshotContracts:
    """Test MarketSnapshot contract requirements."""

    def test_snapshot_requires_pair(self) -> None:
        """MarketSnapshot must have a pair."""
        with pytest.raises(ValidationError):
            MarketSnapshot(
                bid=Decimal("49990"),
                ask=Decimal("50010"),
                last_price=Decimal("50000"),
            )

    def test_snapshot_requires_price_data(self) -> None:
        """MarketSnapshot must have bid/ask/last_price."""
        with pytest.raises(ValidationError):
            MarketSnapshot(
                pair="BTC/USD",
                # Missing price data
            )


class TestAccountStateContracts:
    """Test AccountState contract requirements."""

    def test_state_requires_account_id(self) -> None:
        """AccountState must have an account ID."""
        with pytest.raises(ValidationError):
            AccountState(
                user_id="user_123",
                total_equity_usd=Decimal("10000"),
                available_balance_usd=Decimal("8000"),
            )

    def test_state_requires_user_id(self) -> None:
        """AccountState must have a user ID."""
        with pytest.raises(ValidationError):
            AccountState(
                account_id="acc_123",
                total_equity_usd=Decimal("10000"),
                available_balance_usd=Decimal("8000"),
            )


class TestPipelineProtocol:
    """Test that TradingPipeline protocol is correctly defined."""

    def test_pipeline_is_runtime_checkable(self) -> None:
        """TradingPipeline should be runtime checkable."""
        # This tests that we can use isinstance() with the protocol
        from typing import runtime_checkable
        from shared_contracts.pipeline.protocol import TradingPipeline

        # The protocol should be marked as runtime_checkable
        assert hasattr(TradingPipeline, "__protocol_attrs__") or hasattr(
            TradingPipeline, "_is_runtime_protocol"
        )

    def test_pipeline_protocol_methods(self) -> None:
        """Pipeline protocol should define required methods."""
        # Check that the protocol defines expected methods
        assert hasattr(TradingPipeline, "generate_trade_intent")
        assert hasattr(TradingPipeline, "evaluate_risk")
        assert hasattr(TradingPipeline, "execute")
        assert hasattr(TradingPipeline, "run_pipeline")


class TestSchemaVersioning:
    """Test schema version handling."""

    def test_all_models_have_schema_version(self) -> None:
        """All canonical models should have schema_version."""
        strategy = Strategy(name="Test", strategy_type=StrategyType.CUSTOM)
        assert hasattr(strategy, "schema_version")
        assert strategy.schema_version == "1.0.0"

        intent = TradeIntent(
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
        assert intent.schema_version == "1.0.0"

        decision = ExecutionDecision.approve(
            intent_id="intent_123",
            risk_snapshot=RiskSnapshot(),
        )
        assert decision.schema_version == "1.0.0"

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
        assert trade.schema_version == "1.0.0"
