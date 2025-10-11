"""
mcp/errors.py

Production-grade error hierarchy for crypto-ai-bot MCP layer.

Provides structured exception handling with retryability semantics,
context preservation, secret scrubbing, and logging/telemetry integration
for the Redis-based trading system with circuit breakers and scalping strategies.
"""

from __future__ import annotations

import json
import re
import sys
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, NoReturn, Optional, Tuple, Union

__all__ = [
    "MCPError",
    "SerializationError",
    "RedisUnavailable",
    "CircuitOpenError",
    "ValidationError",
    "ConfigError",
    "MCPTimeoutError",      # renamed to avoid built-in collision
    "NotFoundError",
    "MCPPermissionError",   # renamed to avoid built-in collision
    "RateLimitError",
    "ErrorCode",
    "wrap",
    "http_status_for",
]

# ------------------------- Codes & Status Mapping -------------------------

class ErrorCode(str, Enum):
    """Machine-readable error codes for classification and metrics."""
    MCP_ERROR = "MCP_ERROR"
    SERIALIZATION_ERROR = "SERIALIZATION_ERROR"
    REDIS_UNAVAILABLE = "REDIS_UNAVAILABLE"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    TIMEOUT = "TIMEOUT"
    NOT_FOUND = "NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMIT = "RATE_LIMIT"
    UNHANDLED = "UNHANDLED"


# HTTP status code mapping for bridge implementations
HTTP_STATUS_MAP: Dict[str, int] = {
    ErrorCode.MCP_ERROR.value: 500,
    ErrorCode.SERIALIZATION_ERROR.value: 400,
    ErrorCode.VALIDATION_ERROR.value: 422,
    ErrorCode.NOT_FOUND.value: 404,
    ErrorCode.PERMISSION_DENIED.value: 403,
    ErrorCode.TIMEOUT.value: 504,
    ErrorCode.RATE_LIMIT.value: 429,
    ErrorCode.REDIS_UNAVAILABLE.value: 503,
    ErrorCode.CIRCUIT_OPEN.value: 503,
    ErrorCode.CONFIG_ERROR.value: 500,
}

# ------------------------- Scrubbing Helpers -------------------------

_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[_\-\.\[\{])(password|pass|pwd|token|secret|api[_\-]?key|auth|cookie|credential)(?:$|[_\-\.\]\}])",
    re.I,
)
_SENSITIVE_VALUE_RE = re.compile(
    r"(?:^|[ :=])(?:Bearer\s+[A-Za-z0-9\.\-_]+|sk-[A-Za-z0-9]{10,}|xoxb-[A-Za-z0-9\-]{10,}|eyJ[a-zA-Z0-9_-]{10,})",
)

def _scrub_value(v: Any) -> Any:
    if isinstance(v, str) and _SENSITIVE_VALUE_RE.search(v):
        return "***REDACTED***"
    return v

def _all_slots(cls: type) -> Tuple[str, ...]:
    """Collect __slots__ across the class MRO (used to preserve subclass fields)."""
    slots: list[str] = []
    for c in cls.__mro__:
        s = getattr(c, "__slots__", ())
        if isinstance(s, str):
            slots.append(s)
        elif isinstance(s, Iterable):
            slots.extend(s)
    return tuple(slots)

# ------------------------- Base Exception -------------------------

class MCPError(Exception):
    """
    Base exception for MCP layer operations.

    Provides structured context for logging/telemetry, retryability semantics,
    proper exception chaining, and secret scrubbing for production systems.

    Args:
        message: Human-readable error description
        code: Machine-readable error code (ErrorCode or str)
        retryable: Whether this error represents a transient failure
        context: Additional structured data for debugging/telemetry
        cause: Underlying exception that triggered this error
    """

    __slots__ = ("_message", "_code", "_retryable", "_context", "_cause")

    def __init__(
        self,
        message: str,
        *,
        code: Union[str, ErrorCode] = ErrorCode.MCP_ERROR,
        retryable: bool = False,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self._message = message
        # Normalize enum to string for logs/metrics
        self._code = str(code.value if isinstance(code, ErrorCode) else code)
        self._retryable = retryable
        # Store shallow copy but expose as read-only mapping
        self._context = dict(context or {})
        self._cause = cause

    # --- Properties ---

    @property
    def message(self) -> str:
        return self._message

    @property
    def code(self) -> str:
        return self._code

    @property
    def retryable(self) -> bool:
        return self._retryable

    @property
    def context(self) -> Mapping[str, Any]:
        return MappingProxyType(self._context)

    @property
    def cause(self) -> Optional[BaseException]:
        return self._cause

    # --- Repr/Str ---

    def __str__(self) -> str:
        base = f"[{self.code}] {self.message}"
        if self.cause:
            base += f" (caused by {type(self.cause).__name__})"
        return base

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"code={self.code!r}, retryable={self.retryable!r}, message={self.message!r})"
        )

    # --- Utilities ---

    def _clone_kwargs(self) -> Dict[str, Any]:
        """
        Collect constructor kwargs for this instance, preserving subclass extras
        declared via __slots__ (e.g., endpoint, operation, retry_after, limit_scope).
        """
        kwargs: Dict[str, Any] = dict(
            code=self.code,
            retryable=self.retryable,
            context=dict(self._context),
            cause=self.cause,
        )
        for attr in _all_slots(type(self)):
            if attr.startswith("_"):
                continue
            if hasattr(self, attr):
                kwargs[attr] = getattr(self, attr)
        return kwargs

    def to_log_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict for structured logging with secret scrubbing."""
        safe_context: Dict[str, Any] = {}
        for k, v in self._context.items():
            key = str(k)
            if _SENSITIVE_KEY_RE.search(key):
                safe_context[key] = "***REDACTED***"
                continue
            v = _scrub_value(v)
            try:
                json.dumps(v)  # test serializability
                safe_context[key] = v
            except (TypeError, ValueError):
                safe_context[key] = repr(v)
        return {
            "error": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "context": safe_context,
            "cause": repr(self.cause) if self.cause else None,
        }

    def with_context(self, **extra: Any) -> "MCPError":
        """Create a new instance with additional context (preserves subclass fields)."""
        merged = dict(self._context)
        merged.update(extra)
        kwargs = self._clone_kwargs()
        kwargs["context"] = merged
        return self.__class__(self.message, **kwargs)

    def chain(self, cause: BaseException) -> "MCPError":
        """Create a new instance with cause set (preserves subclass fields)."""
        kwargs = self._clone_kwargs()
        kwargs["cause"] = cause
        return self.__class__(self.message, **kwargs)

    def raise_from(self, cause: BaseException) -> NoReturn:
        """Raise this error chained from another exception (proper __cause__ linking)."""
        self._cause = cause
        raise self from cause

    @staticmethod
    def from_exception(
        exc: BaseException,
        *,
        code: Union[str, ErrorCode] = ErrorCode.UNHANDLED,
        retryable: bool = False,
        context: Optional[Dict[str, Any]] = None,
    ) -> "MCPError":
        """Convert any exception to MCPError."""
        message = str(exc) if str(exc) else f"Unhandled {type(exc).__name__}"
        return MCPError(
            message,
            code=code,
            retryable=retryable,
            context=context,
            cause=exc,
        )

# ------------------------- Subclasses -------------------------

class SerializationError(MCPError):
    """Error in data serialization/deserialization."""
    __slots__ = ()
    def __init__(
        self,
        message: str,
        *,
        code: Union[str, ErrorCode] = ErrorCode.SERIALIZATION_ERROR,
        retryable: bool = False,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, code=code, retryable=retryable, context=context, cause=cause)


class RedisUnavailable(MCPError):
    """
    Redis connectivity or infrastructure failure.
    Typically retryable with exponential backoff.
    """
    __slots__ = ("endpoint", "operation")
    def __init__(
        self,
        message: str,
        *,
        code: Union[str, ErrorCode] = ErrorCode.REDIS_UNAVAILABLE,
        retryable: bool = True,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
        endpoint: Optional[str] = None,
        operation: Optional[str] = None,
    ) -> None:
        super().__init__(message, code=code, retryable=retryable, context=context, cause=cause)
        self.endpoint = endpoint
        self.operation = operation

    def to_log_dict(self) -> Dict[str, Any]:
        d = super().to_log_dict()
        if self.endpoint:
            d["redis_endpoint"] = self.endpoint
        if self.operation:
            d["redis_operation"] = self.operation
        return d


class CircuitOpenError(MCPError):
    """Circuit breaker is open, preventing operation."""
    __slots__ = ()
    def __init__(
        self,
        message: str,
        *,
        code: Union[str, ErrorCode] = ErrorCode.CIRCUIT_OPEN,
        retryable: bool = False,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, code=code, retryable=retryable, context=context, cause=cause)


class ValidationError(MCPError):
    """Semantic (business rule) validation failure."""
    __slots__ = ()
    def __init__(
        self,
        message: str,
        *,
        code: Union[str, ErrorCode] = ErrorCode.VALIDATION_ERROR,
        retryable: bool = False,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, code=code, retryable=retryable, context=context, cause=cause)


class ConfigError(MCPError):
    """Configuration or environment setup error."""
    __slots__ = ()
    def __init__(
        self,
        message: str,
        *,
        code: Union[str, ErrorCode] = ErrorCode.CONFIG_ERROR,
        retryable: bool = False,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, code=code, retryable=retryable, context=context, cause=cause)


class MCPTimeoutError(MCPError):
    """
    Operation exceeded deadline (request/Redis/MCP action).
    Often retryable with adjusted timeouts or backoff.
    """
    __slots__ = ()
    def __init__(
        self,
        message: str,
        *,
        code: Union[str, ErrorCode] = ErrorCode.TIMEOUT,
        retryable: bool = True,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, code=code, retryable=retryable, context=context, cause=cause)


class NotFoundError(MCPError):
    """Required resource not found (non-retryable for same inputs)."""
    __slots__ = ()
    def __init__(
        self,
        message: str,
        *,
        code: Union[str, ErrorCode] = ErrorCode.NOT_FOUND,
        retryable: bool = False,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, code=code, retryable=retryable, context=context, cause=cause)


class MCPPermissionError(MCPError):
    """Authentication or authorization failure (non-retryable without changes)."""
    __slots__ = ()
    def __init__(
        self,
        message: str,
        *,
        code: Union[str, ErrorCode] = ErrorCode.PERMISSION_DENIED,
        retryable: bool = False,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, code=code, retryable=retryable, context=context, cause=cause)


class RateLimitError(MCPError):
    """
    Rate limit exceeded. Retryable with appropriate backoff.
    Enhanced with retry timing and scope information.
    """
    __slots__ = ("retry_after", "limit_scope")
    def __init__(
        self,
        message: str,
        *,
        code: Union[str, ErrorCode] = ErrorCode.RATE_LIMIT,
        retryable: bool = True,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
        retry_after: Optional[float] = None,  # seconds
        limit_scope: Optional[str] = None,    # e.g., "per_api_key", "per_ip"
    ) -> None:
        super().__init__(message, code=code, retryable=retryable, context=context, cause=cause)
        self.retry_after = retry_after
        self.limit_scope = limit_scope

    def to_log_dict(self) -> Dict[str, Any]:
        d = super().to_log_dict()
        if self.retry_after is not None:
            d["retry_after"] = self.retry_after
        if self.limit_scope:
            d["limit_scope"] = self.limit_scope
        return d

# ------------------------- Helpers -------------------------

def wrap(
    exc: BaseException,
    *,
    code: Union[str, ErrorCode] = ErrorCode.UNHANDLED,
    retryable: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> MCPError:
    """
    Convert any exception to MCPError, preserving MCPError instances.
    """
    if isinstance(exc, MCPError):
        return exc.with_context(**(context or {})) if context else exc
    return MCPError.from_exception(exc, code=code, retryable=retryable, context=context)


def http_status_for(error: MCPError) -> int:
    """
    Map MCP error to appropriate HTTP status code for bridge implementations.
    """
    code = getattr(error, "code", ErrorCode.MCP_ERROR)
    code_str = str(code.value if isinstance(code, ErrorCode) else code)
    return HTTP_STATUS_MAP.get(code_str, 500)

# ------------------------- Self-test -------------------------

def _self_test() -> None:
    """Run comprehensive self-tests of the error hierarchy."""

    # SerializationError with context and cause
    original_exc = ValueError("Invalid JSON structure")
    context = {"payload_size": 1024, "stream": "kraken:trade"}
    error = SerializationError("Failed to parse market data", context=context, cause=original_exc)

    assert error.code == ErrorCode.SERIALIZATION_ERROR.value
    assert not error.retryable
    assert error.message == "Failed to parse market data"
    assert dict(error.context) == context
    assert error.cause is original_exc
    assert "[SERIALIZATION_ERROR]" in str(error)
    assert "ValueError" in str(error)

    # Secret scrubbing (keys & values)
    sensitive_context = {
        "api_key": "secret123",
        "password": "pass456",
        "authorization": "Bearer abc.def-ghi",
        "normal_field": "value",
    }
    sensitive_error = SerializationError("test", context=sensitive_context)
    log_dict = sensitive_error.to_log_dict()
    assert log_dict["context"]["api_key"] == "***REDACTED***"
    assert log_dict["context"]["password"] == "***REDACTED***"
    assert log_dict["context"]["authorization"] == "***REDACTED***"
    assert log_dict["context"]["normal_field"] == "value"

    # Context addition preserves subclass fields
    rerr = RedisUnavailable("Connection timeout", endpoint="redis://host:6379", operation="XADD")
    rerr2 = rerr.with_context(attempt=3)
    assert rerr2.endpoint == "redis://host:6379" and rerr2.operation == "XADD"
    assert dict(rerr2.context)["attempt"] == 3

    # raise_from chains cause
    try:
        ValidationError("Bad params").raise_from(ValueError("root cause"))
    except MCPError as caught:
        assert caught.__cause__.__class__.__name__ == "ValueError"
        assert str(caught.__cause__) == "root cause"

    # wrap() for regular exception
    wrapped = wrap(ValueError("test error"))
    assert isinstance(wrapped, MCPError)
    assert wrapped.code == ErrorCode.UNHANDLED.value
    assert not wrapped.retryable
    assert wrapped.cause.__class__.__name__ == "ValueError"

    # wrap() preserves MCPError
    redis_error = RedisUnavailable("Connection lost")
    wrapped_mcp = wrap(redis_error)
    assert wrapped_mcp is redis_error
    assert wrapped_mcp.retryable

    # RateLimit extras
    rle = RateLimitError("API rate limit exceeded", retry_after=60.0, limit_scope="per_api_key")
    rle_log = rle.to_log_dict()
    assert rle_log["retry_after"] == 60.0 and rle_log["limit_scope"] == "per_api_key"

    # HTTP status mapping
    assert http_status_for(ValidationError("x")) == 422
    assert http_status_for(NotFoundError("x")) == 404
    assert http_status_for(RateLimitError("x")) == 429
    assert http_status_for(RedisUnavailable("x")) == 503
    assert http_status_for(MCPError("x", code="SOMETHING_NEW")) == 500

    # Code enum smoke
    assert ErrorCode.SERIALIZATION_ERROR.value == "SERIALIZATION_ERROR"
    assert ErrorCode.REDIS_UNAVAILABLE.value == "REDIS_UNAVAILABLE"

    print("MCP errors self-test PASSED")

# ------------------------- CLI -------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        _self_test()
    else:
        print("Usage: python -m mcp.errors --self-test")
        sys.exit(1)
