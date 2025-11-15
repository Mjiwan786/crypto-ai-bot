#!/usr/bin/env python3
"""
Prometheus Freshness Metrics Exporter
======================================

Exposes freshness and clock-drift metrics for Prometheus scraping.

Metrics Exposed:
- signal_event_age_ms: Age of exchange event (gauge per symbol/timeframe)
- signal_ingest_lag_ms: Processing lag (gauge per symbol/timeframe)
- signal_clock_drift_ms: Clock drift between exchange and server (gauge)
- signal_clock_drift_warnings_total: Count of clock drift warnings (counter)
- signals_published_total: Total signals published (counter per symbol)
- signals_rejected_total: Total signals rejected (counter)

Usage:
    exporter = FreshnessMetricsExporter(port=9108)
    await exporter.start()

    # Update metrics
    exporter.update_freshness_metrics(
        symbol="BTC/USD",
        timeframe="15s",
        event_age_ms=1000,
        ingest_lag_ms=50,
        exchange_server_delta_ms=200,
    )

    # Check clock drift
    if abs(exchange_server_delta_ms) > 2000:
        exporter.record_clock_drift_warning(
            symbol="BTC/USD",
            drift_ms=exchange_server_delta_ms,
        )
"""

import asyncio
import logging
import time
from typing import Dict, Optional
from prometheus_client import Counter, Gauge, Histogram, start_http_server, REGISTRY
from prometheus_client.core import CollectorRegistry

logger = logging.getLogger(__name__)


class FreshnessMetricsExporter:
    """
    Prometheus exporter for signal freshness and clock drift metrics.

    Exposes HTTP endpoint on /metrics for Prometheus scraping.
    """

    def __init__(self, port: int = 9108, registry: Optional[CollectorRegistry] = None):
        """
        Initialize Prometheus exporter.

        Args:
            port: HTTP port for /metrics endpoint (default: 9108)
            registry: Custom registry (default: global REGISTRY)
        """
        self.port = port
        self.registry = registry or REGISTRY
        self.started = False

        # Define metrics

        # Freshness gauges (per symbol/timeframe)
        self.event_age_gauge = Gauge(
            "signal_event_age_ms",
            "Age of exchange event in milliseconds (now - ts_exchange)",
            ["symbol", "timeframe"],
            registry=self.registry,
        )

        self.ingest_lag_gauge = Gauge(
            "signal_ingest_lag_ms",
            "Processing lag in milliseconds (now - ts_server)",
            ["symbol", "timeframe"],
            registry=self.registry,
        )

        self.clock_drift_gauge = Gauge(
            "signal_clock_drift_ms",
            "Clock drift between exchange and server in milliseconds (ts_server - ts_exchange)",
            ["symbol", "timeframe"],
            registry=self.registry,
        )

        # Clock drift warnings counter
        self.clock_drift_warnings = Counter(
            "signal_clock_drift_warnings_total",
            "Total number of clock drift warnings (>2s drift)",
            ["symbol"],
            registry=self.registry,
        )

        # Signal counters
        self.signals_published = Counter(
            "signals_published_total",
            "Total signals published",
            ["symbol", "timeframe"],
            registry=self.registry,
        )

        self.signals_rejected = Counter(
            "signals_rejected_total",
            "Total signals rejected due to validation failures",
            registry=self.registry,
        )

        # Latency histogram
        self.signal_latency = Histogram(
            "signal_processing_latency_seconds",
            "Signal processing latency in seconds",
            ["symbol", "timeframe"],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
            registry=self.registry,
        )

        logger.info(f"FreshnessMetricsExporter initialized (port={port})")

    async def start(self) -> None:
        """Start Prometheus HTTP server"""
        if self.started:
            logger.warning("Prometheus exporter already started")
            return

        try:
            start_http_server(self.port, registry=self.registry)
            self.started = True
            logger.info(f"Prometheus metrics endpoint started on http://localhost:{self.port}/metrics")
        except Exception as e:
            logger.error(f"Failed to start Prometheus exporter: {e}")
            raise

    def update_freshness_metrics(
        self,
        symbol: str,
        timeframe: str,
        event_age_ms: int,
        ingest_lag_ms: int,
        exchange_server_delta_ms: int,
    ) -> None:
        """
        Update freshness metrics for a signal.

        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            timeframe: Timeframe (e.g., "15s")
            event_age_ms: Age of exchange event (now - ts_exchange)
            ingest_lag_ms: Processing lag (now - ts_server)
            exchange_server_delta_ms: Clock drift (ts_server - ts_exchange)
        """
        # Normalize symbol for Prometheus labels (replace / with _)
        symbol_label = symbol.replace("/", "_")

        # Update gauges
        self.event_age_gauge.labels(symbol=symbol_label, timeframe=timeframe).set(event_age_ms)
        self.ingest_lag_gauge.labels(symbol=symbol_label, timeframe=timeframe).set(ingest_lag_ms)
        self.clock_drift_gauge.labels(symbol=symbol_label, timeframe=timeframe).set(exchange_server_delta_ms)

    def record_clock_drift_warning(self, symbol: str, drift_ms: int) -> None:
        """
        Record a clock drift warning.

        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            drift_ms: Clock drift in milliseconds
        """
        symbol_label = symbol.replace("/", "_")
        self.clock_drift_warnings.labels(symbol=symbol_label).inc()
        logger.warning(
            f"[CLOCK DRIFT WARNING] {symbol}: {drift_ms}ms drift detected (threshold: 2000ms)"
        )

    def record_signal_published(self, symbol: str, timeframe: str) -> None:
        """
        Record a successful signal publication.

        Args:
            symbol: Trading pair
            timeframe: Timeframe
        """
        symbol_label = symbol.replace("/", "_")
        self.signals_published.labels(symbol=symbol_label, timeframe=timeframe).inc()

    def record_signal_rejected(self) -> None:
        """Record a rejected signal"""
        self.signals_rejected.inc()

    def record_processing_latency(self, symbol: str, timeframe: str, latency_seconds: float) -> None:
        """
        Record signal processing latency.

        Args:
            symbol: Trading pair
            timeframe: Timeframe
            latency_seconds: Processing latency in seconds
        """
        symbol_label = symbol.replace("/", "_")
        self.signal_latency.labels(symbol=symbol_label, timeframe=timeframe).observe(latency_seconds)

    def get_metrics_summary(self) -> Dict:
        """
        Get current metrics summary (for debugging/logging).

        Returns:
            Dictionary with metric counts
        """
        return {
            "exporter_port": self.port,
            "exporter_started": self.started,
            "metrics_endpoint": f"http://localhost:{self.port}/metrics" if self.started else "not started",
        }


# =============================================================================
# Self-Test
# =============================================================================

async def test_prometheus_exporter():
    """Test Prometheus exporter"""
    print("=" * 80)
    print("           PROMETHEUS FRESHNESS EXPORTER TEST")
    print("=" * 80)

    # Create custom registry for testing (to avoid conflicts)
    from prometheus_client import CollectorRegistry
    test_registry = CollectorRegistry()

    # Initialize exporter
    print("\n1. Initializing exporter...")
    exporter = FreshnessMetricsExporter(port=9109, registry=test_registry)
    print("   [OK] Exporter initialized")

    # Start HTTP server
    print("\n2. Starting HTTP server...")
    await exporter.start()
    print(f"   [OK] HTTP server started on port 9109")

    # Update metrics
    print("\n3. Updating freshness metrics...")
    exporter.update_freshness_metrics(
        symbol="BTC/USD",
        timeframe="15s",
        event_age_ms=1500,
        ingest_lag_ms=50,
        exchange_server_delta_ms=200,
    )
    print("   [OK] BTC/USD metrics updated: event_age=1500ms, ingest_lag=50ms, drift=200ms")

    exporter.update_freshness_metrics(
        symbol="ETH/USD",
        timeframe="15s",
        event_age_ms=2000,
        ingest_lag_ms=100,
        exchange_server_delta_ms=150,
    )
    print("   [OK] ETH/USD metrics updated: event_age=2000ms, ingest_lag=100ms, drift=150ms")

    # Record signal publications
    print("\n4. Recording signal publications...")
    exporter.record_signal_published("BTC/USD", "15s")
    exporter.record_signal_published("ETH/USD", "15s")
    exporter.record_signal_published("BTC/USD", "1m")
    print("   [OK] 3 signals published recorded")

    # Record rejections
    print("\n5. Recording signal rejections...")
    exporter.record_signal_rejected()
    exporter.record_signal_rejected()
    print("   [OK] 2 signals rejected recorded")

    # Record clock drift warning
    print("\n6. Recording clock drift warning...")
    exporter.record_clock_drift_warning("BTC/USD", drift_ms=3000)
    print("   [OK] Clock drift warning recorded (3000ms)")

    # Record latency
    print("\n7. Recording processing latency...")
    exporter.record_processing_latency("BTC/USD", "15s", 0.005)  # 5ms
    exporter.record_processing_latency("ETH/USD", "15s", 0.010)  # 10ms
    print("   [OK] Processing latency recorded")

    # Get summary
    print("\n8. Getting metrics summary...")
    summary = exporter.get_metrics_summary()
    print(f"   [OK] Metrics endpoint: {summary['metrics_endpoint']}")
    print(f"   [OK] Exporter started: {summary['exporter_started']}")

    # Show how to access metrics
    print("\n9. Metrics available at:")
    print(f"   curl http://localhost:9109/metrics")
    print("   (Prometheus can scrape this endpoint)")

    print("\n" + "=" * 80)
    print("[PASS] All tests PASSED")
    print("=" * 80)
    print("\nNote: HTTP server is running. Press Ctrl+C to stop.")
    print("You can test the endpoint with: curl http://localhost:9109/metrics")

    # Keep running for testing
    try:
        await asyncio.sleep(300)  # Run for 5 minutes
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_prometheus_exporter())
