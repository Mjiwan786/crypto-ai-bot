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
from exchange.ccxt_pro_adapter import CcxtProWSAdapter
from exchange.ws_adapter import (
    BaseWSAdapter,
    TickerUpdate,
    OHLCVUpdate,
    TradeUpdate,
)
from exchange.multi_exchange_streamer import MultiExchangeStreamer
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
    # REST Implementation
    "CcxtAdapter",
    # WebSocket Implementation
    "BaseWSAdapter",
    "CcxtProWSAdapter",
    "TickerUpdate",
    "OHLCVUpdate",
    "TradeUpdate",
    "MultiExchangeStreamer",
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
