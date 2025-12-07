"""
Engine Observability Module (monitoring/engine_observability.py)

PRD-001 compliant observability for crypto-ai-bot engine.

PROMETHEUS METRICS (Task D requirements):
- signals_published_total{pair, strategy, side}
- signal_generation_latency_ms (histogram)
- current_drawdown_pct (gauge)
- active_positions{pair} (gauge)
- risk_rejections_total{pair, reason}
- redis_connected (gauge)
- kraken_ws_connected{pair} (gauge)
- last_signal_age_seconds (gauge)
- last_pnl_update_age_seconds (gauge)

HEALTH CHECKS:
- Redis connectivity
- Kraken WS connectivity (per pair)
- Recent signal activity (stale detection)
- Recent PnL updates

HTTP ENDPOINTS:
- /metrics - Prometheus format
- /health - JSON health status

Usage:
    from monitoring.engine_observability import EngineObservability

    obs = EngineObservability(port=9108)
    obs.start()

    # Record metrics
    obs.record_signal_published("BTC/USD", "SCALPER", "LONG")
    obs.record_signal_latency(150.5)  # ms
    obs.set_drawdown(2.5)  # %
    obs.set_active_positions({"BTC/USD": 1, "ETH/USD": 2})
    obs.record_risk_rejection("BTC/USD", "spread_too_wide")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread, Lock
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        Info,
        CollectorRegistry,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class ObservabilityConfig:
    """Configuration for engine observability."""

    # HTTP server
    enabled: bool = field(default_factory=lambda: os.getenv("METRICS_ENABLED", "true").lower() == "true")
    port: int = field(default_factory=lambda: int(os.getenv("METRICS_PORT", os.getenv("PROMETHEUS_PORT", "9108"))))
    host: str = field(default_factory=lambda: os.getenv("METRICS_HOST", "0.0.0.0"))

    # Health check thresholds
    signal_stale_threshold_sec: int = field(default_factory=lambda: int(os.getenv("SIGNAL_STALE_THRESHOLD_SEC", "300")))
    pnl_stale_threshold_sec: int = field(default_factory=lambda: int(os.getenv("PNL_STALE_THRESHOLD_SEC", "600")))
    drawdown_warn_pct: float = field(default_factory=lambda: float(os.getenv("DRAWDOWN_WARN_PCT", "4.0")))
    drawdown_critical_pct: float = field(default_factory=lambda: float(os.getenv("DRAWDOWN_CRITICAL_PCT", "6.0")))

    # Engine mode
    mode: str = field(default_factory=lambda: os.getenv("ENGINE_MODE", os.getenv("TRADING_MODE", "paper")))


# =============================================================================
# HEALTH STATUS
# =============================================================================

@dataclass
class ComponentHealth:
    """Health status of a single component."""
    name: str
    healthy: bool
    message: str
    last_check: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class HealthAggregator:
    """
    Aggregates health status from multiple components.

    Thread-safe for updates from multiple sources.
    """

    def __init__(self, config: ObservabilityConfig):
        self.config = config
        self._lock = Lock()
        self._components: Dict[str, ComponentHealth] = {}
        self._start_time = time.time()

        # Signal/PnL tracking
        self._last_signal_ts: float = 0.0
        self._last_pnl_update_ts: float = 0.0
        self._signals_count: int = 0

    def update_component(self, name: str, healthy: bool, message: str = "", **metadata):
        """Update health status for a component."""
        with self._lock:
            self._components[name] = ComponentHealth(
                name=name,
                healthy=healthy,
                message=message,
                last_check=time.time(),
                metadata=metadata,
            )

    def record_signal(self):
        """Record that a signal was published."""
        with self._lock:
            self._last_signal_ts = time.time()
            self._signals_count += 1

    def record_pnl_update(self):
        """Record that PnL was updated."""
        with self._lock:
            self._last_pnl_update_ts = time.time()

    def is_signal_stale(self) -> bool:
        """Check if signal generation is stale."""
        if self._last_signal_ts == 0:
            return False  # No signals yet, not stale
        age = time.time() - self._last_signal_ts
        return age > self.config.signal_stale_threshold_sec

    def is_pnl_stale(self) -> bool:
        """Check if PnL updates are stale."""
        if self._last_pnl_update_ts == 0:
            return False  # No updates yet
        age = time.time() - self._last_pnl_update_ts
        return age > self.config.pnl_stale_threshold_sec

    def get_overall_health(self) -> Dict[str, Any]:
        """Get overall health status."""
        with self._lock:
            components = list(self._components.values())

        # Check core components
        redis_health = self._components.get("redis")
        ws_health = self._components.get("kraken_ws")

        # Determine overall status
        critical_unhealthy = []
        warnings = []

        if redis_health and not redis_health.healthy:
            critical_unhealthy.append("redis")

        if ws_health and not ws_health.healthy:
            critical_unhealthy.append("kraken_ws")

        if self.is_signal_stale():
            warnings.append("signal_generation_stale")

        if self.is_pnl_stale():
            warnings.append("pnl_updates_stale")

        # Status determination
        if critical_unhealthy:
            status = "unhealthy"
        elif warnings:
            status = "degraded"
        else:
            status = "healthy"

        uptime = time.time() - self._start_time

        return {
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": int(uptime),
            "mode": self.config.mode,
            "components": {c.name: {"healthy": c.healthy, "message": c.message} for c in components},
            "signals_generated": self._signals_count,
            "last_signal_age_seconds": int(time.time() - self._last_signal_ts) if self._last_signal_ts > 0 else None,
            "last_pnl_update_age_seconds": int(time.time() - self._last_pnl_update_ts) if self._last_pnl_update_ts > 0 else None,
            "warnings": warnings,
            "critical": critical_unhealthy,
        }

    def is_healthy(self) -> bool:
        """Quick check if system is healthy."""
        health = self.get_overall_health()
        return health["status"] in ("healthy", "degraded")


# =============================================================================
# PROMETHEUS METRICS
# =============================================================================

class EngineMetrics:
    """
    Prometheus metrics for the crypto-ai-bot engine.

    All metrics are namespaced with 'crypto_ai_bot_' prefix.
    """

    def __init__(self, registry: Optional[Any] = None):
        """Initialize Prometheus metrics."""
        if not PROMETHEUS_AVAILABLE:
            logger.warning("prometheus_client not available, using dummy metrics")
            self._init_dummy_metrics()
            return

        self.registry = registry or CollectorRegistry()
        self._init_prometheus_metrics()

    def _init_prometheus_metrics(self):
        """Initialize Prometheus metric collectors."""

        # Counter: signals_published_total{pair, strategy, side}
        self.signals_published = Counter(
            'crypto_ai_bot_signals_published_total',
            'Total signals published',
            ['pair', 'strategy', 'side'],
            registry=self.registry
        )

        # Histogram: signal_generation_latency_ms
        self.signal_latency = Histogram(
            'crypto_ai_bot_signal_generation_latency_ms',
            'Signal generation latency in milliseconds',
            buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
            registry=self.registry
        )

        # Gauge: current_drawdown_pct
        self.current_drawdown = Gauge(
            'crypto_ai_bot_current_drawdown_pct',
            'Current drawdown percentage',
            registry=self.registry
        )

        # Gauge: active_positions{pair}
        self.active_positions = Gauge(
            'crypto_ai_bot_active_positions',
            'Number of active positions by pair',
            ['pair'],
            registry=self.registry
        )

        # Counter: risk_rejections_total{pair, reason}
        self.risk_rejections = Counter(
            'crypto_ai_bot_risk_rejections_total',
            'Total risk filter rejections',
            ['pair', 'reason'],
            registry=self.registry
        )

        # Gauge: redis_connected (1=connected, 0=disconnected)
        self.redis_connected = Gauge(
            'crypto_ai_bot_redis_connected',
            'Redis connection status',
            registry=self.registry
        )

        # Gauge: kraken_ws_connected{pair}
        self.kraken_ws_connected = Gauge(
            'crypto_ai_bot_kraken_ws_connected',
            'Kraken WebSocket connection status by pair',
            ['pair'],
            registry=self.registry
        )

        # Gauge: last_signal_age_seconds
        self.last_signal_age = Gauge(
            'crypto_ai_bot_last_signal_age_seconds',
            'Seconds since last signal was published',
            registry=self.registry
        )

        # Gauge: last_pnl_update_age_seconds
        self.last_pnl_update_age = Gauge(
            'crypto_ai_bot_last_pnl_update_age_seconds',
            'Seconds since last PnL update',
            registry=self.registry
        )

        # Gauge: uptime_seconds
        self.uptime = Gauge(
            'crypto_ai_bot_uptime_seconds',
            'Engine uptime in seconds',
            registry=self.registry
        )

        # Gauge: engine_healthy (1=healthy, 0=unhealthy)
        self.engine_healthy = Gauge(
            'crypto_ai_bot_engine_healthy',
            'Overall engine health status',
            registry=self.registry
        )

        # Info: engine configuration
        self.engine_info = Info(
            'crypto_ai_bot_engine',
            'Engine configuration information',
            registry=self.registry
        )

        # Counter: errors_total{component}
        self.errors_total = Counter(
            'crypto_ai_bot_errors_total',
            'Total errors by component',
            ['component'],
            registry=self.registry
        )

        logger.info("Prometheus metrics initialized")

    def _init_dummy_metrics(self):
        """Initialize dummy metrics when Prometheus is not available."""

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

        self.signals_published = DummyMetric()
        self.signal_latency = DummyMetric()
        self.current_drawdown = DummyMetric()
        self.active_positions = DummyMetric()
        self.risk_rejections = DummyMetric()
        self.redis_connected = DummyMetric()
        self.kraken_ws_connected = DummyMetric()
        self.last_signal_age = DummyMetric()
        self.last_pnl_update_age = DummyMetric()
        self.uptime = DummyMetric()
        self.engine_healthy = DummyMetric()
        self.engine_info = DummyMetric()
        self.errors_total = DummyMetric()
        self.registry = None


# =============================================================================
# HTTP SERVER
# =============================================================================

class ObservabilityHandler(BaseHTTPRequestHandler):
    """HTTP handler for /health and /metrics endpoints."""

    observability: Optional['EngineObservability'] = None

    def log_message(self, format, *args):
        """Use logger instead of print."""
        logger.debug(f"{self.address_string()} - {format % args}")

    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/metrics':
            self.handle_metrics()
        elif self.path == '/health':
            self.handle_health()
        elif self.path == '/readiness':
            self.handle_readiness()
        elif self.path == '/liveness':
            self.handle_liveness()
        else:
            self.send_error(404, "Not Found")

    def handle_metrics(self):
        """Handle /metrics endpoint (Prometheus format)."""
        if not PROMETHEUS_AVAILABLE or self.observability is None:
            self.send_response(503)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Prometheus client not available")
            return

        try:
            # Update dynamic metrics
            self.observability._update_metrics()

            # Generate Prometheus format
            output = generate_latest(self.observability.metrics.registry)

            self.send_response(200)
            self.send_header('Content-Type', CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(output)

        except Exception as e:
            logger.error(f"Error generating metrics: {e}")
            self.send_error(500, str(e))

    def handle_health(self):
        """Handle /health endpoint (JSON)."""
        if self.observability is None:
            self.send_error(503, "Observability not initialized")
            return

        import json
        health = self.observability.health.get_overall_health()

        status_code = 200 if health["status"] == "healthy" else 503

        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('X-Health-Source', 'crypto-ai-bot')
        self.end_headers()

        self.wfile.write(json.dumps(health, indent=2).encode())

    def handle_readiness(self):
        """Handle /readiness endpoint."""
        if self.observability is None:
            self.send_error(503, "Not ready")
            return

        health = self.observability.health.get_overall_health()
        redis_ok = health["components"].get("redis", {}).get("healthy", False)
        ws_ok = health["components"].get("kraken_ws", {}).get("healthy", False)

        ready = redis_ok  # At minimum need Redis

        status_code = 200 if ready else 503

        self.send_response(status_code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"ready" if ready else b"not ready")

    def handle_liveness(self):
        """Handle /liveness endpoint."""
        if self.observability is None:
            self.send_error(503, "Not alive")
            return

        # Liveness just checks if the process is running
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"alive")


# =============================================================================
# ENGINE OBSERVABILITY (Main Class)
# =============================================================================

class EngineObservability:
    """
    Unified observability for crypto-ai-bot engine.

    Provides:
    - Prometheus metrics
    - Health checks
    - HTTP server for /metrics and /health
    """

    def __init__(self, config: Optional[ObservabilityConfig] = None):
        """
        Initialize engine observability.

        Args:
            config: Observability configuration (defaults from env vars)
        """
        self.config = config or ObservabilityConfig()
        self.metrics = EngineMetrics()
        self.health = HealthAggregator(self.config)

        self._start_time = time.time()
        self._last_signal_ts: float = 0.0
        self._last_pnl_ts: float = 0.0
        self._active_positions: Dict[str, int] = {}

        self._http_server: Optional[HTTPServer] = None
        self._http_thread: Optional[Thread] = None
        self._running = False

        # Set info
        self.metrics.engine_info.info({
            'mode': self.config.mode,
            'version': '1.0.0',
        })

        logger.info(f"EngineObservability initialized (enabled={self.config.enabled})")

    def start(self):
        """Start the HTTP server for /metrics and /health."""
        if not self.config.enabled:
            logger.info("Observability HTTP server disabled")
            return

        if self._running:
            logger.warning("Observability server already running")
            return

        try:
            # Set reference for handler
            ObservabilityHandler.observability = self

            # Create HTTP server
            server_address = (self.config.host, self.config.port)
            self._http_server = HTTPServer(server_address, ObservabilityHandler)

            # Start in background thread
            self._http_thread = Thread(
                target=self._http_server.serve_forever,
                daemon=True,
                name="observability_server"
            )
            self._http_thread.start()
            self._running = True

            logger.info(
                f"Observability server started: "
                f"http://{self.config.host}:{self.config.port}/metrics, "
                f"http://{self.config.host}:{self.config.port}/health"
            )

        except Exception as e:
            logger.error(f"Failed to start observability server: {e}")

    def stop(self):
        """Stop the HTTP server."""
        self._running = False

        if self._http_server:
            self._http_server.shutdown()
            self._http_server = None

        if self._http_thread and self._http_thread.is_alive():
            self._http_thread.join(timeout=5)
            self._http_thread = None

        logger.info("Observability server stopped")

    def _update_metrics(self):
        """Update dynamic metrics before scrape."""
        # Uptime
        self.metrics.uptime.set(time.time() - self._start_time)

        # Signal age
        if self._last_signal_ts > 0:
            self.metrics.last_signal_age.set(time.time() - self._last_signal_ts)

        # PnL age
        if self._last_pnl_ts > 0:
            self.metrics.last_pnl_update_age.set(time.time() - self._last_pnl_ts)

        # Health status
        self.metrics.engine_healthy.set(1 if self.health.is_healthy() else 0)

    # =========================================================================
    # PUBLIC API - Recording Metrics
    # =========================================================================

    def record_signal_published(self, pair: str, strategy: str, side: str):
        """
        Record a signal was published.

        Args:
            pair: Trading pair (e.g., "BTC/USD")
            strategy: Strategy name (e.g., "SCALPER")
            side: Trade direction ("LONG" or "SHORT")
        """
        self.metrics.signals_published.labels(
            pair=pair, strategy=strategy, side=side
        ).inc()

        self._last_signal_ts = time.time()
        self.health.record_signal()

    def record_signal_latency(self, latency_ms: float):
        """
        Record signal generation latency.

        Args:
            latency_ms: Latency in milliseconds
        """
        self.metrics.signal_latency.observe(latency_ms)

    def set_drawdown(self, drawdown_pct: float):
        """
        Set current drawdown percentage.

        Args:
            drawdown_pct: Current drawdown as percentage (e.g., 2.5 for 2.5%)
        """
        self.metrics.current_drawdown.set(drawdown_pct)

    def set_active_positions(self, positions: Dict[str, int]):
        """
        Set active positions by pair.

        Args:
            positions: Dict of {pair: count}
        """
        self._active_positions = positions

        for pair, count in positions.items():
            self.metrics.active_positions.labels(pair=pair).set(count)

    def record_risk_rejection(self, pair: str, reason: str):
        """
        Record a risk filter rejection.

        Args:
            pair: Trading pair
            reason: Rejection reason (e.g., "spread_too_wide", "volume_low")
        """
        self.metrics.risk_rejections.labels(pair=pair, reason=reason).inc()

    def record_error(self, component: str):
        """
        Record an error in a component.

        Args:
            component: Component name (e.g., "redis", "kraken_ws", "signal_gen")
        """
        self.metrics.errors_total.labels(component=component).inc()

    # =========================================================================
    # PUBLIC API - Health Updates
    # =========================================================================

    def set_redis_connected(self, connected: bool, message: str = ""):
        """
        Update Redis connection status.

        Args:
            connected: Whether connected
            message: Optional status message
        """
        self.metrics.redis_connected.set(1 if connected else 0)
        self.health.update_component("redis", connected, message)

    def set_kraken_ws_connected(self, pair: str, connected: bool, message: str = ""):
        """
        Update Kraken WebSocket connection status for a pair.

        Args:
            pair: Trading pair
            connected: Whether connected
            message: Optional status message
        """
        self.metrics.kraken_ws_connected.labels(pair=pair).set(1 if connected else 0)

        # Aggregate WS health
        ws_ok = connected  # Simplified; could track all pairs
        self.health.update_component("kraken_ws", ws_ok, message, pair=pair)

    def record_pnl_update(self):
        """Record that PnL was updated."""
        self._last_pnl_ts = time.time()
        self.health.record_pnl_update()

    # =========================================================================
    # PUBLIC API - Get Status
    # =========================================================================

    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status."""
        return self.health.get_overall_health()

    def is_healthy(self) -> bool:
        """Check if engine is healthy."""
        return self.health.is_healthy()


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_observability: Optional[EngineObservability] = None
_obs_lock = Lock()


def get_observability() -> EngineObservability:
    """Get or create the global observability instance."""
    global _observability

    with _obs_lock:
        if _observability is None:
            _observability = EngineObservability()
        return _observability


def start_observability():
    """Start the global observability instance."""
    obs = get_observability()
    obs.start()
    return obs


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def record_signal(pair: str, strategy: str, side: str):
    """Record a signal was published."""
    get_observability().record_signal_published(pair, strategy, side)


def record_latency(latency_ms: float):
    """Record signal generation latency."""
    get_observability().record_signal_latency(latency_ms)


def record_rejection(pair: str, reason: str):
    """Record a risk rejection."""
    get_observability().record_risk_rejection(pair, reason)


def set_redis_status(connected: bool):
    """Update Redis status."""
    get_observability().set_redis_connected(connected)


def set_ws_status(pair: str, connected: bool):
    """Update WebSocket status for pair."""
    get_observability().set_kraken_ws_connected(pair, connected)


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "EngineObservability",
    "ObservabilityConfig",
    "EngineMetrics",
    "HealthAggregator",
    "get_observability",
    "start_observability",
    "record_signal",
    "record_latency",
    "record_rejection",
    "set_redis_status",
    "set_ws_status",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    import time

    print("=" * 60)
    print("ENGINE OBSERVABILITY SELF-CHECK")
    print("=" * 60)

    # Create observability
    obs = EngineObservability(ObservabilityConfig(enabled=True, port=9108))

    # Start server
    obs.start()

    # Record some metrics
    print("\nRecording metrics...")
    obs.record_signal_published("BTC/USD", "SCALPER", "LONG")
    obs.record_signal_published("ETH/USD", "TREND", "SHORT")
    obs.record_signal_latency(75.5)
    obs.record_signal_latency(120.0)
    obs.set_drawdown(1.5)
    obs.set_active_positions({"BTC/USD": 1, "ETH/USD": 2})
    obs.record_risk_rejection("SOL/USD", "spread_too_wide")
    obs.set_redis_connected(True, "Connected to Redis Cloud")
    obs.set_kraken_ws_connected("BTC/USD", True)

    print("\nHealth status:")
    health = obs.get_health_status()
    import json
    print(json.dumps(health, indent=2))

    print(f"\nMetrics available at: http://localhost:{obs.config.port}/metrics")
    print(f"Health available at: http://localhost:{obs.config.port}/health")
    print("\nPress Ctrl+C to stop...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        obs.stop()
        print("\nStopped.")
