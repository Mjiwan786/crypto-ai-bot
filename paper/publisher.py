"""
Decision and Trade Publisher for Paper Trading.

Publishes ALL decisions (approved + rejected) and trades to Redis streams
with full explainability payloads:
- decisions:paper:{PAIR} - All ExecutionDecisions
- trades:paper:{PAIR} - All executed Trades

Also maintains legacy compatibility with signals:paper:{PAIR} stream.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
import json
import logging

from shared_contracts import (
    Strategy,
    TradeIntent,
    ExecutionDecision,
    Trade,
)

logger = logging.getLogger(__name__)


# Stream configuration
STREAM_MAXLEN_DECISIONS = 10000
STREAM_MAXLEN_TRADES = 10000
STREAM_MAXLEN_EVENTS = 5000


@dataclass(frozen=True)
class StreamNames:
    """Redis stream names for paper trading."""

    @staticmethod
    def decision_stream(mode: str, pair: str) -> str:
        """Get decision stream name."""
        normalized = pair.upper().replace("/", "-")
        return f"decisions:{mode}:{normalized}"

    @staticmethod
    def trade_stream(mode: str, pair: str) -> str:
        """Get trade stream name."""
        normalized = pair.upper().replace("/", "-")
        return f"trades:{mode}:{normalized}"

    @staticmethod
    def signal_stream(mode: str, pair: str) -> str:
        """Get legacy signal stream name (for backward compat)."""
        normalized = pair.upper().replace("/", "-")
        return f"signals:{mode}:{normalized}"

    @staticmethod
    def event_stream() -> str:
        """Get event stream name."""
        return "events:paper:bus"


class DecisionPublisher:
    """
    Publishes paper trading decisions and trades to Redis streams.

    All decisions are published with full explainability payload:
    - Strategy context
    - TradeIntent with reasons[], indicator_inputs
    - ExecutionDecision with rejection_reasons[], risk_snapshot
    - Trade with explainability_chain (for approved decisions)

    This is the SINGLE source of truth for paper trading events.
    """

    def __init__(
        self,
        redis_client: Any,
        mode: Literal["paper", "live"] = "paper",
    ):
        """
        Initialize publisher.

        Args:
            redis_client: Async Redis client
            mode: Trading mode (paper/live)
        """
        self.redis = redis_client
        self.mode = mode

    async def publish_decision(
        self,
        strategy: Strategy,
        intent: TradeIntent,
        decision: ExecutionDecision,
        trade: Trade | None = None,
    ) -> str | None:
        """
        Publish a decision with full explainability.

        This is called for EVERY decision (approved AND rejected).

        Args:
            strategy: Strategy that generated the intent
            intent: TradeIntent with reasons and indicator_inputs
            decision: ExecutionDecision (approved or rejected)
            trade: Trade if decision was approved and executed

        Returns:
            Redis entry ID if successful, None otherwise
        """
        stream_name = StreamNames.decision_stream(self.mode, intent.pair)

        # Build canonical payload (full explainability)
        canonical_payload = {
            # Strategy context
            "strategy": {
                "strategy_id": strategy.strategy_id,
                "name": strategy.name,
                "type": strategy.strategy_type.value,
                "source": strategy.source.value,
                "parameters": strategy.parameters,
                "timeframes": strategy.timeframes,
            },
            # Trade intent (REQUIRED: reasons, indicator_inputs)
            "intent": {
                "intent_id": intent.intent_id,
                "strategy_id": intent.strategy_id,
                "pair": intent.pair,
                "side": intent.side.value,
                "entry_price": str(intent.entry_price),
                "stop_loss": str(intent.stop_loss),
                "take_profit": str(intent.take_profit),
                "position_size_usd": str(intent.position_size_usd),
                "confidence": intent.confidence,
                "reasons": [
                    {"rule": r.rule, "description": r.description}
                    for r in intent.reasons
                ],
                "indicator_inputs": intent.indicator_inputs,
                "mode": intent.mode,
                "timestamp": intent.generated_at.isoformat(),
            },
            # Execution decision (REQUIRED: status, rejection_reasons if rejected)
            "decision": {
                "decision_id": decision.decision_id,
                "intent_id": decision.intent_id,
                "status": decision.status.value,
                "is_approved": decision.is_approved,
                "is_rejected": decision.is_rejected,
                "rejection_reasons": [
                    {"code": r.code, "message": r.message, "details": r.details}
                    for r in decision.rejection_reasons
                ] if decision.rejection_reasons else [],
                "risk_snapshot": {
                    "account_equity_usd": decision.risk_snapshot.account_equity_usd,
                    "daily_pnl_usd": decision.risk_snapshot.daily_pnl_usd,
                    "daily_trades_count": decision.risk_snapshot.daily_trades_count,
                    "open_positions_count": decision.risk_snapshot.open_positions_count,
                    "max_position_size_usd": decision.risk_snapshot.max_position_size_usd,
                    "max_daily_loss_usd": decision.risk_snapshot.max_daily_loss_usd,
                    "max_trades_per_day": decision.risk_snapshot.max_trades_per_day,
                    "trading_enabled": decision.risk_snapshot.trading_enabled,
                },
                "rules_evaluated": decision.rules_evaluated,
                "mode": decision.mode,
                "timestamp": decision.decided_at.isoformat(),
            },
            # Trade (only if approved and executed)
            "trade": None,
            # Metadata
            "published_at": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
        }

        # Add trade if present
        if trade is not None:
            canonical_payload["trade"] = {
                "trade_id": trade.trade_id,
                "decision_id": trade.decision_id,
                "pair": trade.pair,
                "side": trade.side,
                "avg_fill_price": str(trade.avg_fill_price),
                "total_filled_quantity": str(trade.total_filled_quantity),
                "total_fees": str(trade.total_fees),
                "slippage_bps": trade.slippage_bps,
                "status": trade.status.value,
                "explainability_chain": {
                    "strategy_id": trade.explainability_chain.strategy_id,
                    "intent_id": trade.explainability_chain.intent_id,
                    "decision_id": trade.explainability_chain.decision_id,
                    "strategy_name": trade.explainability_chain.strategy_name,
                    "intent_reasons": trade.explainability_chain.intent_reasons,
                    "intent_confidence": trade.explainability_chain.intent_confidence,
                    "decision_status": trade.explainability_chain.decision_status,
                },
                "submitted_at": trade.submitted_at.isoformat() if trade.submitted_at else None,
                "completed_at": trade.completed_at.isoformat() if trade.completed_at else None,
            }

        # Build legacy fields for backward compatibility
        legacy_fields = {
            "pair": intent.pair,
            "side": intent.side.value,
            "confidence": str(intent.confidence),
            "entry": str(intent.entry_price),
            "sl": str(intent.stop_loss),
            "tp": str(intent.take_profit),
            "ts": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            "mode": self.mode,
            "strategy_id": strategy.strategy_id,
            "decision_status": decision.status.value,
        }

        # Encode for Redis
        encoded_data = {
            "json": json.dumps(canonical_payload).encode(),
            **{k: str(v).encode() for k, v in legacy_fields.items()},
        }

        try:
            entry_id = await self.redis.xadd(
                name=stream_name,
                fields=encoded_data,
                maxlen=STREAM_MAXLEN_DECISIONS,
                approximate=True,
            )

            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

            status_str = "APPROVED" if decision.is_approved else "REJECTED"
            logger.info(
                f"Published decision to {stream_name} | status={status_str} "
                f"pair={intent.pair} side={intent.side.value}",
                extra={
                    "stream": stream_name,
                    "decision_id": decision.decision_id,
                    "status": decision.status.value,
                    "pair": intent.pair,
                    "entry_id": entry_id_str,
                },
            )

            return entry_id_str

        except Exception as e:
            logger.error(
                f"Failed to publish decision to {stream_name}: {e}",
                extra={
                    "stream": stream_name,
                    "decision_id": decision.decision_id,
                    "error": str(e),
                },
            )
            return None

    async def publish_trade(
        self,
        strategy: Strategy,
        intent: TradeIntent,
        decision: ExecutionDecision,
        trade: Trade,
    ) -> str | None:
        """
        Publish an executed trade to the trades stream.

        This is called ONLY for approved decisions that result in a trade.

        Args:
            strategy: Strategy that generated the intent
            intent: TradeIntent with reasons
            decision: Approved ExecutionDecision
            trade: Executed Trade

        Returns:
            Redis entry ID if successful, None otherwise
        """
        stream_name = StreamNames.trade_stream(self.mode, trade.pair)

        # Build trade payload with full explainability chain
        payload = {
            "trade_id": trade.trade_id,
            "decision_id": trade.decision_id,
            "pair": trade.pair,
            "side": trade.side,
            "avg_fill_price": str(trade.avg_fill_price),
            "total_filled_quantity": str(trade.total_filled_quantity),
            "total_fees": str(trade.total_fees),
            "slippage_bps": trade.slippage_bps,
            "status": trade.status.value,
            "fills": [
                {
                    "price": str(f.price),
                    "quantity": str(f.quantity),
                    "fee": str(f.fee),
                    "fee_currency": f.fee_currency,
                    "filled_at": f.filled_at.isoformat(),
                }
                for f in trade.fills
            ],
            "explainability_chain": {
                "strategy_id": trade.explainability_chain.strategy_id,
                "strategy_name": trade.explainability_chain.strategy_name,
                "intent_id": trade.explainability_chain.intent_id,
                "intent_reasons": trade.explainability_chain.intent_reasons,
                "intent_confidence": trade.explainability_chain.intent_confidence,
                "decision_id": trade.explainability_chain.decision_id,
                "decision_status": trade.explainability_chain.decision_status,
                "risk_snapshot_summary": trade.explainability_chain.risk_snapshot_summary,
            },
            # Include source data for full audit
            "strategy": {
                "strategy_id": strategy.strategy_id,
                "name": strategy.name,
                "type": strategy.strategy_type.value,
            },
            "intent_summary": {
                "entry_price": str(intent.entry_price),
                "stop_loss": str(intent.stop_loss),
                "take_profit": str(intent.take_profit),
                "confidence": intent.confidence,
                "reasons_count": len(intent.reasons),
            },
            "submitted_at": trade.submitted_at.isoformat() if trade.submitted_at else None,
            "completed_at": trade.completed_at.isoformat() if trade.completed_at else None,
            "mode": trade.mode,
            "exchange": trade.exchange,
        }

        # Legacy fields for backward compat
        legacy_fields = {
            "pair": trade.pair,
            "side": trade.side,
            "price": str(trade.avg_fill_price),
            "qty": str(trade.total_filled_quantity),
            "fee": str(trade.total_fees),
            "ts": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            "mode": self.mode,
        }

        encoded_data = {
            "json": json.dumps(payload).encode(),
            **{k: str(v).encode() for k, v in legacy_fields.items()},
        }

        try:
            entry_id = await self.redis.xadd(
                name=stream_name,
                fields=encoded_data,
                maxlen=STREAM_MAXLEN_TRADES,
                approximate=True,
            )

            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

            logger.info(
                f"Published trade to {stream_name} | trade_id={trade.trade_id} "
                f"pair={trade.pair} side={trade.side} price={trade.avg_fill_price}",
                extra={
                    "stream": stream_name,
                    "trade_id": trade.trade_id,
                    "pair": trade.pair,
                    "entry_id": entry_id_str,
                },
            )

            return entry_id_str

        except Exception as e:
            logger.error(
                f"Failed to publish trade to {stream_name}: {e}",
                extra={
                    "stream": stream_name,
                    "trade_id": trade.trade_id,
                    "error": str(e),
                },
            )
            return None

    async def publish_bot_stopped_event(
        self,
        bot_id: str,
        account_id: str,
        reason: str,
        kill_switch_type: str | None = None,
    ) -> str | None:
        """
        Publish a bot_stopped event when a kill switch is triggered.

        Args:
            bot_id: Bot ID that was stopped
            account_id: Account ID
            reason: Reason for stop
            kill_switch_type: Type of kill switch that triggered stop

        Returns:
            Redis entry ID if successful, None otherwise
        """
        stream_name = StreamNames.event_stream()

        payload = {
            "event_type": "bot_stopped",
            "bot_id": bot_id,
            "account_id": account_id,
            "reason": reason,
            "kill_switch_type": kill_switch_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
        }

        try:
            entry_id = await self.redis.xadd(
                name=stream_name,
                fields={"json": json.dumps(payload).encode()},
                maxlen=STREAM_MAXLEN_EVENTS,
                approximate=True,
            )

            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

            logger.warning(
                f"Published bot_stopped event | bot_id={bot_id} reason={reason}",
                extra={
                    "stream": stream_name,
                    "bot_id": bot_id,
                    "account_id": account_id,
                    "reason": reason,
                    "entry_id": entry_id_str,
                },
            )

            return entry_id_str

        except Exception as e:
            logger.error(f"Failed to publish bot_stopped event: {e}")
            return None

    async def publish_skip_event(
        self,
        bot_id: str,
        strategy: Strategy,
        pair: str,
        reason: str,
        timestamp: datetime,
    ) -> str | None:
        """
        Publish a skip event (when strategy returns None for a tick).

        Optional - for debugging "why didn't it fire" questions.

        Args:
            bot_id: Bot ID
            strategy: Strategy that was evaluated
            pair: Trading pair
            reason: Why signal was skipped
            timestamp: Tick timestamp

        Returns:
            Redis entry ID if successful, None otherwise
        """
        # This is optional and can be disabled for performance
        # For now, just log it
        logger.debug(
            f"Strategy returned no signal | bot={bot_id} strategy={strategy.name} "
            f"pair={pair} reason={reason}",
            extra={
                "bot_id": bot_id,
                "strategy_id": strategy.strategy_id,
                "pair": pair,
                "reason": reason,
                "timestamp": timestamp.isoformat(),
            },
        )
        return None
