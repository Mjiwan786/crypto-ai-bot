"""
Exchange error classification for retry logic and fault handling.

This module provides a comprehensive error classification hierarchy for exchange
interactions, distinguishing between retryable and fatal errors to enable
intelligent error handling and retry strategies.

Key principles:
- Clear error hierarchy: retryable vs fatal
- Error context preservation: original exception, code, message
- Type safety: explicit error classes for common scenarios
- Actionable classification: enables automatic retry/circuit breaking

Usage:
    from agents.scalper.execution.exchange_errors import (
        RateLimitError,
        NetworkError,
        InvalidOrderError,
        InsufficientFundsError,
    )

    try:
        await gateway.place_order(request)
    except RateLimitError as e:
        # Retryable - wait and retry with exponential backoff
        await asyncio.sleep(e.retry_after_seconds)
    except InvalidOrderError as e:
        # Fatal - fix order parameters
        logger.error(f"Invalid order: {e.message}")
"""

from __future__ import annotations

from typing import Optional


# ======================== Base Error Classes ========================


class ExchangeError(Exception):
    """
    Base exception for all exchange-related errors.

    Attributes:
        message: Human-readable error description
        retryable: Whether this error can be retried
        code: Exchange-specific error code
        original_exception: Original exception if wrapped
    """

    def __init__(
        self,
        message: str,
        retryable: bool = False,
        code: str = "",
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.code = code
        self.original_exception = original_exception

    def __str__(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"(code: {self.code})")
        if self.original_exception:
            parts.append(f"[caused by: {self.original_exception}]")
        return " ".join(parts)


# ======================== Retryable Errors ========================


class RateLimitError(ExchangeError):
    """
    Rate limit exceeded error - always retryable after backoff.

    Attributes:
        retry_after_seconds: Recommended wait time before retry
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        code: str = "RATE_LIMIT",
        retry_after_seconds: float = 1.0,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=True,
            code=code,
            original_exception=original_exception,
        )
        self.retry_after_seconds = retry_after_seconds


class NetworkError(ExchangeError):
    """
    Network connectivity error - retryable with exponential backoff.

    Includes timeouts, connection errors, DNS failures, etc.
    """

    def __init__(
        self,
        message: str = "Network error",
        code: str = "NETWORK_ERROR",
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=True,
            code=code,
            original_exception=original_exception,
        )


class ServerError(ExchangeError):
    """
    Exchange server error (5xx) - retryable with backoff.

    Indicates temporary server issues that may resolve on retry.
    """

    def __init__(
        self,
        message: str = "Server error",
        code: str = "SERVER_ERROR",
        status_code: Optional[int] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=True,
            code=code,
            original_exception=original_exception,
        )
        self.status_code = status_code


class TemporaryError(ExchangeError):
    """
    Temporary exchange error - retryable after brief wait.

    Generic category for transient errors that may resolve quickly.
    """

    def __init__(
        self,
        message: str,
        code: str = "TEMPORARY_ERROR",
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=True,
            code=code,
            original_exception=original_exception,
        )


# ======================== Fatal Errors (Not Retryable) ========================


class InvalidOrderError(ExchangeError):
    """
    Invalid order parameters - not retryable without fixing request.

    Includes: invalid symbol, invalid size, invalid price, etc.
    """

    def __init__(
        self,
        message: str = "Invalid order parameters",
        code: str = "INVALID_ORDER",
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=False,
            code=code,
            original_exception=original_exception,
        )


class InsufficientFundsError(ExchangeError):
    """
    Insufficient funds - not retryable without depositing more capital.
    """

    def __init__(
        self,
        message: str = "Insufficient funds",
        code: str = "INSUFFICIENT_FUNDS",
        required: Optional[float] = None,
        available: Optional[float] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=False,
            code=code,
            original_exception=original_exception,
        )
        self.required = required
        self.available = available


class AuthenticationError(ExchangeError):
    """
    Authentication failed - not retryable without fixing credentials.

    Includes: invalid API key, expired signature, missing permissions.
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        code: str = "AUTH_ERROR",
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=False,
            code=code,
            original_exception=original_exception,
        )


class PermissionError(ExchangeError):
    """
    Insufficient permissions - not retryable without API key changes.

    Includes: margin not enabled, feature not available for account tier.
    """

    def __init__(
        self,
        message: str = "Insufficient permissions",
        code: str = "PERMISSION_DENIED",
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=False,
            code=code,
            original_exception=original_exception,
        )


class OrderNotFoundError(ExchangeError):
    """
    Order not found - not retryable (order ID doesn't exist).
    """

    def __init__(
        self,
        message: str = "Order not found",
        code: str = "ORDER_NOT_FOUND",
        order_id: Optional[str] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=False,
            code=code,
            original_exception=original_exception,
        )
        self.order_id = order_id


class DuplicateOrderError(ExchangeError):
    """
    Duplicate order - not retryable (order already exists).
    """

    def __init__(
        self,
        message: str = "Duplicate order",
        code: str = "DUPLICATE_ORDER",
        order_id: Optional[str] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=False,
            code=code,
            original_exception=original_exception,
        )
        self.order_id = order_id


class MarketClosedError(ExchangeError):
    """
    Market closed - not retryable until market reopens.
    """

    def __init__(
        self,
        message: str = "Market closed",
        code: str = "MARKET_CLOSED",
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=False,
            code=code,
            original_exception=original_exception,
        )


class ValidationError(ExchangeError):
    """
    Request validation failed - not retryable without fixing request.
    """

    def __init__(
        self,
        message: str = "Validation failed",
        code: str = "VALIDATION_ERROR",
        field: Optional[str] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            retryable=False,
            code=code,
            original_exception=original_exception,
        )
        self.field = field


# ======================== Helper Functions ========================


def classify_http_error(
    status_code: int,
    response_body: Optional[str] = None,
    error_code: Optional[str] = None,
) -> ExchangeError:
    """
    Classify HTTP error by status code and response content.

    Args:
        status_code: HTTP status code
        response_body: Response body text (optional)
        error_code: Exchange-specific error code (optional)

    Returns:
        Appropriate ExchangeError subclass

    Example:
        >>> error = classify_http_error(429, "Rate limit exceeded")
        >>> isinstance(error, RateLimitError)
        True
    """
    message = response_body or f"HTTP {status_code}"

    # 4xx Client Errors (mostly fatal)
    if status_code == 400:
        return InvalidOrderError(message=message, code=error_code or "BAD_REQUEST")
    elif status_code == 401:
        return AuthenticationError(message=message, code=error_code or "UNAUTHORIZED")
    elif status_code == 403:
        return PermissionError(message=message, code=error_code or "FORBIDDEN")
    elif status_code == 404:
        return OrderNotFoundError(message=message, code=error_code or "NOT_FOUND")
    elif status_code == 429:
        return RateLimitError(message=message, code=error_code or "RATE_LIMIT")

    # 5xx Server Errors (retryable)
    elif status_code >= 500:
        return ServerError(
            message=message,
            code=error_code or f"SERVER_ERROR_{status_code}",
            status_code=status_code,
        )

    # Other 4xx (fatal)
    elif 400 <= status_code < 500:
        return ValidationError(message=message, code=error_code or f"CLIENT_ERROR_{status_code}")

    # Unknown status code
    return ExchangeError(
        message=message,
        retryable=False,
        code=error_code or f"HTTP_{status_code}",
    )


def is_retryable(error: Exception) -> bool:
    """
    Check if an error is retryable.

    Args:
        error: Exception to check

    Returns:
        True if error is retryable, False otherwise

    Example:
        >>> is_retryable(RateLimitError())
        True
        >>> is_retryable(InvalidOrderError())
        False
    """
    if isinstance(error, ExchangeError):
        return error.retryable
    return False


def get_retry_delay(error: Exception, attempt: int, base_delay: float = 1.0) -> float:
    """
    Calculate retry delay with exponential backoff.

    Args:
        error: Exception that occurred
        attempt: Retry attempt number (0-indexed)
        base_delay: Base delay in seconds (default 1.0)

    Returns:
        Delay in seconds before next retry

    Example:
        >>> delay = get_retry_delay(RateLimitError(retry_after_seconds=5.0), 0)
        >>> delay
        5.0
        >>> delay = get_retry_delay(NetworkError(), 2, base_delay=1.0)
        >>> delay  # 1.0 * 2^2 = 4.0
        4.0
    """
    # Respect rate limit retry-after
    if isinstance(error, RateLimitError):
        return error.retry_after_seconds

    # Exponential backoff for other retryable errors
    if isinstance(error, ExchangeError) and error.retryable:
        return min(base_delay * (2 ** attempt), 60.0)  # Cap at 60 seconds

    return 0.0  # Non-retryable
