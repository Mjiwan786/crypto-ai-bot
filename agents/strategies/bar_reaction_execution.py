"""
Bar Reaction 5M Execution Agent

Implements maker-only execution policy for bar_reaction_5m strategy with:
- F1: Maker-only default with post_only=True
- F2: Pre-execution guards (spread, notional checks)
- F3: Queue timeout and cancellation logic

Features:
- Place limit at close ± 0.5*spread to stay maker
- Queue for max_queue_s (10s live, next bar in backtest)
- Cancel if no touch within timeout
- Record execution metadata (spread_bps_at_entry, notional_5m, queue_seconds)
- Fresh spread/notional re-checks before placement
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)


def as_decimal(x: float | str | Decimal) -> Decimal:
    """Convert to Decimal for precise calculations."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


@dataclass
class ExecutionGuards:
    """Pre-execution guard check results."""
    passed: bool
    spread_bps: float
    rolling_notional_usd: float
    fresh_close: float
    rejection_reason: Optional[str] = None


@dataclass
class ExecutionRecord:
    """Detailed execution record with metadata."""
    order_id: str
    signal_id: str
    pair: str
    side: str  # 'buy' or 'sell'
    entry_price: Decimal
    quantity: Decimal
    sl: Decimal
    tp: Decimal

    # Execution metadata
    maker: bool
    spread_bps_at_entry: float
    notional_5m: float  # Rolling 5m notional volume
    queue_seconds: float  # Time spent queued

    # Timestamps
    submitted_at: int  # milliseconds
    filled_at: Optional[int] = None  # milliseconds
    cancelled_at: Optional[int] = None  # milliseconds

    # Status
    status: str = "queued"  # queued, filled, cancelled, rejected
    fill_price: Optional[Decimal] = None
    fee: Decimal = Decimal("0")

    # Strategy context
    strategy: str = "bar_reaction_5m"
    mode: str = "trend"  # trend or revert
    confidence: float = 0.0


@dataclass
class BarReactionExecutionConfig:
    """Configuration for bar reaction execution policy."""

    # F1: Maker-only defaults
    maker_only: bool = True
    post_only: bool = True

    # Queue timeout
    max_queue_s: int = 10  # 10s for live, override for backtest

    # F2: Guard thresholds
    spread_bps_cap: float = 8.0  # Skip if spread > 8 bps
    min_rolling_notional_usd: float = 100_000.0  # Skip if notional < $100k

    # Spread improvement for maker placement
    spread_improvement_factor: float = 0.5  # 0.5 = place at mid-spread

    # Redis keys
    redis_prefix: str = "bar_reaction_exec"

    # Backtest mode
    backtest_mode: bool = False


class BarReactionExecutionAgent:
    """
    Execution agent for bar_reaction_5m strategy.

    Implements maker-only policy with pre-execution guards and queue management.
    """

    def __init__(
        self,
        config: BarReactionExecutionConfig,
        redis_client: redis.Redis,
    ):
        """
        Initialize execution agent.

        Args:
            config: Execution configuration
            redis_client: Async Redis client
        """
        self.config = config
        self.redis = redis_client

        # Execution tracking
        self.active_orders: Dict[str, ExecutionRecord] = {}
        self.execution_stats = {
            "total_submissions": 0,
            "maker_fills": 0,
            "taker_fills": 0,  # Should be 0 in maker_only mode
            "cancellations": 0,
            "spread_rejections": 0,
            "notional_rejections": 0,
            "avg_queue_seconds": 0.0,
            "total_rebate_earned_usd": 0.0,
        }

        logger.info(
            f"BarReactionExecutionAgent initialized [maker_only={config.maker_only}, "
            f"max_queue_s={config.max_queue_s}, spread_cap={config.spread_bps_cap}bps, "
            f"notional_floor=${config.min_rolling_notional_usd:,.0f}]"
        )

    async def execute_signal(
        self,
        signal: Dict[str, Any],
        bar_data: Dict[str, Any],
    ) -> Optional[ExecutionRecord]:
        """
        Execute bar reaction signal with maker-only policy.

        Args:
            signal: Signal dictionary from BarReaction5M
            bar_data: Current bar data (close, volume, etc.)

        Returns:
            ExecutionRecord if order placed, None if rejected
        """
        self.execution_stats["total_submissions"] += 1

        # F2: Pre-execution guards
        guards = await self._check_execution_guards(
            pair=signal["pair"],
            bar_data=bar_data,
        )

        if not guards.passed:
            logger.debug(
                f"Execution guards failed for {signal['pair']}: {guards.rejection_reason}"
            )
            if "spread" in guards.rejection_reason.lower():
                self.execution_stats["spread_rejections"] += 1
            elif "notional" in guards.rejection_reason.lower():
                self.execution_stats["notional_rejections"] += 1
            return None

        # F1: Enforce maker-only policy
        if self.config.maker_only:
            # Reject market orders in maker-only mode
            if signal.get("order_type") == "market":
                logger.warning(
                    f"Rejected market order for {signal['pair']}: maker_only=True"
                )
                return None

        # Calculate maker-friendly entry price
        entry_price = self._calculate_maker_price(
            side=signal["side"],
            close=guards.fresh_close,
            spread_bps=guards.spread_bps,
        )

        # Create execution record
        order_id = self._generate_order_id(signal)
        record = ExecutionRecord(
            order_id=order_id,
            signal_id=signal.get("id", "unknown"),
            pair=signal["pair"],
            side=signal["side"],
            entry_price=entry_price,
            quantity=self._calculate_quantity(signal, entry_price),
            sl=as_decimal(signal["sl"]),
            tp=as_decimal(signal["tp"]),
            maker=True,  # Always maker in maker_only mode
            spread_bps_at_entry=guards.spread_bps,
            notional_5m=guards.rolling_notional_usd,
            queue_seconds=0.0,
            submitted_at=int(time.time() * 1000),
            strategy="bar_reaction_5m",
            mode=signal.get("mode", "trend"),
            confidence=signal.get("confidence", 0.0),
        )

        # Store active order
        self.active_orders[order_id] = record

        # Persist to Redis
        await self._persist_order(record)

        logger.info(
            f"Submitted maker order {order_id[:8]} for {signal['pair']} "
            f"{signal['side']} @ {float(entry_price):.2f} "
            f"[spread={guards.spread_bps:.1f}bps, notional=${guards.rolling_notional_usd:,.0f}]"
        )

        # Queue with timeout (F1)
        if not self.config.backtest_mode:
            # Live mode: queue for max_queue_s
            asyncio.create_task(self._queue_with_timeout(order_id))

        return record

    async def _check_execution_guards(
        self,
        pair: str,
        bar_data: Dict[str, Any],
    ) -> ExecutionGuards:
        """
        F2: Check pre-execution guards.

        Re-checks spread and notional with fresh snapshot.

        Args:
            pair: Trading pair
            bar_data: Bar data with close, volume, etc.

        Returns:
            ExecutionGuards with pass/fail and fresh metrics
        """
        # Fetch fresh market data
        fresh_close = float(bar_data.get("close", 0))
        spread_bps = float(bar_data.get("spread_bps", 0))
        rolling_notional = float(bar_data.get("rolling_notional_usd", 0))

        # Check spread cap
        if spread_bps > self.config.spread_bps_cap:
            return ExecutionGuards(
                passed=False,
                spread_bps=spread_bps,
                rolling_notional_usd=rolling_notional,
                fresh_close=fresh_close,
                rejection_reason=f"Spread {spread_bps:.1f}bps > cap {self.config.spread_bps_cap}bps",
            )

        # Check notional floor
        if rolling_notional < self.config.min_rolling_notional_usd:
            return ExecutionGuards(
                passed=False,
                spread_bps=spread_bps,
                rolling_notional_usd=rolling_notional,
                fresh_close=fresh_close,
                rejection_reason=f"Notional ${rolling_notional:,.0f} < floor ${self.config.min_rolling_notional_usd:,.0f}",
            )

        # All guards passed
        return ExecutionGuards(
            passed=True,
            spread_bps=spread_bps,
            rolling_notional_usd=rolling_notional,
            fresh_close=fresh_close,
        )

    def _calculate_maker_price(
        self,
        side: str,
        close: float,
        spread_bps: float,
    ) -> Decimal:
        """
        F1: Calculate maker-friendly limit price.

        Place limit at close ± 0.5*spread to stay maker.

        Args:
            side: 'long' or 'short' (or 'buy'/'sell')
            close: Current bar close price
            spread_bps: Current spread in basis points

        Returns:
            Limit price as Decimal
        """
        close_decimal = as_decimal(close)
        spread_decimal = as_decimal(spread_bps) / Decimal("10000")  # bps to decimal

        # Adjust by half-spread to stay inside spread (maker)
        half_spread_adjustment = close_decimal * spread_decimal * as_decimal(
            self.config.spread_improvement_factor
        )

        if side in ("long", "buy"):
            # Buy: place below close to stay maker
            maker_price = close_decimal - half_spread_adjustment
        else:  # side in ("short", "sell")
            # Sell: place above close to stay maker
            maker_price = close_decimal + half_spread_adjustment

        return maker_price

    def _calculate_quantity(
        self,
        signal: Dict[str, Any],
        entry_price: Decimal,
    ) -> Decimal:
        """
        Calculate order quantity from signal.

        Args:
            signal: Signal with size or risk parameters
            entry_price: Entry price

        Returns:
            Quantity in base currency
        """
        # If signal has explicit quantity, use it
        if "quantity" in signal:
            return as_decimal(signal["quantity"])

        # Otherwise calculate from USD size
        size_usd = signal.get("size_usd", signal.get("size_quote_usd", 100.0))
        quantity = as_decimal(size_usd) / entry_price

        return quantity

    def _generate_order_id(self, signal: Dict[str, Any]) -> str:
        """
        Generate deterministic order ID.

        Args:
            signal: Signal dictionary

        Returns:
            Order ID (16-char hex)
        """
        # Use signal ID + timestamp for uniqueness
        signal_id = signal.get("id", "unknown")
        timestamp = int(time.time() * 1000)

        id_string = f"{signal_id}:{timestamp}"
        hash_digest = hashlib.sha256(id_string.encode()).hexdigest()

        return hash_digest[:16]

    async def _persist_order(self, record: ExecutionRecord) -> None:
        """
        Persist order record to Redis.

        Args:
            record: Execution record to persist
        """
        key = f"{self.config.redis_prefix}:order:{record.order_id}"

        order_dict = {
            "order_id": record.order_id,
            "signal_id": record.signal_id,
            "pair": record.pair,
            "side": record.side,
            "entry_price": str(record.entry_price),
            "quantity": str(record.quantity),
            "sl": str(record.sl),
            "tp": str(record.tp),
            "maker": "1" if record.maker else "0",
            "spread_bps_at_entry": str(record.spread_bps_at_entry),
            "notional_5m": str(record.notional_5m),
            "submitted_at": str(record.submitted_at),
            "status": record.status,
            "strategy": record.strategy,
            "mode": record.mode,
            "confidence": str(record.confidence),
        }

        await self.redis.hset(key, mapping=order_dict)
        await self.redis.expire(key, 86400)  # 24h TTL

    async def _queue_with_timeout(self, order_id: str) -> None:
        """
        F1: Queue order with timeout.

        Wait up to max_queue_s for fill. Cancel if no touch.

        Args:
            order_id: Order ID to monitor
        """
        if order_id not in self.active_orders:
            return

        record = self.active_orders[order_id]
        queue_start = time.time()

        # Simulate queueing (in real implementation, poll exchange API)
        await asyncio.sleep(self.config.max_queue_s)

        # Check if order still active (not filled externally)
        if order_id in self.active_orders and record.status == "queued":
            queue_time = time.time() - queue_start

            # Timeout - cancel order
            logger.debug(
                f"Order {order_id[:8]} timeout after {queue_time:.1f}s - cancelling"
            )

            await self.cancel_order(order_id, reason="queue_timeout")

    async def mark_filled(
        self,
        order_id: str,
        fill_price: Decimal,
        fee: Decimal,
        maker: bool = True,
    ) -> None:
        """
        Mark order as filled.

        Args:
            order_id: Order ID
            fill_price: Actual fill price
            fee: Trading fee
            maker: True if maker fill, False if taker
        """
        if order_id not in self.active_orders:
            logger.warning(f"Attempted to fill unknown order {order_id}")
            return

        record = self.active_orders[order_id]

        # Update record
        record.status = "filled"
        record.filled_at = int(time.time() * 1000)
        record.fill_price = fill_price
        record.fee = fee
        record.maker = maker
        record.queue_seconds = (record.filled_at - record.submitted_at) / 1000.0

        # Update stats
        if maker:
            self.execution_stats["maker_fills"] += 1
            # Assume negative fee for maker rebate
            if fee < 0:
                self.execution_stats["total_rebate_earned_usd"] += abs(float(fee))
        else:
            self.execution_stats["taker_fills"] += 1

        # Update avg queue time
        prev_avg = self.execution_stats["avg_queue_seconds"]
        fill_count = self.execution_stats["maker_fills"] + self.execution_stats["taker_fills"]
        self.execution_stats["avg_queue_seconds"] = (
            prev_avg * (fill_count - 1) + record.queue_seconds
        ) / fill_count

        # Persist updated record
        await self._persist_order(record)

        logger.info(
            f"Order {order_id[:8]} filled @ {float(fill_price):.2f} "
            f"[maker={maker}, queue={record.queue_seconds:.1f}s, fee=${float(fee):.4f}]"
        )

        # Remove from active orders
        del self.active_orders[order_id]

    async def cancel_order(self, order_id: str, reason: str = "manual") -> bool:
        """
        Cancel active order.

        Args:
            order_id: Order ID to cancel
            reason: Cancellation reason

        Returns:
            True if cancelled, False if not found
        """
        if order_id not in self.active_orders:
            return False

        record = self.active_orders[order_id]

        # Update record
        record.status = "cancelled"
        record.cancelled_at = int(time.time() * 1000)
        record.queue_seconds = (record.cancelled_at - record.submitted_at) / 1000.0

        # Update stats
        self.execution_stats["cancellations"] += 1

        # Persist updated record
        await self._persist_order(record)

        logger.debug(
            f"Order {order_id[:8]} cancelled after {record.queue_seconds:.1f}s ({reason})"
        )

        # Remove from active orders
        del self.active_orders[order_id]

        return True

    def get_execution_stats(self) -> Dict[str, Any]:
        """
        Get execution statistics.

        Returns:
            Dictionary with execution metrics
        """
        total_outcomes = (
            self.execution_stats["maker_fills"]
            + self.execution_stats["taker_fills"]
            + self.execution_stats["cancellations"]
        )

        fill_rate = (
            (self.execution_stats["maker_fills"] + self.execution_stats["taker_fills"])
            / max(total_outcomes, 1)
        ) * 100

        maker_pct = (
            self.execution_stats["maker_fills"]
            / max(self.execution_stats["maker_fills"] + self.execution_stats["taker_fills"], 1)
        ) * 100

        return {
            "total_submissions": self.execution_stats["total_submissions"],
            "maker_fills": self.execution_stats["maker_fills"],
            "taker_fills": self.execution_stats["taker_fills"],
            "cancellations": self.execution_stats["cancellations"],
            "spread_rejections": self.execution_stats["spread_rejections"],
            "notional_rejections": self.execution_stats["notional_rejections"],
            "fill_rate_pct": round(fill_rate, 1),
            "maker_percentage": round(maker_pct, 1),
            "avg_queue_seconds": round(self.execution_stats["avg_queue_seconds"], 2),
            "total_rebate_earned_usd": round(self.execution_stats["total_rebate_earned_usd"], 4),
            "active_orders": len(self.active_orders),
            "config": {
                "maker_only": self.config.maker_only,
                "post_only": self.config.post_only,
                "max_queue_s": self.config.max_queue_s,
                "spread_bps_cap": self.config.spread_bps_cap,
                "min_rolling_notional_usd": self.config.min_rolling_notional_usd,
            },
        }
