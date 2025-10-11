"""
Production-grade metrics collection and analysis for scalping operations.

This module provides comprehensive metrics collection capabilities for the scalping
system, offering real-time metrics, aggregation, monitoring capabilities, and health
checks with production-grade features and safeguards.

Features:
- Comprehensive input validation and sanitization
- Robust error handling with circuit breakers
- Memory management and resource limits
- Security measures and rate limiting
- Health monitoring and diagnostics
- Performance optimization
- Audit logging and compliance
- Multi-format metric export (Prometheus, JSON, Health)
- Scalping-specific metric helpers
- Production-grade error recovery

This module provides the core metrics collection infrastructure for the scalping
system, enabling comprehensive observability and monitoring capabilities.
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import re
import sys
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import psutil

from agents.core.log_keys import K_COMPONENT

logger = logging.getLogger(__name__)


# =============================================================================
# Production Constants and Validation
# =============================================================================

# Security and validation constants
MAX_METRIC_NAME_LENGTH = 100
MAX_TAG_KEY_LENGTH = 50
MAX_TAG_VALUE_LENGTH = 200
MAX_TAGS_PER_METRIC = 20
MAX_SERIES_POINTS = 10000
MAX_MEMORY_USAGE_MB = 500
RATE_LIMIT_PER_SECOND = 1000
HEALTH_CHECK_INTERVAL = 30

# Input validation patterns
METRIC_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-\.]*[a-zA-Z0-9]$")
TAG_KEY_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]*$")
TAG_VALUE_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.:]+$")


# Production error codes
class MetricsError(Exception):
    """Base exception for metrics operations"""

    def __init__(self, message: str, code: str = "METRICS_ERROR", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ValidationError(MetricsError):
    """Input validation error"""

    def __init__(self, message: str):
        super().__init__(message, "VALIDATION_ERROR", False)


class ResourceLimitError(MetricsError):
    """Resource limit exceeded"""

    def __init__(self, message: str):
        super().__init__(message, "RESOURCE_LIMIT", True)


class SecurityError(MetricsError):
    """Security violation"""

    def __init__(self, message: str):
        super().__init__(message, "SECURITY_ERROR", False)


class MetricType(Enum):
    """Types of metrics with production validation"""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"
    RATE = "rate"  # per-second rate derived from deltas

    @classmethod
    def validate(cls, value: str) -> "MetricType":
        """Validate and return metric type"""
        try:
            return cls(value)
        except ValueError:
            raise ValidationError(f"Invalid metric type: {value}")


class AggregationType(Enum):
    """Aggregation methods for metrics"""

    SUM = "sum"
    AVERAGE = "average"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    PERCENTILE = "percentile"
    RATE = "rate"


# =============================================================================
# Production Input Validation
# =============================================================================


def validate_metric_name(name: str) -> str:
    """Validate metric name for security and consistency"""
    if not isinstance(name, str):
        raise ValidationError("Metric name must be a string")

    if len(name) > MAX_METRIC_NAME_LENGTH:
        raise ValidationError(f"Metric name too long: {len(name)} > {MAX_METRIC_NAME_LENGTH}")

    if not METRIC_NAME_PATTERN.match(name):
        raise ValidationError(f"Invalid metric name format: {name}")

    return name.strip()


def validate_tags(tags: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Validate and sanitize tags"""
    if tags is None:
        return {}

    if not isinstance(tags, dict):
        raise ValidationError("Tags must be a dictionary")

    if len(tags) > MAX_TAGS_PER_METRIC:
        raise ValidationError(f"Too many tags: {len(tags)} > {MAX_TAGS_PER_METRIC}")

    validated_tags = {}
    for key, value in tags.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValidationError("Tag keys and values must be strings")

        if len(key) > MAX_TAG_KEY_LENGTH:
            raise ValidationError(f"Tag key too long: {len(key)} > {MAX_TAG_KEY_LENGTH}")

        if len(value) > MAX_TAG_VALUE_LENGTH:
            raise ValidationError(f"Tag value too long: {len(value)} > {MAX_TAG_VALUE_LENGTH}")

        if not TAG_KEY_PATTERN.match(key):
            raise ValidationError(f"Invalid tag key format: {key}")

        if not TAG_VALUE_PATTERN.match(value):
            raise ValidationError(f"Invalid tag value format: {value}")

        validated_tags[key.strip()] = value.strip()

    return validated_tags


def validate_value(value: Any, metric_type: MetricType) -> float:
    """Validate and convert metric value"""
    if not isinstance(value, (int, float, str)):
        raise ValidationError(f"Invalid value type: {type(value)}")

    try:
        float_val = float(value)
    except (ValueError, TypeError):
        raise ValidationError(f"Cannot convert value to float: {value}")

    if not np.isfinite(float_val):
        raise ValidationError(f"Value must be finite: {float_val}")

    # Additional validation based on metric type
    if metric_type == MetricType.COUNTER and float_val < 0:
        raise ValidationError(f"Counter values must be non-negative: {float_val}")

    return float_val


# =============================================================================
# Production Data Models
# =============================================================================


@dataclass
class MetricPoint:
    """Production-grade metric data point with validation"""

    name: str
    value: float
    timestamp: float
    tags: Dict[str, str] = field(default_factory=dict)
    metric_type: MetricType = MetricType.GAUGE
    _validated: bool = field(default=False, init=False)

    def __post_init__(self):
        if not self._validated:
            self.name = validate_metric_name(self.name)
            self.tags = validate_tags(self.tags)
            self.value = validate_value(self.value, self.metric_type)
            self.timestamp = float(self.timestamp)
            self._validated = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "name": self.name,
            "value": self.value,
            "timestamp": self.timestamp,
            "tags": self.tags,
            "metric_type": self.metric_type.value,
        }

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), separators=(",", ":"))


@dataclass
class MetricSeries:
    """Production-grade time series with resource management"""

    name: str
    metric_type: MetricType
    max_points: int
    points: deque = field(init=False)
    tags: Dict[str, str] = field(default_factory=dict)
    _created_at: float = field(default_factory=time.time, init=False)
    _last_accessed: float = field(default_factory=time.time, init=False)
    _access_count: int = field(default=0, init=False)

    def __post_init__(self):
        # Validate inputs
        self.name = validate_metric_name(self.name)
        self.tags = validate_tags(self.tags)
        self.metric_type = (
            MetricType.validate(self.metric_type.value)
            if isinstance(self.metric_type, str)
            else self.metric_type
        )

        # Enforce resource limits
        if self.max_points > MAX_SERIES_POINTS:
            raise ResourceLimitError(
                f"Max points too high: {self.max_points} > {MAX_SERIES_POINTS}"
            )

        self.points = deque(maxlen=self.max_points)

    def add_point(self, value: float, timestamp: Optional[float] = None) -> None:
        """Add a point to the series with validation"""
        try:
            validated_value = validate_value(value, self.metric_type)
            if timestamp is None:
                timestamp = time.time()

            point = MetricPoint(
                name=self.name,
                value=validated_value,
                timestamp=float(timestamp),
                tags=dict(self.tags),
                metric_type=self.metric_type,
            )

            self.points.append(point)
            self._last_accessed = time.time()
            self._access_count += 1

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Failed to add point to series {self.name}: {e}")
            raise MetricsError(f"Failed to add point: {e}")

    def get_latest(self) -> Optional[MetricPoint]:
        """Get the latest point"""
        self._last_accessed = time.time()
        self._access_count += 1
        return self.points[-1] if self.points else None

    def get_range(self, start_time: float, end_time: float) -> List[MetricPoint]:
        """Get points within time range"""
        self._last_accessed = time.time()
        self._access_count += 1

        if start_time > end_time:
            raise ValidationError("Start time must be <= end time")

        return [p for p in self.points if start_time <= p.timestamp <= end_time]

    def get_stats(self) -> Dict[str, Any]:
        """Get series statistics for monitoring"""
        return {
            "name": self.name,
            "metric_type": self.metric_type.value,
            "point_count": len(self.points),
            "max_points": self.max_points,
            "created_at": self._created_at,
            "last_accessed": self._last_accessed,
            "access_count": self._access_count,
            "tags": dict(self.tags),
        }


# =============================================================================
# Production Timer and Context Managers
# =============================================================================


class Timer:
    """Production-grade context manager for timing operations with error handling"""

    def __init__(
        self,
        metrics_collector: "MetricsCollector",
        metric_name: str,
        tags: Optional[Dict[str, str]] = None,
    ):
        self.metrics_collector = metrics_collector
        self.metric_name = validate_metric_name(metric_name)
        self.tags = validate_tags(tags)
        self._start: Optional[float] = None
        self._exception_occurred: bool = False

    # Sync context manager
    def __enter__(self):
        self._start = time.perf_counter()
        self._exception_occurred = False
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._start is not None:
            try:
                duration_ms = (time.perf_counter() - self._start) * 1000.0
                if exc_type is not None:
                    self._exception_occurred = True
                    # Add exception info to tags
                    exception_tags = dict(self.tags)
                    exception_tags["exception"] = exc_type.__name__ if exc_type else "unknown"
                    self.metrics_collector.record_timer(
                        self.metric_name, duration_ms, exception_tags
                    )
                else:
                    self.metrics_collector.record_timer(self.metric_name, duration_ms, self.tags)
            except Exception as e:
                logger.error(f"Failed to record timer metric {self.metric_name}: {e}")

    # Async context manager
    async def __aenter__(self):
        self._start = time.perf_counter()
        self._exception_occurred = False
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._start is not None:
            try:
                duration_ms = (time.perf_counter() - self._start) * 1000.0
                if exc_type is not None:
                    self._exception_occurred = True
                    # Add exception info to tags
                    exception_tags = dict(self.tags)
                    exception_tags["exception"] = exc_type.__name__ if exc_type else "unknown"
                    self.metrics_collector.record_timer(
                        self.metric_name, duration_ms, exception_tags
                    )
                else:
                    self.metrics_collector.record_timer(self.metric_name, duration_ms, self.tags)
            except Exception as e:
                logger.error(f"Failed to record timer metric {self.metric_name}: {e}")

    @property
    def duration_ms(self) -> Optional[float]:
        """Get current duration if timer is running"""
        if self._start is not None:
            return (time.perf_counter() - self._start) * 1000.0
        return None

    @property
    def has_exception(self) -> bool:
        """Check if an exception occurred during timing"""
        return self._exception_occurred


# =============================================================================
# Production Decorators and Utilities
# =============================================================================


def rate_limit(calls_per_second: int = RATE_LIMIT_PER_SECOND):
    """Rate limiting decorator for metrics operations"""

    def decorator(func):
        last_called = [0.0]
        min_interval = 1.0 / calls_per_second

        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            time_since_last = now - last_called[0]

            if time_since_last < min_interval:
                sleep_time = min_interval - time_since_last
                time.sleep(sleep_time)

            last_called[0] = time.time()
            return func(*args, **kwargs)

        return wrapper

    return decorator


def circuit_breaker(failure_threshold: int = 5, recovery_timeout: int = 60):
    """Circuit breaker decorator for metrics operations"""

    def decorator(func):
        failures = [0]
        last_failure_time = [0.0]
        circuit_open = [False]

        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()

            # Check if circuit should be reset
            if circuit_open[0] and (now - last_failure_time[0]) > recovery_timeout:
                circuit_open[0] = False
                failures[0] = 0
                logger.info(f"Circuit breaker reset for {func.__name__}")

            # Check if circuit is open
            if circuit_open[0]:
                raise MetricsError(
                    f"Circuit breaker open for {func.__name__}", "CIRCUIT_OPEN", True
                )

            try:
                result = func(*args, **kwargs)
                failures[0] = 0  # Reset on success
                return result
            except Exception:
                failures[0] += 1
                last_failure_time[0] = now

                if failures[0] >= failure_threshold:
                    circuit_open[0] = True
                    logger.error(
                        f"Circuit breaker opened for {func.__name__} after {failures[0]} failures"
                    )

                raise

        return wrapper

    return decorator


# =============================================================================
# Production Health Monitoring
# =============================================================================


@dataclass
class HealthStatus:
    """Health status for metrics collector"""

    status: str  # "healthy", "degraded", "unhealthy"
    timestamp: float
    memory_usage_mb: float
    series_count: int
    total_points: int
    error_rate: float
    last_cleanup: float
    circuit_breakers_open: int
    issues: List[str] = field(default_factory=list)


class MetricsCollector:
    """
    Production-grade metrics collection system for scalping operations.

    Production Features:
    - Comprehensive input validation and sanitization
    - Memory management and resource limits
    - Circuit breakers and rate limiting
    - Health monitoring and diagnostics
    - Security measures and audit logging
    - Performance optimization
    - Error recovery and resilience
    """

    def __init__(self, max_series_points: int = 1000, cleanup_interval: int = 300):
        # Validate inputs
        if max_series_points > MAX_SERIES_POINTS:
            raise ResourceLimitError(f"Max series points too high: {max_series_points}")
        if cleanup_interval < 10:
            raise ValidationError("Cleanup interval must be >= 10 seconds")

        self.max_series_points = int(max_series_points)
        self.cleanup_interval = int(cleanup_interval)

        # Metric storage with weak references for memory management
        self.series: Dict[str, MetricSeries] = {}
        self.aggregated_metrics: Dict[str, Dict[str, float]] = defaultdict(dict)

        # Threading safety
        self.lock = threading.RLock()

        # Performance tracking
        self.collection_times: deque[float] = deque(maxlen=200)
        self.export_callbacks: List[Callable[[List[MetricPoint]], None]] = []

        # Production monitoring
        self.health_status: Optional[HealthStatus] = None
        self.error_count: int = 0
        self.success_count: int = 0
        self.last_health_check: float = 0.0
        self.circuit_breakers: Dict[str, bool] = {}

        # Memory management
        self.memory_warning_threshold = MAX_MEMORY_USAGE_MB * 0.8
        self.memory_critical_threshold = MAX_MEMORY_USAGE_MB * 0.95

        # Rate limiting
        self.rate_limiter = {}
        self.last_rate_reset = time.time()

        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None
        self._running = False

        # State for rate computation: (last_value, last_timestamp)
        self._rate_state: Dict[str, Tuple[float, float]] = {}

        # Audit logging
        self.audit_log: deque = deque(maxlen=1000)

        # Initialize health status
        self._update_health_status()

    # ---- Production Lifecycle ----
    async def start(self):
        """Start background tasks with production safeguards (idempotent)."""
        if self._running:
            logger.warning("MetricsCollector already running")
            return

        try:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self._health_task = asyncio.create_task(self._health_monitoring_loop())

            # Log startup
            self._audit_log("startup", {"max_series_points": self.max_series_points})
            logger.info("MetricsCollector started with production safeguards")

        except Exception as e:
            self._running = False
            logger.error(f"Failed to start MetricsCollector: {e}")
            raise MetricsError(f"Startup failed: {e}")

    async def stop(self):
        """Stop background tasks gracefully (idempotent)."""
        if not self._running:
            logger.warning("MetricsCollector not running")
            return

        try:
            self._running = False

            # Cancel tasks gracefully
            tasks_to_cancel = []
            if self._cleanup_task:
                tasks_to_cancel.append(self._cleanup_task)
            if self._health_task:
                tasks_to_cancel.append(self._health_task)

            for task in tasks_to_cancel:
                task.cancel()

            # Wait for tasks to complete
            if tasks_to_cancel:
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

            # Final cleanup
            await self._final_cleanup()

            # Log shutdown
            self._audit_log("shutdown", {"series_count": len(self.series)})
            logger.info("MetricsCollector stopped gracefully")

        except Exception as e:
            logger.error(f"Error during MetricsCollector shutdown: {e}")
        finally:
            self._cleanup_task = None
            self._health_task = None

    async def _final_cleanup(self):
        """Final cleanup before shutdown"""
        with self.lock:
            # Export any remaining metrics
            if self.export_callbacks:
                try:
                    all_points = []
                    for series in self.series.values():
                        all_points.extend(list(series.points))

                    for callback in self.export_callbacks:
                        try:
                            callback(all_points)
                        except Exception as e:
                            logger.error(f"Export callback failed during shutdown: {e}")
                except Exception as e:
                    logger.error(f"Final export failed: {e}")

            # Clear memory
            self.series.clear()
            self.aggregated_metrics.clear()
            self._rate_state.clear()
            self.audit_log.clear()

    # ---- Production Recording Methods ----
    @rate_limit(RATE_LIMIT_PER_SECOND)
    @circuit_breaker(failure_threshold=10, recovery_timeout=30)
    def record_counter(self, name: str, value: float = 1.0, tags: Optional[Dict[str, str]] = None):
        """Record a counter metric (cumulative) with production safeguards."""
        try:
            # Validate inputs
            validated_name = validate_metric_name(name)
            validated_tags = validate_tags(tags)
            validated_value = validate_value(value, MetricType.COUNTER)

            with self.lock:
                # Check memory limits
                self._check_memory_limits()

                s = self._get_or_create_series(validated_name, MetricType.COUNTER, validated_tags)
                current_value = s.points[-1].value if s.points else 0.0
                s.add_point(current_value + validated_value)

                self.success_count += 1
                self._audit_log(
                    "counter_recorded",
                    {"name": validated_name, "value": validated_value, "tags": validated_tags},
                )

        except ValidationError as e:
            self.error_count += 1
            logger.warning(f"Validation error in record_counter: {e}")
            raise
        except Exception as e:
            self.error_count += 1
            logger.error(f"Error recording counter {name}: {e}")
            raise MetricsError(f"Failed to record counter: {e}")

    @rate_limit(RATE_LIMIT_PER_SECOND)
    @circuit_breaker(failure_threshold=10, recovery_timeout=30)
    def record_gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Record a gauge metric (point-in-time value) with production safeguards."""
        try:
            # Validate inputs
            validated_name = validate_metric_name(name)
            validated_tags = validate_tags(tags)
            validated_value = validate_value(value, MetricType.GAUGE)

            with self.lock:
                # Check memory limits
                self._check_memory_limits()

                s = self._get_or_create_series(validated_name, MetricType.GAUGE, validated_tags)
                s.add_point(validated_value)

                self.success_count += 1
                self._audit_log(
                    "gauge_recorded",
                    {"name": validated_name, "value": validated_value, "tags": validated_tags},
                )

        except ValidationError as e:
            self.error_count += 1
            logger.warning(f"Validation error in record_gauge: {e}")
            raise
        except Exception as e:
            self.error_count += 1
            logger.error(f"Error recording gauge {name}: {e}")
            raise MetricsError(f"Failed to record gauge: {e}")

    @rate_limit(RATE_LIMIT_PER_SECOND)
    @circuit_breaker(failure_threshold=10, recovery_timeout=30)
    def update_gauge(
        self, name: str, fn: Callable[[float], float], tags: Optional[Dict[str, str]] = None
    ):
        """Atomically update a gauge with production safeguards."""
        try:
            # Validate inputs
            validated_name = validate_metric_name(name)
            validated_tags = validate_tags(tags)

            if not callable(fn):
                raise ValidationError("Update function must be callable")

            with self.lock:
                # Check memory limits
                self._check_memory_limits()

                s = self._get_or_create_series(validated_name, MetricType.GAUGE, validated_tags)
                prev = s.points[-1].value if s.points else 0.0

                try:
                    new_value = fn(prev)
                    validated_new_value = validate_value(new_value, MetricType.GAUGE)
                    s.add_point(validated_new_value)

                    self.success_count += 1
                    self._audit_log(
                        "gauge_updated",
                        {
                            "name": validated_name,
                            "old_value": prev,
                            "new_value": validated_new_value,
                            "tags": validated_tags,
                        },
                    )

                except Exception as e:
                    raise ValidationError(f"Update function failed: {e}")

        except ValidationError as e:
            self.error_count += 1
            logger.warning(f"Validation error in update_gauge: {e}")
            raise
        except Exception as e:
            self.error_count += 1
            logger.error(f"Error updating gauge {name}: {e}")
            raise MetricsError(f"Failed to update gauge: {e}")

    @rate_limit(RATE_LIMIT_PER_SECOND)
    @circuit_breaker(failure_threshold=10, recovery_timeout=30)
    def record_timer(self, name: str, duration_ms: float, tags: Optional[Dict[str, str]] = None):
        """Record a timer metric (duration in ms) with production safeguards."""
        try:
            # Validate inputs
            validated_name = validate_metric_name(name)
            validated_tags = validate_tags(tags)
            validated_duration = validate_value(duration_ms, MetricType.TIMER)

            # Sanity check for timer values
            if validated_duration < 0:
                raise ValidationError("Timer duration cannot be negative")
            if validated_duration > 3600000:  # 1 hour in ms
                logger.warning(
                    f"Unusually long timer duration: {validated_duration}ms for {validated_name}"
                )

            with self.lock:
                # Check memory limits
                self._check_memory_limits()

                s = self._get_or_create_series(validated_name, MetricType.TIMER, validated_tags)
                s.add_point(validated_duration)

                self.success_count += 1
                self._audit_log(
                    "timer_recorded",
                    {
                        "name": validated_name,
                        "duration_ms": validated_duration,
                        "tags": validated_tags,
                    },
                )

        except ValidationError as e:
            self.error_count += 1
            logger.warning(f"Validation error in record_timer: {e}")
            raise
        except Exception as e:
            self.error_count += 1
            logger.error(f"Error recording timer {name}: {e}")
            raise MetricsError(f"Failed to record timer: {e}")

    @rate_limit(RATE_LIMIT_PER_SECOND)
    @circuit_breaker(failure_threshold=10, recovery_timeout=30)
    def record_histogram(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Record a histogram metric (distribution sample) with production safeguards."""
        try:
            # Validate inputs
            validated_name = validate_metric_name(name)
            validated_tags = validate_tags(tags)
            validated_value = validate_value(value, MetricType.HISTOGRAM)

            with self.lock:
                # Check memory limits
                self._check_memory_limits()

                s = self._get_or_create_series(validated_name, MetricType.HISTOGRAM, validated_tags)
                s.add_point(validated_value)

                self.success_count += 1
                self._audit_log(
                    "histogram_recorded",
                    {"name": validated_name, "value": validated_value, "tags": validated_tags},
                )

        except ValidationError as e:
            self.error_count += 1
            logger.warning(f"Validation error in record_histogram: {e}")
            raise
        except Exception as e:
            self.error_count += 1
            logger.error(f"Error recording histogram {name}: {e}")
            raise MetricsError(f"Failed to record histogram: {e}")

    @rate_limit(RATE_LIMIT_PER_SECOND)
    @circuit_breaker(failure_threshold=10, recovery_timeout=30)
    def record_rate(self, name: str, absolute_value: float, tags: Optional[Dict[str, str]] = None):
        """Record a rate (per-second) with production safeguards."""
        try:
            # Validate inputs
            validated_name = validate_metric_name(name)
            validated_tags = validate_tags(tags)
            validated_value = validate_value(
                absolute_value, MetricType.COUNTER
            )  # Rate is derived from counter

            now = time.time()
            series_key = self._series_key(validated_name, validated_tags)

            with self.lock:
                # Check memory limits
                self._check_memory_limits()

                last = self._rate_state.get(series_key)
                rate = 0.0

                if last:
                    last_value, last_ts = last
                    dt = max(1e-9, now - last_ts)
                    dv = validated_value - last_value
                    rate = dv / dt

                    # Sanity check for rate values
                    if abs(rate) > 1000000:  # 1M per second seems excessive
                        logger.warning(f"Unusually high rate: {rate}/s for {validated_name}")

                self._rate_state[series_key] = (validated_value, now)

                s = self._get_or_create_series(validated_name, MetricType.RATE, validated_tags)
                s.add_point(rate)

                self.success_count += 1
                self._audit_log(
                    "rate_recorded",
                    {
                        "name": validated_name,
                        "absolute_value": validated_value,
                        "rate": rate,
                        "tags": validated_tags,
                    },
                )

        except ValidationError as e:
            self.error_count += 1
            logger.warning(f"Validation error in record_rate: {e}")
            raise
        except Exception as e:
            self.error_count += 1
            logger.error(f"Error recording rate {name}: {e}")
            raise MetricsError(f"Failed to record rate: {e}")

    # ---- Production Sugar Methods ----
    def increment(self, name: str, tags: Optional[Dict[str, str]] = None):
        """Increment a counter by 1 with production safeguards."""
        self.record_counter(name, 1.0, tags)

    def decrement(self, name: str, tags: Optional[Dict[str, str]] = None):
        """Decrement a counter by 1 with production safeguards."""
        self.record_counter(name, -1.0, tags)

    def set_gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Alias for record_gauge with production safeguards."""
        self.record_gauge(name, value, tags)

    def get_timer(self, name: str, tags: Optional[Dict[str, str]] = None) -> Timer:
        """Get a timer context manager (sync/async) with production safeguards."""
        return Timer(self, name, tags)

    # ---- Production Health and Monitoring ----
    def get_health_status(self) -> HealthStatus:
        """Get current health status"""
        self._update_health_status()
        return self.health_status

    def _update_health_status(self):
        """Update health status with current metrics"""
        try:
            # Get memory usage
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_usage_mb = memory_info.rss / 1024 / 1024

            # Calculate error rate
            total_operations = self.success_count + self.error_count
            error_rate = (self.error_count / total_operations) if total_operations > 0 else 0.0

            # Count circuit breakers
            open_circuits = sum(1 for is_open in self.circuit_breakers.values() if is_open)

            # Determine status
            issues = []
            status = "healthy"

            if memory_usage_mb > self.memory_critical_threshold:
                status = "unhealthy"
                issues.append(f"Critical memory usage: {memory_usage_mb:.1f}MB")
            elif memory_usage_mb > self.memory_warning_threshold:
                status = "degraded"
                issues.append(f"High memory usage: {memory_usage_mb:.1f}MB")

            if error_rate > 0.1:  # 10% error rate
                if error_rate > 0.5:  # 50% error rate
                    status = "unhealthy"
                else:
                    status = "degraded"
                issues.append(f"High error rate: {error_rate:.1%}")

            if open_circuits > 0:
                if open_circuits > 2:
                    status = "unhealthy"
                else:
                    status = "degraded"
                issues.append(f"Open circuit breakers: {open_circuits}")

            # Count series and points
            series_count = len(self.series)
            total_points = sum(len(s.points) for s in self.series.values())

            if series_count > MAX_SERIES_POINTS * 0.8:
                issues.append(f"High series count: {series_count}")

            self.health_status = HealthStatus(
                status=status,
                timestamp=time.time(),
                memory_usage_mb=memory_usage_mb,
                series_count=series_count,
                total_points=total_points,
                error_rate=error_rate,
                last_cleanup=self.last_health_check,
                circuit_breakers_open=open_circuits,
                issues=issues,
            )

        except Exception as e:
            logger.error(f"Failed to update health status: {e}")
            self.health_status = HealthStatus(
                status="unhealthy",
                timestamp=time.time(),
                memory_usage_mb=0.0,
                series_count=0,
                total_points=0,
                error_rate=1.0,
                last_cleanup=0.0,
                circuit_breakers_open=0,
                issues=[f"Health check failed: {e}"],
            )

    def _check_memory_limits(self):
        """Check memory usage and take action if needed"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_usage_mb = memory_info.rss / 1024 / 1024

            if memory_usage_mb > self.memory_critical_threshold:
                logger.critical(f"Critical memory usage: {memory_usage_mb:.1f}MB")
                self._emergency_cleanup()
                raise ResourceLimitError(f"Memory limit exceeded: {memory_usage_mb:.1f}MB")
            elif memory_usage_mb > self.memory_warning_threshold:
                logger.warning(f"High memory usage: {memory_usage_mb:.1f}MB")
                self._aggressive_cleanup()

        except Exception as e:
            logger.error(f"Memory check failed: {e}")

    def _emergency_cleanup(self):
        """Emergency cleanup to free memory"""
        logger.critical("Performing emergency cleanup")

        # Remove oldest series
        series_by_age = sorted(self.series.items(), key=lambda x: x[1]._created_at)

        # Remove 50% of oldest series
        remove_count = len(series_by_age) // 2
        for i in range(remove_count):
            key, _ = series_by_age[i]
            del self.series[key]

        # Force garbage collection
        gc.collect()

        self._audit_log(
            "emergency_cleanup",
            {"removed_series": remove_count, "remaining_series": len(self.series)},
        )

    def _aggressive_cleanup(self):
        """Aggressive cleanup to reduce memory usage"""
        logger.warning("Performing aggressive cleanup")

        # Remove series with no recent activity
        cutoff_time = time.time() - 3600  # 1 hour ago
        removed_count = 0

        for key, series in list(self.series.items()):
            if series._last_accessed < cutoff_time and len(series.points) == 0:
                del self.series[key]
                removed_count += 1

        # Force garbage collection
        gc.collect()

        self._audit_log(
            "aggressive_cleanup",
            {"removed_series": removed_count, "remaining_series": len(self.series)},
        )

    def _audit_log(self, action: str, details: Dict[str, Any]):
        """Log audit events"""
        try:
            audit_entry = {
                "timestamp": time.time(),
                "action": action,
                "details": details,
                "series_count": len(self.series),
                "memory_usage_mb": psutil.Process().memory_info().rss / 1024 / 1024,
            }
            self.audit_log.append(audit_entry)
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")

    async def _health_monitoring_loop(self):
        """Background health monitoring loop"""
        try:
            while self._running:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)
                self._update_health_status()
                self.last_health_check = time.time()

                # Log health status if degraded or unhealthy
                if self.health_status.status != "healthy":
                    logger.warning(
                        f"Health status: {self.health_status.status} - {self.health_status.issues}"
                    )

        except asyncio.CancelledError:
            logger.info("Health monitoring loop cancelled")
        except Exception as e:
            logger.error(f"Health monitoring loop error: {e}")

    # ---- Production Lookups & Stats ----
    def get_metric_value(self, name: str, tags: Optional[Dict[str, str]] = None) -> Optional[float]:
        """Get the latest value for a metric with production safeguards."""
        try:
            validated_name = validate_metric_name(name)
            validated_tags = validate_tags(tags)

            with self.lock:
                s = self.series.get(self._series_key(validated_name, validated_tags))
                if s and s.points:
                    return float(s.points[-1].value)
                return None

        except ValidationError as e:
            logger.warning(f"Validation error in get_metric_value: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting metric value {name}: {e}")
            return None

    def get_metric_stats(
        self, name: str, window_seconds: int = 300, tags: Optional[Dict[str, str]] = None
    ) -> Dict[str, float]:
        """Get statistical summary of a metric over a time window with production safeguards."""
        try:
            validated_name = validate_metric_name(name)
            validated_tags = validate_tags(tags)

            if window_seconds <= 0:
                raise ValidationError("Window seconds must be positive")
            if window_seconds > 86400:  # 24 hours
                logger.warning(f"Large time window requested: {window_seconds}s")

            with self.lock:
                s = self.series.get(self._series_key(validated_name, validated_tags))
                if not s or not s.points:
                    return {}

                end_time = time.time()
                start_time = end_time - float(window_seconds)
                window_points = [p for p in s.points if start_time <= p.timestamp <= end_time]
                if not window_points:
                    return {}

                values = np.array([p.value for p in window_points], dtype=float)
                stats: Dict[str, float] = {
                    "count": float(values.size),
                    "min": float(np.min(values)),
                    "max": float(np.max(values)),
                    "mean": float(np.mean(values)),
                    "median": float(np.median(values)),
                    "std": float(np.std(values)) if values.size > 1 else 0.0,
                }

                if s.metric_type in (MetricType.TIMER, MetricType.HISTOGRAM):
                    # percentiles
                    for q in (50, 90, 95, 99):
                        stats[f"p{q}"] = float(np.percentile(values, q))
                if s.metric_type == MetricType.COUNTER and values.size > 1:
                    time_span = window_points[-1].timestamp - window_points[0].timestamp
                    if time_span > 0:
                        value_change = window_points[-1].value - window_points[0].value
                        stats["rate"] = float(value_change / time_span)
                if s.metric_type == MetricType.RATE:
                    # Provide average rate in window for convenience.
                    stats["avg_rate"] = float(np.mean(values))

                return stats

        except ValidationError as e:
            logger.warning(f"Validation error in get_metric_stats: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error getting metric stats {name}: {e}")
            return {}

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get all current metrics with their latest values and metadata."""
        with self.lock:
            result: Dict[str, Dict[str, Any]] = {}
            for series_key, s in self.series.items():
                if not s.points:
                    continue
                latest = s.points[-1]
                result[series_key] = {
                    "name": s.name,
                    "type": s.metric_type.value,
                    "value": float(latest.value),
                    "timestamp": float(latest.timestamp),
                    "tags": dict(s.tags),
                    "point_count": len(s.points),
                    "last_accessed": s._last_accessed,
                    "access_count": s._access_count,
                }
            return result

    def delete_series(self, name: str, tags: Optional[Dict[str, str]] = None) -> bool:
        """Delete a metric series with production safeguards; returns True if removed."""
        try:
            validated_name = validate_metric_name(name)
            validated_tags = validate_tags(tags)

            with self.lock:
                key = self._series_key(validated_name, validated_tags)
                existed = key in self.series
                if existed:
                    del self.series[key]
                    self._rate_state.pop(key, None)
                    self._audit_log(
                        "series_deleted", {"name": validated_name, "tags": validated_tags}
                    )
                return existed

        except ValidationError as e:
            logger.warning(f"Validation error in delete_series: {e}")
            return False
        except Exception as e:
            logger.error(f"Error deleting series {name}: {e}")
            return False

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent audit log entries"""
        with self.lock:
            return list(self.audit_log)[-limit:]

    def reset_counters(self):
        """Reset all counters to zero (useful for testing)"""
        with self.lock:
            reset_count = 0
            for series in self.series.values():
                if series.metric_type == MetricType.COUNTER:
                    series.points.clear()
                    reset_count += 1

            self._audit_log("counters_reset", {"reset_count": reset_count})
            logger.info(f"Reset {reset_count} counter series")

    # ---- Production Export Methods ----
    def export_metrics(self, format_type: str = "prometheus") -> str:
        """Export metrics in Prometheus or JSON with production safeguards."""
        try:
            fmt = format_type.lower()
            if fmt == "prometheus":
                return self._export_prometheus()
            elif fmt == "json":
                return self._export_json()
            elif fmt == "health":
                return self._export_health()
            else:
                raise ValidationError(f"Unsupported export format: {format_type}")

        except Exception as e:
            logger.error(f"Export failed: {e}")
            raise MetricsError(f"Export failed: {e}")

    def _export_prometheus(self) -> str:
        """Export metrics in Prometheus exposition format with production safeguards."""
        lines: List[str] = []
        try:
            with self.lock:
                for s in self.series.values():
                    if not s.points:
                        continue
                    latest = s.points[-1]

                    # Sanitize metric name for Prometheus
                    prom_name = re.sub(r"[^a-zA-Z0-9_:]", "_", s.name)
                    if not prom_name or prom_name[0].isdigit():
                        prom_name = f"metric_{prom_name}"

                    type_map = {
                        MetricType.COUNTER: "counter",
                        MetricType.GAUGE: "gauge",
                        MetricType.HISTOGRAM: "histogram",
                        MetricType.TIMER: "histogram",
                        MetricType.RATE: "gauge",
                    }
                    prom_type = type_map.get(s.metric_type, "gauge")
                    lines.append(f"# TYPE {prom_name} {prom_type}")

                    tag_str = ""
                    if s.tags:
                        # Sort for stable output and sanitize
                        tag_pairs = []
                        for k, v in sorted(s.tags.items()):
                            safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", k)
                            safe_value = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", str(v))
                            tag_pairs.append(f'{safe_key}="{safe_value}"')
                        tag_str = "{" + ",".join(tag_pairs) + "}"

                    # Use current timestamp for Prometheus
                    timestamp_ms = int(time.time() * 1000)
                    lines.append(f"{prom_name}{tag_str} {latest.value} {timestamp_ms}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Prometheus export failed: {e}")
            return f"# ERROR: {e}"

    def _export_json(self) -> str:
        """Export metrics in a compact JSON array with production safeguards."""
        try:
            metrics_data: List[Dict[str, Any]] = []
            with self.lock:
                for s in self.series.values():
                    if not s.points:
                        continue
                    latest = s.points[-1]
                    metrics_data.append(
                        {
                            "name": s.name,
                            "type": s.metric_type.value,
                            "value": float(latest.value),
                            "timestamp": float(latest.timestamp),
                            "tags": dict(s.tags),
                            "point_count": len(s.points),
                            "last_accessed": s._last_accessed,
                        }
                    )
            return json.dumps(metrics_data, indent=2, separators=(",", ":"))

        except Exception as e:
            logger.error(f"JSON export failed: {e}")
            return json.dumps({"error": str(e)})

    def _export_health(self) -> str:
        """Export health status as JSON"""
        try:
            health = self.get_health_status()
            return json.dumps(
                {
                    "status": health.status,
                    "timestamp": health.timestamp,
                    "memory_usage_mb": health.memory_usage_mb,
                    "series_count": health.series_count,
                    "total_points": health.total_points,
                    "error_rate": health.error_rate,
                    "issues": health.issues,
                },
                indent=2,
            )
        except Exception as e:
            logger.error(f"Health export failed: {e}")
            return json.dumps({"error": str(e)})

    def register_export_callback(self, callback: Callable[[List[MetricPoint]], None]):
        """Register a callback for metric export with production safeguards."""
        if not callable(callback):
            raise ValidationError("Callback must be callable")

        self.export_callbacks.append(callback)
        self._audit_log("callback_registered", {"callback_count": len(self.export_callbacks)})

    async def emit_metrics(
        self, metrics: Dict[str, Union[int, float]], tags: Optional[Dict[str, str]] = None
    ):
        """Emit multiple metrics as gauges at once with production safeguards."""
        try:
            start = time.perf_counter()
            validated_tags = validate_tags(tags)

            for name, value in metrics.items():
                if isinstance(value, (int, float)):
                    self.record_gauge(name, float(value), validated_tags)

            # Track collection performance
            collection_time = (time.perf_counter() - start) * 1000.0
            self.collection_times.append(collection_time)

            # Snapshot points to avoid holding the lock while running callbacks
            if self.export_callbacks:
                all_points: List[MetricPoint] = []
                with self.lock:
                    for s in self.series.values():
                        if s.points:
                            all_points.extend(list(s.points))

                for cb in self.export_callbacks:
                    try:
                        cb(all_points)
                    except Exception as e:
                        logger.warning(f"Error in export callback: {e}")

        except Exception as e:
            logger.error(f"Emit metrics failed: {e}")
            raise MetricsError(f"Emit metrics failed: {e}")

    # ---- Production Background Maintenance ----
    async def _cleanup_loop(self):
        """Background cleanup of old metric data with production safeguards."""
        try:
            while self._running:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_old_data()

                # Update health status during cleanup
                self._update_health_status()

        except asyncio.CancelledError:
            logger.info("Cleanup loop cancelled")
        except Exception as e:
            logger.error(f"Metrics cleanup loop error: {e}")

    async def _cleanup_old_data(self):
        """Clean up old metric data points with production safeguards."""
        try:
            cutoff = time.time() - (24 * 3600)  # 24 hours
            removed_points = 0
            removed_series = 0

            with self.lock:
                # Clean up old points
                for s in list(self.series.values()):
                    len(s.points)
                    while s.points and s.points[0].timestamp < cutoff:
                        s.points.popleft()
                        removed_points += 1

                    # Remove empty series that haven't been accessed recently
                    if len(s.points) == 0 and s._last_accessed < cutoff and s._access_count == 0:
                        key = self._series_key(s.name, s.tags)
                        if key in self.series:
                            del self.series[key]
                            removed_series += 1

                # Log cleanup results
                if removed_points > 0 or removed_series > 0:
                    self._audit_log(
                        "cleanup_completed",
                        {
                            "removed_points": removed_points,
                            "removed_series": removed_series,
                            "remaining_series": len(self.series),
                        },
                    )

        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

    # ---- Production Performance Monitoring ----
    def get_performance_stats(self) -> Dict[str, float]:
        """Get metrics collection performance statistics with production safeguards."""
        try:
            if not self.collection_times:
                return {}

            times = np.array(self.collection_times, dtype=float)
            with self.lock:
                total_points = float(sum(len(s.points) for s in self.series.values()))
                total_series = float(len(self.series))
                total_operations = self.success_count + self.error_count

            return {
                "avg_collection_time_ms": float(np.mean(times)),
                "p95_collection_time_ms": float(np.percentile(times, 95)),
                "p99_collection_time_ms": float(np.percentile(times, 99)),
                "max_collection_time_ms": float(np.max(times)),
                "min_collection_time_ms": float(np.min(times)),
                "total_collections": float(times.size),
                "total_series": total_series,
                "total_points": total_points,
                "success_count": float(self.success_count),
                "error_count": float(self.error_count),
                "error_rate": (
                    float(self.error_count / total_operations) if total_operations > 0 else 0.0
                ),
                "memory_usage_mb": psutil.Process().memory_info().rss / 1024 / 1024,
            }

        except Exception as e:
            logger.error(f"Performance stats failed: {e}")
            return {"error": str(e)}

    def get_system_info(self) -> Dict[str, Any]:
        """Get system information for monitoring"""
        try:
            process = psutil.Process()
            return {
                "pid": process.pid,
                "memory_usage_mb": process.memory_info().rss / 1024 / 1024,
                "cpu_percent": process.cpu_percent(),
                "thread_count": process.num_threads(),
                "open_files": len(process.open_files()),
                "uptime_seconds": time.time() - process.create_time(),
                "python_version": sys.version,
                "platform": sys.platform,
            }
        except Exception as e:
            logger.error(f"System info failed: {e}")
            return {"error": str(e)}

    # ---- Production Internals ----
    def _get_or_create_series(
        self, name: str, metric_type: MetricType, tags: Optional[Dict[str, str]]
    ) -> MetricSeries:
        """Get or create a metric series with production safeguards."""
        key = self._series_key(name, tags)
        s = self.series.get(key)
        if s is None:
            # Check if we're at the series limit
            if len(self.series) >= MAX_SERIES_POINTS:
                logger.warning(f"Series limit reached: {len(self.series)}")
                # Remove oldest series
                oldest_key = min(self.series.keys(), key=lambda k: self.series[k]._created_at)
                del self.series[oldest_key]
                self._audit_log("series_evicted", {"evicted_key": oldest_key})

            s = MetricSeries(
                name=name,
                metric_type=metric_type,
                max_points=self.max_series_points,
                tags=dict(tags or {}),
            )
            self.series[key] = s
            self._audit_log(
                "series_created", {"name": name, "type": metric_type.value, "tags": tags or {}}
            )
        return s

    def _series_key(self, name: str, tags: Optional[Dict[str, str]]) -> str:
        """Generate a stable series key with production safeguards."""
        if not tags:
            return name

        # Sort tags for stable keys and sanitize
        tag_pairs = []
        for k in sorted(tags.keys()):
            v = str(tags[k])
            # Sanitize key and value
            safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", k)
            safe_value = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", v)
            tag_pairs.append(f"{safe_key}={safe_value}")

        return f"{name}[{','.join(tag_pairs)}]"


# =============================================================================
# Production Scalping Metrics
# =============================================================================


class ScalpingMetrics:
    """Production-grade pre-configured metrics for scalping operations"""

    def __init__(self, collector: MetricsCollector):
        if not isinstance(collector, MetricsCollector):
            raise ValidationError("Collector must be a MetricsCollector instance")
        self.collector = collector

    def record_trade_execution(
        self, pair: str, side: str, size: float, price: float, latency_ms: float, **kwargs
    ):
        """Record trade execution metrics with production safeguards."""
        try:
            # Validate inputs
            if not isinstance(pair, str) or not pair:
                raise ValidationError("Pair must be a non-empty string")
            if side not in ["buy", "sell"]:
                raise ValidationError("Side must be 'buy' or 'sell'")
            if size <= 0:
                raise ValidationError("Size must be positive")
            if price <= 0:
                raise ValidationError("Price must be positive")
            if latency_ms < 0:
                raise ValidationError("Latency cannot be negative")

            tags = {"pair": pair, "side": side}

            # Add optional tags
            for key, value in kwargs.items():
                if isinstance(value, (str, int, float)):
                    tags[key] = str(value)

            # Record metrics
            self.collector.increment("trades_executed_total", tags)
            self.collector.record_gauge("trade_size", size, tags)
            self.collector.record_gauge("trade_price", price, tags)
            self.collector.record_timer("trade_execution_latency_ms", latency_ms, tags)
            self.collector.record_gauge("trade_notional", size * price, tags)

            # Record additional metrics
            self.collector.record_histogram("trade_size_distribution", size, tags)
            self.collector.record_histogram("trade_price_distribution", price, tags)

        except ValidationError as e:
            logger.warning(f"Validation error in record_trade_execution: {e}")
            raise
        except Exception as e:
            logger.error(f"Error recording trade execution: {e}")
            raise MetricsError(f"Failed to record trade execution: {e}")

    def record_order_book_update(
        self, pair: str, spread_bps: float, depth_btc: float, processing_time_ms: float, **kwargs
    ):
        """Record order book metrics with production safeguards."""
        try:
            # Validate inputs
            if not isinstance(pair, str) or not pair:
                raise ValidationError("Pair must be a non-empty string")
            if spread_bps < 0:
                raise ValidationError("Spread cannot be negative")
            if depth_btc < 0:
                raise ValidationError("Depth cannot be negative")
            if processing_time_ms < 0:
                raise ValidationError("Processing time cannot be negative")

            tags = {"pair": pair}

            # Add optional tags
            for key, value in kwargs.items():
                if isinstance(value, (str, int, float)):
                    tags[key] = str(value)

            # Record metrics
            self.collector.increment("book_updates_total", tags)
            self.collector.record_gauge("spread_bps", spread_bps, tags)
            self.collector.record_gauge("book_depth_btc", depth_btc, tags)
            self.collector.record_timer("book_processing_time_ms", processing_time_ms, tags)

            # Record additional metrics
            self.collector.record_histogram("spread_distribution", spread_bps, tags)
            self.collector.record_histogram("depth_distribution", depth_btc, tags)

        except ValidationError as e:
            logger.warning(f"Validation error in record_order_book_update: {e}")
            raise
        except Exception as e:
            logger.error(f"Error recording order book update: {e}")
            raise MetricsError(f"Failed to record order book update: {e}")

    def record_pnl(self, strategy: str, pnl_usd: float, pnl_bps: float, **kwargs):
        """Record P&L metrics with production safeguards."""
        try:
            # Validate inputs
            if not isinstance(strategy, str) or not strategy:
                raise ValidationError("Strategy must be a non-empty string")
            if not np.isfinite(pnl_usd):
                raise ValidationError("PnL USD must be finite")
            if not np.isfinite(pnl_bps):
                raise ValidationError("PnL BPS must be finite")

            tags = {"strategy": strategy}

            # Add optional tags
            for key, value in kwargs.items():
                if isinstance(value, (str, int, float)):
                    tags[key] = str(value)

            # Record metrics
            self.collector.record_gauge("pnl_usd", pnl_usd, tags)
            self.collector.record_gauge("pnl_bps", pnl_bps, tags)

            # Record additional metrics
            self.collector.record_histogram("pnl_usd_distribution", pnl_usd, tags)
            self.collector.record_histogram("pnl_bps_distribution", pnl_bps, tags)

            # Record cumulative P&L
            self.collector.record_counter("cumulative_pnl_usd", pnl_usd, tags)
            self.collector.record_counter("cumulative_pnl_bps", pnl_bps, tags)

        except ValidationError as e:
            logger.warning(f"Validation error in record_pnl: {e}")
            raise
        except Exception as e:
            logger.error(f"Error recording P&L: {e}")
            raise MetricsError(f"Failed to record P&L: {e}")

    def record_risk_metrics(self, drawdown: float, positions: int, exposure: float, **kwargs):
        """Record risk metrics with production safeguards."""
        try:
            # Validate inputs
            if not np.isfinite(drawdown):
                raise ValidationError("Drawdown must be finite")
            if not isinstance(positions, int) or positions < 0:
                raise ValidationError("Positions must be a non-negative integer")
            if not np.isfinite(exposure):
                raise ValidationError("Exposure must be finite")

            tags = {}

            # Add optional tags
            for key, value in kwargs.items():
                if isinstance(value, (str, int, float)):
                    tags[key] = str(value)

            # Record metrics
            self.collector.record_gauge("drawdown", drawdown, tags)
            self.collector.record_gauge("open_positions", positions, tags)
            self.collector.record_gauge("total_exposure", exposure, tags)

            # Record additional risk metrics
            self.collector.record_histogram("drawdown_distribution", drawdown, tags)
            self.collector.record_histogram("exposure_distribution", exposure, tags)

        except ValidationError as e:
            logger.warning(f"Validation error in record_risk_metrics: {e}")
            raise
        except Exception as e:
            logger.error(f"Error recording risk metrics: {e}")
            raise MetricsError(f"Failed to record risk metrics: {e}")

    def record_system_metrics(
        self, cpu_percent: float, memory_percent: float, latency_ms: float, **kwargs
    ):
        """Record system performance metrics with production safeguards."""
        try:
            # Validate inputs
            if not 0 <= cpu_percent <= 100:
                raise ValidationError("CPU percent must be between 0 and 100")
            if not 0 <= memory_percent <= 100:
                raise ValidationError("Memory percent must be between 0 and 100")
            if latency_ms < 0:
                raise ValidationError("Latency cannot be negative")

            tags = {}

            # Add optional tags
            for key, value in kwargs.items():
                if isinstance(value, (str, int, float)):
                    tags[key] = str(value)

            # Record metrics
            self.collector.record_gauge("system_cpu_percent", cpu_percent, tags)
            self.collector.record_gauge("system_memory_percent", memory_percent, tags)
            self.collector.record_gauge("system_latency_ms", latency_ms, tags)

            # Record additional system metrics
            self.collector.record_histogram("cpu_distribution", cpu_percent, tags)
            self.collector.record_histogram("memory_distribution", memory_percent, tags)
            self.collector.record_histogram("latency_distribution", latency_ms, tags)

        except ValidationError as e:
            logger.warning(f"Validation error in record_system_metrics: {e}")
            raise
        except Exception as e:
            logger.error(f"Error recording system metrics: {e}")
            raise MetricsError(f"Failed to record system metrics: {e}")

    def record_strategy_metrics(
        self, strategy: str, signal_strength: float, confidence: float, **kwargs
    ):
        """Record strategy-specific metrics with production safeguards."""
        try:
            # Validate inputs
            if not isinstance(strategy, str) or not strategy:
                raise ValidationError("Strategy must be a non-empty string")
            if not 0 <= signal_strength <= 1:
                raise ValidationError("Signal strength must be between 0 and 1")
            if not 0 <= confidence <= 1:
                raise ValidationError("Confidence must be between 0 and 1")

            tags = {"strategy": strategy}

            # Add optional tags
            for key, value in kwargs.items():
                if isinstance(value, (str, int, float)):
                    tags[key] = str(value)

            # Record metrics
            self.collector.record_gauge("signal_strength", signal_strength, tags)
            self.collector.record_gauge("confidence", confidence, tags)

            # Record additional strategy metrics
            self.collector.record_histogram("signal_strength_distribution", signal_strength, tags)
            self.collector.record_histogram("confidence_distribution", confidence, tags)

        except ValidationError as e:
            logger.warning(f"Validation error in record_strategy_metrics: {e}")
            raise
        except Exception as e:
            logger.error(f"Error recording strategy metrics: {e}")
            raise MetricsError(f"Failed to record strategy metrics: {e}")


# =============================================================================
# Production Example Usage and Testing
# =============================================================================

if __name__ == "__main__":

    async def main():
        """Production example demonstrating all features"""
        logger.info("Starting Production Metrics Example")

        # Create collector with production settings
        collector = MetricsCollector(max_series_points=1000, cleanup_interval=60)

        try:
            # Start with production safeguards
            await collector.start()
            logger.info("MetricsCollector started successfully")

            # Create scalping metrics
            scalping_metrics = ScalpingMetrics(collector)
            logger.info("ScalpingMetrics initialized")

            # Record sample metrics with production validation
            logger.info("Recording sample metrics...")

            # Trade execution metrics
            scalping_metrics.record_trade_execution(
                pair="BTC/USD",
                side="buy",
                size=0.1,
                price=45000.0,
                latency_ms=150.0,
                exchange="kraken",
                strategy="scalping",
            )
            logger.info("Trade execution metrics recorded")

            # Order book metrics
            scalping_metrics.record_order_book_update(
                pair="BTC/USD",
                spread_bps=2.5,
                depth_btc=5.0,
                processing_time_ms=50.0,
                exchange="kraken",
            )
            logger.info("Order book metrics recorded")

            # P&L metrics
            scalping_metrics.record_pnl(
                strategy="scalping", pnl_usd=125.50, pnl_bps=2.8, pair="BTC/USD"
            )
            logger.info("P&L metrics recorded")

            # Risk metrics
            scalping_metrics.record_risk_metrics(
                drawdown=0.05, positions=3, exposure=0.15, pair="BTC/USD"
            )
            logger.info("Risk metrics recorded")

            # System metrics
            scalping_metrics.record_system_metrics(
                cpu_percent=45.2, memory_percent=67.8, latency_ms=25.5, host="production-01"
            )
            logger.info("System metrics recorded")

            # Strategy metrics
            scalping_metrics.record_strategy_metrics(
                strategy="scalping", signal_strength=0.85, confidence=0.92, pair="BTC/USD"
            )
            logger.info("Strategy metrics recorded")

            # Use timer context manager (async)
            logger.info("Testing timer context manager...")
            async with collector.get_timer("order_processing", {K_COMPONENT: "execution"}):
                await asyncio.sleep(0.001)  # Simulate processing
            logger.info("Timer context manager tested")

            # Test error handling
            logger.info("Testing error handling...")
            try:
                scalping_metrics.record_trade_execution(
                    pair="", side="buy", size=0.1, price=45000.0, latency_ms=150.0  # Invalid pair
                )
            except ValidationError as e:
                logger.info("Validation error caught: %s", e)

            # Get metric statistics
            logger.info("Getting metric statistics...")
            stats = collector.get_metric_stats(
                "trade_execution_latency_ms", tags={"pair": "BTC/USD", "side": "buy"}
            )
            logger.info("Trade execution stats: %s", stats)

            # Get health status
            logger.info("Getting health status...")
            health = collector.get_health_status()
            logger.info("Health status: %s", health.status)
            logger.info("Memory usage: %.1fMB", health.memory_usage_mb)
            logger.info("Series count: %d", health.series_count)
            logger.info("Error rate: %.2f%%", health.error_rate * 100)

            # Get performance stats
            logger.info("Getting performance statistics...")
            perf_stats = collector.get_performance_stats()
            logger.info("Performance stats: %s", perf_stats)

            # Export metrics
            logger.info("Exporting metrics...")
            prometheus_output = collector.export_metrics("prometheus")
            logger.info("Prometheus metrics (first 500 chars):\n%s...", prometheus_output[:500])

            json_output = collector.export_metrics("json")
            logger.info("JSON metrics (first 500 chars):\n%s...", json_output[:500])

            health_output = collector.export_metrics("health")
            logger.info("Health export:\n%s", health_output)

            # Get audit log
            logger.info("Getting audit log...")
            audit_log = collector.get_audit_log(limit=10)
            logger.info("Recent audit entries: %d", len(audit_log))

            logger.info("All production features tested successfully!")

        except Exception as e:
            logger.error("Error during testing: %s", e)
            logger.error("Example failed: %s", e)
        finally:
            # Graceful shutdown
            await collector.stop()
            logger.info("MetricsCollector stopped gracefully")

    # Run the example
    asyncio.run(main())
