"""
Signal DTO Model (models/signal.py)

Strict Pydantic model for trading signals published to Redis streams.
Contract must remain consistent across bot → signals-api → signals-site.

Per PRD §4:
- Signal fields: id, ts, pair, side, entry, sl, tp, strategy, confidence, mode
- Idempotent ID generation: hash(ts|pair|strategy)
- Strict validation with Pydantic v2
- Deterministic serialization for Redis

HARD REQUIREMENTS:
- Frozen model (immutable)
- Extra fields forbidden
- Strict field validation
- Timestamp in milliseconds (UTC)
- Prices as floats (Redis-compatible)
- Mode: "paper" | "live"
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignalDTO(BaseModel):
    """
    Trading signal data transfer object.

    Contract (PRD §4):
        {
            "id": "<uuid>",
            "ts": 1730000000000,
            "pair": "BTC-USD",
            "side": "long|short",
            "entry": 64321.1,
            "sl": 63500.0,
            "tp": 65500.0,
            "strategy": "trend_follow_v1",
            "confidence": 0.78,
            "mode": "paper|live"
        }

    Attributes:
        id: Idempotent signal ID (hash of ts|pair|strategy)
        ts: Timestamp in milliseconds (UTC)
        pair: Trading pair (e.g., "BTC-USD", "ETH-USD")
        side: Trade direction ("long" or "short")
        entry: Entry price (float)
        sl: Stop loss price (float)
        tp: Take profit price (float)
        strategy: Strategy name (e.g., "momentum_v1")
        confidence: Signal confidence [0, 1] (float)
        mode: Trading mode ("paper" or "live")
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Idempotent signal ID")
    ts: int = Field(ge=0, description="Timestamp in milliseconds (UTC)")
    pair: str = Field(min_length=3, description="Trading pair (e.g., BTC-USD)")
    side: Literal["long", "short"] = Field(description="Trade direction")
    entry: float = Field(gt=0.0, description="Entry price")
    sl: float = Field(gt=0.0, description="Stop loss price")
    tp: float = Field(gt=0.0, description="Take profit price")
    strategy: str = Field(min_length=1, description="Strategy name")
    confidence: float = Field(ge=0.0, le=1.0, description="Signal confidence [0,1]")
    mode: Literal["paper", "live"] = Field(description="Trading mode")

    @field_validator("entry", "sl", "tp")
    @classmethod
    def validate_finite_prices(cls, v: float, info) -> float:
        """Validate prices are finite (not NaN or Inf)"""
        if not (v == v):  # NaN check
            raise ValueError(f"{info.field_name} cannot be NaN")
        if abs(v) == float("inf"):
            raise ValueError(f"{info.field_name} cannot be infinite")
        return v

    def to_dict(self) -> dict:
        """
        Convert to dictionary for Redis serialization.

        Returns:
            Dict with all fields, suitable for JSON serialization
        """
        return self.model_dump()

    def to_json(self) -> str:
        """
        Convert to JSON string for Redis XADD.

        Returns:
            Compact JSON string with sorted keys (deterministic)
        """
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict) -> SignalDTO:
        """
        Create SignalDTO from dictionary.

        Args:
            data: Dictionary with signal fields

        Returns:
            Validated SignalDTO instance

        Raises:
            ValidationError: If data doesn't match schema
        """
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> SignalDTO:
        """
        Create SignalDTO from JSON string.

        Args:
            json_str: JSON string with signal fields

        Returns:
            Validated SignalDTO instance

        Raises:
            ValidationError: If JSON doesn't match schema
        """
        return cls.model_validate_json(json_str)


def generate_signal_id(ts_ms: int, pair: str, strategy: str) -> str:
    """
    Generate idempotent signal ID from timestamp, pair, and strategy.

    Per PRD §4: Idempotent IDs prevent duplicate signal processing.
    Uses SHA256 hash of "ts_ms|pair|strategy" for deterministic IDs.

    Args:
        ts_ms: Timestamp in milliseconds
        pair: Trading pair (e.g., "BTC-USD")
        strategy: Strategy name (e.g., "momentum_v1")

    Returns:
        32-character hex string (first 32 chars of SHA256 hash)

    Example:
        >>> generate_signal_id(1730000000000, "BTC-USD", "momentum_v1")
        'a1b2c3d4e5f6...'
    """
    # Create deterministic string
    components = f"{ts_ms}|{pair}|{strategy}"

    # Hash with SHA256
    hash_obj = hashlib.sha256(components.encode("utf-8"))

    # Return first 32 characters
    return hash_obj.hexdigest()[:32]


def create_signal_dto(
    ts_ms: int,
    pair: str,
    side: Literal["long", "short"],
    entry: float,
    sl: float,
    tp: float,
    strategy: str,
    confidence: float,
    mode: Literal["paper", "live"],
) -> SignalDTO:
    """
    Convenience function to create SignalDTO with auto-generated ID.

    Args:
        ts_ms: Timestamp in milliseconds
        pair: Trading pair
        side: Trade direction
        entry: Entry price
        sl: Stop loss price
        tp: Take profit price
        strategy: Strategy name
        confidence: Signal confidence [0,1]
        mode: Trading mode

    Returns:
        Validated SignalDTO instance

    Example:
        >>> signal = create_signal_dto(
        ...     ts_ms=1730000000000,
        ...     pair="BTC-USD",
        ...     side="long",
        ...     entry=50000.0,
        ...     sl=49000.0,
        ...     tp=52000.0,
        ...     strategy="momentum_v1",
        ...     confidence=0.75,
        ...     mode="paper"
        ... )
    """
    signal_id = generate_signal_id(ts_ms, pair, strategy)

    return SignalDTO(
        id=signal_id,
        ts=ts_ms,
        pair=pair,
        side=side,
        entry=entry,
        sl=sl,
        tp=tp,
        strategy=strategy,
        confidence=confidence,
        mode=mode,
    )


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "SignalDTO",
    "generate_signal_id",
    "create_signal_dto",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Validate SignalDTO functionality"""
    import sys

    print("=== SignalDTO Self-Check ===\n")

    # Test 1: Create signal with auto-generated ID
    print("Test 1: Create signal with auto-generated ID")
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    signal = create_signal_dto(
        ts_ms=ts_ms,
        pair="BTC-USD",
        side="long",
        entry=50000.0,
        sl=49000.0,
        tp=52000.0,
        strategy="momentum_v1",
        confidence=0.75,
        mode="paper",
    )
    print(f"  Signal ID: {signal.id}")
    print(f"  Pair: {signal.pair}")
    print(f"  Side: {signal.side}")
    print(f"  Entry: ${signal.entry}")
    assert signal.id == generate_signal_id(ts_ms, "BTC-USD", "momentum_v1")
    print("  PASS\n")

    # Test 2: Idempotent ID generation
    print("Test 2: Idempotent ID generation")
    id1 = generate_signal_id(1730000000000, "BTC-USD", "momentum_v1")
    id2 = generate_signal_id(1730000000000, "BTC-USD", "momentum_v1")
    assert id1 == id2, "IDs should be deterministic"
    print(f"  ID: {id1}")
    print("  PASS\n")

    # Test 3: Different inputs produce different IDs
    print("Test 3: Different inputs produce different IDs")
    id_btc = generate_signal_id(1730000000000, "BTC-USD", "momentum_v1")
    id_eth = generate_signal_id(1730000000000, "ETH-USD", "momentum_v1")
    id_diff_ts = generate_signal_id(1730000000001, "BTC-USD", "momentum_v1")
    assert id_btc != id_eth, "Different pairs should have different IDs"
    assert id_btc != id_diff_ts, "Different timestamps should have different IDs"
    print("  PASS\n")

    # Test 4: JSON serialization
    print("Test 4: JSON serialization")
    json_str = signal.to_json()
    print(f"  JSON: {json_str[:80]}...")
    assert isinstance(json_str, str)
    assert "BTC-USD" in json_str
    print("  PASS\n")

    # Test 5: JSON deserialization
    print("Test 5: JSON deserialization")
    signal_restored = SignalDTO.from_json(json_str)
    assert signal_restored.id == signal.id
    assert signal_restored.pair == signal.pair
    assert signal_restored.entry == signal.entry
    print("  PASS\n")

    # Test 6: Dict round-trip
    print("Test 6: Dict round-trip")
    signal_dict = signal.to_dict()
    signal_from_dict = SignalDTO.from_dict(signal_dict)
    assert signal_from_dict.id == signal.id
    assert signal_from_dict.ts == signal.ts
    print("  PASS\n")

    # Test 7: Validation (invalid side)
    print("Test 7: Validation (invalid side)")
    try:
        SignalDTO(
            id="test",
            ts=1730000000000,
            pair="BTC-USD",
            side="invalid",  # Invalid side
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test",
            confidence=0.75,
            mode="paper",
        )
        print("  FAIL: Should have raised ValidationError")
        sys.exit(1)
    except Exception:
        print("  PASS (ValidationError raised as expected)\n")

    # Test 8: Validation (invalid confidence)
    print("Test 8: Validation (invalid confidence)")
    try:
        create_signal_dto(
            ts_ms=1730000000000,
            pair="BTC-USD",
            side="long",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test",
            confidence=1.5,  # > 1.0
            mode="paper",
        )
        print("  FAIL: Should have raised ValidationError")
        sys.exit(1)
    except Exception:
        print("  PASS (ValidationError raised as expected)\n")

    # Test 9: Frozen model (immutability)
    print("Test 9: Frozen model (immutability)")
    try:
        signal.confidence = 0.9  # Should fail
        print("  FAIL: Should not allow mutation")
        sys.exit(1)
    except Exception:
        print("  PASS (Model is frozen)\n")

    # Test 10: Extra fields forbidden
    print("Test 10: Extra fields forbidden")
    try:
        SignalDTO(
            id="test",
            ts=1730000000000,
            pair="BTC-USD",
            side="long",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test",
            confidence=0.75,
            mode="paper",
            extra_field="not_allowed",  # Extra field
        )
        print("  FAIL: Should have rejected extra field")
        sys.exit(1)
    except Exception:
        print("  PASS (Extra fields forbidden)\n")

    print("=== All Self-Checks PASSED ===")
