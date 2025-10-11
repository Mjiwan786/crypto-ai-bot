"""
SLO Tracker - Online SLO Status Computation

This module computes SLO status online over a rolling window and stores results
for dashboards and alerts. It processes metrics from Redis streams and computes
key performance indicators to determine if the system meets its SLO targets.

Usage:
    python -m monitoring.slo_tracker --env .env.staging --interval 60
    python -m monitoring.slo_tracker --help

HTTP Endpoint:
    GET /slo - Returns current SLO status as JSON
"""

import asyncio
import json
import logging
import os
import signal
import ssl
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum
import argparse
import http.server
import socketserver
import threading
from pathlib import Path
import hashlib

import redis
from monitoring.slo_definitions import (
    P95_PUBLISH_LATENCY_MS, 
    MAX_STREAM_LAG_SEC, 
    UPTIME_TARGET, 
    MAX_DUP_RATE,
    window_hours,
    is_staging,
    get_effective_thresholds
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SLOStatus(Enum):
    """SLO status levels"""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class SLOThresholds:
    """SLO threshold configuration"""
    p95_latency_ms: float
    max_stream_lag_sec: float
    uptime_target: float
    max_dup_rate: float
    window_hours: int


@dataclass
class SLOMetrics:
    """Current SLO metrics"""
    p95_latency_ms: float
    stream_lag_p50_sec: float
    stream_lag_p95_sec: float
    uptime_ratio: float
    dup_rate: float
    window_hours: int
    timestamp: float


@dataclass
class SLOStatusResult:
    """SLO status computation result"""
    status: SLOStatus
    metrics: SLOMetrics
    breaches: List[str]
    warnings: List[str]


class SLOTracker:
    """
    Online SLO status tracker that computes metrics over rolling windows.
    """
    
    def __init__(self, redis_client, thresholds: Optional[SLOThresholds] = None):
        """
        Initialize SLO tracker.
        
        Args:
            redis_client: Redis client instance
            thresholds: SLO thresholds (uses defaults if None)
        """
        self.redis = redis_client
        self.logger = logger
        
        # Load thresholds
        if thresholds is None:
            effective_thresholds = get_effective_thresholds()
            self.thresholds = SLOThresholds(
                p95_latency_ms=effective_thresholds['p95_publish_latency_ms'],
                max_stream_lag_sec=effective_thresholds['max_stream_lag_sec'],
                uptime_target=effective_thresholds['uptime_target'],
                max_dup_rate=effective_thresholds['max_dup_rate'],
                window_hours=window_hours()
            )
        else:
            self.thresholds = thresholds
        
        # Metrics storage
        self.latency_samples: List[Tuple[float, float]] = []  # (timestamp, latency_ms)
        self.lag_samples: List[Tuple[float, float]] = []  # (timestamp, lag_sec)
        self.uptime_samples: List[Tuple[float, bool]] = []  # (timestamp, is_up)
        
        # Running state
        self.running = False
        self.task: Optional[asyncio.Task] = None
        
        self.logger.info(f"SLO Tracker initialized with thresholds: {self.thresholds}")
    
    async def start(self, interval_seconds: int = 60):
        """
        Start the SLO tracker.
        
        Args:
            interval_seconds: Computation interval in seconds
        """
        if self.running:
            return
            
        self.running = True
        self.task = asyncio.create_task(self._tracking_loop(interval_seconds))
        self.logger.info(f"SLO Tracker started with {interval_seconds}s interval")
    
    async def stop(self):
        """Stop the SLO tracker."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.logger.info("SLO Tracker stopped")
    
    async def _tracking_loop(self, interval_seconds: int):
        """Main tracking loop."""
        while self.running:
            try:
                await self._compute_and_store_slo_status()
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in SLO tracking loop: {e}")
                await asyncio.sleep(5)  # Back off on error
    
    async def _compute_and_store_slo_status(self):
        """Compute current SLO status and store in Redis."""
        try:
            # Collect metrics from Redis streams
            await self._collect_metrics()
            
            # Compute SLO metrics
            metrics = await self._compute_slo_metrics()
            
            # Determine status
            status_result = self._compute_slo_status(metrics)
            
            # Store in Redis
            await self._store_slo_status(status_result)
            
            self.logger.info(f"SLO Status: {status_result.status.value} - "
                           f"P95 Latency: {metrics.p95_latency_ms:.1f}ms, "
                           f"Stream Lag P95: {metrics.stream_lag_p95_sec:.1f}s, "
                           f"Uptime: {metrics.uptime_ratio:.3f}, "
                           f"Dup Rate: {metrics.dup_rate:.4f}")
            
        except Exception as e:
            self.logger.error(f"Failed to compute SLO status: {e}")
    
    async def _collect_metrics(self):
        """Collect metrics from Redis streams."""
        current_time = time.time()
        window_start = current_time - (self.thresholds.window_hours * 3600)
        
        # Collect latency metrics from metrics:signals:e2e
        await self._collect_latency_metrics(window_start)
        
        # Collect stream lag metrics from metrics:md:lag
        await self._collect_lag_metrics(window_start)
        
        # Collect uptime metrics from bot:up
        await self._collect_uptime_metrics(window_start)
        
        # Clean old samples
        self._cleanup_old_samples(window_start)
    
    async def _collect_latency_metrics(self, window_start: float):
        """Collect latency metrics from Redis stream."""
        try:
            # Read recent latency events
            if hasattr(self.redis, 'xrevrange') and asyncio.iscoroutinefunction(self.redis.xrevrange):
                events = await self.redis.xrevrange("metrics:signals:e2e", count=1000)
            else:
                events = self.redis.xrevrange("metrics:signals:e2e", count=1000)
            
            for event_id, fields in events:
                try:
                    event_ts = int(fields.get(b"ts", b"0").decode()) / 1000.0
                    if event_ts < window_start:
                        break
                    
                    latency_ms = float(fields.get(b"ms", b"0").decode())
                    self.latency_samples.append((event_ts, latency_ms))
                    
                except (ValueError, KeyError) as e:
                    self.logger.warning(f"Invalid latency event: {e}")
                    continue
                    
        except Exception as e:
            self.logger.error(f"Failed to collect latency metrics: {e}")
    
    async def _collect_lag_metrics(self, window_start: float):
        """Collect stream lag metrics from Redis stream."""
        try:
            # Read recent lag events
            if hasattr(self.redis, 'xrevrange') and asyncio.iscoroutinefunction(self.redis.xrevrange):
                events = await self.redis.xrevrange("metrics:md:lag", count=1000)
            else:
                events = self.redis.xrevrange("metrics:md:lag", count=1000)
            
            for event_id, fields in events:
                try:
                    event_ts = int(fields.get(b"ts", b"0").decode()) / 1000.0
                    if event_ts < window_start:
                        break
                    
                    lag_ms = float(fields.get(b"lag", b"0").decode())
                    lag_sec = lag_ms / 1000.0
                    self.lag_samples.append((event_ts, lag_sec))
                    
                except (ValueError, KeyError) as e:
                    self.logger.warning(f"Invalid lag event: {e}")
                    continue
                    
        except Exception as e:
            self.logger.error(f"Failed to collect lag metrics: {e}")
    
    async def _collect_uptime_metrics(self, window_start: float):
        """Collect uptime metrics from bot:up key."""
        try:
            # Check if bot is currently up
            if hasattr(self.redis, 'get') and asyncio.iscoroutinefunction(self.redis.get):
                uptime_data = await self.redis.get("bot:up")
            else:
                uptime_data = self.redis.get("bot:up")
            
            current_time = time.time()
            is_up = uptime_data is not None
            
            # Add current sample
            self.uptime_samples.append((current_time, is_up))
            
            # Also check TTL to estimate uptime more accurately
            if is_up and hasattr(self.redis, 'ttl') and asyncio.iscoroutinefunction(self.redis.ttl):
                ttl_seconds = await self.redis.ttl("bot:up")
            elif is_up and hasattr(self.redis, 'ttl'):
                ttl_seconds = self.redis.ttl("bot:up")
            else:
                ttl_seconds = 0
            
            # If TTL is positive, bot was up for that duration
            if ttl_seconds > 0:
                # Estimate uptime based on TTL (assuming 5-minute heartbeat)
                estimated_uptime_duration = min(ttl_seconds, 300)  # Max 5 minutes
                for i in range(int(estimated_uptime_duration / 60)):  # Every minute
                    sample_time = current_time - (i * 60)
                    if sample_time >= window_start:
                        self.uptime_samples.append((sample_time, True))
            
        except Exception as e:
            self.logger.error(f"Failed to collect uptime metrics: {e}")
    
    def _cleanup_old_samples(self, window_start: float):
        """Clean up old samples outside the window."""
        self.latency_samples = [(ts, val) for ts, val in self.latency_samples if ts >= window_start]
        self.lag_samples = [(ts, val) for ts, val in self.lag_samples if ts >= window_start]
        self.uptime_samples = [(ts, val) for ts, val in self.uptime_samples if ts >= window_start]
    
    async def _compute_slo_metrics(self) -> SLOMetrics:
        """Compute SLO metrics from collected samples."""
        current_time = time.time()
        
        # Compute P95 latency from last 60 minutes
        recent_latencies = [
            val for ts, val in self.latency_samples 
            if ts >= current_time - 3600  # Last 60 minutes
        ]
        
        if recent_latencies:
            recent_latencies.sort()
            p95_latency_ms = recent_latencies[int(len(recent_latencies) * 0.95)]
        else:
            p95_latency_ms = 0.0
        
        # Compute stream lag P50 and P95
        if self.lag_samples:
            lag_values = [val for _, val in self.lag_samples]
            lag_values.sort()
            stream_lag_p50_sec = lag_values[int(len(lag_values) * 0.50)]
            stream_lag_p95_sec = lag_values[int(len(lag_values) * 0.95)]
        else:
            stream_lag_p50_sec = 0.0
            stream_lag_p95_sec = 0.0
        
        # Compute uptime ratio
        uptime_ratio = await self._compute_uptime_ratio()
        
        # Compute duplicate rate
        dup_rate = await self._compute_duplicate_rate()
        
        return SLOMetrics(
            p95_latency_ms=p95_latency_ms,
            stream_lag_p50_sec=stream_lag_p50_sec,
            stream_lag_p95_sec=stream_lag_p95_sec,
            uptime_ratio=uptime_ratio,
            dup_rate=dup_rate,
            window_hours=self.thresholds.window_hours,
            timestamp=current_time
        )
    
    async def _compute_uptime_ratio(self) -> float:
        """Compute uptime ratio over the window."""
        if not self.uptime_samples:
            return 0.0
        
        # Simple uptime calculation based on bot:up key existence
        # In production, you'd want more sophisticated tracking
        current_time = time.time()
        window_start = current_time - (self.thresholds.window_hours * 3600)
        
        # Count samples where bot was up
        up_samples = sum(1 for _, is_up in self.uptime_samples if is_up)
        total_samples = len(self.uptime_samples)
        
        if total_samples == 0:
            return 0.0
        
        return up_samples / total_samples
    
    async def _compute_duplicate_rate(self) -> float:
        """Compute duplicate rate using Redis HLL."""
        try:
            current_time = time.time()
            window_start = current_time - (self.thresholds.window_hours * 3600)
            
            # Get total signals count from Redis counter
            if hasattr(self.redis, 'get') and asyncio.iscoroutinefunction(self.redis.get):
                total_signals = await self.redis.get("slo:total_signals")
            else:
                total_signals = self.redis.get("slo:total_signals")
            
            if total_signals is None:
                total_signals = 0
            else:
                total_signals = int(total_signals.decode() if isinstance(total_signals, bytes) else total_signals)
            
            if total_signals == 0:
                return 0.0
            
            # Get unique signals count from Redis HLL
            if hasattr(self.redis, 'pfcount') and asyncio.iscoroutinefunction(self.redis.pfcount):
                unique_signals = await self.redis.pfcount("slo:unique_signals")
            else:
                unique_signals = self.redis.pfcount("slo:unique_signals")
            
            if unique_signals is None:
                unique_signals = 0
            else:
                unique_signals = int(unique_signals)
            
            # Calculate duplicate rate
            if total_signals == 0:
                return 0.0
            
            dup_rate = 1.0 - (unique_signals / total_signals)
            return max(0.0, dup_rate)
            
        except Exception as e:
            self.logger.error(f"Failed to compute duplicate rate: {e}")
            return 0.0
    
    def _compute_slo_status(self, metrics: SLOMetrics) -> SLOStatusResult:
        """Compute SLO status based on metrics and thresholds."""
        breaches = []
        warnings = []
        
        # Check P95 latency
        if metrics.p95_latency_ms > self.thresholds.p95_latency_ms:
            breaches.append(f"P95 latency {metrics.p95_latency_ms:.1f}ms > {self.thresholds.p95_latency_ms}ms")
        elif metrics.p95_latency_ms > self.thresholds.p95_latency_ms * 0.9:
            warnings.append(f"P95 latency {metrics.p95_latency_ms:.1f}ms approaching threshold")
        
        # Check stream lag
        if metrics.stream_lag_p95_sec > self.thresholds.max_stream_lag_sec:
            breaches.append(f"Stream lag P95 {metrics.stream_lag_p95_sec:.1f}s > {self.thresholds.max_stream_lag_sec}s")
        elif metrics.stream_lag_p95_sec > self.thresholds.max_stream_lag_sec * 0.9:
            warnings.append(f"Stream lag P95 {metrics.stream_lag_p95_sec:.1f}s approaching threshold")
        
        # Check uptime
        if metrics.uptime_ratio < self.thresholds.uptime_target:
            breaches.append(f"Uptime {metrics.uptime_ratio:.3f} < {self.thresholds.uptime_target}")
        elif metrics.uptime_ratio < self.thresholds.uptime_target * 1.1:
            warnings.append(f"Uptime {metrics.uptime_ratio:.3f} approaching threshold")
        
        # Check duplicate rate
        if metrics.dup_rate > self.thresholds.max_dup_rate:
            breaches.append(f"Duplicate rate {metrics.dup_rate:.4f} > {self.thresholds.max_dup_rate}")
        elif metrics.dup_rate > self.thresholds.max_dup_rate * 0.9:
            warnings.append(f"Duplicate rate {metrics.dup_rate:.4f} approaching threshold")
        
        # Determine status
        if len(breaches) == 0 and len(warnings) <= 1:
            status = SLOStatus.PASS
        elif len(breaches) == 0 and len(warnings) == 1:
            status = SLOStatus.WARN
        else:
            status = SLOStatus.FAIL
        
        return SLOStatusResult(
            status=status,
            metrics=metrics,
            breaches=breaches,
            warnings=warnings
        )
    
    async def _store_slo_status(self, status_result: SLOStatusResult):
        """Store SLO status in Redis HASH."""
        try:
            status_data = {
                "p95_latency_ms": str(status_result.metrics.p95_latency_ms),
                "stream_lag_p95_sec": str(status_result.metrics.stream_lag_p95_sec),
                "uptime_ratio": str(status_result.metrics.uptime_ratio),
                "dup_rate": str(status_result.metrics.dup_rate),
                "window_hours": str(status_result.metrics.window_hours),
                "status": status_result.status.value,
                "timestamp": str(int(status_result.metrics.timestamp)),
                "breaches": json.dumps(status_result.breaches),
                "warnings": json.dumps(status_result.warnings)
            }
            
            if hasattr(self.redis, 'hset') and asyncio.iscoroutinefunction(self.redis.hset):
                await self.redis.hset("slo:status", mapping=status_data)
            else:
                self.redis.hset("slo:status", mapping=status_data)
                
        except Exception as e:
            self.logger.error(f"Failed to store SLO status: {e}")
    
    async def record_signal(self, signal_payload: Dict[str, Any]) -> None:
        """
        Record a signal for duplicate detection using Redis HLL.
        
        Args:
            signal_payload: Signal payload to hash for duplicate detection
        """
        try:
            # Create stable hash of signal payload
            signal_str = json.dumps(signal_payload, sort_keys=True)
            signal_hash = hashlib.md5(signal_str.encode()).hexdigest()
            
            # Add to Redis HLL for unique counting
            if hasattr(self.redis, 'pfadd') and asyncio.iscoroutinefunction(self.redis.pfadd):
                await self.redis.pfadd("slo:unique_signals", signal_hash)
            else:
                self.redis.pfadd("slo:unique_signals", signal_hash)
            
            # Increment total signals counter
            if hasattr(self.redis, 'incr') and asyncio.iscoroutinefunction(self.redis.incr):
                await self.redis.incr("slo:total_signals")
            else:
                self.redis.incr("slo:total_signals")
            
        except Exception as e:
            self.logger.error(f"Failed to record signal: {e}")
    
    async def get_current_status(self) -> Optional[Dict[str, Any]]:
        """Get current SLO status from Redis."""
        try:
            if hasattr(self.redis, 'hgetall') and asyncio.iscoroutinefunction(self.redis.hgetall):
                status_data = await self.redis.hgetall("slo:status")
            else:
                status_data = self.redis.hgetall("slo:status")
            
            if not status_data:
                return None
            
            # Convert bytes to strings if needed
            result = {}
            for key, value in status_data.items():
                if isinstance(key, bytes):
                    key = key.decode()
                if isinstance(value, bytes):
                    value = value.decode()
                result[key] = value
            
            # Parse JSON fields
            if 'breaches' in result:
                result['breaches'] = json.loads(result['breaches'])
            if 'warnings' in result:
                result['warnings'] = json.loads(result['warnings'])
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to get current status: {e}")
            return None


class SLOHTTPHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for SLO status endpoint."""
    
    def __init__(self, slo_tracker: SLOTracker, *args, **kwargs):
        self.slo_tracker = slo_tracker
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/slo':
            self._handle_slo_endpoint()
        elif self.path == '/health':
            self._handle_health_endpoint()
        else:
            self._handle_404()
    
    def _handle_slo_endpoint(self):
        """Handle /slo endpoint."""
        try:
            # Get current status (this is a simplified sync version)
            # In production, you'd want to make this async
            status_data = asyncio.run(self.slo_tracker.get_current_status())
            
            if status_data is None:
                self.send_response(503)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "SLO status not available"
                }).encode())
                return
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(status_data, indent=2).encode())
            
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": f"Internal server error: {str(e)}"
            }).encode())
    
    def _handle_health_endpoint(self):
        """Handle /health endpoint."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "healthy",
            "timestamp": time.time()
        }).encode())
    
    def _handle_404(self):
        """Handle 404 errors."""
        self.send_response(404)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            "error": "Not found"
        }).encode())
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def create_http_handler(slo_tracker: SLOTracker):
    """Create HTTP handler with SLO tracker."""
    def handler(*args, **kwargs):
        return SLOHTTPHandler(slo_tracker, *args, **kwargs)
    return handler


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="SLO Tracker")
    parser.add_argument("--env", help="Environment file path")
    parser.add_argument("--interval", type=int, default=60, help="Computation interval in seconds")
    parser.add_argument("--http-port", type=int, default=9109, help="HTTP server port")
    parser.add_argument("--redis-url", help="Redis URL")
    parser.add_argument("--no-http", action="store_true", help="Disable HTTP server")
    
    args = parser.parse_args()
    
    # Load environment variables
    if args.env:
        from dotenv import load_dotenv
        load_dotenv(args.env)
    
    # Get Redis URL
    redis_url = args.redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Connect to Redis with proper TLS support for Redis Cloud
    try:
        if "redis-cloud.com" in redis_url:
            # Parse Redis Cloud URL for proper connection
            from urllib.parse import urlparse
            parsed = urlparse(redis_url)
            
            redis_kwargs = {
                "host": parsed.hostname,
                "port": parsed.port or 6379,
                "username": parsed.username or "default",
                "password": parsed.password,
                "ssl": True,
                "ssl_cert_reqs": ssl.CERT_REQUIRED,
                "decode_responses": False,
                "socket_timeout": 30,
                "socket_connect_timeout": 30,
                "retry_on_timeout": True,
            }
            
            # Add CA cert if provided
            ca_cert = os.getenv("REDIS_CA_CERT")
            if ca_cert and os.path.exists(ca_cert):
                redis_kwargs["ssl_ca_certs"] = ca_cert
            
            redis_client = redis.Redis(**redis_kwargs)
        else:
            # Standard Redis connection - convert to rediss if SSL needed
            if redis_url.startswith("redis://") and "redis-cloud.com" in redis_url:
                redis_url = redis_url.replace("redis://", "rediss://", 1)
            redis_client = redis.from_url(redis_url, ssl_cert_reqs=ssl.CERT_REQUIRED)
        
        redis_client.ping()  # Test connection
        safe_url = redis_url.split("@")[-1] if "@" in redis_url else redis_url
        logger.info(f"Connected to Redis: {safe_url}")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        sys.exit(1)
    
    # Create SLO tracker
    slo_tracker = SLOTracker(redis_client)
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(slo_tracker.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start SLO tracker
        await slo_tracker.start(args.interval)
        
        # Start HTTP server if not disabled
        if not args.no_http:
            http_port = int(os.getenv("SLO_HTTP_PORT", args.http_port))
            handler = create_http_handler(slo_tracker)
            
            with socketserver.TCPServer(("", http_port), handler) as httpd:
                logger.info(f"HTTP server started on port {http_port}")
                logger.info(f"SLO endpoint: http://localhost:{http_port}/slo")
                
                # Start HTTP server in separate thread
                http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                http_thread.start()
        
        # Keep running
        logger.info("SLO Tracker running...")
        while slo_tracker.running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        await slo_tracker.stop()
        logger.info("SLO Tracker stopped")


if __name__ == "__main__":
    asyncio.run(main())

