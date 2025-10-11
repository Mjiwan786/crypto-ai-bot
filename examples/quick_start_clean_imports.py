#!/usr/bin/env python3
"""
Quick Start Example: Clean Import Patterns

This example demonstrates how to use the clean public API surface
for the crypto-ai-bot project. All imports follow best practices
and avoid circular dependencies.

Usage:
    conda activate crypto-bot
    python examples/quick_start_clean_imports.py
"""

import asyncio
from decimal import Decimal
from datetime import datetime
import os

# Configuration - clean import from config package
from config import load_system_config, get_stream

# Infrastructure - clean imports from agents.infrastructure
from agents.infrastructure import (
    RedisCloudClient,
    RedisHealthChecker,
    DataPipeline,
    normalize_symbol,
    build_stream_key,
)

# Core agents - clean imports from agents.core
from agents.core import (
    MarketScanner,
    EnhancedExecutionAgent,
    analyze,
    AnalysisContext,
)

# Serialization and contracts
from agents.core import (
    json_dumps,
    serialize_for_redis,
    SignalPayload,
    MetricsLatencyPayload,
)

# Logging keys for structured logging
from agents.core import K_COMPONENT, K_PAIR, K_SIGNAL_ID

# Utilities
from utils import get_logger, Timer


async def main():
    """Main demonstration of clean imports and API usage."""

    # Initialize structured logger
    logger = get_logger(__name__)
    logger.info("Starting quick start example with clean imports")

    # === 1. Configuration ===
    logger.info("Loading configuration...")
    config = load_system_config(environment="paper")
    logger.info(f"Configuration loaded for environment: {config.environment}")

    # === 2. Redis Connection ===
    logger.info("Connecting to Redis Cloud...")

    # Get Redis configuration from environment
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    try:
        # Initialize Redis client with TLS support for Redis Cloud
        redis_client = RedisCloudClient(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD"),
            ssl=redis_url.startswith("rediss://"),
            decode_responses=True
        )

        # Check health
        health_checker = RedisHealthChecker(redis_client=redis_client)
        health = await health_checker.check_health()

        if health.is_healthy:
            logger.info(
                "Redis connection healthy",
                extra={
                    K_COMPONENT: "redis",
                    "latency_ms": health.latency_ms,
                }
            )
        else:
            logger.error(f"Redis health check failed: {health.error}")
            return

    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        logger.info("Continuing without Redis for demonstration purposes")
        redis_client = None

    # === 3. Stream Key Management ===
    logger.info("Building Redis stream keys...")

    symbols = ["BTC/USDT", "ETH/USDT"]
    stream_keys = {}

    for symbol in symbols:
        # Use clean stream registry API
        signal_stream = get_stream("signals", symbol=normalize_symbol(symbol))
        stream_keys[symbol] = signal_stream
        logger.info(f"Stream key for {symbol}: {signal_stream}")

    # === 4. Market Scanner ===
    logger.info("Initializing market scanner...")

    with Timer() as t:
        scanner = MarketScanner(
            exchange="kraken",
            symbols=symbols,
            timeframe="1m"
        )

    logger.info(f"Market scanner initialized in {t.elapsed:.3f}s")

    # === 5. Signal Analysis ===
    logger.info("Running signal analysis...")

    # Create analysis context
    context = AnalysisContext(
        pair="BTC/USDT",
        close_prices=[50000.0, 50100.0, 50200.0, 50150.0, 50300.0],
        volumes=[100.0, 110.0, 105.0, 115.0, 120.0],
        timestamp=datetime.utcnow()
    )

    # Analyze with timing
    with Timer() as t:
        signals = analyze(context=context)

    logger.info(
        f"Analysis completed in {t.elapsed:.3f}s",
        extra={
            K_COMPONENT: "signal_analyst",
            K_PAIR: "BTC/USDT",
            "signal_count": len(signals),
        }
    )

    # === 6. Serialization ===
    logger.info("Testing serialization...")

    # Create signal payload
    signal = SignalPayload(
        signal_id="sig_demo_001",
        pair="BTC/USDT",
        signal_type="buy",
        strength=0.85,
        price=Decimal("50300.123"),
        timestamp=datetime.utcnow(),
        indicators={"rsi": 65.5, "macd": 0.002}
    )

    # Serialize with Decimal and datetime support
    json_str = json_dumps(signal.dict())
    logger.info(f"Signal serialized: {json_str[:100]}...")

    # Prepare for Redis
    redis_payload = serialize_for_redis(signal.dict())
    logger.info(f"Redis payload prepared: {len(redis_payload)} bytes")

    # === 7. Metrics Payload ===
    logger.info("Creating metrics payload...")

    metrics = MetricsLatencyPayload(
        component="signal_analyst",
        operation="analyze",
        latency_ms=t.elapsed * 1000,
        timestamp=datetime.utcnow(),
        success=True
    )

    logger.info(
        "Metrics recorded",
        extra={
            K_COMPONENT: metrics.component,
            "operation": metrics.operation,
            "latency_ms": metrics.latency_ms,
        }
    )

    # === 8. Data Pipeline (if Redis available) ===
    if redis_client:
        logger.info("Initializing data pipeline...")

        try:
            pipeline = DataPipeline(
                redis_client=redis_client,
                symbols=symbols,
                exchange="kraken"
            )
            logger.info("Data pipeline initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize data pipeline: {e}")

    # === Summary ===
    logger.info("=" * 60)
    logger.info("Clean imports demonstration completed successfully!")
    logger.info("=" * 60)
    logger.info("All imports worked without circular dependencies:")
    logger.info("  ✓ config.load_system_config")
    logger.info("  ✓ agents.infrastructure.RedisCloudClient")
    logger.info("  ✓ agents.core.MarketScanner")
    logger.info("  ✓ agents.core.analyze")
    logger.info("  ✓ agents.core.json_dumps")
    logger.info("  ✓ utils.get_logger")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
