"""
Exchange-agnostic utility functions for crypto-ai-bot.

This package provides common utilities including:
- Structured logging with secret redaction
- Performance monitoring and profiling
- Redis client utilities
- WebSocket connections for Kraken
- Position math calculations
- Retry decorators

**Quick Start:**
    from utils import get_logger, Timer

    # Get structured logger
    logger = get_logger(__name__)

    # Time function execution
    with Timer() as t:
        # Your code here
        pass
    print(f"Elapsed: {t.elapsed}s")

**Available Functions:**
- get_logger() - Get structured logger with secret redaction
- get_metrics_logger() - Get metrics-specific logger
- setup_logging() - Initialize logging configuration
- timer() - Context manager for timing operations
"""

from __future__ import annotations

from .logger import (
    get_logger,
    get_metrics_logger,
    setup_logging,
    LoggerFactory,
    SecretRedactionFilter,
)

from .timer import Timer

__all__ = [
    # Logging
    "get_logger",
    "get_metrics_logger",
    "setup_logging",
    "LoggerFactory",
    "SecretRedactionFilter",
    # Timing
    "Timer",
]
