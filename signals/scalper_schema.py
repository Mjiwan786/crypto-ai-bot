"""
Scalper Signal Schema (Pydantic v2)
====================================

Production-ready signal schema for high-frequency scalping with:
- Strict validation
- Stable JSON ordering
- Stream key generation
- Error handling and alerting
- Trace ID for debugging

STREAM KEYS:
- Signals: signals:<symbol>:<tf> (e.g., signals:BTC/USD:15s)
- Metrics: metrics:scalper

SCHEMA:
{
  "ts_exchange": 1736000000000,     # Exchange timestamp (ms)
  "ts_server": 1736000000100,       # Server timestamp (ms)
  "symbol": "BTC/USD",              # Trading pair
  "timeframe": "15s",               # Timeframe (15s, 1m, 5m)
  "side": "long",                   # Trade direction (long/short)
  "confidence": 0.85,               # Model confidence [0,1]
  "entry": 45234.50,                # Entry price
  "stop": 45000.00,                 # Stop loss price
  "tp": 45500.00,                   # Take profit price
  "model": "momentum_v1",           # Model/strategy name
  "trace_id": "abc123..."           # Unique trace ID for debugging
}
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

import orjson
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


# =============================================================================
# Signal Schema (Pydantic v2)
# =============================================================================


class ScalperSignal(BaseModel):
    """
    Scalper signal schema with strict validation.

    All signals must pass validation before publishing to Redis.
    Invalid signals are dropped and logged.
    """

    model_config = ConfigDict(
        frozen=True,  # Immutable
        extra="forbid",  # No extra fields
        validate_assignment=True,  # Validate on assignment
        str_strip_whitespace=True,  # Strip whitespace from strings
    )

    # Timestamps (milliseconds since epoch)
    ts_exchange: int = Field(
        ge=0,
        description="Exchange timestamp in milliseconds (when signal generated)",
    )
    ts_server: int = Field(
        ge=0,
        description="Server timestamp in milliseconds (when signal received)",
    )

    # Market data
    symbol: str = Field(
        min_length=3,
        max_length=20,
        description="Trading pair (e.g., BTC/USD, ETH/USD)",
    )
    timeframe: str = Field(
        min_length=2,
        max_length=10,
        description="Timeframe (e.g., 15s, 1m, 5m)",
    )

    # Trade parameters
    side: Literal["long", "short"] = Field(description="Trade direction")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model confidence score [0, 1]",
    )

    # Price levels
    entry: float = Field(
        gt=0.0,
        description="Entry price (must be positive)",
    )
    stop: float = Field(
        gt=0.0,
        description="Stop loss price (must be positive)",
    )
    tp: float = Field(
        gt=0.0,
        description="Take profit price (must be positive)",
    )

    # Metadata
    model: str = Field(
        min_length=1,
        max_length=50,
        description="Model/strategy name (e.g., momentum_v1)",
    )
    trace_id: str = Field(
        min_length=8,
        max_length=64,
        description="Unique trace ID for debugging",
    )

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        """Normalize symbol format (BTC/USD)"""
        # Replace common separators with /
        v = v.replace("-", "/").replace("_", "/")
        # Uppercase
        v = v.upper()
        # Validate format
        if "/" not in v:
            raise ValueError(f"Symbol must contain '/': {v}")
        return v

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v: str) -> str:
        """Validate timeframe format"""
        v = v.lower()
        # Common timeframes
        valid_tfs = [
            "5s", "10s", "15s", "30s",
            "1m", "2m", "5m", "10m", "15m", "30m",
            "1h", "2h", "4h", "6h", "12h",
            "1d", "1w"
        ]
        if v not in valid_tfs:
            raise ValueError(f"Invalid timeframe: {v}. Must be one of {valid_tfs}")
        return v

    @field_validator("entry", "stop", "tp")
    @classmethod
    def validate_price(cls, v: float, info) -> float:
        """Validate price is finite (not NaN or Inf)"""
        if v != v:  # NaN check
            raise ValueError(f"{info.field_name} cannot be NaN")
        if abs(v) == float("inf"):
            raise ValueError(f"{info.field_name} cannot be infinite")
        return v

    @field_validator("ts_exchange", "ts_server")
    @classmethod
    def validate_timestamp(cls, v: int, info) -> int:
        """Validate timestamp is reasonable"""
        # Check not in distant past (before 2020)
        min_ts = 1577836800000  # 2020-01-01
        if v < min_ts:
            raise ValueError(f"{info.field_name} too old: {v} < {min_ts}")

        # Check not too far in future (>1 hour)
        max_ts = int(time.time() * 1000) + 3600000
        if v > max_ts:
            raise ValueError(f"{info.field_name} too far in future: {v} > {max_ts}")

        return v

    def validate_logic(self) -> None:
        """Validate signal logic (e.g., stop/tp placement)"""
        # Validate stop loss is on correct side
        if self.side == "long":
            if self.stop >= self.entry:
                raise ValueError(
                    f"Long stop must be below entry: stop={self.stop}, entry={self.entry}"
                )
            if self.tp <= self.entry:
                raise ValueError(
                    f"Long TP must be above entry: tp={self.tp}, entry={self.entry}"
                )
        else:  # short
            if self.stop <= self.entry:
                raise ValueError(
                    f"Short stop must be above entry: stop={self.stop}, entry={self.entry}"
                )
            if self.tp >= self.entry:
                raise ValueError(
                    f"Short TP must be below entry: tp={self.tp}, entry={self.entry}"
                )

        # Validate server timestamp is after exchange timestamp
        if self.ts_server < self.ts_exchange:
            raise ValueError(
                f"Server timestamp cannot be before exchange timestamp: "
                f"ts_server={self.ts_server} < ts_exchange={self.ts_exchange}"
            )

    def get_stream_key(self) -> str:
        """
        Get Redis stream key for this signal.

        Format: signals:<symbol>:<timeframe>
        Example: signals:BTC/USD:15s

        Returns:
            Stream key string
        """
        # Replace / with - for Redis key compatibility
        symbol_safe = self.symbol.replace("/", "-")
        return f"signals:{symbol_safe}:{self.timeframe}"

    def calculate_freshness_metrics(self, now_server_ms: Optional[int] = None) -> Dict[str, int]:
        """
        Calculate freshness metrics for this signal.

        Metrics:
        - event_age_ms: Time elapsed since exchange event (now - ts_exchange)
        - ingest_lag_ms: Processing lag (now - ts_server)
        - exchange_server_delta_ms: Clock drift indicator (ts_server - ts_exchange)

        Args:
            now_server_ms: Current server time in milliseconds (defaults to now)

        Returns:
            Dictionary with freshness metrics
        """
        import time
        if now_server_ms is None:
            now_server_ms = int(time.time() * 1000)

        event_age_ms = now_server_ms - self.ts_exchange
        ingest_lag_ms = now_server_ms - self.ts_server
        exchange_server_delta_ms = self.ts_server - self.ts_exchange

        return {
            "event_age_ms": event_age_ms,
            "ingest_lag_ms": ingest_lag_ms,
            "exchange_server_delta_ms": exchange_server_delta_ms,
        }

    def check_clock_drift(self, threshold_ms: int = 2000) -> tuple[bool, Optional[str]]:
        """
        Check for clock drift between exchange and server timestamps.

        Clock drift indicates potential issues:
        - Exchange clock ahead of server clock
        - Network time synchronization issues
        - Timestamp manipulation

        Args:
            threshold_ms: Maximum acceptable drift in milliseconds (default: 2000ms = 2s)

        Returns:
            Tuple of (has_drift, warning_message)
            - has_drift: True if drift exceeds threshold
            - warning_message: Description of the issue or None
        """
        drift_ms = abs(self.ts_exchange - self.ts_server)

        if drift_ms > threshold_ms:
            if self.ts_exchange > self.ts_server:
                # Exchange timestamp is ahead of server timestamp
                return True, (
                    f"Clock drift detected: Exchange timestamp is {drift_ms}ms ahead of server "
                    f"(ts_exchange={self.ts_exchange}, ts_server={self.ts_server})"
                )
            else:
                # Server timestamp is significantly ahead of exchange timestamp
                return True, (
                    f"Clock drift detected: Server timestamp is {drift_ms}ms ahead of exchange "
                    f"(ts_exchange={self.ts_exchange}, ts_server={self.ts_server})"
                )

        return False, None

    def to_dict_ordered(self) -> Dict:
        """
        Convert to dictionary with stable field ordering.

        Field order matches schema definition for consistent JSON output.

        Returns:
            Ordered dictionary
        """
        return {
            "ts_exchange": self.ts_exchange,
            "ts_server": self.ts_server,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "side": self.side,
            "confidence": self.confidence,
            "entry": self.entry,
            "stop": self.stop,
            "tp": self.tp,
            "model": self.model,
            "trace_id": self.trace_id,
        }

    def to_json_bytes(self) -> bytes:
        """
        Convert to JSON bytes with stable ordering.

        Uses orjson with OPT_SORT_KEYS for deterministic output.

        Returns:
            JSON bytes
        """
        data = self.to_dict_ordered()
        # Use orjson with sorted keys for stable output
        return orjson.dumps(data, option=orjson.OPT_SORT_KEYS)

    def to_json_str(self) -> str:
        """Convert to JSON string with stable ordering"""
        return self.to_json_bytes().decode("utf-8")

    def to_redis_dict(self) -> Dict[str, str]:
        """
        Convert to Redis-compatible dictionary (all string values).

        Required for Redis XADD which expects string values.

        Returns:
            Dictionary with string values
        """
        data = self.to_dict_ordered()
        return {k: str(v) for k, v in data.items()}

    @classmethod
    def from_dict(cls, data: Dict) -> ScalperSignal:
        """Create signal from dictionary with validation"""
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_bytes: bytes | str) -> ScalperSignal:
        """Create signal from JSON with validation"""
        if isinstance(json_bytes, bytes):
            data = orjson.loads(json_bytes)
        else:
            data = orjson.loads(json_bytes.encode())
        return cls.from_dict(data)


# =============================================================================
# Signal Creation Helpers
# =============================================================================


def generate_trace_id() -> str:
    """
    Generate unique trace ID for signal tracking.

    Uses UUID4 for uniqueness with timestamp prefix.

    Returns:
        Trace ID string (e.g., "1736000000-abc123...")
    """
    ts = int(time.time())
    unique = uuid.uuid4().hex[:12]
    return f"{ts}-{unique}"


def create_scalper_signal(
    symbol: str,
    timeframe: str,
    side: Literal["long", "short"],
    entry: float,
    stop: float,
    tp: float,
    confidence: float,
    model: str,
    ts_exchange: Optional[int] = None,
    ts_server: Optional[int] = None,
    trace_id: Optional[str] = None,
) -> ScalperSignal:
    """
    Create and validate a scalper signal.

    Args:
        symbol: Trading pair (e.g., BTC/USD)
        timeframe: Timeframe (e.g., 15s, 1m)
        side: Trade direction (long/short)
        entry: Entry price
        stop: Stop loss price
        tp: Take profit price
        confidence: Model confidence [0, 1]
        model: Model/strategy name
        ts_exchange: Exchange timestamp (ms), defaults to now
        ts_server: Server timestamp (ms), defaults to now
        trace_id: Trace ID, auto-generated if not provided

    Returns:
        Validated ScalperSignal

    Raises:
        ValidationError: If signal is invalid

    Example:
        >>> signal = create_scalper_signal(
        ...     symbol="BTC/USD",
        ...     timeframe="15s",
        ...     side="long",
        ...     entry=45234.50,
        ...     stop=45000.00,
        ...     tp=45500.00,
        ...     confidence=0.85,
        ...     model="momentum_v1"
        ... )
    """
    # Generate timestamps if not provided
    now_ms = int(time.time() * 1000)

    if ts_exchange is None:
        ts_exchange = now_ms

    if ts_server is None:
        ts_server = now_ms

    if trace_id is None:
        trace_id = generate_trace_id()

    # Create signal with validation
    signal = ScalperSignal(
        ts_exchange=ts_exchange,
        ts_server=ts_server,
        symbol=symbol,
        timeframe=timeframe,
        side=side,
        confidence=confidence,
        entry=entry,
        stop=stop,
        tp=tp,
        model=model,
        trace_id=trace_id,
    )

    # Validate logic
    signal.validate_logic()

    return signal


# =============================================================================
# Signal Validation & Error Handling
# =============================================================================


class SignalValidationError(Exception):
    """Signal validation error"""

    def __init__(self, message: str, signal_data: Dict):
        self.message = message
        self.signal_data = signal_data
        super().__init__(message)


def validate_signal_safe(signal_data: Dict) -> tuple[Optional[ScalperSignal], Optional[str]]:
    """
    Safely validate signal data without raising exceptions.

    Args:
        signal_data: Signal data dictionary

    Returns:
        (signal, error_message)
        - If valid: (ScalperSignal, None)
        - If invalid: (None, error_message)

    Example:
        >>> signal, error = validate_signal_safe(data)
        >>> if signal:
        ...     # Process valid signal
        >>> else:
        ...     # Log error
        ...     logger.error(f"Invalid signal: {error}")
    """
    try:
        # Validate schema
        signal = ScalperSignal.from_dict(signal_data)

        # Validate logic
        signal.validate_logic()

        return signal, None

    except Exception as e:
        error_msg = f"Signal validation failed: {e}"
        return None, error_msg


def drop_invalid_signal(signal_data: Dict, error: str) -> None:
    """
    Drop invalid signal and log alert.

    Args:
        signal_data: Invalid signal data
        error: Error message

    Logs critical alert for monitoring.
    """
    logger.critical("[ALERT] INVALID SIGNAL DROPPED")
    logger.critical(f"   Error: {error}")
    logger.critical(f"   Data: {signal_data}")

    # TODO: Send alert to monitoring system (PagerDuty, Slack, etc.)
    # Example:
    # alert_service.send_alert(
    #     severity="high",
    #     title="Invalid Signal Dropped",
    #     message=error,
    #     data=signal_data
    # )


# =============================================================================
# Stream Key Helpers
# =============================================================================


def get_signal_stream_key(symbol: str, timeframe: str) -> str:
    """
    Get signal stream key.

    Args:
        symbol: Trading pair (e.g., BTC/USD)
        timeframe: Timeframe (e.g., 15s)

    Returns:
        Stream key (e.g., signals:BTC-USD:15s)
    """
    symbol_safe = symbol.replace("/", "-").upper()
    tf_safe = timeframe.lower()
    return f"signals:{symbol_safe}:{tf_safe}"


def get_metrics_stream_key() -> str:
    """Get metrics stream key"""
    return "metrics:scalper"


def get_all_signal_stream_keys(symbols: List[str], timeframes: List[str]) -> List[str]:
    """
    Get all signal stream keys for given symbols and timeframes.

    Args:
        symbols: List of trading pairs
        timeframes: List of timeframes

    Returns:
        List of stream keys

    Example:
        >>> keys = get_all_signal_stream_keys(
        ...     symbols=["BTC/USD", "ETH/USD"],
        ...     timeframes=["15s", "1m"]
        ... )
        >>> keys
        ['signals:BTC-USD:15s', 'signals:BTC-USD:1m', 'signals:ETH-USD:15s', ...]
    """
    keys = []
    for symbol in symbols:
        for tf in timeframes:
            keys.append(get_signal_stream_key(symbol, tf))
    return keys


# =============================================================================
# Public API
# =============================================================================


__all__ = [
    "ScalperSignal",
    "create_scalper_signal",
    "generate_trace_id",
    "validate_signal_safe",
    "drop_invalid_signal",
    "get_signal_stream_key",
    "get_metrics_stream_key",
    "get_all_signal_stream_keys",
    "SignalValidationError",
]


# =============================================================================
# Self-Check
# =============================================================================


if __name__ == "__main__":
    """Test signal schema"""
    import sys

    print("=" * 80)
    print(" " * 25 + "SCALPER SIGNAL SCHEMA TEST")
    print("=" * 80)

    # Test 1: Create valid signal
    print("\nTest 1: Create valid long signal")
    try:
        signal = create_scalper_signal(
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            entry=45234.50,
            stop=45000.00,
            tp=45500.00,
            confidence=0.85,
            model="momentum_v1",
        )

        print(f"  [OK] Signal created: {signal.trace_id}")
        print(f"  [OK] Stream key: {signal.get_stream_key()}")

        # Test JSON serialization
        json_str = signal.to_json_str()
        print(f"  [OK] JSON: {json_str[:100]}...")

    except Exception as e:
        print(f"  [FAIL] {e}")
        sys.exit(1)

    # Test 2: Validate signal logic (invalid stop)
    print("\nTest 2: Invalid long signal (stop above entry)")
    try:
        signal = create_scalper_signal(
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            entry=45000.00,
            stop=45500.00,  # Wrong! Stop should be below entry for long
            tp=46000.00,
            confidence=0.75,
            model="test",
        )
        print("  [FAIL] Should have raised error")
        sys.exit(1)
    except ValueError as e:
        print(f"  [OK] Correctly rejected: {e}")

    # Test 3: Symbol normalization
    print("\nTest 3: Symbol normalization")
    try:
        signal1 = create_scalper_signal(
            symbol="BTC/USD", timeframe="15s", side="long",
            entry=45000.0, stop=44900.0, tp=45100.0,
            confidence=0.8, model="test"
        )
        signal2 = create_scalper_signal(
            symbol="btc-usd", timeframe="15s", side="long",
            entry=45000.0, stop=44900.0, tp=45100.0,
            confidence=0.8, model="test"
        )

        assert signal1.symbol == "BTC/USD"
        assert signal2.symbol == "BTC/USD"
        print("  [OK] Symbols normalized correctly")

    except Exception as e:
        print(f"  [FAIL] FAIL: {e}")
        sys.exit(1)

    # Test 4: Invalid timeframe
    print("\nTest 4: Invalid timeframe")
    try:
        signal = create_scalper_signal(
            symbol="BTC/USD",
            timeframe="99s",  # Invalid
            side="long",
            entry=45000.0,
            stop=44900.0,
            tp=45100.0,
            confidence=0.8,
            model="test"
        )
        print("  [FAIL] FAIL: Should have raised error")
        sys.exit(1)
    except ValueError as e:
        print(f"  [OK] Correctly rejected: {e}")

    # Test 5: Safe validation
    print("\nTest 5: Safe validation")
    valid_data = {
        "ts_exchange": int(time.time() * 1000),
        "ts_server": int(time.time() * 1000),
        "symbol": "ETH/USD",
        "timeframe": "1m",
        "side": "short",
        "confidence": 0.75,
        "entry": 3000.0,
        "stop": 3050.0,
        "tp": 2950.0,
        "model": "test_model",
        "trace_id": generate_trace_id(),
    }

    signal, error = validate_signal_safe(valid_data)
    if signal:
        print(f"  [OK] Valid signal: {signal.trace_id}")
    else:
        print(f"  [FAIL] FAIL: {error}")
        sys.exit(1)

    # Test 6: Invalid confidence
    print("\nTest 6: Invalid confidence (>1.0)")
    invalid_data = valid_data.copy()
    invalid_data["confidence"] = 1.5  # Invalid

    signal, error = validate_signal_safe(invalid_data)
    if signal is None:
        print(f"  [OK] Correctly rejected: {error}")
    else:
        print("  [FAIL] FAIL: Should have been rejected")
        sys.exit(1)

    # Test 7: Stream key generation
    print("\nTest 7: Stream key generation")
    keys = get_all_signal_stream_keys(
        symbols=["BTC/USD", "ETH/USD"],
        timeframes=["15s", "1m"]
    )
    expected = [
        "signals:BTC-USD:15s",
        "signals:BTC-USD:1m",
        "signals:ETH-USD:15s",
        "signals:ETH-USD:1m",
    ]

    if keys == expected:
        print(f"  [OK] Stream keys: {keys}")
    else:
        print(f"  [FAIL] FAIL: Expected {expected}, got {keys}")
        sys.exit(1)

    # Test 8: JSON ordering stability
    print("\nTest 8: JSON ordering stability")
    # Create a fresh signal for stability testing
    stability_signal = ScalperSignal(
        ts_exchange=int(time.time() * 1000),
        ts_server=int(time.time() * 1000),
        symbol="BTC/USD",
        timeframe="15s",
        side="long",
        confidence=0.85,
        entry=45000.0,
        stop=44500.0,
        tp=46000.0,
        model="test_model",
        trace_id=generate_trace_id(),
    )
    signal1_json = stability_signal.to_json_str()
    signal2_json = stability_signal.to_json_str()

    if signal1_json == signal2_json:
        print("  [OK] JSON ordering is stable")
    else:
        print("  [FAIL] FAIL: JSON ordering is not stable")
        sys.exit(1)

    # Test 9: Freshness metrics
    print("\nTest 9: Freshness metrics")
    # Create a signal with known timestamps
    now_ms = int(time.time() * 1000)
    past_exchange_ms = now_ms - 5000  # 5 seconds ago
    past_server_ms = now_ms - 3000    # 3 seconds ago

    freshness_signal = ScalperSignal(
        ts_exchange=past_exchange_ms,
        ts_server=past_server_ms,
        symbol="BTC/USD",
        timeframe="15s",
        side="long",
        confidence=0.85,
        entry=45000.0,
        stop=44500.0,
        tp=46000.0,
        model="test_model",
        trace_id=generate_trace_id(),
    )

    metrics = freshness_signal.calculate_freshness_metrics(now_server_ms=now_ms)

    # Verify metrics are calculated correctly (with some tolerance for execution time)
    if 4900 <= metrics["event_age_ms"] <= 5100:  # ~5000ms ± 100ms
        print(f"  [OK] event_age_ms: {metrics['event_age_ms']}ms")
    else:
        print(f"  [FAIL] FAIL: event_age_ms={metrics['event_age_ms']}, expected ~5000ms")
        sys.exit(1)

    if 2900 <= metrics["ingest_lag_ms"] <= 3100:  # ~3000ms ± 100ms
        print(f"  [OK] ingest_lag_ms: {metrics['ingest_lag_ms']}ms")
    else:
        print(f"  [FAIL] FAIL: ingest_lag_ms={metrics['ingest_lag_ms']}, expected ~3000ms")
        sys.exit(1)

    if 1900 <= metrics["exchange_server_delta_ms"] <= 2100:  # ~2000ms ± 100ms
        print(f"  [OK] exchange_server_delta_ms: {metrics['exchange_server_delta_ms']}ms")
    else:
        print(f"  [FAIL] FAIL: exchange_server_delta_ms={metrics['exchange_server_delta_ms']}, expected ~2000ms")
        sys.exit(1)

    # Test 10: Clock drift detection
    print("\nTest 10: Clock drift detection")

    # Test 10a: No drift (within 2s threshold)
    no_drift_signal = ScalperSignal(
        ts_exchange=now_ms - 1000,
        ts_server=now_ms - 500,
        symbol="BTC/USD",
        timeframe="15s",
        side="long",
        confidence=0.85,
        entry=45000.0,
        stop=44500.0,
        tp=46000.0,
        model="test_model",
        trace_id=generate_trace_id(),
    )

    has_drift, message = no_drift_signal.check_clock_drift(threshold_ms=2000)
    if not has_drift:
        print("  [OK] No clock drift detected (500ms delta < 2000ms threshold)")
    else:
        print(f"  [FAIL] FAIL: False positive: {message}")
        sys.exit(1)

    # Test 10b: Clock drift detected (exchange ahead)
    drift_signal = ScalperSignal(
        ts_exchange=now_ms + 3000,  # Exchange 3s in future
        ts_server=now_ms,
        symbol="BTC/USD",
        timeframe="15s",
        side="long",
        confidence=0.85,
        entry=45000.0,
        stop=44500.0,
        tp=46000.0,
        model="test_model",
        trace_id=generate_trace_id(),
    )

    has_drift, message = drift_signal.check_clock_drift(threshold_ms=2000)
    if has_drift and "Exchange timestamp is" in message and "ahead" in message:
        print(f"  [OK] Clock drift detected: {message[:80]}...")
    else:
        print(f"  [FAIL] FAIL: Should detect drift (3000ms > 2000ms threshold)")
        sys.exit(1)

    # Test 10c: Clock drift detected (server ahead)
    drift_signal2 = ScalperSignal(
        ts_exchange=now_ms - 5000,
        ts_server=now_ms - 2000,  # 3s delta
        symbol="BTC/USD",
        timeframe="15s",
        side="long",
        confidence=0.85,
        entry=45000.0,
        stop=44500.0,
        tp=46000.0,
        model="test_model",
        trace_id=generate_trace_id(),
    )

    has_drift, message = drift_signal2.check_clock_drift(threshold_ms=2000)
    if has_drift and "Server timestamp is" in message and "ahead" in message:
        print(f"  [OK] Clock drift detected: {message[:80]}...")
    else:
        print(f"  [FAIL] FAIL: Should detect drift (3000ms > 2000ms threshold)")
        sys.exit(1)

    print("\n" + "=" * 80)
    print("[PASS] All tests PASSED (10/10)")
    print("=" * 80)
