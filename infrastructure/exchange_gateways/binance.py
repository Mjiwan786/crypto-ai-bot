"""
Binance exchange gateway.

Provides a simple wrapper around the ccxt Binance client for placing
orders and retrieving balances.  This implementation assumes spot
trading and does not handle margin or futures products.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

try:
    import ccxt  # type: ignore
except ImportError:  # pragma: no cover
    ccxt = None  # type: ignore

from config.config_loader import ExchangeSettings


logger = logging.getLogger(__name__)


class BinanceGateway:
    """Basic Binance gateway using ccxt."""

    def __init__(self, settings: ExchangeSettings) -> None:
        if ccxt is None:
            raise RuntimeError("ccxt package is required for BinanceGateway")
        self.client = ccxt.binance({
            "apiKey": settings.api_key,
            "secret": settings.api_secret,
            "enableRateLimit": True,
        })
        self.symbol = "BTC/USDT"

    def get_balance(self) -> Dict[str, float]:
        base, quote = self.symbol.split("/")
        try:
            balances = self.client.fetch_balance()["free"]
            return {
                "base": balances.get(base, 0.0),
                "quote": balances.get(quote, 0.0),
            }
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to fetch balances: %s", exc)
            return {"base": 0.0, "quote": 0.0}

    def create_order(self, side: str, price: float, amount: float) -> Optional[str]:
        try:
            order = self.client.create_order(
                symbol=self.symbol,
                type="limit",
                side=side,
                amount=amount,
                price=price,
            )
            return order.get("id")
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to create order: %s", exc)
            return None