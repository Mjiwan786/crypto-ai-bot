"""Order book aggregator for level one quotes.

This module maintains a simple top‑of‑book representation. Incoming
update events adjust the best bid and ask prices. For the purposes
of the scalper strategy only the inside quote is required. Depth of
book could be added later if needed.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TopOfBook:
    """Represents the best bid and ask in the order book."""

    bid_price: Optional[float] = None
    bid_size: float = 0.0
    ask_price: Optional[float] = None
    ask_size: float = 0.0


class OrderBookAggregator:
    """Maintain the top of book for a single trading pair."""

    def __init__(self) -> None:
        self.top: TopOfBook = TopOfBook()

    def update(self, side: str, price: float, size: float) -> None:
        """Update the book with a quote change.

        Args:
            side: "buy" for bids, "sell" for asks.
            price: The price level being updated.
            size: The volume available at that price. If zero the
                level is removed.
        """
        if side == "buy":
            # update bid side
            if size <= 0.0:
                if self.top.bid_price == price:
                    self.top.bid_price = None
                    self.top.bid_size = 0.0
            else:
                if self.top.bid_price is None or price > self.top.bid_price:
                    self.top.bid_price = price
                    self.top.bid_size = size
        elif side == "sell":
            # update ask side
            if size <= 0.0:
                if self.top.ask_price == price:
                    self.top.ask_price = None
                    self.top.ask_size = 0.0
            else:
                if self.top.ask_price is None or price < self.top.ask_price:
                    self.top.ask_price = price
                    self.top.ask_size = size

    def best_bid(self) -> Optional[float]:
        return self.top.bid_price

    def best_ask(self) -> Optional[float]:
        return self.top.ask_price
