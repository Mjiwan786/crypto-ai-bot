"""
Kraken exchange gateway.

This module provides a thin wrapper around the ccxt Kraken client.  It
abstracts away authentication and order placement, returning simple
Python objects rather than raw ccxt structures.
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


class KrakenGateway:
    """Minimal Kraken gateway built on top of ccxt."""

    def __init__(self, settings: ExchangeSettings) -> None:
        if ccxt is None:
            raise RuntimeError("ccxt package is required for KrakenGateway")
        self.client = ccxt.kraken({
            "apiKey": settings.api_key,
            "secret": settings.api_secret,
            "enableRateLimit": True,
        })
        # Default trading pair; could be overridden per trade
        self.symbol = "BTC/USD"

    def get_balance(self) -> Dict[str, float]:
        """
        Fetch available balances for the base and quote currencies of the
        configured trading pair.  Returns a dictionary with keys
        "base" and "quote".  Missing keys are set to zero.
        """
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
        """
        Place a limit order on Kraken and return the order id.

        Args:
            side: "buy" or "sell".
            price: The limit price.
            amount: The quantity to trade.

        Returns:
            The order id on success, or None on failure.
        """
        try:
            order = self.client.create_order(
                symbol=self.symbol,
                type="limit",
                side=side,
                amount=amount,
                price=price,
            )
            return order.get("id") or order.get("txid", [None])[0]
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to create order: %s", exc)
            return None