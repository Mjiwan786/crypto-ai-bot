"""
AI Predicted Signals — Base Strategy

Abstract base class for all trading strategies. Each strategy
implements compute_signal() and declares its required indicators.
Returns a StrategyResult with direction, confidence, and metadata.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any
import numpy as np


@dataclass
class StrategyResult:
    direction: str  # "long" | "short" | "neutral"
    confidence: float  # 0-100
    strategy_name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base for trading strategies."""

    name: str = "base"

    @abstractmethod
    def compute_signal(self, ohlcv: np.ndarray, indicators: Dict[str, np.ndarray]) -> StrategyResult:
        """Compute a trading signal from OHLCV data and pre-computed indicators."""
        ...

    @abstractmethod
    def get_required_indicators(self) -> List[str]:
        """Return list of indicator names this strategy needs (e.g., ['rsi', 'macd'])."""
        ...

    def get_params(self) -> Dict[str, Any]:
        """Return strategy parameters for logging/serialization."""
        return {}
