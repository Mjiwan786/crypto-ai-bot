"""
Canonical Trade model.

A Trade is the final execution record after a trade has been executed.
It links back to the full explainability chain: Strategy -> Intent -> Decision -> Trade.

This is the output of: execute(decision)

CRITICAL: No Trade can exist without an approved ExecutionDecision.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict, field_validator


class TradeStatus(str, Enum):
    """Trade execution status."""

    PENDING = "pending"  # Order submitted, awaiting fill
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


class OrderFill(BaseModel):
    """Individual order fill record."""

    model_config = ConfigDict(frozen=True)

    fill_id: str = Field(
        default_factory=lambda: f"fill_{uuid4().hex[:8]}",
        description="Unique fill identifier",
    )
    price: Decimal = Field(
        ...,
        gt=0,
        description="Fill price",
    )
    quantity: Decimal = Field(
        ...,
        gt=0,
        description="Fill quantity",
    )
    fee: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Fee for this fill",
    )
    fee_currency: str = Field(
        default="USD",
        description="Currency of the fee",
    )
    filled_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this fill occurred",
    )
    exchange_fill_id: str | None = Field(
        default=None,
        description="Exchange-provided fill ID (for live trades)",
    )

    @field_validator("price", "quantity", "fee", mode="before")
    @classmethod
    def coerce_to_decimal(cls, v: Any) -> Decimal:
        """Coerce numeric values to Decimal."""
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))


class ExplainabilityChain(BaseModel):
    """
    Full explainability chain linking trade back to its origins.

    This captures the complete audit trail:
    Strategy -> TradeIntent -> ExecutionDecision -> Trade
    """

    model_config = ConfigDict(frozen=True)

    # Linkage IDs
    strategy_id: str = Field(
        ...,
        description="ID of the strategy that generated the intent",
    )
    intent_id: str = Field(
        ...,
        description="ID of the TradeIntent",
    )
    decision_id: str = Field(
        ...,
        description="ID of the ExecutionDecision",
    )

    # Captured context from the chain (denormalized for easy access)
    strategy_name: str = Field(
        default="",
        description="Name of the strategy",
    )
    intent_reasons: list[str] = Field(
        default_factory=list,
        description="Reasons from the TradeIntent",
    )
    intent_confidence: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Confidence from the TradeIntent",
    )
    decision_status: str = Field(
        default="approved",
        description="Status of the ExecutionDecision",
    )
    risk_snapshot_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of risk snapshot at decision time",
    )


class Trade(BaseModel):
    """
    Canonical Trade model - final execution record.

    This is a 'System Law' object. Every executed trade has a Trade record
    with full explainability chain linking back to Strategy/Intent/Decision.

    Key features:
    - explainability_chain: links to all prior objects in the pipeline
    - fills: actual order fills with prices and fees
    - slippage tracking: expected vs actual execution
    - P&L calculation: realized profit/loss

    Immutability enforced via frozen=True.
    """

    model_config = ConfigDict(frozen=True)

    # Schema version for forward compatibility
    schema_version: str = Field(
        default="1.0.0",
        description="Schema version for this contract",
    )

    # Identity
    trade_id: str = Field(
        default_factory=lambda: f"trade_{uuid4().hex[:12]}",
        description="Unique trade identifier",
    )
    decision_id: str = Field(
        ...,
        description="ID of the ExecutionDecision that authorized this trade",
    )

    # Trade specification (copied from intent for denormalization)
    pair: str = Field(
        ...,
        description="Trading pair (e.g., 'BTC/USD')",
    )
    side: str = Field(
        ...,
        description="Trade direction: 'long' or 'short'",
    )
    requested_quantity: Decimal = Field(
        ...,
        gt=0,
        description="Requested quantity",
    )
    requested_price: Decimal = Field(
        ...,
        gt=0,
        description="Requested/expected entry price",
    )

    # Execution status
    status: TradeStatus = Field(
        default=TradeStatus.PENDING,
        description="Current trade status",
    )

    # Fills and execution
    fills: list[OrderFill] = Field(
        default_factory=list,
        description="List of order fills",
    )
    exchange_order_id: str | None = Field(
        default=None,
        description="Exchange-provided order ID (for live trades)",
    )

    # Execution metrics
    avg_fill_price: Decimal | None = Field(
        default=None,
        description="Volume-weighted average fill price",
    )
    total_filled_quantity: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Total quantity filled",
    )
    total_fees: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Total fees paid",
    )
    slippage_bps: float = Field(
        default=0.0,
        description="Slippage in basis points (actual vs requested price)",
    )

    # P&L (updated on position close)
    realized_pnl: Decimal | None = Field(
        default=None,
        description="Realized P&L when position is closed",
    )
    realized_pnl_pct: float | None = Field(
        default=None,
        description="Realized P&L as percentage",
    )

    # Full explainability chain
    explainability_chain: ExplainabilityChain = Field(
        ...,
        description="Complete audit trail linking to strategy/intent/decision",
    )

    # Timing
    submitted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When trade was submitted for execution",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When trade execution completed",
    )

    # Metadata
    mode: str = Field(
        default="paper",
        description="Trading mode: 'paper' or 'live'",
    )
    exchange: str = Field(
        default="paper",
        description="Exchange where trade was executed",
    )

    @field_validator(
        "requested_quantity",
        "requested_price",
        "total_filled_quantity",
        "total_fees",
        mode="before",
    )
    @classmethod
    def coerce_to_decimal(cls, v: Any) -> Decimal:
        """Coerce numeric values to Decimal."""
        if v is None:
            return Decimal("0")
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    @field_validator("avg_fill_price", "realized_pnl", mode="before")
    @classmethod
    def coerce_optional_decimal(cls, v: Any) -> Decimal | None:
        """Coerce optional numeric values to Decimal."""
        if v is None:
            return None
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    @property
    def is_complete(self) -> bool:
        """Check if trade execution is complete."""
        return self.status in (
            TradeStatus.FILLED,
            TradeStatus.CANCELLED,
            TradeStatus.FAILED,
            TradeStatus.EXPIRED,
        )

    @property
    def is_successful(self) -> bool:
        """Check if trade was successfully filled."""
        return self.status == TradeStatus.FILLED

    @property
    def fill_rate(self) -> float:
        """Calculate fill rate (filled / requested)."""
        if self.requested_quantity == 0:
            return 0.0
        return float(self.total_filled_quantity / self.requested_quantity)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Trade":
        """Create from dictionary."""
        return cls.model_validate(data)
