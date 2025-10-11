"""
Core trading agent components.

This module contains the fundamental building blocks for trading agents:
- Execution agents for order management and trade execution
- Signal processing and analysis components
- Market scanning and monitoring capabilities
- Performance monitoring and metrics collection
- Serialization utilities for JSON and Redis
- Redis stream contracts with Pydantic validators
- AutoGen integration wrappers for AI agent coordination

**Quick Start:**
    from agents.core import MarketScanner, EnhancedExecutionAgent, analyze
    from agents.core import json_dumps, serialize_for_redis
    from agents.core import SignalPayload, MetricsLatencyPayload
    from agents.core import K_COMPONENT, K_PAIR, K_SIGNAL_ID

**Available Classes:**
- MarketScanner - Market data scanning and monitoring
- EnhancedExecutionAgent - Advanced order execution with risk management
- ScalpingExecutionEngine - High-frequency scalping execution
- OrderRequest, OrderFill - Order data structures
- SignalPayload, MetricsLatencyPayload, HealthStatusPayload - Redis contracts
- AnalysisContext - Signal analysis context

**Available Functions:**
- analyze() - Signal analysis with multiple indicators
- analyze_batch() - Batch signal analysis
- json_dumps() - JSON serialization with Decimal/datetime support
- serialize_for_redis() - Prepare objects for Redis storage
"""

from __future__ import annotations

# Primary agent classes
from .market_scanner import MarketScanner, fetch_ohlcv_df
from .execution_agent import (
    EnhancedExecutionAgent,
    ScalpingExecutionEngine,
    OrderRequest,
    OrderFill,
    as_decimal,
)
from .signal_analyst import (
    analyze,
    analyze_batch,
    AnalysisContext,
)

# Serialization utilities
from .serialization import (
    json_dumps,
    serialize_for_redis,
    decimal_to_str,
    ts_to_iso,
)

# Redis stream contracts
from .contracts import (
    SignalPayload,
    MetricsLatencyPayload,
    HealthStatusPayload,
)

# Logging key constants (commonly used)
from . import log_keys
from .log_keys import (
    K_COMPONENT,
    K_PAIR,
    K_SIGNAL_ID,
    K_SIGNAL_TYPE,
    K_ACTION,
)

# Explicit exports for clean public API
__all__ = [
    # Market scanning
    "MarketScanner",
    "fetch_ohlcv_df",
    # Execution agents
    "EnhancedExecutionAgent",
    "ScalpingExecutionEngine",
    "OrderRequest",
    "OrderFill",
    "as_decimal",
    # Signal analysis
    "analyze",
    "analyze_batch",
    "AnalysisContext",
    # Serialization
    "json_dumps",
    "serialize_for_redis",
    "decimal_to_str",
    "ts_to_iso",
    # Contracts
    "SignalPayload",
    "MetricsLatencyPayload",
    "HealthStatusPayload",
    # Logging keys
    "log_keys",
    "K_COMPONENT",
    "K_PAIR",
    "K_SIGNAL_ID",
    "K_SIGNAL_TYPE",
    "K_ACTION",
]
