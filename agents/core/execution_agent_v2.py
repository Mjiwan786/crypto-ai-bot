"""
Execution Agent - Order planning and execution with dry-run support.

Provides clean separation:
1. plan(intent) -> Order - Convert intent to order (NO execution)
2. execute(order, gateway, dry_run) -> ExecutionResult - Execute via injected gateway

Key features:
- Dry-run mode for testing
- Gateway injected via Protocol (no hardcoded Kraken)
- Pure planning logic (testable without network)
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from agents.core.types import (
    ExecutionResult,
    ExchangeClientProtocol,
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Pure Planning Functions
# ==============================================================================


def plan(intent: OrderIntent) -> Order:
    """Convert order intent to executable order (pure function, no I/O).

    Args:
        intent: Order intention with trading parameters

    Returns:
        Order ready for execution

    Examples:
        >>> intent = OrderIntent(symbol="BTC/USD", side=Side.BUY, quantity=Decimal("0.1"))
        >>> order = plan(intent)
        >>> assert order.status == OrderStatus.PENDING
    """
    order_id = f"order_{uuid4().hex[:12]}"

    return Order(
        order_id=order_id,
        symbol=intent.symbol,
        side=intent.side,
        quantity=intent.quantity,
        order_type=intent.order_type,
        status=OrderStatus.PENDING,
        price=intent.price,
        timestamp=time.time(),
        updated_at=time.time(),
        strategy=intent.strategy,
        signal_id=intent.signal_id,
    )


# ==============================================================================
# Execution Functions (with injected gateway)
# ==============================================================================


async def execute(
    order: Order,
    gateway: ExchangeClientProtocol,
    dry_run: bool = False,
) -> ExecutionResult:
    """Execute order via injected gateway with dry-run support.

    Args:
        order: Order to execute
        gateway: Exchange client (injected via Protocol)
        dry_run: If True, simulate execution without real order

    Returns:
        ExecutionResult with success status and details

    Examples:
        >>> fake_gateway = FakeKrakenGateway()
        >>> result = await execute(order, fake_gateway, dry_run=True)
        >>> assert result.success
    """
    start_time = time.time()

    # Dry-run mode: simulate execution
    if dry_run:
        logger.info(f"[DRY-RUN] Would execute {order.side.value} {order.quantity} {order.symbol} @ {order.price}")

        return ExecutionResult(
            success=True,
            order_id=order.order_id,
            filled_quantity=order.quantity,
            average_price=order.price,
            fee=Decimal("0"),
            execution_time_ms=(time.time() - start_time) * 1000,
            timestamp=time.time(),
        )

    # Real execution via injected gateway
    try:
        # Validate order
        if order.quantity <= 0:
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                error_message=f"Invalid quantity: {order.quantity}",
                timestamp=time.time(),
            )

        # Convert to gateway parameters
        order_type_str = order.order_type.value
        side_str = order.side.value
        amount_float = float(order.quantity)
        price_float = float(order.price) if order.price else None

        # Execute via gateway
        response = await gateway.create_order(
            symbol=order.symbol,
            order_type=order_type_str,
            side=side_str,
            amount=amount_float,
            price=price_float,
        )

        # Parse response
        filled_qty = Decimal(str(response.get("filled", amount_float)))
        avg_price = Decimal(str(response.get("average", price_float or 0)))
        fee = Decimal(str(response.get("fee", {}).get("cost", 0)))

        execution_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"✅ Executed {order.side.value} {filled_qty} {order.symbol} @ {avg_price} "
            f"(fee: {fee}, time: {execution_time_ms:.1f}ms)"
        )

        return ExecutionResult(
            success=True,
            order_id=response.get("id", order.order_id),
            filled_quantity=filled_qty,
            average_price=avg_price,
            fee=fee,
            execution_time_ms=execution_time_ms,
            timestamp=time.time(),
        )

    except Exception as e:
        logger.error(f"❌ Execution failed: {e}")

        return ExecutionResult(
            success=False,
            order_id=order.order_id,
            error_message=str(e),
            execution_time_ms=(time.time() - start_time) * 1000,
            timestamp=time.time(),
        )


# ==============================================================================
# Execution Agent Class (with injected dependencies)
# ==============================================================================


class ExecutionAgent:
    """Execution agent with dependency injection."""

    def __init__(self, gateway: ExchangeClientProtocol, default_dry_run: bool = False):
        """Initialize execution agent.

        Args:
            gateway: Exchange gateway (injected)
            default_dry_run: Default dry-run mode
        """
        self.gateway = gateway
        self.default_dry_run = default_dry_run
        logger.info(f"ExecutionAgent initialized (dry_run={default_dry_run})")

    def plan(self, intent: OrderIntent) -> Order:
        """Plan order from intent (delegates to pure function)."""
        return plan(intent)

    async def execute(self, order: Order, dry_run: Optional[bool] = None) -> ExecutionResult:
        """Execute order (delegates to execute function with injected gateway).

        Args:
            order: Order to execute
            dry_run: Override default dry-run mode (None = use default)

        Returns:
            ExecutionResult
        """
        use_dry_run = dry_run if dry_run is not None else self.default_dry_run
        return await execute(order, self.gateway, use_dry_run)


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "plan",
    "execute",
    "ExecutionAgent",
]
