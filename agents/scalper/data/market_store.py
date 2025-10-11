"""
Market data structures for scalper
"""

from dataclasses import dataclass


@dataclass
class TickRecord:
    """Represents a single trade tick"""

    timestamp: float
    price: float
    volume: float
    side: str  # "buy" | "sell"

    def __post_init__(self):
        """Validate the tick record"""
        if self.side not in ["buy", "sell"]:
            raise ValueError(f"Invalid side: {self.side}. Must be 'buy' or 'sell'")
        if self.price <= 0:
            raise ValueError("Price must be positive")
        if self.volume <= 0:
            raise ValueError("Volume must be positive")
