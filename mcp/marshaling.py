# mcp/marshaling.py
#
# Fast, safe, deterministic (de)serialization utilities for MCP events.
# - Canonical JSON (sorted keys) for stable_hash()
# - Prefers orjson; falls back to stdlib json
# - Optional FastMCP hook (env FASTMCP_ENABLED=true) if available
# - Strict UTF‑8, compact payloads, and precise errors

from __future__ import annotations

import os
import json as _json
import hashlib
from typing import Any, Callable, Dict, Optional, Tuple, Type, Union

from mcp.schemas import (
    VersionedBaseModel,
    Signal,
    OrderIntent,
    PolicyUpdate,
    MetricsTick,
)
from mcp.errors import SerializationError

__all__ = [
    "CONTENT_TYPE_JSON",
    "FIELD_JSON",
    "FIELD_ERROR",
    "FIELD_SOURCE",
    "TYPE_TO_MODEL",
    "serialize_event",
    "serialize_event_bytes",
    "peek_type",
    "deserialize_event",
    "pack_stream_fields",
    "unpack_stream_fields",
    "stable_hash",
    "ensure_utf8",
    "try_deserialize",
    "try_unpack",
]

# =========
# Constants
# =========
CONTENT_TYPE_JSON: str = "application/json"
FIELD_JSON: str = "json"
FIELD_ERROR: str = "err"
FIELD_SOURCE: str = "src"

# ============================
# Type registry (discriminators)
# ============================
TYPE_TO_MODEL: Dict[str, Type[VersionedBaseModel]] = {
    "signal": Signal,
    "order.intent": OrderIntent,
    "policy.update": PolicyUpdate,
    "metrics.tick": MetricsTick,
}

# ==========================================
# Optional accelerators (FastMCP / orjson)
# ==========================================
_FM_ENABLED = os.getenv("FASTMCP_ENABLED", "false").lower() == "true"
_fastmcp_loads: Optional[Callable[[Union[str, bytes, bytearray]], Any]] = None
_fastmcp_dumps: Optional[Callable[[Any], Union[str, bytes]]] = None

try:
    if _FM_ENABLED:
        # Optional fastmcp JSON shim (if you have the package)
        from fastmcp.json import loads as _fm_loads, dumps as _fm_dumps  # type: ignore

        _fastmcp_loads, _fastmcp_dumps = _fm_loads, _fm_dumps
except Exception:
    _fastmcp_loads = _fastmcp_dumps = None

# orjson (fast path) with deterministic output
_orjson = None
_ORJSON_OPTS = 0
try:
    import orjson as _orjson  # type: ignore

    _ORJSON_OPTS = (
        getattr(_orjson, "OPT_SORT_KEYS", 0)
        | getattr(_orjson, "OPT_APPEND_NEWLINE", 0)  # harmless
    )
except Exception:
    _orjson = None


def _loads(s: Union[str, bytes, bytearray]) -> Any:
    """Accelerated JSON loads with fallback."""
    if _fastmcp_loads:
        return _fastmcp_loads(s)
    if _orjson is not None:
        return _orjson.loads(s)
    if isinstance(s, (bytes, bytearray)):
        s = s.decode("utf-8", errors="strict")
    return _json.loads(s)


def _dumps_obj(obj: Any) -> str:
    """
    Deterministic (sorted keys), compact JSON string from JSON-safe Python data.
    Use **only** on JSON-safe objects (e.g., model_dump(mode="json") output).
    """
    if _fastmcp_dumps:
        out = _fastmcp_dumps(obj)
        return out.decode("utf-8") if isinstance(out, (bytes, bytearray)) else str(out)

    if _orjson is not None:
        return _orjson.dumps(obj, option=_ORJSON_OPTS).decode("utf-8")

    return _json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


# ===========================================================
# Core API
# ===========================================================
def serialize_event(event: VersionedBaseModel) -> str:
    """
    Serialize a Pydantic model to canonical JSON string.
    Deterministic + compact + excludes None.
    NOTE: Use mode="json" so non-JSON-native types (e.g., set) are normalized.
    """
    try:
        data = event.model_dump(
            mode="json",          # <-- critical: converts sets to lists, etc.
            exclude_none=True,
            by_alias=True,
            round_trip=False,
        )
        return _dumps_obj(data)
    except Exception as e:
        raise SerializationError(
            message=f"Failed to serialize {type(event).__name__}: {e}",
            code="SERIALIZATION_ERROR",
            retryable=False,
        ) from e


def serialize_event_bytes(event: VersionedBaseModel) -> bytes:
    """Serialize a Pydantic model to UTF-8 bytes (deterministic)."""
    try:
        return serialize_event(event).encode("utf-8", errors="strict")
    except Exception as e:
        raise SerializationError(
            message=f"UTF-8 encoding failed: {e}",
            code="SERIALIZATION_ERROR",
            retryable=False,
        ) from e


def peek_type(json_str: str) -> str:
    """
    Extract 'type' discriminator without full schema validation.
    Supports legacy 'event_type'.
    """
    if not isinstance(json_str, str):
        raise TypeError(f"Expected str, got {type(json_str).__name__}")
    try:
        data = _loads(json_str)
    except Exception as e:
        raise SerializationError(
            message=f"Invalid JSON: {e}",
            code="SERIALIZATION_ERROR",
            retryable=False,
        ) from e

    if not isinstance(data, dict):
        raise SerializationError(
            message="JSON must be an object",
            code="SERIALIZATION_ERROR",
            retryable=False,
        )

    event_type = data.get("type") or data.get("event_type")
    if not event_type or not isinstance(event_type, str):
        raise SerializationError(
            message="Missing or invalid 'type' field",
            code="SERIALIZATION_ERROR",
            retryable=False,
        )
    if event_type not in TYPE_TO_MODEL:
        raise SerializationError(
            message=f"Unknown event type: {event_type}",
            code="SERIALIZATION_ERROR",
            retryable=False,
        )
    return event_type


def deserialize_event(json_str: str) -> VersionedBaseModel:
    """
    Route by 'type' and validate with the appropriate Pydantic model.
    Legacy 'version' → 'schema_version' is handled by validators.
    """
    if not isinstance(json_str, str):
        raise TypeError(f"Expected str, got {type(json_str).__name__}")
    event_type = peek_type(json_str)
    model_class = TYPE_TO_MODEL[event_type]
    try:
        return model_class.model_validate_json(json_str)
    except Exception as e:
        raise SerializationError(
            message=f"Failed to deserialize {event_type}: {e}",
            code="SERIALIZATION_ERROR",
            retryable=False,
        ) from e


def pack_stream_fields(event: VersionedBaseModel, *, field: str = FIELD_JSON) -> Dict[str, str]:
    """Pack model into Redis XADD fields (string values)."""
    if not field:
        raise ValueError("Field name cannot be empty")
    if not isinstance(event, VersionedBaseModel):
        raise TypeError(f"Expected VersionedBaseModel, got {type(event).__name__}")
    return {field: serialize_event(event)}


def unpack_stream_fields(
    fields: Dict[str, Union[bytes, str]],
    *,
    field: str = FIELD_JSON,
) -> VersionedBaseModel:
    """Unpack model from Redis XREAD/XRANGE fields."""
    if not field:
        raise ValueError("Field name cannot be empty")
    if not isinstance(fields, dict):
        raise TypeError(f"Expected dict, got {type(fields).__name__}")
    if field not in fields:
        raise SerializationError(
            message=f"Missing required field '{field}'",
            code="SERIALIZATION_ERROR",
            retryable=False,
        )
    raw_value = fields[field]
    json_str = ensure_utf8(raw_value)
    return deserialize_event(json_str)


def stable_hash(json_str: str) -> str:
    """Stable SHA-256 over deterministic JSON."""
    if not isinstance(json_str, str):
        raise TypeError(f"Expected str, got {type(json_str).__name__}")
    return hashlib.sha256(json_str.encode("utf-8", errors="strict")).hexdigest()


def ensure_utf8(data: Union[bytes, str, bytearray]) -> str:
    """Ensure UTF-8 text from bytes/bytearray/str."""
    if isinstance(data, str):
        return data
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).decode("utf-8", errors="strict")
    raise TypeError(f"Expected bytes or str, got {type(data).__name__}")


def try_deserialize(json_str: str) -> Tuple[Optional[VersionedBaseModel], Optional[str]]:
    """Never raises; returns (model, error)."""
    try:
        return deserialize_event(json_str), None
    except Exception as e:
        return None, str(e)


def try_unpack(
    fields: Dict[str, Union[bytes, str]],
    *,
    field: str = FIELD_JSON,
) -> Tuple[Optional[VersionedBaseModel], Optional[str]]:
    """Never raises; returns (model, error)."""
    try:
        return unpack_stream_fields(fields, field=field), None
    except Exception as e:
        return None, str(e)


# ==============
# Self-test
# ==============
def _self_test() -> None:
    print("Running mcp.marshaling self-test...")
    original = Signal.example()
    json_str = serialize_event(original)
    json_bytes = serialize_event_bytes(original)
    assert json_bytes == json_str.encode("utf-8")
    assert len(stable_hash(json_str)) == 64

    deserialized = deserialize_event(json_str)
    assert deserialized.model_dump(mode="json") == original.model_dump(mode="json")

    packed = pack_stream_fields(original)
    unpacked = unpack_stream_fields(packed)
    assert unpacked.model_dump(mode="json") == original.model_dump(mode="json")

    # legacy alias: version
    legacy = {
        "type": "signal",
        "version": "1.0",
        "strategy": "test",
        "symbol": "BTC/USD",
        "timeframe": "1m",
        "side": "buy",
        "confidence": 0.8,
    }
    legacy_json = _dumps_obj(legacy)
    assert deserialize_event(legacy_json).schema_version == "1.0"

    # legacy alias: event_type
    legacy_type = {
        "event_type": "signal",
        "schema_version": "1.0",
        "strategy": "test",
        "symbol": "BTC/USD",
        "timeframe": "1m",
        "side": "buy",
        "confidence": 0.8,
    }
    assert peek_type(_dumps_obj(legacy_type)) == "signal"

    # safe wrappers
    ok, err = try_deserialize(json_str)
    assert ok is not None and err is None
    bad, err = try_deserialize("{not json")
    assert bad is None and err

    ok, err = try_unpack(packed)
    assert ok is not None and err is None
    bad, err = try_unpack({})
    assert bad is None and err

    # cover all event classes
    for cls in (Signal, OrderIntent, PolicyUpdate, MetricsTick):
        e = cls.example()
        s = serialize_event(e)
        # Ensure no sets remain in final JSON
        assert "{" in s and "}" in s
        assert "set(" not in s.lower()
        assert isinstance(deserialize_event(s), cls)

    print("mcp.marshaling self-test PASSED")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        try:
            _self_test()
            raise SystemExit(0)
        except Exception as e:
            print(f"Self-test FAILED: {e}")
            raise SystemExit(1)
    print("Usage: python -m mcp.marshaling --self-test")
    raise SystemExit(1)
