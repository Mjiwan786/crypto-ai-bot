"""
Infrastructure utilities for observability and metrics.

This module provides cross-cutting concerns for the trading system:
- Timing decorators and context managers
- Metric counters and gauges
- Resilience metrics (retries, throttles, circuit breakers)
- No-op safe implementations

All utilities are designed to be no-op safe - they will never break
business logic even if backends are unavailable or logging fails.
"""

from __future__ import annotations

__all__ = ["metrics"]
