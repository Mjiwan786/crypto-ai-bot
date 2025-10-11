"""
Scalper agent package for high-frequency trading operations.

This package provides comprehensive scalping capabilities:
- High-frequency order execution and management
- Market analysis including liquidity and order flow analysis
- Risk management with real-time monitoring and circuit breakers
- Backtesting and performance analysis
- Infrastructure components for state management and monitoring
- Configuration management and settings
"""

from __future__ import annotations

from .kraken_scalper_agent import KrakenScalperAgent

__all__ = ["KrakenScalperAgent"]
