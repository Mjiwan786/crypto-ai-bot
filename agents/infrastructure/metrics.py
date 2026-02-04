"""
Prometheus Metrics Module - E2

Provides observability metrics for the signal publisher.
Metrics are exported on a local web port (off by default).

Metrics:
- events_published_total{pair, stream}: Total signals published per pair
- publish_errors_total{pair, stream, error_type}: Publication errors
- publisher_uptime_seconds: Time since publisher started
- stream_name: Current target stream (as info metric)

Environment Variables:
- METRICS_ENABLED: Enable/disable metrics (default: false)
- METRICS_PORT: HTTP port for /metrics endpoint (default: 9090)
- METRICS_HOST: Host to bind (default: 127.0.0.1 - localhost only)
"""

import time
import logging
import os
from typing import Optional, Dict
from prometheus_client import (
    Counter,
    Gauge,
    Info,
    start_http_server,
    REGISTRY,
    CollectorRegistry
)

logger = logging.getLogger(__name__)


class PrometheusMetrics:
    """
    Prometheus metrics collector for signal publisher.

    Features:
    - Optional (disabled by default for safety)
    - Local-only HTTP server (127.0.0.1)
    - Standard Prometheus metrics format
    - Automatic uptime tracking
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        port: Optional[int] = None,
        host: Optional[str] = None,
        registry: Optional[CollectorRegistry] = None
    ):
        """
        Initialize Prometheus metrics.

        Args:
            enabled: Enable metrics export (default: from env or False)
            port: HTTP port for /metrics (default: from env or 9090)
            host: Host to bind (default: from env or 127.0.0.1)
            registry: Custom registry (default: global REGISTRY)
        """
        # Load configuration
        self.enabled = enabled if enabled is not None else \
            os.getenv('METRICS_ENABLED', 'false').lower() == 'true'

        self.port = port if port is not None else \
            int(os.getenv('METRICS_PORT', '9090'))

        self.host = host if host is not None else \
            os.getenv('METRICS_HOST', '127.0.0.1')

        self.registry = registry or REGISTRY

        # Start time for uptime calculation
        self.start_time = time.time()

        # HTTP server handle
        self._http_server = None

        if not self.enabled:
            logger.info("Prometheus metrics DISABLED (set METRICS_ENABLED=true to enable)")
            # Create dummy metrics that do nothing
            self._init_dummy_metrics()
            return

        # Initialize Prometheus metrics
        self._init_prometheus_metrics()

        # Start HTTP server
        self._start_http_server()

    def _init_prometheus_metrics(self):
        """Initialize Prometheus metric collectors"""

        # Counter: events_published_total{pair, stream}
        self.events_published = Counter(
            'events_published_total',
            'Total number of signals published',
            ['pair', 'stream'],
            registry=self.registry
        )

        # Counter: publish_errors_total{pair, stream, error_type}
        self.publish_errors = Counter(
            'publish_errors_total',
            'Total number of publish errors',
            ['pair', 'stream', 'error_type'],
            registry=self.registry
        )

        # Gauge: publisher_uptime_seconds
        self.uptime = Gauge(
            'publisher_uptime_seconds',
            'Time since publisher started (seconds)',
            registry=self.registry
        )

        # Set uptime callback
        self.uptime.set_function(lambda: time.time() - self.start_time)

        # Info: stream_name
        self.stream_info = Info(
            'stream',
            'Current target stream configuration',
            registry=self.registry
        )

        logger.info("Prometheus metrics initialized")

    def _init_dummy_metrics(self):
        """Initialize dummy metrics (no-op when disabled)"""

        class DummyMetric:
            def labels(self, **kwargs):
                return self

            def inc(self, amount=1):
                pass

            def set(self, value):
                pass

            def set_function(self, func):
                pass

            def info(self, data):
                pass

        self.events_published = DummyMetric()
        self.publish_errors = DummyMetric()
        self.uptime = DummyMetric()
        self.stream_info = DummyMetric()

    def _start_http_server(self):
        """Start HTTP server for /metrics endpoint"""
        if not self.enabled:
            return

        try:
            start_http_server(
                port=self.port,
                addr=self.host,
                registry=self.registry
            )

            logger.info(
                f"Prometheus metrics server started: "
                f"http://{self.host}:{self.port}/metrics"
            )

        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
            logger.info("Metrics will be collected but not exported")

    def record_publish(self, pair: str, stream: str):
        """
        Record a successful signal publish.

        Args:
            pair: Trading pair (e.g., 'BTC-USD')
            stream: Target stream (e.g., 'signals:paper')
        """
        self.events_published.labels(pair=pair, stream=stream).inc()

    def record_error(
        self,
        pair: str,
        stream: str,
        error_type: str
    ):
        """
        Record a publish error.

        Args:
            pair: Trading pair
            stream: Target stream
            error_type: Error classification (e.g., 'redis_error', 'timeout')
        """
        self.publish_errors.labels(
            pair=pair,
            stream=stream,
            error_type=error_type
        ).inc()

    def set_stream_info(self, stream_name: str, mode: str = 'paper'):
        """
        Set current stream configuration.

        Args:
            stream_name: Target stream name
            mode: Publishing mode (paper/live/staging)
        """
        self.stream_info.info({
            'stream_name': stream_name,
            'mode': mode
        })

    def get_uptime(self) -> float:
        """Get publisher uptime in seconds"""
        return time.time() - self.start_time

    def is_enabled(self) -> bool:
        """Check if metrics are enabled"""
        return self.enabled

    def get_endpoint(self) -> Optional[str]:
        """Get metrics HTTP endpoint URL"""
        if not self.enabled:
            return None

        return f"http://{self.host}:{self.port}/metrics"


# Singleton instance
_default_metrics: Optional[PrometheusMetrics] = None


def get_metrics() -> PrometheusMetrics:
    """Get or create default metrics instance"""
    global _default_metrics

    if _default_metrics is None:
        _default_metrics = PrometheusMetrics()

    return _default_metrics


# Convenience functions
def record_publish(pair: str, stream: str):
    """Record a successful publish"""
    get_metrics().record_publish(pair, stream)


def record_error(pair: str, stream: str, error_type: str):
    """Record a publish error"""
    get_metrics().record_error(pair, stream, error_type)


def set_stream_info(stream_name: str, mode: str = 'paper'):
    """Set stream configuration"""
    get_metrics().set_stream_info(stream_name, mode)


def get_uptime() -> float:
    """Get publisher uptime"""
    return get_metrics().get_uptime()
