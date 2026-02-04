"""
Canonical Strategy model.

A Strategy is an immutable configuration object that defines how signals are generated.
It is NOT the execution logic itself, but the configuration/parameters that drive it.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict


class StrategyType(str, Enum):
    """Strategy classification."""

    RSI_MEAN_REVERSION = "rsi_mean_reversion"
    EMA_CROSSOVER = "ema_crossover"
    MACD_TREND = "macd_trend"
    BREAKOUT_HH_LL = "breakout_hh_ll"
    SCALPER = "scalper"
    MOMENTUM = "momentum"
    CUSTOM = "custom"


class StrategySource(str, Enum):
    """Where the strategy originated."""

    PLATFORM = "platform"  # Built-in platform strategy
    INDICATOR = "indicator"  # Pure indicator-based strategy
    USER = "user"  # User-defined custom strategy
    EXTERNAL = "external"  # External signal provider


class RiskProfile(BaseModel):
    """Risk parameters for a strategy."""

    model_config = ConfigDict(frozen=True)

    max_position_size_usd: float = Field(
        default=100.0,
        ge=0,
        description="Maximum position size in USD",
    )
    stop_loss_pct: float = Field(
        default=2.0,
        ge=0,
        le=100,
        description="Stop loss percentage from entry",
    )
    take_profit_pct: float = Field(
        default=4.0,
        ge=0,
        le=100,
        description="Take profit percentage from entry",
    )
    max_daily_loss_usd: float = Field(
        default=50.0,
        ge=0,
        description="Maximum daily loss allowed in USD",
    )
    max_trades_per_day: int = Field(
        default=10,
        ge=0,
        description="Maximum number of trades per day",
    )
    cooldown_seconds: int = Field(
        default=60,
        ge=0,
        description="Cooldown between trades in seconds",
    )


class Strategy(BaseModel):
    """
    Canonical Strategy model - immutable configuration for signal generation.

    This is a 'System Law' object that defines HOW a strategy operates,
    not the strategy execution itself. All strategies must be representable
    by this configuration.

    Immutability enforced via frozen=True.
    """

    model_config = ConfigDict(frozen=True)

    # Schema version for forward compatibility
    schema_version: str = Field(
        default="1.0.0",
        description="Schema version for this contract",
    )

    # Identity
    strategy_id: str = Field(
        default_factory=lambda: f"strat_{uuid4().hex[:12]}",
        description="Unique strategy identifier",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable strategy name",
    )
    description: str = Field(
        default="",
        max_length=500,
        description="Strategy description",
    )

    # Classification
    strategy_type: StrategyType = Field(
        ...,
        description="Strategy classification type",
    )
    source: StrategySource = Field(
        default=StrategySource.PLATFORM,
        description="Where the strategy originated",
    )

    # Configuration
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Strategy-specific parameters (e.g., RSI period, EMA lengths)",
    )
    timeframes: list[str] = Field(
        default_factory=lambda: ["5m"],
        min_length=1,
        description="Timeframes this strategy operates on (e.g., '1m', '5m', '1h')",
    )
    supported_pairs: list[str] = Field(
        default_factory=lambda: ["BTC/USD", "ETH/USD"],
        description="Trading pairs this strategy supports",
    )

    # Risk configuration
    risk_profile: RiskProfile = Field(
        default_factory=RiskProfile,
        description="Risk management parameters",
    )

    # Metadata
    version: str = Field(
        default="1.0.0",
        description="Strategy version",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this strategy configuration was created",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this strategy is enabled",
    )

    def get_param(self, key: str, default: Any = None) -> Any:
        """Get a strategy parameter with optional default."""
        return self.parameters.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Strategy":
        """Create from dictionary."""
        return cls.model_validate(data)
