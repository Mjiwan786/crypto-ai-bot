#!/usr/bin/env python3
"""
Order State Publisher for Redis Streams

Publishes order states (pending, filled, cancelled) to Redis streams for
monitoring, analytics, and execution tracking.

Features:
- Real-time order state publishing to Redis streams
- Supports all order lifecycle events (created, filled, cancelled, rejected)
- Includes maker/taker classification and spread data
- Compatible with both live and backtest modes
- Graceful degradation if Redis unavailable

Redis Stream Keys:
    - kraken:orders:{symbol} -> order state events
    - kraken:fills:{symbol} -> fill events with maker/taker tags

Usage:
    from agents.infrastructure.order_state_publisher import OrderStatePublisher

    publisher = OrderStatePublisher(redis_client)

    # Publish order created
    publisher.publish_order_created(
        order_id="abc123",
        symbol="BTC/USD",
        side="buy",
        size=0.01,
        price=50000.0,
        order_type="limit",
        post_only=True
    )

    # Publish fill
    publisher.publish_fill(
        order_id="abc123",
        symbol="BTC/USD",
        side="buy",
        size=0.01,
        price=50000.0,
        fee=0.00012,
        maker=True,
        spread_bps_at_entry=0.8
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OrderEvent:
    """Order lifecycle event"""

    order_id: str
    symbol: str
    side: str  # "buy" or "sell"
    size: float
    price: Optional[float]
    order_type: str  # "limit", "market", "post_only", "ioc"
    status: str  # "created", "filled", "partially_filled", "cancelled", "rejected"
    timestamp_ms: int
    metadata: dict


@dataclass
class FillEvent:
    """Fill event with maker/taker classification"""

    order_id: str
    fill_id: str
    symbol: str
    side: str
    size: float
    price: float
    fee: float
    maker: bool
    spread_bps_at_entry: Optional[float]
    timestamp_ms: int
    execution_time_ms: Optional[float]


class OrderStatePublisher:
    """
    Publishes order state changes to Redis streams.

    Enables real-time monitoring and analytics of order execution.
    """

    def __init__(self, redis_client=None):
        """
        Initialize order state publisher.

        Args:
            redis_client: Optional Redis client (if None, operates without Redis)
        """
        self.redis_client = redis_client
        self.published_count = 0
        self.failed_count = 0

        logger.info(
            f"OrderStatePublisher initialized [redis={'connected' if redis_client else 'disabled'}]"
        )

    def publish_order_created(
        self,
        order_id: str,
        symbol: str,
        side: str,
        size: float,
        price: Optional[float],
        order_type: str = "limit",
        post_only: bool = False,
        hidden: bool = False,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Publish order created event.

        Args:
            order_id: Unique order identifier
            symbol: Trading pair
            side: "buy" or "sell"
            size: Order size in base currency
            price: Limit price (None for market orders)
            order_type: Order type
            post_only: Whether order is post-only (maker)
            hidden: Whether order is hidden
            metadata: Additional metadata

        Returns:
            True if published successfully
        """
        event = OrderEvent(
            order_id=order_id,
            symbol=symbol,
            side=side,
            size=size,
            price=price,
            order_type=order_type,
            status="created",
            timestamp_ms=int(time.time() * 1000),
            metadata=metadata or {},
        )

        return self._publish_order_event(event, extra_fields={"post_only": str(post_only), "hidden": str(hidden)})

    def publish_order_filled(
        self,
        order_id: str,
        symbol: str,
        side: str,
        size: float,
        price: float,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Publish order filled event.

        Args:
            order_id: Order identifier
            symbol: Trading pair
            side: "buy" or "sell"
            size: Filled size
            price: Fill price
            metadata: Additional metadata

        Returns:
            True if published successfully
        """
        event = OrderEvent(
            order_id=order_id,
            symbol=symbol,
            side=side,
            size=size,
            price=price,
            order_type="filled",
            status="filled",
            timestamp_ms=int(time.time() * 1000),
            metadata=metadata or {},
        )

        return self._publish_order_event(event)

    def publish_order_cancelled(
        self,
        order_id: str,
        symbol: str,
        reason: str = "user_cancel",
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Publish order cancelled event.

        Args:
            order_id: Order identifier
            symbol: Trading pair
            reason: Cancellation reason
            metadata: Additional metadata

        Returns:
            True if published successfully
        """
        event = OrderEvent(
            order_id=order_id,
            symbol=symbol,
            side="",
            size=0.0,
            price=None,
            order_type="",
            status="cancelled",
            timestamp_ms=int(time.time() * 1000),
            metadata=metadata or {"reason": reason},
        )

        return self._publish_order_event(event, extra_fields={"reason": reason})

    def publish_fill(
        self,
        order_id: str,
        symbol: str,
        side: str,
        size: float,
        price: float,
        fee: float,
        maker: bool = True,
        spread_bps_at_entry: Optional[float] = None,
        execution_time_ms: Optional[float] = None,
        fill_id: Optional[str] = None,
    ) -> bool:
        """
        Publish fill event with maker/taker classification.

        Args:
            order_id: Order identifier
            symbol: Trading pair
            side: "buy" or "sell"
            size: Fill size
            price: Fill price
            fee: Trading fee
            maker: True if maker fill, False if taker
            spread_bps_at_entry: Spread at entry in basis points
            execution_time_ms: Execution time in milliseconds
            fill_id: Optional fill identifier

        Returns:
            True if published successfully
        """
        ts = int(time.time() * 1000)
        fill_id = fill_id or f"fill_{order_id}_{ts}"

        fill_event = FillEvent(
            order_id=order_id,
            fill_id=fill_id,
            symbol=symbol,
            side=side,
            size=size,
            price=price,
            fee=fee,
            maker=maker,
            spread_bps_at_entry=spread_bps_at_entry,
            timestamp_ms=ts,
            execution_time_ms=execution_time_ms,
        )

        return self._publish_fill_event(fill_event)

    def _publish_order_event(self, event: OrderEvent, extra_fields: Optional[dict] = None) -> bool:
        """
        Publish order event to Redis stream.

        Args:
            event: Order event to publish
            extra_fields: Additional fields to include

        Returns:
            True if published successfully
        """
        if not self.redis_client:
            logger.debug(f"Redis disabled, skipping order event: {event.order_id}")
            return False

        try:
            stream_key = f"kraken:orders:{event.symbol}"

            payload = {
                "ts": str(event.timestamp_ms),
                "order_id": event.order_id,
                "symbol": event.symbol,
                "side": event.side,
                "size": str(event.size),
                "order_type": event.order_type,
                "status": event.status,
            }

            if event.price is not None:
                payload["price"] = str(event.price)

            if extra_fields:
                payload.update(extra_fields)

            # Add metadata
            for key, value in event.metadata.items():
                payload[f"meta_{key}"] = str(value)

            self.redis_client.xadd(stream_key, payload, maxlen=10000)
            self.published_count += 1

            logger.debug(
                f"Published order event: {event.order_id} {event.status} "
                f"{event.symbol} {event.side} {event.size}"
            )
            return True

        except Exception as e:
            self.failed_count += 1
            logger.error(f"Failed to publish order event: {e}")
            return False

    def _publish_fill_event(self, fill: FillEvent) -> bool:
        """
        Publish fill event to Redis stream.

        Args:
            fill: Fill event to publish

        Returns:
            True if published successfully
        """
        if not self.redis_client:
            logger.debug(f"Redis disabled, skipping fill event: {fill.fill_id}")
            return False

        try:
            stream_key = f"kraken:fills:{fill.symbol}"

            payload = {
                "ts": str(fill.timestamp_ms),
                "fill_id": fill.fill_id,
                "order_id": fill.order_id,
                "symbol": fill.symbol,
                "side": fill.side,
                "size": str(fill.size),
                "price": str(fill.price),
                "fee": str(fill.fee),
                "maker": str(fill.maker),
            }

            if fill.spread_bps_at_entry is not None:
                payload["spread_bps"] = f"{fill.spread_bps_at_entry:.2f}"

            if fill.execution_time_ms is not None:
                payload["exec_time_ms"] = f"{fill.execution_time_ms:.2f}"

            self.redis_client.xadd(stream_key, payload, maxlen=10000)
            self.published_count += 1

            logger.debug(
                f"Published fill: {fill.fill_id} {fill.symbol} {fill.side} "
                f"{fill.size} @ {fill.price} [maker={fill.maker}]"
            )
            return True

        except Exception as e:
            self.failed_count += 1
            logger.error(f"Failed to publish fill event: {e}")
            return False

    def get_stats(self) -> dict:
        """
        Get publisher statistics.

        Returns:
            Dict with published and failed counts
        """
        return {
            "published_count": self.published_count,
            "failed_count": self.failed_count,
            "success_rate": (
                self.published_count / max(1, self.published_count + self.failed_count)
            ) * 100,
        }


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test order state publisher"""
    import sys

    logging.basicConfig(level=logging.INFO)

    try:
        # Test without Redis
        publisher = OrderStatePublisher()

        # Test order created
        success = publisher.publish_order_created(
            order_id="test_order_123",
            symbol="BTC/USD",
            side="buy",
            size=0.01,
            price=50000.0,
            order_type="limit",
            post_only=True,
        )
        assert not success  # Should fail without Redis
        print("  - Order created (no Redis): Skipped OK")

        # Test fill
        success = publisher.publish_fill(
            order_id="test_order_123",
            symbol="BTC/USD",
            side="buy",
            size=0.01,
            price=50000.0,
            fee=0.00012,
            maker=True,
            spread_bps_at_entry=0.8,
        )
        assert not success  # Should fail without Redis
        print("  - Fill published (no Redis): Skipped OK")

        # Test order cancelled
        success = publisher.publish_order_cancelled(
            order_id="test_order_123",
            symbol="BTC/USD",
            reason="timeout",
        )
        assert not success  # Should fail without Redis
        print("  - Order cancelled (no Redis): Skipped OK")

        # Test stats
        stats = publisher.get_stats()
        assert stats["published_count"] == 0
        assert stats["failed_count"] == 0
        print(f"  - Stats: {stats} OK")

        print("\nAll order state publisher tests passed!")

    except Exception as e:
        print(f"\nFAIL Order State Publisher Self-Check: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
