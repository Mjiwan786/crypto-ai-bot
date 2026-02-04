"""
Paper Trading Engine - Canonical Pipeline Implementation.

Implements the canonical pipeline for paper trading:
    Strategy → TradeIntent → ExecutionDecision → Trade

This engine:
- Evaluates strategies on market snapshots
- Enforces risk before execution (non-bypassable)
- Publishes ALL decisions (approved + rejected) with explainability
- Respects kill switches immediately
- Dynamically refreshes risk limits from Redis (TTL-cached)
- Maintains determinism for backtest parity

Phase 2 Step 2.2: Dynamic risk limits enforcement.
Risk limits are now fetched from Redis with caching, not static from config.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
import logging

from shared_contracts import (
    Strategy,
    TradeIntent,
    ExecutionDecision,
    Trade,
    MarketSnapshot,
    AccountState,
    RejectionReason,
    RiskSnapshot,
    DecisionStatus,
)

from strategies.indicator import evaluate_strategy
from backtest.risk_evaluator import RiskEvaluator, RiskLimits
from backtest.simulator import ExecutionSimulator
from paper.state import AccountStateManager, PositionSnapshot
from paper.publisher import DecisionPublisher
from paper.kill_switch import KillSwitchManager, KillSwitchType
from paper.risk_limits_provider import RiskLimitsProvider
from paper.heartbeat import HeartbeatPublisher, EffectiveRiskLimitsSnapshot

logger = logging.getLogger(__name__)


@dataclass
class PaperEngineConfig:
    """Configuration for paper trading engine."""

    # Identity
    bot_id: str
    account_id: str
    user_id: str

    # Strategy
    strategy: Strategy
    pair: str = "BTC/USD"

    # Account settings
    starting_equity: float = 10000.0

    # Execution settings
    fees_bps: float = 10.0  # 10 bps = 0.1%
    slippage_bps: float = 5.0  # 5 bps = 0.05%

    # Risk limits
    max_position_size_usd: float = 1000.0
    max_trades_per_day: int = 10
    max_daily_loss_pct: float = 5.0

    # Behavior
    exit_on_opposite_signal: bool = True
    publish_skip_events: bool = False  # Optional: publish when no signal


@dataclass
class TickResult:
    """Result of processing a single market tick."""

    intent: TradeIntent | None = None
    decision: ExecutionDecision | None = None
    trade: Trade | None = None
    skipped: bool = False
    skip_reason: str | None = None
    blocked: bool = False
    block_reason: str | None = None


class PaperEngine:
    """
    Paper Trading Engine using canonical pipeline.

    Pipeline enforcement:
    1. Check kill switches (bot, account, global)
    2. Evaluate strategy → TradeIntent or None
    3. If intent: evaluate risk → ExecutionDecision
    4. ALWAYS publish decision (approved OR rejected)
    5. If approved: execute → Trade
    6. Update account state deterministically

    No trade can happen without an approved ExecutionDecision.
    """

    def __init__(
        self,
        redis_client: Any,
        config: PaperEngineConfig,
    ):
        """
        Initialize paper trading engine.

        Args:
            redis_client: Async Redis client
            config: Engine configuration
        """
        self.redis = redis_client
        self.config = config

        # Default risk limits from config (used as floor in dynamic merge)
        self._default_limits = RiskLimits(
            max_position_size_usd=config.max_position_size_usd,
            max_trades_per_day=config.max_trades_per_day,
            max_daily_loss_pct=config.max_daily_loss_pct,
        )

        # Phase 2 Step 2.2: Dynamic risk limits provider
        # Fetches limits from Redis with caching, merges with defaults
        self.risk_limits_provider = RiskLimitsProvider(
            redis_client=redis_client,
            defaults=self._default_limits,
            cache_ttl_seconds=15.0,  # Refresh every 15 seconds
        )

        # Simulator for executing approved trades
        self.simulator = ExecutionSimulator(
            fees_bps=config.fees_bps,
            slippage_bps=config.slippage_bps,
        )

        # State management
        self.state_manager = AccountStateManager(
            redis_client=redis_client,
            account_id=config.account_id,
            user_id=config.user_id,
            initial_equity=config.starting_equity,
        )

        # Publishing
        self.publisher = DecisionPublisher(
            redis_client=redis_client,
            mode="paper",
        )

        # Kill switch
        self.kill_switch_manager = KillSwitchManager(redis_client)

        # Phase 2 Step 2.3: Heartbeat publisher for effective state visibility
        self.heartbeat_publisher = HeartbeatPublisher(
            redis_client=redis_client,
            account_id=config.account_id,
            bot_id=config.bot_id,
        )

        # Runtime state
        self._running = False
        self._stopped_reason: str | None = None
        self._last_effective_limits: EffectiveRiskLimitsSnapshot | None = None
        self._last_limits_source: str = "default"
        self._last_limits_refresh: datetime | None = None

    @property
    def is_running(self) -> bool:
        """Check if engine is running."""
        return self._running

    @property
    def stopped_reason(self) -> str | None:
        """Get reason for stop if stopped."""
        return self._stopped_reason

    async def _publish_heartbeat(
        self,
        trading_enabled: bool = True,
        block_reason: str | None = None,
        last_error: str | None = None,
        kill_switch_global: bool = False,
        kill_switch_account: bool = False,
        kill_switch_bot: bool = False,
        force: bool = False,
    ) -> None:
        """
        Publish engine heartbeat with current effective state.

        Phase 2 Step 2.3: This enables API/UI to show what the engine
        is actually enforcing, not just what was saved.
        """
        await self.heartbeat_publisher.publish(
            trading_enabled=trading_enabled,
            block_reason=block_reason,
            effective_limits=self._last_effective_limits,
            limits_source=self._last_limits_source,
            limits_refresh_ts=self._last_limits_refresh,
            last_error=last_error,
            kill_switch_global=kill_switch_global,
            kill_switch_account=kill_switch_account,
            kill_switch_bot=kill_switch_bot,
            force=force,
        )

    async def start(self) -> bool:
        """
        Start the paper trading engine.

        Checks kill switches before starting.

        Returns:
            True if started successfully, False if blocked
        """
        # Check kill switches
        is_blocked, reason = await self.kill_switch_manager.is_trading_blocked(
            bot_id=self.config.bot_id,
            account_id=self.config.account_id,
        )

        if is_blocked:
            logger.warning(
                f"Cannot start engine: {reason}",
                extra={
                    "bot_id": self.config.bot_id,
                    "account_id": self.config.account_id,
                    "reason": reason,
                },
            )
            self._stopped_reason = reason
            return False

        self._running = True
        self._stopped_reason = None

        logger.info(
            f"Paper engine started | bot={self.config.bot_id} "
            f"strategy={self.config.strategy.name} pair={self.config.pair}",
            extra={
                "bot_id": self.config.bot_id,
                "account_id": self.config.account_id,
                "strategy": self.config.strategy.name,
                "pair": self.config.pair,
            },
        )

        return True

    async def stop(self, reason: str = "Manual stop") -> None:
        """
        Stop the paper trading engine.

        Args:
            reason: Reason for stopping
        """
        self._running = False
        self._stopped_reason = reason

        # Publish stop event
        await self.publisher.publish_bot_stopped_event(
            bot_id=self.config.bot_id,
            account_id=self.config.account_id,
            reason=reason,
        )

        # Phase 2 Step 2.3: Publish final heartbeat showing stopped state
        await self.heartbeat_publisher.publish_stopped(reason)

        logger.info(
            f"Paper engine stopped | bot={self.config.bot_id} reason={reason}",
            extra={
                "bot_id": self.config.bot_id,
                "reason": reason,
            },
        )

    async def tick(self, snapshot: MarketSnapshot) -> TickResult:
        """
        Process a single market tick through the canonical pipeline.

        This is the main entry point for each bar/tick of market data.

        Pipeline:
        1. Check kill switches
        2. Evaluate strategy → TradeIntent
        3. If no intent: return skip result
        4. Evaluate risk → ExecutionDecision
        5. PUBLISH decision (always, approved or rejected)
        6. If approved: execute → Trade
        7. Update account state
        8. PUBLISH trade (if executed)

        Args:
            snapshot: MarketSnapshot for this tick

        Returns:
            TickResult with intent, decision, trade, or skip/block info
        """
        result = TickResult()

        # Step 1: Check kill switches
        is_blocked, block_reason = await self.kill_switch_manager.is_trading_blocked(
            bot_id=self.config.bot_id,
            account_id=self.config.account_id,
        )

        if is_blocked:
            result.blocked = True
            result.block_reason = block_reason

            # Publish heartbeat showing blocked state
            await self._publish_heartbeat(
                trading_enabled=False,
                block_reason=block_reason,
                kill_switch_global=block_reason == "GLOBAL_KILL",
                kill_switch_account=block_reason == "ACCOUNT_KILL",
                kill_switch_bot=block_reason == "BOT_KILL",
            )

            # Stop engine if not already stopped
            if self._running:
                await self.stop(reason=f"Kill switch: {block_reason}")

            logger.warning(
                f"Tick blocked by kill switch: {block_reason}",
                extra={
                    "bot_id": self.config.bot_id,
                    "reason": block_reason,
                },
            )
            return result

        # Step 2: Evaluate strategy
        try:
            intent = evaluate_strategy(self.config.strategy, snapshot)
        except Exception as e:
            logger.error(f"Strategy evaluation failed: {e}")
            result.skipped = True
            result.skip_reason = f"Strategy error: {e}"
            return result

        if intent is None:
            # No signal - strategy didn't fire
            result.skipped = True
            result.skip_reason = "No signal generated"

            if self.config.publish_skip_events:
                await self.publisher.publish_skip_event(
                    bot_id=self.config.bot_id,
                    strategy=self.config.strategy,
                    pair=self.config.pair,
                    reason="No signal conditions met",
                    timestamp=snapshot.timestamp,
                )

            return result

        result.intent = intent

        # Step 3: Load account state for risk evaluation
        account_state = await self.state_manager.load()

        # Step 3.5: Get dynamic risk limits (Phase 2 Step 2.2)
        # Limits are cached with TTL, refreshed from Redis when stale
        effective_limits = await self.risk_limits_provider.get_effective_limits(
            account_id=self.config.account_id,
            bot_id=self.config.bot_id,
        )

        # Check if risk limits fetch failed (fail-safe: block trading)
        if not effective_limits.can_trade:
            # Create rejection with RISK_LIMITS_UNAVAILABLE
            risk_snapshot = RiskSnapshot(
                account_equity_usd=float(account_state.total_equity_usd),
                daily_pnl_usd=float(account_state.daily_pnl_usd),
                daily_trades_count=account_state.trades_today,
                open_positions_count=account_state.open_positions_count,
                open_positions_exposure_usd=float(account_state.open_positions_exposure_usd),
                max_position_size_usd=self._default_limits.max_position_size_usd,
                max_daily_loss_usd=float(account_state.total_equity_usd) * (self._default_limits.max_daily_loss_pct / 100),
                max_trades_per_day=self._default_limits.max_trades_per_day,
                drawdown_pct=account_state.drawdown_pct,
                trading_enabled=False,  # Trading blocked due to controls error
            )

            decision = ExecutionDecision.reject(
                intent_id=intent.intent_id,
                reasons=[
                    RejectionReason(
                        code="RISK_LIMITS_UNAVAILABLE",
                        message=f"Cannot fetch risk limits: {effective_limits.meta.error_class}",
                        details={
                            "error_class": effective_limits.meta.error_class,
                            "error_message": effective_limits.meta.error_message,
                            "enforcement_state": effective_limits.meta.enforcement_state,
                            "action": "trading_blocked",
                        },
                    )
                ],
                risk_snapshot=risk_snapshot,
                rules_evaluated=["risk_limits_fetch"],
                mode="paper",
            )
            result.decision = decision

            logger.warning(
                f"Trade REJECTED: RISK_LIMITS_UNAVAILABLE - {effective_limits.meta.error_class}",
                extra={
                    "bot_id": self.config.bot_id,
                    "account_id": self.config.account_id,
                    "decision_id": decision.decision_id,
                    "error_class": effective_limits.meta.error_class,
                    "error_message": effective_limits.meta.error_message,
                },
            )

            # Still publish the rejected decision for visibility
            await self.publisher.publish_decision(
                strategy=self.config.strategy,
                intent=intent,
                decision=decision,
                trade=None,
            )

            # Publish heartbeat showing error state (Phase 2 Step 2.3)
            await self._publish_heartbeat(
                trading_enabled=False,
                block_reason="REDIS_ERROR",
                last_error=effective_limits.meta.error_message,
                force=True,
            )

            return result

        # Phase 2 Step 2.3: Track effective limits for heartbeat
        self._last_effective_limits = EffectiveRiskLimitsSnapshot(
            max_trades_per_day=effective_limits.limits.max_trades_per_day,
            max_position_size_usd=effective_limits.limits.max_position_size_usd,
            max_daily_loss_pct=effective_limits.limits.max_daily_loss_pct,
        )
        self._last_limits_source = "redis" if effective_limits.meta.source_keys else "default"
        self._last_limits_refresh = effective_limits.meta.fetched_at

        # Log when limits were refreshed from Redis (not cache hit)
        if not effective_limits.meta.cache_hit:
            logger.debug(
                f"Risk limits refreshed from Redis | sources={effective_limits.meta.source_keys}",
                extra={
                    "bot_id": self.config.bot_id,
                    "account_id": self.config.account_id,
                    "limits": {
                        "max_position_size_usd": effective_limits.limits.max_position_size_usd,
                        "max_trades_per_day": effective_limits.limits.max_trades_per_day,
                        "max_daily_loss_pct": effective_limits.limits.max_daily_loss_pct,
                    },
                },
            )

        # Step 4: Evaluate risk with dynamic limits (NON-BYPASSABLE)
        # Create evaluator with current effective limits
        risk_evaluator = RiskEvaluator(limits=effective_limits.limits)
        decision = risk_evaluator.evaluate(intent, account_state)
        result.decision = decision

        # Step 5: ALWAYS publish decision (approved OR rejected)
        # This is the key explainability requirement
        trade = None
        if decision.is_approved:
            # Step 6: Execute trade (only if approved)
            trade = self.simulator.execute(
                intent=intent,
                decision=decision,
                strategy_name=self.config.strategy.name,
                execution_time=snapshot.timestamp,
            )
            result.trade = trade

        # Publish decision with trade if applicable
        await self.publisher.publish_decision(
            strategy=self.config.strategy,
            intent=intent,
            decision=decision,
            trade=trade,
        )

        if decision.is_rejected:
            logger.info(
                f"Trade REJECTED: {decision.rejection_codes}",
                extra={
                    "bot_id": self.config.bot_id,
                    "decision_id": decision.decision_id,
                    "codes": decision.rejection_codes,
                    "primary_reason": decision.primary_rejection_reason,
                },
            )
            return result

        # Step 7: Update account state
        # For now, we record the trade fees as the immediate cost
        # Full P&L tracking would require position management
        if trade is not None:
            await self.state_manager.record_trade(
                pnl=0.0,  # No P&L until position closed
                fees=float(trade.total_fees),
                timestamp=snapshot.timestamp,
            )

            # Step 8: Publish trade
            await self.publisher.publish_trade(
                strategy=self.config.strategy,
                intent=intent,
                decision=decision,
                trade=trade,
            )

            logger.info(
                f"Trade EXECUTED: {trade.trade_id}",
                extra={
                    "bot_id": self.config.bot_id,
                    "trade_id": trade.trade_id,
                    "pair": trade.pair,
                    "side": trade.side,
                    "price": str(trade.avg_fill_price),
                    "qty": str(trade.total_filled_quantity),
                },
            )

        # Phase 2 Step 2.3: Publish heartbeat with current effective state
        # Throttled to every 5 seconds to avoid Redis spam
        await self._publish_heartbeat(trading_enabled=True)

        return result

    async def process_batch(
        self,
        snapshots: list[MarketSnapshot],
    ) -> list[TickResult]:
        """
        Process multiple snapshots in sequence (for backtest mode).

        Args:
            snapshots: List of MarketSnapshots in chronological order

        Returns:
            List of TickResults
        """
        results = []

        for snapshot in snapshots:
            result = await self.tick(snapshot)
            results.append(result)

            # Stop if blocked
            if result.blocked:
                break

        return results


class PaperEngineFactory:
    """Factory for creating paper trading engines."""

    def __init__(self, redis_client: Any):
        """Initialize factory with Redis client."""
        self.redis = redis_client

    def create(
        self,
        bot_id: str,
        account_id: str,
        user_id: str,
        strategy: Strategy,
        pair: str = "BTC/USD",
        **kwargs: Any,
    ) -> PaperEngine:
        """
        Create a new paper trading engine.

        Args:
            bot_id: Unique bot identifier
            account_id: Account identifier
            user_id: User identifier
            strategy: Strategy to run
            pair: Trading pair
            **kwargs: Additional config options

        Returns:
            Configured PaperEngine
        """
        config = PaperEngineConfig(
            bot_id=bot_id,
            account_id=account_id,
            user_id=user_id,
            strategy=strategy,
            pair=pair,
            **kwargs,
        )

        return PaperEngine(
            redis_client=self.redis,
            config=config,
        )
