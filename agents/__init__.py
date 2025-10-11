"""
High-level trading agents package for crypto-ai-bot.

This package contains all trading agent implementations including:
- Core execution and signal processing agents
- Scalping strategies and risk management
- Machine learning predictors and feature engineering
- Infrastructure components for Redis, health monitoring, and data pipelines
- Specialized agents for arbitrage, flash loans, and liquidity provision

All agents follow consistent patterns:
- Structured logging with logging.getLogger(__name__)
- Comprehensive type hints with minimal Any usage
- Timezone-aware datetime operations using UTC
- Decimal precision for financial calculations
- Proper error handling and validation

**Quick Start Examples:**

    # Import core trading agents
    from agents.core import MarketScanner, EnhancedExecutionAgent, analyze

    # Import infrastructure components
    from agents.infrastructure import RedisCloudClient, DataPipeline

    # Import serialization and contracts
    from agents.core import json_dumps, SignalPayload

    # Import logging keys for structured logging
    from agents.core import K_COMPONENT, K_PAIR, K_SIGNAL_ID

**Package Organization:**
- agents.core - Core trading agents (market_scanner, execution_agent, signal_analyst)
- agents.infrastructure - Redis clients, health monitoring, data pipelines
- agents.scalper - Scalping-specific strategies and execution
- agents.ml - Machine learning models and feature engineering
- agents.risk - Risk management and position sizing
- agents.special - Specialized agents (arbitrage, flash loans, liquidity)
"""

from __future__ import annotations

# Re-export commonly used core components
from .core import (
    # Agents
    MarketScanner,
    EnhancedExecutionAgent,
    ScalpingExecutionEngine,
    # Analysis
    analyze,
    analyze_batch,
    # Serialization
    json_dumps,
    serialize_for_redis,
    # Contracts
    SignalPayload,
    MetricsLatencyPayload,
    HealthStatusPayload,
    # Logging keys
    K_COMPONENT,
    K_PAIR,
    K_SIGNAL_ID,
)

# Re-export commonly used infrastructure components
from .infrastructure import (
    # Redis
    RedisCloudClient,
    RedisCloudConfig,
    # Health
    RedisHealthChecker,
    # Data pipeline
    DataPipeline,
    CircuitBreaker,
    # Utilities
    normalize_symbol,
    build_stream_key,
)

# Export submodules for deep access
from . import core
from . import infrastructure
from . import scalper
from . import ml
from . import risk
from . import special

__all__ = [
    # Submodules
    "core",
    "infrastructure",
    "scalper",
    "ml",
    "risk",
    "special",
    # Core agents
    "MarketScanner",
    "EnhancedExecutionAgent",
    "ScalpingExecutionEngine",
    # Analysis
    "analyze",
    "analyze_batch",
    # Serialization
    "json_dumps",
    "serialize_for_redis",
    # Contracts
    "SignalPayload",
    "MetricsLatencyPayload",
    "HealthStatusPayload",
    # Logging
    "K_COMPONENT",
    "K_PAIR",
    "K_SIGNAL_ID",
    # Infrastructure
    "RedisCloudClient",
    "RedisCloudConfig",
    "RedisHealthChecker",
    "DataPipeline",
    "CircuitBreaker",
    "normalize_symbol",
    "build_stream_key",
]
