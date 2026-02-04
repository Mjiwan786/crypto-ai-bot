"""
Canonical ExecutionDecision model.

An ExecutionDecision is the result of risk evaluation on a TradeIntent.
It determines whether the trade can proceed and captures the full risk context.

This is the output of: evaluate_risk(trade_intent, account_state)

CRITICAL: No trade can be executed without an approved ExecutionDecision.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict


class DecisionStatus(str, Enum):
    """Execution decision status."""

    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"  # For async risk evaluation


class RejectionReason(BaseModel):
    """
    Structured reason for why a trade was rejected by risk evaluation.

    Every rejection must be explainable.
    """

    model_config = ConfigDict(frozen=True)

    code: str = Field(
        ...,
        description="Machine-readable rejection code (e.g., 'MAX_POSITION_SIZE_EXCEEDED')",
    )
    message: str = Field(
        ...,
        description="Human-readable rejection message",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (e.g., {'requested': 500, 'limit': 100})",
    )


class RiskSnapshot(BaseModel):
    """
    Point-in-time snapshot of risk state when decision was made.

    Captures all risk-relevant data for audit/explainability.
    """

    model_config = ConfigDict(frozen=True)

    # Account state at decision time
    account_equity_usd: float = Field(
        default=0.0,
        ge=0,
        description="Account equity at decision time",
    )
    daily_pnl_usd: float = Field(
        default=0.0,
        description="Daily P&L at decision time",
    )
    daily_trades_count: int = Field(
        default=0,
        ge=0,
        description="Number of trades today",
    )
    open_positions_count: int = Field(
        default=0,
        ge=0,
        description="Number of open positions",
    )
    open_positions_exposure_usd: float = Field(
        default=0.0,
        ge=0,
        description="Total exposure from open positions",
    )

    # Risk limits that were checked
    max_position_size_usd: float = Field(
        default=0.0,
        description="Max position size limit that was applied",
    )
    max_daily_loss_usd: float = Field(
        default=0.0,
        description="Max daily loss limit that was applied",
    )
    max_trades_per_day: int = Field(
        default=0,
        description="Max trades per day limit that was applied",
    )

    # Additional risk metrics
    portfolio_heat: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Portfolio heat/risk utilization (0-1)",
    )
    drawdown_pct: float = Field(
        default=0.0,
        ge=0,
        description="Current drawdown percentage",
    )

    # Market conditions at decision time
    spread_bps: float = Field(
        default=0.0,
        ge=0,
        description="Bid-ask spread in basis points",
    )
    volatility_regime: str = Field(
        default="normal",
        description="Volatility regime (low/normal/high/extreme)",
    )

    # Flags
    emergency_stop_active: bool = Field(
        default=False,
        description="Whether emergency stop was active",
    )
    trading_enabled: bool = Field(
        default=True,
        description="Whether trading was enabled globally",
    )


class ExecutionDecision(BaseModel):
    """
    Canonical ExecutionDecision model - result of risk evaluation.

    This is a 'System Law' object. Every trade MUST have an ExecutionDecision.
    - If status == APPROVED: trade can proceed to execution
    - If status == REJECTED: trade is blocked with full explanation

    Key explainability:
    - risk_snapshot: complete risk state at decision time
    - rejection_reasons: if rejected, WHY it was rejected
    - rules_evaluated: which risk rules were checked

    Immutability enforced via frozen=True.
    """

    model_config = ConfigDict(frozen=True)

    # Schema version for forward compatibility
    schema_version: str = Field(
        default="1.0.0",
        description="Schema version for this contract",
    )

    # Identity
    decision_id: str = Field(
        default_factory=lambda: f"decision_{uuid4().hex[:12]}",
        description="Unique decision identifier",
    )
    intent_id: str = Field(
        ...,
        description="ID of the TradeIntent this decision is for",
    )

    # Decision outcome
    status: DecisionStatus = Field(
        ...,
        description="Decision status: approved, rejected, or pending",
    )

    # Explainability for rejections
    rejection_reasons: list[RejectionReason] = Field(
        default_factory=list,
        description="Reasons why the trade was rejected (empty if approved)",
    )

    # Risk state at decision time
    risk_snapshot: RiskSnapshot = Field(
        default_factory=RiskSnapshot,
        description="Complete risk state snapshot when decision was made",
    )

    # Audit trail
    rules_evaluated: list[str] = Field(
        default_factory=list,
        description="List of risk rules that were evaluated",
    )
    evaluation_time_ms: float = Field(
        default=0.0,
        ge=0,
        description="Time taken to evaluate risk in milliseconds",
    )

    # Timing
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this decision was made",
    )

    # Metadata
    mode: str = Field(
        default="paper",
        description="Trading mode: 'paper' or 'live'",
    )
    evaluator_version: str = Field(
        default="1.0.0",
        description="Version of risk evaluator that made this decision",
    )

    @property
    def is_approved(self) -> bool:
        """Check if the decision allows execution."""
        return self.status == DecisionStatus.APPROVED

    @property
    def is_rejected(self) -> bool:
        """Check if the decision blocks execution."""
        return self.status == DecisionStatus.REJECTED

    @property
    def primary_rejection_reason(self) -> str | None:
        """Get the primary rejection reason message, if rejected."""
        if not self.rejection_reasons:
            return None
        return self.rejection_reasons[0].message

    @property
    def rejection_codes(self) -> list[str]:
        """Get all rejection codes."""
        return [r.code for r in self.rejection_reasons]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionDecision":
        """Create from dictionary."""
        return cls.model_validate(data)

    @classmethod
    def approve(
        cls,
        intent_id: str,
        risk_snapshot: RiskSnapshot,
        rules_evaluated: list[str] | None = None,
        mode: str = "paper",
    ) -> "ExecutionDecision":
        """Factory method to create an approved decision."""
        return cls(
            intent_id=intent_id,
            status=DecisionStatus.APPROVED,
            risk_snapshot=risk_snapshot,
            rules_evaluated=rules_evaluated or [],
            mode=mode,
        )

    @classmethod
    def reject(
        cls,
        intent_id: str,
        reasons: list[RejectionReason],
        risk_snapshot: RiskSnapshot,
        rules_evaluated: list[str] | None = None,
        mode: str = "paper",
    ) -> "ExecutionDecision":
        """Factory method to create a rejected decision."""
        return cls(
            intent_id=intent_id,
            status=DecisionStatus.REJECTED,
            rejection_reasons=reasons,
            risk_snapshot=risk_snapshot,
            rules_evaluated=rules_evaluated or [],
            mode=mode,
        )
