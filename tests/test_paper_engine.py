"""
Tests for Paper Trading Engine.

Verifies:
1. Pipeline enforcement: cannot publish Trade without approved ExecutionDecision
2. Rejection visibility: rejected decisions are published with rejection_reasons
3. Kill switch: bot/account/global disables evaluation immediately and emits stop event
4. Determinism: given fixture snapshots, same events emitted in same order
"""

import json
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from shared_contracts import (
    Strategy,
    StrategyType,
    StrategySource,
    RiskProfile,
    MarketSnapshot,
    TradeIntent,
    ExecutionDecision,
    DecisionStatus,
    TradeSide,
    IntentReason,
)

from paper.engine import PaperEngine, PaperEngineConfig, TickResult
from paper.kill_switch import KillSwitchManager, KillSwitchType, KillSwitchState
from paper.state import AccountStateManager
from paper.publisher import DecisionPublisher, StreamNames


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create mock async Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    redis.hset = AsyncMock()
    redis.hdel = AsyncMock()
    redis.xadd = AsyncMock(return_value=b"1234567890-0")
    return redis


@pytest.fixture
def test_strategy() -> Strategy:
    """Create test EMA crossover strategy."""
    return Strategy(
        name="Test EMA Strategy",
        strategy_type=StrategyType.EMA_CROSSOVER,
        source=StrategySource.INDICATOR,
        parameters={
            "fast_ema_period": 12,
            "slow_ema_period": 26,
            "position_size_usd": 100.0,
            "risk_reward_ratio": 2.0,
        },
    )


@pytest.fixture
def engine_config(test_strategy: Strategy) -> PaperEngineConfig:
    """Create test engine config."""
    return PaperEngineConfig(
        bot_id="test-bot-001",
        account_id="test-account-001",
        user_id="test-user-001",
        strategy=test_strategy,
        pair="BTC/USD",
        starting_equity=10000.0,
        max_position_size_usd=500.0,
        max_trades_per_day=10,
        max_daily_loss_pct=5.0,
    )


@pytest.fixture
def market_snapshot() -> MarketSnapshot:
    """Create test market snapshot."""
    return MarketSnapshot(
        pair="BTC/USD",
        bid=Decimal("50000"),
        ask=Decimal("50010"),
        last_price=Decimal("50005"),
        open=Decimal("49900"),
        high=Decimal("50100"),
        low=Decimal("49800"),
        close=Decimal("50005"),
        volume=Decimal("1000"),
        indicators={
            "closes": [50000 + i * 10 for i in range(100)],  # Uptrend
            "highs": [50050 + i * 10 for i in range(100)],
            "lows": [49950 + i * 10 for i in range(100)],
            "volumes": [1000.0] * 100,
        },
        timestamp=datetime.now(timezone.utc),
    )


# ============================================================================
# PIPELINE ENFORCEMENT TESTS
# ============================================================================

class TestPipelineEnforcement:
    """Test that trades cannot happen without approved ExecutionDecision."""

    @pytest.mark.asyncio
    async def test_no_trade_without_intent(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """If strategy returns None, no trade should be attempted."""
        engine = PaperEngine(mock_redis, engine_config)
        await engine.start()

        with patch("paper.engine.evaluate_strategy", return_value=None):
            result = await engine.tick(market_snapshot)

        assert result.skipped is True
        assert result.intent is None
        assert result.decision is None
        assert result.trade is None
        assert result.skip_reason == "No signal generated"

    @pytest.mark.asyncio
    async def test_no_trade_on_rejected_decision(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """If decision is rejected, no trade should be executed."""
        # Set up config with very low position size limit
        engine_config.max_position_size_usd = 10.0  # Will reject 100 USD intent

        engine = PaperEngine(mock_redis, engine_config)
        await engine.start()

        # Create an intent that will be rejected
        mock_intent = TradeIntent(
            strategy_id=engine_config.strategy.strategy_id,
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),  # Exceeds limit of 10
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test signal")],
        )

        with patch("paper.engine.evaluate_strategy", return_value=mock_intent):
            result = await engine.tick(market_snapshot)

        assert result.intent is not None
        assert result.decision is not None
        assert result.decision.is_rejected is True
        assert result.trade is None  # NO TRADE on rejection

    @pytest.mark.asyncio
    async def test_trade_only_on_approved_decision(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """Trade should only happen when decision is approved."""
        engine = PaperEngine(mock_redis, engine_config)
        await engine.start()

        # Create an intent that will be approved
        mock_intent = TradeIntent(
            strategy_id=engine_config.strategy.strategy_id,
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),  # Within limit
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test signal")],
        )

        with patch("paper.engine.evaluate_strategy", return_value=mock_intent):
            result = await engine.tick(market_snapshot)

        assert result.intent is not None
        assert result.decision is not None
        assert result.decision.is_approved is True
        assert result.trade is not None  # Trade on approval


# ============================================================================
# REJECTION VISIBILITY TESTS
# ============================================================================

class TestRejectionVisibility:
    """Test that rejected decisions are published with full rejection_reasons."""

    @pytest.mark.asyncio
    async def test_rejected_decision_has_reasons(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """Rejected decisions must have rejection_reasons populated."""
        engine_config.max_position_size_usd = 10.0  # Force rejection

        engine = PaperEngine(mock_redis, engine_config)
        await engine.start()

        mock_intent = TradeIntent(
            strategy_id=engine_config.strategy.strategy_id,
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test signal")],
        )

        with patch("paper.engine.evaluate_strategy", return_value=mock_intent):
            result = await engine.tick(market_snapshot)

        assert result.decision.is_rejected is True
        assert len(result.decision.rejection_reasons) >= 1
        assert result.decision.rejection_reasons[0].code == "POSITION_SIZE_EXCEEDED"
        assert "exceeds limit" in result.decision.rejection_reasons[0].message.lower()

    @pytest.mark.asyncio
    async def test_rejected_decision_published(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """Rejected decisions must be published to Redis stream."""
        engine_config.max_position_size_usd = 10.0

        engine = PaperEngine(mock_redis, engine_config)
        await engine.start()

        mock_intent = TradeIntent(
            strategy_id=engine_config.strategy.strategy_id,
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test signal")],
        )

        with patch("paper.engine.evaluate_strategy", return_value=mock_intent):
            await engine.tick(market_snapshot)

        # Verify xadd was called (decision published)
        assert mock_redis.xadd.called
        call_args = mock_redis.xadd.call_args
        stream_name = call_args[1]["name"]
        assert "decisions:paper:" in stream_name

    @pytest.mark.asyncio
    async def test_published_decision_contains_rejection_reasons(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """Published decision payload must include rejection_reasons."""
        engine_config.max_position_size_usd = 10.0

        engine = PaperEngine(mock_redis, engine_config)
        await engine.start()

        mock_intent = TradeIntent(
            strategy_id=engine_config.strategy.strategy_id,
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test signal")],
        )

        with patch("paper.engine.evaluate_strategy", return_value=mock_intent):
            await engine.tick(market_snapshot)

        # Get the published payload
        call_args = mock_redis.xadd.call_args
        fields = call_args[1]["fields"]
        payload = json.loads(fields["json"])

        assert payload["decision"]["is_rejected"] is True
        assert len(payload["decision"]["rejection_reasons"]) >= 1
        assert payload["decision"]["rejection_reasons"][0]["code"] == "POSITION_SIZE_EXCEEDED"


# ============================================================================
# KILL SWITCH TESTS
# ============================================================================

class TestKillSwitch:
    """Test that kill switches disable evaluation immediately."""

    @pytest.mark.asyncio
    async def test_bot_kill_switch_blocks_start(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
    ) -> None:
        """Bot kill switch should prevent engine from starting."""
        # Set up kill switch
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "active": True,
            "type": "bot",
            "target_id": engine_config.bot_id,
            "reason": "Manual stop",
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }))

        engine = PaperEngine(mock_redis, engine_config)
        started = await engine.start()

        assert started is False
        assert engine.is_running is False
        assert "kill switch" in engine.stopped_reason.lower()

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_tick(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """Kill switch should block tick processing."""
        engine = PaperEngine(mock_redis, engine_config)

        # Start normally
        await engine.start()
        assert engine.is_running is True

        # Simulate kill switch activation
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "active": True,
            "type": "bot",
            "target_id": engine_config.bot_id,
            "reason": "Emergency stop",
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }))

        result = await engine.tick(market_snapshot)

        assert result.blocked is True
        assert "kill switch" in result.block_reason.lower()
        assert engine.is_running is False

    @pytest.mark.asyncio
    async def test_global_kill_switch_affects_all(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
    ) -> None:
        """Global paper kill switch should affect all engines."""
        # Mock the global kill switch key specifically
        async def mock_get(key):
            if "kill:global:paper" in key:
                return json.dumps({
                    "active": True,
                    "type": "global",
                    "target_id": "paper",
                    "reason": "System maintenance",
                    "activated_at": datetime.now(timezone.utc).isoformat(),
                })
            return None

        mock_redis.get = mock_get

        engine = PaperEngine(mock_redis, engine_config)
        started = await engine.start()

        assert started is False
        assert "global" in engine.stopped_reason.lower()

    @pytest.mark.asyncio
    async def test_kill_switch_emits_stop_event(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """Kill switch should emit bot_stopped event."""
        engine = PaperEngine(mock_redis, engine_config)
        await engine.start()

        # Activate kill switch
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "active": True,
            "type": "bot",
            "target_id": engine_config.bot_id,
            "reason": "Test stop",
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }))

        await engine.tick(market_snapshot)

        # Find the stop event in xadd calls
        stop_event_published = False
        for call in mock_redis.xadd.call_args_list:
            if "events:paper:bus" in str(call):
                fields = call[1]["fields"]
                # Check both bytes and string keys
                json_field = fields.get(b"json") or fields.get("json")
                if json_field:
                    if isinstance(json_field, bytes):
                        json_field = json_field.decode()
                    payload = json.loads(json_field)
                    if payload.get("event_type") == "bot_stopped":
                        stop_event_published = True
                        break

        assert stop_event_published


# ============================================================================
# DETERMINISM TESTS
# ============================================================================

class TestDeterminism:
    """Test that same inputs produce same outputs."""

    @pytest.mark.asyncio
    async def test_same_snapshot_same_result(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """Same market snapshot should produce same result."""
        engine1 = PaperEngine(mock_redis, engine_config)
        engine2 = PaperEngine(mock_redis, engine_config)

        await engine1.start()
        await engine2.start()

        mock_intent = TradeIntent(
            strategy_id=engine_config.strategy.strategy_id,
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test signal")],
        )

        with patch("paper.engine.evaluate_strategy", return_value=mock_intent):
            result1 = await engine1.tick(market_snapshot)
            result2 = await engine2.tick(market_snapshot)

        # Both should have same outcome
        assert result1.decision.is_approved == result2.decision.is_approved

        if result1.trade and result2.trade:
            assert result1.trade.avg_fill_price == result2.trade.avg_fill_price
            assert result1.trade.total_fees == result2.trade.total_fees

    @pytest.mark.asyncio
    async def test_deterministic_slippage(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """Slippage should be deterministic (not random)."""
        engine = PaperEngine(mock_redis, engine_config)
        await engine.start()

        mock_intent = TradeIntent(
            strategy_id=engine_config.strategy.strategy_id,
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test signal")],
        )

        results = []
        for _ in range(3):
            # Reset xadd to avoid state buildup
            mock_redis.xadd = AsyncMock(return_value=b"1234567890-0")

            with patch("paper.engine.evaluate_strategy", return_value=mock_intent):
                result = await engine.tick(market_snapshot)
                if result.trade:
                    results.append(result.trade.avg_fill_price)

        # All fill prices should be identical (deterministic slippage)
        assert len(set(results)) == 1


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for complete paper trading flow."""

    @pytest.mark.asyncio
    async def test_full_approved_trade_flow(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """Test complete flow for an approved trade."""
        engine = PaperEngine(mock_redis, engine_config)
        await engine.start()

        mock_intent = TradeIntent(
            strategy_id=engine_config.strategy.strategy_id,
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),
            confidence=0.8,
            reasons=[IntentReason(rule="ema_crossover", description="Fast EMA crossed above slow EMA")],
            indicator_inputs={"fast_ema": 50100.0, "slow_ema": 50000.0},
        )

        with patch("paper.engine.evaluate_strategy", return_value=mock_intent):
            result = await engine.tick(market_snapshot)

        # Verify complete chain
        assert result.intent is not None
        assert result.decision is not None
        assert result.decision.is_approved is True
        assert result.trade is not None

        # Verify explainability chain
        assert result.trade.explainability_chain.strategy_id != ""
        assert result.trade.explainability_chain.intent_id == result.intent.intent_id
        assert result.trade.explainability_chain.decision_id == result.decision.decision_id

        # Verify published (xadd called for decision and trade)
        assert mock_redis.xadd.call_count >= 2

    @pytest.mark.asyncio
    async def test_decision_stream_naming(
        self,
        mock_redis: AsyncMock,
        engine_config: PaperEngineConfig,
        market_snapshot: MarketSnapshot,
    ) -> None:
        """Verify correct stream naming for decisions."""
        engine = PaperEngine(mock_redis, engine_config)
        await engine.start()

        mock_intent = TradeIntent(
            strategy_id=engine_config.strategy.strategy_id,
            pair="BTC/USD",
            side=TradeSide.LONG,
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("52000"),
            position_size_usd=Decimal("100"),
            confidence=0.8,
            reasons=[IntentReason(rule="test", description="Test")],
        )

        with patch("paper.engine.evaluate_strategy", return_value=mock_intent):
            await engine.tick(market_snapshot)

        # Check stream names
        stream_names = []
        for call in mock_redis.xadd.call_args_list:
            stream_names.append(call[1]["name"])

        assert "decisions:paper:BTC-USD" in stream_names
        assert "trades:paper:BTC-USD" in stream_names


# ============================================================================
# KILL SWITCH MANAGER TESTS
# ============================================================================

class TestKillSwitchManager:
    """Test KillSwitchManager functionality."""

    @pytest.mark.asyncio
    async def test_activate_bot_kill_switch(self, mock_redis: AsyncMock) -> None:
        """Test activating bot-level kill switch."""
        manager = KillSwitchManager(mock_redis)

        result = await manager.activate(
            switch_type=KillSwitchType.BOT,
            target_id="bot-123",
            reason="Manual stop",
            activated_by="admin",
        )

        assert result is True
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert "kill:bot:bot-123" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_check_inactive_kill_switch(self, mock_redis: AsyncMock) -> None:
        """Test checking inactive kill switch."""
        mock_redis.get = AsyncMock(return_value=None)
        manager = KillSwitchManager(mock_redis)

        state = await manager.check(KillSwitchType.BOT, "bot-123")

        assert state.is_active is False

    @pytest.mark.asyncio
    async def test_hierarchy_check(self, mock_redis: AsyncMock) -> None:
        """Test hierarchical kill switch check (bot -> account -> global)."""
        # Only account kill switch is active
        async def mock_get(key):
            if "kill:account:" in key:
                return json.dumps({
                    "active": True,
                    "type": "account",
                    "target_id": "acct-001",
                    "reason": "Account suspended",
                })
            return None

        mock_redis.get = mock_get
        manager = KillSwitchManager(mock_redis)

        is_blocked, reason = await manager.is_trading_blocked(
            bot_id="bot-123",
            account_id="acct-001",
        )

        assert is_blocked is True
        assert "Account" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
