"""
Smoke test for shared_contracts package import.

This test verifies that the shared_contracts package can be imported
successfully in the crypto-ai-bot environment.

Run with:
    conda activate crypto-bot
    pip install -e ../shared_contracts
    pytest tests/test_shared_contracts_import.py -v
"""

import pytest


class TestSharedContractsImport:
    """Verify shared_contracts package imports correctly."""

    def test_import_main_package(self) -> None:
        """Can import shared_contracts package."""
        import shared_contracts

        assert shared_contracts.__version__ == "0.1.0"

    def test_import_strategy(self) -> None:
        """Can import Strategy model."""
        from shared_contracts import Strategy, StrategyType, StrategySource, RiskProfile

        assert Strategy is not None
        assert StrategyType.RSI_MEAN_REVERSION is not None

    def test_import_trade_intent(self) -> None:
        """Can import TradeIntent model."""
        from shared_contracts import TradeIntent, TradeSide, IntentReason

        assert TradeIntent is not None
        assert TradeSide.LONG is not None

    def test_import_execution_decision(self) -> None:
        """Can import ExecutionDecision model."""
        from shared_contracts import (
            ExecutionDecision,
            DecisionStatus,
            RiskSnapshot,
            RejectionReason,
        )

        assert ExecutionDecision is not None
        assert DecisionStatus.APPROVED is not None

    def test_import_trade(self) -> None:
        """Can import Trade model."""
        from shared_contracts import Trade, TradeStatus, OrderFill, ExplainabilityChain

        assert Trade is not None
        assert TradeStatus.FILLED is not None

    def test_import_supporting_models(self) -> None:
        """Can import supporting models."""
        from shared_contracts import MarketSnapshot, AccountState

        assert MarketSnapshot is not None
        assert AccountState is not None

    def test_import_pipeline_protocol(self) -> None:
        """Can import TradingPipeline protocol."""
        from shared_contracts import TradingPipeline

        assert TradingPipeline is not None

    def test_create_strategy_instance(self) -> None:
        """Can create a Strategy instance."""
        from shared_contracts import Strategy, StrategyType

        strategy = Strategy(
            name="Test RSI Strategy",
            strategy_type=StrategyType.RSI_MEAN_REVERSION,
            parameters={"rsi_period": 14, "oversold": 30},
        )

        assert strategy.name == "Test RSI Strategy"
        assert strategy.strategy_type == StrategyType.RSI_MEAN_REVERSION
        assert strategy.parameters["rsi_period"] == 14

    def test_create_trade_intent_instance(self) -> None:
        """Can create a TradeIntent instance."""
        from decimal import Decimal

        from shared_contracts import TradeIntent, TradeSide, IntentReason

        intent = TradeIntent(
            strategy_id="strat_test123",
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
                    description="RSI below 30 indicates oversold condition",
                    inputs={"rsi_14": 28},
                )
            ],
        )

        assert intent.pair == "BTC/USD"
        assert intent.side == TradeSide.LONG
        assert len(intent.reasons) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
