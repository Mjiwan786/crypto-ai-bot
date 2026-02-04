"""
Infrastructure components for trading agents.

This module provides essential infrastructure services:
- Redis Cloud TLS connection management with health monitoring
- Data pipeline components for market data ingestion
- API health monitoring and circuit breaker functionality
- Redis health checking with comprehensive diagnostics
- Connection pooling and retry logic for resilient operations

**Quick Start:**
    from agents.infrastructure import RedisCloudClient, RedisHealthChecker
    from agents.infrastructure import DataPipeline, CircuitBreaker
    from agents.infrastructure import normalize_symbol, build_stream_key

**Available Classes:**
- RedisCloudClient - TLS-enabled Redis Cloud client with connection pooling
- RedisCloudConfig - Configuration for Redis Cloud connection
- RedisHealthChecker - Comprehensive Redis health monitoring
- RedisHealthResult - Health check result data structure
- DataPipeline - Market data ingestion and processing pipeline
- CircuitBreaker - Circuit breaker for API resilience
- CircuitBreakerState - Circuit breaker state enum

**Available Functions:**
- normalize_symbol() - Standardize trading pair symbols
- normalize_trade() - Normalize trade data format
- normalize_spread() - Normalize spread data format
- build_stream_key() - Build Redis stream keys from templates
- calc_spread_bps() - Calculate spread in basis points

**Available Exceptions:**
- PipelineDegraded - Pipeline operating in degraded mode
- CircuitBreakerOpen - Circuit breaker is open, rejecting requests
"""

from __future__ import annotations

# Redis client and configuration
from .redis_client import (
    RedisCloudClient,
    RedisCloudConfig,
)

# Redis health monitoring
from .redis_health import (
    RedisHealthChecker,
    RedisHealthConfig,
    RedisHealthResult,
)

# Data pipeline and utilities
from .data_pipeline import (
    DataPipeline,
    DataPipelineConfig,
    CircuitBreaker,
    CircuitBreakerState,
    PipelineDegraded,
    CircuitBreakerOpen,
    normalize_symbol,
    normalize_trade,
    normalize_spread,
    build_stream_key,
    calc_spread_bps,
)

# Explicit exports for clean public API
__all__ = [
    # Redis client
    "RedisCloudClient",
    "RedisCloudConfig",
    # Health monitoring
    "RedisHealthChecker",
    "RedisHealthConfig",
    "RedisHealthResult",
    # Data pipeline
    "DataPipeline",
    "DataPipelineConfig",
    "CircuitBreaker",
    "CircuitBreakerState",
    # Utility functions
    "normalize_symbol",
    "normalize_trade",
    "normalize_spread",
    "build_stream_key",
    "calc_spread_bps",
    # Exceptions
    "PipelineDegraded",
    "CircuitBreakerOpen",
]
