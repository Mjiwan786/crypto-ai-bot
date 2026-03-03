"""
Factory for creating exchange adapter instances.

Provides convenience methods for creating authenticated or public-only
adapters for any supported exchange.
"""

from __future__ import annotations

from exchange.base_adapter import BaseExchangeAdapter
from exchange.ccxt_adapter import CcxtAdapter, _SUPPORTED_EXCHANGES
from exchange.errors import ExchangeNotAvailableError


class ExchangeFactory:
    """Factory class for creating exchange adapters.

    Usage::

        # Authenticated adapter
        adapter = ExchangeFactory.create("kraken", api_key="...", secret="...")

        # Public-only adapter (market data, no trading)
        adapter = ExchangeFactory.create_public("coinbase")

        # List supported exchanges
        ExchangeFactory.supported_exchanges()  # ["binance", "bybit", "coinbase", "kraken"]
    """

    @staticmethod
    def create(
        exchange_id: str,
        api_key: str = "",
        secret: str = "",
        passphrase: str = "",
        sandbox: bool = True,
    ) -> BaseExchangeAdapter:
        """Create an exchange adapter with optional authentication.

        Args:
            exchange_id: Lowercase exchange name (e.g. ``"kraken"``).
            api_key: API key for authenticated operations.
            secret: API secret.
            passphrase: Passphrase (needed by some exchanges like Coinbase).
            sandbox: If ``True`` (default), use the exchange sandbox/testnet.

        Returns:
            A ``BaseExchangeAdapter`` instance (currently always ``CcxtAdapter``).

        Raises:
            ExchangeNotAvailableError: If the exchange is not supported.
        """
        exchange_id = exchange_id.lower()
        if exchange_id not in _SUPPORTED_EXCHANGES:
            raise ExchangeNotAvailableError(
                f"Exchange '{exchange_id}' is not supported. "
                f"Supported: {sorted(_SUPPORTED_EXCHANGES)}",
                exchange_id=exchange_id,
            )
        return CcxtAdapter(
            exchange_id=exchange_id,
            api_key=api_key,
            secret=secret,
            passphrase=passphrase,
            sandbox=sandbox,
        )

    @staticmethod
    def create_public(exchange_id: str) -> BaseExchangeAdapter:
        """Create a public-only adapter (no authentication, market data only).

        This is a convenience shortcut for ``create(exchange_id)`` with no
        credentials and sandbox disabled (public endpoints don't need sandbox).

        Args:
            exchange_id: Lowercase exchange name.

        Returns:
            A ``BaseExchangeAdapter`` instance configured for public access.

        Raises:
            ExchangeNotAvailableError: If the exchange is not supported.
        """
        exchange_id = exchange_id.lower()
        if exchange_id not in _SUPPORTED_EXCHANGES:
            raise ExchangeNotAvailableError(
                f"Exchange '{exchange_id}' is not supported. "
                f"Supported: {sorted(_SUPPORTED_EXCHANGES)}",
                exchange_id=exchange_id,
            )
        return CcxtAdapter(
            exchange_id=exchange_id,
            api_key="",
            secret="",
            passphrase="",
            sandbox=False,
        )

    @staticmethod
    def supported_exchanges() -> list[str]:
        """Return a sorted list of supported exchange IDs."""
        return sorted(_SUPPORTED_EXCHANGES)
