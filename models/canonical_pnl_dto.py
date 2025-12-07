"""
Canonical PnL DTO - Week 2 Task A

Unified PnL model that combines:
- PRD-001 (crypto-ai-bot): PnL equity curve schema
- PRD-002 (signals-api): API-compatible field names
- PRD-003 (signals-site): UI-friendly metrics fields

This is the SINGLE SOURCE OF TRUTH for all PnL publishing to Redis Streams.
All code that publishes PnL data MUST use this DTO.

Usage:
    from models.canonical_pnl_dto import CanonicalPnLDTO, create_canonical_pnl

    pnl = create_canonical_pnl(
        equity=10500.0,
        realized_pnl=500.0,
        unrealized_pnl=100.0,
        num_positions=2,
        mode="paper",
    )

    # Publish to Redis
    redis_payload = pnl.to_redis_payload()
    await redis_client.xadd("pnl:paper:equity_curve", redis_payload, maxlen=50000)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# CANONICAL PNL DTO
# =============================================================================

class CanonicalPnLDTO(BaseModel):
    """
    Canonical PnL DTO - Unified schema for bot, API, and frontend.

    Combines:
    - PRD-001 fields (timestamp, equity, realized_pnl, unrealized_pnl, num_positions, drawdown_pct)
    - PRD-002 API-compatible fields (total_pnl, total_trades, win_rate)
    - PRD-003 UI-friendly fields (totalROI, profitFactor, sharpeRatio, maxDrawdown)

    All fields are included in to_redis_payload() for seamless consumption.
    """

    # =========================================================================
    # PRD-001 Core Fields (Canonical)
    # =========================================================================

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        description="ISO8601 UTC timestamp (PRD-001)"
    )
    equity: float = Field(description="Current equity value (PRD-001)")
    realized_pnl: float = Field(default=0.0, description="Total realized PnL (PRD-001)")
    unrealized_pnl: float = Field(default=0.0, description="Total unrealized PnL (PRD-001)")
    num_positions: int = Field(default=0, ge=0, description="Number of open positions (PRD-001)")
    drawdown_pct: float = Field(default=0.0, description="Current drawdown % (PRD-001)")

    # =========================================================================
    # PRD-002 API-Compatible Fields
    # =========================================================================

    total_pnl: Optional[float] = Field(
        None,
        description="Total PnL (realized + unrealized) - PRD-002 API field"
    )
    total_trades: Optional[int] = Field(
        None,
        ge=0,
        description="Total number of completed trades - PRD-002 API field"
    )
    win_rate: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Win rate (0.0-1.0) - PRD-002 API field"
    )

    # =========================================================================
    # PRD-003 UI-Friendly Fields (Week 2 Addition)
    # =========================================================================

    total_roi: Optional[float] = Field(
        None,
        description="Total ROI as percentage - UI display (PRD-003)"
    )
    profit_factor: Optional[float] = Field(
        None,
        gt=0,
        description="Profit factor (gross profit / gross loss) - UI display (PRD-003)"
    )
    sharpe_ratio: Optional[float] = Field(
        None,
        description="Sharpe ratio - UI display (PRD-003)"
    )
    max_drawdown: Optional[float] = Field(
        None,
        description="Maximum drawdown % - UI display (PRD-003)"
    )
    mode: Optional[Literal["paper", "live"]] = Field(
        None,
        description="Trading mode (paper/live) - UI display"
    )
    initial_balance: Optional[float] = Field(
        None,
        gt=0,
        description="Initial balance for ROI calculation - UI display"
    )

    class Config:
        frozen = False  # Allow mutation for calculated fields

    @model_validator(mode="after")
    def calculate_derived_fields(self):
        """Calculate derived fields if not provided"""
        # Calculate total_pnl if not provided
        if self.total_pnl is None:
            self.total_pnl = self.realized_pnl + self.unrealized_pnl

        # Calculate total_roi if initial_balance is provided
        if self.total_roi is None and self.initial_balance is not None and self.initial_balance > 0:
            self.total_roi = ((self.equity - self.initial_balance) / self.initial_balance) * 100.0

        # max_drawdown defaults to drawdown_pct if not provided
        if self.max_drawdown is None:
            self.max_drawdown = abs(self.drawdown_pct)

        return self

    def to_redis_payload(self) -> Dict[str, bytes]:
        """
        Convert to Redis XADD payload with all fields as string values encoded to bytes.

        Includes:
        - PRD-001 canonical fields
        - PRD-002 API-compatible fields
        - PRD-003 UI-friendly fields

        Returns:
            Dictionary with string keys and bytes values, ready for Redis XADD

        Example:
            >>> pnl = CanonicalPnLDTO(...)
            >>> payload = pnl.to_redis_payload()
            >>> await redis_client.xadd("pnl:paper:equity_curve", payload, maxlen=50000)
        """
        result: Dict[str, bytes] = {}

        # PRD-001 Core Fields
        result["timestamp"] = str(self.timestamp).encode()
        result["equity"] = str(self.equity).encode()
        result["realized_pnl"] = str(self.realized_pnl).encode()
        result["unrealized_pnl"] = str(self.unrealized_pnl).encode()
        result["num_positions"] = str(self.num_positions).encode()
        result["drawdown_pct"] = str(self.drawdown_pct).encode()

        # PRD-002 API-Compatible Fields
        if self.total_pnl is not None:
            result["total_pnl"] = str(self.total_pnl).encode()
        if self.total_trades is not None:
            result["total_trades"] = str(self.total_trades).encode()
        if self.win_rate is not None:
            result["win_rate"] = str(self.win_rate).encode()

        # PRD-003 UI-Friendly Fields
        if self.total_roi is not None:
            result["total_roi"] = str(self.total_roi).encode()
        if self.profit_factor is not None:
            result["profit_factor"] = str(self.profit_factor).encode()
        if self.sharpe_ratio is not None:
            result["sharpe_ratio"] = str(self.sharpe_ratio).encode()
        if self.max_drawdown is not None:
            result["max_drawdown"] = str(self.max_drawdown).encode()
        if self.mode is not None:
            result["mode"] = str(self.mode).encode()
        if self.initial_balance is not None:
            result["initial_balance"] = str(self.initial_balance).encode()

        return result

    def get_stream_key(self, mode: Optional[Literal["paper", "live"]] = None) -> str:
        """
        Get Redis stream key for this PnL update.

        PRD-001 Section 2.2: Stream pattern is pnl:{mode}:equity_curve

        Args:
            mode: Trading mode (defaults to self.mode if set)

        Returns:
            Stream key (e.g., "pnl:paper:equity_curve")
        """
        use_mode = mode or self.mode or "paper"
        return f"pnl:{use_mode}:equity_curve"


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_canonical_pnl(
    equity: float,
    realized_pnl: float = 0.0,
    unrealized_pnl: float = 0.0,
    num_positions: int = 0,
    drawdown_pct: float = 0.0,
    mode: Literal["paper", "live"] = "paper",
    total_trades: Optional[int] = None,
    win_rate: Optional[float] = None,
    total_roi: Optional[float] = None,
    profit_factor: Optional[float] = None,
    sharpe_ratio: Optional[float] = None,
    max_drawdown: Optional[float] = None,
    initial_balance: Optional[float] = None,
) -> CanonicalPnLDTO:
    """
    Convenience function to create canonical PnL update.

    Args:
        equity: Current equity value
        realized_pnl: Total realized PnL
        unrealized_pnl: Total unrealized PnL
        num_positions: Number of open positions
        drawdown_pct: Current drawdown %
        mode: Trading mode (paper or live)
        total_trades: Total number of completed trades
        win_rate: Win rate (0.0-1.0)
        total_roi: Total ROI as percentage
        profit_factor: Profit factor
        sharpe_ratio: Sharpe ratio
        max_drawdown: Maximum drawdown %
        initial_balance: Initial balance for ROI calculation

    Returns:
        Validated CanonicalPnLDTO instance

    Example:
        >>> pnl = create_canonical_pnl(
        ...     equity=10500.0,
        ...     realized_pnl=500.0,
        ...     unrealized_pnl=100.0,
        ...     num_positions=2,
        ...     mode="paper",
        ...     initial_balance=10000.0,
        ... )
    """
    return CanonicalPnLDTO(
        equity=equity,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        num_positions=num_positions,
        drawdown_pct=drawdown_pct,
        mode=mode,
        total_trades=total_trades,
        win_rate=win_rate,
        total_roi=total_roi,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        initial_balance=initial_balance,
    )


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "CanonicalPnLDTO",
    "create_canonical_pnl",
]


