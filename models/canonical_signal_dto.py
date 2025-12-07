"""
Canonical Signal DTO - Week 2 Task A

Unified signal model that combines:
- PRD-001 (crypto-ai-bot): Canonical signal schema
- PRD-002 (signals-api): API-compatible field names
- PRD-003 (signals-site): UI-friendly metadata fields

This is the SINGLE SOURCE OF TRUTH for all signal publishing to Redis Streams.
All code that publishes signals MUST use this DTO.

Usage:
    from models.canonical_signal_dto import CanonicalSignalDTO, create_canonical_signal

    signal = create_canonical_signal(
        pair="BTC/USD",
        side="LONG",
        strategy="SCALPER",
        entry_price=50000.0,
        take_profit=52000.0,
        stop_loss=49000.0,
        confidence=0.85,
        mode="paper",
        timeframe="5m",
    )

    # Publish to Redis
    redis_payload = signal.to_redis_payload()
    await redis_client.xadd("signals:paper:BTC-USD", redis_payload, maxlen=10000)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# ENUMS (PRD-001 Compliant)
# =============================================================================

class Side(str, Enum):
    """PRD-001 Side enum: LONG or SHORT"""
    LONG = "LONG"
    SHORT = "SHORT"


class Strategy(str, Enum):
    """PRD-001 Strategy enum"""
    SCALPER = "SCALPER"
    TREND = "TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"


class Regime(str, Enum):
    """PRD-001 Regime enum"""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"


class MACDSignal(str, Enum):
    """PRD-001 MACD signal enum"""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


# =============================================================================
# CANONICAL SIGNAL DTO
# =============================================================================

class CanonicalSignalDTO(BaseModel):
    """
    Canonical Signal DTO - Unified schema for bot, API, and frontend.

    Combines:
    - PRD-001 fields (signal_id, pair, side, strategy, regime, entry_price, etc.)
    - PRD-002 API-compatible aliases (id, symbol, signal_type, price)
    - PRD-003 UI-friendly fields (strategy_label, timeframe_label, mode, risk_reward)

    All fields are included in to_redis_payload() for seamless consumption.
    """

    # =========================================================================
    # PRD-001 Core Fields (Canonical)
    # =========================================================================

    signal_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID v4 signal identifier (PRD-001)"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        description="ISO8601 UTC timestamp (PRD-001)"
    )
    pair: str = Field(description="Trading pair (e.g., BTC/USD) - PRD-001")
    side: Side = Field(description="Trade direction (LONG or SHORT) - PRD-001")
    strategy: Strategy = Field(description="Strategy that generated signal - PRD-001")
    regime: Regime = Field(description="Current market regime - PRD-001")
    entry_price: float = Field(gt=0, description="Entry price - PRD-001")
    take_profit: float = Field(gt=0, description="Take profit price - PRD-001")
    stop_loss: float = Field(gt=0, description="Stop loss price - PRD-001")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score [0-1] - PRD-001")
    position_size_usd: float = Field(gt=0, le=2000, description="Position size in USD - PRD-001")
    risk_reward_ratio: Optional[float] = Field(None, gt=0, description="Risk/reward ratio (auto-calculated if not provided)")

    # =========================================================================
    # PRD-001 Optional Nested Objects
    # =========================================================================

    # Technical indicators (optional)
    rsi_14: Optional[float] = Field(None, ge=0, le=100, description="RSI(14) value")
    macd_signal: Optional[MACDSignal] = Field(None, description="MACD signal")
    atr_14: Optional[float] = Field(None, gt=0, description="ATR(14) value")
    volume_ratio: Optional[float] = Field(None, gt=0, description="Volume ratio vs average")

    # Metadata (optional)
    model_version: Optional[str] = Field(None, description="ML model version")
    backtest_sharpe: Optional[float] = Field(None, description="Backtest Sharpe ratio")
    latency_ms: Optional[int] = Field(None, ge=0, description="Processing latency in ms")

    # =========================================================================
    # PRD-003 UI-Friendly Fields (Week 2 Addition)
    # =========================================================================

    strategy_label: Optional[str] = Field(
        None,
        description="Human-readable strategy label (e.g., 'Scalper v2', 'Trend Follower') - UI display"
    )
    timeframe: Optional[str] = Field(
        None,
        description="Signal timeframe (e.g., '5m', '15s', '1h') - UI filtering"
    )
    mode: Optional[Literal["paper", "live"]] = Field(
        None,
        description="Trading mode (paper/live) - UI display"
    )

    class Config:
        use_enum_values = True
        frozen = False  # Allow mutation for calculated fields

    @field_validator("pair")
    @classmethod
    def normalize_pair(cls, v: str) -> str:
        """Normalize pair to use forward slash (BTC/USD)"""
        return v.replace("-", "/").upper()

    @model_validator(mode="after")
    def validate_and_calculate(self):
        """Validate price relationships and calculate risk_reward_ratio if not provided"""
        # Validate SL/TP vs entry based on side
        if self.side == Side.LONG:
            if self.take_profit <= self.entry_price:
                raise ValueError(
                    f"LONG signal: take_profit ({self.take_profit}) must be > entry_price ({self.entry_price})"
                )
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    f"LONG signal: stop_loss ({self.stop_loss}) must be < entry_price ({self.entry_price})"
                )
            # Calculate risk/reward ratio if not provided
            if self.risk_reward_ratio is None:
                risk = abs(self.entry_price - self.stop_loss)
                reward = abs(self.take_profit - self.entry_price)
                if risk > 0:
                    self.risk_reward_ratio = reward / risk
        elif self.side == Side.SHORT:
            if self.take_profit >= self.entry_price:
                raise ValueError(
                    f"SHORT signal: take_profit ({self.take_profit}) must be < entry_price ({self.entry_price})"
                )
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    f"SHORT signal: stop_loss ({self.stop_loss}) must be > entry_price ({self.entry_price})"
                )
            # Calculate risk/reward ratio if not provided
            if self.risk_reward_ratio is None:
                risk = abs(self.stop_loss - self.entry_price)
                reward = abs(self.entry_price - self.take_profit)
                if risk > 0:
                    self.risk_reward_ratio = reward / risk

        # Auto-generate strategy_label if not provided
        if self.strategy_label is None:
            strategy_map = {
                Strategy.SCALPER: "Scalper",
                Strategy.TREND: "Trend Follower",
                Strategy.MEAN_REVERSION: "Mean Reversion",
                Strategy.BREAKOUT: "Breakout",
            }
            self.strategy_label = strategy_map.get(self.strategy, str(self.strategy))

        return self

    def to_redis_payload(self) -> Dict[str, bytes]:
        """
        Convert to Redis XADD payload with all fields as string values encoded to bytes.

        Includes:
        - PRD-001 canonical fields
        - PRD-002 API-compatible aliases (id, symbol, signal_type, price)
        - PRD-003 UI-friendly fields
        - All nested fields flattened

        Returns:
            Dictionary with string keys and bytes values, ready for Redis XADD

        Example:
            >>> signal = CanonicalSignalDTO(...)
            >>> payload = signal.to_redis_payload()
            >>> await redis_client.xadd("signals:paper:BTC-USD", payload, maxlen=10000)
        """
        result: Dict[str, bytes] = {}

        # PRD-001 Core Fields
        result["signal_id"] = str(self.signal_id).encode()
        result["timestamp"] = str(self.timestamp).encode()
        result["pair"] = str(self.pair).encode()
        result["side"] = str(self.side).encode()
        result["strategy"] = str(self.strategy).encode()
        result["regime"] = str(self.regime).encode()
        result["entry_price"] = str(self.entry_price).encode()
        result["take_profit"] = str(self.take_profit).encode()
        result["stop_loss"] = str(self.stop_loss).encode()
        result["confidence"] = str(self.confidence).encode()
        result["position_size_usd"] = str(self.position_size_usd).encode()

        if self.risk_reward_ratio is not None:
            result["risk_reward_ratio"] = str(self.risk_reward_ratio).encode()

        # PRD-002 API-Compatible Aliases
        result["id"] = str(self.signal_id).encode()  # API expects "id" not "signal_id"
        result["symbol"] = self._get_api_symbol().encode()  # API expects "BTCUSDT" format
        result["signal_type"] = str(self.side).encode()  # API expects "signal_type" not "side"
        result["price"] = str(self.entry_price).encode()  # API expects "price" not "entry_price"

        # PRD-001 Optional Indicators (flattened)
        if self.rsi_14 is not None:
            result["rsi_14"] = str(self.rsi_14).encode()
        if self.macd_signal is not None:
            result["macd_signal"] = str(self.macd_signal).encode()
        if self.atr_14 is not None:
            result["atr_14"] = str(self.atr_14).encode()
        if self.volume_ratio is not None:
            result["volume_ratio"] = str(self.volume_ratio).encode()

        # PRD-001 Optional Metadata (flattened)
        if self.model_version is not None:
            result["model_version"] = str(self.model_version).encode()
        if self.backtest_sharpe is not None:
            result["backtest_sharpe"] = str(self.backtest_sharpe).encode()
        if self.latency_ms is not None:
            result["latency_ms"] = str(self.latency_ms).encode()

        # PRD-003 UI-Friendly Fields
        if self.strategy_label is not None:
            result["strategy_label"] = str(self.strategy_label).encode()
        if self.timeframe is not None:
            result["timeframe"] = str(self.timeframe).encode()
        if self.mode is not None:
            result["mode"] = str(self.mode).encode()

        return result

    def _get_api_symbol(self) -> str:
        """
        Convert pair to API-compatible symbol format.

        PRD-002 expects: "BTCUSDT", "ETHUSDT", etc.
        PRD-001 uses: "BTC/USD", "ETH/USD", etc.

        Returns:
            API-compatible symbol (e.g., "BTC/USD" -> "BTCUSDT")
        """
        # Normalize: BTC/USD -> BTCUSDT, ETH/USD -> ETHUSDT
        normalized = self.pair.replace("/", "").replace("-", "")
        # If ends with USD, replace with USDT for API compatibility
        if normalized.endswith("USD"):
            return normalized.replace("USD", "USDT")
        # If already has USDT or other format, return as-is
        return normalized

    def get_stream_key(self, mode: Optional[Literal["paper", "live"]] = None) -> str:
        """
        Get Redis stream key for this signal.

        PRD-001 Section 2.2: Stream pattern is signals:{mode}:<PAIR>
        Uses dash instead of slash for stream key safety.

        Args:
            mode: Trading mode (defaults to self.mode if set)

        Returns:
            Stream key (e.g., "signals:paper:BTC-USD")
        """
        use_mode = mode or self.mode or "paper"
        # Convert pair format: BTC/USD -> BTC-USD for Redis stream safety
        safe_pair = self.pair.replace("/", "-")
        return f"signals:{use_mode}:{safe_pair}"


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_canonical_signal(
    pair: str,
    side: Literal["LONG", "SHORT"],
    strategy: Literal["SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT"],
    entry_price: float,
    take_profit: float,
    stop_loss: float,
    confidence: float,
    mode: Literal["paper", "live"] = "paper",
    regime: Optional[Literal["TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE"]] = None,
    position_size_usd: float = 100.0,
    timeframe: Optional[str] = None,
    strategy_label: Optional[str] = None,
    # Optional indicators
    rsi_14: Optional[float] = None,
    macd_signal: Optional[Literal["BULLISH", "BEARISH", "NEUTRAL"]] = None,
    atr_14: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    # Optional metadata
    model_version: Optional[str] = None,
    backtest_sharpe: Optional[float] = None,
    latency_ms: Optional[int] = None,
) -> CanonicalSignalDTO:
    """
    Convenience function to create canonical signal with auto-generated ID and timestamp.

    Args:
        pair: Trading pair (e.g., "BTC/USD")
        side: Trade direction ("LONG" or "SHORT")
        strategy: Strategy name
        entry_price: Entry price
        take_profit: Take profit price
        stop_loss: Stop loss price
        confidence: Signal confidence [0-1]
        mode: Trading mode (paper or live)
        regime: Market regime (defaults to RANGING if not provided)
        position_size_usd: Position size in USD (default 100)
        timeframe: Signal timeframe (e.g., "5m", "15s")
        strategy_label: Human-readable strategy label
        rsi_14: Optional RSI(14) value
        macd_signal: Optional MACD signal
        atr_14: Optional ATR(14) value
        volume_ratio: Optional volume ratio
        model_version: Optional model version
        backtest_sharpe: Optional backtest Sharpe ratio
        latency_ms: Optional processing latency

    Returns:
        Validated CanonicalSignalDTO instance

    Example:
        >>> signal = create_canonical_signal(
        ...     pair="BTC/USD",
        ...     side="LONG",
        ...     strategy="SCALPER",
        ...     entry_price=50000.0,
        ...     take_profit=52000.0,
        ...     stop_loss=49000.0,
        ...     confidence=0.85,
        ...     mode="paper",
        ...     timeframe="5m",
        ... )
    """
    return CanonicalSignalDTO(
        pair=pair,
        side=Side(side),
        strategy=Strategy(strategy),
        regime=Regime(regime) if regime else Regime.RANGING,
        entry_price=entry_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
        confidence=confidence,
        position_size_usd=position_size_usd,
        mode=mode,
        timeframe=timeframe,
        strategy_label=strategy_label,
        rsi_14=rsi_14,
        macd_signal=MACDSignal(macd_signal) if macd_signal else None,
        atr_14=atr_14,
        volume_ratio=volume_ratio,
        model_version=model_version,
        backtest_sharpe=backtest_sharpe,
        latency_ms=latency_ms,
    )


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "CanonicalSignalDTO",
    "Side",
    "Strategy",
    "Regime",
    "MACDSignal",
    "create_canonical_signal",
]


