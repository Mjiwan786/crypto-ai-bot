#!/usr/bin/env python3
"""
Comprehensive Prometheus Metrics Exporter
==========================================

Exposes comprehensive metrics for signal publishing pipeline:
- signals_published_total
- signals_dropped_total
- publisher_backpressure_events_total
- event_age_ms_gauge
- ingest_lag_ms_gauge
- heartbeats_total
- last_signal_age_ms

Serves metrics at /metrics endpoint via HTTP.

Usage:
    # Start metrics server
    python agents/monitoring/metrics_exporter.py

    # Custom port
    METRICS_PORT=9090 python agents/monitoring/metrics_exporter.py

    # Query metrics
    curl http://localhost:9108/metrics
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional
from prometheus_client import Counter, Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import start_http_server
import json

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ComprehensiveMetricsExporter:
    """
    Comprehensive Prometheus metrics exporter for signal publishing pipeline.

    Exposes:
    - Counters: signals_published_total, signals_dropped_total,
                publisher_backpressure_events_total, heartbeats_total
    - Gauges: event_age_ms_gauge, ingest_lag_ms_gauge, last_signal_age_ms
    """

    def __init__(
        self,
        port: int = 9108,
        redis_client: Optional[RedisCloudClient] = None,
        registry: Optional[CollectorRegistry] = None,
    ):
        """
        Initialize metrics exporter.

        Args:
            port: HTTP port for metrics server
            redis_client: Optional Redis client for stream monitoring
            registry: Optional Prometheus registry
        """
        self.port = port
        self.redis = redis_client
        self.registry = registry or CollectorRegistry()

        # Initialize metrics
        self._init_metrics()

        # Tracking
        self._last_heartbeat_time = 0
        self._running = False

        logger.info(f"MetricsExporter initialized on port {port}")

    def _init_metrics(self):
        """Initialize all Prometheus metrics"""

        # =====================================================================
        # COUNTERS
        # =====================================================================

        # Signals published (successfully sent to Redis)
        self.signals_published_total = Counter(
            "signals_published_total",
            "Total number of signals successfully published to Redis",
            ["symbol", "timeframe", "side"],
            registry=self.registry,
        )

        # Signals dropped (validation failures, errors)
        self.signals_dropped_total = Counter(
            "signals_dropped_total",
            "Total number of signals dropped due to validation or errors",
            ["reason"],  # validation_error, publish_error, etc.
            registry=self.registry,
        )

        # Publisher backpressure events (queue full, shedding)
        self.publisher_backpressure_events_total = Counter(
            "publisher_backpressure_events_total",
            "Total number of backpressure events (queue full, signal shedding)",
            registry=self.registry,
        )

        # Heartbeats received
        self.heartbeats_total = Counter(
            "heartbeats_total",
            "Total number of heartbeats received from signal queue",
            registry=self.registry,
        )

        # =====================================================================
        # GAUGES
        # =====================================================================

        # Event age (now - ts_exchange)
        self.event_age_ms_gauge = Gauge(
            "event_age_ms",
            "Age of exchange event in milliseconds (now - ts_exchange)",
            ["symbol", "timeframe"],
            registry=self.registry,
        )

        # Ingest lag (now - ts_server)
        self.ingest_lag_ms_gauge = Gauge(
            "ingest_lag_ms",
            "Processing lag in milliseconds (now - ts_server)",
            ["symbol", "timeframe"],
            registry=self.registry,
        )

        # Last signal age (time since last signal)
        self.last_signal_age_ms = Gauge(
            "last_signal_age_ms",
            "Time in milliseconds since last signal was published",
            registry=self.registry,
        )

        # Additional useful gauges
        self.queue_depth = Gauge(
            "signal_queue_depth",
            "Current signal queue depth",
            registry=self.registry,
        )

        self.queue_utilization_pct = Gauge(
            "signal_queue_utilization_pct",
            "Signal queue utilization percentage",
            registry=self.registry,
        )

        self.signals_shed_total = Counter(
            "signals_shed_total",
            "Total number of signals shed due to queue backpressure",
            registry=self.registry,
        )

        logger.info("Initialized Prometheus metrics")

    def record_signal_published(
        self,
        symbol: str,
        timeframe: str,
        side: str,
        event_age_ms: Optional[int] = None,
        ingest_lag_ms: Optional[int] = None,
    ):
        """
        Record a published signal.

        Args:
            symbol: Trading pair (e.g. "BTC/USD")
            timeframe: Timeframe (e.g. "15s")
            side: Signal side ("long" or "short")
            event_age_ms: Optional event age
            ingest_lag_ms: Optional ingest lag
        """
        symbol_label = symbol.replace("/", "_")

        # Increment counter
        self.signals_published_total.labels(
            symbol=symbol_label,
            timeframe=timeframe,
            side=side,
        ).inc()

        # Update freshness gauges
        if event_age_ms is not None:
            self.event_age_ms_gauge.labels(
                symbol=symbol_label,
                timeframe=timeframe,
            ).set(event_age_ms)

        if ingest_lag_ms is not None:
            self.ingest_lag_ms_gauge.labels(
                symbol=symbol_label,
                timeframe=timeframe,
            ).set(ingest_lag_ms)

        # Update last signal age
        self.last_signal_age_ms.set(0)  # Just published, age is 0

    def record_signal_dropped(self, reason: str):
        """
        Record a dropped signal.

        Args:
            reason: Drop reason (e.g. "validation_error", "publish_error")
        """
        self.signals_dropped_total.labels(reason=reason).inc()

    def record_backpressure_event(self):
        """Record a backpressure event (queue full)"""
        self.publisher_backpressure_events_total.inc()

    def record_heartbeat(
        self,
        queue_depth: Optional[int] = None,
        queue_capacity: Optional[int] = None,
        signals_shed: Optional[int] = None,
    ):
        """
        Record a heartbeat.

        Args:
            queue_depth: Current queue depth
            queue_capacity: Queue capacity
            signals_shed: Total signals shed
        """
        self.heartbeats_total.inc()
        self._last_heartbeat_time = time.time()

        # Update queue metrics
        if queue_depth is not None:
            self.queue_depth.set(queue_depth)

        if queue_capacity is not None and queue_depth is not None:
            utilization = (queue_depth / queue_capacity) * 100
            self.queue_utilization_pct.set(utilization)

        if signals_shed is not None:
            # Note: This is a counter, but we're using it as a gauge from heartbeat
            # We'll set it to the total from the heartbeat
            current = self.signals_shed_total._value.get()
            if signals_shed > current:
                self.signals_shed_total.inc(signals_shed - current)

    async def monitor_redis_streams(self):
        """Monitor Redis streams for signals and heartbeats"""
        if not self.redis:
            logger.warning("Redis client not provided, skipping stream monitoring")
            return

        logger.info("Starting Redis stream monitoring")

        # Monitor heartbeat stream
        heartbeat_stream = "metrics:scalper"
        last_heartbeat_id = "$"  # Start from latest

        while self._running:
            try:
                # Read heartbeats
                messages = await self.redis.xread(
                    {heartbeat_stream: last_heartbeat_id},
                    count=10,
                    block=1000,  # 1 second timeout
                )

                if messages:
                    for stream, msgs in messages:
                        for msg_id, msg_data in msgs:
                            last_heartbeat_id = msg_id

                            # Check if this is a heartbeat
                            if msg_data.get("kind") == "heartbeat":
                                await self._process_heartbeat(msg_data)

                # Update last signal age
                if self._last_heartbeat_time > 0:
                    age_ms = int((time.time() - self._last_heartbeat_time) * 1000)
                    self.last_signal_age_ms.set(age_ms)

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Redis monitoring: {e}", exc_info=True)
                await asyncio.sleep(5)

        logger.info("Stopped Redis stream monitoring")

    async def _process_heartbeat(self, heartbeat_data: Dict):
        """Process a heartbeat message"""
        try:
            queue_depth = int(heartbeat_data.get("queue_depth", 0))
            signals_published = int(heartbeat_data.get("signals_published", 0))
            signals_shed = int(heartbeat_data.get("signals_shed", 0))

            # Record heartbeat
            self.record_heartbeat(
                queue_depth=queue_depth,
                queue_capacity=1000,  # Default capacity
                signals_shed=signals_shed,
            )

            # Update last signal time
            last_signal_ms = int(heartbeat_data.get("last_signal_ms", 0))
            if last_signal_ms > 0:
                now_ms = int(time.time() * 1000)
                age_ms = now_ms - last_signal_ms
                self.last_signal_age_ms.set(age_ms)

            logger.debug(
                f"Heartbeat processed: queue={queue_depth}, "
                f"published={signals_published}, shed={signals_shed}"
            )

        except Exception as e:
            logger.error(f"Error processing heartbeat: {e}")

    async def start(self):
        """Start metrics server and monitoring"""
        self._running = True

        # Start Prometheus HTTP server
        logger.info(f"Starting Prometheus HTTP server on port {self.port}")
        start_http_server(self.port, registry=self.registry)
        logger.info(f"Metrics available at http://localhost:{self.port}/metrics")

        # Start Redis monitoring if client provided
        if self.redis:
            logger.info("Starting Redis stream monitoring")
            await self.monitor_redis_streams()
        else:
            logger.info("Redis client not provided, metrics will be updated externally")

            # Keep running to serve metrics
            while self._running:
                await asyncio.sleep(1)

    def stop(self):
        """Stop metrics server"""
        self._running = False
        logger.info("Metrics exporter stopped")

    def get_metrics(self) -> bytes:
        """Get current metrics in Prometheus format"""
        return generate_latest(self.registry)


# Singleton instance for easy access
_exporter_instance: Optional[ComprehensiveMetricsExporter] = None


def get_metrics_exporter() -> ComprehensiveMetricsExporter:
    """Get singleton metrics exporter instance"""
    global _exporter_instance
    if _exporter_instance is None:
        raise RuntimeError("Metrics exporter not initialized. Call init_metrics_exporter() first.")
    return _exporter_instance


def init_metrics_exporter(
    port: int = 9108,
    redis_client: Optional[RedisCloudClient] = None,
) -> ComprehensiveMetricsExporter:
    """
    Initialize global metrics exporter.

    Args:
        port: HTTP port for metrics server
        redis_client: Optional Redis client for stream monitoring

    Returns:
        ComprehensiveMetricsExporter instance
    """
    global _exporter_instance
    if _exporter_instance is None:
        _exporter_instance = ComprehensiveMetricsExporter(
            port=port,
            redis_client=redis_client,
        )
    return _exporter_instance


async def main():
    """Main entry point for standalone metrics server"""
    print("=" * 80)
    print("         COMPREHENSIVE METRICS EXPORTER")
    print("=" * 80)

    # Load environment
    env_file = project_root / ".env.paper"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"\n[OK] Loaded environment from: {env_file}")

    # Configuration
    port = int(os.getenv("METRICS_PORT", "9108"))

    # Redis connection (optional)
    redis_url = os.getenv("REDIS_URL")
    redis_ca_cert = os.getenv("REDIS_CA_CERT", "config/certs/redis_ca.pem")

    redis_client = None
    if redis_url:
        print(f"\n[1/2] Connecting to Redis...")
        redis_config = RedisCloudConfig(
            url=redis_url,
            ca_cert_path=redis_ca_cert,
        )
        redis_client = RedisCloudClient(redis_config)

        try:
            await redis_client.connect()
            print("      [OK] Connected to Redis Cloud")
        except Exception as e:
            print(f"      [WARN] Failed to connect to Redis: {e}")
            print("      [INFO] Starting without Redis monitoring")
            redis_client = None

    # Initialize exporter
    print(f"\n[2/2] Starting metrics exporter on port {port}...")
    exporter = init_metrics_exporter(
        port=port,
        redis_client=redis_client,
    )

    print(f"\n{'=' * 80}")
    print(f"Metrics available at: http://localhost:{port}/metrics")
    print(f"{'=' * 80}\n")

    try:
        await exporter.start()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        exporter.stop()
        if redis_client:
            await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
