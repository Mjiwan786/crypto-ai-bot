# ai_engine/events.py
"""
Production-Ready Crypto AI Bot Event Contract System

Defines strict, versioned Pydantic v2 models for all events exchanged between components
(ingestion → ai_engine → orchestrator/execution → storage/analytics).

Design goals:
- Deterministic, JSON-safe serialization (sorted keys; no sets)
- Frozen models with extra="forbid"; no wall-clock reads; pure logic
- Redis stream adapters: dict[str, bytes] with UTF-8 encoding
- Integrity: content_hash (SHA256) of the body excluding content_hash, recomputed on encode and verified on decode
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

# Module logger (errors only in this file; caller decides handler/level)
logger = logging.getLogger(__name__)

# Single source-of-truth timeframe pattern
_TIMEFRAME_RE = re.compile(r"^\d+[mhdw]$")

__all__ = [
    "EventType",
    "BaseEvent",
    "MarketSnapshotEvent",
    "RegimeDetectedEvent",
    "StrategyDecisionEvent",
    "PolicyUpdateEvent",
    "ExecutionReportEvent",
    "HeartbeatEvent",
    "ErrorEvent",
    "EVENT_REGISTRY",
    "model_for",
    "to_json",
    "from_json",
    "to_stream_entry",
    "from_stream_entry",
    "compute_content_hash",
    "assert_event_roundtrip",
]


class EventType(str, Enum):
    """Event type enumeration for all supported events"""
    MARKET_SNAPSHOT = "market_snapshot"
    REGIME_DETECTED = "regime_detected"
    STRATEGY_DECISION = "strategy_decision"
    POLICY_UPDATE = "policy_update"
    EXECUTION_REPORT = "execution_report"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


class BaseEvent(BaseModel):
    """
    Base event model with common fields and validators.
    Pure logic: no wall-clock, no I/O. Deterministic serialization.
    """
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )

    schema_version: str = Field(default="1.0", description="Schema version for compatibility")
    event_type: EventType = Field(description="Event type discriminator")
    ts_ms: int = Field(description="Epoch milliseconds provided by caller", ge=0)
    source: str = Field(description="Source component", min_length=1)
    correlation_id: str = Field(description="Trace ID across pipeline", min_length=1)
    partition_key: str = Field(description="Stream shard key (routing/partition)", min_length=1)
    meta: Dict[str, str] = Field(
        default_factory=dict,
        description="String-only metadata with sorted serialization",
    )
    content_hash: str = Field(
        default="",
        description="SHA256 of event body excluding content_hash; set by to_json()/to_stream_entry",
    )

    @field_serializer("meta")
    def _serialize_meta(self, v: Dict[str, str]) -> Dict[str, str]:
        """Serialize meta dict with sorted keys for deterministic output."""
        return {k: v[k] for k in sorted(v.keys())}

    @field_validator("meta")
    @classmethod
    def _validate_meta(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Validate meta contains only string keys and values."""
        for key, value in v.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("meta must contain only string keys and values")
        return v

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, v: str) -> str:
        """If provided, content_hash must be a 64-char lowercase hex string."""
        if not v:
            return v
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError("content_hash must be 64-char lowercase hex")
        return v


class MarketSnapshotEvent(BaseEvent):
    """Market data snapshot from ingestion layer"""
    event_type: EventType = Field(default=EventType.MARKET_SNAPSHOT)

    symbols: List[str] = Field(description="List of trading symbols", min_length=1)
    timeframe: str = Field(description="Timeframe (e.g., 1m, 5m, 1h, 1d)")
    mid_px: Dict[str, float] = Field(description="Mid prices by symbol")
    spread_bps: Dict[str, float] = Field(description="Spreads in basis points by symbol")
    funding_8h: Dict[str, float] = Field(
        default_factory=dict,
        description="8-hour funding rates by symbol",
    )
    open_interest: Dict[str, float] = Field(
        default_factory=dict,
        description="Open interest by symbol",
    )

    @field_validator("timeframe")
    @classmethod
    def _validate_timeframe(cls, v: str) -> str:
        """Validate timeframe format."""
        if not _TIMEFRAME_RE.match(v):
            raise ValueError("timeframe must match ^\\d+[mhdw]$")
        return v

    @field_validator("symbols")
    @classmethod
    def _validate_symbols(cls, v: List[str]) -> List[str]:
        """Validate symbols are non-empty strings."""
        for symbol in v:
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("symbols must be non-empty strings")
        return v

    @field_validator("mid_px", "spread_bps", "funding_8h", "open_interest")
    @classmethod
    def _validate_float_dicts(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate float dicts don't contain NaN/Inf and are numeric."""
        import math
        for key, value in v.items():
            if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
                raise ValueError(f"invalid numeric value for {key}: {value}")
        return v

    @field_serializer("mid_px", "spread_bps", "funding_8h", "open_interest")
    def _serialize_float_dicts(self, v: Dict[str, float]) -> Dict[str, float]:
        """Serialize float dicts with sorted keys."""
        return {k: v[k] for k in sorted(v.keys())}


class RegimeDetectedEvent(BaseEvent):
    """Market regime detection from AI engine"""
    event_type: EventType = Field(default=EventType.REGIME_DETECTED)

    label: str = Field(description="Regime label", pattern="^(bull|bear|chop)$")
    confidence: float = Field(description="Confidence score 0..1", ge=0.0, le=1.0)
    components: Dict[str, float] = Field(description="Regime components with sorted keys")
    features: Dict[str, float] = Field(description="Feature values with sorted keys")
    explain: str = Field(description="Human-readable explanation", min_length=1)

    @field_validator("components", "features")
    @classmethod
    def _validate_feature_dicts(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate feature dicts don't contain NaN/Inf and are numeric."""
        import math
        for key, value in v.items():
            if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
                raise ValueError(f"invalid numeric value for {key}: {value}")
        return v

    @field_serializer("components", "features")
    def _serialize_feature_dicts(self, v: Dict[str, float]) -> Dict[str, float]:
        """Serialize feature dicts with sorted keys."""
        return {k: v[k] for k in sorted(v.keys())}


class StrategyDecisionEvent(BaseEvent):
    """Strategy decision from AI engine"""
    event_type: EventType = Field(default=EventType.STRATEGY_DECISION)

    action: str = Field(description="Action to take", pattern="^(open|close|reduce|hold|noop)$")
    side: str = Field(description="Position side", pattern="^(long|short|none)$")
    allocations: Dict[str, float] = Field(description="Symbol allocations 0..1; sum ≤ 1.0")
    max_position_usd: float = Field(description="Maximum position size in USD", gt=0)
    sl_multiplier: float = Field(description="Stop loss multiplier", gt=0)
    tp_multiplier: float = Field(description="Take profit multiplier", gt=0)
    explain: str = Field(description="Human-readable explanation", min_length=1)

    @field_validator("allocations")
    @classmethod
    def _validate_allocations(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate allocations are between 0 and 1 and total ≤ 1.0."""
        import math
        total = 0.0
        for symbol, allocation in v.items():
            if not isinstance(allocation, (int, float)) or math.isnan(allocation) or math.isinf(allocation):
                raise ValueError(f"invalid allocation value for {symbol}: {allocation}")
            if not (0.0 <= allocation <= 1.0):
                raise ValueError(f"allocation for {symbol} must be in [0,1]: {allocation}")
            total += float(allocation)
        if total > 1.0 + 1e-9:
            raise ValueError(f"total allocations must be ≤ 1.0, got {total:.6f}")
        return v

    @field_validator("side")
    @classmethod
    def _validate_side_action_consistency(cls, v: str, info: Any) -> str:
        """Validate side is 'none' only when action is hold or noop."""
        action = (info.data or {}).get("action") if hasattr(info, "data") else None
        if v == "none" and action not in ["hold", "noop"]:
            raise ValueError("side can be 'none' only when action is 'hold' or 'noop'")
        if v != "none" and action in ["hold", "noop"]:
            raise ValueError("side must be 'none' when action is 'hold' or 'noop'")
        return v

    @field_serializer("allocations")
    def _serialize_allocations(self, v: Dict[str, float]) -> Dict[str, float]:
        """Serialize allocations with sorted keys."""
        return {k: v[k] for k in sorted(v.keys())}


class PolicyUpdateEvent(BaseEvent):
    """Policy update from adaptive learner"""
    event_type: EventType = Field(default=EventType.POLICY_UPDATE)

    mode: str = Field(description="Update mode", pattern="^(shadow|active)$")
    new_params: Dict[str, float] = Field(description="New parameter values")
    deltas: Dict[str, float] = Field(description="Parameter changes")
    confidence: float = Field(description="Update confidence 0..1", ge=0.0, le=1.0)
    reason: str = Field(description="Update reason", min_length=1)
    diagnostics: Dict[str, float] = Field(description="Diagnostic metrics")

    @field_validator("new_params", "deltas", "diagnostics")
    @classmethod
    def _validate_param_dicts(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate parameter dicts don't contain NaN/Inf and are numeric."""
        import math
        for key, value in v.items():
            if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
                raise ValueError(f"invalid numeric value for {key}: {value}")
        return v

    @field_serializer("new_params", "deltas", "diagnostics")
    def _serialize_param_dicts(self, v: Dict[str, float]) -> Dict[str, float]:
        """Serialize parameter dicts with sorted keys."""
        return {k: v[k] for k in sorted(v.keys())}


class ExecutionReportEvent(BaseEvent):
    """Execution report from execution layer"""
    event_type: EventType = Field(default=EventType.EXECUTION_REPORT)

    symbol: str = Field(description="Trading symbol", min_length=1)
    strategy: str = Field(description="Strategy name", min_length=1)
    order_id: str = Field(description="Order identifier", min_length=1)
    side: str = Field(description="Order side", pattern="^(long|short)$")
    status: str = Field(
        description="Order status",
        pattern="^(accepted|partial_fill|filled|canceled|rejected|error)$",
    )
    qty: float = Field(description="Order quantity", gt=0)
    avg_px: float = Field(description="Average fill price", gt=0)
    pnl_usd: float = Field(default=0.0, description="PnL in USD")
    error_code: Optional[str] = Field(default=None, description="Error code if applicable")
    error_msg: Optional[str] = Field(default=None, description="Error message if applicable")

    @field_validator("pnl_usd", "qty", "avg_px")
    @classmethod
    def _validate_numeric_fields(cls, v: float) -> float:
        """Validate numeric fields don't contain NaN/Inf."""
        import math
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"invalid numeric value: {v}")
        return v


class HeartbeatEvent(BaseEvent):
    """Heartbeat from any service"""
    event_type: EventType = Field(default=EventType.HEARTBEAT)

    status: str = Field(description="Service status", pattern="^(alive|degraded|dead)$")
    latency_ms: int = Field(description="Latency in milliseconds", ge=0)
    counters: Dict[str, int] = Field(
        default_factory=dict,
        description="Integer counters with sorted keys",
    )
    gauges: Dict[str, float] = Field(
        default_factory=dict,
        description="Float gauges with sorted keys",
    )

    @field_validator("counters")
    @classmethod
    def _validate_counters(cls, v: Dict[str, int]) -> Dict[str, int]:
        """Validate counters are non-negative integers."""
        for key, value in v.items():
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"counter {key} must be non-negative int: {value}")
        return v

    @field_validator("gauges")
    @classmethod
    def _validate_gauges(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate gauges don't contain NaN/Inf and are numeric."""
        import math
        for key, value in v.items():
            if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
                raise ValueError(f"invalid gauge value for {key}: {value}")
        return v

    @field_serializer("counters", "gauges")
    def _serialize_metric_dicts(self, v: Dict[str, Union[int, float]]) -> Dict[str, Union[int, float]]:
        """Serialize metric dicts with sorted keys."""
        return {k: v[k] for k in sorted(v.keys())}


class ErrorEvent(BaseEvent):
    """Error event for cross-cutting concerns"""
    event_type: EventType = Field(default=EventType.ERROR)

    code: str = Field(description="Error code", min_length=1)
    message: str = Field(description="Error message", min_length=1)
    details: Dict[str, str] = Field(
        default_factory=dict,
        description="Additional error details with sorted keys",
    )

    @field_validator("details")
    @classmethod
    def _validate_details(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Validate details contains only string keys and values."""
        for key, value in v.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("details must contain only string keys and values")
        return v

    @field_serializer("details")
    def _serialize_details(self, v: Dict[str, str]) -> Dict[str, str]:
        """Serialize details with sorted keys."""
        return {k: v[k] for k in sorted(v.keys())}


# Event registry for type mapping
EVENT_REGISTRY: Dict[EventType, Type[BaseEvent]] = {
    EventType.MARKET_SNAPSHOT: MarketSnapshotEvent,
    EventType.REGIME_DETECTED: RegimeDetectedEvent,
    EventType.STRATEGY_DECISION: StrategyDecisionEvent,
    EventType.POLICY_UPDATE: PolicyUpdateEvent,
    EventType.EXECUTION_REPORT: ExecutionReportEvent,
    EventType.HEARTBEAT: HeartbeatEvent,
    EventType.ERROR: ErrorEvent,
}


def model_for(event_type: Union[str, EventType]) -> Type[BaseEvent]:
    """
    Get model class for event type.

    Raises:
        ValueError: If event type is unknown
    """
    if isinstance(event_type, str):
        try:
            event_type = EventType(event_type)
        except ValueError as err:
            raise ValueError(f"unknown event_type: {event_type}") from err

    try:
        return EVENT_REGISTRY[event_type]
    except KeyError as err:
        raise ValueError(f"unknown event_type: {event_type}") from err


def compute_content_hash(e: BaseEvent) -> str:
    """
    Compute SHA256 content hash of event excluding the content_hash field.
    Deterministic across runs due to sorted-keys JSON and ensure_ascii.
    """
    body = e.model_dump(mode="json", exclude={"content_hash"})
    s = json.dumps(body, separators=(",", ":"), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def to_json(e: BaseEvent) -> str:
    """
    Serialize event to a deterministic JSON string (sorted keys; compact).
    Recomputes content_hash unconditionally for integrity.
    """
    e = e.model_copy(update={"content_hash": compute_content_hash(e)})
    return json.dumps(
        e.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    )


def from_json(s: str) -> BaseEvent:
    """
    Deserialize event from JSON string using registry and validate integrity.

    Raises:
        ValueError: If JSON is invalid, event type unknown, or content_hash verification fails.
    """
    try:
        data = json.loads(s)
    except json.JSONDecodeError as err:
        logger.error("JSON parse error: %s", err)
        raise ValueError(f"Invalid JSON: {err}") from err

    if not isinstance(data, dict):
        raise ValueError("JSON must be an object")

    et = data.get("event_type")
    if not et:
        raise ValueError("Missing event_type field")

    model = model_for(et)
    try:
        ev = model.model_validate(data)
    except Exception as err:
        logger.error("Validation failed for %s: %s", et, err)
        raise ValueError(f"Event validation failed: {err}") from err

    expected = compute_content_hash(ev)
    if ev.content_hash and ev.content_hash != expected:
        logger.error("content_hash mismatch: provided=%s expected=%s", ev.content_hash, expected)
        raise ValueError("content_hash verification failed")
    if not ev.content_hash:
        ev = ev.model_copy(update={"content_hash": expected})
    return ev


def to_stream_entry(e: BaseEvent) -> Dict[str, bytes]:
    """
    Convert event to Redis stream entry format: dict[str, bytes].
    """
    e = e.model_copy(update={"content_hash": compute_content_hash(e)})
    entry: Dict[str, bytes] = {
        "event_type": e.event_type.value.encode("utf-8"),
        "schema_version": e.schema_version.encode("utf-8"),
        "correlation_id": e.correlation_id.encode("utf-8"),
        "partition_key": e.partition_key.encode("utf-8"),
        "ts_ms": str(e.ts_ms).encode("utf-8"),
        "source": e.source.encode("utf-8"),
        "content_hash": e.content_hash.encode("utf-8"),
        "payload": to_json(e).encode("utf-8"),
    }
    return entry


def from_stream_entry(d: Dict[str, Union[bytes, str]]) -> BaseEvent:
    """
    Convert Redis stream entry to event instance.

    Raises:
        ValueError: If entry format is invalid or UTF-8 decode fails.
    """
    payload = d.get("payload")
    if payload is None:
        raise ValueError("Missing payload field")

    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as ue:
            logger.error("UTF-8 decode error: %s", ue)
            raise ValueError("payload must be UTF-8 bytes or str") from ue

    if not isinstance(payload, str):
        raise ValueError("payload must be str or UTF-8 bytes")

    return from_json(payload)


def assert_event_roundtrip(e: BaseEvent) -> None:
    """
    Assert that event survives JSON and stream roundtrips unchanged.
    """
    s = to_json(e)
    e2 = from_json(s)
    assert e.model_dump(mode="json") == e2.model_dump(mode="json"), "JSON roundtrip failed"

    entry = to_stream_entry(e)
    e3 = from_stream_entry(entry)
    assert e.model_dump(mode="json") == e3.model_dump(mode="json"), "stream roundtrip failed"


if __name__ == "__main__":
    # Self-check: build instances and test round-trips (deterministic; no wall-clock)
    import sys

    logging.basicConfig(level=logging.INFO)
    ts = 1700000000000  # fixed timestamp for deterministic testing

    tests: List[BaseEvent] = [
        MarketSnapshotEvent(
            ts_ms=ts,
            source="ingestion.kraken",
            correlation_id="t1",
            partition_key="BTCUSD",
            symbols=["BTC/USD", "ETH/USD"],
            timeframe="1m",
            mid_px={"BTC/USD": 45000.0, "ETH/USD": 3000.0},
            spread_bps={"BTC/USD": 2.5, "ETH/USD": 3.0},
            funding_8h={"BTC/USD": 0.01, "ETH/USD": 0.005},
        ),
        RegimeDetectedEvent(
            ts_ms=ts,
            source="ai_engine",
            correlation_id="t2",
            partition_key="regime",
            label="bull",
            confidence=0.85,
            components={"trend": 0.8, "momentum": 0.7, "volatility": 0.3},
            features={"rsi": 65.5, "macd": 0.15, "volume_ratio": 1.2},
            explain="Strong upward momentum with bullish indicators",
        ),
        StrategyDecisionEvent(
            ts_ms=ts,
            source="ai_engine",
            correlation_id="t3",
            partition_key="BTCUSD",
            action="open",
            side="long",
            allocations={"BTC/USD": 0.4, "ETH/USD": 0.3},
            max_position_usd=250.0,
            sl_multiplier=1.2,
            tp_multiplier=1.8,
            explain="Bull regime detected; allocating to top performers",
        ),
        PolicyUpdateEvent(
            ts_ms=ts,
            source="adaptive_learner",
            correlation_id="t4",
            partition_key="policy",
            mode="active",
            new_params={"risk_factor": 0.8, "momentum_threshold": 0.15},
            deltas={"risk_factor": -0.1, "momentum_threshold": 0.05},
            confidence=0.75,
            reason="Market volatility decreased",
            diagnostics={"accuracy": 0.82, "sharpe": 1.45},
        ),
        ExecutionReportEvent(
            ts_ms=ts,
            source="execution",
            correlation_id="t5",
            partition_key="BTCUSD",
            symbol="BTC/USD",
            strategy="scalp",
            order_id="ord-12345",
            side="long",
            status="filled",
            qty=0.01,
            avg_px=45000.0,
            pnl_usd=25.50,
        ),
        HeartbeatEvent(
            ts_ms=ts,
            source="risk_manager",
            correlation_id="t6",
            partition_key="health",
            status="alive",
            latency_ms=15,
            counters={"orders_processed": 1234, "errors": 2},
            gauges={"cpu_usage": 45.2, "memory_mb": 512.8},
        ),
        ErrorEvent(
            ts_ms=ts,
            source="execution",
            correlation_id="t7",
            partition_key="errors",
            code="ORDER_REJECTED",
            message="Insufficient margin",
            details={"symbol": "BTC/USD", "required_margin": "1000.0"},
        ),
    ]

    ok = 0
    total = len(tests)
    for ev in tests:
        try:
            ev = ev.model_copy(update={"content_hash": compute_content_hash(ev)})
            assert_event_roundtrip(ev)
            logger.info("✓ %s roundtrip test passed", ev.event_type.value)
            ok += 1
        except Exception as err:
            logger.error("✗ %s roundtrip test failed: %s", ev.event_type.value, err)

    sys.exit(0 if ok == total else 1)
