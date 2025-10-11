"""
Abstract base class for trading strategies.

All strategies should inherit from `Strategy` and implement the
`generate_signals` method to produce trading signals based on market data.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class Strategy(ABC):
    """Base class for trading strategies."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    def generate_signals(self, market_data: Any) -> Any:
        """Generate trading signals given market data.

        Args:
            market_data: A data structure containing price and volume
                information for the assets traded.

        Returns:
            A signal object consumed by agents to place orders.
        """
        raise NotImplementedError
