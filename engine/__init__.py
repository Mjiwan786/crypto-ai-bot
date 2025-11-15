"""
engine - Live Trading Engine Module

Production-grade live engine that wires:
WS → indicators → regime → router → strategy → risk → publisher

Exports:
- LiveEngine: Main engine class
- EngineConfig: Configuration
- OHLCVCache: Rolling OHLCV cache
- CircuitBreakerManager: Breaker management

Example:
    >>> from engine import LiveEngine, EngineConfig
    >>> config = EngineConfig(mode="paper")
    >>> engine = LiveEngine(config=config)
    >>> await engine.start()
"""

from engine.loop import (
    LiveEngine,
    EngineConfig,
    OHLCVCache,
    CircuitBreakerManager,
)

__all__ = [
    "LiveEngine",
    "EngineConfig",
    "OHLCVCache",
    "CircuitBreakerManager",
]
