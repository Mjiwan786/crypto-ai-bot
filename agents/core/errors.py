"""
Custom exception hierarchy for agents.core modules.

Provides specific exception types for different error scenarios,
enabling better error handling and debugging throughout the trading system.
"""

from __future__ import annotations

from typing import Any, Optional

# ==============================================================================
# Base Exception
# ==============================================================================


class AgentError(Exception):
    """Base exception for all agent-related errors.

    All custom exceptions in agents.core inherit from this base class,
    allowing for broad exception handling when needed.

    Attributes:
        message: Human-readable error message
        details: Optional dictionary with additional error context
    """

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None) -> None:
        """Initialize agent error.

        Args:
            message: Error message describing what went wrong
            details: Optional dictionary with additional context (e.g., symbol, timestamp)
        """
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return string representation of error.

        Returns:
            Formatted error message with details if available
        """
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message

    def __repr__(self) -> str:
        """Return repr for debugging.

        Returns:
            Technical representation of the exception
        """
        return f"{self.__class__.__name__}(message={self.message!r}, details={self.details!r})"


# ==============================================================================
# Configuration Errors
# ==============================================================================


class ConfigError(AgentError):
    """Configuration-related errors.

    Raised when there are issues with configuration files, environment variables,
    or validation of configuration parameters.

    Examples:
        - Missing required configuration keys
        - Invalid configuration values
        - Configuration file parsing errors
        - Environment variable issues
    """

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        config_file: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize configuration error.

        Args:
            message: Error description
            config_key: Optional configuration key that caused the error
            config_file: Optional path to configuration file
            details: Optional additional context
        """
        error_details = details or {}
        if config_key:
            error_details["config_key"] = config_key
        if config_file:
            error_details["config_file"] = config_file

        super().__init__(message, error_details)
        self.config_key = config_key
        self.config_file = config_file


class ValidationError(ConfigError):
    """Configuration validation errors.

    Raised when configuration values fail validation checks.

    Examples:
        - Invalid timeframe values
        - Out of range parameters (e.g., confidence > 1.0)
        - Type mismatches
    """

    def __init__(
        self,
        message: str,
        field_name: Optional[str] = None,
        field_value: Optional[Any] = None,
        expected_type: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize validation error.

        Args:
            message: Error description
            field_name: Name of the field that failed validation
            field_value: The invalid value
            expected_type: Expected type or format
            details: Optional additional context
        """
        error_details = details or {}
        if field_name:
            error_details["field_name"] = field_name
        if field_value is not None:
            error_details["field_value"] = str(field_value)
        if expected_type:
            error_details["expected_type"] = expected_type

        super().__init__(message, details=error_details)
        self.field_name = field_name
        self.field_value = field_value
        self.expected_type = expected_type


# ==============================================================================
# Connectivity Errors
# ==============================================================================


class ConnectivityError(AgentError):
    """Network and connectivity-related errors.

    Raised when there are issues connecting to external services like
    Redis, exchanges, or APIs.

    Examples:
        - Redis connection failures
        - Exchange API timeouts
        - Network interruptions
        - Authentication failures
    """

    def __init__(
        self,
        message: str,
        service: Optional[str] = None,
        endpoint: Optional[str] = None,
        retry_count: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize connectivity error.

        Args:
            message: Error description
            service: Name of the service (e.g., "redis", "kraken")
            endpoint: Connection endpoint or URL
            retry_count: Number of retry attempts made
            details: Optional additional context
        """
        error_details = details or {}
        if service:
            error_details["service"] = service
        if endpoint:
            error_details["endpoint"] = endpoint
        if retry_count is not None:
            error_details["retry_count"] = retry_count

        super().__init__(message, error_details)
        self.service = service
        self.endpoint = endpoint
        self.retry_count = retry_count


class RedisError(ConnectivityError):
    """Redis-specific connectivity errors.

    Raised for Redis connection, stream, or operation failures.
    """

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        stream_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize Redis error.

        Args:
            message: Error description
            operation: Redis operation that failed (e.g., "xadd", "xreadgroup")
            stream_name: Name of the Redis stream
            details: Optional additional context
        """
        error_details = details or {}
        if operation:
            error_details["operation"] = operation
        if stream_name:
            error_details["stream_name"] = stream_name

        super().__init__(message, service="redis", details=error_details)
        self.operation = operation
        self.stream_name = stream_name


class ExchangeError(ConnectivityError):
    """Exchange API-related errors.

    Raised for exchange connection or API failures.
    """

    def __init__(
        self,
        message: str,
        exchange: str = "kraken",
        api_method: Optional[str] = None,
        http_status: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize exchange error.

        Args:
            message: Error description
            exchange: Exchange name (default: kraken)
            api_method: API method that failed
            http_status: HTTP status code if applicable
            details: Optional additional context
        """
        error_details = details or {}
        if api_method:
            error_details["api_method"] = api_method
        if http_status:
            error_details["http_status"] = http_status

        super().__init__(message, service=exchange, details=error_details)
        self.exchange = exchange
        self.api_method = api_method
        self.http_status = http_status


# ==============================================================================
# Risk Management Errors
# ==============================================================================


class RiskViolation(AgentError):
    """Risk management rule violations.

    Raised when trading operations violate risk management rules.

    Examples:
        - Position size too large
        - Daily loss limit exceeded
        - Maximum drawdown reached
        - Spread too wide
        - Insufficient liquidity
    """

    def __init__(
        self,
        message: str,
        rule_name: Optional[str] = None,
        current_value: Optional[float] = None,
        limit_value: Optional[float] = None,
        symbol: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize risk violation error.

        Args:
            message: Error description
            rule_name: Name of the violated risk rule
            current_value: Current value that violated the rule
            limit_value: The limit that was exceeded
            symbol: Trading symbol if applicable
            details: Optional additional context
        """
        error_details = details or {}
        if rule_name:
            error_details["rule_name"] = rule_name
        if current_value is not None:
            error_details["current_value"] = current_value
        if limit_value is not None:
            error_details["limit_value"] = limit_value
        if symbol:
            error_details["symbol"] = symbol

        super().__init__(message, error_details)
        self.rule_name = rule_name
        self.current_value = current_value
        self.limit_value = limit_value
        self.symbol = symbol


class PositionSizeError(RiskViolation):
    """Position size violations.

    Raised when position size exceeds allowed limits.
    """

    def __init__(
        self,
        message: str,
        requested_size: float,
        max_allowed_size: float,
        symbol: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize position size error.

        Args:
            message: Error description
            requested_size: Requested position size
            max_allowed_size: Maximum allowed position size
            symbol: Trading symbol
            details: Optional additional context
        """
        super().__init__(
            message,
            rule_name="max_position_size",
            current_value=requested_size,
            limit_value=max_allowed_size,
            symbol=symbol,
            details=details,
        )
        self.requested_size = requested_size
        self.max_allowed_size = max_allowed_size


class DrawdownError(RiskViolation):
    """Drawdown limit violations.

    Raised when drawdown exceeds allowed limits.
    """

    def __init__(
        self,
        message: str,
        current_drawdown: float,
        max_drawdown: float,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize drawdown error.

        Args:
            message: Error description
            current_drawdown: Current drawdown (negative value)
            max_drawdown: Maximum allowed drawdown
            details: Optional additional context
        """
        super().__init__(
            message,
            rule_name="max_drawdown",
            current_value=current_drawdown,
            limit_value=max_drawdown,
            details=details,
        )
        self.current_drawdown = current_drawdown
        self.max_drawdown = max_drawdown


# ==============================================================================
# Execution Errors
# ==============================================================================


class ExecutionError(AgentError):
    """Order execution-related errors.

    Raised when there are issues with order placement, filling, or management.

    Examples:
        - Order rejection by exchange
        - Insufficient balance
        - Invalid order parameters
        - Order timeout
        - Partial fill failures
    """

    def __init__(
        self,
        message: str,
        order_id: Optional[str] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        error_code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize execution error.

        Args:
            message: Error description
            order_id: Order ID if applicable
            symbol: Trading symbol
            side: Order side (buy/sell)
            error_code: Exchange error code if available
            details: Optional additional context
        """
        error_details = details or {}
        if order_id:
            error_details["order_id"] = order_id
        if symbol:
            error_details["symbol"] = symbol
        if side:
            error_details["side"] = side
        if error_code:
            error_details["error_code"] = error_code

        super().__init__(message, error_details)
        self.order_id = order_id
        self.symbol = symbol
        self.side = side
        self.error_code = error_code


class OrderRejectedError(ExecutionError):
    """Order rejected by exchange.

    Raised when an order is rejected during placement.
    """

    def __init__(
        self,
        message: str,
        symbol: str,
        side: str,
        reason: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize order rejected error.

        Args:
            message: Error description
            symbol: Trading symbol
            side: Order side
            reason: Rejection reason from exchange
            details: Optional additional context
        """
        error_details = details or {}
        if reason:
            error_details["rejection_reason"] = reason

        super().__init__(message, symbol=symbol, side=side, details=error_details)
        self.reason = reason


class InsufficientBalanceError(ExecutionError):
    """Insufficient balance for order.

    Raised when account balance is insufficient for order execution.
    """

    def __init__(
        self,
        message: str,
        required_balance: float,
        available_balance: float,
        currency: str = "USD",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize insufficient balance error.

        Args:
            message: Error description
            required_balance: Required balance for order
            available_balance: Available balance in account
            currency: Currency code
            details: Optional additional context
        """
        error_details = details or {}
        error_details["required_balance"] = required_balance
        error_details["available_balance"] = available_balance
        error_details["currency"] = currency

        super().__init__(message, details=error_details)
        self.required_balance = required_balance
        self.available_balance = available_balance
        self.currency = currency


# ==============================================================================
# Signal Processing Errors
# ==============================================================================


class SignalError(AgentError):
    """Signal generation and processing errors.

    Raised when there are issues with signal generation, validation, or routing.
    """

    def __init__(
        self,
        message: str,
        signal_id: Optional[str] = None,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize signal error.

        Args:
            message: Error description
            signal_id: Signal identifier if applicable
            strategy: Strategy name
            symbol: Trading symbol
            details: Optional additional context
        """
        error_details = details or {}
        if signal_id:
            error_details["signal_id"] = signal_id
        if strategy:
            error_details["strategy"] = strategy
        if symbol:
            error_details["symbol"] = symbol

        super().__init__(message, error_details)
        self.signal_id = signal_id
        self.strategy = strategy
        self.symbol = symbol


class SignalValidationError(SignalError):
    """Signal validation failures.

    Raised when signal data fails validation checks.
    """

    pass


# ==============================================================================
# Data Errors
# ==============================================================================


class DataError(AgentError):
    """Market data-related errors.

    Raised when there are issues with market data fetching or processing.
    """

    def __init__(
        self,
        message: str,
        symbol: Optional[str] = None,
        data_type: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize data error.

        Args:
            message: Error description
            symbol: Trading symbol
            data_type: Type of data (e.g., "ticker", "ohlcv", "orderbook")
            details: Optional additional context
        """
        error_details = details or {}
        if symbol:
            error_details["symbol"] = symbol
        if data_type:
            error_details["data_type"] = data_type

        super().__init__(message, error_details)
        self.symbol = symbol
        self.data_type = data_type


class StaleDataError(DataError):
    """Stale or outdated data error.

    Raised when market data is too old to be reliable.
    """

    def __init__(
        self,
        message: str,
        symbol: str,
        data_age_seconds: float,
        max_age_seconds: float,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize stale data error.

        Args:
            message: Error description
            symbol: Trading symbol
            data_age_seconds: Age of the data in seconds
            max_age_seconds: Maximum allowed age
            details: Optional additional context
        """
        error_details = details or {}
        error_details["data_age_seconds"] = data_age_seconds
        error_details["max_age_seconds"] = max_age_seconds

        super().__init__(message, symbol=symbol, details=error_details)
        self.data_age_seconds = data_age_seconds
        self.max_age_seconds = max_age_seconds


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    # Base
    "AgentError",
    # Configuration
    "ConfigError",
    "ValidationError",
    # Connectivity
    "ConnectivityError",
    "RedisError",
    "ExchangeError",
    # Risk
    "RiskViolation",
    "PositionSizeError",
    "DrawdownError",
    # Execution
    "ExecutionError",
    "OrderRejectedError",
    "InsufficientBalanceError",
    # Signals
    "SignalError",
    "SignalValidationError",
    # Data
    "DataError",
    "StaleDataError",
]
