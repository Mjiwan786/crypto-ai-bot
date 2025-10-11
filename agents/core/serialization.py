#!/usr/bin/env python3
"""
Centralized JSON serialization utilities for the trading system.

Provides a single place to configure JSON serialization backend and common
conversion helpers. Uses orjson for performance when available, falls back
to standard json library.

Features:
- High-performance JSON serialization with orjson (optional)
- Decimal and datetime conversion helpers
- Consistent serialization across the codebase
- Single point to switch JSON backends

Usage:
    from agents.core.serialization import json_dumps, decimal_to_str, ts_to_iso

    # JSON serialization
    data = {"price": Decimal("123.45"), "timestamp": datetime.now()}
    json_str = json_dumps(data)

    # Decimal conversion
    price_str = decimal_to_str(Decimal("123.45"))

    # Datetime conversion
    iso_str = ts_to_iso(datetime.now())
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

# Try to import orjson for better performance
try:
    import orjson

    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False


def json_dumps(obj: Any, *, indent: int | None = None, ensure_ascii: bool = False) -> str:
    """
    Serialize object to JSON string using orjson if available, fallback to json.

    Uses orjson for high-performance serialization when available. Automatically
    falls back to standard json library if orjson is not installed.

    Args:
        obj: Object to serialize (dict, list, etc.)
        indent: Number of spaces for indentation (None for compact output)
        ensure_ascii: If True, escape non-ASCII characters

    Returns:
        JSON string representation of the object

    Examples:
        >>> json_dumps({"price": 123.45, "symbol": "BTC/USD"})
        '{"price":123.45,"symbol":"BTC/USD"}'

        >>> json_dumps({"data": "test"}, indent=2)
        '{\\n  "data": "test"\\n}'
    """
    if HAS_ORJSON:
        # orjson options
        options = 0
        if indent is not None:
            options |= orjson.OPT_INDENT_2  # orjson only supports 2-space indent
        if not ensure_ascii:
            options |= orjson.OPT_NON_STR_KEYS

        # orjson returns bytes, decode to str
        # Use default handler for non-standard types
        return orjson.dumps(obj, option=options, default=_json_default).decode("utf-8")
    else:
        # Fallback to standard json
        return json.dumps(
            obj,
            indent=indent,
            ensure_ascii=ensure_ascii,
            default=_json_default,
            separators=(",", ":") if indent is None else (",", ": "),
        )


def _json_default(obj: Any) -> Any:
    """
    Default JSON encoder for non-standard types.

    Handles Decimal and datetime objects for json.dumps fallback.

    Args:
        obj: Object to encode

    Returns:
        JSON-serializable representation

    Raises:
        TypeError: If object type is not supported
    """
    if isinstance(obj, Decimal):
        return decimal_to_str(obj)
    elif isinstance(obj, datetime):
        return ts_to_iso(obj)
    else:
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def decimal_to_str(x: Decimal) -> str:
    """
    Convert Decimal to string, removing trailing zeros and unnecessary decimal point.

    Provides consistent string representation of Decimal values for JSON serialization
    and logging. Removes trailing zeros and decimal point when appropriate.

    Args:
        x: Decimal value to convert

    Returns:
        String representation without trailing zeros

    Examples:
        >>> decimal_to_str(Decimal("123.45000"))
        '123.45'

        >>> decimal_to_str(Decimal("100.00"))
        '100'

        >>> decimal_to_str(Decimal("0.00100"))
        '0.001'
    """
    if not isinstance(x, Decimal):
        raise TypeError(f"Expected Decimal, got {type(x).__name__}")

    # Normalize to remove trailing zeros
    normalized = x.normalize()

    # Convert to string
    s = str(normalized)

    # Handle scientific notation (e.g., '1E+2' -> '100')
    if "E" in s.upper():
        # Convert back from scientific notation
        s = format(normalized, "f")
        # Remove trailing zeros after decimal point
        if "." in s:
            s = s.rstrip("0").rstrip(".")

    return s


def ts_to_iso(dt: datetime) -> str:
    """
    Convert datetime to ISO 8601 string with UTC timezone.

    Ensures consistent datetime serialization across the system. Always returns
    UTC timezone format for consistency.

    Args:
        dt: Datetime object to convert

    Returns:
        ISO 8601 formatted string with timezone

    Examples:
        >>> from datetime import datetime, timezone
        >>> dt = datetime(2025, 10, 11, 12, 30, 45, tzinfo=timezone.utc)
        >>> ts_to_iso(dt)
        '2025-10-11T12:30:45+00:00'

        >>> # Naive datetime is treated as UTC
        >>> dt_naive = datetime(2025, 10, 11, 12, 30, 45)
        >>> ts_to_iso(dt_naive)
        '2025-10-11T12:30:45+00:00'
    """
    if not isinstance(dt, datetime):
        raise TypeError(f"Expected datetime, got {type(dt).__name__}")

    # If naive (no timezone), assume UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # If not UTC, convert to UTC
    elif dt.tzinfo != timezone.utc:
        dt = dt.astimezone(timezone.utc)

    return dt.isoformat()


# Convenience function for common use case: serialize with Decimal/datetime support
def serialize_for_redis(obj: Any) -> str:
    """
    Serialize object for Redis storage.

    Convenience function that handles common trading types (Decimal, datetime)
    and produces compact JSON suitable for Redis storage.

    Args:
        obj: Object to serialize

    Returns:
        Compact JSON string

    Examples:
        >>> from datetime import datetime
        >>> from decimal import Decimal
        >>> data = {
        ...     "symbol": "BTC/USD",
        ...     "price": Decimal("50000.00"),
        ...     "timestamp": datetime(2025, 10, 11, 12, 0, 0, tzinfo=timezone.utc)
        ... }
        >>> serialize_for_redis(data)
        '{"symbol":"BTC/USD","price":"50000","timestamp":"2025-10-11T12:00:00+00:00"}'
    """
    # Pre-process object to convert Decimal and datetime
    return json_dumps(_prepare_for_serialization(obj))


def _prepare_for_serialization(obj: Any) -> Any:
    """
    Recursively prepare object for JSON serialization.

    Converts Decimal and datetime objects to their string representations
    throughout nested structures.

    Args:
        obj: Object to prepare

    Returns:
        Object with all Decimal/datetime converted to strings
    """
    if isinstance(obj, Decimal):
        return decimal_to_str(obj)
    elif isinstance(obj, datetime):
        return ts_to_iso(obj)
    elif isinstance(obj, dict):
        return {k: _prepare_for_serialization(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_prepare_for_serialization(item) for item in obj]
    else:
        return obj


# Alias for consistency with user's naming preference
to_decimal_str = decimal_to_str


# Export public API
__all__ = [
    "json_dumps",
    "decimal_to_str",
    "to_decimal_str",  # Alias
    "ts_to_iso",
    "serialize_for_redis",
    "HAS_ORJSON",
]
