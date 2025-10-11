"""
Order execution and management components for scalping operations.

This module provides high-frequency order execution capabilities:
- Kraken exchange gateway with WebSocket and REST API integration
- Order optimization based on market conditions and latency
- Position management with real-time tracking
- Slippage modeling and execution quality monitoring
- Order routing and execution strategies
"""

from __future__ import annotations

from .kraken_gateway import KrakenGateway, OrderRequest, OrderResponse, Position
from .order_optimizer import (
    MarketConditions,
    OptimizedOrder,
    OrderOptimizer,
    OrderTactic,
)
from .position_manager import PositionManager

__all__ = [
    "KrakenGateway",
    "OrderRequest",
    "OrderResponse",
    "Position",
    "OrderOptimizer",
    "MarketConditions",
    "OptimizedOrder",
    "OrderTactic",
    "PositionManager",
]
