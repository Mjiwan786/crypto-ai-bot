"""
PRD-001 Compliant Prometheus Metrics Exporter

This module provides a unified Prometheus metrics exporter that exposes all
required metrics for Task D observability requirements.

Required Metrics (Task D):
- signals_published_total{pair, strategy, side}
- signal_generation_latency_ms (histogram)
- current_drawdown_pct (gauge)
- active_positions{pair} (gauge)
- risk_rejections_total{pair, reason} (counter)

Additional Metrics:
- redis_connected (gauge)
- kraken_ws_connected{pair} (gauge)
- last_signal_age_seconds (gauge)
- last_pnl_update_age_seconds (gauge)
- engine_uptime_seconds (gauge)
- engine_healthy (gauge)

Usage:
    from monitoring.prd_metrics_exporter import PRDMetricsExporter

    exporter = PRDMetricsExporter(port=9108)
    exporter.start()

    # Record metrics
    exporter.record_signal_published("BTC/USD", "SCALPER", "LONG", latency_ms=150)
    exporter.record_risk_rejection("BTC/USD", "wide_spread")
    exporter.update_drawdown(2.5)
    exporter.update_active_positions("BTC/USD", 1)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, Optional, Any

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        Info,
        start_http_server,
        REGISTRY,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Create dummy classes for when prometheus_client is not available
    class Counter:
        def __init__(self, *args, **kwargs):
            pass
        def labels(self, **kwargs):
            return self
        def inc(self, amount=1):
            pass
    class Gauge:
        def __init__(self, *args, **kwargs):
            pass
        def labels(self, **kwargs):
            return self
        def set(self, value):
            pass
    class Histogram:
        def __init__(self, *args, **kwargs):
            pass
        def observe(self, value):
            pass
    class Info:
        def __init__(self, *args, **kwargs):
            pass
        def info(self, data):
            pass
    def start_http_server(*args, **kwargs):
        pass

logger = logging.getLogger(__name__)


class PRDMetricsExporter:
    """
    PRD-001 Compliant Prometheus Metrics Exporter

    Exposes all required metrics via HTTP /metrics endpoint.
    """

    def __init__(
        self,
        port: int = 9108,
        host: str = "0.0.0.0",
        enabled: Optional[bool] = None,
    ):
        """
        Initialize metrics exporter.

        Args:
            port: HTTP port for /metrics endpoint (default: 9108)
            host: Host to bind (default: 0.0.0.0)
            enabled: Enable metrics (default: from METRICS_ENABLED env or True)
        """
        self.port = port or int(os.getenv("METRICS_PORT", "9108"))
        self.host = host or os.getenv("METRICS_HOST", "0.0.0.0")
        self.enabled = enabled if enabled is not None else (
            os.getenv("METRICS_ENABLED", "true").lower() == "true"
        )

        self.start_time = time.time()
        self._server_started = False
        self._server_thread: Optional[threading.Thread] = None

        if not PROMETHEUS_AVAILABLE:
            logger.warning("prometheus_client not available, metrics disabled")
            self.enabled = False

        if self.enabled:
            self._init_metrics()
            logger.info(f"PRDMetricsExporter initialized (port={self.port})")
        else:
            logger.info("PRDMetricsExporter disabled")
            self._init_dummy_metrics()

    def _init_metrics(self):
        """Initialize all Prometheus metrics."""

        # =====================================================================
        # Task D Required Metrics
        # =====================================================================

        # Counter: signals_published_total{pair, strategy, side}
        self.signals_published_total = Counter(
            "signals_published_total",
            "Total number of signals published to Redis",
            ["pair", "strategy", "side"],
        )

        # Histogram: signal_generation_latency_ms
        self.signal_generation_latency_ms = Histogram(
            "signal_generation_latency_ms",
            "Signal generation latency in milliseconds",
            buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
        )

        # Gauge: current_drawdown_pct
        self.current_drawdown_pct = Gauge(
            "current_drawdown_pct",
            "Current drawdown percentage",
        )

        # Gauge: active_positions{pair}
        self.active_positions = Gauge(
            "active_positions",
            "Number of active positions by trading pair",
            ["pair"],
        )

        # Counter: risk_rejections_total{pair, reason}
        self.risk_rejections_total = Counter(
            "risk_rejections_total",
            "Total number of risk filter rejections",
            ["pair", "reason"],
        )

        # =====================================================================
        # Additional Observability Metrics
        # =====================================================================

        # Gauge: redis_connected (1=connected, 0=disconnected)
        self.redis_connected = Gauge(
            "redis_connected",
            "Redis connection status (1=connected, 0=disconnected)",
        )

        # Gauge: kraken_ws_connected{pair}
        self.kraken_ws_connected = Gauge(
            "kraken_ws_connected",
            "Kraken WebSocket connection status by pair (1=connected, 0=disconnected)",
            ["pair"],
        )

        # Gauge: last_signal_age_seconds
        self.last_signal_age_seconds = Gauge(
            "last_signal_age_seconds",
            "Seconds since last signal was published",
        )

        # Gauge: last_pnl_update_age_seconds
        self.last_pnl_update_age_seconds = Gauge(
            "last_pnl_update_age_seconds",
            "Seconds since last PnL update",
        )

        # Gauge: engine_uptime_seconds
        self.engine_uptime_seconds = Gauge(
            "engine_uptime_seconds",
            "Engine uptime in seconds",
        )

        # Gauge: engine_healthy (1=healthy, 0=unhealthy)
        self.engine_healthy = Gauge(
            "engine_healthy",
            "Overall engine health status (1=healthy, 0=unhealthy)",
        )

        # Info: engine_info
        self.engine_info = Info(
            "engine_info",
            "Engine configuration information",
        )

        logger.info("Prometheus metrics initialized")

    def _init_dummy_metrics(self):
        """Initialize dummy metrics when disabled."""

        class DummyMetric:
            def labels(self, **kwargs):
                return self
            def inc(self, amount=1):
                pass
            def set(self, value):
                pass
            def observe(self, value):
                pass
            def info(self, data):
                pass

        self.signals_published_total = DummyMetric()
        self.signal_generation_latency_ms = DummyMetric()
        self.current_drawdown_pct = DummyMetric()
        self.active_positions = DummyMetric()
        self.risk_rejections_total = DummyMetric()
        self.redis_connected = DummyMetric()
        self.kraken_ws_connected = DummyMetric()
        self.last_signal_age_seconds = DummyMetric()
        self.last_pnl_update_age_seconds = DummyMetric()
        self.engine_uptime_seconds = DummyMetric()
        self.engine_healthy = DummyMetric()
        self.engine_info = DummyMetric()

    def start(self):
        """Start the Prometheus HTTP server."""
        if not self.enabled:
            logger.info("Metrics exporter disabled, not starting server")
            return

        if self._server_started:
            logger.warning("Metrics server already started")
            return

        try:
            def _start_server():
                start_http_server(self.port, addr=self.host, registry=REGISTRY)

            self._server_thread = threading.Thread(
                target=_start_server,
                daemon=True,
                name="prometheus_metrics_server"
            )
            self._server_thread.start()
            self._server_started = True

            logger.info(
                f"Prometheus metrics server started on {self.host}:{self.port}/metrics"
            )

        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")

    def stop(self):
        """Stop the metrics server (not typically needed for daemon thread)."""
        self._server_started = False
        logger.info("Metrics exporter stopped")

    # =====================================================================
    # Metric Recording Methods
    # =====================================================================

    def record_signal_published(
        self,
        pair: str,
        strategy: str,
        side: str,
        latency_ms: Optional[float] = None,
    ):
        """
        Record a published signal.

        Args:
            pair: Trading pair (e.g., "BTC/USD")
            strategy: Strategy name (e.g., "SCALPER")
            side: Trade side ("LONG" or "SHORT")
            latency_ms: Optional signal generation latency in milliseconds
        """
        self.signals_published_total.labels(
            pair=pair,
            strategy=strategy,
            side=side,
        ).inc()

        if latency_ms is not None:
            self.signal_generation_latency_ms.observe(latency_ms)

        # Update last signal age to 0 (just published)
        self.last_signal_age_seconds.set(0)

    def record_risk_rejection(self, pair: str, reason: str):
        """
        Record a risk filter rejection.

        Args:
            pair: Trading pair
            reason: Rejection reason (e.g., "wide_spread", "high_volatility", "daily_drawdown")
        """
        self.risk_rejections_total.labels(
            pair=pair,
            reason=reason,
        ).inc()

    def update_drawdown(self, drawdown_pct: float):
        """
        Update current drawdown percentage.

        Args:
            drawdown_pct: Current drawdown percentage (negative value)
        """
        self.current_drawdown_pct.set(drawdown_pct)

    def update_active_positions(self, pair: str, count: int):
        """
        Update active positions count for a pair.

        Args:
            pair: Trading pair
            count: Number of active positions
        """
        self.active_positions.labels(pair=pair).set(count)

    def update_redis_status(self, connected: bool):
        """
        Update Redis connection status.

        Args:
            connected: True if connected, False otherwise
        """
        self.redis_connected.set(1 if connected else 0)

    def update_kraken_ws_status(self, pair: str, connected: bool):
        """
        Update Kraken WebSocket connection status for a pair.

        Args:
            pair: Trading pair
            connected: True if connected, False otherwise
        """
        self.kraken_ws_connected.labels(pair=pair).set(1 if connected else 0)

    def update_signal_age(self, age_seconds: float):
        """
        Update last signal age.

        Args:
            age_seconds: Seconds since last signal was published
        """
        self.last_signal_age_seconds.set(age_seconds)

    def update_pnl_age(self, age_seconds: float):
        """
        Update last PnL update age.

        Args:
            age_seconds: Seconds since last PnL update
        """
        self.last_pnl_update_age_seconds.set(age_seconds)

    def update_uptime(self):
        """Update engine uptime gauge."""
        uptime = time.time() - self.start_time
        self.engine_uptime_seconds.set(uptime)

    def update_health(self, healthy: bool):
        """
        Update engine health status.

        Args:
            healthy: True if healthy, False otherwise
        """
        self.engine_healthy.set(1 if healthy else 0)

    def update_engine_info(self, info: Dict[str, str]):
        """
        Update engine info labels.

        Args:
            info: Dictionary of info labels (e.g., {"version": "1.0.0", "mode": "paper"})
        """
        self.engine_info.info(info)

    def update_all_dynamic_metrics(
        self,
        redis_connected: Optional[bool] = None,
        kraken_ws_status: Optional[Dict[str, bool]] = None,
        signal_age_seconds: Optional[float] = None,
        pnl_age_seconds: Optional[float] = None,
        healthy: Optional[bool] = None,
    ):
        """
        Update all dynamic metrics in one call.

        Args:
            redis_connected: Redis connection status
            kraken_ws_status: Dict of {pair: connected} for Kraken WS
            signal_age_seconds: Age of last signal
            pnl_age_seconds: Age of last PnL update
            healthy: Overall health status
        """
        self.update_uptime()

        if redis_connected is not None:
            self.update_redis_status(redis_connected)

        if kraken_ws_status:
            for pair, connected in kraken_ws_status.items():
                self.update_kraken_ws_status(pair, connected)

        if signal_age_seconds is not None:
            self.update_signal_age(signal_age_seconds)

        if pnl_age_seconds is not None:
            self.update_pnl_age(pnl_age_seconds)

        if healthy is not None:
            self.update_health(healthy)


# =============================================================================
# Singleton Instance
# =============================================================================

_global_exporter: Optional[PRDMetricsExporter] = None


def get_metrics_exporter() -> PRDMetricsExporter:
    """
    Get or create the global metrics exporter instance.

    Returns:
        PRDMetricsExporter singleton
    """
    global _global_exporter
    if _global_exporter is None:
        _global_exporter = PRDMetricsExporter()
        _global_exporter.start()
    return _global_exporter


# =============================================================================
# Convenience Functions
# =============================================================================

def record_signal_published(pair: str, strategy: str, side: str, latency_ms: Optional[float] = None):
    """Convenience function to record signal published."""
    exporter = get_metrics_exporter()
    exporter.record_signal_published(pair, strategy, side, latency_ms)


def record_risk_rejection(pair: str, reason: str):
    """Convenience function to record risk rejection."""
    exporter = get_metrics_exporter()
    exporter.record_risk_rejection(pair, reason)


def update_drawdown(drawdown_pct: float):
    """Convenience function to update drawdown."""
    exporter = get_metrics_exporter()
    exporter.update_drawdown(drawdown_pct)


def update_active_positions(pair: str, count: int):
    """Convenience function to update active positions."""
    exporter = get_metrics_exporter()
    exporter.update_active_positions(pair, count)


__all__ = [
    "PRDMetricsExporter",
    "get_metrics_exporter",
    "record_signal_published",
    "record_risk_rejection",
    "update_drawdown",
    "update_active_positions",
]









