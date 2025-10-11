"""Tick processing utilities.

This module contains classes to transform raw tick data into higher
level features consumed by the strategy. It currently implements a
simple sliding window processor that computes moving averages and
returns derived features after each update.
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional


@dataclass
class Features:
    """Computed features derived from recent tick history."""

    last_price: float
    sma_short: float
    sma_long: float
    volatility: float


class TickProcessor:
    """Compute rolling statistics from tick data.

    The processor keeps a window of recent prices to compute two
    simple moving averages (short and long) and a basic volatility
    estimate. These features are used by the signal generator to
    derive trading signals.
    """

    def __init__(self, short_window: int = 5, long_window: int = 20) -> None:
        if short_window <= 0 or long_window <= 0:
            raise ValueError("Window lengths must be positive")
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        self.short_window = short_window
        self.long_window = long_window
        self.prices: Deque[float] = deque(maxlen=long_window)

    def update(self, price: float) -> Optional[Features]:
        """Update the processor with a new price and return features.

        If there are not enough data points to compute the long moving
        average the function returns ``None``.

        Args:
            price: The latest trade price.

        Returns:
            A :class:`Features` instance or ``None`` if insufficient
            history is available.
        """
        self.prices.append(price)
        if len(self.prices) < self.long_window:
            return None
        # compute moving averages
        prices_list = list(self.prices)
        sma_long = sum(prices_list) / self.long_window
        sma_short = sum(prices_list[-self.short_window :]) / self.short_window
        # compute volatility as stddev of returns
        returns = [prices_list[i] - prices_list[i - 1] for i in range(1, len(prices_list))]
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        volatility = variance**0.5
        return Features(
            last_price=price, sma_short=sma_short, sma_long=sma_long, volatility=volatility
        )
