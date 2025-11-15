"""
PRD-001 Compliant Signal Schema (Line 87)

This module defines the EXACT signal schema specified in PRD-001:
"The interface of 'signals' stream must include: timestamp, signal_type (entry/exit/stop),
trading_pair, size, stop_loss, take_profit, confidence_score, agent_id."

This schema is REQUIRED for all signals published to Redis "signals" stream to ensure
downstream compatibility with signals-api and signals-site.

WARNING: This differs from models/signal_dto.py which uses a different schema.
         Use THIS schema for PRD-001 compliance.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SignalType(str, Enum):
    """Signal types as per PRD-001: entry/exit/stop"""

    ENTRY = "entry"
    EXIT = "exit"
    STOP = "stop"
    # Extended types for backward compatibility
    BUY = "buy"
    SELL = "sell"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    SCALP_ENTRY = "scalp_entry"
    SCALP_EXIT = "scalp_exit"


class PRDSignalSchema(BaseModel):
    """
    PRD-001 Line 87 Compliant Signal Schema

    EXACT REQUIRED FIELDS per PRD-001:
    - timestamp: Unix timestamp (float)
    - signal_type: entry/exit/stop (string)
    - trading_pair: Symbol like "BTC/USD" (string)
    - size: Position size/quantity (float)
    - stop_loss: Stop loss price level (float, optional)
    - take_profit: Take profit price level (float, optional)
    - confidence_score: 0.0-1.0 (float)
    - agent_id: Agent identifier (string)

    Example:
        {
            "timestamp": 1699564800.123,
            "signal_type": "entry",
            "trading_pair": "BTC/USD",
            "size": 0.5,
            "stop_loss": 50000.0,
            "take_profit": 55000.0,
            "confidence_score": 0.85,
            "agent_id": "momentum_strategy"
        }
    """

    # PRD-001 REQUIRED FIELDS (LINE 87)
    timestamp: float = Field(
        description="Unix timestamp when signal was generated",
        examples=[1699564800.123]
    )
    signal_type: str = Field(
        description="Signal type: entry, exit, or stop",
        examples=["entry", "exit", "stop"],
        min_length=3,
        max_length=20
    )
    trading_pair: str = Field(
        description="Trading pair symbol (e.g., BTC/USD, ETH/USD)",
        examples=["BTC/USD", "ETH/USD", "SOL/USD"],
        min_length=3,
        max_length=20
    )
    size: float = Field(
        description="Position size or quantity",
        gt=0.0,
        examples=[0.1, 1.5, 100.0]
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="Stop loss price level (optional)",
        examples=[50000.0, None]
    )
    take_profit: Optional[float] = Field(
        default=None,
        description="Take profit price level (optional)",
        examples=[55000.0, None]
    )
    confidence_score: float = Field(
        description="Signal confidence score (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
        examples=[0.85, 0.92, 0.65]
    )
    agent_id: str = Field(
        description="ID of the agent that generated this signal",
        examples=["signal_processor", "scalper", "momentum_strategy"],
        min_length=1,
        max_length=100
    )

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: float) -> float:
        """Ensure timestamp is reasonable (not too far in past or future)"""
        now = time.time()
        one_day = 86400

        if v < now - one_day:
            raise ValueError(
                f"Timestamp {v} is more than 1 day in the past. "
                "Signals should be recent."
            )
        if v > now + 60:
            raise ValueError(
                f"Timestamp {v} is more than 1 minute in the future. "
                "Check system clock."
            )
        return v

    @field_validator("signal_type")
    @classmethod
    def validate_signal_type(cls, v: str) -> str:
        """Validate signal_type is one of: entry/exit/stop or extended types"""
        valid_types = {
            "entry", "exit", "stop",
            "buy", "sell",  # Extended
            "close_long", "close_short",  # Extended
            "scalp_entry", "scalp_exit"  # Extended
        }
        if v.lower() not in valid_types:
            raise ValueError(
                f"signal_type must be one of {valid_types}, got: {v}"
            )
        return v.lower()

    @field_validator("trading_pair")
    @classmethod
    def validate_trading_pair(cls, v: str) -> str:
        """Ensure trading pair is in standard format with / or -"""
        if "/" not in v and "-" not in v:
            raise ValueError(
                f"Invalid trading_pair format: {v}. "
                "Expected format: 'BASE/QUOTE' or 'BASE-QUOTE'"
            )
        return v.upper()

    @field_validator("stop_loss", "take_profit")
    @classmethod
    def validate_price_levels(cls, v: Optional[float]) -> Optional[float]:
        """Validate price levels are positive if set"""
        if v is not None and v <= 0:
            raise ValueError(f"Price level must be positive, got: {v}")
        return v

    def to_redis_dict(self) -> Dict[str, str]:
        """
        Convert to Redis-compatible dictionary with string values.

        All values are converted to strings for Redis XADD compatibility.

        Returns:
            Dict with all values as strings
        """
        data = {
            "timestamp": str(self.timestamp),
            "signal_type": self.signal_type,
            "trading_pair": self.trading_pair,
            "size": str(self.size),
            "confidence_score": str(self.confidence_score),
            "agent_id": self.agent_id,
        }

        # Add optional fields if present
        if self.stop_loss is not None:
            data["stop_loss"] = str(self.stop_loss)
        if self.take_profit is not None:
            data["take_profit"] = str(self.take_profit)

        return data

    @classmethod
    def from_legacy_signal(
        cls,
        signal: Dict[str, Any],
        agent_id: str = "unknown"
    ) -> "PRDSignalSchema":
        """
        Convert legacy signal format to PRD-001 compliant schema.

        Handles field name mapping from current signal_processor.py schema:
        - pair → trading_pair
        - action → signal_type
        - quantity → size
        - ai_confidence / confidence → confidence_score
        - strategy → agent_id

        Args:
            signal: Legacy signal dictionary (from signal_processor.py)
            agent_id: Default agent ID if not found in signal

        Returns:
            PRD-001 compliant PRDSignalSchema

        Example:
            >>> legacy = {
            ...     "timestamp": 1699564800.0,
            ...     "pair": "BTC/USD",
            ...     "action": "buy",
            ...     "quantity": 0.5,
            ...     "stop_loss": 50000.0,
            ...     "take_profit": 55000.0,
            ...     "ai_confidence": 0.85,
            ...     "strategy": "momentum_v1"
            ... }
            >>> prd_signal = PRDSignalSchema.from_legacy_signal(legacy)
        """
        # Map legacy field names to PRD-001 schema
        return cls(
            timestamp=signal.get("timestamp", time.time()),
            signal_type=signal.get("action", signal.get("signal_type", "entry")),
            trading_pair=signal.get("pair", signal.get("trading_pair", "UNKNOWN")),
            size=float(signal.get("quantity", signal.get("size", 0.0))),
            stop_loss=signal.get("stop_loss"),
            take_profit=signal.get("take_profit"),
            confidence_score=float(
                signal.get("ai_confidence", signal.get("confidence", signal.get("confidence_score", 0.5)))
            ),
            agent_id=signal.get("agent_id", signal.get("strategy", agent_id))
        )

    class Config:
        """Pydantic model configuration"""
        validate_assignment = True  # Validate on field assignment
        extra = "forbid"  # Disallow extra fields not in PRD-001 schema


def validate_signal_for_publishing(signal_dict: Dict[str, Any]) -> PRDSignalSchema:
    """
    Validate a signal dictionary against PRD-001 schema before publishing to Redis.

    This function should be called before every XADD to the "signals" stream
    to ensure PRD-001 compliance.

    Args:
        signal_dict: Signal dictionary to validate

    Returns:
        Validated PRDSignalSchema instance

    Raises:
        ValidationError: If signal doesn't match PRD-001 schema

    Example:
        >>> signal = {"timestamp": time.time(), ...}
        >>> validated = validate_signal_for_publishing(signal)
        >>> await redis_client.xadd("signals", validated.to_redis_dict())
    """
    # Try direct validation first
    try:
        return PRDSignalSchema.model_validate(signal_dict)
    except Exception:
        # If fails, try legacy conversion
        return PRDSignalSchema.from_legacy_signal(signal_dict)


# =============================================================================
# SCHEMA COMPARISON with existing signal_dto.py
# =============================================================================
"""
SCHEMA MISMATCH ALERT:

models/signal_dto.py uses DIFFERENT schema:
    {
        "id": str,
        "ts": int (milliseconds),
        "pair": str,
        "side": "long" | "short",
        "entry": float,
        "sl": float,
        "tp": float,
        "strategy": str,
        "confidence": float,
        "mode": "paper" | "live"
    }

PRD-001 Line 87 requires THIS schema:
    {
        "timestamp": float (seconds),
        "signal_type": "entry" | "exit" | "stop",
        "trading_pair": str,
        "size": float,
        "stop_loss": float (optional),
        "take_profit": float (optional),
        "confidence_score": float,
        "agent_id": str
    }

RECOMMENDED ACTION:
1. Migrate signal_processor.py to use PRDSignalSchema
2. Update all Redis publishing code to use PRDSignalSchema.to_redis_dict()
3. Keep signal_dto.py for backward compatibility (if needed elsewhere)
4. Or: Unify both schemas into single source of truth
"""


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

# =============================================================================
# PRD-001 Section 5.1: Comprehensive Signal Schema with Enums and Validators
# =============================================================================

from datetime import datetime as dt

# PRD-001 Section 5.1: Side enum
class Side(str, Enum):
    """Trading side enumeration."""
    LONG = "LONG"
    SHORT = "SHORT"


# PRD-001 Section 5.1: Strategy enum
class Strategy(str, Enum):
    """Trading strategy enumeration."""
    SCALPER = "SCALPER"
    TREND = "TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"


# PRD-001 Section 5.1: Regime enum
class Regime(str, Enum):
    """Market regime enumeration."""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"


# PRD-001 Section 5.1: MACDSignal enum
class MACDSignal(str, Enum):
    """MACD signal enumeration."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


# PRD-001 Section 5.1: Indicators model
class Indicators(BaseModel):
    """Technical indicators model with validation."""
    rsi_14: float = Field(..., description="RSI(14) value")
    macd_signal: MACDSignal = Field(..., description="MACD signal")
    atr_14: float = Field(..., description="ATR(14) value")
    volume_ratio: float = Field(..., description="Volume ratio")

    @field_validator('rsi_14')
    @classmethod
    def validate_rsi_14(cls, v):
        """Validate rsi_14 is in [0, 100]."""
        if not 0 <= v <= 100:
            raise ValueError(f"rsi_14 must be in [0, 100], got {v}")
        return v

    @field_validator('atr_14')
    @classmethod
    def validate_atr_14(cls, v):
        """Validate atr_14 > 0."""
        if v <= 0:
            raise ValueError(f"atr_14 must be > 0, got {v}")
        return v

    @field_validator('volume_ratio')
    @classmethod
    def validate_volume_ratio(cls, v):
        """Validate volume_ratio > 0."""
        if v <= 0:
            raise ValueError(f"volume_ratio must be > 0, got {v}")
        return v


# PRD-001 Section 5.1: Metadata model
class SignalMetadata(BaseModel):
    """Signal metadata model."""
    model_version: str = Field(..., description="ML model version")
    backtest_sharpe: Optional[float] = Field(None, description="Backtest Sharpe ratio")
    latency_ms: Optional[float] = Field(None, description="Latency in milliseconds")


# PRD-001 Section 5.1: Comprehensive TradingSignal model
class TradingSignal(BaseModel):
    """
    PRD-001 Section 5.1 compliant comprehensive trading signal model.

    All required fields with comprehensive validation.
    """
    signal_id: str = Field(..., description="Unique signal identifier")
    timestamp: dt = Field(..., description="Signal generation timestamp")
    trading_pair: str = Field(..., description="Trading pair (e.g., BTC/USD)")
    side: Side = Field(..., description="Trading side (LONG/SHORT)")
    strategy: Strategy = Field(..., description="Trading strategy")
    regime: Regime = Field(..., description="Market regime")
    entry_price: float = Field(..., description="Entry price")
    take_profit: float = Field(..., description="Take profit price")
    stop_loss: float = Field(..., description="Stop loss price")
    confidence: float = Field(..., description="Signal confidence [0, 1]")
    position_size_usd: float = Field(..., description="Position size in USD")
    indicators: Indicators = Field(..., description="Technical indicators")
    metadata: Optional[SignalMetadata] = Field(None, description="Optional metadata")

    @field_validator('entry_price')
    @classmethod
    def validate_entry_price(cls, v):
        """Validate entry_price > 0."""
        if v <= 0:
            raise ValueError(f"entry_price must be > 0, got {v}")
        return v

    @field_validator('take_profit')
    @classmethod
    def validate_take_profit(cls, v):
        """Validate take_profit > 0."""
        if v <= 0:
            raise ValueError(f"take_profit must be > 0, got {v}")
        return v

    @field_validator('stop_loss')
    @classmethod
    def validate_stop_loss(cls, v):
        """Validate stop_loss > 0."""
        if v <= 0:
            raise ValueError(f"stop_loss must be > 0, got {v}")
        return v

    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v):
        """Validate confidence in [0, 1]."""
        if not 0 <= v <= 1:
            raise ValueError(f"confidence must be in [0, 1], got {v}")
        return v

    @field_validator('position_size_usd')
    @classmethod
    def validate_position_size_usd(cls, v):
        """Validate position_size_usd > 0 and <= 2000."""
        if v <= 0:
            raise ValueError(f"position_size_usd must be > 0, got {v}")
        if v > 2000:
            raise ValueError(f"position_size_usd must be <= 2000, got {v}")
        return v

    @field_validator('trading_pair')
    @classmethod
    def validate_trading_pair_format(cls, v):
        """Ensure trading pair is in standard format."""
        if "/" not in v and "-" not in v:
            raise ValueError(f"Invalid trading_pair format: {v}")
        return v.upper()

    @model_validator(mode='after')
    def validate_price_relationships(self):
        """
        PRD-001 Section 5.1: Validate price relationships based on side.

        For LONG:
          - take_profit must be > entry_price
          - stop_loss must be < entry_price

        For SHORT:
          - take_profit must be < entry_price
          - stop_loss must be > entry_price
        """
        if self.side == Side.LONG:
            if self.take_profit <= self.entry_price:
                raise ValueError(
                    f"LONG signal: take_profit ({self.take_profit}) must be > entry_price ({self.entry_price})"
                )
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    f"LONG signal: stop_loss ({self.stop_loss}) must be < entry_price ({self.entry_price})"
                )
        elif self.side == Side.SHORT:
            if self.take_profit >= self.entry_price:
                raise ValueError(
                    f"SHORT signal: take_profit ({self.take_profit}) must be < entry_price ({self.entry_price})"
                )
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    f"SHORT signal: stop_loss ({self.stop_loss}) must be > entry_price ({self.entry_price})"
                )

        return self

    class Config:
        use_enum_values = True


if __name__ == "__main__":
    import json

    print("=" * 70)
    print("PRD-001 Compliant Signal Schema Examples")
    print("=" * 70)

    # Example 1: Create valid PRD-001 signal
    print("\nExample 1: Create PRD-001 Compliant Signal")
    print("-" * 70)

    signal = PRDSignalSchema(
        timestamp=time.time(),
        signal_type="entry",
        trading_pair="BTC/USD",
        size=0.5,
        stop_loss=50000.0,
        take_profit=55000.0,
        confidence_score=0.85,
        agent_id="momentum_strategy"
    )

    print("Python object:")
    print(json.dumps(signal.model_dump(), indent=2))

    print("\nRedis format (for XADD):")
    print(json.dumps(signal.to_redis_dict(), indent=2))

    # Example 2: Convert legacy signal
    print("\n" + "=" * 70)
    print("Example 2: Convert Legacy Signal to PRD-001")
    print("-" * 70)

    legacy_signal = {
        "timestamp": time.time(),
        "pair": "ETH/USD",
        "action": "buy",
        "quantity": 2.5,
        "stop_loss": 3000.0,
        "take_profit": 3500.0,
        "ai_confidence": 0.92,
        "strategy": "signal_processor"
    }

    print("Legacy format (from signal_processor.py):")
    print(json.dumps(legacy_signal, indent=2))

    prd_signal = PRDSignalSchema.from_legacy_signal(legacy_signal)
    print("\nPRD-001 compliant format:")
    print(json.dumps(prd_signal.model_dump(), indent=2))

    # Example 3: Validation catches invalid data
    print("\n" + "=" * 70)
    print("Example 3: Validation Catches Invalid Data")
    print("-" * 70)

    try:
        invalid_signal = PRDSignalSchema(
            timestamp=time.time(),
            signal_type="invalid_type",  # Invalid signal type
            trading_pair="BTC/USD",
            size=0.5,
            confidence_score=0.85,
            agent_id="test"
        )
    except Exception as e:
        print(f"✓ Validation error (expected):\n  {str(e)[:100]}...")

    # Example 4: Redis publishing pattern
    print("\n" + "=" * 70)
    print("Example 4: Redis Publishing Pattern")
    print("-" * 70)

    print("""
# Before publishing to Redis "signals" stream:
from models.prd_signal_schema import validate_signal_for_publishing

async def publish_signal_to_redis(signal_dict):
    # Validate against PRD-001 schema
    validated = validate_signal_for_publishing(signal_dict)

    # Convert to Redis format
    redis_data = validated.to_redis_dict()

    # Publish to signals stream
    await redis_client.xadd("signals", redis_data)

    # Log for monitoring
    logger.info(f"Published PRD-001 signal: {{validated.signal_type}} "
                f"{{validated.trading_pair}} @ {{validated.size}}")
    """)

    print("\n" + "=" * 70)
    print("✅ All examples completed successfully")
    print("=" * 70)
