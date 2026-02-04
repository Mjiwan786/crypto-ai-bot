"""
Tests for canonical backtest runner.

Verifies:
1. Determinism: same inputs produce identical results
2. Parity wiring: backtest uses indicator evaluator registry
3. Explainability: all artifacts have required fields
4. Risk enforcement: limits are respected
5. Fees/slippage: calculations are correct
"""

import json
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from shared_contracts import Strategy, StrategyType, TradeSide

from backtest import (
    BacktestRunner,
    BacktestConfig,
    BacktestResult,
    ExecutionSimulator,
    RiskEvaluator,
    RiskLimits,
)
from backtest.runner import OHLCVBar
from tests.fixtures.ohlcv_fixture import (
    generate_ohlcv_fixture,
    generate_ema_crossover_fixture,
    OHLCV_FIXTURE_300_BARS,
    OHLCV_FIXTURE_EMA_CROSSOVER,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def ema_strategy() -> Strategy:
    """EMA crossover strategy for testing."""
    return Strategy(
        name="Test EMA Crossover",
        strategy_type=StrategyType.EMA_CROSSOVER,
        parameters={
            "fast_ema_period": 12,
            "slow_ema_period": 26,
        },
    )


@pytest.fixture
def backtest_config(ema_strategy: Strategy) -> BacktestConfig:
    """Default backtest configuration."""
    return BacktestConfig(
        strategy=ema_strategy,
        pair="BTC/USD",
        timeframe="5m",
        starting_equity=10000.0,
        fees_bps=10.0,
        slippage_bps=5.0,
        max_position_size_usd=500.0,
        max_trades_per_day=10,
        max_daily_loss_pct=5.0,
    )


# ============================================================================
# DETERMINISM TESTS
# ============================================================================

class TestDeterminism:
    """Test that backtest produces identical results for same inputs."""

    def test_identical_results_multiple_runs(self, backtest_config: BacktestConfig) -> None:
        """Running same backtest twice yields identical results."""
        ohlcv = OHLCV_FIXTURE_EMA_CROSSOVER

        # Run 1
        runner1 = BacktestRunner(backtest_config)
        result1 = runner1.run(ohlcv)

        # Run 2
        runner2 = BacktestRunner(backtest_config)
        result2 = runner2.run(ohlcv)

        # Compare key metrics
        assert result1.summary.num_trades == result2.summary.num_trades
        assert result1.summary.num_rejected == result2.summary.num_rejected
        assert result1.summary.final_equity == result2.summary.final_equity
        assert result1.summary.total_return_pct == result2.summary.total_return_pct

        # Compare equity curve length
        assert len(result1.equity_curve) == len(result2.equity_curve)

        # Compare final equity values
        if result1.equity_curve and result2.equity_curve:
            assert result1.equity_curve[-1].equity == result2.equity_curve[-1].equity

    def test_deterministic_trade_ids(self, backtest_config: BacktestConfig) -> None:
        """Trade IDs should be stable (or use hash-based approach)."""
        ohlcv = OHLCV_FIXTURE_EMA_CROSSOVER

        result1 = BacktestRunner(backtest_config).run(ohlcv)
        result2 = BacktestRunner(backtest_config).run(ohlcv)

        # Trade count should match
        assert len(result1.trades) == len(result2.trades)

        # Key trade attributes should match
        for t1, t2 in zip(result1.trades, result2.trades):
            assert t1.pair == t2.pair
            assert t1.side == t2.side
            assert t1.avg_fill_price == t2.avg_fill_price
            assert t1.total_filled_quantity == t2.total_filled_quantity


# ============================================================================
# PARITY WIRING TESTS
# ============================================================================

class TestParityWiring:
    """Test that backtest uses the indicator evaluator registry."""

    def test_uses_indicator_evaluator(self, backtest_config: BacktestConfig) -> None:
        """Backtest should use strategies.indicator.evaluate_strategy."""
        ohlcv = OHLCV_FIXTURE_EMA_CROSSOVER

        with patch("backtest.runner.evaluate_strategy") as mock_eval:
            # Setup mock to return None (no signals)
            mock_eval.return_value = None

            runner = BacktestRunner(backtest_config)
            runner.run(ohlcv)

            # Verify evaluate_strategy was called
            assert mock_eval.called, "evaluate_strategy should be called by backtest"

            # Check it was called with Strategy and MarketSnapshot
            for call in mock_eval.call_args_list:
                args = call[0]
                assert len(args) == 2
                assert isinstance(args[0], Strategy)
                # MarketSnapshot is the second arg

    def test_processes_intents_through_risk(self, backtest_config: BacktestConfig) -> None:
        """All intents should go through risk evaluation."""
        ohlcv = OHLCV_FIXTURE_EMA_CROSSOVER

        runner = BacktestRunner(backtest_config)
        result = runner.run(ohlcv)

        # Every intent should have a corresponding decision
        assert len(result.decisions) == len(result.intents)

        # Verify intent IDs match
        intent_ids = {i.intent_id for i in result.intents}
        decision_intent_ids = {d.intent_id for d in result.decisions}
        assert intent_ids == decision_intent_ids


# ============================================================================
# EXPLAINABILITY TESTS
# ============================================================================

class TestExplainability:
    """Test that all artifacts have required explainability fields."""

    def test_trade_intents_have_reasons(self, backtest_config: BacktestConfig) -> None:
        """Every TradeIntent must have non-empty reasons."""
        ohlcv = OHLCV_FIXTURE_EMA_CROSSOVER

        result = BacktestRunner(backtest_config).run(ohlcv)

        for intent in result.intents:
            assert len(intent.reasons) >= 1, f"Intent {intent.intent_id} has no reasons"
            assert intent.reasons[0].rule != ""
            assert intent.reasons[0].description != ""

    def test_trade_intents_have_indicator_inputs(self, backtest_config: BacktestConfig) -> None:
        """Every TradeIntent must have indicator_inputs."""
        ohlcv = OHLCV_FIXTURE_EMA_CROSSOVER

        result = BacktestRunner(backtest_config).run(ohlcv)

        for intent in result.intents:
            assert intent.indicator_inputs is not None
            assert len(intent.indicator_inputs) > 0, f"Intent {intent.intent_id} has no indicator_inputs"

    def test_rejected_decisions_have_reasons(self, backtest_config: BacktestConfig) -> None:
        """Rejected ExecutionDecision must have rejection_reasons."""
        # Use config that will cause rejections
        strict_config = BacktestConfig(
            strategy=backtest_config.strategy,
            max_trades_per_day=1,  # Very restrictive
            starting_equity=10000.0,
        )

        ohlcv = OHLCV_FIXTURE_300_BARS

        result = BacktestRunner(strict_config).run(ohlcv)

        rejected = [d for d in result.decisions if d.is_rejected]
        for decision in rejected:
            assert len(decision.rejection_reasons) >= 1, (
                f"Rejected decision {decision.decision_id} has no rejection_reasons"
            )
            assert decision.rejection_reasons[0].code != ""
            assert decision.rejection_reasons[0].message != ""

    def test_trades_have_explainability_chain(self, backtest_config: BacktestConfig) -> None:
        """Every Trade must have complete explainability_chain."""
        ohlcv = OHLCV_FIXTURE_EMA_CROSSOVER

        result = BacktestRunner(backtest_config).run(ohlcv)

        for trade in result.trades:
            chain = trade.explainability_chain
            assert chain.strategy_id != ""
            assert chain.intent_id != ""
            assert chain.decision_id != ""

    def test_explainability_chain_links_match(self, backtest_config: BacktestConfig) -> None:
        """Explainability chain IDs should match actual objects."""
        ohlcv = OHLCV_FIXTURE_EMA_CROSSOVER

        result = BacktestRunner(backtest_config).run(ohlcv)

        for trade in result.trades:
            chain = trade.explainability_chain

            # Find matching decision
            matching_decisions = [d for d in result.decisions if d.decision_id == chain.decision_id]
            assert len(matching_decisions) == 1, f"No matching decision for trade {trade.trade_id}"

            decision = matching_decisions[0]
            assert decision.intent_id == chain.intent_id

            # Find matching intent
            matching_intents = [i for i in result.intents if i.intent_id == chain.intent_id]
            assert len(matching_intents) == 1, f"No matching intent for trade {trade.trade_id}"


# ============================================================================
# RISK ENFORCEMENT TESTS
# ============================================================================

class TestRiskEnforcement:
    """Test that risk limits are enforced."""

    def test_max_trades_per_day_enforced(self) -> None:
        """max_trades_per_day causes deterministic rejections."""
        strategy = Strategy(
            name="Test",
            strategy_type=StrategyType.EMA_CROSSOVER,
        )

        config = BacktestConfig(
            strategy=strategy,
            max_trades_per_day=2,  # Only allow 2 trades per day
            starting_equity=10000.0,
        )

        # Use data that would normally produce many signals
        ohlcv = OHLCV_FIXTURE_300_BARS

        result = BacktestRunner(config).run(ohlcv)

        # Should have exactly 2 trades (max per day)
        # Note: depends on data producing enough signals
        if len(result.intents) > 2:
            # Some should be rejected
            rejected = [d for d in result.decisions if d.is_rejected]
            assert len(rejected) > 0

            # Check rejection reason is MAX_TRADES_EXCEEDED
            trade_limit_rejections = [
                d for d in rejected
                if any(r.code == "MAX_TRADES_EXCEEDED" for r in d.rejection_reasons)
            ]
            assert len(trade_limit_rejections) > 0

    def test_position_size_limit_enforced(self) -> None:
        """Position size exceeding limit is rejected."""
        strategy = Strategy(
            name="Test",
            strategy_type=StrategyType.EMA_CROSSOVER,
            parameters={
                "position_size_usd": 2000.0,  # Request 2000 USD
            },
        )

        config = BacktestConfig(
            strategy=strategy,
            max_position_size_usd=100.0,  # But limit is 100 USD
            starting_equity=10000.0,
        )

        # Test risk evaluator directly
        from shared_contracts import TradeIntent, TradeSide, IntentReason, AccountState

        intent = TradeIntent(
            strategy_id="test",
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("2000"),  # Exceeds limit
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test")],
        )

        account = AccountState(
            account_id="test",
            user_id="test",
            total_equity_usd=Decimal("10000"),
            available_balance_usd=Decimal("10000"),
        )

        evaluator = RiskEvaluator(RiskLimits(max_position_size_usd=100.0))
        decision = evaluator.evaluate(intent, account)

        assert decision.is_rejected
        assert any(r.code == "POSITION_SIZE_EXCEEDED" for r in decision.rejection_reasons)


# ============================================================================
# FEES AND SLIPPAGE TESTS
# ============================================================================

class TestFeesAndSlippage:
    """Test fee and slippage calculations."""

    def test_slippage_applied_correctly(self) -> None:
        """Fill price includes slippage in correct direction."""
        simulator = ExecutionSimulator(fees_bps=0, slippage_bps=10.0)  # 10 bps slippage

        from shared_contracts import (
            TradeIntent, TradeSide, IntentReason,
            ExecutionDecision, RiskSnapshot
        )

        # Long trade
        intent_long = TradeIntent(
            strategy_id="test",
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test")],
        )

        decision = ExecutionDecision.approve(
            intent_id=intent_long.intent_id,
            risk_snapshot=RiskSnapshot(),
        )

        trade_long = simulator.execute(intent_long, decision)

        # Long should buy at higher price (slippage against us)
        expected_fill_long = 50000 * (1 + 10 / 10000)  # 50005
        assert float(trade_long.avg_fill_price) == pytest.approx(expected_fill_long, rel=1e-6)

        # Short trade
        intent_short = TradeIntent(
            strategy_id="test",
            pair="BTC/USD",
            side=TradeSide.SHORT,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("51000"),
            take_profit=Decimal("48000"),
            position_size_usd=Decimal("100"),
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test")],
        )

        trade_short = simulator.execute(intent_short, decision)

        # Short should sell at lower price (slippage against us)
        expected_fill_short = 50000 * (1 - 10 / 10000)  # 49995
        assert float(trade_short.avg_fill_price) == pytest.approx(expected_fill_short, rel=1e-6)

    def test_fees_calculated_correctly(self) -> None:
        """Trading fees are calculated correctly."""
        simulator = ExecutionSimulator(fees_bps=10.0, slippage_bps=0)  # 10 bps = 0.1%

        from shared_contracts import (
            TradeIntent, TradeSide, IntentReason,
            ExecutionDecision, RiskSnapshot
        )

        intent = TradeIntent(
            strategy_id="test",
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("1000"),  # $1000 position
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test")],
        )

        decision = ExecutionDecision.approve(
            intent_id=intent.intent_id,
            risk_snapshot=RiskSnapshot(),
        )

        trade = simulator.execute(intent, decision)

        # Fee should be 1000 * (10/10000) = $1.00
        expected_fee = 1000 * (10 / 10000)
        assert float(trade.total_fees) == pytest.approx(expected_fee, rel=1e-6)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for complete backtest flow."""

    def test_full_backtest_produces_result(self, backtest_config: BacktestConfig) -> None:
        """Full backtest run produces valid result."""
        ohlcv = OHLCV_FIXTURE_300_BARS

        result = BacktestRunner(backtest_config).run(ohlcv)

        # Should have assumptions
        assert result.assumptions.strategy_id != ""
        assert result.assumptions.num_candles == 300

        # Should have equity curve
        assert len(result.equity_curve) > 0

        # Summary should have final equity
        assert result.summary.final_equity > 0

    def test_result_serializable_to_json(self, backtest_config: BacktestConfig) -> None:
        """BacktestResult can be serialized to JSON."""
        ohlcv = OHLCV_FIXTURE_EMA_CROSSOVER

        result = BacktestRunner(backtest_config).run(ohlcv)

        # Should not raise
        json_str = json.dumps(result.to_dict(), default=str)
        assert isinstance(json_str, str)
        assert len(json_str) > 0

        # Should be deserializable
        data = json.loads(json_str)
        assert "summary" in data
        assert "trades" in data
        assert "decisions" in data

    def test_empty_data_handled_gracefully(self, backtest_config: BacktestConfig) -> None:
        """Empty OHLCV data doesn't crash."""
        result = BacktestRunner(backtest_config).run([])

        assert result.summary.num_trades == 0
        assert result.summary.final_equity == backtest_config.starting_equity


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
