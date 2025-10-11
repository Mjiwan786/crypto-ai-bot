# agents/scalper/monitoring/latency.py
"""
Comprehensive latency monitoring for scalping operations.
Tracks all forms of latency that impact execution quality.
"""

import asyncio
import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ..config_loader import KrakenScalpingConfig
from ..infra.redis_bus import RedisBus


class LatencyType(Enum):
    """Types of latency measurements"""

    ORDER_PLACEMENT = "order_placement"  # Time to place order
    ORDER_FILL = "order_fill"  # Time from order to fill
    MARKET_DATA = "market_data"  # Market data feed latency
    API_RESPONSE = "api_response"  # API response time
    NETWORK_RTT = "network_rtt"  # Network round-trip time
    EXECUTION_CHAIN = "execution_chain"  # End-to-end execution latency
    DECISION_TO_ORDER = "decision_to_order"  # Decision to order placement
    WEBSOCKET_LATENCY = "websocket_latency"  # WebSocket message latency


@dataclass
class LatencyMeasurement:
    """Individual latency measurement"""

    measurement_type: LatencyType
    latency_ms: float
    timestamp: float = field(default_factory=time.time)
    source: str = "system"
    context: Dict[str, Any] = field(default_factory=dict)

    @property
    def latency_seconds(self) -> float:
        """Latency in seconds"""
        return self.latency_ms / 1000.0


@dataclass
class LatencyStats:
    """Statistical summary of latency measurements"""

    measurement_type: LatencyType
    count: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    std_dev_ms: float
    last_update: float = field(default_factory=time.time)

    def is_degraded(self, threshold_ms: float) -> bool:
        """Check if latency is degraded beyond threshold"""
        return self.p95_ms > threshold_ms


@dataclass
class LatencyAlert:
    """Latency alert event"""

    measurement_type: LatencyType
    current_value_ms: float
    threshold_ms: float
    severity: str  # "warning", "critical"
    message: str
    timestamp: float = field(default_factory=time.time)


class LatencyTracker:
    """Tracks latency for a specific measurement type"""

    def __init__(
        self,
        measurement_type: LatencyType,
        max_samples: int = 1000,
        alert_threshold_ms: float = 200.0,
        critical_threshold_ms: float = 500.0,
    ):
        self.measurement_type = measurement_type
        self.max_samples = max_samples
        self.alert_threshold_ms = alert_threshold_ms
        self.critical_threshold_ms = critical_threshold_ms

        # Storage
        self.measurements: deque[LatencyMeasurement] = deque(maxlen=max_samples)
        self.latency_values: deque[float] = deque(maxlen=max_samples)

        # Timing state
        self.active_timings: Dict[str, float] = {}

        # Alert state
        self.last_alert_time = 0.0
        self.alert_cooldown_seconds = 60.0

        self.logger = logging.getLogger(f"{__name__}.{measurement_type.value}")

    def start_timing(self, operation_id: str) -> None:
        """Start timing an operation"""
        self.active_timings[operation_id] = time.time()

    def end_timing(
        self, operation_id: str, context: Optional[Dict[str, Any]] = None
    ) -> Optional[LatencyMeasurement]:
        """End timing and record measurement"""
        start_time = self.active_timings.pop(operation_id, None)
        if start_time is None:
            self.logger.warning(f"No active timing for operation {operation_id}")
            return None

        latency_ms = (time.time() - start_time) * 1000.0
        return self.record_measurement(latency_ms, context or {})

    def record_measurement(
        self, latency_ms: float, context: Optional[Dict[str, Any]] = None
    ) -> LatencyMeasurement:
        """Record a latency measurement directly"""
        measurement = LatencyMeasurement(
            measurement_type=self.measurement_type,
            latency_ms=float(latency_ms),
            context=context or {},
        )

        self.measurements.append(measurement)
        self.latency_values.append(float(latency_ms))

        # Check for alerts (local logger-level alerts)
        self._check_alerts(float(latency_ms))

        return measurement

    def get_stats(self) -> Optional[LatencyStats]:
        """Get current statistics"""
        if not self.latency_values:
            return None

        values = list(self.latency_values)
        values.sort()

        count = len(values)
        mean_ms = statistics.mean(values)
        median_ms = statistics.median(values)
        min_ms = values[0]
        max_ms = values[-1]
        std_dev_ms = statistics.stdev(values) if count > 1 else 0.0

        # Percentiles (index clamped to range)
        p95_index = min(max(int(count * 0.95), 0), count - 1)
        p99_index = min(max(int(count * 0.99), 0), count - 1)
        p95_ms = values[p95_index]
        p99_ms = values[p99_index]

        return LatencyStats(
            measurement_type=self.measurement_type,
            count=count,
            mean_ms=mean_ms,
            median_ms=median_ms,
            p95_ms=p95_ms,
            p99_ms=p99_ms,
            min_ms=min_ms,
            max_ms=max_ms,
            std_dev_ms=std_dev_ms,
        )

    def _check_alerts(self, latency_ms: float) -> None:
        """Check if a single latency sample requires local alert logging"""
        current_time = time.time()

        # Rate limit alerts
        if current_time - self.last_alert_time < self.alert_cooldown_seconds:
            return

        severity: Optional[str] = None
        threshold = 0.0

        if latency_ms > self.critical_threshold_ms:
            severity = "critical"
            threshold = self.critical_threshold_ms
        elif latency_ms > self.alert_threshold_ms:
            severity = "warning"
            threshold = self.alert_threshold_ms

        if severity:
            self.last_alert_time = current_time
            self.logger.warning(
                f"Latency alert: {self.measurement_type.value} "
                f"{latency_ms:.1f}ms > {threshold}ms ({severity})"
            )


class LatencyMonitor:
    """
    Comprehensive latency monitoring system for scalping operations.

    Features:
    - Multi-dimensional latency tracking
    - Real-time alerting and degradation detection
    - Performance baseline establishment
    - Integration with circuit breakers
    """

    def __init__(
        self, config: KrakenScalpingConfig, redis_bus: RedisBus, agent_id: str = "kraken_scalper"
    ):
        self.config = config
        self.redis_bus = redis_bus
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

        # Latency trackers for different types
        self.trackers: Dict[LatencyType, LatencyTracker] = {}
        self._setup_trackers()

        # Performance baselines
        self.baselines: Dict[LatencyType, float] = {}
        self.baseline_window_hours = 24

        # Alert callbacks
        self.alert_callbacks: List[Callable[[LatencyAlert], None]] = []

        # Monitoring state
        self.monitoring_active = False
        self.last_health_check = 0.0

        # Performance degradation tracking
        self.degradation_events: List[Dict] = []

        # API operation id tracking to fix start/stop mismatch
        self._api_active_ops: Dict[str, str] = {}  # endpoint -> last operation_id

        self.logger.info("LatencyMonitor initialized")

    async def start(self) -> None:
        """Start latency monitoring"""
        self.logger.info("Starting LatencyMonitor...")

        # Setup subscriptions
        await self._setup_subscriptions()

        # Start monitoring loops
        self.monitoring_active = True
        asyncio.create_task(self._monitoring_loop())
        asyncio.create_task(self._health_check_loop())
        asyncio.create_task(self._baseline_update_loop())

        self.logger.info("LatencyMonitor started")

    async def stop(self) -> None:
        """Stop latency monitoring"""
        self.monitoring_active = False
        self.logger.info("LatencyMonitor stopped")

    def start_timing(self, measurement_type: LatencyType, operation_id: str) -> None:
        """Start timing an operation"""
        tracker = self.trackers.get(measurement_type)
        if tracker:
            tracker.start_timing(operation_id)

    def end_timing(
        self,
        measurement_type: LatencyType,
        operation_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[LatencyMeasurement]:
        """End timing and record measurement"""
        tracker = self.trackers.get(measurement_type)
        if tracker:
            return tracker.end_timing(operation_id, context)
        self.logger.warning(f"No tracker for measurement type {measurement_type}")
        return None

    def record_latency(
        self,
        measurement_type: LatencyType,
        latency_ms: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[LatencyMeasurement]:
        """Record a latency measurement directly"""
        tracker = self.trackers.get(measurement_type)
        if tracker:
            return tracker.record_measurement(latency_ms, context)
        self.logger.warning(f"No tracker for measurement type {measurement_type}")
        return None

    async def get_all_stats(self) -> Dict[LatencyType, Optional[LatencyStats]]:
        """Get statistics for all latency types"""
        return {
            latency_type: tracker.get_stats() for latency_type, tracker in self.trackers.items()
        }

    async def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary (JSON-friendly)"""
        all_stats = await self.get_all_stats()

        summary: Dict[str, Any] = {
            "overall_health": "good",
            "degraded_components": [],
            "critical_components": [],
            "stats_by_type": {},
            "baselines": {lt.value: v for lt, v in self.baselines.items()},
            "last_update": time.time(),
        }

        for latency_type, stats in all_stats.items():
            if not stats:
                continue

            type_name = latency_type.value
            summary["stats_by_type"][type_name] = {
                "mean_ms": stats.mean_ms,
                "p95_ms": stats.p95_ms,
                "p99_ms": stats.p99_ms,
                "count": stats.count,
            }

            # Check against baselines (use p95 as indicator)
            baseline = self.baselines.get(latency_type, stats.p95_ms * 1.5)

            if stats.p95_ms > baseline * 2:  # Critical degradation
                summary["critical_components"].append(type_name)
                summary["overall_health"] = "critical"
            elif stats.p95_ms > baseline * 1.5:  # Warning degradation
                summary["degraded_components"].append(type_name)
                if summary["overall_health"] == "good":
                    summary["overall_health"] = "degraded"

        return summary

    async def check_degradation(self) -> List[LatencyAlert]:
        """Check for latency degradation and return alerts"""
        alerts: List[LatencyAlert] = []

        for latency_type, tracker in self.trackers.items():
            stats = tracker.get_stats()
            if not stats:
                continue

            baseline = self.baselines.get(latency_type)
            if not baseline:
                continue

            # Check for degradation
            if stats.p95_ms > baseline * 2:
                alerts.append(
                    LatencyAlert(
                        measurement_type=latency_type,
                        current_value_ms=stats.p95_ms,
                        threshold_ms=baseline * 2,
                        severity="critical",
                        message=f"{latency_type.value} severely degraded: {stats.p95_ms:.1f}ms vs baseline {baseline:.1f}ms",
                    )
                )
            elif stats.p95_ms > baseline * 1.5:
                alerts.append(
                    LatencyAlert(
                        measurement_type=latency_type,
                        current_value_ms=stats.p95_ms,
                        threshold_ms=baseline * 1.5,
                        severity="warning",
                        message=f"{latency_type.value} degraded: {stats.p95_ms:.1f}ms vs baseline {baseline:.1f}ms",
                    )
                )

        return alerts

    def register_alert_callback(self, callback: Callable[[LatencyAlert], None]) -> None:
        """Register callback for latency alerts"""
        self.alert_callbacks.append(callback)

    # Context managers for easy timing

    def time_operation(self, measurement_type: LatencyType, operation_id: str = None):
        """Context manager for timing operations"""
        return LatencyContext(self, measurement_type, operation_id)

    # Convenience methods for common operations

    def time_order_placement(self, order_id: str) -> str:
        """Start timing order placement and return the operation id"""
        op_id = f"order_{order_id}"
        self.start_timing(LatencyType.ORDER_PLACEMENT, op_id)
        return op_id

    def complete_order_placement(
        self, order_id: str, context: Dict = None
    ) -> Optional[LatencyMeasurement]:
        """Complete order placement timing"""
        return self.end_timing(LatencyType.ORDER_PLACEMENT, f"order_{order_id}", context)

    def time_api_call(self, api_endpoint: str) -> str:
        """
        Start timing an API call and return the operation id.

        NOTE: Always pass the returned operation_id to complete_api_call()
        to avoid mismatches under concurrency.
        """
        operation_id = f"api_{api_endpoint}_{time.time():.6f}"
        self._api_active_ops[api_endpoint] = operation_id
        self.start_timing(LatencyType.API_RESPONSE, operation_id)
        return operation_id

    def complete_api_call(
        self, api_endpoint: str, operation_id: Optional[str] = None, context: Dict = None
    ) -> Optional[LatencyMeasurement]:
        """
        Complete API call timing. Prefer passing the exact operation_id
        returned by time_api_call(). If omitted, will use the last seen
        operation id for the endpoint (best-effort fallback).
        """
        op_id = operation_id or self._api_active_ops.pop(api_endpoint, None)
        if not op_id:
            self.logger.warning(f"No matching API timing found for endpoint '{api_endpoint}'")
            return None
        return self.end_timing(LatencyType.API_RESPONSE, op_id, context)

    # Private methods

    def _setup_trackers(self) -> None:
        """Setup latency trackers for different measurement types"""

        # Get thresholds from config or use defaults
        default_thresholds = {
            LatencyType.ORDER_PLACEMENT: (100.0, 300.0),  # 100ms warning, 300ms critical
            LatencyType.ORDER_FILL: (500.0, 2000.0),  # 500ms warning, 2s critical
            LatencyType.MARKET_DATA: (50.0, 200.0),  # 50ms warning, 200ms critical
            LatencyType.API_RESPONSE: (200.0, 1000.0),  # 200ms warning, 1s critical
            LatencyType.NETWORK_RTT: (20.0, 100.0),  # 20ms warning, 100ms critical
            LatencyType.EXECUTION_CHAIN: (300.0, 1000.0),  # 300ms warning, 1s critical
            LatencyType.DECISION_TO_ORDER: (50.0, 200.0),  # 50ms warning, 200ms critical
            LatencyType.WEBSOCKET_LATENCY: (30.0, 150.0),  # 30ms warning, 150ms critical
        }

        for latency_type, (warning_ms, critical_ms) in default_thresholds.items():
            self.trackers[latency_type] = LatencyTracker(
                measurement_type=latency_type,
                max_samples=1000,
                alert_threshold_ms=warning_ms,
                critical_threshold_ms=critical_ms,
            )

    async def _setup_subscriptions(self) -> None:
        """Setup Redis subscriptions for latency data"""
        try:
            # Subscribe to order events for latency tracking
            await self.redis_bus.subscribe(
                f"orders:placed:{self.agent_id}", self._handle_order_placed
            )

            await self.redis_bus.subscribe(
                f"orders:filled:{self.agent_id}", self._handle_order_filled
            )

            # Subscribe to market data latency
            await self.redis_bus.subscribe(
                f"market:latency:{self.agent_id}", self._handle_market_data_latency
            )

        except Exception as e:
            self.logger.error(f"Error setting up subscriptions: {e}")

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop"""
        while self.monitoring_active:
            try:
                # Check for latency degradation
                alerts = await self.check_degradation()
                for alert in alerts:
                    await self._handle_alert(alert)

                # Broadcast performance summary
                summary = await self.get_performance_summary()
                await self.redis_bus.publish(f"latency:summary:{self.agent_id}", summary)

                await asyncio.sleep(30)  # Check every 30 seconds

            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)

    async def _health_check_loop(self) -> None:
        """Health check loop for system responsiveness"""
        while self.monitoring_active:
            try:
                # Perform network RTT check
                await self._check_network_latency()

                # Check API responsiveness
                await self._check_api_responsiveness()

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                self.logger.error(f"Error in health check loop: {e}")
                await asyncio.sleep(120)

    async def _baseline_update_loop(self) -> None:
        """Update performance baselines periodically"""
        while self.monitoring_active:
            try:
                await self._update_baselines()
                await asyncio.sleep(3600)  # Update every hour

            except Exception as e:
                self.logger.error(f"Error updating baselines: {e}")
                await asyncio.sleep(3600)

    async def _check_network_latency(self) -> None:
        """Check network latency to exchange"""
        try:
            # Simple ping test (placeholder)
            start_time = time.time()
            await asyncio.sleep(0.01)  # Simulate ~10ms latency
            latency_ms = (time.time() - start_time) * 1000.0
            self.record_latency(LatencyType.NETWORK_RTT, latency_ms)
        except Exception as e:
            self.logger.error(f"Error checking network latency: {e}")

    async def _check_api_responsiveness(self) -> None:
        """Check API responsiveness"""
        try:
            start_time = time.time()
            await asyncio.sleep(0.05)  # Simulate ~50ms response
            latency_ms = (time.time() - start_time) * 1000.0
            self.record_latency(LatencyType.API_RESPONSE, latency_ms, {"endpoint": "health_check"})
        except Exception as e:
            self.logger.error(f"Error checking API responsiveness: {e}")

    async def _update_baselines(self) -> None:
        """Update performance baselines based on recent good performance"""
        try:
            for latency_type, tracker in self.trackers.items():
                stats = tracker.get_stats()
                if stats and stats.count >= 100:  # Need sufficient data
                    values = list(tracker.latency_values)
                    values.sort()
                    baseline_index = int(len(values) * 0.75)  # 75th percentile
                    new_baseline = values[min(baseline_index, len(values) - 1)]

                    current_baseline = self.baselines.get(latency_type, float("inf"))
                    # Only update if the new baseline is not unreasonably worse
                    if new_baseline < current_baseline * 1.5:
                        self.baselines[latency_type] = new_baseline
                        self.logger.info(
                            f"Updated baseline for {latency_type.value}: {new_baseline:.1f}ms"
                        )
        except Exception as e:
            self.logger.error(f"Error updating baselines: {e}")

    async def _handle_alert(self, alert: LatencyAlert) -> None:
        """Handle latency alert"""
        # Execute registered callbacks
        for callback in self.alert_callbacks:
            try:
                await callback(alert)
            except Exception as e:
                self.logger.error(f"Error in alert callback: {e}")

        # Broadcast alert
        await self.redis_bus.publish(
            f"alerts:latency:{self.agent_id}",
            {
                "type": alert.measurement_type.value,
                "current_ms": alert.current_value_ms,
                "threshold_ms": alert.threshold_ms,
                "severity": alert.severity,
                "message": alert.message,
                "timestamp": alert.timestamp,
            },
        )

        # Log alert
        if alert.severity == "critical":
            self.logger.critical(alert.message)
        else:
            self.logger.warning(alert.message)

    # Event handlers

    async def _handle_order_placed(self, data: Dict) -> None:
        """Handle order placed event"""
        try:
            latency_ms = data.get("latency_ms", 0.0)
            if latency_ms and latency_ms > 0:
                self.record_latency(
                    LatencyType.ORDER_PLACEMENT,
                    float(latency_ms),
                    {"order_id": data.get("order_id"), "symbol": data.get("symbol")},
                )
        except Exception as e:
            self.logger.error(f"Error handling order placed event: {e}")

    async def _handle_order_filled(self, data: Dict) -> None:
        """Handle order filled event"""
        try:
            order_id = data.get("order_id")
            latency_ms = data.get("fill_latency_ms")
            if order_id and latency_ms:
                self.record_latency(
                    LatencyType.ORDER_FILL,
                    float(latency_ms),
                    {"order_id": order_id, "symbol": data.get("symbol")},
                )
        except Exception as e:
            self.logger.error(f"Error handling order filled event: {e}")

    async def _handle_market_data_latency(self, data: Dict) -> None:
        """Handle market data latency event"""
        try:
            latency_ms = data.get("latency_ms", 0.0)
            if latency_ms and latency_ms > 0:
                self.record_latency(
                    LatencyType.MARKET_DATA,
                    float(latency_ms),
                    {"source": data.get("source"), "symbol": data.get("symbol")},
                )
        except Exception as e:
            self.logger.error(f"Error handling market data latency: {e}")


class LatencyContext:
    """Context manager for timing operations"""

    def __init__(
        self, monitor: LatencyMonitor, measurement_type: LatencyType, operation_id: str = None
    ):
        self.monitor = monitor
        self.measurement_type = measurement_type
        self.operation_id = operation_id or f"op_{time.time():.6f}"
        self.measurement: Optional[LatencyMeasurement] = None

    def __enter__(self):
        self.monitor.start_timing(self.measurement_type, self.operation_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.measurement = self.monitor.end_timing(self.measurement_type, self.operation_id)
        return False

    async def __aenter__(self):
        self.monitor.start_timing(self.measurement_type, self.operation_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.measurement = self.monitor.end_timing(self.measurement_type, self.operation_id)
        return False


class LatencyOptimizer:
    """Optimize operations based on latency patterns"""

    def __init__(self, latency_monitor: LatencyMonitor):
        self.latency_monitor = latency_monitor
        self.optimization_suggestions: List[Dict] = []
        self.logger = logging.getLogger(f"{__name__}.LatencyOptimizer")

    async def analyze_patterns(self) -> List[Dict[str, Any]]:
        """Analyze latency patterns and suggest optimizations"""
        suggestions: List[Dict[str, Any]] = []

        try:
            all_stats = await self.latency_monitor.get_all_stats()

            for latency_type, stats in all_stats.items():
                if not stats or stats.count < 50:
                    continue

                # Check for high variance (inconsistent performance)
                cv = (stats.std_dev_ms / stats.mean_ms) if stats.mean_ms > 0 else 0.0
                if cv > 0.5:  # High coefficient of variation
                    suggestions.append(
                        {
                            "type": "high_variance",
                            "component": latency_type.value,
                            "issue": f"Inconsistent {latency_type.value} performance",
                            "metric": f"CV: {cv:.2f}",
                            "suggestion": "Investigate network stability or system load",
                        }
                    )

                # Check for high tail latencies
                if stats.p99_ms > stats.mean_ms * 3:
                    suggestions.append(
                        {
                            "type": "high_tail",
                            "component": latency_type.value,
                            "issue": f"High tail latency in {latency_type.value}",
                            "metric": f"P99: {stats.p99_ms:.1f}ms vs Mean: {stats.mean_ms:.1f}ms",
                            "suggestion": "Consider timeout optimization or retry logic",
                        }
                    )

                # Check against known good baselines
                baseline = self.latency_monitor.baselines.get(latency_type)
                if baseline and stats.p95_ms > baseline * 1.3:
                    suggestions.append(
                        {
                            "type": "baseline_degradation",
                            "component": latency_type.value,
                            "issue": "Performance degraded vs baseline",
                            "metric": f"Current: {stats.p95_ms:.1f}ms vs Baseline: {baseline:.1f}ms",
                            "suggestion": "Review recent changes or system health",
                        }
                    )

            self.optimization_suggestions = suggestions
            return suggestions

        except Exception as e:
            self.logger.error(f"Error analyzing latency patterns: {e}")
            return []

    async def get_performance_recommendations(self) -> Dict[str, List[str]]:
        """Get specific performance recommendations"""
        try:
            recommendations: Dict[str, List[str]] = {
                "immediate": [],
                "short_term": [],
                "long_term": [],
            }

            suggestions = await self.analyze_patterns()

            for suggestion in suggestions:
                if suggestion["type"] == "high_variance":
                    recommendations["immediate"].append(
                        f"Check network stability for {suggestion['component']}"
                    )
                elif suggestion["type"] == "high_tail":
                    recommendations["short_term"].append(
                        f"Optimize timeout handling for {suggestion['component']}"
                    )
                elif suggestion["type"] == "baseline_degradation":
                    recommendations["immediate"].append(
                        f"Investigate performance regression in {suggestion['component']}"
                    )

            return recommendations

        except Exception as e:
            self.logger.error(f"Error generating recommendations: {e}")
            return {"immediate": [], "short_term": [], "long_term": []}
