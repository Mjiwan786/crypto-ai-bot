"""
mcp/__init__.py
================
Public exports for the Model Context Protocol (MCP) layer.

- Only export stable, supported symbols
- Keep the surface minimal & versioned
- Ensure forward/backward compatibility
"""

# Errors / exceptions
from .errors import (
    MCPError,
    RedisUnavailable,
    SerializationError,
    CircuitOpenError,
)

# Namespacing helpers
from .keys import (
    BOT_ENV,
    ns_key,
    channel,
    stream,
)

# Canonical schemas (see mcp/schemas.py)
from .schemas import (
    OrderSide,
    OrderType,
    TimeInForce,
    VersionedBaseModel,
    Signal,
    OrderIntent,
    PolicyUpdate,
    MetricsTick,
    export_json_schema,
    write_json_schemas,
)

# Infrastructure
from .redis_manager import RedisManager
from .context import MCPContext

__all__ = [
    # Errors
    "MCPError",
    "RedisUnavailable",
    "SerializationError",
    "CircuitOpenError",

    # Keys
    "BOT_ENV",
    "ns_key",
    "channel",
    "stream",

    # Schemas / enums
    "OrderSide",
    "OrderType",
    "TimeInForce",
    "VersionedBaseModel",
    "Signal",
    "OrderIntent",
    "PolicyUpdate",
    "MetricsTick",
    "export_json_schema",
    "write_json_schemas",

    # Infra
    "RedisManager",
    "MCPContext",
]

# Versioning for MCP package
__version__ = "1.0.0"
