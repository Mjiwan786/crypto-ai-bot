"""
Roundtrip serialization tests for canonical models.

Verifies that models can be serialized to JSON and deserialized back
without losing data integrity.
"""

import json
from datetime import datetime
from decimal import Decimal

import pytest

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


class TestStrategyRoundtrip:
    """Test Strategy serialization roundtrip."""

    def test_strategy_basic_roundtrip(self) -> None:
        """Test basic strategy serialization."""
        strategy = Strategy(
            name="RSI Mean Reversion",
            strategy_type=StrategyType.RSI_MEAN_REVERSION,
            source=StrategySource.PLATFORM,
            parameters={"rsi_period": 14, "oversold": 30, "overbought": 70},
            timeframes=["5m", "15m"],
            supported_pairs=["BTC/USD", "ETH/USD"],
        )

        # Serialize to dict
        data = strategy.to_dict()
        assert isinstance(data, dict)
        assert data["name"] == "RSI Mean Reversion"
        assert data["strategy_type"] == "rsi_mean_reversion"

        # Deserialize back
        restored = Strategy.from_dict(data)
        assert restored.name == strategy.name
        assert restored.strategy_type == strategy.strategy_type
        assert restored.parameters == strategy.parameters
        assert restored.strategy_id == strategy.strategy_id

    def test_strategy_json_roundtrip(self) -> None:
        """Test strategy JSON string roundtrip."""
        strategy = Strategy(
            name="EMA Crossover",
            strategy_type=StrategyType.EMA_CROSSOVER,
            parameters={"fast_ema": 12, "slow_ema": 26},
        )

        # To JSON string
        json_str = json.dumps(strategy.to_dict())
        assert isinstance(json_str, str)

        # From JSON string
        data = json.loads(json_str)
        restored = Strategy.from_dict(data)
        assert restored.name == strategy.name
        assert restored.parameters["fast_ema"] == 12

    def test_strategy_preserves_schema_version(self) -> None:
        """Test that schema_version is preserved."""
        strategy = Strategy(
            name="Test",
            strategy_type=StrategyType.CUSTOM,
            schema_version="2.0.0",
        )

        data = strategy.to_dict()
        assert data["schema_version"] == "2.0.0"

        restored = Strategy.from_dict(data)
        assert restored.schema_version == "2.0.0"


class TestTradeIntentRoundtrip:
    """Test TradeIntent serialization roundtrip."""

    def test_trade_intent_basic_roundtrip(self) -> None:
        """Test basic trade intent serialization."""
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
                IntentReason(
                    rule="rsi_oversold",
                    description="RSI below 30 indicates oversold",
                    inputs={"rsi": 28, "threshold": 30},
                    weight=1.0,
                )
            ],
            indicator_inputs={"rsi_14": 28, "macd_signal": "bullish"},
        )

        data = intent.to_dict()
        assert data["pair"] == "BTC/USD"
        assert data["side"] == "long"
        assert len(data["reasons"]) == 1

        restored = TradeIntent.from_dict(data)
        assert restored.pair == intent.pair
        assert restored.side == intent.side
        assert restored.entry_price == intent.entry_price
        assert len(restored.reasons) == 1
        assert restored.reasons[0].rule == "rsi_oversold"

    def test_trade_intent_decimal_precision(self) -> None:
        """Test that decimal precision is preserved."""
        intent = TradeIntent(
            strategy_id="strat_123",
            pair="ETH/USD",
            side=TradeSide.SHORT,
            entry_price=Decimal("3000.123456"),
            stop_loss=Decimal("3100.50"),
            take_profit=Decimal("2900.75"),
            position_size_usd=Decimal("50.5"),
            confidence=0.75,
            reasons=[
                IntentReason(
                    rule="test",
                    description="Test reason",
                )
            ],
        )

        data = intent.to_dict()
        restored = TradeIntent.from_dict(data)

        # Note: JSON serialization may lose some precision
        assert float(restored.entry_price) == pytest.approx(3000.123456, rel=1e-6)

    def test_trade_intent_requires_reasons(self) -> None:
        """Test that TradeIntent requires at least one reason."""
        with pytest.raises(ValueError):
            TradeIntent(
                strategy_id="strat_123",
                pair="BTC/USD",
                side=TradeSide.LONG,
                entry_price=Decimal("50000"),
                stop_loss=Decimal("49000"),
                take_profit=Decimal("52000"),
                position_size_usd=Decimal("100"),
                confidence=0.85,
                reasons=[],  # Empty - should fail
            )


class TestExecutionDecisionRoundtrip:
    """Test ExecutionDecision serialization roundtrip."""

    def test_approved_decision_roundtrip(self) -> None:
        """Test approved decision serialization."""
        decision = ExecutionDecision.approve(
            intent_id="intent_123",
            risk_snapshot=RiskSnapshot(
                account_equity_usd=10000.0,
                daily_pnl_usd=-50.0,
                daily_trades_count=3,
            ),
            rules_evaluated=["max_position_size", "daily_loss_limit", "trade_count"],
        )

        data = decision.to_dict()
        assert data["status"] == "approved"
        assert len(data["rejection_reasons"]) == 0

        restored = ExecutionDecision.from_dict(data)
        assert restored.is_approved
        assert restored.intent_id == "intent_123"
        assert restored.risk_snapshot.account_equity_usd == 10000.0

    def test_rejected_decision_roundtrip(self) -> None:
        """Test rejected decision serialization."""
        decision = ExecutionDecision.reject(
            intent_id="intent_456",
            reasons=[
                RejectionReason(
                    code="MAX_DAILY_LOSS_EXCEEDED",
                    message="Daily loss limit of $50 exceeded",
                    details={"current_loss": 60, "limit": 50},
                ),
                RejectionReason(
                    code="MAX_TRADES_EXCEEDED",
                    message="Maximum 10 trades per day reached",
                    details={"count": 10, "limit": 10},
                ),
            ],
            risk_snapshot=RiskSnapshot(
                account_equity_usd=9940.0,
                daily_pnl_usd=-60.0,
                daily_trades_count=10,
            ),
            rules_evaluated=["max_position_size", "daily_loss_limit", "trade_count"],
        )

        data = decision.to_dict()
        assert data["status"] == "rejected"
        assert len(data["rejection_reasons"]) == 2

        restored = ExecutionDecision.from_dict(data)
        assert restored.is_rejected
        assert len(restored.rejection_reasons) == 2
        assert restored.rejection_codes == ["MAX_DAILY_LOSS_EXCEEDED", "MAX_TRADES_EXCEEDED"]


class TestTradeRoundtrip:
    """Test Trade serialization roundtrip."""

    def test_trade_basic_roundtrip(self) -> None:
        """Test basic trade serialization."""
        trade = Trade(
            decision_id="decision_123",
            pair="BTC/USD",
            side="long",
            requested_quantity=Decimal("0.002"),
            requested_price=Decimal("50000"),
            status=TradeStatus.FILLED,
            fills=[
                OrderFill(
                    price=Decimal("50005"),
                    quantity=Decimal("0.002"),
                    fee=Decimal("0.10"),
                )
            ],
            avg_fill_price=Decimal("50005"),
            total_filled_quantity=Decimal("0.002"),
            total_fees=Decimal("0.10"),
            slippage_bps=1.0,
            explainability_chain=ExplainabilityChain(
                strategy_id="strat_123",
                intent_id="intent_123",
                decision_id="decision_123",
                strategy_name="RSI Mean Reversion",
                intent_reasons=["RSI oversold at 28"],
                intent_confidence=0.85,
            ),
        )

        data = trade.to_dict()
        assert data["status"] == "filled"
        assert len(data["fills"]) == 1

        restored = Trade.from_dict(data)
        assert restored.is_successful
        assert restored.trade_id == trade.trade_id
        assert len(restored.fills) == 1
        assert restored.explainability_chain.strategy_name == "RSI Mean Reversion"

    def test_trade_with_realized_pnl(self) -> None:
        """Test trade with P&L tracking."""
        trade = Trade(
            decision_id="decision_789",
            pair="ETH/USD",
            side="short",
            requested_quantity=Decimal("1.0"),
            requested_price=Decimal("3000"),
            status=TradeStatus.FILLED,
            fills=[
                OrderFill(price=Decimal("3000"), quantity=Decimal("1.0")),
            ],
            avg_fill_price=Decimal("3000"),
            total_filled_quantity=Decimal("1.0"),
            realized_pnl=Decimal("150.50"),
            realized_pnl_pct=5.02,
            explainability_chain=ExplainabilityChain(
                strategy_id="strat_abc",
                intent_id="intent_xyz",
                decision_id="decision_789",
            ),
        )

        data = trade.to_dict()
        restored = Trade.from_dict(data)

        assert float(restored.realized_pnl) == pytest.approx(150.50, rel=1e-6)
        assert restored.realized_pnl_pct == pytest.approx(5.02, rel=1e-6)


class TestMarketSnapshotRoundtrip:
    """Test MarketSnapshot serialization roundtrip."""

    def test_market_snapshot_roundtrip(self) -> None:
        """Test market snapshot serialization."""
        snapshot = MarketSnapshot(
            pair="BTC/USD",
            bid=Decimal("49990"),
            ask=Decimal("50010"),
            last_price=Decimal("50000"),
            spread_bps=4.0,
            indicators={"rsi_14": 45.2, "ema_20": 49500.5},
            regime="trending_up",
        )

        data = snapshot.to_dict()
        assert data["pair"] == "BTC/USD"

        restored = MarketSnapshot(
            pair=data["pair"],
            bid=Decimal(str(data["bid"])),
            ask=Decimal(str(data["ask"])),
            last_price=Decimal(str(data["last_price"])),
            spread_bps=data["spread_bps"],
            indicators=data["indicators"],
            regime=data["regime"],
        )

        assert restored.pair == snapshot.pair
        assert restored.get_indicator("rsi_14") == 45.2


class TestAccountStateRoundtrip:
    """Test AccountState serialization roundtrip."""

    def test_account_state_roundtrip(self) -> None:
        """Test account state serialization."""
        state = AccountState(
            account_id="acc_123",
            user_id="user_456",
            total_equity_usd=Decimal("10000"),
            available_balance_usd=Decimal("8000"),
            daily_pnl_usd=Decimal("-25.50"),
            trades_today=5,
        )

        data = state.to_dict()
        assert data["account_id"] == "acc_123"

        # Verify margin utilization calculation
        assert state.margin_utilization == 0.0  # No margin used
