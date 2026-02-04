"""
Supporting models for the trading pipeline.

MarketSnapshot: Market state input for generate_trade_intent()
AccountState: Account state input for evaluate_risk()
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, ConfigDict, field_validator


class MarketSnapshot(BaseModel):
    """
    Point-in-time market state snapshot.

    This is the input to generate_trade_intent(strategy, market_snapshot).
    It contains all market data needed by strategies to generate intents.

    Immutability enforced via frozen=True.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    pair: str = Field(
        ...,
        description="Trading pair (e.g., 'BTC/USD')",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Snapshot timestamp",
    )

    # Price data
    bid: Decimal = Field(
        ...,
        gt=0,
        description="Current best bid price",
    )
    ask: Decimal = Field(
        ...,
        gt=0,
        description="Current best ask price",
    )
    last_price: Decimal = Field(
        ...,
        gt=0,
        description="Last trade price",
    )

    # OHLCV (for current/recent candle)
    open: Decimal | None = Field(
        default=None,
        description="Open price of current candle",
    )
    high: Decimal | None = Field(
        default=None,
        description="High price of current candle",
    )
    low: Decimal | None = Field(
        default=None,
        description="Low price of current candle",
    )
    close: Decimal | None = Field(
        default=None,
        description="Close price of current candle",
    )
    volume: Decimal | None = Field(
        default=None,
        ge=0,
        description="Volume of current candle",
    )

    # Computed metrics
    spread_bps: float = Field(
        default=0.0,
        ge=0,
        description="Bid-ask spread in basis points",
    )
    mid_price: Decimal | None = Field(
        default=None,
        description="Mid price between bid and ask",
    )

    # Indicators (pre-computed, strategy-agnostic)
    indicators: dict[str, Any] = Field(
        default_factory=dict,
        description="Pre-computed indicators (e.g., {'rsi_14': 45.2, 'ema_20': 50000.5})",
    )

    # Market context
    regime: str = Field(
        default="unknown",
        description="Market regime (e.g., 'trending_up', 'ranging', 'volatile')",
    )
    volatility: str = Field(
        default="normal",
        description="Volatility level (low/normal/high/extreme)",
    )

    # Data quality
    data_age_ms: int = Field(
        default=0,
        ge=0,
        description="Age of this data in milliseconds",
    )
    is_stale: bool = Field(
        default=False,
        description="Whether this data is considered stale",
    )

    @field_validator("bid", "ask", "last_price", mode="before")
    @classmethod
    def coerce_required_decimal(cls, v: Any) -> Decimal:
        """Coerce required numeric values to Decimal."""
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    @field_validator("open", "high", "low", "close", "volume", "mid_price", mode="before")
    @classmethod
    def coerce_optional_decimal(cls, v: Any) -> Decimal | None:
        """Coerce optional numeric values to Decimal."""
        if v is None:
            return None
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    def get_indicator(self, key: str, default: Any = None) -> Any:
        """Get an indicator value with optional default."""
        return self.indicators.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(mode="json")


class AccountState(BaseModel):
    """
    Account state snapshot for risk evaluation.

    This is the input to evaluate_risk(trade_intent, account_state).
    It contains all account data needed by risk evaluators.

    Immutability enforced via frozen=True.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    account_id: str = Field(
        ...,
        description="Account identifier",
    )
    user_id: str = Field(
        ...,
        description="User identifier",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="State snapshot timestamp",
    )

    # Balance and equity
    total_equity_usd: Decimal = Field(
        ...,
        ge=0,
        description="Total account equity in USD",
    )
    available_balance_usd: Decimal = Field(
        ...,
        ge=0,
        description="Available balance for trading",
    )
    margin_used_usd: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Margin currently in use",
    )

    # P&L tracking
    daily_pnl_usd: Decimal = Field(
        default=Decimal("0"),
        description="Daily P&L in USD",
    )
    weekly_pnl_usd: Decimal = Field(
        default=Decimal("0"),
        description="Weekly P&L in USD",
    )
    drawdown_pct: float = Field(
        default=0.0,
        ge=0,
        description="Current drawdown percentage from peak",
    )

    # Position tracking
    open_positions_count: int = Field(
        default=0,
        ge=0,
        description="Number of open positions",
    )
    open_positions_exposure_usd: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Total exposure from open positions",
    )
    open_positions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of open position summaries",
    )

    # Trading activity
    trades_today: int = Field(
        default=0,
        ge=0,
        description="Number of trades executed today",
    )
    last_trade_at: datetime | None = Field(
        default=None,
        description="Timestamp of last trade",
    )
    last_loss_at: datetime | None = Field(
        default=None,
        description="Timestamp of last losing trade (for cooldown)",
    )

    # Account status
    trading_enabled: bool = Field(
        default=True,
        description="Whether trading is enabled for this account",
    )
    mode: str = Field(
        default="paper",
        description="Account mode: 'paper' or 'live'",
    )

    @field_validator(
        "total_equity_usd",
        "available_balance_usd",
        "margin_used_usd",
        "daily_pnl_usd",
        "weekly_pnl_usd",
        "open_positions_exposure_usd",
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

    @property
    def margin_utilization(self) -> float:
        """Calculate margin utilization percentage."""
        if self.total_equity_usd == 0:
            return 0.0
        return float(self.margin_used_usd / self.total_equity_usd) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(mode="json")
