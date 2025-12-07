"""
Unified Signal Schema with Idempotency (signals/schema.py)

Standardized signal schema for crypto-ai-bot → signals-api → signals-site pipeline.
Combines best aspects of models/signal_dto.py and models/prd_signal_schema.py.

DESIGN PRINCIPLES:
- Idempotent signal IDs (hash of ts_ms|pair|strategy)
- Immutable frozen model (Pydantic v2)
- Strict validation
- Compatible with both Redis XADD and JSON serialization
- Supports paper and live modes
- Per-pair stream sharding (signals:live:<PAIR>)

CONTRACT:
    {
        "id": "<32-char-hash>",
        "ts_ms": 1730000000000,
        "pair": "BTC/USD",
        "side": "long" | "short",
        "entry": 50000.0,
        "sl": 49000.0,
        "tp": 52000.0,
        "strategy": "momentum_v1",
        "confidence": 0.85,
        "mode": "paper" | "live"
    }
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Literal, Dict, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
import orjson


class Signal(BaseModel):
    """
    Standardized trading signal with idempotent ID.

    SCHEMA COMPATIBILITY: This schema matches signals-api SignalDTO exactly.
    - Field names: ts (not ts_ms), pair, side, entry, sl, tp, strategy, confidence, mode
    - Side values: "buy" or "sell" (not "long" or "short")
    - Compatible with both Redis XADD and JSON serialization

    Attributes:
        id: Idempotent signal ID (SHA256 hash of ts|pair|strategy)
        ts: Timestamp in milliseconds (UTC)
        pair: Trading pair (e.g., "BTC/USD", "ETH/USD")
        side: Trade direction ("buy" or "sell") - matches signals-api
        entry: Entry price (float)
        sl: Stop loss price (float)
        tp: Take profit price (float)
        strategy: Strategy name (e.g., "momentum_v1")
        confidence: Signal confidence [0, 1] (float)
        mode: Trading mode ("paper" or "live")
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Idempotent identifier
    id: str = Field(description="Idempotent signal ID (32-char hash)")

    # Timestamp (changed from ts_ms to ts for API compatibility)
    ts: int = Field(ge=0, description="Timestamp in milliseconds (UTC)")

    # Market data
    pair: str = Field(min_length=3, description="Trading pair (e.g., BTC/USD)")
    side: Literal["buy", "sell"] = Field(description="Trade direction (buy or sell)")

    # Execution parameters
    entry: float = Field(gt=0.0, description="Entry price")
    sl: float = Field(gt=0.0, description="Stop loss price")
    tp: float = Field(gt=0.0, description="Take profit price")

    # Metadata
    strategy: str = Field(min_length=1, description="Strategy name")
    confidence: float = Field(ge=0.0, le=1.0, description="Signal confidence [0,1]")
    mode: Literal["paper", "live"] = Field(description="Trading mode")

    @field_validator("entry", "sl", "tp")
    @classmethod
    def validate_finite_prices(cls, v: float, info) -> float:
        """Validate prices are finite (not NaN or Inf)"""
        if v != v:  # NaN check
            raise ValueError(f"{info.field_name} cannot be NaN")
        if abs(v) == float("inf"):
            raise ValueError(f"{info.field_name} cannot be infinite")
        return v

    @field_validator("pair")
    @classmethod
    def normalize_pair(cls, v: str) -> str:
        """Normalize pair format to use forward slash (BTC/USD)"""
        # Replace dash with slash for consistency
        return v.replace("-", "/").upper()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis serialization."""
        return self.model_dump()

    def to_json_bytes(self) -> bytes:
        """Convert to compact JSON bytes using orjson."""
        return orjson.dumps(self.to_dict())

    def to_json_str(self) -> str:
        """Convert to JSON string."""
        return self.to_json_bytes().decode("utf-8")

    def to_redis_dict(self) -> Dict[str, str]:
        """
        Convert to Redis-compatible dictionary with string values.
        Required for Redis XADD which expects all values as strings.
        """
        data = self.to_dict()
        # Convert all values to strings
        return {k: str(v) for k, v in data.items()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Signal:
        """Create Signal from dictionary."""
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str | bytes) -> Signal:
        """Create Signal from JSON string or bytes."""
        if isinstance(json_str, bytes):
            data = orjson.loads(json_str)
        else:
            data = orjson.loads(json_str.encode())
        return cls.from_dict(data)

    def get_stream_key(self) -> str:
        """
        Get Redis stream key for this signal.

        Uses PER-PAIR stream pattern for data separation:
        - signals:paper:<PAIR> (e.g., signals:paper:BTC-USD)
        - signals:live:<PAIR> (e.g., signals:live:BTC-USD)

        This ensures proper data isolation and scalability across trading pairs.
        Each pair gets its own stream for independent consumption.

        Note: Replaces "/" with "-" in pair name for consistent stream naming
        across crypto-ai-bot and signals-api.

        Returns:
            Per-pair stream key (e.g., "signals:paper:BTC-USD")
        """
        # Convert pair format from BTC/USD to BTC-USD for stream keys
        pair_normalized = self.pair.replace("/", "-")
        return f"signals:{self.mode}:{pair_normalized}"


def generate_signal_id(ts: int, pair: str, strategy: str) -> str:
    """
    Generate idempotent signal ID from timestamp, pair, and strategy.

    Uses SHA256 hash of "ts|pair|strategy" for deterministic IDs.
    This prevents duplicate signal processing across the pipeline.

    Args:
        ts: Timestamp in milliseconds
        pair: Trading pair (e.g., "BTC/USD")
        strategy: Strategy name (e.g., "momentum_v1")

    Returns:
        32-character hex string (first 32 chars of SHA256 hash)

    Example:
        >>> generate_signal_id(1730000000000, "BTC/USD", "momentum_v1")
        'a1b2c3d4e5f6...'
    """
    # Normalize pair format
    pair_normalized = pair.replace("-", "/").upper()

    # Create deterministic string
    components = f"{ts}|{pair_normalized}|{strategy}"

    # Hash with SHA256
    hash_obj = hashlib.sha256(components.encode("utf-8"))

    # Return first 32 characters
    return hash_obj.hexdigest()[:32]


def create_signal(
    pair: str,
    side: Literal["buy", "sell"],
    entry: float,
    sl: float,
    tp: float,
    strategy: str,
    confidence: float,
    mode: Literal["paper", "live"],
    ts: int | None = None,
) -> Signal:
    """
    Convenience function to create Signal with auto-generated ID and timestamp.

    SCHEMA COMPATIBILITY: Uses "buy"/"sell" for side (not "long"/"short")
    to match signals-api expectations.

    Args:
        pair: Trading pair (e.g., "BTC/USD")
        side: Trade direction ("buy" or "sell")
        entry: Entry price
        sl: Stop loss price
        tp: Take profit price
        strategy: Strategy name
        confidence: Signal confidence [0,1]
        mode: Trading mode ("paper" or "live")
        ts: Optional timestamp in milliseconds (defaults to now)

    Returns:
        Validated Signal instance with auto-generated ID

    Example:
        >>> signal = create_signal(
        ...     pair="BTC/USD",
        ...     side="buy",
        ...     entry=50000.0,
        ...     sl=49000.0,
        ...     tp=52000.0,
        ...     strategy="momentum_v1",
        ...     confidence=0.75,
        ...     mode="paper"
        ... )
    """
    # Generate timestamp if not provided
    if ts is None:
        ts = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Generate idempotent ID
    signal_id = generate_signal_id(ts, pair, strategy)

    return Signal(
        id=signal_id,
        ts=ts,
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
    "Signal",
    "generate_signal_id",
    "create_signal",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Validate Signal functionality"""
    import sys

    print("=" * 70)
    print(" " * 20 + "SIGNAL SCHEMA SELF-CHECK")
    print("=" * 70)

    # Test 1: Create signal with auto-generated ID
    print("\nTest 1: Create signal with auto-generated ID")
    signal = create_signal(
        pair="BTC/USD",
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
    print(f"  Stream key: {signal.get_stream_key()}")
    assert len(signal.id) == 32
    print("  PASS")

    # Test 2: Idempotent ID generation
    print("\nTest 2: Idempotent ID generation")
    id1 = generate_signal_id(1730000000000, "BTC/USD", "momentum_v1")
    id2 = generate_signal_id(1730000000000, "BTC/USD", "momentum_v1")
    assert id1 == id2
    print(f"  ID: {id1}")
    print("  PASS")

    # Test 3: Pair normalization
    print("\nTest 3: Pair normalization")
    signal_slash = create_signal(
        pair="BTC/USD", side="long", entry=50000.0, sl=49000.0, tp=52000.0,
        strategy="test", confidence=0.5, mode="paper"
    )
    signal_dash = create_signal(
        pair="BTC-USD", side="long", entry=50000.0, sl=49000.0, tp=52000.0,
        strategy="test", confidence=0.5, mode="paper"
    )
    assert signal_slash.pair == "BTC/USD"
    assert signal_dash.pair == "BTC/USD"
    print("  PASS")

    # Test 4: JSON serialization with orjson
    print("\nTest 4: JSON serialization with orjson")
    json_bytes = signal.to_json_bytes()
    assert isinstance(json_bytes, bytes)
    json_str = signal.to_json_str()
    assert isinstance(json_str, str)
    assert "BTC/USD" in json_str
    print(f"  JSON size: {len(json_bytes)} bytes")
    print("  PASS")

    # Test 5: JSON deserialization
    print("\nTest 5: JSON deserialization")
    signal_restored = Signal.from_json(json_bytes)
    assert signal_restored.id == signal.id
    assert signal_restored.pair == signal.pair
    print("  PASS")

    # Test 6: Redis dict format
    print("\nTest 6: Redis dict format (all string values)")
    redis_dict = signal.to_redis_dict()
    assert all(isinstance(v, str) for v in redis_dict.values())
    assert redis_dict["pair"] == "BTC/USD"
    assert redis_dict["entry"] == "50000.0"
    print("  PASS")

    # Test 7: Stream key generation
    print("\nTest 7: Stream key generation")
    assert signal.get_stream_key() == "signals:paper:BTC-USD"
    live_signal = create_signal(
        pair="ETH/USD", side="short", entry=3000.0, sl=3100.0, tp=2900.0,
        strategy="test", confidence=0.8, mode="live"
    )
    assert live_signal.get_stream_key() == "signals:live:ETH-USD"
    print("  PASS")

    # Test 8: Validation (invalid confidence)
    print("\nTest 8: Validation (confidence > 1.0 rejected)")
    try:
        create_signal(
            pair="BTC/USD", side="long", entry=50000.0, sl=49000.0, tp=52000.0,
            strategy="test", confidence=1.5, mode="paper"
        )
        print("  FAIL: Should have raised ValidationError")
        sys.exit(1)
    except Exception:
        print("  PASS")

    # Test 9: Frozen model (immutability)
    print("\nTest 9: Frozen model (immutability)")
    try:
        signal.confidence = 0.9
        print("  FAIL: Should not allow mutation")
        sys.exit(1)
    except Exception:
        print("  PASS")

    # Test 10: Extra fields forbidden
    print("\nTest 10: Extra fields forbidden")
    try:
        Signal(
            id="test",
            ts_ms=1730000000000,
            pair="BTC/USD",
            side="long",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test",
            confidence=0.75,
            mode="paper",
            extra_field="not_allowed",
        )
        print("  FAIL: Should have rejected extra field")
        sys.exit(1)
    except Exception:
        print("  PASS")

    print("\n" + "=" * 70)
    print("[OK] All Self-Checks PASSED")
    print("=" * 70)
