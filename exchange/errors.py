"""
Exchange-specific exception types.

Provides a hierarchy of exceptions for exchange operations so that
callers can handle different failure modes (network, auth, funds, etc.)
without coupling to CCXT internals.
"""


class ExchangeError(Exception):
    """Base exception for all exchange-related errors.

    Attributes:
        exchange_id: The exchange that raised the error (e.g. "kraken").
        original: The original exception from the underlying library, if any.
    """

    def __init__(
        self,
        message: str,
        exchange_id: str = "",
        original: Exception | None = None,
    ) -> None:
        self.exchange_id = exchange_id
        self.original = original
        super().__init__(message)


class ExchangeNetworkError(ExchangeError):
    """Raised when a network-level failure occurs (timeout, DNS, connection reset)."""


class ExchangeAuthError(ExchangeError):
    """Raised when authentication fails (invalid API key/secret, expired nonce)."""


class InsufficientFundsError(ExchangeError):
    """Raised when the account lacks sufficient balance to execute an order."""


class InvalidOrderError(ExchangeError):
    """Raised when an order is rejected due to invalid parameters
    (e.g. below minimum size, invalid pair, price out of range)."""


class ExchangeNotAvailableError(ExchangeError):
    """Raised when the requested exchange is not supported or not available
    in the user's region."""


class RateLimitError(ExchangeError):
    """Raised when the exchange rate limit has been exceeded."""
