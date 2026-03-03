"""
Multi-exchange adapter layer for crypto_ai_bot.

Provides a unified interface for interacting with multiple cryptocurrency
exchanges through CCXT. This is an additive layer that runs alongside
the existing Kraken-coupled production engine.

Usage:
    from exchange import ExchangeFactory

    # Public data (no auth)
    adapter = ExchangeFactory.create_public("kraken")
    await adapter.connect()
    ticker = await adapter.fetch_ticker("BTC/USD")

    # Authenticated trading
    adapter = ExchangeFactory.create(
        exchange_id="kraken",
        api_key="...",
        secret="...",
        sandbox=True,
    )
    await adapter.connect()
    balance = await adapter.fetch_balance()
"""

from exchange.base_adapter import (
    BaseExchangeAdapter,
    Ticker,
    OHLCV,
    OrderResult,
    Balance,
    ExchangeLimits,
    OrderSide,
    OrderType,
    OrderStatus,
)
from exchange.ccxt_adapter import CcxtAdapter
from exchange.exchange_factory import ExchangeFactory
from exchange.exchange_registry import ExchangeRegistry, ExchangeConfig
from exchange.errors import (
    ExchangeError,
    ExchangeNetworkError,
    ExchangeAuthError,
    InsufficientFundsError,
    InvalidOrderError,
    ExchangeNotAvailableError,
    RateLimitError,
)

__all__ = [
    # Abstract base
    "BaseExchangeAdapter",
    # Dataclasses
    "Ticker",
    "OHLCV",
    "OrderResult",
    "Balance",
    "ExchangeLimits",
    # Enums
    "OrderSide",
    "OrderType",
    "OrderStatus",
    # Implementation
    "CcxtAdapter",
    # Factory & Registry
    "ExchangeFactory",
    "ExchangeRegistry",
    "ExchangeConfig",
    # Errors
    "ExchangeError",
    "ExchangeNetworkError",
    "ExchangeAuthError",
    "InsufficientFundsError",
    "InvalidOrderError",
    "ExchangeNotAvailableError",
    "RateLimitError",
]
