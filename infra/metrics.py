#!/usr/bin/env python3
"""
Observability hooks for timing, counters, and metrics.

This module provides timing decorators, context managers, and metric counters
for measuring system performance and tracking resilience patterns (retries,
throttles, circuit breaker trips).

**Features:**
- Timing decorators for functions and methods
- Context managers for code blocks
- Counters for retries, throttles, and circuit breaker events
- No-op safe (graceful degradation if backends unavailable)
- Structured logging with standardized keys
- Support for Redis/StatsD backends (optional)

**Usage:**
    from infra.metrics import (
        time_operation,
        TimeOperation,
        increment_counter,
        record_retry,
        record_throttle,
        record_circuit_breaker_trip
    )

    # Decorator
    @time_operation("signal_analysis")
    def analyze_signal(data):
        ...

    # Context manager
    with TimeOperation("gateway_roundtrip"):
        response = await gateway.fetch()

    # Counters
    increment_counter("retries", labels={"operation": "kraken_api"})
    record_throttle("rate_limit", duration_ms=1000)
    record_circuit_breaker_trip("postgres", state="open")
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar, cast

# Import log keys
try:
    from agents.core.log_keys import (
        K_COMPONENT,
        K_OPERATION,
        K_DURATION_MS,
        K_ELAPSED_MS,
        K_SIGNAL_ANALYSIS_MS,
        K_DECISION_TO_PUBLISH_MS,
        K_GATEWAY_ROUNDTRIP_MS,
        K_START_TIME,
        K_END_TIME,
        K_COUNTER_NAME,
        K_COUNTER_VALUE,
        K_COUNTER_DELTA,
        K_RETRY_ATTEMPT,
        K_MAX_RETRIES,
        K_BACKOFF_MS,
        K_THROTTLED,
        K_THROTTLE_REASON,
        K_THROTTLE_DURATION_MS,
        K_CIRCUIT_BREAKER,
        K_CIRCUIT_STATE,
        K_CIRCUIT_BREAKER_TRIP,
        K_FAILURE_COUNT,
    )
except ImportError:
    # Fallback if log_keys not available
    K_COMPONENT = "component"
    K_OPERATION = "operation"
    K_DURATION_MS = "duration_ms"
    K_ELAPSED_MS = "elapsed_ms"
    K_SIGNAL_ANALYSIS_MS = "signal_analysis_ms"
    K_DECISION_TO_PUBLISH_MS = "decision_to_publish_ms"
    K_GATEWAY_ROUNDTRIP_MS = "gateway_roundtrip_ms"
    K_START_TIME = "start_time"
    K_END_TIME = "end_time"
    K_COUNTER_NAME = "counter_name"
    K_COUNTER_VALUE = "counter_value"
    K_COUNTER_DELTA = "counter_delta"
    K_RETRY_ATTEMPT = "retry_attempt"
    K_MAX_RETRIES = "max_retries"
    K_BACKOFF_MS = "backoff_ms"
    K_THROTTLED = "throttled"
    K_THROTTLE_REASON = "throttle_reason"
    K_THROTTLE_DURATION_MS = "throttle_duration_ms"
    K_CIRCUIT_BREAKER = "circuit_breaker"
    K_CIRCUIT_STATE = "circuit_state"
    K_CIRCUIT_BREAKER_TRIP = "circuit_breaker_trip"
    K_FAILURE_COUNT = "failure_count"


# Type variables for decorators
F = TypeVar("F", bound=Callable[..., Any])

# Global logger
logger = logging.getLogger(__name__)

# Global metrics backend (optional)
# Can be set to Redis client, StatsD client, or custom backend
_metrics_backend: Optional[Any] = None


# ============================================================================
# No-op Safe Logging Helper
# ============================================================================

def _safe_log(level: int, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
    """
    Log message safely - never raises exceptions.

    Args:
        level: Logging level
        message: Log message
        extra: Extra context fields
    """
    try:
        if logger is not None:
            logger.log(level, message, extra=extra or {})
    except Exception:
        # Silently fail - metrics should never break business logic
        pass


# ============================================================================
# Metrics Backend Configuration
# ============================================================================

def set_metrics_backend(backend: Any) -> None:
    """
    Set global metrics backend for publishing metrics.

    The backend can be a Redis client, StatsD client, or any object
    with appropriate methods. This is optional - metrics will still
    log to console if no backend is set.

    Args:
        backend: Metrics backend instance (Redis, StatsD, etc.)

    Examples:
        >>> import redis
        >>> r = redis.Redis()
        >>> set_metrics_backend(r)
    """
    global _metrics_backend
    _metrics_backend = backend
    _safe_log(logging.INFO, "Metrics backend configured", extra={K_COMPONENT: "metrics"})


def get_metrics_backend() -> Optional[Any]:
    """
    Get current metrics backend.

    Returns:
        Metrics backend instance or None
    """
    return _metrics_backend


# ============================================================================
# Timing Utilities
# ============================================================================

def _get_timestamp_ms() -> float:
    """Get current timestamp in milliseconds."""
    return time.time() * 1000


def _format_duration_key(operation: str) -> str:
    """
    Format operation name to standardized duration key.

    Args:
        operation: Operation name (e.g., "signal_analysis", "gateway_roundtrip")

    Returns:
        Standardized key (e.g., "signal_analysis_ms", "gateway_roundtrip_ms")
    """
    # Map common operations to standardized keys
    key_mapping = {
        "signal_analysis": K_SIGNAL_ANALYSIS_MS,
        "decision_to_publish": K_DECISION_TO_PUBLISH_MS,
        "gateway_roundtrip": K_GATEWAY_ROUNDTRIP_MS,
    }

    return key_mapping.get(operation, f"{operation}_ms")


# ============================================================================
# Timing Decorator
# ============================================================================

def time_operation(
    operation: str,
    *,
    log_level: int = logging.INFO,
    include_result: bool = False,
    component: Optional[str] = None,
) -> Callable[[F], F]:
    """
    Decorator to measure and log function execution time.

    Measures the duration of function execution and logs it with
    standardized keys. No-op safe - always completes even if logging fails.

    Args:
        operation: Operation name for logging (e.g., "signal_analysis")
        log_level: Logging level (default: INFO)
        include_result: If True, include function result in log (default: False)
        component: Component name for logging (default: None)

    Returns:
        Decorated function

    Examples:
        >>> @time_operation("signal_analysis")
        ... def analyze(data):
        ...     return process(data)

        >>> @time_operation("gateway_roundtrip", component="kraken")
        ... async def fetch_ticker(pair):
        ...     return await api.get_ticker(pair)
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_ms = _get_timestamp_ms()

            try:
                result = func(*args, **kwargs)

                # Measure duration
                end_ms = _get_timestamp_ms()
                duration_ms = end_ms - start_ms

                # Build log context
                log_context = {
                    K_OPERATION: operation,
                    _format_duration_key(operation): round(duration_ms, 2),
                    K_DURATION_MS: round(duration_ms, 2),
                    K_START_TIME: start_ms,
                    K_END_TIME: end_ms,
                }

                if component:
                    log_context[K_COMPONENT] = component

                if include_result and result is not None:
                    # Only include serializable results
                    try:
                        log_context["result"] = str(result)[:200]  # Truncate
                    except Exception:
                        pass

                # Log timing
                _safe_log(
                    log_level,
                    f"Operation '{operation}' completed in {duration_ms:.2f}ms",
                    extra=log_context
                )

                # Publish to metrics backend if available
                _publish_timing_metric(operation, duration_ms, component)

                return result

            except Exception as e:
                # Measure duration even on error
                end_ms = _get_timestamp_ms()
                duration_ms = end_ms - start_ms

                log_context = {
                    K_OPERATION: operation,
                    K_DURATION_MS: round(duration_ms, 2),
                    "error": str(e),
                }
                if component:
                    log_context[K_COMPONENT] = component

                _safe_log(
                    logging.WARNING,
                    f"Operation '{operation}' failed after {duration_ms:.2f}ms",
                    extra=log_context
                )

                raise

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_ms = _get_timestamp_ms()

            try:
                result = await func(*args, **kwargs)

                # Measure duration
                end_ms = _get_timestamp_ms()
                duration_ms = end_ms - start_ms

                # Build log context
                log_context = {
                    K_OPERATION: operation,
                    _format_duration_key(operation): round(duration_ms, 2),
                    K_DURATION_MS: round(duration_ms, 2),
                    K_START_TIME: start_ms,
                    K_END_TIME: end_ms,
                }

                if component:
                    log_context[K_COMPONENT] = component

                if include_result and result is not None:
                    try:
                        log_context["result"] = str(result)[:200]
                    except Exception:
                        pass

                # Log timing
                _safe_log(
                    log_level,
                    f"Operation '{operation}' completed in {duration_ms:.2f}ms",
                    extra=log_context
                )

                # Publish to metrics backend
                _publish_timing_metric(operation, duration_ms, component)

                return result

            except Exception as e:
                end_ms = _get_timestamp_ms()
                duration_ms = end_ms - start_ms

                log_context = {
                    K_OPERATION: operation,
                    K_DURATION_MS: round(duration_ms, 2),
                    "error": str(e),
                }
                if component:
                    log_context[K_COMPONENT] = component

                _safe_log(logging.WARNING, 
                    f"Operation '{operation}' failed after {duration_ms:.2f}ms",
                    extra=log_context
                )

                raise

        # Return appropriate wrapper based on function type
        import inspect
        if inspect.iscoroutinefunction(func):
            return cast(F, async_wrapper)
        else:
            return cast(F, sync_wrapper)

    return decorator


# ============================================================================
# Timing Context Manager
# ============================================================================

@contextmanager
def TimeOperation(
    operation: str,
    *,
    log_level: int = logging.INFO,
    component: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
):
    """
    Context manager to measure and log execution time of a code block.

    No-op safe - always completes even if logging fails.

    Args:
        operation: Operation name for logging
        log_level: Logging level (default: INFO)
        component: Component name for logging
        labels: Additional labels for metrics

    Yields:
        None

    Examples:
        >>> with TimeOperation("gateway_roundtrip", component="kraken"):
        ...     response = await api.get_ticker("BTC/USD")

        >>> with TimeOperation("signal_analysis"):
        ...     signal = analyze_market_data(data)
    """
    start_ms = _get_timestamp_ms()

    try:
        yield

        # Measure duration
        end_ms = _get_timestamp_ms()
        duration_ms = end_ms - start_ms

        # Build log context
        log_context = {
            K_OPERATION: operation,
            _format_duration_key(operation): round(duration_ms, 2),
            K_DURATION_MS: round(duration_ms, 2),
            K_START_TIME: start_ms,
            K_END_TIME: end_ms,
        }

        if component:
            log_context[K_COMPONENT] = component

        if labels:
            log_context.update(labels)

        # Log timing
        _safe_log(
            log_level,
            f"Operation '{operation}' completed in {duration_ms:.2f}ms",
            extra=log_context
        )

        # Publish to metrics backend
        _publish_timing_metric(operation, duration_ms, component, labels)

    except Exception as e:
        # Measure duration even on error
        end_ms = _get_timestamp_ms()
        duration_ms = end_ms - start_ms

        log_context = {
            K_OPERATION: operation,
            K_DURATION_MS: round(duration_ms, 2),
            "error": str(e),
        }
        if component:
            log_context[K_COMPONENT] = component

        _safe_log(logging.WARNING, 
            f"Operation '{operation}' failed after {duration_ms:.2f}ms",
            extra=log_context
        )

        raise


def _publish_timing_metric(
    operation: str,
    duration_ms: float,
    component: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
) -> None:
    """
    Publish timing metric to backend (if available).

    This is no-op safe - failures are logged but don't propagate.

    Args:
        operation: Operation name
        duration_ms: Duration in milliseconds
        component: Component name
        labels: Additional labels
    """
    try:
        backend = get_metrics_backend()
        if backend is None:
            return

        # Try Redis backend (publish to stream)
        if hasattr(backend, 'xadd'):
            metric_data = {
                "type": "timing",
                "operation": operation,
                "duration_ms": duration_ms,
                "timestamp": time.time(),
            }
            if component:
                metric_data["component"] = component
            if labels:
                metric_data.update(labels)

            backend.xadd("metrics:timing", metric_data, maxlen=10000)

        # Try StatsD backend
        elif hasattr(backend, 'timing'):
            metric_name = f"{component}.{operation}" if component else operation
            backend.timing(metric_name, duration_ms)

    except Exception as e:
        # Log but don't propagate - metrics should never break business logic
        _safe_log(logging.DEBUG, f"Failed to publish timing metric: {e}")


# ============================================================================
# Counter Utilities
# ============================================================================

def increment_counter(
    counter_name: str,
    *,
    delta: int = 1,
    component: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
) -> None:
    """
    Increment a counter metric.

    No-op safe - always completes even if backend unavailable.

    Args:
        counter_name: Counter name (e.g., "retries", "throttles")
        delta: Amount to increment (default: 1)
        component: Component name
        labels: Additional labels

    Examples:
        >>> increment_counter("retries", component="kraken_api")
        >>> increment_counter("requests", delta=5, labels={"endpoint": "/ticker"})
    """
    try:
        log_context = {
            K_COUNTER_NAME: counter_name,
            K_COUNTER_DELTA: delta,
        }
        if component:
            log_context[K_COMPONENT] = component
        if labels:
            log_context.update(labels)

        _safe_log(logging.DEBUG, f"Counter '{counter_name}' incremented by {delta}", extra=log_context)

        # Publish to backend
        backend = get_metrics_backend()
        if backend is None:
            return

        # Redis backend
        if hasattr(backend, 'hincrby'):
            key = f"counter:{component}:{counter_name}" if component else f"counter:{counter_name}"
            backend.hincrby("metrics:counters", key, delta)

        # StatsD backend
        elif hasattr(backend, 'incr'):
            metric_name = f"{component}.{counter_name}" if component else counter_name
            backend.incr(metric_name, count=delta)

    except Exception as e:
        _safe_log(logging.DEBUG, f"Failed to increment counter: {e}")


def set_gauge(
    gauge_name: str,
    value: float,
    *,
    component: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
) -> None:
    """
    Set a gauge metric value.

    No-op safe - always completes even if backend unavailable.

    Args:
        gauge_name: Gauge name (e.g., "queue_depth", "active_connections")
        value: Gauge value
        component: Component name
        labels: Additional labels

    Examples:
        >>> set_gauge("queue_depth", 42, component="redis")
        >>> set_gauge("active_connections", 10, labels={"pool": "main"})
    """
    try:
        log_context = {
            "gauge_name": gauge_name,
            "gauge_value": value,
        }
        if component:
            log_context[K_COMPONENT] = component
        if labels:
            log_context.update(labels)

        _safe_log(logging.DEBUG, f"Gauge '{gauge_name}' set to {value}", extra=log_context)

        # Publish to backend
        backend = get_metrics_backend()
        if backend is None:
            return

        # Redis backend
        if hasattr(backend, 'hset'):
            key = f"gauge:{component}:{gauge_name}" if component else f"gauge:{gauge_name}"
            backend.hset("metrics:gauges", key, value)

        # StatsD backend
        elif hasattr(backend, 'gauge'):
            metric_name = f"{component}.{gauge_name}" if component else gauge_name
            backend.gauge(metric_name, value)

    except Exception as e:
        _safe_log(logging.DEBUG, f"Failed to set gauge: {e}")


# ============================================================================
# Resilience Metrics (Retries, Throttles, Circuit Breakers)
# ============================================================================

def record_retry(
    operation: str,
    attempt: int,
    max_retries: int,
    *,
    backoff_ms: Optional[float] = None,
    component: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """
    Record a retry attempt.

    Args:
        operation: Operation being retried
        attempt: Current attempt number (1-indexed)
        max_retries: Maximum retry attempts
        backoff_ms: Backoff duration in milliseconds
        component: Component name
        error: Error message that triggered retry

    Examples:
        >>> record_retry("fetch_ticker", attempt=1, max_retries=3, backoff_ms=1000)
        >>> record_retry("place_order", 2, 5, component="kraken", error="Rate limited")
    """
    try:
        log_context = {
            K_OPERATION: operation,
            K_RETRY_ATTEMPT: attempt,
            K_MAX_RETRIES: max_retries,
        }
        if backoff_ms:
            log_context[K_BACKOFF_MS] = backoff_ms
        if component:
            log_context[K_COMPONENT] = component
        if error:
            log_context["error"] = error

        _safe_log(logging.INFO, 
            f"Retry attempt {attempt}/{max_retries} for '{operation}'",
            extra=log_context
        )

        # Increment retry counter
        increment_counter(
            "retries",
            component=component,
            labels={"operation": operation}
        )

    except Exception as e:
        _safe_log(logging.DEBUG, f"Failed to record retry: {e}")


def record_throttle(
    operation: str,
    *,
    reason: Optional[str] = None,
    duration_ms: Optional[float] = None,
    component: Optional[str] = None,
) -> None:
    """
    Record a throttle event (rate limit, backpressure, etc.).

    Args:
        operation: Operation being throttled
        reason: Reason for throttling (e.g., "rate_limit", "backpressure")
        duration_ms: Throttle duration in milliseconds
        component: Component name

    Examples:
        >>> record_throttle("api_call", reason="rate_limit", duration_ms=1000)
        >>> record_throttle("publish", reason="backpressure", component="redis")
    """
    try:
        log_context = {
            K_OPERATION: operation,
            K_THROTTLED: True,
        }
        if reason:
            log_context[K_THROTTLE_REASON] = reason
        if duration_ms:
            log_context[K_THROTTLE_DURATION_MS] = duration_ms
        if component:
            log_context[K_COMPONENT] = component

        _safe_log(logging.WARNING, 
            f"Operation '{operation}' throttled: {reason or 'unknown'}",
            extra=log_context
        )

        # Increment throttle counter
        increment_counter(
            "throttles",
            component=component,
            labels={"operation": operation, "reason": reason or "unknown"}
        )

    except Exception as e:
        _safe_log(logging.DEBUG, f"Failed to record throttle: {e}")


def record_circuit_breaker_trip(
    circuit_name: str,
    state: str,
    *,
    failure_count: Optional[int] = None,
    component: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """
    Record a circuit breaker state change.

    Args:
        circuit_name: Circuit breaker name
        state: Circuit state ("open", "half_open", "closed")
        failure_count: Number of failures that triggered state change
        component: Component name
        error: Error message that triggered circuit breaker

    Examples:
        >>> record_circuit_breaker_trip("postgres", "open", failure_count=5)
        >>> record_circuit_breaker_trip("kraken_api", "half_open", component="gateway")
    """
    try:
        log_context = {
            K_CIRCUIT_BREAKER: circuit_name,
            K_CIRCUIT_STATE: state,
            K_CIRCUIT_BREAKER_TRIP: True,
        }
        if failure_count is not None:
            log_context[K_FAILURE_COUNT] = failure_count
        if component:
            log_context[K_COMPONENT] = component
        if error:
            log_context["error"] = error

        _safe_log(logging.ERROR, 
            f"Circuit breaker '{circuit_name}' changed to state: {state}",
            extra=log_context
        )

        # Increment circuit breaker counter
        increment_counter(
            "circuit_breaker_trips",
            component=component,
            labels={"circuit": circuit_name, "state": state}
        )

    except Exception as e:
        _safe_log(logging.DEBUG, f"Failed to record circuit breaker trip: {e}")


# ============================================================================
# Export public API
# ============================================================================

__all__ = [
    # Backend configuration
    "set_metrics_backend",
    "get_metrics_backend",
    # Timing
    "time_operation",
    "TimeOperation",
    # Counters and gauges
    "increment_counter",
    "set_gauge",
    # Resilience metrics
    "record_retry",
    "record_throttle",
    "record_circuit_breaker_trip",
]
